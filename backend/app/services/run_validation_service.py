"""Persist calculator checks and summarize publication readiness per target."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models.facts import (
    RunDecision,
    RunValidation,
    decode_json_text,
    encode_json_text,
)
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunStatus,
    TargetStatus,
)
from app.pipeline.calculation import validators
from app.repositories import run_repo
from app.services.review_service import (
    WEEKLY_DEDUPE_ANSWER,
    sync_weekly_review_decisions,
)


@dataclass(frozen=True)
class ValidationSummary:
    run_id: str
    report_kind: str
    publishable: bool
    target_status: str
    run_status_blocker: str | None
    pending_decision_count: int
    blocking_validation_codes: tuple[str, ...]
    block_count: int
    review_count: int


def _report_kind(value: str) -> str:
    if value not in {"daily", "weekly"}:
        raise ValueError(f"unsupported report kind: {value}")
    return value


def _target(db: Session, run_id: str, report_kind: str) -> RunReportTarget:
    return run_repo.ensure_report_targets(db, run_id, (report_kind,))[0]


def replace_calculation_validations(
    db: Session,
    run_id: str,
    report_kind: str,
    *,
    checks: Sequence[Mapping[str, Any]],
    review_items: Sequence[Mapping[str, Any]] = (),
) -> list[RunValidation]:
    kind = _report_kind(report_kind)
    run = db.get(ReportRun, run_id)
    if run is None or run.is_deleted:
        raise LookupError(f"Run {run_id} was not found")
    target = _target(db, run_id, kind)
    if target.status == TargetStatus.published.value:
        raise ValueError("published target validations are immutable")

    if kind == "weekly":
        sync_weekly_review_decisions(db, run_id, review_items)

    db.execute(
        delete(RunValidation).where(
            RunValidation.run_id == run_id,
            RunValidation.report_kind == kind,
        )
    )
    raw_checks = [dict(check) for check in checks]
    raw_checks.extend(
        validators.review_item_as_check(dict(item)) for item in review_items
    )
    stored: list[RunValidation] = []
    used_codes: set[str] = set()
    for index, check in enumerate(raw_checks, start=1):
        record = validators.persisted_validation_record(check)
        code = record["validation_code"]
        if code in used_codes:
            code = f"{code[:58]}_{index:03d}"
        used_codes.add(code)
        validation = RunValidation(
            run_id=run_id,
            report_kind=kind,
            validation_code=code,
            severity=record["severity"],
            outcome=record["outcome"],
            message=record["message"],
            evidence_refs=encode_json_text(record["evidence_refs"]),
        )
        db.add(validation)
        stored.append(validation)
    db.commit()
    return stored


def validate_run_target(
    db: Session, run_id: str, report_kind: str
) -> ValidationSummary:
    kind = _report_kind(report_kind)
    run = db.get(ReportRun, run_id)
    if run is None or run.is_deleted:
        raise LookupError(f"Run {run_id} was not found")
    target = _target(db, run_id, kind)

    pending_decisions = db.scalars(
        select(RunDecision).where(
            RunDecision.run_id == run_id,
            RunDecision.is_deleted == 0,
            RunDecision.status != "answered",
            or_(
                RunDecision.report_kind.is_(None),
                RunDecision.report_kind == kind,
            ),
        )
    ).all()
    failed_validations = db.scalars(
        select(RunValidation).where(
            RunValidation.run_id == run_id,
            RunValidation.report_kind == kind,
            RunValidation.is_deleted == 0,
            RunValidation.outcome != "PASS",
            RunValidation.severity.in_(("BLOCK", "REVIEW")),
        )
    ).all()
    accepted_weekly_refs = {
        decision.fact_ref
        for decision in db.scalars(
            select(RunDecision).where(
                RunDecision.run_id == run_id,
                RunDecision.report_kind == "weekly",
                RunDecision.decision_code == "multiple_active_employments",
                RunDecision.status == "answered",
                RunDecision.is_deleted == 0,
            )
        ).all()
        if decode_json_text(decision.answer) == WEEKLY_DEDUPE_ANSWER
    }
    accepted_top3_refs = {
        decision.fact_ref
        for decision in db.scalars(
            select(RunDecision).where(
                RunDecision.run_id == run_id,
                RunDecision.report_kind == "weekly",
                RunDecision.decision_code == "top3_cutoff_tie",
                RunDecision.status == "answered",
                RunDecision.is_deleted == 0,
            )
        ).all()
        if isinstance(decode_json_text(decision.answer), list)
    }

    def review_resolved(validation: RunValidation) -> bool:
        if kind != "weekly" or validation.severity != "REVIEW":
            return False
        refs = decode_json_text(validation.evidence_refs) or []
        if validation.validation_code.startswith("top3_cutoff_tie"):
            tie_refs = [
                str(ref).removeprefix("fact:weekly_top3:")
                for ref in refs
                if str(ref).startswith("fact:weekly_top3:")
            ]
            return len(tie_refs) == 1 and (
                f"weekly:top3_cutoff_tie:{tie_refs[0]}" in accepted_top3_refs
            )
        if not validation.validation_code.startswith(
            "multiple_active_employments"
        ):
            return False
        person_refs = [
            str(ref).removeprefix("person:")
            for ref in refs
            if str(ref).startswith("person:")
        ]
        return len(person_refs) == 1 and (
            f"weekly:multiple_active_employments:{person_refs[0]}"
            in accepted_weekly_refs
        )

    unresolved_validations = [
        validation
        for validation in failed_validations
        if not review_resolved(validation)
    ]
    block_count = sum(v.severity == "BLOCK" for v in unresolved_validations)
    review_count = sum(v.severity == "REVIEW" for v in unresolved_validations)
    run_status_blocker = (
        None if run.status == RunStatus.ready.value else run.status
    )
    publishable = not (
        run_status_blocker
        or pending_decisions
        or block_count
        or review_count
    )

    if target.status in {
        TargetStatus.published.value,
        TargetStatus.superseded.value,
    }:
        target_status = target.status
    elif run.status == RunStatus.failed.value:
        target_status = TargetStatus.failed.value
    elif run_status_blocker or pending_decisions or review_count:
        target_status = TargetStatus.needs_review.value
    elif block_count:
        schedule_only = kind == "weekly" and all(
            validation.validation_code == "weekly_last_workday_only"
            for validation in unresolved_validations
        )
        target_status = (
            TargetStatus.needs_review.value
            if schedule_only
            else TargetStatus.failed.value
        )
    else:
        target_status = TargetStatus.ready.value

    summary = ValidationSummary(
        run_id=run_id,
        report_kind=kind,
        publishable=publishable,
        target_status=target_status,
        run_status_blocker=run_status_blocker,
        pending_decision_count=len(pending_decisions),
        blocking_validation_codes=tuple(
            sorted(
                validation.validation_code
                for validation in unresolved_validations
            )
        ),
        block_count=block_count,
        review_count=review_count,
    )
    if target.status not in {
        TargetStatus.published.value,
        TargetStatus.superseded.value,
    }:
        target.status = target_status
    target.validation_summary = encode_json_text(asdict(summary))
    db.commit()
    return summary
