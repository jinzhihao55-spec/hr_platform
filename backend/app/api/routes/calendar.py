"""Calendar projection for the single-user report workflow."""

from __future__ import annotations

import calendar as month_calendar
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunReportTarget, RunStatus
from app.schemas.runs import CalendarResponse
from app.utils.calendar_utils import is_last_workday_of_week, is_workday


router = APIRouter(tags=["calendar"])
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def _calendar_target_status(report_kind: str, status: str | None, value: date) -> str | None:
    if (
        report_kind == "weekly"
        and status is not None
        and status != "published"
        and not is_last_workday_of_week(value)
    ):
        return "not_due"
    return status


@router.get("/calendar", response_model=CalendarResponse)
def calendar_view(
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
):
    match = _MONTH.fullmatch(month)
    if match is None:
        raise HTTPException(422, "month must use YYYY-MM")
    year, month_number = (int(value) for value in match.groups())
    if month_number < 1 or month_number > 12:
        raise HTTPException(422, "month must use YYYY-MM")
    last_day = month_calendar.monthrange(year, month_number)[1]
    start = date(year, month_number, 1)
    end = date(year, month_number, last_day)

    runs = db.scalars(
        select(ReportRun)
        .where(
            ReportRun.report_date >= start,
            ReportRun.report_date <= end,
            ReportRun.status != RunStatus.deduplicated.value,
            ReportRun.is_deleted == 0,
        )
        .order_by(
            ReportRun.report_date,
            ReportRun.create_time.desc(),
            ReportRun.id.desc(),
        )
    ).all()
    latest_by_day: dict[date, ReportRun] = {}
    for run in runs:
        latest_by_day.setdefault(run.report_date, run)
    run_ids = [run.id for run in latest_by_day.values()]
    targets = (
        db.scalars(
            select(RunReportTarget).where(
                RunReportTarget.run_id.in_(run_ids),
                RunReportTarget.is_deleted == 0,
            )
        ).all()
        if run_ids
        else []
    )
    target_by_run = {
        (target.run_id, target.report_kind): target.status for target in targets
    }
    current_publications = {
        (period_end, report_kind)
        for period_end, report_kind in db.execute(
            select(PublishedReport.period_end, PublishedReport.report_kind).where(
                PublishedReport.period_end >= start,
                PublishedReport.period_end <= end,
                PublishedReport.is_current.is_(True),
                PublishedReport.is_deleted == 0,
            )
        ).all()
    }

    days = []
    for day_number in range(1, last_day + 1):
        value = date(year, month_number, day_number)
        run = latest_by_day.get(value)
        days.append(
            {
                "date": value,
                "is_workday": is_workday(value),
                "run_id": run.id if run else None,
                "run_status": run.status if run else None,
                "daily_status": (
                    "published"
                    if (value, "daily") in current_publications
                    else target_by_run.get((run.id, "daily")) if run else None
                ),
                "weekly_status": (
                    "published"
                    if (value, "weekly") in current_publications
                    else (
                        _calendar_target_status(
                            "weekly",
                            target_by_run.get((run.id, "weekly")),
                            value,
                        )
                        if run
                        else None
                    )
                ),
            }
        )
    return {"month": month, "days": days}
