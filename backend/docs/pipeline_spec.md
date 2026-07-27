# 生产流水线规格（模式 B · 双 Agent）

> **类型**：后端规格 · **读者**：后端开发者 · **模式**：B（未实现）  
> **算 Row：Python 规则引擎（不是 AI）** · **两次 AI：解析 + 可选日志/提问**

---

## 0. 与门户方案对照 + 算 Row 策略

| 她说的 / 场景 | 本方案 | 执行者 |
|---------------|--------|--------|
| **两次给 AI** | 第 1 次解析 + 第 2 次可选（日志/提问） | 见 §0.1 |
| **一次访问查询/解析** | Agent 1 · OCR + 合并 + staging | AI + Python |
| **统计** | **Python 算 Row** | **不是 AI** |
| **录入数据库** | Python 写 staging → compute | Python 直写为主 |
| **导出（有模版）** | openpyxl 读 compute | Python |

### 0.1 「两次 AI」定义（模式 B）

| 次序 | 内容 | 必调？ | Prompt |
|------|------|--------|--------|
| **第 1 次** | 输入解析（截图 OCR、缺字段提问） | 有截图时必调；纯 Excel 可 0 次 | 4、5 |
| **第 2 次** | 计算日志 / 提问 / LWD 等 | **可选**；整批可 0 次 | 7、5、1… |

**两次 AI 都不算 Row。** Row 由 Python 在两次 AI 之间执行。

### 0.2 与模式 A 试跑的区别

| | 模式 A | 模式 B |
|--|--------|--------|
| 算 Row | Agent 2（AI） | **Python** |
| 用途 | 验证 Skill 口径 | 生产交付 |

---

## 1. 总览

```
上传 Excel / 截图 / 混合
        │
        ▼
[后端] 写 raw 层                                         无 AI
        │
        ▼
★ AI 第 1 次 · Agent 1（Prompt 4/5）→ 写 staging         有截图则必调 AI
        │
        ▼
[后端] Python 算 Row + trace + 校验 → 写 compute        ★ 无 AI
        │
        ▼
★ AI 第 2 次（可选）Prompt 7 日志 / 5 提问 / 1 LWD     不算 Row
        │
        ▼
[后端] openpyxl 读 compute → xlsx                       无 AI
        │
        ▼
前端下载
```

---

## 2. Agent 1 · 输入解析（后端 ↔ AI 交接）

### 2.1 后端先做什么（不调 AI）

| 动作 | 产出 |
|------|------|
| 接收上传，生成 `batch_id`、`report_date` | `RawUpload` |
| 文件存盘/对象存储，写 **raw 层** | *待建* `upload_batch`, `upload_file`（当前：文件系统/OSS + `batch_id`） |
| 判断本批有哪些源：excel / image / mixed | `parse_plan` |

### 2.2 给 AI 什么 · AI 回什么（有截图时）

**调用**：Prompt 4 · OCR（每个 screenshot 一次，或批量）

| | 内容 |
|--|------|
| **后端→AI · system** | Prompt 4 正文 |
| **后端→AI · user** | `{ "report_date", "source_type": "oa_release|recruitment", "image_ref", "paired_excel": {...} }` |
| **AI→后端** | `{ "status", "confidence", "columns", "rows", "uncertain_cells", "missing_key_columns" }` |

**后端拿到后**：合并进内存中的四类表草稿；**不执行 SQL**。

### 2.3 后端再做什么（可无 AI）

| 动作 | 说明 |
|------|------|
| pandas 读 Excel（若有） | 人员/离职必须 Excel 或有等效结构化行 |
| 合并 Excel + OCR | Q6：Excel 优先，冲突写 `merge_conflicts` |
| 字段校验 | 对照 `input_spec.md` ★ 字段 |
| 低置信 / 缺字段 | 调 **Prompt 5** → `blocking=true` 则停 |
| 写 **staging 库** | `employees` / `employee_resignations` / `oa_protocols` / `recruitment_pipeline` |
| **复用/去重** | 某类未上传 → 不动该表，**沿用库内数据**；上传则按唯一键 **UPSERT** 就地更新，不产生重复行 |
| 更新 batch 状态 | `parse_status=ready` 或 `blocked` |

### 2.4 Agent 1 产出（交给 Agent 2 的接口）

```json
{
  "batch_id": "batch_20260624_001",
  "ready_for_calc": true,
  "staging_ref": "staging/batch_20260624_001"
}
```

`ready_for_calc=false` → **不启动 Agent 2**。

---

## 3. Agent 2 · 计算（后端 ↔ AI 交接）

### 3.1 后端先做什么（**算 Row · 无 AI**）

| 动作 | 说明 |
|------|------|
| 读 **staging 库** | 四类业务表（见 [`data_contract.md`](data_contract.md)） |
| Python SELECT **`daily_reports`** 昨日基线 | 不用 Prompt 8 |
| **`daily_rows.md` 算 Row2–40** | **Python 规则引擎，不是 DeepSeek** |
| 写 trace、跑 12 项校验 | `passed=false` 不写 compute 终态 |
| 写 **compute 库** | Python 直写 `daily_reports`（+ trace/validation 日志） |

### 3.2 给 AI 什么 · AI 回什么（**可选 · 不算 Row**）

| Prompt | 何时 | 后端→AI user | AI→后端 |
|--------|------|--------------|---------|
| **5** | 缺基线/歧义 | `issues[]` | `questions[]`, `blocking` |
| **1** | LWD 模糊 | 单行 OA JSON | `{ lwd, confidence }` |
| **2** | 校验失败 | `failures[]` | 排查建议 JSON |
| **7** | 算完且校验过（**可作第 2 次 AI**） | `daily_rows`, `row_traces` | `calc_log_md` |

**算 Row 本身不调 AI。** 模式 A 试跑时由 Cursor Agent 算 Row，不走本流水线。

### 3.3 导出（无 AI）

openpyxl 读 **compute 库** 填模板 → xlsx；日志 md 路径写入 artifact。

## 4. 多步入库顺序

```
① raw       上传完成即写
② staging   Agent 1 解析完成写（四类结构化行）
③ compute   **Python 算 Row** + 校验通过写（Row + trace + validation）
④ artifact  导出 xlsx / 日志 md 后写路径
```

同一 `batch_id` 串联全链路。

---

## 5. 速查：谁干什么

| 步骤 | 后端 | AI | 入库层 |
|------|------|-----|--------|
| 上传 | 存文件、写 raw | — | raw |
| OCR | 组 user、调 API、合并结果 | Prompt 4 出 rows | — |
| 解析合并 | pandas、质检、写库 | Prompt 5（若阻断） | **staging** |
| 读 staging | 读库 | — | 读 staging |
| 查基线 | SQL 直查 compute | — | 读 compute |
| 算 Row | **Python** | — | — |
| 写 compute | Python 直写 | Prompt 7（可选，**第 2 次 AI**） | **compute** |
| 导出 | openpyxl | — | **artifact** |
| 日志 | 存 md | Prompt 7（可选） | artifact |

---

## 6. Prompt 8 说明

原 Prompt 8（AI 生成 SELECT 查基线）在双 Agent + 分层入库方案下 **由 Python 直查 compute 库替代**。  
Prompt 8 正文保留于 `prompt_design.md` 供参考，**新模式 B 主路径不调用**。

Prompt 9 仍 **可选**：表结构稳定时建议 **Python 直写 compute**，不调 AI。

---

## 7. 实现顺序

1. raw（文件/OSS）+ Agent 1 写四类业务表（Excel + OCR）  
2. Python 读四类表算 Row（0 次 AI 也可跑通）  
3. 写 `daily_reports` + trace  
4. openpyxl 导出  
5. 门户对接 + 可选 Prompt 7/9  
