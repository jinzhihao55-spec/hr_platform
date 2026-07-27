"""报表输出 ORM 模型，严格对应 database/schema.sql：
daily_reports（按日宽表）、weekly_reports（按周×事业部）、monthly_reports（月报暂不处理）。

注意：完整在岗时长和计算日志仍是派生产物；仅保存已验收日报中的 8 个 BU
汇总快照，供后续日期做链式增量计算，不保存人员级工龄明细。"""
from datetime import date, datetime

from sqlalchemy import Date, DECIMAL, Integer, String, Text, UniqueConstraint, func, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin, uuid_pk


class DailyReport(Base):
    """6. daily_reports —— 员工数增减日报（每个报告日期一行）。"""

    __tablename__ = "daily_reports"

    id: Mapped[str] = uuid_pk()
    report_date: Mapped[date] = mapped_column(Date, unique=True)         # 报告日期
    daily_onboard: Mapped[int] = mapped_column(Integer, default=0)       # 当日入职 Row2
    daily_resign: Mapped[int] = mapped_column(Integer, default=0)        # 当日离职 Row3
    daily_employee_change: Mapped[int] = mapped_column(Integer, default=0)  # 当日净增 Row7
    mtd_onboard: Mapped[int] = mapped_column(Integer, default=0)         # MTD入职 Row8
    mtd_resign: Mapped[int] = mapped_column(Integer, default=0)          # MTD离职 Row9
    mtd_transfer: Mapped[int] = mapped_column(Integer, default=0)        # MTD转正 Row10
    mtd_project_change: Mapped[int] = mapped_column(Integer, default=0)  # MTD微软项目调整 Row11
    mtd_employee_change: Mapped[int] = mapped_column(Integer, default=0) # MTD净增减 Row12
    ytd_onboard: Mapped[int] = mapped_column(Integer, default=0)         # YTD入职 Row13
    ytd_resign: Mapped[int] = mapped_column(Integer, default=0)          # YTD离职 Row14
    ytd_transfer: Mapped[int] = mapped_column(Integer, default=0)        # YTD转正 Row15
    ytd_project_change: Mapped[int] = mapped_column(Integer, default=0)  # YTD微软项目调整 Row16
    ytd_employee_change: Mapped[int] = mapped_column(Integer, default=0) # YTD净增减 Row17
    predicted_resign_recruitment: Mapped[int] = mapped_column(Integer, default=0)  # 预测离职-招聘提供
    predicted_resign: Mapped[int] = mapped_column(Integer, default=0)    # 本月预估离职 Row19/Row33
    predicted_onboard: Mapped[int] = mapped_column(Integer, default=0)   # 本月预估入职 Row18=Row40
    release_today: Mapped[int] = mapped_column(Integer, default=0)       # 当日Release Row5
    release_cum: Mapped[int] = mapped_column(Integer, default=0)         # 累计Release Row30
    release_pending_total: Mapped[int] = mapped_column(Integer, default=0)  # 预计Release(待release)
    expected_resign_cum: Mapped[int] = mapped_column(Integer, default=0) # 预计离职累计 Row33
    expected_onboard_offer: Mapped[int] = mapped_column(Integer, default=0)  # 本月offer预计入职 Row39
    expected_onboard_prev: Mapped[int] = mapped_column(Integer, default=0)   # 上月offer预计入职 Row38
    bi_ytd_resign_rate: Mapped[str | None] = mapped_column(String(20))   # BI口径YTD离职率
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    create_id: Mapped[str | None] = mapped_column(String(36))


class WeeklyReport(Base):
    """8. weekly_reports —— 员工数增减周报（每周×事业部一行）。"""

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint("week_start", "bu", name="uq_weekly_report_week_bu"),
    )

    id: Mapped[str] = uuid_pk()
    week_start: Mapped[date] = mapped_column(Date)                       # 周开始日期
    week_end: Mapped[date] = mapped_column(Date)                         # 周结束日期
    bu: Mapped[str | None] = mapped_column(String(50))                   # 事业部
    headcount_active: Mapped[int] = mapped_column(Integer, default=0)    # 在职人数
    headcount_formal: Mapped[int] = mapped_column(Integer, default=0)    # 正式员工
    headcount_intern: Mapped[int] = mapped_column(Integer, default=0)    # 实习生
    headcount_outsource: Mapped[int] = mapped_column(Integer, default=0) # 外包/劳务
    resigned_formal: Mapped[int] = mapped_column(Integer, default=0)     # 本周离职-正式员工
    onboard_formal: Mapped[int] = mapped_column(Integer, default=0)      # 本周入职-正式员工
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    create_id: Mapped[str | None] = mapped_column(String(36))


class TenureSnapshotMetric(Base):
    """7. 已验收日报中的在岗时长汇总；后续日期在此基线上增量更新。"""

    __tablename__ = "tenure_snapshot_metrics"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "slot", name="uq_tenure_snapshot_slot"),
    )

    id: Mapped[str] = uuid_pk()
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    slot: Mapped[str] = mapped_column(String(20))
    business_unit: Mapped[str] = mapped_column(String(50))
    ytd_leavers: Mapped[int] = mapped_column(Integer, default=0)
    avg_tenure_years: Mapped[float | None] = mapped_column(DECIMAL(8, 2))


class MonthOpeningBaseline(AuditMixin, Base):
    """每月首个报告日前由 HR 确认的独立基线，不覆盖上月定稿。"""

    __tablename__ = "month_opening_baselines"

    id: Mapped[str] = uuid_pk()
    report_month: Mapped[date] = mapped_column(Date, unique=True, index=True)
    baseline_date: Mapped[date] = mapped_column(Date)
    source_type: Mapped[str] = mapped_column(String(20))
    baseline_rows_json: Mapped[str] = mapped_column(Text)
    tenure_rows_json: Mapped[str] = mapped_column(Text)
    template_sha256: Mapped[str] = mapped_column(String(64))
    confirmed_by: Mapped[str] = mapped_column(String(100))


class MonthlyReport(Base):
    """9. monthly_reports —— 员工数增减月报（当前不处理，仅保留表结构）。"""

    __tablename__ = "monthly_reports"

    id: Mapped[str] = uuid_pk()
    report_month: Mapped[date] = mapped_column(Date)                     # 报告月份(每月1日)
    bu: Mapped[str | None] = mapped_column(String(50))
    headcount_start: Mapped[int] = mapped_column(Integer, default=0)
    headcount_end: Mapped[int] = mapped_column(Integer, default=0)
    onboard_count: Mapped[int] = mapped_column(Integer, default=0)
    resign_count: Mapped[int] = mapped_column(Integer, default=0)
    transfer_count: Mapped[int] = mapped_column(Integer, default=0)
    project_name: Mapped[str | None] = mapped_column(String(100))
    project_headcount: Mapped[int] = mapped_column(Integer, default=0)
    monthly_net: Mapped[int] = mapped_column(Integer, default=0)
    ytd_onboard: Mapped[int] = mapped_column(Integer, default=0)
    ytd_resign: Mapped[int] = mapped_column(Integer, default=0)
    resigned_rate: Mapped[float | None] = mapped_column(DECIMAL(5, 2))
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    create_id: Mapped[str | None] = mapped_column(String(36))
