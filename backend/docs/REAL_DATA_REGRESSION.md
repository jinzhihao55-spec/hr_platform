# 本地启动与真实链式回归

本文说明两件事：如何启动 A 组人事报表智能体，以及如何用已定稿日报作为基线重放后续日期。

## 1. 验证边界

本回归流程验证：

- 人员表、离职人员报表的 `.xls` 解析和入库；
- OA、招聘结构化结果的入库；
- 日报 Row2-40 中全部业务行；
- 在岗时长 8 个事业部的编码、YTD 离职人数和平均在职年限；
- 在岗时长合计与 Sheet1 Row14；
- 所有硬阻断校验；
- 周二基线 -> 周三 -> 周四的链式累计。

不比较 Excel 二进制文件、单元格样式和文件元数据。

真实人员文件只在本地读取。回归摘要只写日期、行号、BU 槽位和错误类别，不写姓名、工号、原始值或期望值。

## 2. 环境要求

- Python 3.12
- MySQL 8.0 和 Redis 7（仅完整应用启动需要）
- Node.js 18+（仅前端需要）
- OA/招聘直接使用 PNG/JPG 时，需要真正支持图像输入的 OpenAI 协议兼容模型

官方 DeepSeek API 不支持图像输入。只有 DeepSeek 文本 key 时，不能据此宣称截图识别链路已验证。

## 3. 后端启动

### 3.1 启动依赖

可使用本机服务，也可使用 Docker：

```bash
docker run -d --name hr-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=ai_hr_reports \
  mysql:8.0

docker run -d --name hr-redis -p 6379:6379 redis:7
```

如容器名或端口已占用，应复用现有服务或改用其他端口，并同步修改 `.env`。

### 3.2 安装与配置

在 backend 仓库根目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

最小本地配置：

```env
APP_ENV=dev
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DB=ai_hr_reports
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
```

需要直接解析截图时，另行配置：

```env
LLM_VISION_API_KEY=<secret>
LLM_VISION_BASE_URL=<multimodal-provider-base-url>
LLM_VISION_MODEL=<vision-capable-model>
```

禁止把真实 key 写入代码、提交记录、测试样例或文档。

### 3.3 建表与运行

先执行 database 仓库中的 `schema.sql`，或在开发环境让 ORM 建表：

```bash
python -m scripts.init_db
bash scripts/run_dev.sh
```

**既有环境升级**：旧 schema 没有 `employee_snapshots` 和 `tenure_snapshot_metrics`。
必须先执行 `scripts/migrations/2026-07-12_add_snapshot_tables.sql` 再发布应用，
否则任何人员表上传都会因缺表失败。脚本幂等，可重复执行；内容需同步合入
database 仓库的 `schema.sql`。

验证：

- 健康检查：`http://localhost:8000/health`
- Swagger：`http://localhost:8000/docs`

`tenure_snapshot_metrics` 用于保存已验收日报里的 8 个事业部工龄汇总。导入定稿日报时，系统同时验证 `sum(BU YTD) = B10 = Sheet1 Row14`，通过后才能成为后续日期的链式基线。

真实历史数据存在人工验收的事业部人数和平均值时，应使用 `POST /reports/daily/import` 导入完整定稿日报。`POST /reports/baseline` 只有 5 个 Sheet1 累计数字，无法表达 8 个事业部平均值，不应替代完整定稿基线。

## 4. 前端启动

在 frontend 仓库根目录执行：

```bash
npm install
npm run dev
```

访问 `http://localhost:5173`。

当前前端仓库主要使用模拟数据展示页面；后端真链路应优先通过 Swagger 或 API 调用验证，不能把前端页面能打开等同于前后端已经联通。

## 5. 链式回归

### 5.1 目录约定

`--data-root` 下应有按日期命名的直接子目录，例如：

```text
日报/
  2026-07-07/
    人员表_20260707.xls
    离职人员报表_20260707.xls
    协议签署_20260707.png
    招聘数据_20260707.png
    员工数增减情况日报-7月_20260707.xlsx
  2026-07-08/
  2026-07-09/
```

脚本只读取日期目录第一层，不读取 `_废弃文档` 等子目录。

### 5.2 截图处理

有可用视觉模型时，可省略 `--structured-image-dir`，脚本直接走应用的视觉解析代码。

没有可用视觉模型时，应由有权限的人员在本地把当天 OA/招聘截图转成经复核的 xlsx，并放在：

```text
approved-structured-inputs/
  2026-07-08/
    协议签署_20260708.xlsx
    招聘数据_20260708.xlsx
```

这些结构化文件仍属于真实数据处理过程，不得提交到学生仓库。使用结构化替代文件只验证确定性入库和计算链，不代表视觉识别已通过。

### 5.3 执行命令

```bash
python -m scripts.run_chain_regression \
  --data-root /path/to/日报 \
  --baseline-date 2026-07-07 \
  --dates 2026-07-08 2026-07-09 \
  --structured-image-dir /path/to/approved-structured-inputs \
  --output-dir /tmp/hr-chain-regression
```

回归使用内存 SQLite，不连接生产 MySQL，不修改源文件。输出目录包含生成的日报和 `chain_regression_summary.json`。

通过条件：

- 两天均输出 `PASS`；
- `row_mismatches` 为空；
- `tenure_row_mismatches` 为空；
- `tenure_total_match` 为 `true`；
- `hard_failures` 为空。

任何一天失败后，脚本立即停止，不把失败结果保存为下一天的链式基线。
