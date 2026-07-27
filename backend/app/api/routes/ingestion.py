from datetime import date

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.api import IngestResponse
from app.services import ingestion_service

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _apply_status(out: dict, response: Response) -> dict:
    """业务状态 -> HTTP 状态码：needs_clarification -> 409（与 /reports 保持一致）。"""
    if out.get("status") == "needs_clarification":
        response.status_code = status.HTTP_409_CONFLICT
    return out


@router.post("/combined", response_model=IngestResponse)
async def ingest_combined_workbook(
    response: Response,
    report_date: date = Form(..., description="报告日 YYYY-MM-DD"),
    file: UploadFile = File(..., description="四表合一 xlsx（必选，点 Choose File）"),
    db: Session = Depends(get_db),
):
    """上传四表合一工作簿（推荐）。Safari /docs 若 combined 无可选文件，请用本接口。"""
    out = await ingestion_service.ingest(db, report_date, {"combined": file})
    return IngestResponse(report_date=report_date, **_apply_status(out, response))


@router.post("", response_model=IngestResponse)
async def ingest_inputs(
    response: Response,
    report_date: date = Form(..., description="报告日 YYYY-MM-DD，如 2026-06-22"),
    combined: UploadFile | None = File(
        None, description="四表合一 xlsx（多 sheet）；与下方分文件二选一"
    ),
    employees: UploadFile | None = File(
        None, description="人员表：.xlsx / .xls"
    ),
    resignations: UploadFile | None = File(
        None, description="离职报表：.xlsx / .xls"
    ),
    agreements: UploadFile | None = File(
        None,
        description="OA 协议签署：.xlsx 或截图 .png/.jpg（视觉 LLM 自动识别，需配置 LLM_VISION_*）",
    ),
    recruitment: UploadFile | None = File(
        None,
        description="招聘数据：.xlsx 或截图 .png/.jpg（视觉 LLM 自动识别，需配置 LLM_VISION_*）",
    ),
    db: Session = Depends(get_db),
):
    """上传四类结构化输入；支持 combined 多 sheet 合一文件。

    **传截图**：只需填 report_date，并在 agreements / recruitment 点 Choose File 选 PNG/JPG
    （取消勾选 Send empty value）；employees / resignations 可留空沿用库内数据。
    解析进库后即删除临时文件。
    """
    files = {
        "combined": combined,
        "employees": employees,
        "resignations": resignations,
        "agreements": agreements,
        "recruitment": recruitment,
    }
    out = await ingestion_service.ingest(db, report_date, files)
    return IngestResponse(report_date=report_date, **_apply_status(out, response))
