# P1 claim extraction: problem report (for solution design)

## 1. Goal and constraints
Chronicle is a personal-agent memory built for the NVIDIA Agent Memory Benchmark (Nebius x NVIDIA hackathon). P1 (`chronicle/ingest`) turns documents into **atomic, source-dated claims** that P2 stores bi-temporally (valid interval + record time, supersession on same subject+predicate) and P3 queries to answer questions.

Claim = `subject, predicate, object, valid_from, valid_to, observed_at (= document date), doc_id, quote, confidence`.

Benchmark facts that drive the design:
- Corpus A: 425 documents (200 emails, 225 Slack channel-days), 16 Apr to 27 May 2026, ingested in two halves (part_a, then part_b); **part_b overrides some part_a facts**. 186 questions, graded deterministically (no LLM judge), answers must be short, current-state-only, cite doc ids, and abstain when the corpus doesn't say.
- Question categories we must win: single_hop, multi_source (73), disambiguation (15), abstention (13), freshness (12), citation (12), plus hard set: as_of / point-in-time (6, NVIDIA scored only 66.7%), chain_freshness (value changed twice), set_difference, constraint, attribution (who proposed vs who did), ordering.
- Hard rules: every timestamp must come from the source document's date (never ingestion time or "today"); never look at gold answers while developing (we have not fetched `questions/` or `answers.jsonl`, so we cannot score accuracy ourselves; P3's eval does that); corpus B is the held-out set.
- Model: Nemotron 3.5 Lightning on Nebius Token Factory (cheap, dev); Nemotron 3 Ultra for final runs. Credits are limited (~$25 each).

## 2. What exists now (working)
Pipeline: parse (benchmark/markdown/email/chat/ics) -> LLM extraction (one call per document, JSON claims) -> verify quote is in the document -> resolve date expressions against the document date (rules + dateparser) -> entity resolution (alias + fuzzy) -> `claims.jsonl`. Idempotent, disk-cached, parallel (6 workers). 127 unit tests pass. ("next Friday" = Friday of the following Mon-Sun week.)

Full run on corpus A (real data), Lightning with thinking disabled (thinking on was ~10x slower and truncated answers, which silently produced empty claim lists; fixed):
- 425/425 documents processed, 0 failures, ~8 minutes, ~367k input + ~177k output tokens (well under $1).
- 2,001 claims kept (964 part_a, 1,037 part_b); 69 more dropped because the quote wasn't found verbatim (after ignoring markdown formatting).
- 370 of 425 documents yielded at least one claim (55 yielded none, not yet inspected).
- All claims carry the document date as `observed_at`.

## 3. The problem: claims exist but are the wrong kind for the benchmark
Measured on the full run:

| Signal | Value | Why it matters |
|---|---|---|
| `related_to` predicate | 689 / 2,001 (34%) | Vague "A related_to B" claims carry no answerable meaning and pollute retrieval. |
| Predicates outside the controlled list | ~201 (e.g. `invitee`, `organized_by`) | Supersession in P2 keys on (subject, predicate); free-form predicates never collide, so changes are not detected. |
| `owns` | 9 | Ownership/role changes are the core of freshness, chain_freshness and as_of questions. Almost none extracted. |
| Claims with `valid_to` (a fact ending) | 16 / 2,001 | A tiny share, so the store has almost no closed intervals to answer "what was true on date X". |
| Distinct subjects | 963; "Alex Chen" alone is 282 claims | Many subjects are likely surface-form variants or non-entities (e.g. `WaveWiki.run`, `chat_items`). Entity resolution on real data is unverified. |
| Slack user ids like `<@U20094F0C2DD>` in message text | present | Not mapped to names, so "who did X" can fail or fragment entities. |

Observed on a 20-document sample: much of the volume is low-value (GitLab/CI notification emails producing code-level or housekeeping claims, e.g. "merge request !284 related_to alex_chen", "Assignees: @alex"), while the sparse, high-value statements (a handover, a decision, a date change, a proposal vs who did it) are not reliably captured as paired new-state + old-state-ending claims. A prompt rule for takeovers (emit a new `owns` claim and an end-dated claim for the old owner) worked on a hand-made fixture; its recall on the real corpus has **not** been measured.

## 4. Root-cause hypotheses (not yet verified)
1. The extraction prompt asks for "all atomic claims" per document, so the model emits many easy structural facts and under-weights rare, important state changes.
2. A closed predicate vocabulary is only advisory; the model can invent predicates and fall back on `related_to`.
3. Each document is extracted in isolation. A change in part_b ("Dana takes over payments") is only linked to the part_a state if both use the same canonical subject/predicate/object; there is no step that looks at existing memory when extracting, so end-dating the old fact relies entirely on the model writing the old owner in the same document.
4. No evaluation signal: without gold answers we cannot tell which extraction variant is better, only inspect claims by eye.
5. Entity canonicalisation is string-based; Slack ids and name variants (Alex / Alex Chen / @alex / alex_chen) are likely fragmenting subjects.

## 5. Questions for the solution
1. How should extraction be restructured to prioritise state changes (ownership, role, status, decisions, deadlines) over structural noise, without losing citation-level detail that single_hop/citation questions need (a detail only one document carries)? Options: two-pass (cheap triage then focused extraction), per-document-type prompts (automated notification vs human thread), a constrained predicate schema enforced via JSON-schema enum, retrieval-augmented extraction that shows the model existing claims about the same entities.
2. How should supersession be made robust across part_a to part_b when predicates/entities drift? (Canonical predicate set plus entity linking before write, vs. letting P2 or P3 reconcile with an LLM at query time.)
3. What is the right division between P1 claims and raw-text retrieval for questions the claims don't cover (the plan's hybrid search)? Is it acceptable that many documents produce no claims if raw text remains searchable?
4. How do we evaluate extraction quality without touching gold answers? E.g. a small hand-labelled synthetic set with known ownership changes, held-out corpus B for final checking only, automatic checks (quote faithfulness, date-in-range, supersession pairs found).
5. Slack id mapping and entity resolution on real data: best cheap approach (parse the id-to-name mapping already present in message headers, alias tables built from email From/To fields, embedding + LLM tie-break only on ambiguous pairs).
6. Budget: each full corpus-A pass costs well under $1 on Lightning, so iterative prompt experiments are affordable; Ultra is reserved for final runs.

## 6. Reproduce
```
# corpus is in data/benchmark/corpus_a (gitignored); key in .env
python -m chronicle.ingest --corpus data/benchmark/corpus_a/part_a --state data/benchmark/state_full --part a
python -m chronicle.ingest --corpus data/benchmark/corpus_a/part_b --state data/benchmark/state_full --part b
```
Key files: `chronicle/ingest/extractor.py` (prompt `SYSTEM_PROMPT`, `PREDICATES`, quote check), `pipeline.py`, `entity_resolver.py`, `temporal_normalizer.py`, `llm.py`. Output: `data/benchmark/state_full/claims.jsonl`.
