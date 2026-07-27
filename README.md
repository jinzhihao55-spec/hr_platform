# 人事报表智能体 · hr_platform

基于确定性规则与 Qwen 辅助能力的**双 Agent** 人事报表系统，覆盖人员、离职、OA 协议、招聘四类数据，自动生成**员工数增减日报（Row2-40）**、**周报**和**计算日志**。

核心原则：所有数字由确定性规则计算，模型不生成任何数字；缺数据/有歧义时停下提问；每行可追溯。

## 项目结构

```
hr_platform/
├── backend/         # Python FastAPI 后端 —— 双 Agent 流水线、计算引擎、API
├── frontend/        # React 19 + Vite 前端 —— 工作台、日报、周报、归档、设置
├── database/        # MySQL 建表脚本与迁移 —— schema.sql + 版本化迁移
└── deploy/          # Docker Compose 部署配置
```

## 双 Agent 架构

| Agent | 职责 | 入口 |
|-------|------|------|
| **Agent 1 · 解析** | 图像/Excel 解析 → 四类结构化表 → 写库 | `backend/docs/skills/SKILL_PARSE.md` |
| **Agent 2 · 计算** | 读库 → 算 Row2–40 + 校验 → 写报表 → 导出 Excel | `backend/docs/skills/SKILL_CALC.md` |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12+ · FastAPI · Pandas · SQLAlchemy |
| 前端 | React 19 · Vite · 原生 CSS（CSS 变量驱动） |
| 数据库 | MySQL 8.0+ · Redis |
| AI | Qwen API（阿里云百炼 OpenAI 兼容接口） |
| 部署 | Docker Compose · Nginx |

## 快速开始

### Docker 部署（推荐）

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env 填写密钥
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

默认 Nginx 发布 `127.0.0.1:8080`，浏览器、MySQL、Redis 均不直接暴露。

### 本地开发

```bash
# 后端
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 编辑 .env 填写配置
bash scripts/run_dev.sh

# 前端
cd frontend
npm install && npm run dev
```

### 数据库初始化

```bash
mysql -u root -p < database/schema.sql
cd backend && python -m scripts.init_db
```

## 测试

```bash
cd backend
pytest -q                          # 单元测试（SQLite 内存库）
python scripts/run_single_user_regression.py --mode fake  # 链式回归
```

## 安全

- 所有密钥从环境变量读取，不得硬编码
- 生产环境强制要求 MySQL、Redis、API Token 和人员身份密钥
- 模型产出的 SQL 经 `sql_guard.py` 只读校验后才可执行
- 上传文件解析入库后立即删除

## 相关文档

- [`backend/docs/pipeline_spec.md`](backend/docs/pipeline_spec.md) — 后端流水线规格
- [`backend/docs/frontend_api_map.md`](backend/docs/frontend_api_map.md) — 前端接口映射
- [`backend/docs/DEPLOYMENT_SINGLE_USER.md`](backend/docs/DEPLOYMENT_SINGLE_USER.md) — 部署与升级指南
- [`backend/docs/TESTING_SINGLE_USER_V1.md`](backend/docs/TESTING_SINGLE_USER_V1.md) — 测试方法
- [`backend/docs/USER_MANUAL_SINGLE_USER_V1.md`](backend/docs/USER_MANUAL_SINGLE_USER_V1.md) — 用户操作手册