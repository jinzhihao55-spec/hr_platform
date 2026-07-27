"""API 请求/响应模型。"""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class IngestResponse(BaseModel):
    report_date: date
    job_id: str
    status: str
    counts: dict[str, int] = {}         # 各主表当前行数（needs_clarification 分支也需提供）
    sources: dict[str, dict] = {}       # 每类源：updated(本次上传) / reused(沿用库内)
    warnings: list[str] = []
    error: dict[str, Any] | None = None  # needs_clarification 时的业务错误详情（code/message/detail）


class ClarificationItem(BaseModel):
    code: str
    message: str
    affects: str | None = None          # 如 "日报 Row30"
    options: list[str] = []


class DailyExistsResponse(BaseModel):
    """检查报告日前一工作日基线日报是否已落库（能否链式生成 report_date 当日日报）。"""
    report_date: date
    baseline_date: date
    exists: bool
    action_required: str | None = None
    message: str
    daily_employee_change: int | None = None
    generated_at: datetime | None = None


class ImportDailyResponse(BaseModel):
    report_date: date
    status: str
    overwritten: bool
    rows_imported: int
    baseline_report_id: str
    kpis: dict[str, int] = {}
    # 导入后按新基线级联重算的后续日报 [{"report_date","status"}, ...]
    cascaded: list[dict[str, Any]] = []
    cascade_error: str | None = None


class GenerateReportRequest(BaseModel):
    report_date: date
    baseline_date: date | None = None   # 链式基线日；缺省=早于报告日的最近一份日报（通常昨日）


class GenerateWeeklyRequest(BaseModel):
    week_start: date
    week_end: date


class JobOut(BaseModel):
    job_id: str
    kind: str
    status: str
    report_date: date | None = None
    message: str | None = None
    result: dict[str, Any] | None = None


class SeedBaselineRequest(BaseModel):
    """手动注入链式基线（当历史日报缺失导致 BaselineMissingError 时使用）。

    for_date：提供的数据所代表的"昨日"报告日期（即 report_date - 1 工作日）。
    计算引擎将以此日期创建或覆盖 daily_reports 基线行，使下一次生成日报时
    能正常完成 MTD/YTD 链式顺推。
    """
    for_date: date          # 基线所在日期（通常是报告日的前一工作日）
    row8: int = 0           # MTD 入职累计
    row9: int = 0           # MTD 离职累计
    row13: int = 0          # YTD 入职累计
    row14: int = 0          # YTD 离职累计
    row30: int = 0          # Release 截至当日累计


class MonthOpeningConfirmRequest(BaseModel):
    """HR 明确确认某份已验收日报可作为新月份的月初基线。"""

    report_month: date
    baseline_date: date
    confirmed_by: str = ""  # 本机开发使用；共享环境由网关注入真实用户


class QueryRequest(BaseModel):
    question: str
    schema_hint: str = ""
    max_rows: int = 1000


class QueryResponse(BaseModel):
    sql: str
    row_count: int
    rows: list[dict[str, Any]]
