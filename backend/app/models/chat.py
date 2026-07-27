"""对话消息 ORM 模型。

每一条用户 / 助手消息均持久化到 MySQL，供历史查询与审计。
chat_messages 表也作为计算日志的补充：当用户通过对话提供澄清时，
metadata 字段记录对应的 clarification_id 和对 DB 字段的更新操作。
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin, uuid_pk


class ChatMessage(Base, AuditMixin):
    """chat_messages — 对话历史表。"""

    __tablename__ = "chat_messages"

    id: Mapped[str] = uuid_pk()

    # 会话标识（前端生成 UUID，同一报告日的一组对话共享同一 session_id）
    session_id: Mapped[str] = mapped_column(String(36), index=True)

    # 关联报告日期（允许为空，以兼容与日期无关的通用对话）
    report_date: Mapped[date | None] = mapped_column(Date, index=True)

    # 消息角色：user | assistant
    role: Mapped[str] = mapped_column(String(10))

    # 消息正文（用户输入或助手回复）
    content: Mapped[str] = mapped_column(Text)

    # 本次消息触发的动作（generate / seed_baseline / answer_clarification / info / error）
    action: Mapped[str | None] = mapped_column(String(50))

    # 若本消息是对某条澄清的答复，记录澄清 ID（对应 Redis hr:clarify:item:{id}）
    clarification_id: Mapped[str | None] = mapped_column(String(50))

    # JSON 附加数据（文件路径、更新的 DB 字段、错误详情等）
    metadata_json: Mapped[str | None] = mapped_column("metadata_json", Text)
