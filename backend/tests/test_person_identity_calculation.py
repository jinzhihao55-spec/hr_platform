"""Natural-person headcount and employment-event semantics remain distinct."""

from datetime import date

import pandas as pd

from app.agents.calculation_agent import CalculationAgent
from app.domain.fact_bundle import FactBundle
from app.pipeline.calculation.weekly import top3_tie_ref


def _employment(
    person_key: str,
    employee_no: str,
    entry_date: date,
    *,
    source_row_no: int = 2,
    business_unit: str = "FAKE-BU-A",
    project_name: str = "测试项目",
) -> dict:
    return {
        "source_row_no": source_row_no,
        "person_key": person_key,
        "person_id": person_key,
        "emp_no": employee_no,
        "employee_type": "正式员工",
        "employee_status": "active",
        "hire_date": entry_date,
        "leave_date": None,
        "hire_first_visible": entry_date,
        "leave_first_visible": None,
        "business_unit": business_unit,
        "business_unit_no": business_unit,
        "project_no": project_name,
        "project_name": project_name,
    }


def _bundle(
    employments: list[dict],
    report_date: date,
    *,
    resignations: list[dict] | None = None,
    releases: list[dict] | None = None,
    decisions: tuple[dict, ...] = (),
) -> FactBundle:
    return FactBundle(
        report_date=report_date,
        baseline_date=report_date.replace(day=report_date.day - 1),
        rule_version="rules-v1",
        employments=pd.DataFrame(employments),
        resignations=pd.DataFrame(resignations or []),
        releases=pd.DataFrame(releases or []),
        decisions=decisions,
        baseline_rows={8: 0, 9: 0, 13: 0, 14: 0, 30: 0},
        daily_reconciliation={
            "available_days": 0,
            "report_dates": [],
            "expected_dates": [],
            "complete": False,
            "joiners": 0,
            "leavers": 0,
        },
    )


def test_weekly_headcount_counts_one_person_with_two_active_employments():
    bundle = _bundle(
        [
            _employment(
                "person-1", "FAKE-E1", date(2025, 1, 1), source_row_no=7
            ),
            _employment(
                "person-1", "FAKE-E2", date(2026, 7, 8), source_row_no=8
            ),
        ],
        date(2026, 7, 10),
    )

    result = CalculationAgent().run_weekly_bundle(
        bundle, date(2026, 7, 6), date(2026, 7, 10)
    )

    total = next(row for row in result["trace"] if row.get("is_total"))
    assert total["headcount"] == 1
    assert total["joiners"] == 1
    item = result["review_items"][0]
    assert item["code"] == "multiple_active_employments"
    assert item["employment_source_row_nos"] == [7, 8]
    assert item["selected_source_row_no"] == 8
    assert item["conflicting_dimensions"] == []


def test_distinct_rehire_event_is_not_collapsed_by_person_headcount():
    bundle = _bundle(
        [
            _employment("person-1", "FAKE-E1", date(2025, 1, 1)),
            _employment("person-1", "FAKE-E2", date(2026, 7, 8)),
        ],
        date(2026, 7, 8),
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert result["rows"][2]["value"] == 1
    assert result["rows"][8]["value"] == 1


def test_daily_active_resignation_uses_selected_employment_per_person():
    report_date = date(2026, 7, 20)
    bundle = _bundle(
        [
            _employment(
                "person-1", "FAKE-OLD", date(2026, 7, 6), source_row_no=7
            ),
            _employment(
                "person-1", "FAKE-CURRENT", date(2026, 7, 13), source_row_no=8
            ),
            _employment(
                "person-2", "FAKE-VALID", date(2025, 1, 1), source_row_no=9
            ),
        ],
        report_date,
        resignations=[
            {
                "person_id": "resignation-employee-number-fallback-old",
                "process_no": "FAKE-PROCESS-OLD",
                "emp_no": "FAKE-OLD",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": date(2026, 9, 11),
                "apply_time": pd.Timestamp(report_date),
                "name": "测试员工甲",
            },
            {
                "person_id": "resignation-employee-number-fallback-valid",
                "process_no": "FAKE-PROCESS-VALID",
                "emp_no": "FAKE-VALID",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": date(2026, 8, 4),
                "apply_time": pd.Timestamp(report_date),
                "name": "测试员工乙",
            },
        ],
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert result["rows"][4]["value"] == 1
    assert result["rows"][6]["value"] == 1


def test_daily_active_resignation_counts_selected_person_once():
    report_date = date(2026, 7, 20)
    bundle = _bundle(
        [
            _employment(
                "person-1", "FAKE-OLD", date(2026, 7, 6), source_row_no=7
            ),
            _employment(
                "person-1", "FAKE-CURRENT", date(2026, 7, 13), source_row_no=8
            ),
        ],
        report_date,
        resignations=[
            {
                "person_id": "person-1",
                "process_no": "FAKE-PROCESS-OLD",
                "emp_no": "FAKE-OLD",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": date(2026, 9, 11),
                "apply_time": pd.Timestamp(report_date),
                "name": "测试员工甲",
            },
            {
                "person_id": "person-1",
                "process_no": "FAKE-PROCESS-CURRENT-1",
                "emp_no": "FAKE-CURRENT",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": date(2026, 8, 4),
                "apply_time": pd.Timestamp(report_date),
                "name": "测试员工甲",
            },
            {
                "person_id": "person-1",
                "process_no": "FAKE-PROCESS-CURRENT-2",
                "emp_no": "FAKE-CURRENT",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": date(2026, 8, 5),
                "apply_time": pd.Timestamp(report_date),
                "name": "测试员工甲",
            },
        ],
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert result["rows"][4]["value"] == 1


def test_daily_release_distribution_excludes_passive_row31_but_includes_row32():
    report_date = date(2026, 7, 29)
    employments = []
    resignations = []

    def add_resignation(index, application_date, resignation_type):
        person_id = f"person-{index}"
        employee_no = f"FAKE-E{index}"
        employments.append(
            _employment(
                person_id,
                employee_no,
                date(2025, 1, 1),
                source_row_no=index + 2,
            )
        )
        resignations.append(
            {
                "person_id": person_id,
                "process_no": f"FAKE-R{index}",
                "emp_no": employee_no,
                "process_status": "审批完成",
                "resignation_type": resignation_type,
                "last_working_day": date(2026, 7, 30),
                "apply_time": pd.Timestamp(application_date),
                "name": f"测试员工{index}",
            }
        )

    for index in range(24):
        add_resignation(index, date(2026, 7, index + 1), "主动离职")
    add_resignation(24, date(2026, 7, 29), "协商一致")
    add_resignation(25, date(2026, 6, 29), "主动离职")
    # Row32 是上月提出、本月离职的总数；协商一致虽属被动 Release，仍计入。
    add_resignation(26, date(2026, 6, 30), "协商一致")

    bundle = _bundle(
        employments,
        report_date,
        resignations=resignations,
        releases=[
            {
                "order_no": "FAKE-OLD-OA",
                "counts_row5": True,
                "manual_row5_include": True,
                "in_month_release": True,
                "lwd_pending": False,
                "first_seen_batch": date(2026, 6, 23),
            }
        ],
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert {row: result["rows"][row]["value"] for row in (5, 30, 31, 32, 33)} == {
        5: 1,
        30: 1,
        31: 24,
        32: 2,
        33: 27,
    }


def test_daily_departure_ignores_non_selected_duplicate_employment():
    report_date = date(2026, 7, 21)
    old_employment = _employment(
        "person-1",
        "FAKE-OLD",
        date(2026, 7, 6),
        source_row_no=7,
        business_unit="NWTS",
    )
    old_employment.update({
        "employee_status": "resigned",
        "leave_date": report_date,
        "leave_first_visible": report_date,
    })

    bundle = _bundle(
        [
            old_employment,
            _employment(
                "person-1",
                "FAKE-CURRENT",
                date(2026, 7, 13),
                source_row_no=8,
                business_unit="NWTS",
            ),
        ],
        report_date,
        resignations=[
            {
                "person_id": "person-1",
                "process_no": "FAKE-PROCESS-OLD",
                "emp_no": "FAKE-OLD",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": report_date,
                "apply_time": pd.Timestamp(date(2026, 7, 17)),
                "name": "测试员工甲",
            }
        ],
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert result["rows"][3]["value"] == 0


def test_monthly_departure_rosters_ignore_non_selected_duplicate_employment():
    report_date = date(2026, 7, 21)
    employments = [
        _employment("person-1", "FAKE-OLD", date(2026, 7, 6), source_row_no=7),
        _employment(
            "person-1", "FAKE-CURRENT", date(2026, 7, 13), source_row_no=8
        ),
    ]
    resignations = [
        {
            "person_id": "person-1",
            "process_no": "FAKE-PROCESS-CURRENT-MONTH",
            "emp_no": "FAKE-OLD",
            "process_status": "审批完成",
            "resignation_type": "主动离职",
            "last_working_day": report_date,
            "apply_time": pd.Timestamp(date(2026, 7, 17)),
            "name": "测试员工甲",
        },
        {
            "person_id": "person-1",
            "process_no": "FAKE-PROCESS-PREVIOUS-MONTH",
            "emp_no": "FAKE-OLD",
            "process_status": "审批完成",
            "resignation_type": "主动离职",
            "last_working_day": report_date,
            "apply_time": pd.Timestamp(date(2026, 6, 30)),
            "name": "测试员工甲",
        },
    ]

    result = CalculationAgent().run_daily_bundle(
        _bundle(employments, report_date, resignations=resignations)
    )

    assert result["rows"][31]["value"] == 0
    assert result["rows"][32]["value"] == 0


def test_tenure_ignores_non_selected_duplicate_employment():
    report_date = date(2026, 7, 21)
    old_employment = _employment(
        "person-1",
        "FAKE-OLD",
        date(2026, 7, 6),
        source_row_no=7,
        business_unit="NWTS",
    )
    old_employment.update({
        "employee_status": "resigned",
        "leave_date": report_date,
        "leave_first_visible": report_date,
    })
    bundle = _bundle(
        [
            old_employment,
            _employment(
                "person-1",
                "FAKE-CURRENT",
                date(2026, 7, 13),
                source_row_no=8,
                business_unit="NWTS",
            ),
        ],
        report_date,
        resignations=[
            {
                "person_id": "person-1",
                "process_no": "FAKE-PROCESS-OLD",
                "emp_no": "FAKE-OLD",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": report_date,
                "apply_time": pd.Timestamp(date(2026, 7, 17)),
                "name": "测试员工甲",
            }
        ],
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert result["tenure"]["b10"] == 0


def test_same_person_duplicate_employments_first_seen_today_count_once():
    bundle = _bundle(
        [
            _employment("person-1", "FAKE-E1", date(2026, 7, 8)),
            _employment("person-1", "FAKE-E2", date(2026, 7, 8)),
        ],
        date(2026, 7, 8),
    )

    result = CalculationAgent().run_daily_bundle(bundle)

    assert result["rows"][2]["value"] == 1
    assert result["rows"][8]["value"] == 1


def test_weekly_joiners_count_same_person_once_across_duplicate_employments():
    bundle = _bundle(
        [
            _employment("person-1", "FAKE-E1", date(2026, 7, 8)),
            _employment("person-1", "FAKE-E2", date(2026, 7, 8)),
        ],
        date(2026, 7, 10),
    )

    result = CalculationAgent().run_weekly_bundle(
        bundle, date(2026, 7, 6), date(2026, 7, 10)
    )

    total = next(row for row in result["trace"] if row.get("is_total"))
    assert total["joiners"] == 1


def test_weekly_departure_ignores_non_selected_duplicate_employment():
    report_date = date(2026, 7, 24)
    old_employment = _employment(
        "person-1",
        "FAKE-OLD",
        date(2026, 7, 6),
        source_row_no=7,
        business_unit="NWTS",
    )
    old_employment.update({
        "employee_status": "resigned",
        "leave_date": date(2026, 7, 21),
        "leave_first_visible": date(2026, 7, 21),
    })
    current_employment = _employment(
        "person-1",
        "FAKE-CURRENT",
        date(2026, 7, 13),
        source_row_no=8,
        business_unit="NWTS",
    )
    bundle = _bundle(
        [old_employment, current_employment],
        report_date,
        resignations=[
            {
                "person_id": "person-1",
                "process_no": "FAKE-PROCESS-OLD",
                "emp_no": "FAKE-OLD",
                "process_status": "审批完成",
                "resignation_type": "主动离职",
                "last_working_day": date(2026, 7, 21),
                "apply_time": pd.Timestamp(date(2026, 7, 17)),
                "name": "测试员工甲",
            }
        ],
    )

    result = CalculationAgent().run_weekly_bundle(
        bundle, date(2026, 7, 20), report_date
    )

    assert result["main_rows"][0]["leavers"] == 0
    total = next(row for row in result["trace"] if row.get("is_total"))
    assert total["leavers"] == 0


def test_conflicting_active_employment_dimensions_block_weekly_review():
    bundle = _bundle(
        [
            _employment("person-1", "FAKE-E1", date(2025, 1, 1)),
            _employment(
                "person-1",
                "FAKE-E2",
                date(2026, 7, 8),
                business_unit="NINS",
                project_name="另一个测试项目",
            ),
        ],
        date(2026, 7, 10),
    )

    result = CalculationAgent().run_weekly_bundle(
        bundle, date(2026, 7, 6), date(2026, 7, 10)
    )

    assert result["review_items"][0]["severity"] == "BLOCK"


def test_weekly_bundle_applies_answered_top3_tie_decision():
    projects = ["Top", "Top", "Top", "Middle", "Middle", "ZuluTie", "AlphaTie"]
    bundle = _bundle(
        [
            _employment(
                f"person-{index}",
                f"FAKE-E{index}",
                date(2025, 1, 1),
                source_row_no=index,
                project_name=project,
            )
            for index, project in enumerate(projects, start=1)
        ],
        date(2026, 7, 17),
        decisions=(
            {
                "decision_code": "top3_cutoff_tie",
                "fact_ref": (
                    f"weekly:top3_cutoff_tie:{top3_tie_ref('FAKE-BU-A')}:1"
                ),
                "answer": ["ZuluTie"],
                "status": "answered",
            },
        ),
    )

    result = CalculationAgent().run_weekly_bundle(
        bundle, date(2026, 7, 13), date(2026, 7, 17)
    )

    assert [item["name"] for item in result["main_rows"][0]["top3_projects"]] == [
        "Top",
        "Middle",
        "ZuluTie",
    ]
