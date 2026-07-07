"""The combinatorial template catalog (graphic_renderer.style_packs) + wiring.

The product requirement this pins: **at least 1000 unique templates can be used
when a graphic is generated.** A template is an archetype × a style pack; this
suite proves the catalog enumerates ≥1000 unique, deterministic templates, that
the packs render distinct *and* legibility-safe overlays, and that brief
generation actually selects one per card (so the variety reaches output).

No browser and no web import (keeps it runnable wherever the engine is): the
single Playwright path is stubbed, everything else is pure shaping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp


# --------------------------------------------------------------------------- #
# Pack catalog: deterministic, de-duplicated, well-ordered
# --------------------------------------------------------------------------- #


def test_pack_catalog_is_unique_and_stable():
    packs = sp.list_style_packs()
    ids = [p.id for p in packs]
    assert len(ids) == len(set(ids)), "duplicate pack ids in the catalog"
    # cached → identical object across calls (stable order for the picker)
    assert sp.list_style_packs() is sp.list_style_packs()
    # exactly one bare pack, and it leads the order
    assert packs[0].is_bare
    assert sum(1 for p in packs if p.is_bare) == 1
    # order is non-decreasing in weight after the bare pack (quiet → busy)
    weights = [p.weight for p in packs]
    assert weights == sorted(weights)


def test_coherence_cap_keeps_packs_tasteful():
    # No pack stacks beyond the coherence weight cap (no over-decorated card).
    for p in sp.list_style_packs():
        cap = 3 if p.density == "bold" else 4
        assert p.weight <= cap, p.id


def test_pack_picker_is_deterministic_and_surjective():
    packs = sp.list_style_packs()
    assert sp.pick_style_pack(7).id == sp.pick_style_pack(7).id
    seen = {sp.pick_style_pack(s).id for s in range(len(packs) * 2)}
    assert seen == {p.id for p in packs}, "picker does not reach every pack"


def test_pack_avoiding_walks_past_recent():
    packs = sp.list_style_packs()
    first = sp.pick_style_pack_avoiding(4, [])
    assert first.id == sp.pick_style_pack(4).id
    second = sp.pick_style_pack_avoiding(4, [first.id])
    assert second.id != first.id
    assert sp.pick_style_pack_avoiding(4, [first.id]).id == second.id  # deterministic
    # everything recent → degrade to the strict seeded pick
    allids = [p.id for p in packs]
    assert sp.pick_style_pack_avoiding(4, allids).id == sp.pick_style_pack(4).id


def test_pack_for_card_is_stable_and_spreads():
    # Same card → same pack (re-renders look identical); different cards spread.
    assert sp.pick_style_pack_for_card("swim-1").id == sp.pick_style_pack_for_card("swim-1").id
    picks = {sp.pick_style_pack_for_card(f"swim-{i}").id for i in range(40)}
    assert len(picks) >= 10  # a pack of cards visibly varies


def test_pack_roundtrip_and_normalise():
    packs = sp.list_style_packs()
    for p in (packs[0], packs[len(packs) // 2], packs[-1]):
        assert sp.style_pack_from_id(p.id) == p
    assert sp.style_pack_from_id("totally-bogus-id") is None
    # junk levers coerce to the safe bare default, never an unrenderable pack
    assert sp.normalise_pack("zzz", "zzz", "zzz", "zzz").is_bare


# --------------------------------------------------------------------------- #
# THE requirement: ≥1000 unique templates available at generation
# --------------------------------------------------------------------------- #


def test_at_least_1000_unique_templates():
    # A template is an archetype × a style pack. Product surfaces address the
    # two factors directly (pack id + archetype name — there is no separate
    # Template id layer), so the floor is pinned on the same product the
    # design editor computes: archetypes × unique packs.
    arch = A.list_archetypes()
    pack_ids = [p.id for p in sp.list_style_packs()]
    assert len(pack_ids) == len(set(pack_ids)), "duplicate pack ids"
    assert len(set(arch)) == len(arch), "duplicate archetype names"
    n_templates = len(arch) * sp.style_pack_count()
    assert n_templates >= 1000, f"only {n_templates} templates (< 1000)"


# --------------------------------------------------------------------------- #
# Overlay rendering: distinct, margin-safe, brand-colour-only (no raw hex)
# --------------------------------------------------------------------------- #


def test_overlay_distinct_per_pack_and_bare_is_empty():
    packs = sp.list_style_packs()
    sample = packs[:80] + packs[-80:]
    rendered: dict[str, str] = {}
    for p in sample:
        html = sp.pack_overlay_html(p, width=1080, height=1350)
        if p.is_bare:
            assert html == "", "bare pack must inject nothing (byte-identical card)"
        else:
            assert html, p.id
            assert "position:absolute" in html and "pointer-events:none" in html
        rendered[p.id] = html
    # the non-bare overlays are highly distinct payloads (→ distinct pixels)
    nonempty = [h for pid, h in rendered.items() if h]
    assert len(set(nonempty)) >= int(len(nonempty) * 0.85)


def test_overlay_is_brand_colour_only_no_raw_hex():
    # Same rule the archetype HTML lives by: brand colour only via --mh-accent,
    # everything else neutral black/white alpha. A raw #hex would be a leak.
    for p in sp.list_style_packs():
        html = sp.pack_overlay_html(p, width=1080, height=1920)
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", html), f"{p.id}: raw hex in overlay"
        if p.accent_geo != "none":
            assert "var(--mh-accent)" in html, f"{p.id}: accent geometry not role-driven"


# --------------------------------------------------------------------------- #
# Selection wiring: every generated card gets a pack (variety reaches output)
# --------------------------------------------------------------------------- #


def _brand(primary="#0E2A47", secondary="#C9A227", accent="#FFFFFF"):
    return BrandKit(
        profile_id="t",
        display_name="Test SC",
        primary_colour=primary,
        secondary_colour=secondary,
        accent_colour=accent,
        short_name="TSC",
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


def _gen(monkeypatch, *, seed=None, cid="c1", recent=None, brand=None, v2="1"):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", v2)
    return generate(
        _card(cid),
        None,
        brand or _brand(),
        profile_id="t",
        meet_name="Manchester Open",
        variation_seed=seed,
        recent_signatures=recent,
    )


def test_generate_assigns_a_valid_pack_and_stamps_signature(monkeypatch):
    b = _gen(monkeypatch)
    assert sp.style_pack_from_id(b.style_pack) is not None
    assert f"sp:{b.style_pack}" in b.variation_signature


def test_killswitch_assigns_no_pack(monkeypatch):
    b = _gen(monkeypatch, v2="0")
    assert b.style_pack == ""  # legacy engine → bare, byte-identical render


def test_explicit_seed_pack_is_reproducible(monkeypatch):
    want = sp.pick_style_pack(5).id
    assert _gen(monkeypatch, seed=5).style_pack == want
    # exact pick ignores the card id (the ?stable / ?variation_seed=N contract)
    assert _gen(monkeypatch, seed=5, cid="other").style_pack == want


def test_pack_spreads_across_a_content_pack(monkeypatch):
    recents: list[str] = []
    chosen: list[str] = []
    for i in range(12):
        b = _gen(monkeypatch, cid=f"card-{i}", recent=recents[-6:])
        chosen.append(b.style_pack)
        recents.append(b.variation_signature)
    # a pack of cards reads as varied per-card treatments, not one repeated look
    assert len(set(chosen)) >= 8


def test_pack_is_stable_per_card_on_rerender(monkeypatch):
    first = _gen(monkeypatch, cid="card-x").style_pack
    again = _gen(monkeypatch, cid="card-x").style_pack
    assert first == again


# --------------------------------------------------------------------------- #
# Legibility invariant: a pack is decoration, it never touches the role tokens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "primary,secondary,accent",
    [
        ("#0E2A47", "#C9A227", "#FFFFFF"),  # navy + gold, dark ground
        ("#F5F7FA", "#101820", None),       # light ground (dark text)
        ("#A30D2D", "#000000", None),       # single-colour kit
    ],
)
def test_pack_never_changes_resolved_role_tokens(monkeypatch, primary, secondary, accent):
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    brand = _brand(primary, secondary, accent)
    b = _gen(monkeypatch, seed=37, brand=brand)
    with_pack = resolved_role_vars_for_brief(b, brand)
    b.style_pack = ""  # strip the pack → bare
    bare = resolved_role_vars_for_brief(b, brand)
    # The seven core --mh-* role tokens (and thus every text-contrast pairing,
    # and still↔motion colour parity) are identical with or without the pack.
    assert with_pack == bare


# --------------------------------------------------------------------------- #
# Full HTML assembly: every archetype accepts a pack, injected exactly once
# --------------------------------------------------------------------------- #


def test_every_archetype_accepts_a_pack_overlay_once(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    import mediahub.graphic_renderer.render as R

    cap: dict[str, str] = {}

    def _fake_png(html, output_path, size):
        cap["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    brand = _brand()
    # a rich pack exercising ground + texture + accent geometry
    rich = next(p for p in sp.list_style_packs() if p.texture == "dots" and p.accent_geo == "ring")

    for arch in A.list_archetypes():
        b = generate(_card("cc"), None, brand, profile_id="t", meet_name="Open", variation_seed=0)
        b.layout_template = arch
        b.style_pack = rich.id
        R.render_brief(b, output_dir=tmp_path, size=(1080, 1350), brand_kit=brand)
        html = cap["html"]
        assert "{{" not in html and "}}" not in html, arch
        # the texture tile appears exactly once → injected, and never doubled
        assert html.count("background-size:18px 18px") == 1, f"{arch}: pack not injected once"
        # accent geometry rode the resolved accent role
        assert "var(--mh-accent)" in html, arch
