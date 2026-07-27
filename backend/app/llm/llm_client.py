"""LLM 客户端（OpenAI 协议兼容，供应商无关）。强制 JSON 结构化输出。

文本与视觉分开配置、各自独立的 client：
  - 文本（json_chat）：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL，默认阿里云百炼 Qwen。
  - 视觉（vision_json_chat）：LLM_VISION_API_KEY / LLM_VISION_BASE_URL / LLM_VISION_MODEL。
    默认通过阿里云百炼 OpenAI 兼容接口调用 qwen3.7-plus。
    留空则视觉不启用（vision_enabled=False）——图像解析（image_parser.py）没有
    本地 OCR 兜底，会直接报错并提示改传 Excel。

密钥仅从环境读取——不得硬编码。若未配置密钥，对应客户端视为"禁用"；
调用方必须优雅降级（确定性流水线绝不依赖 LLM 产生任何数字——§0 最高原则 第2条）。
"""
from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _parse_vision_json(content: str) -> dict[str, Any]:
    """Parse one trusted table object, tolerating only optional JSON fences."""
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


def _build_client(api_key: str, base_url: str, label: str):
    if not api_key:
        return None
    try:
        import httpx
        from openai import OpenAI

        # 显式传入 http_client，避免 openai 旧版与 httpx>=0.28 的 proxies 参数冲突
        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.Client(),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    except Exception as exc:  # pragma: no cover
        log.warning("LLM 客户端初始化失败（%s）: %s", label, exc)
        return None


class LLMClient:
    def __init__(self) -> None:
        self._client = _build_client(settings.llm_api_key, settings.llm_base_url, "文本")
        # 视觉客户端未单独配置 key 时不回退到文本 key——两者可能指向不同供应商/
        # 中转，误用文本 key 去访问视觉的 base_url 大概率是认证失败而非"能用"。
        self._vision_client = _build_client(
            settings.llm_vision_api_key, settings.llm_vision_base_url, "视觉"
        )

    @property
    def enabled(self) -> bool:
        """文本客户端是否可用。"""
        return self._client is not None

    @property
    def vision_enabled(self) -> bool:
        """视觉客户端是否可用（需 LLM_VISION_API_KEY + LLM_VISION_BASE_URL 均已配置）。"""
        return self._vision_client is not None

    @staticmethod
    def _is_omni_model(model: str) -> bool:
        """Qwen-Omni 系列只使用流式输出。"""
        return "omni" in model.lower()

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        """解析模型返回：容忍 markdown 代码块、JSON 后多余文本（Extra data）。"""
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
            text = text.removesuffix("```").strip()
        try:
            return json.loads(text or "{}")
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text)
            if isinstance(obj, dict):
                return obj
            raise

    def _create_chat(self, client, **kwargs: Any):
        """封装 chat.completions.create，并将 Omni 流式结果拼成完整文本。"""
        model = kwargs.get("model", "")
        if self._is_omni_model(model):
            kwargs["stream"] = True
            chunks: list[str] = []
            for event in client.chat.completions.create(**kwargs):
                delta = event.choices[0].delta if event.choices else None
                if delta is not None and getattr(delta, "content", None):
                    chunks.append(delta.content)
            return "".join(chunks)
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or "{}"

    def vision_json_chat(
        self,
        system_prompt: str,
        image_b64: str,
        image_mime: str = "image/jpeg",
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """调用视觉模型，将图像中的表格提取为 JSON。
        返回结构：{"headers": [...], "rows": [{"col": val, ...}, ...]}
        视觉客户端未启用时抛 RuntimeError。
        """
        if not self.vision_enabled:
            raise RuntimeError(
                "视觉 LLM 客户端已禁用（未配置 LLM_VISION_API_KEY / LLM_VISION_BASE_URL）。"
            )
        model = settings.llm_vision_model
        request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_mime};base64,{image_b64}"
                            },
                        },
                        {
                            "type": "text",
                            "text": "请严格按 JSON 格式输出上方表格的表头与数据行。",
                        },
                    ],
                },
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if not model.lower().startswith("qwen"):
            request["max_tokens"] = max_tokens

        content = self._create_chat(self._vision_client, **request)
        return _parse_vision_json(content)

    def json_chat(
        self,
        system_prompt: str,
        user_content: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """调用文本模型，强制 JSON 输出。返回解析后的 dict。

        客户端禁用时抛 RuntimeError——由调用方决定回退（流水线不得编造数字）。
        """
        if not self.enabled:
            raise RuntimeError("LLM 客户端已禁用（未配置 API key）。")

        content = self._create_chat(
            self._client,
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},  # 强约束 JSON 结构化输出
        )
        return self._parse_json_content(content or "{}")


_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMClient()
    return _singleton
