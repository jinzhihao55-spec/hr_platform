"""Run validation summaries isolate daily and weekly publication targets."""

from datetime import date

from app.models.facts import (
    RunDecision,
    RunValidation,
    decode_json_text,
    encode_json_text,
)
from app.models.runs import ReportRun, RunStatus, TargetStatus
from app.pipeline.calculation.weekly import top3_tie_ref
from app.services.run_validation_service import (
    replace_calculation_validations,
    validate_run_target,
)


def _run(db, status: RunStatus = RunStatus.ready) -> ReportRun:
    run = ReportRun(
        report_date=date(2026, 7, 10),
        status=status.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    return run


def _duplicate_review(
    *, severity: str = "REVIEW", conflicts: list[str] | None = None
) -> dict:
    return {
        "code": "multiple_active_employments",
        "severity": severity,
        "person_ref": "abc123def456",
        "employment_source_row_nos": [7, 8],
        "selected_source_row_no": 8,
        "conflicting_dimensions": conflicts or [],
    }


def _top3_review() -> dict:
    return {
        "code": "top3_cutoff_tie",
        "severity": "REVIEW",
        "business_unit": "FAKE-BU-A",
        "tie_ref": top3_tie_ref("FAKE-BU-A"),
        "candidates": ["AlphaTie", "ZuluTie"],
        "slots": 1,
        "selected_projects": ["AlphaTie"],
    }


def test_weekly_review_does_not_block_daily_target(db):
    run = _run(db)
    db.add(
        RunValidation(
            run_id=run.id,
            report_kind="weekly",
            validation_code="weekly_third_place_tie",
            severity="REVIEW",
            outcome="FAIL",
            message="周报第三名并列待确认",
            evidence_refs=encode_json_text(["validation:weekly:third-place"]),
        )
    )
    db.commit()

    daily = validate_run_target(db, run.id, "daily")
    weekly = validate_run_target(db, run.id, "weekly")

    assert daily.publishable is True
    assert daily.target_status == TargetStatus.ready.value
    assert weekly.publishable is False
    assert weekly.target_status == TargetStatus.needs_review.value
    assert weekly.blocking_validation_codes == ("weekly_third_place_tie",)


def test_partial_week_with_pending_review_is_needs_review_not_failed(db):
    run = ReportRun(
        report_date=date(2026, 7, 20),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[{
            "check": "周报仅可在本周最后一个工作日发布",
            "validation_code": "weekly_last_workday_only",
            "passed": False,
            "hard_block": True,
        }],
        review_items=[_top3_review()],
    )

    summary = validate_run_target(db, run.id, "weekly")

    assert summary.publishable is False
    assert summary.pending_decision_count == 1
    assert summary.target_status == TargetStatus.needs_review.value


def test_partial_week_without_pending_review_is_not_failed(db):
    run = ReportRun(
        report_date=date(2026, 7, 20),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[{
            "check": "周报仅可在本周最后一个工作日发布",
            "validation_code": "weekly_last_workday_only",
            "passed": False,
            "hard_block": True,
        }],
    )

    summary = validate_run_target(db, run.id, "weekly")

    assert summary.publishable is False
    assert summary.target_status == TargetStatus.needs_review.value


def test_shared_pending_decision_blocks_both_targets(db):
    run = _run(db)
    db.add(
        RunDecision(
            run_id=run.id,
            report_kind=None,
            decision_code="release_row5_classification_required",
            fact_ref="source:release:row:2",
            question="是否计入 Row5？",
            options=encode_json_text(["计入Row5", "不计入Row5"]),
            status="pending",
        )
    )
    db.commit()

    daily = validate_run_target(db, run.id, "daily")
    weekly = validate_run_target(db, run.id, "weekly")

    assert daily.publishable is False
    assert weekly.publishable is False
    assert daily.pending_decision_count == 1
    assert weekly.pending_decision_count == 1


def test_calculation_validation_persists_only_opaque_evidence(db):
    run = _run(db)

    replace_calculation_validations(
        db,
        run.id,
        "daily",
        checks=[
            {
                "check": "Row6=Row4+Row5",
                "passed": False,
                "hard_block": True,
                "employee_name": "测试甲",
                "left": 1,
                "right": 2,
                "evidence_refs": ["fact:event:fake-1"],
            }
        ],
    )

    stored = db.query(RunValidation).filter_by(run_id=run.id).one()
    assert stored.severity == "BLOCK"
    assert stored.outcome == "FAIL"
    assert "测试甲" not in stored.message
    assert "测试甲" not in stored.evidence_refs
    assert stored.evidence_refs == encode_json_text(["fact:event:fake-1"])

    summary = validate_run_target(db, run.id, "daily")
    assert summary.publishable is False
    assert summary.target_status == TargetStatus.failed.value


def test_weekly_review_persists_source_and_selection_as_opaque_refs(db):
    run = _run(db)

    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                "code": "multiple_active_employments",
                "severity": "REVIEW",
                "person_ref": "abc123def456",
                "employment_source_row_nos": [7, 8],
                "selected_source_row_no": 8,
                "conflicting_dimensions": [],
            }
        ],
    )

    stored = db.query(RunValidation).filter_by(run_id=run.id).one()
    assert decode_json_text(stored.evidence_refs) == [
        "person:abc123def456",
        "source:personnel:row:7",
        "source:personnel:row:8",
        "employment:selected:8",
    ]
    assert "employee_no" not in stored.evidence_refs


def test_weekly_conflict_dimensions_are_persisted_as_opaque_refs(db):
    run = _run(db)

    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                "code": "multiple_active_employments",
                "severity": "BLOCK",
                "person_ref": "abc123def456",
                "employment_source_row_nos": [7, 8],
                "selected_source_row_no": 8,
                "conflicting_dimensions": ["project_name"],
            }
        ],
    )

    stored = db.query(RunValidation).filter_by(run_id=run.id).one()
    assert "validation:dimension:project_name" in decode_json_text(
        stored.evidence_refs
    )


def test_weekly_duplicate_review_creates_stable_pending_decision(db):
    run = _run(db)

    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[_duplicate_review()],
    )

    decision = db.query(RunDecision).filter_by(
        run_id=run.id,
        report_kind="weekly",
        decision_code="multiple_active_employments",
        fact_ref="weekly:multiple_active_employments:abc123def456",
    ).one()
    assert decode_json_text(decision.options) == ["确认按自然人计1人"]
    assert decision.status == "pending"
    summary = validate_run_target(db, run.id, "weekly")
    assert summary.pending_decision_count == 1
    assert summary.review_count == 1


def test_weekly_top3_tie_creates_scoped_pending_decision(db):
    run = _run(db)

    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[_top3_review()],
    )

    decision = db.query(RunDecision).filter_by(
        run_id=run.id,
        report_kind="weekly",
        decision_code="top3_cutoff_tie",
        fact_ref=f"weekly:top3_cutoff_tie:{top3_tie_ref('FAKE-BU-A')}:1",
    ).one()
    assert decode_json_text(decision.options) == ["AlphaTie", "ZuluTie"]
    assert decision.status == "pending"
    validation = db.query(RunValidation).filter_by(run_id=run.id).one()
    assert decode_json_text(validation.evidence_refs) == [
        f"fact:weekly_top3:{top3_tie_ref('FAKE-BU-A')}:1"
    ]
    summary = validate_run_target(db, run.id, "weekly")
    assert summary.pending_decision_count == 1
    assert summary.review_count == 1


def test_weekly_conflict_never_creates_confirmable_decision(db):
    run = _run(db)

    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            _duplicate_review(
                severity="BLOCK", conflicts=["project_name"]
            )
        ],
    )

    assert db.query(RunDecision).filter_by(
        run_id=run.id,
        decision_code="multiple_active_employments",
    ).count() == 0
    summary = validate_run_target(db, run.id, "weekly")
    assert summary.block_count == 1
    assert summary.publishable is False


def test_run_needs_review_is_a_shared_blocker(db):
    run = _run(db, RunStatus.needs_review)

    daily = validate_run_target(db, run.id, "daily")
    weekly = validate_run_target(db, run.id, "weekly")

    assert daily.publishable is False
    assert weekly.publishable is False
    assert daily.run_status_blocker == RunStatus.needs_review.value
