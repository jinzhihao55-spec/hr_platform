"""Safe review read models expose evidence without protected identity fields."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.models.facts import (
    EmploymentFact,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    RunDecision,
    encode_json_text,
)
from app.models.runs import ReportRun, RunStatus
from app.pipeline.calculation.weekly import top3_tie_ref
from app.services.review_service import (
    ReviewEvidenceMissing,
    decision_preview,
    weekly_review,
)
from app.services.run_validation_service import replace_calculation_validations


def _run(db, report_date: date = date(2026, 7, 17)) -> ReportRun:
    run = ReportRun(
        report_date=report_date,
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    return run


def _ocr_decision(db, run: ReportRun, source_type: str) -> RunDecision:
    decision = RunDecision(
        run_id=run.id,
        report_kind=None,
        decision_code="ocr_review_required",
        fact_ref=f"source:{source_type}:row:ocr",
        question="Confirm structured OCR facts.",
        options=encode_json_text(["确认", "替换输入"]),
        status="pending",
    )
    db.add(decision)
    db.flush()
    return decision


def test_release_ocr_preview_returns_only_whitelisted_fields(db):
    run = _run(db)
    decision = _ocr_decision(db, run, "release")
    db.add(
        ReleaseFact(
            run_id=run.id,
            source_row_no=2,
            order_no="FAKE-REL-001",
            employee_no="FAKE-EMP-SECRET",
            application_date=date(2026, 7, 17),
            last_working_day=date(2026, 7, 30),
            process_status="审批中",
            row5_classification="include",
            row30_classification="include",
            ocr_confidence="unreviewed",
        )
    )
    db.commit()

    payload = decision_preview(db, run.id, decision.id)

    assert payload["kind"] == "ocr_source"
    assert payload["source_type"] == "release"
    assert payload["rows"] == [
        {
            "source_row_no": 2,
            "order_no": "FAKE-REL-001",
            "application_date": date(2026, 7, 17),
            "last_working_day": date(2026, 7, 30),
            "process_status": "审批中",
            "row5_classification": "include",
            "row30_classification": "include",
            "ocr_confidence": "unreviewed",
        }
    ]
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    assert "FAKE-EMP-SECRET" not in serialized
    for forbidden in ("person_key", "person_id", "employee_no", "certificate"):
        assert forbidden not in serialized
    assert payload["warnings"] == [
        "原始图片按安全策略不留存；请核对结构化结果。"
    ]


def test_recruitment_ocr_preview_decodes_labels_and_sorts_rows(db):
    run = _run(db)
    decision = _ocr_decision(db, run, "recruitment")
    db.add_all(
        [
            RecruitmentSnapshot(
                run_id=run.id,
                source_row_no=3,
                report_date=run.report_date,
                is_total_row=False,
                previous_month_offer_current_month_onboard=2,
                current_month_offer_current_month_onboard=4,
                recognized_labels=encode_json_text(["业务行"]),
                ocr_confidence="unreviewed",
            ),
            RecruitmentSnapshot(
                run_id=run.id,
                source_row_no=2,
                report_date=run.report_date,
                is_total_row=True,
                previous_month_offer_current_month_onboard=3,
                current_month_offer_current_month_onboard=5,
                recognized_labels=encode_json_text(
                    ["合计", "当月接受offer当月预计入职"]
                ),
                ocr_confidence="unreviewed",
            ),
        ]
    )
    db.commit()

    payload = decision_preview(db, run.id, decision.id)

    assert [row["source_row_no"] for row in payload["rows"]] == [2, 3]
    assert payload["rows"][0] == {
        "source_row_no": 2,
        "report_date": date(2026, 7, 17),
        "is_total_row": True,
        "previous_month_offer_current_month_onboard": 3,
        "current_month_offer_current_month_onboard": 5,
        "recognized_labels": ["合计", "当月接受offer当月预计入职"],
        "ocr_confidence": "unreviewed",
    }


def test_ocr_preview_rejects_decision_from_another_run(db):
    run = _run(db)
    other_run = _run(db, date(2026, 7, 18))
    decision = _ocr_decision(db, other_run, "release")
    db.commit()

    with pytest.raises(ValueError, match="does not belong"):
        decision_preview(db, run.id, decision.id)


def test_ocr_preview_requires_staged_facts(db):
    run = _run(db)
    decision = _ocr_decision(db, run, "release")
    db.commit()

    with pytest.raises(ReviewEvidenceMissing, match="replace the input"):
        decision_preview(db, run.id, decision.id)


def _weekly_employments(db, run: ReportRun) -> None:
    person = PersonIdentity(
        person_key="fake-person-key",
        key_version="v1",
        match_confidence="fake",
        identity_namespace="test",
    )
    db.add(person)
    db.flush()
    db.add_all(
        [
            EmploymentFact(
                run_id=run.id,
                source_row_no=7,
                person_id=person.id,
                employee_no="FAKE-E1",
                display_name="测试甲",
                employee_type="正式员工",
                status="active",
                entry_date=date(2025, 1, 1),
                business_unit="网络事业部",
                business_unit_no="NENT",
                project_code="FAKE-P1",
                project_name="测试项目",
            ),
            EmploymentFact(
                run_id=run.id,
                source_row_no=8,
                person_id=person.id,
                employee_no="FAKE-E2",
                display_name="测试甲",
                employee_type="正式员工",
                status="active",
                entry_date=date(2026, 7, 8),
                business_unit="网络事业部",
                business_unit_no="NENT",
                project_code="FAKE-P1",
                project_name="测试项目",
            ),
        ]
    )
    db.flush()


def _weekly_review_item(*, severity="REVIEW", conflicts=None) -> dict:
    return {
        "code": "multiple_active_employments",
        "severity": severity,
        "person_ref": "abc123def456",
        "employment_source_row_nos": [7, 8],
        "selected_source_row_no": 8,
        "conflicting_dimensions": conflicts or [],
    }


def test_weekly_review_returns_selected_safe_employment_rows(db):
    run = _run(db)
    _weekly_employments(db, run)
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[_weekly_review_item()],
    )

    payload = weekly_review(db, run.id)

    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["person_ref"] == "abc123def456"
    assert item["severity"] == "REVIEW"
    assert item["resolution"] == "confirm_dedupe"
    assert item["decision_id"] is not None
    assert item["decision_status"] == "pending"
    assert item["selected_source_row_no"] == 8
    assert [row["source_row_no"] for row in item["employments"]] == [7, 8]
    assert item["employments"][1]["selected"] is True
    assert item["employments"][1]["employee_no"] == "FAKE-E2"

    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    for forbidden in ("person_key", "person_id", "certificate", "id_card"):
        assert forbidden not in serialized
    assert "fake-person-key" not in serialized


def test_weekly_review_returns_top3_cutoff_candidates(db):
    run = _run(db)
    reference = top3_tie_ref("FAKE-BU-A")
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                "code": "top3_cutoff_tie",
                "severity": "REVIEW",
                "business_unit": "FAKE-BU-A",
                "tie_ref": reference,
                "candidates": ["AlphaTie", "ZuluTie"],
                "slots": 1,
                "selected_projects": ["AlphaTie"],
            }
        ],
    )

    item = weekly_review(db, run.id)["items"][0]

    assert item == {
        "kind": "top3_cutoff_tie",
        "tie_ref": reference,
        "severity": "REVIEW",
        "resolution": "select_top3_projects",
        "decision_id": item["decision_id"],
        "decision_status": "pending",
        "question": "FAKE-BU-A 的前三项目在截止位并列，请选择 1 个项目。",
        "candidates": ["AlphaTie", "ZuluTie"],
        "slots": 1,
        "selected_projects": [],
    }


def test_weekly_conflict_has_revision_resolution_without_decision(db):
    run = _run(db)
    _weekly_employments(db, run)
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            _weekly_review_item(
                severity="BLOCK", conflicts=["project_name"]
            )
        ],
    )

    item = weekly_review(db, run.id)["items"][0]

    assert item["resolution"] == "replace_input"
    assert item["decision_id"] is None
    assert item["conflicting_dimensions"] == ["project_name"]


def test_weekly_review_fails_closed_when_evidence_row_is_missing(db):
    run = _run(db)
    _weekly_employments(db, run)
    replace_calculation_validations(
        db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                **_weekly_review_item(),
                "employment_source_row_nos": [7, 9],
                "selected_source_row_no": 9,
            }
        ],
    )

    with pytest.raises(ReviewEvidenceMissing, match="source row"):
        weekly_review(db, run.id)
