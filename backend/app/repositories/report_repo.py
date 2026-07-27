"""读：把数据库主表读成"计算引擎规范列名"的 DataFrame（屏蔽 schema 列名差异，
使计算层保持稳定）。写：日报/周报写入 daily_reports / weekly_reports 宽表。
链式基线 = 上一报告日期的 daily_reports 行。"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.inputs import (
    Employee,
    EmployeeResignation,
    EmployeeSnapshot,
    OAProtocol,
    Project,
    RecruitmentPipeline,
)
from app.models.reports import DailyReport, TenureSnapshotMetric, WeeklyReport

_TRUE = {"是", "Y", "y", "yes", "true", "True", "1"}


def _alive(model):
    # 过滤软删
    return getattr(model, "is_deleted", None) == 0 if hasattr(model, "is_deleted") else True


# ---------- 读取为规范 DataFrame ----------
def load_employees(db: Session, *_args) -> pd.DataFrame:
    proj = {p.project_code: p.project_name for p in db.scalars(select(Project)).all()}
    rows = db.scalars(select(Employee).where(Employee.is_deleted == 0)).all()
    out = []
    for e in rows:
        out.append({
            "emp_no": e.employee_no,
            "employee_type": e.employee_type,
            "employee_status": e.status,
            "hire_date": e.entry_date,
            "leave_date": e.resign_date,
            "hire_first_visible": e.hire_first_visible_date,
            "leave_first_visible": e.resign_first_visible_date,
            "business_unit": e.bu,
            "business_unit_no": e.bu_code,
            "department": e.department,
            "project_no": e.project_code,
            "project_name": proj.get(e.project_code) or e.project_code,
        })
    return pd.DataFrame(out)


def load_employee_snapshot(db: Session, report_date: date) -> pd.DataFrame:
    rows = db.scalars(
        select(EmployeeSnapshot).where(
            EmployeeSnapshot.report_date == report_date,
            EmployeeSnapshot.is_deleted == 0,
        )
    ).all()
    return pd.DataFrame([
        {
            "emp_no": row.employee_no,
            "employee_type": row.employee_type,
            "employee_status": row.status,
            "hire_date": row.entry_date,
            "leave_date": row.resign_date,
            "hire_first_visible": None,
            "leave_first_visible": None,
            "business_unit": row.business_unit,
            "business_unit_no": row.business_unit_no,
            "project_no": row.project_code,
            "project_name": row.project_name or row.project_code,
        }
        for row in rows
    ])


def load_resignations(db: Session, *_args) -> pd.DataFrame:
    names = {e.employee_no: e.name for e in db.scalars(select(Employee)).all()}
    rows = db.scalars(
        select(EmployeeResignation).where(EmployeeResignation.is_deleted == 0)
    ).all()
    out = []
    for r in rows:
        fvd = r.first_visible_date
        out.append({
            "process_no": r.process_no,
            "emp_no": r.employee_no,
            "process_status": r.process_status,
            "resignation_type": r.resign_type,
            "last_working_day": r.resign_date,
            # 库内以首次可见日期驱动"提出离职"，映射为 apply_time 供 Row4/31/32
            "apply_time": pd.Timestamp(fvd) if fvd else None,
            "name": names.get(r.employee_no),
        })
    return pd.DataFrame(out)


def load_agreements(db: Session, *_args) -> pd.DataFrame:
    rows = db.scalars(select(OAProtocol).where(OAProtocol.is_deleted == 0)).all()
    out = []
    for o in rows:
        # row5_flag 若已被人工显式标注（非空），以其为准；
        # 仅当 flag 为空/null 时才按 process_type 推断（避免"否"被进程类型覆盖）。
        flag5 = str(o.row5_flag).strip() if o.row5_flag is not None else ""
        flag30 = str(o.row30_flag or "").strip()
        if flag5:
            is_release = flag5 in _TRUE
        else:
            is_release = o.process_type in {"离职审批", "协议解除", "人事相关"}

        in_month = flag30 in _TRUE
        lwd_pending = (o.row30_flag is None) or (flag30 == "")
        counts_row5 = flag5 in _TRUE if flag5 else is_release
        apply_d = o.first_visible_date
        if apply_d is None and o.initiate_time is not None:
            apply_d = o.initiate_time.date()
        out.append({
            "order_no": o.order_no,
            "is_release": is_release,
            "counts_row5": counts_row5,
            "in_month_release": in_month,
            "lwd_pending": lwd_pending,
            "first_seen_batch": o.first_visible_date,
            "apply_date": apply_d,
            "current_status": o.current_status,
        })
    return pd.DataFrame(out)


def load_recruitment(db: Session, report_date: "date") -> pd.DataFrame:
    """加载指定报告日的招聘漏斗数据。

    只取 report_date 当天的记录，防止跨日期行被累加导致 Row38/39 虚高。
    合计行（recruiter="__TOTAL__"）恢复 is_total_row=True，使 _recruitment_value
    能执行逐行求和 vs 合计行的交叉校验（Q7）。
    """
    from app.repositories.input_repo import _TOTAL_SENTINEL

    q = select(RecruitmentPipeline).where(
        RecruitmentPipeline.report_date == report_date
    )
    if hasattr(RecruitmentPipeline, "is_deleted"):
        q = q.where(RecruitmentPipeline.is_deleted == 0)
    rows = db.scalars(q).all()
    out = []
    for r in rows:
        out.append({
            "is_total_row": r.recruiter == _TOTAL_SENTINEL,
            "onboard_m": r.onboard_m,
            "prev_month_offer_curr_join": r.expected_onboard_m_prev,
            "curr_month_offer_curr_join": r.expected_onboard_m,
        })
    return pd.DataFrame(out)


def load_daily_week_totals(db: Session, week_start: date, week_end: date) -> dict:
    rows = db.scalars(
        select(DailyReport)
        .where(
            DailyReport.report_date >= week_start,
            DailyReport.report_date <= week_end,
        )
        .order_by(DailyReport.report_date)
    ).all()
    return {
        "available_days": len(rows),
        "report_dates": [row.report_date for row in rows],
        "joiners": sum(int(row.daily_onboard or 0) for row in rows),
        "leavers": sum(int(row.daily_resign or 0) for row in rows),
    }


def save_tenure_snapshot(
    db: Session,
    snapshot_date: date,
    rows: list[dict],
    *,
    commit: bool = True,
) -> None:
    db.execute(
        delete(TenureSnapshotMetric).where(
            TenureSnapshotMetric.snapshot_date == snapshot_date
        )
    )
    for row in rows:
        db.add(TenureSnapshotMetric(
            snapshot_date=snapshot_date,
            slot=str(row["slot"]),
            business_unit=str(row.get("business_unit") or row["slot"]),
            ytd_leavers=int(row.get("ytd_leavers") or 0),
            avg_tenure_years=row.get("avg_tenure_years"),
        ))
    if commit:
        db.commit()
    else:
        db.flush()


def load_tenure_snapshot(db: Session, report_date: date) -> tuple[date | None, list[dict]]:
    snapshot_date = db.scalar(
        select(TenureSnapshotMetric.snapshot_date)
        .where(TenureSnapshotMetric.snapshot_date <= report_date)
        .order_by(TenureSnapshotMetric.snapshot_date.desc())
        .limit(1)
    )
    if snapshot_date is None:
        return None, []
    records = db.scalars(
        select(TenureSnapshotMetric)
        .where(TenureSnapshotMetric.snapshot_date == snapshot_date)
        .order_by(TenureSnapshotMetric.slot)
    ).all()
    return snapshot_date, [
        {
            "slot": record.slot,
            "business_unit": record.business_unit,
            "ytd_leavers": record.ytd_leavers,
            "avg_tenure_years": (
                float(record.avg_tenure_years)
                if record.avg_tenure_years is not None else None
            ),
        }
        for record in records
    ]


# ---------- 链式基线 ----------
_BASELINE_COL = {8: "mtd_onboard", 9: "mtd_resign", 13: "ytd_onboard",
                 14: "ytd_resign", 30: "release_cum"}


def get_baseline_rows(db: Session, report_date: date,
                      baseline_date: date | None = None) -> dict[int, float]:
    """取基线日报，映射回行号值（Row8/9/13/14/30）。

    baseline_date 缺省 → 早于 report_date 的最近一份（默认链式基线，通常是昨日）；
    指定 baseline_date → 取该日日报（必须早于 report_date），不存在则返回 {}
    （由上层触发 baseline_missing 澄清）。
    """
    q = select(DailyReport)
    if baseline_date is not None:
        if baseline_date >= report_date:
            return {}
        q = q.where(DailyReport.report_date == baseline_date)
    else:
        q = (q.where(DailyReport.report_date < report_date)
             .order_by(DailyReport.report_date.desc()))
    prev = db.scalars(q.limit(1)).first()
    if not prev:
        return {}
    return {n: float(getattr(prev, col) or 0) for n, col in _BASELINE_COL.items()}


def baseline_date(db: Session, report_date: date) -> date | None:
    prev = db.scalars(
        select(DailyReport.report_date)
        .where(DailyReport.report_date < report_date)
        .order_by(DailyReport.report_date.desc())
        .limit(1)
    ).first()
    return prev


# ---------- 持久化输出 ----------
def _v(rows: dict[int, dict], n: int):
    info = rows.get(n) or {}
    val = info.get("value")
    return int(val) if val is not None else 0


def save_daily(
    db: Session,
    report_date: date,
    rows: dict[int, dict],
    *,
    commit: bool = True,
) -> None:
    obj = db.scalar(select(DailyReport).where(DailyReport.report_date == report_date))
    if obj is None:
        obj = DailyReport(report_date=report_date)
        db.add(obj)
    obj.daily_onboard = _v(rows, 2)
    obj.daily_resign = _v(rows, 3)
    obj.daily_employee_change = _v(rows, 7)
    obj.mtd_onboard = _v(rows, 8)
    obj.mtd_resign = _v(rows, 9)
    obj.mtd_transfer = _v(rows, 10)
    obj.mtd_project_change = _v(rows, 11)
    obj.mtd_employee_change = _v(rows, 12)
    obj.ytd_onboard = _v(rows, 13)
    obj.ytd_resign = _v(rows, 14)
    obj.ytd_transfer = _v(rows, 15)
    obj.ytd_project_change = _v(rows, 16)
    obj.ytd_employee_change = _v(rows, 17)
    obj.predicted_onboard = _v(rows, 18)
    obj.predicted_resign = _v(rows, 19)
    obj.release_today = _v(rows, 5)
    obj.release_cum = _v(rows, 30)
    obj.expected_resign_cum = _v(rows, 33)
    obj.expected_onboard_offer = _v(rows, 39)
    obj.expected_onboard_prev = _v(rows, 38)
    if commit:
        db.commit()
    else:
        db.flush()


def save_weekly(
    db: Session,
    week_start: date,
    week_end: date,
    main_rows: list[dict],
    *,
    commit: bool = True,
) -> None:
    # 同周整批替换：同时清理消失的 BU 和历史重复行。数据库唯一键
    # (week_start, bu) 再兜住并发写入，避免生成重复事业部记录。
    db.execute(
        delete(WeeklyReport).where(WeeklyReport.week_start == week_start)
    )
    for r in main_rows:
        db.add(
            WeeklyReport(
                week_start=week_start,
                week_end=week_end,
                bu=r["business_unit"],
                headcount_active=r["headcount"],
                headcount_formal=r["cnt_formal"],
                headcount_intern=r["cnt_intern"],
                headcount_outsource=r["cnt_labor"],
                onboard_formal=r.get("joiners_formal", r["joiners"]),
                resigned_formal=r.get("leavers_formal", r["leavers"]),
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()


# ---------- 主表行数（用于"复用 vs 更新"判定） ----------
def count_inputs(db: Session) -> dict[str, int]:
    from sqlalchemy import func as _f
    from app.models.inputs import (
        Employee, EmployeeResignation, OAProtocol, RecruitmentPipeline,
    )
    def _c(model):
        q = select(_f.count()).select_from(model)
        if hasattr(model, "is_deleted"):
            q = q.where(model.is_deleted == 0)
        return int(db.scalar(q) or 0)
    return {
        "employees": _c(Employee),
        "resignations": _c(EmployeeResignation),
        "agreements": _c(OAProtocol),
        "recruitment": _c(RecruitmentPipeline),
    }


# ---------- 列表（供前端日期/周次选择器） ----------
def list_daily_dates(db: Session, limit: int = 60) -> list[dict]:
    rows = db.scalars(
        select(DailyReport).order_by(DailyReport.report_date.desc()).limit(limit)
    ).all()
    return [{"report_date": r.report_date.isoformat(),
             "daily_employee_change": r.daily_employee_change} for r in rows]


def list_weeks(db: Session, limit: int = 30) -> list[dict]:
    from sqlalchemy import distinct
    rows = db.execute(
        select(distinct(WeeklyReport.week_start), WeeklyReport.week_end)
        .order_by(WeeklyReport.week_start.desc()).limit(limit)
    ).all()
    return [{"week_start": ws.isoformat(), "week_end": we.isoformat()} for ws, we in rows]


def get_daily_row(db: Session, report_date: date) -> DailyReport | None:
    return db.scalar(select(DailyReport).where(DailyReport.report_date == report_date))


def daily_exists(db: Session, report_date: date) -> bool:
    return get_daily_row(db, report_date) is not None
