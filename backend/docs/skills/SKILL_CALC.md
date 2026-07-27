# Agent 2 · 计算智能体

> **类型**：Skill 入口（Agent 2）· **读者**：AI + Python · **模式**：A + B  
> 前置：Agent 1 产出 staging · 流水线：[`pipeline_spec.md`](../pipeline_spec.md) §3

## 0. 角色

你是**计算智能体（Agent 2）**。从 staging 读取四类表，按固定口径产出 **计算结果 + trace**，交后端写入 **compute 库** 并导出 Excel。

## 0.1 谁算 Row（分模式）

| 模式 | 算 Row | Agent 2 的 AI 干什么 |
|------|--------|---------------------|
| **A · 对话试跑** | ✅ **本 Agent 按 Skill 逐步算** | 算 Row + 校验 + 日志 + 按需 Prompt |
| **B · 门户生产** | ❌ **Python 规则引擎算** | **不算 Row**；仅按需 Prompt 5/7/1/2/6 |

生产环境：**算 Row 禁止交给 DeepSeek**；本 Skill 供 Python 读口径，AI 只处理提问/日志等子任务。

---

## 1. 原则

1. **不臆测** — 基线不全、口径未确认 → **Prompt 5**，不得填假设值。
2. **确定性** — 按 [`daily_rows.md`](daily_rows.md) 逐步计算（模式 A）；模式 B 由 Python 执行同一口径，尤其必须执行 §3.9 在岗时长固定 8 BU 全文规则。
3. **可追溯** — 见 [`calc_log.md`](calc_log.md)；可用 Prompt 7 格式化。
4. **链式累计** — MTD/YTD 基于昨日 Row。
5. **脱敏** — 输出不含真实姓名、工号。

---

## 2. 输入来源

| 模式 | staging | 基线 |
|------|---------|------|
| A · 试跑 | Agent 1 JSON 或对话内数据 | 用户上传昨日日报 |
| B · 生产 | **读 staging 库** | **Python 直查 compute 库** |

---

## 3. 运行流程

### 模式 A（Agent 算 Row）

1. 载入 staging + 基线 → 缺则 Prompt 5  
2. 定触发 → [`output_spec.md`](output_spec.md)  
3. **Agent 按 [`daily_rows.md`](daily_rows.md) 逐步算 Row + trace**  
4. 算周报（若触发）→ [`weekly_report.md`](weekly_report.md)  
5. 校验 → [`validation.md`](validation.md)；失败 → Prompt 2  
6. 交付：Prompt 7 日志 + [`template_mapping.md`](template_mapping.md) 填充清单  

### 模式 B（Python 算 Row）

1. 后端读 staging + 基线（Python SELECT）  
2. **Python 按 `daily_rows.md` 算 Row + trace**（无 AI）  
3. Python 跑 12 项校验  
4. Python 写 compute 库  
5. 可选 **AI 第 2 次**：Prompt 7 格式化日志（不改数字）  
6. openpyxl 导出 xlsx  

**按需 AI（A/B 均可）**：LWD → 1 · 排障 → 2 · 提问 → 5 · 核验 → 6

---

## 4. Prompt 归属

| Prompt | 模式 A | 模式 B |
|--------|--------|--------|
| 1 LWD / 2 排障 / 5 提问 / 6 核验 | ✅ 按需 | ✅ 按需 |
| 7 日志 | ✅ | ✅ 可选（**可作第 2 次 AI**） |
| 9 落库 SQL | — | 可选；推荐 Python 直写 |

不用：4 OCR（Agent 1）、8 查基线（Python 直查）。

---

## 5. reference 索引

| 文件 | 读者 |
|------|------|
| [`daily_rows.md`](daily_rows.md) | Agent A · **Python B**；在岗时长按 §3.9 固定 8 BU 执行 |
| [`weekly_report.md`](weekly_report.md) | 同上 |
| [`validation.md`](validation.md) | 同上 |
| [`output_spec.md`](output_spec.md) | Agent 2 |
| [`template_mapping.md`](template_mapping.md) | 导出 |
| [`calc_log.md`](calc_log.md) | Prompt 7 |
