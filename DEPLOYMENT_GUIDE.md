# HR 报表智能体 v1.7.21 — 部署指南

## 部署前准备

### 1. 环境要求
- Windows Server 或 Linux
- Python 3.12+
- Node.js 20+ (仅构建前端时需要)
- MySQL 8.0+
- Redis 5.0+ (Windows 仅支持到 5.0)
- Nginx

### 2. 数据库迁移

在 MySQL 中执行以下 SQL（按顺序）：

```sql
-- 如果尚未创建 Run 相关表，执行 migrations 目录下的 4 个 SQL 文件：
-- 2026-07-15_01_report_runs.sql
-- 2026-07-15_02_run_facts.sql
-- 2026-07-15_03_publications.sql
-- 2026-07-16_04_expand_publication_snapshot.sql

-- 新增 original_filename 列
ALTER TABLE run_sources ADD COLUMN original_filename VARCHAR(255) DEFAULT '';
```

### 3. 配置 .env 文件

```bash
# 后端 backend/.env
APP_ENV=prod
APP_HOST=127.0.0.1
APP_PORT=8000

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=hr_agent
MYSQL_PASSWORD=<你的密码>
MYSQL_DB=ai_hr_reports

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

PERSON_KEY_SECRET=<用 python3 -c "import secrets; print(secrets.token_urlsafe(48))" 生成>
PERSON_KEY_VERSION=v1

LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-plus
LLM_VISION_API_KEY=同 LLM_API_KEY
LLM_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_VISION_MODEL=qwen3.7-plus

API_AUTH_TOKEN=<与 Nginx 注入的一致>
CORS_ALLOW_ORIGINS=
MAX_UPLOAD_MB=20

UPLOAD_DIR=./data/uploads
OUTPUT_DIR=./data/outputs
```

## 部署步骤

### 后端

```powershell
cd C:\Users\Administrator\Desktop\v1_7.21\backend

# 安装依赖
pip install -r requirements.txt
# Python redis 版本必须 < 5.0
pip install "redis>=4.0,<5.0"

# 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Windows 服务化（推荐）：**

```powershell
nssm install HRAgentAPI "C:\Python312\python.exe" "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
nssm set HRAgentAPI AppDirectory "C:\Users\Administrator\Desktop\v1_7.21\backend"
nssm set HRAgentAPI Start SERVICE_AUTO_START
nssm start HRAgentAPI
```

### 前端

前端已构建在 `frontend/dist/`，直接放到 Nginx 根目录即可。

Nginx 配置参考：

```nginx
server {
    listen 8080;
    server_name _;

    root /path/to/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-API-Token "<API_AUTH_TOKEN>";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### 初始化：建立初始基线

首次使用系统，需要：

1. 打开浏览器访问 `http://服务器:8080`
2. 在运行日历中点击第一个工作日
3. 上传 4 类源文件（人员表、离职报表、协议签署、招聘数据）
4. 确认所有 OCR 识别结果
5. 点击"预览日报与周报"
6. 校验数值后点击"发布日报"
7. 后续日期会自动继承此日报作为链式基线

## 验证命令

```bash
curl http://127.0.0.1:8000/health
# 预期: {"status":"ok","mysql":true,"redis":true,"llm_enabled":true}
```

## 注意事项

- PERSON_KEY_SECRET 一旦设定不能更改，否则历史人员身份关联失效
- API_AUTH_TOKEN 需要和 Nginx 注入的一致
- 图像识别依赖阿里云百炼 API，确保额度充足
- Windows Redis 必须用 5.0 版本
- 定期备份 MySQL 数据库
