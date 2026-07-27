"""weekly_reports 落库契约：重跑同一周不得残留已消失的事业部行。"""
from datetime import date

from sqlalchemy import select

from app.models.reports import WeeklyReport
from app.repositories import report_repo


def _row(bu: str) -> dict:
    return {"business_unit": bu, "headcount": 1, "cnt_formal": 1,
            "cnt_intern": 0, "cnt_labor": 0, "joiners": 0, "leavers": 0}


def test_save_weekly_removes_stale_bu_rows(db):
    week_start, week_end = date(2026, 7, 6), date(2026, 7, 10)
    report_repo.save_weekly(db, week_start, week_end, [_row("NINS"), _row("NWMT")])

    report_repo.save_weekly(db, week_start, week_end, [_row("NINS")])

    bus = [r.bu for r in db.scalars(
        select(WeeklyReport).where(WeeklyReport.week_start == week_start)
    ).all()]
    assert bus == ["NINS"]
