# 人事报表智能体 · 后端

基于确定性规则与 Qwen 辅助能力的**双 Agent**人事报表：把四类输入（人员表、离职、协议签署/OA、招聘）
按固定口径转换成三份交付物：**员工数增减情况日报**、**员工数增减周报**、**计算日志**。

核心原则：所有数字由确定性规则计算，模型不生成任何数字；缺数据/有歧义时停下提问；每行可追溯。

## 双 Agent

| Agent | 职责 | Skill 入口 |
|-------|------|-----------|
| **Agent 1 · 解析** | 图像/Excel 解析 → 四类结构化表 → 写库 | [`docs/skills/SKILL_PARSE.md`](docs/skills/SKILL_PARSE.md) |
| **Agent 2 · 计算** | 读库 → 算 Row2–40 + 校验 → 写报表表 → 导出 Excel | [`docs/skills/SKILL_CALC.md`](docs/skills/SKILL_CALC.md) |

## 技术栈

- **Python 3.12+** · **FastAPI** · **Pandas**
- **MySQL 8.0+** · **Redis**
- **Qwen API**（阿里云百炼 OpenAI 兼容接口）—— 文本场景，可缺省
- **Qwen3.5-Omni**（图像解析，需单独配置 `LLM_VISION_*`，见下）

---

# 快速开始

## 推荐：单用户 Docker 部署

正式试运行使用 `web + api + migrate + mysql + redis` 的 Compose 方案。默认只有
Nginx 发布 `127.0.0.1:8080`，API token 由 Nginx 服务端注入，浏览器、MySQL、
Redis 均不直接暴露。

```bash
cp deploy/.env.example deploy/.env
# 填写 deploy/.env 中所有空白密钥
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
python scripts/check_ready.py
```

完整的密钥生成、升级、备份恢复和故障处理见
[`docs/DEPLOYMENT_SINGLE_USER.md`](docs/DEPLOYMENT_SINGLE_USER.md)。以下原生安装方式
主要用于开发与调试。

首次 Run 缺少正式基线时，直接在 Run 页面上传前一工作日的已验收日报；导入文件
会登记为不可变正式版本，后续 Run 自动引用最近一份已发布日报。

## 测试与发布门禁

仓库内测试只允许假数据；真实日报材料仅在导师本机、仓库外执行脱敏回归：

```bash
PYTHONPATH="$PWD" python -m pytest -q
PYTHONPATH="$PWD" python scripts/run_single_user_regression.py --mode fake
python scripts/scan_sensitive_artifacts.py .
```

完整的导师本机回放、12 维制品检查和敏感值精确扫描见
[`docs/TESTING_SINGLE_USER_V1.md`](docs/TESTING_SINGLE_USER_V1.md)。部署前逐项执行
[`docs/RELEASE_CHECKLIST_SINGLE_USER_V1.md`](docs/RELEASE_CHECKLIST_SINGLE_USER_V1.md)。

## macOS

### 1. 安装 Python 3.12

```bash
brew install python@3.12
python3.12 --version   # 应显示 Python 3.12.x
```

### 2. 安装 MySQL 和 Redis

```bash
brew install mysql redis
brew services start mysql
brew services start redis

# 初始化 MySQL root 密码（首次）
mysql_secure_installation
```

或用 Docker：

```bash
docker run -d --name hr-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=ai_hr_reports mysql:8.0
docker run -d --name hr-redis -p 6379:6379 redis:7
```

### 3. 创建虚拟环境并安装依赖

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`（最少需要填 MySQL 密码，其余有默认值）：

```env
MYSQL_PASSWORD=your_mysql_password
LLM_API_KEY=                    # 可留空，留空则不使用 LLM 文本辅助场景
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-plus
LLM_VISION_API_KEY=             # 可留空，留空则不支持上传截图/图片（PNG/JPG）作为输入
LLM_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_VISION_MODEL=qwen3.7-plus
API_AUTH_TOKEN=                 # 本机开发可留空；共享内网/正式部署必须设置（所有接口要求 X-API-Token）
PERSON_KEY_SECRET=              # 生产/恢复环境必须设置并长期保持一致
PERSON_KEY_VERSION=v1
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173  # 按前端实际来源收紧
MAX_UPLOAD_MB=20
MONTH_OPENING_ALLOWED_USERS=hr.user1,hr.user2  # 网关用户名；仅这些用户可确认月初基线
```

### 5. 初始化数据库

```bash
mysql -u root -p < ../database/schema.sql   # 建库建表
python -m scripts.init_db                    # 开发便捷方式（ORM 自动建表）
```

既有库升级到本版本前，须依次执行以下幂等迁移：

```bash
mysql -u root -p ai_hr_reports < scripts/migrations/2026-07-12_add_snapshot_tables.sql
mysql -u root -p ai_hr_reports < scripts/migrations/2026-07-12_add_upload_records.sql
mysql -u root -p ai_hr_reports < scripts/migrations/2026-07-12_add_month_opening_baselines.sql
```

### 6. 启动

```bash
bash scripts/run_dev.sh
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. 验证

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

---

## Linux（Ubuntu / Debian）

### 1. 安装 Python 3.12

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version
```

### 2. 安装 MySQL 和 Redis

```bash
sudo apt install -y mysql-server redis-server
sudo systemctl start mysql redis-server
sudo systemctl enable mysql redis-server

# 设置 MySQL root 密码
sudo mysql_secure_installation
```

或用 Docker：

```bash
docker run -d --name hr-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=ai_hr_reports mysql:8.0
docker run -d --name hr-redis -p 6379:6379 redis:7
```

### 3. 创建虚拟环境并安装依赖

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cp .env.example .env
nano .env   # 或 vim .env
```

```env
MYSQL_PASSWORD=your_mysql_password
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-plus
LLM_VISION_API_KEY=
LLM_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_VISION_MODEL=qwen3.7-plus
API_AUTH_TOKEN=                 # 本机开发可留空；共享内网/正式部署必须设置（所有接口要求 X-API-Token）
PERSON_KEY_SECRET=              # 生产/恢复环境必须设置并长期保持一致
PERSON_KEY_VERSION=v1
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173  # 按前端实际来源收紧
MAX_UPLOAD_MB=20
MONTH_OPENING_ALLOWED_USERS=hr.user1,hr.user2  # 网关用户名；仅这些用户可确认月初基线
```

### 5. 初始化数据库

```bash
mysql -u root -p < ../database/schema.sql
python -m scripts.init_db
```

### 6. 启动

```bash
bash scripts/run_dev.sh
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Windows

图像解析已不依赖任何需要本地编译/GPU 驱动的 OCR 引擎，纯 Python 依赖，Windows 原生安装即可，无需 WSL2/Docker。

### 方式 A：WSL2（可选）

1. 安装 WSL2：在 PowerShell（管理员）运行 `wsl --install`，重启后按提示完成 Ubuntu 安装
2. 打开 Ubuntu 终端，按 **Linux 步骤** 操作即可

### 方式 B：原生 Windows

**安装 Python 3.12：**
从 https://www.python.org/downloads/release/python-3120/ 下载并安装，勾选"Add Python to PATH"。

**安装 MySQL 和 Redis：**
- MySQL：https://dev.mysql.com/downloads/installer/（选 MySQL Installer）
- Redis：https://github.com/tporadowski/redis/releases（Windows 社区版）

**创建虚拟环境并安装依赖：**

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
# 如果执行策略报错：
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt
```

```bat
REM CMD 用户
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\activate.bat
pip install -r requirements.txt
```

**配置环境变量：**

```powershell
Copy-Item .env.example .env
notepad .env
```

**初始化数据库：**

```powershell
mysql -u root -p < ..\database\schema.sql
python -m scripts.init_db
```

**启动：**

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

macOS / Linux 推荐：

```bash
bash scripts/run_dev.sh
```

---

## 测试（可选）

SQLite 内存库，无需 MySQL / Redis：

```bash
pip install pytest
pytest -q
```

真实链式回归（SQLite 隔离运行，不需要 MySQL/Redis；真实文件不进入仓库）：

```bash
python -m scripts.run_chain_regression \
  --data-root /path/to/日报 \
  --baseline-date 2026-07-07 \
  --dates 2026-07-08 2026-07-09 \
  --structured-image-dir /path/to/approved-structured-inputs \
  --output-dir /tmp/hr-chain-regression
```

完整说明见 [`docs/REAL_DATA_REGRESSION.md`](docs/REAL_DATA_REGRESSION.md)。

---

# 使用说明

## 上传输入文件

```
POST /ingest
Content-Type: multipart/form-data

report_date: 2026-06-30
employees:    人员表.xlsx        (截图须人工确认，未确认直接拒绝——请传 Excel)
resignations: 离职表.xlsx        (同上，仅接受 Excel)
agreements:   协议签署.xlsx      (或 OA系统截图.png)
recruitment:  招聘数据.xlsx      (或 招聘截图.png)
```

四类文件每次可只传部分——未传的沿用库内已有数据（如人员表无变化可不重传）。

### 四表合一 xlsx（combined）

一个 xlsx 含 4 个 sheet（人员 / 离职 / OA / 招聘）时，推荐：

```bash
# Swagger：POST /ingest/combined（report_date + file）
curl -F "report_date=2026-06-24" \
     -F "file=@输入合集_20260624.xlsx" \
     http://localhost:8000/ingest/combined

bash scripts/upload_combined.sh 2026-06-24 <xlsx路径>
python scripts/ingest_combined.py --date 2026-06-24 --file testdata/2026-06-24/xxx.xlsx
```

训练样例与标准答案见 [`testdata/README.md`](testdata/README.md)（6/22 增量、6/24 全量、对比脚本）。

**Swagger 上传文件**：`employees` 等字段须点 **Choose File**，不要填路径字符串（否则 422）。

## 对话驱动报表生成

```
POST /chat
{
  "report_date": "2026-06-30",
  "message":     "生成今日报表",
  "session_id":  "可选"
}
```

后端自动判断状态并执行：

| 用户说 | 后端做 |
|---|---|
| "生成" / "出报表" 等 | 触发日报生成，返回文件路径或澄清问题 |
| JSON 含数字 | 解析为基线值 → 注入 → 自动重试生成 |
| 日期字符串（LWD 待补） | 更新 OA 记录 → 重试 |
| 未知员工类型答复 | 更新口径配置 → 重试 |
| 其他 | 返回当前状态（各表行数 + 待确认澄清数） |

所有对话永久保存到 MySQL `chat_messages` 表。

## 图像识别

支持直接上传 `.png` / `.jpg` 等截图，无需转 Excel：

| 图像类型 | 对应字段 |
|---|---|
| OA 系统"流程高级查询"页面截图 | `agreements` |
| 招聘漏斗 Excel 区域截图 | `recruitment` |

**识别方式：** 阿里云百炼视觉 LLM（`.env` 中配置 `LLM_VISION_API_KEY` +
`LLM_VISION_BASE_URL` + `LLM_VISION_MODEL`）。当前默认模型为
`qwen3.7-plus`，接口地址见 `.env.example`。

未配置视觉 LLM，或视觉模型未能从图像中提取到有效数据时 → 返回错误，提示改用 Excel
（`.xlsx`）文件上传代替截图。

（曾用 PaddleOCR 本地识别作为无需 API key 的首选方案，因安装/依赖不稳定、对
"表单+表格"混合版面识别不可靠，已移除。）

---

# API 接口一览

| 方法 & 路径 | 用途 | 状态码 |
|---|---|---|
| `GET /health` | 探活 | 200 |
| `POST /chat` | **统一对话入口**，驱动完整流水线 | 200 |
| `GET /chat/history` | 对话历史（按日期或会话） | 200 |
| `POST /ingest` | 上传四类输入（Excel 或图像；支持 `combined` 四表合一） | 200 · 409 · 422 |
| `POST /ingest/combined` | 上传四表合一 xlsx（Swagger 选文件推荐） | 200 · 409 · 422 |
| `POST /reports/daily` | 生成日报（周末自动出周报） | 200 · 422 · 409 |
| `POST /reports/weekly` | 单独生成周报 | 200 · 422 |
| `POST /reports/baseline` | 注入链式基线（解除 baseline_missing） | 200 |
| `POST /reports/month-opening/confirm` | HR 确认沿用指定定稿作为月初基线 | 200 · 409 |
| `POST /reports/month-opening/import` | 上传 HR 重述后的 A+B 与在岗时长月初基线 | 200 · 409 · 422 |
| `GET /reports/month-opening/{month}` | 查询月初基线确认状态 | 200 · 404 |
| `GET /reports/download?path=` | 下载产物（xlsx / md） | 200 · 404 |
| `GET /jobs/{id}` · `GET /jobs` | 任务状态 | 200 · 404 |
| `GET /query` | 自然语言 → 只读 SQL | 200 · 409 · 503 |
| `GET /context?report_date=` | 页头上下文（行数 + 文件状态） | 200 |
| `GET /reports/daily/dates` | 已生成日报的日期列表 | 200 |
| `GET /reports/daily/{date}/view` | Row2–40 结构化视图 | 200 |
| `GET /reports/weekly/weeks` | 已生成周报的周次列表 | 200 |
| `GET /reports/weekly/{week_end}/view` | 周报结构化视图 | 200 |
| `GET /archive?kind=` | 产物文件归档列表 | 200 |
| `GET /config` | 读取当前生效口径 | 200 |
| `PUT /config` | 在线修改可变业务字典 | 200 |
| `DELETE /config/{field}` · `DELETE /config` | 重置口径 | 200 |
| `GET /clarifications?report_date=` | 澄清事项列表（MySQL 永久） | 200 |
| `POST /clarifications/{id}/answer` | 提交澄清答复 | 200 · 404 |

最后工作日自动周报若被硬校验阻断，日报仍返回 `status=succeeded`，并附带
`weekly_status=blocked`、`weekly_hard_failures`；修正数据后可单独重跑周报。

前端主交互只需 `POST /ingest` + `POST /chat`。

---

# 数据库表

| 表名 | 说明 | 存储 |
|---|---|---|
| `projects` | 项目表 | MySQL |
| `employees` | 人员主表 | MySQL |
| `employee_snapshots` | 按报告日保存的人员快照（周报在职与历史重算） | MySQL |
| `employee_resignations` | 离职流程 | MySQL |
| `oa_protocols` | OA 协议签署 | MySQL |
| `recruitment_pipeline` | 招聘漏斗 | MySQL |
| `daily_reports` | 日报宽表（Row2–40） | MySQL |
| `tenure_snapshot_metrics` | 已验收在岗时长汇总基线（8 个 BU，无人员明细） | MySQL |
| `month_opening_baselines` | HR 显式确认的月初 Sheet1/在岗时长独立基线 | MySQL + 文件校验和 |
| `weekly_reports` | 周报（按周×事业部） | MySQL |
| `monthly_reports` | 月报（结构预留） | MySQL |
| `clarifications` | 澄清事项（与 Redis 双写） | MySQL + Redis |
| `chat_messages` | 对话历史（全量） | MySQL |
| Job / Config / Source 状态 | 任务状态 · 口径覆盖 · 文件状态 | Redis |

---

# 安全

- 所有密钥（MySQL / Redis / LLM 文本 / LLM 视觉）只从环境变量读取，不得硬编码
- 生产环境强制要求 MySQL、Redis、API 和人员身份密钥，缺一项即拒绝启动
- Compose 默认只有 Nginx 绑定主机回环地址；API token 只在代理层注入
- 上传文件解析入库后立即删除（含图像转换的临时 xlsx）
- 模型产出的 SQL 必须经 `app/llm/sql_guard.py` 只读校验后才可执行

---

## 相关文档

- [`docs/skills/SKILL.md`](docs/skills/SKILL.md) — 双 Agent 总入口
- [`docs/skills/daily_rows.md`](docs/skills/daily_rows.md) §3.9 — 在岗时长固定 8 BU、B10=Row14 硬校验
- [`docs/pipeline_spec.md`](docs/pipeline_spec.md) — 后端流水线
- [`docs/frontend_api_map.md`](docs/frontend_api_map.md) — 前端接口映射
- [`docs/DEPLOYMENT_SINGLE_USER.md`](docs/DEPLOYMENT_SINGLE_USER.md) — 单用户部署、升级与备份恢复
- [`docs/USER_MANUAL_SINGLE_USER_V1.md`](docs/USER_MANUAL_SINGLE_USER_V1.md) — 人事同事 Web 操作手册
- [`docs/FRONTEND_E2E_TESTING_SINGLE_USER_V1.md`](docs/FRONTEND_E2E_TESTING_SINGLE_USER_V1.md) — 前端端到端验收与测试方法
- [`docs/FRONTEND_VISUAL_QA_2026-07-15.md`](docs/FRONTEND_VISUAL_QA_2026-07-15.md) — 桌面与移动端视觉验收报告

## 协作者

- A 组
