import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chronicle.guard.egress_logger import EgressLogger
from chronicle.integrations import tavily
from chronicle.integrations.hermes_provider import (
    ChronicleMemoryProvider,
    InMemoryBackend,
)
from chronicle.integrations.tavily import TavilyClient


def _day(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=UTC)


@pytest.fixture
def provider():
    p = ChronicleMemoryProvider(web=TavilyClient(api_key=""))
    p.initialize("s1", hermes_home="/tmp/hermes-test")
    return p


def test_identity_and_tools(provider):
    assert provider.name == "chronicle"
    assert provider.is_available()
    names = {t["name"] for t in provider.get_tool_schemas()}
    assert names == {"chronicle_recall", "chronicle_remember"}
    for tool in provider.get_tool_schemas():
        assert tool["parameters"]["type"] == "object"


def test_remember_then_recall_via_tools(provider):
    out = json.loads(provider.handle_tool_call("chronicle_remember", {"content": "Alice owns the payments service"}))
    assert out["ok"]
    results = json.loads(provider.handle_tool_call("chronicle_recall", {"query": "who owns payments"}))["results"]
    assert results[0]["content"] == "Alice owns the payments service"


def test_as_of_returns_fact_true_at_that_date():
    backend = InMemoryBackend()
    old = backend.remember("Alice owns payments", source="test", occurred_at=_day("2026-05-01"))
    backend.remember("Bob owns payments", source="test", occurred_at=_day("2026-05-15"), supersedes=old)

    before = backend.recall("payments owner", as_of=_day("2026-05-10"))
    after = backend.recall("payments owner", as_of=_day("2026-05-20"))

    assert [r.content for r in before] == ["Alice owns payments"]
    assert before[0].valid_to == _day("2026-05-15")
    assert [r.content for r in after] == ["Bob owns payments"]


def test_as_of_tool_argument(provider):
    provider.handle_tool_call("chronicle_remember", {"content": "Alice owns payments", "occurred_at": "2026-05-01"})
    on_date = json.loads(provider.handle_tool_call("chronicle_recall", {"query": "payments", "as_of": "2026-05-01"}))
    before = json.loads(provider.handle_tool_call("chronicle_recall", {"query": "payments", "as_of": "2026-04-30"}))
    assert len(on_date["results"]) == 1
    assert before["results"] == []


def test_builtin_replace_supersedes_and_remove_retires(provider):
    provider.on_memory_write("add", "memory", "User prefers tea")
    provider.on_memory_write("replace", "memory", "User prefers coffee", {"previous_content": "User prefers tea"})
    assert "coffee" in provider.prefetch("what does the user prefer")
    assert "tea" not in provider.prefetch("what does the user prefer")

    provider.on_memory_write("remove", "memory", "User prefers coffee")
    assert provider.prefetch("what does the user prefer") == ""


def test_prefetch_redacts_contact_details_but_keeps_names(provider, monkeypatch):
    monkeypatch.delenv("CHRONICLE_REDACT_RECALL", raising=False)
    provider.handle_tool_call("chronicle_remember", {"content": "Alice email is alice@example.com"})
    block = provider.prefetch("alice email")
    assert "alice@example.com" not in block
    assert "EMAIL_1" in block
    assert "Alice" in block


def test_recall_tool_redacts_too(provider):
    provider.handle_tool_call("chronicle_remember", {"content": "Bob phone is +1 415 555 0123"})
    results = json.loads(provider.handle_tool_call("chronicle_recall", {"query": "bob phone"}))["results"]
    assert "555" not in results[0]["content"]


def test_redaction_can_be_disabled(provider, monkeypatch):
    monkeypatch.setenv("CHRONICLE_REDACT_RECALL", "0")
    provider.handle_tool_call("chronicle_remember", {"content": "Alice email is alice@example.com"})
    assert "alice@example.com" in provider.prefetch("alice email")


def test_sync_turn_stores_user_message_only(provider):
    provider.sync_turn("Carol joined the platform team", "Noted, welcome Carol!")
    provider.shutdown()
    block = provider.prefetch("platform team")
    assert "Carol joined the platform team" in block
    assert "welcome" not in block


def test_sync_turn_skips_trivial_prompts(provider):
    provider.sync_turn("/help", "Here are the commands")
    provider.shutdown()
    assert provider.prefetch("help commands") == ""


def test_bad_tool_calls_return_json_errors(provider):
    assert "error" in json.loads(provider.handle_tool_call("nope", {}))
    assert "error" in json.loads(provider.handle_tool_call("chronicle_recall", {}))
    assert "error" in json.loads(provider.handle_tool_call("chronicle_recall", {"query": "x", "as_of": "May 3"}))


def test_plugin_dir_registers_provider_like_hermes_loads_it():
    # Hermes imports user plugins by path under its own namespace, not as `chronicle`.
    plugin_init = Path(__file__).resolve().parents[2] / "deploy/hermes-plugin/chronicle/__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_user_plugins.chronicle", plugin_init)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    registered = []

    class Ctx:
        def register_memory_provider(self, p):
            registered.append(p)

    module.register(Ctx())
    assert isinstance(registered[0], ChronicleMemoryProvider)


@pytest.fixture
def web_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(tavily, "get_logger", lambda: EgressLogger(tmp_path / "egress.log"))
    sent = []

    def transport(url, headers, body, timeout):
        sent.append(json.loads(body))
        return json.dumps({"results": [{"title": "Nebius", "url": "https://nebius.com", "content": "AI cloud", "score": 0.8}]}).encode()

    p = ChronicleMemoryProvider(web=TavilyClient("tvly-test", transport=transport))
    p.initialize("s1")
    p.sent = sent
    return p


def test_web_tool_only_offered_when_tavily_configured(provider, web_provider):
    assert "chronicle_web_search" not in {t["name"] for t in provider.get_tool_schemas()}
    assert "chronicle_web_search" in {t["name"] for t in web_provider.get_tool_schemas()}


def test_web_search_tool_returns_results(web_provider):
    out = json.loads(web_provider.handle_tool_call("chronicle_web_search", {"query": "Nebius Token Factory pricing", "max_results": 2}))
    assert out["results"][0]["url"] == "https://nebius.com"
    assert web_provider.sent == [{"query": "Nebius Token Factory pricing", "max_results": 2}]


def test_web_search_tool_refuses_personal_data(web_provider):
    out = json.loads(web_provider.handle_tool_call("chronicle_web_search", {"query": "alice@example.com"}))
    assert out["blocked"] is True
    assert "EMAIL_ADDRESS" in out["pii_types"]
    assert web_provider.sent == []


def test_web_search_without_key_reports_error(provider):
    out = json.loads(provider.handle_tool_call("chronicle_web_search", {"query": "Nebius"}))
    assert "TAVILY_API_KEY" in out["error"]
