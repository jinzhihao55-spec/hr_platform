from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.llm.llm_client import LLMClient, _parse_vision_json


def test_parse_vision_json_accepts_plain_object() -> None:
    result = _parse_vision_json('{"headers":["A"],"rows":[{"A":"1"}]}')

    assert result == {"headers": ["A"], "rows": [{"A": "1"}]}


def test_parse_vision_json_accepts_standard_json_fence() -> None:
    result = _parse_vision_json(
        '```json\n{"headers":["A"],"rows":[{"A":"1"}]}\n```'
    )

    assert result["rows"] == [{"A": "1"}]


def test_parse_vision_json_accepts_observed_trailing_fence() -> None:
    result = _parse_vision_json(
        '\n{"headers":["A"],"rows":[{"A":"1"}]}\n```'
    )

    assert result["headers"] == ["A"]


@pytest.mark.parametrize(
    "content",
    [
        '{"headers":["A"],"rows":[]}说明',
        '{"headers":["A"],"rows":[]} {"headers":["A"],"rows":[]}',
        '{"rows":[]}',
        '{"headers":["A"],"rows":{}}',
        '{"headers":["A"],"rows":["not-an-object"]}',
        '{"headers":["A"],"rows":[{"B":1}]}',
        '[]',
    ],
)
def test_parse_vision_json_rejects_untrusted_output(content: str) -> None:
    with pytest.raises(ValueError):
        _parse_vision_json(content)


def _capture_vision_request(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> dict:
    client = object.__new__(LLMClient)
    client._vision_client = object()
    captured: dict = {}

    def fake_create(_client, **kwargs):
        captured.update(kwargs)
        return '{"headers":["A"],"rows":[]}'

    monkeypatch.setattr(settings, "llm_vision_model", model)
    monkeypatch.setattr(client, "_create_chat", fake_create)
    client.vision_json_chat("输出 JSON", "ZmFrZQ==")
    return captured


def test_qwen_vision_request_omits_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_vision_request(monkeypatch, "qwen3.5-omni-flash")

    assert "max_tokens" not in captured
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"][1]["content"][0]["type"] == "image_url"


def test_non_qwen_vision_request_keeps_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_vision_request(monkeypatch, "ernie-5.0")

    assert captured["max_tokens"] == 4096


def test_omni_stream_content_is_concatenated() -> None:
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=part))]
        )
        for part in ('{"headers":["A"],', '"rows":[]}')
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            return iter(chunks)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    client = object.__new__(LLMClient)

    content = client._create_chat(
        fake_client,
        model="qwen3.5-omni-flash",
        messages=[],
    )

    assert content == '{"headers":["A"],"rows":[]}'


def test_build_client_applies_configured_timeout_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """视觉/文本请求必须有显式超时与重试上限，防止挂住上传接口。"""
    from app.llm.llm_client import _build_client

    monkeypatch.setattr(settings, "llm_timeout_seconds", 45.0)
    monkeypatch.setattr(settings, "llm_max_retries", 1)

    client = _build_client("test-key", "https://example.invalid/v1", "文本")

    assert client is not None
    assert client.timeout == 45.0
    assert client.max_retries == 1


def test_default_llm_endpoints_use_official_qwen(monkeypatch) -> None:
    for key in (
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_VISION_BASE_URL",
        "LLM_VISION_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    defaults = Settings(_env_file=None)

    assert defaults.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert defaults.llm_model == "qwen3.7-plus"
    assert defaults.llm_vision_base_url == defaults.llm_base_url
    assert defaults.llm_vision_model == "qwen3.7-plus"
