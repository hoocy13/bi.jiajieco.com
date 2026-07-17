from pydantic import BaseModel, Field


class SchemaLinkRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    top_k_tables: int = Field(default=5, ge=1, le=10)
    top_k_examples: int = Field(default=3, ge=0, le=10)


class GenerateSqlRequest(SchemaLinkRequest):
    pass


class AskTextToSqlRequest(SchemaLinkRequest):
    max_rows: int = Field(default=200, ge=1, le=1000)
    max_retries: int = Field(default=2, ge=0, le=3)
    include_schema_context: bool = False
