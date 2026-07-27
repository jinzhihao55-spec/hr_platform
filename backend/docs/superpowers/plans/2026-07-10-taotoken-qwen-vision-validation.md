# TaoToken Qwen Vision Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TaoToken `qwen3.5-omni-flash` a testable screenshot parser, prove its extracted tables against manually verified XLSX files, and replay the Wednesday/Thursday HR daily-report chain from a Tuesday baseline.

**Architecture:** Keep the existing OpenAI-compatible vision client and Omni streaming path. Add a strict JSON-object parser that tolerates only optional Markdown fences, omit `max_tokens` for Qwen visual calls, and leave all business calculations deterministic. Validate screenshots once into temporary XLSX files, compare those files cell-by-cell with local gold files, then feed the same generated XLSX files into the existing chain regression runner to avoid duplicate billable calls.

**Tech Stack:** Python 3.12, pytest, OpenAI Python SDK, pandas, existing `image_parser` and `run_chain_regression.py`.

## Global Constraints

- Never write the supplied TaoToken API key to Git, `.env`, test fixtures, command output, or logs.
- Do not copy real HR screenshots or extracted row values into the repository.
- Qwen only transcribes screenshots; existing deterministic Python computes every business metric.
- Excel remains the formal fallback whenever visual extraction fails validation.
- Production code changes must follow red-green-refactor TDD.
- Validation output may contain counts, field names, row indexes, and mismatch categories, but not raw HR values.

---

### Task 1: Strict Qwen Vision Response Parsing

**Files:**
- Create: `tests/test_llm_client_vision.py`
- Modify: `app/llm/llm_client.py`

**Interfaces:**
- Produces: `_parse_vision_json(content: str) -> dict[str, Any]`
- Consumes: the complete text returned by `LLMClient._create_chat()`
- Preserves: `LLMClient.vision_json_chat(...) -> dict[str, Any]`

- [x] **Step 1: Write failing parser tests**

Add tests for pure JSON, standard fenced JSON, the observed trailing-only closing fence, explanatory trailing text, two JSON objects, missing `headers`, invalid row elements, and row keys outside `headers`.

```python
def test_parse_vision_json_accepts_observed_trailing_fence():
    result = _parse_vision_json(
        '\n{"headers":["姓名"],"rows":[{"姓名":"测试"}]}\n```'
    )
    assert result["headers"] == ["姓名"]


@pytest.mark.parametrize(
    "content",
    [
        '{"headers":["A"],"rows":[]}说明',
        '{"headers":["A"],"rows":{}}',
        '{"headers":["A"],"rows":[{"B":1}]}',
        '{"headers":["A"],"rows":[]} {"headers":[],"rows":[]}',
    ],
)
def test_parse_vision_json_rejects_untrusted_shapes(content):
    with pytest.raises(ValueError):
        _parse_vision_json(content)
```

- [x] **Step 2: Run parser tests and verify RED**

Run:

```bash
pytest -q tests/test_llm_client_vision.py
```

Expected: collection/import failure because `_parse_vision_json` does not exist.

- [x] **Step 3: Implement the minimal strict parser**

Add to `app/llm/llm_client.py`:

```python
def _parse_vision_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        first_line, separator, remainder = text.partition("\n")
        if not separator or first_line.strip().lower() not in {"```", "```json"}:
            raise ValueError("视觉模型返回了不支持的 Markdown 围栏")
        text = remainder.strip()
    if text.endswith("```"):
        text = text[:-3].rstrip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("视觉模型未返回单一 JSON 对象") from exc

    if not isinstance(result, dict):
        raise ValueError("视觉模型返回值必须是 JSON 对象")
    headers = result.get("headers")
    rows = result.get("rows")
    if not isinstance(headers, list) or not headers or any(
        not isinstance(header, str) or not header.strip() for header in headers
    ):
        raise ValueError("视觉模型 headers 必须是非空字符串列表")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("视觉模型 rows 必须是对象列表")
    allowed = set(headers)
    if any(set(row) - allowed for row in rows):
        raise ValueError("视觉模型数据行包含表头之外的字段")
    return result
```

Replace `json.loads(content or "{}")` in `vision_json_chat()` with `_parse_vision_json(content)`.

- [x] **Step 4: Run parser tests and verify GREEN**

Run:

```bash
pytest -q tests/test_llm_client_vision.py
```

Expected: all parser tests pass.

---

### Task 2: Qwen Request Contract and Default Configuration

**Files:**
- Modify: `tests/test_llm_client_vision.py`
- Modify: `app/llm/llm_client.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `settings.llm_vision_model`
- Produces: a Qwen vision request without `max_tokens`
- Preserves: non-Qwen visual calls with their existing `max_tokens` limit

- [x] **Step 1: Write failing request-contract tests**

Use `object.__new__(LLMClient)` and a captured `_create_chat` replacement so no network call occurs.

```python
def test_qwen_vision_request_omits_max_tokens(monkeypatch):
    client = object.__new__(LLMClient)
    client._vision_client = object()
    captured = {}
    monkeypatch.setattr(settings, "llm_vision_model", "qwen3.5-omni-flash")
    client._create_chat = lambda _, **kwargs: captured.update(kwargs) or (
        '{"headers":["A"],"rows":[]}'
    )

    client.vision_json_chat("输出 JSON", "ZmFrZQ==")

    assert "max_tokens" not in captured
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"][1]["content"][0]["type"] == "image_url"
```

Add a companion test asserting a non-Qwen visual model still receives `max_tokens=4096`.

- [x] **Step 2: Run request tests and verify RED**

Run:

```bash
pytest -q tests/test_llm_client_vision.py -k 'request or max_tokens'
```

Expected: Qwen test fails because current code always includes `max_tokens`.

- [x] **Step 3: Implement minimal model-specific request kwargs**

In `vision_json_chat()` build kwargs first, then conditionally add the limit:

```python
request: dict[str, Any] = {
    "model": model,
    "messages": messages,
    "temperature": temperature,
    "response_format": {"type": "json_object"},
}
if not model.lower().startswith("qwen"):
    request["max_tokens"] = max_tokens
content = self._create_chat(self._vision_client, **request)
```

- [x] **Step 4: Change only the default visual model**

Set `LLM_VISION_MODEL=qwen3.5-omni-flash` in `.env.example` and the matching default in `app/config.py`. Update README examples and remove wording that presents `ernie-5.0` as the active default. Keep the TaoToken Base URL unchanged and keep the key blank.

- [x] **Step 5: Run focused and full tests**

Run:

```bash
pytest -q tests/test_llm_client_vision.py
pytest -q
```

Expected: focused tests pass; full suite has no new failures.

---

### Task 3: Real Screenshot Accuracy and Wednesday/Thursday Chain

**Files:**
- No repository files changed.
- Read-only real inputs: `/Users/andrewhua/Desktop/Claude Project/project/日报/2026-07-08` and `2026-07-09`
- Read-only gold files: `/Users/andrewhua/Desktop/Claude Project/tmp_groupa_regression/structured/2026-07-08` and `2026-07-09`
- Temporary outputs: a new directory under `/Users/andrewhua/Desktop/Claude Project/tmp_groupa_regression/`

**Interfaces:**
- Consumes: production `image_parser.convert_to_xlsx()` using environment-only `LLM_VISION_*`
- Produces: four temporary model-generated XLSX files and a redacted accuracy summary
- Feeds: existing `scripts/run_chain_regression.py`

- [x] **Step 1: Run four billable screenshot extractions once**

Use an interactive `read -s` shell prompt for the token. Set in-process variables only:

```bash
LLM_VISION_BASE_URL=https://taotoken.net/api/v1
LLM_VISION_MODEL=qwen3.5-omni-flash
LLM_VISION_API_KEY=$TAO_TOKEN
```

Call `convert_to_xlsx()` for agreement and recruitment screenshots on 2026-07-08 and 2026-07-09. Write generated files only to the temporary validation directory.

- [x] **Step 2: Compare generated tables with gold without printing values**

For each image/gold pair:

1. Normalize blank cells to `None` and trim string whitespace.
2. Require identical column order and row count.
3. Compare each aligned cell.
4. Print only `header_match`, `row_count_match`, `cell_count`, `mismatch_count`, `missing_rows`, `extra_rows`, and elapsed time.

Expected gate:

```text
header_match=true
row_count_match=true
mismatch_count=0 for critical fields
missing_rows=0
extra_rows=0
```

If a table fails, stop before the chain replay and report the field/row indexes only.

- [x] **Step 3: Replay Tuesday baseline -> Wednesday -> Thursday**

Use the manually verified Tuesday 2026-07-07 XLSX files as baseline overrides. Use the four model-generated XLSX files from Step 1 as the Wednesday/Thursday structured-image directory, then run:

```bash
python -m scripts.run_chain_regression \
  --data-root '/Users/andrewhua/Desktop/Claude Project/project/日报' \
  --baseline-date 2026-07-07 \
  --dates 2026-07-08 2026-07-09 \
  --structured-image-dir '/Users/andrewhua/Desktop/Claude Project/tmp_groupa_regression/qwen_vision_20260710/structured' \
  --output-dir '/Users/andrewhua/Desktop/Claude Project/tmp_groupa_regression/qwen_vision_20260710/output'
```

Expected:

```text
2026-07-08 PASS: mismatch_rows=none
2026-07-09 PASS: mismatch_rows=none
```

- [x] **Step 4: Verify repository hygiene**

Run:

```bash
git diff --check
git status --short
rg -l 'sk-[A-Za-z0-9_-]{16,}' --glob '!**/.git/**' .
```

Expected: no new secret-containing file; only intentional code/test/doc changes; real samples remain outside the repository.

- [x] **Step 5: Report evidence separately**

Final report must distinguish:

1. unit-test and request-format compatibility;
2. table-recognition accuracy by image type/date;
3. downstream Wednesday/Thursday chain result;
4. residual limitation that TaoToken is a third-party proxy and Excel remains the formal fallback.
