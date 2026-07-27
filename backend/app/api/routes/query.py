from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.exceptions import HRAgentError

from app.core.database import get_db
from app.schemas.api import QueryRequest, QueryResponse
from app.services import query_service
from app.services.query_service import LLMUnavailable

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
def nl_query(req: QueryRequest, db: Session = Depends(get_db)):
    """自然语言 -> LLM 生成只读 SQL -> 安全校验 -> 执行并返回行。

    - 200：成功，返回所用 SQL 与结果行
    - 409：模型 SQL 未过安全校验（SQLGuardError，由全局处理器返回）
    - 503：LLM 不可用 / propose_sql 提示词留空
    """
    try:
        return query_service.answer(db, req.question, req.schema_hint, req.max_rows)
    except LLMUnavailable as exc:
        raise HTTPException(503, exc.message)
    except HRAgentError as exc:
        raise HTTPException(422, exc.message)
    except Exception as exc:
        raise HTTPException(500, f"查询失败: {exc}")
