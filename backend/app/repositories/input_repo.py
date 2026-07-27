"""把上传 Excel 解析出的行写入数据库主表（projects / employees /
employee_resignations / oa_protocols / recruitment_pipeline）。

采用按唯一键 UPSERT（存在则更新、不存在则插入），兼容 MySQL 与测试用 SQLite。
解析器输出的是中文规范列名，这里负责映射到 schema.sql 的英文列。"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.inputs import (
    Employee,
    EmployeeResignation,
    EmployeeSnapshot,
    OAProtocol,
    Project,
    RecruitmentPipeline,
)
from app.core.logging import get_logger
from app.utils import calendar_utils as cal
from app.utils.dates import parse_date, parse_datetime, to_int

log = get_logger("repo.input")


def _s(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ---------- projects（从人员表的项目编号/项目名称派生，满足 FK） ----------
def upsert_projects_from_employees(db: Session, df: pd.DataFrame) -> int:
    if "项目编号" not in df.columns and "项目名称" not in df.columns:
        return 0
    n = 0
    seen = set()
    for _, r in df.iterrows():
        code = _s(r.get("项目编号")) or _s(r.get("项目名称"))
        if not code or code in seen:
            continue
        seen.add(code)
        obj = db.scalar(select(Project).where(Project.project_code == code))
        name = _s(r.get("项目名称")) or code
        if obj:
            obj.project_name = name
        else:
            db.add(Project(project_code=code, project_name=name))
            n += 1
    db.flush()
    return n


def upsert_employees(db: Session, df: pd.DataFrame, report_date: date | None = None) -> int:
    """UPSERT 人员表快照。

    report_date：本次上传对应的报告日（下午3点导出快照日期）。用于驱动
    hire_first_visible_date / resign_first_visible_date（Row2/Row3 的"晚到
    补入今天"判断，见 05表Q9、02表Row2/Row3 口径）：
      - 首次插入该员工、且已带入职/离职日期：视为今天首次可见，记录首次可见日期；
      - 已存在的员工：只在该日期字段从"空"变为"有值"（本次上传才第一次出现该事实）
        时补记首次可见日期；已记录过的首次可见日期不回写/不覆盖，
        即便后续上传把 entry_date/resign_date 本身做了追溯性修正。

    首次建库（基线导入）的特殊处理：
      若本次上传前 employees 表是空的（is_baseline_load=True），说明这是把
      "已经在职多年的现有人员名单"第一次搬进本系统，不是"今天真的有这么多人
      入职/离职"。此时若仍按上面"首次可见=report_date(今天)"的规则记
      hire_first_visible_date/resign_first_visible_date，daily.py 的
      _count_today_fact()（"晚到补入今天"）会把每一个人的历史入职/离职日期
      都判定成"今天才首次可见"从而记为今日入职/今日离职，导致 Row2/Row3
      虚增成"全员工都是今天入职"。基线导入时改为把 first_visible_date 直接
      设为事实日期本身（= entry_date/resign_date），而不是 report_date；
      这样只有真的等于 report_date 的记录（例如系统上线当天恰好有人真入职）
      才会被计入"今日"，历史数据不受影响。之后的日常增量上传（is_baseline_load
      变为 False）才走"晚到补入今天"的原有逻辑。
    """
    upsert_projects_from_employees(db, df)
    if report_date is not None:
        _replace_employee_snapshot(db, df, report_date)
    is_baseline_load = report_date is not None and (
        db.scalar(select(func.count()).select_from(Employee)) or 0
    ) == 0
    n = 0
    for _, r in df.iterrows():
        emp_no = _s(r.get("工号"))
        if not emp_no:
            continue
        obj = db.scalar(select(Employee).where(Employee.employee_no == emp_no))
        is_new = obj is None
        if obj is None:
            obj = Employee(employee_no=emp_no)
            db.add(obj)
            n += 1
        obj.name = _s(r.get("中文名")) or obj.name or emp_no
        obj.english_name = _s(r.get("英文名"))
        obj.alias = _s(r.get("Alias"))
        obj.employee_type = _s(r.get("员工类型")) or obj.employee_type
        obj.status = _map_status(_s(r.get("员工状态")))
        obj.department = _s(r.get("部门"))
        obj.department_code = _s(r.get("部门编号"))
        obj.bu = _s(r.get("事业部"))
        obj.bu_code = _s(r.get("事业部编号"))
        obj.project_code = _s(r.get("项目编号")) or _s(r.get("项目名称"))

        new_entry = parse_date(r.get("入职日期"))
        new_resign = parse_date(r.get("离职日期"))
        had_entry = obj.entry_date is not None
        had_resign = obj.resign_date is not None
        obj.entry_date = new_entry
        obj.resign_date = new_resign
        obj.intern_contract_end = parse_date(r.get("实习生合同结束日期"))

        if report_date is not None:
            # 入职事实首次可见：新员工首次入库即带入职日期，或老员工原先没有
            # 入职日期、本次上传才首次出现 -> 都算"今天才首次可见"。
            # 但如果这是基线导入（is_baseline_load），"今天才首次可见"记为
            # entry_date 本身而不是 report_date——见函数 docstring。
            if new_entry is not None and obj.hire_first_visible_date is None and (
                is_new or not had_entry
            ):
                obj.hire_first_visible_date = new_entry if is_baseline_load else report_date
            # 离职事实首次可见：同理
            if new_resign is not None and obj.resign_first_visible_date is None and (
                is_new or not had_resign
            ):
                obj.resign_first_visible_date = new_resign if is_baseline_load else report_date
    db.flush()
    return n


def _replace_employee_snapshot(db: Session, df: pd.DataFrame, report_date: date) -> None:
    """按报告日整批替换快照，避免更正文件重传后残留旧行。

    真实导出偶发同工号重复行：与主表 UPSERT 的语义一致取最后一行，
    不让唯一键 (report_date, employee_no) 冲突拖垮整个上传。"""
    db.execute(
        delete(EmployeeSnapshot).where(EmployeeSnapshot.report_date == report_date)
    )
    latest_rows: dict[str, pd.Series] = {}
    for _, r in df.iterrows():
        emp_no = _s(r.get("工号"))
        if not emp_no:
            continue
        if emp_no in latest_rows:
            log.warning(
                "人员表快照发现重复工号，按最后一行为准（报告日=%s）",
                report_date,
            )
        latest_rows[emp_no] = r
    for emp_no, r in latest_rows.items():
        db.add(EmployeeSnapshot(
            report_date=report_date,
            employee_no=emp_no,
            employee_type=_s(r.get("员工类型")) or "",
            status=_map_status(_s(r.get("员工状态"))),
            business_unit=_s(r.get("事业部")),
            business_unit_no=_s(r.get("事业部编号")),
            project_code=_s(r.get("项目编号")) or _s(r.get("项目名称")),
            project_name=_s(r.get("项目名称")),
            entry_date=parse_date(r.get("入职日期")),
            resign_date=parse_date(r.get("离职日期")),
        ))
    db.flush()


def _map_status(s: str | None) -> str:
    if not s:
        return "active"
    if "离" in s:
        return "resigned"
    if "转签" in s:
        return "transferred"
    return "active"


def _ensure_employee_for_resignation(db: Session, r: pd.Series) -> None:
    """离职报表可能早于人员表增量到达；缺主表时从离职行补建最小员工记录以满足 FK。"""
    emp_no = _s(r.get("工号"))
    if not emp_no:
        return
    if db.scalar(select(Employee).where(Employee.employee_no == emp_no)):
        return
    proj = _s(r.get("项目名称")) or _s(r.get("项目编号"))
    if proj and not db.scalar(select(Project).where(Project.project_code == proj)):
        db.add(Project(project_code=proj, project_name=proj))
        db.flush()
    db.add(
        Employee(
            employee_no=emp_no,
            name=_s(r.get("姓名")) or emp_no,
            employee_type=_s(r.get("员工类型")) or "正式员工",
            bu=_s(r.get("事业部")),
            department=_s(r.get("部门")),
            project_code=proj,
            entry_date=parse_date(r.get("入职时间")),
        )
    )


def upsert_resignations(db: Session, df: pd.DataFrame) -> int:
    n = 0
    for _, r in df.iterrows():
        pno = _s(r.get("流程单号"))
        if not pno:
            continue
        _ensure_employee_for_resignation(db, r)
        obj = db.scalar(
            select(EmployeeResignation).where(EmployeeResignation.process_no == pno)
        )
        if obj is None:
            obj = EmployeeResignation(process_no=pno)
            db.add(obj)
            n += 1
        obj.node_name = _s(r.get("节点名称"))
        obj.process_status = _s(r.get("流程状态"))
        obj.employee_no = _s(r.get("工号")) or obj.employee_no or ""
        obj.resign_date = parse_date(r.get("最后工作日"))
        obj.resign_type = _s(r.get("离职方式"))
        obj.resign_reason = _s(r.get("离职原因"))
        # 申请时间 -> 首次可见日期（库内以首次可见驱动提出离职取数）
        obj.first_visible_date = (
            parse_date(r.get("员工申请时间")) or parse_date(r.get("首次可见日期"))
        )
    db.flush()
    return n


def upsert_oa(
    db: Session, df: pd.DataFrame, report_date: date | None = None
) -> int:
    is_baseline_load = (
        db.scalar(
            select(func.count())
            .select_from(OAProtocol)
            .where(OAProtocol.is_deleted == 0)
        )
        or 0
    ) == 0
    n = 0
    for _, r in df.iterrows():
        ono = _s(r.get("单号"))
        if not ono:
            continue
        obj = db.scalar(select(OAProtocol).where(OAProtocol.order_no == ono))
        is_new = obj is None
        if obj is None:
            obj = OAProtocol(order_no=ono, task_no=_s(r.get("任务号")) or ono)
            db.add(obj)
            n += 1
        obj.title = _s(r.get("流程名称"))
        obj.initiator = _s(r.get("创建人"))
        obj.initiate_time = parse_datetime(r.get("申请时间"))
        obj.current_status = _s(r.get("当前状态"))
        obj.process_type = _s(r.get("流程类型")) or (
            "人事相关" if "协议" in str(r.get("流程名称") or "") else None
        )
        obj.employee_flag = _s(r.get("员工标识"))
        explicit_first_visible = parse_date(r.get("首次可见批次"))
        application_date = parse_date(r.get("申请时间"))
        if is_new:
            obj.first_visible_date = explicit_first_visible or (
                application_date
                if (
                    is_baseline_load
                    or report_date is None
                    or (
                        application_date is not None
                        and application_date < cal.prev_workday(report_date)
                    )
                )
                else report_date
            )
        elif obj.first_visible_date is None:
            obj.first_visible_date = (
                explicit_first_visible or report_date or application_date
            )
        # 计入Row5/Row30 只能从 否→是，不能从 是→否：
        # 首次可见时已标 是，后续天的上传不应覆盖降级
        _TRUE_SET = {"是", "Y", "y", "yes", "true", "True", "1"}
        new5 = _s(r.get("计入Row5"))
        if new5 in _TRUE_SET or obj.row5_flag not in _TRUE_SET:
            obj.row5_flag = new5
        new30 = _s(r.get("计入Row30"))
        if new30 in _TRUE_SET or obj.row30_flag not in _TRUE_SET:
            obj.row30_flag = new30
        obj.remarks = _s(r.get("备注"))
    db.flush()
    return n


_TOTAL_SENTINEL = "__TOTAL__"


def upsert_recruitment(db: Session, report_date: date, df: pd.DataFrame) -> int:
    """招聘表按 (report_date, recruiter) UPSERT；动态列已在解析层归一。

    合计行以 recruiter="__TOTAL__" 入库而非丢弃，使 load_recruitment 能还原
    is_total_row=True 并在计算层执行行求和 vs 合计行的交叉校验（Q7）。
    """
    n = 0
    for _, r in df.iterrows():
        is_total = bool(r.get("is_total_row"))
        recruiter = _TOTAL_SENTINEL if is_total else _s(r.get("招聘专员"))
        if not recruiter:
            continue
        obj = db.scalar(
            select(RecruitmentPipeline).where(
                RecruitmentPipeline.report_date == report_date,
                RecruitmentPipeline.recruiter == recruiter,
            )
        )
        if obj is None:
            obj = RecruitmentPipeline(report_date=report_date, recruiter=recruiter)
            db.add(obj)
            n += 1
        obj.expected_onboard_m = to_int(r.get("当月接受offer当月预计入职")) or 0
        obj.expected_onboard_m_prev = to_int(r.get("上月接受offer当月预计入职")) or 0
        obj.onboard_m = to_int(r.get("当月已入职总数")) or 0
    db.flush()
    return n
