"""Roster: extract a canonical person table and alias map from document headers.

Before extraction runs, ``build_roster`` scans every document's metadata to discover
real names and all the surface forms they appear under.  The result feeds both the
entity resolver (so ``@alex`` always maps to *Alex Chen*) and the document renderer
(so ``<@U20094F0C2DD>`` in Slack messages is replaced with the person's name before
the LLM sees the text).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from chronicle.schema import Document

_SLACK_SPEAKER = re.compile(r"^(?:\[[\dTZ:.-]+\]\s+)?(.+?)\s*\(([A-Z0-9]{6,20})\)\s*\[ts=", re.MULTILINE)
_EMAIL_ADDR = re.compile(r"(.+?)\s*\(@?(\w[\w.-]*)\)\s*<([\w.+-]+)@")
_MENTION = re.compile(r"<@([A-Z0-9]{6,20})>")


@dataclass
class Roster:
    """Mapping of every known surface form → canonical display name."""

    # surface form (lowercased) → canonical display name
    aliases: dict[str, str] = field(default_factory=dict)
    # Slack user id (UXXX…) → canonical display name
    slack_ids: dict[str, str] = field(default_factory=dict)
    # canonical display names seen, in discovery order
    people: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ public

    def expand_slack_mention(self, uid: str) -> str:
        """Return the display name for a Slack uid, or ``@<uid>`` as fallback."""
        return self.slack_ids.get(uid, f"@{uid}")

    def render(self, text: str) -> str:
        """Replace every ``<@Uxxx>`` mention in *text* with the person's name."""
        return _MENTION.sub(lambda m: self.expand_slack_mention(m.group(1)), text)

    # ------------------------------------------------------------------ serialisation

    def to_json(self) -> str:
        return json.dumps({"aliases": self.aliases, "slack_ids": self.slack_ids, "people": self.people},
                          indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Roster:
        d = json.loads(text)
        return cls(aliases=d.get("aliases", {}), slack_ids=d.get("slack_ids", {}), people=d.get("people", []))

    # ------------------------------------------------------------------ internal

    def _add(self, display: str, *surface_forms: str) -> None:
        """Register *display* as canonical and bind every surface form to it."""
        if not display:
            return
        if display not in self.people:
            self.people.append(display)
        for form in surface_forms:
            norm = form.strip().lower()
            if norm:
                self.aliases.setdefault(norm, display)

    def _add_slack(self, uid: str, display: str) -> None:
        if uid and display:
            self.slack_ids.setdefault(uid, display)
            self._add(display, display, f"<@{uid}>", uid)

    def _add_email_person(self, display: str, handle: str, local: str) -> None:
        """Register a person from an email header field."""
        self._add(
            display,
            display,
            f"@{handle}",
            handle,
            local,
            local.replace(".", " "),
            local.replace(".", "_"),
            local.replace("-", " "),
            local.replace("-", "_"),
        )

    def _ingest_doc(self, doc: Document) -> None:
        meta = doc.metadata

        if doc.kind in ("email",):
            for field_name in ("from", "to", "cc"):
                val = meta.get(field_name)
                if not val:
                    continue
                items = val if isinstance(val, list) else [val]
                for item in items:
                    for m in _EMAIL_ADDR.finditer(str(item)):
                        self._add_email_person(m.group(1).strip(), m.group(2).strip(), m.group(3).strip())

        elif doc.kind in ("slack", "chat"):
            # Slack docs formatted as ``Name (UID) [ts=...]:`` prefixes
            for m in _SLACK_SPEAKER.finditer(doc.text):
                self._add_slack(m.group(2), m.group(1).strip())
            # channel_name from metadata
            ch = meta.get("channel_name") or meta.get("channel") or ""
            if ch:
                pass  # channels aren't people; skip


def build_roster(docs: Iterable[Document], existing: Roster | None = None) -> Roster:
    """Scan all documents and return a Roster with every person discovered.

    Pass *existing* (loaded from ``roster.json``) to merge in previously found names
    so that part_b runs see names found in part_a.
    """
    roster = existing or Roster()
    for doc in docs:
        roster._ingest_doc(doc)
    return roster


def load_or_build_roster(state: Path, docs: Iterable[Document]) -> Roster:
    """Load ``roster.json`` from *state* if present, then update with *docs* and save."""
    path = state / "roster.json"
    existing = Roster.from_json(path.read_text(encoding="utf-8")) if path.is_file() else None
    roster = build_roster(docs, existing)
    path.write_text(roster.to_json(), encoding="utf-8")
    return roster
