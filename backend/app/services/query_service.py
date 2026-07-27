"""自然语言只读查询：LLM 产出 SQL -> 安全校验（sql_guard）-> 只读执行。

关键：模型产出的 SQL 一律先过 validate_sql，绝不直接执行；非只读/危险/多语句一律拒绝。
LLM 不可用或提示词留空时，返回 available=False，不执行任何 SQL。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import HRAgentError
from app.llm.scenarios import propose_sql
from app.repositories import safe_sql


class LLMUnavailable(HRAgentError):
    code = "llm_unavailable"


def answer(db: Session, question: str, schema_hint: str = "", max_rows: int = 1000) -> dict[str, Any]:
    out = propose_sql(question, schema_hint)
    if not out.get("available"):
        raise LLMUnavailable("LLM 不可用或 propose_sql 提示词留空，未生成 SQL",
                             detail={"reason": out.get("reason")})
    sql = out.get("sql")
    # run_safe_query 内部先 validate_sql（不通过抛 SQLGuardError），再只读执行
    rows = safe_sql.run_safe_query(db, sql, max_rows=max_rows)
    return {"sql": sql, "row_count": len(rows), "rows": rows}
