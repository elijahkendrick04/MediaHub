"""G1.22 — icon / badge overlay system.

Covers the deterministic medal / club-record / PB-ribbon / nationality-flag SVG
overlay hook (``graphic_renderer/sprint_hooks/icon_overlay.py``) and its asset
set (``graphic_renderer/icons/``):

* the hook is auto-discovered and runs through ``apply_render_hooks``;
* badges are derived purely from brief semantics (no AI, no randomness);
* a card with nothing badge-worthy is returned byte-identical (the seam contract);
* medal / record / PB / flag detection, priority, the 3-badge cap and the
  family-suppression of a doubled medal;
* placement, z-index, token substitution and per-badge id uniqueness;
* an optional real Playwright render so the SVGs are proven to rasterise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.creative_brief.generator import CreativeBrief
from mediahub.graphic_renderer.sprint_hooks import (
    RenderHookCtx,
    apply_render_hooks,
)
from mediahub.graphic_renderer.sprint_hooks import icon_overlay as io

# A minimal but realistic card body with both a v1 `.canvas` and a `</body>`.
CARD_HTML = (
    "<!DOCTYPE html><html><head><style>.canvas{width:100vw;height:100vh}</style>"
    "</head><body><div class=\"canvas\">card</div></body></html>"
)


def _brief(**over) -> CreativeBrief:
    """A real CreativeBrief with sensible defaults; ``over`` patches fields.

    Building the genuine dataclass (not a fake) guards the exact field names the
    hook reads — confidence_label / inspiration_pattern_id / text_layers /
    palette / primary_hook.
    """
    base = dict(
        id="b1",
        content_item_id="ci1",
        profile_id="p1",
        achievement_summary="",
        objective="",
        primary_hook="",
        confidence_label="",
        tone="data_led",
        layout_template="individual_hero",
        inspiration_pattern_id="",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={},
        palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F2C14E"},
        format_priority=[],
    )
    base.update(over)
    return CreativeBrief(**base)


def _ctx(brief, *, family="individual_hero", w=1080, h=1350) -> RenderHookCtx:
    return RenderHookCtx(
        brief=brief, width=w, height=h, family=family,
        format_name="feed_portrait", is_v2=True,
    )


def _run(brief, **kw) -> str:
    """Run via the registry so discovery + isolation are exercised too."""
    return apply_render_hooks(CARD_HTML, _ctx(brief, **kw))


def _badges(html: str) -> list[str]:
    m = re.search(r'data-badges="([^"]*)"', html)
    return m.group(1).split(",") if m else []


# ---------------------------------------------------------------------------
# registry / contract
# ---------------------------------------------------------------------------
def test_hook_is_discovered_by_registry():
    from mediahub.graphic_renderer.sprint_hooks import _discover

    names = {name for _order, name, _fn in _discover()}
    assert "icon_overlay" in names


def test_no_signal_is_byte_identical():
    # A recap / non-achievement card earns no badge → unchanged output.
    out = _run(_brief(confidence_label="RECAP", inspiration_pattern_id="recap_mention"))
    assert out == CARD_HTML


def test_kill_switch_off_returns_unchanged():
    for off in ("off", "none", "0", "false", "NO"):
        b = _brief(
            confidence_label="GOLD",
            inspiration_pattern_id="medal_gold",
            text_layers={"place": "1st", "icon_overlay": off},
        )
        assert _run(b) == CARD_HTML
    # explicit attribute form
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold")
    object.__setattr__(b, "icon_overlay", "off")
    assert _run(b) == CARD_HTML


def test_auto_is_default_enabled():
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
               text_layers={"place": "1st", "icon_overlay": "auto"})
    assert "mh-icon-overlay" in _run(b)


# ---------------------------------------------------------------------------
# medal detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "conf,insp,place,tier",
    [
        ("GOLD", "medal_gold", "1st", "gold"),
        ("SILVER", "medal_silver", "2nd", "silver"),
        ("BRONZE", "medal_bronze", "3rd", "bronze"),
        ("", "medal_and_pb_combo", "1st", "gold"),    # place implies tier in medal ctx
        ("", "medal_and_pb_combo", "2nd", "silver"),
        ("", "medal_and_pb_combo", "3rd", "bronze"),
    ],
)
def test_medal_tier_detection(conf, insp, place, tier):
    b = _brief(confidence_label=conf, inspiration_pattern_id=insp,
               text_layers={"place": place})
    assert io._medal_tier(b) == tier
    assert f"medal-{tier}" in _badges(_run(b))


def test_place_alone_without_medal_context_is_not_a_medal():
    # 1st in a heat / finalist card must NOT mint a gold badge.
    b = _brief(confidence_label="FINALIST", inspiration_pattern_id="finalist",
               text_layers={"place": "1st"})
    assert io._medal_tier(b) is None
    assert _run(b) == CARD_HTML


def test_tenth_place_is_not_a_medal():
    b = _brief(confidence_label="TOP OF FIELD", inspiration_pattern_id="medal_x",
               text_layers={"place": "10th"})
    # "medal" context but place 10 → no tier
    assert io._medal_tier(b) is None


def test_golden_hook_copy_is_not_a_medal():
    # Free-form hook copy must never mint a medal badge — "a golden night"
    # is marketing phrasing, not a factual gold-medal claim.
    b = _brief(primary_hook="A GOLDEN NIGHT FOR THE SQUAD",
               inspiration_pattern_id="recap_mention")
    assert io._medal_tier(b) is None
    assert _run(b) == CARD_HTML


def test_gold_in_hook_copy_alone_is_not_a_medal():
    # Even an exact "gold" token in the hook is copy, not a verified fact.
    b = _brief(primary_hook="GOLD RUSH", confidence_label="RECAP",
               inspiration_pattern_id="recap_mention")
    assert io._medal_tier(b) is None


def test_achievement_label_gold_still_mints_medal():
    b = _brief(text_layers={"achievement_label": "GOLD"})
    assert io._medal_tier(b) == "gold"
    assert "medal-gold" in _badges(_run(b))


def test_record_in_hook_copy_is_not_a_record():
    # "record turnout" phrasing in the post angle must not stamp a record shield.
    b = _brief(text_layers={"post_angle": "record turnout at the gala"},
               inspiration_pattern_id="recap_mention")
    assert io._record_kind(b) is None
    assert _run(b) == CARD_HTML


def test_medal_baked_families_suppress_medal_badge():
    for fam in ("medal_card", "centered_medal_spotlight"):
        b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
                   text_layers={"place": "1st"})
        out = _run(b, family=fam)
        assert "medal-gold" not in _badges(out)
        # nothing else badge-worthy on this card → fully opt out
        assert out == CARD_HTML


def test_medal_baked_family_still_allows_other_badges():
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
               text_layers={"place": "1st", "nationality": "GBR"})
    out = _run(b, family="medal_card")
    assert _badges(out) == ["flag"]


# ---------------------------------------------------------------------------
# record + PB
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label,kind",
    [
        ("NEW CLUB RECORD", "CLUB"),
        ("COUNTY RECORD", "COUNTY"),
        ("REGIONAL RECORD", "COUNTY"),
        ("NATIONAL RECORD", "NATIONAL"),
        ("RECORD", "RECORD"),
    ],
)
def test_record_kind_detection(label, kind):
    # label alone drives the kind here (a "club_record" inspiration id would,
    # correctly, force the generic RECORD case to CLUB).
    b = _brief(confidence_label=label)
    assert io._record_kind(b) == kind
    assert "record" in _badges(_run(b))


def test_record_suppresses_pb_ribbon():
    # A record is already a best — don't double up with a PB rosette.
    b = _brief(confidence_label="NEW CLUB RECORD", inspiration_pattern_id="club_record",
               primary_hook="NEW PB")
    assert _badges(_run(b)) == ["record"]


@pytest.mark.parametrize("label", ["NEW PB", "LIKELY PB", "Personal best"])
def test_pb_ribbon_detection(label):
    b = _brief(confidence_label=label, inspiration_pattern_id="pb_improvement")
    assert io._is_pb(b) is True
    assert _badges(_run(b)) == ["ribbon"]


def test_pb_word_boundary_no_false_positive():
    # "pb" must be a token, not a substring of another word.
    b = _brief(confidence_label="UPBEAT", inspiration_pattern_id="recap_mention")
    assert io._is_pb(b) is False
    assert _run(b) == CARD_HTML


def test_medal_and_pb_combo_shows_both():
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_and_pb_combo",
               primary_hook="NEW PB", text_layers={"place": "1st"})
    assert _badges(_run(b)) == ["medal-gold", "ribbon"]


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["nationality", "nation", "noc", "country_code", "country"])
def test_flag_from_each_text_layer_key(key):
    b = _brief(confidence_label="NEW PB", inspiration_pattern_id="pb",
               text_layers={key: "GBR"})
    assert io._nation_code(b) == "GBR"
    assert "flag" in _badges(_run(b))


def test_flag_alpha2_and_alpha3_resolve_colours():
    for code in ("GB", "GBR", "us", "USA", "AUS"):
        b = _brief(text_layers={"nationality": code})
        out = _run(b)
        assert _badges(out) == ["flag"]
        # the resolved bands are real hexes, code chip uppercased
        assert f">{code.upper()}</text>" in out


def test_flag_full_country_name_maps_to_code():
    b = _brief(text_layers={"country": "Great Britain"})
    assert io._nation_code(b) == "GBR"


def test_unknown_nation_uses_neutral_fallback_but_still_shows():
    b = _brief(text_layers={"nationality": "ZZ"})
    out = _run(b)
    assert _badges(out) == ["flag"]
    b1, b2, b3 = io._NATION_FALLBACK
    assert b1 in out and b2 in out and b3 in out
    assert ">ZZ</text>" in out


def test_no_nation_no_flag():
    b = _brief(confidence_label="NEW PB", inspiration_pattern_id="pb_improvement")
    assert io._nation_code(b) is None
    assert "flag" not in _badges(_run(b))


# ---------------------------------------------------------------------------
# priority, cap, ordering
# ---------------------------------------------------------------------------
def test_priority_and_cap_at_three():
    # record + medal + flag (+ PB suppressed by record) → exactly 3, in order.
    b = _brief(
        confidence_label="NATIONAL RECORD",
        inspiration_pattern_id="medal_gold club_record",
        primary_hook="NEW PB",
        text_layers={"place": "1st", "nationality": "USA"},
    )
    assert _badges(_run(b)) == ["record", "medal-gold", "flag"]


def test_priority_order_medal_flag_ribbon():
    b = _brief(
        confidence_label="GOLD",
        inspiration_pattern_id="medal_gold",
        primary_hook="NEW PB",
        text_layers={"place": "1st", "nationality": "AUS"},
    )
    assert _badges(_run(b)) == ["medal-gold", "flag", "ribbon"]


# ---------------------------------------------------------------------------
# structure / placement / tokens
# ---------------------------------------------------------------------------
def test_overlay_structure_and_layering():
    out = _run(_brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
                      text_layers={"place": "1st"}))
    assert "position:fixed" in out and "inset:0" in out
    assert f"z-index:{io._OVERLAY_Z}" in out
    assert "pointer-events:none" in out
    # injected exactly once, before </body>
    assert out.count("mh-icon-overlay") == 1
    assert out.endswith("</body></html>")
    assert "mh-icon-overlay" in out.split("</body>")[0]


def test_all_placeholder_tokens_substituted():
    b = _brief(
        confidence_label="GOLD",
        inspiration_pattern_id="medal_gold club_record national",
        primary_hook="NEW PB",
        text_layers={"place": "1st", "nationality": "FRA"},
    )
    out = _run(b)
    # no raw __TOKEN__ left anywhere
    assert "__" not in out.split("mh-icon-overlay")[1]


def test_per_badge_svg_ids_are_unique():
    # Two inlined SVGs must not share a gradient/clip id or the second clobbers
    # the first when both are on one page.
    b = _brief(confidence_label="NATIONAL RECORD", inspiration_pattern_id="club_record",
               text_layers={"nationality": "GER"})
    out = _run(b)  # record + flag
    ids = re.findall(r'id="([^"]+)"', out)
    assert len(ids) == len(set(ids)), f"duplicate svg ids: {ids}"


def test_no_body_tag_appends_overlay():
    html = "<div class='canvas'>x</div>"  # no </body>
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
               text_layers={"place": "1st"})
    out = apply_render_hooks(html, _ctx(b))
    assert out.startswith(html)
    assert "mh-icon-overlay" in out


def test_zero_dimensions_guard():
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
               text_layers={"place": "1st"})
    assert apply_render_hooks(CARD_HTML, _ctx(b, w=0, h=0)) == CARD_HTML


# ---------------------------------------------------------------------------
# determinism + isolation
# ---------------------------------------------------------------------------
def test_deterministic_same_brief_same_output():
    mk = lambda: _brief(confidence_label="GOLD", inspiration_pattern_id="medal_and_pb_combo",
                        primary_hook="NEW PB", text_layers={"place": "1st", "nationality": "GBR"})
    assert _run(mk()) == _run(mk())


def test_badge_size_scales_with_short_edge():
    b = _brief(confidence_label="GOLD", inspiration_pattern_id="medal_gold",
               text_layers={"place": "1st"})
    small = apply_render_hooks(CARD_HTML, _ctx(b, w=600, h=600))
    large = apply_render_hooks(CARD_HTML, _ctx(b, w=1080, h=1080))

    def first_box(html):
        return int(re.search(r"width:(\d+)px;height:\1px", html).group(1))

    assert first_box(small) < first_box(large)


def test_bad_brief_is_skipped_not_fatal():
    # The registry isolates a raising hook. A brief whose palette is the wrong
    # type must never crash the pipeline.
    class Weird:
        confidence_label = "GOLD"
        inspiration_pattern_id = "medal_gold"
        text_layers = {"place": "1st"}
        palette = "not-a-dict"  # would break a naive .get
        primary_hook = ""

    out = apply_render_hooks(CARD_HTML, _ctx(Weird()))
    assert isinstance(out, str)  # never raises; badge may or may not render


# ---------------------------------------------------------------------------
# colour helpers
# ---------------------------------------------------------------------------
def test_hex_normalisation():
    assert io._hex("#0E5BFF") == "#0e5bff"
    assert io._hex("0E5BFF") == "#0e5bff"
    assert io._hex("#abc") == "#aabbcc"
    assert io._hex("nope") is None
    assert io._hex(None) is None
    assert io._hex(123) is None


def test_darken_and_luma():
    assert io._darken("#ffffff", 0.5) == "#7f7f7f"
    assert io._darken("#ffffff", 0.0) == "#000000"
    assert io._luma("#ffffff") == pytest.approx(1.0, abs=1e-6)
    assert io._luma("#000000") == 0.0
    assert io._luma("#ffffff") > io._luma("#0e5bff")


def test_brand_base_falls_back_when_primary_too_light():
    # very light primary → fall back to dark secondary so the badge stays visible
    b = _brief(palette={"primary": "#FFFFFF", "secondary": "#0a0f16", "accent": "#fff"})
    face, deep = io._brand_base(b)
    assert io._luma(face) < 0.72
    assert io._luma(deep) <= io._luma(face)


def test_brand_base_uses_primary_when_dark_enough():
    b = _brief(palette={"primary": "#0B2E59", "secondary": "#fff", "accent": "#fff"})
    face, _deep = io._brand_base(b)
    assert face == "#0b2e59"


# ---------------------------------------------------------------------------
# asset set
# ---------------------------------------------------------------------------
def test_icon_assets_exist():
    icons = Path(io._ICONS_DIR)
    for name in ("medal.svg", "record.svg", "ribbon.svg", "flag.svg", "README.md"):
        assert (icons / name).is_file(), f"missing {name}"


@pytest.mark.parametrize(
    "name,tokens",
    [
        ("medal.svg", ["__TINT__", "__TINT_DEEP__", "__UID__"]),
        ("record.svg", ["__TINT__", "__TINT_DEEP__", "__TEXT__", "__UID__"]),
        ("ribbon.svg", ["__TINT__", "__TINT_DEEP__", "__TEXT__", "__UID__"]),
        ("flag.svg", ["__BAND1__", "__BAND2__", "__BAND3__", "__CODE__", "__UID__"]),
    ],
)
def test_asset_tokens_present(name, tokens):
    text = (Path(io._ICONS_DIR) / name).read_text(encoding="utf-8")
    for tok in tokens:
        assert tok in text, f"{name} missing {tok}"
    assert text.lstrip().startswith("<svg")


def test_nation_table_values_are_valid_hex():
    for code, bands in io._NATIONS.items():
        assert len(bands) == 3, code
        for band in bands:
            assert io._hex(band) is not None, f"{code}: {band}"
    for band in io._NATION_FALLBACK:
        assert io._hex(band) is not None


def test_fill_injects_sizing_and_uid():
    svg = io._fill("medal.svg", "med", TINT="#FFE07A", TINT_DEEP="#9A6E0E", LABEL="Gold")
    assert "width:100%;height:100%" in svg
    assert "__UID__" not in svg and "medalFacemed" in svg


# ---------------------------------------------------------------------------
# optional: prove the SVGs actually rasterise
# ---------------------------------------------------------------------------
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
def test_real_render_with_badges_produces_png(tmp_path):
    from mediahub.graphic_renderer.render import render_html_to_png

    b = _brief(
        confidence_label="GOLD",
        inspiration_pattern_id="medal_and_pb_combo",
        primary_hook="NEW PB",
        text_layers={"place": "1st", "nationality": "GBR"},
    )
    body = (
        "<!DOCTYPE html><html><head><style>html,body{margin:0}"
        ".canvas{width:100vw;height:100vh;background:#13202e}</style></head>"
        "<body><div class='canvas'></div></body></html>"
    )
    html = apply_render_hooks(body, _ctx(b, w=1080, h=1350))
    out = tmp_path / "card.png"
    n = render_html_to_png(html, out, (1080, 1350))
    assert out.is_file() and n > 0 and out.stat().st_size > 2000
