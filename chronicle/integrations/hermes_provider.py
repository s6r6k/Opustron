"""Chronicle as a Hermes Agent memory provider.

Hermes loads this through deploy/hermes-plugin/chronicle (see its README).
The provider talks to Chronicle only through ``ChronicleBackend``, so the
in-memory placeholder below can be swapped for the real bi-temporal store
without touching the Hermes side.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from chronicle.guard.pii_detector import detect
from chronicle.guard.pseudonymizer import PseudonymMapping, pseudonymize
from chronicle.integrations.tavily import PrivacyBlocked, TavilyClient, TavilyError
from chronicle.memory.api import MemoryAPI
from chronicle.schema import Event, Source

try:  # Only importable inside a Hermes process.
    from agent.memory_provider import (
        MemoryProvider,
        is_trivial_prompt,
        spawn_context_thread,
    )
except ImportError:
    from abc import ABC as MemoryProvider

    def is_trivial_prompt(text: str) -> bool:
        stripped = (text or "").strip()
        return not stripped or stripped.startswith("/")

    def spawn_context_thread(target, *, name, daemon=True, args=(), kwargs=None):
        return threading.Thread(target=target, name=name, daemon=daemon, args=args, kwargs=kwargs or {})


logger = logging.getLogger(__name__)

PROVIDER_NAME = "chronicle"
RECALL_LIMIT = 5

# Names stay readable because the user typed them into Hermes anyway; contact
# and financial identifiers recalled from documents do not leave the machine.
_RECALL_REDACT_TYPES = {"EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD", "IP_ADDRESS"}

_WORD_RE = re.compile(r"[a-z0-9]{3,}")


# ---------------------------------------------------------------------------
# Backend seam
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Recollection:
    memory_id: str
    content: str
    source: str
    valid_from: datetime | None
    valid_to: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.memory_id,
            "content": self.content,
            "source": self.source,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
        }


class ChronicleBackend(Protocol):
    def remember(
        self,
        content: str,
        *,
        source: str,
        occurred_at: datetime | None = None,
        supersedes: str | None = None,
    ) -> str: ...

    def retire(self, content: str, *, at: datetime) -> None: ...

    def recall(self, query: str, *, as_of: datetime | None = None, limit: int = RECALL_LIMIT) -> list[Recollection]: ...


class InMemoryBackend:
    """Placeholder over ``MemoryAPI`` until the SQLite bi-temporal store lands.

    Facts are never deleted: superseding or retiring a fact closes its
    ``valid_to``, so ``recall(as_of=...)`` still sees what was true then.
    """

    def __init__(self, api: MemoryAPI | None = None) -> None:
        self._api = api or MemoryAPI()
        self._lock = threading.Lock()

    def remember(self, content, *, source, occurred_at=None, supersedes=None):
        valid_from = _utc(occurred_at) or _now()
        with self._lock:
            if supersedes:
                self._close(supersedes, valid_from)
            event = Event(content=content, source=Source(uri=source, kind="hermes"), occurred_at=valid_from)
            self._api.remember(event)
        return event.event_id

    def retire(self, content, *, at):
        with self._lock:
            self._close(content, _utc(at))

    def recall(self, query, *, as_of=None, limit=RECALL_LIMIT):
        as_of = _utc(as_of) or _now()
        terms = set(_WORD_RE.findall(query.casefold()))
        scored = []
        for event in self._api.list_memories():
            valid_to = event.metadata.get("valid_to")
            if event.occurred_at > as_of or (valid_to and valid_to <= as_of):
                continue
            score = len(terms & set(_WORD_RE.findall(event.content.casefold())))
            if score:
                scored.append((score, event.occurred_at, event))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            Recollection(e.event_id, e.content, e.source.uri, e.occurred_at, e.metadata.get("valid_to"))
            for _, _, e in scored[:limit]
        ]

    def _close(self, content_or_id: str, at: datetime) -> None:
        for event in self._api.list_memories():
            if event.metadata.get("valid_to"):
                continue
            if content_or_id in (event.event_id, event.content):
                event.metadata["valid_to"] = at
                event.metadata["superseded_at"] = _now()


# ---------------------------------------------------------------------------
# Hermes provider
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "chronicle_recall",
        "description": (
            "Search Chronicle's long-term memory. Pass as_of (YYYY-MM-DD) to see what was "
            "true on that date; superseded facts are returned with their valid_to date."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up."},
                "as_of": {"type": "string", "description": "Optional date, YYYY-MM-DD."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "chronicle_remember",
        "description": "Store a durable fact in Chronicle's long-term memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact, as one sentence."},
                "occurred_at": {"type": "string", "description": "Optional date it became true, YYYY-MM-DD."},
            },
            "required": ["content"],
        },
    },
]

_WEB_TOOL = {
    "name": "chronicle_web_search",
    "description": (
        "Search the public web (Tavily) to enrich memory about organisations, products, places "
        "or public events. Queries naming private people or containing emails, phone numbers or "
        "IDs are refused."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "max_results": {"type": "integer", "description": "Optional, 1-20 (default 5)."},
        },
        "required": ["query"],
    },
}


class ChronicleMemoryProvider(MemoryProvider):
    def __init__(self, backend: ChronicleBackend | None = None, web: TavilyClient | None = None) -> None:
        self._backend = backend or InMemoryBackend()
        self._web = web or TavilyClient()
        self._mapping = PseudonymMapping()
        self._session_id = ""
        self._hermes_home = ""
        self._sync_thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._hermes_home = str(kwargs.get("hermes_home", ""))

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "nebius_api_key",
                "description": "Nebius Token Factory API key (fact extraction; recall works offline)",
                "secret": True,
                "required": False,
                "env_var": "NEBIUS_API_KEY",
            },
            {
                "key": "tavily_api_key",
                "description": "Tavily API key (optional; enables chronicle_web_search)",
                "secret": True,
                "required": False,
                "env_var": "TAVILY_API_KEY",
            },
        ]

    def system_prompt_block(self) -> str:
        return (
            "Chronicle long-term memory is active. It is bi-temporal: facts carry the dates they "
            "were true. For questions about a past date, call chronicle_recall with as_of."
        )

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [*_TOOLS, _WEB_TOOL] if self._web.configured else list(_TOOLS)

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            if tool_name == "chronicle_recall":
                found = self._backend.recall(args["query"], as_of=_parse_day(args.get("as_of")))
                return json.dumps({"results": [self._redacted(r.to_dict()) for r in found]})
            if tool_name == "chronicle_remember":
                memory_id = self._backend.remember(
                    args["content"],
                    source=f"hermes://session/{self._session_id}/tool",
                    occurred_at=_parse_day(args.get("occurred_at"), end_of_day=False),
                )
                return json.dumps({"ok": True, "id": memory_id})
            if tool_name == "chronicle_web_search":
                found = self._web.search(args["query"], max_results=int(args.get("max_results") or 5))
                return json.dumps({"results": [r.to_dict() for r in found]})
            return json.dumps({"error": f"unknown tool: {tool_name}"})
        except PrivacyBlocked as exc:
            return json.dumps({"error": str(exc), "blocked": True, "pii_types": exc.pii_types})
        except TavilyError as exc:
            return json.dumps({"error": str(exc)})
        except (KeyError, ValueError) as exc:
            return json.dumps({"error": f"bad arguments: {exc}"})

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if is_trivial_prompt(query):
            return ""
        found = self._backend.recall(query)
        if not found:
            return ""
        lines = ["Relevant facts from Chronicle memory:"]
        for r in found:
            since = r.valid_from.date().isoformat() if r.valid_from else "unknown"
            lines.append(f"- {self._redact_text(r.content)} (true since {since}; source {r.source})")
        return "\n".join(lines)

    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None, turn_author=None):
        # Only the user's words become memory; storing assistant replies would let
        # the model's own guesses come back later as "facts".
        if is_trivial_prompt(user_content):
            return
        source = f"hermes://session/{session_id or self._session_id}"

        def _sync() -> None:
            try:
                self._backend.remember(user_content, source=source)
            except Exception:
                logger.warning("Chronicle sync_turn failed", exc_info=True)

        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)
        self._sync_thread = spawn_context_thread(_sync, name="chronicle-sync")
        self._sync_thread.start()

    def on_memory_write(self, action: str, target: str, content: str, metadata: dict | None = None) -> None:
        source = f"hermes://builtin/{target}"
        if action == "add":
            self._backend.remember(content, source=source)
        elif action == "replace":
            previous = (metadata or {}).get("previous_content")
            self._backend.remember(content, source=source, supersedes=previous)
        elif action == "remove":
            self._backend.retire(content, at=_now())

    def shutdown(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

    def _redact_text(self, text: str) -> str:
        if os.environ.get("CHRONICLE_REDACT_RECALL", "1") == "0":
            return text
        matches = [m for m in detect(text) if m.entity_type in _RECALL_REDACT_TYPES]
        redacted, _ = pseudonymize(text, self._mapping, entities=matches)
        return redacted

    def _redacted(self, item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "content": self._redact_text(item["content"])}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_day(value: str | None, *, end_of_day: bool = True) -> datetime | None:
    if not value:
        return None
    day = date.fromisoformat(value[:10])
    return datetime.combine(day, time.max if end_of_day else time.min, tzinfo=UTC)
