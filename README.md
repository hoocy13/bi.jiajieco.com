# Jiajieco BI

Jiajieco 内部经营分析平台，覆盖销售、渠道、品牌、库存、到货、周转、效期、
滞销和库存健康分析，并提供 AI 决策与数据问答入口。

## 技术架构

- 前端：Vue 3、Vite、Vue Router、Pinia、Element Plus、ECharts
- 后端：FastAPI、SQLAlchemy
- 管理数据：SQLite 独立持久化卷
- 业务源数据：MySQL ODS，只读
- 在线分析数据：独立 MySQL ADS，只读查询账号与构建账号分离
- 部署：Docker Compose、GitHub Actions、版本目录切换与失败回滚

生产事实查询使用 ADS：

```text
ODS 业务视图
  → ADS 定时构建
  → 版本化对账与 ready 发布
  → FastAPI
  → Vue 看板
```

在线接口只读取最新 `ready` 版本。ODS 保留为业务源和小型实时维表来源，不承担
页面请求中的百万级实时聚合。

## 项目结构

```text
frontend/              Vue 前端
backend/               FastAPI 后端、ADS 模型与构建任务
docs/                  ADS、性能基线和数据口径文档
ops/                   ADS 定时刷新脚本与 cron
.github/workflows/     生产发布工作流
docker-compose.yml     生产容器编排
AGENT.md               完整业务口径与开发说明
AGENTS.md              Codex 协作和验收约定
```

## 本地启动

后端：

```powershell
cd D:\code\bi.jiajieco.com\backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd D:\code\bi.jiajieco.com\frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5174
```

- 前端：`http://127.0.0.1:5174`
- 后端：`http://127.0.0.1:8000`
- API 前缀：`/api/v1`
- 统一响应：`{ "code": 0, "message": "ok", "data": {} }`

账号、密码、数据库连接和模型密钥只通过本地环境配置或安全的仓库 Secret
维护，不写入 README、源码或日志。

## 当前功能

### 经营与智能

- `/dashboard`：经营总览
- `/ai/decisions`：AI 决策中心
- `/ai/text-to-sql`：数据智能问答

### 销售分析

- `/sales/overview`：销售概览
- `/sales/detail`：销售明细
- `/sales/product-rank`：商品销售排行
- `/sales/brand-analysis`：品牌销售分析
- `/sales/brand-analysis/:brand`：品牌经营下钻
- `/sales/channel-analysis`：渠道分析

### 库存分析

- `/inventory/overview`：库存总览
- `/inventory/brand-arrivals`：品牌月度到货
- `/inventory/turnover`：品牌周转与商品周转
- `/inventory/slow-moving`：滞销库存
- `/inventory/batch-expiry`：批次效期与 FEFO
- `/inventory/health`：库存健康

### 系统管理

- `/users`：用户管理
- `/model-settings`：模型设置

## 数据与权限原则

- ODS 账号只授予 `SELECT`、`SHOW VIEW`，分析接口禁止修改源数据。
- ADS 在线账号只读；ADS 构建账号仅拥有目标表所需的最小写权限。
- 汇总与明细必须使用一致的日期、品牌、分类、仓库和渠道条件。
- 订单、SKU、入库单的去重口径必须明确，退货、红冲和负数记录参与净额计算。
- 新增筛选条件时必须同步更新 SQL、缓存键和组合筛选测试。
- 页面需要展示数据更新时间；库存数据是每日同步快照，不等同于业务实时库存。

详细口径见 [AGENT.md](./AGENT.md)，ADS 设计见
[销售 ADS](./docs/ads-sales-pilot.md) 和
[库存 ADS](./docs/ads-inventory-overview.md)。

## 性能与验证

核心接口响应包含请求、数据库、ODS 和 ADS 耗时诊断头。当前约定：

- 常用 ADS 冷查询目标不超过 1 秒，复杂页面不超过 3 秒。
- 热访问 P95 不超过 500 ms。
- 大数据量使用后端分页、数据库聚合和 Top N，不把大量事实行拉到 Python 聚合。
- 后端修改至少执行对应模块 `py_compile` 和后端单元测试。
- 前端修改至少执行 `npm.cmd run build`。
- 口径或筛选修改至少验证默认条件与一组组合筛选。
- 视觉或交互修改必须检查浏览器实际渲染和控制台错误。

历史基线与诊断方式见 [性能基线](./docs/performance-baseline.md)。

## ADS 构建

后端构建任务：

```powershell
cd D:\code\bi.jiajieco.com\backend
.\.venv\Scripts\python.exe -m app.jobs.build_sales_ads
.\.venv\Scripts\python.exe -m app.jobs.build_inventory_ads
```

构建流程创建新版本、执行口径对账，成功后才发布为 `ready`。生产每日定时刷新
销售和库存 ADS，并通过互斥锁阻止任务重叠。

## 生产发布

GitHub Actions 工作流 `Deploy BI` 默认执行快速应用发布，不重建 ADS。只有 ADS
模型、构建逻辑或数据内容需要刷新时，才按需启用：

- `rebuild_sales_ads`
- `rebuild_inventory_ads`

带 ADS 重建的发布会先构建候选镜像和数据，核对成功后再切换应用；普通代码发布
跳过数据重建。部署失败会恢复上一版本，生产发布之间不会并发执行。

## 下一阶段方向

优先级建议：

1. 建立 Prometheus/OpenTelemetry 指标、P95/P99 看板和慢接口告警。
2. 将进程内缓存升级为 Redis，共享缓存、请求合并和主动失效。
3. 将 ADS 构建升级为增量流水线，保留周期性全量对账。
4. 引入统一语义层和指标注册表，集中管理销售额、库存、周转等口径。
5. 数据规模继续增长后，再评估 ClickHouse 等列式 OLAP；当前不建议仅为技术升级
   立即迁移数据库。
