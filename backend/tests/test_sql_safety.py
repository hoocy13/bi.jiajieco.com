from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.services.sql_safety import (
    SqlSafetyError,
    prepare_safe_sql,
    validate_sql,
)
from app.services.model_client import get_model_config
from app.services.text_to_sql_agent import execute_readonly_sql


SALES_TABLE = "ods.`销售单明细账`"


class SqlSafetyTest(unittest.TestCase):
    def test_allows_select_and_rewrites_large_limit(self) -> None:
        safe = prepare_safe_sql(
            f"SELECT `品牌`, SUM(`分摊后金额`) AS amount "
            f"FROM {SALES_TABLE} GROUP BY `品牌` LIMIT 999",
            200,
        )
        self.assertIn("LIMIT 200", safe.sql)
        self.assertTrue(safe.limit_rewritten)
        self.assertEqual(safe.tables, ("ods.销售单明细账",))
        self.assertIn("`品牌`", safe.sql)

    def test_preserves_smaller_limit(self) -> None:
        safe = prepare_safe_sql(
            f"SELECT `品牌` FROM {SALES_TABLE} LIMIT 10",
            200,
        )
        self.assertIn("LIMIT 10", safe.sql)
        self.assertFalse(safe.limit_rewritten)

    def test_enforces_global_row_cap(self) -> None:
        safe = prepare_safe_sql(
            f"SELECT `品牌` FROM {SALES_TABLE}",
            1000,
        )
        self.assertEqual(safe.max_rows, 200)
        self.assertIn("LIMIT 200", safe.sql)

    def test_allows_cte_with_whitelisted_table(self) -> None:
        safe = prepare_safe_sql(
            "WITH sales AS ("
            f"SELECT `品牌`, SUM(`分摊后金额`) AS amount FROM {SALES_TABLE} "
            "GROUP BY `品牌`) "
            "SELECT `品牌`, amount FROM sales ORDER BY amount DESC",
            50,
        )
        self.assertIn("WITH", safe.sql)
        self.assertIn("LIMIT 50", safe.sql)

    def test_allows_count_star_but_rejects_data_star(self) -> None:
        self.assertEqual(
            validate_sql(f"SELECT COUNT(*) AS total FROM {SALES_TABLE}"),
            [],
        )
        errors = validate_sql(f"SELECT * FROM {SALES_TABLE}")
        self.assertTrue(any("SELECT *" in error for error in errors))

    def test_rejects_write_multi_statement_and_locking_sql(self) -> None:
        cases = [
            f"DELETE FROM {SALES_TABLE}",
            f"SELECT `品牌` FROM {SALES_TABLE}; DROP TABLE x",
            f"SELECT `品牌` FROM {SALES_TABLE} FOR UPDATE",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlSafetyError):
                    prepare_safe_sql(sql, 100)

    def test_rejects_unauthorized_unqualified_and_unknown_columns(self) -> None:
        cases = [
            "SELECT user FROM mysql.user",
            "SELECT `品牌` FROM `销售单明细账`",
            f"SELECT `客户手机号` FROM {SALES_TABLE}",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlSafetyError):
                    prepare_safe_sql(sql, 100)

    def test_rejects_dangerous_functions_and_session_variables(self) -> None:
        cases = [
            f"SELECT SLEEP(1) AS wait_time FROM {SALES_TABLE}",
            f"SELECT @@version AS version FROM {SALES_TABLE}",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlSafetyError):
                    prepare_safe_sql(sql, 100)

    def test_rejects_excessive_joins(self) -> None:
        sql = (
            f"SELECT a.`品牌` FROM {SALES_TABLE} a "
            f"JOIN {SALES_TABLE} b ON a.`订单编号` = b.`订单编号` "
            f"JOIN {SALES_TABLE} c ON a.`订单编号` = c.`订单编号`"
        )
        with self.assertRaises(SqlSafetyError):
            prepare_safe_sql(sql, 100, max_joins=1)


class SqlExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        connection = self.engine.connect()
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ods")
        connection.exec_driver_sql(
            "CREATE TABLE ods.`销售单明细账` "
            "(`品牌` TEXT, `分摊后金额` REAL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO ods.`销售单明细账` VALUES "
            "('A', 10), ('B', 20), ('C', 30)"
        )
        connection.commit()
        connection.close()
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_executes_bounded_readonly_query(self) -> None:
        result = execute_readonly_sql(
            self.db,
            f"SELECT `品牌`, `分摊后金额` FROM {SALES_TABLE} "
            "ORDER BY `分摊后金额` DESC",
            max_rows=2,
            timeout_ms=5000,
        )
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["max_rows"], 2)
        self.assertEqual(result["tables"], ["ods.销售单明细账"])
        self.assertTrue(result["limited"])
        self.assertEqual(result["rows"][0]["品牌"], "C")


class _FakeDialect:
    name = "mysql"


class _FakeBind:
    dialect = _FakeDialect()


class _TimeoutSession:
    bind = _FakeBind()

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.rolled_back = False

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if sql.lstrip().upper().startswith("SELECT"):
            raise OperationalError(
                "statement",
                {},
                TimeoutError("maximum statement execution time exceeded"),
            )
        return None

    def rollback(self) -> None:
        self.rolled_back = True


class SqlTimeoutTest(unittest.TestCase):
    def test_sets_readonly_timeout_and_rolls_back_on_timeout(self) -> None:
        db = _TimeoutSession()
        with self.assertRaises(OperationalError):
            execute_readonly_sql(
                db,
                f"SELECT `品牌` FROM {SALES_TABLE}",
                max_rows=20,
                timeout_ms=5000,
            )
        self.assertEqual(db.statements[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(
            db.statements[1],
            "SET SESSION MAX_EXECUTION_TIME=5000",
        )
        self.assertTrue(db.rolled_back)


class _UnavailableAdminDb:
    def __init__(self) -> None:
        self.rolled_back = False

    def get(self, model, identifier):
        raise OperationalError("statement", {}, OSError("unavailable"))

    def rollback(self) -> None:
        self.rolled_back = True


class ModelConfigFallbackTest(unittest.TestCase):
    @patch("app.services.model_client.settings.OPENAI_API_KEY", "test-key")
    @patch("app.services.model_client.settings.OPENAI_MODEL_ID", "test-model")
    @patch(
        "app.services.model_client.settings.OPENAI_BASE_URL",
        "https://model.example/v1",
    )
    def test_uses_environment_when_admin_database_is_unavailable(self) -> None:
        db = _UnavailableAdminDb()
        config = get_model_config(db)
        self.assertEqual(
            config,
            ("https://model.example/v1", "test-model", "test-key"),
        )
        self.assertTrue(db.rolled_back)


if __name__ == "__main__":
    unittest.main()
