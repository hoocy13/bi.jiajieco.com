import unittest
import sqlite3

from app.services.sales_sources import ACTIVE_SALES_ORDER_SQL, is_online_sales_channel


class SalesOrderStatusTests(unittest.TestCase):
    def test_active_order_filter_excludes_pending_review_and_cancelled_orders(self):
        statuses = ['待审核', '审核中', '待复核', '复核中', '取消', '已取消',
                    '已发货', '已完成', '', None]
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE orders (`订单状态` TEXT)')
            db.executemany('INSERT INTO orders VALUES (?)', [(s,) for s in statuses])
            actual = [row[0] for row in db.execute(
                f'SELECT `订单状态` FROM orders WHERE {ACTIVE_SALES_ORDER_SQL}'
            )]
        self.assertEqual(actual, ['已发货', '已完成', '', None])


class SalesChannelClassificationTests(unittest.TestCase):
    def test_wuyan_category_is_online_without_platform(self):
        self.assertTrue(is_online_sales_channel("梧颜", "未设置", "梧颜友谊分销"))

    def test_wuyan_alias_is_online_without_dimension_match(self):
        self.assertTrue(is_online_sales_channel("未匹配渠道", "未设置", "枷美妆-抖店"))

    def test_jd_channel_is_online_even_if_it_was_in_sales_department(self):
        self.assertTrue(is_online_sales_channel("销售部渠道", "京东", "京东政企"))

    def test_regular_sales_department_channel_remains_offline(self):
        self.assertFalse(is_online_sales_channel("销售部渠道", "未设置", "张婷婷"))


if __name__ == "__main__":
    unittest.main()
