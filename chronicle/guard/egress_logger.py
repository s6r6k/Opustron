"""Structured egress audit log.

Every outbound LLM / Tavily call is written as a JSONL line to
~/.chronicle/egress.log so the Memory Time Machine UI can show a live
feed of what left the machine and whether it was redacted.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_LOG_PATH = Path.home() / ".chronicle" / "egress.log"


class EgressLogger:
    def __init__(self, log_path: Path | None = None) -> None:
        self._path = log_path or _DEFAULT_LOG_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        redacted: bool,
        pii_types: list[str] | None = None,
        request_preview: str | None = None,
    ) -> None:
        """Append one structured record to the egress log."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "redacted": redacted,
            "pii_types": pii_types or [],
            "request_preview": (request_preview or "")[:200],
        }
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")

    def tail(self, n: int = 50) -> list[dict]:  # type: ignore[type-arg]
        """Return the last n records from the log, newest first."""
        if not self._path.exists():
            return []
        with self._lock:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in reversed(lines[-n:]):
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records


# ---------------------------------------------------------------------------
# Module-level singleton (used by LLMClient)
# ---------------------------------------------------------------------------

_default_logger: EgressLogger | None = None


def get_logger(log_path: Path | None = None) -> EgressLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = EgressLogger(log_path)
    return _default_logger
