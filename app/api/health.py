"""Kubernetes/Docker liveness and readiness probes."""
from __future__ import annotations

import time

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import QDRANT_URL
from app.core.database import engine
from app.core.redis import get_redis

router = APIRouter(tags=["Health"])


def _check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _check_redis() -> None:
    client = get_redis()
    if client is None or not client.ping():
        raise RuntimeError("Redis client unavailable")


def _check_qdrant() -> None:
    from qdrant_client import QdrantClient

    QdrantClient(url=QDRANT_URL, timeout=2, trust_env=False).get_collections()


@router.get("/health/live")
def liveness():
    return {"status": "ok"}


@router.get("/health")
@router.get("/health/ready")
def readiness(response: Response):
    checks = {}
    for name, check in (
        ("postgresql", _check_database),
        ("redis", _check_redis),
        ("qdrant", _check_qdrant),
    ):
        started = time.perf_counter()
        try:
            check()
            checks[name] = {
                "status": "up",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except Exception as exc:
            checks[name] = {
                "status": "down",
                "error": type(exc).__name__,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
    ready = all(item["status"] == "up" for item in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": checks}


__all__ = ["router"]
