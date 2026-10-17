"""NVIDIA mnemo answer adapter: JSONL stdin -> JSONL stdout."""
import argparse
import json
import sys
from pathlib import Path

# Works when called from the benchmark root or the Chronicle repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from chronicle.reason.pipeline import answer_question

def run(state: Path, instream=sys.stdin, outstream=sys.stdout):
    for line_number, line in enumerate(instream, start=1):
        if not line.strip():
            continue
        try:
            question = json.loads(line)
        except json.JSONDecodeError:
            print(f"[chronicle] skipping line {line_number}: invalid JSON", file=sys.stderr)
            continue
        if (not isinstance(question, dict)
                or not isinstance(question.get("id"), str)
                or not isinstance(question.get("question"), str)):
            print(
                f"[chronicle] skipping line {line_number}: expected an object with string 'id' and 'question'",
                file=sys.stderr,
            )
            continue
        result = answer_question(question["question"], state)
        print(json.dumps({"id": question["id"], "answer": result.answer, "source_ids": result.source_ids}), file=outstream, flush=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--state", type=Path, required=True)
    args = p.parse_args()
    run(args.state)

if __name__ == "__main__":
    main()
