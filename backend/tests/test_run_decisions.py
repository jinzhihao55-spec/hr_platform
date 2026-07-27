"""Typed decision handlers may edit facts, never final report values."""

from datetime import date

import pytest

from app.models.facts import (
    ReleaseFact,
    RunDecision,
    decode_json_text,
    encode_json_text,
)
from app.models.runs import ReportRun, RunReportTarget, RunStatus, TargetStatus
from app.pipeline.calculation.weekly import top3_tie_ref
from app.services.decision_service import (
    DecisionAnswerConflict,
    InvalidDecisionAnswer,
    answer_decision,
    list_decisions,
)
from app.services.run_validation_service import (
    replace_calculation_validations,
    validate_run_target,
)


def _run(db) -> ReportRun:
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    return run


def _release_decision(db, run: ReportRun) -> tuple[ReleaseFact, RunDecision]:
    fact = ReleaseFact(
        run_id=run.id,
        source_row_no=2,
        order_no="FAKE-O1",
        application_date=date(2026, 7, 8),
        row5_classification="review",
        row30_classification="review",
    )
    decision = RunDecision(
        run_id=run.id,
        report_kind=None,
        decision_code="release_row5_classification_required",
        fact_ref="source:release:row:2",
        question="是否计入 Row5？",
        options=encode_json_text(["计入Row5", "不计入Row5", "替换输入"]),
        status="pending",
    )
    db.add_all([fact, decision])
    db.commit()
    return fact, decision


def test_decision_cannot_set_final_row_value(db):
    run = _run(db)
    fact, decision = _release_decision(db, run)

    with pytest.raises(InvalidDecisionAnswer, match="final report"):
        answer_decision(
            db,
            run.id,
            decision.id,
            {"row30": 99},
            "local-operator",
        )

    db.refresh(decision)
    db.refresh(fact)
    assert decision.status == "pending"
    assert fact.row5_classification == "review"


def test_release_decision_updates_fact_classification_and_audit(db):
    run = _run(db)
    fact, decision = _release_decision(db, run)

    answered = answer_decision(
        db,
        run.id,
        decision.id,
        "计入Row5",
        "local-operator",
    )

    db.refresh(fact)
    assert fact.row5_classification == "include"
    assert answered.status == "answered"
    assert answered.operator_ref == "local-operator"
    assert answered.decided_at is not None
    assert decode_json_text(answered.answer) == "计入Row5"

    queue = list_decisions(db, run.id, report_kind="daily")
    assert [item.id for item in queue] == [decision.id]
    assert queue[0].answer == "计入Row5"


def test_release_lwd_decision_requires_date_and_derives_row30(db):
    run = _run(db)
    fact = ReleaseFact(
        run_id=run.id,
        source_row_no=2,
        order_no="FAKE-LWD-1",
        application_date=run.report_date,
        row5_classification="include",
        row30_classification="review",
    )
    decision = RunDecision(
        run_id=run.id,
        report_kind=None,
        decision_code="release_lwd_missing",
        fact_ref="source:release:row:2",
        question="请补充最后工作日。",
        options=encode_json_text(["补充最后工作日", "替换输入"]),
        status="pending",
    )
    db.add_all([fact, decision])
    db.commit()

    with pytest.raises(InvalidDecisionAnswer, match="last_working_day"):
        answer_decision(db, run.id, decision.id, "不计入Row30", "local-operator")

    answered = answer_decision(
        db,
        run.id,
        decision.id,
        {"last_working_day": "2026-08-14"},
        "local-operator",
    )

    db.refresh(fact)
    assert fact.last_working_day == date(2026, 8, 14)
    assert fact.row30_classification == "exclude"
    assert answered.status == "answered"


def test_unknown_decision_code_fails_closed(db):
    run = _run(db)
    decision = RunDecision(
        run_id=run.id,
        report_kind="weekly",
        decision_code="unregistered_rule_guess",
        fact_ref="validation:unknown",
        question="未知问题",
        options=encode_json_text(["确认"]),
        status="pending",
    )
    db.add(decision)
    db.commit()

    with pytest.raises(InvalidDecisionAnswer, match="unsupported decision code"):
        answer_decision(db, run.id, decision.id, "确认", "local-operator")


def _stage_weekly_duplicate_decision(db, run: ReportRun) -> RunDecision:
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
    return db.query(RunDecision).filter_by(
        run_id=run.id,
        decision_code="multiple_active_employments",
    ).one()


def _top3_review_item() -> dict:
    return {
        "code": "top3_cutoff_tie",
        "severity": "REVIEW",
        "business_unit": "FAKE-BU-A",
        "tie_ref": top3_tie_ref("FAKE-BU-A"),
        "candidates": ["AlphaTie", "ZuluTie"],
        "slots": 1,
        "selected_projects": ["AlphaTie"],
    }


def _stage_weekly_top3_decision(db, run: ReportRun) -> RunDecision:
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[_top3_review_item()],
    )
    return db.query(RunDecision).filter_by(
        run_id=run.id,
        decision_code="top3_cutoff_tie",
    ).one()


def test_weekly_duplicate_answer_resolves_review_and_survives_recalculation(db):
    run = _run(db)
    decision = _stage_weekly_duplicate_decision(db, run)

    answer_decision(
        db,
        run.id,
        decision.id,
        "确认按自然人计1人",
        "local-operator",
    )
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

    db.refresh(decision)
    assert decision.status == "answered"
    summary = validate_run_target(db, run.id, "weekly")
    assert summary.pending_decision_count == 0
    assert summary.review_count == 0
    assert summary.publishable is True


def test_weekly_top3_answer_resolves_review_and_survives_recalculation(db):
    run = _run(db)
    decision = _stage_weekly_top3_decision(db, run)

    answered = answer_decision(
        db,
        run.id,
        decision.id,
        ["ZuluTie"],
        "local-operator",
    )
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {**_top3_review_item(), "selected_projects": ["ZuluTie"]}
        ],
    )

    assert decode_json_text(answered.answer) == ["ZuluTie"]
    summary = validate_run_target(db, run.id, "weekly")
    assert summary.pending_decision_count == 0
    assert summary.review_count == 0
    assert summary.publishable is True


def test_weekly_top3_answer_rejects_unlisted_or_wrong_sized_selection(db):
    run = _run(db)
    decision = _stage_weekly_top3_decision(db, run)

    with pytest.raises(InvalidDecisionAnswer, match="只能从候选项中选择"):
        answer_decision(
            db,
            run.id,
            decision.id,
            ["UnknownProject"],
            "local-operator",
        )
    with pytest.raises(InvalidDecisionAnswer, match="恰好选择 1 项"):
        answer_decision(
            db,
            run.id,
            decision.id,
            ["AlphaTie", "ZuluTie"],
            "local-operator",
        )


def test_weekly_duplicate_answer_is_idempotent_but_rejects_a_different_replay(db):
    run = _run(db)
    decision = _stage_weekly_duplicate_decision(db, run)

    first = answer_decision(
        db,
        run.id,
        decision.id,
        "确认按自然人计1人",
        "local-operator",
    )
    repeated = answer_decision(
        db,
        run.id,
        decision.id,
        "确认按自然人计1人",
        "local-operator",
    )

    assert repeated.id == first.id
    with pytest.raises(DecisionAnswerConflict, match="different answer"):
        answer_decision(
            db,
            run.id,
            decision.id,
            "其他答案",
            "local-operator",
        )


def test_weekly_duplicate_confirmation_remains_available_after_daily_publish(db):
    run = _run(db)
    decision = _stage_weekly_duplicate_decision(db, run)
    db.add(
        RunReportTarget(
            run_id=run.id,
            report_kind="daily",
            status=TargetStatus.published.value,
        )
    )
    db.commit()

    answered = answer_decision(
        db,
        run.id,
        decision.id,
        "确认按自然人计1人",
        "local-operator",
    )

    assert answered.status == "answered"


def test_weekly_top3_selection_remains_available_after_daily_publish(db):
    run = _run(db)
    decision = _stage_weekly_top3_decision(db, run)
    db.add(
        RunReportTarget(
            run_id=run.id,
            report_kind="daily",
            status=TargetStatus.published.value,
        )
    )
    db.commit()

    answered = answer_decision(
        db,
        run.id,
        decision.id,
        ["ZuluTie"],
        "local-operator",
    )

    assert answered.status == "answered"
    assert decode_json_text(answered.answer) == ["ZuluTie"]
