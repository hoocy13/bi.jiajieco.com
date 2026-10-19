import unittest
from app.services.monthly_operating_analysis import changes, inventory_analysis

class OperatingAnalysisTests(unittest.TestCase):
    def test_changes_keep_lost_and_new_channels_without_infinite_growth(self):
        rows=[dict(key='old',period='2026-08',paid_amount=100),dict(key='new',period='2026-09',paid_amount=20)]
        got=changes(rows,'2026-09','2026-08')
        self.assertEqual(got[0]['name'],'new');self.assertIsNone(got[0]['mom'])
        self.assertEqual(got[1]['change'],-100);self.assertEqual(got[1]['mom'],-1)
    def test_inventory_merges_warehouses_and_uses_month_days(self):
        got=inventory_analysis([dict(product_code='a',product='a',quantity=30)],
            [dict(product_code='a',product='a',stock=3),dict(product_code='a',product='a',stock=6)],30)
        self.assertEqual(got['low'][0]['stock'],9);self.assertEqual(got['low'][0]['days'],9)
    def test_returns_and_negative_stock_are_not_restock_suggestions(self):
        got=inventory_analysis([dict(product_code='r',quantity=-10)],
            [dict(product_code='r',stock=3),dict(product_code='n',stock=-2),dict(product_code='z',stock=50)],30)
        self.assertEqual(got['low'],[]);self.assertEqual(got['exception_count'],2)
        self.assertEqual(got['high'][0]['signal'],'本月无净动销')
    def test_missing_stock_is_not_zero_stock(self):
        got=inventory_analysis([dict(product_code='bundle',quantity=300)],[],30)
        self.assertEqual(got['low'],[]);self.assertEqual(got['unmatched_sales_skus'],1)

    def test_missing_codes_are_not_name_matched(self):
        got=inventory_analysis([dict(product_code='-',product='same',quantity=30)],
            [dict(product_code='real',product='same',stock=2)],30)
        self.assertEqual(got['low'],[]);self.assertEqual(got['missing_code_sales_quantity'],30)

if __name__=='__main__':unittest.main()
