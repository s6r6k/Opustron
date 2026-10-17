"""Ingestion caches: in-memory event cache and an on-disk LLM response cache."""

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from chronicle.schema import Event


class IngestCache:
    def __init__(self) -> None:
        self._events: dict[str, Event] = {}

    def get(self, key: str) -> Event | None:
        return self._events.get(key)

    def put(self, key: str, event: Event) -> None:
        self._events[key] = event


def cache_key(*parts: str) -> str:
    """Stable key over model, prompt version and input text."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class DiskCache:
    """JSON-file cache keyed by prompt hash so re-runs cost $0. Tracks hits/misses."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                value = None  # corrupt entry: treat as a miss
            if value is not None:
                with self._lock:
                    self.hits += 1
                return value
        with self._lock:
            self.misses += 1
        return None

    def put(self, key: str, value: Any) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value), encoding="utf-8")
        tmp.replace(path)  # atomic: a crash never leaves a half-written entry
