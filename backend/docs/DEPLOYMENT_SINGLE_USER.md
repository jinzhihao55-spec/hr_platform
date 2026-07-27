# 单用户正式部署手册

本文覆盖当前单用户版本的安装、升级、探活、备份和恢复。默认部署目标是 HR
同事自己的电脑或一台只允许本人访问的内网主机。

## 1. 部署边界

Compose 包含五个服务：

| 服务 | 职责 | 是否发布主机端口 |
|---|---|---|
| `web` | React 静态页面、Nginx 反向代理 | 是，默认仅 `127.0.0.1:8080` |
| `api` | FastAPI、确定性规则、文件导出 | 否 |
| `migrate` | 一次性数据库 schema/迁移 | 否 |
| `mysql` | 正式事实、Run、定稿版本 | 否 |
| `redis` | 任务状态、临时配置和缓存 | 否 |

浏览器只访问 `web`。Nginx 在服务器侧注入 `X-API-Token`，令牌不会编译进
前端 JavaScript。MySQL、Redis 和 API 不能从主机网络直接访问。

本版本没有企业 SSO，也不是多用户系统。不得把 `WEB_BIND_ADDRESS` 改为
`0.0.0.0` 后直接暴露到局域网或互联网。需要跨机器访问时，应先接入带 TLS 和
企业身份认证的网关。

## 2. 目录要求

默认按以下同级目录组织三个仓库：

```text
groupA/
├── backend/
├── frontend/
└── database/
```

所有部署命令都在 `backend` 目录执行。若三个仓库位于独立 worktree，在
`deploy/.env` 中用绝对路径设置 `BACKEND_CONTEXT`、`FRONTEND_CONTEXT` 和
`DATABASE_CONTEXT`。

## 3. 首次启动

前置要求：Docker Desktop 或 Docker Engine，且支持 `docker compose`。

```bash
cd backend
cp deploy/.env.example deploy/.env
```

打开 `deploy/.env`，至少填写以下五个强随机密钥：

```env
MYSQL_PASSWORD=
MYSQL_ROOT_PASSWORD=
REDIS_PASSWORD=
API_AUTH_TOKEN=
PERSON_KEY_SECRET=
```

其中 MySQL 应用密码和 root 密码必须不同。可重复执行下面的命令生成不同值：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`PERSON_KEY_SECRET` 用于生成不可逆人员关联键。恢复环境必须沿用原值，否则历史
Run 与新 Run 的人员身份无法稳定关联。不要把 `deploy/.env` 发给学生、提交 Git
或放入普通网盘。

图片输入需要经批准的视觉模型配置：

```env
LLM_VISION_API_KEY=
LLM_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_VISION_MODEL=qwen3.7-plus
```

未配置视觉密钥时，系统仍可处理 Excel，但会拒绝图片并提示改传结构化文件。
真实人事截图只有在公司批准对应云端模型和数据路径后才能启用。

先校验 Compose，再启动：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
python scripts/check_ready.py
```

就绪检查必须同时满足 MySQL、Redis、迁移版本、输出目录和生产密钥五项要求。
通过后打开：

```text
http://127.0.0.1:8080/
```

## 4. 正式输入

首次使用时，系统还没有上一份正式日报。先从日历创建第一个 Run；页面出现“缺少
日报基线”后，选择前一工作日并上传 HR 已验收的定稿日报。系统会校验 Sheet1 与
“在岗时长”，把原文件登记为不可变 v1 基线，再自动关联当前 Run。同日期重导不会
覆盖历史 artifact，而是生成新版本并保留旧版本。

每个报告日只接受四个显式来源槽位：

| 槽位 | 推荐格式 | 说明 |
|---|---|---|
| 人员表 | `.xlsx` / `.xls` | 当日人员主表 |
| 离职人员报表 | `.xlsx` / `.xls` | 正式离职流程表；不要求“离职明细” |
| 协议签署 / OA Release | Excel 或图片 | 图片需启用经批准的视觉模型 |
| 招聘数据 | Excel 或图片 | 图片需启用经批准的视觉模型 |

用户从日历选择报告日，创建 Run，上传四个来源，完成校验与必要澄清后预览。日报
与周报分别发布；正式文件只从已发布版本下载。原始上传文件放在容器 `tmpfs`，解析
结束即删除，不进入持久卷和备份。

## 5. 日常运维

查看服务状态与日志：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml logs --tail=200 api web
python scripts/check_ready.py --attempts 3
```

停止或重新启动：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml stop
docker compose --env-file deploy/.env -f deploy/compose.yaml start
```

`docker compose down` 会删除容器和网络，但保留命名卷。不要在正式环境执行
`docker compose down -v`，它会删除数据库和报表产物。

## 6. 升级

升级前先完成第 7 节备份，然后拉取三个仓库的同一发布版本：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml build --pull
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
python scripts/check_ready.py
```

`migrate` 服务在 API 启动前运行。迁移失败、MySQL/Redis 未就绪或生产密钥缺失
都会阻止 API 对外提供服务。不要绕过迁移服务单独启动 API。

## 7. 备份

正式恢复所需的三项资产：

1. MySQL 全库备份。
2. `report_outputs` 命名卷中的正式 Excel、日志和 manifest。
3. 原部署的 `PERSON_KEY_SECRET`、数据库密码及版本配置，存入公司的密钥保管系统。

创建备份目录并导出 MySQL：

```bash
mkdir -p backups
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T mysql \
  sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction ai_hr_reports' \
  > backups/ai_hr_reports.sql
```

备份正式输出卷：

```bash
docker run --rm \
  -v hr-agent-single-user_report_outputs:/data:ro \
  -v "$PWD/backups":/backup \
  alpine:3.20 tar -czf /backup/report_outputs.tgz -C /data .
```

Redis 不是正式报表的唯一事实来源，可以由 MySQL 和后续运行重建。原始上传区是
临时内存文件系统，明确不备份。

## 8. 恢复演练

在隔离机器创建新的 `deploy/.env`，填入原 `PERSON_KEY_SECRET` 和新的基础设施密码，
先启动 MySQL/Redis：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d mysql redis
```

恢复数据库：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T mysql \
  sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ai_hr_reports' \
  < backups/ai_hr_reports.sql
```

恢复输出卷：

```bash
docker run --rm \
  -v hr-agent-single-user_report_outputs:/data \
  -v "$PWD/backups":/backup:ro \
  alpine:3.20 sh -c 'rm -rf /data/* && tar -xzf /backup/report_outputs.tgz -C /data'
```

随后执行完整启动和 `python scripts/check_ready.py`。在恢复环境抽查历史定稿的
manifest/hash，并用批准的非敏感测试集跑一次 Run 后，才能切换正式使用。

## 9. 不使用 Docker 的开发运行

macOS、Linux 和 Windows 都可使用 Python 3.12、Node 22、MySQL 8.0 与 Redis 7
原生运行。环境变量名称与 `deploy/.env.example` 一致，API 仍应设置
`APP_ENV=prod`、`API_AUTH_TOKEN`、`PERSON_KEY_SECRET` 和数据库密码。

原生运行不会自动获得 Nginx 的令牌隔离。仅限回环地址开发时，可将
`APP_ENV=local` 并关闭令牌；任何真实数据试运行仍应使用 Compose 或等价的受控
反向代理，避免把共享令牌交给浏览器。

## 10. 常见失败

| 现象 | 检查项 |
|---|---|
| Compose 直接报变量为空 | 填写 `deploy/.env` 中所有必填密钥 |
| `migration=false` | 查看 `migrate` 日志；确认三个仓库版本一致 |
| `redis=false` | 检查 Redis 密码是否与 API 配置一致 |
| 图片被拒绝 | 配置经批准的 `LLM_VISION_*`，或改传 Excel |
| 页面可开但接口 401 | 检查 `web` 与 `api` 的 `API_AUTH_TOKEN` 是否来自同一环境文件 |
| 历史人员无法关联 | 恢复时使用了错误的 `PERSON_KEY_SECRET`；停止写入并重新恢复 |

正式诊断信息不得打印人员姓名、证件号、原始文件名、模型密钥或数据库密码。
