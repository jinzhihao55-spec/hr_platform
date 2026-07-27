"""对话历史存储（MySQL）。

提供保存消息、按日期/会话查询的简单接口。
所有消息类型（用户输入、助手回复、系统提示）均存入同一表。
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage


def save(
    db: Session,
    session_id: str,
    report_date: date | None,
    role: str,
    content: str,
    *,
    action: str | None = None,
    clarification_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChatMessage:
    """保存一条消息，返回已持久化的对象。"""
    msg = ChatMessage(
        id=str(uuid.uuid4()),   # CHAR(36) column — must be full UUID with dashes
        session_id=session_id,
        report_date=report_date,
        role=role,
        content=content,
        action=action,
        clarification_id=clarification_id,
        metadata_json=json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_by_date(db: Session, report_date: date, limit: int = 200) -> list[dict[str, Any]]:
    """查询某报告日的全部消息（按时间正序）。"""
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.report_date == report_date,
               ChatMessage.is_deleted == 0)
        .order_by(ChatMessage.create_time.asc())
        .limit(limit)
    ).all()
    return [_to_dict(r) for r in rows]


def list_by_session(db: Session, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """查询某会话的全部消息（按时间正序）。"""
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id,
               ChatMessage.is_deleted == 0)
        .order_by(ChatMessage.create_time.asc())
        .limit(limit)
    ).all()
    return [_to_dict(r) for r in rows]


def _to_dict(msg: ChatMessage) -> dict[str, Any]:
    meta = None
    if msg.metadata_json:
        try:
            meta = json.loads(msg.metadata_json)
        except Exception:
            meta = {"raw": msg.metadata_json}
    return {
        "id": msg.id,
        "session_id": msg.session_id,
        "report_date": msg.report_date.isoformat() if msg.report_date else None,
        "role": msg.role,
        "content": msg.content,
        "action": msg.action,
        "clarification_id": msg.clarification_id,
        "metadata": meta,
        "created_at": msg.create_time.isoformat() if msg.create_time else None,
    }
