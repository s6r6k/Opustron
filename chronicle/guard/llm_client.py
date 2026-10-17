"""Shared LLM client for Chronicle.

Every module (P1–P4) uses this instead of calling openai directly.
All requests pass through the privacy router before leaving the machine.

Usage:
    from chronicle.guard import llm

    response = llm.complete(
        messages=[{"role": "user", "content": "Who owned payments on 3 May?"}],
    )

    # Structured JSON output, parsed for you:
    data = llm.complete(messages=..., schema={"type": "object", ...})

    # Structured output, raw reply text (you parse it yourself):
    text = llm.complete(messages=..., schema={"name": "claims", "schema": {...}})
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_CACHE_DIR = Path.home() / ".chronicle" / "llm_cache"

# Models
DEV_MODEL = "nvidia/nemotron-mini-4b-instruct"   # cheap, fast
PROD_MODEL = "nvidia/nemotron-4-340b-instruct"    # official benchmark runs
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MAX_TOKENS = 1024  # reasoning models (Nemotron) need ~8192: set max_tokens or CHRONICLE_MAX_TOKENS

# HTTP statuses an OpenAI-compatible endpoint returns when it rejects response_format
_SCHEMA_REJECTED_STATUSES = (400, 422)


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?")
_JSON_START = re.compile(r"[{\[]")


def parse_json_reply(text: str) -> Any:
    """Parse a model reply that should be JSON, tolerating reasoning-model noise.

    Strips <think> blocks (and anything before a stray closing </think>) and
    code fences, then returns the LAST complete top-level JSON value, since a
    reasoning model's answer follows its thinking. Raises ValueError if none.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = _THINK_BLOCK.sub("", text)
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[1]
    cleaned = _FENCE.sub("", cleaned)

    decoder, found, pos = json.JSONDecoder(), None, 0
    while (match := _JSON_START.search(cleaned, pos)) is not None:
        try:
            value, end = decoder.raw_decode(cleaned, match.start())
        except json.JSONDecodeError:
            pos = match.start() + 1
            continue
        found, pos = value, end  # skip past it, so nested objects never win
    if found is None:
        raise ValueError(f"model reply contained no JSON: {text[:120]!r}")
    return found


def _is_wrapped(schema: dict[str, Any]) -> bool:
    """True for an OpenAI ``json_schema`` envelope ({"name": ..., "schema": {...}})."""
    return "type" not in schema and "name" in schema and isinstance(schema.get("schema"), dict)


class LLMClient:
    """OpenAI-compatible client wired to Nebius Token Factory."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        use_cache: bool = True,
        privacy_router: Any | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        """
        transport: optional replacement for ``OpenAI().chat.completions.create``
        (takes its keyword arguments, returns an object with ``.choices`` and
        ``.usage``). Tests use it to run without the network.
        """
        self._api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self._base_url = base_url or os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL)
        self._default_model = default_model or os.environ.get(
            "CHRONICLE_MODEL", DEV_MODEL
        )
        self._use_cache = use_cache
        self._router = privacy_router  # set after construction to avoid circular import
        self.max_tokens = max_tokens or int(
            os.environ.get("CHRONICLE_MAX_TOKENS", DEFAULT_MAX_TOKENS)
        )
        self._timeout = timeout
        self._transport = transport
        self._transport_lock = threading.Lock()
        self._structured = True  # flips to False once the endpoint rejects json_schema

        if use_cache:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def model(self) -> str:
        """The model used when ``complete`` is called without ``model``."""
        return self._default_model

    # ------------------------------------------------------------------
    # Public interface (P1–P4 all call this)
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str | dict[str, Any]:
        """Call the LLM, routing PII through the privacy router.

        `schema` may be a bare JSON Schema or an OpenAI ``json_schema``
        envelope ({"name": ..., "schema": {...}}):

        - no schema: returns the reply text.
        - bare schema: returns the parsed JSON object.
        - envelope: returns the reply text, for callers that parse it
          themselves.

        Bare-schema replies go through ``parse_json_reply``, so <think> blocks
        and code fences around the JSON are tolerated.

        If the endpoint rejects ``response_format``, the call is retried
        without it and later calls on this client skip it.
        """
        from .egress_logger import get_logger
        from .privacy_router import PrivacyRouter

        router: PrivacyRouter = self._router or PrivacyRouter()

        # Redact PII in all message contents
        redacted_messages, mapping = router.redact_messages(messages)

        # Check cache
        cache_key = self._cache_key(redacted_messages, schema, model or self._default_model)
        if self._use_cache:
            cached = self._load_cache(cache_key)
            if cached is not None:
                raw = cached
                prompt_tokens = completion_tokens = 0
            else:
                raw, prompt_tokens, completion_tokens = self._call_api(
                    redacted_messages, schema, model, temperature, max_tokens or self.max_tokens
                )
                self._save_cache(cache_key, raw)
        else:
            raw, prompt_tokens, completion_tokens = self._call_api(
                redacted_messages, schema, model, temperature, max_tokens or self.max_tokens
            )

        # Re-identify pseudonyms in the response
        restored_raw = router.restore(raw, mapping)

        # Log egress
        get_logger().log(
            provider="nebius_token_factory",
            model=model or self._default_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            redacted=mapping is not None and bool(mapping.pii_types_seen()),
            pii_types=mapping.pii_types_seen() if mapping else [],
            request_preview=redacted_messages[-1]["content"][:200] if redacted_messages else "",
        )

        if schema is not None and not _is_wrapped(schema):
            return parse_json_reply(restored_raw)

        return restored_raw

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_api(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """Make the actual API call. Returns (content, prompt_tokens, completion_tokens)."""
        create = self._get_transport()

        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None and self._structured:
            envelope = schema if _is_wrapped(schema) else {"name": "response", "schema": schema}
            kwargs["response_format"] = {"type": "json_schema", "json_schema": envelope}

        try:
            resp = create(**kwargs)
        except Exception as exc:
            if "response_format" not in kwargs or not _rejects_schema(exc):
                raise
            kwargs.pop("response_format")
            resp = create(**kwargs)
            self._structured = False

        content = resp.choices[0].message.content or ""
        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return content, prompt_tokens, completion_tokens

    def _get_transport(self) -> Callable[..., Any]:
        with self._transport_lock:
            if self._transport is None:
                try:
                    from openai import OpenAI
                except ImportError as exc:
                    raise RuntimeError(
                        "openai package is required: uv add openai"
                    ) from exc
                kwargs: dict[str, Any] = {"api_key": self._api_key, "base_url": self._base_url,
                                          "max_retries": 2}
                if self._timeout is not None:
                    kwargs["timeout"] = self._timeout
                self._transport = OpenAI(**kwargs).chat.completions.create
            return self._transport

    def _cache_key(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        model: str,
    ) -> str:
        payload = json.dumps({"messages": messages, "schema": schema, "model": model}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _load_cache(self, key: str) -> str | None:
        path = _CACHE_DIR / f"{key}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _save_cache(self, key: str, content: str) -> None:
        path = _CACHE_DIR / f"{key}.txt"
        path.write_text(content, encoding="utf-8")


def _rejects_schema(exc: Exception) -> bool:
    """Did the endpoint refuse the request (most likely its response_format)?"""
    return getattr(exc, "status_code", None) in _SCHEMA_REJECTED_STATUSES


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly:
#   from chronicle.guard import llm
#   llm.complete(messages)
# ---------------------------------------------------------------------------

llm = LLMClient()
