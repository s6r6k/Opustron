const BASE = "/api";

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

// P2 memory store endpoints
export const getEntities = () => get("/entities");
export const getEntityHistory = (id) => get(`/entities/${id}/history`);
export const getFactsAsOf = (isoDate) => get(`/facts?as_of=${isoDate}`);
export const getTimeline = (start, end) =>
  get(`/timeline?start=${start}&end=${end}`);

// P3 reasoning endpoint
export const ask = (question, asOf = null) =>
  post("/ask", { question, as_of: asOf });

// P4 egress log endpoint
export const getEgressLog = (n = 30) => get(`/egress?n=${n}`);

// ---------------------------------------------------------------------------
// Mock data — used when the backend is not running (scaffold phase)
// ---------------------------------------------------------------------------

const CORPUS_START = new Date("2026-04-16");
const CORPUS_END = new Date("2026-05-27");

export const MOCK = {
  corpusStart: CORPUS_START,
  corpusEnd: CORPUS_END,

  entities: [
    { entity_id: "e1", name: "payments service", entity_type: "SERVICE" },
    { entity_id: "e2", name: "deploy pipeline", entity_type: "SERVICE" },
    { entity_id: "e3", name: "Alice Chen", entity_type: "PERSON" },
    { entity_id: "e4", name: "Bob Nakamura", entity_type: "PERSON" },
  ],

  facts: [
    {
      fact_id: "f1",
      subject: "payments service",
      predicate: "owner",
      object: "Alice Chen",
      valid_from: "2026-05-01",
      valid_to: "2026-05-14",
      doc_id: "email_001",
      quote: "Alice owns the payments service going forward.",
    },
    {
      fact_id: "f2",
      subject: "payments service",
      predicate: "owner",
      object: "Bob Nakamura",
      valid_from: "2026-05-15",
      valid_to: null,
      doc_id: "email_042",
      quote: "Bob now owns the payments service.",
    },
    {
      fact_id: "f3",
      subject: "deploy pipeline",
      predicate: "lead",
      object: "Alice Chen",
      valid_from: "2026-04-16",
      valid_to: null,
      doc_id: "email_003",
      quote: "Alice Chen is leading the deploy pipeline effort.",
    },
    {
      fact_id: "f4",
      subject: "deploy pipeline",
      predicate: "on-call",
      object: "Bob Nakamura",
      valid_from: "2026-04-22",
      valid_to: "2026-05-05",
      doc_id: "chat_007",
      quote: "Bob is on-call for deploys this sprint.",
    },
  ],

  egressEntries: [
    {
      ts: new Date(Date.now() - 8000).toISOString(),
      provider: "nebius_token_factory",
      model: "nvidia/nemotron-mini-4b-instruct",
      prompt_tokens: 312,
      completion_tokens: 48,
      redacted: true,
      pii_types: ["PERSON"],
      request_preview: "Who owned ORG_1_service on 3 May?",
    },
    {
      ts: new Date(Date.now() - 22000).toISOString(),
      provider: "nebius_token_factory",
      model: "nvidia/nemotron-mini-4b-instruct",
      prompt_tokens: 204,
      completion_tokens: 31,
      redacted: false,
      pii_types: [],
      request_preview: "What is the current lead for the deploy pipeline?",
    },
  ],
};

export function factsAsOf(facts, isoDate) {
  const d = new Date(isoDate);
  return facts.filter((f) => {
    const from = new Date(f.valid_from);
    const to = f.valid_to ? new Date(f.valid_to) : new Date("2099-01-01");
    return from <= d && d <= to;
  });
}

export function allFactsForSubject(facts, subject) {
  return facts.filter((f) => f.subject === subject);
}
