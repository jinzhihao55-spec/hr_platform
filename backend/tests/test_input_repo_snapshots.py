"""人员日快照写入的鲁棒性契约。"""
from datetime import date

import pandas as pd

from app.agents.extraction_agent import _deduplicate_personnel_identities
from app.repositories import input_repo, report_repo


def _emp_row(no, bu_code, status="在职", entry=date(2025, 1, 1), resign=None):
    return {"工号": no, "中文名": no, "员工类型": "正式员工", "员工状态": status,
            "入职日期": entry, "离职日期": resign, "事业部": bu_code, "事业部编号": bu_code,
            "项目编号": "P1", "项目名称": "P1"}


def test_duplicate_emp_no_in_upload_keeps_last_row_without_error(db):
    """真实导出偶发重复行：不得触发唯一键冲突拖垮整个上传，按最后一行为准。"""
    day = date(2026, 7, 6)
    first = _emp_row("C1", "NENT")
    second = _emp_row("C1", "NENT", "离职", resign=date(2026, 7, 3))

    input_repo.upsert_employees(db, pd.DataFrame([first, second]), day)
    db.commit()

    snap = report_repo.load_employee_snapshot(db, day)
    assert len(snap) == 1
    assert snap.iloc[0]["employee_status"] == "resigned"


def test_legacy_extraction_selects_one_employment_for_same_certificate():
    first = {
        **_emp_row("FAKE-E1", "NENT", entry=date(2026, 7, 6)),
        "证件号": " FAKE-CERT-1 ",
    }
    second = {
        **_emp_row("FAKE-E2", "NENT", entry=date(2026, 7, 13)),
        "证件号": "fake-cert-1",
    }

    result = _deduplicate_personnel_identities(pd.DataFrame([first, second]))

    assert result["工号"].tolist() == ["FAKE-E2"]


def test_oa_first_visible_uses_report_date_for_late_rolling_record(db):
    baseline = pd.DataFrame(
        [
            {
                "单号": "FAKE-O-OLD",
                "流程名称": "协议签署",
                "申请时间": "2026-06-20 09:00:00",
            }
        ]
    )
    input_repo.upsert_oa(db, baseline, date(2026, 7, 10))
    db.commit()
    rolling = pd.DataFrame(
        [
            *baseline.to_dict(orient="records"),
            {
                "单号": "FAKE-O-LATE",
                "流程名称": "协议签署",
                "申请时间": "2026-07-10 18:30:00",
            },
            {
                "单号": "FAKE-O-HISTORICAL",
                "流程名称": "协议签署",
                "申请时间": "2026-06-21 09:00:00",
            },
        ]
    )

    input_repo.upsert_oa(db, rolling, date(2026, 7, 13))
    db.commit()

    agreements = report_repo.load_agreements(db).set_index("order_no")
    assert agreements.loc["FAKE-O-OLD", "first_seen_batch"] == date(
        2026, 6, 20
    )
    assert agreements.loc["FAKE-O-LATE", "first_seen_batch"] == date(
        2026, 7, 13
    )
    assert agreements.loc[
        "FAKE-O-HISTORICAL", "first_seen_batch"
    ] == date(2026, 6, 21)
