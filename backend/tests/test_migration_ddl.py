"""迁移 DDL 必须存在并覆盖 ORM 新表的全部列，防止建表脚本与 ORM 漂移。"""
from pathlib import Path

from sqlalchemy.dialects import mysql

from app.models.inputs import EmployeeSnapshot, SourceUploadRecord
from app.models.facts import (
    EmploymentFact,
    FactEvent,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    RunDecision,
    RunValidation,
)
from app.models.reports import MonthOpeningBaseline, TenureSnapshotMetric, WeeklyReport
from app.models.publication import PublicationAttempt, PublishedReport, ReportArtifact
from app.models.runs import ReportRun, RunReportTarget, RunSource

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "migrations"
MIGRATION = _MIGRATIONS_DIR / "2026-07-12_add_snapshot_tables.sql"
UPLOAD_MIGRATION = _MIGRATIONS_DIR / "2026-07-12_add_upload_records.sql"
MONTH_OPENING_MIGRATION = _MIGRATIONS_DIR / "2026-07-12_add_month_opening_baselines.sql"
RUN_MIGRATION = _MIGRATIONS_DIR / "2026-07-15_add_report_runs.sql"
FACT_MIGRATION = _MIGRATIONS_DIR / "2026-07-15_add_run_facts.sql"
PUBLICATION_MIGRATION = _MIGRATIONS_DIR / "2026-07-15_add_publications.sql"
PUBLICATION_SNAPSHOT_MIGRATION = (
    _MIGRATIONS_DIR / "2026-07-16_expand_publication_snapshot.sql"
)


def test_migration_covers_new_snapshot_tables():
    assert MIGRATION.is_file(), "缺少 employee_snapshots/tenure_snapshot_metrics 迁移脚本"
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for model in (EmployeeSnapshot, TenureSnapshotMetric):
        assert model.__tablename__ in sql, f"迁移未建表 {model.__tablename__}"
        for column in model.__table__.columns:
            assert column.name.lower() in sql, (
                f"迁移缺少列 {model.__tablename__}.{column.name}"
            )


def test_weekly_reports_has_unique_week_and_bu_contract():
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in WeeklyReport.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("week_start", "bu") in unique_column_sets

    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "uq_weekly_report_week_bu" in sql
    assert "delete" in sql and "weekly_reports" in sql


def test_upload_record_migration_covers_orm_columns():
    assert UPLOAD_MIGRATION.is_file(), "缺少 source_upload_records 迁移脚本"
    sql = UPLOAD_MIGRATION.read_text(encoding="utf-8").lower()
    assert SourceUploadRecord.__tablename__ in sql
    for column in SourceUploadRecord.__table__.columns:
        assert column.name.lower() in sql, f"迁移缺少列 {column.name}"
    assert "uq_source_upload_day" in sql


def test_weekly_unique_guard_checks_index_columns_not_name():
    """权威 schema 里唯一键叫 uk_week_bu；迁移必须按索引列（week_start,bu）
    判定是否已存在等价唯一索引，按名字判会重复建索引。"""
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "non_unique = 0" in sql
    assert "group_concat(column_name" in sql
    assert "'week_start,bu'" in sql


def test_month_opening_migration_covers_orm_columns():
    assert MONTH_OPENING_MIGRATION.is_file(), "缺少 month_opening_baselines 迁移脚本"
    sql = MONTH_OPENING_MIGRATION.read_text(encoding="utf-8").lower()
    assert MonthOpeningBaseline.__tablename__ in sql
    for column in MonthOpeningBaseline.__table__.columns:
        assert column.name.lower() in sql, f"迁移缺少列 {column.name}"
    assert "uq_month_opening_report_month" in sql


def test_run_migration_covers_orm_columns_and_unique_contracts():
    assert RUN_MIGRATION.is_file(), "缺少 report run 迁移脚本"
    sql = RUN_MIGRATION.read_text(encoding="utf-8").lower()
    for model in (ReportRun, RunSource, RunReportTarget):
        assert model.__tablename__ in sql, f"迁移未建表 {model.__tablename__}"
        for column in model.__table__.columns:
            assert column.name.lower() in sql, (
                f"迁移缺少列 {model.__tablename__}.{column.name}"
            )
    assert "uq_report_run_fingerprint" in sql
    assert "uq_run_source_type" in sql
    assert "uq_run_report_target_kind" in sql


def test_fact_migration_covers_orm_columns_and_unique_contracts():
    assert FACT_MIGRATION.is_file(), "缺少 canonical fact 迁移脚本"
    sql = FACT_MIGRATION.read_text(encoding="utf-8").lower()
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
    for model in models:
        assert model.__tablename__ in sql, f"迁移未建表 {model.__tablename__}"
        for column in model.__table__.columns:
            assert column.name.lower() in sql, (
                f"迁移缺少列 {model.__tablename__}.{column.name}"
            )
    for constraint in (
        "uq_person_identity_key",
        "uq_employment_fact_run_row",
        "uq_resignation_fact_run_process",
        "uq_release_fact_run_order",
        "uq_recruitment_snapshot_run_row",
        "uq_fact_event_run_key",
        "uq_run_validation_code",
    ):
        assert constraint in sql


def test_publication_migration_covers_orm_columns_and_unique_contracts():
    assert PUBLICATION_MIGRATION.is_file(), "缺少 publication 迁移脚本"
    sql = PUBLICATION_MIGRATION.read_text(encoding="utf-8").lower()
    for model in (PublishedReport, ReportArtifact, PublicationAttempt):
        assert model.__tablename__ in sql, f"迁移未建表 {model.__tablename__}"
        for column in model.__table__.columns:
            assert column.name.lower() in sql, (
                f"迁移缺少列 {model.__tablename__}.{column.name}"
            )
    assert "uq_published_report_period_version" in sql
    assert "uq_report_artifact_kind" in sql


def test_publication_snapshot_uses_longtext_and_has_upgrade_migration():
    column_type = PublishedReport.__table__.c.snapshot_json.type.compile(
        dialect=mysql.dialect()
    )
    assert str(column_type).upper() == "LONGTEXT"

    create_sql = PUBLICATION_MIGRATION.read_text(encoding="utf-8").lower()
    assert "snapshot_json      longtext" in create_sql

    assert PUBLICATION_SNAPSHOT_MIGRATION.is_file()
    upgrade_sql = PUBLICATION_SNAPSHOT_MIGRATION.read_text(encoding="utf-8").lower()
    assert "alter table published_reports" in upgrade_sql
    assert "snapshot_json longtext" in upgrade_sql
