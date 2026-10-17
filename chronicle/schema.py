"""Shared domain models used across Chronicle."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


@dataclass(slots=True)
class Source:
    uri: str
    kind: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Entity:
    name: str
    entity_type: str = "unknown"
    entity_id: str = field(default_factory=lambda: str(uuid4()))
    aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Event:
    content: str
    source: Source
    occurred_at: datetime | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    entities: list[Entity] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Document(BaseModel):
    """A parsed source document. ``doc_date`` is the date the document was written,
    never the ingestion date."""

    doc_id: str
    text: str
    doc_date: date | None = None
    kind: str = "markdown"
    part: str | None = None
    path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Claim(BaseModel):
    """One atomic fact extracted from a document (P1 -> P2 contract)."""

    subject: str
    predicate: str
    object: str
    valid_from: date | None = None
    valid_to: date | None = None
    observed_at: date | None = None  # = document date
    doc_id: str
    quote: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
