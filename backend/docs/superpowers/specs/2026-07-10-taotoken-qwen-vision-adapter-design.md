# TaoToken Qwen 视觉识别适配设计

日期：2026-07-10  
状态：已实施并验证
目标分支：`codex/fix-a-group-validation-chain-20260710`

## 1. 目标

在不改变人事报表确定性计算链路的前提下，将截图解析的默认视觉模型从
`ernie-5.0` 切换为 TaoToken 提供的 `qwen3.5-omni-flash`，并用真实 HR 截图
验证其表格提取准确性。

视觉模型只负责把截图转成 `headers + rows`。人数、司龄、增减和汇总仍由现有
Python 代码计算，视觉结果不得直接成为最终业务数字。

## 2. 已验证事实

1. TaoToken `/api/v1/models` 当前返回 `qwen3.5-omni-flash` 和
   `qwen3.7-max`，不返回 `qwen3.7-plus`。
2. `qwen3.7-plus` 请求返回 `model_not_found`。
3. `qwen3.7-max` 通过 TaoToken Chat Completions 接收标准 Base64
   `image_url` 时返回 `Unexpected item type in content`，不能用于当前图片链路。
4. `qwen3.5-omni-flash` 能读取真实 OA 截图，并返回包含 7 个表头和 10 行数据的
   JSON 对象。
5. 该模型实测会在有效 JSON 后附加一个 closing Markdown fence（```），导致
   当前 `json.loads()` 抛出 `JSONDecodeError`。
6. 现有 `LLMClient._create_chat()` 已经包含 Omni 模型的流式拼接逻辑，本次不
   重写该部分。

以上探针没有把 token、请求体或识别出的人员信息写入仓库。

## 3. 方案选择

采用最小适配方案：

- TaoToken Base URL 保持 `https://taotoken.net/api/v1`；
- 默认视觉模型改为 `qwen3.5-omni-flash`；
- 保留 OpenAI 兼容的 `image_url` 和 `response_format=json_object` 请求；
- Qwen 视觉请求不发送 `max_tokens`，避免 JSON 被截断；
- 增加只处理 Markdown 围栏的严格 JSON 解析；
- 增加输出结构校验和自动化测试；
- Excel 输入继续作为正式、确定性的首选路径。

不建设通用 Provider Adapter。当前只有一个已验证可用的 TaoToken 视觉模型，
为多个供应商提前抽象会扩大范围。

## 4. 代码改动

### 4.1 配置

修改：

- `app/config.py`
- `.env.example`
- 与视觉配置直接相关的 README 说明

默认值：

```env
LLM_VISION_BASE_URL=https://taotoken.net/api/v1
LLM_VISION_MODEL=qwen3.5-omni-flash
LLM_VISION_API_KEY=
```

API Key 仍只从环境变量读取，禁止写入 Git、测试夹具、日志或文档。

### 4.2 请求参数

`vision_json_chat()` 按模型构造参数：

- Qwen 模型：不传 `max_tokens`；
- 其他已有视觉模型：保留当前 `max_tokens` 行为；
- 所有模型继续使用 `temperature=0` 和
  `response_format={"type": "json_object"}`。

不修改文本模型 `json_chat()` 的参数，避免影响现有 DeepSeek 文本链路。

### 4.3 JSON 解析

新增一个小型内部函数，只允许以下返回形式：

1. 纯 JSON 对象；
2. JSON 对象外包一层标准 Markdown fence；
3. 实测出现的“JSON 对象 + closing fence”。

处理顺序：

1. 去除首尾空白；
2. 最多移除一个 opening fence（可带 `json` 标记）；
3. 最多移除一个 closing fence；
4. 对剩余完整字符串执行 `json.loads()`；
5. 校验顶层必须是对象；
6. 校验 `headers` 是非空字符串列表，`rows` 是对象列表；
7. 每行不得出现 `headers` 之外的字段。

以下情况必须失败，不做“尽量提取”：

- JSON 前后存在解释性文字；
- 返回两个 JSON 对象；
- 缺少 `headers` 或 `rows`；
- `rows` 中出现非对象元素；
- JSON 被截断；
- 返回空表头。

这样可以修复 TaoToken 的围栏兼容问题，但不会把任意混杂文本静默当成业务数据。

## 5. 数据流

```text
PNG/JPG
  -> image_parser 读取并转 Base64
  -> LLMClient 通过 TaoToken 调用 qwen3.5-omni-flash
  -> Omni 流式响应拼接
  -> 严格移除可接受的 Markdown fence
  -> JSON 与 headers/rows 结构校验
  -> DataFrame 后处理
  -> 临时 XLSX
  -> 现有确定性解析与计算流水线
```

任何阶段失败，均停止截图输入并提示改传 Excel；不得生成猜测数据。

## 6. 自动化测试

遵循 TDD，先写失败测试，再修改生产代码。

新增 `tests/test_llm_client_vision.py`，覆盖：

1. 当前 `JSON + closing fence` 输入在旧实现中失败；修复后成功；
2. 标准 fenced JSON 成功；
3. 纯 JSON 成功；
4. JSON 后有说明文字时失败；
5. 两个 JSON 对象时失败；
6. 缺少 `headers` 或 `rows` 时失败；
7. 行出现额外字段时失败；
8. `qwen3.5-omni-flash` 请求不包含 `max_tokens`；
9. 非 Qwen 模型仍保留 `max_tokens`；
10. Omni 流式内容能够正确拼接并进入同一解析器。

测试使用 fake client，不访问网络、不包含 API Key 或真实 HR 数据。

## 7. 真实样本验收

自动化测试通过后，在本地一次性环境变量中使用限额 token，验证：

- `2026-07-08/协议签署_20260708.png`；
- `2026-07-08/招聘数据_20260708.png`。

对照物为本机人工核对过的结构化 XLSX，不进入 Git。验收输出只包含：

- 表头是否一致；
- 行数是否一致；
- 总单元格数与不一致单元格数；
- 漏行数；
- 增造行数；
- 请求耗时。

不打印姓名、单号、日期等原始值。

通过门槛：

| 指标 | 门槛 |
|---|---:|
| JSON 与结构校验 | 100% |
| 表头与行数 | 100% |
| 关键字段准确率 | 100% |
| 全部单元格准确率 | >= 99.5% |
| 漏行 / 增造行 | 0 |

若任一关键字段不一致，则记录该模型不满足自动入库条件；Excel 路径继续作为正式
输入，截图入口不得宣称可用于无人复核的生产处理。

## 8. 非目标

- 不把 API Key 写入 `.env.example` 或仓库；
- 不训练或微调 Qwen；
- 不增加多模型自动路由；
- 不重写现有报表计算；
- 不把真实 HR 样本复制给学生；
- 不在本次实现中接入阿里云百炼或其他供应商；
- 不因视觉模型返回结果而自动修改最终报表口径。

## 9. 完成定义

1. 设计中的测试先红后绿；
2. 全量 pytest 无新增失败；
3. 配置默认值和文档一致；
4. 仓库中不存在本次 token 或真实 HR 数据副本；
5. 两张真实样本得到结构化验收结果；
6. 最终报告明确区分“接口兼容成功”和“业务准确率达标”。
