"""NVIDIA benchmark input parser."""

import json
from collections.abc import Iterator
from pathlib import Path

from chronicle.schema import Document, Event, Source

from .markdown import parse_document, to_date


def parse(record: dict, *, uri: str = "memory://benchmark") -> Event:
    """Parse a benchmark record while retaining its original fields."""
    return Event(
        content=str(record.get("text", record.get("question", ""))),
        source=Source(uri=uri, kind="benchmark"),
        metadata=dict(record),
    )


def part_dirs(corpus: Path) -> list[tuple[str, Path]]:
    """Return ``[(part_name, dir)]`` with ``part_a`` before ``part_b``.

    ``corpus`` may be a single part directory (the adapter passes ``{corpus}`` per half),
    a ``corpus/`` directory containing ``part_*`` children, or a plain directory of documents.
    """
    children = sorted(p for p in corpus.iterdir() if p.is_dir() and p.name.startswith("part_"))
    if children:
        return [(p.name.removeprefix("part_"), p) for p in children]
    name = corpus.name.removeprefix("part_") if corpus.name.startswith("part_") else None
    return [(name, corpus)]  # type: ignore[list-item]


def _load_manifest(corpus: Path) -> dict[str, dict]:
    """Index manifest rows by file name. Looks in ``corpus`` and its parent."""
    for base in (corpus, corpus.parent):
        manifest = base / "manifest.jsonl"
        if manifest.is_file():
            rows = (json.loads(line) for line in manifest.read_text().splitlines() if line.strip())
            return {Path(r["path"]).name: r for r in rows if r.get("path")}
    return {}


def iter_documents(corpus: Path) -> Iterator[Document]:
    """Yield every document under ``corpus`` (part_a before part_b), recursively.

    Sub-directory names are never hardcoded (corpus A uses ``slack/``, corpus B ``chat/``).
    Frontmatter is authoritative; ``manifest.jsonl`` only fills a missing doc_id or date.
    """
    manifest = _load_manifest(corpus)
    for part, directory in part_dirs(corpus):
        for path in sorted(directory.rglob("*.md")):
            doc = parse_document(path, root=directory, part=part)
            row = manifest.get(path.name)
            if row and doc.metadata.get("date_source") == "mtime" and row.get("timestamp"):
                doc.doc_date = to_date(row["timestamp"]) or doc.doc_date
                doc.metadata.pop("date_source", None)
            if row and doc.doc_id.startswith("M:") and row.get("doc_id"):
                doc.doc_id = row["doc_id"]
            yield doc
