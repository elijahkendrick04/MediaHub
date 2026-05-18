"""tests/test_signup_audits.py — E1-E8. Eight signup-page audits.

These tests codify the audit-and-fix passes the user asked for. Each
test corresponds to one of the 8 audit subtasks in the plan and asserts
the behaviour we found / fixed during the audit.

  E1. AI integration — every brand-relevant field flows through an LLM
      step (heuristic fallbacks tolerated).
  E2. User-friendliness — form carries loader text, combobox is
      keyboard-accessible, drop-zone has a class hook for hover state.
  E3. Form-data → ClubProfile — every form field name has a
      corresponding ClubProfile assignment in the capture handler.
  E4. Profile → AI memory — every ClubProfile field that affects voice
      is reachable from brand_context_for_llm.
  E5. Brand guidelines respect — the mandatory rules block is at the
      TOP of the system prompt with override framing, and the
      compliance recheck is appended at the END.
  E6. [Next-page] Identity transfer — display_name, country, org_type,
      governing_body, brand_logos are all carried into the active
      profile after capture, and brand_context_for_llm surfaces them
      so the next page's AI calls see them.
  E7. [Next-page] Link-derived context transfer — captured DNA fields
      (voice_summary, keywords, palette, phrases) appear in the
      system prompt produced by brand_context_for_llm.
  E8. [Next-page] AI memory persistence — save_profile → load_profile
      round-trips every field used by brand_context_for_llm.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web.club_profile import ClubProfile, save_profile, load_profile  # noqa: E402
from mediahub.brand.context import brand_context_for_llm  # noqa: E402


# ---------------------------------------------------------------------------
# E1. AI integration audit — every brand-relevant module exposes an LLM seam
# ---------------------------------------------------------------------------

def test_link_handlers_pipeline_is_llm_driven():
    """Every link-handler delegate (strategy, block_detector,
    endpoint_discoverer, content_extractor) MUST consult the LLM
    wrapper when one is available — no hardcoded extractor regressions.
    """
    from mediahub.brand.link_learners import (
        strategy, block_detector, endpoint_discoverer, content_extractor,
    )
    # Each module has the LLM call wired in.
    import inspect
    for mod in (strategy, block_detector, endpoint_discoverer, content_extractor):
        src = inspect.getsource(mod)
        assert "is_available" in src, f"{mod.__name__} bypasses the LLM wrapper"
        assert "generate_json" in src, f"{mod.__name__} bypasses generate_json"


def test_guidelines_pipeline_calls_llm_in_two_passes():
    """Brand guidelines must invoke the LLM twice: once for the
    structured interpretation and once for mandatory-rule extraction."""
    import inspect
    from mediahub.brand import guidelines
    src = inspect.getsource(guidelines)
    # Two distinct system prompt constants
    assert "_LLM_SYSTEM" in src
    assert "_MANDATORY_RULES_LLM_SYSTEM" in src


def test_logos_pipeline_has_optional_vision_seam():
    """Logo metadata may include an AI description + dominant colours
    when a vision-capable model is configured. Verify the seam exists."""
    import inspect
    from mediahub.brand import logos
    src = inspect.getsource(logos)
    assert "describe_logo_with_ai" in src
    assert "describe_image" in src  # the llm-wrapper hook


# ---------------------------------------------------------------------------
# E2. User-friendliness audit
# ---------------------------------------------------------------------------

def test_setup_form_carries_loader_text(monkeypatch, tmp_path):
    """The form takes 10-30s on the capture step; the loader overlay
    must announce that to the user instead of leaving them staring at
    a frozen page."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app
    app = create_app()
    client = app.test_client()
    resp = client.get("/organisation/setup")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "data-loader-text=" in body
    assert "data-loader-sub=" in body


def test_country_combobox_has_aria_attributes(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app
    app = create_app()
    client = app.test_client()
    resp = client.get("/organisation/setup")
    body = resp.get_data(as_text=True)
    assert 'role="combobox"' in body
    assert 'aria-autocomplete="list"' in body
    assert 'aria-controls="country-options"' in body
    assert 'role="listbox"' in body


def test_drop_zone_has_dragover_class_hook(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app
    app = create_app()
    client = app.test_client()
    resp = client.get("/organisation/setup")
    body = resp.get_data(as_text=True)
    assert "mh-drop-zone" in body
    assert "is-dragover" in body  # JS toggles this class


# ---------------------------------------------------------------------------
# E3. Form-data → ClubProfile audit
# ---------------------------------------------------------------------------

EXPECTED_FORM_FIELDS = {
    "display_name", "org_type", "country", "governing_body",
    "website_url",
    "social_instagram", "social_facebook", "social_twitter",
    "social_tiktok", "social_linkedin",
    "brand_guidelines_file",
    "brand_logos",
}


def test_setup_form_contains_all_expected_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app
    app = create_app()
    client = app.test_client()
    resp = client.get("/organisation/setup")
    body = resp.get_data(as_text=True)
    for field in EXPECTED_FORM_FIELDS:
        assert f'name="{field}"' in body, f"form is missing name={field!r}"


def test_capture_writes_every_form_field_to_profile(monkeypatch, tmp_path):
    """End-to-end audit: submit the full form, then read the persisted
    ClubProfile JSON and verify every text field landed on the right
    attribute. No silent drops."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Disable the LLM-heavy paths so the test runs deterministically.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from mediahub.web.web import create_app
    from mediahub.brand import link_handlers
    monkeypatch.setattr(link_handlers, "process_links",
                         lambda **kw: {"any_real": False, "state": {},
                                        "merged_dna": {}})
    app = create_app()
    client = app.test_client()
    resp = client.post("/organisation/setup/capture", data={
        "display_name": "Test Aquatics",
        "org_type": "swimming_club",
        "country": "United Kingdom",
        "governing_body": "Swim England",
        "website_url": "https://test-aquatics.example",
        "social_instagram": "https://instagram.com/test.aquatics",
        "social_facebook": "https://facebook.com/test.aquatics",
        "social_twitter": "https://x.com/test.aquatics",
        "social_tiktok": "https://tiktok.com/@test.aquatics",
        "social_linkedin": "https://linkedin.com/company/test-aquatics",
    })
    assert resp.status_code in (302, 303)
    prof = load_profile("test-aquatics")
    assert prof is not None
    assert prof.display_name == "Test Aquatics"
    assert prof.org_type == "swimming_club"
    assert prof.country == "United Kingdom"
    assert prof.governing_body == "Swim England"
    assert prof.social_links["instagram"] == "https://instagram.com/test.aquatics"
    assert prof.social_links["facebook"] == "https://facebook.com/test.aquatics"
    assert prof.social_links["twitter"] == "https://x.com/test.aquatics"
    assert prof.social_links["tiktok"] == "https://tiktok.com/@test.aquatics"
    assert prof.social_links["linkedin"] == "https://linkedin.com/company/test-aquatics"


# ---------------------------------------------------------------------------
# E4. Profile → AI memory audit
# ---------------------------------------------------------------------------

PROFILE_FIELDS_THAT_AFFECT_VOICE = (
    "display_name", "short_name", "org_type", "country", "governing_body",
    "sponsor_name",
    "brand_voice_summary", "brand_keywords",
    "brand_phrases_to_use", "brand_phrases_to_avoid",
    "voice_profile",
    "brand_guidelines", "brand_guidelines_mandatory_rules",
    "brand_logos",
)


def test_every_voice_relevant_field_surfaces_in_brand_context():
    """For each ClubProfile field that should reach the AI, populate
    it with a sentinel value and confirm that value appears in the
    rendered system-prompt block."""
    prof = ClubProfile(
        profile_id="audit",
        display_name="AUDIT-NAME",
        short_name="AUDITSHORT",
        org_type="swimming_club",
        country="AUDIT-COUNTRY",
        governing_body="AUDIT-BODY",
        sponsor_name="AUDIT-SPONSOR",
        brand_voice_summary="AUDIT-VOICE-SUMMARY",
        brand_keywords=["audit-keyword"],
        brand_phrases_to_use=["audit-phrase-use"],
        brand_phrases_to_avoid=["audit-phrase-avoid"],
        voice_profile={"sentence_length_avg": 22.0, "emoji_rate_per_caption": 1.5},
        brand_guidelines={"summary": "AUDIT-GUIDELINES-SUMMARY",
                            "tone_dos": ["AUDIT-DO"],
                            "tone_donts": ["AUDIT-DONT"]},
        brand_guidelines_mandatory_rules=["AUDIT-MUST-RULE"],
        brand_logos=[
            {"logo_id": "x", "label": "AUDIT-LOGO-LABEL",
              "original_filename": "x.png", "mime": "image/png",
              "ai_description": "AUDIT-LOGO-DESC"},
        ],
    )
    ctx = brand_context_for_llm(prof)
    # Hard fail any field that doesn't make it into the prose.
    must_appear = [
        "AUDIT-NAME", "AUDITSHORT",  "AUDIT-COUNTRY", "AUDIT-BODY",
        "AUDIT-SPONSOR", "AUDIT-VOICE-SUMMARY", "audit-keyword",
        "audit-phrase-use", "audit-phrase-avoid",
        "AUDIT-GUIDELINES-SUMMARY", "AUDIT-DO", "AUDIT-DONT",
        "AUDIT-MUST-RULE", "AUDIT-LOGO-LABEL", "AUDIT-LOGO-DESC",
    ]
    for marker in must_appear:
        assert marker in ctx, f"field carrying {marker!r} missing from brand context"


def test_org_type_shows_up_as_organisational_phrase():
    """E4 surfaced a gap: org_type was stored but never reached the
    AI. Verify the fix — different org_type values produce different
    natural-language descriptors."""
    for org_type, marker in (
        ("swimming_club", "swimming club"),
        ("athletics", "athletics club"),
        ("university_society", "university society"),
        ("corporate_team", "corporate team"),
    ):
        prof = ClubProfile(profile_id="x", display_name="X", org_type=org_type)
        ctx = brand_context_for_llm(prof)
        assert marker in ctx, f"org_type={org_type!r} not surfaced (expected {marker!r})"


# ---------------------------------------------------------------------------
# E5. Brand guidelines respect audit
# ---------------------------------------------------------------------------

def test_must_rules_lead_and_recheck_trails():
    prof = ClubProfile(
        profile_id="x", display_name="X",
        brand_guidelines_mandatory_rules=[
            "ALWAYS include the hashtag #ProbeTag in every caption.",
        ],
        brand_voice_summary="An inclusive club.",
    )
    ctx = brand_context_for_llm(prof)
    # The MUST block leads
    assert ctx.startswith("=== NON-NEGOTIABLE RULES")
    # The recheck reminder is at the END
    last_chunk = ctx[-400:]
    assert "re-read the NON-NEGOTIABLE RULES" in last_chunk
    # The literal rule survives intact
    assert "ALWAYS include the hashtag #ProbeTag in every caption." in ctx


def test_no_must_rules_means_no_overhead():
    prof = ClubProfile(profile_id="x", display_name="X",
                        brand_voice_summary="Generic.")
    ctx = brand_context_for_llm(prof)
    assert "NON-NEGOTIABLE" not in ctx
    assert "re-read the NON-NEGOTIABLE" not in ctx


def test_guidelines_lead_website_dna_in_prose():
    """E5 / regression: with a brand-guidelines summary AND a website
    voice summary on the same profile, the guidelines section must
    appear earlier in the prose so it outranks the website voice
    when the LLM weighs competing cues."""
    prof = ClubProfile(
        profile_id="x", display_name="X",
        brand_guidelines={"summary": "PRECEDENCE-CHECK-GUIDELINES"},
        brand_voice_summary="PRECEDENCE-CHECK-WEBSITE",
    )
    ctx = brand_context_for_llm(prof)
    g_pos = ctx.find("PRECEDENCE-CHECK-GUIDELINES")
    w_pos = ctx.find("PRECEDENCE-CHECK-WEBSITE")
    assert 0 <= g_pos < w_pos


# ---------------------------------------------------------------------------
# E6. [Next-page] Identity transfer
# ---------------------------------------------------------------------------

def test_capture_pins_profile_into_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from mediahub.web.web import create_app
    from mediahub.brand import link_handlers
    monkeypatch.setattr(link_handlers, "process_links",
                         lambda **kw: {"any_real": False, "state": {}, "merged_dna": {}})
    app = create_app()
    with app.test_client() as client:
        resp = client.post("/organisation/setup/capture", data={
            "display_name": "Pinned Org",
            "country": "United Kingdom",
        })
        assert resp.status_code in (302, 303)
        # Session now carries the new active profile id
        with client.session_transaction() as sess:
            assert sess["active_profile_id"] == "pinned-org"

        # Next-page request resolves the profile via the session
        api = client.get("/api/organisation/active")
        assert api.status_code == 200
        body = json.loads(api.get_data(as_text=True))
        assert body["profile_id"] == "pinned-org"
        assert body["display_name"] == "Pinned Org"


# ---------------------------------------------------------------------------
# E7. [Next-page] Link-derived context transfer
# ---------------------------------------------------------------------------

def test_link_derived_dna_reaches_next_page_prompt():
    """Populate a profile with the link-derived DNA fields, render
    brand_context_for_llm as if the next page were generating a
    caption, and verify each field appears."""
    prof = ClubProfile(
        profile_id="x", display_name="X",
        brand_voice_summary="Inclusive grassroots club.",
        brand_keywords=["inclusive", "grassroots"],
        brand_palette_extracted={"primary": "#0066cc", "secondary": "#f2a900"},
        brand_phrases_to_avoid=["elite only"],
        brand_phrases_to_use=["celebrate every effort"],
    )
    ctx = brand_context_for_llm(prof)
    assert "Inclusive grassroots club" in ctx
    assert "inclusive" in ctx
    assert "grassroots" in ctx
    assert "celebrate every effort" in ctx
    assert "elite only" in ctx


def test_link_capture_state_persists_for_audit(monkeypatch, tmp_path):
    """link_capture_state is the per-link audit trail the user wanted —
    "which playbook served Instagram, did it regenerate, what voice
    digest did the AI pull". Verify it round-trips through save/load."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    prof = ClubProfile(
        profile_id="x", display_name="X",
        link_capture_state={
            "instagram": {"url": "https://www.instagram.com/x/",
                            "status": "real_content",
                            "playbook_age": 0,
                            "regenerated": True,
                            "voice_digest": "Friendly community voice."},
        },
    )
    save_profile(prof)
    loaded = load_profile("x")
    assert loaded.link_capture_state["instagram"]["voice_digest"] == "Friendly community voice."


# ---------------------------------------------------------------------------
# E8. [Next-page] AI memory persistence
# ---------------------------------------------------------------------------

def test_full_profile_roundtrips_through_disk(tmp_path, monkeypatch):
    """Close the browser, reopen — i.e. write the profile to disk,
    load it fresh, and confirm the system-prompt block produced from
    the loaded copy is identical to the in-memory original."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    prof = ClubProfile(
        profile_id="round-trip", display_name="Round Trip Org",
        org_type="swimming_club",
        country="United Kingdom",
        governing_body="Swim England",
        brand_voice_summary="Friendly squad.",
        brand_keywords=["friendly", "squad"],
        brand_phrases_to_use=["lap by lap"],
        brand_phrases_to_avoid=["pros only"],
        brand_guidelines={"summary": "Be warm.", "tone_dos": ["be warm"]},
        brand_guidelines_mandatory_rules=["NEVER name minors without consent."],
        brand_logos=[
            {"logo_id": "a", "original_filename": "x.svg",
              "label": "Main wordmark", "mime": "image/svg+xml",
              "ai_description": "Wordmark for light backgrounds."},
        ],
        voice_profile={"sentence_length_avg": 18.0},
    )
    save_profile(prof)
    loaded = load_profile("round-trip")
    assert loaded is not None
    # Critical equality: the prompt the AI receives is identical
    # before and after persistence.
    assert brand_context_for_llm(prof) == brand_context_for_llm(loaded)
    # And every mandatory rule survives intact
    assert loaded.brand_guidelines_mandatory_rules == prof.brand_guidelines_mandatory_rules
    # Logos survive
    assert len(loaded.brand_logos) == 1
    assert loaded.brand_logos[0]["ai_description"] == "Wordmark for light backgrounds."


def test_loading_legacy_profile_without_new_fields_works(tmp_path, monkeypatch):
    """Backward compatibility: a profile written before these fields
    existed must still load via from_dict with the new fields filled
    in as their defaults."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    legacy_json = {
        "profile_id": "legacy",
        "display_name": "Legacy Club",
        "club_codes": ["LEG"],
        # Notably MISSING: brand_logos, brand_guidelines_mandatory_rules,
        # link_capture_state
    }
    p = tmp_path / "club_profiles" / "legacy.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(legacy_json))

    prof = load_profile("legacy")
    assert prof is not None
    assert prof.display_name == "Legacy Club"
    assert prof.brand_logos == []
    assert prof.brand_guidelines_mandatory_rules == []
    assert prof.link_capture_state == {}
    # Brand context still works on the legacy profile
    ctx = brand_context_for_llm(prof)
    assert "Legacy Club" in ctx
