"""每日各输入源的最近入库状态存储（Redis）。

由 ingestion_service 在入库成功后写入；由 context_service 读取以向前端
展示文件面板的"沿用昨日 / 今日上传"状态。

Redis key：hr:sources:{report_date}    Hash
字段：employees / resignations / agreements / recruitment
值：JSON {"action": "updated|reused", "rows_in_db": N,
          "rows_upserted": N, "ingested_at": "ISO 时间戳"}
TTL：7 天（工作台不会需要更久的历史）。
"""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from app.core.redis_client import get_redis

_KEY = "hr:sources:{}"
_TTL = 7 * 24 * 3600


def save(report_date: date, sources: dict[str, dict]) -> None:
    """将本次入库的 sources 字典写入 Redis。

    sources 格式（与 ingestion_service 保持一致）：
    {
        "employees":    {"action": "updated", "rows_in_db": 120, "rows_upserted": 5},
        "resignations": {"action": "reused",  "rows_in_db": 30},
        ...
    }
    """
    r = get_redis()
    key = _KEY.format(report_date.isoformat())
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    mapping = {}
    for src, info in sources.items():
        payload = {**info, "ingested_at": ts}
        mapping[src] = json.dumps(payload, ensure_ascii=False)
    r.hset(key, mapping=mapping)
    r.expire(key, _TTL)


def load(report_date: date) -> dict[str, Any]:
    """读取指定报告日的各源状态；键不存在时返回空 dict。"""
    r = get_redis()
    raw = r.hgetall(_KEY.format(report_date.isoformat()))
    return {k: json.loads(v) for k, v in raw.items()}


# ---------- MySQL 持久化（每日生成门禁以此为准，Redis 仅作展示缓存） ----------

def save_db(db, report_date: date, sources: dict[str, dict]) -> None:
    """按 (report_date, source) UPSERT 上传记录。调用方负责 commit。"""
    from sqlalchemy import select

    from app.models.inputs import SourceUploadRecord

    for src, info in sources.items():
        obj = db.scalar(
            select(SourceUploadRecord).where(
                SourceUploadRecord.report_date == report_date,
                SourceUploadRecord.source == src,
            )
        )
        if obj is None:
            obj = SourceUploadRecord(report_date=report_date, source=src)
            db.add(obj)
        obj.action = str(info.get("action") or "")
        obj.rows_upserted = info.get("rows_upserted")
    db.flush()


def load_db(db, report_date: date) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.inputs import SourceUploadRecord

    rows = db.scalars(
        select(SourceUploadRecord).where(
            SourceUploadRecord.report_date == report_date,
            SourceUploadRecord.is_deleted == 0,
        )
    ).all()
    return {
        row.source: {"action": row.action, "rows_upserted": row.rows_upserted}
        for row in rows
    }
