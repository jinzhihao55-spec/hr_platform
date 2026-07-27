"""在岗时长：固定 8 BU 槽位 + B10=Row14。"""
from datetime import date

import pandas as pd
import pytest

from app.core import constants as C
from app.pipeline.calculation import daily as daily_calc
from app.pipeline.calculation import tenure as tenure_calc
from app.pipeline.calculation import validators
from app.repositories import input_repo, report_repo
from tests.conftest import seed_month_start_baseline


@pytest.mark.parametrize(
    ("bu_code", "slot"),
    [
        ("NBJO", "BU_A"),
        ("NENT", "BU_B"),
        ("NGOV", "BU_C"),
        ("NINS", "BU_D"),
        ("NITL", "BU_E"),
        ("NMSI", "BU_F"),
        ("NWMT", "BU_G"),
        ("NWTS", "BU_H"),
    ],
)
def test_real_bu_codes_resolve_to_tenure_slots(bu_code, slot):
    assert C.resolve_bu_slot(None, bu_code) == slot


def test_tenure_fixed_eight_rows(db):
    report_date = date(2026, 6, 1)
    emp = pd.DataFrame([{
        "员工类型": "正式员工", "工号": "E1", "中文名": "甲", "员工状态": "离职",
        "入职日期": date(2025, 1, 1), "离职日期": report_date,
        "事业部": "BU_A", "事业部编号": "01",
        "项目编号": "P1", "项目名称": "P",
    }])
    input_repo.upsert_employees(db, emp)
    db.commit()
    seed_month_start_baseline(db, report_date)

    t = tenure_calc.compute_tenure(db, report_date)
    assert len(t["rows"]) == len(C.get_tenure_bu_slots())
    assert t["rows"][0]["slot"] == "BU_A"
    assert t["b10"] == 1
    assert sum(r["ytd_leavers"] for r in t["rows"]) == t["b10"]

    ctx = daily_calc.compute_daily(db, report_date)
    ctx["tenure"] = t
    assert not validators.hard_failures(validators.run_daily_checks(ctx))


def test_tenure_empty_slots_are_zero(db):
    report_date = date(2026, 6, 1)
    t = tenure_calc.compute_tenure(db, report_date)
    assert len(t["rows"]) == 8
    assert t["b10"] == 0
    assert all(r["ytd_leavers"] == 0 for r in t["rows"])


def test_finalized_tenure_metrics_are_baseline_for_later_departures(db):
    snapshot_date = date(2026, 7, 7)
    report_repo.save_tenure_snapshot(db, snapshot_date, [
        {"slot": "BU_A", "business_unit": "NBJO", "ytd_leavers": 1,
         "avg_tenure_years": 1.5},
        {"slot": "BU_D", "business_unit": "NINS", "ytd_leavers": 1,
         "avg_tenure_years": 2.03},
    ])

    active = pd.DataFrame([{
        "员工类型": "正式员工", "工号": "E3", "中文名": "丙", "员工状态": "在职",
        "入职日期": date(2025, 7, 8), "离职日期": None,
        "事业部": "保险业务", "事业部编号": "NINS",
        "项目编号": "P1", "项目名称": "P",
    }])
    input_repo.upsert_employees(db, active, snapshot_date)
    db.commit()

    baseline = tenure_calc.compute_tenure(db, snapshot_date)
    assert baseline["b10"] == 2

    resigned = active.copy()
    resigned.loc[0, "员工状态"] = "离职"
    resigned.loc[0, "离职日期"] = date(2026, 7, 8)
    input_repo.upsert_employees(db, resigned, date(2026, 7, 8))
    db.commit()

    next_day = tenure_calc.compute_tenure(db, date(2026, 7, 8))
    assert next_day["b10"] == 3
    assert next_day["rows"][3]["avg_tenure_years"] == 1.52


def test_month_opening_tenure_baseline_overrides_previous_snapshot(db):
    """跨月 HR 重述必须覆盖上月末在岗时长快照，且不改写历史快照。"""
    previous_date = date(2026, 6, 30)
    report_repo.save_tenure_snapshot(db, previous_date, [
        {"slot": "BU_A", "business_unit": "NBJO", "ytd_leavers": 86,
         "avg_tenure_years": 2.0},
    ])
    opening_rows = [
        {"slot": f"BU_{letter}", "business_unit": f"BU_{letter}",
         "ytd_leavers": 123 if letter == "A" else 0,
         "avg_tenure_years": 1.5 if letter == "A" else None}
        for letter in "ABCDEFGH"
    ]

    result = tenure_calc.compute_tenure(
        db,
        date(2026, 7, 1),
        opening_baseline_date=previous_date,
        opening_rows=opening_rows,
    )

    assert result["b10"] == 123
    stored_date, stored_rows = report_repo.load_tenure_snapshot(db, previous_date)
    assert stored_date == previous_date
    assert sum(row["ytd_leavers"] for row in stored_rows) == 86
