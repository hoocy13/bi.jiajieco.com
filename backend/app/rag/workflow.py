from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embeddings import EmbeddingProvider
from app.rag.llm import ChatModel
from app.rag.metric_tools import (
    MetricProvider,
    UnsupportedMetricError,
    format_metric_answer,
)
from app.rag.retrieval import search_knowledge
from app.rag.routing import (
    RagIntent,
    knowledge_part_of_mixed_question,
    requires_sql,
    route_question,
)
from app.rag.sql_tool import SqlProvider, format_sql_answer
from app.rag.vector_store import QdrantKnowledgeStore


class RagWorkflowState(TypedDict, total=False):
    question: str
    normalized_question: str
    roles: list[str]
    intent: RagIntent
    evidence: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    answer: str
    warnings: list[str]


def build_knowledge_graph(
    db: Session,
    embedding_provider: EmbeddingProvider,
    vector_store: QdrantKnowledgeStore,
    chat_model: ChatModel,
    metric_provider: MetricProvider | None = None,
    sql_provider: SqlProvider | None = None,
):
    def normalize_question(state: RagWorkflowState) -> dict:
        return {"normalized_question": " ".join(state["question"].strip().split())}

    def classify_intent(state: RagWorkflowState) -> dict:
        return {"intent": route_question(state["normalized_question"])}

    def retrieve_knowledge(state: RagWorkflowState) -> dict:
        retrieval_question = (
            knowledge_part_of_mixed_question(state["normalized_question"])
            if state["intent"] == "mixed"
            else state["normalized_question"]
        )
        rows = search_knowledge(
            db,
            retrieval_question,
            state["roles"],
            embedding_provider,
            vector_store,
            limit=settings.RAG_SEARCH_TOP_K,
        )
        evidence = [
            row
            for row in rows
            if float(row.get("score", 0)) >= settings.RAG_MIN_RETRIEVAL_SCORE
        ][: settings.RAG_CONTEXT_TOP_K]
        return {"evidence": evidence}

    def compose_answer(state: RagWorkflowState) -> dict:
        evidence = state.get("evidence") or []
        if not evidence:
            return {
                "answer": (
                    "当前知识库中没有找到足够可靠的内部证据，暂时无法回答。"
                    "请补充或确认相关业务口径后重新入库。"
                ),
                "warnings": ["insufficient_evidence"],
            }
        return {
            "answer": chat_model.answer(
                state["normalized_question"],
                evidence,
            )
        }

    def call_metric_tool(state: RagWorkflowState) -> dict:
        if metric_provider is None:
            return {
                "answer": (
                    "已识别为指标查询，但当前没有配置只读指标数据源，"
                    "因此不会使用模型猜测动态业务数据。"
                ),
                "warnings": ["metric_tool_not_available"],
                "tool_results": [],
            }
        try:
            result = metric_provider.execute(state["normalized_question"])
        except UnsupportedMetricError as exc:
            return {
                "answer": str(exc),
                "warnings": ["unsupported_metric"],
                "tool_results": [],
            }
        return {"tool_results": [result]}

    def compose_metric_answer(state: RagWorkflowState) -> dict:
        tool_results = state.get("tool_results") or []
        if not tool_results:
            return {"answer": state.get("answer") or "指标工具暂不可用。"}
        metric_answer = format_metric_answer(tool_results[0])
        if state["intent"] == "metric":
            return {"answer": metric_answer}
        evidence = state.get("evidence") or []
        if evidence:
            knowledge_question = knowledge_part_of_mixed_question(
                state["normalized_question"]
            )
            knowledge_answer = chat_model.answer(
                f"请解释以下业务口径及其限制：{knowledge_question}",
                evidence,
            )
        else:
            knowledge_answer = "知识库中没有找到足够可靠的业务口径证据。"
        return {
            "answer": (
                f"业务口径：{knowledge_answer}\n\n"
                f"实际数据：{metric_answer}"
            )
        }

    def call_sql_tool(state: RagWorkflowState) -> dict:
        if sql_provider is None:
            return {
                "answer": (
                    "已识别为明细或多维分析查询，但当前没有配置 Text-to-SQL "
                    "只读工具，因此不会生成或执行 SQL。"
                ),
                "warnings": ["sql_tool_not_available"],
                "tool_results": [],
            }
        return {
            "tool_results": [
                sql_provider.execute(state["normalized_question"])
            ]
        }

    def compose_sql_answer(state: RagWorkflowState) -> dict:
        tool_results = state.get("tool_results") or []
        if not tool_results:
            return {"answer": state.get("answer") or "SQL 工具暂不可用。"}
        sql_answer = format_sql_answer(tool_results[0])
        if state["intent"] == "sql":
            return {"answer": sql_answer}
        evidence = state.get("evidence") or []
        if evidence:
            knowledge_question = knowledge_part_of_mixed_question(
                state["normalized_question"]
            )
            knowledge_answer = chat_model.answer(
                f"请解释以下业务口径及其限制：{knowledge_question}",
                evidence,
            )
        else:
            knowledge_answer = "知识库中没有找到足够可靠的业务口径证据。"
        return {
            "answer": (
                f"业务口径：{knowledge_answer}\n\n"
                f"实际数据：{sql_answer}"
            )
        }

    def unsupported_route(state: RagWorkflowState) -> dict:
        return {
            "answer": "当前问题类型尚未接入可执行工具。",
            "warnings": ["route_not_available"],
            "evidence": [],
        }

    builder = StateGraph(RagWorkflowState)
    builder.add_node("normalize_question", normalize_question)
    builder.add_node("route_intent", classify_intent)
    builder.add_node("retrieve_knowledge", retrieve_knowledge)
    builder.add_node("compose_answer", compose_answer)
    builder.add_node("call_metric_tool", call_metric_tool)
    builder.add_node("compose_metric_answer", compose_metric_answer)
    builder.add_node("call_sql_tool", call_sql_tool)
    builder.add_node("compose_sql_answer", compose_sql_answer)
    builder.add_node("unsupported_route", unsupported_route)
    builder.add_edge(START, "normalize_question")
    builder.add_edge("normalize_question", "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        lambda state: (
            "retrieve_knowledge"
            if state["intent"] in {"knowledge", "mixed"}
            else (
                "call_metric_tool"
                if state["intent"] == "metric"
                else "call_sql_tool"
            )
        ),
        {
            "retrieve_knowledge": "retrieve_knowledge",
            "call_metric_tool": "call_metric_tool",
            "call_sql_tool": "call_sql_tool",
        },
    )
    builder.add_conditional_edges(
        "retrieve_knowledge",
        lambda state: (
            (
                "call_sql_tool"
                if requires_sql(state["normalized_question"])
                else "call_metric_tool"
            )
            if state["intent"] == "mixed"
            else "compose_answer"
        ),
        {
            "call_metric_tool": "call_metric_tool",
            "call_sql_tool": "call_sql_tool",
            "compose_answer": "compose_answer",
        },
    )
    builder.add_edge("call_metric_tool", "compose_metric_answer")
    builder.add_edge("call_sql_tool", "compose_sql_answer")
    builder.add_edge("compose_answer", END)
    builder.add_edge("compose_metric_answer", END)
    builder.add_edge("compose_sql_answer", END)
    builder.add_edge("unsupported_route", END)
    return builder.compile()
