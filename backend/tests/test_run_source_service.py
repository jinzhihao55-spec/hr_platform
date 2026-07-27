"""Run source ingestion is atomic, minimal, and deletes raw upload bytes."""

import asyncio
from datetime import date
from io import BytesIO

import pandas as pd
import pytest
from fastapi import UploadFile

from app.core.exceptions import InputMissingError, RunInputFrozenError, SchemaMismatchError
from app.models.facts import PersonIdentity
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)
from app.repositories import fact_repo
from app.repositories.fact_repo import PublishedRunMutationError
from app.services import run_source_service
from app.services.run_source_service import RunSourceService


def _run(db) -> ReportRun:
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.created.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.commit()
    return run


def _xlsx_upload(rows: list[dict], filename: str) -> UploadFile:
    stream = BytesIO()
    pd.DataFrame(rows).to_excel(stream, index=False)
    stream.seek(0)
    return UploadFile(filename=filename, file=stream)


def _personnel_upload(*, filename: str = "人员表.xlsx") -> UploadFile:
    return _xlsx_upload(
        [
            {
                "员工类型": "正式员工",
                "工号": "FAKE-E1",
                "中文名": "测试甲",
                "员工状态": "在职",
                "入职日期": "2026-07-01",
                "事业部编号": "FAKE-BU1",
                "证件类型": "身份证",
                "证件号码": "FAKE-CERT-SAME",
            },
            {
                "员工类型": "正式员工",
                "工号": "FAKE-E2",
                "中文名": "测试甲",
                "员工状态": "在职",
                "入职日期": "2026-07-08",
                "事业部编号": "FAKE-BU1",
                "证件类型": "居民身份证",
                "证件号码": "fake-cert-same",
            },
        ],
        filename,
    )


def test_personnel_stage_deduplicates_identity_without_collapsing_employment(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")

    result = asyncio.run(
        service.ingest(run.id, SourceType.personnel, _personnel_upload())
    )

    facts = fact_repo.list_employment_facts(db, run.id)
    assert result.row_count == 2
    assert facts[0].person_id == facts[1].person_id
    assert {fact.employee_no for fact in facts} == {"FAKE-E1", "FAKE-E2"}
    assert db.query(PersonIdentity).count() == 1
    assert "certificate_number" not in result.persisted_fields
    assert "证件号" not in result.persisted_fields
    source = db.query(RunSource).filter_by(run_id=run.id).one()
    assert source.original_extension == ".xlsx"
    assert "人员表" not in source.original_extension


def test_failed_parse_preserves_existing_facts_and_source_metadata(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    asyncio.run(service.ingest(run.id, SourceType.personnel, _personnel_upload()))
    before_facts = [fact.id for fact in fact_repo.list_employment_facts(db, run.id)]
    before_source = db.query(RunSource).filter_by(run_id=run.id).one()
    before_hash = before_source.sha256
    malformed = _xlsx_upload(
        [{"无关字段": "FAKE", "私人邮箱": "fake@example.invalid"}],
        "broken.xlsx",
    )

    with pytest.raises(SchemaMismatchError):
        asyncio.run(service.ingest(run.id, SourceType.personnel, malformed))

    assert [fact.id for fact in fact_repo.list_employment_facts(db, run.id)] == before_facts
    source = db.query(RunSource).filter_by(run_id=run.id).one()
    assert source.sha256 == before_hash


def test_temporary_upload_directory_is_removed_on_success(db, tmp_path, monkeypatch):
    run = _run(db)
    temp_dir = tmp_path / "one-run-upload"
    monkeypatch.setattr(
        run_source_service.tempfile,
        "mkdtemp",
        lambda prefix: str(temp_dir.mkdir() or temp_dir),
    )
    service = RunSourceService(db, person_key_secret="test-secret")

    asyncio.run(service.ingest(run.id, SourceType.personnel, _personnel_upload()))

    assert not temp_dir.exists()


def test_personnel_image_is_rejected_before_vision_processing(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    upload = UploadFile(filename="人员表.png", file=BytesIO(b"fake-image"))

    with pytest.raises(InputMissingError, match="Excel"):
        asyncio.run(service.ingest(run.id, SourceType.personnel, upload))


def test_release_image_parse_failure_returns_actionable_input_error(db, monkeypatch):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    upload = UploadFile(filename="OA_Release.png", file=BytesIO(b"fake-image"))

    def fail_conversion(*_args, **_kwargs):
        raise RuntimeError("视觉 LLM 未配置，请配置模型或改传 Excel")

    monkeypatch.setattr(
        run_source_service.image_parser,
        "convert_to_xlsx",
        fail_conversion,
    )

    with pytest.raises(InputMissingError) as exc_info:
        asyncio.run(service.ingest(run.id, SourceType.release, upload))

    assert "视觉 LLM 未配置" in exc_info.value.message
    assert exc_info.value.detail == {
        "source": "release",
        "code": "image_parse_failed",
    }


def test_unknown_run_is_rejected_without_persisting_source(db):
    service = RunSourceService(db, person_key_secret="test-secret")

    with pytest.raises(LookupError, match="Run"):
        asyncio.run(
            service.ingest("missing-run", SourceType.personnel, _personnel_upload())
        )

    assert db.query(RunSource).count() == 0


def test_published_target_freezes_shared_source_facts(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    asyncio.run(service.ingest(run.id, SourceType.personnel, _personnel_upload()))
    before_facts = [fact.id for fact in fact_repo.list_employment_facts(db, run.id)]
    before_hash = db.query(RunSource).filter_by(run_id=run.id).one().sha256
    db.add(
        RunReportTarget(
            run_id=run.id,
            report_kind="daily",
            status=TargetStatus.published.value,
        )
    )
    db.commit()

    with pytest.raises(PublishedRunMutationError, match="new Run"):
        asyncio.run(service.ingest(run.id, SourceType.personnel, _personnel_upload()))

    assert [fact.id for fact in fact_repo.list_employment_facts(db, run.id)] == before_facts
    assert db.query(RunSource).filter_by(run_id=run.id).one().sha256 == before_hash


def test_finalized_run_rejects_source_replacement_and_requires_new_run(db):
    run = _run(db)
    run.status = RunStatus.ready.value
    run.source_bundle_hash = "f" * 64
    db.commit()

    with pytest.raises(RunInputFrozenError, match="new Run"):
        asyncio.run(
            RunSourceService(db, person_key_secret="test-secret").ingest(
                run.id, SourceType.personnel, _personnel_upload()
            )
        )

    assert db.query(RunSource).count() == 0
