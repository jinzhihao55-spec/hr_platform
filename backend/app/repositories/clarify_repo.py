"""澄清事项存储 — MySQL（权威）+ Redis（快速缓存）双写。

MySQL：永久保存，供历史查询、与 chat_messages 关联、审计。
Redis：14天TTL，供高频 pending 计数与实时列表（避免每次查库）。

所有写操作（add / answer）同时写入两端。
读操作优先走 MySQL（当 db 可用时），Redis 作为备用。
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.models.clarification import Clarification

# Redis key 模板（保持向后兼容）
_SET = "hr:clarify:{}"
_ITEM = "hr:clarify:item:{}"
_TTL = 14 * 24 * 3600


# ─────────────────────────────────────────────────────────────
# 写操作
# ─────────────────────────────────────────────────────────────

def add(
    report_date: date,
    code: str,
    message: str,
    ref: str | None = None,
    options: list[str] | None = None,
    db: Session | None = None,
) -> str:
    """创建澄清事项，同时写入 MySQL 和 Redis。返回 item_id。"""
    item_id = uuid.uuid4().hex[:12]
    options_json = json.dumps(options or [], ensure_ascii=False)

    # ── MySQL（权威存储）──────────────────────────────────────
    if db is not None:
        obj = Clarification(
            id=item_id,
            report_date=report_date,
            code=code,
            message=message,
            ref=ref,
            options_json=options_json,
            status="pending",
        )
        db.add(obj)
        db.commit()

    # ── Redis（快速缓存）──────────────────────────────────────
    r = get_redis()
    r.hset(_ITEM.format(item_id), mapping={
        "id": item_id,
        "report_date": report_date.isoformat(),
        "code": code,
        "message": message,
        "ref": ref or "",
        "options": options_json,
        "status": "pending",
        "answer": "",
        "created": str(time.time()),
    })
    r.expire(_ITEM.format(item_id), _TTL)
    r.zadd(_SET.format(report_date.isoformat()), {item_id: time.time()})
    r.expire(_SET.format(report_date.isoformat()), _TTL)

    return item_id


def answer(
    item_id: str,
    ans: str,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """记录用户答复，同时更新 MySQL 和 Redis。"""
    answered_at = datetime.utcnow()

    # ── MySQL ─────────────────────────────────────────────────
    if db is not None:
        obj = db.scalar(select(Clarification).where(Clarification.id == item_id))
        if obj is not None:
            obj.status = "answered"
            obj.answer = ans
            obj.answered_at = answered_at
            db.commit()

    # ── Redis ─────────────────────────────────────────────────
    r = get_redis()
    key = _ITEM.format(item_id)
    if not r.exists(key):
        # Redis 已过期但 MySQL 仍有记录时，重新推入 Redis
        if db is not None:
            obj = db.scalar(select(Clarification).where(Clarification.id == item_id))
            if obj is None:
                return None
            r.hset(key, mapping=_obj_to_redis(obj))
            r.expire(key, _TTL)
        else:
            return None

    r.hset(key, mapping={
        "status": "answered",
        "answer": ans,
        "answered_at": str(time.time()),
    })

    d = r.hgetall(key)
    d["options"] = json.loads(d.get("options") or "[]")
    return d


# ─────────────────────────────────────────────────────────────
# 读操作（MySQL 优先，回退 Redis）
# ─────────────────────────────────────────────────────────────

def list_pending(report_date: date, db: Session | None = None) -> list[dict[str, Any]]:
    if db is not None:
        rows = db.scalars(
            select(Clarification)
            .where(Clarification.report_date == report_date,
                   Clarification.status == "pending",
                   Clarification.is_deleted == 0)
            .order_by(Clarification.create_time.asc())
        ).all()
        return [_obj_to_dict(r) for r in rows]
    # Redis 回退
    return [i for i in _redis_list(report_date) if i.get("status") == "pending"]


def list_all(report_date: date, db: Session | None = None) -> list[dict[str, Any]]:
    if db is not None:
        rows = db.scalars(
            select(Clarification)
            .where(Clarification.report_date == report_date,
                   Clarification.is_deleted == 0)
            .order_by(Clarification.create_time.asc())
        ).all()
        return [_obj_to_dict(r) for r in rows]
    return _redis_list(report_date)


def count_pending(report_date: date, db: Session | None = None) -> int:
    return len(list_pending(report_date, db=db))


# ─────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────

def _redis_list(report_date: date) -> list[dict[str, Any]]:
    r = get_redis()
    ids = r.zrange(_SET.format(report_date.isoformat()), 0, -1)
    out = []
    for jid in ids:
        d = r.hgetall(_ITEM.format(jid))
        if d:
            d["options"] = json.loads(d.get("options") or "[]")
            out.append(d)
    return out


def _obj_to_dict(obj: Clarification) -> dict[str, Any]:
    return {
        "id": obj.id,
        "report_date": obj.report_date.isoformat() if obj.report_date else None,
        "code": obj.code,
        "message": obj.message,
        "ref": obj.ref or "",
        "options": json.loads(obj.options_json or "[]"),
        "status": obj.status,
        "answer": obj.answer or "",
        "answered_at": obj.answered_at.isoformat() if obj.answered_at else None,
        "created": obj.create_time.isoformat() if obj.create_time else None,
    }


def _obj_to_redis(obj: Clarification) -> dict:
    return {
        "id": obj.id,
        "report_date": obj.report_date.isoformat() if obj.report_date else "",
        "code": obj.code,
        "message": obj.message,
        "ref": obj.ref or "",
        "options": obj.options_json or "[]",
        "status": obj.status,
        "answer": obj.answer or "",
        "answered_at": str(obj.answered_at.timestamp()) if obj.answered_at else "",
        "created": str(obj.create_time.timestamp()) if obj.create_time else "",
    }
