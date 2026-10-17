from datetime import date, datetime

import pytest

from chronicle.ingest.temporal_normalizer import (
    NormalizerConfig,
    Resolved,
    normalize,
    resolve,
)

REF = date(2026, 5, 12)  # a Tuesday

D = date  # single-day results: (expression, expected start)
SINGLE = [
    ("2026-05-20", D(2026, 5, 20)), ("2026-05-20T10:00:00Z", D(2026, 5, 20)),
    ("today", REF), ("now", REF), ("tonight", REF), ("this morning", REF),
    ("tomorrow", D(2026, 5, 13)), ("yesterday", D(2026, 5, 11)),
    ("day before yesterday", D(2026, 5, 10)), ("the day after tomorrow", D(2026, 5, 14)),
    ("next Friday", D(2026, 5, 22)), ("next Tuesday", D(2026, 5, 19)), ("next Monday", D(2026, 5, 18)),
    ("next Sunday", D(2026, 5, 24)),
    ("last Monday", D(2026, 5, 11)), ("last Tuesday", D(2026, 5, 5)), ("last Friday", D(2026, 5, 8)),
    ("this Friday", D(2026, 5, 15)), ("this Tuesday", D(2026, 5, 12)), ("Friday", D(2026, 5, 15)),
    ("on Friday", D(2026, 5, 15)), ("by Friday", D(2026, 5, 15)), ("next fri", D(2026, 5, 22)),
    ("in 3 days", D(2026, 5, 15)), ("in two days", D(2026, 5, 14)), ("in a week", D(2026, 5, 19)),
    ("in 2 weeks", D(2026, 5, 26)), ("in 1 month", D(2026, 6, 12)), ("in a year", D(2027, 5, 12)),
    ("two weeks ago", D(2026, 4, 28)), ("a week ago", D(2026, 5, 5)), ("3 days ago", D(2026, 5, 9)),
    ("2 months ago", D(2026, 3, 12)), ("a year ago", D(2025, 5, 12)), ("one week from now", D(2026, 5, 19)),
    ("end of month", D(2026, 5, 31)), ("end of the month", D(2026, 5, 31)), ("end of week", D(2026, 5, 17)),
    ("end of the year", D(2026, 12, 31)), ("end of quarter", D(2026, 6, 30)), ("start of month", D(2026, 5, 1)),
    ("beginning of the year", D(2026, 1, 1)), ("end of next month", D(2026, 6, 30)),
    ("3 May", D(2026, 5, 3)), ("May 3", D(2026, 5, 3)), ("3rd May 2025", D(2025, 5, 3)),
    ("May 3, 2025", D(2025, 5, 3)), ("1 January", D(2026, 1, 1)), ("sept 9", D(2026, 9, 9)),
]

RANGES = [  # (expression, start, end, precision)
    ("next week", D(2026, 5, 18), D(2026, 5, 24), "week"), ("last week", D(2026, 5, 4), D(2026, 5, 10), "week"),
    ("this week", D(2026, 5, 11), D(2026, 5, 17), "week"),
    ("next month", D(2026, 6, 1), D(2026, 6, 30), "month"), ("last month", D(2026, 4, 1), D(2026, 4, 30), "month"),
    ("this month", D(2026, 5, 1), D(2026, 5, 31), "month"),
    ("next year", D(2027, 1, 1), D(2027, 12, 31), "year"), ("last year", D(2025, 1, 1), D(2025, 12, 31), "year"),
    ("next quarter", D(2026, 7, 1), D(2026, 9, 30), "quarter"), ("last quarter", D(2026, 1, 1), D(2026, 3, 31), "quarter"),
    ("Q1", D(2026, 1, 1), D(2026, 3, 31), "quarter"), ("Q3 2027", D(2027, 7, 1), D(2027, 9, 30), "quarter"),
    ("4Q", D(2026, 10, 1), D(2026, 12, 31), "quarter"), ("May 2026", D(2026, 5, 1), D(2026, 5, 31), "month"),
    ("February 2028", D(2028, 2, 1), D(2028, 2, 29), "month"), ("2027", D(2027, 1, 1), D(2027, 12, 31), "year"),
    ("March", D(2026, 3, 1), D(2026, 3, 31), "month"),
]


@pytest.mark.parametrize("expr,expected", SINGLE)
def test_single_day(expr, expected):
    r = resolve(expr, REF)
    assert r.start == expected and r.end is None and r.confidence > 0


@pytest.mark.parametrize("expr,start,end,precision", RANGES)
def test_ranges(expr, start, end, precision):
    r = resolve(expr, REF)
    assert (r.start, r.end, r.precision) == (start, end, precision)


def test_table_has_50_plus_expressions():
    assert len(SINGLE) + len(RANGES) >= 50


def test_reference_date_drives_everything_not_wall_clock():
    assert resolve("tomorrow", date(2020, 2, 28)).start == date(2020, 2, 29)
    assert resolve("next Friday", date(2031, 1, 1)).start == date(2031, 1, 10)


def test_bare_weekday_is_lower_confidence_and_same_day_for_this():
    assert resolve("Friday", REF).confidence < resolve("next Friday", REF).confidence
    assert resolve("this Tuesday", REF).start == REF


def test_passthrough_types_and_empty():
    assert resolve(date(2026, 1, 2), REF).start == date(2026, 1, 2)
    assert resolve(datetime(2026, 1, 2, 5), REF).start == date(2026, 1, 2)
    for empty in (None, "", "   "):
        assert resolve(empty, REF).start is None


def test_unresolvable_without_fallback():
    r = resolve("whenever the stars align", REF)
    assert r.start is None and r.method == "unresolved"


def test_llm_fallback_used_last():
    fb = lambda expr, ref: Resolved(date(2026, 6, 1), confidence=0.5, method="llm")
    assert resolve("when the stars align", REF, llm_fallback=fb).method == "llm"
    assert resolve("tomorrow", REF, llm_fallback=fb).method == "rule"


def test_invalid_calendar_date_does_not_crash():
    assert resolve("31 February", REF).start is None


def test_sprint_needs_anchor():
    assert resolve("end of sprint", REF).start is None
    cfg = NormalizerConfig(sprint_days=14, sprint_anchor=date(2026, 5, 4))
    assert resolve("end of sprint", REF, config=cfg).start == date(2026, 5, 17)
    assert resolve("start of sprint", REF, config=cfg).start == date(2026, 5, 4)


def test_dateparser_fallback_is_anchored_to_reference():
    r = resolve("12 days ago at noon", REF)
    assert r.start == date(2026, 4, 30) and r.method == "dateparser"


def test_legacy_normalize():
    assert normalize(None) is None
    assert normalize("2026-05-12T01:02:03") == datetime(2026, 5, 12, 1, 2, 3)


def test_next_weekday_is_in_the_following_calendar_week():
    thu = date(2026, 4, 16)  # Thursday: "next Friday" is NOT tomorrow
    assert resolve("next Friday", thu).start == date(2026, 4, 24)
    assert resolve("this Friday", thu).start == date(2026, 4, 17)
    sun = date(2026, 5, 17)  # Sunday still belongs to the week that started Mon 11 May
    assert resolve("next Monday", sun).start == date(2026, 5, 18)
