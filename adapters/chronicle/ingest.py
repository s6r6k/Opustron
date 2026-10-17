"""Compatibility entry point for P1 ingestion; no separate adapter store."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from chronicle.ingest.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
