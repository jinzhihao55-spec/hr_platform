"""Run-scoped canonical facts, events, decisions, and validation evidence."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin, uuid_pk


def encode_json_text(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def decode_json_text(value: str | None) -> Any:
    return None if value is None else json.loads(value)


class PersonIdentity(AuditMixin, Base):
    __tablename__ = "person_identities"
    __table_args__ = (
        UniqueConstraint("person_key", name="uq_person_identity_key"),
    )

    id: Mapped[str] = uuid_pk()
    person_key: Mapped[str] = mapped_column(String(64), index=True)
    key_version: Mapped[str] = mapped_column(String(16))
    match_confidence: Mapped[str] = mapped_column(String(32))
    identity_namespace: Mapped[str] = mapped_column(String(32))


class EmploymentFact(AuditMixin, Base):
    __tablename__ = "employment_facts"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_row_no", name="uq_employment_fact_run_row"
        ),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    source_row_no: Mapped[int] = mapped_column(Integer)
    person_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("person_identities.id", ondelete="RESTRICT"), index=True
    )
    employee_no: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employee_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resign_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    business_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_unit_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contract_dates: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_visible_dates: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResignationFact(AuditMixin, Base):
    __tablename__ = "resignation_facts"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "process_no", name="uq_resignation_fact_run_process"
        ),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    source_row_no: Mapped[int] = mapped_column(Integer)
    process_no: Mapped[str] = mapped_column(String(100))
    person_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("person_identities.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    employee_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    process_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    application_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    resignation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_visible_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ReleaseFact(AuditMixin, Base):
    __tablename__ = "release_facts"
    __table_args__ = (
        UniqueConstraint("run_id", "order_no", name="uq_release_fact_run_order"),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    source_row_no: Mapped[int] = mapped_column(Integer)
    order_no: Mapped[str] = mapped_column(String(100))
    person_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("person_identities.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    employee_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    application_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    process_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_visible_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    row5_classification: Mapped[str | None] = mapped_column(String(24), nullable=True)
    row30_classification: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ocr_confidence: Mapped[str | None] = mapped_column(String(24), nullable=True)


class RecruitmentSnapshot(AuditMixin, Base):
    __tablename__ = "recruitment_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_row_no", name="uq_recruitment_snapshot_run_row"
        ),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    source_row_no: Mapped[int] = mapped_column(Integer)
    report_date: Mapped[date] = mapped_column(Date)
    is_total_row: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_month_offer_current_month_onboard: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    current_month_offer_current_month_onboard: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    recognized_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[str | None] = mapped_column(String(24), nullable=True)


class FactEvent(AuditMixin, Base):
    __tablename__ = "fact_events"
    __table_args__ = (
        UniqueConstraint("run_id", "event_key", name="uq_fact_event_run_key"),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(32))
    person_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("person_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    employment_ref: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employment_facts.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(24))
    source_event_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_visible_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    minimal_payload: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunDecision(AuditMixin, Base):
    __tablename__ = "run_decisions"

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    report_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_code: Mapped[str] = mapped_column(String(64))
    fact_ref: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    operator_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RunValidation(AuditMixin, Base):
    __tablename__ = "run_validations"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "report_kind",
            "validation_code",
            name="uq_run_validation_code",
        ),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    report_kind: Mapped[str] = mapped_column(String(16))
    validation_code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[str] = mapped_column(Text)
