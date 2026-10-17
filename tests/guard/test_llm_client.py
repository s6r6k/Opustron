import json
from types import SimpleNamespace

import pytest

from chronicle.guard import egress_logger, llm_client
from chronicle.guard.egress_logger import EgressLogger
from chronicle.guard.llm_client import LLMClient

BARE = {"type": "object", "properties": {"x": {"type": "integer"}}}
WRAPPED = {"name": "claims", "schema": BARE}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep the cache and egress log out of ~/.chronicle."""
    monkeypatch.setattr(llm_client, "_CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    monkeypatch.setattr(egress_logger, "_default_logger", EgressLogger(tmp_path / "egress.log"))
    return tmp_path


def reply(content, prompt_tokens=3, completion_tokens=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class Recorder:
    def __init__(self, content='{"x": 1}'):
        self.content, self.calls = content, []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.content)


class Rejected(Exception):
    status_code = 400


def test_bare_schema_is_wrapped_once_and_parsed():
    t = Recorder()
    out = LLMClient(transport=t, use_cache=False).complete([{"role": "user", "content": "hi"}], schema=BARE)
    assert out == {"x": 1}
    assert t.calls[0]["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "response", "schema": BARE}}


def test_wrapped_schema_passed_as_is_and_returns_text():
    t = Recorder('<think>{"draft": true}</think>{"x": 1}')
    out = LLMClient(transport=t, use_cache=False).complete([{"role": "user", "content": "hi"}], WRAPPED)
    assert out == '<think>{"draft": true}</think>{"x": 1}'  # caller parses; no double wrap
    assert t.calls[0]["response_format"] == {"type": "json_schema", "json_schema": WRAPPED}


def test_no_schema_returns_text_without_response_format():
    t = Recorder("plain answer")
    assert LLMClient(transport=t, use_cache=False).complete([{"role": "user", "content": "hi"}]) == "plain answer"
    assert "response_format" not in t.calls[0]


def test_max_tokens_configurable(monkeypatch):
    t = Recorder()
    LLMClient(transport=t, use_cache=False).complete([{"role": "user", "content": "a"}])
    LLMClient(transport=t, use_cache=False, max_tokens=8192).complete([{"role": "user", "content": "b"}])
    LLMClient(transport=t, use_cache=False, max_tokens=8192).complete([{"role": "user", "content": "c"}],
                                                                       max_tokens=50)
    monkeypatch.setenv("CHRONICLE_MAX_TOKENS", "4096")
    LLMClient(transport=t, use_cache=False).complete([{"role": "user", "content": "d"}])
    assert [c["max_tokens"] for c in t.calls] == [1024, 8192, 50, 4096]


def test_schema_rejection_falls_back_and_sticks():
    calls = []

    def transport(**kwargs):
        calls.append(kwargs)
        if "response_format" in kwargs:
            raise Rejected("response_format json_schema is not supported")
        return reply('{"x": 2}')

    client = LLMClient(transport=transport, use_cache=False)
    assert client.complete([{"role": "user", "content": "a"}], WRAPPED) == '{"x": 2}'
    assert client.complete([{"role": "user", "content": "b"}], BARE) == {"x": 2}
    # first call: rejected + retried; second call skips response_format entirely
    assert ["response_format" in c for c in calls] == [True, False, False]


def test_other_errors_are_not_swallowed():
    def transport(**kwargs):
        raise TimeoutError("slow")

    client = LLMClient(transport=transport, use_cache=False)
    with pytest.raises(TimeoutError):
        client.complete([{"role": "user", "content": "a"}], WRAPPED)
    assert client._structured  # a timeout says nothing about json_schema support


def test_failed_retry_keeps_structured_output_on():
    def transport(**kwargs):
        raise Rejected("context too long")

    client = LLMClient(transport=transport, use_cache=False)
    with pytest.raises(Rejected):
        client.complete([{"role": "user", "content": "a"}], WRAPPED)
    assert client._structured


def test_pii_redacted_on_the_wire_restored_and_logged(isolated_home):
    t = Recorder("Reply to EMAIL_1 today.")
    out = LLMClient(transport=t, use_cache=False).complete(
        [{"role": "user", "content": "Write to alice@example.com"}])
    assert "alice@example.com" not in json.dumps(t.calls)
    assert out == "Reply to alice@example.com today."
    (record,) = [json.loads(line) for line in (isolated_home / "egress.log").read_text().splitlines()]
    assert record["redacted"] and record["pii_types"] == ["EMAIL"]
    assert record["prompt_tokens"] == 3 and "alice@example.com" not in record["request_preview"]


def test_model_and_timeout_settings(monkeypatch):
    monkeypatch.delenv("CHRONICLE_MODEL", raising=False)
    assert LLMClient(use_cache=False).model == llm_client.DEV_MODEL
    assert LLMClient(use_cache=False, default_model="m-x").model == "m-x"

    seen = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=Recorder()))

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-unrelated")
    monkeypatch.setenv("NEBIUS_API_KEY", "nebius-key")
    LLMClient(use_cache=False, timeout=12).complete([{"role": "user", "content": "a"}])
    assert seen["timeout"] == 12 and seen["api_key"] == "nebius-key"


ANSWER = {"answer": "Bob", "source_ids": ["email_042"]}


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps(ANSWER),
        f"```json\n{json.dumps(ANSWER)}\n```",
        f"<think>Owner changed on 15 May, so {{\"answer\": \"Alice\"}} is stale.</think>\n{json.dumps(ANSWER)}",
        f"Let me check {{the dates}} first...\n</think>\n\n{json.dumps(ANSWER)}",
        f"<think>hmm</think>```json\n{json.dumps(ANSWER)}\n```",
        f"Draft: {{\"answer\": \"Alice\", \"source_ids\": []}}\nFinal: {json.dumps(ANSWER)}",
    ],
    ids=["plain", "fenced", "think-with-braces", "stray-close-tag", "think-then-fence", "last-wins"],
)
def test_parse_json_reply_tolerates_reasoning_noise(raw):
    assert llm_client.parse_json_reply(raw) == ANSWER


def test_parse_json_reply_returns_outer_object_not_nested():
    raw = '<think>x</think>{"answer": "Bob", "meta": {"confidence": 0.9}}'
    assert llm_client.parse_json_reply(raw) == {"answer": "Bob", "meta": {"confidence": 0.9}}


@pytest.mark.parametrize("raw", ["", "<think>still thinking", "Not in the corpus.", "{broken"])
def test_parse_json_reply_raises_when_no_json(raw):
    with pytest.raises(ValueError):
        llm_client.parse_json_reply(raw)


def test_bare_schema_call_survives_think_block():
    t = Recorder('<think>EMAIL_1 sent the handover on 15 May.</think>{"answer": "EMAIL_1", "source_ids": ["email_042"]}')
    out = LLMClient(transport=t, use_cache=False).complete(
        [{"role": "user", "content": "Who sent the handover? It came from dana@corp.io."}], schema=BARE
    )
    assert "dana@corp.io" not in json.dumps(t.calls[0]["messages"])
    assert out == {"answer": "dana@corp.io", "source_ids": ["email_042"]}  # restored, then parsed
