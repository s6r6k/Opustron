from unittest.mock import patch

import pytest

from chronicle.reason.answerer import ANSWER_SCHEMA, generate_answer
from chronicle.reason.models import AnswerResult, Evidence, QueryPlan


def test_answer_calls_guard_with_json_schema_and_limits_citations():
    evidence = [Evidence("E:one", "Alice owns payments.", "2026-04-01")]
    with patch("chronicle.reason.answerer.llm.complete", return_value={
        "answer": "Alice", "source_ids": ["E:one", "E:invented", "E:one", 7],
    }) as complete:
        assert generate_answer(QueryPlan("Who owns payments?"), evidence) == AnswerResult("Alice", ["E:one"])
    messages = complete.call_args.args[0]
    assert "Who owns payments?" in messages[1]["content"]
    assert "Alice owns payments." in messages[1]["content"]
    assert complete.call_args.kwargs == {"schema": ANSWER_SCHEMA}


def test_no_evidence_abstains_without_calling_model():
    with patch("chronicle.reason.answerer.llm.complete") as complete:
        assert generate_answer(QueryPlan("unknown"), []) == AnswerResult("Not in the corpus", [])
    complete.assert_not_called()


def test_invalid_model_object_fails_explicitly():
    with patch("chronicle.reason.answerer.llm.complete", return_value=[]):
        with pytest.raises(ValueError, match="no JSON object"):
            generate_answer(QueryPlan("payments"), [Evidence("E:one", "payments")])
