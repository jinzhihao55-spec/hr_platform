"""LLM 三大应用场景。每个场景从（当前留空的）docs/skills 目录加载系统提示词；
若 skill 或 API key 不可用，函数返回结构化的"不可用"结果，流水线回退到确定性处理
（如标记 待补 / 人工确认）。

场景 skill 文件名（提示词待后续编写，放在 docs/skills/）：
  - extract_unstructured   非结构化字段提取（如 LWD 解析）
  - diagnose_error         错误诊断与解释（排障助手）
  - summarize_memory       增量经验总结（记忆回流）
  - image_to_table         图像表格识别（由 image_parser 直接调用视觉模型，此处仅作注册）
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.llm.llm_client import get_llm_client
from app.llm.skill_loader import load_skill

log = get_logger(__name__)


def _run(skill_name: str, user_content: str) -> dict[str, Any]:
    prompt = load_skill(skill_name)
    client = get_llm_client()
    if prompt is None or not client.enabled:
        return {
            "available": False,
            "reason": "skill_prompt_blank" if prompt is None else "llm_disabled",
        }
    try:
        out = client.json_chat(prompt, user_content)
        out["available"] = True
        return out
    except Exception as exc:  # pragma: no cover
        log.warning("LLM 场景 '%s' 失败: %s", skill_name, exc)
        return {"available": False, "reason": f"error:{exc}"}


def extract_unstructured_field(field: str, raw_text: str) -> dict[str, Any]:
    """场景①：非结构化字段提取（如从备注里解析 LWD）。"""
    return _run("extract_unstructured", f"FIELD={field}\nTEXT={raw_text}")


def diagnose_error(context: dict[str, Any]) -> dict[str, Any]:
    """场景②：错误诊断与解释（排障助手）。"""
    import json

    return _run("diagnose_error", json.dumps(context, ensure_ascii=False, default=str))


def summarize_memory(run_traces: list[dict[str, Any]]) -> dict[str, Any]:
    """场景③：增量经验总结（记忆回流）。"""
    import json

    return _run(
        "summarize_memory", json.dumps(run_traces, ensure_ascii=False, default=str)
    )


def propose_sql(question: str, schema_hint: str = "") -> dict[str, Any]:
    """场景④（可选）：自然语言 -> 只读 SQL。返回 {"sql": ...}。
    产出的 SQL 必须再经 app.llm.sql_guard 校验后才可执行（见 query_service）。"""
    return _run("propose_sql", f"SCHEMA={schema_hint}\nQUESTION={question}")


# 场景名 -> 函数（供 BaseAgent.run_scenario 按白名单分发）
SCENARIOS = {
    "extract_unstructured": extract_unstructured_field,
    "diagnose_error": diagnose_error,
    "summarize_memory": summarize_memory,
    "propose_sql": propose_sql,
}
