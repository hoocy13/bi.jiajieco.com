# bi.jiajieco.com

Jiajieco 管理后台 / BI 看板第一版骨架。

## 技术栈

- 前端：Vue 3 + Vite + Vue Router + Pinia + Element Plus + ECharts
- 后端：FastAPI + SQLAlchemy + SQLite 登录库 + MySQL ODS 只读库
- 接口：统一返回 `{ "code": 0, "message": "ok", "data": {} }`

## 本地启动

后端：

```powershell
cd D:\code\bi.jiajieco.com\backend
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

前端：

```powershell
cd D:\code\bi.jiajieco.com\frontend
npm.cmd install
npm.cmd run dev
```

登录账号：

```text
admin / admin123
```

## 当前菜单

- `/dashboard` 经营总览
- `/sales/overview` 销售概览，已接入 ods 只读库
- `/sales/detail` 销售明细
- `/sales/product-rank` 商品销售排行
- `/inventory/overview` 库存概览
- `/inventory/turnover` 库存周转
- `/inventory/slow-moving` 滞销商品
- `/users` 用户管理

## 线上只读库

后端通过 `backend/.env` 中的 `ODS_DATABASE_URL` 连接线上 MySQL `ods` 库。该账号应只保留 `SELECT, SHOW VIEW` 权限。

已接入接口：

```text
GET /api/v1/sales/overview
GET /api/v1/inventory/overview
GET /api/v1/inventory/turnover
GET /api/v1/inventory/brand-turnover
GET /api/v1/inventory/slow-moving
```

当前销售概览口径：

```text
数据表：ods.销售单查询
时间字段：下单时间
金额字段：实付金额
数量字段：货品数量
订单字段：订单编号
```

## 下一阶段

1. 将销售明细接入 `ods.销售单查询`。
2. 将商品销售排行接入 `ods.销售单明细账`。
3. 将库存概览接入 `ods.总库存查询`。
4. 将库存周转和滞销商品接入 `近30天销量`、`近90天销量(库存公式)` 等字段。
5. 后续补角色、菜单权限、导出和部署配置。
