"""Run-scoped workflow records for staged, previewed, and published reports."""

from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin, uuid_pk


class RunStatus(str, enum.Enum):
    created = "created"
    parsing = "parsing"
    needs_review = "needs_review"
    ready = "ready"
    deduplicated = "deduplicated"
    failed = "failed"


class SourceType(str, enum.Enum):
    personnel = "personnel"
    resignation = "resignation"
    release = "release"
    recruitment = "recruitment"


class TargetStatus(str, enum.Enum):
    draft = "draft"
    calculating = "calculating"
    needs_review = "needs_review"
    ready = "ready"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    superseded = "superseded"


class ReportRun(AuditMixin, Base):
    """One immutable input/baseline attempt for a report date."""

    __tablename__ = "report_runs"
    __table_args__ = (
        UniqueConstraint(
            "report_date",
            "rule_version",
            "source_bundle_hash",
            name="uq_report_run_fingerprint",
        ),
    )

    id: Mapped[str] = uuid_pk()
    report_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    rule_version: Mapped[str] = mapped_column(String(64))
    source_bundle_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    baseline_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    canonical_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("report_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)

class RunSource(AuditMixin, Base):
    """Metadata and parse outcome for one explicit source in a Run."""

    __tablename__ = "run_sources"
    __table_args__ = (
        UniqueConstraint("run_id", "source_type", name="uq_run_source_type"),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_status: Mapped[str] = mapped_column(String(24))
    original_extension: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RunReportTarget(AuditMixin, Base):
    """Daily and weekly lifecycle state isolated within the same Run."""

    __tablename__ = "run_report_targets"
    __table_args__ = (
        UniqueConstraint("run_id", "report_kind", name="uq_run_report_target_kind"),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    report_kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), index=True)
    preview_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
