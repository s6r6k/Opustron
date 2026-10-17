"""Reversible PII pseudonymisation.

Maps real values → ENTITY_N tokens before any external LLM call,
and restores them on the way back.

  mapping = PseudonymMapping()
  redacted, mapping = pseudonymize(text, mapping)
  # ... LLM call with redacted text ...
  restored = reidentify(llm_response, mapping)
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from .pii_detector import PiiMatch, detect


# ---------------------------------------------------------------------------
# Entity-type → token-prefix mapping
# ---------------------------------------------------------------------------

_PREFIX: dict[str, str] = {
    "PERSON": "PERSON",
    "ORGANIZATION": "ORG",
    "LOCATION": "LOC",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "SSN",
    "CREDIT_CARD": "CARD",
    "IP_ADDRESS": "IP",
    "URL": "URL",
    "NRP": "NRP",
    "DATE_TIME": "DATE",
    "US_DRIVER_LICENSE": "DL",
    "US_PASSPORT": "PASSPORT",
    "US_ITIN": "ITIN",
    "MEDICAL_LICENSE": "MED",
}

_DEFAULT_PREFIX = "PII"


@dataclass
class PseudonymMapping:
    """Thread-safe bidirectional map between real values and ENTITY_N tokens."""

    _forward: dict[str, str] = field(default_factory=dict)   # value  → token
    _reverse: dict[str, str] = field(default_factory=dict)   # token  → value
    _counters: dict[str, int] = field(default_factory=dict)  # prefix → count
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def token_for(self, entity_type: str, value: str) -> str:
        """Return (and cache) the stable token for a given real value."""
        with self._lock:
            if value in self._forward:
                return self._forward[value]
            prefix = _PREFIX.get(entity_type, _DEFAULT_PREFIX)
            n = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = n
            token = f"{prefix}_{n}"
            self._forward[value] = token
            self._reverse[token] = value
            return token

    def original_for(self, token: str) -> str | None:
        with self._lock:
            return self._reverse.get(token)

    def pii_types_seen(self) -> list[str]:
        with self._lock:
            return list({v.rsplit("_", 1)[0] for v in self._forward.values()})


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def pseudonymize(
    text: str,
    mapping: PseudonymMapping | None = None,
    entities: list[PiiMatch] | None = None,
) -> tuple[str, PseudonymMapping]:
    """Replace PII spans with ENTITY_N tokens.

    Returns (redacted_text, mapping). Pass an existing mapping to reuse tokens
    across multiple texts in the same session.
    """
    if mapping is None:
        mapping = PseudonymMapping()

    if entities is None:
        entities = detect(text)

    if not entities:
        return text, mapping

    # Number tokens in reading order, then replace right-to-left to preserve offsets.
    ordered = sorted(entities, key=lambda m: m.start)
    tokens = [mapping.token_for(m.entity_type, m.value) for m in ordered]
    result = list(text)
    for match, token in reversed(list(zip(ordered, tokens))):
        result[match.start : match.end] = list(token)

    return "".join(result), mapping


_TOKEN_RE = re.compile(
    r"\b(?:PERSON|ORG|LOC|EMAIL|PHONE|SSN|CARD|IP|URL|NRP|DATE|DL|PASSPORT|ITIN|MED|PII)_\d+\b"
)


def reidentify(text: str, mapping: PseudonymMapping) -> str:
    """Replace ENTITY_N tokens in LLM response with original values."""

    def replace(m: re.Match) -> str:  # type: ignore[type-arg]
        original = mapping.original_for(m.group())
        return original if original is not None else m.group()

    return _TOKEN_RE.sub(replace, text)
