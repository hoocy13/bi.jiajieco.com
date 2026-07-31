# RAG MVP 开发启动说明

完整范围和验收口径见项目根目录 `AGENT.md` 的“企业知识与数据问答 MVP V1”。

## 启动基础设施

首次启动前，在当前 PowerShell 会话设置一个强随机密码：

```powershell
$env:RAG_POSTGRES_PASSWORD = "<通过安全方式生成的强密码>"
docker compose -f docker-compose.yml -f docker-compose.rag.yml config
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --build
```

生产环境通过部署系统 Secret 或受保护的环境文件提供
`RAG_POSTGRES_PASSWORD`，不得把真实密码写入仓库、文档或日志。

基础设施启动后执行 PostgreSQL 初始迁移：

```powershell
cd backend
$env:RAG_DATABASE_URL = "postgresql+psycopg://rag_user:<密码>@127.0.0.1:5432/jjc_bi_rag"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

生产容器不映射 PostgreSQL 端口，应在后端容器中执行迁移：

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml \
  exec backend python -m alembic upgrade head
```

现有、不启用 RAG 的部署命令保持不变：

```powershell
docker compose -f docker-compose.yml up -d --build
```

## 验证

登录后访问：

```text
GET /api/v1/rag/health
```

预期 PostgreSQL、Redis、Qdrant 均为 `available`，整体 `ready=true`。

所有新增基础设施仅使用 Docker `expose`，不映射到宿主机公网端口。

## 配置 Embedding

MiMo Chat Model 用于后续答案生成。知识向量化需要单独配置支持 OpenAI-compatible
`/embeddings` 的模型服务：

```text
RAG_EMBEDDING_BASE_URL=
RAG_EMBEDDING_MODEL_ID=
RAG_EMBEDDING_API_KEY=
RAG_EMBEDDING_DIMENSIONS=0
RAG_EMBEDDING_BATCH_SIZE=10
```

维度为 `0` 表示由服务默认模型决定。第一次入库后不得直接更换向量维度；如需更换，
应创建新的 Qdrant Collection 并重新索引。

国内服务器的 MVP 推荐使用阿里云百炼 OpenAI-compatible Embedding：

```text
RAG_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RAG_EMBEDDING_MODEL_ID=text-embedding-v4
RAG_EMBEDDING_DIMENSIONS=1024
RAG_EMBEDDING_BATCH_SIZE=10
```

API Key 只写入服务器受保护的 `backend/.env`。MiMo Chat Model 的 Key 与
Embedding Key 分开管理。

## 执行知识入库

知识文件审核为 `status: active` 后，以管理员身份调用：

```text
POST /api/v1/rag/admin/reindex
```

查看每份文档的任务：

```text
GET /api/v1/rag/admin/jobs
GET /api/v1/rag/admin/jobs/{job_id}
```

检索调试：

```text
POST /api/v1/rag/search

{
  "question": "品牌周转天数为什么不是标准库存周转率？",
  "limit": 5
}
```

## M3 知识问答

当前 M3 第一版使用 LangGraph 单图工作流：

```text
normalize_question
  → route_intent
  → knowledge: retrieve_knowledge → compose_answer
  → metric: call_metric_tool → compose_metric_answer
  → mixed: 拆分口径与数据子问题
      → retrieve_knowledge
      → call_metric_tool
      → compose_metric_answer
  → sql: unsupported_route
```

当前指标白名单包括销售概览和品牌周转。工具直接复用现有 BI 查询函数，并在 ODS
连接上使用只读事务；展示数字由代码格式化，不交给模型改写。暂未支持的指标和 SQL
会明确提示能力范围，不会猜测或错误选择其他工具。

销售概览支持近 30 天、本月、本年和 `YYYY-MM-DD` 起止日期。品牌周转支持年度、
季度、品牌、正装/小样和最低可用库存；未指定季度时沿用页面的上一个完整季度默认值。
每次指标调用会把工具名、解析参数、数据来源和精简结果保存到 `rag_runs.trace`。

创建会话：

```text
POST /api/v1/rag/conversations

{
  "title": "库存口径问答"
}
```

执行知识问答：

```text
POST /api/v1/rag/conversations/{conversation_id}/runs

{
  "question": "品牌周转天数为什么不是标准库存周转率？"
}
```

查询历史：

```text
GET /api/v1/rag/conversations
GET /api/v1/rag/conversations/{conversation_id}
GET /api/v1/rag/runs/{run_id}
```

回答中的 `[1]`、`[2]` 与响应中的 `citations[].ordinal` 对应。引用包含知识标题、
章节、源文件路径、文档版本、Chunk ID 和证据摘录。会话和 Run 按当前登录用户隔离。

## 停止

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml stop
```

停止容器不会删除数据卷。除非已经完成备份并明确需要清空数据，否则不得执行带
`--volumes` 的删除命令。
