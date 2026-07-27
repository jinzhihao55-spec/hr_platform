"""工作台/页头上下文：报告日期、基线、本周窗口、节假日、主表行数 + 文件状态、待确认数。"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import clarify_repo, report_repo, source_status_repo

from app.utils import calendar_utils as cal

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

_SOURCE_KEYS = ("employees", "resignations", "agreements", "recruitment")


def context(db: Session, report_date: date) -> dict[str, Any]:
    week_start, week_end = cal.week_bounds(report_date)
    last_wd = cal.last_workday_of_week(report_date)
    is_last = cal.is_last_workday_of_week(report_date)
    baseline = report_repo.baseline_date(db, report_date)
    counts = report_repo.count_inputs(db)

    # 文件状态：优先读 Redis 当日上传记录；Redis 不可用/过期时降级为 MySQL 兜底：
    # 库内有数据 → 标记为 reused（沿用库内数据），不显示为 empty（红叉）。
    stored_sources = source_status_repo.load(report_date)
    sources: dict[str, Any] = {}
    for key in _SOURCE_KEYS:
        rows_in_db = counts.get(key, 0)
        info = stored_sources.get(key) or {}
        uploaded = info.get("action") == "updated"
        action = "updated" if uploaded else ("reused" if rows_in_db > 0 else "empty")
        sources[key] = {
            "action": action,
            "rows_in_db": rows_in_db,
            "rows_upserted": info.get("rows_upserted") if uploaded else None,
            "ingested_at": info.get("ingested_at") if uploaded else None,
        }

    return {
        "report_date": report_date.isoformat(),
        "weekday": _WEEKDAY_CN[report_date.weekday()],
        "baseline_date": baseline.isoformat() if baseline else None,
        # 默认基线日 = 报告日前第一个工作日（跳过周末/法定节假日），随报告日联动
        "default_baseline_date": cal.prev_workday(report_date).isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "last_workday_of_week": last_wd.isoformat(),
        "is_last_workday": is_last,
        "will_generate_weekly": is_last,
        "calendar_known": cal.calendar_known(report_date),
        # inputs: 行数摘要（保持向后兼容）
        "inputs": counts,
        # sources: 完整文件状态（供前端文件面板区分"沿用昨日"/"今日上传"/"未入库"）
        "sources": sources,
        "pending_clarifications": clarify_repo.count_pending(report_date, db=db),
    }
