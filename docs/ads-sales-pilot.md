# 销售 ADS 试点

## 目标

销售 ADS 将页面高频聚合从 ODS 请求链路移到独立查询库。ODS 仅由构建任务读取，FastAPI 请求不通过 ADS 连接执行写操作。

当前阶段只建立数据构建和发布基础设施，线上接口仍由以下配置保持在 ODS：

```env
BI_QUERY_SOURCE=ods
```

## 权限边界

使用两个 ADS 账号：

- `ADS_DATABASE_URL`：FastAPI 使用，只授予 `bi_ads` 的 `SELECT` 权限。
- `ADS_BUILD_DATABASE_URL`：独立构建任务使用，授予 ADS 表的写权限。

两者都必须指向独立的 `bi_ads` 数据库。程序会拒绝将 ADS 配置为 ODS 数据库，防止构建任务误写源库。

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

## 初始化

配置环境变量后，在 `backend/` 执行：

```powershell
.venv\Scripts\python.exe -m app.jobs.build_sales_ads --initialize-only
```

初始化完成后，可以撤销构建账号的 DDL 权限，只保留 `SELECT`、`INSERT`、`UPDATE` 和 `DELETE`。

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
6. 对账成功后原子标记为 `ready`；
7. 失败时回滚数据并将批次标记为 `failed`。

构建日志只输出版本、日期范围和行数，不输出连接地址、账号、密码、Token 或业务明细。

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

在 ODS/ADS 双跑核对完成之前，不修改 `BI_QUERY_SOURCE=ods`。

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
