from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories import clarify_repo

router = APIRouter(prefix="/clarifications", tags=["clarifications"])


class AnswerIn(BaseModel):
    answer: str


@router.get("")
def list_clarifications(
    report_date: date,
    include_answered: bool = False,
    db: Session = Depends(get_db),
):
    """工作台「对话」：列出某报告日的待确认事项（或全部）。
    MySQL 为数据源，永久保留（不受 Redis TTL 限制）。
    """
    return (
        clarify_repo.list_all(report_date, db=db)
        if include_answered
        else clarify_repo.list_pending(report_date, db=db)
    )


@router.post("/{item_id}/answer")
def answer_clarification(
    item_id: str,
    body: AnswerIn,
    db: Session = Depends(get_db),
):
    """提交澄清答复（人在环留痕）。
    同时更新 MySQL clarifications 表和 Redis 缓存。
    答复写入 MySQL 后永久保存；下次生成日报时自动消费。
    """
    out = clarify_repo.answer(item_id, body.answer, db=db)
    if out is None:
        raise HTTPException(404, "澄清事项不存在")
    return out
