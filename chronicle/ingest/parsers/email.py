"""Email parser (.eml and mbox)."""

import mailbox
from datetime import date
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from chronicle.schema import Document, Event, Source


def parse(message: dict[str, Any], *, uri: str = "memory://email") -> Event:
    """Parse a normalized email record."""
    subject = str(message.get("subject", "")).strip()
    body = str(message.get("body", "")).strip()
    content = f"{subject}\n\n{body}".strip()
    return Event(content=content, source=Source(uri=uri, kind="email"), metadata=dict(message))


def _body(msg: Message) -> str:
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
    return (part.get_content() if part is not None else "").strip()


def _to_document(msg: Message, fallback_id: str, path: str | None) -> Document:
    doc_date: date | None = None
    if msg["Date"]:
        try:
            doc_date = parsedate_to_datetime(str(msg["Date"])).date()
        except (TypeError, ValueError):
            doc_date = None
    subject = str(msg["Subject"] or "").strip()
    return Document(
        doc_id=str(msg["Message-ID"] or fallback_id).strip("<>"),
        text=f"{subject}\n\n{_body(msg)}".strip(),
        doc_date=doc_date,
        kind="email",
        path=path,
        metadata={"from": str(msg["From"] or ""), "to": str(msg["To"] or ""), "subject": subject},
    )


def parse_eml(path: Path) -> Document:
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    return _to_document(msg, f"eml:{path.name}", path.name)


def parse_mbox(path: Path) -> list[Document]:
    box = mailbox.mbox(str(path), factory=lambda f: BytesParser(policy=policy.default).parse(f))
    return [_to_document(m, f"mbox:{path.name}#{i}", path.name) for i, m in enumerate(box)]
