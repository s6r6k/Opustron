"""Entity resolution: alias table + string similarity (+ optional LLM tie-break)."""

import re
from collections.abc import Callable

from rapidfuzz import fuzz

from chronicle.schema import Claim, Entity

MERGE_THRESHOLD = 92  # confident duplicate
REVIEW_THRESHOLD = 80  # ambiguous band -> LLM tie-break (if provided), else keep separate
_TITLES = re.compile(r"^(mr|mrs|ms|dr|prof)\.?\s+", re.IGNORECASE)


def resolve(entities: list[Entity]) -> list[Entity]:
    """Deduplicate entities by case-insensitive name."""
    unique: dict[str, Entity] = {}
    for entity in entities:
        unique.setdefault(entity.name.casefold(), entity)
    return list(unique.values())


def normalize_name(name: str) -> str:
    name = _TITLES.sub("", name.strip())
    # Strip leading @ (Slack/email handles), replace _ and . with space for fuzzy matching
    name = re.sub(r"^@+", "", name)
    name = re.sub(r"[_.]", " ", name)
    return re.sub(r"[^\w\s-]", "", name).casefold().strip()


class EntityResolver:
    """Maps surface forms to a canonical name, incrementally and deterministically.

    ``tie_break(a, b) -> bool`` is asked only for ambiguous pairs; distinct people who share a
    first name are never merged on the first name alone when two candidates exist.
    """

    def __init__(self, aliases: dict[str, str] | None = None,
                 tie_break: Callable[[str, str], bool] | None = None) -> None:
        self.canonical: dict[str, str] = {}  # normalized surface form -> canonical display name
        self.known: dict[str, str] = {}  # normalized canonical -> display
        self.tie_break = tie_break
        for alias, canon in (aliases or {}).items():
            self.known[normalize_name(canon)] = canon
            self.canonical[normalize_name(alias)] = canon

    def resolve(self, name: str) -> str:
        key = normalize_name(name)
        if not key:
            return name
        if key in self.canonical:
            return self.canonical[key]
        if key in self.known:
            return self.known[key]
        match = self._match(key)
        canon = match or name.strip()
        self.known.setdefault(normalize_name(canon), canon)
        self.canonical[key] = canon
        return canon

    def _match(self, key: str) -> str | None:
        tokens = key.split()
        # first-name-only mention -> unique known full name starting with it
        if len(tokens) == 1:
            cands = [d for k, d in self.known.items() if len(k.split()) > 1 and k.split()[0] == key]
            return cands[0] if len(cands) == 1 else None
        scored = sorted(((fuzz.token_sort_ratio(key, k), k) for k in self.known), reverse=True)
        if not scored:
            return None
        score, best = scored[0]
        if len(best.split()) == 1 and best == tokens[0]:
            return None  # known "Alice", now "Alice Chen": keep distinct unless aliased
        if score >= MERGE_THRESHOLD:
            return self.known[best]
        if score >= REVIEW_THRESHOLD and self.tie_break and self.tie_break(key, best):
            return self.known[best]
        return None

    def resolve_claim(self, claim: Claim) -> Claim:
        subject = self.resolve(claim.subject)
        obj_key = normalize_name(claim.object)
        # Resolve object when it's a known alias OR already in the known canonical table
        obj = self.resolve(claim.object) if (obj_key in self.canonical or obj_key in self.known) else claim.object
        return claim.model_copy(update={"subject": subject, "object": obj})
