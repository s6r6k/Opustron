"""Calendar event parser (.ics)."""

from datetime import date, datetime
from pathlib import Path
from typing import Any

from icalendar import Calendar

from chronicle.schema import Document, Event, Source


def parse(item: dict[str, Any], *, uri: str = "memory://calendar") -> Event:
    """Parse a calendar record with an ISO-8601 start time."""
    value = item.get("start")
    occurred_at = datetime.fromisoformat(value) if isinstance(value, str) else None
    return Event(
        content=str(item.get("summary", "")),
        source=Source(uri=uri, kind="calendar"),
        occurred_at=occurred_at,
        metadata=dict(item),
    )


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def parse_ics(path: Path) -> list[Document]:
    """One Document per VEVENT. ``doc_date`` is the event's creation/modification date when
    present (when we learned it), else its start; the event start is kept in metadata."""
    cal = Calendar.from_ical(path.read_bytes())
    docs = []
    for i, ev in enumerate(cal.walk("VEVENT")):
        def get(k: str, ev=ev):
            return ev.get(k).dt if ev.get(k) is not None else None
        start, end = _as_date(get("DTSTART")), _as_date(get("DTEND"))
        learned = _as_date(get("DTSTAMP")) or _as_date(get("CREATED")) or start
        summary, desc, loc = (str(ev.get(k, "")) for k in ("SUMMARY", "DESCRIPTION", "LOCATION"))
        text = "\n".join(p for p in (summary, f"Starts: {start}" if start else "", f"Ends: {end}" if end else "",
                                     f"Location: {loc}" if loc else "", desc) if p)
        docs.append(Document(
            doc_id=f"C:{ev.get('UID') or f'{path.stem}#{i}'!s}", text=text, doc_date=learned, kind="calendar",
            path=path.name, metadata={"start": str(start), "end": str(end), "summary": summary},
        ))
    return docs
