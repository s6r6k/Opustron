"""Generate privacy-routed answers with citations limited to retrieved evidence."""
from chronicle.guard import llm

from .models import AnswerResult, Evidence, QueryPlan

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "source_ids"],
    "additionalProperties": False,
}

FALLBACK_CONTRACT = """Answer the question from the memory you built out of the corpus.
Rules:
1. Be short. Answer with the specific value asked for, not a paragraph.
2. Give the CURRENT state unless the question explicitly asks about the past. A later document may supersede an earlier one.
3. If the corpus does not support an answer, say plainly that it is not in the corpus. Never guess. Something only scheduled has not happened.
4. Cite the exact document ids you relied on.
Reply with a single JSON object and nothing else:
{"answer": "<your short answer>", "source_ids": ["<doc id>", ...]}"""

def _contract() -> str:
    try:
        from bench.answer_contract import ANSWER_CONTRACT
        return ANSWER_CONTRACT
    except ImportError:
        return FALLBACK_CONTRACT

def generate_answer(plan: QueryPlan, evidence: list[Evidence]) -> AnswerResult:
    if not evidence:
        return AnswerResult("Not in the corpus", [])
    context = "\n\n".join(f"[{e.doc_id}] date={e.date}\n{e.text}" for e in evidence)
    messages = [
        {"role": "system", "content": _contract()},
        {"role": "user", "content": f"EVIDENCE:\n{context}\n\nQUESTION: {plan.question}"},
    ]
    parsed = llm.complete(messages, schema=ANSWER_SCHEMA)
    if not isinstance(parsed, dict):
        raise ValueError("LLM returned no JSON object")
    allowed = {e.doc_id for e in evidence}
    ids = parsed.get("source_ids") or []
    if not isinstance(ids, list):
        ids = []
    ids = list(dict.fromkeys(i for i in ids if isinstance(i, str) and i in allowed))
    answer = parsed.get("answer", "Not in the corpus")
    if not isinstance(answer, str):
        answer = "Not in the corpus"
    return AnswerResult(answer=answer, source_ids=ids)
