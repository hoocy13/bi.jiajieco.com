from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import User
from app.rag.conversations import (
    ConversationNotFoundError,
    create_conversation,
    execute_run,
    get_user_conversation,
)
from app.rag.db import RagBase
from app.rag.models import (
    RagCitation,
    RagConversation,
    RagDocument,
    RagDocumentVersion,
    RagKnowledgeBase,
    RagMessage,
)
from app.rag.metric_tools import ExistingBiMetricProvider, parse_metric_query
from app.rag.routing import knowledge_part_of_mixed_question, route_question
from app.rag.workflow import build_knowledge_graph


class FakeEmbeddingProvider:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]

    def embed_documents(self, texts) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class FakeVectorStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0

    def search(self, *args, **kwargs) -> list[dict]:
        self.calls += 1
        return self.rows


class FakeChatModel:
    def __init__(self, answer: str = "周转天数使用期末库存代理。[1]") -> None:
        self.result = answer
        self.calls = 0
        self.last_question = ""

    def answer(self, question: str, evidence) -> str:
        self.calls += 1
        self.last_question = question
        return self.result


class FakeMetricProvider:
    def __init__(self, result: dict | None = None) -> None:
        self.calls = 0
        self.result = result or {
            "tool": "sales_overview",
            "source": "ods",
            "parameters": {
                "range_key": "this_month",
                "start_date": None,
                "end_date": None,
                "brand": "",
            },
            "data": {
                "as_of": "2026-07-30",
                "period": "本月",
                "start_date": "2026-07-01",
                "end_date": "2026-07-30",
                "metrics": {
                    "paid_amount": 12345.67,
                    "orders": 12,
                    "quantity": 34,
                    "avg_order_amount": 1028.805833,
                },
                "channels": [],
            },
        }

    def execute(self, question: str) -> dict:
        self.calls += 1
        return self.result


class FakeSqlProvider:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, question: str) -> dict:
        self.calls += 1
        return {
            "tool": "text_to_sql",
            "source": "ods",
            "parameters": {"max_rows": 200, "timeout_ms": 15000},
            "data": {
                "status": "completed",
                "sql": (
                    "SELECT `品牌`, SUM(`分摊后金额`) AS `销售额` "
                    "FROM `ods`.`销售单明细账` GROUP BY `品牌` LIMIT 10;"
                ),
                "tables": ["ods.销售单明细账"],
                "columns": ["品牌", "销售额"],
                "rows": [{"品牌": "A", "销售额": 123.45}],
                "row_count": 1,
                "limited": False,
                "attempts": [],
            },
        }


class RagRoutingTest(unittest.TestCase):
    def test_routes_four_supported_intents(self) -> None:
        self.assertEqual(route_question("品牌周转天数为什么这样计算？"), "knowledge")
        self.assertEqual(route_question("本月品牌销售额是多少？"), "metric")
        self.assertEqual(route_question("帮我写一个 SQL 查询语句"), "sql")
        self.assertEqual(
            route_question("本月销售额口径是什么，实际是多少？"),
            "mixed",
        )
        self.assertEqual(route_question("查询兰蔻品牌周转"), "metric")
        self.assertEqual(route_question("按品牌统计本月销售额"), "sql")
        self.assertEqual(
            route_question("销售额口径是什么，并按品牌列出本月销售额"),
            "mixed",
        )
        self.assertEqual(
            knowledge_part_of_mixed_question(
                "品牌周转天数口径是什么，2026年Q2小样实际周转是多少？"
            ),
            "品牌周转天数口径是什么",
        )

    def test_parses_default_and_combination_metric_filters(self) -> None:
        default_sales = parse_metric_query("最近销售情况怎么样？")
        self.assertEqual(default_sales.tool, "sales_overview")
        self.assertEqual(default_sales.range_key, "last_30")

        custom_sales = parse_metric_query(
            "查询 2026-07-01 到 2026-07-20 的销售额"
        )
        self.assertEqual(custom_sales.range_key, "custom")
        self.assertEqual(custom_sales.start_date.isoformat(), "2026-07-01")
        self.assertEqual(custom_sales.end_date.isoformat(), "2026-07-20")

        turnover = parse_metric_query(
            "查询2026年Q2品牌兰蔻周转，小样，可用库存不少于500"
        )
        self.assertEqual(turnover.tool, "brand_turnover")
        self.assertEqual((turnover.year, turnover.quarter), (2026, 2))
        self.assertEqual(turnover.brand, "兰蔻")
        self.assertEqual(turnover.product_types, ("小样",))
        self.assertEqual(turnover.min_stock, 500)
        with self.assertRaises(ValueError):
            parse_metric_query("本月库存量是多少？")


class RagWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        RagBase.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.knowledge_base = RagKnowledgeBase(
            name="bi-core",
            description="test",
            status="active",
        )
        self.db.add(self.knowledge_base)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def evidence(version_id: str | None = None) -> dict:
        return {
            "score": 0.8,
            "document_version_id": version_id or str(uuid4()),
            "chunk_id": "chunk-1",
            "title": "品牌估算周转天数",
            "section_path": ["定义"],
            "source_path": "metrics/inventory-turnover-days.yaml",
            "content": "当前使用期末库存代理。",
        }

    def test_knowledge_route_retrieves_and_composes_answer(self) -> None:
        store = FakeVectorStore([self.evidence()])
        chat = FakeChatModel()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
        )

        result = graph.invoke(
            {
                "question": " 品牌周转天数为什么这样计算？ ",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(result["intent"], "knowledge")
        self.assertEqual(store.calls, 1)
        self.assertEqual(chat.calls, 1)
        self.assertIn("[1]", result["answer"])
        self.assertEqual(len(result["evidence"]), 1)

    def test_metric_route_does_not_call_vector_store_or_model(self) -> None:
        store = FakeVectorStore([self.evidence()])
        chat = FakeChatModel()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
        )

        result = graph.invoke(
            {
                "question": "本月销售额是多少？",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(result["intent"], "metric")
        self.assertEqual(store.calls, 0)
        self.assertEqual(chat.calls, 0)
        self.assertIn("不会使用模型猜测", result["answer"])

    def test_metric_route_uses_read_only_tool_result_without_model(self) -> None:
        store = FakeVectorStore([self.evidence()])
        chat = FakeChatModel()
        metrics = FakeMetricProvider()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
            metrics,
        )

        result = graph.invoke(
            {
                "question": "本月销售额是多少？",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(result["intent"], "metric")
        self.assertEqual(metrics.calls, 1)
        self.assertEqual(store.calls, 0)
        self.assertEqual(chat.calls, 0)
        self.assertIn("12,345.67 元", result["answer"])
        self.assertIn("12 单", result["answer"])

    def test_mixed_route_returns_knowledge_and_metric_result(self) -> None:
        store = FakeVectorStore([self.evidence()])
        chat = FakeChatModel("销售额口径来自实付金额。[1]")
        metrics = FakeMetricProvider()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
            metrics,
        )

        result = graph.invoke(
            {
                "question": "本月销售额口径是什么，实际是多少？",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(result["intent"], "mixed")
        self.assertEqual(store.calls, 1)
        self.assertEqual(metrics.calls, 1)
        self.assertEqual(chat.calls, 1)
        self.assertIn("本月销售额口径是什么", chat.last_question)
        self.assertNotIn("实际是多少", chat.last_question)
        self.assertIn("业务口径：", result["answer"])
        self.assertIn("实际数据：", result["answer"])
        self.assertIn("12,345.67 元", result["answer"])

    def test_sql_route_uses_sql_tool_without_vector_or_chat_model(self) -> None:
        store = FakeVectorStore([self.evidence()])
        chat = FakeChatModel()
        sql = FakeSqlProvider()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
            FakeMetricProvider(),
            sql,
        )

        result = graph.invoke(
            {
                "question": "按品牌统计本月销售额",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(result["intent"], "sql")
        self.assertEqual(sql.calls, 1)
        self.assertEqual(store.calls, 0)
        self.assertEqual(chat.calls, 0)
        self.assertIn("| 品牌 | 销售额 |", result["answer"])
        self.assertIn("SELECT", result["answer"])

    def test_mixed_sql_route_returns_knowledge_and_sql_result(self) -> None:
        store = FakeVectorStore([self.evidence()])
        chat = FakeChatModel("销售额使用分摊后金额。[1]")
        sql = FakeSqlProvider()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
            FakeMetricProvider(),
            sql,
        )

        result = graph.invoke(
            {
                "question": "销售额口径是什么，并按品牌列出本月销售额",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(result["intent"], "mixed")
        self.assertEqual(store.calls, 1)
        self.assertEqual(sql.calls, 1)
        self.assertEqual(chat.calls, 1)
        self.assertIn("业务口径：", result["answer"])
        self.assertIn("实际数据：查询结果", result["answer"])

    def test_insufficient_evidence_does_not_call_model(self) -> None:
        store = FakeVectorStore([])
        chat = FakeChatModel()
        graph = build_knowledge_graph(
            self.db,
            FakeEmbeddingProvider(),
            store,
            chat,
        )

        result = graph.invoke(
            {
                "question": "品牌周转规则是什么？",
                "roles": ["analyst"],
                "warnings": [],
            }
        )

        self.assertEqual(chat.calls, 0)
        self.assertIn("没有找到足够可靠", result["answer"])
        self.assertIn("insufficient_evidence", result["warnings"])

    def test_persists_completed_run_messages_and_citation(self) -> None:
        document = RagDocument(
            knowledge_base_id=self.knowledge_base.id,
            stable_id="metric.inventory_turnover_days",
            title="品牌估算周转天数",
            source_path="metrics/inventory-turnover-days.yaml",
            allowed_roles=["analyst"],
            status="active",
        )
        self.db.add(document)
        self.db.flush()
        version = RagDocumentVersion(
            document_id=document.id,
            version=1,
            content_hash="a" * 64,
            status="active",
            chunk_count=1,
        )
        self.db.add(version)
        self.db.commit()
        user = User(
            id=7,
            username="analyst",
            hashed_password="unused",
            is_active=True,
        )
        conversation = create_conversation(self.db, user)

        run = execute_run(
            self.db,
            conversation,
            user,
            "品牌周转天数为什么这样计算？",
            FakeEmbeddingProvider(),
            FakeVectorStore([self.evidence(str(version.id))]),
            FakeChatModel(),
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.intent, "knowledge")
        messages = self.db.scalars(
            select(RagMessage).where(RagMessage.run_id == run.id)
        ).all()
        citations = self.db.scalars(
            select(RagCitation).where(RagCitation.run_id == run.id)
        ).all()
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].document_version_id, version.id)

    def test_persists_only_citations_referenced_by_answer(self) -> None:
        document = RagDocument(
            knowledge_base_id=self.knowledge_base.id,
            stable_id="metric.inventory_turnover_days",
            title="品牌估算周转天数",
            source_path="metrics/inventory-turnover-days.yaml",
            allowed_roles=["analyst"],
            status="active",
        )
        self.db.add(document)
        self.db.flush()
        version = RagDocumentVersion(
            document_id=document.id,
            version=1,
            content_hash="b" * 64,
            status="active",
            chunk_count=2,
        )
        self.db.add(version)
        self.db.commit()
        user = User(
            id=8,
            username="analyst",
            hashed_password="unused",
            is_active=True,
        )
        conversation = create_conversation(self.db, user)
        first = self.evidence(str(version.id))
        second = {
            **self.evidence(str(version.id)),
            "chunk_id": "chunk-2",
            "source_path": "tables/unrelated.yaml",
        }

        run = execute_run(
            self.db,
            conversation,
            user,
            "品牌周转天数为什么这样计算？",
            FakeEmbeddingProvider(),
            FakeVectorStore([first, second]),
            FakeChatModel("只使用第一份证据。[1]"),
        )

        citations = self.db.scalars(
            select(RagCitation).where(RagCitation.run_id == run.id)
        ).all()
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].ordinal, 1)
        self.assertEqual(
            citations[0].source_path,
            "metrics/inventory-turnover-days.yaml",
        )

    def test_conversation_is_scoped_to_owner(self) -> None:
        owner = User(
            id=9,
            username="owner",
            hashed_password="unused",
            is_active=True,
        )
        conversation = create_conversation(self.db, owner, "测试会话")
        found = get_user_conversation(self.db, conversation.id, owner.id)
        self.assertEqual(found.id, conversation.id)
        with self.assertRaises(ConversationNotFoundError):
            get_user_conversation(self.db, conversation.id, 10)

    def test_persists_metric_tool_trace(self) -> None:
        user = User(
            id=11,
            username="analyst",
            hashed_password="unused",
            is_active=True,
        )
        conversation = create_conversation(self.db, user)
        metrics = FakeMetricProvider()

        run = execute_run(
            self.db,
            conversation,
            user,
            "本月销售额是多少？",
            FakeEmbeddingProvider(),
            FakeVectorStore([]),
            FakeChatModel(),
            metrics,
        )

        tool_trace = next(
            item for item in run.trace if item["node"] == "metric_tool"
        )
        self.assertEqual(tool_trace["tool"], "sales_overview")
        self.assertEqual(tool_trace["source"], "ods")
        self.assertEqual(
            tool_trace["result"]["metrics"]["paid_amount"],
            12345.67,
        )


class ExistingBiMetricProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    @patch("app.rag.metric_tools.sales_overview")
    def test_calls_sales_overview_with_combination_dates(self, call) -> None:
        call.return_value = {
            "data": {
                "as_of": "2026-07-20",
                "period": "自定义",
                "start_date": "2026-07-01",
                "end_date": "2026-07-20",
                "metrics": {
                    "paid_amount": 100,
                    "orders": 2,
                    "quantity": 3,
                    "avg_order_amount": 50,
                },
                "channels": [],
            }
        }
        provider = ExistingBiMetricProvider(self.session_factory)

        result = provider.execute("查询 2026-07-01 到 2026-07-20 的销售额")

        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["range"], "custom")
        self.assertEqual(kwargs["start_date"].isoformat(), "2026-07-01")
        self.assertEqual(kwargs["end_date"].isoformat(), "2026-07-20")
        self.assertEqual(result["data"]["metrics"]["paid_amount"], 100)

    @patch("app.rag.metric_tools.inventory_brand_turnover")
    def test_calls_brand_turnover_with_combination_filters(self, call) -> None:
        call.return_value = {
            "data": {
                "period": "2026 Q2",
                "start_date": "2026-04-01",
                "end_date": "2026-06-30",
                "snapshot_at": "2026-07-30",
                "basis": "ending_stock_proxy",
                "summary": {
                    "brand_count": 1,
                    "available_stock": 600,
                    "net_sales_quantity": 300,
                    "turnover_days": 182,
                    "attention_brands": 1,
                },
                "chart_rows": [
                    {
                        "brand": "兰蔻",
                        "available_stock": 600,
                        "net_sales_quantity": 300,
                        "turnover_days": 182,
                        "status": "过慢",
                    }
                ],
            }
        }
        provider = ExistingBiMetricProvider(self.session_factory)

        result = provider.execute(
            "查询2026年Q2品牌兰蔻周转，小样，可用库存不少于500"
        )

        kwargs = call.call_args.kwargs
        self.assertEqual((kwargs["year"], kwargs["quarter"]), (2026, 2))
        self.assertEqual(kwargs["keyword"], "兰蔻")
        self.assertEqual(kwargs["product_type"], ["小样"])
        self.assertEqual(kwargs["min_stock"], 500)
        self.assertEqual(result["data"]["rows"][0]["brand"], "兰蔻")


if __name__ == "__main__":
    unittest.main()
