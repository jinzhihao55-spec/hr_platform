from fastapi import APIRouter, Query

from app.services import archive_service

router = APIRouter(prefix="/archive", tags=["archive"])


@router.get("")
def archive(kind: str = Query("all", description="all / daily / weekly / calc_log")):
    """归档页：按报告日期归类的产物文件列表（含 path 供 /reports/download 下载）。"""
    return archive_service.list_archive(kind)
