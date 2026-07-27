# 单用户 V1 测试与验收

本项目采用三层验证：仓库内假数据单元/集成测试、假数据发布回归、导师本机真实材料回放。真实材料及其结构化 OCR 中间表不得进入 Git。

## 1. 仓库测试

后端：

```bash
PYTHONPATH="$PWD" python -m pytest -q
```

单独 checkout 后端仓库时，跨仓库部署契约用例会自动跳过。正式发布验证必须用与 Compose 一致的目录显式启用：

```bash
export FRONTEND_CONTEXT="/absolute/path/to/frontend"
export DATABASE_CONTEXT="/absolute/path/to/database"
PYTHONPATH="$PWD" python -m pytest tests/test_deploy_contract.py -q
```

前端：

```bash
npm test -- --run
npm run lint
npm run build
```

测试用例必须使用明确标记的假工号、假证件号和假业务值。真实口径、字段名、行号和项目族配置可以保留；真实人员值和真实汇总值不能写入断言或 fixture。

## 2. 假数据发布回归

```bash
PYTHONPATH="$PWD" python scripts/run_single_user_regression.py --mode fake
```

该模式使用内存数据库和临时目录，完整执行日报/周报预览、发布、Excel 回读和制品校验。共检查 12 个维度：

- 日报值、累计日期列、样式、合并单元格和在岗时长控制
- 周报值、样式、合并单元格和日周勾稽
- manifest、事件台账和验证报告

未指定 `--output-root` 时，全部制品随临时目录自动删除。

## 3. 导师本机回放

输入根目录、结构化截图目录和输出目录都必须位于仓库之外。输入根目录按 `YYYY-MM-DD/` 分日，每个验收日至少包含四类源文件和已验收日报；周报验收日可额外放已验收周报。

```bash
export MENTOR_DAILY_ROOT="/absolute/private/daily-root"
export APPROVED_OCR_ROOT="/absolute/private/approved-structured-images"
export REGRESSION_OUTPUT="/absolute/private/redacted-regression-output"

PYTHONPATH="$PWD" python scripts/run_single_user_regression.py \
  --mode mentor-local \
  --input-root "$MENTOR_DAILY_ROOT" \
  --start 2026-07-08 \
  --structured-image-dir "$APPROVED_OCR_ROOT" \
  --output-root "$REGRESSION_OUTPUT"
```

截图结构化文件必须经过导师确认，命名为 `协议签署_YYYYMMDD.xlsx` 和 `招聘数据_YYYYMMDD.xlsx`。回放程序不会复制源文件，只在系统临时目录生成待比对工作簿，退出时自动删除。输出目录只保留 `regression_summary.json`。

摘要只包含日期、状态、检查维度、行号/单元格坐标和错误代码，不包含单元格值、姓名、工号、证件号、OA 单号或本机输入路径：

- `passed`：计算和制品全部匹配
- `failed`：已执行，但存在行值、样式、合并或勾稽差异
- `blocked`：输入缺失、结构化 OCR 缺失或解析/计算未能执行

本机截至 2026-07-16 的验证证据：2026-07-08 至 2026-07-15 的 6 个已验收工作日日报和 1 个已验收周报经 `qwen3.7-plus` 截图结构化后全部通过；随后以 2026-07-15 定稿为基线，本地 OCR 加导师复核结构化输入重放 2026-07-16，值、累计日期列、样式、合并区域和在岗时长全部通过。两段证据合计覆盖 7 个日报和 1 个周报，只保留导师本机脱敏摘要，不把 2026-07-16 误记为 Qwen 调用。

链式顺序为 `07-08 基线 -> 07-09 -> 07-10 -> 07-13 -> 07-14 -> 07-15 -> 07-16`。每个日期只有在业务行、在岗时长和硬校验全部通过后才保存为下一工作日基线；任一日期失败即停止。

需在 `pytest` 中单独执行真实 golden 对齐用例时，必须显式设置 `HR_REAL_DAILY_ROOT`；未设置时这些 mentor-local 用例自动跳过，不会猜测或默认读取个人目录。

## 4. 隐私扫描

基础扫描检测私钥、常见 API key 和带密码的数据库 URL：

```bash
python scripts/scan_sensitive_artifacts.py .
```

发布前还应在仓库外准备敏感值清单，并执行精确扫描：

```json
{
  "employee_number": ["FAKE-EXAMPLE-ONLY"],
  "certificate_number": ["FAKE-EXAMPLE-ONLY"],
  "person_name": ["FAKE-EXAMPLE-ONLY"]
}
```

```bash
python scripts/scan_sensitive_artifacts.py . \
  --sensitive-values-file "/absolute/private/sensitive-values.json"
```

清单不得提交。扫描输出只报告文件路径和规则名，不回显命中的敏感值。

## 5. 失败处理

不要用修改预期文件的方式让回归变绿。先根据摘要中的行号或坐标定位规则、首次可见事实、累计基线、模板样式或 OCR 结构，再修代码或重新审批结构化输入。任何真实值诊断只在导师本机临时目录完成，完成后清除。
