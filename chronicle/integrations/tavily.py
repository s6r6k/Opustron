"""Tavily web search, gated so personal data never becomes a search query.

Pseudonymising a search query would make it useless (nobody can search for
PERSON_1), so instead a query that identifies a person is refused before it
leaves the machine. Every query that is sent is written to the egress log.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from chronicle.guard.egress_logger import get_logger
from chronicle.guard.pii_detector import detect

SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS_LIMIT = 20

# Organisations, places and links are what enrichment looks up; every other
# detected type identifies a person or their accounts.
_SEARCHABLE_TYPES = {"ORGANIZATION", "LOCATION", "URL", "DATE_TIME", "NRP"}

Transport = Callable[[str, dict[str, str], bytes, float], bytes]


class PrivacyBlocked(ValueError):
    def __init__(self, pii_types: set[str]) -> None:
        self.pii_types = sorted(pii_types)
        super().__init__(f"query contains {', '.join(self.pii_types)}; not sent to Tavily")


class TavilyError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    content: str
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise TavilyError(f"Tavily returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TavilyError(f"Tavily unreachable: {exc.reason}") from exc


class TavilyClient:
    def __init__(self, api_key: str | None = None, *, transport: Transport | None = None, timeout: float = 20.0) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("TAVILY_API_KEY", "")
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, *, max_results: int = 5) -> list[WebResult]:
        query = query.strip()
        if not query:
            raise ValueError("empty query")
        blocked = {m.entity_type for m in detect(query)} - _SEARCHABLE_TYPES
        if blocked:
            raise PrivacyBlocked(blocked)
        if not self.api_key:
            raise TavilyError("TAVILY_API_KEY is not set")

        body = json.dumps({"query": query, "max_results": max(1, min(max_results, MAX_RESULTS_LIMIT))}).encode()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        # Logged before sending: the query has left the machine even if the call fails.
        get_logger().log(provider="tavily", model="search", redacted=False, request_preview=query)
        raw = self._transport(SEARCH_URL, headers, body, self._timeout)

        try:
            results = json.loads(raw).get("results", [])
        except (json.JSONDecodeError, AttributeError) as exc:
            raise TavilyError("Tavily returned a response that is not JSON") from exc
        return [
            WebResult(
                title=str(r.get("title", "")),
                url=str(r.get("url", "")),
                content=str(r.get("content", "")),
                score=float(r.get("score") or 0.0),
            )
            for r in results
        ]
