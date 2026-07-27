"""Calendar API exposes independently scoped daily and weekly status."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunReportTarget, RunStatus, TargetStatus


@pytest.fixture()
def api_client(api_db):
    def override_db():
        yield api_db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_calendar_exposes_daily_and_weekly_status(api_db, api_client):
    db = api_db
    run = ReportRun(
        report_date=date(2026, 7, 15),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    db.add_all(
        [
            RunReportTarget(
                run_id=run.id,
                report_kind="daily",
                status=TargetStatus.published.value,
            ),
            RunReportTarget(
                run_id=run.id,
                report_kind="weekly",
                status=TargetStatus.needs_review.value,
            ),
        ]
    )
    db.commit()

    response = api_client.get("/calendar", params={"month": "2026-07"})

    assert response.status_code == 200
    day = next(item for item in response.json()["days"] if item["date"] == "2026-07-15")
    assert day == {
        "date": "2026-07-15",
        "is_workday": True,
        "run_id": run.id,
        "run_status": "ready",
        "daily_status": "published",
        "weekly_status": "not_due",
    }


def test_calendar_projects_midweek_weekly_block_as_not_due(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    api_db.add(
        RunReportTarget(
            run_id=run.id,
            report_kind="weekly",
            status=TargetStatus.failed.value,
        )
    )
    api_db.commit()

    response = api_client.get("/calendar", params={"month": "2026-07"})

    assert response.status_code == 200
    day = next(item for item in response.json()["days"] if item["date"] == "2026-07-08")
    assert day["weekly_status"] == "not_due"


def test_calendar_projects_midweek_draft_weekly_target_as_not_due(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 7),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    api_db.add(
        RunReportTarget(
            run_id=run.id,
            report_kind="weekly",
            status=TargetStatus.draft.value,
        )
    )
    api_db.commit()

    response = api_client.get("/calendar", params={"month": "2026-07"})

    assert response.status_code == 200
    day = next(item for item in response.json()["days"] if item["date"] == "2026-07-07")
    assert day["weekly_status"] == "not_due"


def test_calendar_aggregates_current_publications_across_same_day_runs(
    api_db, api_client
):
    report_date = date(2026, 7, 17)
    daily_run = ReportRun(
        report_date=report_date,
        status=RunStatus.ready.value,
        rule_version="rules-v1",
        create_time=datetime(2026, 7, 17, 17, 0, 0),
    )
    weekly_run = ReportRun(
        report_date=report_date,
        status=RunStatus.ready.value,
        rule_version="rules-v1",
        create_time=datetime(2026, 7, 17, 18, 0, 0),
    )
    api_db.add_all([daily_run, weekly_run])
    api_db.flush()
    daily_report = PublishedReport(
        run_id=daily_run.id,
        report_kind="daily",
        period_start=report_date,
        period_end=report_date,
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="d" * 64,
        published_by="test-operator",
        published_at=datetime(2026, 7, 17, 17, 30, 0),
    )
    weekly_report = PublishedReport(
        run_id=weekly_run.id,
        report_kind="weekly",
        period_start=date(2026, 7, 13),
        period_end=report_date,
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="w" * 64,
        published_by="test-operator",
        published_at=datetime(2026, 7, 17, 18, 30, 0),
    )
    api_db.add_all([daily_report, weekly_report])
    api_db.flush()
    api_db.add_all(
        [
            RunReportTarget(
                run_id=daily_run.id,
                report_kind="daily",
                status=TargetStatus.published.value,
                published_report_id=daily_report.id,
            ),
            RunReportTarget(
                run_id=daily_run.id,
                report_kind="weekly",
                status=TargetStatus.superseded.value,
            ),
            RunReportTarget(
                run_id=weekly_run.id,
                report_kind="daily",
                status=TargetStatus.draft.value,
            ),
            RunReportTarget(
                run_id=weekly_run.id,
                report_kind="weekly",
                status=TargetStatus.published.value,
                published_report_id=weekly_report.id,
            ),
        ]
    )
    api_db.commit()

    response = api_client.get("/calendar", params={"month": "2026-07"})

    assert response.status_code == 200
    day = next(item for item in response.json()["days"] if item["date"] == "2026-07-17")
    assert day["run_id"] == weekly_run.id
    assert day["daily_status"] == "published"
    assert day["weekly_status"] == "published"


def test_calendar_rejects_invalid_month_before_query(api_client):
    response = api_client.get("/calendar", params={"month": "July-2026"})

    assert response.status_code == 422
