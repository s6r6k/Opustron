import io
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch
from chronicle.reason.planner import plan_query
from chronicle.reason.retriever import retrieve
from chronicle.reason.models import AnswerResult
from chronicle.ingest.pipeline import ingest_corpus, read_claims
from adapters.chronicle.answer import run
from eval.metrics import summarize

def test_planner_as_of():
    p = plan_query("Who owned payments on 2026-05-03?")
    assert p.kind == "as_of" and p.reference_date == date(2026, 5, 3)

def test_planner_current():
    assert plan_query("Who currently owns payments?").kind == "current"

def test_ingest_twice_and_retrieve(tmp_path):
    class FakeLLM:
        def complete(self, messages, schema=None):
            return json.dumps({"claims": [{
                "subject": "Alice", "predicate": "owns", "object": "payments",
                "quote": messages[1]["content"].strip(), "valid_from": "today",
            }]})

    a, b, state = tmp_path / "a", tmp_path / "b", tmp_path / "state"
    a.mkdir(); b.mkdir()
    (a / "one.md").write_text("---\ndoc_id: E:one\ndate: 2026-04-01\nsubject: payments\n---\nAlice managed payments.", encoding="utf-8")
    (b / "two.md").write_text("---\ndoc_id: E:two\ndate: 2026-05-01\nsubject: payments\n---\nBob replaced Alice in payments.", encoding="utf-8")
    llm = FakeLLM()
    ingest_corpus(a, state, llm); ingest_corpus(b, state, llm)
    assert ingest_corpus(a, state, llm).skipped == 1
    assert len(read_claims(state / "claims.jsonl")) == 2
    assert not (state / "chronicle_adapter.sqlite3").exists()
    evidence = retrieve(plan_query("Who managed payments?"), state)
    assert {e.doc_id for e in evidence} == {"E:one", "E:two"}
    assert all(json.loads(e.text)["quote"] for e in evidence)

def test_answer_jsonl_shape(tmp_path):
    inp = io.StringIO('{"id":"q1","question":"unknown"}\n')
    out = io.StringIO()
    with patch("adapters.chronicle.answer.answer_question", return_value=AnswerResult("Bob", ["E:two"])):
        run(tmp_path, inp, out)
    assert json.loads(out.getvalue()) == {"id":"q1", "answer":"Bob", "source_ids":["E:two"]}


def test_malformed_questions_are_skipped_without_logging_content(tmp_path, capsys):
    inp = io.StringIO('\nnot-json-private-text\n[]\nnull\n{"id":3,"question":"private"}\n'
                      '{"id":"q0"}\n{"id":"q1","question":"payments"}\n')
    out = io.StringIO()
    with patch("adapters.chronicle.answer.answer_question", return_value=AnswerResult("Bob", ["E:two"])) as answer:
        run(tmp_path, inp, out)
    answer.assert_called_once_with("payments", tmp_path)
    assert json.loads(out.getvalue())["id"] == "q1"
    stderr = capsys.readouterr().err
    assert stderr.count("skipping line") == 5
    assert "line 2: invalid JSON" in stderr
    assert "private" not in stderr

def test_summary():
    assert summarize([{"category":"as_of","correct":True},{"category":"as_of","correct":False}])["as_of"]["accuracy"] == .5
