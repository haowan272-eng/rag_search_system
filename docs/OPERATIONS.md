# 项目运行�?UV 依赖管理

## 环境要求

- Python 3.12，由根目�?`.python-version` 固定
- uv
- Docker Desktop，用�?PostgreSQL、Redis、Qdrant 或整套服�?- Node.js 22，仅 Vue 前端使用

UV 管理 Python 后端，不替代 npm、Docker �?Tesseract 等系统工具�?
## 安装依赖

```powershell
# 生产环境
uv sync --frozen --no-dev

# 开发和测试
uv sync --frozen --group dev

# Jupyter �?RAGAS
uv sync --frozen --group evaluation
```

不要手工执行 `pip install`。新增运行依赖使�?`uv add 包名`，测试依赖使�?`uv add --group dev 包名`，评估依赖使�?`uv add --group evaluation 包名`。依赖变化后应同时提�?`pyproject.toml` �?`uv.lock`�?
## 本地启动

```powershell
# FastAPI
uv run --frozen python run.py

# Celery Worker
uv run --frozen celery -A app.core.celery:celery_app worker --loglevel=INFO --queues=document_index --pool=solo --concurrency=1

# 全部 Python 测试
uv run --frozen --group dev python -m pytest

# RAGAS Notebook
uv run --frozen --group evaluation jupyter lab
```

前端继续使用 npm�?
```powershell
cd frontend
npm ci
npm run dev
```

## Docker

后端镜像通过 `uv sync --frozen --no-dev` 创建生产虚拟环境，不安装 pytest、Jupyter �?RAGAS�?
```powershell
docker compose up --build
docker compose -f docker-compose.prod.yml up --build -d
```

## 全局 GC

全局 GC 用于清理孤儿上传文件、孤�?caption/assets、长期失败或卡住的文档，以及数据库中已不存在�?Qdrant 向量点�?
默认 dry-run，只检查不删除�?
```powershell
uv run python scripts/gc.py
```

确认输出无误后再真正删除�?
```powershell
uv run python scripts/gc.py --execute
```

常用参数�?
```powershell
uv run python scripts/gc.py --failed-days 7 --stuck-hours 24
uv run python scripts/gc.py --skip-qdrant
uv run python scripts/gc.py --skip-files
uv run python scripts/gc.py --skip-stale-docs
```

## 锁文件检�?
```powershell
uv lock --check
uv sync --frozen --group dev
uv run --frozen --group dev python -m pytest
```

`uv lock --check` 失败表示 `pyproject.toml` �?`uv.lock` 不一致，需要执�?`uv lock` 并提交新锁文件�?
## 健康检查与日志

- `GET /health/live`：API 进程存活检查�?- `GET /health`、`GET /health/ready`：检�?PostgreSQL、Redis �?Qdrant，任一不可用返�?HTTP 503�?- `LOG_LEVEL=INFO`：日志级别�?- `LOG_JSON=true`：生产环境结构化日志�?
Docker Compose 使用 `/health` 判断后端是否可接收流量。API �?Celery Worker 使用同一套日志配置�?
## SSE 回答

`POST /embedding/rag/answer/stream` 接收与普通回答接口相同的 JSON �?Bearer Token。客户端应以 `final` 事件作为最终事实源，因为其中包含引用校验后的完整回答和 `degraded` 标记�?
