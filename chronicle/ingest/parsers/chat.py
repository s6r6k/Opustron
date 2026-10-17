"""Chat export parsers (Slack JSON, WhatsApp text). Messages are grouped into channel-days."""

import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from chronicle.schema import Document, Event, Source


def parse(message: dict[str, Any], *, uri: str = "memory://chat") -> Event:
    """Parse a chat message into an event."""
    return Event(
        content=str(message.get("content", "")),
        source=Source(uri=uri, kind="chat"),
        metadata=dict(message),
    )


def parse_slack(path: Path, channel: str | None = None) -> list[Document]:
    """Parse a Slack day/channel export (a JSON list of messages) into one Document per day."""
    channel = channel or path.parent.name or path.stem
    by_day: dict[date, list[str]] = defaultdict(list)
    for m in json.loads(path.read_text(encoding="utf-8")):
        if not m.get("text") or "ts" not in m:
            continue
        when = datetime.fromtimestamp(float(m["ts"]), tz=UTC)
        by_day[when.date()].append(f"{m.get('user', 'unknown')} ({when:%H:%M}): {m['text']}")
    return [
        Document(doc_id=f"S:{channel}@{day.isoformat()}", text="\n".join(lines), doc_date=day,
                 kind="slack", path=path.name, metadata={"channel": channel, "message_count": len(lines)})
        for day, lines in sorted(by_day.items())
    ]


_WA_LINE = re.compile(r"^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),? (\d{1,2}:\d{2})(?::\d{2})?(?: ?[APap][Mm])?\]?[ -]+([^:]+): (.*)$")


def parse_whatsapp(path: Path, channel: str | None = None, *, day_first: bool = True) -> list[Document]:
    """Parse a WhatsApp ``.txt`` export. Continuation lines attach to the previous message."""
    channel = channel or path.stem
    by_day: dict[date, list[str]] = defaultdict(list)
    current: tuple[date, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _WA_LINE.match(line)
        if m:
            a, b, y, _t, sender, text = m.groups()
            d, mo = (int(a), int(b)) if day_first else (int(b), int(a))
            year = int(y) + (2000 if len(y) == 2 else 0)
            current = (date(year, mo, d), sender)
            by_day[current[0]].append(f"{sender}: {text}")
        elif current and line.strip():
            by_day[current[0]][-1] += f"\n{line}"
    return [
        Document(doc_id=f"S:{channel}@{day.isoformat()}", text="\n".join(lines), doc_date=day,
                 kind="whatsapp", path=path.name, metadata={"channel": channel, "message_count": len(lines)})
        for day, lines in sorted(by_day.items())
    ]
