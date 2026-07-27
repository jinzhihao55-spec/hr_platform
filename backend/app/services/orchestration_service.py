"""对话驱动的流水线编排服务。

前端只需调用 POST /chat，本服务根据当前流水线状态和用户消息决定做什么：

  消息中的日期引用（6/22、2026-06-22、6月22日）会覆盖默认报告日。

  状态机（按优先级）：
  1. 检测是否有待确认澄清 + 用户消息是否是答复 → 应用答复 → 更新 DB 字段 → 重试生成
  2. 用户显式请求生成 → 触发 report_service.generate_daily（支持指定日期）
  3. 差异/明细提问 → 展示 12 项校验的左右值明细
  4. 计算逻辑提问（怎么计算/公式/RowN 怎么算）→ 展示计算日志（逐行公式/取数/trace）
  5. 报表查询（我要 6/22 的日报）→ 返回该日报表摘要 + 文件路径，未生成则引导生成
  6. 显式询问状态/进度 → 返回当前流水线状态摘要
  7. 其他自由文本 → 智能问答（LLM + 库内上下文，数据类问题走 NL->SQL 只读查询）；
     LLM 未配置时回退到状态摘要

所有消息（用户 + 助手）都保存到 chat_messages 表。
澄清答复在 Redis clarify_repo 落地后，若涉及具体 DB 字段（LWD / row30_flag 等），
同步更新数据库对应记录并在 metadata 中留痕。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import chat_repo, clarify_repo, report_repo
from app.services import report_service

log = get_logger("service.orchestration")

# ── 意图检测关键词 ────────────────────────────────────────────
# 显式生成指令。刻意不用单字"开始/执行/计算"等宽泛词——"怎么计算的""开始之前想问下"
# 这类提问不应触发全量生成；组合词（计算日报/开始生成…）才算指令。
_GENERATE_RE = re.compile(
    r"生成|出报|出日报|出周报|计算日报|计算周报|开始计算|开始生成|执行生成"
    r"|\bgenerate\b|\brun\b|跑一下|帮我出",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"状态|进度|进展|情况怎么样|\bstatus\b|\bprogress\b", re.IGNORECASE)
# 计算逻辑提问：展示计算日志（逐行公式 / 取数来源 / trace），不走 LLM
_CALC_Q_RE = re.compile(
    r"怎么算|怎么计算|如何计算|怎样计算|计算逻辑|计算过程|计算方法|计算日志|公式|"
    r"为什么\s*row|how\s+.*calculat", re.IGNORECASE,
)
_ROW_REF_RE = re.compile(r"row\s*(\d{1,2})", re.IGNORECASE)
# 校验差异/明细提问：展示 12 项校验的左右值明细
_DIFF_RE = re.compile(r"差异|明细|校验详情|对不上|不一致|为什么不等|diff", re.IGNORECASE)
# 查看/获取某日报表："我要 6/22 的日报"、"看看上周的周报"、"日报在哪"
_REPORT_VIEW_RE = re.compile(r"我要|要看|看看|看一下|查看|查一下|给我|在哪|下载|导出|获取|拿")
_REPORT_KIND_RE = re.compile(r"日报|周报")
# 名单/人数查询（确定性，直接查 employees 表，无需 LLM）
# 容错：人员名（少打"单"）、都有谁、有哪些人 等说法都算要名单
_ROSTER_RE = re.compile(r"名单|花名册|人员名|都有谁|有哪些人|有谁|名字|roster", re.IGNORECASE)
_HEADCOUNT_RE = re.compile(
    r"(在职|离职)[^。\n]{0,8}(多少|人数|几人)|(多少|几)人?(在职|离职)")

# 消息中的日期引用：2026-06-22 / 2026/6/22 / 2026年6月22日 / 6/22 / 6月22日 / 22号
_FULL_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日号]?")
_MD_RE = re.compile(r"(?<![\d\-/])(\d{1,2})[/月](\d{1,2})[日号]?(?!\d)")
_DAY_RE = re.compile(r"(?<![\d/\-月])(\d{1,2})\s*[日号](?!\d)")


def _extract_date(message: str, default: date) -> date | None:
    """从消息中提取日期引用；缺年份用 default 的年份，缺月份用 default 的月份。"""
    m = _FULL_DATE_RE.search(message)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = _MD_RE.search(message)
    if m:
        try:
            return date(default.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = _DAY_RE.search(message)
    if m:
        try:
            return date(default.year, default.month, int(m.group(1)))
        except ValueError:
            pass
    return None
_DATA_Q_RE = re.compile(
    r"多少|几个|几人|几条|人数|名单|哪些|谁|查询|查一下|查查|统计|列出|top|排名|"
    r"哪天|什么时候|何时|平均|最多|最少|比例|离职率|合计|明明|对比",
    re.IGNORECASE,
)
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ─────────────────────────────────────────────────────────────
# 公共入口
# ─────────────────────────────────────────────────────────────

def handle_message(
    db: Session,
    report_date: date,
    message: str,
    session_id: str | None = None,
    baseline_date: date | None = None,
) -> dict[str, Any]:
    """处理一条用户消息，返回助手回复字典。

    Returns:
        {
          "session_id": str,
          "role": "assistant",
          "message": str,          # 显示给用户的文字
          "action": str,           # generate | answer_clarification | seed_baseline | info | error
          "status": str,           # succeeded | needs_clarification | blocked | error | info
          "payload": dict | None,  # 生成结果/澄清详情等
        }
    """
    session_id = session_id or uuid.uuid4().hex

    # 1. 保存用户消息
    chat_repo.save(db, session_id, report_date, "user", message)

    # 2. 确定意图并执行
    pending = clarify_repo.list_pending(report_date, db=db)

    # 消息中的日期引用（"我要 6/22 的日报"、"生成 2026-06-22 日报"）覆盖默认报告日
    eff_date = _extract_date(message, report_date) or report_date

    if pending and _looks_like_clarification_answer(message, pending):
        result = _handle_clarification_answer(db, report_date, message, pending, session_id)
    elif _looks_like_generate_intent(message):
        # 仅在用户显式请求生成时触发流水线，避免闲聊消息（如"你好"）误触发全量生成
        result = _handle_generate(db, eff_date, session_id, baseline_date)
    elif _DIFF_RE.search(message):
        # "查看差异明细" → 12 项校验的左右值/差异明细
        result = _handle_diff_detail(db, eff_date, session_id)
    elif _CALC_Q_RE.search(message) or _ROW_REF_RE.search(message):
        # "怎么计算的" / 任何 RowN 引用（"给我 6/22 日报的 Row4"）
        # → 展示该行的值/公式/取数来源/trace（确定性数据）
        result = _handle_calc_explain(db, eff_date, message, session_id)
    elif _REPORT_KIND_RE.search(message) and (
        _REPORT_VIEW_RE.search(message) or eff_date != report_date
    ):
        # "我要 6/22 的日报" / "周报在哪" → 查找该日报表并返回摘要与文件
        result = _handle_report_request(db, eff_date, message, session_id)
    elif _ROSTER_RE.search(message) or _HEADCOUNT_RE.search(message):
        # "在职人员名单" / "现在多少人在职" → 直接查 employees 表（确定性，无需 LLM）
        result = _handle_roster(db, eff_date, message, session_id)
    elif _STATUS_RE.search(message):
        result = _handle_status_query(db, eff_date, session_id)
    else:
        # 自由问答：LLM 智能助手（可用时），否则回退状态摘要
        result = _handle_free_chat(db, report_date, message, session_id)

    # 3. 保存助手回复
    chat_repo.save(
        db, session_id, report_date, "assistant", result["message"],
        action=result.get("action"),
        clarification_id=result.get("clarification_id"),
        metadata=result.get("payload"),
    )

    result["session_id"] = session_id
    return result


# ─────────────────────────────────────────────────────────────
# 意图检测
# ─────────────────────────────────────────────────────────────

def _looks_like_generate_intent(message: str) -> bool:
    return bool(_GENERATE_RE.search(message))


def _looks_like_clarification_answer(message: str, pending: list[dict]) -> bool:
    """判断用户消息是否是对某条待确认澄清的答复。

    启发式规则：
    - 待澄清项中有 baseline_missing → 消息含 JSON 或数字序列
    - 待澄清项中有 lwd_pending → 消息含日期字符串
    - 其他 → 消息较短（<100 字）且含数字或"是/否/确认"等确认词
    """
    # 计算逻辑/差异/状态类提问不是澄清答复——即便消息里带数字（如"Row12 怎么计算的"）
    if _CALC_Q_RE.search(message) or _STATUS_RE.search(message) or _DIFF_RE.search(message):
        return False
    # 报表查询/名单查询/显式生成指令 同样不是澄清答复——这些消息常含数字
    # （"我要 6/22 的日报"、"生成 6/22 日报"），若被当成 baseline 答复消费，
    # 会静默注入基线并触发生成，用户完全没有感知。
    if _GENERATE_RE.search(message) or _ROSTER_RE.search(message) or _HEADCOUNT_RE.search(message):
        return False
    if _REPORT_KIND_RE.search(message) and _REPORT_VIEW_RE.search(message):
        return False

    codes = {p.get("code") for p in pending}
    if "baseline_missing" in codes:
        return (bool(_JSON_RE.search(message)) or bool(re.search(r"\d+", message))
                or bool(re.search(r"自动|重算|auto|recompute", message, re.I)))
    if "lwd_pending" in codes or "input_missing" in codes:
        return bool(_DATE_RE.search(message)) or any(
            kw in message for kw in ("是", "否", "确认", "跳过", "暂无")
        )
    # 通用：短消息 + 含数字/确认词/选项动词（"按合计行取数"、"采用逐行求和"）
    return len(message) < 120 and bool(
        re.search(r"\d|是|否|确认|同意|采用|按|跳过|暂无|ok|yes|no", message, re.I)
    )


# ─────────────────────────────────────────────────────────────
# 生成报表
# ─────────────────────────────────────────────────────────────

def _handle_generate(db: Session, report_date: date, session_id: str,
                     baseline_date: date | None = None) -> dict[str, Any]:
    """触发 generate_daily，将结果翻译为对话回复。"""
    counts = report_repo.count_inputs(db)
    if counts.get("employees", 0) == 0:
        return {
            "message": (
                "人员表（employees）库内为空，无法生成日报。\n"
                "请先通过上传接口（POST /ingest）上传人员表，"
                "支持 .xlsx 或图像截图格式。"
            ),
            "action": "info",
            "status": "needs_clarification",
            "payload": {"missing": "employees"},
        }

    out = report_service.generate_daily_cascade(db, report_date, baseline_date)
    status = out.get("status")

    if status == "succeeded":
        files = []
        partial_weekly_failure = out.get("weekly_status") == "blocked"
        if out.get("daily_xlsx"):
            files.append(f"📊 日报：{out['daily_xlsx']}")
        if out.get("weekly_xlsx"):
            files.append(f"📈 周报：{out['weekly_xlsx']}")
        if out.get("weekly_status") == "blocked":
            checks = "、".join(
                str(item.get("check") or "未知校验")
                for item in (out.get("weekly_hard_failures") or [])
            )
            detail = f"：{checks}" if checks else ""
            files.append(f"⚠️ 自动周报被阻断{detail}")
        if out.get("calc_log_md"):
            files.append(f"📋 计算日志：{out['calc_log_md']}")
        cascaded = out.get("cascaded") or []
        if cascaded:
            ok = [c["report_date"] for c in cascaded if c["status"] == "succeeded"]
            bad = [c for c in cascaded if c["status"] != "succeeded"]
            weekly_bad = [
                c["report_date"] for c in cascaded
                if c.get("weekly_status") == "blocked"
            ]
            if ok:
                files.append(f"🔁 已级联重算后续日报：{'、'.join(ok)}（链式基线已更新）")
            if weekly_bad:
                partial_weekly_failure = True
                files.append(
                    f"⚠️ {'、'.join(weekly_bad)}：级联日报成功，但自动周报被阻断"
                )
            if bad:
                files.append(
                    f"⚠️ 级联重算在 {bad[0]['report_date']} 停止"
                    f"（{bad[0]['status']}），请单独处理该日。")
        headline = (
            "⚠️ 日报已生成，但有周报被阻断"
            if partial_weekly_failure
            else "✅ 报表已生成！"
        )
        return {
            "message": headline + "\n" + "\n".join(files),
            "action": "generate",
            "status": "succeeded",
            "payload": out,
        }

    if status == "needs_clarification":
        err = out.get("error", {})
        pending = clarify_repo.list_pending(report_date, db=db)
        options_hint = ""
        if pending:
            opts = pending[0].get("options") or []
            if opts:
                options_hint = f"\n\n参考格式：\n{opts[0]}"
        return {
            "message": (
                f"⚠️ 需要补充信息才能继续：\n\n{err.get('message', '')}{options_hint}\n\n"
                "请直接在对话中回复，系统会自动继续生成。"
            ),
            "action": "info",
            "status": "needs_clarification",
            "payload": out,
            "clarification_id": pending[0]["id"] if pending else None,
        }

    if status == "blocked":
        hard = out.get("hard_failures", [])
        checks = "\n".join(f"  • {h['check']}" for h in hard)
        return {
            "message": f"🚫 校验未通过，报表已阻断：\n{checks}\n\n请检查输入数据后重新上传。",
            "action": "info",
            "status": "blocked",
            "payload": out,
        }

    return {
        "message": f"❓ 生成结果未知（status={status}）",
        "action": "error",
        "status": "error",
        "payload": out,
    }


# ─────────────────────────────────────────────────────────────
# 澄清答复处理 + DB 字段回写
# ─────────────────────────────────────────────────────────────

def _handle_clarification_answer(
    db: Session,
    report_date: date,
    message: str,
    pending: list[dict],
    session_id: str,
) -> dict[str, Any]:
    """将用户回复应用到第一条待确认澄清，更新相关 DB 字段，然后重试生成。"""
    item = pending[0]
    item_id = item["id"]
    code = item.get("code", "")

    # 1. 记录答复到 Redis clarify_repo
    clarify_repo.answer(item_id, message, db=db)
    db_updates: dict[str, Any] = {}

    # 2. 按澄清类型更新对应 DB 字段
    if code == "baseline_missing":
        db_updates = _apply_baseline_answer(db, report_date, message)

    elif code in ("lwd_pending", "lwd_missing"):
        db_updates = _apply_lwd_answer(db, message, item, report_date)

    elif code == "inclusion_filter":
        db_updates = _apply_inclusion_answer(db, message, item)

    # 3. 澄清已答复 → 自动重试生成
    retry_result = _handle_generate(db, report_date, session_id)

    action_summary = f"已记录澄清答复（{code}）"
    if db_updates:
        action_summary += f"，DB 已更新：{db_updates}"

    retry_payload = retry_result.get("payload") or {}
    retry_msg = retry_result["message"]
    return {
        "message": f"\U0001f4dd {action_summary}\n\n{retry_msg}",
        "action": "answer_clarification",
        "status": retry_result["status"],
        "clarification_id": item_id,
        "payload": {**retry_payload, "db_updates": db_updates},
    }


def _apply_baseline_answer(db: Session, report_date: date, message: str) -> dict:
    """从消息解析基线数值并注入 daily_reports。

    「自动重算」/全 0/解析不出数值 → 按库内数据全量重算
    （report_service.resolve_baseline_values），避免注入全 0 基线后
    Row14 链式值与在岗时长 B10 硬校验永远对不上、报表反复被阻断。
    """
    vals: dict[str, Any] = {}
    auto = report_service._wants_auto_baseline(message)
    if not auto:
        # 尝试解析 JSON
        m = _JSON_RE.search(message)
        if m:
            try:
                vals = json.loads(m.group())
            except json.JSONDecodeError:
                pass
        # 回退：尝试从自然语言提取五个数字（row8 row9 row13 row14 row30 顺序）
        if not vals:
            nums = re.findall(r"\d+", message)
            if len(nums) >= 5:
                keys = ["row8", "row9", "row13", "row14", "row30"]
                vals = {k: int(n) for k, n in zip(keys, nums[:5])}
        # 解析不出数值（如「都是0」「全0」「没有基线」）→ 不再提前返回 {}，
        # 而是按 docstring 承诺交给 resolve_baseline_values 全量重算。
        # 之前这里 return {} 会导致：答复已被 clarify_repo 标记为已答，
        # 但基线未注入，重试生成再次 baseline_missing —— 死循环。

    for_date_str = vals.get("for_date")
    if for_date_str:
        try:
            for_date = date.fromisoformat(str(for_date_str))
        except ValueError:
            for_date = report_date - timedelta(days=1)
    else:
        for_date = report_date - timedelta(days=1)

    if for_date >= report_date:
        # 基线必须早于报告日（get_baseline_rows 用严格 <）；注入到报告日
        # 当天/之后的行取不到，会陷入 baseline_missing 死循环
        for_date = report_date - timedelta(days=1)

    vals = report_service.resolve_baseline_values(db, for_date, vals)
    report_service.seed_baseline(
        db, for_date=for_date,
        row8=int(vals.get("row8") or 0),
        row9=int(vals.get("row9") or 0),
        row13=int(vals.get("row13") or 0),
        row14=int(vals.get("row14") or 0),
        row30=int(vals.get("row30") or 0),
    )
    return {"seeded_baseline": for_date.isoformat(), **vals}


def _apply_lwd_answer(db: Session, message: str, item: dict,
                      report_date: date | None = None) -> dict:
    """从消息解析最后工作日并更新 oa_protocols / employee_resignations。

    澄清的 ref 字段存储了单号或流程单号，用于定位具体记录。
    """
    from sqlalchemy import select
    from app.models.inputs import EmployeeResignation, OAProtocol

    lwd_match = _DATE_RE.search(message)
    if not lwd_match:
        return {}

    from datetime import date as _date
    try:
        lwd = _date.fromisoformat(lwd_match.group())
    except ValueError:
        return {}

    ref = item.get("ref", "")
    updated = []

    # 尝试更新 OAProtocol（按单号）
    oa = db.scalar(select(OAProtocol).where(OAProtocol.order_no == ref))
    if oa:
        # 用户提供 LWD → 判断是否在本月 → 自动设置 row30_flag。
        # 「本月」以报告日为基准（口径：参考基准日=报告日，见架构文档 §3.3 实现约束），
        # 不用服务器当日——补跑历史日报时两者可能不同月。
        from datetime import date as today_cls
        base = report_date or today_cls.today()
        in_month = (lwd.year == base.year and lwd.month == base.month)
        oa.row30_flag = "是" if in_month else "否"
        oa.row5_flag = oa.row5_flag or "是"   # LWD 已知，确认为 Release
        db.commit()
        updated.append(f"oa_protocols[{ref}].row30_flag={'是' if in_month else '否'}, LWD={lwd}")

    # 尝试更新 EmployeeResignation（按流程单号）
    res = db.scalar(select(EmployeeResignation).where(EmployeeResignation.process_no == ref))
    if res:
        res.resign_date = lwd
        db.commit()
        updated.append(f"employee_resignations[{ref}].resign_date={lwd}")

    return {"lwd_applied": str(lwd), "records_updated": updated}


def _apply_inclusion_answer(db: Session, message: str, item: dict) -> dict:
    """处理"未知员工类型"澄清：用户指定是纳入还是排除该类型。

    unknown_types 存储在 options[0] 的 JSON 中（由 ingestion_service 写入），
    不在 detail 字段（detail 字段未持久化到 clarifications 表）。
    """
    import json as _json
    unknown_types: list[str] = []
    options = item.get("options") or []
    if options:
        try:
            parsed = _json.loads(options[0]) if isinstance(options[0], str) else options[0]
            unknown_types = parsed.get("unknown_types", [])
        except Exception as exc:
            # 之前这里是裸 except...pass：options[0] 解析失败时静默返回 {}，
            # 调用方收不到任何错误信号，这条澄清就永远处于"已答复但什么都
            # 没发生"的状态，且日志里完全看不出原因。现在记录清楚是哪条
            # 澄清记录（ref/code）解析失败、原始内容是什么，方便定位脏数据。
            log.warning(
                "澄清记录 options[0] 解析失败（ref=%s, code=%s）：%s；原始内容=%r",
                item.get("ref"), item.get("code"), exc, options[0],
            )
    if not unknown_types:
        if options:
            log.warning(
                "未知员工类型澄清缺少可用的 unknown_types（ref=%s），本次答复未产生任何变更",
                item.get("ref"),
            )
        return {}

    # 判断用户意图
    exclude = any(kw in message for kw in ("排除", "不纳入", "exclude", "剔除", "不计"))

    from app.repositories.config_repo import get_overrides, save_overrides
    from app.core.constants import INCLUDED_EMPLOYEE_TYPES, EXCLUDED_EMPLOYEE_TYPES
    overrides = get_overrides()

    if exclude:
        excl = set(overrides.get("exclusion_types") or list(EXCLUDED_EMPLOYEE_TYPES))
        excl.update(unknown_types)
        save_overrides({"exclusion_types": sorted(excl)})
        return {"added_to_exclusion": unknown_types}
    else:
        incl = set(overrides.get("inclusion_types") or list(INCLUDED_EMPLOYEE_TYPES))
        incl.update(unknown_types)
        save_overrides({"inclusion_types": sorted(incl)})
        return {"added_to_inclusion": unknown_types}


# ─────────────────────────────────────────────────────────────
# 状态摘要（无明确命令时）
# ─────────────────────────────────────────────────────────────

def _handle_status_query(db: Session, report_date: date, session_id: str) -> dict[str, Any]:
    """返回当前流水线状态摘要。"""
    counts = report_repo.count_inputs(db)
    pending = clarify_repo.list_pending(report_date, db=db)
    lines = [f"📅 报告日期：{report_date}"]
    for key, n in counts.items():
        status_icon = "✅" if n > 0 else "❌"
        lines.append(f"  {status_icon} {key}：{n} 行")
    if pending:
        lines.append(f"\n⚠️ 有 {len(pending)} 条待确认事项：")
        for p in pending[:3]:
            lines.append(f"  • [{p.get('code')}] {p.get('message', '')[:60]}…")
    else:
        lines.append("\n✅ 无待确认事项，可发送「生成」触发日报。")
    return {
        "message": "\n".join(lines),
        "action": "info",
        "status": "info",
        "payload": {"counts": counts, "pending_clarifications": len(pending)},
    }


# ─────────────────────────────────────────────────────────────
# 报表查询（"我要 6/22 的日报"）
# ─────────────────────────────────────────────────────────────

def _handle_report_request(
    db: Session, eff_date: date, message: str, session_id: str
) -> dict[str, Any]:
    """查找指定日期的日报/周报：已生成 → 返回 KPI 摘要 + 文件路径；未生成 → 引导生成。"""
    from app.services import archive_service, view_service

    if "周报" in message:
        weeks = report_repo.list_weeks(db, limit=30)
        hit = next(
            (w for w in weeks if w["week_start"] <= eff_date.isoformat() <= w["week_end"]),
            None,
        )
        if hit:
            we = hit["week_end"]
            paths = archive_service.find_export_paths(date.fromisoformat(we), ["weekly"])
            lines = [f"✅ 周报（{hit['week_start']} ~ {we}）已生成。"]
            if paths.get("weekly"):
                lines.append(f"📈 文件：{paths['weekly']}")
            lines.append("可在「周报」页选择该周次查看 Sheet1 / Sheet2 明细。")
            return {"message": "\n".join(lines), "action": "report_info",
                    "status": "info", "payload": {"weekly": hit}}
        return {
            "message": (
                f"📭 {eff_date} 所在周的周报尚未生成。\n"
                f"发送「生成 {eff_date} 日报」，若该日为本周最后工作日会自动一并生成周报；"
                "或直接调用周报生成。"
            ),
            "action": "report_info", "status": "info",
            "payload": {"weekly": None, "date": eff_date.isoformat()},
        }

    # 日报
    generated = {d["report_date"] for d in report_repo.list_daily_dates(db, limit=120)}
    if eff_date.isoformat() in generated:
        lines = [f"✅ {eff_date} 日报已生成。"]
        try:
            view = view_service.daily_view(db, eff_date)
            k = view.get("kpis", {})
            lines.append(
                f"  今日入职 {k.get('row2_今日入职')} · 今日离职 {k.get('row3_今日离职')}"
                f" · 今日净增 {k.get('row7_今日净增')} · MTD净增 {k.get('row12_MTD净增')}"
            )
            if view.get("export_path"):
                lines.append(f"📊 文件：{view['export_path']}")
            if view.get("calc_log_path"):
                lines.append(f"📋 计算日志：{view['calc_log_path']}")
        except Exception as exc:
            log.info("日报摘要重算失败（不影响查询）：%s", exc)
        lines.append("可在「日报」页选择该日期查看完整 Row2–40、在岗时长与校验。")
        return {"message": "\n".join(lines), "action": "report_info",
                "status": "info", "payload": {"date": eff_date.isoformat(), "exists": True}}

    return {
        "message": (
            f"📭 {eff_date} 的日报尚未生成。\n"
            f"发送「生成 {eff_date} 日报」即可生成（MTD/YTD 将以上一工作日日报为基线链式计算）。"
        ),
        "action": "report_info", "status": "info",
        "payload": {"date": eff_date.isoformat(), "exists": False},
    }


# ─────────────────────────────────────────────────────────────
# 校验差异明细（"查看差异明细"）
# ─────────────────────────────────────────────────────────────

def _handle_diff_detail(db: Session, eff_date: date, session_id: str) -> dict[str, Any]:
    """展示 12 项发布前校验的明细：每项的左右值/差异数据，失败项排前。"""
    from app.services import view_service

    view = None
    used_date = eff_date
    try:
        view = view_service.daily_view(db, eff_date)
    except Exception:
        try:
            dates = report_repo.list_daily_dates(db, limit=1)
            if dates:
                used_date = date.fromisoformat(dates[0]["report_date"])
                view = view_service.daily_view(db, used_date)
        except Exception as exc:
            log.info("差异明细回退失败: %s", exc)

    if view is None:
        return {
            "message": "📭 库内暂无可核对的数据（还没有可重算的日报）。上传输入并生成日报后即可查看差异明细。",
            "action": "diff_detail", "status": "info", "payload": {"available": False},
        }

    vals = view.get("validations", [])
    failed = [v for v in vals if not v.get("passed")]
    passed = [v for v in vals if v.get("passed")]
    lines = [f"🔍 {used_date} 校验差异明细（{len(passed)}/{len(vals)} 通过）："]

    def fmt(v):
        mark = "✗" if not v.get("passed") else "✓"
        hard = " ★" if v.get("hard_block") else ""
        detail = {k: x for k, x in v.items()
                  if k not in {"check", "passed", "hard_block"} and x is not None}
        dtxt = ("　" + "；".join(f"{k}={x}" for k, x in detail.items())) if detail else ""
        return f"  {mark} {v.get('check')}{hard}{dtxt}"

    lines += [fmt(v) for v in failed] + [fmt(v) for v in passed]
    if failed:
        lines.append("\n★ 为硬阻断项：不通过则报表不交付。请核对上方左右值定位差异来源。")
    else:
        lines.append("\n全部校验通过，无差异。")
    return {
        "message": "\n".join(lines),
        "action": "diff_detail", "status": "info",
        "payload": {"report_date": used_date.isoformat(),
                    "failed": len(failed), "total": len(vals)},
    }


# ─────────────────────────────────────────────────────────────
# 计算逻辑说明（展示计算日志）
# ─────────────────────────────────────────────────────────────

# 无库内数据可重算时的公式链兜底说明（与 validators.run_daily_checks 一致）
_FORMULA_OVERVIEW = (
    "🧮 日报公式链（发布前逐条硬校验）：\n"
    "  Row7 = Row2 − Row3（今日净增 = 今日入职 − 今日离职）\n"
    "  Row6 = Row4 + Row5\n"
    "  Row12 = Row8 − Row9 − Row10 + Row11（MTD 净增）\n"
    "  Row17 = Row13 − Row14 − Row15 + Row16（YTD 净增）\n"
    "  Row22 = Row18 − Row19 − Row20 + Row21\n"
    "  Row33 = Row30 + Row31 + Row32；Row19 = Row33\n"
    "  Row40 = Row37 + Row38 + Row39；Row18 = Row40；Row37 = Row8\n"
    "  在岗时长 B10 = Sheet1 Row14\n\n"
    "MTD/YTD 为链式累计：今日累计 = 昨日日报累计 + 今日事实。"
    "所有数字均来自输入表的确定性计算，不由模型产生。\n"
    "生成日报后，「计算日志」页可逐行查看取数、公式、中间值与校验。"
)

# item 关键词 → 用于把自然语言问题定位到具体行
_CALC_KEYWORDS = ("入职", "离职", "净增", "转正", "预估", "预计", "释放", "release",
                  "协议", "mtd", "ytd", "在岗", "离职率", "offer", "招聘")


def _handle_calc_explain(
    db: Session, report_date: date, message: str, session_id: str
) -> dict[str, Any]:
    """回答"怎么计算的"：从只读重算结果提取逐行公式 / 取数来源 / trace。

    行定位优先级：显式 RowN 引用 > item 关键词匹配 > 全部派生公式行。
    库内无法重算（如无数据）时回退到静态公式链说明。
    """
    from app.services import view_service

    view = None
    used_date = report_date
    try:
        view = view_service.daily_view(db, report_date)
    except Exception:
        # 当前报告日无法重算（缺数据/缺基线）→ 回退最近一次已生成的日报
        try:
            dates = report_repo.list_daily_dates(db, limit=1)
            if dates:
                used_date = date.fromisoformat(dates[0]["report_date"])
                view = view_service.daily_view(db, used_date)
        except Exception as exc:
            log.info("计算说明回退失败，使用静态公式链: %s", exc)

    if view is None:
        return {
            "message": _FORMULA_OVERVIEW,
            "action": "calc_explain",
            "status": "info",
            "payload": {"source": "formula_overview"},
        }

    rows = [r for r in view.get("rows", [])
            if not r.get("is_blank") and not r.get("is_header")]

    # 1) 显式 RowN 引用
    wanted = {int(n) for n in _ROW_REF_RE.findall(message)}
    selected = [r for r in rows if r["row"] in wanted]
    # 2) item 关键词匹配（如"离职怎么计算的"→ 含"离职"的行）
    if not selected:
        msg_l = message.lower()
        kws = [k for k in _CALC_KEYWORDS if k in msg_l]
        if kws:
            selected = [r for r in rows
                        if r.get("item") and any(k in str(r["item"]).lower() for k in kws)]
    # 3) 默认：全部派生公式行（公式链主干）
    if not selected:
        selected = [r for r in rows if r.get("derived")]
    selected = selected[:10]

    lines = [f"🧮 {used_date} 日报计算说明（库内数据确定性重算，非模型生成）："]
    for r in selected:
        lines.append(f"\n▸ Row{r['row']} · {r.get('item') or ''}")
        base = r.get("baseline")
        lines.append(f"   当前值 = {r.get('value')}"
                     + (f"（基线 {base}）" if base is not None else ""))
        if r.get("formula"):
            lines.append(f"   公式：{r['formula']}")
        if r.get("source"):
            lines.append(f"   来源：{r['source']}")
        trace = r.get("trace") or {}
        extra = {k: v for k, v in trace.items()
                 if k not in {"formula", "source"} and v not in (None, "", [])}
        if extra:
            kv = "；".join(f"{k}={v}" for k, v in list(extra.items())[:4])
            lines.append(f"   trace：{kv}")

    if view.get("calc_log_path"):
        lines.append(f"\n📋 完整逐行 trace 见「计算日志」页；文件：{view['calc_log_path']}")
    else:
        lines.append("\n📋 完整逐行 trace 见「计算日志」页（生成日报后自动产出 md 文件）")

    return {
        "message": "\n".join(lines),
        "action": "calc_explain",
        "status": "info",
        "payload": {
            "report_date": used_date.isoformat(),
            "rows": [r["row"] for r in selected],
            "calc_log_path": view.get("calc_log_path"),
        },
    }


# ─────────────────────────────────────────────────────────────
# 名单 / 人数查询（"在职人员名单"、"现在多少人在职"）——确定性，无需 LLM
# ─────────────────────────────────────────────────────────────

def _fetch_employees_roster(db: Session, resigned: bool, as_of: date) -> list:
    """按截止日从 employees 表取在职/离职人员（≤500 条，按事业部+姓名排序）。"""
    from sqlalchemy import or_, select
    from app.models.inputs import Employee

    q = select(Employee)
    if hasattr(Employee, "is_deleted"):
        q = q.where(Employee.is_deleted == 0)
    if resigned:
        q = q.where(Employee.resign_date.is_not(None), Employee.resign_date <= as_of)
    else:
        # 在职判定与周报口径一致：离职日期为空或晚于截止日
        q = q.where(or_(Employee.resign_date.is_(None), Employee.resign_date > as_of))
    return list(db.scalars(q.order_by(Employee.bu, Employee.name).limit(500)).all())


def _handle_roster(
    db: Session, eff_date: date, message: str, session_id: str
) -> dict[str, Any]:
    """在职/离职 名单或人数：直接查库、按事业部分组呈现，数字不经过任何模型。"""
    resigned = "离职" in message and "在职" not in message
    label = "离职" if resigned else "在职"
    try:
        emps = _fetch_employees_roster(db, resigned, eff_date)
    except Exception as exc:
        log.warning("名单查询失败: %s", exc)
        return _handle_status_query(db, eff_date, session_id)

    total = len(emps)
    payload = {"kind": label, "as_of": eff_date.isoformat(), "count": total}

    # 只问人数、没要名单 → 只报数
    if not _ROSTER_RE.search(message):
        return {
            "message": f"📊 截至 {eff_date}，{label}人员共 {total} 人"
                       f"（employees 表确定性统计，口径：离职日期{'非空且≤截止日' if resigned else '为空或>截止日'}）。",
            "action": "data_lookup", "status": "info", "payload": payload,
        }

    # 同名同事用工号区分显示，避免看起来像重复数据
    name_count: dict[str, int] = {}
    for e in emps:
        name_count[e.name] = name_count.get(e.name, 0) + 1

    def disp(e) -> str:
        if name_count.get(e.name, 0) > 1 and getattr(e, "employee_no", None):
            return f"{e.name}({e.employee_no})"
        return e.name

    by_bu: dict[str, list[str]] = {}
    for e in emps:
        by_bu.setdefault(getattr(e, "bu", None) or "未分组", []).append(disp(e))
    lines = [f"📋 {label}人员名单（截至 {eff_date}，共 {total} 人；同名者已标注工号）："]
    for bu, names in sorted(by_bu.items()):
        lines.append(f"  ▸ {bu}（{len(names)} 人）：{'、'.join(names)}")
    if total >= 500:
        lines.append("  …已达 500 条显示上限，完整数据请查人员表。")
    if total == 0:
        lines.append("  （无匹配记录）")
    return {"message": "\n".join(lines), "action": "data_lookup",
            "status": "info", "payload": payload}


# ─────────────────────────────────────────────────────────────
# 人员查询（"测试员工甲哪天离职的"）——确定性 DB 查找，无需 LLM
# ─────────────────────────────────────────────────────────────

_PERSON_Q_RE = re.compile(r"哪天|什么时候|何时|离职|入职|在职|走了|last\s*work", re.IGNORECASE)
_CJK_RUN_RE = re.compile(r"[一-龥]{2,}")
# 从中文串里剔除的疑问/业务词，剩下的 2~4 字片段视为候选姓名
_NAME_STOPWORDS = (
    "什么时候", "告诉我", "查一下", "帮我查", "我想知道", "哪一天", "是不是",
    "哪天", "何时", "时候", "什么", "离职", "入职", "在职", "时间", "日期",
    "员工", "请问", "一下", "帮我", "查询", "查查", "知道", "谁是", "是谁",
    "走了", "没有", "还在", "公司", "日报", "周报", "名单", "人员", "现在",
    "的", "是", "了", "吗", "呢", "啊", "哪", "谁", "查", "在", "有", "没",
)


def _extract_person_candidates(message: str) -> list[str]:
    cands: list[str] = []
    for run in _CJK_RUN_RE.findall(message):
        rem = run
        for w in sorted(_NAME_STOPWORDS, key=len, reverse=True):
            rem = rem.replace(w, "|")
        for tok in rem.split("|"):
            if 2 <= len(tok) <= 4 and tok not in cands:
                cands.append(tok)
    return cands


def _search_employees(db: Session, name_like: str) -> list:
    from sqlalchemy import select
    from app.models.inputs import Employee

    rows = db.scalars(
        select(Employee).where(Employee.name == name_like).limit(5)).all()
    if not rows:
        rows = db.scalars(
            select(Employee).where(Employee.name.like(f"%{name_like}%")).limit(5)).all()
    return list(rows)


def _search_resignations(db: Session, employee_no: str) -> list:
    from sqlalchemy import select
    from app.models.inputs import EmployeeResignation

    return list(db.scalars(
        select(EmployeeResignation)
        .where(EmployeeResignation.employee_no == employee_no).limit(5)).all())


def _person_lookup(db: Session, message: str) -> str | None:
    """按消息中的姓名候选查 employees / employee_resignations，命中则组装答案。"""
    for cand in _extract_person_candidates(message):
        emps = _search_employees(db, cand)
        if not emps:
            continue
        lines = []
        for e in emps[:3]:
            head = f"👤 {e.name}（{e.employee_no}"
            if getattr(e, "employee_type", None):
                head += f" · {e.employee_type}"
            if getattr(e, "bu", None):
                head += f" · {e.bu}"
            lines.append(head + "）")
            if getattr(e, "entry_date", None):
                lines.append(f"   入职：{e.entry_date}")
            if getattr(e, "resign_date", None):
                lines.append(f"   离职：{e.resign_date}"
                             + (f"（{e.release_type}）" if getattr(e, "release_type", None) else ""))
            else:
                lines.append("   离职：—（当前在职，离职日期为空）")
            for r in _search_resignations(db, e.employee_no):
                seg = [str(r.resign_date) if getattr(r, "resign_date", None) else "LWD 待定"]
                if getattr(r, "resign_type", None):
                    seg.append(r.resign_type)
                if getattr(r, "process_status", None):
                    seg.append(r.process_status)
                lines.append(f"   离职流程：{' · '.join(seg)}（单号 {r.process_no}）")
        if len(emps) > 3:
            lines.append(f"   …共匹配 {len(emps)} 人，仅显示前 3 条")
        lines.append("（数据来自库内 employees / employee_resignations 表）")
        return "\n".join(lines)
    return None


# ─────────────────────────────────────────────────────────────
# 口径/操作 FAQ（确定性知识库，来源 docs/skills 口径字典 Q1–Q16 等）
# ─────────────────────────────────────────────────────────────

# (关键词元组【任一命中】, 答案)。按特异性排序，先匹配先答。
_FAQ: list[tuple[tuple[str, ...], str]] = [
    (("转正",),
     "📖 转正（Row10/15）：口径字典 Q1 —— 暂不涉及，默认填 0。"),
    (("微软", "项目调整"),
     "📖 微软项目调整（Row11/16）：口径字典 Q2 —— 暂不涉及，默认填 0。"),
    (("lwd", "最后工作日"),
     "📖 LWD（最后工作日）缺失：口径字典 Q5 —— 该 OA 单只计入 Row5（今日提出 release），"
     "不计入 Row30（Release 截至月底）。在对话中补充 LWD 日期后，系统自动回填并重算。"),
    (("截图", "图片", "照片", "ocr", "扫描"),
     "📖 截图输入：口径字典 Q6 —— 四类输入均支持截图识别（视觉 LLM，需配置 LLM_VISION_* "
     "环境变量），Excel 优先、冲突以 Excel 为准；人员表与离职表用截图时需人工确认后才参与计算。"
     "未配置视觉 LLM 时请改传 .xlsx。在工作台直接拖入 PNG/JPG 即可。"),
    (("招聘", "合计", "逐行"),
     "📖 招聘取数（Row38/39）：口径字典 Q7 —— 优先取合计行，同时逐行求和校验；不一致硬阻断；"
     "请修正招聘表合计行或明细行后重新上传。"),
    (("拒绝", "驳回"),
     "📖 经理拒绝/流程驳回：口径字典 Q10 —— Row4 不回写、Row31 剔除该记录。"),
    (("重复计", "去重", "算两次", "重复统计"),
     "📖 主动/被动去重：口径字典 Q3 —— 主动离职（Row4）与被动 Release（Row5）"
     "不会重复，无需跨源去重；Row4 按流程单号、Row5/Row30 按 OA 单号各自去重。"),
    (("离职方式", "协商一致", "主动离职", "被动离职", "离职表和oa", "关联"),
     "📖 离职方式口径：口径字典 Q4/Q8 —— 离职方式∈{主动, 被动, 协商一致}，"
     "主动→Row4，被动/协商一致→按被动处理；离职报表主要用于判断被动 Release，OA 为主链路。"),
    (("员工状态", "状态矛盾", "在职状态"),
     "📖 员工状态：口径字典 Q9 —— 以入/离职日期事实为主，员工状态字段仅作交叉校验，"
     "两者矛盾时阻断并请人工确认。"),
    (("转签", "外派"),
     "📖 转签/外派：口径字典 Q11 —— 当前暂不涉及自动排重，仅识别留痕。"),
    (("境外",),
     "📖 境外主体（Row25/26）：口径字典 Q13 —— 当前暂不涉及，保持 0。"),
    (("实习",),
     "📖 实习生：口径字典 Q12 —— 周报中长期/短期实习合并为「实习生」列统计。"),
    (("节假", "假期", "放假", "调休"),
     "📖 节假日：口径字典 Q14 —— 周报在节假日前最后一个工作日随日报自动生成。"),
    (("周报填", "填人数", "填姓名"),
     "📖 周报入/离职列：口径字典 Q15 —— 填人数计数，不填姓名名单。"),
    (("前三", "top3", "项目排序"),
     "📖 前三大项目：口径字典 Q16 —— 按在职人数降序，平手按项目名字母序。"),
    (("空白行",),
     "📖 空白行：Row23/24/27/28/34/35 不填、不计、不入库（模板保持空白）。"),
    (("硬校验", "阻断", "校验规则", "校验有哪些"),
     "📖 发布前校验：9 项公式链硬校验（如 Row7=Row2−Row3、Row12=Row8−9−10+11、"
     "Row33=Row30+31+32、Row18=Row40）+ 在岗时长 B10=Sheet1 Row14 ★ + 招聘取数一致等软校验。"
     "任一硬阻断失败即停止交付。发送「查看差异明细」可看每项左右值。"),
    (("基线", "链式"),
     "📖 链式基线：MTD/YTD = 昨日已验收日报累计 + 今日事实（Row8/9/13/14/30）。"
     "历史日报缺失会发起澄清，回复五个基线数值（或「自动重算」）即可继续。"),
    (("怎么上传", "如何上传", "上传方法", "怎么导入"),
     "📖 上传：在工作台把四类文件（人员表/离职报表/OA 协议/招聘数据）一起拖入即可，"
     "按文件名自动识别归类入库；支持 xlsx/xls 与截图。"),
    (("怎么下载", "如何下载", "怎么导出", "如何导出"),
     "📖 下载：日报/周报页右上「导出 Excel」；「归档」页可按日期下载全部产物（含计算日志）。"),
    (("在职判定", "在职口径", "算在职", "判定标准"),
     "📖 在职判定：离职日期为空，或离职日期晚于截止日（与周报口径一致）。"),
    (("数字", "编造", "幻觉", "可信"),
     "📖 数字可信度：所有报表数字均来自输入表的确定性计算与数据库查询，"
     "任何数字都不由大模型产生；每行可在「计算日志」页追溯公式与取数来源。"),
]


def _match_faq(message: str) -> str | None:
    msg = message.lower()
    for keywords, answer in _FAQ:
        if any(k in msg for k in keywords):
            return answer
    return None


def _capability_menu(llm_enabled: bool) -> str:
    lines = [
        "🤔 这个问题我暂时没有把握直接回答。我目前能帮你：",
        "  • 生成报表：「生成日报」「生成 6/22 日报」",
        "  • 查报表/文件：「我要 6/22 的日报」「周报在哪」",
        "  • 计算逻辑：「Row30 怎么计算的」「查看差异明细」「怎么计算的」",
        "  • 数据查询：「在职人员名单」「现在多少人在职」「测试员工甲哪天离职的」",
        "  • 口径规则：「实习生怎么统计」「LWD 缺失怎么处理」「硬校验有哪些」",
        "  • 状态：「当前状态」",
    ]
    if not llm_enabled:
        lines.append("（配置 LLM_API_KEY 环境变量后，我还能自由问答并按任意条件查数据库）")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 自由问答（智能助手）
# ─────────────────────────────────────────────────────────────

_DEFAULT_CHAT_PROMPT = """你是「人事报表智能体」的对话助手，帮助 HR 用户使用本系统并回答相关问题。

系统能力（用户在工作台对话框即可完成）：
- 上传四类输入：人员表 / 离职报表 / OA 协议签署 / 招聘数据（xlsx 或截图）
- 发送「生成」触发日报（本周最后工作日自动附带周报与计算日志）
- 待确认澄清直接在对话中回复（如基线数值、最后工作日 LWD、未知员工类型的纳入/排除）
- 日报/周报/计算日志/归档/口径与设置 页面可查看结果

回答规则：
1. 用简体中文，简明扼要，可用少量 emoji。
2. CONTEXT 中提供了当前库内数据行数、待澄清事项、已生成报表等真实状态；
   涉及数字时【只能引用 CONTEXT 或 ROWS 中出现的数字，绝不编造】。
3. 若提供了 ROWS（数据库只读查询结果），基于它回答数据问题，并注明数据来自库内查询。
4. 问题超出系统范围时如实说明，并引导用户使用上述能力。
5. 严格输出 JSON：{"answer": "<你的回答文本>"}
"""

# NL->SQL 的表结构提示——静态兜底（列名对齐 app/models/inputs.py、reports.py，
# 表范围须在 sql_guard._ALLOWED_TABLES 白名单内）。优先使用 _db_schema_hint()
# 从数据库/模型元数据实时获取。
_SCHEMA_HINT = (
    "employees(employee_no, name, employee_type, status, department, bu, "
    "project_code, entry_date, resign_date, release_type), "
    "employee_resignations(process_no, employee_no, process_status, resign_date, "
    "resign_type, first_visible_date), "
    "oa_protocols(order_no, task_no, related_employee, related_name, current_status, "
    "process_type, row5_flag, row30_flag, first_visible_date), "
    "recruitment_pipeline(report_date, month_offers, onboard_m, expected_onboard_m, "
    "expected_onboard_m_prev), "
    "daily_reports(report_date, daily_onboard, daily_resign, daily_employee_change, "
    "mtd_onboard, mtd_resign, ytd_onboard, ytd_resign, release_cum), "
    "weekly_reports(week_start, week_end), projects(project_code, project_name)"
)


_schema_hint_cache: str | None = None


def _db_schema_hint(db: Session) -> str:
    """获取数据库真实 schema 供 NL->SQL 使用（仅白名单表）。

    优先级：① 连接库 inspector 实时反射（列名+类型）
            ② SQLAlchemy 模型元数据（无需连库）
            ③ 静态 _SCHEMA_HINT 兜底
    结果缓存（表结构在运行期不变）。
    """
    global _schema_hint_cache
    if _schema_hint_cache:
        return _schema_hint_cache

    from app.llm.sql_guard import _ALLOWED_TABLES

    # ① 数据库实时反射
    try:
        from sqlalchemy import inspect as sa_inspect

        insp = sa_inspect(db.get_bind())
        parts = []
        for t in sorted(_ALLOWED_TABLES):
            try:
                cols = insp.get_columns(t)
            except Exception:
                continue
            if cols:
                parts.append(
                    f"{t}(" + ", ".join(f"{c['name']} {c['type']}" for c in cols) + ")")
        if parts:
            _schema_hint_cache = "; ".join(parts)
            return _schema_hint_cache
    except Exception as exc:
        log.info("DB schema 反射失败，回退模型元数据: %s", exc)

    # ② 模型元数据（不需要活跃连接）
    try:
        import app.models  # noqa: F401  确保模型注册到 Base.metadata
        from app.core.database import Base

        parts = []
        for t, table in sorted(Base.metadata.tables.items()):
            if t not in _ALLOWED_TABLES:
                continue
            parts.append(
                f"{t}(" + ", ".join(f"{c.name} {c.type}" for c in table.columns) + ")")
        if parts:
            _schema_hint_cache = "; ".join(parts)
            return _schema_hint_cache
    except Exception as exc:
        log.info("模型元数据获取失败，使用静态 schema: %s", exc)

    return _SCHEMA_HINT


def _format_rows_answer(sql: str, rows: list[dict], row_count: int,
                        max_show: int = 10) -> str:
    """LLM 组稿不可用时的确定性结果呈现：直接列出查询行。"""
    lines = [f"🔎 库内查询结果（共 {row_count} 行；SQL 已过只读安全校验）："]
    for r in rows[:max_show]:
        lines.append("  • " + " · ".join(f"{k}={v}" for k, v in r.items()))
    if row_count > max_show:
        lines.append(f"  …仅显示前 {max_show} 行")
    if row_count == 0:
        lines.append("  （无匹配记录）")
    lines.append(f"SQL：{sql}")
    return "\n".join(lines)


def _build_chat_context(db: Session, report_date: date) -> dict[str, Any]:
    """收集库内真实状态，注入 LLM 上下文（模型只引用、不产生数字）。"""
    counts = report_repo.count_inputs(db)
    pending = clarify_repo.list_pending(report_date, db=db)
    daily_dates = report_repo.list_daily_dates(db, limit=5)
    weeks = report_repo.list_weeks(db, limit=3)
    return {
        "report_date": report_date.isoformat(),
        "input_row_counts": counts,
        "pending_clarifications": [
            {"code": p.get("code"), "message": p.get("message")} for p in pending[:5]
        ],
        "generated_daily_reports": daily_dates,
        "generated_weekly_reports": weeks,
    }


def _handle_free_chat(
    db: Session, report_date: date, message: str, session_id: str
) -> dict[str, Any]:
    """自由文本 → LLM 智能问答；LLM 未配置/失败时回退状态摘要。

    数据类问题先尝试 NL->SQL 只读查询（经 sql_guard 校验），把真实查询结果
    交给 LLM 组织回答——数字永远来自数据库，模型只负责表述。
    """
    from app.llm.llm_client import get_llm_client
    from app.llm.skill_loader import load_skill

    # 人员查询（"测试员工甲哪天离职的"）：确定性 DB 查找，命中即答，无需 LLM
    if _PERSON_Q_RE.search(message):
        try:
            person_answer = _person_lookup(db, message)
            if person_answer:
                return {"message": person_answer, "action": "data_lookup",
                        "status": "info", "payload": {"source": "employees"}}
        except Exception as exc:
            log.info("人员查询失败，继续走 LLM/状态摘要: %s", exc)

    # 口径/操作 FAQ：确定性知识库（docs/skills 口径字典），无需 LLM
    faq = _match_faq(message)
    if faq:
        return {"message": faq, "action": "faq", "status": "info",
                "payload": {"source": "qa_dictionary"}}

    client = get_llm_client()
    if not client.enabled:
        # 无 LLM：给能力清单而非状态墙，引导用户用可用的确定性命令
        return {"message": _capability_menu(False), "action": "info",
                "status": "info", "payload": {"llm": False}}

    # 数据类问题：Agent 取库内真实 schema → LLM 生成只读 SQL（过安全校验）→ 执行
    query_note = ""
    query_result: dict[str, Any] | None = None
    query_payload: dict[str, Any] | None = None
    if _DATA_Q_RE.search(message):
        try:
            from app.services import query_service

            q = query_service.answer(
                db, message, schema_hint=_db_schema_hint(db), max_rows=50)
            preview = json.dumps(q["rows"][:20], ensure_ascii=False, default=str)
            query_note = f"\nSQL={q['sql']}\nROW_COUNT={q['row_count']}\nROWS={preview}"
            query_result = q
            query_payload = {"sql": q["sql"], "row_count": q["row_count"]}
        except Exception as exc:
            # LLM 未配置 propose_sql 提示词 / SQL 未过安全校验 / 查询失败 → 纯问答
            log.info("NL->SQL 查询不可用，回退纯问答: %s", exc)

    prompt = load_skill("chat_assistant") or _DEFAULT_CHAT_PROMPT
    context = _build_chat_context(db, report_date)
    user_content = (
        f"CONTEXT={json.dumps(context, ensure_ascii=False, default=str)}"
        f"{query_note}\n\nQUESTION={message}"
    )
    try:
        out = client.json_chat(prompt, user_content, max_tokens=1024)
        answer = str(out.get("answer") or "").strip()
        if answer:
            return {
                "message": answer,
                "action": "chat",
                "status": "info",
                "payload": {"llm": True, **({"query": query_payload} if query_payload else {})},
            }
        log.warning("chat LLM 返回空 answer，回退")
    except Exception as exc:
        log.warning("chat LLM 调用失败，回退: %s", exc)

    # SQL 查询成功但 LLM 组稿失败 → 确定性呈现查询结果（数字仍全部来自数据库）
    if query_result is not None:
        return {
            "message": _format_rows_answer(
                query_result["sql"], query_result["rows"], query_result["row_count"]),
            "action": "data_lookup",
            "status": "info",
            "payload": {"llm": False, "query": query_payload},
        }

    return {"message": _capability_menu(True), "action": "info",
            "status": "info", "payload": {"llm": True}}
