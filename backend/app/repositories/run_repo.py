"""Persistence boundary for report Runs, source metadata, and report targets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.run_fingerprint import compute_source_bundle_hash
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)


class InvalidRunTransition(ValueError):
    pass


class CanonicalRunNotFound(LookupError):
    pass


_RUN_TRANSITIONS = {
    RunStatus.created: {RunStatus.parsing},
    RunStatus.parsing: {
        RunStatus.needs_review,
        RunStatus.ready,
        RunStatus.deduplicated,
        RunStatus.failed,
    },
    RunStatus.needs_review: {RunStatus.ready, RunStatus.deduplicated, RunStatus.failed},
    RunStatus.ready: {RunStatus.deduplicated},
    RunStatus.deduplicated: set(),
    RunStatus.failed: {RunStatus.parsing},
}

_REPORT_KINDS = ("daily", "weekly")


def _run_status(value: str | RunStatus) -> RunStatus:
    try:
        return value if isinstance(value, RunStatus) else RunStatus(value)
    except ValueError as exc:
        raise InvalidRunTransition(f"unknown Run status: {value}") from exc


def create_provisional_run(
    db: Session,
    report_date: date,
    rule_version: str,
    baseline_report_id: str | None,
) -> ReportRun:
    run = ReportRun(
        report_date=report_date,
        status=RunStatus.created.value,
        rule_version=rule_version,
        source_bundle_hash=None,
        baseline_report_id=baseline_report_id,
        attempt_no=0,
    )
    db.add(run)
    db.flush()
    return run


def transition_run(
    db: Session, run: ReportRun, new_status: str | RunStatus
) -> ReportRun:
    current = _run_status(run.status)
    try:
        target = _run_status(new_status)
    except InvalidRunTransition as exc:
        target_value = (
            new_status.value if isinstance(new_status, RunStatus) else str(new_status)
        )
        raise InvalidRunTransition(
            f"invalid Run transition: {current.value} -> {target_value}"
        ) from exc
    if current == target:
        return run
    if target not in _RUN_TRANSITIONS[current]:
        raise InvalidRunTransition(
            f"invalid Run transition: {current.value} -> {target.value}"
        )
    run.status = target.value
    db.flush()
    return run


def upsert_source_metadata(
    db: Session,
    run_id: str,
    source_type: str | SourceType,
    *,
    sha256: str,
    schema_version: str,
    parser_version: str,
    media_type: str | None,
    row_count: int,
    parse_status: str,
    original_extension: str | None,
    original_filename: str | None = None,
) -> RunSource:
    source_value = (
        source_type.value
        if isinstance(source_type, SourceType)
        else SourceType(source_type).value
    )
    source = db.scalar(
        select(RunSource).where(
            RunSource.run_id == run_id,
            RunSource.source_type == source_value,
            RunSource.is_deleted == 0,
        )
    )
    if source is None:
        source = RunSource(run_id=run_id, source_type=source_value)
        db.add(source)
    source.sha256 = sha256
    source.schema_version = schema_version
    source.parser_version = parser_version
    source.media_type = media_type
    source.row_count = row_count
    source.parse_status = parse_status
    source.original_extension = original_extension
    source.original_filename = original_filename
    db.flush()
    return source


def ensure_report_targets(
    db: Session,
    run_id: str,
    report_kinds: Iterable[str] = _REPORT_KINDS,
) -> list[RunReportTarget]:
    kinds = tuple(report_kinds)
    unknown = set(kinds) - set(_REPORT_KINDS)
    if unknown:
        raise ValueError(f"unsupported report kinds: {', '.join(sorted(unknown))}")

    existing = {
        target.report_kind: target
        for target in db.scalars(
            select(RunReportTarget).where(
                RunReportTarget.run_id == run_id,
                RunReportTarget.is_deleted == 0,
            )
        ).all()
    }
    for kind in kinds:
        if kind not in existing:
            target = RunReportTarget(
                run_id=run_id,
                report_kind=kind,
                status=TargetStatus.draft.value,
            )
            db.add(target)
            existing[kind] = target
    db.flush()
    return [existing[kind] for kind in kinds]


def _find_by_fingerprint(
    db: Session,
    report_date: date,
    rule_version: str,
    fingerprint: str,
) -> ReportRun | None:
    return db.scalar(
        select(ReportRun)
        .where(
            ReportRun.report_date == report_date,
            ReportRun.rule_version == rule_version,
            ReportRun.source_bundle_hash == fingerprint,
            ReportRun.is_deleted == 0,
        )
        .order_by(ReportRun.create_time, ReportRun.id)
    )


def _mark_deduplicated(
    db: Session, provisional: ReportRun, canonical: ReportRun
) -> None:
    provisional.source_bundle_hash = None
    provisional.canonical_run_id = canonical.id
    transition_run(db, provisional, RunStatus.deduplicated)


def finalize_run_fingerprint(
    db: Session,
    run: ReportRun,
    source_hashes: Mapping[str, str],
    *,
    baseline_report_id: str,
    baseline_sha256: str,
) -> ReportRun:
    fingerprint = compute_source_bundle_hash(
        source_hashes, baseline_report_id, baseline_sha256
    )
    if run.source_bundle_hash == fingerprint:
        return get_canonical_run(db, run)

    canonical = _find_by_fingerprint(
        db, run.report_date, run.rule_version, fingerprint
    )
    if canonical is not None and canonical.id != run.id:
        # If canonical already has published reports, supersede it
        from app.models.publication import PublishedReport
        from sqlalchemy import exists, select
        has_published = db.scalar(
            select(PublishedReport.id).where(
                PublishedReport.run_id == canonical.id,
                PublishedReport.is_deleted == 0,
            ).limit(1)
        ) is not None
        if has_published:
            # Mark old canonical as deduplicated; this new run becomes canonical
            _mark_deduplicated(db, canonical, run)
            run.canonical_run_id = run.id
            run.source_bundle_hash = fingerprint
            return run
        _mark_deduplicated(db, run, canonical)
        return canonical

    run_id = run.id
    try:
        with db.begin_nested():
            run.baseline_report_id = baseline_report_id
            run.source_bundle_hash = fingerprint
            db.flush()
    except IntegrityError:
        run = db.get(ReportRun, run_id)
        canonical = _find_by_fingerprint(
            db, run.report_date, run.rule_version, fingerprint
        )
        if canonical is None or canonical.id == run.id:
            raise
        _mark_deduplicated(db, run, canonical)
        return canonical
    return run


def get_canonical_run(db: Session, run: ReportRun) -> ReportRun:
    if run.canonical_run_id is None:
        return run
    canonical = db.get(ReportRun, run.canonical_run_id)
    if canonical is None or canonical.is_deleted:
        raise CanonicalRunNotFound(
            f"canonical Run {run.canonical_run_id} for {run.id} was not found"
        )
    return canonical
