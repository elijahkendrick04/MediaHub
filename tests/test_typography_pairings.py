"""D5 (Canva gap analysis) — the curated typography pairing table.

Pins the contract of ``graphic_renderer.type_pairs``:

* the table is a set of real (display, kicker, body, data) quadruples with the
  data register locked to JetBrains Mono;
* the default pairing (and the two legacy aliases) emits **no** font vars, so
  every pre-D5 brief renders byte-identically;
* the display face per pairing mirrors the motion renderer's ``fontStackFor``
  (still ↔ motion parity, the contract ``render._PAIR_DISPLAY_FONT`` used to
  carry);
* mood subsets stay inside the design-spec mood vocabulary and the table;
* selection is deterministic (same card key → same pairing);
* the v2 layouts actually consume the kicker/body vars with their old stacks
  as fallbacks, and quote_led_recap no longer leads with system Georgia.
"""

from __future__ import annotations

import re
from pathlib import Path

from mediahub.creative_brief import design_spec as ds
from mediahub.graphic_renderer import type_pairs as tp

_ROOT = Path(__file__).resolve().parents[1]
_V2 = _ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts" / "v2"
_SHARED = _ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts" / "_shared.css"
_STORYCARD = _ROOT / "src" / "mediahub" / "remotion" / "src" / "compositions" / "StoryCard.tsx"


def _first_family(stack: str) -> str:
    return stack.split(",", 1)[0].strip().strip("'\"")


# --------------------------------------------------------------------------- #
# Table shape
# --------------------------------------------------------------------------- #
def test_table_is_a_curated_set_of_real_quadruples():
    distinct = {(p.display, p.kicker, p.body) for p in tp.PAIRINGS.values() if not p.is_default}
    # 6-8 real quadruples (the Canva "curated font sets" band); aliases and the
    # default share the empty quadruple.
    assert 5 <= len(distinct) <= 8
    assert tp.DEFAULT_PAIR_ID in tp.PAIRINGS
    # A serif register exists (the D5 headline addition).
    assert any(_first_family(p.display) == "Playfair Display" for p in tp.PAIRINGS.values())


def test_data_register_is_locked_to_mono():
    for p in tp.PAIRINGS.values():
        assert p.data == "", f"{p.id}: the data register never rebinds (tnum alignment)"
        assert "--mh-font-data" not in tp.font_vars_for_pair(p.id)


def test_default_and_legacy_aliases_emit_no_vars():
    # Byte-identity: anton-inter and the druk/oswald aliases must bind nothing.
    for pair_id in ("anton-inter", "druk-inter", "oswald-inter", "", "unknown-pair"):
        assert tp.font_vars_for_pair(pair_id) == {}, pair_id


def test_every_bound_stack_leads_with_a_self_hosted_family():
    css = _SHARED.read_text(encoding="utf-8")
    for p in tp.PAIRINGS.values():
        for stack in (p.display, p.kicker, p.body):
            if not stack:
                continue
            lead = _first_family(stack)
            assert f"'{lead}'" in css, (
                f"{p.id}: lead family {lead!r} is not declared in _shared.css — "
                f"pairings may only name self-hosted faces"
            )


# --------------------------------------------------------------------------- #
# Still ↔ motion display parity
# --------------------------------------------------------------------------- #
def _tsx_display_leads() -> dict[str, str]:
    """Parse fontStackFor's switch: pair id → lead family of its return stack."""
    src = _STORYCARD.read_text(encoding="utf-8")
    body = src.split("export function fontStackFor", 1)[1].split("\n}", 1)[0]
    out: dict[str, str] = {}
    pending: list[str] = []
    for line in body.splitlines():
        m = re.match(r'\s*case "([^"]+)":', line)
        if m:
            pending.append(m.group(1))
            continue
        r = re.search(r'return\s+"([^"]+)"', line)
        if r and pending:
            for pair in pending:
                out[pair] = _first_family(r.group(1))
            pending = []
    return out


def test_display_face_parity_with_motion():
    tsx = _tsx_display_leads()
    for p in tp.PAIRINGS.values():
        if p.is_default:
            # Default/aliases render Anton on both surfaces.
            assert tsx.get(p.id, "Anton") == "Anton", p.id
            continue
        assert p.id in tsx, f"{p.id}: no fontStackFor case in StoryCard.tsx"
        assert tsx[p.id] == _first_family(p.display), (
            f"{p.id}: still display leads {_first_family(p.display)!r} but motion "
            f"leads {tsx[p.id]!r} — still↔motion typography parity broken"
        )


def test_render_helper_surfaces_the_pairing_display():
    from mediahub.graphic_renderer.render import _display_font_stack_for_pair

    assert _display_font_stack_for_pair("anton-inter") == ""
    assert _display_font_stack_for_pair("playfair-editorial").startswith("'Playfair Display'")
    assert _display_font_stack_for_pair("bebas-grotesk").startswith("'Bebas Neue'")


# --------------------------------------------------------------------------- #
# Mood subsets + deterministic selection
# --------------------------------------------------------------------------- #
def test_mood_subsets_stay_inside_the_vocabularies():
    for mood, subset in tp.MOOD_PAIR_SUBSETS.items():
        assert mood == "" or mood in ds.MOODS, f"unknown mood {mood!r}"
        assert subset, f"{mood!r}: empty subset"
        for pair_id in subset:
            assert pair_id in tp.PAIRINGS, f"{mood!r} names unknown pairing {pair_id!r}"


def test_pick_is_deterministic_and_mood_keyed():
    a = tp.pick_pair_for_card("stoic", "card-123")
    b = tp.pick_pair_for_card("stoic", "card-123")
    assert a.id == b.id  # same card → same pairing
    assert a.id in tp.MOOD_PAIR_SUBSETS["stoic"]
    # The free-ish mood channel ("electric, precise") resolves on the first
    # recognised word; unknown text falls to the neutral subset.
    assert tp.pick_pair_for_card("electric, precise", "k").id in tp.MOOD_PAIR_SUBSETS["electric"]
    assert tp.pick_pair_for_card("moody nonsense", "k").id in tp.MOOD_PAIR_SUBSETS[""]
    # No key → the subset's characteristic first entry.
    assert tp.pick_pair_for_card("stoic", None).id == tp.MOOD_PAIR_SUBSETS["stoic"][0]


def test_pick_spreads_across_a_pack():
    ids = {tp.pick_pair_for_card("", f"swim-{i}").id for i in range(24)}
    assert len(ids) >= 2, "24 cards should not all land on one pairing"


# --------------------------------------------------------------------------- #
# Generator integration
# --------------------------------------------------------------------------- #
def _brand():
    from mediahub.brand.kit import BrandKit

    return BrandKit(
        profile_id="tp",
        display_name="Pairing SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#FFFFFF",
        short_name="PSC",
    )


def _item(i: int = 1) -> dict:
    return {
        "id": f"swim-tp-{i}",
        "post_angle": "individual_pb",
        "achievement": {
            "swim_id": f"swim-tp-{i}",
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }


def test_generate_draws_pair_from_table_on_the_bulk_path(monkeypatch):
    from mediahub.creative_brief.generator import generate

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    brief = generate(_item(1), None, _brand(), profile_id="tp")
    assert brief.typography_pair in tp.PAIRINGS
    # Deterministic: same card → same pairing.
    again = generate(_item(1), None, _brand(), profile_id="tp")
    assert again.typography_pair == brief.typography_pair


def test_generate_keeps_seeded_callers_byte_identical(monkeypatch):
    from mediahub.creative_brief.generator import generate

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    brief = generate(_item(2), None, _brand(), profile_id="tp", variation_seed=2)
    # Explicit-seed callers (?variation_seed / ?stable) keep the pinned default.
    assert brief.typography_pair == "anton-inter"


def test_apply_design_spec_rekeys_pair_to_the_director_mood(monkeypatch):
    from mediahub.creative_brief.generator import CreativeBrief, apply_design_spec, generate

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    brief = generate(_item(3), None, _brand(), profile_id="tp")
    assert brief.style_pack  # v2 active — the re-key guard
    spec = ds.normalise(
        {"mood": "stoic", "archetype": brief.layout_template},
        archetypes=[brief.layout_template],
        token_roles=["primary"],
    )
    apply_design_spec(brief, spec)
    assert brief.typography_pair in tp.MOOD_PAIR_SUBSETS["stoic"]


# --------------------------------------------------------------------------- #
# Layout adoption
# --------------------------------------------------------------------------- #
def test_layouts_consume_kicker_and_body_vars_with_fallbacks():
    kicker = body = 0
    for f in _V2.glob("*.html"):
        t = f.read_text(encoding="utf-8")
        kicker += t.count("var(--mh-font-kicker,")
        body += t.count("var(--mh-font-body,")
        # No register consumes a var without its old stack as fallback.
        assert "var(--mh-font-kicker)" not in t, f.name
        assert "var(--mh-font-body)" not in t, f.name
    assert kicker >= 80, f"kicker register barely adopted ({kicker} consumers)"
    assert body >= 90, f"body register barely adopted ({body} consumers)"


def test_quote_led_recap_serif_is_self_hosted():
    t = (_V2 / "quote_led_recap.html").read_text(encoding="utf-8")
    m = re.search(r"\.ql__quote\s*\{[^}]*font-family:\s*([^;]+);", t, re.S)
    assert m, "quote glyph rule missing"
    assert _first_family(m.group(1)) == "Playfair Display", (
        "the hanging quote glyph must lead with the self-hosted serif, not system Georgia"
    )


def test_playfair_measures_from_its_char_table():
    from mediahub.graphic_renderer.autofit import em_width, kern_ligature_em

    # Char-table families carry no Helvetica kern model (it does not transfer).
    assert kern_ligature_em("TAYLOR", font_family="Playfair Display") == 0.0
    # And the serif measures wider than the condensed Anton for the same run.
    assert em_width("WESTHUIZEN", font_family="Playfair Display") > em_width(
        "WESTHUIZEN", font_family="Anton"
    )
