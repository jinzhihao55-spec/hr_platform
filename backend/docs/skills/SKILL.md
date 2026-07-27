# 人事报表智能体 · 总入口（双 Agent）

> **类型**：Skill 路由 · **读者**：AI + 后端调度 · **模式**：A + B  
> 流水线：[`pipeline_spec.md`](../pipeline_spec.md) · Prompt：[`prompt_design.md`](../prompt_design.md)

## 架构

```
用户上传 Excel / 截图 / 混合
        │
        ▼
┌──────────────────────────┐
│ ★ AI 第 1 次 · Agent 1    │  Skill: SKILL_PARSE.md
│ Prompt 4 OCR / 5 提问     │  产出 → staging
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ 算 Row + trace + 校验     │  见下方「谁算 Row」
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ ★ AI 第 2 次（可选）      │  Prompt 5/7 等；**不算 Row**
│ 提问 / 计算日志           │  产出 → compute + artifact
└──────────────────────────┘
        │
        ▼
后端 openpyxl 读 compute → 导出 Excel
```

### 谁算 Row（重要）

| 模式 | 算 Row 执行者 | 说明 |
|------|---------------|------|
| **A · 对话试跑** | **Agent 2（AI）** | 读 `SKILL_CALC` + `daily_rows.md` 逐步算，快速验证口径 |
| **B · 门户生产** | **Python 规则引擎** | 读 staging + Skill 口径；**不调 AI 算数** |

### 「两次 AI」指什么

| 次序 | 内容 | 必调？ |
|------|------|--------|
| **第 1 次** | Agent 1 解析（OCR / 提问） | 有截图时必调；纯 Excel 可 0 次 AI |
| **第 2 次** | 日志 / 提问 / LWD 等（Prompt 5/7/1…） | **可选**；**不算 Row** |

**不是**：两次 AI 都算 Row；**不是** Prompt 8/9 查库落库 SQL（已退出主路径）。

---

## 选哪个 Skill

| Agent | 入口文件 | 干什么 |
|-------|----------|--------|
| **1 · 解析** | [`SKILL_PARSE.md`](SKILL_PARSE.md) | Excel/截图 → 四类结构化表 → staging |
| **2 · 计算** | [`SKILL_CALC.md`](SKILL_CALC.md) | staging → Row + trace → compute → 导出 |

后端调度：Agent 1 完成且 `ready_for_calc=true` 后才启动 Agent 2。

---

## 共享 reference（两 Agent 都可能读）

| 文件 | Agent 1 | Agent 2 |
|------|---------|---------|
| [`input_spec.md`](input_spec.md) | ✅ 字段、多源 | ✅ 纳入口径 |
| [`execution_modes.md`](execution_modes.md) | ✅ | ✅ |
| [`qa_dictionary.md`](qa_dictionary.md) | Q6 冲突 | Q1–Q16 |
| [`daily_rows.md`](daily_rows.md) | — | ✅ |
| [`validation.md`](validation.md) | — | ✅ |
| [`output_spec.md`](output_spec.md) | — | ✅ |
| [`template_mapping.md`](template_mapping.md) | — | ✅ |
| [`calc_log.md`](calc_log.md) | — | ✅ |
| [`question_templates.md`](question_templates.md) | ✅ | ✅ |

---

## 后端规格（给人，Agent 不整篇加载）

| 文件 | 内容 |
|------|------|
| [`pipeline_spec.md`](../pipeline_spec.md) | 双 Agent 流水线 + 交接 |
| [`data_contract.md`](../data_contract.md) | raw / staging / compute JSON |
| [`sql_rules.md`](../sql_rules.md) | 可选 Prompt 9 SQL 安检 |

---

## 模式 A · 对话试跑（当前）

1. **会话 1 · Agent 1**：`SKILL_PARSE.md` + 上传 → staging JSON。
2. **会话 2 · Agent 2**：`SKILL_CALC.md` + staging + 昨日日报 → **Agent 按 Skill 算 Row** + 日志 + 填充清单。

## 模式 B · 生产（未实现）

门户上传 → **AI 第 1 次** Agent 1 解析 → staging → **Python 算 Row** → 写 compute → 可选 **AI 第 2 次** Prompt 7 日志 → 导出。见 [`pipeline_spec.md`](../pipeline_spec.md)。

---

## 实现状态与后端对接（模式 B 已实现）

后端已实现**模式 B**（`backend/app/`，FastAPI + MySQL `ai_hr_reports` + Redis）：

- **两个 Agent 保持分工**：`extraction_agent`（**图像/Excel 解析**，Agent 1）、
  `calculation_agent`（**信息与计算**，Agent 2）。**Row 由 Python 规则引擎算，不调 AI。**
- **staging = 四类主表**：`employees` / `employee_resignations` / `oa_protocols` /
  `recruitment_pipeline`；**compute = 报表表**：`daily_reports` / `weekly_reports`。
- **DeepSeek 仅辅助**：OCR、LWD 解析、提问、日志、只读 SQL（经 `sql_guard` 安检）。

### 输入复用与去重（后端语义）

- 四类输入都是**数据库主表、跨天持久化**：**某类当天未重新上传 → 自动沿用库内数据**
  （如人员表每天相同可不重传）；`/ingest` 响应标注 `reused` / `updated`。
- 重新上传按唯一键 **UPSERT**：重复数据**就地更新**、不产生重复行。
- 人员表库内为空时出日报 → 阻断提问（不产出全 0 报表）。

> 口径文档（`daily_rows.md` 等）描述统一 Row 口径，模式 A/B 共用；
> 后端因 schema 适配的实现差异见 [`../data_contract.md`](../data_contract.md)。
