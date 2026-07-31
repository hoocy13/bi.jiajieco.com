from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embeddings import EmbeddingProvider
from app.rag.knowledge_loader import (
    KnowledgeDocument,
    scan_knowledge,
    split_knowledge_document,
)
from app.rag.models import (
    RagDocument,
    RagDocumentVersion,
    RagIngestionJob,
    RagKnowledgeBase,
)
from app.rag.vector_store import QdrantKnowledgeStore, VectorChunk


def _content_hash(document: KnowledgeDocument) -> str:
    normalized = "\n".join(
        [
            document.stable_id,
            document.title,
            document.source_path,
            ",".join(document.allowed_roles),
            document.content,
        ]
    )
    return sha256(normalized.encode("utf-8")).hexdigest()


def _get_or_create_knowledge_base(db: Session) -> RagKnowledgeBase:
    knowledge_base = db.scalar(
        select(RagKnowledgeBase).where(
            RagKnowledgeBase.name == settings.RAG_KNOWLEDGE_BASE_NAME
        )
    )
    if knowledge_base is None:
        knowledge_base = RagKnowledgeBase(
            name=settings.RAG_KNOWLEDGE_BASE_NAME,
            description="Jiajieco BI 核心业务知识",
            status="active",
        )
        db.add(knowledge_base)
        db.flush()
    return knowledge_base


def _latest_version_number(db: Session, document_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.max(RagDocumentVersion.version)).where(
                RagDocumentVersion.document_id == document_id
            )
        )
        or 0
    )


def ingest_document(
    db: Session,
    document: KnowledgeDocument,
    embedding_provider: EmbeddingProvider,
    vector_store: QdrantKnowledgeStore,
) -> dict:
    knowledge_base = _get_or_create_knowledge_base(db)
    stored_document = db.scalar(
        select(RagDocument).where(
            RagDocument.knowledge_base_id == knowledge_base.id,
            RagDocument.stable_id == document.stable_id,
        )
    )
    if stored_document is None:
        stored_document = RagDocument(
            knowledge_base_id=knowledge_base.id,
            stable_id=document.stable_id,
            title=document.title,
            source_path=document.source_path,
            allowed_roles=list(document.allowed_roles),
        )
        db.add(stored_document)
        db.flush()
    else:
        stored_document.title = document.title
        stored_document.source_path = document.source_path
        stored_document.allowed_roles = list(document.allowed_roles)
        stored_document.status = "active"

    digest = _content_hash(document)
    active_version = db.scalar(
        select(RagDocumentVersion).where(
            RagDocumentVersion.document_id == stored_document.id,
            RagDocumentVersion.status == "active",
        )
    )
    if active_version is not None and active_version.content_hash == digest:
        db.commit()
        return {
            "document_id": str(stored_document.id),
            "version_id": str(active_version.id),
            "status": "unchanged",
            "chunk_count": active_version.chunk_count,
        }

    version = RagDocumentVersion(
        document_id=stored_document.id,
        version=_latest_version_number(db, stored_document.id) + 1,
        content_hash=digest,
        status="indexing",
        chunk_count=0,
    )
    db.add(version)
    db.flush()
    job = RagIngestionJob(
        document_version_id=version.id,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(job)
    db.commit()

    try:
        chunks = split_knowledge_document(document)
        vectors = embedding_provider.embed_documents(
            [chunk.content for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count does not match chunk count")
        vector_chunks = [
            VectorChunk(
                point_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{version.id}:{chunk.chunk_index}",
                    )
                ),
                vector=vector,
                payload={
                    "knowledge_base_id": str(knowledge_base.id),
                    "document_id": str(stored_document.id),
                    "document_version_id": str(version.id),
                    "document_version": version.version,
                    "chunk_id": f"{version.id}:{chunk.chunk_index}",
                    "chunk_index": chunk.chunk_index,
                    "title": document.title,
                    "section_path": list(chunk.section_path),
                    "source_path": document.source_path,
                    "allowed_roles": list(document.allowed_roles),
                    "content_hash": digest,
                    "content": chunk.content,
                    "status": "validating",
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        vector_store.stage_version(vector_chunks)
        vector_store.activate_version(stored_document.id, version.id)

        if active_version is not None:
            active_version.status = "archived"
        version.status = "active"
        version.chunk_count = len(chunks)
        version.activated_at = datetime.now(UTC)
        job.status = "completed"
        job.finished_at = datetime.now(UTC)
        db.commit()
        return {
            "document_id": str(stored_document.id),
            "version_id": str(version.id),
            "status": "indexed",
            "chunk_count": len(chunks),
        }
    except Exception as exc:
        db.rollback()
        try:
            vector_store.delete_version(version.id)
        except Exception:
            pass
        failed_version = db.get(RagDocumentVersion, version.id)
        failed_job = db.get(RagIngestionJob, job.id)
        if failed_version is not None:
            failed_version.status = "failed"
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.error_code = type(exc).__name__
            failed_job.error_message = str(exc)[:2000]
            failed_job.finished_at = datetime.now(UTC)
        db.commit()
        raise


def archive_inactive_documents(
    db: Session,
    vector_store: QdrantKnowledgeStore,
    active_stable_ids: set[str],
) -> int:
    knowledge_base = db.scalar(
        select(RagKnowledgeBase).where(
            RagKnowledgeBase.name == settings.RAG_KNOWLEDGE_BASE_NAME
        )
    )
    if knowledge_base is None:
        return 0
    active_documents = db.scalars(
        select(RagDocument).where(
            RagDocument.knowledge_base_id == knowledge_base.id,
            RagDocument.status == "active",
        )
    ).all()
    archived = 0
    for document in active_documents:
        if document.stable_id in active_stable_ids:
            continue
        vector_store.archive_document(document.id)
        document.status = "archived"
        versions = db.scalars(
            select(RagDocumentVersion).where(
                RagDocumentVersion.document_id == document.id,
                RagDocumentVersion.status == "active",
            )
        ).all()
        for version in versions:
            version.status = "archived"
        archived += 1
    db.commit()
    return archived


def sync_knowledge_repository(
    db: Session,
    embedding_provider: EmbeddingProvider,
    vector_store: QdrantKnowledgeStore,
    *,
    root: Path | None = None,
) -> dict:
    knowledge_root = root or Path(settings.RAG_KNOWLEDGE_PATH)
    scanned_documents = scan_knowledge(knowledge_root)
    documents = [
        document
        for document in scanned_documents
        if document.status == "active"
    ]
    results = []
    failures = []
    for document in documents:
        try:
            results.append(
                ingest_document(
                    db,
                    document,
                    embedding_provider,
                    vector_store,
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "source_path": document.source_path,
                    "error": type(exc).__name__,
                }
            )
    archived = archive_inactive_documents(
        db,
        vector_store,
        {document.stable_id for document in documents},
    )
    return {
        "scanned": len(scanned_documents),
        "active": len(documents),
        "indexed": sum(result["status"] == "indexed" for result in results),
        "unchanged": sum(result["status"] == "unchanged" for result in results),
        "archived": archived,
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }
