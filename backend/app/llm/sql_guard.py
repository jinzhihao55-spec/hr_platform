"""SQL 安全校验（针对 LLM 等模型产出的 SQL）。

最高原则：模型产出的 SQL 一律视为不可信，执行前必须通过本校验。
默认仅允许只读查询（SELECT / WITH），阻断一切写/改/删/结构变更/多语句注入。

使用：
    from app.llm.sql_guard import validate_sql
    safe = validate_sql(model_sql)          # 通过则返回清洗后的单条只读SQL
                                            # 不通过抛 SQLGuardError（流水线停下，不执行）
"""
from __future__ import annotations

import re

from app.core.exceptions import SQLGuardError

# 允许的起始关键字（只读）
_ALLOWED_START = {"SELECT", "WITH"}

# 禁止出现的关键字（写/改/删/结构变更/权限/系统/文件等）
_FORBIDDEN = {
    "DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE", "INSERT", "REPLACE",
    "CREATE", "RENAME", "MERGE", "UPSERT", "GRANT", "REVOKE", "CALL", "EXEC",
    "EXECUTE", "ATTACH", "DETACH", "LOAD", "SET", "USE", "SHUTDOWN", "KILL",
    "LOCK", "UNLOCK", "HANDLER", "PREPARE", "DEALLOCATE", "COMMIT", "ROLLBACK",
    "SAVEPOINT", "VACUUM", "PRAGMA", "COPY", "DO", "DECLARE",
}

# 危险片段（文件落地 / 注入常见手法）
_DANGER_PATTERNS = [
    re.compile(r"\bINTO\s+OUTFILE\b", re.I),
    re.compile(r"\bINTO\s+DUMPFILE\b", re.I),
    re.compile(r"\bLOAD_FILE\s*\(", re.I),
    re.compile(r"\bBENCHMARK\s*\(", re.I),
    re.compile(r"\bSLEEP\s*\(", re.I),
]

# 允许查询的业务表（对齐 database/schema.sql 中面向报表/自然语言查询的主表）。
# 之前本文件只做"禁止关键字"黑名单，没有任何表范围限制：只要 SQL 是
# SELECT/WITH 且不含被禁关键字，就能读取该数据库账号能看到的任意表
# （information_schema / mysql / performance_schema / sys，或本应用内部表
# 如 chat_messages），属于越权数据探测面。这里补一个白名单，配合下面的
# _check_table_allowlist 强制生效。
_ALLOWED_TABLES = {
    "employees", "employee_resignations", "oa_protocols",
    "recruitment_pipeline", "daily_reports", "weekly_reports",
    "monthly_reports", "projects",
}

_WORD = re.compile(r"[A-Za-z_]+")


def _strip_comments(sql: str) -> str:
    # markdown 代码围栏 ```sql ... ```
    sql = re.sub(r"```[a-zA-Z]*", " ", sql).replace("```", " ")
    # 块注释 /* ... */
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    # 行注释 -- ... 与 # ...
    out_lines = []
    for line in sql.splitlines():
        line = re.sub(r"--.*$", "", line)
        line = re.sub(r"#.*$", "", line)
        out_lines.append(line)
    return " ".join(out_lines)


def validate_sql(sql: str, *, allow_start: set[str] | None = None) -> str:
    """校验并返回清洗后的单条只读 SQL；不通过抛 SQLGuardError。

    allow_start：默认 {'SELECT','WITH'}，仅允许只读查询。
    """
    if not sql or not isinstance(sql, str) or not sql.strip():
        raise SQLGuardError("SQL 为空")

    cleaned = _strip_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise SQLGuardError("去除注释后 SQL 为空")

    # 多语句注入：去掉注释后不得再含分号
    if ";" in cleaned:
        raise SQLGuardError("检测到多条语句（疑似注入），仅允许单条只读查询",
                            detail={"sql": cleaned})

    # 危险片段
    for pat in _DANGER_PATTERNS:
        if pat.search(cleaned):
            raise SQLGuardError(f"检测到危险片段：{pat.pattern}", detail={"sql": cleaned})

    # 起始关键字必须是只读
    allow = {k.upper() for k in (allow_start or _ALLOWED_START)}
    first = _WORD.search(cleaned)
    start_kw = first.group(0).upper() if first else ""
    if start_kw not in allow:
        raise SQLGuardError(
            f"仅允许只读查询（{'/'.join(sorted(allow))}），实际起始为 {start_kw or '未知'}",
            detail={"sql": cleaned},
        )

    # 禁止关键字（整词匹配）
    tokens = {t.upper() for t in _WORD.findall(cleaned)}
    hit = tokens & _FORBIDDEN
    if hit:
        raise SQLGuardError(f"检测到禁止的关键字：{sorted(hit)}", detail={"sql": cleaned})

    # 语法解析（确认 SQL 合法且为单条）+ 表范围白名单校验。
    # 这两项都依赖 sqlglot 的真实 AST 解析——正则/子串匹配很容易被别名、
    # 子查询、反引号等绕过。之前 sqlglot 缺失时会静默跳过语法检查，"关键字
    # 黑名单仍生效"聊胜于无；但没有 sqlglot 就完全没法做表范围校验，
    # 因此这里改为 fail-closed：sqlglot 不可用时直接拒绝，而不是放行。
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as exc:
        raise SQLGuardError(
            "SQL 安全校验依赖 sqlglot（表范围白名单/语法解析），但未安装，"
            "出于安全考虑拒绝执行；请安装 sqlglot>=25.0",
            detail={"sql": cleaned},
        ) from exc

    try:
        stmts = sqlglot.parse(cleaned, read="mysql")
        non_empty = [s for s in stmts if s is not None]
        if len(non_empty) != 1:
            raise SQLGuardError("SQL 必须为单条语句", detail={"sql": cleaned})
        parsed = non_empty[0]
    except SQLGuardError:
        raise
    except Exception as exc:
        raise SQLGuardError(f"SQL 语法非法：{exc}", detail={"sql": cleaned}) from exc

    tables = {t.name.lower() for t in parsed.find_all(exp.Table) if t.name}
    disallowed = tables - _ALLOWED_TABLES
    if disallowed:
        raise SQLGuardError(
            f"检测到未授权访问的表：{sorted(disallowed)}"
            f"（仅允许查询：{sorted(_ALLOWED_TABLES)}）",
            detail={"sql": cleaned, "tables": sorted(tables)},
        )

    return cleaned


def is_safe_sql(sql: str) -> bool:
    """便捷布尔判断（不抛异常）。"""
    try:
        validate_sql(sql)
        return True
    except SQLGuardError:
        return False
