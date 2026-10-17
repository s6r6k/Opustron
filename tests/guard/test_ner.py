"""Real Presidio + spaCy name detection (no fakes): names leave as tokens, dates don't."""

import logging
import sys
from types import SimpleNamespace

import pytest

from chronicle.guard import egress_logger, llm_client, pii_detector
from chronicle.guard.egress_logger import EgressLogger
from chronicle.guard.llm_client import LLMClient
from chronicle.guard.pii_detector import detect, ner_available
from chronicle.guard.pseudonymizer import pseudonymize, reidentify
from chronicle.integrations.tavily import PrivacyBlocked, TavilyClient

TAKEOVER = "Effective today, Dana Whitfield takes over payments from Alice Tan."


def test_name_detection_is_installed():
    # Fails CI (rather than silently sending names) if spaCy's model is missing.
    assert ner_available()


def test_full_names_are_detected():
    people = {m.value for m in detect(TAKEOVER) if m.entity_type == "PERSON"}
    assert people == {"Dana Whitfield", "Alice Tan"}


@pytest.mark.parametrize("text", ["due next Friday, 12 May 2026", "Who owned payments on 3 May?", "The meeting is at 9am tomorrow"])
def test_dates_are_never_pseudonymised(text):
    redacted, _ = pseudonymize(text)
    assert redacted == text


def test_names_round_trip_and_dates_survive():
    redacted, mapping = pseudonymize(TAKEOVER)
    assert redacted == "Effective today, PERSON_1 takes over payments from PERSON_2."
    assert reidentify(redacted, mapping) == TAKEOVER


def test_names_never_reach_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(egress_logger, "_default_logger", EgressLogger(tmp_path / "egress.log"))
    sent = []

    def transport(**kwargs):
        sent.append(kwargs["messages"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="PERSON_1 now owns payments."))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    client = LLMClient(api_key="test", use_cache=False, transport=transport)
    reply = client.complete([{"role": "user", "content": TAKEOVER}])

    outgoing = sent[0][0]["content"]
    assert "Dana Whitfield" not in outgoing and "Alice Tan" not in outgoing
    assert reply == "Dana Whitfield now owns payments."
    [entry] = egress_logger._default_logger.tail()
    assert "PERSON" in entry["pii_types"]


def test_tavily_refuses_a_query_naming_a_person():
    with pytest.raises(PrivacyBlocked) as exc:
        TavilyClient("k", transport=lambda *a: b"{}").search("Alice Tan new job")
    assert "PERSON" in exc.value.pii_types


def test_missing_model_warns_once_and_falls_back(monkeypatch, caplog):
    monkeypatch.setattr(pii_detector, "_presidio_analyzer", None)
    monkeypatch.setattr(pii_detector, "_presidio_load_failed", False)
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)

    with caplog.at_level(logging.WARNING, logger="chronicle.guard.pii_detector"):
        assert not ner_available()
        assert {m.entity_type for m in detect("mail bob@corp.io")} == {"EMAIL_ADDRESS"}
        detect("again")
    assert sum("Name detection is OFF" in r.message for r in caplog.records) == 1
