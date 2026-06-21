"""Roadmap 1.12 build 2 — Brand Check (deterministic) + Brand Assist (AI).

The scorer must reuse the existing colour-science maths and stay deterministic;
the advisory + auto-fix layers must honest-error without a provider and route
every proposed fix through the P6.2 ``apply_patch`` gate.
"""

from __future__ import annotations

import pytest

from mediahub.brand.check import (
    BrandCheckReport,
    advise,
    autofix,
    check_brief,
)
from mediahub.brand.kits import BrandKitRef
from mediahub.creative_brief.generator import CreativeBrief

# A palette that clears the APCA legibility gate (same one the patch tests use).
_GOOD_PALETTE = {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"}


def _brief(**over) -> CreativeBrief:
    base = dict(
        id="cb_src",
        content_item_id="swim_1",
        profile_id="club",
        achievement_summary="",
        objective="",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="data-led",
        layout_template="split_diagonal_hero",
        inspiration_pattern_id="",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={"headline_line1": "OLD"},
        palette=dict(_GOOD_PALETTE),
        format_priority=["story"],
    )
    base.update(over)
    return CreativeBrief(**base)


def _kit(**over) -> BrandKitRef:
    base = dict(kit_id="k1", name="Club", role="primary", palette=dict(_GOOD_PALETTE))
    base.update(over)
    return BrandKitRef(**base)


@pytest.fixture(autouse=True)
def _no_provider(monkeypatch):
    # Default: no LLM configured, so the AI layers honest-error unless a test
    # explicitly mocks generate_json.
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


# ---- deterministic scorer ---------------------------------------------


def test_on_brand_brief_passes_every_check():
    report = check_brief(_brief(), _kit())
    assert isinstance(report, BrandCheckReport)
    assert report.passed
    assert report.score >= 0.8
    checks = {f.check for f in report.findings}
    assert checks == {"palette", "contrast", "fonts", "logo"}


def test_off_palette_colour_is_flagged():
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    report = check_brief(brief, _kit())
    pal = next(f for f in report.findings if f.check == "palette")
    assert not pal.passed
    assert any(o.lower() == "#ff00ff" for o in pal.offenders)
    assert not report.passed


def test_locked_palette_surfaces_as_locked_failure():
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    kit = _kit(locks=["palette"])
    report = check_brief(brief, kit)
    locked = [f.check for f in report.locked_failures]
    assert "palette" in locked


def test_unlocked_off_palette_is_not_an_approval_blocker():
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    report = check_brief(brief, _kit())  # palette NOT locked
    pal = next(f for f in report.findings if f.check == "palette")
    # The palette drift is reported but, because the kit hasn't locked the
    # palette token, it is not an approval blocker on its own.
    assert not pal.passed
    assert not pal.locked
    assert pal not in report.locked_failures


def test_contrast_is_reported_but_not_a_kit_lock():
    # Contrast is reported as a finding, but it is not a lockable kit token —
    # legibility is enforced at render time, so it never gates approval here.
    report = check_brief(_brief(), _kit(locks=["palette", "fonts", "logo"]))
    contrast = next(f for f in report.findings if f.check == "contrast")
    assert contrast.locked is False


def test_font_mismatch_flagged_only_when_kit_pins_a_pairing():
    # kit pins a different pairing → fail
    kit = _kit(font_pairing="poppins-roboto")
    brief = _brief(typography_pair="anton-inter")
    fonts = next(f for f in check_brief(brief, kit).findings if f.check == "fonts")
    assert not fonts.passed
    # kit pins nothing → pass
    fonts2 = next(f for f in check_brief(brief, _kit()).findings if f.check == "fonts")
    assert fonts2.passed


def test_report_to_dict_shape():
    d = check_brief(_brief(), _kit()).to_dict()
    assert set(d) >= {"kit_id", "passed", "score", "findings", "locked_failures", "explanation"}
    assert isinstance(d["findings"], list)


def test_check_accepts_brief_dict():
    report = check_brief(_brief().to_dict(), _kit())
    assert report.findings  # coerced from dict, not empty


# ---- AI advisory (honest-error) ---------------------------------------


def test_advise_honest_error_without_provider():
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    report = check_brief(brief, _kit())
    res = advise(report, brief, _kit())
    assert res.available is False
    assert res.notes == []


def test_advise_skips_llm_when_already_on_brand():
    report = check_brief(_brief(), _kit())
    res = advise(report, _brief(), _kit())
    assert res.available is True
    assert res.notes == []
    assert "on-brand" in res.message.lower()


def test_advise_returns_notes_with_mocked_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "generate_json", lambda *a, **k: {"notes": ["Use the kit accent."]})
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    report = check_brief(brief, _kit())
    res = advise(report, brief, _kit())
    assert res.available is True
    assert res.notes == ["Use the kit accent."]


# ---- AI auto-fix (honest-error, routed through apply_patch) ------------


def test_autofix_honest_error_without_provider():
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    res = autofix(brief, _kit())
    assert res.available is False
    assert res.changed is False


def test_autofix_noop_when_on_brand():
    res = autofix(_brief(), _kit())
    assert res.available is True
    assert res.changed is False
    assert "on-brand" in res.message.lower()


def test_autofix_applies_validated_patch(monkeypatch):
    from mediahub.media_ai import llm as _llm

    # Model proposes a mood change (a safe, always-valid op) for an off-brand card.
    monkeypatch.setattr(
        _llm,
        "generate_json",
        lambda *a, **k: {"ops": [{"kind": "set_mood", "mood": "bold"}]},
    )
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    res = autofix(brief, _kit())
    assert res.available is True
    assert res.changed is True
    assert res.brief.mood == "bold"
    # the source brief was not mutated (apply_patch works on a copy)
    assert brief.mood == ""


def test_autofix_rejects_illegible_patch_via_gate(monkeypatch):
    from mediahub.media_ai import llm as _llm

    # A hallucinated op kind is dropped at parse; nothing illegible is painted.
    monkeypatch.setattr(
        _llm,
        "generate_json",
        lambda *a, **k: {"ops": [{"kind": "obliterate_brand"}]},
    )
    brief = _brief(palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FF00FF"})
    res = autofix(brief, _kit())
    assert res.available is True
    assert res.changed is False  # nothing valid to apply
