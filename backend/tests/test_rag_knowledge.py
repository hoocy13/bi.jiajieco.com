import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.rag.db import RagBase
from app.core.config import settings
from app.rag.embeddings import OpenAICompatibleEmbeddingProvider
from app.rag.ingestion import archive_inactive_documents, ingest_document
from app.rag.knowledge_loader import (
    KnowledgeDocument,
    scan_active_knowledge,
    split_knowledge_document,
)
from app.rag.models import RagDocumentVersion, RagIngestionJob
from app.rag.vector_store import QdrantKnowledgeStore, VectorChunk


class FakeEmbeddingProvider:
    def embed_documents(self, texts):
        return [[float(index + 1), 0.5, 0.25] for index, _ in enumerate(texts)]

    def embed_query(self, text):
        return [1.0, 0.5, 0.25]


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    def embed_documents(self, texts):
        raise RuntimeError("embedding failed")


class FakeVectorStore:
    def __init__(self):
        self.staged = []
        self.activations = []
        self.deleted = []
        self.archived = []

    def stage_version(self, chunks):
        self.staged.extend(chunks)

    def activate_version(self, document_id, version_id):
        self.activations.append((document_id, version_id))

    def delete_version(self, version_id):
        self.deleted.append(version_id)

    def archive_document(self, document_id):
        self.archived.append(document_id)


class RagKnowledgeLoaderTest(unittest.TestCase):
    def test_scans_only_active_supported_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            (root / "metrics").mkdir()
            (root / "evaluation").mkdir()
            (root / "metrics" / "active.yaml").write_text(
                "id: active_metric\nname: Active\nstatus: active\n",
                encoding="utf-8",
            )
            (root / "metrics" / "draft.yaml").write_text(
                "id: draft_metric\nname: Draft\nstatus: draft\n",
                encoding="utf-8",
            )
            (root / "evaluation" / "questions.yaml").write_text(
                "- id: eval-1\n  question: test\n",
                encoding="utf-8",
            )

            documents = scan_active_knowledge(root)

            self.assertEqual([document.stable_id for document in documents], ["active_metric"])

    def test_splits_markdown_by_heading_and_size(self) -> None:
        document = KnowledgeDocument(
            stable_id="playbook",
            title="排查流程",
            source_path="playbooks/example.md",
            content="# 排查流程\n\n## 第一步\n" + "库存异常。" * 80,
            allowed_roles=("admin", "analyst"),
            status="active",
        )

        chunks = split_knowledge_document(
            document,
            chunk_size=120,
            chunk_overlap=20,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.content for chunk in chunks))
        self.assertEqual(chunks[0].section_path[0], "排查流程")


class EmbeddingProviderTest(unittest.TestCase):
    @patch("app.rag.embeddings.httpx.Client")
    def test_batches_openai_compatible_embedding_requests(self, client_class) -> None:
        original_batch_size = settings.RAG_EMBEDDING_BATCH_SIZE
        settings.RAG_EMBEDDING_BATCH_SIZE = 2
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [2.0]}]},
            {"data": [{"index": 0, "embedding": [3.0]}, {"index": 1, "embedding": [4.0]}]},
            {"data": [{"index": 0, "embedding": [5.0]}]},
        ]
        client = client_class.return_value.__enter__.return_value
        client.post.return_value = response
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://embedding.example/v1",
            model_id="embedding-model",
            api_key="test-only",
            dimensions=1024,
        )
        try:
            vectors = provider.embed_documents(["a", "b", "c", "d", "e"])
        finally:
            settings.RAG_EMBEDDING_BATCH_SIZE = original_batch_size

        self.assertEqual(vectors, [[1.0], [2.0], [3.0], [4.0], [5.0]])
        self.assertEqual(client.post.call_count, 3)
        self.assertTrue(
            all(
                call.kwargs["json"]["dimensions"] == 1024
                for call in client.post.call_args_list
            )
        )


class RagIngestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        RagBase.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.vector_store = FakeVectorStore()
        self.document = KnowledgeDocument(
            stable_id="inventory_turnover_days",
            title="品牌估算周转天数",
            source_path="metrics/inventory-turnover-days.yaml",
            content="定义：使用当前可用库存估算周转天数。",
            allowed_roles=("admin", "analyst"),
            status="active",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_indexes_once_and_skips_unchanged_content(self) -> None:
        first = ingest_document(
            self.db,
            self.document,
            FakeEmbeddingProvider(),
            self.vector_store,
        )
        second = ingest_document(
            self.db,
            self.document,
            FakeEmbeddingProvider(),
            self.vector_store,
        )

        self.assertEqual(first["status"], "indexed")
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(len(self.vector_store.activations), 1)
        self.assertEqual(
            self.db.scalar(select(RagDocumentVersion).where(RagDocumentVersion.status == "active")).version,
            1,
        )

    def test_creates_new_version_and_archives_previous_version(self) -> None:
        ingest_document(
            self.db,
            self.document,
            FakeEmbeddingProvider(),
            self.vector_store,
        )
        changed_document = KnowledgeDocument(
            **{
                **self.document.__dict__,
                "content": "定义：使用季度天数、净销售数量和当前可用库存估算。",
            }
        )

        result = ingest_document(
            self.db,
            changed_document,
            FakeEmbeddingProvider(),
            self.vector_store,
        )

        versions = self.db.scalars(
            select(RagDocumentVersion).order_by(RagDocumentVersion.version)
        ).all()
        self.assertEqual(result["status"], "indexed")
        self.assertEqual([version.status for version in versions], ["archived", "active"])
        self.assertEqual([version.version for version in versions], [1, 2])

    def test_records_failed_job_without_leaving_active_version(self) -> None:
        with self.assertRaises(RuntimeError):
            ingest_document(
                self.db,
                self.document,
                FailingEmbeddingProvider(),
                self.vector_store,
            )

        version = self.db.scalar(select(RagDocumentVersion))
        job = self.db.scalar(select(RagIngestionJob))
        self.assertEqual(version.status, "failed")
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error_code, "RuntimeError")
        self.assertEqual(self.vector_store.deleted, [version.id])

    def test_archives_document_removed_from_active_knowledge(self) -> None:
        ingest_document(
            self.db,
            self.document,
            FakeEmbeddingProvider(),
            self.vector_store,
        )

        archived_count = archive_inactive_documents(
            self.db,
            self.vector_store,
            active_stable_ids=set(),
        )

        version = self.db.scalar(select(RagDocumentVersion))
        self.assertEqual(archived_count, 1)
        self.assertEqual(version.status, "archived")
        self.assertEqual(len(self.vector_store.archived), 1)


class QdrantKnowledgeStoreTest(unittest.TestCase):
    def test_filters_search_results_by_role(self) -> None:
        client = QdrantClient(":memory:")
        store = QdrantKnowledgeStore(client=client, collection_name="role-filter-test")
        knowledge_base_id = uuid4()
        document_id = uuid4()
        version_id = uuid4()
        store.stage_version(
            [
                VectorChunk(
                    point_id=str(uuid4()),
                    vector=[1.0, 0.0, 0.0],
                    payload={
                        "knowledge_base_id": str(knowledge_base_id),
                        "document_id": str(document_id),
                        "document_version_id": str(version_id),
                        "status": "active",
                        "allowed_roles": ["admin", "analyst"],
                        "content": "共享知识",
                    },
                ),
                VectorChunk(
                    point_id=str(uuid4()),
                    vector=[0.9, 0.1, 0.0],
                    payload={
                        "knowledge_base_id": str(knowledge_base_id),
                        "document_id": str(document_id),
                        "document_version_id": str(version_id),
                        "status": "active",
                        "allowed_roles": ["admin"],
                        "content": "管理员知识",
                    },
                ),
            ]
        )

        results = store.search(
            [1.0, 0.0, 0.0],
            knowledge_base_id=knowledge_base_id,
            roles=["analyst"],
            limit=5,
        )

        self.assertEqual([result["content"] for result in results], ["共享知识"])
        client.close()


if __name__ == "__main__":
    unittest.main()
