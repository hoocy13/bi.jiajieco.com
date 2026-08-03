# BI 数据源审计

审计日期：2026-08-03。

## 结论

- BI 默认查询模式为 `ads`。
- ADS 在线查询只读取 `ads_publish_batch` 中最新的 `ready` 版本，并在所有事实表查询中带上同一个 `data_version`。
- 销售明细级查询与销售 ADS 构建统一读取 `dwd.销售单明细账_品牌补全`。
- 销售订单头统一读取 `dwd.销售单查询_进口超市上海仓补全`。
- `ods.历史库存`、`ods.历史库存快照批次` 和 `ods.渠道列表` 仍按业务口径直接使用。

## 页面与最终事实表

| 页面 / API | 默认事实表 |
|---|---|
| 首页销售概览、销售总览 | `ads.ads_sales_daily`、`ads.ads_sales_daily_channel`、`ads.ads_sales_daily_city_channel` |
| 销售订单明细 | `ads.ads_sales_order_detail`、`ads.ads_sales_order_daily_filter` |
| 商品销售 | `ads.ads_sales_detail_daily`、`ads.ads_sales_daily_product`、`ads.ads_sales_detail_daily_scope` |
| 品牌销售 | `ads.ads_sales_daily_brand_scope`、`ads.ads_sales_daily_brand_product` |
| 渠道销售 / 客户下钻 | `ads.ads_sales_detail_daily_channel`、`ads.ads_sales_daily_channel_customer` |
| 品牌渠道 | `ads.ads_sales_daily_brand_channel_scope`、`ads.ads_sales_daily_brand_channel_product` |
| 库存总览 | `ads.ads_inventory_product_warehouse`、`ads.ads_inventory_batch_summary` |
| 库存健康 / 滞销库存 | `ads.ads_inventory_health_item`、`ads.ads_inventory_turnover_item` |
| 批次与效期 | `ads.ads_inventory_batch_item` |
| 商品周转 | `ads.ads_inventory_turnover_item` |
| 品牌周转 | `ads.ads_inventory_turnover_item`、`ads.ads_sales_brand_turnover_item`、`ads.ads_sales_brand_turnover_order` |
| 品牌月度到货 | `ads.ads_inventory_arrival_item` |
| 库存筛选项 | `ads.ads_inventory_filter_option` |
| 品牌进销存历史水位 | `dwd.销售单明细账_品牌补全`、`ods.历史库存`、`ods.历史库存快照批次`；入库流量暂按日级 ODS 明细计算 |
| 品牌进销存周转分析 | 销售使用 `ads.ads_sales_brand_turnover_item`、`ads.ads_sales_daily_brand_channel_scope`；库存使用正式历史快照 ODS |

## 保留的在线 ODS 用途

- `ods.历史库存`、`ods.历史库存快照批次`：历史月末快照，没有同口径 ADS 替代。
- `ods.渠道列表`：小型渠道维表，用于线上 / 线下和平台属性补充。
- 品牌进销存的历史入库流量：需要与历史月末库存按月衔接，目前从 `ods.入库查询`、`ods.入库查询明细` 精确到日计算。
- ADS 不可用时的兼容回退分支仍保留，但回退销售事实已改为 DWD，不再直接读取原始销售 ODS。

## 配置要求

生产环境必须配置 `ADS_DATABASE_URL`，并使用 `BI_QUERY_SOURCE=ads`。本地若未配置 ADS 连接，不能仅切换该变量，否则无法验证 ADS 页面数据。
