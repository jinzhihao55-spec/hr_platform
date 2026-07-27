## 项目名称

人事报表智能体 · 数据库（`hr_ai_agent_groupA` / database）

存放建库建表脚本与数据库说明。为「人事报表智能体」提供持久化（长记忆）能力：员工、离职、OA、招聘等原始数据，以及日报/周报/月报、对话历史、澄清事项等。库名 `ai_hr_reports`。

## 运行条件

- MySQL 8.0+
- 字符集 `utf8mb4`
- 可选：Redis（应用层用于任务状态、短记忆、口径覆盖、澄清双写；不由本仓管理）

## 运行说明

1. 创建数据库并建表：
   ```bash
   mysql -u root -p < schema.sql
   ```
   `schema.sql` 内含全部表结构。如无数据库先手动创建：`CREATE DATABASE ai_hr_reports DEFAULT CHARSET utf8mb4;`
2. 应用侧连接：在 `backend/.env` 配置 `MYSQL_HOST/PORT/USER/PASSWORD/DB=ai_hr_reports`。
3. 开发便捷方式（ORM 自动建表）：`cd backend && python -m scripts.init_db`。

## 表结构一览

| 表名 | 说明 |
|------|------|
| `projects` | 项目表 |
| `employees` | 人员主表 |
| `employee_resignations` | 离职人员报表 |
| `oa_protocols` | OA 协议签署 / 离职审批表 |
| `recruitment_pipeline` | 招聘漏斗表 |
| `daily_reports` | 员工数增减日报（宽表 Row2–40） |
| `weekly_reports` | 员工数增减周报（按周 × 事业部） |
| `monthly_reports` | 员工数增减月报（**结构预留，当前未使用**） |
| `chat_messages` | 对话历史表（全量） |
| `clarifications` | 澄清事项表（永久存储，与 Redis 双写） |

> 任务状态、口径覆盖、文件状态等易变数据存于 Redis，不落 MySQL。

## 测试说明

- 后端单测使用 SQLite 内存库，不依赖本 MySQL（`cd backend && pytest -q`）。
- 评测脚本需真实 MySQL + 标准答案 JSON（见 `backend/scripts/` 与 `backend/testdata/`）。

## 技术架构

MySQL 8.0+ 作为长记忆中枢，配合应用层 SQLAlchemy Async ORM 访问；Redis 作为短记忆/缓存中枢。整体架构见主仓 `架构说明文档.md`。
