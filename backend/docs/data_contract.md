# 数据契约（JSON）

> **类型**：后端规格 · **读者**：后端开发者  
> 流水线：[`pipeline_spec.md`](pipeline_spec.md) · 双 Agent：[`skills/SKILL.md`](skills/SKILL.md)

## 四层入库 + 契约对照

> **数据库**：`ai_hr_reports`（见 [`database/schema.sql`](../../database/schema.sql)）  
> **主键**：`CHAR(36) UUID` · **软删**：`is_deleted`

| 层 | 契约 JSON 键 | MySQL 表 | 产出者 | 消费者 |
|----|-------------|----------|--------|--------|
| **raw** | §1 `RawUpload` | *（待建）* `upload_batch` / `upload_file`；文件存盘/OSS | 门户/后端 | Agent 1 |
| **staging** | §2 `StagingPayload.tables.*` | `employees` · `employee_snapshots` · `employee_resignations` · `oa_protocols` · `recruitment_pipeline` | **Agent 1** | Agent 2 / Python |
| **master** | — | `projects` | 人工/导入 | `employees.project_code` FK |
| **compute** | §4 `ComputePayload` | `daily_reports` · `weekly_reports` · `monthly_reports` | **Python（B）** / Agent（A 试跑） | 导出、基线、Prompt 7 |
| **artifact** | §6 `Artifacts` | 文件路径（无独立表） | openpyxl | 用户下载 |

### JSON 表键 → MySQL 表

| `StagingPayload.tables` 键 | MySQL 表 | 说明 |
|---------------------------|----------|------|
| `personnel` | `employees` | 人员主表 |
| `personnel` | `employee_snapshots` | 同次上传按 `report_date + employee_no` 保存的周报历史快照 |
| `resignation` | `employee_resignations` | 离职流程；`employee_no` FK → `employees` |
| `oa_release` | `oa_protocols` | OA 协议/离职审批 |
| `recruitment` | `recruitment_pipeline` | 招聘漏斗；按 `report_date` 区分批次 |

### Row → `daily_reports` 列（算 Row 仍用 Row 编号；落库映射如下）

| Row | 输出项 | `daily_reports` 列 |
|-----|--------|-------------------|
| 2 | 今日入职 | `daily_onboard` |
| 3 | 今日离职 | `daily_resign` |
| 7 | 今日净增 | `daily_employee_change` |
| 8 | MTD 入职 | `mtd_onboard` |
| 9 | MTD 离职 | `mtd_resign` |
| 10 | MTD 转正 | `mtd_transfer` |
| 11 | MTD 微软调整 | `mtd_project_change` |
| 12 | MTD 净增减 | `mtd_employee_change` |
| 13 | YTD 入职 | `ytd_onboard` |
| 14 | YTD 离职 | `ytd_resign` |
| 15 | YTD 转正 | `ytd_transfer` |
| 16 | YTD 微软调整 | `ytd_project_change` |
| 17 | YTD 净增减 | `ytd_employee_change` |
| 18 | 本月预估入职 | `predicted_onboard` |
| 19 | 本月预估离职 | `predicted_resign` |
| 38 | 预计入职（本月 offer） | `expected_onboard_offer` |
| 39 | 预计入职（上月 offer） | `expected_onboard_prev` |
| 30 相关 | Release 累计等 | `release_today` · `release_cum` · `release_pending_total` · `expected_resign_cum` |

Row 4–6、20–22、25–29、31–37、40 等：**算 Row / 导出 xlsx 仍产出**；当前 schema **无对应列**，不入 `daily_reports`（空白行 23/24/27/28/34/35 同样不入库）。`bi_ytd_resign_rate` 为 BI 口径字段，非 Row 编号。

### 输入字段 → 列（Agent 1 写 staging 时映射）

**`employees`**（① 人员）

| 输入字段 | 列 |
|----------|-----|
| 工号 | `employee_no` |
| 中文名 / 英文名 / Alias | `name` / `english_name` / `alias` |
| 员工类型 | `employee_type` |
| 员工状态 | `status`（active / resigned / transferred） |
| 入职日期 / 离职日期 | `entry_date` / `resign_date` |
| 事业部 / 编号 | `bu` / `bu_code` |
| 部门 / 编号 | `department` / `department_code` |
| 项目编号 | `project_code` |
| 职位 / 职级 / 汇报人 | `position` / `job_level` / `report_to` |
| 试用期 / 实习生合同 | `probation_*` / `intern_contract_*` |
| 合同公司 | `contract_company` |

**`employee_resignations`**（② 离职）

| 输入字段 | 列 |
|----------|-----|
| 流程单号 | `process_no` |
| 流程状态 / 节点 | `process_status` / `node_name` |
| 工号 | `employee_no` |
| 离职方式 / LWD | `resign_type` / `resign_date` |
| 申请时间相关 | `first_visible_date` · `release_notice_date` |

**`oa_protocols`**（③ OA）

| 输入字段 | 列 |
|----------|-----|
| 单号 | `order_no` |
| 任务号 | `task_no` |
| 流程标题 / 类型 | `title` / `process_type` |
| 申请时间 | `initiate_time` |
| 当前状态 | `current_status` |
| 关联员工 | `related_employee` / `related_name` |
| 首次可见 | `first_visible_date` |
| Row5/Row30 标志 | `row5_flag` / `row30_flag` |

**`recruitment_pipeline`**（④ 招聘）

| 输入字段 | 列 |
|----------|-----|
| 招聘专员 | `recruiter` |
| 本月/待入职等 | `onboard_m` · `expected_onboard_m` · `expected_onboard_m_prev` · `month_offers` 等 |
| 数据日期 | `report_date` |

### 基线查询（模式 B · 替代 Prompt 8）

昨日基线 Row8/9/13/14/30 → 查 **`daily_reports`**：

```sql
SELECT mtd_onboard, mtd_resign, ytd_onboard, ytd_resign, release_cum
FROM daily_reports
WHERE report_date = :baseline_date;
```

OA 去重：查 **`oa_protocols.first_visible_date`**（无独立 `consumed_oa_ids` 表）。日报事实查 **`employees`** 的 `entry_date` / `resign_date` / `status`；周报窗口末在职查 **`employee_snapshots`** 的对应 `report_date`。

### 尚未建表（raw / 辅助）

| 表（规划） | 用途 | 当前替代 |
|-----------|------|----------|
| `upload_batch` / `upload_file` | 上传批次与文件元数据 | 文件系统/OSS + 内存 `batch_id` |
| `ai_knowledge_base` | Prompt 长记忆 | 暂无 |
| `holiday_calendar` | Q14 周报窗口 | 暂无 |
| `batch_run` / `daily_report_trace` / `validation_result` | 跑批审计 | 应用层日志文件 |

---

## 1. 原始层 `RawUpload`

```json
{
  "batch_id": "batch_20260624_001",
  "report_date": "2026-06-24",
  "files": [
    {"name": "人员表.xlsx", "type": "excel", "source_table": "personnel"},
    {"name": "OA截图.png", "type": "image", "source_table": "oa_release"}
  ],
  "uploaded_at": "2026-06-24T09:00:00Z"
}
```

---

## 2. 解析层 `StagingPayload`（Agent 1 产出 → 写 staging）

```json
{
  "batch_id": "batch_20260624_001",
  "report_date": "2026-06-24",
  "agent": "parse",
  "tables": {
    "personnel": {
      "source": "ocr",
      "confidence": "medium",
      "human_confirmed": false,
      "row_count": 25,
      "rows": [{"员工类型": "正式员工", "工号": "E001", "入职日期": "2026-06-24"}]
    },
    "resignation": {"source": "excel", "confidence": "high", "row_count": 4, "rows": []},
    "oa_release": {"source": "ocr", "confidence": "medium", "row_count": 3, "rows": []},
    "recruitment": {"source": "merged", "confidence": "high", "row_count": 5, "rows": []}
  },
  "merge_conflicts": [],
  "missing": [],
  "parse_errors": [],
  "ocr_review_required": true,
  "ready_for_calc": false
}
```

`ready_for_calc` 条件：四类齐全 + 无 parse_errors + **①② 若 source=ocr 则 `human_confirmed=true`** + 无 blocking 的 Prompt 5 问题。表级字段：

| 字段 | 说明 |
|------|------|
| `source` | excel / ocr / merged |
| `confidence` | high / medium / low |
| `human_confirmed` | ①② OCR 时用户是否已确认 |
| `ocr_review_required` | 整批是否等待 OCR 确认 |

---

## 3. 基线层 `Baseline`（Agent 2 输入）

```json
{
  "baseline_date": "2026-06-23",
  "source": "user_upload | compute_db",
  "rows": {"8": 5, "9": 3, "13": 12, "14": 8, "30": 2}
}
```

模式 B：Python 直查 **`daily_reports`**（**不用 Prompt 8**）。见上文「基线查询」。

---

## 4. 计算层 `ComputePayload`（Agent 2 产出 → 写 compute）

```json
{
  "batch_id": "batch_20260624_001",
  "report_date": "2026-06-24",
  "agent": "calc",
  "daily_rows": {
    "2": {"value": 2, "label": "今日入职"},
    "3": {"value": 1, "label": "今日离职"}
  },
  "weekly_rows": null,
  "trace": [
    {
      "row": 2,
      "value": 2,
      "source": "employees",
      "filter": "纳入口径 AND 入职日期=2026-06-24",
      "evidence": ["E***"]
    }
  ],
  "validation": {"passed": true, "failures": []},
  "new_consumed_oa_ids": ["REL_001"],
  "tenure": {
    "rows": [
      {
        "slot": "BU_A",
        "business_unit": "企业服务事业部",
        "ytd_leavers": 2,
        "avg_tenure_years": 1.85,
        "invalid_records": 0
      }
    ],
    "total": {"business_unit": "合计", "ytd_leavers": 6, "avg_tenure_years": 1.94, "invalid_records": 0},
    "b10": 6,
    "invalid_records": 0,
    "unmapped_bu": []
  }
}
```

`tenure.rows` **固定 8 行**（`BU_A`…`BU_H`，空槽 `ytd_leavers=0`、`avg_tenure_years=null`）；`b10` = 各 BU YTD 之和，须等于 Sheet1 Row14。

口径：[`skills/daily_rows.md`](skills/daily_rows.md)。空白行 23/24/27/28/34/35 不入库。
Row14 是链式 YTD 离职，必须与在岗时长固定 8 BU 汇总 B10 一致；不一致按规则 10 硬阻断。

---

## 5. 落库层 `PersistPayload`（可选 Prompt 9）

Python 直写 compute 表时不必调 AI。若用 Prompt 9：

```json
{
  "batch_id": "batch_20260624_001",
  "report_date": "2026-06-24",
  "daily_rows": {"2": 2, "3": 1},
  "validation": {"passed": true},
  "trace_ref": "trace/batch_20260624_001.json",
  "new_consumed_oa_ids": ["REL_001"],
  "target_layer": "compute"
}
```

---

## 6. 交付层 `Artifacts`

```json
{
  "batch_id": "batch_20260624_001",
  "report_date": "2026-06-24",
  "artifacts": {
    "daily_xlsx": "project/日报/2026-06-24/日报.xlsx",
    "weekly_xlsx": null,
    "calc_log_md": "project/日报/2026-06-24/计算日志_2026-06-24.md"
  }
}
```

导出读 **compute 库**（`daily_reports` 等），不是读 staging（四类业务表）。

---

## Agent 间 handoff

```
RawUpload → [Agent 1] → StagingPayload → employees / employee_resignations / oa_protocols / recruitment_pipeline
                              ↓ ready_for_calc=true
四类表 + 昨日 daily_reports → [Agent 2 / Python] → ComputePayload → daily_reports (+ weekly/monthly)
                              ↓ validation.passed
daily_reports → [openpyxl] → Artifacts（xlsx / 计算日志 md）
```
