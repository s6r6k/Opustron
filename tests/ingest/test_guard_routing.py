"""Ingestion goes through the privacy-routed guard client, and quotes survive the round trip."""

import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from chronicle.guard import egress_logger, llm_client, privacy_router
from chronicle.guard.egress_logger import EgressLogger
from chronicle.guard.llm_client import LLMClient
from chronicle.guard.pii_detector import PiiMatch, detect
from chronicle.ingest.extractor import ClaimExtractor
from chronicle.ingest.pipeline import read_claims
from chronicle.schema import Document

FIX = Path(__file__).parent.parent / "fixtures" / "corpus"
NAMES = ("Alice Chen", "Dana Lee", "Alice")
TOKEN = re.compile(r"\b(?:PERSON|EMAIL)_\d+\b")


@pytest.fixture(autouse=True)
def guarded(tmp_path, monkeypatch):
    """Isolate ~/.chronicle and detect names without needing presidio/spaCy installed."""
    monkeypatch.setattr(llm_client, "_CACHE_DIR", tmp_path / "guard_cache")
    (tmp_path / "guard_cache").mkdir()
    monkeypatch.setattr(egress_logger, "_default_logger", EgressLogger(tmp_path / "egress.log"))

    def detect_with_names(text):
        found = detect(text)
        taken: list[tuple[int, int]] = [(m.start, m.end) for m in found]
        for name in NAMES:  # longest first, so "Alice" never splits "Alice Chen"
            for m in re.finditer(rf"\b{name}\b", text):
                if not any(s < m.end() and m.start() < e for s, e in taken):
                    found.append(PiiMatch("PERSON", name, m.start(), m.end()))
                    taken.append((m.start(), m.end()))
        return found

    monkeypatch.setattr(privacy_router, "detect", detect_with_names)
    return tmp_path


class EchoTransport:
    """Stands in for Nebius: sees only tokenised text and quotes it back verbatim."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        doc = kwargs["messages"][1]["content"]
        body = doc.split("---")[-1].strip()  # drop front matter for fixture files
        sentence = body.split(". ")[0].rstrip(".") + "."
        tokens = TOKEN.findall(sentence)
        claims = [{"subject": tokens[0] if tokens else "service", "predicate": "owns",
                   "object": tokens[-1] if tokens else "service", "valid_from": "today",
                   "quote": sentence}]
        content = "<think>The subject is " + (tokens[0] if tokens else "?") + "</think>" + json.dumps({"claims": claims})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20))


def test_quotes_with_names_and_emails_survive_pseudonymisation(guarded):
    doc = Document(doc_id="D1", doc_date=date(2026, 5, 12),
                   text="Alice Chen hands payments to Dana Lee, cc alice.chen@example.com. Done.")
    transport = EchoTransport()
    extractor = ClaimExtractor(LLMClient(transport=transport, use_cache=False))

    (claim,) = extractor.extract(doc)

    sent = json.dumps(transport.calls)
    assert not any(pii in sent for pii in ("Alice Chen", "Dana Lee", "alice.chen@example.com"))
    assert "PERSON_1" in sent and "EMAIL_1" in sent
    assert claim.quote == "Alice Chen hands payments to Dana Lee, cc alice.chen@example.com."
    assert claim.subject == "Alice Chen" and claim.object == "alice.chen@example.com"
    assert extractor.dropped_total == 0
    assert transport.calls[0]["response_format"]["json_schema"]["name"] == "claims"  # not double-wrapped


def test_cli_ingests_through_guard_and_logs_egress(guarded, monkeypatch):
    from chronicle.ingest import __main__ as cli

    transport, made = EchoTransport(), {}

    class Client(LLMClient):
        def __init__(self, **kwargs):
            made.update(kwargs)
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr(cli, "LLMClient", Client)
    state = guarded / "state"
    rc = cli.main(["--corpus", str(FIX), "--state", str(state), "--model", "m-test", "--timeout", "7"])

    assert rc == 0
    assert made == {"default_model": "m-test", "timeout": 7.0, "max_tokens": 8192}
    assert {c["model"] for c in transport.calls} == {"m-test"}
    assert {c["max_tokens"] for c in transport.calls} == {8192}
    assert "Alice Chen" not in json.dumps(transport.calls)

    claims = read_claims(state / "claims.jsonl")
    assert any("Alice Chen" in c.quote for c in claims)
    log = [json.loads(line) for line in (guarded / "egress.log").read_text().splitlines()]
    assert len(log) == len(transport.calls) == 3
    assert all(r["model"] == "m-test" for r in log) and any("PERSON" in r["pii_types"] for r in log)


def test_no_direct_openai_client_in_ingest():
    pkg = Path(__file__).parents[2] / "chronicle" / "ingest"
    offenders = [p.name for p in pkg.rglob("*.py") if re.search(r"^\s*(from|import)\s+openai\b",
                                                               p.read_text(), re.MULTILINE)]
    assert offenders == []
