"""Build calculator-ready frames from one Run's canonical fact records."""

from __future__ import annotations

from datetime import date
import time
from typing import Any, Mapping, Sequence

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fact_bundle import FactBundle
from app.core.logging import get_logger
from app.models.facts import (
    EmploymentFact,
    FactEvent,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    RunDecision,
    decode_json_text,
)
from app.models.runs import ReportRun
from app.utils.dates import parse_date


log = get_logger(__name__)


_EMPLOYMENT_COLUMNS = (
    "source_row_no",
    "person_id",
    "person_key",
    "emp_no",
    "employee_type",
    "employee_status",
    "hire_date",
    "leave_date",
    "hire_first_visible",
    "leave_first_visible",
    "business_unit",
    "business_unit_no",
    "department",
    "project_no",
    "project_name",
)
_RESIGNATION_COLUMNS = (
    "person_id",
    "process_no",
    "emp_no",
    "process_status",
    "resignation_type",
    "last_working_day",
    "apply_time",
    "application_date",
    "name",
)
_RELEASE_COLUMNS = (
    "order_no",
    "is_release",
    "counts_row5",
    "manual_row5_include",
    "in_month_release",
    "lwd_pending",
    "first_seen_batch",
    "apply_date",
    "current_status",
)
_RECRUITMENT_COLUMNS = (
    "is_total_row",
    "prev_month_offer_curr_join",
    "curr_month_offer_curr_join",
)
_EVENT_COLUMNS = (
    "event_key",
    "event_type",
    "person_id",
    "employment_ref",
    "source_type",
    "source_event_ref",
    "effective_date",
    "first_visible_date",
    "classification",
    "minimal_payload",
)


def _status(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    if "离" in text or text == "resigned":
        return "resigned"
    if "转签" in text or text == "transferred":
        return "transferred"
    return "active"


def _frame(rows: list[dict[str, Any]], columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


class FactBundleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build(
        self,
        run_id: str,
        *,
        baseline_date: date,
        baseline_rows: Mapping[int, int],
        tenure_snapshot_date: date | None = None,
        tenure_rows: Sequence[Mapping[str, Any]] = (),
        daily_reconciliation: Mapping[str, Any] | None = None,
    ) -> FactBundle:
        started = time.perf_counter()
        run = self.db.get(ReportRun, run_id)
        if run is None or run.is_deleted:
            raise LookupError(f"Run {run_id} was not found")

        employment_rows, names = self._employment_rows(run.id)
        log.info(
            "fact bundle run=%s stage=employments seconds=%.3f",
            run_id,
            time.perf_counter() - started,
        )
        resignations = self._resignation_rows(run.id, names)
        log.info(
            "fact bundle run=%s stage=resignations seconds=%.3f",
            run_id,
            time.perf_counter() - started,
        )
        releases = self._release_rows(run.id)
        log.info(
            "fact bundle run=%s stage=releases seconds=%.3f",
            run_id,
            time.perf_counter() - started,
        )
        recruitment = self._recruitment_rows(run.id)
        log.info(
            "fact bundle run=%s stage=recruitment seconds=%.3f",
            run_id,
            time.perf_counter() - started,
        )
        events = self._event_rows(run.id)
        log.info(
            "fact bundle run=%s stage=events seconds=%.3f",
            run_id,
            time.perf_counter() - started,
        )
        decisions = self._decision_rows(run.id)
        log.info(
            "fact bundle run=%s stage=decisions seconds=%.3f",
            run_id,
            time.perf_counter() - started,
        )
        return FactBundle(
            report_date=run.report_date,
            baseline_date=baseline_date,
            rule_version=run.rule_version,
            employments=_frame(employment_rows, _EMPLOYMENT_COLUMNS),
            resignations=_frame(resignations, _RESIGNATION_COLUMNS),
            releases=_frame(releases, _RELEASE_COLUMNS),
            recruitment=_frame(recruitment, _RECRUITMENT_COLUMNS),
            events=_frame(events, _EVENT_COLUMNS),
            decisions=tuple(decisions),
            baseline_rows=baseline_rows,
            tenure_snapshot_date=tenure_snapshot_date,
            tenure_rows=tuple(dict(row) for row in tenure_rows),
            daily_reconciliation=daily_reconciliation or {},
        )

    def _employment_rows(
        self, run_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
        records = self.db.execute(
            select(EmploymentFact, PersonIdentity.person_key)
            .join(PersonIdentity, EmploymentFact.person_id == PersonIdentity.id)
            .where(EmploymentFact.run_id == run_id)
            .order_by(EmploymentFact.source_row_no)
        ).all()
        rows: list[dict[str, Any]] = []
        names: dict[str, str | None] = {}
        for fact, person_key in records:
            first_visible = decode_json_text(fact.first_visible_dates) or {}
            names[fact.employee_no] = fact.display_name
            rows.append(
                {
                    "source_row_no": fact.source_row_no,
                    "person_id": fact.person_id,
                    "person_key": person_key,
                    "emp_no": fact.employee_no,
                    "employee_type": fact.employee_type,
                    "employee_status": _status(fact.status),
                    "hire_date": fact.entry_date,
                    "leave_date": fact.resign_date,
                    "hire_first_visible": parse_date(first_visible.get("hire"))
                    or fact.entry_date,
                    "leave_first_visible": parse_date(first_visible.get("leave"))
                    or fact.resign_date,
                    "business_unit": fact.business_unit,
                    "business_unit_no": fact.business_unit_no,
                    "department": None,
                    "project_no": fact.project_code,
                    "project_name": fact.project_name or fact.project_code,
                }
            )
        return rows, names

    def _resignation_rows(
        self, run_id: str, names: Mapping[str, str | None]
    ) -> list[dict[str, Any]]:
        records = self.db.scalars(
            select(ResignationFact)
            .where(ResignationFact.run_id == run_id)
            .order_by(ResignationFact.source_row_no)
        ).all()
        return [
            {
                "person_id": fact.person_id,
                "process_no": fact.process_no,
                "emp_no": fact.employee_no,
                "process_status": fact.process_status,
                "resignation_type": fact.resignation_type,
                "last_working_day": fact.last_working_day,
                "apply_time": (
                    pd.Timestamp(fact.first_visible_date or fact.application_date)
                    if fact.first_visible_date is not None
                    or fact.application_date is not None
                    else None
                ),
                "application_date": (
                    pd.Timestamp(fact.application_date)
                    if fact.application_date is not None
                    else None
                ),
                "name": names.get(fact.employee_no or ""),
            }
            for fact in records
        ]

    def _release_rows(self, run_id: str) -> list[dict[str, Any]]:
        manual_row5_rows: set[int] = set()
        decisions = self.db.scalars(
            select(RunDecision).where(
                RunDecision.run_id == run_id,
                RunDecision.decision_code
                == "release_row5_classification_required",
                RunDecision.status == "answered",
                RunDecision.is_deleted == 0,
            )
        ).all()
        for decision in decisions:
            parts = (decision.fact_ref or "").split(":")
            if (
                len(parts) == 4
                and parts[:3] == ["source", "release", "row"]
                and parts[3].isdigit()
                and decode_json_text(decision.answer) == "计入Row5"
            ):
                manual_row5_rows.add(int(parts[3]))

        records = self.db.scalars(
            select(ReleaseFact)
            .where(ReleaseFact.run_id == run_id)
            .order_by(ReleaseFact.source_row_no)
        ).all()
        return [
            {
                "order_no": fact.order_no,
                "is_release": fact.row5_classification == "include",
                "counts_row5": fact.row5_classification == "include",
                "manual_row5_include": fact.source_row_no in manual_row5_rows,
                "in_month_release": fact.row30_classification == "include",
                "lwd_pending": fact.row30_classification == "review",
                "first_seen_batch": fact.first_visible_date,
                "apply_date": fact.application_date,
                "current_status": fact.process_status,
            }
            for fact in records
        ]

    def _recruitment_rows(self, run_id: str) -> list[dict[str, Any]]:
        records = self.db.scalars(
            select(RecruitmentSnapshot)
            .where(RecruitmentSnapshot.run_id == run_id)
            .order_by(RecruitmentSnapshot.source_row_no)
        ).all()
        return [
            {
                "is_total_row": fact.is_total_row,
                "prev_month_offer_curr_join": (
                    fact.previous_month_offer_current_month_onboard
                ),
                "curr_month_offer_curr_join": (
                    fact.current_month_offer_current_month_onboard
                ),
            }
            for fact in records
        ]

    def _event_rows(self, run_id: str) -> list[dict[str, Any]]:
        records = self.db.scalars(
            select(FactEvent)
            .where(FactEvent.run_id == run_id)
            .order_by(FactEvent.event_key)
        ).all()
        return [
            {
                "event_key": fact.event_key,
                "event_type": fact.event_type,
                "person_id": fact.person_id,
                "employment_ref": fact.employment_ref,
                "source_type": fact.source_type,
                "source_event_ref": fact.source_event_ref,
                "effective_date": fact.effective_date,
                "first_visible_date": fact.first_visible_date,
                "classification": fact.classification,
                "minimal_payload": decode_json_text(fact.minimal_payload),
            }
            for fact in records
        ]

    def _decision_rows(self, run_id: str) -> list[dict[str, Any]]:
        records = self.db.scalars(
            select(RunDecision)
            .where(RunDecision.run_id == run_id, RunDecision.is_deleted == 0)
            .order_by(RunDecision.create_time, RunDecision.id)
        ).all()
        return [
            {
                "id": decision.id,
                "report_kind": decision.report_kind,
                "decision_code": decision.decision_code,
                "fact_ref": decision.fact_ref,
                "question": decision.question,
                "options": decode_json_text(decision.options),
                "answer": decode_json_text(decision.answer),
                "status": decision.status,
            }
            for decision in records
        ]
