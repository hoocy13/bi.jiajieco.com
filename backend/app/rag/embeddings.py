from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def embedding_is_configured() -> bool:
    parsed_url = urlparse(settings.RAG_EMBEDDING_BASE_URL.strip())
    return bool(
        parsed_url.scheme in {"http", "https"}
        and parsed_url.netloc
        and settings.RAG_EMBEDDING_MODEL_ID
        and settings.RAG_EMBEDDING_API_KEY
    )


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.RAG_EMBEDDING_BASE_URL).rstrip("/")
        self.model_id = model_id or settings.RAG_EMBEDDING_MODEL_ID
        self.api_key = api_key or settings.RAG_EMBEDDING_API_KEY
        self.dimensions = (
            settings.RAG_EMBEDDING_DIMENSIONS
            if dimensions is None
            else dimensions
        )
        if not self.base_url or not self.model_id or not self.api_key:
            raise ValueError(
                "RAG embedding configuration is incomplete; configure base URL, model ID and API key"
            )
        parsed_url = urlparse(self.base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError(
                "RAG embedding base URL must be a valid HTTP(S) URL"
            )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        with httpx.Client(timeout=settings.OPENAI_TIMEOUT_SECONDS) as client:
            for offset in range(0, len(texts), settings.RAG_EMBEDDING_BATCH_SIZE):
                batch = list(texts[offset : offset + settings.RAG_EMBEDDING_BATCH_SIZE])
                payload: dict = {
                    "model": self.model_id,
                    "input": batch,
                }
                if self.dimensions > 0:
                    payload["dimensions"] = self.dimensions
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                rows = sorted(
                    result.get("data", []),
                    key=lambda row: row.get("index", 0),
                )
                batch_vectors = [row.get("embedding") for row in rows]
                if len(batch_vectors) != len(batch) or any(
                    not isinstance(vector, list) for vector in batch_vectors
                ):
                    raise RuntimeError(
                        "Embedding service returned an invalid response shape"
                    )
                vectors.extend(batch_vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]
