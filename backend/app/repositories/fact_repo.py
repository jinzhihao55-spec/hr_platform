"""Atomic replacement and lookup helpers for run-scoped canonical facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.identity import DerivedIdentity
from app.models.facts import (
    EmploymentFact,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    RunDecision,
)
from app.models.runs import RunReportTarget, SourceType, TargetStatus


class PublishedRunMutationError(RuntimeError):
    pass


_SOURCE_MODELS = {
    SourceType.personnel: EmploymentFact,
    SourceType.resignation: ResignationFact,
    SourceType.release: ReleaseFact,
    SourceType.recruitment: RecruitmentSnapshot,
}

_SAFE_FIELDS = {
    SourceType.personnel: {
        "source_row_no",
        "identity",
        "employee_no",
        "display_name",
        "employee_type",
        "status",
        "entry_date",
        "resign_date",
        "business_unit",
        "business_unit_no",
        "project_code",
        "project_name",
        "contract_dates",
        "first_visible_dates",
    },
    SourceType.resignation: {
        "source_row_no",
        "identity",
        "process_no",
        "employee_no",
        "process_status",
        "application_date",
        "last_working_day",
        "resignation_type",
        "first_visible_date",
    },
    SourceType.release: {
        "source_row_no",
        "identity",
        "order_no",
        "employee_no",
        "application_date",
        "last_working_day",
        "process_status",
        "first_visible_date",
        "row5_classification",
        "row30_classification",
        "ocr_confidence",
    },
    SourceType.recruitment: {
        "source_row_no",
        "report_date",
        "is_total_row",
        "previous_month_offer_current_month_onboard",
        "current_month_offer_current_month_onboard",
        "recognized_labels",
        "ocr_confidence",
    },
}

_FORBIDDEN_FIELDS = {
    "certificate_number",
    "certificate_type",
    "证件号",
    "证件号码",
    "证件类型",
}


def _source_type(value: str | SourceType) -> SourceType:
    return value if isinstance(value, SourceType) else SourceType(value)


def persisted_fields_for(source_type: str | SourceType) -> tuple[str, ...]:
    source = _source_type(source_type)
    return tuple(sorted(_SAFE_FIELDS[source] - {"identity"}))


def assert_run_facts_mutable(db: Session, run_id: str) -> None:
    published_target_id = db.scalar(
        select(RunReportTarget.id)
        .where(
            RunReportTarget.run_id == run_id,
            RunReportTarget.status == TargetStatus.published.value,
            RunReportTarget.is_deleted == 0,
        )
        .limit(1)
    )
    if published_target_id is not None:
        raise PublishedRunMutationError(
            "published report targets freeze shared facts; create a new Run"
        )


def _get_or_create_person(
    db: Session, identity: DerivedIdentity | None
) -> PersonIdentity | None:
    if identity is None:
        return None
    person = db.scalar(
        select(PersonIdentity).where(PersonIdentity.person_key == identity.person_key)
    )
    if person is None:
        person = PersonIdentity(
            person_key=identity.person_key,
            key_version=identity.key_version,
            match_confidence=identity.confidence,
            identity_namespace=identity.namespace,
        )
        db.add(person)
        db.flush()
    return person


def replace_source_facts(
    db: Session,
    run_id: str,
    source_type: str | SourceType,
    facts: Sequence[Mapping[str, Any]],
) -> None:
    assert_run_facts_mutable(db, run_id)
    source = _source_type(source_type)
    model = _SOURCE_MODELS[source]
    db.execute(delete(model).where(model.run_id == run_id))

    for fact in facts:
        keys = set(fact)
        forbidden = keys & _FORBIDDEN_FIELDS
        if forbidden:
            raise ValueError(
                f"certificate plaintext fields cannot be persisted: {sorted(forbidden)}"
            )
        unexpected = keys - _SAFE_FIELDS[source]
        if unexpected:
            raise ValueError(
                f"unexpected {source.value} fact fields: {sorted(unexpected)}"
            )
        payload = {key: value for key, value in fact.items() if key != "identity"}
        person = _get_or_create_person(db, fact.get("identity"))
        if person is not None:
            payload["person_id"] = person.id
        db.add(model(run_id=run_id, **payload))
    db.flush()


def replace_source_review_decisions(
    db: Session,
    run_id: str,
    source_type: str | SourceType,
    decisions: Sequence[Mapping[str, Any]],
) -> None:
    assert_run_facts_mutable(db, run_id)
    source = _source_type(source_type)
    prefix = f"source:{source.value}:"
    db.execute(
        delete(RunDecision).where(
            RunDecision.run_id == run_id,
            RunDecision.fact_ref.like(f"{prefix}%"),
        )
    )
    for decision in decisions:
        fact_ref = str(decision.get("fact_ref") or "")
        if not fact_ref.startswith(prefix):
            raise ValueError(f"decision fact_ref must start with {prefix}")
        db.add(RunDecision(run_id=run_id, **dict(decision)))
    db.flush()


def list_employment_facts(db: Session, run_id: str) -> list[EmploymentFact]:
    return list(
        db.scalars(
            select(EmploymentFact)
            .where(EmploymentFact.run_id == run_id)
            .order_by(EmploymentFact.source_row_no)
        ).all()
    )


def list_resignation_facts(db: Session, run_id: str) -> list[ResignationFact]:
    return list(
        db.scalars(
            select(ResignationFact)
            .where(ResignationFact.run_id == run_id)
            .order_by(ResignationFact.source_row_no)
        ).all()
    )


def list_release_facts(db: Session, run_id: str) -> list[ReleaseFact]:
    return list(
        db.scalars(
            select(ReleaseFact)
            .where(ReleaseFact.run_id == run_id)
            .order_by(ReleaseFact.source_row_no)
        ).all()
    )


def list_recruitment_snapshots(
    db: Session, run_id: str
) -> list[RecruitmentSnapshot]:
    return list(
        db.scalars(
            select(RecruitmentSnapshot)
            .where(RecruitmentSnapshot.run_id == run_id)
            .order_by(RecruitmentSnapshot.source_row_no)
        ).all()
    )
