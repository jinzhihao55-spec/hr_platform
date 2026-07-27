"""周报计算合成用例：不依赖真实数据的行为契约。"""
import logging
from datetime import date

import pandas as pd

from app.core import constants as C
from app.pipeline.calculation import validators
from app.pipeline.calculation.weekly import (
    compute_weekly,
    compute_weekly_from_frames,
    top3_tie_ref,
)
from app.repositories import input_repo


def _emp_row(no, bu_code, status="在职", entry=date(2025, 1, 1), resign=None, proj="P1"):
    return {"工号": no, "中文名": no, "员工类型": "正式员工", "员工状态": status,
            "入职日期": entry, "离职日期": resign, "事业部": bu_code, "事业部编号": bu_code,
            "项目编号": proj, "项目名称": proj}


def test_bu_with_zero_active_but_window_leaver_keeps_row(db):
    """窗口末零在职、但本周有离职事实的事业部必须保留 Sheet2 行，
    否则其离职人数从合计里消失，Row3 交叉校验会误报或漏报。"""
    mon, fri = date(2026, 7, 6), date(2026, 7, 10)
    input_repo.upsert_employees(db, pd.DataFrame([
        _emp_row("A1", "NINS"), _emp_row("A2", "NINS"), _emp_row("B1", "NWMT"),
    ]), mon)
    db.commit()
    input_repo.upsert_employees(db, pd.DataFrame([
        _emp_row("A1", "NINS"), _emp_row("A2", "NINS"),
        _emp_row("B1", "NWMT", "离职", resign=date(2026, 7, 8)),
    ]), fri)
    db.commit()

    rows = {r["business_unit"]: r for r in compute_weekly(db, mon, fri)["main_rows"]}

    assert "NWMT" in rows
    assert rows["NWMT"]["headcount"] == 0
    assert rows["NWMT"]["leavers"] == 1
    assert sum(r["leavers"] for r in rows.values()) == 1


def test_project_family_prefix_conflict_blocks_weekly_report(db, monkeypatch):
    """同一项目名命中多个族前缀时归并结果取决于配置顺序，
    必须硬阻断，不能交付可能归错成本中心的周报。"""
    monkeypatch.setattr(C, "WEEKLY_PROJECT_FAMILIES", (
        {"name": "族A", "prefixes": ("AA",), "cost_center": "9000"},
        {"name": "族B", "prefixes": ("AAB",), "cost_center": "9300"},
    ))
    mon, fri = date(2026, 7, 6), date(2026, 7, 10)
    row = _emp_row("A1", "NINS", proj="AAB项目")
    input_repo.upsert_employees(db, pd.DataFrame([row]), fri)
    db.commit()

    ctx = compute_weekly(db, mon, fri)

    assert ctx["project_family_conflicts"] == [
        {"project": "AAB项目", "families": ["族A", "族B"]},
    ]
    check = next(
        c for c in validators.run_weekly_checks(ctx)
        if c["check"] == "项目族前缀归并无冲突"
    )
    assert check["passed"] is False
    assert check.get("hard_block") is True
    assert check in validators.hard_failures(validators.run_weekly_checks(ctx))


def _top3_tie_employees():
    projects = [
        "TopProject",
        "TopProject",
        "TopProject",
        "MiddleProject",
        "MiddleProject",
        "ZuluTieFirst",
        "AlphaTieLater",
    ]
    return pd.DataFrame(
        [
            {
                "source_row_no": index,
                "person_key": f"person-{index}",
                "emp_no": f"E{index}",
                "employee_type": "正式员工",
                "employee_status": "active",
                "hire_date": date(2025, 1, 1),
                "leave_date": None,
                "hire_first_visible": date(2025, 1, 1),
                "leave_first_visible": None,
                "business_unit": "FAKE-BU-A",
                "business_unit_no": "FAKE-BU-A",
                "project_no": project,
                "project_name": project,
            }
            for index, project in enumerate(projects, start=1)
        ]
    )


def test_top3_cutoff_tie_requires_review_with_lexical_default():
    """第三名并列时保留确定性默认值，同时要求非数值人工复核。"""
    result = compute_weekly_from_frames(
        employees=_top3_tie_employees(),
        resignations=pd.DataFrame(),
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 17),
        daily_reconciliation={"complete": True},
    )
    top3 = result["main_rows"][0]["top3_projects"]

    assert [project["name"] for project in top3] == [
        "TopProject",
        "MiddleProject",
        "AlphaTieLater",
    ]
    assert result["review_items"] == [
        {
            "code": "top3_cutoff_tie",
            "severity": "REVIEW",
            "business_unit": "FAKE-BU-A",
            "tie_ref": top3_tie_ref("FAKE-BU-A"),
            "candidates": ["AlphaTieLater", "ZuluTieFirst"],
            "slots": 1,
            "selected_projects": ["AlphaTieLater"],
        }
    ]


def test_top3_cutoff_tie_applies_answered_project_selection():
    result = compute_weekly_from_frames(
        employees=_top3_tie_employees(),
        resignations=pd.DataFrame(),
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 17),
        daily_reconciliation={"complete": True},
        top3_selections={f"{top3_tie_ref('FAKE-BU-A')}:1": ["ZuluTieFirst"]},
    )
    top3 = result["main_rows"][0]["top3_projects"]

    assert [project["name"] for project in top3] == [
        "TopProject",
        "MiddleProject",
        "ZuluTieFirst",
    ]
    assert result["review_items"][0]["selected_projects"] == ["ZuluTieFirst"]


def test_weekly_info_logs_do_not_include_business_values(caplog):
    caplog.set_level(logging.INFO, logger="calc.weekly")

    compute_weekly_from_frames(
        employees=_top3_tie_employees(),
        resignations=pd.DataFrame(),
        week_start=date(2026, 7, 13),
        week_end=date(2026, 7, 17),
        daily_reconciliation={"complete": True},
    )

    for sensitive_value in (
        "FAKE-BU-A",
        "TopProject",
        "MiddleProject",
        "AlphaTieLater",
        "ZuluTieFirst",
        "E1",
    ):
        assert sensitive_value not in caplog.text
