"""基于 Redis 的任务状态存储（替代 MySQL 表）。

数据结构：
  - hr:job:{id}      Hash，存单个任务字段
  - hr:jobs          Sorted Set，score=创建时间(epoch)，member=job_id，用于倒序列表
任务带 TTL（默认 7 天）自动过期，避免堆积。"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime
from typing import Any

from app.core.redis_client import get_redis

_JOB_KEY = "hr:job:{}"
_INDEX_KEY = "hr:jobs"
_TTL_SECONDS = 7 * 24 * 3600


def create(kind: str, report_date: date | None = None) -> str:
    r = get_redis()
    job_id = uuid.uuid4().hex
    now = time.time()
    mapping = {
        "id": job_id,
        "kind": kind,
        "status": "pending",
        "report_date": report_date.isoformat() if report_date else "",
        "message": "",
        "result": "",
        "create_time": datetime.now().isoformat(timespec="seconds"),
        "update_time": datetime.now().isoformat(timespec="seconds"),
    }
    key = _JOB_KEY.format(job_id)
    r.hset(key, mapping=mapping)
    r.expire(key, _TTL_SECONDS)
    r.zadd(_INDEX_KEY, {job_id: now})
    return job_id


def update(
    job_id: str,
    *,
    status: str | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    r = get_redis()
    key = _JOB_KEY.format(job_id)
    fields: dict[str, str] = {"update_time": datetime.now().isoformat(timespec="seconds")}
    if status is not None:
        fields["status"] = status
    if message is not None:
        fields["message"] = message
    if result is not None:
        fields["result"] = json.dumps(result, ensure_ascii=False, default=str)
    r.hset(key, mapping=fields)
    r.expire(key, _TTL_SECONDS)


def _hydrate(data: dict[str, str]) -> dict[str, Any]:
    if not data:
        return {}
    result = data.get("result") or ""
    return {
        "job_id": data.get("id"),
        "kind": data.get("kind"),
        "status": data.get("status"),
        "report_date": data.get("report_date") or None,
        "message": data.get("message") or None,
        "result": json.loads(result) if result else None,
    }


def get(job_id: str) -> dict[str, Any] | None:
    data = get_redis().hgetall(_JOB_KEY.format(job_id))
    return _hydrate(data) if data else None


def list_recent(limit: int = 50) -> list[dict[str, Any]]:
    r = get_redis()
    ids = r.zrevrange(_INDEX_KEY, 0, limit - 1)
    out = []
    for jid in ids:
        data = r.hgetall(_JOB_KEY.format(jid))
        if data:
            out.append(_hydrate(data))
    return out
