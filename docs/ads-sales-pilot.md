# 销售 ADS 试点

## 目标

销售 ADS 将页面高频聚合从 ODS 请求链路移到独立查询库。ODS 仅由构建任务读取，FastAPI 请求不通过 ADS 连接执行写操作。

当前生产销售概览使用以下配置直接读取 ADS：

```env
BI_QUERY_SOURCE=ads
```

## 权限边界

使用两个 ADS 账号：

- `ADS_DATABASE_URL`：FastAPI 使用，只授予 `ads` 的 `SELECT` 权限。
- `ADS_BUILD_DATABASE_URL`：独立构建任务使用，仅授予销售 ADS 表所需的 `SELECT`、`INSERT`、`UPDATE` 权限。

两者都必须指向独立的 `ads` 数据库。程序会拒绝将 ADS 配置为 ODS 数据库，防止构建任务误写源库。

数据库和账号由运维或 DBA 创建，不在代码、文档或日志中保存真实密码。

构建任务使用独立的 ODS 读取超时配置，默认允许聚合任务运行 300 秒，不会放宽在线 API 的 30 秒查询超时：

```env
ODS_BUILD_READ_TIMEOUT_SECONDS=300
```

## 表结构

### `ads_publish_batch`

记录不可变数据版本、构建范围、状态、行数和对账结果。

状态：

- `building`：正在构建，API 不可读取。
- `ready`：构建及对账成功，可以发布。
- `failed`：构建或对账失败，API 不可读取。

### `ads_sales_daily`

粒度为“数据版本 × 销售日期”，保存：

- 净实付金额；
- 净销售数量；
- 货品数量大于 0 的订单编号去重数。

用于销售概览指标和趋势。

### `ads_sales_daily_channel`

粒度为“数据版本 × 销售日期 × 原始销售渠道”，保存相同指标。

渠道为空时归为“未归类”。该表用于渠道排行和占比，但渠道订单数不能跨渠道直接累加为全局订单数。

### `ads_sales_daily_city_channel`

粒度为“数据版本 × 销售日期 × 城市 × 原始销售渠道”，保存净实付金额和净销售数量，用于首页销售看板的城市渠道构成地图。

### `ads_sales_detail_daily`

粒度为“数据版本 × 销售日期”，保存销售单明细账的订单去重数、分摊后金额和数量，用于商品排行的整体汇总。

### `ads_sales_daily_product`

粒度为“数据版本 × 销售日期 × 商品名称”，保存订单去重数、分摊后金额和数量，用于商品金额排行、数量排行和商品关键字筛选。

### `ads_sales_detail_daily_scope`

粒度为“数据版本 × 销售日期 × 货品分类范围”，预计算全部、正装、小样、正装与小样四种范围的明细总汇总。

### `ads_sales_daily_brand_scope`

粒度为“数据版本 × 销售日期 × 货品分类范围 × 品牌”，保存品牌排行所需的订单去重数、金额和数量。

### `ads_sales_daily_brand_product`

粒度为“数据版本 × 销售日期 × 品牌 × 货品分类 × 商品”，用于品牌商品数去重和后续品牌下钻。

### `ads_sales_brand_turnover_item`

粒度为“数据版本 × 销售日期 × 发货仓库 × 品牌 × 货品分类 × 商品”，保存货品编号、商品名称、净销售数量和分摊后金额，用于品牌周转和品牌下商品周转。

构建时按月读取 ODS，避免全年度单条查询超过数据库读取时限。

### `ads_sales_brand_turnover_order`

保存品牌周转所需的日订单去重汇总，覆盖全部仓、单仓和页面默认双仓，以及全部、正装、小样、正装与小样四种货品分类范围。非常规多仓或分类组合由接口安全回退 ODS。

### `ads_sales_detail_daily_channel`

粒度为“数据版本 × 销售日期 × 渠道”，保存销售单明细账的订单去重数、分摊后金额和数量。渠道类型、平台、负责人和授权状态仍实时读取渠道主数据。

### 剩余慢接口表

- `ads_sales_order_detail`：销售明细页所需的窄字段事实表，按 5,000 行分批写入，并为日期、渠道、状态和订单编号建立索引。
- `ads_sales_daily_channel_customer`：按“日期 × 渠道 × 客户”聚合，用于渠道客户下钻及关键字分页。
- `ads_sales_daily_brand_channel_scope`：按“日期 × 品牌 × 渠道 × 货品分类范围”聚合，保证品牌渠道汇总和趋势的订单去重口径。
- `ads_sales_daily_brand_channel_product`：按“日期 × 品牌 × 渠道 × 分类 × 商品”聚合，用于品牌渠道商品和负责人正装/小样分析。

渠道主数据仍从 ODS 小表实时读取，事实统计全部从 ADS 读取。

## 初始化

配置环境变量后，在 `backend/` 执行：

```powershell
.venv\Scripts\python.exe -m app.jobs.build_sales_ads --initialize-only
```

初始化完成后，可以撤销构建账号的 DDL 权限。当前版本化构建只需要销售 ADS 表上的 `SELECT`、`INSERT`，以及发布批次表上的 `UPDATE`。

## 构建

全量构建：

```powershell
.venv\Scripts\python.exe -m app.jobs.build_sales_ads
```

指定日期范围：

```powershell
.venv\Scripts\python.exe -m app.jobs.build_sales_ads --start-date 2026-07-01 --end-date 2026-07-25
```

任务执行以下流程：

1. 在 ADS 创建 `building` 批次；
2. 只读查询 ODS 每日总汇总；
3. 只读查询 ODS 每日渠道汇总；
4. 写入新 `data_version`；
5. 分别核对订单数、净金额和净数量；
6. 核对明细日汇总与商品汇总的金额、数量和订单口径；
7. 核对品牌分类范围与品牌商品汇总的金额、数量和订单口径；
8. 核对渠道日汇总的金额和数量口径；
9. 核对城市渠道日汇总的金额和数量口径；
10. 核对品牌周转的订单数、金额和数量口径；
11. 核对销售明细、渠道客户、品牌渠道范围和品牌渠道商品口径；
12. 对账成功后原子标记为 `ready`；
13. 失败时回滚数据并将批次标记为 `failed`。

构建日志只输出版本、日期范围和行数，不输出连接地址、账号、密码、Token 或业务明细。

同一 MySQL 实例中，销售明细窄表优先由构建账号在数据库服务器内按月执行
`INSERT ... SELECT`。构建账号只额外拥有源销售视图的 `SELECT`，不拥有 ODS
写权限；不同数据库服务器的环境自动回退为 5,000 行分批传输。

## 部署

应用发布默认不重建 ADS。手动触发 `Deploy BI` 时可按需勾选：

- `rebuild_sales_ads`
- `rebuild_inventory_ads`

勾选后，工作流先从待发布代码构建候选后端镜像，并在旧站持续服务期间完成
ADS 构建和对账。只有构建成功后才切换应用目录；构建失败或任务取消不会替换
当前线上版本。普通代码发布跳过 ADS 构建，可显著缩短服务器部署时间。

## 发布规则

API 后续只读取：

```sql
SELECT `data_version`
FROM `ads_publish_batch`
WHERE `dataset` = 'sales_daily'
  AND `status` = 'ready'
ORDER BY `published_at` DESC
LIMIT 1;
```

生产发布会先生成新的完整版本并完成汇总核对，再以 `BI_QUERY_SOURCE=ads` 启动销售概览。发布后的定时任务每天北京时间 06:30 构建一次；`flock` 防止任务重叠执行。

## 查询模式

销售概览支持三种模式：

```env
BI_QUERY_SOURCE=ods
```

- 只查询并返回 ODS。

```env
BI_QUERY_SOURCE=dual
```

- 查询并返回 ODS；
- 同时读取最新 `ready` ADS 版本；
- 比较日期范围、订单数、净金额、净数量、每日趋势和渠道排行；
- 差异只记录字段路径，不记录业务数值或查询参数；
- ADS 不可用或比较失败时不影响 ODS 响应。

```env
BI_QUERY_SOURCE=ads
```

- 只返回最新 `ready` ADS 版本；
- 不创建 ODS 请求会话；
- ADS 未配置、没有可用版本或版本不覆盖筛选日期时返回 503。

诊断响应头：

- `X-BI-Query-Mode`
- `X-BI-Response-Source`
- `X-BI-Dual-Status`

`X-BI-Dual-Status` 可能为：

- `matched`
- `mismatch`
- `unavailable`
- `error`
- `cached`：本次命中应用缓存，没有重新执行双跑比较

建议至少完成默认条件和组合筛选的连续双跑核对，再切换到 `ads`。
