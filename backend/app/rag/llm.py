from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class ChatModel(Protocol):
    def answer(self, question: str, evidence: Sequence[dict[str, Any]]) -> str: ...


def chat_model_is_configured() -> bool:
    parsed_url = urlparse(settings.OPENAI_BASE_URL.strip())
    return bool(
        parsed_url.scheme in {"http", "https"}
        and parsed_url.netloc
        and settings.OPENAI_MODEL_ID
        and settings.OPENAI_API_KEY
    )


class OpenAICompatibleChatModel:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.model_id = model_id or settings.OPENAI_MODEL_ID
        self.api_key = api_key or settings.OPENAI_API_KEY
        parsed_url = urlparse(self.base_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or not self.model_id
            or not self.api_key
        ):
            raise ValueError("RAG chat model configuration is incomplete")

    def answer(
        self,
        question: str,
        evidence: Sequence[dict[str, Any]],
    ) -> str:
        context_blocks = []
        for ordinal, item in enumerate(evidence, start=1):
            section = " > ".join(item.get("section_path") or [])
            context_blocks.append(
                "\n".join(
                    [
                        f"[{ordinal}] 标题：{item.get('title', '')}",
                        f"章节：{section or '全文'}",
                        f"来源：{item.get('source_path', '')}",
                        f"内容：{item.get('content', '')}",
                    ]
                )
            )
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是佳杰 BI 的内部知识助手。只能依据提供的内部证据回答，"
                            "不得使用常识补写业务口径或动态数据。每个事实后用 [1]、[2] "
                            "形式标注证据编号。证据不足时明确说明缺少什么，不要猜测。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"问题：{question}\n\n内部证据：\n"
                            + "\n\n".join(context_blocks)
                        ),
                    },
                ],
                "temperature": 0.1,
                "max_tokens": settings.RAG_CHAT_MAX_TOKENS,
            },
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        content = (
            choices[0].get("message", {}).get("content")
            if choices and isinstance(choices[0], dict)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Chat model returned an empty answer")
        return content.strip()
