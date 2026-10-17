from chronicle.guard.pseudonymizer import (
    PseudonymMapping,
    pseudonymize,
    reidentify,
)


def test_email_is_redacted():
    redacted, _ = pseudonymize("Contact a@example.com")
    assert "a@example.com" not in redacted
    assert "EMAIL_1" in redacted


def test_same_value_gets_same_token():
    mapping = PseudonymMapping()
    text = "alice@example.com and alice@example.com again"
    redacted, mapping = pseudonymize(text, mapping)
    assert redacted.count("EMAIL_1") == 2


def test_different_values_get_different_tokens():
    mapping = PseudonymMapping()
    t1, mapping = pseudonymize("alice@example.com", mapping)
    t2, mapping = pseudonymize("bob@example.com", mapping)
    assert "EMAIL_1" in t1
    assert "EMAIL_2" in t2


def test_reidentify_restores_original():
    original = "Contact alice@example.com for help"
    redacted, mapping = pseudonymize(original)
    restored = reidentify(redacted, mapping)
    assert restored == original


def test_mapping_shared_across_texts():
    mapping = PseudonymMapping()
    _, mapping = pseudonymize("Call 555-867-5309", mapping)
    _, mapping = pseudonymize("Again: 555-867-5309", mapping)
    # Same phone should map to same token
    tokens = list(mapping._forward.values())
    assert len(set(tokens)) == 1


def test_no_pii_text_unchanged():
    text = "The quick brown fox jumps over the lazy dog."
    redacted, mapping = pseudonymize(text)
    assert redacted == text


def test_multiple_pii_types():
    text = "Alice can be reached at alice@corp.com or +1-800-555-0199"
    redacted, mapping = pseudonymize(text)
    assert "alice@corp.com" not in redacted
    assert "+1-800-555-0199" not in redacted
    assert len(mapping.pii_types_seen()) >= 1


def test_reidentify_unknown_token_unchanged():
    mapping = PseudonymMapping()
    result = reidentify("Hello PERSON_99 world", mapping)
    assert result == "Hello PERSON_99 world"
