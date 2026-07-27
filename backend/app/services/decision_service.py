"""Typed answers for Run review decisions.

Handlers may change canonical fact classifications or source relationships. They
never accept direct report-row values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.facts import (
    RecruitmentSnapshot,
    ReleaseFact,
    RunDecision,
    decode_json_text,
    encode_json_text,
)
from app.models.runs import ReportRun
from app.repositories import fact_repo
from app.services.review_service import WEEKLY_DEDUPE_ANSWER
from app.utils.dates import parse_date


class InvalidDecisionAnswer(ValueError):
    pass


class DecisionNotFound(LookupError):
    pass


class DecisionAnswerConflict(InvalidDecisionAnswer):
    pass


@dataclass(frozen=True)
class DecisionItem:
    id: str
    report_kind: str | None
    decision_code: str
    fact_ref: str
    question: str
    options: tuple[Any, ...]
    answer: Any
    status: str
    decided_at: datetime | None
    operator_ref: str | None


def _decision_item(decision: RunDecision) -> DecisionItem:
    options = decode_json_text(decision.options) or ()
    return DecisionItem(
        id=decision.id,
        report_kind=decision.report_kind,
        decision_code=decision.decision_code,
        fact_ref=decision.fact_ref,
        question=decision.question,
        options=tuple(options),
        answer=decode_json_text(decision.answer),
        status=decision.status,
        decided_at=decision.decided_at,
        operator_ref=decision.operator_ref,
    )


def list_decisions(
    db: Session, run_id: str, report_kind: str | None = None
) -> list[DecisionItem]:
    query = select(RunDecision).where(
        RunDecision.run_id == run_id,
        RunDecision.is_deleted == 0,
    )
    if report_kind is not None:
        if report_kind not in {"daily", "weekly"}:
            raise ValueError(f"unsupported report kind: {report_kind}")
        query = query.where(
            or_(
                RunDecision.report_kind.is_(None),
                RunDecision.report_kind == report_kind,
            )
        )
    records = db.scalars(query.order_by(RunDecision.create_time, RunDecision.id)).all()
    return [_decision_item(record) for record in records]


_FINAL_ROW_KEY = re.compile(r"^row\s*\d+$", re.IGNORECASE)
_FORBIDDEN_ANSWER_KEYS = {
    "rows",
    "report_value",
    "final_value",
    "日报数值",
    "周报数值",
    "最终数值",
}


def _contains_final_report_override(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().casefold()
            if normalized in _FORBIDDEN_ANSWER_KEYS or _FINAL_ROW_KEY.fullmatch(
                normalized
            ):
                return True
            if _contains_final_report_override(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_final_report_override(item) for item in value)
    return False


def _source_ref(decision: RunDecision, expected_source: str) -> str:
    parts = decision.fact_ref.split(":")
    if len(parts) != 4 or parts[:2] != ["source", expected_source] or parts[2] != "row":
        raise InvalidDecisionAnswer(
            f"decision fact reference is not a {expected_source} source row"
        )
    return parts[3]


def _release_fact(db: Session, run_id: str, decision: RunDecision) -> ReleaseFact:
    row = _source_ref(decision, "release")
    if not row.isdigit():
        raise InvalidDecisionAnswer("release decision requires a numeric source row")
    fact = db.scalar(
        select(ReleaseFact).where(
            ReleaseFact.run_id == run_id,
            ReleaseFact.source_row_no == int(row),
            ReleaseFact.is_deleted == 0,
        )
    )
    if fact is None:
        raise InvalidDecisionAnswer("referenced release fact was not found")
    return fact


def _answer_release_row5(
    db: Session, run: ReportRun, decision: RunDecision, answer: Any
) -> str:
    if answer == "替换输入":
        return "replacement_required"
    mapping = {"计入Row5": "include", "不计入Row5": "exclude"}
    if answer not in mapping:
        raise InvalidDecisionAnswer("release Row5 answer must use a listed option")
    _release_fact(db, run.id, decision).row5_classification = mapping[answer]
    return "answered"


def _answer_release_lwd(
    db: Session, run: ReportRun, decision: RunDecision, answer: Any
) -> str:
    fact = _release_fact(db, run.id, decision)
    if not isinstance(answer, dict):
        raise InvalidDecisionAnswer("release LWD answer requires last_working_day")
    if set(answer) != {"last_working_day"}:
        raise InvalidDecisionAnswer("release LWD answer requires only last_working_day")
    last_working_day = parse_date(answer.get("last_working_day"))
    if last_working_day is None:
        raise InvalidDecisionAnswer("last_working_day must be a valid date")
    classification = (
        "include"
        if (last_working_day.year, last_working_day.month)
        == (run.report_date.year, run.report_date.month)
        else "exclude"
    )
    fact.last_working_day = last_working_day
    fact.row30_classification = classification
    return "answered"


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidDecisionAnswer(f"{field} must be a non-negative integer")
    return value


def _answer_recruitment_labels(
    db: Session, run: ReportRun, decision: RunDecision, answer: Any
) -> str:
    if answer == "替换输入":
        return "replacement_required"
    if not isinstance(answer, dict):
        raise InvalidDecisionAnswer("recruitment answer requires both forecast values")
    fields = {
        "previous_month_offer_current_month_onboard",
        "current_month_offer_current_month_onboard",
    }
    if set(answer) != fields:
        raise InvalidDecisionAnswer("recruitment answer requires exactly two fields")
    row = _source_ref(decision, "recruitment")
    if not row.isdigit():
        raise InvalidDecisionAnswer("recruitment decision requires a numeric source row")
    fact = db.scalar(
        select(RecruitmentSnapshot).where(
            RecruitmentSnapshot.run_id == run.id,
            RecruitmentSnapshot.source_row_no == int(row),
            RecruitmentSnapshot.is_deleted == 0,
        )
    )
    if fact is None:
        raise InvalidDecisionAnswer("referenced recruitment fact was not found")
    fact.previous_month_offer_current_month_onboard = _non_negative_int(
        answer["previous_month_offer_current_month_onboard"],
        "previous_month_offer_current_month_onboard",
    )
    fact.current_month_offer_current_month_onboard = _non_negative_int(
        answer["current_month_offer_current_month_onboard"],
        "current_month_offer_current_month_onboard",
    )
    return "answered"


def _answer_ocr_review(
    db: Session, run: ReportRun, decision: RunDecision, answer: Any
) -> str:
    if answer == "替换输入":
        return "replacement_required"
    if answer != "确认":
        raise InvalidDecisionAnswer("OCR review answer must be 确认 or 替换输入")
    parts = decision.fact_ref.split(":")
    if len(parts) != 4 or parts[0] != "source" or parts[2:] != ["row", "ocr"]:
        raise InvalidDecisionAnswer("OCR decision has an invalid source reference")
    model = {"release": ReleaseFact, "recruitment": RecruitmentSnapshot}.get(parts[1])
    if model is None:
        raise InvalidDecisionAnswer("OCR confirmation is unsupported for this source")
    facts = db.scalars(
        select(model).where(model.run_id == run.id, model.is_deleted == 0)
    ).all()
    for fact in facts:
        fact.ocr_confidence = "confirmed"
    return "answered"


def _answer_weekly_dedupe(
    db: Session, run: ReportRun, decision: RunDecision, answer: Any
) -> str:
    del db, run, decision
    if answer != WEEKLY_DEDUPE_ANSWER:
        raise InvalidDecisionAnswer(
            "weekly duplicate review answer must use the listed option"
        )
    return "answered"


def _answer_weekly_top3_tie(
    db: Session, run: ReportRun, decision: RunDecision, answer: Any
) -> str:
    del db, run
    parts = decision.fact_ref.split(":")
    if (
        len(parts) != 4
        or parts[:2] != ["weekly", "top3_cutoff_tie"]
        or not parts[3].isdigit()
    ):
        raise InvalidDecisionAnswer("周报前三项目决策引用无效")
    slots = int(parts[3])
    if not isinstance(answer, list) or len(answer) != slots:
        raise InvalidDecisionAnswer(f"周报前三项目必须恰好选择 {slots} 项")
    if len(set(answer)) != slots:
        raise InvalidDecisionAnswer("周报前三项目不能重复选择")
    options = decode_json_text(decision.options) or []
    if not all(isinstance(value, str) and value in options for value in answer):
        raise InvalidDecisionAnswer("周报前三项目只能从候选项中选择")
    return "answered"


DecisionHandler = Callable[[Session, ReportRun, RunDecision, Any], str]


@dataclass(frozen=True)
class DecisionHandlerSpec:
    handler: DecisionHandler
    mutates_shared_facts: bool


_HANDLERS: dict[str, DecisionHandlerSpec] = {
    "release_row5_classification_required": DecisionHandlerSpec(
        _answer_release_row5, mutates_shared_facts=True
    ),
    "release_lwd_missing": DecisionHandlerSpec(
        _answer_release_lwd, mutates_shared_facts=True
    ),
    "recruitment_label_uncertain": DecisionHandlerSpec(
        _answer_recruitment_labels, mutates_shared_facts=True
    ),
    "ocr_review_required": DecisionHandlerSpec(
        _answer_ocr_review, mutates_shared_facts=True
    ),
    "multiple_active_employments": DecisionHandlerSpec(
        _answer_weekly_dedupe, mutates_shared_facts=False
    ),
    "top3_cutoff_tie": DecisionHandlerSpec(
        _answer_weekly_top3_tie, mutates_shared_facts=False
    ),
}


def answer_decision(
    db: Session,
    run_id: str,
    decision_id: str,
    answer: Any,
    operator_ref: str,
) -> RunDecision:
    operator = str(operator_ref or "").strip()
    if not operator:
        raise InvalidDecisionAnswer("operator_ref is required")
    if _contains_final_report_override(answer):
        raise InvalidDecisionAnswer("final report row values cannot be set by a decision")

    run = db.get(ReportRun, run_id)
    decision = db.get(RunDecision, decision_id)
    if (
        run is None
        or run.is_deleted
        or decision is None
        or decision.is_deleted
        or decision.run_id != run_id
    ):
        raise DecisionNotFound(f"decision {decision_id} was not found in Run {run_id}")
    if decision.status == "answered":
        if decode_json_text(decision.answer) == answer:
            return decision
        raise DecisionAnswerConflict(
            "decision has already been answered with a different answer"
        )
    handler_spec = _HANDLERS.get(decision.decision_code)
    if handler_spec is None:
        raise InvalidDecisionAnswer(
            f"unsupported decision code: {decision.decision_code}"
        )

    if handler_spec.mutates_shared_facts:
        fact_repo.assert_run_facts_mutable(db, run_id)
    try:
        status = handler_spec.handler(db, run, decision, answer)
        decision.answer = encode_json_text(answer)
        decision.status = status
        decision.operator_ref = operator
        decision.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return decision
