"""Preview calculation is deterministic and does not mutate report projections."""

from dataclasses import replace
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func, select

from app.domain.fact_bundle import FactBundle
from app.agents.calculation_agent import CalculationAgent
from app.models.publication import PublishedReport
from app.models.reports import DailyReport, WeeklyReport
from app.models.runs import ReportRun, RunReportTarget, RunStatus, TargetStatus
from app.services.preview_service import PreviewSnapshot, build_preview


def make_run(db, report_date: date) -> ReportRun:
    run = ReportRun(
        report_date=report_date,
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.commit()
    return run


def make_daily_bundle(report_date: date = date(2026, 7, 8)) -> FactBundle:
    employees = pd.DataFrame(
        [
            {
                "person_key": "fake-person-1",
                "person_id": "fake-person-1",
                "emp_no": "FAKE-E1",
                "employee_type": "正式员工",
                "employee_status": "active",
                "hire_date": report_date,
                "leave_date": None,
                "hire_first_visible": report_date,
                "leave_first_visible": None,
                "business_unit": "NENT",
                "business_unit_no": "NENT",
                "project_no": "FAKE-P1",
                "project_name": "测试项目",
            }
        ]
    )
    return FactBundle(
        report_date=report_date,
        baseline_date=date(2026, 7, 7),
        rule_version="rules-v1",
        employments=employees,
        baseline_rows={8: 0, 9: 0, 13: 0, 14: 0, 30: 0},
        daily_reconciliation={
            "available_days": 0,
            "report_dates": [],
            "expected_dates": [],
            "complete": False,
            "joiners": 0,
            "leavers": 0,
        },
    )


def make_weekly_bundle() -> FactBundle:
    report_date = date(2026, 7, 10)
    employees = pd.DataFrame(
        [
            {
                "person_key": "fake-person-1",
                "person_id": "fake-person-1",
                "emp_no": "FAKE-E1",
                "employee_type": "正式员工",
                "employee_status": "active",
                "hire_date": date(2025, 1, 1),
                "leave_date": None,
                "hire_first_visible": date(2025, 1, 1),
                "leave_first_visible": None,
                "business_unit": "NENT",
                "business_unit_no": "NENT",
                "project_no": "FAKE-P1",
                "project_name": "内部测试项目",
            }
        ]
    )
    return FactBundle(
        report_date=report_date,
        baseline_date=date(2026, 7, 9),
        rule_version="rules-v1",
        employments=employees,
        baseline_rows={8: 0, 9: 0, 13: 0, 14: 0, 30: 0},
        daily_reconciliation={
            "available_days": 5,
            "report_dates": [
                "2026-07-06",
                "2026-07-07",
                "2026-07-08",
                "2026-07-09",
                "2026-07-10",
            ],
            "expected_dates": [
                "2026-07-06",
                "2026-07-07",
                "2026-07-08",
                "2026-07-09",
                "2026-07-10",
            ],
            "complete": True,
            "joiners": 0,
            "leavers": 0,
        },
    )


def test_daily_preview_does_not_write_compatibility_reports(db):
    run = make_run(db, date(2026, 7, 8))

    snapshot = build_preview(db, run.id, "daily", bundle=make_daily_bundle())

    assert isinstance(snapshot, PreviewSnapshot)
    assert snapshot.rows[2].value == 1
    assert snapshot.publishable is True
    assert db.scalar(select(func.count()).select_from(DailyReport)) == 0
    target = db.scalar(
        select(RunReportTarget).where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.report_kind == "daily",
        )
    )
    assert target.preview_hash == snapshot.snapshot_hash


def test_weekly_preview_does_not_write_compatibility_reports(db):
    run = make_run(db, date(2026, 7, 10))

    snapshot = build_preview(
        db,
        run.id,
        "weekly",
        bundle=make_weekly_bundle(),
        week_start=date(2026, 7, 6),
        week_end=date(2026, 7, 10),
    )

    assert snapshot.publishable is True
    assert snapshot.main_rows[0]["headcount"] == 1
    assert db.scalar(select(func.count()).select_from(WeeklyReport)) == 0


def test_weekly_preview_before_last_workday_is_not_publishable(db):
    report_date = date(2026, 7, 8)
    run = make_run(db, report_date)
    bundle = replace(
        make_weekly_bundle(),
        report_date=report_date,
        baseline_date=date(2026, 7, 7),
        daily_reconciliation={
            "available_days": 3,
            "report_dates": ["2026-07-06", "2026-07-07", "2026-07-08"],
            "expected_dates": ["2026-07-06", "2026-07-07", "2026-07-08"],
            "complete": True,
            "joiners": 0,
            "leavers": 0,
        },
    )

    snapshot = build_preview(
        db,
        run.id,
        "weekly",
        bundle=bundle,
        week_start=date(2026, 7, 6),
        week_end=report_date,
    )

    assert snapshot.publishable is False
    assert "weekly_last_workday_only" in (
        snapshot.validation_summary.blocking_validation_codes
    )


def test_same_preview_input_has_same_hash(db):
    run = make_run(db, date(2026, 7, 8))
    bundle = make_daily_bundle()

    first = build_preview(db, run.id, "daily", bundle=bundle)
    second = build_preview(db, run.id, "daily", bundle=bundle)

    assert first.snapshot_hash == second.snapshot_hash
    assert first.snapshot_json == second.snapshot_json


def test_published_preview_reads_immutable_snapshot_without_recalculation(db, monkeypatch):
    run = make_run(db, date(2026, 7, 8))
    bundle = make_daily_bundle()
    original = build_preview(db, run.id, "daily", bundle=bundle)
    report = PublishedReport(
        run_id=run.id,
        report_kind="daily",
        period_start=run.report_date,
        period_end=run.report_date,
        version=1,
        is_current=True,
        snapshot_json=original.snapshot_json,
        snapshot_hash=original.snapshot_hash,
        published_by="test-operator",
        published_at=datetime(2026, 7, 8, 18, 0, 0),
    )
    db.add(report)
    db.flush()
    target = db.scalar(
        select(RunReportTarget).where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.report_kind == "daily",
        )
    )
    target.status = TargetStatus.published.value
    target.published_report_id = report.id
    db.commit()

    def fail_if_recalculated(*_args, **_kwargs):
        raise AssertionError("published previews must not invoke the calculator")

    monkeypatch.setattr(CalculationAgent, "run_daily_bundle", fail_if_recalculated)

    reopened = build_preview(db, run.id, "daily", bundle=bundle)

    assert reopened.snapshot_hash == original.snapshot_hash
    assert reopened.snapshot_json == original.snapshot_json
    assert reopened.rows[2].value == original.rows[2].value
    assert reopened.publishable is True


def test_published_weekly_preview_preserves_export_period_context(db, monkeypatch):
    run = make_run(db, date(2026, 7, 10))
    bundle = make_weekly_bundle()
    week_start = date(2026, 7, 6)
    week_end = date(2026, 7, 10)
    original = build_preview(
        db,
        run.id,
        "weekly",
        bundle=bundle,
        week_start=week_start,
        week_end=week_end,
    )
    report = PublishedReport(
        run_id=run.id,
        report_kind="weekly",
        period_start=week_start,
        period_end=week_end,
        version=1,
        is_current=True,
        snapshot_json=original.snapshot_json,
        snapshot_hash=original.snapshot_hash,
        published_by="test-operator",
        published_at=datetime(2026, 7, 10, 18, 0, 0),
    )
    db.add(report)
    db.flush()
    target = db.scalar(
        select(RunReportTarget).where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.report_kind == "weekly",
        )
    )
    target.status = TargetStatus.published.value
    target.published_report_id = report.id
    db.commit()

    def fail_if_recalculated(*_args, **_kwargs):
        raise AssertionError("published previews must not invoke the calculator")

    monkeypatch.setattr(CalculationAgent, "run_weekly_bundle", fail_if_recalculated)

    reopened = build_preview(
        db,
        run.id,
        "weekly",
        bundle=bundle,
        week_start=week_start,
        week_end=week_end,
    )

    assert reopened.calculation_context["week_start"] == week_start
    assert reopened.calculation_context["week_end"] == week_end
