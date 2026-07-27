"""Immutable published report versions, artifacts, and recovery attempts."""

from __future__ import annotations

from datetime import date, datetime

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
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin, uuid_pk


class PublishedReport(AuditMixin, Base):
    __tablename__ = "published_reports"
    __table_args__ = (
        UniqueConstraint(
            "report_kind",
            "period_start",
            "period_end",
            "version",
            name="uq_published_report_period_version",
        ),
        UniqueConstraint(
            "run_id", "report_kind", name="uq_published_report_run_kind"
        ),
    )

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="RESTRICT"), index=True
    )
    report_kind: Mapped[str] = mapped_column(String(16), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    snapshot_json: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql")
    )
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    baseline_report_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("published_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by: Mapped[str] = mapped_column(String(100))
    published_at: Mapped[datetime] = mapped_column(DateTime)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReportArtifact(AuditMixin, Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "artifact_kind", name="uq_report_artifact_kind"
        ),
    )

    id: Mapped[str] = uuid_pk()
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("published_reports.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_kind: Mapped[str] = mapped_column(String(32))
    protected_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)


class PublicationAttempt(AuditMixin, Base):
    __tablename__ = "publication_attempts"

    id: Mapped[str] = uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_runs.id", ondelete="CASCADE"), index=True
    )
    report_kind: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    staging_path: Mapped[str] = mapped_column(String(1024))
    final_path: Mapped[str] = mapped_column(String(1024))
    report_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("published_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
