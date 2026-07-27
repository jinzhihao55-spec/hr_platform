"""Redis-backed 配置覆盖存储。

GET /config 读取时：constants.py 默认值 + Redis 覆盖（Redis 优先）。
PUT /config 写入时：仅保存本次提交的可变字段到 Redis。
不可变字段（formula_chain / daily_*_rows）不在此存储——由 constants.py 写死。

Redis key：hr:config        Hash，字段=配置键，值=JSON 序列化的覆盖值。
不带 TTL（配置为持久数据）。
"""
from __future__ import annotations

import json
from typing import Any

from app.core.redis_client import get_redis

_KEY = "hr:config"

# 允许通过 PUT /config 覆盖的字段（可变业务字典）
MUTABLE_FIELDS = frozenset({
    "inclusion_types",
    "exclusion_types",
    "resignation_active",
    "resignation_passive",
    "process_status_valid",
    "process_status_rejected",
    "oa_release_flow_names",
    "oa_release_flow_types",
    "business_units",
    "tenure_bu_labels",
    "bu_to_slot",
})


def get_overrides() -> dict[str, Any]:
    """读取所有已覆盖的配置项（无覆盖时返回空 dict）。"""
    r = get_redis()
    raw = r.hgetall(_KEY)
    return {k: json.loads(v) for k, v in raw.items()}


def save_overrides(updates: dict[str, Any]) -> dict[str, list[str]]:
    """将 updates 中属于 MUTABLE_FIELDS 的字段写入 Redis。

    返回: {"saved": [...], "ignored": [...]} 说明哪些字段被保存/忽略。
    """
    r = get_redis()
    saved, ignored = [], []
    for k, v in updates.items():
        if k not in MUTABLE_FIELDS:
            ignored.append(k)
            continue
        if isinstance(v, dict):
            normalized = v
        elif isinstance(v, (list, set)):
            normalized = sorted(set(v))
        else:
            normalized = v
        r.hset(_KEY, k, json.dumps(normalized, ensure_ascii=False))
        saved.append(k)
    return {"saved": saved, "ignored": ignored}


def reset(field: str | None = None) -> None:
    """重置指定字段（或全部）回 constants.py 默认值。"""
    r = get_redis()
    if field is None:
        r.delete(_KEY)
    else:
        r.hdel(_KEY, field)
