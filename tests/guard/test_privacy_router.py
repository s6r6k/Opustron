from chronicle.guard.privacy_router import PrivacyRouter


def test_route_clean_text():
    router = PrivacyRouter()
    assert router.route("The meeting is at 9am") == "external"


def test_route_pii_text():
    router = PrivacyRouter()
    assert router.route("Email alice@example.com") == "local"


def test_redact_and_restore_roundtrip():
    router = PrivacyRouter()
    original = "Please contact alice@corp.com for the invoice"
    redacted, mapping = router.redact(original)
    assert "alice@corp.com" not in redacted
    restored = router.restore(redacted, mapping)
    assert restored == original


def test_redact_messages():
    router = PrivacyRouter()
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "My email is test@example.com"},
    ]
    redacted, mapping = router.redact_messages(messages)
    assert "test@example.com" not in redacted[1]["content"]
    assert redacted[0]["content"] == messages[0]["content"]


def test_shared_mapping_across_messages():
    router = PrivacyRouter()
    messages = [
        {"role": "user", "content": "alice@example.com"},
        {"role": "user", "content": "Contact alice@example.com again"},
    ]
    redacted, mapping = router.redact_messages(messages)
    # Both should use the same EMAIL_1 token
    assert "EMAIL_1" in redacted[0]["content"]
    assert "EMAIL_1" in redacted[1]["content"]
