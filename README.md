# Chronicle

A personal AI agent whose memory keeps up. Built for the Nebius x NVIDIA Global
AI Hackathon.

Chronicle's memory is **bi-temporal**: every fact records when it was true
(`valid_from` / `valid_to`) and when Chronicle learned it. Facts are never
deleted. When Bob takes over the payments service from Alice, Alice's fact is
closed rather than overwritten, so "who owned payments on 3 May?" still has the
right answer. Personal data is pseudonymised before any call leaves the machine.

| Piece | What it does |
|---|---|
| Ingest (P1) | Parses email, chat, calendar and markdown into events and facts |
| Memory (P2) | Bi-temporal store with `as_of()` queries |
| Reason (P3) | Plans, retrieves and answers with citations; abstains when unsure |
| Guard (P4) | PII detection, pseudonymisation, the shared LLM client, egress log |
| UI (P4) | Memory Time Machine: drag a date slider and watch facts change |
| Deploy (P4) | Hermes Agent plugin, OpenShell egress lockdown, one-command install |

## Quick start

Needs Python 3.10+, [uv](https://docs.astral.sh/uv/) and Node 18+.

```bash
git clone https://github.com/Opustron66/Opustron.git
cd Opustron
uv sync --extra dev
cp .env.example .env        # then fill in NEBIUS_API_KEY
uv run pytest
```

Chronicle reads keys from environment variables and does not load `.env` by
itself yet, so export it in your shell before running anything that calls a
model:

```bash
set -a; source .env; set +a
```

| Variable | Used for |
|---|---|
| `NEBIUS_API_KEY` | Nebius Token Factory (all model calls) |
| `NEBIUS_BASE_URL` | Defaults to `https://api.tokenfactory.nebius.com/v1/` |
| `CHRONICLE_MODEL` | Defaults to the cheap dev model; use the large model only for official benchmark runs |
| `CHRONICLE_MAX_TOKENS` | Default completion budget for `chronicle.guard.llm` (1024). Reasoning models need ~8192 |
| `TAVILY_API_KEY` | Web enrichment |
| `CHRONICLE_REDACT_RECALL` | Hermes plugin: `0` stops masking emails/phones/IDs in recalled memory |

## Calling a model: always use `chronicle.guard.llm`

Every teammate calls models through one client. Never import `openai`
directly.

CI enforces this: `tests/guard/test_egress_boundary.py` fails if code outside
`chronicle/guard/` imports `openai`, `requests`, `httpx`, `aiohttp`,
`urllib.request` or `http.client`, or hard-codes the Token Factory / Tavily URLs.
The only exception is the Tavily client, which has its own PII gate. The sandbox
policy can't catch this, because it sees one Python process.

```python
from chronicle.guard import llm

text = llm.complete([{"role": "user", "content": "Summarise Alice's email"}])
data = llm.complete(messages, schema={"type": "object", "properties": {...}})  # returns a dict
raw = llm.complete(messages, schema={"name": "claims", "schema": {...}})      # returns the reply text
```

Pass a bare JSON Schema to get a parsed dict back. The parser tolerates
reasoning-model noise (`<think>` blocks, code fences, a draft before the final
answer) and takes the last complete JSON value; it raises `ValueError` if the
reply has none. The same parser is available as
`chronicle.guard.llm_client.parse_json_reply`. Pass an OpenAI `json_schema`
envelope (`{"name": ..., "schema": ...}`) to get the raw reply text and parse
it yourself.
If the endpoint rejects `response_format`, the client retries without it and
stops sending it. For your own settings, build a client:
`LLMClient(default_model=..., max_tokens=8192, timeout=180)`.

What it does for you:

- **Pseudonymises** names, emails, phone numbers and other PII (`Alice Tan` →
  `PERSON_1`) before the request leaves the machine, and restores them in the
  reply.
- **Caches** responses in `~/.chronicle/llm_cache/`, so reruns cost nothing.
- **Logs** every outbound call (model, tokens, which PII types were redacted,
  a redacted preview) to `~/.chronicle/egress.log`. The UI shows this log.

Ingestion uses this client too, so corpus text is pseudonymised before it
reaches Nebius and quotes come back with the real values restored:

```bash
python -m chronicle.ingest --corpus DIR --state DIR [--model ID] [--timeout 180] [--max-tokens 8192]
```

What gets detected:

| Masked | How |
|---|---|
| Emails, phones, SSNs, cards, IPs, URLs | Regex, always on |
| People, organisations, places | Presidio + spaCy `en_core_web_sm`, installed by `uv sync` |
| **Not masked: dates and times** | Deliberately. Chronicle reasons about when facts were true; a model shown `DATE_1` can't order them |

The first call takes ~15s while spaCy loads. If the model can't load, a warning
says `Name detection is OFF` and only the regex tier runs. Check with
`uv run python -c "from chronicle.guard.pii_detector import ner_available; print(ner_available())"`.
The small model misses some lone first names ("Priya") and sometimes flags
non-names ("Nebius AI" as a person).

## Web enrichment (Tavily)

```python
from chronicle.integrations.tavily import TavilyClient, PrivacyBlocked

results = TavilyClient().search("Nebius Token Factory pricing", max_results=5)
```

Needs `TAVILY_API_KEY`. A search query can't be pseudonymised (nobody can search
for `PERSON_1`), so a query that identifies a person is refused instead:
emails, phone numbers, IDs and people's names raise `PrivacyBlocked` and
nothing is sent. Organisations, places and links are
allowed. Every query that is sent goes to the egress log as provider `tavily`.

## P3: benchmark adapter and ingestion handoff

The benchmark adapter now runs P1's `python -m chronicle.ingest`. It uses the
same extraction, entity resolution, incremental ingestion and `Claim` schema
as normal ingestion. P3 retrieves evidence from P1's `state/claims.jsonl`,
retaining source document IDs, verbatim quotes, observation dates and validity
fields. There is no separate raw-document SQLite ingestion path.

```powershell
uv run python -m chronicle.ingest --corpus tests/fixtures/corpus/part_a --state .tmp/chronicle
uv run python -m chronicle.ingest --corpus tests/fixtures/corpus/part_b --state .tmp/chronicle
'{"id":"q1","question":"Who owns payments?"}' | uv run python adapters/chronicle/answer.py --state .tmp/chronicle
uv run pytest tests/reason tests/ingest tests/guard
```

Set `NEBIUS_API_KEY` and `CHRONICLE_MODEL` before starting either process.
Extraction and answering both use the shared privacy guard. For reasoning
models, set `CHRONICLE_MAX_TOKENS` to a sufficient answer budget (for example,
8192); P1's CLI defaults to 8192 for extraction. The legacy adapter ingest
script forwards to P1's CLI for existing callers, including its exit status.
Existing `chronicle_adapter.sqlite3` state must be re-ingested into a fresh
state directory. It is never used as a fallback. Malformed question records
are skipped with a line-number diagnostic on stderr; stdout stays JSONL.

### Proposed P1/P2/P3 handoff (agreement pending)

P1 ingestion is shared now. P2 currently exposes only an in-memory event store,
so this baseline reads P1's persisted claims directly. The proposed next
handoff is before a full-system benchmark run, once P2 provides persistent
claim ingestion and search that preserve `Claim` provenance, validity and
observation dates across separate ingest/answer processes. Sara/P1 and P2
still need to confirm the interface and timing; no agreement is claimed here.

- P1 owns extraction and the shared `Claim` contract.
- P2 owns durable claim storage, supersession and temporal search.
- P3 will switch retrieval to P2's API when it lands, with tests for A/B
  ingestion, restart persistence, citations and as-of queries. Ingestion will
  continue to use P1's entry point.

Current retrieval ranks claims by keyword overlap. It does not resolve
supersession or guarantee correct as-of answers; temporal integration,
live-provider behavior, official benchmark scores and final ablations are not
verified by the unit tests. Do not compare legacy raw-document runs with
claim-based runs as if they used identical ingestion.

Update `adapters/chronicle/adapter.json`'s `model` to the actual model for an
official run. Launch NVIDIA's `python -m bench.runner --adapter
adapters/chronicle` from its benchmark root with Chronicle importable. If the
runner supplies an accounting proxy, configure the guard's `NEBIUS_BASE_URL`
to that proxy and verify accounting before reporting results. The adapter no
longer reads `OPENAI_BASE_URL`, `OPENAI_API_KEY` or `MNEMO_MODEL`. A proxy run
without model traffic is not an official result. Keep state and gold answers
out of Git, and do not tune on gold answers.

## Memory Time Machine UI

```bash
cd ui
npm install
npm run dev      # http://localhost:5173
npm test         # Vitest + Testing Library
```

The UI proxies `/api` to `http://localhost:8000`. Until the backend is
running it shows mock data, and the console shows 500s from `/api/egress`
polling. That is expected.

## Running in a sandbox with Hermes Agent

Chronicle plugs into [Hermes Agent](https://hermes-agent.nousresearch.com) as
its memory provider and runs inside an NVIDIA OpenShell sandbox via NemoClaw.

```bash
# Inside the sandbox (nemoclaw <sandbox> connect), or wherever Hermes runs:
./deploy/install.sh
hermes memory setup                  # choose "chronicle"

# On the host: allow Chronicle's two hosts on top of the sandbox's policy (dev)
./deploy/install.sh --sandbox <sandbox>

# On the host: lock the sandbox down to Token Factory + Tavily only (demo)
./deploy/install.sh --sandbox <sandbox> --lockdown
```

Install before `--lockdown`: the lockdown policy blocks PyPI. The install also
downloads spaCy's English model from github.com, so inside a NemoClaw sandbox
add the `github` preset while installing (`install.sh` stops with a clear error
if name detection can't load). To see anything
the policy blocked, run `openshell logs <sandbox> --source sandbox`.

| File | Purpose |
|---|---|
| `deploy/openshell-policy.yaml` | Complete policy. Network reaches only Hermes's inference route, Token Factory and Tavily. Replaces the live policy. |
| `deploy/presets/chronicle.yaml` | Same two Chronicle hosts as a NemoClaw preset that layers on top |
| `deploy/hermes-plugin/chronicle/` | Hermes plugin; see its README for hooks and tools |

In Hermes, the agent gets `chronicle_recall` (with `as_of: YYYY-MM-DD` to ask
about a past date) and `chronicle_remember`, plus `chronicle_web_search` when
`TAVILY_API_KEY` is set. The plugin currently stores memory
in-process until the SQLite store lands, so memory does not survive a Hermes
restart yet.

## Tests

```bash
uv run pytest            # Python: guard, memory, ingest, deploy policy, Hermes plugin
cd ui && npm test        # UI
```

CI runs both on every push and pull request. Every PR adds tests for what it
changes and updates this README when setup or behaviour changes.

## Repo layout

```
chronicle/
  ingest/        P1  parsers, extraction, entity resolution, temporal normalisation
  memory/        P2  bi-temporal store, search, supersession
  reason/        P3  planner, retriever, answerer, abstention
  guard/         P4  PII detection, pseudonymiser, privacy router, LLM client, egress log
  integrations/  P4  Hermes memory provider, Tavily
  schema.py          shared models (Event, Entity, Source)
adapters/        NVIDIA Agent Memory Benchmark adapter
eval/            benchmark runner, ablations, failure analysis
ui/              P4  Memory Time Machine (React + Vite)
deploy/          P4  install script, OpenShell policy and preset, Hermes plugin
docs/            architecture, benchmark results, demo script
```

## Working on the repo

- Branch from `main` as `p<N>/<topic>` and open a PR.
- Every PR needs one approving review from someone in a different role before
  merging.
- Never look at the benchmark's gold answers while developing.
