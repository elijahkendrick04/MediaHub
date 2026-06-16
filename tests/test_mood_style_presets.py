"""Mood-keyed style-pack preset bundles (G1.28).

The graphic generator picks a decorative style pack per card. Before this, the
pick was mood-blind — a seeded walk over the full 1000+ pack catalog. G1.28 adds
**curated, deterministic preset bundles selected from ``brief.mood``**: each
``design_spec`` mood maps to a small hand-authored tuple of packs whose
ground/texture/accent vocabulary expresses that feeling, so an explosive card
gets sharp diagonals + wedges and a calm card gets soft fades + light rules.

These tests pin the contract end-to-end:
  * the preset map covers every ``design_spec.MOODS`` value (drift guard) and
    every preset is a real, in-catalog, coherence-capped, brand-safe pack;
  * the mood-aware pickers are deterministic, stay inside the bundle, and fall
    **straight through to the full-catalog pickers** for an empty/unknown mood —
    so every legacy / non-AI brief is byte-identical to before;
  * brief generation actually keys the pack off the mood (both the
    ``generate()`` path and the post-hoc ``apply_design_spec`` re-key the
    candidate-pool / regenerate-variants paths use), and the v2 kill switch and
    bare-brief paths stay undecorated.

Pure Python shaping — no browser, no web import.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.design_spec import MOODS, normalise
from mediahub.creative_brief.generator import (
    CreativeBrief,
    VariationProfile,
    apply_design_spec,
    generate,
)
from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp


# --------------------------------------------------------------------------- #
# Vocabulary integrity & curation
# --------------------------------------------------------------------------- #


def test_preset_keys_cover_every_design_spec_mood_exactly():
    # Drift guard: the curated map mirrors design_spec.MOODS one-for-one. A new
    # mood without a bundle (or a stale bundle key) fails here, not silently in
    # production where it would just fall through to the full catalog.
    assert set(sp.mood_preset_moods()) == set(MOODS)
    # neutral is the design-spec default → it must carry a bundle (so a
    # hallucinated-then-coerced mood still lands on a curated, tasteful set).
    assert sp.mood_preset_packs("neutral")


@pytest.mark.parametrize("mood", list(MOODS))
def test_every_mood_bundle_is_valid_in_catalog_and_unique(mood):
    bundle = sp.mood_preset_packs(mood)
    assert bundle, f"{mood}: empty bundle"
    ids = [p.id for p in bundle]
    assert len(ids) == len(set(ids)), f"{mood}: duplicate pack in bundle {ids}"
    catalog = {p.id for p in sp.list_style_packs()}
    for p in bundle:
        # Every preset is a real catalog member → addressable + round-trips.
        assert p.id in catalog, f"{mood}: {p.id} not in catalog"
        assert sp.style_pack_from_id(p.id) == p
    # mood_preset_ids mirrors the packs.
    assert sp.mood_preset_ids(mood) == tuple(ids)


def test_presets_stay_under_the_coherence_weight_cap():
    # Same taste rule the catalog enforces — no over-decorated preset.
    for mood in MOODS:
        for p in sp.mood_preset_packs(mood):
            cap = 3 if p.density == "bold" else 4
            assert p.weight <= cap, f"{mood}: {p.id} weight {p.weight} > {cap}"


def test_every_mood_has_a_human_note_unknown_has_none():
    for mood in MOODS:
        assert sp.mood_preset_note(mood).strip(), f"{mood}: missing note"
    assert sp.mood_preset_note("not-a-mood") == ""
    assert sp.mood_preset_note("") == ""


def test_bundles_are_stable_across_calls():
    # Curated map is fixed: same mood → identical ids every call (the picker
    # relies on this for cross-process reproducibility).
    for mood in MOODS:
        assert sp.mood_preset_ids(mood) == sp.mood_preset_ids(mood.upper())


# --------------------------------------------------------------------------- #
# Lookup + the no-mood fall-through (the backward-compatibility guarantee)
# --------------------------------------------------------------------------- #


def test_empty_or_unknown_mood_yields_no_bundle():
    assert sp.mood_preset_packs("") == ()
    assert sp.mood_preset_packs(None) == ()
    assert sp.mood_preset_packs("   ") == ()
    assert sp.mood_preset_packs("ultra-mega-hype") == ()
    assert sp.mood_preset_ids("nope") == ()


def test_mood_lookup_is_case_and_space_insensitive():
    base = sp.mood_preset_ids("explosive")
    assert base
    assert sp.mood_preset_ids("EXPLOSIVE") == base
    assert sp.mood_preset_ids("  Explosive  ") == base


def test_no_mood_pickers_are_byte_identical_to_full_catalog():
    # The crux of backward compatibility: with no mood the mood-aware pickers
    # must equal the existing full-catalog pickers exactly.
    for mood in ("", None, "totally-unknown"):
        for seed in (0, 1, 5, 99, 100003):
            assert sp.pick_mood_pack(mood, seed).id == sp.pick_style_pack(seed).id
        assert sp.pick_mood_pack_avoiding(mood, 4, []).id == sp.pick_style_pack_avoiding(4, []).id
        for key in ("swim-1", "swim-2", "abc"):
            assert sp.pick_mood_pack_for_card(mood, key).id == sp.pick_style_pack_for_card(key).id


# --------------------------------------------------------------------------- #
# Mood-scoped pickers: deterministic, in-bundle, well-spread
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mood", list(MOODS))
def test_pick_mood_pack_is_deterministic_and_in_bundle(mood):
    bundle = set(sp.mood_preset_packs(mood))
    assert sp.pick_mood_pack(mood, 7).id == sp.pick_mood_pack(mood, 7).id
    for seed in range(0, 30):
        assert sp.pick_mood_pack(mood, seed) in bundle


@pytest.mark.parametrize("mood", list(MOODS))
def test_pick_mood_pack_reaches_every_pack_in_its_bundle(mood):
    bundle = sp.mood_preset_packs(mood)
    seen = {sp.pick_mood_pack(mood, s).id for s in range(len(bundle) * 3)}
    assert seen == {p.id for p in bundle}, f"{mood}: picker misses part of its bundle"


def test_pick_mood_pack_avoiding_walks_within_the_bundle():
    mood = "celebratory"
    bundle = sp.mood_preset_packs(mood)
    first = sp.pick_mood_pack_avoiding(mood, 0, [])
    assert first.id == sp.pick_mood_pack(mood, 0).id
    second = sp.pick_mood_pack_avoiding(mood, 0, [first.id])
    assert second.id != first.id and second in bundle
    # deterministic
    assert sp.pick_mood_pack_avoiding(mood, 0, [first.id]).id == second.id
    # everything recent → degrade to the strict seeded pick (still in-bundle)
    allids = [p.id for p in bundle]
    assert sp.pick_mood_pack_avoiding(mood, 0, allids).id == sp.pick_mood_pack(mood, 0).id


def test_pick_mood_pack_for_card_is_stable_and_spreads():
    mood = "electric"
    bundle_ids = {p.id for p in sp.mood_preset_packs(mood)}
    # same card → same pack (re-renders identical)
    assert (
        sp.pick_mood_pack_for_card(mood, "swim-7").id
        == sp.pick_mood_pack_for_card(mood, "swim-7").id
    )
    picks = {sp.pick_mood_pack_for_card(mood, f"swim-{i}").id for i in range(40)}
    assert picks <= bundle_ids  # never leaves the mood's bundle
    assert len(picks) >= 2  # a pack of same-mood cards visibly varies


def test_pick_mood_pack_for_card_without_key_stays_in_bundle():
    mood = "fierce"
    bundle = set(sp.mood_preset_packs(mood))
    # missing key → a fresh time-seeded pick, but still a member of the bundle
    for _ in range(5):
        assert sp.pick_mood_pack_for_card(mood, None) in bundle


# --------------------------------------------------------------------------- #
# Decoration is brand-safe & actually reaches the card
# --------------------------------------------------------------------------- #


def test_preset_overlays_are_brand_colour_only_no_raw_hex():
    for mood in MOODS:
        for p in sp.mood_preset_packs(mood):
            html = sp.pack_overlay_html(p, width=1080, height=1350)
            assert not re.search(r"#[0-9a-fA-F]{3,6}\b", html), f"{mood}/{p.id}: raw hex"
            if p.accent_geo != "none":
                assert "var(--mh-accent)" in html, f"{mood}/{p.id}: accent not role-driven"


@pytest.mark.parametrize("mood", list(MOODS))
def test_every_mood_bundle_has_a_decorating_pack(mood):
    bundle = sp.mood_preset_packs(mood)
    decorators = [p for p in bundle if not p.is_bare]
    assert decorators, f"{mood}: bundle is entirely bare (no decoration reaches output)"
    for p in decorators:
        assert sp.pack_overlay_html(p, width=1080, height=1350), f"{mood}/{p.id}"


def test_minimal_offers_the_bare_pack():
    # "minimal" should include the spare, undecorated option.
    assert any(p.is_bare for p in sp.mood_preset_packs("minimal"))


# --------------------------------------------------------------------------- #
# Generator wiring — the mood actually keys the pack at output
# --------------------------------------------------------------------------- #


def _brand():
    return BrandKit(
        profile_id="t",
        display_name="Mood SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#FFFFFF",
        short_name="MSC",
    )


def _card(cid="c1"):
    return {
        "id": cid,
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }


def _spec(archetype, *, mood="explosive", token_roles=None):
    return normalise(
        {"archetype": archetype, "mood": mood},
        archetypes=A.list_archetypes(),
        token_roles=token_roles or list(A.TOKEN_ROLES),
    )


def test_no_mood_brief_keeps_the_full_catalog_pack(monkeypatch):
    # Backward compatibility: a non-AI brief (mood == "") picks from the whole
    # catalog exactly as before — the explicit-seed pick is unchanged.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    b = generate(_card(), None, _brand(), profile_id="t", variation_seed=5)
    assert b.mood == ""
    assert b.style_pack == sp.pick_style_pack(5).id


@pytest.mark.parametrize("mood", list(MOODS))
def test_variation_profile_mood_keys_the_pack(monkeypatch, mood):
    # A mood supplied up front (the VariationProfile path) keys generate()'s
    # own pack block to that mood's bundle — no AI provider needed.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    b = generate(
        _card(),
        None,
        _brand(),
        profile_id="t",
        variation_profile=VariationProfile(mood=mood),
    )
    assert b.mood == mood
    assert sp.style_pack_from_id(b.style_pack) in sp.mood_preset_packs(mood)


def test_explicit_seed_with_mood_is_reproducible_and_in_bundle(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    vp = VariationProfile(mood="triumphant")
    a = generate(_card(), None, _brand(), profile_id="t", variation_seed=3, variation_profile=vp)
    b = generate(_card(), None, _brand(), profile_id="t", variation_seed=3, variation_profile=vp)
    assert a.style_pack == b.style_pack  # deterministic
    assert sp.style_pack_from_id(a.style_pack) in sp.mood_preset_packs("triumphant")


def test_same_mood_content_pack_spreads_within_the_bundle(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    mood = "celebratory"
    bundle_ids = {p.id for p in sp.mood_preset_packs(mood)}
    recents: list[str] = []
    chosen: list[str] = []
    for i in range(12):
        b = generate(
            _card(f"card-{i}"),
            None,
            _brand(),
            profile_id="t",
            variation_profile=VariationProfile(mood=mood),
            recent_signatures=recents[-6:],
        )
        chosen.append(b.style_pack)
        recents.append(b.variation_signature)
    assert set(chosen) <= bundle_ids  # never leaves the mood's bundle
    assert len(set(chosen)) >= 2  # but visibly varies within it


def test_v2_killswitch_assigns_no_pack_even_with_a_mood(monkeypatch):
    # Kill switch wins: legacy engine → bare, byte-identical, mood or not.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
    b = generate(
        _card(), None, _brand(), profile_id="t", variation_profile=VariationProfile(mood="fierce")
    )
    assert b.style_pack == ""


# --- apply_design_spec re-key (the candidate-pool / regenerate-variants path) --


def test_apply_design_spec_rekeys_pack_to_the_mood_bundle(monkeypatch):
    # Mirrors the pool: generate() with seed 0 picks the bare pack, then a
    # pre-computed spec with a mood is applied → the pack re-keys to the bundle.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    names = A.list_archetypes()
    b = generate(_card(), None, _brand(), profile_id="t", variation_seed=0)
    assert b.style_pack  # generate picked one (the bare pack at seed 0)
    apply_design_spec(b, _spec(names[2], mood="explosive"))
    assert b.mood == "explosive"
    assert sp.style_pack_from_id(b.style_pack) in sp.mood_preset_packs("explosive")
    # signature reflects the re-keyed pack
    assert f"sp:{b.style_pack}" in b.variation_signature


def test_apply_design_spec_rekey_is_deterministic(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    names = A.list_archetypes()

    def _run():
        b = generate(_card(), None, _brand(), profile_id="t", variation_seed=0)
        apply_design_spec(b, _spec(names[2], mood="calm"))
        return b.style_pack

    assert _run() == _run()


def test_apply_design_spec_spreads_distinct_candidates_across_a_bundle(monkeypatch):
    # The archetype is folded into the re-key key, so N candidates for one card
    # that share a mood don't all collapse onto a single pack.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    names = A.list_archetypes()
    picks = set()
    for arch in names[:6]:
        b = generate(_card(), None, _brand(), profile_id="t", variation_seed=0)
        apply_design_spec(b, _spec(arch, mood="bold"))
        assert sp.style_pack_from_id(b.style_pack) in sp.mood_preset_packs("bold")
        picks.add(b.style_pack)
    assert len(picks) >= 2  # the bundle is actually exercised across candidates


def test_apply_design_spec_rekey_is_noop_without_a_pack():
    # A bare brief (no pack chosen — v2 off / direct caller) is never given one
    # by the re-key: decoration stays absent, byte-identical to before.
    names = A.list_archetypes()
    bare = CreativeBrief(
        id="cb",
        content_item_id="swim-x",
        profile_id="t",
        achievement_summary="x",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template=names[0],
        inspiration_pattern_id="p1",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="d",
        text_layers={},
        palette={"primary": "#0E2A47"},
        format_priority=["feed_portrait"],
    )
    assert bare.style_pack == ""
    apply_design_spec(bare, _spec(names[1], mood="explosive"))
    assert bare.mood == "explosive"
    assert bare.style_pack == ""  # still bare — no pack to re-key


def test_apply_design_spec_rekey_noop_for_v2_off_brief(monkeypatch):
    # End-to-end kill-switch: generate() with v2 off leaves style_pack empty, so
    # the post-hoc spec application leaves it empty too.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
    names = A.list_archetypes()
    b = generate(_card(), None, _brand(), profile_id="t", variation_seed=0)
    assert b.style_pack == ""
    apply_design_spec(b, _spec(names[2], mood="electric"))
    assert b.style_pack == ""
