"""Deterministic supersession: emit closing claims when a stateful fact changes.

When a new open claim (``valid_to is None``) overwrites an older open claim on the
same *functional key*, we emit a closing claim: the old subject/predicate/object with
``valid_to`` set to the new fact's effective start date.

Functional keys by predicate
-----------------------------
``owns``, ``assigned_to``       → (object, predicate)   — one owner per thing
``status``, ``deadline``,
``scheduled_for``, ``role``,
``reports_to``, ``located_in``, ``attr:*``
                                → (subject, predicate)   — one value per subject/predicate

Multi-valued predicates (``works_on``, ``member_of``, ``proposed``, ``decided``,
``completed``, ``requested``, ``blocked_by``) never auto-close.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from chronicle.schema import Claim

_OWNER_PREDICATES = {"owns", "assigned_to"}
_SCALAR_PREDICATES = {"status", "deadline", "scheduled_for", "role", "reports_to", "located_in"}
_ATTR_RE = re.compile(r"^attr:[a-z0-9_]+$")


def _functional_key(claim: Claim) -> tuple[str, str] | None:
    """Return the supersession key for a stateful claim, or None for multi-valued ones."""
    pred = claim.predicate
    if pred in _OWNER_PREDICATES:
        return (claim.object.strip().lower(), pred)
    if pred in _SCALAR_PREDICATES or _ATTR_RE.match(pred):
        return (claim.subject.strip().lower(), pred)
    return None


def _is_open(claim: Claim) -> bool:
    """True when the claim has no end date (current / ongoing fact)."""
    return claim.valid_to is None


def _effective_start(claim: Claim) -> date | None:
    """Best date to use as the closing valid_to for the old fact."""
    return claim.valid_from or claim.observed_at


class ReconcileIndex:
    """Running index of open stateful claims, keyed by functional key.

    Seed it with ``extend(existing_claims)`` before processing new documents
    so that part_b runs can close part_a facts.
    """

    def __init__(self) -> None:
        # functional_key -> the currently-open Claim
        self._open: dict[tuple[str, str], Claim] = {}

    def extend(self, claims: Iterable[Claim]) -> None:
        """Index a batch of already-stored claims (e.g. from a previous run)."""
        for c in claims:
            key = _functional_key(c)
            if key is None:
                continue
            if _is_open(c):
                self._open[key] = c
            else:
                # A closed claim voids the open slot for that key
                self._open.pop(key, None)

    def reconcile(self, new_claims: list[Claim]) -> list[Claim]:
        """Return any auto-generated closing claims for *new_claims* and update the index.

        For each new open claim whose functional key already has a different open
        entry, we emit a closing claim for the old entry (if one isn't already in
        *new_claims*).  We then update the index.
        """
        closings: list[Claim] = []
        # Build a set of (subj, pred, obj) already closed within this batch to
        # avoid duplicating closings the LLM already emitted.
        llm_closed: set[tuple[str, str, str]] = {
            (c.subject.strip().lower(), c.predicate, c.object.strip().lower())
            for c in new_claims
            if not _is_open(c)
        }

        for c in new_claims:
            key = _functional_key(c)
            if key is None or not _is_open(c):
                # Update index for closing claims the LLM emitted
                if key is not None and not _is_open(c):
                    self._open.pop(key, None)
                continue

            old = self._open.get(key)
            if old is None:
                self._open[key] = c
                continue

            # Same value → idempotent, just refresh the pointer.
            # For deadline/scheduled_for the date lives in valid_from, so include it.
            same_subject = old.subject.strip().lower() == c.subject.strip().lower()
            same_object = old.object.strip().lower() == c.object.strip().lower()
            same_date = old.valid_from == c.valid_from
            if same_subject and same_object and (same_date or old.predicate not in ("deadline", "scheduled_for")):
                self._open[key] = c
                continue

            # Different value → old fact is superseded
            close_key = (old.subject.strip().lower(), old.predicate, old.object.strip().lower())
            if close_key not in llm_closed:
                closing = old.model_copy(update={
                    "valid_to": _effective_start(c),
                    "doc_id": c.doc_id,
                    "observed_at": c.observed_at,
                    "quote": c.quote,
                    "confidence": min(old.confidence, c.confidence),
                })
                closings.append(closing)

            self._open[key] = c

        return closings
