"""Queries and mutation helpers for immutable report versions."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.publication import PublishedReport
from app.models.runs import RunReportTarget, TargetStatus


def current_report(
    db: Session,
    report_kind: str,
    period_start: date,
    period_end: date,
    *,
    for_update: bool = False,
) -> PublishedReport | None:
    query = (
        select(PublishedReport)
        .where(
            PublishedReport.report_kind == report_kind,
            PublishedReport.period_start == period_start,
            PublishedReport.period_end == period_end,
            PublishedReport.is_current.is_(True),
            PublishedReport.is_deleted == 0,
        )
        .order_by(PublishedReport.version.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def current_daily(db: Session, report_date: date) -> PublishedReport | None:
    return current_report(db, "daily", report_date, report_date)


def current_weekly(
    db: Session, week_start: date, week_end: date
) -> PublishedReport | None:
    return current_report(db, "weekly", week_start, week_end)


def next_version(
    db: Session, report_kind: str, period_start: date, period_end: date
) -> int:
    current = db.scalar(
        select(func.max(PublishedReport.version)).where(
            PublishedReport.report_kind == report_kind,
            PublishedReport.period_start == period_start,
            PublishedReport.period_end == period_end,
            PublishedReport.is_deleted == 0,
        )
    )
    return int(current or 0) + 1


def supersede_current(
    db: Session,
    report_kind: str,
    period_start: date,
    period_end: date,
    superseded_at: datetime,
) -> PublishedReport | None:
    previous = current_report(
        db, report_kind, period_start, period_end, for_update=True
    )
    if previous is None:
        return None
    previous.is_current = False
    previous.superseded_at = superseded_at
    previous_target = db.scalar(
        select(RunReportTarget).where(
            RunReportTarget.published_report_id == previous.id,
            RunReportTarget.is_deleted == 0,
        )
    )
    if previous_target is not None:
        previous_target.status = TargetStatus.superseded.value
    return previous
