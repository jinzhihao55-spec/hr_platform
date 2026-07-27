from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import context_service

router = APIRouter(tags=["context"])


@router.get("/context")
def get_context(report_date: date, db: Session = Depends(get_db)):
    """工作台/页头上下文：报告日期、星期、基线日、本周窗口、是否本周最后工作日、
    是否自动出周报、四类主表行数、待确认澄清数。"""
    return context_service.context(db, report_date)
