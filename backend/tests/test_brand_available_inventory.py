import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.services.brand_inventory_flow import load_brand_available_inventory


class AvailableInventoryTests(unittest.TestCase):
    def test_default_and_combined_filters_preserve_negative_stock(self):
        engine = create_engine('sqlite://')
        with Session(engine) as db:
            db.execute(text('CREATE TABLE `分仓库查询` (`品牌` TEXT, `仓库` TEXT, `货品分类` TEXT, `可用库存` NUMERIC)'))
            db.execute(text("INSERT INTO `分仓库查询` VALUES ('品牌甲','仓库一','正装',100),('品牌甲','仓库一','正装',-5),('品牌甲','仓库二','小样',30),('品牌乙','仓库一','正装',900),('品牌甲','仓库一','赠品',20)"))
            self.assertEqual(load_brand_available_inventory(db, brand='品牌甲'), 125)
            self.assertEqual(load_brand_available_inventory(db, brand='品牌甲', warehouses=('仓库一',), product_types=('正装',)), 95)
            self.assertEqual(load_brand_available_inventory(db, brand='不存在'), 0)
        engine.dispose()
