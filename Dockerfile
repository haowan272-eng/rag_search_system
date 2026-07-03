FROM ghcr.io/astral-sh/uv:0.11.18 AS uv
FROM python:3.12-slim

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

# 模型挂载点（运行时通过 volume 挂载，不打进镜像）
RUN mkdir -p /app/models

ENV PATH="/app/.venv/bin:$PATH"
ENV MODEL_ROOT=/app/models
EXPOSE 8001
CMD ["uv", "run", "--frozen", "--no-dev", "python", "run.py"]
