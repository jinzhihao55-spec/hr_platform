"""只读视图服务：为前端「日报/周报/计算日志」页面提供结构化数据。

已发布报表必须读取不可变发布快照；只有尚未发布的兼容链路才允许按当前主表只读重算。
否则后续日期入库后，历史计算日志会与当时发布的 Excel 发生漂移。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.calculation_agent import CalculationAgent
from app.core import constants as C
from app.models.facts import RunValidation, decode_json_text
from app.models.publication import PublishedReport
from app.repositories import publication_repo, report_repo
from app.services import archive_service

_agent = CalculationAgent()

_SAFE_TRACE_FIELDS = {
    "baseline",
    "increment",
    "left",
    "right",
    "row30",
    "row31",
    "row32",
    "total_row",
    "rowsum",
    "conflict",
    "note",
}

_VALIDATION_LABELS = {
    "multiple_active_employments": "同一自然人存在多条有效任职记录",
    "top3_cutoff_tie": "前三项目截止位并列",
}


def _validation_view(
    db: Session, run_id: str, report_kind: str
) -> list[dict[str, Any]]:
    records = db.scalars(
        select(RunValidation)
        .where(
            RunValidation.run_id == run_id,
            RunValidation.report_kind == report_kind,
            RunValidation.is_deleted == 0,
        )
        .order_by(RunValidation.validation_code)
    ).all()
    result = []
    for record in records:
        # These views are called only for published reports. Publication proves
        # every failed REVIEW check had an accepted operator decision; keep the
        # original check visible, but do not present it as an unresolved error.
        resolved_by_review = (
            record.outcome != "PASS" and record.severity == "REVIEW"
        )
        result.append(
            {
                "check": _VALIDATION_LABELS.get(record.message, record.message),
                "validation_code": record.validation_code,
                "passed": record.outcome == "PASS" or resolved_by_review,
                "resolved_by_review": resolved_by_review,
                "hard_block": record.severity == "BLOCK",
                "severity": record.severity,
            }
        )
    return result


def _previous_daily_snapshot(
    db: Session, report_date: date
) -> tuple[date | None, dict[int, Any]]:
    report = db.scalar(
        select(PublishedReport)
        .where(
            PublishedReport.report_kind == "daily",
            PublishedReport.period_end < report_date,
            PublishedReport.is_current.is_(True),
            PublishedReport.is_deleted == 0,
        )
        .order_by(PublishedReport.period_end.desc(), PublishedReport.version.desc())
        .limit(1)
    )
    if report is None:
        return None, {}
    payload = decode_json_text(report.snapshot_json) or {}
    rows = payload.get("rows") or {}
    return report.period_end, {
        int(number): info.get("value") for number, info in rows.items()
    }


def _published_daily_view(
    db: Session, report: PublishedReport, report_date: date
) -> dict[str, Any]:
    payload = decode_json_text(report.snapshot_json) or {}
    raw_rows = payload.get("rows") or {}
    baseline_date, baseline = _previous_daily_snapshot(db, report_date)

    # Formula/source strings are rule metadata. Values, tenure and validations
    # always come from the immutable publication and its originating Run.
    try:
        metadata_ctx = _agent.run_daily(db, report_date)
    except Exception:
        metadata_ctx = {}
    trace_by_ref = {
        trace.get("ref"): trace for trace in metadata_ctx.get("trace", [])
    }

    rows = []
    for number in range(2, 41):
        info = raw_rows.get(str(number)) or {}
        trace = trace_by_ref.get(f"Row{number}", {})
        rows.append(
            {
                "row": number,
                "item": info.get("label") or info.get("item"),
                "baseline": baseline.get(number),
                "value": info.get("value"),
                "is_blank": bool(info.get("is_blank")),
                "is_header": number in C.DAILY_HEADER_ROWS,
                "derived": number in C.DAILY_DERIVED_ROWS,
                "formula": trace.get("formula"),
                "source": trace.get("source"),
                "trace": {
                    key: value
                    for key, value in trace.items()
                    if key in _SAFE_TRACE_FIELDS
                },
            }
        )

    value_by_row = {row["row"]: row["value"] for row in rows}
    paths = archive_service.find_export_paths(report_date, ["daily", "calc_log"])
    return {
        "report_date": report_date.isoformat(),
        "baseline_date": baseline_date.isoformat() if baseline_date else None,
        "published_report_id": report.id,
        "snapshot_hash": report.snapshot_hash,
        "export_path": paths.get("daily"),
        "calc_log_path": paths.get("calc_log"),
        "kpis": {
            "row2_今日入职": value_by_row.get(2),
            "row3_今日离职": value_by_row.get(3),
            "row7_今日净增": value_by_row.get(7),
            "row12_MTD净增": value_by_row.get(12),
        },
        "rows": rows,
        "tenure": payload.get("tenure") or {},
        "validations": _validation_view(db, report.run_id, "daily"),
    }


def daily_view(db: Session, report_date: date) -> dict[str, Any]:
    published = publication_repo.current_daily(db, report_date)
    if published is not None:
        return _published_daily_view(db, published, report_date)

    ctx = _agent.run_daily(db, report_date)          # 只读重算（不写库）
    rows_ctx = ctx["rows"]
    baseline = report_repo.get_baseline_rows(db, report_date)
    trace_by_ref = {t.get("ref"): t for t in ctx.get("trace", [])}

    rows = []
    for n in range(2, 41):
        info = rows_ctx.get(n, {})
        t = trace_by_ref.get(f"Row{n}", {})
        rows.append({
            "row": n,
            "item": info.get("item"),
            "baseline": baseline.get(n),
            "value": info.get("value"),
            "is_blank": bool(info.get("is_blank")),
            "is_header": bool(info.get("is_header")),
            "derived": n in C.DAILY_DERIVED_ROWS,
            "formula": t.get("formula"),
            "source": t.get("source"),
            "trace": {k: v for k, v in t.items()
                      if k not in {"scope", "ref", "item", "value"}},
        })

    def _v(n):
        return (rows_ctx.get(n) or {}).get("value")

    paths = archive_service.find_export_paths(report_date, ["daily", "calc_log"])
    return {
        "report_date": report_date.isoformat(),
        "baseline_date": ctx.get("baseline_date").isoformat() if ctx.get("baseline_date") else None,
        "export_path": paths.get("daily"),         # 日报 xlsx，供前端导出按钮使用
        "calc_log_path": paths.get("calc_log"),    # 计算日志 md
        "kpis": {"row2_今日入职": _v(2), "row3_今日离职": _v(3),
                 "row7_今日净增": _v(7), "row12_MTD净增": _v(12)},
        "rows": rows,
        "tenure": ctx["tenure"],
        "validations": ctx["validations"],
    }


def weekly_view(db: Session, week_start: date, week_end: date) -> dict[str, Any]:
    published = publication_repo.current_weekly(db, week_start, week_end)
    if published is not None:
        payload = decode_json_text(published.snapshot_json) or {}
        mr = payload.get("main_rows") or []
        cc = payload.get("cc_rows") or []
        sheet2_total = {
            "headcount": sum(int(row.get("headcount") or 0) for row in mr),
            "cnt_formal": sum(int(row.get("cnt_formal") or 0) for row in mr),
            "cnt_intern": sum(int(row.get("cnt_intern") or 0) for row in mr),
            "cnt_labor": sum(int(row.get("cnt_labor") or 0) for row in mr),
            "joiners": sum(int(row.get("joiners") or 0) for row in mr),
            "leavers": sum(int(row.get("leavers") or 0) for row in mr),
        }
        sheet1_total = {
            "headcount": sum(int(row.get("headcount") or 0) for row in cc),
            "joiners": sum(int(row.get("joiners") or 0) for row in cc),
            "leavers": sum(int(row.get("leavers") or 0) for row in cc),
        }
        traces = [
            {
                "scope": "weekly_bu",
                "ref": row.get("business_unit"),
                "headcount": row.get("headcount"),
                "split": [
                    row.get("cnt_formal"),
                    row.get("cnt_intern"),
                    row.get("cnt_labor"),
                ],
                "joiners": row.get("joiners"),
                "leavers": row.get("leavers"),
                "top3": row.get("top3_projects") or [],
            }
            for row in mr
        ]
        cc_traces = [
            {
                "scope": "weekly_cc",
                "ref": row.get("project"),
                "project": row.get("project"),
                "cost_center": row.get("cost_center"),
                "headcount": row.get("headcount"),
                "joiners": row.get("joiners"),
                "leavers": row.get("leavers"),
            }
            for row in cc
        ]
        paths = archive_service.find_export_paths(week_end, ["weekly", "calc_log"])
        return {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "published_report_id": published.id,
            "snapshot_hash": published.snapshot_hash,
            "export_path": paths.get("weekly"),
            "calc_log_path": paths.get("calc_log"),
            "sheet2": {"rows": mr, "total": sheet2_total},
            "sheet1": {"rows": cc, "total": sheet1_total},
            "traces": traces,
            "cc_traces": cc_traces,
            "validations": _validation_view(db, published.run_id, "weekly"),
        }

    ctx = _agent.run_weekly(db, week_start, week_end)
    mr = ctx["main_rows"]
    cc = ctx["cc_rows"]
    sheet2_total = {
        "headcount": sum(x["headcount"] for x in mr),
        "cnt_formal": sum(x["cnt_formal"] for x in mr),
        "cnt_intern": sum(x["cnt_intern"] for x in mr),
        "cnt_labor": sum(x["cnt_labor"] for x in mr),
        "joiners": sum(x["joiners"] for x in mr),
        "leavers": sum(x["leavers"] for x in mr),
    }
    sheet1_total = {
        "headcount": sum(x["headcount"] for x in cc),
        "joiners": sum(x["joiners"] for x in cc),
        "leavers": sum(x["leavers"] for x in cc),
    }
    paths = archive_service.find_export_paths(week_end, ["weekly", "calc_log"])
    cc_traces = [
        {
            "scope": "weekly_cc",
            "ref": r.get("project"),
            "cost_center": r.get("cost_center"),
            "headcount": r.get("headcount"),
            "joiners": r.get("joiners"),
            "leavers": r.get("leavers"),
        }
        for r in cc
    ]
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "export_path": paths.get("weekly"),
        # 周报常与当周最后工作日日报一并生成，计算日志 md 以 week_end 日报为准
        "calc_log_path": paths.get("calc_log"),
        "sheet2": {"rows": mr, "total": sheet2_total},
        "sheet1": {"rows": cc, "total": sheet1_total},
        "traces": ctx.get("trace", []),
        "cc_traces": cc_traces,
        "validations": ctx.get("validations", []),
    }
