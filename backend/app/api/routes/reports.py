from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import HRAgentError
from app.config import settings
from app.schemas.api import (
    DailyExistsResponse,
    GenerateReportRequest,
    GenerateWeeklyRequest,
    ImportDailyResponse,
    MonthOpeningConfirmRequest,
    SeedBaselineRequest,
)
from app.services import (
    baseline_check_service,
    daily_import_service,
    month_opening_service,
    report_service,
    view_service,
)
from app.repositories import report_repo

router = APIRouter(prefix="/reports", tags=["reports"])


def _month_opening_actor(request: Request, claimed: str) -> str:
    """共享环境只信反向代理注入的身份，并限制为配置的 HR 用户。"""
    proxy_user = (request.headers.get("x-authenticated-user") or "").strip()
    if settings.app_env in ("dev", "local", "test"):
        return proxy_user or claimed.strip()
    allowed = {
        user.strip()
        for user in settings.month_opening_allowed_users.split(",")
        if user.strip()
    }
    if not proxy_user or proxy_user not in allowed:
        raise HTTPException(403, "当前用户无权确认或上传月初基线")
    return proxy_user


def _apply_status(out: dict, response: Response) -> dict:
    """业务状态 -> HTTP 状态码：succeeded->200 / blocked->422 / needs_clarification->409。"""
    s = out.get("status")
    if s == "blocked":
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif s == "needs_clarification":
        response.status_code = status.HTTP_409_CONFLICT
    return out


# ---------------- 基线注入 ----------------
@router.post("/baseline")
def seed_baseline(req: SeedBaselineRequest, db: Session = Depends(get_db)):
    """手动注入链式基线（解决 BaselineMissingError）。

    当历史日报缺失导致 MTD/YTD 无法链式顺推时，用此接口提供上一工作日的累计值。
    注入后重新调用 POST /reports/daily 即可正常生成当日报表。

    也可通过 POST /clarifications/{id}/answer 提交相同 JSON，系统在下次生成日报时
    自动消费该答复并注入基线。
    """
    return report_service.seed_baseline(
        db,
        for_date=req.for_date,
        row8=req.row8,
        row9=req.row9,
        row13=req.row13,
        row14=req.row14,
        row30=req.row30,
    )


@router.post("/month-opening/confirm")
def confirm_month_opening(
    req: MonthOpeningConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """HR 明确确认沿用指定已验收定稿作为新月份基线。"""
    return month_opening_service.confirm_carry_forward(
        db,
        report_month=req.report_month,
        baseline_date=req.baseline_date,
        confirmed_by=_month_opening_actor(request, req.confirmed_by),
    )


@router.post("/month-opening/import")
async def import_month_opening(
    request: Request,
    report_month: date = Form(..., description="目标月份，必须是该月 1 日"),
    confirmed_by: str = Form("", description="本机开发使用；共享环境以网关身份为准"),
    file: UploadFile = File(..., description="A+B 基线工作簿，含在岗时长基线"),
    db: Session = Depends(get_db),
):
    """上传 HR 重述后的独立月初基线，不覆盖上月日报。"""
    return await month_opening_service.import_baseline(
        db,
        report_month=report_month,
        confirmed_by=_month_opening_actor(request, confirmed_by),
        file=file,
    )


@router.get("/month-opening/{report_month}")
def get_month_opening(report_month: date, db: Session = Depends(get_db)):
    """查询目标月份是否已有 HR 确认的月初基线。"""
    out = month_opening_service.get_confirmed(db, report_month)
    if out is None:
        raise HTTPException(404, "该月份尚未确认月初基线")
    return out


# ---------------- 生成 ----------------
@router.post("/daily")
def generate_daily(
    req: GenerateReportRequest, response: Response, db: Session = Depends(get_db)
):
    """生成日报（本周最后工作日自动一并出周报）。数据取自数据库主表。

    补生成历史日期时，其后已生成的日报会按日期顺序级联重算
    （MTD/YTD/Row30 为链式累计，前面变了后面必须跟着变），结果附 "cascaded" 字段。

    baseline_date 可选：指定链式基线日（默认取早于报告日的最近一份日报，通常昨日）。"""
    return _apply_status(
        report_service.generate_daily_cascade(
            db, req.report_date, req.baseline_date), response)


@router.post("/weekly")
def generate_weekly(
    req: GenerateWeeklyRequest, response: Response, db: Session = Depends(get_db)
):
    """单独生成周报（窗口 week_start ~ week_end）。"""
    return _apply_status(
        report_service.generate_weekly(db, req.week_start, req.week_end), response
    )


# ---------------- 列表（选择器） ----------------
@router.get("/daily/dates")
def daily_dates(db: Session = Depends(get_db)):
    """日报页日期选择器：已生成日报的日期列表（倒序）。"""
    return report_repo.list_daily_dates(db)


@router.post("/daily/import", response_model=ImportDailyResponse)
async def import_daily(
    request: Request,
    report_date: str = Form(..., description="要导入的日报日期（通常为前一工作日），格式 YYYY-MM-DD"),
    file: UploadFile = File(..., description="定稿日报 xlsx"),
    db: Session = Depends(get_db),
):
    """上传定稿日报，并登记为下一 Run 可引用的不可变正式基线。"""
    operator = (
        request.headers.get("x-authenticated-user") or "local-operator"
    ).strip()
    parsed_date = date.fromisoformat(report_date)
    return await daily_import_service.import_daily(
        db, parsed_date, file, imported_by=operator
    )


@router.post("/daily/{report_date}/baseline-override", response_model=ImportDailyResponse)
async def override_daily_baseline(
    report_date: date,
    request: Request,
    file: UploadFile = File(..., description="调整后的日报 xlsx"),
    db: Session = Depends(get_db),
):
    """上传用户手动调整后的日报 xlsx 作为新的链式基线。

    系统以用户上传的调整后日报为准，覆盖 daily_reports 中该日期的数据，
    并自动级联重算后续所有日报和周报。上传的调整日报跳过校验（视为人工验收），
    级联重算的后续报表走正常校验。
    """
    operator = (
        request.headers.get("x-authenticated-user") or "local-operator"
    ).strip()
    return await daily_import_service.override_daily_baseline(
        db, report_date, file, imported_by=operator
    )


@router.get("/weekly/weeks")
def weekly_weeks(db: Session = Depends(get_db)):
    """周报页周次选择器：已生成周报的周次列表（倒序）。"""
    return report_repo.list_weeks(db)


# ---------------- 存在性查询 ----------------
@router.get("/daily/{report_date}/exists", response_model=DailyExistsResponse)
def daily_exists(
    report_date: date,
    baseline_date: date | None = Query(
        None, description="可选：待校验的链式基线日；缺省=报告日前一工作日"),
    db: Session = Depends(get_db),
):
    """检查链式基线日报是否已落库（链式基线就绪）。

    路径参数 report_date 为待生成的报告日。baseline_date 缺省时校验
    prev_workday(report_date)；显式指定时校验用户选定的基线日在 daily_reports
    中是否有记录（exists）。"""
    return baseline_check_service.check(db, report_date, baseline_date)


# ---------------- 结构化视图（日报/周报/计算日志页） ----------------
@router.get("/daily/{report_date}/view")
def daily_view(report_date: date, response: Response, db: Session = Depends(get_db)):
    """日报结构化视图：Row2–40（含基线、公式、来源、trace）+ 在岗时长 + 12 项校验 + KPI。
    同一份数据供「计算日志」页逐行追溯。"""
    try:
        return view_service.daily_view(db, report_date)
    except HRAgentError as exc:
        response.status_code = status.HTTP_409_CONFLICT
        return {"status": "needs_clarification", "error": exc.to_dict()}


@router.get("/weekly/{week_end}/view")
def weekly_view(
    week_end: date,
    week_start: date = Query(..., description="本周一（窗口起始）"),
    db: Session = Depends(get_db),
):
    """周报结构化视图：Sheet2（主体×事业部 + 合计）+ Sheet1（成本中心×项目）。"""
    return view_service.weekly_view(db, week_start, week_end)


# ---------------- 下载 ----------------
@router.get("/download")
def download(path: str):
    """按服务器路径下载已生成的产物（日报/周报 xlsx、计算日志 md）。

    安全限制：仅允许下载导出目录（settings.output_dir）内的文件，防止路径穿越。
    当部署目录变更后，旧路径会自动重定位到当前 output_dir 下。
    """
    from app.config import settings
    from app.utils.path_security import resolve_protected_path

    output_root = Path(settings.output_dir).resolve()
    p = Path(path).resolve()
    try:
        p.relative_to(output_root)
    except ValueError:
        # 路径在 output_dir 之外，尝试重定位（部署目录迁移场景）
        resolved = resolve_protected_path(path, output_root)
        if resolved is None:
            raise HTTPException(403, "禁止访问导出目录以外的文件")
        return FileResponse(str(resolved), filename=resolved.name)
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(p), filename=p.name)
