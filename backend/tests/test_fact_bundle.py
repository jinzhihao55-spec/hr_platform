"""FactBundle maps one Run into deterministic calculator input frames."""

from datetime import date

from app.domain.fact_bundle import FactBundle
from app.pipeline.calculation.daily import _count_release
from app.models.facts import (
    EmploymentFact,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    RunDecision,
    encode_json_text,
)
from app.models.runs import ReportRun, RunStatus
from app.services.fact_bundle_service import FactBundleService


def test_fact_bundle_service_maps_run_facts_without_certificate_plaintext(db):
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    person = PersonIdentity(
        person_key="a" * 64,
        key_version="v1",
        match_confidence="certificate",
        identity_namespace="certificate",
    )
    db.add_all([run, person])
    db.flush()
    db.add_all(
        [
            EmploymentFact(
                run_id=run.id,
                source_row_no=2,
                person_id=person.id,
                employee_no="FAKE-E1",
                display_name="测试甲",
                employee_type="正式员工",
                status="在职",
                entry_date=date(2026, 7, 8),
                first_visible_dates=encode_json_text({"hire": "2026-07-09"}),
                business_unit="测试事业部",
                business_unit_no="NENT",
                project_code="FAKE-P1",
                project_name="测试项目",
            ),
            ResignationFact(
                run_id=run.id,
                source_row_no=2,
                process_no="FAKE-R1",
                person_id=person.id,
                employee_no="FAKE-E1",
                process_status="已完成",
                application_date=date(2026, 7, 8),
                last_working_day=date(2026, 7, 31),
                resignation_type="主动离职",
                first_visible_date=date(2026, 7, 8),
            ),
            ReleaseFact(
                run_id=run.id,
                source_row_no=2,
                order_no="FAKE-O1",
                application_date=date(2026, 7, 8),
                last_working_day=date(2026, 7, 30),
                first_visible_date=date(2026, 7, 8),
                row5_classification="include",
                row30_classification="include",
            ),
            RecruitmentSnapshot(
                run_id=run.id,
                source_row_no=2,
                report_date=date(2026, 7, 8),
                is_total_row=True,
                previous_month_offer_current_month_onboard=2,
                current_month_offer_current_month_onboard=3,
            ),
            RunDecision(
                run_id=run.id,
                report_kind=None,
                decision_code="fake_review",
                fact_ref="source:release:row:2",
                question="测试确认",
                options=encode_json_text(["确认"]),
                status="answered",
                answer=encode_json_text("确认"),
            ),
        ]
    )
    db.commit()

    bundle = FactBundleService(db).build(
        run.id,
        baseline_date=date(2026, 7, 7),
        baseline_rows={8: 4, 9: 1, 13: 10, 14: 3, 30: 2},
    )

    assert isinstance(bundle, FactBundle)
    assert bundle.employments.loc[0, "person_key"] == "a" * 64
    assert bundle.employments.loc[0, "emp_no"] == "FAKE-E1"
    assert bundle.employments.loc[0, "hire_first_visible"] == date(2026, 7, 9)
    assert bundle.resignations.loc[0, "apply_time"].date() == date(2026, 7, 8)
    assert bool(bundle.releases.loc[0, "counts_row5"]) is True
    assert bool(bundle.recruitment.loc[0, "is_total_row"]) is True
    assert bundle.baseline_rows[13] == 10
    assert bundle.decisions[0]["answer"] == "确认"
    all_columns = set().union(
        bundle.employments.columns,
        bundle.resignations.columns,
        bundle.releases.columns,
        bundle.recruitment.columns,
    )
    assert "证件号" not in all_columns
    assert "certificate_number" not in all_columns


def test_manual_row5_decision_overrides_first_visible_date_without_mutating_it(db):
    run = ReportRun(
        report_date=date(2026, 7, 29),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    fact = ReleaseFact(
        run_id=run.id,
        source_row_no=4,
        order_no="FAKE-OLD-OA",
        first_visible_date=date(2026, 6, 23),
        row5_classification="include",
        row30_classification="exclude",
    )
    decision = RunDecision(
        run_id=run.id,
        report_kind=None,
        decision_code="release_row5_classification_required",
        fact_ref="source:release:row:4",
        question="是否计入 Row5？",
        options=encode_json_text(["计入Row5", "不计入Row5"]),
        status="answered",
        answer=encode_json_text("计入Row5"),
    )
    db.add_all([fact, decision])
    db.commit()

    bundle = FactBundleService(db).build(
        run.id,
        baseline_date=date(2026, 7, 28),
        baseline_rows={},
    )
    result = _count_release(bundle.releases, run.report_date)

    assert bundle.releases.loc[0, "first_seen_batch"] == date(2026, 6, 23)
    assert bool(bundle.releases.loc[0, "manual_row5_include"]) is True
    assert result == {
        "count": 1,
        "hits": [{"order_no": "FAKE-OLD-OA", "manual_override": True}],
    }


def test_fact_bundle_copies_mutable_frames():
    import pandas as pd

    source = pd.DataFrame([{"emp_no": "FAKE-E1"}])
    bundle = FactBundle(
        report_date=date(2026, 7, 8),
        baseline_date=date(2026, 7, 7),
        rule_version="rules-v1",
        employments=source,
        baseline_rows={8: 0, 9: 0, 13: 0, 14: 0, 30: 0},
    )
    source.loc[0, "emp_no"] = "MUTATED"

    assert bundle.employments.loc[0, "emp_no"] == "FAKE-E1"
