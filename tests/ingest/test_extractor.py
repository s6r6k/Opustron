import json
from datetime import date

import pytest

from chronicle.ingest.cache import DiskCache
from chronicle.ingest.extractor import ClaimExtractor, parse_llm_json
from chronicle.schema import Document, Event

DOC = Document(doc_id="E:1", text="Alice Chen owns the payments service. The migration is due next Friday.",
               doc_date=date(2026, 5, 12), kind="email")


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def complete(self, messages, schema=None):
        self.calls += 1
        return self.replies.pop(0)


GOOD = json.dumps({"claims": [
    {"subject": "Alice Chen", "predicate": "owns", "object": "payments service",
     "valid_from": None, "valid_to": None, "quote": "Alice Chen owns the payments service.", "confidence": 0.9},
    {"subject": "migration", "predicate": "deadline", "object": "due", "valid_from": "next Friday",
     "quote": "The migration is due next Friday."},
    {"subject": "Bob", "predicate": "owns", "object": "billing", "quote": "Bob owns billing."},  # hallucinated
]})


def test_extract_stamps_with_document_date_and_drops_hallucinations():
    ex = ClaimExtractor(FakeLLM([GOOD]))
    claims = ex.extract(DOC)
    assert len(claims) == 2 and ex.dropped_total == 1
    assert all(c.observed_at == date(2026, 5, 12) and c.doc_id == "E:1" for c in claims)
    assert claims[0].valid_from == date(2026, 5, 12)
    assert claims[1].valid_from == date(2026, 5, 22)  # "next Friday" = Friday of next week, vs doc date not today


def test_cache_makes_rerun_free(tmp_path):
    llm = FakeLLM([GOOD])
    ex = ClaimExtractor(llm, cache=DiskCache(tmp_path))
    first = ex.extract(DOC)
    second = ex.extract(DOC)
    assert llm.calls == 1 and first == second and ex.cache.hits == 1


def test_repair_retry_then_success_and_final_failure():
    assert len(ClaimExtractor(FakeLLM(["oops", GOOD])).extract(DOC)) == 2
    with pytest.raises(ValueError):
        ClaimExtractor(FakeLLM(["oops", "still bad"])).extract(DOC)


def test_undated_document_is_refused():
    with pytest.raises(ValueError, match="no date"):
        ClaimExtractor(FakeLLM([GOOD])).extract(DOC.model_copy(update={"doc_date": None}))


def test_unresolvable_date_lowers_confidence():
    reply = json.dumps({"claims": [{"subject": "A", "predicate": "deadline", "object": "x",
                                    "valid_from": "when stars align", "quote": "Alice Chen owns"}]})
    (c,) = ClaimExtractor(FakeLLM([reply])).extract(DOC)
    assert c.confidence <= 0.4


@pytest.mark.parametrize("raw", [
    '```json\n{"claims": []}\n```', '<think>hmm</think>{"claims": []}', 'Sure! {"claims": []}', "[]",
])
def test_parse_llm_json_tolerant(raw):
    assert parse_llm_json(raw) == []


@pytest.mark.parametrize("raw", ["", "no json", '{"foo": 1}'])
def test_parse_llm_json_rejects(raw):
    with pytest.raises(ValueError):
        parse_llm_json(raw)


def test_legacy_extract_entities():
    from chronicle.ingest.extractor import extract_entities
    from chronicle.schema import Source

    ents = extract_entities(Event(content="Met Alice, Bob.", source=Source(uri="u", kind="k")))
    assert [e.name for e in ents] == ["Alice", "Bob"]


def test_parse_llm_json_ignores_braces_in_reasoning_text():
    raw = ('Here\'s a thinking process:\n1. Output {"ok": true} maybe?\n2. Use {"claims": [1]} no.\n'
           'Final:\n{"claims": [{"subject": "a", "predicate": "owns", "object": "b", "quote": "q"}]}')
    (c,) = parse_llm_json(raw)
    assert c["subject"] == "a"


def test_closing_claim_keeps_start_unknown():
    reply = json.dumps({"claims": [
        {"subject": "Alice Chen", "predicate": "owns", "object": "payments service", "valid_to": "today",
         "quote": "Alice Chen owns the payments service."}]})
    (c,) = ClaimExtractor(FakeLLM([reply])).extract(DOC)
    assert c.valid_from is None and c.valid_to == date(2026, 5, 12)


def test_quote_check_ignores_markdown_formatting_but_not_content():
    """related_to is now off-vocabulary (dropped at predicate); Bob's quote is hallucinated (dropped at quote)."""
    doc = DOC.model_copy(update={"text": "**Branch:** `feature/x` → main\n- [Alice Chen](http://u) owns it"})
    reply = json.dumps({"claims": [
        {"subject": "x", "predicate": "related_to", "object": "main", "quote": "Branch: feature/x → main"},
        {"subject": "Alice Chen", "predicate": "owns", "object": "it", "quote": "Alice Chen owns it"},
        {"subject": "Bob", "predicate": "owns", "object": "it", "quote": "Bob owns it"},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    claims = ex.extract(doc)
    assert len(claims) == 1  # only Alice's claim passes
    assert ex.dropped["predicate"] >= 1  # related_to dropped
    assert ex.dropped["quote"] >= 1  # Bob's hallucinated quote dropped
    assert ex.dropped_total == 2

# ---------------------------------------------------------------------------
# New v3 tests: rendering, roster, classifier, predicate enforcement
# ---------------------------------------------------------------------------

def test_email_header_included_in_rendered_prompt():
    """The model should see From/To/Subject so it can attribute claims correctly."""
    from chronicle.ingest.extractor import render_for_llm
    doc = Document(doc_id="E:1", text="Dana takes over payments from Alice.",
                   doc_date=date(2026, 5, 12), kind="email",
                   metadata={"from": "Alex Chen (@alex) <alex.chen@example.com>",
                              "to": ["Dana Lee (@dana) <dana.lee@example.com>"],
                              "subject": "Payments handover"})
    rendered = render_for_llm(doc)
    assert "From: Alex Chen" in rendered
    assert "Subject: Payments handover" in rendered
    assert "Dana takes over payments" in rendered


def test_slack_mention_replaced_in_rendered_text():
    from chronicle.ingest.extractor import render_for_llm
    from chronicle.ingest.roster import Roster
    roster = Roster(slack_ids={"U20094F0C2DD": "Lena Park"},
                    aliases={"lena park": "Lena Park"}, people=["Lena Park"])
    doc = Document(doc_id="S:1", text="can you look <@U20094F0C2DD>?",
                   doc_date=date(2026, 4, 21), kind="slack")
    rendered = render_for_llm(doc, roster)
    assert "Lena Park" in rendered
    assert "<@U20094F0C2DD>" not in rendered


def test_ts_noise_stripped():
    from chronicle.ingest.extractor import render_for_llm
    doc = Document(doc_id="S:1",
                   text="Sam Iverson (U200C6) [ts=1776761863.394136]: hello\nreply [ts=abc] done",
                   doc_date=date(2026, 4, 21), kind="slack")
    rendered = render_for_llm(doc)
    assert "[ts=" not in rendered


def test_classify_automated_folder():
    from chronicle.ingest.extractor import classify_doc
    doc = Document(doc_id="E:1", text="", doc_date=date(2026, 4, 16), kind="email",
                   metadata={"folder": "inbox-automated"})
    assert classify_doc(doc) == "automated"


def test_classify_bot_sender():
    from chronicle.ingest.extractor import classify_doc
    doc = Document(doc_id="E:1", text="", doc_date=date(2026, 4, 16), kind="email",
                   metadata={"from": "GitLab <gitlab@example.com>"})
    assert classify_doc(doc) == "automated"


def test_classify_human_email():
    from chronicle.ingest.extractor import classify_doc
    doc = Document(doc_id="E:1", text="", doc_date=date(2026, 4, 16), kind="email",
                   metadata={"from": "Alex Chen (@alex) <alex.chen@example.com>", "folder": "inbox"})
    assert classify_doc(doc) == "human"


def test_off_vocabulary_predicate_dropped():
    reply = json.dumps({"claims": [
        {"subject": "Alice Chen", "predicate": "invitee", "object": "standup",
         "quote": "Alice Chen owns the payments service."},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    # invitee -> member_of via PREDICATE_SYNONYMS, should NOT be dropped
    claims = ex.extract(DOC)
    assert any(c.predicate == "member_of" for c in claims)


def test_truly_unknown_predicate_dropped():
    reply = json.dumps({"claims": [
        {"subject": "Alice Chen", "predicate": "totally_made_up", "object": "something",
         "quote": "Alice Chen owns the payments service."},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    assert ex.extract(DOC) == []
    assert ex.dropped["predicate"] == 1


def test_attr_predicate_accepted():
    reply = json.dumps({"claims": [
        {"subject": "atlas", "predicate": "attr:p95_latency", "object": "120ms",
         "quote": "Alice Chen owns the payments service."},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    claims = ex.extract(DOC)
    assert len(claims) == 1 and claims[0].predicate == "attr:p95_latency"


def test_non_entity_subject_dropped():
    """A URL or file path as subject should be rejected."""
    reply = json.dumps({"claims": [
        {"subject": "https://gitlab.example.com/mr/284", "predicate": "status", "object": "open",
         "quote": "Alice Chen owns the payments service."},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    assert ex.extract(DOC) == []
    assert ex.dropped["non_entity"] == 1


def test_mr_subject_allowed_for_status():
    """!284 is a valid subject when predicate is status/completed."""
    doc = Document(doc_id="E:1",
                   text="merge request !284 was merged by Alice Chen.",
                   doc_date=date(2026, 5, 12), kind="email",
                   metadata={"folder": "inbox-automated",
                              "from": "GitLab <gitlab@example.com>"})
    reply = json.dumps({"claims": [
        {"subject": "!284", "predicate": "completed", "object": "merged",
         "quote": "merge request !284 was merged by Alice Chen."},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    claims = ex.extract(doc)
    assert len(claims) == 1
    assert claims[0].subject == "MR !284"


def test_header_quote_passes_verification():
    """A quote lifted from the rendered header (From/Subject) should verify."""
    doc = Document(doc_id="E:2", text="See above.",
                   doc_date=date(2026, 5, 12), kind="email",
                   metadata={"from": "Alex Chen (@alex) <alex@example.com>",
                              "subject": "Payments handover update"})
    reply = json.dumps({"claims": [
        {"subject": "Alex Chen", "predicate": "proposed", "object": "payments handover",
         "quote": "Subject: Payments handover update"},
    ]})
    ex = ClaimExtractor(FakeLLM([reply]))
    claims = ex.extract(doc)
    assert len(claims) == 1
