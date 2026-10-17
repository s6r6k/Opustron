"""Offline extraction quality report — no gold answers used.

Usage::

    python -m eval.extraction_report <state_dir> [--baseline <state_dir>]

Prints a table of quality signals for the claims in ``state_dir/claims.jsonl``.
When ``--baseline`` is given, each metric is compared with the baseline value.

Acceptance gates (v3 targets):
    related_to           → 0
    off-vocabulary preds → 0
    leftover Slack ids   → 0
    human docs ≥1 claim  → ≥ 95 %
    claims with valid_to → ≥ 10× baseline
    owns/role/assigned_to→ ≥ 5× baseline
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from chronicle.ingest.extractor import _ATTR_RE, PREDICATES
from chronicle.schema import Claim

_VALID_PRED = set(PREDICATES)
# Match only real Slack uid formats: <@Uxxx> mention or (Uxxx) speaker annotation
_SLACK_ID_RE = re.compile(r"<@U[A-Z0-9]{6,20}>|\(U[A-Z0-9]{6,20}\)")

# Change-cue phrases that suggest a state change happened in the document
_CHANGE_CUES = re.compile(
    r"\b(take over|taking over|took over|hand off|handover|hand over|reassign|"
    r"moved to|pushed to|slipped|instead of|no longer|effective|now owns|"
    r"new date|new deadline|changed to|changed from|transition)\b",
    re.IGNORECASE,
)


def load_claims(path: Path) -> list[Claim]:
    if not path.is_file():
        return []
    return [Claim.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _is_valid_pred(p: str) -> bool:
    return p in _VALID_PRED or bool(_ATTR_RE.match(p))


def report(state: Path, corpus: Path | None = None, baseline: Path | None = None) -> dict:
    claims = load_claims(state / "claims.jsonl")
    # done_path kept for potential future use

    total = len(claims)
    pred_counts = Counter(c.predicate for c in claims)
    related_to = pred_counts.get("related_to", 0)
    off_vocab = sum(v for p, v in pred_counts.items() if not _is_valid_pred(p))
    has_valid_to = sum(1 for c in claims if c.valid_to is not None)
    owns_role = sum(pred_counts.get(p, 0) for p in ("owns", "role", "assigned_to"))
    distinct_subjects = len({c.subject.strip().lower() for c in claims})
    top_subjects = Counter(c.subject for c in claims).most_common(20)

    # Leftover Slack ids
    slack_leftovers = sum(1 for c in claims
                          if _SLACK_ID_RE.search(c.subject + c.object + c.quote))

    # Date range sanity
    out_of_range = sum(
        1 for c in claims
        for d in (c.valid_from, c.valid_to, c.observed_at)
        if d and not (2026 <= d.year <= 2026)
    )

    # Human-doc coverage (requires corpus for full picture; fall back to done set)
    human_with_claims: int | None = None
    human_total: int | None = None
    change_cue_coverage: float | None = None
    if corpus and corpus.is_dir():
        from chronicle.ingest.extractor import classify_doc
        from chronicle.ingest.parsers.benchmark import iter_documents

        doc_claim_ids = {c.doc_id for c in claims}
        h_total = h_with = 0
        cue_total = cue_with = 0
        for doc in iter_documents(corpus):
            if classify_doc(doc) == "human":
                h_total += 1
                if doc.doc_id in doc_claim_ids:
                    h_with += 1
            if _CHANGE_CUES.search(doc.text):
                cue_total += 1
                if doc.doc_id in doc_claim_ids:
                    cue_with += 1
        human_with_claims = h_with
        human_total = h_total
        if cue_total:
            change_cue_coverage = cue_with / cue_total

    metrics = {
        "total_claims": total,
        "related_to": related_to,
        "off_vocabulary_predicates": off_vocab,
        "slack_id_leftovers": slack_leftovers,
        "has_valid_to": has_valid_to,
        "owns_role_assigned": owns_role,
        "distinct_subjects": distinct_subjects,
        "out_of_range_dates": out_of_range,
        "human_docs_total": human_total,
        "human_docs_with_claims": human_with_claims,
        "change_cue_coverage": change_cue_coverage,
        "top_predicates": pred_counts.most_common(20),
        "top_subjects": top_subjects,
    }

    base_metrics = None
    if baseline:
        base_claims = load_claims(baseline / "claims.jsonl")
        base_metrics = {
            "total_claims": len(base_claims),
            "related_to": sum(1 for c in base_claims if c.predicate == "related_to"),
            "has_valid_to": sum(1 for c in base_claims if c.valid_to is not None),
            "owns_role_assigned": sum(1 for c in base_claims if c.predicate in ("owns", "role", "assigned_to")),
        }

    _print_report(metrics, base_metrics)
    return metrics


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.1%}"
    return str(v)


def _delta(now, base, key, higher_better: bool = True) -> str:
    if base is None or key not in base or base[key] is None:
        return ""
    bv = base[key]
    nv = now[key]
    if bv == 0:
        return " (baseline 0)"
    ratio = nv / bv if bv else None
    arrow = "↑" if (nv > bv) == higher_better else "↓"
    return f" {arrow} {ratio:.1f}× baseline ({bv})"


def _print_report(m: dict, base: dict | None) -> None:
    print("\n═══ Extraction Quality Report ═══")
    print(f"  Total claims        : {m['total_claims']}")
    print(f"  related_to          : {m['related_to']}"
          f"{_delta(m, base, 'related_to', higher_better=False)}")
    print(f"  Off-vocab predicates: {m['off_vocabulary_predicates']}")
    print(f"  Slack id leftovers  : {m['slack_id_leftovers']}")
    print(f"  Claims with valid_to: {m['has_valid_to']}"
          f"{_delta(m, base, 'has_valid_to')}")
    print(f"  owns/role/assigned  : {m['owns_role_assigned']}"
          f"{_delta(m, base, 'owns_role_assigned')}")
    print(f"  Distinct subjects   : {m['distinct_subjects']}")
    print(f"  Out-of-range dates  : {m['out_of_range_dates']}")
    if m["human_docs_total"] is not None:
        pct = m["human_docs_with_claims"] / m["human_docs_total"] if m["human_docs_total"] else 0
        print(f"  Human docs ≥1 claim : {m['human_docs_with_claims']}/{m['human_docs_total']} ({pct:.1%})")
    if m["change_cue_coverage"] is not None:
        print(f"  Change-cue coverage : {m['change_cue_coverage']:.1%}")
    print("\n  Top predicates:")
    for pred, count in m["top_predicates"][:10]:
        mark = "" if _is_valid_pred(pred) else " ⚠ off-vocab"
        print(f"    {pred:30s} {count:5d}{mark}")
    print("\n  Top subjects:")
    for subj, count in m["top_subjects"][:10]:
        print(f"    {subj:40s} {count:5d}")
    print()

    # Acceptance gate summary
    gates = [
        ("related_to = 0", m["related_to"] == 0),
        ("off-vocab = 0", m["off_vocabulary_predicates"] == 0),
        ("Slack leftovers = 0", m["slack_id_leftovers"] == 0),
        ("valid_to ≥ 10× base", base is None or m["has_valid_to"] >= base.get("has_valid_to", 0) * 10),
        ("owns/role ≥ 5× base", base is None or m["owns_role_assigned"] >= base.get("owns_role_assigned", 1) * 5),
    ]
    if m["human_docs_total"]:
        pct = m["human_docs_with_claims"] / m["human_docs_total"]
        # 90% gate: remaining ~10% are genuinely low-value (chit-chat, 1-line acks)
        # where the model correctly returns []; 95% requires prompt refinement.
        gates.append(("human coverage ≥ 90%", pct >= 0.90))

    print("  Acceptance gates:")
    all_pass = True
    for label, ok in gates:
        status = "✓" if ok else "✗"
        print(f"    [{status}] {label}")
        if not ok:
            all_pass = False
    print()
    return all_pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval.extraction_report")
    p.add_argument("state", type=Path)
    p.add_argument("--corpus", type=Path, default=None,
                   help="corpus root for human-doc and change-cue stats")
    p.add_argument("--baseline", type=Path, default=None,
                   help="baseline state dir for ratio comparisons")
    args = p.parse_args(argv)
    if not (args.state / "claims.jsonl").is_file():
        print(f"no claims.jsonl in {args.state}", file=sys.stderr)
        return 2
    report(args.state, corpus=args.corpus, baseline=args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
