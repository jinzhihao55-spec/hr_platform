"""Run lifecycle orchestration used by thin API routes."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.facts import RunDecision, RunValidation, decode_json_text
from app.models.publication import PublishedReport
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)
from app.repositories import run_repo
from app.services.decision_service import list_decisions
from app.services.fact_history_service import materialize_run_history


class StaleRunBaseline(ValueError):
    pass


def _summary(run: ReportRun) -> dict:
    return {
        "id": run.id,
        "report_date": run.report_date,
        "status": run.status,
        "rule_version": run.rule_version,
        "baseline_report_id": run.baseline_report_id,
        "canonical_run_id": run.canonical_run_id,
    }


def _default_baseline(db: Session, report_date: date) -> PublishedReport | None:
    return db.scalar(
        select(PublishedReport)
        .where(
            PublishedReport.report_kind == "daily",
            PublishedReport.period_end < report_date,
            PublishedReport.is_current.is_(True),
            PublishedReport.is_deleted == 0,
        )
        .order_by(PublishedReport.period_end.desc(), PublishedReport.version.desc())
        .limit(1)
    )


def baseline_view(db: Session, run: ReportRun) -> dict:
    selected = (
        db.get(PublishedReport, run.baseline_report_id)
        if run.baseline_report_id
        else None
    )
    latest = _default_baseline(db, run.report_date)
    if latest is None:
        status = "missing" if selected is None else "current"
    elif selected is None or selected.id != latest.id:
        status = "stale"
    else:
        status = "current"
    return {
        "baseline_status": status,
        "baseline_period_end": selected.period_end if selected else None,
        "baseline_version": selected.version if selected else None,
        "latest_baseline_report_id": latest.id if latest else None,
        "latest_baseline_period_end": latest.period_end if latest else None,
        "latest_baseline_version": latest.version if latest else None,
    }


def require_current_baseline(db: Session, run: ReportRun) -> None:
    view = baseline_view(db, run)
    if view["baseline_status"] != "stale":
        return
    selected = (
        f'{view["baseline_period_end"].isoformat()} v{view["baseline_version"]}'
        if view["baseline_period_end"]
        else "未关联"
    )
    latest = (
        f'{view["latest_baseline_period_end"].isoformat()} '
        f'v{view["latest_baseline_version"]}'
    )
    raise StaleRunBaseline(
        f"当前日报基线 {selected} 已过期，最新可用基线为 {latest}；"
        "请创建同日修订 Run。"
    )


def create_or_get_run(
    db: Session,
    report_date: date,
    *,
    baseline_report_id: str | None = None,
    create_new: bool = False,
) -> tuple[ReportRun, bool]:
    baseline = None
    if baseline_report_id:
        baseline = db.get(PublishedReport, baseline_report_id)
        if baseline is None or baseline.is_deleted or baseline.report_kind != "daily":
            raise ValueError("baseline_report_id must reference a published daily report")
        if baseline.period_end >= report_date:
            raise ValueError("baseline daily report must precede report_date")
    else:
        baseline = _default_baseline(db, report_date)
        baseline_report_id = baseline.id if baseline is not None else None

    if not create_new:
        existing = db.scalar(
            select(ReportRun)
            .where(
                ReportRun.report_date == report_date,
                ReportRun.rule_version == settings.report_rule_version,
                ReportRun.is_deleted == 0,
                ReportRun.status != RunStatus.deduplicated.value,
                (
                    ReportRun.baseline_report_id == baseline_report_id
                    if baseline_report_id is not None
                    else ReportRun.baseline_report_id.is_(None)
                ),
            )
            .order_by(ReportRun.create_time.desc(), ReportRun.id.desc())
            .limit(1)
        )
        if existing is not None:
            run_repo.ensure_report_targets(db, existing.id)
            db.commit()
            return existing, True

    run = run_repo.create_provisional_run(
        db,
        report_date,
        settings.report_rule_version,
        baseline_report_id,
    )
    run_repo.ensure_report_targets(db, run.id)
    db.commit()
    return run, False


def get_run(db: Session, run_id: str) -> ReportRun:
    run = db.get(ReportRun, run_id)
    if run is None or run.is_deleted:
        raise LookupError(f"Run {run_id} was not found")
    return run


def run_view(db: Session, run_id: str) -> dict:
    run = get_run(db, run_id)
    baseline = baseline_view(db, run)
    sources = db.scalars(
        select(RunSource)
        .where(RunSource.run_id == run.id, RunSource.is_deleted == 0)
        .order_by(RunSource.source_type)
    ).all()
    validations = db.scalars(
        select(RunValidation)
        .where(RunValidation.run_id == run.id, RunValidation.is_deleted == 0)
        .order_by(RunValidation.report_kind, RunValidation.validation_code)
    ).all()
    targets = db.scalars(
        select(RunReportTarget)
        .where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.is_deleted == 0,
        )
        .order_by(RunReportTarget.report_kind)
    ).all()
    return {
        **_summary(run),
        **baseline,
        "attempt_no": run.attempt_no,
        "source_bundle_hash": run.source_bundle_hash,
        "error_code": run.error_code,
        "error_message": run.error_message_redacted,
        "sources": [
            {
                "source_type": source.source_type,
                "sha256": source.sha256,
                "schema_version": source.schema_version,
                "parser_version": source.parser_version,
                "media_type": source.media_type,
                "row_count": source.row_count,
                "parse_status": source.parse_status,
                "original_extension": source.original_extension,
                "original_filename": source.original_filename or "",
            }
            for source in sources
        ],
        "decisions": [
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
            for item in list_decisions(db, run.id)
        ],
        "validations": [
            {
                "report_kind": validation.report_kind,
                "validation_code": validation.validation_code,
                "severity": validation.severity,
                "outcome": validation.outcome,
                "message": validation.message,
                "evidence_refs": decode_json_text(validation.evidence_refs) or [],
            }
            for validation in validations
        ],
        "targets": [
            {
                "report_kind": target.report_kind,
                "status": target.status,
                "preview_hash": target.preview_hash,
                "validation_summary": decode_json_text(target.validation_summary),
                "published_report_id": target.published_report_id,
                "error_code": target.error_code,
                "error_message": target.error_message_redacted,
            }
            for target in targets
        ],
    }


def refresh_run_state(db: Session, run_id: str) -> tuple[ReportRun, dict]:
    run = get_run(db, run_id)
    if run.status == RunStatus.failed.value:
        return run, {"missing_sources": [], "baseline_missing": False}
    if run.status in {
        RunStatus.ready.value,
        RunStatus.deduplicated.value,
    }:
        return run, {"missing_sources": [], "baseline_missing": False}
    if run.status == RunStatus.created.value:
        run_repo.transition_run(db, run, RunStatus.parsing)

    sources = db.scalars(
        select(RunSource).where(
            RunSource.run_id == run.id,
            RunSource.is_deleted == 0,
        )
    ).all()
    by_type = {source.source_type: source for source in sources}
    missing = [
        source.value for source in SourceType if source.value not in by_type
    ]
    pending_shared = db.scalar(
        select(RunDecision.id)
        .where(
            RunDecision.run_id == run.id,
            RunDecision.report_kind.is_(None),
            RunDecision.status != "answered",
            RunDecision.is_deleted == 0,
        )
        .limit(1)
    )
    baseline = (
        db.get(PublishedReport, run.baseline_report_id)
        if run.baseline_report_id
        else None
    )
    if baseline is None and run.baseline_report_id is None:
        baseline = _default_baseline(db, run.report_date)
        if baseline is not None:
            run.baseline_report_id = baseline.id
    baseline_missing = baseline is None

    if missing:
        db.commit()
        return run, {"missing_sources": missing, "baseline_missing": baseline_missing}
    if pending_shared:
        if run.status == RunStatus.parsing.value:
            run_repo.transition_run(db, run, RunStatus.needs_review)
        db.commit()
        return run, {"missing_sources": [], "baseline_missing": baseline_missing}
    if baseline_missing:
        # Initial run: allow ready transition without baseline
        if run.status in {RunStatus.parsing.value, RunStatus.needs_review.value}:
            run_repo.transition_run(db, run, RunStatus.needs_review)
        db.commit()
        return run, {"missing_sources": [], "baseline_missing": True}

    materialize_run_history(db, run, baseline)
    canonical = run_repo.finalize_run_fingerprint(
        db,
        run,
        {source.source_type: source.sha256 for source in sources},
        baseline_report_id=baseline.id,
        baseline_sha256=baseline.snapshot_hash,
    )
    if canonical.id == run.id and run.status in {
        RunStatus.parsing.value,
        RunStatus.needs_review.value,
    }:
        run_repo.transition_run(db, run, RunStatus.ready)
    db.commit()
    return canonical, {"missing_sources": [], "baseline_missing": False}


def retry_run(db: Session, run_id: str) -> ReportRun:
    run = get_run(db, run_id)
    if run.status != RunStatus.failed.value:
        raise ValueError("only failed Runs can be retried")
    run.attempt_no += 1
    run.error_code = None
    run.error_message_redacted = None
    run_repo.transition_run(db, run, RunStatus.parsing)
    targets = db.scalars(
        select(RunReportTarget).where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.is_deleted == 0,
        )
    ).all()
    for target in targets:
        if target.status == TargetStatus.failed.value:
            target.status = TargetStatus.draft.value
            target.error_code = None
            target.error_message_redacted = None
    db.commit()
    return run
