import pytest
from chronicle.guard.pii_detector import contains_pii, detect


@pytest.mark.parametrize("text,expected_type", [
    ("Email me at alice@example.com", "EMAIL_ADDRESS"),
    ("Call 555-867-5309", "PHONE_NUMBER"),
    ("SSN: 123-45-6789", "US_SSN"),
    ("Visit https://example.com/path", "URL"),
])
def test_detects_known_pii(text, expected_type):
    matches = detect(text)
    types = [m.entity_type for m in matches]
    assert expected_type in types, f"Expected {expected_type} in {types}"


def test_contains_pii_true():
    assert contains_pii("Contact me at bob@example.com")


def test_contains_pii_false():
    assert not contains_pii("The meeting is at 9am tomorrow")


def test_no_overlapping_spans():
    text = "alice@example.com and bob@example.com"
    matches = detect(text)
    for i, m in enumerate(matches):
        for j, n in enumerate(matches):
            if i != j:
                assert not (m.start < n.end and n.start < m.end), (
                    f"Overlapping spans: {m} and {n}"
                )


def test_match_value_matches_text():
    text = "Phone: +1-800-555-0199"
    matches = detect(text)
    for m in matches:
        assert text[m.start:m.end] == m.value
