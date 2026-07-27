"""澄清事项 ORM 模型（MySQL 永久存储）。

Redis 仍作为快速缓存（14天TTL，供高频 pending 计数），
MySQL 为权威来源（永久保留、可追溯、与 chat_messages 可做真外键关联）。
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models._mixins import AuditMixin


class Clarification(Base, AuditMixin):
    """clarifications — 澄清事项表。"""

    __tablename__ = "clarifications"

    # 主键复用 Redis item_id（12位hex），确保两者可互查
    id: Mapped[str] = mapped_column(String(12), primary_key=True)

    report_date: Mapped[date] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(50), index=True)   # baseline_missing / lwd_pending / ...
    message: Mapped[str] = mapped_column(Text)                  # 展示给用户的完整问题
    ref: Mapped[str | None] = mapped_column(String(100))        # 关联业务对象（单号/工号等）
    options_json: Mapped[str | None] = mapped_column(Text)      # JSON: 建议答复选项

    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | answered
    answer: Mapped[str | None] = mapped_column(Text)            # 用户答复原文
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)      # 答复时间戳

    # 以下由 AuditMixin 提供: create_time / update_time / is_deleted
