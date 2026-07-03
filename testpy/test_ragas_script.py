import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ragas_evaluate.py"
SPEC = importlib.util.spec_from_file_location("ragas_evaluate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_load_cases_accepts_ground_truth_alias(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps({"question": "退款期限？", "ground_truth": "七天"}, ensure_ascii=False),
        encoding="utf-8",
    )
    cases = MODULE.load_cases(path)
    assert cases[0].reference == "七天"


def test_load_cases_rejects_missing_reference(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"question": "退款期限？"}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=r"question.*eference"):
        MODULE.load_cases(path)


def test_collect_samples_uses_citation_quotes_as_contexts():
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(
            200,
            json={
                "answer": "应在七天内提交[1]。",
                "conversation_id": 9,
                "degraded": False,
                "citations": [{"quote": "退款申请应在七天内提交。"}],
            },
        )

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    samples = MODULE.collect_samples(
        client,
        [MODULE.EvalCase("1", "多久退款？", "七天内")],
        "token",
        retries=0,
    )
    assert samples[0].retrieved_contexts == ["退款申请应在七天内提交。"]
    assert samples[0].conversation_id == 9
