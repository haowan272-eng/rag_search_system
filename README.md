# Atlas RAG Knowledge Platform

Atlas RAG Knowledge Platform 是一个面向多格式文档的 RAG 知识库系统，包含 FastAPI 后端、Vue 前端控制台、PostgreSQL、Redis、Qdrant、Celery Worker、RAGAS 评估脚本和 Docker Compose 部署配置。

项目目标不是只做一个问答 Demo，而是把真实 RAG 系统的主链路拆清楚：文档上传、异步解析、Markdown 中间表示、结构化分块、Embedding、向量入库、权限过滤、检索问答、引用输出、短期/长期记忆和质量评估。

## 核心能力

- JWT 鉴权：登录后访问上传、知识库、问答和记忆接口。
- 多格式上传：支持 PDF、Word、PPT、Excel、TXT、Markdown、图片等格式，具体以 `app/rag/chunker.py` 为准。
- Markdown 中间表示：不同格式统一转换为 Markdown，再进入清洗和分块链路。
- 多模态解析：文本提取、OCR，可选接入 Qwen-VL/vLLM 视觉理解 caption。
- 异步索引：上传接口快速返回，文档解析、OCR/VL、Embedding、Qdrant 入库由 Celery Worker 执行。
- 向量检索：Qdrant 存储 chunk 向量和元数据，支持知识库/文档过滤。
- 结构化存储：PostgreSQL 保存用户、知识库、文档、chunk 元数据、会话和长期记忆。
- Redis 能力：Celery Broker/Result Backend、短期记忆、缓存、并发控制和限流。
- RAG 回答：调用 DeepSeek/OpenAI-compatible LLM 生成答案，并返回引用来源。
- SSE 流式回答：支持边生成边返回，改善长回答等待体验。
- RAGAS 评估：提供脚本和 Notebook，用于评估回答质量。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端 API | FastAPI, Uvicorn |
| 异步任务 | Celery, Redis |
| 数据库 | PostgreSQL, SQLAlchemy |
| 向量库 | Qdrant |
| RAG | LangChain, OpenAI-compatible API |
| 文档解析 | MarkItDown, PyMuPDF, Pillow, pytesseract |
| 视觉理解 | Qwen-VL/vLLM，可选 |
| 前端 | Vue 3, Vite, Pinia, TypeScript |
| 评估 | RAGAS, JupyterLab |
| 依赖管理 | uv, npm |
| 部署 | Docker, Docker Compose |

## 项目结构

```text
rag/
├── app/
│   ├── api/              # FastAPI 路由
│   ├── auth/             # JWT 工具
│   ├── core/             # 配置、数据库、Redis、Celery
│   ├── rag/              # 分块、Embedding、向量库、视觉处理、回答链
│   ├── schemas/          # Pydantic 模型
│   ├── services/         # 索引、问答、记忆、会话上下文
│   ├── tasks/            # Celery 后台任务
│   └── main.py           # FastAPI 应用入口
├── eval/                 # RAGAS/Jupyter 实验数据与 Notebook
├── frontend/             # Vue 前端控制台
├── scripts/              # RAGAS、GC 等脚本
├── tests/                # 后端测试
├── testpy/               # 评估相关测试
├── docker-compose.yml
├── docker-compose.prod.yml
├── pyproject.toml
├── uv.lock
├── run.py
└── worker.py
```

## 快速开始

### 1. 安装依赖

```powershell
cd E:\my-project\rag
uv sync --frozen --group dev
```

如果要运行 RAGAS/Jupyter：

```powershell
uv sync --frozen --group evaluation
```

前端依赖：

```powershell
cd E:\my-project\rag\frontend
npm ci
```

### 2. 配置环境变量

```powershell
cd E:\my-project\rag
Copy-Item .env.example .env
```

开发环境常用配置：

```env
APP_ENV=development
DATABASE_URL=postgresql://postgres:12345@127.0.0.1:5432/rag_db
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_NAME=chatai_chunks
QDRANT_DIM=1024
SECRET_KEY=change-me-in-production-please
REFRESH_SECRET_KEY=change-me-in-production-refresh
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

不配置 `VISION_MODEL` 时，系统仍可使用文本解析和 OCR；配置后可接入 OpenAI-compatible 视觉模型服务。

## 本地启动

### 1. 启动基础服务

如果本机没有 PostgreSQL、Redis、Qdrant，可以用 Docker Compose 启动整套服务：

```powershell
cd E:\my-project\rag
docker compose up -d --build
```

当前开发 Compose 为避免和本机数据库冲突，宿主机端口映射为：

```text
PostgreSQL: localhost:15432 -> container:5432
Redis:      localhost:16379 -> container:6379
Qdrant:     localhost:6333  -> container:6333
Backend:    localhost:8001  -> container:8001
Frontend:   localhost:3000  -> container:80
```

如果你要从宿主机连接 Docker 里的数据库，请使用：

```env
DATABASE_URL=postgresql://rag_user:rag_password@127.0.0.1:15432/rag_db
REDIS_URL=redis://localhost:16379/0
QDRANT_URL=http://localhost:6333
```

Compose 内部服务之间仍然使用容器名和容器端口，例如 `postgres:5432`、`redis:6379`、`qdrant:6333`。

### 2. 手动启动后端 API

如果基础服务已经运行，可以手动启动后端：

```powershell
cd E:\my-project\rag
uv run --frozen python run.py
```

接口文档：

```text
http://127.0.0.1:8001/docs
```

### 3. 启动 Celery Worker

```powershell
cd E:\my-project\rag
uv run --frozen celery -A app.core.celery:celery_app worker --loglevel=INFO --queues=document_index --pool=solo --concurrency=1
```

或者：

```powershell
uv run --frozen python worker.py
```

Worker 必须启动，否则上传文档后只会创建任务，不会真正完成解析和向量入库。

### 4. 启动前端

```powershell
cd E:\my-project\rag\frontend
npm run dev
```

默认访问：

```text
http://localhost:5173
```

## 主链路

1. 用户通过前端或 API 上传文档。
2. API 校验 JWT、文件类型、文件大小和知识库权限。
3. API 保存原始文件，写入 PostgreSQL，并投递 Celery 任务。
4. Worker 执行解析、OCR/VL、Markdown 转换、分块和 Embedding。
5. chunk 元数据写入 PostgreSQL，向量写入 Qdrant。
6. 用户提问时，系统读取短期/长期记忆并检索相关 chunk。
7. LLM 生成答案，接口返回答案、引用和来源元数据。
8. 对话写入会话、短期记忆和长期记忆。

## 常用接口

| 功能 | 方法 | 路径 |
| --- | --- | --- |
| 健康检查 | GET | `/health` |
| 登录 | POST | `/auth/login` |
| 刷新 Token | POST | `/auth/refresh` |
| 文档上传 | POST | `/document/upload` |
| 文档列表 | GET | `/document/list` |
| 删除文档 | DELETE | `/document/{document_id}` |
| 知识库 | 多种 | `/kb/...` |
| RAG 回答 | POST | `/embedding/rag/answer` |
| RAG 流式回答 | POST | `/embedding/rag/answer/stream` |
| 会话 | 多种 | `/conversation/...` |
| 记忆 | 多种 | `/memory/...` |

具体请求体以 `/docs` 生成的 OpenAPI 文档为准。

## 测试与构建

后端测试：

```powershell
cd E:\my-project\rag
uv run --frozen --group dev python -m pytest
```

当前 Windows 环境下建议用 `python -m pytest`，因为 `.venv` 里可能没有生成 `pytest.exe` 入口脚本。

前端构建：

```powershell
cd E:\my-project\rag\frontend
npm run build
```

## RAGAS 评估

主入口：

```text
eval/ragas_experiment.ipynb
scripts/ragas_evaluate.py
eval/ragas_dataset.example.jsonl
```

启动 Jupyter：

```powershell
cd E:\my-project\rag
uv run --frozen --group evaluation jupyter lab
```

命令行评估：

```powershell
uv run --frozen --group evaluation python scripts/ragas_evaluate.py --dataset eval/ragas_dataset.example.jsonl --token "你的JWT"
```

常用指标包括 faithfulness、response relevancy、context precision 和 context recall。

## 运维工具

全局 GC 默认 dry-run，只检查不删除：

```powershell
cd E:\my-project\rag
uv run python scripts/gc.py
```

确认输出无误后真正删除：

```powershell
uv run python scripts/gc.py --execute
```

常用参数：

```powershell
uv run python scripts/gc.py --failed-days 7 --stuck-hours 24
uv run python scripts/gc.py --skip-qdrant
uv run python scripts/gc.py --skip-files
uv run python scripts/gc.py --skip-stale-docs
```

## Docker 部署

开发环境：

```powershell
docker compose up -d --build
```

生产配置检查：

```powershell
docker compose -f docker-compose.prod.yml config
```

生产启动前至少修改：

- `SECRET_KEY`
- `REFRESH_SECRET_KEY`
- PostgreSQL 密码
- Redis 密码
- CORS 白名单
- LLM API Key
- 文件存储策略

## 常见问题

### 上传成功但检索不到内容？

先检查 Celery Worker 是否启动，再检查文档状态是否索引成功。上传接口返回 202 只代表任务已创建，不代表索引已完成。

### 为什么不用同步上传后立刻索引？

OCR、VL、Embedding 都可能很慢。同步处理会阻塞 API，导致高并发上传时延迟明显升高。异步 Worker 可以让上传接口快速返回，并让索引能力独立扩容。

### Redis 里存什么？

Redis 用于 Celery 队列、任务结果、短期记忆、缓存、分布式并发控制和限流。重要业务状态仍然保存到 PostgreSQL。

### Qdrant 里存什么？

Qdrant 存 chunk 向量和检索元数据，例如 `document_id`、`kb_id`、标题路径、页码等。完整业务状态由 PostgreSQL 管理。

### 不启用 Qwen-VL 还能用吗？

可以。文本、PDF 文本和 OCR 仍然可用。Qwen-VL 是增强能力，不是系统启动强依赖。
