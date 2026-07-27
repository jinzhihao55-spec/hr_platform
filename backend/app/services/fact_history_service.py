"""Materialize cross-Run first-visible dates and a minimal event ledger."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import constants as C
from app.models.facts import (
    EmploymentFact,
    FactEvent,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    decode_json_text,
    encode_json_text,
)
from app.models.publication import PublishedReport
from app.models.runs import ReportRun
from app.repositories import fact_repo
from app.utils.dates import parse_date


def _visible_date(
    *,
    explicit: date | None,
    previous: date | None,
    effective: date | None,
    report_date: date,
    has_previous_snapshot: bool,
) -> date | None:
    if explicit is not None:
        return explicit
    if previous is not None:
        return previous
    if effective is None:
        return None
    return report_date if has_previous_snapshot else effective


def _event_key(*parts: object) -> str:
    payload = "|".join("" if value is None else str(value) for value in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_departed_status(value: str | None) -> bool:
    status = str(value or "").strip().casefold()
    return status == "resigned" or "离" in status


def _materialize_employments(
    db: Session,
    run: ReportRun,
    baseline_run_id: str,
    has_previous_snapshot: bool,
) -> list[EmploymentFact]:
    previous = db.scalars(
        select(EmploymentFact).where(EmploymentFact.run_id == baseline_run_id)
    ).all()
    current = db.scalars(
        select(EmploymentFact)
        .where(EmploymentFact.run_id == run.id)
        .order_by(EmploymentFact.source_row_no)
    ).all()
    previous_by_employee = {fact.employee_no: fact for fact in previous}
    for fact in current:
        visible = decode_json_text(fact.first_visible_dates) or {}
        prior = previous_by_employee.get(fact.employee_no)
        prior_visible = (
            decode_json_text(prior.first_visible_dates) or {} if prior else {}
        )
        hire = _visible_date(
            explicit=parse_date(visible.get("hire")),
            previous=(
                parse_date(prior_visible.get("hire")) or prior.entry_date
                if prior
                else None
            ),
            effective=fact.entry_date,
            report_date=run.report_date,
            has_previous_snapshot=has_previous_snapshot,
        )
        leave = _visible_date(
            explicit=parse_date(visible.get("leave")),
            previous=(
                parse_date(prior_visible.get("leave")) or prior.resign_date
                if prior
                else None
            ),
            effective=fact.resign_date,
            report_date=run.report_date,
            has_previous_snapshot=has_previous_snapshot,
        )
        fact.first_visible_dates = encode_json_text(
            {
                key: value.isoformat()
                for key, value in (("hire", hire), ("leave", leave))
                if value is not None
            }
        )
    return list(current)


def _carry_forward_effective_departures(
    db: Session,
    run: ReportRun,
    baseline_run_id: str,
    employments: list[EmploymentFact],
    resignations: list[ResignationFact],
) -> list[EmploymentFact]:
    """Restore a departed employee omitted from the current personnel snapshot.

    The personnel export can drop a person on their last working day. Carrying
    every missing row would hide truncated inputs, so this is limited to either
    a matching effective resignation or a personnel-only departure that was
    already visible in the published baseline during the current week. Negative
    row numbers distinguish derived history rows from uploaded rows.
    """
    current_employee_numbers = {
        fact.employee_no for fact in employments if fact.employee_no
    }
    candidates: dict[str, list[ResignationFact]] = {}
    resignation_employee_numbers: set[str] = set()
    rejected = C.get_process_status_rejected()
    pending = C.get_process_status_row3_pending()
    for resignation in resignations:
        employee_no = str(resignation.employee_no or "").strip()
        if employee_no:
            resignation_employee_numbers.add(employee_no)
        status = str(resignation.process_status or "")
        if (
            not employee_no
            or resignation.last_working_day is None
            or resignation.last_working_day > run.report_date
            or status in rejected
            or status in pending
        ):
            continue
        first_visible = resignation.first_visible_date or run.report_date
        if first_visible > run.report_date:
            continue
        candidates.setdefault(employee_no, []).append(resignation)

    previous = db.scalars(
        select(EmploymentFact)
        .where(EmploymentFact.run_id == baseline_run_id)
        .order_by(EmploymentFact.source_row_no, EmploymentFact.id)
    ).all()
    previous_by_employee = {
        fact.employee_no: fact for fact in previous if fact.employee_no
    }
    week_start = run.report_date - timedelta(days=run.report_date.weekday())
    personnel_only_departures: dict[str, tuple[date, date]] = {}
    for employee_no, prior in previous_by_employee.items():
        if employee_no in resignation_employee_numbers:
            continue
        visible = decode_json_text(prior.first_visible_dates) or {}
        leave_date = prior.resign_date
        leave_visible = parse_date(visible.get("leave")) or leave_date
        attribution_date = max(
            value for value in (leave_date, leave_visible) if value is not None
        ) if leave_date is not None or leave_visible is not None else None
        if (
            _is_departed_status(prior.status)
            and leave_date is not None
            and leave_visible is not None
            and attribution_date is not None
            and week_start <= attribution_date <= run.report_date
        ):
            personnel_only_departures[employee_no] = (leave_date, leave_visible)

    employee_numbers = set(candidates) | set(personnel_only_departures)
    if not employee_numbers:
        return employments

    used_rows = {fact.source_row_no for fact in employments}
    next_derived_row = -1

    for employee_no in sorted(employee_numbers):
        if employee_no in current_employee_numbers:
            continue
        prior = previous_by_employee.get(employee_no)
        if prior is None:
            continue
        resignation = None
        if employee_no in candidates:
            resignation = max(
                candidates[employee_no],
                key=lambda fact: (
                    fact.last_working_day or date.min,
                    fact.application_date or date.min,
                    fact.process_no,
                ),
            )
        while next_derived_row in used_rows:
            next_derived_row -= 1
        prior_visible = decode_json_text(prior.first_visible_dates) or {}
        hire_visible = parse_date(prior_visible.get("hire")) or prior.entry_date
        if resignation is not None:
            leave_date = resignation.last_working_day
            leave_visible = resignation.first_visible_date or run.report_date
        else:
            leave_date, leave_visible = personnel_only_departures[employee_no]
        carried = EmploymentFact(
            run_id=run.id,
            source_row_no=next_derived_row,
            person_id=prior.person_id,
            employee_no=prior.employee_no,
            display_name=prior.display_name,
            employee_type=prior.employee_type,
            status="离职",
            entry_date=prior.entry_date,
            resign_date=leave_date,
            business_unit=prior.business_unit,
            business_unit_no=prior.business_unit_no,
            project_code=prior.project_code,
            project_name=prior.project_name,
            contract_dates=prior.contract_dates,
            first_visible_dates=encode_json_text(
                {
                    key: value.isoformat()
                    for key, value in (
                        ("hire", hire_visible),
                        ("leave", leave_visible),
                    )
                    if value is not None
                }
            ),
        )
        db.add(carried)
        employments.append(carried)
        current_employee_numbers.add(employee_no)
        used_rows.add(next_derived_row)
        next_derived_row -= 1
    db.flush()
    return employments


def _materialize_resignations(
    db: Session,
    run: ReportRun,
    baseline_run_id: str,
    has_previous_snapshot: bool,
    baseline_date: date,
) -> list[ResignationFact]:
    previous = db.scalars(
        select(ResignationFact).where(ResignationFact.run_id == baseline_run_id)
    ).all()
    current = db.scalars(
        select(ResignationFact)
        .where(ResignationFact.run_id == run.id)
        .order_by(ResignationFact.source_row_no)
    ).all()
    previous_by_process = {fact.process_no: fact for fact in previous}
    for fact in current:
        prior = previous_by_process.get(fact.process_no)
        fact.first_visible_date = _visible_date(
            explicit=fact.first_visible_date,
            previous=(
                prior.first_visible_date or prior.application_date if prior else None
            ),
            effective=fact.application_date,
            report_date=run.report_date,
            has_previous_snapshot=(
                has_previous_snapshot
                and (
                    fact.application_date is None
                    or fact.application_date >= baseline_date
                )
            ),
        )
    return list(current)


def _materialize_releases(
    db: Session,
    run: ReportRun,
    baseline_run_id: str,
    has_previous_snapshot: bool,
    baseline_date: date,
) -> list[ReleaseFact]:
    previous = db.scalars(
        select(ReleaseFact).where(ReleaseFact.run_id == baseline_run_id)
    ).all()
    current = db.scalars(
        select(ReleaseFact)
        .where(ReleaseFact.run_id == run.id)
        .order_by(ReleaseFact.source_row_no)
    ).all()
    previous_by_order = {fact.order_no: fact for fact in previous}
    for fact in current:
        prior = previous_by_order.get(fact.order_no)
        fact.first_visible_date = _visible_date(
            explicit=fact.first_visible_date,
            previous=(
                prior.first_visible_date or prior.application_date if prior else None
            ),
            effective=fact.application_date,
            report_date=run.report_date,
            has_previous_snapshot=(
                has_previous_snapshot
                and (
                    fact.application_date is None
                    or fact.application_date >= baseline_date
                )
            ),
        )
    return list(current)


def _replace_events(
    db: Session,
    run: ReportRun,
    employments: list[EmploymentFact],
    resignations: list[ResignationFact],
    releases: list[ReleaseFact],
) -> None:
    db.execute(delete(FactEvent).where(FactEvent.run_id == run.id))
    for fact in employments:
        visible = decode_json_text(fact.first_visible_dates) or {}
        carried_from_history = fact.source_row_no < 0
        for event_type, effective, first_visible in (
            ("hire", fact.entry_date, parse_date(visible.get("hire"))),
            ("leave", fact.resign_date, parse_date(visible.get("leave"))),
        ):
            if effective is None:
                continue
            db.add(
                FactEvent(
                    run_id=run.id,
                    event_key=_event_key(
                        event_type, fact.person_id, fact.employee_no, effective
                    ),
                    event_type=event_type,
                    person_id=fact.person_id,
                    employment_ref=fact.id,
                    source_type=(
                        "personnel_history" if carried_from_history else "personnel"
                    ),
                    source_event_ref=(
                        fact.id if carried_from_history else fact.employee_no
                    ),
                    effective_date=effective,
                    first_visible_date=first_visible,
                    classification="deterministic",
                    minimal_payload=(
                        encode_json_text({"derived": "effective_departure"})
                        if carried_from_history
                        else None
                    ),
                )
            )
    for fact in resignations:
        db.add(
            FactEvent(
                run_id=run.id,
                event_key=_event_key(
                    "resignation_proposed", fact.process_no, fact.application_date
                ),
                event_type="resignation_proposed",
                person_id=fact.person_id,
                source_type="resignation",
                source_event_ref=fact.process_no,
                effective_date=fact.application_date,
                first_visible_date=fact.first_visible_date,
                classification="deterministic",
            )
        )
    for fact in releases:
        db.add(
            FactEvent(
                run_id=run.id,
                event_key=_event_key(
                    "release_proposed", fact.order_no, fact.application_date
                ),
                event_type="release_proposed",
                person_id=fact.person_id,
                source_type="release",
                source_event_ref=fact.order_no,
                effective_date=fact.application_date,
                first_visible_date=fact.first_visible_date,
                classification=fact.row5_classification,
            )
        )
    db.flush()


def materialize_run_history(
    db: Session, run: ReportRun, baseline: PublishedReport
) -> None:
    """Resolve first-visible dates once, before the Run becomes immutable."""
    if baseline.report_kind != "daily" or baseline.period_end >= run.report_date:
        raise ValueError("baseline must be an earlier published daily report")
    fact_repo.assert_run_facts_mutable(db, run.id)
    fact_models = (
        EmploymentFact,
        ResignationFact,
        ReleaseFact,
        RecruitmentSnapshot,
    )
    has_previous_snapshot = any(
        db.scalar(
            select(model.id).where(model.run_id == baseline.run_id).limit(1)
        )
        is not None
        for model in fact_models
    )
    resignations = _materialize_resignations(
        db,
        run,
        baseline.run_id,
        has_previous_snapshot,
        baseline.period_end,
    )
    employments = _materialize_employments(
        db, run, baseline.run_id, has_previous_snapshot
    )
    employments = _carry_forward_effective_departures(
        db,
        run,
        baseline.run_id,
        employments,
        resignations,
    )
    releases = _materialize_releases(
        db,
        run,
        baseline.run_id,
        has_previous_snapshot,
        baseline.period_end,
    )
    _replace_events(db, run, employments, resignations, releases)


def materialize_initial_history(db: Session, run: ReportRun) -> None:
    """Seed first-visible dates from the four confirmed bootstrap sources."""
    fact_repo.assert_run_facts_mutable(db, run.id)
    employments = db.scalars(
        select(EmploymentFact)
        .where(EmploymentFact.run_id == run.id)
        .order_by(EmploymentFact.source_row_no)
    ).all()
    for fact in employments:
        visible = decode_json_text(fact.first_visible_dates) or {}
        hire = parse_date(visible.get("hire")) or fact.entry_date
        leave = parse_date(visible.get("leave")) or fact.resign_date
        fact.first_visible_dates = encode_json_text(
            {
                key: value.isoformat()
                for key, value in (("hire", hire), ("leave", leave))
                if value is not None
            }
        )

    resignations = db.scalars(
        select(ResignationFact)
        .where(ResignationFact.run_id == run.id)
        .order_by(ResignationFact.source_row_no)
    ).all()
    for fact in resignations:
        fact.first_visible_date = fact.first_visible_date or fact.application_date

    releases = db.scalars(
        select(ReleaseFact)
        .where(ReleaseFact.run_id == run.id)
        .order_by(ReleaseFact.source_row_no)
    ).all()
    for fact in releases:
        fact.first_visible_date = fact.first_visible_date or fact.application_date

    _replace_events(
        db,
        run,
        list(employments),
        list(resignations),
        list(releases),
    )
