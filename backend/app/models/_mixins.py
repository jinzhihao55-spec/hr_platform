"""ORM 公共字段：UUID 主键、审计字段、软删。与 schema.sql 保持一致。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[str]:
    # 应用层生成 UUID，兼容 MySQL(UUID()) 与 SQLite
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class AuditMixin:
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    create_id: Mapped[str | None] = mapped_column(String(36))            # 创建人ID
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    update_id: Mapped[str | None] = mapped_column(String(36))            # 修改人ID
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)          # 软删：0=正常 1=删除
