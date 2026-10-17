"""Summarize an explicitly provided development verdicts JSONL file.
Official NVIDIA scoring is done by bench.runner / tools/regrade.py.
"""
import argparse
import json
from pathlib import Path
from eval.metrics import summarize

def main():
    p = argparse.ArgumentParser()
    p.add_argument("verdicts", type=Path, help="Development JSONL with 'correct' and optional 'category' fields")
    args = p.parse_args()
    rows = [json.loads(line) for line in args.verdicts.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(summarize(rows), indent=2))

if __name__ == "__main__":
    main()
