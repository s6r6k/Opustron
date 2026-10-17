"""Retrieve P1's persisted claims until P2 exposes persistent claim search."""
import re
from pathlib import Path

from chronicle.ingest.pipeline import CLAIMS_FILE, read_claims

from .models import Evidence, QueryPlan

STOPWORDS = set("a an the is are was were who what which when where why how did does do to in on at for from with of and or by it its this that currently current now".split())

def terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}

def retrieve(plan: QueryPlan, state: Path, top_k: int = 8) -> list[Evidence]:
    claims_path = state / CLAIMS_FILE
    if not claims_path.is_file():
        raise FileNotFoundError(
            f"Ingest corpus with python -m chronicle.ingest before answering: {claims_path}. "
            "Legacy chronicle_adapter.sqlite3 state must be re-ingested."
        )
    query_terms = terms(plan.question)
    results: dict[str, Evidence] = {}
    for claim in read_claims(claims_path):
        overlap = len(query_terms & terms(
            f"{claim.subject} {claim.predicate} {claim.object} {claim.quote}"
        ))
        if overlap:
            # Retain source quotes and validity fields, including closing claims.
            # P2 will supply supersession/as-of semantics; do not infer them here.
            content = claim.model_dump_json()
            observed = claim.observed_at.isoformat() if claim.observed_at else ""
            if claim.doc_id in results:
                evidence = results[claim.doc_id]
                evidence.text += "\n" + content
                evidence.date = max(evidence.date, observed)
                evidence.score = max(evidence.score, float(overlap))
            else:
                results[claim.doc_id] = Evidence(
                    doc_id=claim.doc_id, text=content, date=observed, score=float(overlap),
                )
    return sorted(results.values(), key=lambda e: (e.score, e.date), reverse=True)[:top_k]
