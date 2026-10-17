from datetime import date

from chronicle.ingest.entity_resolver import EntityResolver, normalize_name, resolve
from chronicle.schema import Claim, Entity


def test_legacy_resolve_dedups_case_insensitively():
    assert len(resolve([Entity(name="Alice"), Entity(name="ALICE")])) == 1


def test_normalize_name_strips_titles_and_punct():
    assert normalize_name("Dr. Alice Chen!") == "alice chen"


def test_alias_table_wins():
    r = EntityResolver(aliases={"payments": "Payments Service", "pay svc": "Payments Service"})
    assert r.resolve("Pay Svc") == "Payments Service"


def test_fuzzy_merge_and_case():
    r = EntityResolver()
    assert r.resolve("Alice Chen") == "Alice Chen"
    assert r.resolve("alice chen") == "Alice Chen"
    assert r.resolve("Alice  Chen.") == "Alice Chen"
    assert r.resolve("Chen Alice") == "Alice Chen"  # token-order variant


def test_first_name_maps_only_when_unique():
    r = EntityResolver()
    r.resolve("Alice Chen")
    assert r.resolve("Alice") == "Alice Chen"
    r2 = EntityResolver()
    r2.resolve("Alice Chen")
    r2.resolve("Alice Park")
    assert r2.resolve("Alice") == "Alice"  # ambiguous -> stays separate


def test_distinct_people_not_merged():
    r = EntityResolver()
    r.resolve("Alice Chen")
    assert r.resolve("Dana Lee") == "Dana Lee"
    assert r.resolve("Alice Park") == "Alice Park"


def test_llm_tie_break_for_ambiguous_band():
    calls = []
    r = EntityResolver(tie_break=lambda a, b: calls.append((a, b)) or True)
    r.resolve("Payments Platform Team")
    assert r.resolve("Payments Platform Squad") == "Payments Platform Team"
    assert calls
    r2 = EntityResolver(tie_break=lambda a, b: False)
    r2.resolve("Payments Platform Team")
    assert r2.resolve("Payments Platform Squad") == "Payments Platform Squad"


def test_resolve_claim_rewrites_subject_and_known_object():
    r = EntityResolver()
    r.resolve("Alice Chen")
    c = Claim(subject="alice chen", predicate="reports_to", object="alice chen", doc_id="d", quote="q",
              observed_at=date(2026, 1, 1))
    out = r.resolve_claim(c)
    assert out.subject == "Alice Chen" and out.object == "Alice Chen"
    plain = r.resolve_claim(c.model_copy(update={"object": "the payments service"}))
    assert plain.object == "the payments service"


# ---------------------------------------------------------------------------
# v3 alias normalisation: @, _ and . variants
# ---------------------------------------------------------------------------

def test_at_handle_resolves():
    r = EntityResolver(aliases={"alex": "Alex Chen"})
    assert r.resolve("@alex") == "Alex Chen"


def test_underscore_variant_resolves():
    r = EntityResolver(aliases={"alex chen": "Alex Chen"})
    assert r.resolve("alex_chen") == "Alex Chen"


def test_dot_variant_resolves():
    r = EntityResolver(aliases={"alex chen": "Alex Chen"})
    assert r.resolve("alex.chen") == "Alex Chen"


def test_resolve_claim_object_via_alias():
    r = EntityResolver(aliases={"@dana": "Dana Lee", "dana lee": "Dana Lee"})
    r.resolve("Dana Lee")
    c = Claim(subject="someone", predicate="reports_to", object="@dana",
              doc_id="d", quote="q", observed_at=date(2026, 1, 1))
    out = r.resolve_claim(c)
    assert out.object == "Dana Lee"
