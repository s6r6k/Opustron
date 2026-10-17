from pathlib import Path
from .planner import plan_query
from .retriever import retrieve
from .abstention import should_abstain
from .answerer import generate_answer
from .models import AnswerResult

def answer_question(question: str, state: str | Path) -> AnswerResult:
    plan = plan_query(question)
    evidence = retrieve(plan, Path(state))
    if should_abstain(evidence):
        return AnswerResult("Not in the corpus", [])
    return generate_answer(plan, evidence)
