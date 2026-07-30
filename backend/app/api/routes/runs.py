"""Thin typed routes for Run sources, review, preview, and publication."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.models.facts import decode_json_text
from app.models.publication import PublishedReport, ReportArtifact
from app.models.runs import RunSource, SourceType
from app.schemas.runs import (
    DecisionAnswerRequest,
    DecisionPreviewResponse,
    DecisionView,
    PreviewResponse,
    PublishRequest,
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunSourceView,
    WeeklyReviewResponse,
)
from app.schemas.api import ImportDailyResponse
from app.services import daily_import_service, publication_service, run_workflow_service
from app.services.decision_service import (
    DecisionAnswerConflict,
    DecisionNotFound,
    InvalidDecisionAnswer,
    answer_decision,
    list_decisions,
)
from app.services.preview_service import PreviewSnapshot, build_preview
from app.services.review_service import (
    ReviewEvidenceMissing,
    decision_preview,
    weekly_review,
)
from app.services.run_source_service import RunSourceService
from app.services.run_validation_service import validate_run_target


router = APIRouter(tags=["runs"])


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


def _stale_baseline(exc: run_workflow_service.StaleRunBaseline) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


def _preview_response(snapshot: PreviewSnapshot) -> dict:
    return {
        "run_id": snapshot.run_id,
        "report_kind": snapshot.report_kind,
        "period_start": snapshot.period_start,
        "period_end": snapshot.period_end,
        "rule_version": snapshot.rule_version,
        "snapshot_hash": snapshot.snapshot_hash,
        "publishable": snapshot.publishable,
        "rows": {
            str(number): {
                "number": row.number,
                "label": row.label,
                "value": row.value,
                "is_blank": row.is_blank,
            }
            for number, row in snapshot.rows.items()
        },
        "main_rows": list(snapshot.main_rows),
        "cc_rows": list(snapshot.cc_rows),
        "tenure": dict(snapshot.tenure),
        "validation_summary": asdict(snapshot.validation_summary),
    }


@router.post(
    "/runs",
    response_model=RunCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_run(req: RunCreateRequest, db: Session = Depends(get_db)):
    try:
        run, reused = run_workflow_service.create_or_get_run(
            db,
            req.report_date,
            baseline_report_id=req.baseline_report_id,
            create_new=req.create_new,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "reused": reused,
        "run": {
            "id": run.id,
            "report_date": run.report_date,
            "status": run.status,
            "rule_version": run.rule_version,
            "baseline_report_id": run.baseline_report_id,
            "canonical_run_id": run.canonical_run_id,
        },
    }


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)):
    try:
        return run_workflow_service.run_view(db, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post("/runs/{run_id}/retry", response_model=RunDetail)
def retry_run(run_id: str, db: Session = Depends(get_db)):
    try:
        run_workflow_service.retry_run(db, run_id)
        return run_workflow_service.run_view(db, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/runs/{run_id}/sources/{source_type}")
async def put_source(
    run_id: str,
    source_type: SourceType,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        run = run_workflow_service.get_run(db, run_id)
        run_workflow_service.require_current_baseline(db, run)
        result = await RunSourceService(db).ingest(run_id, source_type, file)
        run, readiness = run_workflow_service.refresh_run_state(db, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except run_workflow_service.StaleRunBaseline as exc:
        raise _stale_baseline(exc) from exc
    return {
        **asdict(result),
        "run_status": run.status,
        "readiness": readiness,
    }


@router.get("/runs/{run_id}/sources", response_model=list[RunSourceView])
def get_sources(run_id: str, db: Session = Depends(get_db)):
    try:
        run_workflow_service.get_run(db, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    sources = db.scalars(
        select(RunSource)
        .where(RunSource.run_id == run_id, RunSource.is_deleted == 0)
        .order_by(RunSource.source_type)
    ).all()
    return [
        {
            "source_type": source.source_type,
            "original_filename": source.original_filename,
            "sha256": source.sha256,
            "schema_version": source.schema_version,
            "parser_version": source.parser_version,
            "media_type": source.media_type,
            "row_count": source.row_count,
            "parse_status": source.parse_status,
            "original_extension": source.original_extension,
        }
        for source in sources
    ]


@router.post("/runs/{run_id}/parse", response_model=RunDetail)
def parse_run(run_id: str, db: Session = Depends(get_db)):
    try:
        run = run_workflow_service.get_run(db, run_id)
        run_workflow_service.require_current_baseline(db, run)
        run, _ = run_workflow_service.refresh_run_state(db, run_id)
        return run_workflow_service.run_view(db, run.id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except run_workflow_service.StaleRunBaseline as exc:
        raise _stale_baseline(exc) from exc


@router.post("/runs/{run_id}/baseline", response_model=ImportDailyResponse)
async def finalize_initial_baseline(
    run_id: str,
    request: Request,
    file: UploadFile = File(..., description="当前运行日的已验收日报 xlsx"),
    db: Session = Depends(get_db),
):
    """Freeze the first four-source Run with its approved same-day daily."""
    operator = (
        request.headers.get("x-authenticated-user") or "local-operator"
    ).strip()
    return await daily_import_service.finalize_initial_run_baseline(
        db, run_id, file, imported_by=operator
    )


@router.get("/runs/{run_id}/decisions", response_model=list[DecisionView])
def get_decisions(
    run_id: str,
    report_kind: str | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        run_workflow_service.get_run(db, run_id)
        items = list_decisions(db, run_id, report_kind)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [
        {
            "id": item.id,
            "report_kind": item.report_kind,
            "decision_code": item.decision_code,
            "fact_ref": item.fact_ref,
            "question": item.question,
            "options": list(item.options),
            "answer": item.answer,
            "status": item.status,
            "decided_at": item.decided_at,
            "operator_ref": item.operator_ref,
        }
        for item in items
    ]


@router.get(
    "/runs/{run_id}/decisions/{decision_id}/preview",
    response_model=DecisionPreviewResponse,
)
def get_decision_preview(
    run_id: str,
    decision_id: str,
    db: Session = Depends(get_db),
):
    try:
        return decision_preview(db, run_id, decision_id)
    except ReviewEvidenceMissing as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "识别后的结构化事实已不可用，请重新上传对应输入。",
        ) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get(
    "/runs/{run_id}/weekly/review",
    response_model=WeeklyReviewResponse,
)
def get_weekly_review(run_id: str, db: Session = Depends(get_db)):
    try:
        return weekly_review(db, run_id)
    except ReviewEvidenceMissing as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "周报复核证据不完整，请创建同日修订 Run 并重新上传输入。",
        ) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post("/runs/{run_id}/decisions/{decision_id}", response_model=DecisionView)
def post_decision(
    run_id: str,
    decision_id: str,
    req: DecisionAnswerRequest,
    db: Session = Depends(get_db),
):
    try:
        decision = answer_decision(
            db, run_id, decision_id, req.answer, req.operator_ref
        )
        run_workflow_service.refresh_run_state(db, run_id)
        if decision.report_kind in {"daily", "weekly"}:
            validate_run_target(db, run_id, decision.report_kind)
    except (LookupError, DecisionNotFound) as exc:
        raise _not_found(exc) from exc
    except DecisionAnswerConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InvalidDecisionAnswer as exc:
        raise HTTPException(422, str(exc)) from exc
    item = next(item for item in list_decisions(db, run_id) if item.id == decision.id)
    return {
        "id": item.id,
        "report_kind": item.report_kind,
        "decision_code": item.decision_code,
        "fact_ref": item.fact_ref,
        "question": item.question,
        "options": list(item.options),
        "answer": item.answer,
        "status": item.status,
        "decided_at": item.decided_at,
        "operator_ref": item.operator_ref,
    }


@router.get("/runs/{run_id}/preview/daily", response_model=PreviewResponse)
def preview_daily(
    run_id: str,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return _preview_response(
            build_preview(
                db,
                run_id,
                "daily",
                reuse_published_snapshot=False,
            )
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    except run_workflow_service.StaleRunBaseline as exc:
        raise _stale_baseline(exc) from exc


@router.get("/runs/{run_id}/preview/weekly", response_model=PreviewResponse)
def preview_weekly(
    run_id: str,
    week_start: date | None = Query(None),
    week_end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        return _preview_response(
            build_preview(
                db,
                run_id,
                "weekly",
                week_start=week_start,
                week_end=week_end,
            )
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    except run_workflow_service.StaleRunBaseline as exc:
        raise _stale_baseline(exc) from exc


@router.post("/runs/{run_id}/publish")
def publish_run(
    run_id: str,
    req: PublishRequest,
    db: Session = Depends(get_db),
):
    try:
        reports = publication_service.publish(
            db, run_id, req.report_kinds, req.operator_ref
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    except run_workflow_service.StaleRunBaseline as exc:
        raise _stale_baseline(exc) from exc
    except publication_service.PublicationBlocked as exc:
        raise HTTPException(422, str(exc)) from exc
    except publication_service.PublicationFailed as exc:
        raise HTTPException(
            409, "报表发布失败，请检查系统状态后重试"
        ) from exc
    return {
        "reports": [
            {
                "id": report.id,
                "report_kind": report.report_kind,
                "period_start": report.period_start,
                "period_end": report.period_end,
                "version": report.version,
                "snapshot_hash": report.snapshot_hash,
            }
            for report in reports
        ]
    }


def _report_list(db: Session, report_kind: str):
    reports = db.execute(
        select(
            PublishedReport.id,
            PublishedReport.run_id,
            PublishedReport.report_kind,
            PublishedReport.period_start,
            PublishedReport.period_end,
            PublishedReport.version,
            PublishedReport.is_current,
            PublishedReport.snapshot_hash,
            PublishedReport.published_at,
        )
        .where(
            PublishedReport.report_kind == report_kind,
            PublishedReport.is_deleted == 0,
        )
        .order_by(PublishedReport.period_end.desc(), PublishedReport.version.desc())
    ).mappings().all()
    return [dict(report) for report in reports]


@router.get("/reports/daily")
def daily_history(db: Session = Depends(get_db)):
    return _report_list(db, "daily")


@router.get("/reports/weekly")
def weekly_history(db: Session = Depends(get_db)):
    return _report_list(db, "weekly")


@router.get("/reports/{report_id}")
def report_detail(report_id: str, db: Session = Depends(get_db)):
    report = db.get(PublishedReport, report_id)
    if report is None or report.is_deleted:
        raise HTTPException(404, "published report was not found")
    artifacts = db.scalars(
        select(ReportArtifact).where(
            ReportArtifact.report_id == report.id,
            ReportArtifact.is_deleted == 0,
        )
    ).all()
    return {
        "id": report.id,
        "run_id": report.run_id,
        "report_kind": report.report_kind,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "version": report.version,
        "is_current": report.is_current,
        "snapshot": decode_json_text(report.snapshot_json),
        "artifacts": [
            {
                "artifact_kind": artifact.artifact_kind,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in artifacts
        ],
    }


@router.delete("/runs/{run_id}/decisions/{decision_id}")
def undo_decision(run_id: str, decision_id: str, db: Session = Depends(get_db)):
    """撤销已确认的决策，恢复为 pending 状态。"""
    from app.models.facts import RunDecision
    decision = db.get(RunDecision, decision_id)
    if decision is None or decision.is_deleted or decision.run_id != run_id:
        raise HTTPException(404, "Decision was not found")
    if decision.status != "answered":
        raise HTTPException(409, "只能撤销已确认的决策")
    decision.status = "pending"
    decision.answer = None
    decision.decided_at = None
    decision.operator_ref = None
    db.commit()
    return {"status": "pending"}

@router.get("/reports/{report_id}/artifacts/{artifact_kind}")
def download_artifact(
    report_id: str,
    artifact_kind: str,
    db: Session = Depends(get_db),
):
    import traceback
    import logging
    _log = logging.getLogger(__name__)

    try:
        from app.utils.path_security import resolve_protected_path
        from fastapi.responses import FileResponse as _FileResponse

        artifact = db.scalar(
            select(ReportArtifact).where(
                ReportArtifact.report_id == report_id,
                ReportArtifact.artifact_kind == artifact_kind,
                ReportArtifact.is_deleted == 0,
            )
        )
        if artifact is None:
            raise HTTPException(404, "report artifact was not found")
        output_root = Path(settings.output_dir).resolve()
        resolved = resolve_protected_path(artifact.protected_path, output_root)
        if resolved is None:
            raise HTTPException(403, "artifact path is outside protected output")
        # Auto-heal: persist the rebased path so subsequent requests skip relocation
        stale = Path(artifact.protected_path).resolve()
        if resolved != stale:
            artifact.protected_path = str(resolved)
            db.commit()
        return _FileResponse(resolved, filename=resolved.name)
    except HTTPException:
        raise
    except Exception as exc:
        _log.error("download_artifact 失败: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, f"download_artifact 失败: {type(exc).__name__}: {exc}")
