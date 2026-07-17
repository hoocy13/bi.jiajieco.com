from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.ods import get_ods_db
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ok
from app.schemas.text_to_sql import AskTextToSqlRequest, GenerateSqlRequest, SchemaLinkRequest
from app.services.schema_linker import link_schema
from app.services.sql_generator import generate_sql
from app.services.text_to_sql_agent import ask_text_to_sql


router = APIRouter(prefix="/text-to-sql", tags=["text-to-sql"])


@router.post("/schema-link")
def schema_link(
    payload: SchemaLinkRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    return ok(link_schema(payload.question, payload.top_k_tables, payload.top_k_examples))


@router.post("/generate-sql")
def generate_text_to_sql(
    payload: GenerateSqlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return ok(generate_sql(db, payload.question, payload.top_k_tables, payload.top_k_examples))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ask")
def ask_text_to_sql_agent(
    payload: AskTextToSqlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ods_db: Session = Depends(get_ods_db),
) -> dict:
    try:
        return ok(
            ask_text_to_sql(
                db=db,
                ods_db=ods_db,
                question=payload.question,
                top_k_tables=payload.top_k_tables,
                top_k_examples=payload.top_k_examples,
                max_rows=payload.max_rows,
                max_retries=payload.max_retries,
                include_schema_context=payload.include_schema_context,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
