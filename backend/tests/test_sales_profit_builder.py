import unittest
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.jobs.build_sales_profit_ads import (
    DATASET,
    DECIMAL_FIELDS,
    MAX_SOURCE_DAYS,
    SOURCE_GROUP_SQL,
    SOURCE_SUMMARY_SQL,
    iter_source_profit_rows,
    load_source_summary,
    normalize_summary,
    prune_old_profit_versions,
    publish_profit_rows,
    reconciliation_payload,
    resolve_source_range,
    source_chunks,
)
from app.models.ads import AdsPublishBatch, AdsSalesProfitDaily


def profit_row(**overrides) -> dict:
    row = {
        "sales_date": date(2026, 10, 8),
        "brand": "brand",
        "channel": "channel",
        "customer_code": "client",
        "customer_name": "client name",
        "product_code": "sku",
        "product_name": "product",
        "product_type": "full size",
        "quantity": Decimal("8"),
        "paid_amount": Decimal("800.23"),
        "sale_quantity": Decimal("10"),
        "sale_amount": Decimal("1000.23"),
        "return_quantity": Decimal("2"),
        "return_amount": Decimal("200"),
        "source_rows": 3,
    }
    row.update(overrides)
    return row


def source_summary(rows: list[dict]) -> dict:
    result = normalize_summary({})
    for row in rows:
        for key in DECIMAL_FIELDS:
            result[key] += row[key]
        result["source_rows"] += row["source_rows"]
    result["source_max_updated_at"] = datetime(2026, 10, 9, 10, 0)
    result["max_sales_date"] = date(2026, 10, 8)
    return result


class SalesProfitRangeTests(unittest.TestCase):
    def test_default_is_93_days_anchored_to_source(self):
        start, end = resolve_source_range(date(2026, 10, 8))
        self.assertEqual(end, date(2026, 10, 8))
        self.assertEqual((end - start).days + 1, MAX_SOURCE_DAYS)

    def test_custom_range_checks_limit_future_and_reversal(self):
        with self.assertRaises(ValueError):
            resolve_source_range(date(2026, 10, 8), date(2026, 1, 1))
        with self.assertRaises(ValueError):
            resolve_source_range(date(2026, 10, 8), end_date=date(2026, 10, 9))
        with self.assertRaises(ValueError):
            resolve_source_range(date(2026, 10, 8), date(2026, 10, 8), date(2026, 10, 1))

    def test_source_query_keeps_net_values_and_anonymous_customers(self):
        self.assertIn("SUM(COALESCE(l.`数量`, 0)) AS quantity", SOURCE_GROUP_SQL)
        self.assertIn("COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '')", SOURCE_GROUP_SQL)
        self.assertNotIn("customer_code IS NOT NULL", SOURCE_GROUP_SQL)
        self.assertIn("GROUP BY `订单编号`", SOURCE_GROUP_SQL)
        self.assertIn("l.`下单时间` < :end_exclusive", SOURCE_GROUP_SQL)
        self.assertIn("COUNT(*) AS source_rows", SOURCE_SUMMARY_SQL)
        self.assertNotIn("`毛利`", SOURCE_GROUP_SQL)
        self.assertNotIn("`货品成本`", SOURCE_GROUP_SQL)

    def test_weekly_chunks_cover_dates_once_with_exclusive_end(self):
        chunks = list(source_chunks(date(2026, 9, 1), date(2026, 9, 16)))
        self.assertEqual(chunks, [
            {"start_date": date(2026, 9, 1), "end_exclusive": date(2026, 9, 8)},
            {"start_date": date(2026, 9, 8), "end_exclusive": date(2026, 9, 15)},
            {"start_date": date(2026, 9, 15), "end_exclusive": date(2026, 9, 17)},
        ])
        self.assertEqual(sum((chunk["end_exclusive"] - chunk["start_date"]).days for chunk in chunks), 16)

    def test_empty_chunks_do_not_erase_latest_source_date(self):
        class Result:
            def __init__(self, value):
                self.value = value

            def mappings(self):
                return self

            def one(self):
                return self.value

        class Source:
            def __init__(self):
                self.responses = iter([
                    source_summary([profit_row()]),
                    {"source_rows": 0, "quantity": None, "max_sales_date": None, "source_max_updated_at": None},
                ])

            def execute(self, statement, params):
                return Result(next(self.responses))

        summary = load_source_summary(Source(), date(2026, 10, 1), date(2026, 10, 8))
        self.assertEqual(summary["source_rows"], 3)
        self.assertEqual(summary["max_sales_date"], date(2026, 10, 8))
        self.assertEqual(summary["paid_amount"], Decimal("800.23"))

    def test_grouped_cursor_is_consumed_and_closed_before_next_chunk(self):
        class Result:
            def __init__(self, row):
                self.row = row
                self.closed = False

            def mappings(self):
                return iter([self.row])

            def close(self):
                self.closed = True

        class Source:
            def __init__(self):
                self.results = []

            def execute(self, statement, params):
                if self.results:
                    self.assert_previous_closed = self.results[-1].closed
                    if not self.assert_previous_closed:
                        raise AssertionError("Previous streaming cursor still open")
                result = Result(profit_row(sales_date=params["start_date"]))
                self.results.append(result)
                return result

        source = Source()
        rows = list(iter_source_profit_rows(source, date(2026, 10, 1), date(2026, 10, 8)))
        self.assertEqual([row["sales_date"] for row in rows], [date(2026, 10, 1), date(2026, 10, 8)])
        self.assertTrue(all(result.closed for result in source.results))


class SalesProfitPublishTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        AdsPublishBatch.__table__.create(self.engine)
        AdsSalesProfitDaily.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def publish(self, rows, summary=None, version="profit-test"):
        return publish_profit_rows(
            self.db, iter(rows), summary or source_summary(rows),
            date(2026, 10, 1), date(2026, 10, 8), data_version=version,
        )

    def test_source_group_and_persisted_metrics_match_before_ready(self):
        rows = [profit_row(), profit_row(customer_code="", customer_name=None, product_code=None)]
        result = self.publish(rows)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["reconciliation"]["passed"])
        self.assertEqual(result["reconciliation"]["source"]["source_rows"], 6)
        self.assertEqual(result["reconciliation"]["max_sales_date"], "2026-10-08")
        self.assertEqual(result["reconciliation"]["source_max_updated_at"], "2026-10-09T10:00:00")
        anonymous = self.db.execute(select(AdsSalesProfitDaily).where(
            AdsSalesProfitDaily.customer_code == "",
        )).scalar_one()
        self.assertEqual(anonymous.product_code, "")
        self.assertEqual(anonymous.quantity, Decimal("8"))
        self.assertEqual(anonymous.sale_quantity, Decimal("10"))
        self.assertEqual(anonymous.return_amount, Decimal("200"))

    def test_mismatch_marks_failed_and_cannot_reuse_immutable_version(self):
        rows = [profit_row()]
        summary = source_summary(rows)
        summary["paid_amount"] += Decimal("0.01")
        with self.assertRaises(RuntimeError):
            self.publish(rows, summary)
        batch = self.db.execute(select(AdsPublishBatch)).scalar_one()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.error_code, "RuntimeError")
        self.assertEqual(batch.reconciliation["mismatches"], ["paid_amount"])
        with self.assertRaises(ValueError):
            self.publish(rows)

    def test_exact_reconciliation_includes_source_row_count_and_signs(self):
        summary = source_summary([profit_row()])
        matching = reconciliation_payload(summary, summary, summary)
        self.assertTrue(matching["passed"])
        incorrect = dict(summary, return_amount=Decimal("199.99"), source_rows=2)
        mismatch = reconciliation_payload(summary, incorrect, summary)
        self.assertFalse(mismatch["passed"])
        self.assertEqual(mismatch["mismatches"], ["return_amount", "source_rows"])

    def test_chunked_publication_retains_all_rows(self):
        rows = [profit_row(customer_code=f"c{index}") for index in range(1003)]
        result = self.publish(rows)
        self.assertEqual(result["daily_row_count"], 1003)
        self.assertTrue(result["reconciliation"]["passed"])

    def test_sqlite_decimal_reconciliation_avoids_float_sum_drift(self):
        rows = [profit_row(customer_code=f"c{index}", paid_amount=Decimal("12345678.90")) for index in range(1100)]
        result = self.publish(rows)
        self.assertTrue(result["reconciliation"]["passed"])
        self.assertEqual(result["reconciliation"]["ads"]["paid_amount"], "13580246790.000000")

    def test_pruning_only_touches_older_versions_of_this_dataset(self):
        for index in range(3):
            self.publish([profit_row()], version=f"profit-{index}")
        self.db.add(AdsPublishBatch(
            data_version="other-dataset", dataset="sales_daily", status="ready",
            source_start_date=date(2026, 1, 1), source_end_date=date(2026, 1, 1),
            created_at=datetime(2026, 1, 1), published_at=datetime(2026, 1, 1),
        ))
        self.db.commit()
        removed = prune_old_profit_versions(self.db)
        self.assertEqual(removed, {"profit-0": 1})
        remaining = self.db.execute(select(AdsPublishBatch).where(
            AdsPublishBatch.dataset == DATASET, AdsPublishBatch.status == "ready",
        )).scalars().all()
        self.assertEqual(len(remaining), 2)
        other = self.db.execute(select(AdsPublishBatch).where(
            AdsPublishBatch.data_version == "other-dataset",
        )).scalar_one()
        self.assertEqual(other.status, "ready")
        with self.assertRaises(ValueError):
            prune_old_profit_versions(self.db, keep_ready=1)


if __name__ == "__main__":
    unittest.main()
