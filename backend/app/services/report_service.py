"""报表编排：运行计算 Agent -> 写库 -> 导出文件。
处理澄清（停下提问）与硬阻断校验失败。任务状态存于 Redis（job_repo）。"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.agents.calculation_agent import CalculationAgent
from app.config import settings
from app.core.exceptions import BaselineMissingError, HRAgentError
from app.core.logging import get_logger
from app.models.jobs import JobKind, JobStatus
from app.models.reports import DailyReport
from app.pipeline.calculation import validators
from app.pipeline.export import calc_log_exporter, daily_exporter, weekly_exporter
from app.repositories import clarify_repo, job_repo, report_repo
from app.services import month_opening_service
from app.utils import calendar_utils as cal

log = get_logger("service.report")
_agent = CalculationAgent()

# 澄清问题中用户回答应包含的基线字段
_BASELINE_FIELDS = ("row8", "row9", "row13", "row14", "row30")


def _try_consume_baseline_answer(db: Session, report_date: date) -> bool:
    """检查是否已有用户回答了 baseline_missing 澄清；若有，将其注入基线行后返回 True。

    用户回答格式（JSON 字符串）：
      {"for_date": "2026-06-29", "row8": 50, "row9": 5, "row13": 100, "row14": 20, "row30": 3}
    for_date 可选；若缺省则以 report_date 前一自然日作为基线日期。
    """
    answered = [
        item for item in clarify_repo.list_all(report_date, db=db)
        if item.get("code") == "baseline_missing" and item.get("status") == "answered"
    ]
    if not answered:
        return False

    def _sort_key(item):
        val = item.get("answered_at") or "0"
        try:
            return float(val)          # Redis path: epoch float string
        except ValueError:
            from datetime import datetime
            try:
                return datetime.fromisoformat(val).timestamp()  # MySQL path: ISO string
            except ValueError:
                return 0.0

    latest = sorted(answered, key=_sort_key)[-1]
    raw = latest.get("answer", "").strip()
    if not raw:
        return False

    if _wants_auto_baseline(raw):
        vals = {}
    else:
        try:
            vals = json.loads(raw)
        except json.JSONDecodeError:
            # 非 JSON 答复：先尝试提取五个数字（row8 row9 row13 row14 row30 顺序）；
            # 提取不到（如「都是0」「全0」）→ vals={}，交给 resolve_baseline_values
            # 全量重算。之前直接 return False 会让该答复永远无法被消费，
            # 每次生成都重新发起 baseline_missing —— 死循环。
            import re as _re
            nums = _re.findall(r"\d+", raw)
            if len(nums) >= 5:
                keys = ["row8", "row9", "row13", "row14", "row30"]
                vals = {k: int(n) for k, n in zip(keys, nums[:5])}
            else:
                log.warning(
                    "baseline_missing 答复无法解析为 JSON/数值，按库内数据全量重算")
                vals = {}

    if not isinstance(vals, dict):
        log.warning(
            "baseline_missing 澄清答复不是 JSON 对象（类型=%s）",
            type(vals).__name__,
        )
        return False

    # for_date：用户指定的基线日期，默认为报告日前一自然日
    from datetime import timedelta
    for_date_str = vals.get("for_date")
    if for_date_str:
        try:
            from datetime import date as _date
            for_date = _date.fromisoformat(str(for_date_str))
        except ValueError:
            for_date = report_date - timedelta(days=1)
    else:
        for_date = report_date - timedelta(days=1)

    if for_date >= report_date:
        # 基线必须早于报告日（get_baseline_rows 用严格 <）；注入到报告日
        # 当天/之后的行永远取不到，会陷入 baseline_missing 死循环
        log.warning("基线 for_date=%s 不早于报告日 %s，已改按前一自然日注入",
                    for_date, report_date)
        for_date = report_date - timedelta(days=1)

    vals = resolve_baseline_values(db, for_date, vals)
    seed_baseline(
        db,
        for_date=for_date,
        row8=int(vals.get("row8") or 0),
        row9=int(vals.get("row9") or 0),
        row13=int(vals.get("row13") or 0),
        row14=int(vals.get("row14") or 0),
        row30=int(vals.get("row30") or 0),
    )
    log.info("已从澄清答复注入基线 for_date=%s", for_date)
    return True


def _wants_auto_baseline(message: str) -> bool:
    """答复是否要求系统按库内数据自动重算基线。"""
    import re
    return bool(re.search(r"自动|重算|auto|recompute", message, re.I))


def resolve_baseline_values(db: Session, for_date: date, vals: dict) -> dict:
    """确定最终注入的基线值。

    用户提供了非全 0 的数值 → 尊重用户提供的值；
    未提供数值或全为 0 → 按库内数据全量重算（recompute_chain_baseline）。

    全 0 视为"未知"而非事实：库内已有历史离职时注入全 0 基线，
    Row14 链式值将永远追不上在岗时长 B10 的全量重算值，硬校验
    「在岗时长 B10 = Sheet1 Row14」必然阻断、报表反复被拦。
    若库确实为空，重算结果同样是全 0，语义不受影响。
    """
    provided = {k: int(vals.get(k) or 0) for k in _BASELINE_FIELDS}
    if any(provided.values()):
        return {**vals, **provided}
    from app.pipeline.calculation.daily import recompute_chain_baseline
    computed = recompute_chain_baseline(db, for_date)
    log.info("基线答复缺省/全0，已按库内数据全量重算 for_date=%s", for_date)
    return {**vals, **computed, "auto_recomputed": True}


def seed_baseline(
    db: Session,
    for_date: date,
    row8: int = 0,
    row9: int = 0,
    row13: int = 0,
    row14: int = 0,
    row30: int = 0,
) -> dict:
    """手动注入链式基线。

    在 daily_reports 中以 for_date 创建（或覆盖）一行，
    使后续 report_date=for_date+1 的日报能正常完成 MTD/YTD 链式顺推。
    """
    obj = db.scalar(select(DailyReport).where(DailyReport.report_date == for_date))
    if obj is None:
        obj = DailyReport(report_date=for_date)
        db.add(obj)
    # 只写入链式基线字段，不触碰其他字段
    obj.mtd_onboard = row8
    obj.mtd_resign = row9
    obj.ytd_onboard = row13
    obj.ytd_resign = row14
    obj.release_cum = row30
    # 没有真实计算，其余字段保持 0（或已有值）
    db.commit()
    log.info("基线已注入 for_date=%s", for_date)
    return {"for_date": for_date.isoformat(), "row8": row8, "row9": row9,
            "row13": row13, "row14": row14, "row30": row30}


_SOURCE_LABELS = {"employees": "人员表", "resignations": "离职人员报表",
                  "agreements": "协议签署/OA", "recruitment": "招聘数据"}


def _weekly_blocked_payload(weekly_ctx: dict) -> dict:
    """周报阻断只描述周报状态，不覆盖已经成功的日报状态。"""
    hard = weekly_ctx.get("hard_failures") or validators.hard_failures(
        weekly_ctx.get("validations", [])
    )
    return {
        "weekly_status": "blocked",
        "weekly_validations": weekly_ctx.get("validations", []),
        "weekly_hard_failures": hard,
        "warnings": ["日报已生成；自动周报硬阻断校验未通过，请修正后单独重跑周报"],
    }


def _attach_automatic_weekly(db: Session, result: dict, report_date: date) -> dict | None:
    """本周最后工作日随日报自动出周报，把周报状态标注到 result 上。

    返回 weekly_ctx（供计算日志合并周报 trace）；非最后工作日返回 None。"""
    if not cal.is_last_workday_of_week(report_date):
        return None
    week_start, _ = cal.week_bounds(report_date)
    weekly_path, _, weekly_ctx = _run_weekly(
        db, week_start, report_date, export_calc_log=False,
    )
    if weekly_path is None:
        result.update(_weekly_blocked_payload(weekly_ctx))
    else:
        result["weekly_status"] = "succeeded"
        result["weekly_xlsx"] = weekly_path
    return weekly_ctx


def _missing_uploads(report_date: date, db: Session | None = None) -> list[str]:
    """返回该报告日尚未上传（action != updated）的输入源标签列表。

    MySQL 上传记录（report_date + source）是唯一权威；Redis 只是前端展示缓存，
    不参与门禁——否则伪造/陈旧的缓存可以顶替当日输入。
    也绝不用「库内历史行数 > 0」兜底：旧数据不能顶替当日输入。
    """
    from app.repositories import source_status_repo

    persisted: dict = {}
    if db is not None:
        persisted = source_status_repo.load_db(db, report_date)

    return [
        label for key, label in _SOURCE_LABELS.items()
        if (persisted.get(key) or {}).get("action") != "updated"
    ]


def generate_daily(db: Session, report_date: date,
                   baseline_date: date | None = None,
                   enforce_uploads: bool = True) -> dict:
    """baseline_date：可选的链式基线日；缺省用早于报告日的最近一份日报（通常昨日）。

    enforce_uploads：要求四类输入均在该报告日实际上传过（每日上传门禁）。
    级联重算历史日报时由调用方置 False（当日上传记录可能已过 Redis TTL）。
    """
    job_id = job_repo.create(JobKind.daily.value, report_date)
    job_repo.update(job_id, status=JobStatus.running.value)

    try:
        # 每日上传门禁：四类输入当日都上传过才允许生成（未上传显示红叉，不再沿用旧数据）
        if enforce_uploads:
            missing = _missing_uploads(report_date, db)
            if missing:
                msg = (f"{report_date} 尚未上传：{'、'.join(missing)}。"
                       "每个报告日需上传全部四类输入文件后才能生成日报，请先在工作台上传。")
                job_repo.update(job_id, status=JobStatus.needs_clarification.value,
                                message=msg)
                clarify_repo.add(report_date, "input_missing", msg, ref="输入", db=db)
                return {"status": "needs_clarification",
                        "error": {"code": "input_missing", "message": msg}}

        # 若库内人员表为空则无法计算，停下提问而非产出全 0 报表。
        if report_repo.count_inputs(db).get("employees", 0) == 0:
            msg = "人员表（employees）库内为空：请先上传人员表，或确认数据已入库后重试"
            job_repo.update(job_id, status=JobStatus.needs_clarification.value, message=msg)
            clarify_repo.add(report_date, "input_missing", msg, ref="输入", db=db)
            return {"status": "needs_clarification",
                    "error": {"code": "input_missing", "message": msg}}
        generation = month_opening_service.prepare_generation(
            db, report_date, baseline_date,
        )
        ctx = _agent.run_daily(
            db,
            report_date,
            generation["baseline_date"],
            baseline_override=generation["baseline_override"],
            tenure_baseline=generation["tenure_baseline"],
        )
        tenure = ctx["tenure"]
        results = ctx["validations"]

        hard = validators.hard_failures(results)
        if hard:
            job_repo.update(job_id, status=JobStatus.blocked.value,
                            message="硬阻断校验未通过", result={"hard_failures": hard})
            return {"status": "blocked", "validations": results, "hard_failures": hard}

        daily_path = daily_exporter.export_daily(
            ctx, tenure, settings.output_dir,
            generation["export_baseline_rows"],
            template_path=generation["template_path"],
        )
        # 导出成功后才允许成为后续日期的链式基线；缺月初模板时不落脏行。
        report_repo.save_daily(db, report_date, ctx["rows"])
        result = {"daily_xlsx": daily_path, "validations": results}

        # 若今天是本周最后工作日，则一并出周报，并写入计算日志
        weekly_ctx = _attach_automatic_weekly(db, result, report_date)

        log_path = calc_log_exporter.export_calc_log(
            ctx, tenure, results, settings.output_dir, weekly_ctx=weekly_ctx,
        )
        result["calc_log_md"] = log_path

        job_repo.update(job_id, status=JobStatus.succeeded.value, result=result)
        return {"status": "succeeded", **result}

    except BaselineMissingError as exc:
        # 先检查用户是否已回答过 baseline_missing 澄清；若有则注入基线并立即重试一次
        if _try_consume_baseline_answer(db, report_date):
            log.info("检测到已答复的基线澄清，注入后自动重试 report_date=%s", report_date)
            try:
                # 重试时不再传显式 baseline_date：基线注入到默认位置（前一自然日），
                # 显式基线日若无日报正是本次失败的原因
                generation = month_opening_service.prepare_generation(db, report_date)
                ctx = _agent.run_daily(
                    db,
                    report_date,
                    generation["baseline_date"],
                    baseline_override=generation["baseline_override"],
                    tenure_baseline=generation["tenure_baseline"],
                )
                tenure = ctx["tenure"]
                results = ctx["validations"]
                hard = validators.hard_failures(results)
                if hard:
                    job_repo.update(job_id, status=JobStatus.blocked.value,
                                    message="硬阻断校验未通过", result={"hard_failures": hard})
                    return {"status": "blocked", "validations": results, "hard_failures": hard}
                daily_path = daily_exporter.export_daily(
                    ctx, tenure, settings.output_dir,
                    generation["export_baseline_rows"],
                    template_path=generation["template_path"],
                )
                report_repo.save_daily(db, report_date, ctx["rows"])
                result = {"daily_xlsx": daily_path, "validations": results}
                weekly_ctx = _attach_automatic_weekly(db, result, report_date)
                log_path = calc_log_exporter.export_calc_log(
                    ctx, tenure, results, settings.output_dir, weekly_ctx=weekly_ctx,
                )
                result["calc_log_md"] = log_path
                job_repo.update(job_id, status=JobStatus.succeeded.value, result=result)
                return {"status": "succeeded", **result}
            except HRAgentError as retry_exc:
                # 重试仍失败：记录 retry 错误到日志，但保留原始 baseline_missing
                # 作为对外展示的错误码，避免用不相关的错误码覆盖澄清记录
                log.warning("基线注入后重试仍失败（code=%s）", retry_exc.code)

        _baseline_clarification_message = (
            f"{exc.message}\n\n"
            "可选处理方式：\n"
            "1) 回复「自动重算」：系统按库内数据全量重算基线"
            "（推荐；与在岗时长 B10=Row14 硬校验口径自洽）；\n"
            "2) 通过 POST /reports/baseline 提供手动基线；\n"
            "3) 在对话中回复以下 JSON：\n"
            '{"for_date": "上一工作日日期", "row8": MTD入职, "row9": MTD离职, '
            '"row13": YTD入职, "row14": YTD离职, "row30": Release累计}\n'
            "（数值全为 0 视为未知，将按库内数据自动重算，"
            "避免注入全 0 后 Row14 与在岗时长合计对不上被硬阻断）"
        )
        job_repo.update(job_id, status=JobStatus.needs_clarification.value,
                        message=_baseline_clarification_message, result=exc.to_dict())
        clarify_repo.add(report_date, exc.code, _baseline_clarification_message,
                         options=['自动重算',
                                  '{"for_date":"YYYY-MM-DD","row8":0,"row9":0,"row13":0,"row14":0,"row30":0}'],
                         db=db)
        return {"status": "needs_clarification", "error": exc.to_dict()}

    except HRAgentError as exc:
        job_repo.update(job_id, status=JobStatus.needs_clarification.value,
                        message=exc.message, result=exc.to_dict())
        clarify_repo.add(report_date, exc.code, exc.message, db=db)
        return {"status": "needs_clarification", "error": exc.to_dict()}
    except Exception as exc:
        job_repo.update(job_id, status=JobStatus.failed.value, message=str(exc))
        raise


def generate_daily_cascade(db: Session, report_date: date,
                           baseline_date: date | None = None) -> dict:
    """生成指定日期的日报；若为补生成历史日期（其后已存在已生成日报），
    则按日期顺序级联重算之后的所有日报。

    原因：MTD/YTD/Row30 是链式累计（今日 = 昨日基线 + 今日事实）。往前补一天
    会改变后续每一天的基线，之后已生成的日报若不重算，链条将不一致。

    返回主结果，附加 "cascaded": [{"report_date", "status"}, ...]（无级联则省略）。
    级联中任一天 needs_clarification/blocked 时停止（后面的链条依赖它）。
    """
    out = generate_daily(db, report_date, baseline_date)
    if out.get("status") != "succeeded":
        return out

    cascaded = cascade_later(db, report_date)
    if cascaded:
        out["cascaded"] = cascaded
    return out


def cascade_later(db: Session, after_date: date) -> list[dict]:
    """按日期顺序重算 after_date 之后（不含）已存在的所有日报。

    用于两种场景：(1) 补生成/重算某日日报后，顺推刷新其后链条；
    (2) 导入定稿基线日报后，刷新其后所有依赖该基线的日报（含随日报联动的周报）。

    级联重算不检查当日上传门禁：这些日期此前已生成过日报（当日上传记录可能已过
    Redis TTL），只需按新基线重算链条。任一天非 succeeded 即停止（后续依赖它）。
    返回 [{"report_date", "status"}, ...]（无后续日期则为空列表）。
    """
    later = sorted(
        d["report_date"] for d in report_repo.list_daily_dates(db, limit=366)
        if d["report_date"] > after_date.isoformat()
    )
    cascaded: list[dict] = []
    for d_str in later:
        d = date.fromisoformat(d_str)
        r = generate_daily(db, d, enforce_uploads=False)
        entry = {"report_date": d_str, "status": r.get("status")}
        # 日报成功但随附周报被硬阻断时，级联结果必须透出周报状态，
        # 否则导入方只看 status=succeeded 会漏掉需要单独重跑的周报。
        if "weekly_status" in r:
            entry["weekly_status"] = r["weekly_status"]
        cascaded.append(entry)
        if r.get("status") != "succeeded":
            log.warning("级联重算在 %s 停止（status=%s）", d_str, r.get("status"))
            break
    return cascaded


def _run_weekly(
    db: Session,
    week_start: date,
    week_end: date,
    *,
    export_calc_log: bool = True,
) -> tuple[str | None, str | None, dict]:
    log.info("生成周报：窗口 %s ~ %s（export_calc_log=%s）",
             week_start, week_end, export_calc_log)
    ctx = _agent.run_weekly(db, week_start, week_end)

    hard = validators.hard_failures(ctx.get("validations", []))
    if hard:
        log.warning("周报硬阻断校验未通过 %d 项：%s", len(hard),
                    "；".join(v.get("check", "") for v in hard))
        ctx["hard_failures"] = hard
        return None, None, ctx

    report_repo.save_weekly(db, week_start, week_end, ctx["main_rows"])
    path = weekly_exporter.export_weekly(ctx, settings.output_dir)
    log_path = None
    if export_calc_log:
        log_path = calc_log_exporter.merge_weekly_into_calc_log(ctx, settings.output_dir)
    log.info("周报已导出：xlsx=%s；计算日志=%s", path, log_path or "（随日报计算日志合并）")
    return path, log_path, ctx


def generate_weekly(
    db: Session,
    week_start: date,
    week_end: date,
    *,
    export_calc_log: bool = True,
) -> dict:
    path, log_path, ctx = _run_weekly(
        db, week_start, week_end, export_calc_log=export_calc_log,
    )
    hard = ctx.get("hard_failures") or validators.hard_failures(
        ctx.get("validations", [])
    )
    if hard:
        return {
            "status": "blocked",
            "validations": ctx.get("validations", []),
            "hard_failures": hard,
        }
    return {
        "status": "succeeded",
        "weekly_xlsx": path,
        "calc_log_md": log_path,
        "validations": ctx.get("validations", []),
    }
