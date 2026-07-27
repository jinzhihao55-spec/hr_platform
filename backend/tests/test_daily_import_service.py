"""定稿日报导入后的级联状态必须对调用方可见。"""
import asyncio
from datetime import date
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
import pytest
from sqlalchemy import select

from app.core.exceptions import DailyImportError
from app.models.facts import EmploymentFact, FactEvent, PersonIdentity, RunDecision, decode_json_text
from app.models.publication import PublishedReport, ReportArtifact
from app.models.reports import DailyReport
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)
from app.repositories import publication_repo
from app.repositories import report_repo
from app.schemas.api import ImportDailyResponse
from app.services import daily_import_service, report_service, run_workflow_service


def _baseline_rows() -> dict[int, dict]:
    return {
        2: {"value": 3, "label": "今日入职"},
        3: {"value": 0, "label": "今日离职"},
        7: {"value": 3, "label": "今日净增"},
        8: {"value": 26, "label": "MTD入职"},
        9: {"value": 2, "label": "MTD离职"},
        12: {"value": 24, "label": "MTD净增减人数"},
        13: {"value": 185, "label": "YTD入职"},
        14: {"value": 125, "label": "YTD离职"},
        17: {"value": 60, "label": "YTD净增减人数"},
        30: {"value": 0, "label": "Release数-截至月底"},
    }


def _tenure_rows() -> list[dict]:
    return [{
        "slot": "BU_A",
        "business_unit": "NBJO",
        "ytd_leavers": 125,
        "avg_tenure_years": 1.85,
    }]


def test_imported_daily_is_an_immutable_baseline_for_the_next_run(
    db, monkeypatch, tmp_path
):
    report_date = date(2026, 7, 7)
    monkeypatch.setattr(
        daily_import_service, "parse_daily_workbook",
        lambda *_args, **_kwargs: (_baseline_rows(), report_date),
    )
    monkeypatch.setattr(
        daily_import_service, "parse_tenure_workbook",
        lambda *_args, **_kwargs: _tenure_rows(),
    )
    monkeypatch.setattr(daily_import_service.settings, "output_dir", str(tmp_path))
    upload = UploadFile(filename="daily.xlsx", file=BytesIO(b"approved workbook"))

    result = asyncio.run(
        daily_import_service.import_daily(
            db,
            report_date,
            upload,
            regenerate=False,
            imported_by="qa-operator",
        )
    )

    baseline = publication_repo.current_daily(db, report_date)
    assert baseline is not None
    assert result["baseline_report_id"] == baseline.id
    assert baseline.published_by == "qa-operator"
    snapshot = decode_json_text(baseline.snapshot_json)
    assert snapshot["rows"]["8"]["value"] == 26
    assert snapshot["tenure"]["rows"][0]["ytd_leavers"] == 125
    baseline_run = db.get(ReportRun, baseline.run_id)
    assert baseline_run.status == RunStatus.ready.value
    target = db.scalar(
        select(RunReportTarget).where(
            RunReportTarget.run_id == baseline_run.id,
            RunReportTarget.report_kind == "daily",
        )
    )
    assert target.status == TargetStatus.published.value
    artifact = db.scalar(
        select(ReportArtifact).where(ReportArtifact.report_id == baseline.id)
    )
    assert artifact.artifact_kind == "excel"
    assert Path(artifact.protected_path).read_bytes() == b"approved workbook"

    next_run, _ = run_workflow_service.create_or_get_run(
        db, date(2026, 7, 8), create_new=True
    )
    assert next_run.baseline_report_id == baseline.id


def test_reimported_daily_supersedes_the_previous_baseline_version(
    db, monkeypatch, tmp_path
):
    report_date = date(2026, 7, 7)
    monkeypatch.setattr(
        daily_import_service, "parse_daily_workbook",
        lambda *_args, **_kwargs: (_baseline_rows(), report_date),
    )
    monkeypatch.setattr(
        daily_import_service, "parse_tenure_workbook",
        lambda *_args, **_kwargs: _tenure_rows(),
    )
    monkeypatch.setattr(daily_import_service.settings, "output_dir", str(tmp_path))

    first = asyncio.run(
        daily_import_service.import_daily(
            db,
            report_date,
            UploadFile(filename="first.xlsx", file=BytesIO(b"first workbook")),
            regenerate=False,
        )
    )
    second = asyncio.run(
        daily_import_service.import_daily(
            db,
            report_date,
            UploadFile(filename="second.xlsx", file=BytesIO(b"second workbook")),
            regenerate=False,
        )
    )

    reports = db.scalars(
        select(PublishedReport)
        .where(PublishedReport.report_kind == "daily")
        .order_by(PublishedReport.version)
    ).all()
    assert [report.version for report in reports] == [1, 2]
    assert [report.is_current for report in reports] == [False, True]
    assert first["baseline_report_id"] == reports[0].id
    assert second["baseline_report_id"] == reports[1].id


def test_provisional_run_attaches_a_baseline_imported_after_run_creation(
    db, monkeypatch, tmp_path
):
    provisional, _ = run_workflow_service.create_or_get_run(
        db, date(2026, 7, 8), create_new=True
    )
    assert provisional.baseline_report_id is None
    monkeypatch.setattr(
        daily_import_service, "parse_daily_workbook",
        lambda *_args, **_kwargs: (_baseline_rows(), date(2026, 7, 7)),
    )
    monkeypatch.setattr(
        daily_import_service, "parse_tenure_workbook",
        lambda *_args, **_kwargs: _tenure_rows(),
    )
    monkeypatch.setattr(daily_import_service.settings, "output_dir", str(tmp_path))
    result = asyncio.run(
        daily_import_service.import_daily(
            db,
            date(2026, 7, 7),
            UploadFile(filename="baseline.xlsx", file=BytesIO(b"approved")),
            regenerate=False,
        )
    )

    refreshed, readiness = run_workflow_service.refresh_run_state(
        db, provisional.id
    )

    assert refreshed.baseline_report_id == result["baseline_report_id"]
    assert readiness["baseline_missing"] is False


def test_failed_protected_copy_does_not_leave_a_false_published_directory(
    db, monkeypatch, tmp_path
):
    report_date = date(2026, 7, 7)
    monkeypatch.setattr(
        daily_import_service, "parse_daily_workbook",
        lambda *_args, **_kwargs: (_baseline_rows(), report_date),
    )
    monkeypatch.setattr(
        daily_import_service, "parse_tenure_workbook",
        lambda *_args, **_kwargs: _tenure_rows(),
    )
    monkeypatch.setattr(daily_import_service.settings, "output_dir", str(tmp_path))
    real_copy = daily_import_service.shutil.copyfile

    def fail_protected_copy(source, target):
        if "published" in Path(target).parts:
            raise OSError("synthetic protected storage failure")
        return real_copy(source, target)

    monkeypatch.setattr(daily_import_service.shutil, "copyfile", fail_protected_copy)

    with pytest.raises(OSError, match="protected storage failure"):
        asyncio.run(
            daily_import_service.import_daily(
                db,
                report_date,
                UploadFile(filename="baseline.xlsx", file=BytesIO(b"approved")),
                regenerate=False,
            )
        )

    assert not (tmp_path / "published").exists()
    assert db.scalar(select(PublishedReport)) is None


def test_cascade_exception_returns_partial_and_keeps_import(db, monkeypatch):
    report_date = date(2026, 7, 7)
    rows = {
        2: {"value": 3, "label": "今日入职"},
        3: {"value": 0, "label": "今日离职"},
        7: {"value": 3, "label": "今日净增"},
        8: {"value": 26, "label": "MTD入职"},
        9: {"value": 2, "label": "MTD离职"},
        12: {"value": 24, "label": "MTD净增减人数"},
        13: {"value": 185, "label": "YTD入职"},
        14: {"value": 125, "label": "YTD离职"},
        17: {"value": 60, "label": "YTD净增减人数"},
        30: {"value": 0, "label": "Release数-截至月底"},
    }
    monkeypatch.setattr(
        daily_import_service,
        "parse_daily_workbook",
        lambda *_args, **_kwargs: (rows, report_date),
    )
    monkeypatch.setattr(
        daily_import_service,
        "parse_tenure_workbook",
        lambda *_args, **_kwargs: [{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 125, "avg_tenure_years": 1.85,
        }],
    )
    monkeypatch.setattr(
        report_service,
        "cascade_later",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic cascade failure")),
    )
    upload = UploadFile(filename="daily.xlsx", file=BytesIO(b"placeholder"))

    result = asyncio.run(daily_import_service.import_daily(db, report_date, upload))

    assert result["status"] == "partial"
    assert result["cascade_error"]
    assert "Traceback" not in result["cascade_error"]
    ImportDailyResponse.model_validate(result)
    assert db.scalar(select(DailyReport).where(DailyReport.report_date == report_date)) is not None
    assert report_repo.load_tenure_snapshot(db, report_date)[1][0]["ytd_leavers"] == 125


def test_daily_and_tenure_baseline_are_saved_atomically(db, monkeypatch):
    report_date = date(2026, 7, 7)
    rows = {
        8: {"value": 26, "label": "MTD入职"},
        9: {"value": 2, "label": "MTD离职"},
        13: {"value": 185, "label": "YTD入职"},
        14: {"value": 125, "label": "YTD离职"},
        30: {"value": 0, "label": "Release数-截至月底"},
    }
    monkeypatch.setattr(
        daily_import_service,
        "parse_daily_workbook",
        lambda *_args, **_kwargs: (rows, report_date),
    )
    monkeypatch.setattr(
        daily_import_service,
        "parse_tenure_workbook",
        lambda *_args, **_kwargs: [{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 125, "avg_tenure_years": 1.85,
        }],
    )
    monkeypatch.setattr(
        daily_import_service.report_repo,
        "save_tenure_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database failure")),
    )
    upload = UploadFile(filename="daily.xlsx", file=BytesIO(b"placeholder"))

    with pytest.raises(RuntimeError, match="database failure"):
        asyncio.run(
            daily_import_service.import_daily(
                db, report_date, upload, regenerate=False,
            )
        )

    assert db.scalar(select(DailyReport).where(DailyReport.report_date == report_date)) is None


def test_upload_filename_cannot_escape_tmp_dir(db, monkeypatch, tmp_path):
    """multipart filename 由客户端提供，携带 ../ 时不得写出临时目录。"""
    import tempfile
    from pathlib import Path

    report_date = date(2026, 7, 7)
    base = tmp_path / "a" / "b"
    base.mkdir(parents=True)
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        tempfile, "mkdtemp",
        lambda prefix: real_mkdtemp(prefix=prefix, dir=base),
    )

    seen: dict[str, Path] = {}
    rows = {14: {"value": 125, "label": "YTD离职"}}

    def fake_parse(dest, *_args, **_kwargs):
        seen["dest"] = Path(dest)
        return rows, report_date

    monkeypatch.setattr(daily_import_service, "parse_daily_workbook", fake_parse)
    monkeypatch.setattr(
        daily_import_service,
        "parse_tenure_workbook",
        lambda *_args, **_kwargs: [{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 125, "avg_tenure_years": 1.85,
        }],
    )
    upload = UploadFile(filename="../../evil.xlsx", file=BytesIO(b"placeholder"))

    asyncio.run(daily_import_service.import_daily(db, report_date, upload, regenerate=False))

    assert seen["dest"].name == "evil.xlsx"
    assert ".." not in seen["dest"].parts
    assert not (tmp_path / "a" / "evil.xlsx").exists()


def _stage_initial_run(db, report_date: date) -> ReportRun:
    run, _ = run_workflow_service.create_or_get_run(
        db, report_date, create_new=True
    )
    run.status = RunStatus.needs_review.value
    for index, source in enumerate(SourceType):
        db.add(
            RunSource(
                run_id=run.id,
                source_type=source.value,
                sha256=f"{index + 1}" * 64,
                schema_version=f"{source.value}-v1",
                parser_version="test-v1",
                row_count=1,
                parse_status="parsed",
                original_extension=".xlsx",
            )
        )
    db.commit()
    return run


def test_initial_baseline_reuses_confirmed_run_and_preserves_source_facts(
    db, monkeypatch, tmp_path
):
    report_date = date(2026, 7, 7)
    run = _stage_initial_run(db, report_date)
    person = PersonIdentity(
        person_key="e" * 64,
        key_version="v1",
        match_confidence="employee_no",
        identity_namespace="employee_no",
    )
    db.add(person)
    db.flush()
    employment = EmploymentFact(
        run_id=run.id,
        source_row_no=2,
        person_id=person.id,
        employee_no="FAKE-BASELINE-E1",
        employee_type="正式员工",
        status="在职",
        entry_date=date(2025, 1, 6),
    )
    db.add(employment)
    db.commit()
    monkeypatch.setattr(
        daily_import_service,
        "parse_daily_workbook",
        lambda *_args, **_kwargs: (_baseline_rows(), report_date),
    )
    monkeypatch.setattr(
        daily_import_service,
        "parse_tenure_workbook",
        lambda *_args, **_kwargs: _tenure_rows(),
    )
    monkeypatch.setattr(daily_import_service.settings, "output_dir", str(tmp_path))

    result = asyncio.run(
        daily_import_service.finalize_initial_run_baseline(
            db,
            run.id,
            UploadFile(filename="approved.xlsx", file=BytesIO(b"approved baseline")),
            imported_by="qa-operator",
        )
    )

    baseline = db.get(PublishedReport, result["baseline_report_id"])
    assert baseline.run_id == run.id
    assert baseline.period_end == report_date
    assert db.get(EmploymentFact, employment.id) is not None
    assert db.scalar(
        select(FactEvent).where(
            FactEvent.run_id == run.id,
            FactEvent.event_type == "hire",
        )
    ) is not None
    db.refresh(run)
    assert run.status == RunStatus.ready.value
    assert len(run.source_bundle_hash) == 64
    target = db.scalar(
        select(RunReportTarget).where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.report_kind == "daily",
        )
    )
    assert target.status == TargetStatus.published.value
    next_run, _ = run_workflow_service.create_or_get_run(
        db, date(2026, 7, 8), create_new=True
    )
    assert next_run.baseline_report_id == baseline.id


def test_initial_baseline_rejects_incomplete_or_unconfirmed_run(
    db, monkeypatch, tmp_path
):
    report_date = date(2026, 7, 7)
    run, _ = run_workflow_service.create_or_get_run(
        db, report_date, create_new=True
    )
    monkeypatch.setattr(daily_import_service.settings, "output_dir", str(tmp_path))
    upload = UploadFile(filename="approved.xlsx", file=BytesIO(b"approved baseline"))

    with pytest.raises(DailyImportError, match="四项输入"):
        asyncio.run(
            daily_import_service.finalize_initial_run_baseline(db, run.id, upload)
        )

    run = _stage_initial_run(db, date(2026, 7, 8))
    db.add(
        RunDecision(
            run_id=run.id,
            report_kind=None,
            decision_code="ocr_review_required",
            fact_ref="source:release:row:ocr",
            question="确认 OCR 结果",
            options='["确认","替换输入"]',
            status="pending",
        )
    )
    db.commit()
    upload = UploadFile(filename="approved.xlsx", file=BytesIO(b"approved baseline"))

    with pytest.raises(DailyImportError, match="人工确认"):
        asyncio.run(
            daily_import_service.finalize_initial_run_baseline(db, run.id, upload)
        )
