"""Generation Engine v2 — Tier A (archetype library + deterministic picker).

Covers the SEQ-1 wiring: the ``layouts/v2`` archetype registry, the seeded
picker, the ``MEDIAHUB_GEN_V2`` gate, the brand-role / autofit / saliency CSS
injection, and the flag-off-is-unchanged invariant. The heavy Playwright render
is exercised once and skipped when Chromium is unavailable; everything else runs
without a browser by stubbing the single ``render_html_to_png`` call.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult

# The PAR-7 placeholder allow-list every v2 archetype must stay within.
_ALLOWED_PLACEHOLDERS = {
    "ATHLETE_FULL_NAME",
    "ATHLETE_FIRST_NAME",
    "ATHLETE_SURNAME_DISPLAY",
    "EVENT_NAME",
    "RESULT_VALUE",
    "ACHIEVEMENT_LABEL",
    "MEET_NAME",
    "CLUB_FULL",
    "HERO_STAT",
    "LOGO_BLOCK",
    "ATHLETE_IMG_BLOCK",
    # Per-frame cutout custom property (--mh-athlete-img) for contact_sheet,
    # filled by render.py.
    "ATHLETE_IMG_VAR",
    "ACCENT_DECORATION",
    "SPONSOR_BLOCK",
    "WIDTH",
    "HEIGHT",
    "BASE_CSS",
    # Conditional photo/text wrappers filled by render.py (they comment out the
    # block on the path that shouldn't render) — used by contact_sheet's per-frame
    # cutouts so an empty frame never emits a broken <img>.
    "PHOTO_ONLY_OPEN",
    "PHOTO_ONLY_CLOSE",
    "TEXT_ONLY_OPEN",
    "TEXT_ONLY_CLOSE",
    # M11 — data-led slots: the secondary-stat chip row and the honest
    # before/after PB bars (both collapse to "" when the facts are absent).
    "STAT_CHIPS",
    "PB_BARS",
    # M14 — matte-gate fallback marker for the layered cutout archetypes
    # (" mh-photo-flat" when the original photo honestly ships instead).
    "PHOTO_FLAT_CLASS",
    # F7 (Canva gap analysis) — the seeded overlap accent that straddles a
    # declared mh-anchor edge (badge/tab/rule/tape); "" for a bare/legacy card.
    "OVERLAP_ACCENT",
}


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _eval(layout="individual_hero"):
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief(*, seed=0, swimmer="Eira Hughes", result="2:08.41"):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": result,
        },
    }
    return gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="test",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=seed,
    )


# --------------------------------------------------------------------------- #
# Registry + picker (no rendering)
# --------------------------------------------------------------------------- #


def test_registry_lists_six_distinct_archetypes():
    names = archetypes.list_archetypes()
    assert len(names) >= 6, names
    assert names == sorted(names)  # stable order for a deterministic picker
    assert len(set(names)) == len(names)


def test_v2_is_default_on_with_killswitch(monkeypatch):
    # v2 is the production default: unset (or anything but a kill value) is ON.
    monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
    assert archetypes.is_enabled() is True
    for val in ("1", "true", "on", "yes", "TRUE", "anything"):
        monkeypatch.setenv("MEDIAHUB_GEN_V2", val)
        assert archetypes.is_enabled() is True
    # the kill-switch values fall back to the legacy engine
    for val in ("0", "false", "off", "no", "OFF"):
        monkeypatch.setenv("MEDIAHUB_GEN_V2", val)
        assert archetypes.is_enabled() is False


def test_picker_is_deterministic_and_spreads():
    names = archetypes.list_archetypes()
    # stable per seed
    assert archetypes.pick_archetype(3) == archetypes.pick_archetype(3)
    # spreads across the whole library over distinct seeds
    picks = {archetypes.pick_archetype(s) for s in range(len(names) * 2)}
    assert picks == set(names)


def test_picker_avoiding_walks_past_recent():
    names = archetypes.list_archetypes()
    # empty recents → identical to the strict seeded pick
    first = archetypes.pick_archetype_avoiding(4, [])
    assert first == archetypes.pick_archetype(4)
    # the seeded pick was recently used → step to a different archetype
    second = archetypes.pick_archetype_avoiding(4, [first])
    assert second in names and second != first
    # deterministic: same seed + same recents → same pick
    assert archetypes.pick_archetype_avoiding(4, [first]) == second
    # everything recently used → degrade to the strict seeded pick
    assert archetypes.pick_archetype_avoiding(4, names) == archetypes.pick_archetype(4)


# --------------------------------------------------------------------------- #
# Archetype authoring convention (PAR-7 hygiene)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", archetypes.list_archetypes())
def test_archetype_follows_convention(name):
    raw = (archetypes.V2_DIR / f"{name}.html").read_text(encoding="utf-8")
    # {{BASE_CSS}} present
    assert "{{BASE_CSS}}" in raw
    # brand colour only via --mh-* roles: no hex colour literal anywhere
    assert re.search(r"#[0-9a-fA-F]{3,6}\b", raw) is None, f"{name} has a hex literal"
    assert "var(--mh-" in raw
    # every placeholder is on the allow-list
    for ph in set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", raw)):
        assert ph in _ALLOWED_PLACEHOLDERS, f"{name} uses unknown placeholder {ph}"


@pytest.mark.parametrize("name", archetypes.list_archetypes())
def test_archetype_has_authoring_notes(name):
    # GENERATION.md §7: every archetype ships a one-paragraph <name>.notes.md
    # describing the composition and when the director should pick it — the
    # notes feed the SEQ-2 design-spec director's archetype catalog.
    notes = archetypes.V2_DIR / f"{name}.notes.md"
    assert notes.exists(), f"{name} is missing its .notes.md (director catalog entry)"
    text = notes.read_text(encoding="utf-8").strip()
    assert len(text) > 200, f"{name}.notes.md is too thin to brief the director"


@pytest.mark.parametrize("name", archetypes.list_archetypes())
def test_director_note_extracted_for_every_archetype(name):
    # The director's catalog line is derived from the notes (PAR-7's purpose):
    # bounded, plain-text, and substantive for every archetype in the library.
    note = archetypes.director_note(name)
    assert note, f"{name}: director_note extracted nothing from its notes"
    assert len(note) <= archetypes._NOTE_MAX_CHARS + 2, f"{name}: note unbounded"
    assert "**" not in note and "`" not in note, f"{name}: markdown leaked into the prompt line"
    assert len(note) >= 60, f"{name}: note too thin to guide an archetype choice"


# --------------------------------------------------------------------------- #
# Generator integration: flag flips the layout to a v2 archetype
# --------------------------------------------------------------------------- #


def test_generator_uses_legacy_family_with_killswitch(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")  # kill-switch → legacy engine
    brief = _brief()
    assert brief.layout_template not in archetypes.list_archetypes()


def test_generator_swaps_to_v2_when_flag_on(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    chosen = {_brief(seed=s).layout_template for s in range(12)}
    # every chosen layout is a real v2 archetype, and a pack spans them all
    assert chosen <= set(archetypes.list_archetypes())
    assert len(chosen) >= 6


def test_multifact_recap_keeps_v1_list_layout_when_family_pinned(monkeypatch):
    """A caption-only / athlete-spotlight-composite graphic pins
    ``allowed_families=["text_led_recap"]`` and supplies a BULLET LIST of
    several moments with no single hero result. No v2 single-subject archetype
    can render that list (``_fill_v2_archetype`` fills only one
    ``RESULT_VALUE``/``HERO_STAT``), so the v2 override must be skipped and the
    v1 ``text_led_recap`` layout — headline + bullets + stat strip — kept;
    otherwise the card renders blank. Regression guard for the empty
    athlete-spotlight graphic (the bullets the caller supplied disappeared when
    the director overrode the layout to e.g. ``index_card``)."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")  # v2 on (the default engine)
    from mediahub.creative_brief.generator import VariationProfile

    item = {
        "id": "athlete_spotlight",
        "post_angle": "recap_mention",
        "achievement": {"post_angle": "recap_mention", "confidence": 0.85},
        "graphic_text": {
            "headline_line1": "EIRA",
            "headline_line2": "SPOTLIGHT",
            "bullets": ["50m Breaststroke — 27.98 · PB", "100m Butterfly — 51.81 · 🥉"],
            "primary_hook": "SPOTLIGHT",
            "stats": {"athlete": "Eira Hughes", "moments": "5 approved"},
        },
    }
    vp = VariationProfile(
        layout_family="text_led_recap",
        photo_treatment="no-photo",
        background_style="clean",
        accent_style="minimal",
        composition="center",
    )
    brief = gen_brief(
        item,
        _eval(layout="text_led_recap"),
        _brand(),
        profile_id="test",
        meet_name="Manchester Open",
        variation_seed=0,
        variation_profile=vp,
        use_ai_director=True,
        allowed_families=["text_led_recap"],
    )
    # The v1 list layout is kept (NOT swapped to a v2 single-subject archetype)…
    assert brief.layout_template == "text_led_recap"
    assert brief.layout_template not in archetypes.list_archetypes()
    # …and the bullet list it needs survived onto the brief.
    assert brief.text_layers.get("bullets")
    assert not str(brief.text_layers.get("result_value") or "").strip()


def _brief_for_item(item, *, seed=None, recent=None):
    # seed=None mirrors the bulk-pack / fresh-regenerate call shape (no
    # explicit seed → the floor derives one from the card id); pass an int
    # (including 0) for the exact ?stable / ?variation_seed=N contract.
    return gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="test",
        meet_name="Manchester Open",
        variation_seed=seed,
        recent_signatures=recent,
    )


def test_pack_without_seeds_still_spreads_archetypes(monkeypatch):
    """The bulk-pack call shape (attach_visuals_to_pack) passes NO variation
    seed. The floor must derive a per-card seed from the card id so a pack
    still spreads across the library — not render one archetype 12 times."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    chosen = []
    for i in range(12):
        item = {
            "id": f"card-{i}",
            "post_angle": "individual_pb",
            "achievement": {
                "swimmer_name": "Eira Hughes",
                "event_name": "200m Freestyle",
                "result_time": "2:08.41",
            },
        }
        chosen.append(_brief_for_item(item).layout_template)
    assert set(chosen) <= set(archetypes.list_archetypes())
    assert len(set(chosen)) >= 6  # §8C archetype-diversity floor
    # …and the pick is stable per card (same id → same archetype on re-render)
    item0 = {
        "id": "card-0",
        "post_angle": "individual_pb",
        "achievement": {"swimmer_name": "Eira Hughes", "event_name": "200m Freestyle"},
    }
    assert _brief_for_item(item0).layout_template == chosen[0]


def test_pack_with_threaded_recents_avoids_seed_collisions(monkeypatch):
    """attach_visuals_to_pack threads each rendered signature into the next
    card's recents (a 6-deep window), so two cards whose id-hashes collide on
    the same archetype rotate apart. The structural guarantee — independent of
    library size — is that any 7 consecutive cards are pairwise distinct."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    recents: list[str] = []
    chosen = []
    for i in range(10):
        item = {
            "id": f"swim-{i:03d}",
            "post_angle": "individual_pb",
            "achievement": {
                "swimmer_name": "Eira Hughes",
                "event_name": "200m Freestyle",
                "result_time": "2:08.41",
            },
        }
        brief = _brief_for_item(item, recent=recents[-6:])
        chosen.append(brief.layout_template)
        recents.append(brief.variation_signature)
    for start in range(len(chosen) - 6):
        window = chosen[start : start + 7]
        assert len(set(window)) == 7, (start, window)
    assert len(set(chosen)) >= 7  # comfortably above the §8C 0.60 floor


def test_fresh_regenerate_rotates_without_a_provider(monkeypatch):
    """The regenerate route's no-LLM floor: no explicit seed plus the card's
    recent signatures must walk the library, not return the same archetype
    forever."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {"swimmer_name": "Eira Hughes", "event_name": "200m Freestyle"},
    }
    recents: list[str] = []
    seen = []
    for _ in range(6):
        brief = _brief_for_item(item, recent=recents[-6:])
        seen.append(brief.layout_template)
        recents.append(brief.variation_signature)
    assert len(set(seen)) == 6, seen  # six regenerates → six distinct archetypes


def test_explicit_seed_stays_reproducible_and_ignores_recents(monkeypatch):
    """?stable / ?variation_seed=N contract: an explicit seed is an exact pick,
    even when the history already contains that archetype."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    expected = archetypes.pick_archetype(5)
    brief = _brief(seed=5)
    assert brief.layout_template == expected
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {"swimmer_name": "Eira Hughes", "event_name": "200m Freestyle"},
    }
    again = _brief_for_item(item, seed=5, recent=[f"{expected}|#0E5BFF|gradient"])
    assert again.layout_template == expected


# --------------------------------------------------------------------------- #
# Full HTML assembly without a browser (stub the Playwright call)
# --------------------------------------------------------------------------- #


def _render_html(monkeypatch, tmp_path, brief):
    """Run render_brief but capture the assembled HTML instead of rasterising."""
    import mediahub.graphic_renderer.render as R

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=(1080, 1350))
    return captured["html"]


@pytest.mark.parametrize("seed", range(6))
def test_assembly_is_clean_on_both_engines(render_engine, monkeypatch, tmp_path, seed):
    """Clean HTML assembly on BOTH still engines (deep-review #132 parity).

    v2 is the production default engine, but the suite historically pinned the
    legacy v1 path, so the production render was under-tested. This runs the
    clean-assembly invariant from one body under each engine (``render_engine``
    parametrises v1/v2):

    * **Engine-invariant** — no raw ``{{…}}`` placeholder survives and the real
      meet name lands, on *either* engine.
    * **v2 (production)** — the generator picks a real ``layouts/v2`` archetype
      and the render injects the brand role tokens + autofit vars.
    * **v1 (legacy)** — the generator keeps a legacy family and the v2
      role-token block is absent (the legacy shape, guarded so parity can't
      silently start emitting it).

    No assertion the v2-only test made is dropped; the legacy path adds coverage.
    """
    brief = _brief(seed=seed)
    html = _render_html(monkeypatch, tmp_path, brief)
    # No raw placeholders survive — engine-invariant.
    assert "{{" not in html and "}}" not in html
    # Real content made it in — engine-invariant.
    assert "Manchester Open" in html
    if render_engine == "v2":
        # The production engine chose a real v2 archetype …
        assert brief.layout_template in archetypes.list_archetypes()
        # … and injected the brand role tokens + autofit vars.
        assert ":root{" in html
        for token in (
            "--mh-primary:",
            "--mh-accent:",
            "--mh-on-primary:",
            "--mh-fit-surname-px:",
            "--mh-fit-result-px:",
            "--mh-photo-pos:",
        ):
            assert token in html, f"{brief.layout_template} missing {token}"
    else:
        # Legacy engine: a legacy family, none of the v2 role-token block.
        assert brief.layout_template not in archetypes.list_archetypes()
        assert "--mh-fit-surname-px:" not in html


def test_autofit_shrinks_a_long_surname(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")

    def _surname_px(html):
        m = re.search(r"--mh-fit-surname-px:(\d+)px", html)
        assert m, "surname autofit var not found"
        return int(m.group(1))

    short = _render_html(monkeypatch, tmp_path, _brief(seed=0, swimmer="Mo Li"))
    # a genuinely long, wide surname can't fit at the 132px default in the box,
    # so autofit must shrink it rather than let it overflow
    long = _render_html(
        monkeypatch,
        tmp_path,
        _brief(seed=0, swimmer="Aleksandra Vandersloot-Chamberlain"),
    )
    short_px, long_px = _surname_px(short), _surname_px(long)
    assert short_px == 132  # short name keeps the layout's full default
    assert long_px < short_px  # long name autofits down — no overflow


def test_killswitch_renders_a_legacy_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")  # kill-switch → legacy engine
    brief = _brief()
    html = _render_html(monkeypatch, tmp_path, brief)
    # legacy engine: no v2 role-token block is injected
    assert "--mh-fit-surname-px:" not in html
    assert "{{" not in html


# --------------------------------------------------------------------------- #
# Regression guards (from code review)
# --------------------------------------------------------------------------- #


def test_darken_fallback_is_byte_identical_flag_off():
    """The v2 helpers must not shadow the module-level `_hex_to_rgb` and change
    `darken`/`lighten`'s malformed-input fallback — that would alter the legacy
    (flag-OFF) render path. Pre-PR `darken("")` is "#000000"."""
    from mediahub.graphic_renderer.render import darken, lighten

    assert darken("") == "#000000"
    assert lighten("") != "#0A2540"  # not the navy the duplicate helper returned


def test_single_colour_kit_accent_stays_legible():
    """A kit with only a primary (accent=None, secondary=#000000 by BrandKit
    default) must NOT collapse --mh-accent to black against a dark ground."""
    from mediahub.graphic_renderer.render import _mh_role_vars, _contrast_ratio

    kit = BrandKit(
        profile_id="x",
        display_name="X",
        primary_colour="#A30D2D",
        secondary_colour="#000000",
        short_name="X",
    )  # accent_colour defaults to None
    roles = _mh_role_vars({}, kit)
    assert _contrast_ratio(roles["--mh-accent"], roles["--mh-primary"]) >= 3.0


def test_contrasting_secondary_is_used_as_accent():
    """A navy+gold kit (no explicit accent) should still get the gold secondary
    as its accent — the legibility guard must not discard a good contrast."""
    from mediahub.graphic_renderer.render import _mh_role_vars

    kit = BrandKit(
        profile_id="x",
        display_name="X",
        primary_colour="#0A2540",
        secondary_colour="#F2C14E",
        short_name="X",
    )
    assert _mh_role_vars({}, kit)["--mh-accent"].upper() == "#F2C14E"


def test_fit_one_line_keeps_multiword_surname_on_one_line():
    """`white-space: nowrap` slots must be sized single-line: a multi-word
    surname has to FIT on one line at the returned px (no overflow/clip)."""
    from mediahub.graphic_renderer.render import _fit_one_line_px
    from mediahub.graphic_renderer.autofit import em_width

    box_w = 1080 * 0.86
    surname = "VAN DER BERG"
    px = _fit_one_line_px(
        surname, box_w, 1350 * 0.18, font_family="Anton", weight=400, min_px=44, max_px=132
    )
    assert em_width(surname, font_family="Anton", weight=400) * px <= box_w + 1


# --------------------------------------------------------------------------- #
# Medal tier, hero stat, and AI-background economy on the v2 path
# --------------------------------------------------------------------------- #


def _medal_item(place="1"):
    return {
        "id": "ci-medal",
        "post_angle": "medal_gold",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "place": place,
        },
    }


def test_medal_card_tints_v2_accent_with_the_metal(monkeypatch, tmp_path):
    """v1 makes a gold card READ gold (the colour is the information). The v2
    role resolver must do the same — APCA-gated, deep metal on light grounds."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    brief = _brief_for_item(_medal_item())
    html = _render_html(monkeypatch, tmp_path, brief)
    assert "--mh-accent:#FFD24A;" in html  # bright gold reads on the dark brand

    # On a light club ground the bright gold fails the gate → deep gold.
    import mediahub.graphic_renderer.render as R

    light = BrandKit(
        profile_id="light",
        display_name="Light SC",
        primary_colour="#F5F7FA",
        secondary_colour="#101820",
        short_name="LSC",
    )
    brief2 = gen_brief(
        _medal_item(),
        _eval(),
        light,
        profile_id="light",
        meet_name="Manchester Open",
        variation_seed=0,
    )
    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief2, output_dir=tmp_path / "light", size=(1080, 1350), brand_kit=light)
    assert "--mh-accent:#A77A07;" in captured["html"]


def test_hero_stat_filled_from_measured_drop_only(monkeypatch, tmp_path):
    """{{HERO_STAT}} carries a real measured fact (the detectors' drop_seconds)
    and stays empty when nothing was measured — never a fabricated number."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "raw_facts": {"drop_seconds": 2.4},
        },
    }
    brief = _brief_for_item(item)
    assert brief.text_layers.get("hero_stat") == "−2.40s on PB"
    html = _render_html(monkeypatch, tmp_path, brief)
    assert "−2.40s on PB" in html
    # no measured facts → the slot is empty (and the layout collapses it)
    assert _brief().text_layers.get("hero_stat", "") == ""


def test_tenth_place_is_not_a_medal(monkeypatch, tmp_path):
    """Tier detection parses the placing as a number: 10th/12th place must NOT
    tint the card gold (the old prefix match did exactly that)."""
    from mediahub.graphic_renderer.render import _detect_medal_tier

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    item = {
        "id": "ci-12th",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "place": "12",
        },
    }
    brief = _brief_for_item(item)
    assert _detect_medal_tier(brief) is None
    html = _render_html(monkeypatch, tmp_path, brief)
    assert "--mh-accent:#FFD24A;" not in html


def test_hero_stat_uses_placing_when_no_drop(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    item = {
        "id": "ci-2",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "place": "2",
        },
    }
    assert _brief_for_item(item).text_layers.get("hero_stat") == "2nd place"
    # on a medal angle the label already says it — don't repeat it in the slot
    assert _brief_for_item(_medal_item(place="1")).text_layers.get("hero_stat", "") == ""


def test_v2_render_never_fetches_the_ai_background(monkeypatch, tmp_path):
    """v2 archetypes have no {{AI_BG_URI}} slot, so the (paid) background
    fetch must not run for them even when the provider is configured."""
    import mediahub.visual.ai_background as ai_bg

    calls = []
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    monkeypatch.setattr(ai_bg, "is_available", lambda: True)
    monkeypatch.setattr(ai_bg, "background_data_uri_for", lambda *a, **k: calls.append(a) or None)
    _render_html(monkeypatch, tmp_path, _brief(seed=1))
    assert calls == []


# --------------------------------------------------------------------------- #
# One real Playwright render (skipped without Chromium)
# --------------------------------------------------------------------------- #


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                b = p.chromium.launch()
                b.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
def test_real_render_produces_pngs_for_all_archetypes(monkeypatch, tmp_path):
    from mediahub.graphic_renderer.render import render_brief

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    seen = set()
    for seed in range(6):
        brief = _brief(seed=seed)
        seen.add(brief.layout_template)
        res = render_brief(brief, output_dir=tmp_path / str(seed), size=(1080, 1350))
        assert res.png_bytes > 2000  # a real, non-empty card
        assert "{{" not in res.html
    assert len(seen) >= 6  # the pack really spanned the library
