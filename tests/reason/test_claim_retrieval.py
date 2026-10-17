import json
from pathlib import Path

import pytest

from adapters.chronicle import ingest as adapter_ingest
from chronicle.ingest.__main__ import main as ingest_main
from chronicle.reason.planner import plan_query
from chronicle.reason.retriever import retrieve
from chronicle.schema import Claim


def test_adapter_uses_p1_entry_point():
    assert adapter_ingest.main is ingest_main
    manifest = json.loads((Path(__file__).parents[2] / "adapters/chronicle/adapter.json").read_text())
    assert manifest["ingest"][:3] == ["python", "-m", "chronicle.ingest"]


def test_retrieval_preserves_opening_and_closing_claims(tmp_path):
    claims = [
        Claim(subject="Alice", predicate="owns", object="payments", valid_to="2026-05-01",
              observed_at="2026-05-01", doc_id="E:change", quote="Bob takes over payments from Alice."),
        Claim(subject="Bob", predicate="owns", object="payments", valid_from="2026-05-01",
              observed_at="2026-05-01", doc_id="E:change", quote="Bob takes over payments from Alice."),
        Claim(subject="Dana", predicate="owns", object="search", doc_id="E:other", quote="Dana owns search."),
    ]
    (tmp_path / "claims.jsonl").write_text("\n".join(c.model_dump_json() for c in claims), encoding="utf-8")
    evidence = retrieve(plan_query("payments"), tmp_path)
    assert len(evidence) == 1
    assert evidence[0].doc_id == "E:change"
    assert evidence[0].date == "2026-05-01"
    assert [json.loads(line) for line in evidence[0].text.splitlines()] == [
        c.model_dump(mode="json") for c in claims[:2]
    ]


def test_empty_claims_do_not_fall_back_to_legacy_store(tmp_path):
    (tmp_path / "claims.jsonl").touch()
    (tmp_path / "chronicle_adapter.sqlite3").write_bytes(b"legacy state")
    assert retrieve(plan_query("payments"), tmp_path) == []


def test_legacy_state_requires_reingestion(tmp_path):
    (tmp_path / "chronicle_adapter.sqlite3").touch()
    with pytest.raises(FileNotFoundError, match="must be re-ingested"):
        retrieve(plan_query("payments"), tmp_path)
