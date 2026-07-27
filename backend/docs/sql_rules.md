# SQL 安检规则

> **类型**：后端规格 · **读者**：后端开发者  
> **用途**：可选 **Prompt 9** 生成 INSERT 时安检；**staging/compute 直写由 Python 参数化，不经 AI**  
> **数据库**：`ai_hr_reports` · 建表脚本：[`database/schema.sql`](../../database/schema.sql)  
> 流水线：[`pipeline_spec.md`](pipeline_spec.md)

## 执行流程

```
AI 返回 sql / statements[]
    → 1. 全局禁止正则
    → 2. Prompt 8：SELECT-only + 查表白名单
    → 3. Prompt 9：INSERT|REPLACE-only + 写表白名单
    → 4. 通过才执行；失败记日志，可选 Prompt 5 通知人工
```

---

## 全局禁止（任一命中即拒绝）

```text
DROP | DELETE | TRUNCATE | ALTER | CREATE | UPDATE | GRANT | REVOKE
```

正则：`\b(DROP|DELETE|TRUNCATE|ALTER|CREATE|UPDATE|GRANT|REVOKE)\b`（不区分大小写）

---

## Prompt 8 · 仅允许 SELECT

| 规则 | 说明 |
|------|------|
| 语句开头 | 必须以 `SELECT` 开头 |
| 禁止 | `INTO OUTFILE`、`FOR UPDATE`、多语句（`;` 后第二条） |
| 参数化 | 用 `:report_date` 等占位，禁止拼接用户原始输入 |

**查表白名单**（[`schema.sql`](../../database/schema.sql) 已建）

| 表 | 用途 |
|----|------|
| `daily_reports` | 昨日基线：Row8/9/13/14/30 → `mtd_*` / `ytd_*` / `release_cum` |
| `employees` | 人员快照、Row2/3 跨日比对 |
| `employee_resignations` | 离职流程 |
| `oa_protocols` | OA 去重（`order_no` + `first_visible_date`） |
| `recruitment_pipeline` | 招聘 |
| `projects` | 项目维度 |
| `weekly_reports` · `monthly_reports` | 周报/月报基线 |

**待建**（若启用 Prompt 8 长记忆）：`ai_knowledge_base` · `holiday_calendar`

---

## Prompt 9 · 仅允许 INSERT / REPLACE

**写表白名单（compute 层 · 已建）**

`daily_reports` · `weekly_reports` · `monthly_reports`

**写表白名单（staging 层 · 已建 · Python 直写为主）**

`employees` · `employee_resignations` · `oa_protocols` · `recruitment_pipeline` · `projects`

**raw 层（待建）**

`upload_batch` · `upload_file`

**待建审计表**（可选）：`batch_run` · `daily_report_trace` · `validation_result`

> 模式 B 主路径：**Python 参数化 INSERT/REPLACE** 写 `daily_reports` 等，不调 Prompt 9。Row→列映射见 [`data_contract.md`](data_contract.md)。
