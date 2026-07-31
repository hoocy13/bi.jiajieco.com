from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User
from app.db.session import get_db
from app.rag.db import get_rag_db
from app.rag.embeddings import (
    OpenAICompatibleEmbeddingProvider,
    embedding_is_configured,
)
from app.rag.infrastructure import rag_infrastructure_health
from app.rag.conversations import (
    ConversationNotFoundError,
    citation_payload,
    create_conversation,
    execute_run,
    get_user_conversation,
)
from app.rag.llm import OpenAICompatibleChatModel, chat_model_is_configured
from app.rag.metric_tools import ExistingBiMetricProvider
from app.rag.sql_tool import ExistingTextToSqlProvider
from app.rag.models import (
    RagCitation,
    RagConversation,
    RagIngestionJob,
    RagMessage,
    RagRun,
)
from app.rag.permissions import rag_role_for_user, require_rag_admin
from app.rag.retrieval import search_knowledge
from app.rag.tasks import reindex_knowledge_task
from app.rag.vector_store import QdrantKnowledgeStore
from app.schemas.common import ok
from app.schemas.rag import RagConversationCreate, RagRunCreate, RagSearchRequest


router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/health")
def rag_health(current_user: User = Depends(get_current_user)) -> dict:
    return ok(rag_infrastructure_health())


def _conversation_payload(conversation: RagConversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "status": conversation.status,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _run_payload(db: Session, run: RagRun) -> dict:
    answer = db.scalar(
        select(RagMessage.content).where(
            RagMessage.run_id == run.id,
            RagMessage.role == "assistant",
        )
    )
    citations = db.scalars(
        select(RagCitation)
        .where(RagCitation.run_id == run.id)
        .order_by(RagCitation.ordinal)
    ).all()
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "question": run.question,
        "intent": run.intent,
        "status": run.status,
        "answer": answer,
        "citations": [citation_payload(db, item) for item in citations],
        "error_code": run.error_code,
        "error_message": run.error_message,
        "trace": run.trace,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/conversations")
def create_rag_conversation(
    payload: RagConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_rag_db),
) -> dict:
    conversation = create_conversation(db, current_user, payload.title)
    return ok(_conversation_payload(conversation))


@router.get("/conversations")
def list_rag_conversations(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_rag_db),
) -> dict:
    conversations = db.scalars(
        select(RagConversation)
        .where(
            RagConversation.user_id == current_user.id,
            RagConversation.status == "active",
        )
        .order_by(RagConversation.updated_at.desc())
        .limit(limit)
    ).all()
    return ok([_conversation_payload(item) for item in conversations])


@router.get("/conversations/{conversation_id}")
def get_rag_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_rag_db),
) -> dict:
    try:
        conversation = get_user_conversation(
            db,
            conversation_id,
            current_user.id,
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": 404, "message": "RAG conversation not found", "data": None},
        ) from None
    messages = db.scalars(
        select(RagMessage)
        .where(RagMessage.conversation_id == conversation.id)
        .order_by(RagMessage.created_at)
    ).all()
    runs = db.scalars(
        select(RagRun)
        .where(RagRun.conversation_id == conversation.id)
        .order_by(RagRun.created_at)
    ).all()
    result = _conversation_payload(conversation)
    result["messages"] = [
        {
            "id": str(message.id),
            "run_id": str(message.run_id) if message.run_id else None,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]
    result["runs"] = [_run_payload(db, run) for run in runs]
    return ok(result)


@router.post("/conversations/{conversation_id}/runs")
def create_rag_run(
    conversation_id: UUID,
    payload: RagRunCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_rag_db),
    admin_db: Session = Depends(get_db),
) -> dict:
    if (
        not settings.RAG_ENABLED
        or not embedding_is_configured()
        or not chat_model_is_configured()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": 503,
                "message": "RAG embedding or chat model is not configured",
                "data": None,
            },
        )
    try:
        conversation = get_user_conversation(
            db,
            conversation_id,
            current_user.id,
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": 404, "message": "RAG conversation not found", "data": None},
        ) from None
    run = execute_run(
        db,
        conversation,
        current_user,
        payload.question,
        OpenAICompatibleEmbeddingProvider(),
        QdrantKnowledgeStore(),
        OpenAICompatibleChatModel(),
        ExistingBiMetricProvider(),
        ExistingTextToSqlProvider(admin_db),
    )
    return ok(_run_payload(db, run))


@router.get("/runs/{run_id}")
def get_rag_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_rag_db),
) -> dict:
    run = db.scalar(
        select(RagRun).where(
            RagRun.id == run_id,
            RagRun.user_id == current_user.id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": 404, "message": "RAG run not found", "data": None},
        )
    return ok(_run_payload(db, run))


def _job_payload(job: RagIngestionJob) -> dict:
    return {
        "id": str(job.id),
        "document_version_id": (
            str(job.document_version_id) if job.document_version_id else None
        ),
        "status": job.status,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("/admin/reindex")
def reindex_knowledge(current_user: User = Depends(require_rag_admin)) -> dict:
    if (
        not settings.RAG_ENABLED
        or not settings.RAG_REDIS_URL
        or not embedding_is_configured()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": 503,
                "message": "RAG task queue or embedding service is not configured",
                "data": None,
            },
        )
    task = reindex_knowledge_task.delay()
    return ok({"task_id": task.id, "status": "queued"})


@router.get("/admin/jobs")
def list_ingestion_jobs(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_rag_admin),
    db: Session = Depends(get_rag_db),
) -> dict:
    jobs = db.scalars(
        select(RagIngestionJob)
        .order_by(RagIngestionJob.created_at.desc())
        .limit(limit)
    ).all()
    return ok([_job_payload(job) for job in jobs])


@router.get("/admin/jobs/{job_id}")
def get_ingestion_job(
    job_id: UUID,
    current_user: User = Depends(require_rag_admin),
    db: Session = Depends(get_rag_db),
) -> dict:
    job = db.get(RagIngestionJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": 404, "message": "RAG ingestion job not found", "data": None},
        )
    return ok(_job_payload(job))


@router.post("/search")
def search_rag_knowledge(
    payload: RagSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_rag_db),
) -> dict:
    if not settings.RAG_ENABLED or not embedding_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": 503,
                "message": "RAG embedding service is not configured",
                "data": None,
            },
        )
    role = rag_role_for_user(current_user)
    results = search_knowledge(
        db,
        payload.question,
        [role],
        OpenAICompatibleEmbeddingProvider(),
        QdrantKnowledgeStore(),
        limit=payload.limit,
    )
    return ok(
        {
            "question": payload.question,
            "role": role,
            "items": results,
            "count": len(results),
        }
    )
