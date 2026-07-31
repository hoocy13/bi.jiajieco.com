import unittest
from unittest.mock import patch

from app.core.config import settings
from app.rag.infrastructure import rag_infrastructure_health


class RagInfrastructureHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_values = {
            "RAG_ENABLED": settings.RAG_ENABLED,
            "RAG_DATABASE_URL": settings.RAG_DATABASE_URL,
            "RAG_REDIS_URL": settings.RAG_REDIS_URL,
            "RAG_QDRANT_URL": settings.RAG_QDRANT_URL,
            "RAG_EMBEDDING_BASE_URL": settings.RAG_EMBEDDING_BASE_URL,
            "RAG_EMBEDDING_MODEL_ID": settings.RAG_EMBEDDING_MODEL_ID,
            "RAG_EMBEDDING_API_KEY": settings.RAG_EMBEDDING_API_KEY,
        }

    def tearDown(self) -> None:
        for key, value in self.original_values.items():
            setattr(settings, key, value)

    def test_reports_disabled_when_rag_is_not_configured(self) -> None:
        settings.RAG_ENABLED = False
        settings.RAG_DATABASE_URL = ""
        settings.RAG_REDIS_URL = ""
        settings.RAG_QDRANT_URL = ""
        settings.RAG_EMBEDDING_BASE_URL = ""
        settings.RAG_EMBEDDING_MODEL_ID = ""
        settings.RAG_EMBEDDING_API_KEY = ""

        result = rag_infrastructure_health()

        self.assertFalse(result["enabled"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["embedding_configured"])
        self.assertEqual(result["components"]["postgresql"]["status"], "disabled")
        self.assertEqual(result["components"]["redis"]["status"], "disabled")
        self.assertEqual(result["components"]["qdrant"]["status"], "disabled")

    @patch("app.rag.infrastructure._check_qdrant")
    @patch("app.rag.infrastructure._check_redis")
    @patch("app.rag.infrastructure._check_postgresql")
    def test_reports_ready_when_all_components_are_available(
        self,
        check_postgresql,
        check_redis,
        check_qdrant,
    ) -> None:
        settings.RAG_ENABLED = True
        settings.RAG_DATABASE_URL = "postgresql+psycopg://example"
        settings.RAG_REDIS_URL = "redis://example"
        settings.RAG_QDRANT_URL = "http://example"
        settings.RAG_EMBEDDING_BASE_URL = "https://embedding.example/v1"
        settings.RAG_EMBEDDING_MODEL_ID = "embedding-model"
        settings.RAG_EMBEDDING_API_KEY = "test-only"

        result = rag_infrastructure_health()

        self.assertTrue(result["ready"])
        self.assertTrue(result["embedding_configured"])
        self.assertEqual(result["components"]["postgresql"]["status"], "available")
        self.assertEqual(result["components"]["redis"]["status"], "available")
        self.assertEqual(result["components"]["qdrant"]["status"], "available")
        check_postgresql.assert_called_once_with()
        check_redis.assert_called_once_with()
        check_qdrant.assert_called_once_with()

    @patch("app.rag.infrastructure._check_qdrant")
    @patch("app.rag.infrastructure._check_redis", side_effect=ConnectionError)
    @patch("app.rag.infrastructure._check_postgresql")
    def test_reports_degraded_without_exposing_connection_details(
        self,
        check_postgresql,
        check_redis,
        check_qdrant,
    ) -> None:
        settings.RAG_ENABLED = True
        settings.RAG_DATABASE_URL = "postgresql+psycopg://secret@example"
        settings.RAG_REDIS_URL = "redis://secret@example"
        settings.RAG_QDRANT_URL = "http://example"
        settings.RAG_EMBEDDING_BASE_URL = "https://embedding.example/v1"
        settings.RAG_EMBEDDING_MODEL_ID = "embedding-model"
        settings.RAG_EMBEDDING_API_KEY = "test-only"

        result = rag_infrastructure_health()

        self.assertFalse(result["ready"])
        self.assertEqual(result["components"]["redis"]["status"], "unavailable")
        self.assertEqual(result["components"]["redis"]["error"], "ConnectionError")
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
