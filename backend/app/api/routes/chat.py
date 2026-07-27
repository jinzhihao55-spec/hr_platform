"""对话接口。

前端通过 POST /chat 驱动整个流水线，无需关心内部各步骤 API。
后端自动判断当前状态（文件是否已上传、是否有待确认澄清）并执行对应操作。

GET /chat/history?report_date=&session_id= 查询历史消息。
"""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories import chat_repo
from app.services import orchestration_service

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    report_date: date
    message: str
    session_id: str | None = None     # 前端可复用同一 session；为空则后端自动生成
    baseline_date: date | None = None  # 可选链式基线日（生成日报时生效；默认=最近一份日报）


class ChatResponse(BaseModel):
    session_id: str
    role: str = "assistant"
    message: str
    action: str
    status: str
    payload: dict | None = None
    clarification_id: str | None = None


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """统一对话入口。

    前端发送用户消息（自然语言或 JSON 答复），后端：
    1. 若有待确认澄清且消息是答复 → 应用答复，更新 DB 相关字段，自动重试生成
    2. 若用户请求生成（或无澄清待回复）→ 触发日报/周报生成
    3. 其他情况 → 返回当前流水线状态摘要

    所有消息（用户 + 助手）均保存到 chat_messages 表。
    """
    result = orchestration_service.handle_message(
        db,
        report_date=req.report_date,
        message=req.message,
        session_id=req.session_id,
        baseline_date=req.baseline_date,
    )
    # Filter out None values so Pydantic v2 uses field defaults (e.g. role="assistant")
    return ChatResponse(**{k: v for k, v in result.items()
                           if k in ChatResponse.model_fields and v is not None})


@router.get("/history")
def chat_history(
    report_date: date | None = None,
    session_id: str | None = None,
    db: Session = Depends(get_db),
):
    """查询对话历史。

    - 指定 report_date → 返回该报告日的全部消息
    - 指定 session_id → 返回该会话的全部消息
    - 两者都指定 → 以 session_id 为准
    """
    if session_id:
        return chat_repo.list_by_session(db, session_id)
    if report_date:
        return chat_repo.list_by_date(db, report_date)
    return []
