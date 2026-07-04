# Atlas RAG Knowledge Platform

一个面向多格式文档的企业级 RAG 知识库后端与前端控制台项目。项目支持用户鉴权、知识库管理、文档上传、异步索引、多格式/多模态解析、Markdown 结构化分块、向量检索、RAG 回答、引用输出、短期/长期记忆、SSE 流式回答、RAGAS 评估与 Docker 化部署。

这个项目的核心目标不是只做一个“能问答的 Demo”，而是把真实 RAG 系统需要面对的主链路拆清楚：文档怎么进来、怎么异步处理、怎么分块、怎么入库、怎么检索、怎么回答、怎么保存对话记忆，以及高并发时怎么避免 API 被 OCR/VL/Embedding 拖慢。

## 核心能力

- JWT 用户鉴权：登录后通过 Token 访问上传、知识库、问答与记忆接口。
- 多格式文档上传：支持 PDF、Word、PPT、Excel、TXT、Markdown、图片等格式，具体以 `app/rag/chunker.py` 中 `SUPPORTED_DOCUMENT_EXTENSIONS` 为准。
- 统一 Markdown 中间表示：不同格式先解析/转换为 Markdown，再进入统一清洗和分块链路。
- 多模态解析：文本直接提取，图片支持 OCR，复杂图片可选接入 Qwen-VL/vLLM 视觉理解模型生成 caption。
- 异步索引：上传接口立即返回 `202 Accepted`，重型解析、OCR/VL、Embedding、入库由 Celery Worker 后台执行。
- 向量检索：使用 Qdrant 存储 chunk 向量，支持按知识库、文档等元数据过滤。
- 结构化存储：PostgreSQL 存用户、知识库、文档、chunk 元数据、会话和长期记忆。
- Redis 能力：作为 Celery Broker/Result Backend，同时支持短期记忆、缓存、并发控制和限流。
- RAG 回答接口：基于 LangChain/OpenAI-compatible LLM 生成答案，并返回引用来源。
- SSE 流式输出：支持边生成边返回，提升长回答体验。
- 记忆系统：Redis 保存短期对话记忆，PostgreSQL 保存会话与长期结构化记忆。
- RAGAS 评估：提供脚本和 Jupyter 实验入口，用于评估 RAG 回答质量。
- uv 工程化：Python 依赖通过 `pyproject.toml + uv.lock` 管理，保证依赖可复现。
- Docker Compose：编排 API、Worker、PostgreSQL、Redis、Qdrant 等服务。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 API | FastAPI, Uvicorn |
| 异步任务 | Celery, Redis |
| 数据库 | PostgreSQL, SQLAlchemy |
| 向量数据库 | Qdrant |
| 缓存/短期记忆 | Redis |
| RAG 编排 | LangChain, OpenAI-compatible API |
| 文档解析 | MarkItDown, PyMuPDF, Pillow, pytesseract |
| 视觉理解 | Qwen-VL/vLLM 或其他 OpenAI-compatible VL 服务，可选 |
| 前端 | Vue 3, Vite, Pinia, TypeScript |
| 评估 | RAGAS, JupyterLab |
| 依赖管理 | uv |
| 部署 | Docker, Docker Compose |

## 项目结构

```text
rag/
├── app/
│   ├── api/                    # FastAPI 路由：鉴权、文档、知识库、RAG、记忆、健康检查
│   ├── auth/                   # JWT 工具
│   ├── core/                   # 配置、数据库、Redis、Celery
│   ├── models/                 # SQLAlchemy ORM 模型
│   ├── rag/                    # RAG 核心：分块、Embedding、向量库、视觉处理、回答链
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/               # 业务服务：索引、问答、记忆、会话上下文
│   ├── tasks/                  # Celery 后台任务
│   ├── main.py                 # FastAPI 应用入口
│   └── logging_config.py       # 日志配置
├── frontend/                   # Vue 前端控制台
├── docs/                       # 运维、RAGAS 评估等文档
├── eval/                       # RAGAS/Jupyter 实验数据与 Notebook
├── scripts/                    # 脚本工具
├── tests/                      # 后端测试
├── testpy/                     # 实验/评估相关测试
├── uploads/                    # 本地上传文件目录，生产建议替换为对象存储
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── pyproject.toml
├── uv.lock
└── run.py
```

## 总体架构

```mermaid
flowchart TD
    U[用户/前端 Vue] --> API[FastAPI API]
    API --> AUTH[JWT 鉴权]
    API --> PG[(PostgreSQL)]
    API --> REDIS[(Redis)]
    API --> QDRANT[(Qdrant)]

    U -->|上传文档| UPLOAD[/POST /document/upload/]
    UPLOAD --> PG
    UPLOAD --> LOCAL[本地 uploads 或对象存储]
    UPLOAD -->|投递任务| CELERY[Celery Queue]
    CELERY --> WORKER[Document Index Worker]
    WORKER --> PARSE[文档解析/OCR/VL]
    PARSE --> MD[统一 Markdown]
    MD --> CHUNK[Markdown 结构感知分块]
    CHUNK --> EMB[Embedding]
    EMB --> QDRANT
    CHUNK --> PG

    U -->|提问| RAG[/POST /embedding/rag/answer/]
    RAG --> MEMORY[短期/长期记忆]
    MEMORY --> REDIS
    MEMORY --> PG
    RAG --> RETRIEVE[向量检索/过滤]
    RETRIEVE --> QDRANT
    RAG --> LLM[DeepSeek/OpenAI-compatible LLM]
    LLM --> ANSWER[答案 + 引用]
    ANSWER --> U
```

## 主链路说明

### 1. 文档上传与异步索引

1. 前端或客户端调用 `POST /document/upload` 上传文件。
2. FastAPI 校验 JWT、文件后缀、文件头、大小限制和知识库权限。
3. API 保存原始文件并写入 `documents` 表。
4. API 将 `document_index` 任务投递到 Redis/Celery。
5. API 立即返回 `202 Accepted`，不等待 OCR/VL/Embedding 完成。
6. Celery Worker 异步执行文档解析、Markdown 转换、清洗、分块、Embedding 和 Qdrant 入库。
7. 文档状态从 `uploaded` 更新为索引中、成功或失败。

这样设计的原因：OCR、VL caption、Embedding 和向量入库都可能耗时。如果全部放在请求线程里，会阻塞 FastAPI 事件循环，导致高并发上传时 P95 延迟明显升高。通过 Worker 解耦后，API 保持轻量，索引能力可以独立扩容。

### 2. 多格式/多模态解析

项目将 PDF、Word、TXT、Markdown、图片等输入统一抽象为 document。不同格式可以使用不同解析器，但最终都会被转换为 Markdown 文本。

- 普通文档：优先通过 MarkItDown 转换为 Markdown。
- PDF：结合文本抽取、图片提取、OCR、附近正文和可选视觉 caption。
- 图片：通过 OCR 提取文字；必要时通过 Qwen-VL/vLLM 生成图像语义描述。
- 文本类文件：直接读取并做轻量清洗。

统一转 Markdown 的好处是后续分块器只处理一种中间格式，避免 PDF、Word、图片各写一套分块策略。

### 3. Markdown 结构感知分块

分块不只是按固定长度切文本，而是尽量利用 Markdown 结构：

- 保留标题层级 `heading_path`。
- 避免切断表格、代码块、列表。
- 小块合并，大块递归切分。
- 图片 caption 可以和附近正文绑定。
- 每个 chunk 保留 `document_id`、`kb_id`、页码/段落位置、标题路径等元数据。

这些元数据会在检索和引用输出中使用。

### 4. RAG 问答链路

1. 用户调用 `POST /embedding/rag/answer` 或 `POST /embedding/rag/answer/stream`。
2. 系统读取当前用户的短期记忆和长期记忆。
3. 根据问题从 Qdrant 检索相关 chunk。
4. 根据知识库、文档、权限等元数据过滤结果。
5. 拼接问题、历史上下文、检索上下文和系统提示词。
6. 调用 DeepSeek/OpenAI-compatible LLM 生成答案。
7. 返回答案、引用、chunk 来源和相关元数据。
8. 将本轮问答写入会话和短期记忆，必要时提取长期记忆。

### 5. 记忆系统

项目采用三层记忆设计：

- 当前请求上下文：本轮问题和当前构造 prompt 所需的上下文。
- 短期记忆：Redis 保存最近 N 轮对话，读取快，适合构造 prompt。
- 长期记忆：PostgreSQL 保存会话、消息、用户偏好、长期事实和结构化摘要。

这种设计能兼顾速度和持久化，也能避免把所有历史对话无脑塞进 LLM 上下文导致污染。

## 快速开始：本地运行

### 1. 准备环境

推荐 Python 3.12，并安装 uv。

```bash
cd E:/my-project/rag
uv sync --frozen --group dev
```

如果需要运行 RAGAS/Jupyter 评估：

```bash
uv sync --frozen --group evaluation
```

### 2. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

Windows PowerShell 可以使用：

```powershell
Copy-Item .env.example .env
```

重点检查以下配置：

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

如果要启用 Qwen-VL/vLLM 视觉理解：

```env
VISION_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
VISION_BASE_URL=http://127.0.0.1:8001/v1
VISION_API_KEY=EMPTY
VISION_MAX_CAPTIONS_PER_DOCUMENT=8
```

如果不配置 `VISION_MODEL`，系统仍可使用 OCR 和文本解析能力。

### 3. 启动基础服务

可以用 Docker Compose 启动 PostgreSQL、Redis、Qdrant、API 和 Worker：

```bash
docker compose up -d
```

只查看配置是否正确：

```bash
docker compose config
```

如果你只想本地手动启动 Python 后端，需要确保 PostgreSQL、Redis、Qdrant 已经在本机运行。

### 4. 启动后端 API

```bash
uv run --frozen python run.py
```

默认后端端口由 `.env` 中 `HOST`、`PORT` 控制。

接口文档：

```text
http://127.0.0.1:8001/docs
```

### 5. 启动 Celery Worker

```bash
uv run --frozen celery -A app.core.celery:celery_app worker --loglevel=INFO --queues=document_index
```

或者使用项目提供的 worker 入口：

```bash
uv run --frozen python worker.py
```

Worker 必须启动，否则上传文档后只会创建任务，不会真正完成解析和向量入库。

### 6. 启动前端

```bash
cd E:/my-project/rag/frontend
npm install
npm run dev
```

前端默认由 Vite 启动，通常访问：

```text
http://localhost:5173
```

## 常用接口

| 功能 | 方法 | 路径 |
| --- | --- | --- |
| 健康检查 | GET | `/health` |
| 用户登录 | POST | `/auth/login` |
| 用户刷新 Token | POST | `/auth/refresh` |
| 文档上传 | POST | `/document/upload` |
| 文档列表 | GET | `/document/list` |
| 删除文档 | DELETE | `/document/{document_id}` |
| 知识库管理 | 多种 | `/kb/...` |
| RAG 回答 | POST | `/embedding/rag/answer` |
| RAG 流式回答 | POST | `/embedding/rag/answer/stream` |
| 会话管理 | 多种 | `/conversation/...` |
| 记忆管理 | 多种 | `/memory/...` |

具体请求体以 `/docs` 自动生成的 OpenAPI 文档为准。

## 测试

运行后端测试：

```bash
uv run --frozen --group dev python -m pytest
```

当前项目测试覆盖重点包括：

- 用户与鉴权相关逻辑。
- 共享知识库和私有会话隔离。
- 文档上传、删除和索引链路。
- RAG 检索、BM25/向量相关逻辑。
- RAGAS 脚本基础可用性。

## RAGAS 评估

项目提供 RAGAS 评估脚本和 Jupyter 实验入口。文档见：

```text
docs/RAGAS_EVALUATION.md
```

启动 Jupyter：

```bash
uv run --frozen --group evaluation jupyter lab
```

Notebook 示例：

```text
eval/ragas_experiment.ipynb
```

RAGAS 主要用于评估：

- Faithfulness：答案是否忠实于检索上下文。
- Answer Relevancy：答案是否真正回答了问题。
- Context Precision：检索到的上下文是否有效。
- Context Recall：回答所需信息是否被召回。

## 日志与可观测性

项目已统一使用 `logging`，不再依赖 `print()` 做生产日志。支持：

- `LOG_LEVEL` 控制日志等级。
- `LOG_JSON=true/false` 控制 JSON 或普通文本日志。
- 请求级 `X-Request-ID`，便于排查单次请求链路。
- API 和 Celery Worker 使用统一日志风格。

常见配置：

```env
LOG_LEVEL=INFO
LOG_JSON=true
```

生产环境可以进一步接入 ELK、Loki、Prometheus、OpenTelemetry 等系统。

## 高并发设计要点

- API 无状态：FastAPI 实例不依赖本地内存保存关键状态，便于横向扩容。
- Worker 独立扩容：文档解析、OCR/VL、Embedding 不占用 API 请求线程。
- Redis 队列削峰：上传高峰时任务进入队列，由 Worker 按能力消费。
- 并发控制：OCR、VL 设置进程内并发和全局并发，避免打爆模型服务。
- 大文件保护：上传限制文件大小，并采用分块读取，避免一次性读入内存。
- Qdrant 过滤：检索时按 `kb_id`、`document_id` 等元数据控制范围。
- PostgreSQL 持久化：业务数据、会话、记忆和文档状态都落库。
- 可演进方向：对象存储直传、PgBouncer、外置 BM25、模型服务独立部署、限流和熔断。

## 安全与权限设计

- JWT 鉴权保护核心接口。
- `user_id` 表示上传者，不直接等价于文档所有权。
- 知识库权限通过成员关系和角色控制。
- 私人会话和记忆按用户隔离。
- 共享知识库需要进一步增强审核、配额、限流和内容安全策略，防止恶意上传污染数据库。

建议的生产增强：

- 文档状态增加 `pending/approved/rejected` 审核流。
- 上传文件做病毒扫描和内容安全检测。
- 对用户设置上传频率、文件大小、总空间配额。
- 对共享知识库引入管理员审核和回滚机制。
- 对检索结果引入来源可信度和文档质量权重。

## Docker 部署

开发环境：

```bash
docker compose up -d --build
```

生产配置检查：

```bash
docker compose -f docker-compose.prod.yml config
```

生产启动前请至少修改：

- `SECRET_KEY`
- `REFRESH_SECRET_KEY`
- PostgreSQL 密码
- Redis 密码
- CORS 白名单
- LLM API Key
- 文件存储策略

## 常见问题

### 上传成功但检索不到内容？

先检查 Celery Worker 是否启动，再检查文档状态是否变为索引成功。上传接口返回 202 只代表任务已创建，不代表索引已完成。

### 为什么不用同步上传后立刻索引？

因为 OCR、VL、Embedding 都可能很慢。同步处理会阻塞 API，导致 P95 延迟升高。异步 Worker 可以让上传接口快速返回，并让索引能力独立扩容。

### Redis 里存什么？

Redis 主要用于 Celery 队列、任务结果、短期记忆、缓存、分布式并发控制和限流。重要的会话、文档、长期记忆仍然存 PostgreSQL。

### Qdrant 里存什么？

Qdrant 存 chunk 的向量和检索元数据，例如 `document_id`、`kb_id`、标题路径、页码等。完整业务状态仍由 PostgreSQL 管理。

### 如果不启用 Qwen-VL，还能用吗？

可以。图片仍可通过 OCR 提取文字，文本文档和 PDF 文本仍可正常进入 RAG 链路。Qwen-VL 是增强能力，不是系统启动的强依赖。

## 面试讲法速记

这个项目可以概括为：我实现了一个支持多格式文档的企业知识库 RAG 系统。上传侧通过 FastAPI 接收文件并立即返回任务 ID，使用 Celery + Redis 将 OCR/VL、Markdown 转换、分块、Embedding 和 Qdrant 入库异步化，避免重任务阻塞 API。存储侧使用 PostgreSQL 管理用户、知识库、文档、会话和长期记忆，Qdrant 存向量，Redis 存任务队列、短期记忆和缓存。问答侧通过 Qdrant 检索相关 chunk，结合短期/长期记忆构造上下文，调用 LLM 生成带引用的回答，并支持 SSE 流式输出。项目还提供 RAGAS 评估、日志、健康检查、Docker 和 uv 依赖锁定，便于测试和部署。

## 后续优化方向

- 引入真正的混合检索：向量检索 + BM25 + rerank。
- 建立文档审核机制，防止共享知识库被污染。
- 对 chunk size、top_k、rerank 数量做 RAGAS 驱动调参。
- 使用对象存储替代本地 `uploads/`。
- 增加 PgBouncer 和连接池治理。
- 接入 Prometheus/Grafana 或 OpenTelemetry。
- 完善前端任务进度、失败重试和引用高亮。
- 增加文档版本管理和增量索引。
