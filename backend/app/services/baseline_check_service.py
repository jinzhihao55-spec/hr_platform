"""链式基线就绪检查：报告日前一工作日日报是否已落库。"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.repositories import report_repo
from app.utils import calendar_utils as cal


def check(db: Session, report_date: date, baseline_date: date | None = None) -> dict:
    """检查链式基线日报是否已落库。

    baseline_date 缺省 → 报告日前一工作日（默认链式基线）；
    显式指定 → 检查用户选定的基线日（必须早于报告日）在 daily_reports 中是否有记录。
    """
    if baseline_date is None:
        baseline_date = cal.prev_workday(report_date)
        is_default = True
    else:
        is_default = baseline_date == cal.prev_workday(report_date)

    # 选定基线晚于/等于报告日无效：链式基线必须严格早于报告日
    if baseline_date >= report_date:
        return {
            "report_date": report_date,
            "baseline_date": baseline_date,
            "exists": False,
            "action_required": "invalid_baseline",
            "message": f"所选基线日 {baseline_date} 不早于报告日 {report_date}，无法作为链式起点，请另选。",
            "daily_employee_change": None,
            "generated_at": None,
        }

    row = report_repo.get_daily_row(db, baseline_date)
    exists = row is not None
    label = "前一工作日" if is_default else "所选基线日"
    if exists:
        message = f"{baseline_date} {label}日报已落库，可正常生成 {report_date} 日报"
        action_required = None
    else:
        message = (
            f"{baseline_date} {label}日报尚未落库，"
            f"请上传定稿日报（员工数增减情况日报_{baseline_date}.xlsx）后再生成"
        )
        action_required = "import_previous_daily"

    return {
        "report_date": report_date,
        "baseline_date": baseline_date,
        "exists": exists,
        "action_required": action_required,
        "message": message,
        "daily_employee_change": row.daily_employee_change if row else None,
        "generated_at": row.create_time if row else None,
    }
