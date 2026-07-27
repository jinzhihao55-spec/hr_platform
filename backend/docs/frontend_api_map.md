# 前端页面 ↔ 后端接口映射

> 静态原型：`frontend/static templates/*.html`。后端已开放 CORS（`*`），
> 前端可直接调用以下接口填充数据。日期均为 `YYYY-MM-DD`。

## 工作台（工作台.html）

| 区块 | 接口 | 说明 |
|------|------|------|
| 页头（报告日/基线/本周窗口/节假日/待确认数） | `GET /context?report_date=` | 一次取齐页头所需上下文 |
| 拖入上传 → 识别归类入库 | `POST /ingest`（multipart） | 返回 `sources`（updated/reused）+ 行数 |
| 识别清单（今日上传/沿用） | 同上 `sources` | `action=reused` 显示「沿用 YYYY-MM-DD」 |
| 生成今日日报（含周报自动） | `POST /reports/daily` | 200/422(blocked)/409(needs_clarification) |
| 对话 · 待确认列表 | `GET /clarifications?report_date=` | 待确认事项（缺基线/LWD/招聘冲突等） |
| 对话 · 提交答复 / 选择 | `POST /clarifications/{id}/answer` | 记录答复（人在环留痕） |
| 最近输出 | `GET /reports/daily/dates` 或 `GET /archive` | 近期日报/周报列表 |

## 日报（日报.html）

| 区块 | 接口 |
|------|------|
| 日期选择器 | `GET /reports/daily/dates` |
| KPI + Sheet1 主表 Row2–40（基线/报告/公式/来源） | `GET /reports/daily/{date}/view` → `rows[]` + `kpis` |
| 在岗时长（固定 8 BU×YTD离职×平均在职 + B10） | 同上 → `tenure.rows` 固定 `BU_A`...`BU_H`，空 BU `ytd_leavers=0` |
| 发布前校验 12 项 | 同上 → `validations` |
| 导出 Excel | `POST /reports/daily` 得到 `daily_xlsx` → `GET /reports/download?path=` |

## 周报（周报.html）

| 区块 | 接口 |
|------|------|
| 周次选择器 | `GET /reports/weekly/weeks` |
| Sheet2 主体×事业部（含类型拆分/前三项目/合计） | `GET /reports/weekly/{week_end}/view?week_start=` → `sheet2` |
| Sheet1 成本中心×项目 | 同上 → `sheet1` |
| 导出 Excel | `POST /reports/weekly` → `weekly_xlsx` → `GET /reports/download?path=` |

## 计算日志（计算日志.html）

| 区块 | 接口 |
|------|------|
| 报表类型切换（日报 / 周报） | 前端本地切换 |
| 日报日期选择器 | `GET /reports/daily/dates` |
| 周报周次选择器 | `GET /reports/weekly/weeks` |
| 日报逐行 trace（Row2–40 / 在岗时长 / 校验） | `GET /reports/daily/{date}/view` → `rows` / `tenure` / `validations` |
| 周报逐行 trace（Sheet2 事业部 + Sheet1 成本中心） | `GET /reports/weekly/{week_end}/view?week_start=` → `traces` / `cc_traces` / `validations` |
| 下载完整 md 计算日志 | 日报 view → `calc_log_path`；周报同日归档亦指向 `计算日志_{week_end}.md` |

## 归档（归档.html）

| 区块 | 接口 |
|------|------|
| 按日期归类的产物（日报/周报/计算日志 + 大小 + 打开） | `GET /archive?kind=all|daily|weekly|calc_log` |
| 打开/下载某文件 | `GET /reports/download?path=`（用归档项的 `path`） |

## 口径与设置（口径与设置.html）

| 区块 | 接口 |
|------|------|
| 纳入/排除口径、离职方式/流程状态枚举、员工状态字典、公式链、空白/派生行、`tenure_bu_slots` / `tenure_bu_labels` / `bu_to_slot` | `GET /config` |
| 节假日/调休、工号↔OA 映射、微软项目清单 | 当前为业务配置/暂不涉及，前端可静态展示或后续接入 |

## 全部新增接口一览

```
GET  /context?report_date=
GET  /reports/daily/dates
GET  /reports/daily/{date}/view
GET  /reports/weekly/weeks
GET  /reports/weekly/{week_end}/view?week_start=
GET  /archive?kind=
GET  /config
GET  /clarifications?report_date=
POST /clarifications/{id}/answer
```
（既有：`/health`、`/ingest`、`POST /reports/daily|weekly`、`/reports/download`、`/jobs`、`/query`）
