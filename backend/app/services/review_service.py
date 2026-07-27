"""PII-minimized evidence read models for human review workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.facts import (
    EmploymentFact,
    RunDecision,
    RunValidation,
    decode_json_text,
    encode_json_text,
)
from app.models.runs import ReportRun
from app.repositories import fact_repo


class ReviewEvidenceMissing(RuntimeError):
    """The review record exists but its staged facts are no longer available."""


WEEKLY_DEDUPE_ANSWER = "确认按自然人计1人"


_RELEASE_COLUMNS = (
    {"key": "source_row_no", "label": "来源行"},
    {"key": "order_no", "label": "单号"},
    {"key": "application_date", "label": "申请日期"},
    {"key": "last_working_day", "label": "最后工作日"},
    {"key": "process_status", "label": "流程状态"},
    {"key": "row5_classification", "label": "Row5 分类"},
    {"key": "row30_classification", "label": "Row30 分类"},
    {"key": "ocr_confidence", "label": "OCR 状态"},
)

_RECRUITMENT_COLUMNS = (
    {"key": "source_row_no", "label": "来源行"},
    {"key": "report_date", "label": "报表日期"},
    {"key": "is_total_row", "label": "是否合计行"},
    {
        "key": "previous_month_offer_current_month_onboard",
        "label": "上月 Offer 当月预计入职",
    },
    {
        "key": "current_month_offer_current_month_onboard",
        "label": "当月 Offer 当月预计入职",
    },
    {"key": "recognized_labels", "label": "识别标签"},
    {"key": "ocr_confidence", "label": "OCR 状态"},
)


def _recognized_labels(value: str | None) -> list[str]:
    decoded = decode_json_text(value) or []
    if not isinstance(decoded, list):
        return []
    return [str(label) for label in decoded]


def decision_preview(
    db: Session, run_id: str, decision_id: str
) -> dict[str, Any]:
    run = db.get(ReportRun, run_id)
    decision = db.get(RunDecision, decision_id)
    if run is None or run.is_deleted or decision is None or decision.is_deleted:
        raise LookupError("Run or decision was not found")
    if decision.run_id != run_id:
        raise ValueError("decision does not belong to this Run")
    if decision.decision_code != "ocr_review_required":
        raise ValueError("decision is not an OCR review")

    parts = decision.fact_ref.split(":")
    if len(parts) != 4 or parts[0] != "source" or parts[2:] != ["row", "ocr"]:
        raise ValueError("OCR decision has an invalid source reference")
    source_type = parts[1]

    if source_type == "release":
        facts = [
            fact
            for fact in fact_repo.list_release_facts(db, run_id)
            if not fact.is_deleted
        ]
        columns = _RELEASE_COLUMNS
        rows = [
            {
                "source_row_no": fact.source_row_no,
                "order_no": fact.order_no,
                "application_date": fact.application_date,
                "last_working_day": fact.last_working_day,
                "process_status": fact.process_status,
                "row5_classification": fact.row5_classification,
                "row30_classification": fact.row30_classification,
                "ocr_confidence": fact.ocr_confidence,
            }
            for fact in facts
        ]
    elif source_type == "recruitment":
        facts = [
            fact
            for fact in fact_repo.list_recruitment_snapshots(db, run_id)
            if not fact.is_deleted
        ]
        columns = _RECRUITMENT_COLUMNS
        rows = [
            {
                "source_row_no": fact.source_row_no,
                "report_date": fact.report_date,
                "is_total_row": fact.is_total_row,
                "previous_month_offer_current_month_onboard": (
                    fact.previous_month_offer_current_month_onboard
                ),
                "current_month_offer_current_month_onboard": (
                    fact.current_month_offer_current_month_onboard
                ),
                "recognized_labels": _recognized_labels(fact.recognized_labels),
                "ocr_confidence": fact.ocr_confidence,
            }
            for fact in facts
        ]
    else:
        raise ValueError("unsupported OCR source")

    if not rows:
        raise ReviewEvidenceMissing(
            "OCR facts are no longer available; replace the input"
        )
    return {
        "kind": "ocr_source",
        "source_type": source_type,
        "columns": [dict(column) for column in columns],
        "rows": rows,
        "warnings": ["原始图片按安全策略不留存；请核对结构化结果。"],
    }


def sync_weekly_review_decisions(
    db: Session,
    run_id: str,
    review_items: Sequence[Mapping[str, Any]],
) -> None:
    existing = list(
        db.scalars(
            select(RunDecision).where(
                RunDecision.run_id == run_id,
                RunDecision.report_kind == "weekly",
                RunDecision.decision_code.in_(
                    ("multiple_active_employments", "top3_cutoff_tie")
                ),
                RunDecision.is_deleted == 0,
            )
        ).all()
    )
    by_ref = {decision.fact_ref: decision for decision in existing}
    desired_refs: set[str] = set()
    for item in review_items:
        code = item.get("code")
        if code == "top3_cutoff_tie":
            if str(item.get("severity") or "").upper() != "REVIEW":
                continue
            tie_ref = str(item.get("tie_ref") or "").strip()
            slots = item.get("slots")
            candidates = [
                str(value).strip()
                for value in item.get("candidates") or ()
                if str(value).strip()
            ]
            if (
                len(tie_ref) != 12
                or not tie_ref.isalnum()
                or not isinstance(slots, int)
                or slots < 1
                or slots >= len(candidates)
                or len(set(candidates)) != len(candidates)
            ):
                continue
            fact_ref = f"weekly:top3_cutoff_tie:{tie_ref}:{slots}"
            desired_refs.add(fact_ref)
            decision = by_ref.get(fact_ref)
            if decision is None:
                db.add(
                    RunDecision(
                        run_id=run_id,
                        report_kind="weekly",
                        decision_code="top3_cutoff_tie",
                        fact_ref=fact_ref,
                        question=(
                            f"{item.get('business_unit') or '该事业部'} 的前三项目"
                            f"在截止位并列，请选择 {slots} 个项目。"
                        ),
                        options=encode_json_text(candidates),
                        status="pending",
                    )
                )
                continue
            decision.options = encode_json_text(candidates)
            answer = decode_json_text(decision.answer)
            if decision.status == "answered" and not (
                isinstance(answer, list)
                and len(answer) == slots
                and len(set(answer)) == slots
                and set(answer).issubset(candidates)
            ):
                decision.status = "pending"
                decision.answer = None
                decision.decided_at = None
                decision.operator_ref = None
            continue
        if code != "multiple_active_employments":
            continue
        person_ref = str(item.get("person_ref") or "").strip()
        if not person_ref or str(item.get("severity") or "").upper() != "REVIEW":
            continue
        fact_ref = f"weekly:multiple_active_employments:{person_ref}"
        desired_refs.add(fact_ref)
        if fact_ref in by_ref:
            continue
        db.add(
            RunDecision(
                run_id=run_id,
                report_kind="weekly",
                decision_code="multiple_active_employments",
                fact_ref=fact_ref,
                question=(
                    "同一自然人存在多条归属维度一致的有效在职记录，"
                    "请确认按较晚入职记录归属并按1人计数。"
                ),
                options=encode_json_text([WEEKLY_DEDUPE_ANSWER]),
                status="pending",
            )
        )

    for decision in existing:
        if decision.fact_ref not in desired_refs and decision.status != "answered":
            db.delete(decision)
    db.flush()


def _ref_values(refs: Sequence[Any], prefix: str) -> list[str]:
    return [
        str(ref)[len(prefix):]
        for ref in refs
        if str(ref).startswith(prefix)
    ]


def weekly_review(db: Session, run_id: str) -> dict[str, Any]:
    run = db.get(ReportRun, run_id)
    if run is None or run.is_deleted:
        raise LookupError(f"Run {run_id} was not found")

    validations = list(
        db.scalars(
            select(RunValidation)
            .where(
                RunValidation.run_id == run_id,
                RunValidation.report_kind == "weekly",
                or_(
                    RunValidation.validation_code.like(
                        "multiple_active_employments%"
                    ),
                    RunValidation.validation_code.like("top3_cutoff_tie%"),
                ),
                RunValidation.outcome != "PASS",
                RunValidation.is_deleted == 0,
            )
            .order_by(RunValidation.validation_code, RunValidation.id)
            .limit(101)
        ).all()
    )
    if len(validations) > 100:
        raise ReviewEvidenceMissing(
            "weekly review exceeds the safe display limit"
        )

    decisions = list(
        db.scalars(
            select(RunDecision).where(
                RunDecision.run_id == run_id,
                RunDecision.report_kind == "weekly",
                RunDecision.decision_code.in_(
                    ("multiple_active_employments", "top3_cutoff_tie")
                ),
                RunDecision.is_deleted == 0,
            )
        ).all()
    )
    decisions_by_ref = {decision.fact_ref: decision for decision in decisions}
    items = []
    for validation in validations:
        refs = decode_json_text(validation.evidence_refs) or []
        if validation.validation_code.startswith("top3_cutoff_tie"):
            tie_values = _ref_values(refs, "fact:weekly_top3:")
            if len(tie_values) != 1:
                raise ReviewEvidenceMissing(
                    "weekly Top-3 review is missing a stable tie reference"
                )
            tie_parts = tie_values[0].split(":")
            if len(tie_parts) != 2 or not tie_parts[1].isdigit():
                raise ReviewEvidenceMissing(
                    "weekly Top-3 review has an invalid tie reference"
                )
            tie_ref, slots_text = tie_parts
            slots = int(slots_text)
            fact_ref = f"weekly:top3_cutoff_tie:{tie_ref}:{slots}"
            decision = decisions_by_ref.get(fact_ref)
            if decision is None:
                raise ReviewEvidenceMissing(
                    "weekly Top-3 review decision is no longer available"
                )
            candidates = decode_json_text(decision.options) or []
            answer = decode_json_text(decision.answer)
            items.append(
                {
                    "kind": "top3_cutoff_tie",
                    "tie_ref": tie_ref,
                    "severity": validation.severity,
                    "resolution": "select_top3_projects",
                    "decision_id": decision.id,
                    "decision_status": decision.status,
                    "question": decision.question,
                    "candidates": candidates,
                    "slots": slots,
                    "selected_projects": (
                        answer if isinstance(answer, list) else []
                    ),
                }
            )
            continue
        person_refs = _ref_values(refs, "person:")
        source_row_values = _ref_values(refs, "source:personnel:row:")
        selected_values = _ref_values(refs, "employment:selected:")
        conflicting_dimensions = _ref_values(
            refs, "validation:dimension:"
        )
        if len(person_refs) != 1:
            raise ReviewEvidenceMissing(
                "weekly review is missing a stable person reference"
            )
        try:
            source_rows = sorted({int(value) for value in source_row_values})
            selected_source_row = (
                int(selected_values[0]) if len(selected_values) == 1 else None
            )
        except (TypeError, ValueError) as exc:
            raise ReviewEvidenceMissing(
                "weekly review contains an invalid source row reference"
            ) from exc
        if (
            len(source_rows) < 2
            or len(source_rows) > 20
            or selected_source_row not in source_rows
        ):
            raise ReviewEvidenceMissing(
                "weekly review is missing a valid selected source row"
            )

        facts = list(
            db.scalars(
                select(EmploymentFact)
                .where(
                    EmploymentFact.run_id == run_id,
                    EmploymentFact.source_row_no.in_(source_rows),
                    EmploymentFact.is_deleted == 0,
                )
                .order_by(EmploymentFact.source_row_no)
            ).all()
        )
        if [fact.source_row_no for fact in facts] != source_rows:
            raise ReviewEvidenceMissing(
                "weekly review source row evidence is no longer available"
            )

        person_ref = person_refs[0]
        fact_ref = f"weekly:multiple_active_employments:{person_ref}"
        decision = decisions_by_ref.get(fact_ref)
        is_confirmable = validation.severity == "REVIEW"
        if is_confirmable and decision is None:
            raise ReviewEvidenceMissing(
                "weekly review decision is no longer available"
            )
        items.append(
            {
                "kind": "multiple_active_employments",
                "person_ref": person_ref,
                "severity": validation.severity,
                "resolution": (
                    "confirm_dedupe" if is_confirmable else "replace_input"
                ),
                "decision_id": decision.id if is_confirmable else None,
                "decision_status": (
                    decision.status if is_confirmable else None
                ),
                "conflicting_dimensions": sorted(conflicting_dimensions),
                "selected_source_row_no": selected_source_row,
                "employments": [
                    {
                        "source_row_no": fact.source_row_no,
                        "employee_no": fact.employee_no,
                        "display_name": fact.display_name,
                        "entry_date": fact.entry_date,
                        "business_unit_no": fact.business_unit_no,
                        "business_unit": fact.business_unit,
                        "project_code": fact.project_code,
                        "project_name": fact.project_name,
                        "employee_type": fact.employee_type,
                        "status": fact.status,
                        "selected": fact.source_row_no == selected_source_row,
                    }
                    for fact in facts
                ],
            }
        )
    return {
        "items": sorted(
            items,
            key=lambda item: (
                item["kind"], item.get("person_ref") or item.get("tie_ref") or ""
            ),
        )
    }
