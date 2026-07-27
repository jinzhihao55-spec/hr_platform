"""只读执行经安全校验的 SQL。任何模型产出的 SQL 都必须经此入口，
先 validate_sql 再执行，并强制行数上限，杜绝写/改/删与超大结果集。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.llm.sql_guard import validate_sql

_DEFAULT_MAX_ROWS = 1000


def run_safe_query(db: Session, sql: str, *, max_rows: int = _DEFAULT_MAX_ROWS) -> list[dict[str, Any]]:
    """校验为只读单语句后执行；无 LIMIT 时自动加上限。返回行字典列表。"""
    safe = validate_sql(sql)  # 不通过会抛 SQLGuardError，调用方据此停下/提问
    if not _has_outer_limit(safe):
        safe = f"{safe} LIMIT {int(max_rows)}"
    rows = db.execute(text(safe)).mappings().all()
    return [dict(r) for r in rows]


def _has_outer_limit(sql: str) -> bool:
    """判断整条 SQL 最外层是否已带 LIMIT。

    之前用 `"limit" not in safe.lower()` 做子串匹配：只要子查询/CTE 里含
    LIMIT，或列名/别名恰好含 "limit"（如 credit_limit），就会误判为"已有
    LIMIT"而跳过行数上限的自动追加，等同于放行无界结果集——这正是本函数存在
    的目的所以必须修。改为用 sqlglot 解析出最外层语句的 AST，直接检查其
    `limit` 子句是否存在；sqlglot 不可用/解析失败时回退到更保守的正则
    （只认整句末尾的 `LIMIT <n>`，不会被子查询里的 LIMIT 或普通标识符误触发）。
    """
    try:
        import sqlglot

        parsed = sqlglot.parse_one(sql, read="mysql")
        return parsed is not None and parsed.args.get("limit") is not None
    except Exception:
        return bool(re.search(r"\blimit\s+\d+\s*(,\s*\d+\s*)?$", sql.strip(), re.IGNORECASE))
