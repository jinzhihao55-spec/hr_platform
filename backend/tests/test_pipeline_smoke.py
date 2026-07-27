"""端到端冒烟测试：写入数据库主表 -> 计算 -> 导出。
用内存 SQLite 代替 MySQL，无需外部服务。

运行：  pytest -q tests/test_pipeline_smoke.py
"""
import os
from datetime import date

import pandas as pd

from app.pipeline.calculation import daily as daily_calc
from app.pipeline.calculation import tenure as tenure_calc
from app.pipeline.calculation import validators
from app.pipeline.export import daily_exporter
from app.repositories import input_repo
from tests.conftest import seed_month_start_baseline


def _seed(db, report_date):
    """构造覆盖行公式的最小确定性数据集，写入主表。"""
    emp = pd.DataFrame([
        {"员工类型": "正式员工", "工号": "E1", "中文名": "甲", "员工状态": "在职",
         "入职日期": report_date, "离职日期": None, "事业部": "BU_A",
         "事业部编号": "01", "项目编号": "P1", "项目名称": "PROJECT_A"},
        {"员工类型": "正式员工", "工号": "E2", "中文名": "乙", "员工状态": "离职",
         "入职日期": date(2025, 1, 1), "离职日期": report_date, "事业部": "BU_A",
         "事业部编号": "01", "项目编号": "P1", "项目名称": "PROJECT_A"},
    ])
    input_repo.upsert_employees(db, emp)
    rec = pd.DataFrame([
        {"招聘专员": "Recruiter A", "is_total_row": False,
         "上月接受offer当月预计入职": 2, "当月接受offer当月预计入职": 3},
    ])
    input_repo.upsert_recruitment(db, report_date, rec)
    db.commit()


def test_daily_pipeline(db, tmp_path):
    report_date = date(2026, 6, 1)  # 月初：MTD 从 0 起算，YTD 需上月末基线
    _seed(db, report_date)
    seed_month_start_baseline(db, report_date)

    ctx = daily_calc.compute_daily(db, report_date)
    ctx["tenure"] = tenure_calc.compute_tenure(db, report_date)
    results = validators.run_daily_checks(ctx)

    assert len(ctx["tenure"]["rows"]) == 8

    rows = ctx["rows"]
    assert rows[2]["value"] == 1      # 今日入职
    assert rows[3]["value"] == 1      # 今日离职
    assert rows[7]["value"] == 0      # 净增 = 1 - 1
    assert rows[40]["value"] == rows[37]["value"] + rows[38]["value"] + rows[39]["value"]
    assert rows[18]["value"] == rows[40]["value"]   # Row18 == Row40
    assert [r["business_unit"] for r in ctx["tenure"]["rows"]] == [
        "BU_A", "BU_B", "BU_C", "BU_D", "BU_E", "BU_F", "BU_G", "BU_H"
    ]
    assert ctx["tenure"]["rows"][0]["ytd_leavers"] == 1
    assert all(r["ytd_leavers"] == 0 for r in ctx["tenure"]["rows"][1:])
    assert not validators.hard_failures(results)     # 全部硬校验通过

    from tests.test_daily_export_layout import _make_template
    template = _make_template(tmp_path / "template.xlsx", date(2026, 5, 30))
    path = daily_exporter.export_daily(
        ctx, ctx["tenure"], str(tmp_path), template_path=template,
    )
    assert os.path.exists(path)


def test_month_opening_baseline_overrides_previous_month_ytd(db):
    """月初 HR 重述是独立基线，不得继续使用上月末 YTD。"""
    report_date = date(2026, 7, 1)
    _seed(db, report_date)
    seed_month_start_baseline(db, report_date)

    ctx = daily_calc.compute_daily(
        db,
        report_date,
        baseline_date=date(2026, 6, 30),
        baseline_override={8: 73, 9: 59, 13: 159, 14: 123, 30: 14},
    )

    assert ctx["rows"][8]["value"] == 1    # 跨月 MTD 仍从 0 开始
    assert ctx["rows"][13]["value"] == 160
    assert ctx["rows"][14]["value"] == 124
    assert ctx["rows"][17]["value"] == 36
