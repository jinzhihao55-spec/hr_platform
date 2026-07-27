"""四类输入源、项目表与人员日快照的 ORM 模型。

说明：这是一套以 employees 为主表的规范化业务库（非按 run 快照）。
入离职/在职事实由 employees.entry_date / resign_date 驱动；
提出离职/Release 事实由 employee_resignations / oa_protocols 的首次可见日期驱动。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin, uuid_pk


class Project(Base, AuditMixin):
    """1. projects —— 项目表。"""

    __tablename__ = "projects"

    id: Mapped[str] = uuid_pk()
    project_code: Mapped[str] = mapped_column(String(20), unique=True)   # 项目编码
    project_name: Mapped[str] = mapped_column(String(100))               # 项目名称
    project_staff: Mapped[str | None] = mapped_column(String(50))        # 项目人员


class Employee(Base, AuditMixin):
    """2. employees —— 人员主表（实际入职/离职/在职事实的唯一权威源）。"""

    __tablename__ = "employees"

    id: Mapped[str] = uuid_pk()
    employee_no: Mapped[str] = mapped_column(String(20), unique=True)    # 员工编号/工号 ★
    name: Mapped[str] = mapped_column(String(50))                        # 姓名
    english_name: Mapped[str | None] = mapped_column(String(50))
    alias: Mapped[str | None] = mapped_column(String(50))
    employee_type: Mapped[str] = mapped_column(String(20))               # 正式员工/实习/外包/顾问 ★
    status: Mapped[str | None] = mapped_column(String(20), default="active")  # active/resigned/transferred
    department: Mapped[str | None] = mapped_column(String(100))
    department_code: Mapped[str | None] = mapped_column(String(20))
    bu: Mapped[str | None] = mapped_column(String(50))                   # 事业部
    bu_code: Mapped[str | None] = mapped_column(String(20))              # 事业部编码 ★
    position: Mapped[str | None] = mapped_column(String(50))
    position_en: Mapped[str | None] = mapped_column(String(100))
    job_level: Mapped[str | None] = mapped_column(String(20))
    report_to: Mapped[str | None] = mapped_column(String(50))
    project_code: Mapped[str | None] = mapped_column(String(20))         # FK -> projects.project_code
    entry_date: Mapped[date | None] = mapped_column(Date)                # 入职日期 ★
    resign_date: Mapped[date | None] = mapped_column(Date)               # 离职日期 ★
    hire_first_visible_date: Mapped[date | None] = mapped_column(Date)   # 入职事实首次可见日期(晚到补入) ★
    resign_first_visible_date: Mapped[date | None] = mapped_column(Date)  # 离职事实首次可见日期(晚到补入) ★
    contract_start: Mapped[date | None] = mapped_column(Date)
    contract_end: Mapped[date | None] = mapped_column(Date)
    contract_company: Mapped[str | None] = mapped_column(String(100))
    probation_start: Mapped[date | None] = mapped_column(Date)
    probation_end: Mapped[date | None] = mapped_column(Date)
    transfer_prev_company: Mapped[str | None] = mapped_column(String(100))   # 转签前单位
    transfer_prev_contract_start: Mapped[date | None] = mapped_column(Date)
    transfer_prev_contract_end: Mapped[date | None] = mapped_column(Date)
    intern_contract_start: Mapped[date | None] = mapped_column(Date)
    intern_contract_end: Mapped[date | None] = mapped_column(Date)       # 实习期合同结束 ★
    expected_release_date: Mapped[date | None] = mapped_column(Date)     # 预计Release日期(供Row30判断)
    release_type: Mapped[str | None] = mapped_column(String(20))         # 主动离职/协议解除/到期不续


class EmployeeSnapshot(Base, AuditMixin):
    """报告日人员快照，用于可追溯地重算周报在职口径。"""

    __tablename__ = "employee_snapshots"
    __table_args__ = (
        UniqueConstraint("report_date", "employee_no", name="uq_employee_snapshot_day_no"),
    )

    id: Mapped[str] = uuid_pk()
    report_date: Mapped[date] = mapped_column(Date, index=True)
    employee_no: Mapped[str] = mapped_column(String(20), index=True)
    employee_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str | None] = mapped_column(String(20))
    business_unit: Mapped[str | None] = mapped_column(String(50))
    business_unit_no: Mapped[str | None] = mapped_column(String(20))
    project_code: Mapped[str | None] = mapped_column(String(100))
    project_name: Mapped[str | None] = mapped_column(String(100))
    entry_date: Mapped[date | None] = mapped_column(Date)
    resign_date: Mapped[date | None] = mapped_column(Date)


class EmployeeResignation(Base, AuditMixin):
    """3. employee_resignations —— 离职人员报表（主动提出离职流程）。"""

    __tablename__ = "employee_resignations"

    id: Mapped[str] = uuid_pk()
    process_no: Mapped[str] = mapped_column(String(50), unique=True)     # 流程单号 ★
    node_name: Mapped[str | None] = mapped_column(String(50))
    process_status: Mapped[str | None] = mapped_column(String(20))       # 进行中/已完结/已驳回 ★
    employee_no: Mapped[str] = mapped_column(String(20))                 # FK -> employees.employee_no
    resign_date: Mapped[date | None] = mapped_column(Date)              # 离职日期(LWD) ★
    resign_type: Mapped[str | None] = mapped_column(String(20))         # 主动离职/协商解除/合同到期/辞退 ★
    resign_reason: Mapped[str | None] = mapped_column(String(200))
    release_notice_date: Mapped[date | None] = mapped_column(Date)       # 项目释放通知时间
    first_visible_date: Mapped[date | None] = mapped_column(Date)        # 首次可见日期(提出离职取数) ★


class OAProtocol(Base, AuditMixin):
    """4. oa_protocols —— OA协议签署/离职审批表（被动 Release 提出事实）。"""

    __tablename__ = "oa_protocols"

    id: Mapped[str] = uuid_pk()
    task_no: Mapped[str] = mapped_column(String(50), unique=True)        # 任务号
    order_no: Mapped[str] = mapped_column(String(50), unique=True)       # 单号 ★
    title: Mapped[str | None] = mapped_column(String(200))               # 流程标题
    initiator: Mapped[str | None] = mapped_column(String(50))
    initiator_department: Mapped[str | None] = mapped_column(String(50))
    initiate_time: Mapped[datetime | None] = mapped_column(DateTime)     # 发起时间
    current_status: Mapped[str | None] = mapped_column(String(20))       # 审批中/已通过/已驳回 ★
    process_type: Mapped[str | None] = mapped_column(String(20))         # 离职审批/协议解除/转签 ★
    related_employee: Mapped[str | None] = mapped_column(String(20))     # 关联员工编号
    related_name: Mapped[str | None] = mapped_column(String(50))
    employee_flag: Mapped[str | None] = mapped_column(String(30))        # 员工标识
    first_visible_date: Mapped[date | None] = mapped_column(Date)        # 首次可见日期 ★
    row5_flag: Mapped[str | None] = mapped_column(String(10))            # 计入Row5 是/否
    row30_flag: Mapped[str | None] = mapped_column(String(10))           # 计入Row30 是/否(LWD在本月)
    remarks: Mapped[str | None] = mapped_column(Text)                    # 备注


class SourceUploadRecord(Base, AuditMixin):
    """每日各输入源的上传记录（MySQL 持久化）。

    每日生成门禁以本表为准：按 report_date + source 判定当日是否上传；
    Redis（source_status_repo.save/load）仅作前端展示缓存，过期不影响门禁。"""

    __tablename__ = "source_upload_records"
    __table_args__ = (
        UniqueConstraint("report_date", "source", name="uq_source_upload_day"),
    )

    id: Mapped[str] = uuid_pk()
    report_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(20))    # employees/resignations/agreements/recruitment
    action: Mapped[str] = mapped_column(String(10))    # updated / reused
    rows_upserted: Mapped[int | None] = mapped_column(Integer)


class RecruitmentPipeline(Base, AuditMixin):
    """5. recruitment_pipeline —— 招聘漏斗表（本月预估入职取数）。"""

    __tablename__ = "recruitment_pipeline"

    id: Mapped[str] = uuid_pk()
    recruiter: Mapped[str | None] = mapped_column(String(50))            # 招聘专员/模板字段
    target_position: Mapped[str | None] = mapped_column(String(50))
    month_offers: Mapped[int] = mapped_column(Integer, default=0)
    month_offer_date: Mapped[date | None] = mapped_column(Date)
    month_offer_prev_cum: Mapped[int] = mapped_column(Integer, default=0)
    onboard_m: Mapped[int] = mapped_column(Integer, default=0)           # 本月内入职数(确定入职)
    onboard_m_headhunter: Mapped[int] = mapped_column(Integer, default=0)
    expected_onboard_m: Mapped[int] = mapped_column(Integer, default=0)  # 本月offer本月即入职 -> Row39
    expected_onboard_m_prev: Mapped[int] = mapped_column(Integer, default=0)  # 上月offer本月入职 -> Row38
    confirmed_onboard_m: Mapped[int] = mapped_column(Integer, default=0)
    remarks: Mapped[str | None] = mapped_column(Text)
    report_date: Mapped[date | None] = mapped_column(Date)               # 数据日期
