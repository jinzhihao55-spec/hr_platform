# 运行模式说明

> **类型**：Skill · **读者**：AI + 人 · **模式**：A + B  
> 总入口：[`SKILL.md`](SKILL.md)

---

## 核心分工（已定）

| 场景 | 算 Row | DeepSeek API 用在哪 |
|------|--------|---------------------|
| **A · Cursor 试跑** | ✅ **Agent 2 算** | Agent 1 OCR；Agent 2 算数+日志 |
| **B · 门户生产** | ✅ **Python 算** | Agent 1 OCR；**第 2 次 AI 仅日志/提问**，不算 Row |
| **截图 + 多源** | Python（B）/ Agent（A） | **AI 在 Agent 1 解析** |
| **「两次 AI」** | ❌ 不算 Row | **第 1 次解析 + 第 2 次可选日志/提问** |

---

## 模式 A · 对话试跑（当前）

| 步骤 | 执行者 | 说明 |
|------|--------|------|
| 上传 | 用户 | Excel / 截图 / 混合 |
| 会话 1 · Agent 1 | AI · [`SKILL_PARSE.md`](SKILL_PARSE.md) | Prompt 4/5 → staging JSON |
| 会话 2 · Agent 2 | AI · [`SKILL_CALC.md`](SKILL_CALC.md) | **Agent 算 Row** + trace + 日志 |
| 入库 | 可选 | 可不连 MySQL |
| 交付 | Agent 2 | 计算日志 + 填充清单 |

---

## 模式 B · 生产（未实现）

| 步骤 | 执行者 | 说明 |
|------|--------|------|
| 上传 | 门户 | → raw 层 |
| **AI 第 1 次** | Agent 1 | Prompt 4 OCR → **写 staging** |
| 算 Row | **Python** | 读 staging + 基线；**不调 AI** |
| 校验 + 写库 | Python | → compute 层 |
| **AI 第 2 次（可选）** | Prompt 7 / 5 / 1… | 日志、提问；**不算 Row** |
| 导出 | openpyxl | 读 compute → xlsx |

详见 [`pipeline_spec.md`](../pipeline_spec.md)。

---

## 模式选择

```
未说明 → 模式 A
门户跑跑 / 连库 → 模式 B
```

两模式共享：**同一 Row 口径（daily_rows.md）**；差异在 **谁执行算 Row、AI 调用次数**。
