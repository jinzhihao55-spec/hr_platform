"""Redis 客户端。用于：任务状态、运行级缓存、去重快照，以及跨运行的轻量去重/锁。"""
from __future__ import annotations

import redis

from app.config import settings

_pool: redis.ConnectionPool | None = None


def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.redis_url, decode_responses=True
        )
    return redis.Redis(connection_pool=_pool)
