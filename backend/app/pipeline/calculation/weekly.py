"""周报（§4）：Sheet2（主体×事业部）+ Sheet1（成本中心×项目）。从主表动态重算。

落库 weekly_reports 时，本周入/离职取"正式员工"口径（schema 仅有 *_formal 列）；
Excel 则保留全口径与前三项目、成本中心维度。

在职/本周离职与日报 Row3 对齐：人员表日期 + 离职流程状态（审批中/被拒不算已离职）。
本周入职与日报 Row2 对齐：归属日 = max(hire_date, hire_first_visible)（晚到补入）。"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

import pandas as pd

from sqlalchemy.orm import Session

from app.core import constants as C
from app.core.constants import TYPE_BUCKET
from app.core.logging import get_logger
from app.pipeline.calculation.daily import (
    _departure_fact_confirmed,
    _in_inclusion,
    _resignations_by_emp,
    _selected_employment_rows,
)
from app.repositories import report_repo
from app.utils import calendar_utils as cal

log = get_logger("calc.weekly")


def _effective_hire_day(row: pd.Series | dict) -> date | None:
    """入职归属日（与日报 Row2 / daily._count_today_fact 一致）。"""
    hd = row.get("hire_date")
    if not isinstance(hd, date):
        return None
    fv = row.get("hire_first_visible")
    if isinstance(fv, date) and fv > hd:
        return fv
    return hd


def _effective_leave_day(row: pd.Series | dict) -> date | None:
    """离职归属日（与日报 Row3 / daily._count_today_fact 的 leave 归属一致）。

    归属日 = max(leave_date, leave_first_visible)：晚到补入（离职事实先发生、
    快照里晚一天才可见时算首次可见日）。注意窗口归属用本归属日，但离职流程
    生效判定（_departure_fact_confirmed）仍以原始 leave_date 与离职报表 LWD 匹配。"""
    ld = row.get("leave_date")
    if not isinstance(ld, date):
        return None
    fv = row.get("leave_first_visible")
    if isinstance(fv, date) and fv > ld:
        return fv
    return ld


def _departed_by_week_end(
    row: pd.Series | dict,
    window_end: date,
    res_by_emp: dict[str, list[dict]],
) -> bool:
    """窗口结束日是否已离职（流程已生效且离职事实在窗口末已可见）。

    归属日（含晚到补入）晚于窗口末 → 窗口末尚不可见，仍视为在职；
    LWD 已预填但流程审批中/被拒 → 仍视为在职（如 E77/E78）。
    生效判定用原始 leave_date 与离职报表 LWD 匹配。"""
    eff = _effective_leave_day(row)
    if eff is None or eff > window_end:
        return False
    ok, _ = _departure_fact_confirmed(row, res_by_emp, row.get("leave_date"))
    return ok


def _active(
    emp: pd.DataFrame,
    window_end: date,
    res_by_emp: dict[str, list[dict]],
) -> pd.DataFrame:
    """纳入口径在职：入职日 <= 窗口结束，且窗口结束日离职事实未生效。"""
    if emp.empty:
        return emp

    def is_active(row) -> bool:
        if not _in_inclusion(row.get("employee_type")):
            return False
        # 入职归属日（含晚到补入）晚于窗口末 → 窗口末尚不可见，不计在职。
        # 与本周入职（_effective_hire_day）及离职快照口径对称；无 hire_date 时沿用宽松处理。
        eff_hd = _effective_hire_day(row)
        if eff_hd is not None and eff_hd > window_end:
            return False
        return not _departed_by_week_end(row, window_end, res_by_emp)

    return emp[emp.apply(is_active, axis=1)]


_SHEET2_SOURCE = "人员表（窗口结束日在职快照 + 窗口内入离职归属日）"
_SHEET2_FORMULA = (
    "在职总数=COUNT(纳入口径 且 入职日≤窗口末 且 窗口末离职未生效)；"
    "类型拆分=正式+实习+劳务；本周入职=COUNT(入职归属日∈窗口)；"
    "本周离职=COUNT(离职归属日∈窗口 且 离职流程已生效)"
)


def _business_unit(row: pd.Series | dict) -> str:
    return str(row.get("business_unit_no") or row.get("business_unit") or "").strip()


def _project_family(project_name: object) -> str:
    name = str(project_name or "").strip()
    for family in C.WEEKLY_PROJECT_FAMILIES:
        if any(name.startswith(prefix) for prefix in family["prefixes"]):
            return str(family["name"])
    return name


def top3_tie_ref(business_unit: str) -> str:
    """Opaque stable reference for a business unit's Top-3 cutoff review."""
    return hashlib.sha256(
        f"weekly-top3:{business_unit}".encode("utf-8")
    ).hexdigest()[:12]


def _project_family_conflicts(project_names) -> list[dict]:
    """同一项目名命中多个族前缀时，归并结果取决于配置顺序——
    列出冲突项目与命中的族，供软校验暴露、人工确认配置。"""
    conflicts = []
    for name in sorted({str(n).strip() for n in project_names
                        if n is not None and str(n).strip()}):
        matched = list(dict.fromkeys(
            str(family["name"]) for family in C.WEEKLY_PROJECT_FAMILIES
            if any(name.startswith(prefix) for prefix in family["prefixes"])
        ))
        if len(matched) > 1:
            conflicts.append({"project": name, "families": matched})
    return conflicts


def _daily_reconciliation(db: Session, week_start: date, week_end: date) -> dict:
    daily = report_repo.load_daily_week_totals(db, week_start, week_end)
    expected_dates: list[date] = []
    current = week_start
    while current <= week_end:
        if cal.is_workday(current):
            expected_dates.append(current)
        current += timedelta(days=1)
    daily["expected_dates"] = expected_dates
    daily["complete"] = daily.get("report_dates") == expected_dates
    return daily


def _dedupe_active_people(active: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Count a natural person once while retaining employment-level review evidence."""
    if active.empty or "person_key" not in active.columns:
        return active, []

    work = active.copy()
    identity_keys = []
    for index, row in work.iterrows():
        key = row.get("person_key")
        if key is None or (isinstance(key, float) and pd.isna(key)) or not str(key):
            key = f"employment:{index}"
        identity_keys.append(str(key))
    work["_person_identity"] = identity_keys

    selected_indices: list[Any] = []
    reviews: list[dict] = []
    dimensions = (
        "business_unit_no",
        "business_unit",
        "project_no",
        "project_name",
        "employee_type",
    )
    for identity, group in work.groupby("_person_identity", sort=False):
        if len(group) == 1:
            selected_indices.append(group.index[0])
            continue

        conflicts = []
        for dimension in dimensions:
            values = {
                str(value).strip()
                for value in group[dimension].tolist()
                if value is not None and str(value).strip()
            }
            if len(values) > 1:
                conflicts.append(dimension)

        def _selection_key(index):
            row = group.loc[index]
            hire_date = row.get("hire_date")
            return (
                hire_date if isinstance(hire_date, date) else date.min,
                str(row.get("emp_no") or ""),
            )

        selected_index = max(group.index, key=_selection_key)
        selected_indices.append(selected_index)
        source_rows = []
        if "source_row_no" in group.columns:
            source_rows = sorted(
                int(value)
                for value in group["source_row_no"].tolist()
                if value is not None and not pd.isna(value)
            )
        selected_source_row = group.loc[selected_index].get("source_row_no")
        reviews.append(
            {
                "code": "multiple_active_employments",
                "severity": "BLOCK" if conflicts else "REVIEW",
                "person_ref": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12],
                "employment_count": len(group),
                "employment_source_row_nos": source_rows,
                "selected_source_row_no": (
                    int(selected_source_row)
                    if selected_source_row is not None
                    and not pd.isna(selected_source_row)
                    else None
                ),
                "conflicting_dimensions": conflicts,
            }
        )

    deduplicated = work.loc[selected_indices].drop(columns=["_person_identity"])
    return deduplicated.reset_index(drop=True), reviews


def compute_weekly(
    db: Session | None,
    week_start: date,
    week_end: date,
    *,
    input_frames: Mapping[str, pd.DataFrame] | None = None,
    daily_reconciliation: Mapping[str, Any] | None = None,
    snapshot_found_override: bool | None = None,
    top3_selections: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    if input_frames is None:
        if db is None:
            raise ValueError("db is required when input_frames are not provided")
        emp = report_repo.load_employees(db)
        end_snapshot = report_repo.load_employee_snapshot(db, week_end)
        res = report_repo.load_resignations(db)
    else:
        emp = input_frames["employees"].copy(deep=True)
        end_snapshot = input_frames["end_snapshot"].copy(deep=True)
        res = input_frames["resignations"].copy(deep=True)
    res_by_emp = _resignations_by_emp(res)
    # 周窗口事件与日报 Row2/Row3 共用当前主任职，避免旧任职离职与新任职在职并存时重复计数。
    event_emp = _selected_employment_rows(emp)
    if end_snapshot.empty:
        log.warning("周报缺少 %s 人员快照，暂按主表兼容计算", week_end)
        active = _active(emp, week_end, res_by_emp)
    else:
        active_snapshot = end_snapshot[
            end_snapshot["employee_status"].astype(str) == "active"
        ]
        active = _active(active_snapshot, week_end, res_by_emp)
    active, identity_reviews = _dedupe_active_people(active)
    top3_reviews: list[dict[str, Any]] = []
    top3_selections = top3_selections or {}

    seen_bus = {_business_unit(r) for _, r in active.iterrows()} if not active.empty else set()
    # 窗口末零在职但本周有入/离职事实的事业部也必须出行，否则其人数从
    # Sheet2 合计消失，与日报 Row2/Row3 的交叉校验会漏报或误报。
    # 判定条件与 _window_count 完全一致，保证「有行 ⇔ 计数非零」。
    if not event_emp.empty:
        for _, r in event_emp.iterrows():
            bu = _business_unit(r)
            if not bu or bu in seen_bus or not _in_inclusion(r.get("employee_type")):
                continue
            hd = _effective_hire_day(r)
            if isinstance(hd, date) and week_start <= hd <= week_end:
                seen_bus.add(bu)
                continue
            ld = _effective_leave_day(r)
            if (isinstance(ld, date) and week_start <= ld <= week_end
                    and _departure_fact_confirmed(r, res_by_emp, r.get("leave_date"))[0]):
                seen_bus.add(bu)
    seen_bus.discard("")
    bus = [bu for bu in C.WEEKLY_BUSINESS_UNIT_ORDER if bu in seen_bus]
    bus.extend(sorted(seen_bus - set(bus)))
    log.info(
        "周报计算开始：窗口 %s ~ %s",
        week_start,
        week_end,
    )

    # 每行的事业部只算一次，避免逐 BU 全表 apply（O(BU×N) 的 Python 级扫描）
    active_bu = active.apply(_business_unit, axis=1) if not active.empty else None
    event_bu = (
        event_emp.apply(_business_unit, axis=1) if not event_emp.empty else None
    )

    main_rows = []
    trace = []
    unbucketed_all: list[dict] = []
    for bu in bus:
        sub = active[active_bu == bu] if active_bu is not None else active
        emp_sub = (
            event_emp[event_bu == bu] if event_bu is not None else event_emp
        )
        formal = intern = labor = 0
        headcount = 0
        proj_counts: dict[str, int] = {}
        for _, r in (sub.iterrows() if not sub.empty else []):
            # sub 已按「纳入口径 + 窗口末在职」过滤，每一行都计入在职总数；
            # 在职总数取实际在职人数（而非类型拆分之和），使「拆分=总数」硬校验有意义、
            # 能在类型未落入 TYPE_BUCKET 时暴露问题，而不是被定义式恒等静默吞掉。
            headcount += 1
            bucket = TYPE_BUCKET.get(str(r.get("employee_type") or ""))
            if bucket == "正式员工":
                formal += 1
            elif bucket == "实习生":
                intern += 1
            elif bucket == "劳务人员":
                labor += 1
            else:
                unbucketed_all.append({
                    "bu": bu, "emp_no": r.get("emp_no"),
                    "employee_type": r.get("employee_type"),
                })
            pn = r.get("project_name")
            if pn:
                family = _project_family(pn)
                proj_counts[family] = proj_counts.get(family, 0) + 1

        joiners, joiner_ids = _window_count(
            emp_sub, week_start, week_end, res_by_emp, joiners=True,
        )
        leavers, leaver_ids = _window_count(
            emp_sub, week_start, week_end, res_by_emp, leavers=True,
        )
        joiners_formal, _ = _window_count(
            emp_sub, week_start, week_end, res_by_emp,
            joiners=True, formal_only=True,
        )
        leavers_formal, _ = _window_count(
            emp_sub, week_start, week_end, res_by_emp,
            leavers=True, formal_only=True,
        )

        ranked_projects = sorted(
            proj_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
        top3 = ranked_projects[:3]
        if len(ranked_projects) > 3:
            cutoff_count = ranked_projects[2][1]
            above_cutoff = [
                item for item in ranked_projects if item[1] > cutoff_count
            ]
            tied_at_cutoff = [
                item for item in ranked_projects if item[1] == cutoff_count
            ]
            slots = 3 - len(above_cutoff)
            if len(tied_at_cutoff) > slots:
                candidates = sorted(name for name, _ in tied_at_cutoff)
                tie_ref = top3_tie_ref(bu)
                selection_key = f"{tie_ref}:{slots}"
                requested = list(top3_selections.get(selection_key) or ())
                valid_request = (
                    len(requested) == slots
                    and len(set(requested)) == slots
                    and set(requested).issubset(candidates)
                )
                selected = requested if valid_request else candidates[:slots]
                top3 = sorted(
                    [*above_cutoff, *((name, proj_counts[name]) for name in selected)],
                    key=lambda kv: (-kv[1], kv[0]),
                )
                top3_reviews.append(
                    {
                        "code": "top3_cutoff_tie",
                        "severity": "REVIEW",
                        "business_unit": bu,
                        "tie_ref": tie_ref,
                        "candidates": candidates,
                        "slots": slots,
                        "selected_projects": selected,
                    }
                )
        top3_list = [{"name": n, "count": c} for n, c in top3]

        main_rows.append({
            "business_unit": bu, "headcount": headcount,
            "cnt_formal": formal, "cnt_intern": intern, "cnt_labor": labor,
            "joiners": joiners, "leavers": leavers,
            "joiners_formal": joiners_formal, "leavers_formal": leavers_formal,
            "top3_projects": top3_list,
        })
        trace.append({
            "scope": "weekly", "ref": bu, "item": "主体×事业部（Sheet2）",
            "headcount": headcount, "split": [formal, intern, labor],
            "joiners": joiners, "leavers": leavers,
            "joiners_formal": joiners_formal, "leavers_formal": leavers_formal,
            "top3": top3_list,
            "source": _SHEET2_SOURCE, "formula": _SHEET2_FORMULA,
            # 命中工号只留入/离职（解释 Row2/Row3 的最小证据）；
            # 在职 roster 属人员级名单，不进 trace 也不进计算日志。
            "hits": {"joiners": joiner_ids, "leavers": leaver_ids},
        })

    # ---- 合计行：与 Excel「合计」一致，确保逐行日志覆盖所有行（含汇总）----
    if main_rows:
        total = {
            "scope": "weekly", "ref": "合计", "item": "全部事业部合计（Sheet2）",
            "headcount": sum(x["headcount"] for x in main_rows),
            "split": [sum(x["cnt_formal"] for x in main_rows),
                      sum(x["cnt_intern"] for x in main_rows),
                      sum(x["cnt_labor"] for x in main_rows)],
            "joiners": sum(x["joiners"] for x in main_rows),
            "leavers": sum(x["leavers"] for x in main_rows),
            "joiners_formal": sum(x["joiners_formal"] for x in main_rows),
            "leavers_formal": sum(x["leavers_formal"] for x in main_rows),
            "top3": [],
            "source": "各事业部 Sheet2 行求和",
            "formula": "合计=Σ各事业部（在职总数 / 类型拆分 / 本周入职 / 本周离职）",
            "is_total": True,
        }
        trace.append(total)
    if unbucketed_all:
        log.warning(
            "周报存在未映射员工类型；类型拆分校验将拦截，详见受控验证报告"
        )

    cc_rows = _cost_center_rows(
        event_emp, active, week_start, week_end, res_by_emp
    )
    log.info("周报计算完成")

    project_names: list = []
    if not active.empty:
        project_names.extend(active["project_name"].dropna().tolist())
    if not emp.empty:
        project_names.extend(emp["project_name"].dropna().tolist())

    return {
        "week_start": week_start,
        "week_end": week_end,
        "main_rows": main_rows,
        "cc_rows": cc_rows,
        "trace": trace,
        "snapshot_found": (
            not end_snapshot.empty
            if snapshot_found_override is None
            else snapshot_found_override
        ),
        "daily_reconciliation": (
            _daily_reconciliation(db, week_start, week_end)
            if daily_reconciliation is None
            else dict(daily_reconciliation)
        ),
        "project_family_conflicts": _project_family_conflicts(project_names),
        "review_items": [*identity_reviews, *top3_reviews],
    }


def compute_weekly_from_frames(
    *,
    employees: pd.DataFrame,
    resignations: pd.DataFrame,
    week_start: date,
    week_end: date,
    daily_reconciliation: Mapping[str, Any],
    top3_selections: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    return compute_weekly(
        None,
        week_start,
        week_end,
        input_frames={
            "employees": employees,
            "end_snapshot": employees,
            "resignations": resignations,
        },
        daily_reconciliation=daily_reconciliation,
        snapshot_found_override=True,
        top3_selections=top3_selections,
    )


def _window_count(
    sub: pd.DataFrame,
    start: date,
    end: date,
    res_by_emp: dict[str, list[dict]],
    *,
    formal_only: bool = False,
    joiners: bool = False,
    leavers: bool = False,
) -> tuple[int, list[str]]:
    """返回 (命中人数, 命中工号列表)，供逐行日志留痕（对齐日报 hits）。

    sub 须已按事业部过滤（调用方用预计算的 BU Series 切片，避免逐次全表扫描）。"""
    ids: list[str] = []
    if sub.empty:
        return 0, ids
    seen_people: set[str] = set()
    for index, r in sub.iterrows():
        if not _in_inclusion(r.get("employee_type")):
            continue
        if formal_only and TYPE_BUCKET.get(str(r.get("employee_type") or "")) != "正式员工":
            continue
        if joiners:
            d = _effective_hire_day(r)
        else:
            d = _effective_leave_day(r)
        if not isinstance(d, date) or not (start <= d <= end):
            continue
        if leavers:
            # 归属用归属日 d（含晚到补入），生效判定用原始 leave_date 匹配离职报表 LWD
            ok, _ = _departure_fact_confirmed(r, res_by_emp, r.get("leave_date"))
            if not ok:
                continue
        person_key = r.get("person_key")
        if person_key is None or (
            isinstance(person_key, float) and pd.isna(person_key)
        ) or not str(person_key).strip():
            person_key = r.get("emp_no") or f"row:{index}"
        identity = str(person_key)
        if identity in seen_people:
            continue
        seen_people.add(identity)
        emp_no = r.get("emp_no")
        ids.append(str(emp_no) if emp_no is not None and str(emp_no).strip() else "?")
    return len(ids), ids


def _cost_center_rows(
    emp: pd.DataFrame,
    active: pd.DataFrame,
    start: date,
    end: date,
    res_by_emp: dict[str, list[dict]],
) -> list[dict]:
    rows = []
    # 项目族映射整表只算一次，避免每个族重复 map 全列
    active_family = active["project_name"].map(_project_family) if not active.empty else None
    emp_family = emp["project_name"].map(_project_family) if not emp.empty else None
    for family in C.WEEKLY_PROJECT_FAMILIES:
        proj = str(family["name"])
        cost_center = str(family.get("cost_center") or "")
        if not cost_center:
            continue
        hc = int((active_family == proj).sum()) if active_family is not None else 0
        joiners = leavers = 0
        joiner_ids: list[str] = []
        leaver_ids: list[str] = []
        sub = emp[emp_family == proj] if emp_family is not None else emp
        seen_joiners: set[str] = set()
        seen_leavers: set[str] = set()
        for index, r in (sub.iterrows() if not sub.empty else []):
            if not _in_inclusion(r.get("employee_type")):
                continue
            eff = _effective_hire_day(r)
            eff_l = _effective_leave_day(r)
            emp_no = str(r.get("emp_no")) if r.get("emp_no") is not None else "?"
            person_key = r.get("person_key")
            if person_key is None or (
                isinstance(person_key, float) and pd.isna(person_key)
            ) or not str(person_key).strip():
                person_key = r.get("emp_no") or f"row:{index}"
            identity = str(person_key)
            if (
                isinstance(eff, date)
                and start <= eff <= end
                and identity not in seen_joiners
            ):
                seen_joiners.add(identity)
                joiners += 1
                joiner_ids.append(emp_no)
            if (
                isinstance(eff_l, date)
                and start <= eff_l <= end
                and identity not in seen_leavers
            ):
                ok, _ = _departure_fact_confirmed(r, res_by_emp, r.get("leave_date"))
                if ok:
                    seen_leavers.add(identity)
                    leavers += 1
                    leaver_ids.append(emp_no)
        rows.append({
            "cost_center": cost_center, "project": proj,
            "headcount": hc, "joiners": joiners, "leavers": leavers,
            "source": "人员表（按项目归集在职快照 + 窗口内入离职）",
            "formula": ("在职人数=COUNT(在职快照.project=本项目)；"
                        "本周入职/离职口径同 Sheet2"),
            "hits": {"joiners": joiner_ids, "leavers": leaver_ids},
        })
    return rows
