import unittest

from app.services.sales_sources import is_online_sales_channel


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
