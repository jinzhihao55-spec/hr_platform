"""每个 Agent 对应的 Skill / LLM 场景白名单。

依据 docs/skills/SKILL.md「共享 reference」表：**按需提供，不把全部 Skill 给每个 Agent。**
- Agent 1（extraction）：只读「图像/Excel 解析」相关；
- Agent 2（calculation）：只读「信息与计算」相关。
"""

# 参考口径文档（reference skills，docs/skills/*.md）——供 AI/人阅读的口径上下文
AGENT_REFERENCE_SKILLS: dict[str, list[str]] = {
    "extraction": [   # Agent 1 · 图像/Excel 解析
        "SKILL_PARSE", "input_spec", "execution_modes",
        "qa_dictionary", "question_templates",
    ],
    "calculation": [  # Agent 2 · 信息与计算
        "SKILL_CALC", "daily_rows", "weekly_report", "validation",
        "output_spec", "template_mapping", "calc_log",
        "input_spec", "execution_modes", "qa_dictionary", "question_templates",
    ],
}

# LLM 场景提示词（scenario prompts，由 app/llm/scenarios.py 调用）
AGENT_SCENARIOS: dict[str, list[str]] = {
    # image_to_table：视觉模型提取图像表格（由 image_parser 直接调用，白名单确认归属）
    "extraction": ["extract_unstructured", "image_to_table"],
    "calculation": ["diagnose_error", "summarize_memory"],   # Prompt 2 排障 / Prompt 7 日志
}

# 说明：propose_sql 不属于任一 Agent（它是独立的只读查询能力，由 query_service 调用，
# 且必经 sql_guard 安检），因此不在上述任一白名单内——Agent 无法调用它。
