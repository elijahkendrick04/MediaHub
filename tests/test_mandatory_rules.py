"""C1: Brand guidelines mandatory-rule extraction + top-of-prompt enforcement.

User pain point: rules like "the strapline MUST always appear" written
in uploaded PDFs were being soft-interpreted as preferences and getting
drowned out by website-derived voice signals when the LLM weighed
competing cues.

The fix:
  1. A dedicated extract_mandatory_rules(text) pass surfaces hard
     constraints verbatim. The implementation is LLM-driven; when no
     cloud provider is configured the function returns ``[]`` rather
     than fabricating regex-extracted rules — production deployments
     have an LLM key configured.
  2. brand.context.brand_context_for_llm puts those rules at the TOP of
     the system prompt with explicit override framing, AND appends a
     compliance-recheck reminder at the end.
"""
from __future__ import annotations

from mediahub.brand.guidelines import (
    extract_mandatory_rules,
    ingest_guidelines_file,
    _normalise_mandatory_rules,
)
from mediahub.brand.context import brand_context_for_llm
from mediahub.web.club_profile import ClubProfile


# ---------------------------------------------------------------------------
# _normalise_mandatory_rules — defensive coercion
# ---------------------------------------------------------------------------

def test_normalise_accepts_list():
    assert _normalise_mandatory_rules(["Rule one.", "Rule two."]) == [
        "Rule one.", "Rule two."
    ]


def test_normalise_accepts_dict_with_key():
    assert _normalise_mandatory_rules({"mandatory_rules": ["A", "B"]}) == ["A", "B"]


def test_normalise_strips_quotes():
    assert _normalise_mandatory_rules(['"Rule A"', "'Rule B'"]) == ["Rule A", "Rule B"]


def test_normalise_rejects_garbage():
    assert _normalise_mandatory_rules(None) == []
    assert _normalise_mandatory_rules("not a list") == []
    assert _normalise_mandatory_rules([None, "", "  ", 42]) == []


# ---------------------------------------------------------------------------
# extract_mandatory_rules — top-level entry point
# ---------------------------------------------------------------------------

def test_extract_handles_empty_input():
    assert extract_mandatory_rules("") == []
    assert extract_mandatory_rules("   ") == []


def test_extract_returns_empty_when_no_llm(monkeypatch):
    """When no cloud LLM provider is configured, extract_mandatory_rules
    returns an empty list rather than fabricating rules from regex.
    Production deployments have a provider configured, so this path
    only affects no-key dev environments."""
    def fake_is_available():
        return False

    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", fake_is_available, raising=False)

    text = "The strapline MUST appear. Voice is warm."
    rules = extract_mandatory_rules(text)
    assert rules == []


# ---------------------------------------------------------------------------
# ingest_guidelines_file populates the new payload key
# ---------------------------------------------------------------------------

def test_ingest_populates_mandatory_rules_payload_key(monkeypatch):
    """With an LLM provider mocked, ingest_guidelines_file surfaces
    the extracted mandatory rules verbatim under the payload key."""
    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True, raising=False)
    monkeypatch.setattr(
        _llm, "generate_json",
        lambda *a, **kw: {
            "mandatory_rules": [
                "The strapline 'Swim ACME' MUST always appear in the caption.",
                "NEVER refer to the club as 'ACME SC'.",
            ]
        },
        raising=False,
    )
    txt = (
        b"Brand guidelines for ACME Swim Club.\n"
        b"The strapline 'Swim ACME' MUST always appear in the caption.\n"
        b"NEVER refer to the club as 'ACME SC'."
    )
    payload = ingest_guidelines_file("guidelines.txt", txt)
    assert "brand_guidelines_mandatory_rules" in payload
    rules = payload["brand_guidelines_mandatory_rules"]
    assert isinstance(rules, list)
    assert any("MUST" in r for r in rules)
    assert any("NEVER" in r for r in rules)


def test_ingest_returns_empty_rules_when_no_text():
    payload = ingest_guidelines_file("empty.txt", b"")
    assert payload["brand_guidelines_mandatory_rules"] == []


# ---------------------------------------------------------------------------
# brand_context_for_llm puts mandatory rules at the TOP with override framing
# ---------------------------------------------------------------------------

def test_mandatory_rules_appear_first_in_context():
    prof = ClubProfile(
        profile_id="acme",
        display_name="ACME Swim Club",
        brand_guidelines_mandatory_rules=[
            "The strapline 'Swim ACME' MUST always appear in the caption.",
            "NEVER refer to the club as 'ACME SC'.",
        ],
        brand_voice_summary="ACME is a community-focused club.",
        brand_keywords=["community", "grassroots"],
    )
    ctx = brand_context_for_llm(prof)
    # The mandatory rules block is at the TOP
    assert ctx.startswith("=== NON-NEGOTIABLE RULES")
    # Identity follows, not before
    identity_pos = ctx.find("You are writing for")
    rules_pos = ctx.find("=== NON-NEGOTIABLE RULES")
    assert rules_pos < identity_pos
    # Verbatim rules appear
    assert "The strapline 'Swim ACME' MUST always appear" in ctx
    assert "NEVER refer to the club as 'ACME SC'." in ctx
    # Override framing is present
    assert "override every other instruction" in ctx
    # Compliance recheck appended
    assert "re-read the NON-NEGOTIABLE RULES" in ctx


def test_no_mandatory_rules_means_no_top_block():
    prof = ClubProfile(
        profile_id="acme",
        display_name="ACME Swim Club",
        brand_voice_summary="ACME is a community-focused club.",
    )
    ctx = brand_context_for_llm(prof)
    assert "NON-NEGOTIABLE RULES" not in ctx
    assert "re-read the NON-NEGOTIABLE RULES" not in ctx
    # Identity still leads
    assert "You are writing for **ACME Swim Club**" in ctx


def test_guidelines_now_precede_dna():
    """Reordering: uploaded guidelines outrank website-derived DNA."""
    prof = ClubProfile(
        profile_id="acme",
        display_name="ACME Swim Club",
        brand_guidelines={
            "summary": "Confident, data-led voice.",
            "tone_dos": ["Lead with the result."],
        },
        brand_voice_summary="A community-focused, friendly club.",
    )
    ctx = brand_context_for_llm(prof)
    g_pos = ctx.find("Brand guidelines")
    dna_pos = ctx.find("About the organisation")
    assert g_pos != -1 and dna_pos != -1
    assert g_pos < dna_pos, (
        "Guidelines must lead website DNA in the system prompt "
        "(was the section order regressed?)"
    )


def test_mandatory_rules_truncate_at_25():
    rules = [f"Rule {i}: MUST do thing {i}." for i in range(50)]
    prof = ClubProfile(
        profile_id="acme",
        display_name="ACME",
        brand_guidelines_mandatory_rules=rules,
    )
    ctx = brand_context_for_llm(prof)
    # 25-cap renders rules 1..25; rule 26 should not appear
    assert "Rule 24: MUST" in ctx
    assert "Rule 49: MUST" not in ctx
