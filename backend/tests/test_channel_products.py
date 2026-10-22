import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.channel_products import load_channel_products


class ChannelProductTests(unittest.TestCase):
    def test_net_sales_scope_filters_and_pagination(self):
        with Session(create_engine('sqlite://')) as db:
            db.execute(text('CREATE TABLE ads_sales_daily_brand_channel_product '
                            '(data_version TEXT, sales_date TEXT, channel TEXT, product TEXT, '
                            'brand TEXT, product_type TEXT, paid_amount NUMERIC, quantity NUMERIC)'))
            rows = [
                ('v1', '2026-09-01', 'A', '水', '兰蔻', '正装', 100, 2),
                ('v1', '2026-09-02', 'A', '水', '兰蔻', '正装', -30, -1),
                ('v1', '2026-09-02', 'A', '霜', '兰蔻', '小样', 20, 3),
                ('v1', '2026-09-02', 'B', '水', '兰蔻', '正装', 900, 9),
                ('v2', '2026-09-02', 'A', '水', '兰蔻', '正装', 800, 8),
                ('v1', '2026-10-01', 'A', '水', '兰蔻', '正装', 700, 7),
            ]
            for row in rows:
                db.execute(text('INSERT INTO ads_sales_daily_brand_channel_product VALUES '
                                '(:v,:d,:c,:p,:b,:t,:a,:q)'), dict(zip('vdcpbtaq', row)))
            args = dict(channel='A', start='2026-09-01', end='2026-09-30', version='v1')
            result = load_channel_products(db, **args, page_size=1)
            self.assertEqual(result['summary']['paid_amount'], 90)
            self.assertEqual(result['summary']['quantity'], 4)
            self.assertEqual(result['pagination']['total'], 2)
            self.assertEqual(result['rows'][0]['paid_amount'], 70)
            second = load_channel_products(db, **args, page_size=1, page=2)
            self.assertEqual(second['rows'][0]['product'], '霜')
            filtered = load_channel_products(db, **args, product_type='正装', keyword='兰蔻')
            self.assertEqual(filtered['summary']['paid_amount'], 70)
            self.assertEqual(filtered['rows'][0]['share'], 100)
            empty = load_channel_products(db, **args, keyword="' OR 1=1 --")
            self.assertEqual(empty['summary']['products'], 0)


if __name__ == '__main__':
    unittest.main()
