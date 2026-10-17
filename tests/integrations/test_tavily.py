import io
import json
import urllib.error

import pytest

from chronicle.guard.egress_logger import EgressLogger
from chronicle.guard.pii_detector import PiiMatch
from chronicle.integrations import tavily
from chronicle.integrations.tavily import PrivacyBlocked, TavilyClient, TavilyError

RESPONSE = {
    "query": "NVIDIA OpenShell",
    "results": [
        {"title": "OpenShell docs", "url": "https://docs.nvidia.com/openshell", "content": "Sandbox runtime", "score": 0.91},
        {"title": "Repo", "url": "https://github.com/NVIDIA/OpenShell", "content": "Source", "score": None},
    ],
    "response_time": 0.4,
}


class FakeTransport:
    def __init__(self, response=RESPONSE):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        return self.response if isinstance(self.response, bytes) else json.dumps(self.response).encode()


@pytest.fixture
def egress(tmp_path, monkeypatch):
    logger = EgressLogger(tmp_path / "egress.log")
    monkeypatch.setattr(tavily, "get_logger", lambda: logger)
    return logger


def test_search_sends_bearer_request_and_parses_results(egress):
    transport = FakeTransport()
    results = TavilyClient("tvly-test", transport=transport).search("  NVIDIA OpenShell  ", max_results=3)

    call = transport.calls[0]
    assert call["url"] == "https://api.tavily.com/search"
    assert call["headers"]["Authorization"] == "Bearer tvly-test"
    assert call["body"] == {"query": "NVIDIA OpenShell", "max_results": 3}
    assert [r.title for r in results] == ["OpenShell docs", "Repo"]
    assert results[0].score == 0.91
    assert results[1].score == 0.0


def test_max_results_is_clamped(egress):
    transport = FakeTransport()
    client = TavilyClient("k", transport=transport)
    client.search("Nebius", max_results=500)
    client.search("Nebius", max_results=0)
    assert [c["body"]["max_results"] for c in transport.calls] == [20, 1]


def test_sent_queries_are_logged(egress):
    TavilyClient("k", transport=FakeTransport()).search("Nebius Token Factory pricing")
    [entry] = egress.tail()
    assert entry["provider"] == "tavily"
    assert entry["request_preview"] == "Nebius Token Factory pricing"
    assert entry["redacted"] is False


@pytest.mark.parametrize(
    ("query", "pii_type"),
    [("who is alice@example.com", "EMAIL_ADDRESS"), ("owner of +1 415 555 0123", "PHONE_NUMBER")],
)
def test_queries_with_personal_data_are_refused(egress, query, pii_type):
    transport = FakeTransport()
    with pytest.raises(PrivacyBlocked) as exc:
        TavilyClient("k", transport=transport).search(query)
    assert pii_type in exc.value.pii_types
    assert transport.calls == []
    assert egress.tail() == []


def test_person_names_are_refused_but_organisations_allowed(egress, monkeypatch):
    def fake_detect(text):
        if "Alice" in text:
            return [PiiMatch("PERSON", "Alice Tan", 0, 9)]
        return [PiiMatch("ORGANIZATION", "Nebius", 0, 6)]

    monkeypatch.setattr(tavily, "detect", fake_detect)
    transport = FakeTransport()
    client = TavilyClient("k", transport=transport)

    with pytest.raises(PrivacyBlocked):
        client.search("Alice Tan new job")
    client.search("Nebius funding round")
    assert [c["body"]["query"] for c in transport.calls] == ["Nebius funding round"]


def test_missing_key_fails_before_anything_is_sent(egress, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    transport = FakeTransport()
    client = TavilyClient(transport=transport)
    assert not client.configured
    with pytest.raises(TavilyError, match="TAVILY_API_KEY"):
        client.search("Nebius")
    assert transport.calls == []
    assert egress.tail() == []


def test_key_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-env")
    assert TavilyClient().api_key == "tvly-env"


def test_empty_query_is_rejected(egress):
    with pytest.raises(ValueError):
        TavilyClient("k", transport=FakeTransport()).search("   ")


def test_non_json_response_raises(egress):
    with pytest.raises(TavilyError, match="not JSON"):
        TavilyClient("k", transport=FakeTransport(b"<html>gateway error</html>")).search("Nebius")


def test_http_errors_become_tavily_errors(monkeypatch):
    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 432, "limit", {}, io.BytesIO(b""))

    monkeypatch.setattr(tavily.urllib.request, "urlopen", fail)
    with pytest.raises(TavilyError, match="432"):
        tavily._urllib_transport("https://api.tavily.com/search", {}, b"{}", 1.0)
