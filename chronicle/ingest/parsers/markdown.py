"""Markdown parser."""

from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from chronicle.schema import Document, Event, Source


def parse(text: str, *, uri: str = "memory://markdown") -> list[Event]:
    """Convert non-empty Markdown paragraphs into events."""
    return [
        Event(content=paragraph.strip(), source=Source(uri=uri, kind="markdown"))
        for paragraph in text.split("\n\n")
        if paragraph.strip()
    ]


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``---`` YAML frontmatter from the body. Malformed headers yield ``({}, text)``."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                meta = yaml.safe_load("".join(lines[1:i])) or {}
            except yaml.YAMLError:
                return {}, text
            if not isinstance(meta, dict):
                return {}, text
            return meta, "".join(lines[i + 1 :]).lstrip("\n")
    return {}, text


def to_date(value: Any) -> date | None:
    """Coerce a frontmatter value (date, datetime or ISO string) to a ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip()).date()
        except ValueError:
            return None
    return None


def parse_document(path: Path, *, root: Path | None = None, part: str | None = None) -> Document:
    """Parse a Markdown file (note, benchmark email or chat channel-day) into a ``Document``.

    The document date comes from frontmatter ``date``; if absent we fall back to the file's
    mtime and record ``date_source="mtime"`` so downstream can treat it as low confidence.
    """
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    rel = path.relative_to(root).as_posix() if root else path.name
    doc_date = to_date(meta.get("date"))
    metadata = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in meta.items()}
    if doc_date is None:
        doc_date = datetime.fromtimestamp(path.stat().st_mtime).date()
        metadata["date_source"] = "mtime"
    return Document(
        doc_id=str(meta.get("doc_id") or f"M:{rel}"),
        text=body,
        doc_date=doc_date,
        kind=str(meta.get("source") or "markdown"),
        part=part,
        path=rel,
        metadata=metadata,
    )
