"""同一员工存在多条离职流程时，已完成流程不能被拒绝记录遮蔽。"""
from datetime import date

from app.pipeline.calculation.daily import _departure_fact_confirmed


def test_any_completed_process_confirms_departure():
    leave_date = date(2026, 7, 8)
    employee = {"emp_no": "E1", "employee_status": "resigned"}
    resignations = {
        "E1": [
            {"last_working_day": leave_date, "process_status": "经理拒绝离职"},
            {"last_working_day": leave_date, "process_status": "审批完成"},
        ]
    }

    confirmed, note = _departure_fact_confirmed(employee, resignations, leave_date)

    assert confirmed is True
    assert "审批完成" in note
