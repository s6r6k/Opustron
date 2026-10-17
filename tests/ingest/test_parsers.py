from datetime import date
from pathlib import Path

from chronicle.ingest.parsers.markdown import parse_document, split_frontmatter, to_date

FIX = Path(__file__).parent.parent / "fixtures" / "corpus"


def test_split_frontmatter_roundtrip():
    meta, body = split_frontmatter("---\ndoc_id: X\ndate: 2026-04-16\n---\n\nHello")
    assert meta["doc_id"] == "X" and body == "Hello"


def test_split_frontmatter_missing_or_broken():
    assert split_frontmatter("no header") == ({}, "no header")
    assert split_frontmatter("---\n: : bad\n[\n---\nx")[0] == {}
    assert split_frontmatter("---\nnever closed")[0] == {}


def test_to_date_variants():
    assert to_date("2026-04-16T09:12:00Z") == date(2026, 4, 16)
    assert to_date(date(2026, 1, 2)) == date(2026, 1, 2)
    assert to_date("garbage") is None and to_date(None) is None


def test_parse_document_email():
    doc = parse_document(FIX / "part_a/email/e1.md", root=FIX / "part_a", part="a")
    assert doc.doc_id == "E:2026-04-16T09-12-00__aaaa0001"
    assert doc.doc_date == date(2026, 4, 16) and doc.kind == "email" and doc.part == "a"
    assert doc.text.startswith("Alice Chen owns")


def test_parse_document_without_date_falls_back_to_mtime(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("just a note")
    doc = parse_document(p, root=tmp_path)
    assert doc.doc_id == "M:note.md" and doc.metadata["date_source"] == "mtime"


def test_iter_documents_orders_parts_and_recurses():
    from chronicle.ingest.parsers.benchmark import iter_documents

    docs = list(iter_documents(FIX))
    assert [d.part for d in docs] == ["a", "a", "b"]
    assert {d.kind for d in docs} == {"email", "slack"}
    assert docs[-1].doc_id.startswith("E:2026-05-12")


def test_iter_documents_single_part_dir():
    from chronicle.ingest.parsers.benchmark import iter_documents

    docs = list(iter_documents(FIX / "part_b"))
    assert len(docs) == 1 and docs[0].part == "b"


def test_manifest_fills_missing_date(tmp_path):
    import json

    from chronicle.ingest.parsers.benchmark import iter_documents

    part = tmp_path / "part_a"
    part.mkdir()
    (part / "n.md").write_text("no frontmatter")
    (tmp_path / "manifest.jsonl").write_text(
        json.dumps({"doc_id": "E:x", "part": "a", "path": "part_a/n.md", "timestamp": "2026-04-20T00:00:00Z"}) + "\n"
    )
    (doc,) = iter_documents(tmp_path)
    assert doc.doc_id == "E:x" and doc.doc_date == date(2026, 4, 20)


EML = (
    "Message-ID: <m1@example.test>\nDate: Fri, 17 Apr 2026 10:00:00 +0000\n"
    "From: a@example.test\nTo: b@example.test\nSubject: Hello\n\nBody text here.\n"
)


def test_parse_eml(tmp_path):
    from chronicle.ingest.parsers.email import parse_eml

    p = tmp_path / "a.eml"
    p.write_text(EML)
    doc = parse_eml(p)
    assert doc.doc_id == "m1@example.test" and doc.doc_date == date(2026, 4, 17)
    assert "Body text here." in doc.text and doc.kind == "email"


def test_parse_mbox(tmp_path):
    from chronicle.ingest.parsers.email import parse_mbox

    p = tmp_path / "box.mbox"
    p.write_text("From a@example.test Fri Apr 17 10:00:00 2026\n" + EML)
    docs = parse_mbox(p)
    assert len(docs) == 1 and docs[0].doc_date == date(2026, 4, 17)


def test_parse_slack_groups_by_day(tmp_path):
    import json

    from chronicle.ingest.parsers.chat import parse_slack

    p = tmp_path / "general.json"
    p.write_text(json.dumps([
        {"user": "bob", "text": "hi", "ts": "1776330000"},
        {"user": "amy", "text": "yo", "ts": "1776333600"},
        {"user": "amy", "text": "next day", "ts": "1776430000"},
        {"text": ""},
    ]))
    docs = parse_slack(p, channel="general")
    assert len(docs) == 2 and docs[0].doc_id.startswith("S:general@2026-04-1")
    assert docs[0].metadata["message_count"] == 2


def test_parse_whatsapp_multiline(tmp_path):
    from chronicle.ingest.parsers.chat import parse_whatsapp

    p = tmp_path / "grp.txt"
    p.write_text("17/04/2026, 10:00 - Bob: hello\nsecond line\n18/04/2026, 09:00 - Amy: bye\n")
    docs = parse_whatsapp(p)
    assert [d.doc_date for d in docs] == [date(2026, 4, 17), date(2026, 4, 18)]
    assert "second line" in docs[0].text


def test_parse_ics(tmp_path):
    from chronicle.ingest.parsers.calendar import parse_ics

    p = tmp_path / "c.ics"
    p.write_text(
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\nBEGIN:VEVENT\nUID:u1\n"
        "DTSTAMP:20260410T080000Z\nDTSTART:20260420T090000Z\nDTEND:20260420T100000Z\n"
        "SUMMARY:Payments review\nLOCATION:Room 4\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    (doc,) = parse_ics(p)
    assert doc.doc_id == "C:u1" and doc.doc_date == date(2026, 4, 10)
    assert doc.metadata["start"] == "2026-04-20" and "Room 4" in doc.text
