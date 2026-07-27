# docs/skills/

DeepSeek 系统提示词（skill prompts）目录。**与代码分离维护，按场景逐步落地。**

代码通过 `app/llm/skill_loader.load_skill(name)` 读取 `<name>.md`。
文件缺失或为空时，对应 LLM 场景视为不可用，流水线回退到确定性处理
（不臆测任何数字）。

场景 skill 文件。**每个场景按需归属对应 Agent，不向所有 Agent 开放**
（白名单见 `app/agents/skill_registry.py`，由 `BaseAgent.run_scenario` 强制）：

| 文件名 | 场景 | 归属 Agent | 用途 |
|---|---|---|---|
| `extract_unstructured.md` | 非结构化字段提取 | **Agent 1 · 解析** | ✅ 已落地；如从备注解析 LWD（OCR/字段） |
| `diagnose_error.md` | 错误诊断与解释 | **Agent 2 · 计算** | ✅ 已落地；校验硬阻断时排障（不改数字） |
| `summarize_memory.md` | 增量经验总结 | **Agent 2 · 计算** | ✅ 已落地；计算日志 / 记忆回流 |
| `propose_sql.md` | 自然语言→只读SQL | **不属任一 Agent** | ✅ 已落地；独立查询能力，由 query_service 调用，必经 sql_guard |
| `chat_assistant.md` | 使用帮助 / 口径问答 | **对话服务** | ✅ 已落地；不参与计算 |

参考口径文档（`SKILL_PARSE.md` / `daily_rows.md` 等）同样按 Agent 白名单提供：
Agent 1 只读解析相关；Agent 2 只读计算相关（见 SKILL.md「共享 reference」表）。

要求：强约束 JSON 结构化输出；不得在提示词中写入真实人事数据。
