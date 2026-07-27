"""Run a privacy-safe, isolated end-to-end preview against real input files.

The script writes only to the database/output locations configured by the caller
and prints aggregate counts plus report row values. It never publishes a report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app import models  # noqa: F401 - register all SQLAlchemy models
from app.core.database import Base, SessionLocal, engine
from app.models.facts import RecruitmentSnapshot, ReleaseFact
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunStatus, SourceType
from app.services.daily_import_service import import_daily
from app.services.decision_service import answer_decision, list_decisions
from app.services.fact_history_service import materialize_initial_history
from app.services.preview_service import build_preview
from app.services.run_source_service import RunSourceService
from app.services.run_workflow_service import create_or_get_run, refresh_run_state, run_view


def _upload(path: Path) -> UploadFile:
    return UploadFile(
        filename=path.name,
        file=path.open("rb"),
        headers={"content-type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"},
    )


async def _ingest(service: RunSourceService, run_id: str, source: SourceType, path: Path) -> dict:
    upload = _upload(path)
    try:
        result = await service.ingest(run_id, source, upload)
        return {
            "source_type": result.source_type,
            "row_count": result.row_count,
            "parse_status": result.parse_status,
        }
    finally:
        await upload.close()


async def _run(args: argparse.Namespace) -> dict:
    Base.metadata.create_all(bind=engine)
    input_dir = Path(args.input_dir).resolve()
    baseline_path = Path(args.baseline).resolve()
    files = {
        SourceType.personnel: input_dir / "人员表_20260723.xls",
        SourceType.resignation: input_dir / "离职人员报表_20260723.xls",
        SourceType.release: input_dir / "Release明细_20260723.xlsx",
        SourceType.recruitment: input_dir / "微信图片_20260724101734_539_1140.jpg",
    }
    missing = [str(path) for path in [baseline_path, *files.values()] if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing verification inputs: {missing}")

    db = SessionLocal()
    try:
        baseline_upload = _upload(baseline_path)
        try:
            baseline = await import_daily(
                db,
                date(2026, 7, 22),
                baseline_upload,
                regenerate=False,
                imported_by="local-verification",
            )
        finally:
            await baseline_upload.close()

        # A workbook-only baseline has no fact snapshot. Seed a representative
        # previous-day personnel/resignation snapshot from the same extracts so
        # first-visible behavior matches a normal consecutive production Run.
        seed_run = ReportRun(
            report_date=date(2026, 7, 22),
            status=RunStatus.created.value,
            rule_version="local-verification-seed",
        )
        db.add(seed_run)
        db.commit()
        seed_service = RunSourceService(db)
        await _ingest(seed_service, seed_run.id, SourceType.personnel, files[SourceType.personnel])
        await _ingest(seed_service, seed_run.id, SourceType.resignation, files[SourceType.resignation])
        materialize_initial_history(db, seed_run)
        baseline_report = db.get(PublishedReport, baseline["baseline_report_id"])
        if baseline_report is None:
            raise RuntimeError("imported baseline report was not registered")
        baseline_report.run_id = seed_run.id
        db.commit()

        run, _ = create_or_get_run(
            db,
            date(2026, 7, 23),
            baseline_report_id=baseline["baseline_report_id"],
            create_new=True,
        )
        service = RunSourceService(db)
        ingested = []
        for source, path in files.items():
            ingested.append(await _ingest(service, run.id, source, path))

        refresh_run_state(db, run.id)
        decisions_before = list_decisions(db, run.id)
        decision_codes = [item.decision_code for item in decisions_before]

        for item in decisions_before:
            if item.status == "answered":
                continue
            if item.decision_code == "ocr_review_required":
                answer = "确认"
            elif item.decision_code == "recruitment_label_uncertain":
                answer = {
                    "previous_month_offer_current_month_onboard": 0,
                    "current_month_offer_current_month_onboard": 3,
                }
            else:
                raise RuntimeError(
                    f"unexpected pending decision {item.decision_code}; manual review required"
                )
            answer_decision(db, run.id, item.id, answer, "local-verification")

        canonical, readiness = refresh_run_state(db, run.id)
        preview = build_preview(db, canonical.id, "daily")
        release_count = db.scalar(
            select(func.count(ReleaseFact.id)).where(
                ReleaseFact.run_id == canonical.id,
                ReleaseFact.is_deleted == 0,
            )
        )
        release_row5 = db.scalar(
            select(func.count(ReleaseFact.id)).where(
                ReleaseFact.run_id == canonical.id,
                ReleaseFact.row5_classification == "include",
                ReleaseFact.is_deleted == 0,
            )
        )
        release_row30 = db.scalar(
            select(func.count(ReleaseFact.id)).where(
                ReleaseFact.run_id == canonical.id,
                ReleaseFact.row30_classification == "include",
                ReleaseFact.is_deleted == 0,
            )
        )
        recruitment_facts = db.scalars(
            select(RecruitmentSnapshot).where(
                RecruitmentSnapshot.run_id == canonical.id,
                RecruitmentSnapshot.is_deleted == 0,
            )
        ).all()
        view = run_view(db, canonical.id)
        key_rows = {
            str(number): {
                "label": preview.rows[number].label,
                "value": preview.rows[number].value,
            }
            for number in (2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 17, 30, 38, 39)
            if number in preview.rows
        }
        return {
            "baseline_date": "2026-07-22",
            "run_date": "2026-07-23",
            "run_status": canonical.status,
            "readiness": readiness,
            "sources": ingested,
            "decision_codes_before_confirmation": decision_codes,
            "pending_decisions_after_confirmation": [
                item.decision_code
                for item in list_decisions(db, canonical.id)
                if item.status != "answered"
            ],
            "release": {
                "records": release_count,
                "row5_included": release_row5,
                "row30_included": release_row30,
            },
            "recruitment": {
                "records": len(recruitment_facts),
                "confirmed_records": sum(
                    fact.ocr_confidence == "confirmed" for fact in recruitment_facts
                ),
            },
            "preview_publishable": preview.publishable,
            "key_rows": key_rows,
            "source_metadata": [
                {
                    "source_type": source["source_type"],
                    "schema_version": source["schema_version"],
                    "parser_version": source["parser_version"],
                    "row_count": source["row_count"],
                    "parse_status": source["parse_status"],
                    "original_filename": source["original_filename"],
                }
                for source in view["sources"]
            ],
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
