from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "bi.jiajieco.com Backend"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "sqlite:///./bi_admin.db"
    ODS_DATABASE_URL: str = ""
    ADS_DATABASE_URL: str = ""
    ADS_BUILD_DATABASE_URL: str = ""
    BI_QUERY_SOURCE: str = "ads"
    ADS_POOL_SIZE: int = 5
    ADS_MAX_OVERFLOW: int = 5
    ODS_BUILD_READ_TIMEOUT_SECONDS: int = 300
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    PERFORMANCE_LOG_ALL_REQUESTS: bool = False
    PERFORMANCE_SLOW_REQUEST_MS: int = 1000
    PERFORMANCE_SLOW_QUERY_MS: int = 500

    DEMO_USERNAME: str = "jiajie"
    DEMO_PASSWORD: str = "change-me"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL_ID: str = ""
    OPENAI_TIMEOUT_SECONDS: int = 120

    RAG_ENABLED: bool = False
    RAG_DATABASE_URL: str = ""
    RAG_REDIS_URL: str = ""
    RAG_QDRANT_URL: str = ""
    RAG_QDRANT_API_KEY: str = ""
    RAG_CONNECT_TIMEOUT_SECONDS: int = 3
    RAG_KNOWLEDGE_PATH: str = "../docs/knowledge"
    RAG_KNOWLEDGE_BASE_NAME: str = "bi-core"
    RAG_QDRANT_COLLECTION: str = "jjc_bi_knowledge_v1"
    RAG_ADMIN_USERNAMES: list[str] = ["jiajie"]
    RAG_CHUNK_SIZE: int = 800
    RAG_CHUNK_OVERLAP: int = 120
    RAG_SEARCH_TOP_K: int = 5
    RAG_CONTEXT_TOP_K: int = 4
    RAG_MIN_RETRIEVAL_SCORE: float = 0.35
    RAG_CHAT_MAX_TOKENS: int = 1200
    RAG_SQL_MAX_ROWS: int = 200
    RAG_SQL_TIMEOUT_MS: int = 15000
    RAG_SQL_MAX_JOINS: int = 5
    RAG_EMBEDDING_BASE_URL: str = ""
    RAG_EMBEDDING_MODEL_ID: str = ""
    RAG_EMBEDDING_API_KEY: str = ""
    RAG_EMBEDDING_DIMENSIONS: int = 0
    RAG_EMBEDDING_BATCH_SIZE: int = 10
    RAG_CELERY_RESULT_BACKEND: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("BI_QUERY_SOURCE")
    @classmethod
    def validate_bi_query_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"ods", "dual", "ads"}:
            raise ValueError("BI_QUERY_SOURCE must be one of: ods, dual, ads")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
