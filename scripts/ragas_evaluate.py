"""Evaluate the running Atlas RAG API with RAGAS.

Input JSONL fields:
  question (required), reference (required), kb_id/document_id/top_k (optional)

The script first persists raw API responses, then evaluates them. A saved response
file can be reused with --responses-file to avoid paying for RAG generation twice.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from app.logging_config import setup_logging  # noqa: E402
except ImportError:  # Allows the evaluator to run as a standalone copied tool.
    def setup_logging() -> None:
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

setup_logging()
logger = logging.getLogger("ragas_evaluate")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    reference: str
    kb_id: int | None = None
    document_id: int | None = None
    top_k: int = 5
    bm25_weight: float = 0.4


@dataclass(frozen=True)
class CollectedSample:
    case_id: str
    question: str
    reference: str
    response: str
    retrieved_contexts: list[str]
    conversation_id: int | None
    degraded: bool
    latency_ms: float
    citations: list[dict[str, Any]]


def load_cases(path: Path, limit: int | None = None) -> list[EvalCase]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是有效JSON") from exc
            question = str(item.get("question") or "").strip()
            reference = str(item.get("reference") or item.get("ground_truth") or "").strip()
            if not question or not reference:
                raise ValueError(f"{path}:{line_number} 必须包含question和reference")
            cases.append(EvalCase(
                case_id=str(item.get("id") or line_number),
                question=question,
                reference=reference,
                kb_id=item.get("kb_id"),
                document_id=item.get("document_id"),
                top_k=max(1, min(int(item.get("top_k", 5)), 20)),
                bm25_weight=max(0.0, min(float(item.get("bm25_weight", 0.4)), 1.0)),
            ))
            if limit and len(cases) >= limit:
                break
    if not cases:
        raise ValueError("评估集为空")
    return cases


def login(client: httpx.Client, username: str, password: str) -> str:
    response = client.post("/login", json={"username": username, "password": password})
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("登录响应没有access_token")
    return str(token)


def _post_with_retry(
    client: httpx.Client,
    path: str,
    payload: dict,
    headers: dict,
    retries: int,
) -> httpx.Response:
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = client.post(path, json=payload, headers=headers)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(8.0, 2 ** attempt))
    raise RuntimeError(f"RAG API请求失败: {last_error}") from last_error


def collect_samples(
    client: httpx.Client,
    cases: Iterable[EvalCase],
    token: str,
    retries: int = 2,
) -> list[CollectedSample]:
    headers = {"Authorization": f"Bearer {token}"}
    samples = []
    for index, case in enumerate(cases, 1):
        payload = {
            "query": case.question,
            "top_k": case.top_k,
            "kb_id": case.kb_id,
            "document_id": case.document_id,
            "bm25_weight": case.bm25_weight,
            "use_memory": False,
        }
        started = time.perf_counter()
        response = _post_with_retry(
            client, "/embedding/rag/answer", payload, headers, retries
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        data = response.json()
        citations = list(data.get("citations") or [])
        contexts = [
            str(item.get("quote") or "").strip()
            for item in citations
            if str(item.get("quote") or "").strip()
        ]
        samples.append(CollectedSample(
            case_id=case.case_id,
            question=case.question,
            reference=case.reference,
            response=str(data.get("answer") or ""),
            retrieved_contexts=contexts,
            conversation_id=data.get("conversation_id"),
            degraded=bool(data.get("degraded", False)),
            latency_ms=latency_ms,
            citations=citations,
        ))
        logger.info(
            "collected evaluation sample %s/%s case_id=%s contexts=%s latency_ms=%s",
            index, len(cases) if hasattr(cases, "__len__") else "?",
            case.case_id, len(contexts), latency_ms,
        )
    return samples


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_collected(path: Path) -> list[CollectedSample]:
    values = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                values.append(CollectedSample(**json.loads(raw)))
            except Exception as exc:
                raise ValueError(f"{path}:{line_number} 响应记录格式错误") from exc
    if not values:
        raise ValueError("响应记录为空")
    return values


def _build_ragas_components(metric_names: set[str]):
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        # RAGAS 0.4.x compatibility API works with evaluate(..., llm=..., embeddings=...).
        # The new collections API requires passing model objects to every metric
        # constructor, so migrating it must be done together with run_ragas().
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextRecall,
            ResponseRelevancy,
        )
    except ImportError as exc:
        raise RuntimeError("缺少RAGAS依赖，请先执行: uv sync --frozen --group evaluation") from exc

    llm_key = os.getenv("RAGAS_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    llm_base = os.getenv("RAGAS_LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_model = os.getenv("RAGAS_LLM_MODEL", "deepseek-chat")
    if not llm_key:
        raise RuntimeError("必须配置RAGAS_LLM_API_KEY或DEEPSEEK_API_KEY")
    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(
        api_key=llm_key,
        base_url=llm_base,
        model=llm_model,
        temperature=0,
        timeout=float(os.getenv("RAGAS_TIMEOUT_SECONDS", "120")),
        max_retries=int(os.getenv("RAGAS_MAX_RETRIES", "2")),
    ))

    evaluator_embeddings = None
    if "response_relevancy" in metric_names:
        embedding_key = os.getenv("RAGAS_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not embedding_key:
            raise RuntimeError("response_relevancy需要RAGAS_EMBEDDING_API_KEY或OPENAI_API_KEY")
        evaluator_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
            api_key=embedding_key,
            base_url=os.getenv("RAGAS_EMBEDDING_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("RAGAS_EMBEDDING_MODEL", "text-embedding-3-small"),
        ))

    factories = {
        "faithfulness": Faithfulness,
        "response_relevancy": ResponseRelevancy,
        "context_precision": LLMContextPrecisionWithReference,
        "context_recall": LLMContextRecall,
    }
    unknown = metric_names - factories.keys()
    if unknown:
        raise ValueError(f"未知metrics: {', '.join(sorted(unknown))}")
    return [factories[name]() for name in sorted(metric_names)], evaluator_llm, evaluator_embeddings


def run_ragas(samples: list[CollectedSample], metric_names: set[str]):
    from ragas import EvaluationDataset, SingleTurnSample, evaluate

    dataset = EvaluationDataset(samples=[
        SingleTurnSample(
            user_input=item.question,
            retrieved_contexts=item.retrieved_contexts,
            response=item.response,
            reference=item.reference,
        )
        for item in samples
    ])
    metrics, evaluator_llm, evaluator_embeddings = _build_ragas_components(metric_names)
    return evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
        raise_exceptions=False,
    )


def summarize(frame, samples: list[CollectedSample]) -> dict:
    metric_summary = {}
    for column in frame.columns:
        values = [float(value) for value in frame[column].tolist()
                  if isinstance(value, (int, float)) and not math.isnan(float(value))]
        if values:
            metric_summary[column] = round(sum(values) / len(values), 4)
    latencies = sorted(item.latency_ms for item in samples)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    return {
        "sample_count": len(samples),
        "metrics": metric_summary,
        "latency_ms": {
            "average": round(sum(latencies) / len(latencies), 2),
            "p95": latencies[p95_index],
        },
        "degraded_rate": round(sum(item.degraded for item in samples) / len(samples), 4),
        "empty_context_rate": round(sum(not item.retrieved_contexts for item in samples) / len(samples), 4),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Atlas RAG with RAGAS")
    parser.add_argument("--dataset", type=Path, default=Path("eval/ragas_dataset.example.jsonl"))
    parser.add_argument("--responses-file", type=Path, help="复用已采集的JSONL响应")
    parser.add_argument("--output-dir", type=Path, default=Path("eval/results"))
    parser.add_argument("--base-url", default=os.getenv("RAG_EVAL_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("RAG_EVAL_TOKEN"))
    parser.add_argument("--username", default=os.getenv("RAG_EVAL_USERNAME"))
    parser.add_argument("--password", default=os.getenv("RAG_EVAL_PASSWORD"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--request-retries", type=int, default=2)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument(
        "--metrics",
        default="faithfulness,response_relevancy,context_precision,context_recall",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_dir / f"responses_{run_id}.jsonl"

    if args.responses_file:
        samples = load_collected(args.responses_file)
    else:
        cases = load_cases(args.dataset, args.limit)
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.request_timeout) as client:
            token = args.token
            if not token:
                if not args.username or not args.password:
                    raise RuntimeError("请提供--token，或同时提供--username和--password")
                token = login(client, args.username, args.password)
            samples = collect_samples(client, cases, token, args.request_retries)
        write_jsonl(raw_path, (asdict(item) for item in samples))
        logger.info("raw responses saved to %s", raw_path)

    if args.collect_only:
        return 0

    metric_names = {name.strip() for name in args.metrics.split(",") if name.strip()}
    result = run_ragas(samples, metric_names)
    frame = result.to_pandas()
    summary = summarize(frame, samples)
    metadata = [asdict(item) for item in samples]
    for index, item in enumerate(metadata):
        for key, value in item.items():
            if key not in frame.columns:
                frame.loc[index, key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
    csv_path = args.output_dir / f"ragas_scores_{run_id}.csv"
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary_path = args.output_dir / f"summary_{run_id}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("RAGAS report saved: csv=%s summary=%s metrics=%s", csv_path, summary_path, summary["metrics"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
