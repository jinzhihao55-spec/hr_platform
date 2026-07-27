"""Persistence contracts for provisional runs and independent report targets."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)


def _run(**overrides) -> ReportRun:
    values = {
        "report_date": date(2026, 7, 8),
        "status": RunStatus.created.value,
        "rule_version": "rules-v1",
    }
    values.update(overrides)
    return ReportRun(**values)


def test_report_run_allows_multiple_provisional_runs_without_fingerprint(db):
    first = _run()
    second = _run()
    db.add_all([first, second])

    db.commit()

    assert first.source_bundle_hash is None
    assert second.source_bundle_hash is None
    assert first.id != second.id


def test_completed_source_bundle_fingerprint_is_unique(db):
    db.add(_run(source_bundle_hash="a" * 64))
    db.commit()
    db.add(_run(source_bundle_hash="a" * 64))

    with pytest.raises(IntegrityError):
        db.commit()


def test_each_source_type_is_unique_within_run(db):
    run = _run()
    db.add(run)
    db.flush()
    values = {
        "run_id": run.id,
        "source_type": SourceType.personnel.value,
        "sha256": "b" * 64,
        "schema_version": "personnel-v1",
        "parser_version": "parser-v1",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "row_count": 2,
        "parse_status": "parsed",
        "original_extension": ".xlsx",
    }
    db.add(RunSource(**values))
    db.commit()
    db.add(RunSource(**values))

    with pytest.raises(IntegrityError):
        db.commit()


def test_daily_and_weekly_targets_are_independent_within_run(db):
    run = _run(status=RunStatus.ready.value)
    db.add(run)
    db.flush()
    db.add_all(
        [
            RunReportTarget(
                run_id=run.id,
                report_kind="daily",
                status=TargetStatus.ready.value,
            ),
            RunReportTarget(
                run_id=run.id,
                report_kind="weekly",
                status=TargetStatus.needs_review.value,
            ),
        ]
    )

    db.commit()

    targets = {
        target.report_kind: target.status
        for target in db.query(RunReportTarget).filter_by(run_id=run.id).all()
    }
    assert targets == {"daily": "ready", "weekly": "needs_review"}


def test_same_report_target_kind_cannot_be_added_twice(db):
    run = _run()
    db.add(run)
    db.flush()
    db.add(
        RunReportTarget(
            run_id=run.id, report_kind="daily", status=TargetStatus.draft.value
        )
    )
    db.commit()
    db.add(
        RunReportTarget(
            run_id=run.id, report_kind="daily", status=TargetStatus.draft.value
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_state_enums_match_frozen_workflow_contract():
    assert {status.value for status in RunStatus} == {
        "created",
        "parsing",
        "needs_review",
        "ready",
        "deduplicated",
        "failed",
    }
    assert {source.value for source in SourceType} == {
        "personnel",
        "resignation",
        "release",
        "recruitment",
    }
    assert {status.value for status in TargetStatus} == {
        "draft",
        "calculating",
        "needs_review",
        "ready",
        "publishing",
        "published",
        "failed",
        "superseded",
    }
