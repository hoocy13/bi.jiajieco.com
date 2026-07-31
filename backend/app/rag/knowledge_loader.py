from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.core.config import settings


INDEXED_DIRECTORIES = {
    "metrics",
    "tables",
    "pages",
    "sql-examples",
    "playbooks",
    "faq",
}
SUPPORTED_SUFFIXES = {".md", ".markdown", ".yaml", ".yml"}


@dataclass(frozen=True)
class KnowledgeDocument:
    stable_id: str
    title: str
    source_path: str
    content: str
    allowed_roles: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_index: int
    content: str
    section_path: tuple[str, ...]


def _normalized_roles(value: Any) -> tuple[str, ...]:
    raw_roles = value if isinstance(value, list) else ["admin", "analyst"]
    roles = tuple(
        sorted({str(role).strip() for role in raw_roles if str(role).strip()})
    )
    return roles or ("admin",)


def _load_yaml(path: Path, relative_path: str) -> KnowledgeDocument | None:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    stable_id = str(payload.get("id") or relative_path).strip()
    title = str(
        payload.get("name")
        or payload.get("title")
        or payload.get("table")
        or stable_id
    ).strip()
    status = str(payload.get("status") or "draft").strip().lower()
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).strip()
    return KnowledgeDocument(
        stable_id=stable_id,
        title=title,
        source_path=relative_path,
        content=content,
        allowed_roles=_normalized_roles(payload.get("allowed_roles")),
        status=status,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    marker_index = text.find("\n---\n", 4)
    if marker_index < 0:
        return {}, text
    raw_frontmatter = text[4:marker_index]
    payload = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(payload, dict):
        payload = {}
    return payload, text[marker_index + 5 :]


def _load_markdown(path: Path, relative_path: str) -> KnowledgeDocument:
    raw_text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw_text)
    first_heading = next(
        (
            line.lstrip("#").strip()
            for line in body.splitlines()
            if line.startswith("#") and line.lstrip("#").strip()
        ),
        "",
    )
    stable_id = str(frontmatter.get("id") or relative_path).strip()
    return KnowledgeDocument(
        stable_id=stable_id,
        title=str(frontmatter.get("title") or first_heading or stable_id).strip(),
        source_path=relative_path,
        content=body.strip(),
        allowed_roles=_normalized_roles(frontmatter.get("allowed_roles")),
        status=str(frontmatter.get("status") or "draft").strip().lower(),
    )


def load_knowledge_document(path: Path, root: Path) -> KnowledgeDocument | None:
    relative_path = path.relative_to(root).as_posix()
    if path.suffix.lower() in {".yaml", ".yml"}:
        return _load_yaml(path, relative_path)
    return _load_markdown(path, relative_path)


def scan_knowledge(root: Path) -> list[KnowledgeDocument]:
    if not root.exists():
        raise FileNotFoundError(f"Knowledge path does not exist: {root}")
    documents: list[KnowledgeDocument] = []
    for directory in sorted(INDEXED_DIRECTORIES):
        source_directory = root / directory
        if not source_directory.exists():
            continue
        for path in sorted(source_directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            document = load_knowledge_document(path, root)
            if document is not None:
                documents.append(document)
    return documents


def scan_active_knowledge(root: Path) -> list[KnowledgeDocument]:
    return [
        document
        for document in scan_knowledge(root)
        if document.status == "active"
    ]


def split_knowledge_document(
    document: KnowledgeDocument,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[KnowledgeChunk]:
    target_size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = (
        settings.RAG_CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap
    )
    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=target_size,
        chunk_overlap=overlap,
        separators=["\n## ", "\n### ", "\n", "。", "；", "，", " ", ""],
        length_function=len,
    )

    if document.source_path.endswith((".md", ".markdown")):
        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
            ],
            strip_headers=False,
        )
        sections = header_splitter.split_text(document.content)
        chunks: list[KnowledgeChunk] = []
        for section in sections:
            section_path = tuple(
                str(section.metadata[key])
                for key in ("h1", "h2", "h3")
                if section.metadata.get(key)
            ) or (document.title,)
            for text_chunk in recursive_splitter.split_text(section.page_content):
                chunks.append(
                    KnowledgeChunk(
                        chunk_index=len(chunks),
                        content=text_chunk.strip(),
                        section_path=section_path,
                    )
                )
        return chunks

    return [
        KnowledgeChunk(
            chunk_index=index,
            content=content.strip(),
            section_path=(document.title,),
        )
        for index, content in enumerate(
            recursive_splitter.split_text(document.content)
        )
        if content.strip()
    ]
