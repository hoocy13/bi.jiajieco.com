# OCR 任务节点

浏览器 → BI FastAPI 队列 → 公司电脑主动领取 → 本机 Ollama → 回传结果。
容器不监听端口，不挂载公司文件夹，也不需要 GPU 透传；GPU 由 Windows Ollama 使用。

## 配置与启动

1. 在 BI 后端环境设置独立、随机的 `OCR_WORKER_KEY`（至少 32 字符）。不要使用管理员密码。
2. 复制 `.env.example` 为 `.env`，填入相同密钥和 BI HTTPS 地址。密钥只保存在被 Git 忽略的环境文件中。
3. 保持 Windows Ollama 启动，并已下载 `longwayxu/xiaomi-ocr-0:bf16`。
4. 在此目录运行 `docker compose up -d --build`，查看 `docker compose logs --tail 20`。

本地开发时，`OCR_BI_URL=http://host.docker.internal:8000`，`OCR_ALLOW_LOCAL_HTTP=1`。
BI 本地服务须能被 Docker Desktop 容器访问。正式部署必须用 HTTPS，并保持 `OCR_ALLOW_LOCAL_HTTP=0`。
容器访问 Ollama 使用 `http://host.docker.internal:11434`，已在本机验证。
需要 Docker Desktop 和 Ollama 随 Windows 登录启动；容器设置了 `unless-stopped`，手动停止后需手动启动。

## 运行规则

- 当前访问权限沿用 `dashboard.view`，任务按用户隔离；工作节点使用独立密钥，仅开放领取、文件读取、心跳、结果回传接口。
- 每用户最多 3 个未完成任务，全局最多 30 个，单工作节点串行处理。
- 图片最大 20 MB，PDF 最大 20 页，文档解析支持整页/区域；字段提取、图像问答只支持图片。
- 20 秒心跳，120 秒租约；中断任务可重领，最多尝试 3 次，旧租约无法覆盖新结果。
- PDF 按页更新进度，区域模式显示当前页的区域进度，输入图像最长边 2048 像素。输出截断、字段 JSON 无效会明确报错。
- 区域模式：PaddlePaddle 3.3.1、PaddleX 3.7.2、Shapely 2.1.2，CPU 运行 PP-DocLayoutV3，阈值 0.25。保留检测器阅读顺序，使用上游裁剪和合并代码；正文、表格、公式分别使用对应提示词。
- 区域串行调用现有 Ollama GPU，单页最多 100 个可识别区域。未检测到区域时明确报错，不伪造结果或悄悄切换模式。
- 版面模型在后台初始化，成功预热后上报 `region_ready`；尚未就绪的工作节点不会领取区域任务，整页任务仍可处理。
- 模型缓存通过两个 Docker 卷持久化，不因重建容器重复下载；容器内存上限 4 GB，CPU 上限 2 核，不开放入站端口。
- 文件、提示词和结果在上传 24 小时后失效；在节点轮询或用户查询/提交任务时清除内容。不将清理时间描述为严格准点删除。
- 文件保存在 BI 管理数据库，随现有管理库持久化，不写入 ODS；备份保留周期需单独管理。
- 文件不落在工作节点持久磁盘，日志不记录文件内容、提问、识别结果或密钥。
- 页面保留 Xiaomi 原版完整 UI，通过同源消息桥连接 BI 接口；Markdown/公式直接预览，HTML 表格经上游白名单清理后展示。
- 登录凭据留在 BI 父页面，结果下载使用带认证的 POST 表单，不把凭据放入 URL 或传给原版工作区。
- 当前在线状态代表工作节点近期成功检测到 Ollama 中的指定模型，不代表识别准确率保证。

## 上游代码

`vendor/postprocess/` 与 `vendor/evaluation_pipeline/` 中的代码来自 Xiaomi-OCR-0 commit `b1a9bb4c07060c453785e9151715ccda6b96f0b1`，
用于区域序列化、裁剪、文档公式、OTSL 表格和阅读顺序合并；保留 Apache-2.0 LICENSE 与 THIRD_PARTY_NOTICES.md。
模型为社区 BF16 GGUF，未建立与官方推理实现的准确率等价关系。

## 原版界面维护

`frontend/public/ocr-workbench/` 保留上游 Demo 的 HTML、CSS、语言包、KaTeX、三份样例和许可文件。
`bi-adapter.js` 是 BI 同源消息桥，不直接连接 Ollama，也不读取登录凭据。
从已检出的上游目录更新资产：`python scripts/sync_ocr_workbench.py <upstream-repository-path>`。
此脚本保留全部界面，仅替换推理、状态与下载的传输逻辑，并生成资源版本号。
不模拟逐 token 输出；等待时显示队列和页进度，完成后一次展示真实结果。
原入口“区域”可直接提交图片或 PDF；依赖提示根据真实工作节点的 `region_ready` 更新。

## 验证

后端队列测试：在 backend 下执行 `.venv\Scripts\python.exe -m unittest tests.test_ocr`。
容器区域逻辑测试：`docker compose run --rm --no-deps --entrypoint python ocr-worker -m unittest discover -s tests -v`。
本地真实区域链路：在 backend 下执行 `.venv\Scripts\python.exe ../scripts/verify_ocr_local.py --mode region --image <image-path> --pdf <pdf-path>`。
