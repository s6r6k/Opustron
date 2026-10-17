"""Tests for chronicle.ingest.roster."""

import json
from datetime import date

from chronicle.ingest.roster import Roster, build_roster
from chronicle.schema import Document


def _email(text: str, meta: dict | None = None) -> Document:
    return Document(doc_id="E:test", text=text, doc_date=date(2026, 4, 16), kind="email",
                    metadata=meta or {})


def _slack(text: str, meta: dict | None = None) -> Document:
    return Document(doc_id="S:test", text=text, doc_date=date(2026, 4, 21), kind="slack",
                    metadata=meta or {})


# ---------------------------------------------------------------------------
# Email header parsing
# ---------------------------------------------------------------------------

def test_email_from_field_registers_person():
    doc = _email("Hello", meta={"from": "Alex Chen (@alex) <alex.chen@example.com>"})
    r = build_roster([doc])
    assert r.aliases.get("alex chen") == "Alex Chen"
    assert r.aliases.get("@alex") == "Alex Chen"
    assert r.aliases.get("alex") == "Alex Chen"


def test_email_local_part_variants_registered():
    doc = _email("Hi", meta={"from": "Dana Lee (@dana) <dana.lee@example.com>"})
    r = build_roster([doc])
    # "dana.lee" -> "dana lee" and "dana_lee"
    assert r.aliases.get("dana lee") == "Dana Lee"
    assert r.aliases.get("dana_lee") == "Dana Lee"
    assert r.aliases.get("dana.lee") == "Dana Lee"


def test_email_to_and_cc_lists():
    doc = _email("Hi", meta={
        "from": "Alex Chen (@alex) <alex.chen@example.com>",
        "to": ["Jordan Kim (@jordan) <jordan.kim@example.com>"],
        "cc": ["Morgan Lee (@morgan) <morgan.lee@example.com>"],
    })
    r = build_roster([doc])
    assert "Alex Chen" in r.people
    assert "Jordan Kim" in r.people
    assert "Morgan Lee" in r.people


# ---------------------------------------------------------------------------
# Slack speaker parsing
# ---------------------------------------------------------------------------

def test_slack_speaker_line_parsed():
    text = (
        "[2026-04-21T08:57:43Z] Sam Iverson (U200C6EF237B) [ts=1776761863.394136]: hello\n"
        "[2026-04-21T09:08:22Z] Alex Chen (U200AC3F7E12) [ts=1776762502.394136]: world\n"
    )
    r = build_roster([_slack(text)])
    assert r.slack_ids.get("U200C6EF237B") == "Sam Iverson"
    assert r.slack_ids.get("U200AC3F7E12") == "Alex Chen"
    assert r.aliases.get("sam iverson") == "Sam Iverson"


def test_slack_mention_replacement():
    text = (
        "[2026-04-21T11:00:43Z] Sam Iverson (U200C6EF237B) [ts=x]: can you look <@U20094F0C2DD>?\n"
        "[2026-04-21T15:41:23Z] Lena Park (U20094F0C2DD) [ts=y]: on it\n"
    )
    r = build_roster([_slack(text)])
    assert r.expand_slack_mention("U20094F0C2DD") == "Lena Park"
    rendered = r.render("done by <@U20094F0C2DD> and <@U200C6EF237B>")
    assert "Lena Park" in rendered and "Sam Iverson" in rendered


def test_unknown_uid_fallback():
    r = Roster()
    assert r.expand_slack_mention("UUNKNOWN") == "@UUNKNOWN"


# ---------------------------------------------------------------------------
# Cross-document accumulation and idempotency
# ---------------------------------------------------------------------------

def test_first_seen_name_wins():
    doc1 = _email("", meta={"from": "Alex Chen (@alex) <alex.chen@example.com>"})
    doc2 = _email("", meta={"from": "Alexander Chen (@alex) <alex.chen@example.com>"})
    r = build_roster([doc1, doc2])
    assert r.aliases.get("alex chen") == "Alex Chen"  # first one wins


def test_existing_roster_merged():
    doc1 = _email("", meta={"from": "Alex Chen (@alex) <alex.chen@example.com>"})
    r1 = build_roster([doc1])
    doc2 = _email("", meta={"from": "Dana Lee (@dana) <dana.lee@example.com>"})
    r2 = build_roster([doc2], existing=r1)
    assert "Alex Chen" in r2.people and "Dana Lee" in r2.people


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------

def test_roster_json_round_trip():
    doc = _email("", meta={"from": "Alex Chen (@alex) <alex.chen@example.com>"})
    r = build_roster([doc])
    r2 = Roster.from_json(r.to_json())
    assert r2.aliases == r.aliases
    assert r2.slack_ids == r.slack_ids
    assert r2.people == r.people
