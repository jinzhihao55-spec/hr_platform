"""日报 Sheet1 Row2–Row40（§3）。确定性、链式。

数据源 = 数据库主表 + 上一报告日 daily_reports 基线。
口径以 docs/skills/daily_rows.md / 模板说明为准。

Row2/Row3 使用 hire_first_visible_date / resign_first_visible_date 处理
「晚到补入今天」（见 input_repo.upsert_employees、Q9）。"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

from sqlalchemy.orm import Session

from app.core import constants as C
from app.core.exceptions import BaselineMissingError
from app.core.logging import get_logger
from app.repositories import report_repo
from app.utils.dates import same_month, to_int

log = get_logger("calc.daily")

ITEMS = {
    2: "今日入职", 3: "今日离职", 4: "今日提出离职数（主动）",
    5: "今日提出release数（被动）", 6: "合计提出离职数（主动+被动）",
    7: "今日净增", 8: "MTD入职", 9: "MTD离职", 10: "MTD转正",
    11: "MTD微软项目调整至非微软项目", 12: "MTD净增减人数",
    13: "YTD入职", 14: "YTD离职", 15: "YTD转正",
    16: "YTD微软项目调整至非微软项目", 17: "YTD净增减人数",
    18: "本月预估入职人数-招聘提供", 19: "本月预估离职人数",
    20: "MTD转正", 21: "MTD微软项目调整至非微软项目", 22: "本月预估净增减人数",
    25: "境外YTD在职数据", 26: "境外主体_A",
    29: "事项", 30: "Release数-截至月底", 31: "本月提出离职数",
    32: "上月提出本月离职数", 33: "本月预估离职人数",
    36: "事项", 37: "当月已经入职总数", 38: "上月接受offer后当月预计入职",
    39: "当月接受offer当月预计入职", 40: "合计",
}


def compute_daily(
    db: Session | None,
    report_date: date,
    baseline_date: date | None = None,
    baseline_override: dict[int, int] | None = None,
    *,
    input_frames: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """baseline_date：链式基线日；缺省用早于报告日的最近一份日报（通常昨日）。"""
    if input_frames is None:
        if db is None:
            raise ValueError("db is required when input_frames are not provided")
        emp = report_repo.load_employees(db)
        res = report_repo.load_resignations(db)
        agr = report_repo.load_agreements(db)
        rec = report_repo.load_recruitment(db, report_date)
    else:
        emp = input_frames["employees"].copy(deep=True)
        res = input_frames["resignations"].copy(deep=True)
        agr = input_frames["releases"].copy(deep=True)
        rec = input_frames["recruitment"].copy(deep=True)

    if baseline_override is not None:
        if baseline_date is None:
            raise BaselineMissingError("月初基线缺少 baseline_date，无法确定跨月/跨年重置规则")
        baseline = {int(row): int(value) for row, value in baseline_override.items()}
    else:
        if db is None:
            raise BaselineMissingError(
                "FactBundle 日报计算必须显式提供 baseline_rows"
            )
        baseline = report_repo.get_baseline_rows(db, report_date, baseline_date)
    if baseline_date is None:
        baseline_date = report_repo.baseline_date(db, report_date)
    elif baseline_override is None and not baseline:
        # 用户显式指定的基线日不存在日报 → 停下提问，不静默回退
        raise BaselineMissingError(
            f"指定的基线日 {baseline_date} 没有已生成/已验收的日报，"
            "无法按该基线链式顺推。请先生成该日日报，或改用默认基线。",
            detail={"baseline_date": baseline_date.isoformat()},
        )

    # MTD/YTD 语义修正：基线日报只是链式起点，不是任意可加的累计值。
    #   MTD = month-to-date —— 基线日与报告日不同月 → MTD(Row8/9) 与
    #         Row30（Release 截至月底，同为月内累计）从 0 重新起算；
    #   YTD = year-to-date  —— 基线日与报告日不同年 → YTD(Row13/14) 也从 0 重新起算。
    # 否则跨月/跨年生成时会把上月 MTD、去年 YTD 错误地带入本期。
    baseline_resets: list[str] = []
    if baseline and isinstance(baseline_date, date):
        if (baseline_date.year, baseline_date.month) != (report_date.year, report_date.month):
            baseline[8] = 0
            baseline[9] = 0
            baseline[30] = 0
            baseline_resets.append("跨月：MTD(Row8/9)与Row30 从0起算")
        if baseline_date.year != report_date.year:
            baseline[13] = 0
            baseline[14] = 0
            baseline_resets.append("跨年：YTD(Row13/14) 从0起算")
        if baseline_resets:
            log.info("基线 %s → 报告日 %s：%s", baseline_date, report_date,
                     "；".join(baseline_resets))

    rows: dict[int, dict] = {}
    trace: list[dict] = []

    def emit(n, value, *, is_blank=False, **trace_fields):
        rows[n] = {"item": ITEMS.get(n, ""), "value": value, "is_blank": is_blank}
        trace.append({"scope": "daily", "ref": f"Row{n}", "item": ITEMS.get(n, ""),
                      "value": value, **trace_fields})

    # ----- §3.1 当日实际入离职 -----
    r2 = _count_today_fact(emp, "hire_date", "hire_first_visible", report_date)
    emit(2, r2["count"], source="人员表", hits=r2["hits"],
         formula="COUNT(入职归属日=报告日 且 纳入口径)")
    r3 = _count_today_resigns(emp, res, report_date)
    emit(3, r3["count"], source="人员表+离职报表", hits=r3["hits"],
         formula="COUNT(离职归属日=报告日 且 纳入口径 且 流程非审批中)")

    # ----- §3.2 当日提出离职 -----
    r4 = _count_active_resign(emp, res, report_date)
    emit(4, r4["count"], source="离职人员报表", hits=r4["hits"],
         formula="COUNT(自然人当前主记录首次可见=今日 且 主动 且 流程未拒)")
    r5 = _count_release(agr, report_date)
    emit(5, r5["count"], source="OA协议签署", hits=r5["hits"],
         formula="COUNT(今日首次可见 且 计入Row5=是)")
    emit(6, rows[4]["value"] + rows[5]["value"], formula="Row6=Row4+Row5",
         left=rows[4]["value"], right=rows[5]["value"])
    emit(7, rows[2]["value"] - rows[3]["value"], formula="Row7=Row2-Row3",
         left=rows[2]["value"], right=rows[3]["value"])

    # ----- §3.3 MTD（链式）-----
    _require_baseline(baseline, [8, 9, 13, 14, 30], report_date)
    emit(8, baseline.get(8, 0) + rows[2]["value"], formula="Row8=昨日Row8+今日Row2",
         baseline=baseline.get(8, 0), increment=rows[2]["value"])
    emit(9, baseline.get(9, 0) + rows[3]["value"], formula="Row9=昨日Row9+今日Row3",
         baseline=baseline.get(9, 0), increment=rows[3]["value"])
    emit(10, 0, formula="默认0 (Q1 转正暂不涉及)")
    emit(11, 0, formula="默认0 (Q2 微软项目调整暂不涉及)")
    emit(12, rows[8]["value"] - rows[9]["value"] - rows[10]["value"] + rows[11]["value"],
         formula="Row12=Row8-Row9-Row10+Row11")

    # ----- §3.4 YTD（链式）-----
    emit(13, baseline.get(13, 0) + rows[2]["value"], formula="Row13=昨日Row13+今日Row2",
         baseline=baseline.get(13, 0), increment=rows[2]["value"])
    emit(14, baseline.get(14, 0) + rows[3]["value"], formula="Row14=昨日Row14+今日Row3",
         baseline=baseline.get(14, 0), increment=rows[3]["value"])
    emit(15, 0, formula="默认0 (同Row10)")
    emit(16, 0, formula="默认0 (同Row11)")
    emit(17, rows[13]["value"] - rows[14]["value"] - rows[15]["value"] + rows[16]["value"],
         formula="Row17=Row13-Row14-Row15+Row16")

    # ----- §3.7 预估离职链路 -----
    r30 = _release_to_month_end(agr, report_date, baseline.get(30, 0))
    emit(30, r30["value"], formula="Row30=昨日Row30+今日首次可见且计入Row30=是",
         baseline=baseline.get(30, 0), increment=r30["increment"], hits=r30["hits"])
    r31 = _proposed_this_month(emp, res, report_date)
    emit(31, r31["count"], formula="本月申请+LWD在本月+流程未拒(含协商一致)",
         hits=r31["hits"], roster=r31["roster"])
    r32 = _proposed_last_month_leave_this_month(emp, res, report_date)
    emit(32, r32["count"], formula="上月申请+LWD在本月+流程未拒", hits=r32["hits"])
    emit(33, rows[30]["value"] + rows[31]["value"] + rows[32]["value"],
         formula="Row33=Row30+Row31+Row32",
         row30=rows[30]["value"], row31=rows[31]["value"], row32=rows[32]["value"])

    # ----- §3.8 招聘预估入职链路 -----
    r38 = _recruitment_value(rec, "prev_month_offer_curr_join")
    r39 = _recruitment_value(rec, "curr_month_offer_curr_join")
    emit(37, rows[8]["value"], formula="Row37=Row8(MTD入职)",
         note="不可用招聘已入职合计覆盖")
    emit(38, r38["value"], formula="招聘表上月offer当月入职",
         total_row=r38["total"], rowsum=r38["rowsum"], conflict=r38["conflict"])
    emit(39, r39["value"], formula="招聘表当月offer当月入职",
         total_row=r39["total"], rowsum=r39["rowsum"], conflict=r39["conflict"])
    emit(40, rows[37]["value"] + rows[38]["value"] + rows[39]["value"],
         formula="Row40=Row37+Row38+Row39")

    # ----- §3.5 本月预估区 -----
    emit(18, rows[40]["value"], formula="Row18=Row40")
    emit(19, rows[33]["value"], formula="Row19=Row33")
    emit(20, 0, formula="同Row10")
    emit(21, 0, formula="同Row11")
    emit(22, rows[18]["value"] - rows[19]["value"] - rows[20]["value"] + rows[21]["value"],
         formula="Row22=Row18-Row19-Row20+Row21")

    # ----- §3.6 境外区 -----
    emit(25, 0, formula="境外YTD在职数据，当前通常为0 (Q13暂不涉及)")
    emit(26, 0, formula="境外主体_A，当前通常为0 (Q13暂不涉及)")

    for n in C.DAILY_HEADER_ROWS:
        rows[n] = {"item": ITEMS.get(n, "事项"), "value": None, "is_blank": False,
                   "is_header": True}
    for n in C.DAILY_BLANK_ROWS:
        rows[n] = {"item": None, "value": None, "is_blank": True}

    if baseline_resets:
        trace.append({"scope": "daily", "ref": "baseline", "item": "链式基线",
                      "value": None,
                      "note": f"基线日 {baseline_date}；" + "；".join(baseline_resets)})

    return {
        "report_date": report_date, "baseline_date": baseline_date,
        "rows": rows, "trace": trace,
        "rosters": {"row31": r31["roster"]},
        "baseline_resets": baseline_resets,
    }


def compute_daily_from_frames(
    *,
    report_date: date,
    baseline_date: date,
    baseline_rows: Mapping[int, int],
    employees: pd.DataFrame,
    resignations: pd.DataFrame,
    releases: pd.DataFrame,
    recruitment: pd.DataFrame,
) -> dict[str, Any]:
    return compute_daily(
        None,
        report_date,
        baseline_date,
        baseline_override={int(row): int(value) for row, value in baseline_rows.items()},
        input_frames={
            "employees": employees,
            "resignations": resignations,
            "releases": releases,
            "recruitment": recruitment,
        },
    )


def recompute_chain_baseline(db: Session, for_date: date) -> dict[str, int]:
    """按库内数据全量重算链式基线（row8/9/13/14/30，均截至 for_date）。

    口径与 Row2/Row3/在岗时长完全一致，保证注入后硬校验（B10=Row14）自洽：
    - 入职/离职归属日 = 事实日期与首次可见日期的较晚者（晚到补入，同
      _count_today_fact）；首次可见晚于 for_date 的记录不计（当时还看不见）；
    - 离职须流程已生效（_departure_fact_confirmed，审批中/被拒不计）；
    - 只统计纳入口径员工类型；
    - Row30 = 计入Row30=是 且 LWD 不缺 且首次可见<=for_date 的 OA 单数（去重）。

    用途：baseline_missing 澄清时用户提供不了人工基线（答复"自动重算"或全 0）
    时，由系统自动推得基线，避免注入全 0 后 Row14 与在岗时长 B10 永远对不上。
    """
    emp = report_repo.load_employees(db)
    res = report_repo.load_resignations(db)
    agr = report_repo.load_agreements(db)
    res_by_emp = _resignations_by_emp(res)

    month_start = for_date.replace(day=1)
    year_start = for_date.replace(month=1, day=1)

    def _effective(d, fv):
        if not isinstance(d, date):
            return None
        return fv if isinstance(fv, date) and fv > d else d

    row8 = row9 = row13 = row14 = 0
    if not emp.empty:
        for _, r in emp.iterrows():
            if not _in_inclusion(r.get("employee_type")):
                continue
            hd = _effective(r.get("hire_date"), r.get("hire_first_visible"))
            if hd and year_start <= hd <= for_date:
                row13 += 1
                if hd >= month_start:
                    row8 += 1
            ld_raw = r.get("leave_date")
            ld = _effective(ld_raw, r.get("leave_first_visible"))
            if ld and year_start <= ld <= for_date:
                ok, _note = _departure_fact_confirmed(r, res_by_emp, ld_raw)
                if ok:
                    row14 += 1
                    if ld >= month_start:
                        row9 += 1

    row30 = 0
    if not agr.empty:
        seen = set()
        for _, r in agr.iterrows():
            fsb = r.get("first_seen_batch")
            if not isinstance(fsb, date) or fsb > for_date:
                continue
            if bool(r.get("lwd_pending")) or not bool(r.get("in_month_release")):
                continue
            ono = r.get("order_no")
            if ono in seen:
                continue
            seen.add(ono)
            row30 += 1

    result = {"row8": row8, "row9": row9, "row13": row13,
              "row14": row14, "row30": row30}
    log.info("基线全量重算完成 for_date=%s", for_date)
    return result


def _require_baseline(baseline, needed, report_date):
    if not baseline:
        if report_date.day != 1:
            raise BaselineMissingError(
                "未拿到昨日已验收日报，MTD/YTD(Row8/9/13/14/30)无法链式顺推",
                detail={"needed_rows": needed},
            )
        if report_date.month != 1:
            ytd_rows = [r for r in needed if r in (13, 14, 30)]
            if ytd_rows:
                raise BaselineMissingError(
                    f"月初（{report_date.strftime('%m月%d日')}）MTD 从 0 重置，"
                    "但 YTD(Row13/14/30) 需要上月末基线无法自动补零。"
                    "请通过 POST /reports/baseline 提供上月末的 YTD 累计值。",
                    detail={"needed_rows": ytd_rows},
                )


def _in_inclusion(employee_type) -> bool:
    return str(employee_type or "").strip() in C.get_included_types()


def _count_today_fact(emp: pd.DataFrame, col: str, first_visible_col: str, report_date):
    """今日入职/离职事实计数（02表Row2/Row3）。

    归属日 = 日期字段(col) 与 首次可见日期(first_visible_col) 中较晚的那个：
      effective_day = first_visible_col  若 first_visible_col > col（晚到：
                       事实已经发生在过去，今天才第一次在快照里看到 —— 补入
                       "今天"，例如某人入职日期=6.22，但系统里第一次出现是
                       6.23，应算 6.23 的今日入职，不是 6.22）
      effective_day = col                否则（含日期字段本身=报告日的当日
                       事实，以及"提前预告"的未来日期——例如离职流程已提前
                       录入 LWD=6.25，但 6.23 就能在快照里看到——这种要等到
                       LWD 那天(6.25)才算"今日离职"，不能提前到首次看到的
                       那天算）
    命中条件：effective_day == report_date。

    为什么不能直接用"日期字段(col) 本身 = 报告日"：employees 是单张可变主表、
    按工号 UPSERT，日期字段会被后续更晚的上传"就地覆盖/追溯修正"（如入职日期
    从 6.22 修正为 6.20）。若日报是按"先把所有日期的数据都入库完、再回头逐日
    生成日报"的顺序跑（如离线批量重算/测试脚本），直接比较当前(已被后续上传
    改写过的)日期字段与 report_date 会产生假阳性/假阴性；用 first_visible_col
    锚定"这条事实是哪天第一次被记录"则不受后续修正影响（该字段只在首次由空
    变为有值时写入一次，见 input_repo.upsert_employees）。
    也不能直接用"first_visible_col = 报告日"：某些离职流程会提前把 LWD 录入
    系统（如 6.23 录入 LWD=6.25），这种要等到 LWD 当天才算"今日离职"，不能
    提前到首次看到的那天算——所以需要 col 与 first_visible_col 取较晚者。
    """
    hits = []
    if emp.empty:
        return {"count": 0, "hits": hits}
    seen_people: set[str] = set()
    for index, r in emp.iterrows():
        if not _in_inclusion(r.get("employee_type")):
            continue
        d = r.get(col)
        if not isinstance(d, date):
            continue
        fv = r.get(first_visible_col)
        if isinstance(fv, date) and fv > d:
            effective, reason = fv, "晚到补入今天"
        else:
            effective, reason = d, "当日事实"
        if effective == report_date:
            person_key = r.get("person_key")
            if person_key is None or (
                isinstance(person_key, float) and pd.isna(person_key)
            ) or not str(person_key).strip():
                person_key = r.get("emp_no") or f"row:{index}"
            identity = str(person_key)
            if identity in seen_people:
                continue
            seen_people.add(identity)
            hits.append({"emp_no": r.get("emp_no"), "date": str(d), "reason": reason})
    return {"count": len(hits), "hits": hits}


def _resignations_by_emp(res: pd.DataFrame) -> dict[str, list[dict]]:
    by_emp: dict[str, list[dict]] = {}
    if res.empty:
        return by_emp
    for _, r in res.iterrows():
        emp_no = str(r.get("emp_no") or "").strip()
        if emp_no:
            by_emp.setdefault(emp_no, []).append(r.to_dict())
    return by_emp


def _departure_fact_confirmed(
    emp_row: pd.Series | dict,
    res_by_emp: dict[str, list[dict]],
    leave_date: date,
) -> tuple[bool, str]:
    """离职事实是否已生效（Row3 / 在岗 YTD 共用）。

    有离职流程时以流程状态为准：审批中/等待审批不算已离职；
    无流程记录时回退人员表 status=resigned/含「离」。
    """
    emp_no = str((emp_row.get("emp_no") if hasattr(emp_row, "get") else "") or "").strip()
    status = str(emp_row.get("employee_status") or "")
    recs = [
        r for r in res_by_emp.get(emp_no, [])
        if r.get("last_working_day") == leave_date
    ]
    if recs:
        statuses = [str(record.get("process_status") or "") for record in recs]
        rejected_statuses = C.get_process_status_rejected()
        pending_statuses = C.get_process_status_row3_pending()
        effective = [
            status for status in statuses
            if status not in rejected_statuses and status not in pending_statuses
        ]
        if effective:
            return True, f"流程{effective[0]}"
        pending = [status for status in statuses if status in pending_statuses]
        if pending:
            return False, f"流程{pending[0]}未生效"
        return False, f"流程{statuses[0]}"
    if status == "resigned" or "离" in status:
        return True, "人员状态已离职"
    return False, "仍在职或无有效离职流程"


def _count_today_resigns(emp: pd.DataFrame, res: pd.DataFrame, report_date: date):
    """Row3：归属日=报告日，且离职流程已审批完成（审批中不计）。"""
    emp = _selected_employment_rows(emp)
    res_by_emp = _resignations_by_emp(res)
    raw = _count_today_fact(emp, "leave_date", "leave_first_visible", report_date)
    hits = []
    for h in raw["hits"]:
        emp_no = h.get("emp_no")
        sub = emp[emp["emp_no"] == emp_no] if emp_no and not emp.empty else pd.DataFrame()
        if sub.empty:
            continue
        row = sub.iloc[0]
        ld = row.get("leave_date")
        if not isinstance(ld, date):
            continue
        ok, note = _departure_fact_confirmed(row, res_by_emp, ld)
        if ok:
            hits.append({**h, "process": note})
    return {"count": len(hits), "hits": hits}


def _person_identity(row: pd.Series | dict) -> str | None:
    for column in ("person_id", "person_key"):
        value = row.get(column)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        identity = str(value).strip()
        if identity:
            return identity
    return None


def _selected_employment_numbers(emp: pd.DataFrame) -> dict[str, str]:
    """Choose one current employment per natural person using the weekly tie-break."""
    if emp.empty:
        return {}

    selected: dict[str, tuple[date, str]] = {}
    for _, row in emp.iterrows():
        identity = _person_identity(row)
        if identity is None:
            continue
        emp_no = str(row.get("emp_no") or "").strip()
        if not emp_no:
            continue
        hire_date = row.get("hire_date")
        candidate = (
            hire_date if isinstance(hire_date, date) else date.min,
            emp_no,
        )
        if identity not in selected or candidate > selected[identity]:
            selected[identity] = candidate
    return {identity: candidate[1] for identity, candidate in selected.items()}


def _selected_employment_rows(emp: pd.DataFrame) -> pd.DataFrame:
    """Keep the canonical employment while preserving rows without stable identity."""
    selected = _selected_employment_numbers(emp)
    if emp.empty or not selected:
        return emp

    keep: list[bool] = []
    for _, row in emp.iterrows():
        identity = _person_identity(row)
        emp_no = str(row.get("emp_no") or "").strip()
        selected_emp_no = selected.get(identity) if identity else None
        keep.append(
            selected_emp_no is None or not emp_no or emp_no == selected_emp_no
        )
    return emp.loc[keep].copy()


def _employment_identities_by_number(emp: pd.DataFrame) -> dict[str, str]:
    """Resolve fallback resignation identities through the personnel roster."""
    if emp.empty:
        return {}

    identities: dict[str, str] = {}
    for _, row in emp.iterrows():
        emp_no = str(row.get("emp_no") or "").strip()
        identity = _person_identity(row)
        if not emp_no or identity is None:
            continue
        identities[emp_no] = identity
    return identities


def _selected_resignation_rows(emp: pd.DataFrame, res: pd.DataFrame):
    selected_employments = _selected_employment_numbers(emp)
    employment_identities = _employment_identities_by_number(emp)
    for index, row in res.iterrows():
        emp_no = str(row.get("emp_no") or "").strip()
        identity = employment_identities.get(emp_no) or _person_identity(row)
        if identity is None:
            process_no = str(row.get("process_no") or "").strip()
            identity = f"process:{process_no or index}"
        selected_emp_no = selected_employments.get(identity)
        if selected_emp_no and emp_no and emp_no != selected_emp_no:
            continue
        yield identity, row


def _count_active_resign(
    emp: pd.DataFrame,
    res: pd.DataFrame,
    report_date: date,
):
    hits = []
    if res.empty:
        return {"count": 0, "hits": hits}
    seen = set()
    for identity, r in _selected_resignation_rows(emp, res):
        rtype = str(r.get("resignation_type") or "")
        status = str(r.get("process_status") or "")
        apply_t = r.get("apply_time")
        ad = apply_t.date() if hasattr(apply_t, "date") else None
        pno = str(r.get("process_no") or "").strip()
        if not _is_active_type(rtype):
            continue
        if status in C.get_process_status_rejected():
            continue
        if ad != report_date:
            continue

        if identity in seen:
            continue
        seen.add(identity)
        hits.append({"process_no": pno, "name": r.get("name"), "apply": str(ad)})
    return {"count": len(hits), "hits": hits}


def _is_active_type(rtype: str) -> bool:
    return rtype in C.get_resignation_active()


def _count_release(agr: pd.DataFrame, report_date):
    """Row5：今日首次可见并计入；HR 人工明确计入时优先于日期过滤。"""
    hits = []
    if agr.empty:
        return {"count": 0, "hits": hits}
    seen = set()
    for _, r in agr.iterrows():
        fsb = r.get("first_seen_batch")
        manual_include = bool(r.get("manual_row5_include"))
        if (
            not manual_include
            and (fsb if isinstance(fsb, date) else None) != report_date
        ):
            continue
        if not bool(r.get("counts_row5")):
            continue
        ono = r.get("order_no")
        if ono in seen:
            continue
        seen.add(ono)
        hits.append({"order_no": ono, "manual_override": manual_include})
    return {"count": len(hits), "hits": hits}


def _release_to_month_end(agr: pd.DataFrame, report_date, baseline_val):
    """Row30：昨日值 + 当日新增；HR 人工确认计入时优先于首次可见日期。"""
    inc = 0
    hits = []
    if not agr.empty:
        seen = set()
        for _, r in agr.iterrows():
            fsb = r.get("first_seen_batch")
            manual_include = bool(r.get("manual_row5_include"))
            if (
                not manual_include
                and (fsb if isinstance(fsb, date) else None) != report_date
            ):
                continue
            if bool(r.get("lwd_pending")):
                continue
            if not bool(r.get("in_month_release")):
                continue
            ono = r.get("order_no")
            if ono in seen:
                continue
            seen.add(ono)
            inc += 1
            hits.append({"order_no": ono})
    return {"value": (baseline_val or 0) + inc, "increment": inc, "hits": hits}


def _proposed_this_month(emp: pd.DataFrame, res: pd.DataFrame, report_date):
    """Row31：本月主动离职申请 + LWD 在本月 + 流程未拒。"""
    roster = []
    if not res.empty:
        seen = set()
        for identity, r in _selected_resignation_rows(emp, res):
            rtype = str(r.get("resignation_type") or "")
            status = str(r.get("process_status") or "")
            if not _is_active_type(rtype):
                continue
            if status in C.get_process_status_rejected():
                continue
            apply_t = r.get("apply_time")
            ad = apply_t.date() if hasattr(apply_t, "date") else None
            lwd = r.get("last_working_day")
            lwd = lwd if isinstance(lwd, date) else None
            if not same_month(ad, report_date):
                continue
            if not same_month(lwd, report_date):
                continue
            if identity in seen:
                continue
            seen.add(identity)
            roster.append({"process_no": r.get("process_no"), "name": r.get("name"),
                           "lwd": str(lwd) if lwd else None,
                           "type": r.get("resignation_type")})
    return {"count": len(roster), "roster": roster, "hits": roster}


def _proposed_last_month_leave_this_month(
    emp: pd.DataFrame,
    res: pd.DataFrame,
    report_date,
):
    """Row32：上月申请 + LWD 在本月 + 流程未拒（含主动/被动）。"""
    hits = []
    prev_m = 12 if report_date.month == 1 else report_date.month - 1
    prev_y = report_date.year - 1 if report_date.month == 1 else report_date.year
    if not res.empty:
        seen = set()
        for identity, r in _selected_resignation_rows(emp, res):
            status = str(r.get("process_status") or "")
            if status in C.get_process_status_rejected():
                continue
            apply_t = r.get("apply_time")
            ad = apply_t.date() if hasattr(apply_t, "date") else None
            lwd = r.get("last_working_day")
            lwd = lwd if isinstance(lwd, date) else None
            if (
                ad
                and ad.month == prev_m
                and ad.year == prev_y
                and same_month(lwd, report_date)
                and identity not in seen
            ):
                seen.add(identity)
                hits.append({"process_no": r.get("process_no"), "name": r.get("name")})
    return {"count": len(hits), "hits": hits}


def _recruitment_value(rec: pd.DataFrame, col: str):
    total = None
    rowsum = 0
    if not rec.empty:
        for _, r in rec.iterrows():
            v = to_int(r.get(col)) or 0
            if bool(r.get("is_total_row")):
                total = v
            else:
                rowsum += v
    if total is not None and total > 0:
        chosen = total
    elif rowsum > 0:
        chosen = rowsum
    else:
        chosen = int(total or 0)
    # 合计行存在时，任何与逐行求和的差异都应标记为冲突；
    # 之前 total > 0 的条件会导致 total=0 而 rowsum>0 时静默通过（不报冲突、取 rowsum）
    conflict = total is not None and rowsum > 0 and total != rowsum
    if conflict:
        log.error(
            "招聘取数分歧：合计行与逐行求和不一致，校验将硬阻断；"
            "详情见受控验证报告"
        )
    return {"value": chosen, "total": total, "rowsum": rowsum, "conflict": conflict}
