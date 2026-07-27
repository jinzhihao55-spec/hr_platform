"""Canonical facts preserve HR reviewability without certificate plaintext."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.facts import (
    EmploymentFact,
    FactEvent,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    RunDecision,
    RunValidation,
    decode_json_text,
    encode_json_text,
)
from app.models.runs import ReportRun, RunStatus


def _run(db) -> ReportRun:
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.parsing.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    return run


def _person(db, key: str = "a" * 64) -> PersonIdentity:
    person = PersonIdentity(
        person_key=key,
        key_version="v1",
        match_confidence="certificate",
        identity_namespace="certificate",
    )
    db.add(person)
    db.flush()
    return person


def test_same_person_can_have_multiple_employment_numbers(db):
    run = _run(db)
    person = _person(db)
    db.add_all(
        [
            EmploymentFact(
                run_id=run.id,
                source_row_no=2,
                person_id=person.id,
                employee_no="FAKE-E1",
                display_name="测试甲",
                employee_type="正式员工",
            ),
            EmploymentFact(
                run_id=run.id,
                source_row_no=3,
                person_id=person.id,
                employee_no="FAKE-E2",
                display_name="测试甲",
                employee_type="正式员工",
            ),
        ]
    )

    db.commit()

    facts = db.query(EmploymentFact).order_by(EmploymentFact.source_row_no).all()
    assert {fact.employee_no for fact in facts} == {"FAKE-E1", "FAKE-E2"}
    assert {fact.person_id for fact in facts} == {person.id}


def test_person_key_is_unique(db):
    _person(db)
    db.commit()
    db.add(
        PersonIdentity(
            person_key="a" * 64,
            key_version="v1",
            match_confidence="certificate",
            identity_namespace="certificate",
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_fact_event_key_is_unique_within_run(db):
    run = _run(db)
    db.add(
        FactEvent(
            run_id=run.id,
            event_key="event-1",
            event_type="hire",
            source_type="personnel",
        )
    )
    db.commit()
    db.add(
        FactEvent(
            run_id=run.id,
            event_key="event-1",
            event_type="hire",
            source_type="personnel",
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_source_business_keys_are_unique_within_run(db):
    run = _run(db)
    person = _person(db)
    db.add_all(
        [
            ResignationFact(
                run_id=run.id,
                source_row_no=2,
                process_no="FAKE-P1",
                person_id=person.id,
                employee_no="FAKE-E1",
            ),
            ReleaseFact(
                run_id=run.id,
                source_row_no=2,
                order_no="FAKE-O1",
                person_id=person.id,
                employee_no="FAKE-E1",
            ),
            RecruitmentSnapshot(
                run_id=run.id,
                source_row_no=2,
                report_date=date(2026, 7, 8),
            ),
        ]
    )
    db.commit()
    db.add(
        ResignationFact(
            run_id=run.id,
            source_row_no=3,
            process_no="FAKE-P1",
            person_id=person.id,
            employee_no="FAKE-E1",
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_fact_models_never_define_certificate_plaintext_columns():
    models = (
        PersonIdentity,
        EmploymentFact,
        ResignationFact,
        ReleaseFact,
        RecruitmentSnapshot,
        FactEvent,
        RunDecision,
        RunValidation,
    )
    forbidden = {
        "certificate_number",
        "certificate_type",
        "证件号",
        "证件号码",
        "证件类型",
    }

    for model in models:
        assert forbidden.isdisjoint(model.__table__.columns.keys())


def test_json_text_helpers_are_deterministic_and_round_trip_unicode():
    value = {"规则": "Q9", "refs": ["fact-2", "fact-1"], "count": 2}

    encoded = encode_json_text(value)

    assert encoded == '{"count":2,"refs":["fact-2","fact-1"],"规则":"Q9"}'
    assert decode_json_text(encoded) == value
    assert decode_json_text(None) is None


def test_decisions_and_validations_can_be_scoped_per_report_kind(db):
    run = _run(db)
    db.add_all(
        [
            RunDecision(
                run_id=run.id,
                report_kind=None,
                decision_code="identity_conflict",
                fact_ref="employment:2",
                question="请选择关联方式",
                options=encode_json_text(["keep_separate", "same_person"]),
                status="pending",
            ),
            RunValidation(
                run_id=run.id,
                report_kind="weekly",
                validation_code="multiple_active_employments",
                severity="REVIEW",
                outcome="FAIL",
                message="存在多个有效任职记录",
                evidence_refs=encode_json_text(["employment:2", "employment:3"]),
            ),
        ]
    )

    db.commit()

    decision = db.query(RunDecision).one()
    validation = db.query(RunValidation).one()
    assert decision.report_kind is None
    assert validation.report_kind == "weekly"


def test_recruitment_snapshot_preserves_total_row_semantics(db):
    run = _run(db)
    db.add(
        RecruitmentSnapshot(
            run_id=run.id,
            source_row_no=3,
            report_date=date(2026, 7, 8),
            is_total_row=True,
        )
    )

    db.commit()

    assert db.query(RecruitmentSnapshot).one().is_total_row is True
