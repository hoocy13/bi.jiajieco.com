from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient, models

from app.core.config import settings


@dataclass(frozen=True)
class VectorChunk:
    point_id: str
    vector: list[float]
    payload: dict[str, Any]


class QdrantKnowledgeStore:
    def __init__(
        self,
        *,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.client = client or QdrantClient(
            url=settings.RAG_QDRANT_URL,
            api_key=settings.RAG_QDRANT_API_KEY or None,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        )
        self.collection_name = collection_name or settings.RAG_QDRANT_COLLECTION

    def ensure_collection(self, vector_size: int) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            for field_name, field_schema in (
                ("knowledge_base_id", models.PayloadSchemaType.KEYWORD),
                ("document_id", models.PayloadSchemaType.KEYWORD),
                ("document_version_id", models.PayloadSchemaType.KEYWORD),
                ("status", models.PayloadSchemaType.KEYWORD),
                ("allowed_roles", models.PayloadSchemaType.KEYWORD),
            ):
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                )
            return

        collection = self.client.get_collection(self.collection_name)
        vectors_config = collection.config.params.vectors
        existing_size = getattr(vectors_config, "size", None)
        if existing_size is not None and existing_size != vector_size:
            raise ValueError(
                f"Qdrant collection vector size is {existing_size}, embedding returned {vector_size}"
            )

    def stage_version(self, chunks: list[VectorChunk]) -> None:
        if not chunks:
            raise ValueError("Cannot index an empty document")
        self.ensure_collection(len(chunks[0].vector))
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=chunk.point_id,
                    vector=chunk.vector,
                    payload=chunk.payload,
                )
                for chunk in chunks
            ],
            wait=True,
        )

    @staticmethod
    def _match(field: str, value: str) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key=field,
                    match=models.MatchValue(value=value),
                )
            ]
        )

    def activate_version(self, document_id: UUID, document_version_id: UUID) -> None:
        version_filter = self._match("document_version_id", str(document_version_id))
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"status": "active"},
            points=version_filter,
            wait=True,
        )
        old_versions_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            ],
            must_not=[
                models.FieldCondition(
                    key="document_version_id",
                    match=models.MatchValue(value=str(document_version_id)),
                )
            ],
        )
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"status": "archived"},
            points=old_versions_filter,
            wait=True,
        )

    def delete_version(self, document_version_id: UUID) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=self._match(
                    "document_version_id",
                    str(document_version_id),
                )
            ),
            wait=True,
        )

    def archive_document(self, document_id: UUID) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"status": "archived"},
            points=self._match("document_id", str(document_id)),
            wait=True,
        )

    def search(
        self,
        vector: list[float],
        *,
        knowledge_base_id: UUID,
        roles: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="knowledge_base_id",
                    match=models.MatchValue(value=str(knowledge_base_id)),
                ),
                models.FieldCondition(
                    key="status",
                    match=models.MatchValue(value="active"),
                ),
                models.FieldCondition(
                    key="allowed_roles",
                    match=models.MatchAny(any=roles),
                ),
            ]
        )
        points = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        ).points
        return [
            {
                "score": float(point.score),
                **(point.payload or {}),
            }
            for point in points
        ]
