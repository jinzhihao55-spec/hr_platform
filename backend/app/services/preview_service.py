"""Pure report calculation plus scoped validation persistence for Run previews."""

from __future__ import annotations

import copy
import hashlib
import math
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.calculation_agent import CalculationAgent
from app.core.logging import get_logger
from app.core.exceptions import BaselineMissingError
from app.domain.fact_bundle import FactBundle
from app.models.facts import decode_json_text, encode_json_text
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunSource, SourceType
from app.pipeline.calculation import validators
from app.repositories import report_repo, run_repo
from app.services.fact_bundle_service import FactBundleService
from app.services.run_workflow_service import require_current_baseline
from app.services.run_validation_service import (
    ValidationSummary,
    replace_calculation_validations,
    validate_run_target,
)
from app.utils import calendar_utils as cal


log = get_logger(__name__)


@dataclass(frozen=True)
class PreviewRow:
    number: int
    label: str | None
    value: Any
    is_blank: bool = False


@dataclass(frozen=True)
class PreviewSnapshot:
    run_id: str
    report_kind: str
    period_start: date
    period_end: date
    rule_version: str
    rows: Mapping[int, PreviewRow]
    main_rows: tuple[dict[str, Any], ...]
    cc_rows: tuple[dict[str, Any], ...]
    tenure: Mapping[str, Any]
    events: tuple[dict[str, Any], ...]
    validation_summary: ValidationSummary
    snapshot_json: str
    snapshot_hash: str
    calculation_context: Mapping[str, Any]
    baseline_rows: Mapping[int, int]

    @property
    def publishable(self) -> bool:
        return self.validation_summary.publishable


def _recalculated_validation_summary(
    run: ReportRun,
    report_kind: str,
    bundle: FactBundle,
    ctx: Mapping[str, Any],
    published: PreviewSnapshot,
) -> ValidationSummary:
    """Summarize replay validations without mutating a published Run."""
    pending_decisions = [
        decision
        for decision in bundle.decisions
        if decision.get("status") != "answered"
        and decision.get("report_kind") in {None, report_kind}
    ]
    raw_checks = [dict(check) for check in ctx.get("validations") or ()]
    raw_checks.extend(
        validators.review_item_as_check(dict(item))
        for item in ctx.get("review_items") or ()
    )
    records = [validators.persisted_validation_record(check) for check in raw_checks]
    failed = [
        record
        for record in records
        if record["outcome"] != "PASS"
        and record["severity"] in {"BLOCK", "REVIEW"}
    ]
    block_count = sum(record["severity"] == "BLOCK" for record in failed)
    review_count = sum(record["severity"] == "REVIEW" for record in failed)
    run_status_blocker = None if run.status == "ready" else run.status
    return ValidationSummary(
        run_id=run.id,
        report_kind=report_kind,
        publishable=not (
            run_status_blocker
            or pending_decisions
            or block_count
            or review_count
        ),
        target_status=published.validation_summary.target_status,
        run_status_blocker=run_status_blocker,
        pending_decision_count=len(pending_decisions),
        blocking_validation_codes=tuple(
            sorted(record["validation_code"] for record in failed)
        ),
        block_count=block_count,
        review_count=review_count,
    )


def _published_preview(
    db: Session, run: ReportRun, report_kind: str
) -> PreviewSnapshot | None:
    report = db.scalar(
        select(PublishedReport)
        .where(
            PublishedReport.run_id == run.id,
            PublishedReport.report_kind == report_kind,
            PublishedReport.is_deleted == 0,
        )
        .order_by(PublishedReport.version.desc())
        .limit(1)
    )
    if report is None:
        return None

    payload = decode_json_text(report.snapshot_json) or {}
    raw_summary = payload.get("validation_summary") or {}
    summary = ValidationSummary(
        run_id=run.id,
        report_kind=report_kind,
        publishable=bool(raw_summary.get("publishable", True)),
        target_status=raw_summary.get("target_status") or "published",
        run_status_blocker=raw_summary.get("run_status_blocker"),
        pending_decision_count=int(raw_summary.get("pending_decision_count") or 0),
        blocking_validation_codes=tuple(
            raw_summary.get("blocking_validation_codes") or ()
        ),
        block_count=int(raw_summary.get("block_count") or 0),
        review_count=int(raw_summary.get("review_count") or 0),
    )
    raw_rows = payload.get("rows") or {}
    rows = MappingProxyType(
        {
            int(number): PreviewRow(
                number=int(number),
                label=info.get("label") or info.get("item"),
                value=info.get("value"),
                is_blank=bool(info.get("is_blank")),
            )
            for number, info in raw_rows.items()
        }
    )
    main_rows = tuple(copy.deepcopy(payload.get("main_rows") or ()))
    cc_rows = tuple(copy.deepcopy(payload.get("cc_rows") or ()))
    tenure = copy.deepcopy(payload.get("tenure") or {})
    events = tuple(copy.deepcopy(payload.get("events") or ()))
    calculation_context = {
        "rows": {
            number: {
                "item": row.label,
                "value": row.value,
                "is_blank": row.is_blank,
            }
            for number, row in rows.items()
        },
        "main_rows": list(main_rows),
        "cc_rows": list(cc_rows),
        "tenure": tenure,
        "week_start": report.period_start,
        "week_end": report.period_end,
    }
    return PreviewSnapshot(
        run_id=run.id,
        report_kind=report_kind,
        period_start=report.period_start,
        period_end=report.period_end,
        rule_version=payload.get("rule_version") or run.rule_version,
        rows=rows,
        main_rows=main_rows,
        cc_rows=cc_rows,
        tenure=MappingProxyType(tenure),
        events=events,
        validation_summary=summary,
        snapshot_json=report.snapshot_json,
        snapshot_hash=report.snapshot_hash,
        calculation_context=MappingProxyType(calculation_context),
        baseline_rows=MappingProxyType({}),
    )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return str(value)


def _safe_events(bundle: FactBundle) -> tuple[dict[str, Any], ...]:
    if bundle.events.empty:
        return ()
    allowed = (
        "event_key",
        "event_type",
        "employment_ref",
        "source_type",
        "source_event_ref",
        "effective_date",
        "first_visible_date",
        "classification",
    )
    return tuple(
        {
            key: _jsonable(row.get(key))
            for key in allowed
            if key in bundle.events.columns
        }
        for row in bundle.events.to_dict(orient="records")
    )


def _baseline_from_published(
    db: Session,
    run: ReportRun,
    *,
    replay_latest_rules: bool = True,
) -> tuple[date, dict[int, int], date | None, tuple[dict[str, Any], ...]] | None:
    if not run.baseline_report_id:
        return None
    report = db.get(PublishedReport, run.baseline_report_id)
    if report is None or report.is_deleted or report.report_kind != "daily":
        raise BaselineMissingError("Run 指定的已发布日报基线不存在")
    payload = decode_json_text(report.snapshot_json) or {}
    rows = payload.get("rows") or {}
    required = (8, 9, 13, 14, 30)
    baseline: dict[int, int] = {}
    for number, info in rows.items():
        if not isinstance(info, Mapping):
            continue
        value = info.get("value")
        if value is None:
            continue
        try:
            baseline[int(number)] = int(value)
        except (TypeError, ValueError):
            continue
    for row in required:
        baseline[row] = int(baseline.get(row) or 0)
    tenure = payload.get("tenure") or {}
    tenure_rows = tuple(dict(row) for row in tenure.get("rows") or ())

    baseline_run = db.get(ReportRun, report.run_id) if report.run_id else None
    required_sources = {source_type.value for source_type in SourceType}
    available_sources = set()
    if baseline_run is not None:
        available_sources = set(
            db.scalars(
                select(RunSource.source_type).where(
                    RunSource.run_id == baseline_run.id,
                    RunSource.is_deleted == 0,
                )
            ).all()
        )
    replayable = (
        replay_latest_rules
        and baseline_run is not None
        and baseline_run.id != run.id
        and baseline_run.report_date == report.period_end
        and required_sources.issubset(available_sources)
    )
    if replayable:
        try:
            replayed = build_preview(
                db,
                baseline_run.id,
                "daily",
                persist_preview_hash=False,
                reuse_published_snapshot=False,
                replay_published_baseline=False,
            )
        except Exception as exc:
            log.exception(
                "failed to replay published baseline run=%s report=%s",
                baseline_run.id,
                report.id,
            )
            raise BaselineMissingError("前一日基线无法按最新规则重新计算") from exc
        baseline = {
            number: int(row.value)
            for number, row in replayed.rows.items()
            if row.value is not None
        }
        for row in required:
            baseline[row] = int(baseline.get(row) or 0)
        tenure_rows = tuple(dict(row) for row in replayed.tenure.get("rows") or ())
    return report.period_end, baseline, report.period_end, tenure_rows


def _daily_reconciliation(db: Session, week_start: date, week_end: date) -> dict:
    result = report_repo.load_daily_week_totals(db, week_start, week_end)
    expected: list[date] = []
    current = week_start
    while current <= week_end:
        if cal.is_workday(current):
            expected.append(current)
        current += timedelta(days=1)
    report_dates = result.get("report_dates") or []
    return {
        **result,
        "expected_dates": expected,
        "complete": set(report_dates) == set(expected),
    }


def _build_bundle(
    db: Session,
    run: ReportRun,
    report_kind: str,
    *,
    replay_published_baseline: bool = True,
) -> FactBundle:
    bundle_started = time.perf_counter()
    published = _baseline_from_published(
        db,
        run,
        replay_latest_rules=(report_kind == "daily" and replay_published_baseline),
    )
    log.info(
        "preview bundle run=%s kind=%s stage=baseline seconds=%.3f",
        run.id,
        report_kind,
        time.perf_counter() - bundle_started,
    )
    if published is not None:
        baseline_date, baseline_rows, tenure_date, tenure_rows = published
    else:
        baseline_date = report_repo.baseline_date(db, run.report_date)
        baseline_rows = report_repo.get_baseline_rows(db, run.report_date, baseline_date)
        tenure_date, loaded_tenure_rows = report_repo.load_tenure_snapshot(
            db, run.report_date
        )
        tenure_rows = tuple(loaded_tenure_rows)
        if report_kind == "daily" and (baseline_date is None or not baseline_rows):
            raise BaselineMissingError("日报预览缺少已发布基线")
        if baseline_date is None:
            baseline_date = cal.prev_workday(run.report_date)
        if not baseline_rows:
            baseline_rows = {8: 0, 9: 0, 13: 0, 14: 0, 30: 0}

    week_start, _ = cal.week_bounds(run.report_date)
    reconciliation = _daily_reconciliation(db, week_start, run.report_date)
    log.info(
        "preview bundle run=%s kind=%s stage=reconciliation seconds=%.3f",
        run.id,
        report_kind,
        time.perf_counter() - bundle_started,
    )
    result = FactBundleService(db).build(
        run.id,
        baseline_date=baseline_date,
        baseline_rows=baseline_rows,
        tenure_snapshot_date=tenure_date,
        tenure_rows=tenure_rows,
        daily_reconciliation=reconciliation,
    )
    log.info(
        "preview bundle run=%s kind=%s stage=facts seconds=%.3f",
        run.id,
        report_kind,
        time.perf_counter() - bundle_started,
    )
    return result


def _payload(
    run: ReportRun,
    report_kind: str,
    period_start: date,
    period_end: date,
    ctx: Mapping[str, Any],
    events: tuple[dict[str, Any], ...],
    summary: ValidationSummary,
) -> dict[str, Any]:
    rows = {
        str(number): {
            "label": info.get("item"),
            "value": _jsonable(info.get("value")),
            "is_blank": bool(info.get("is_blank")),
        }
        for number, info in sorted((ctx.get("rows") or {}).items())
    }
    return {
        "report_kind": report_kind,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "rule_version": run.rule_version,
        "rows": rows,
        "main_rows": _jsonable(ctx.get("main_rows") or []),
        "cc_rows": _jsonable(ctx.get("cc_rows") or []),
        "tenure": _jsonable(ctx.get("tenure") or {}),
        "events": _jsonable(events),
        "validation_summary": _jsonable(asdict(summary)),
    }


def build_preview(
    db: Session,
    run_id: str,
    report_kind: str,
    *,
    bundle: FactBundle | None = None,
    week_start: date | None = None,
    week_end: date | None = None,
    persist_preview_hash: bool = True,
    reuse_published_snapshot: bool = True,
    replay_published_baseline: bool = True,
) -> PreviewSnapshot:
    started = time.perf_counter()
    last_checkpoint = started

    def checkpoint(stage: str) -> None:
        nonlocal last_checkpoint
        now = time.perf_counter()
        log.info(
            "preview stage run=%s kind=%s stage=%s stage_seconds=%.3f total_seconds=%.3f",
            run_id,
            report_kind,
            stage,
            now - last_checkpoint,
            now - started,
        )
        last_checkpoint = now

    if report_kind not in {"daily", "weekly"}:
        raise ValueError(f"unsupported report kind: {report_kind}")
    checkpoint("start")
    run = db.get(ReportRun, run_id)
    if run is None or run.is_deleted:
        raise LookupError(f"Run {run_id} was not found")
    published = _published_preview(db, run, report_kind)
    checkpoint("published_lookup")
    if published is not None and reuse_published_snapshot:
        checkpoint("published_snapshot")
        return published
    if published is None:
        require_current_baseline(db, run)
    bundle = bundle or _build_bundle(
        db,
        run,
        report_kind,
        replay_published_baseline=replay_published_baseline,
    )
    checkpoint("fact_bundle")
    if bundle.report_date != run.report_date:
        raise ValueError("FactBundle report_date does not match Run")
    if bundle.rule_version != run.rule_version:
        raise ValueError("FactBundle rule_version does not match Run")

    agent = CalculationAgent()
    if report_kind == "daily":
        ctx = agent.run_daily_bundle(bundle)
        period_start = period_end = run.report_date
    else:
        default_start, default_end = cal.week_bounds(run.report_date)
        period_start = week_start or default_start
        period_end = week_end or min(default_end, run.report_date)
        ctx = agent.run_weekly_bundle(bundle, period_start, period_end)
        ctx["validations"] = [
            *(ctx.get("validations") or ()),
            {
                "check": "周报仅可在本周最后一个工作日发布",
                "validation_code": "weekly_last_workday_only",
                "passed": (
                    cal.is_last_workday_of_week(run.report_date)
                    and period_end == run.report_date
                ),
                "hard_block": True,
            },
        ]
    checkpoint("calculation")

    if published is not None:
        summary = _recalculated_validation_summary(
            run,
            report_kind,
            bundle,
            ctx,
            published,
        )
        checkpoint("validation_replay")
    else:
        replace_calculation_validations(
            db,
            run.id,
            report_kind,
            checks=ctx.get("validations") or (),
            review_items=ctx.get("review_items") or (),
        )
        checkpoint("validation_persistence")
        summary = validate_run_target(db, run.id, report_kind)
        checkpoint("target_validation")
    events = _safe_events(bundle)
    payload = _payload(
        run, report_kind, period_start, period_end, ctx, events, summary
    )
    snapshot_json = encode_json_text(payload)
    snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

    rows = MappingProxyType(
        {
            int(number): PreviewRow(
                number=int(number),
                label=info.get("item"),
                value=info.get("value"),
                is_blank=bool(info.get("is_blank")),
            )
            for number, info in (ctx.get("rows") or {}).items()
        }
    )
    target = run_repo.ensure_report_targets(db, run.id, (report_kind,))[0]
    if persist_preview_hash:
        target.preview_hash = snapshot_hash
        db.commit()
    checkpoint("snapshot_commit")
    return PreviewSnapshot(
        run_id=run.id,
        report_kind=report_kind,
        period_start=period_start,
        period_end=period_end,
        rule_version=run.rule_version,
        rows=rows,
        main_rows=tuple(copy.deepcopy(ctx.get("main_rows") or ())),
        cc_rows=tuple(copy.deepcopy(ctx.get("cc_rows") or ())),
        tenure=MappingProxyType(copy.deepcopy(ctx.get("tenure") or {})),
        events=events,
        validation_summary=summary,
        snapshot_json=snapshot_json,
        snapshot_hash=snapshot_hash,
        calculation_context=MappingProxyType(copy.deepcopy(ctx)),
        baseline_rows=MappingProxyType(dict(bundle.baseline_rows)),
    )
