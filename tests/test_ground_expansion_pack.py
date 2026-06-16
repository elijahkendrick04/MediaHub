"""Ground-treatment expansion pack (roadmap G1.4).

The style-pack *ground* lever — the atmospheric, darken-only overlay painted
behind a card's content — grows four richer treatments:

  * ``gradient_mesh`` — soft multi-pool shadow mesh ringing a lit centre;
  * ``bokeh``        — scattered, defocused discs in the margins;
  * ``light_ray``    — raking crepuscular rays from a top corner;
  * ``paper_weave``  — a fine woven field of crossed thin lines.

Every one keeps the four guarantees the catalog lives by: deterministic,
**darken-only + fades to transparent** (so text contrast is never lowered below
the archetype's flat baseline), **brand-colour-only** (no invented hex — grounds
paint in neutral black alpha only), and **mirrored on the motion surface** so a
card's video carries the exact same ground its still graphic did.

No Node needed: ``StoryCard.tsx`` is checked as a source contract (the same
shape the existing parity suites use); the rest is pure-Python catalog shaping
plus one stubbed render to prove the ground reaches assembled HTML.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp
from mediahub.visual import motion


# The four grounds this expansion pack adds (G1.4).
NEW_GROUNDS = ("gradient_mesh", "bokeh", "light_ray", "paper_weave")

# Standard / bold ground alphas, mirrored from ``pack_overlay_html``.
_STD_ALPHA = 0.24
_BOLD_ALPHA = 0.34


def _story_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


# --------------------------------------------------------------------------- #
# Vocabulary, weights and labels
# --------------------------------------------------------------------------- #


def test_new_grounds_are_in_the_vocabulary():
    for g in NEW_GROUNDS:
        assert g in sp.GROUNDS, g
    # appended, not replacing — the original grounds are all still present.
    for g in ("flat", "vignette", "twotone", "edge_frame", "diagonal_fade"):
        assert g in sp.GROUNDS, g


def test_new_grounds_carry_weights_within_the_existing_scale():
    # weight() must not KeyError, and a ground never out-weighs the heaviest
    # pre-existing ground (2) — these stay within the tuned coherence scale.
    for g in NEW_GROUNDS:
        w = sp.normalise_pack(ground=g).weight
        assert isinstance(w, int)
        assert 1 <= w <= 2, f"{g}: weight {w} outside the ground scale"
    # bokeh is the sparse/light one; the field grounds carry full presence.
    assert sp.normalise_pack(ground="bokeh").weight == 1
    for g in ("gradient_mesh", "light_ray", "paper_weave"):
        assert sp.normalise_pack(ground=g).weight == 2, g


def test_new_grounds_carry_names_and_why_lines():
    # name()/why() must not KeyError on any new ground and must read sensibly.
    for g in NEW_GROUNDS:
        p = sp.normalise_pack(ground=g)
        assert p.name() and p.name() != "Clean", g
        why = p.why()
        assert why and "ground" in why, g


def test_normalise_accepts_new_grounds_and_still_rejects_junk():
    for g in NEW_GROUNDS:
        assert sp.normalise_pack(ground=g).ground == g
    # an unknown ground still coerces to the safe flat default (never unrenderable)
    assert sp.normalise_pack(ground="not_a_ground").ground == "flat"


# --------------------------------------------------------------------------- #
# Each ground renders a real, darken-only, brand-safe overlay
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ground", NEW_GROUNDS)
def test_new_ground_renders_darken_only_overlay(ground):
    html = sp.pack_overlay_html(sp.normalise_pack(ground=ground), width=1080, height=1350)
    # a real overlay, clipped and pointer-safe like every pack layer
    assert html, ground
    assert "position:absolute" in html and "pointer-events:none" in html
    # darken-only: paints in neutral black alpha, never a raw hex or white fill,
    # and a ground-only pack invents no accent colour.
    assert "rgba(0,0,0," in html, ground
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", html), f"{ground}: raw hex leaked"
    assert "255" not in html, f"{ground}: a non-darkening (white) stop leaked"
    assert "var(--mh-accent)" not in html, f"{ground}: ground-only pack drew accent"


@pytest.mark.parametrize("ground", NEW_GROUNDS)
def test_new_ground_fades_to_transparent(ground):
    # The legibility guarantee: every ground falls back to fully-transparent
    # black (rgba(0,0,0,0)) so the lit area is preserved — it can only *add*
    # darkness at the edges/threads, never sit opaque over content.
    css = sp._ground_layer(ground, _STD_ALPHA)
    assert css, ground
    assert "rgba(0,0,0,0)" in css, f"{ground}: no transparent fall-off (not darken-only-safe)"


def test_bold_density_darkens_more_than_standard():
    # The intensity tier scales the alpha up for bold, same as the legacy grounds.
    for g in NEW_GROUNDS:
        std = sp._ground_layer(g, _STD_ALPHA)
        bold = sp._ground_layer(g, _BOLD_ALPHA)
        assert std != bold, g
        assert str(_STD_ALPHA) in std and str(_BOLD_ALPHA) in bold, g


def test_new_grounds_are_mutually_and_globally_distinct():
    # Each new ground is a distinct treatment from the others and from every
    # pre-existing ground → distinct pixels, more real variety in the catalog.
    css_by_ground = {g: sp._ground_layer(g, _STD_ALPHA) for g in sp.GROUNDS if g != "flat"}
    assert len(set(css_by_ground.values())) == len(css_by_ground), "duplicate ground CSS"
    for g in NEW_GROUNDS:
        assert css_by_ground[g], g


# --------------------------------------------------------------------------- #
# Catalog: the new grounds are reachable, and the cap keeps packs tasteful
# --------------------------------------------------------------------------- #


def test_new_grounds_reach_the_pack_catalog():
    grounds_in_catalog = {p.ground for p in sp.list_style_packs()}
    for g in NEW_GROUNDS:
        assert g in grounds_in_catalog, f"{g} never appears in a buildable pack"


def test_new_grounds_grew_the_catalog_past_its_floors():
    # Additive grounds can only enlarge the deterministic template space; the
    # ≥1000-template product requirement holds with room to spare.
    assert sp.style_pack_count() > 1000
    assert sp.template_count(A.list_archetypes()) > 10000


def test_packs_using_new_grounds_respect_the_coherence_cap():
    # No pack built on a new ground stacks past its density's weight cap, so the
    # expansion can never produce an over-decorated card.
    for p in sp.list_style_packs():
        if p.ground in NEW_GROUNDS:
            cap = 3 if p.density == "bold" else 4
            assert p.weight <= cap, p.id


# --------------------------------------------------------------------------- #
# Still ↔ motion parity: the motion renderer executes the same grounds, byte-equal
# --------------------------------------------------------------------------- #


def test_new_grounds_are_in_the_motion_ground_set():
    src = _story_src()
    for g in NEW_GROUNDS:
        assert f'"{g}"' in src, f"{g} missing from StoryCard.tsx PACK_GROUNDS"
        assert f'case "{g}":' in src, f"{g} not handled in packGroundGradient"


def _canon(s: str) -> str:
    """Collapse a CSS string and the TSX source to a comparable form.

    The still emits one f-string with a concrete alpha; the motion side emits
    backtick chunks joined by ``+`` with ``${a}`` for the alpha. Unifying the
    alpha token, dropping the template-literal punctuation and stripping all
    whitespace lets the still's ground CSS be matched verbatim inside the TSX.
    """
    s = (
        s.replace("${a}", "%A%")
        .replace(str(_STD_ALPHA), "%A%")
        .replace("`", "")
        .replace("+", "")
    )
    return re.sub(r"\s+", "", s)


@pytest.mark.parametrize("ground", NEW_GROUNDS)
def test_motion_ground_css_matches_the_still_verbatim(ground):
    # The strongest parity guard: the exact gradient(s) the still paints for
    # this ground appear, character-for-character (modulo the alpha variable),
    # in StoryCard.tsx — so a reel/story beat darkens identically to its still.
    still = _canon(sp._ground_layer(ground, _STD_ALPHA))
    tsx = _canon(_story_src())
    assert still in tsx, f"{ground}: motion ground CSS drifted from the still"


def test_parity_drift_guard_still_iterates_every_ground():
    # Belt-and-braces: the catalog-wide parity test must keep covering grounds,
    # so a future ground addition that forgets the motion side fails loudly.
    src = _story_src()
    for g in sp.GROUNDS:
        if g == "flat":
            continue
        assert f'"{g}"' in src, f"ground {g!r} not mirrored in StoryCard.tsx"


# --------------------------------------------------------------------------- #
# End-to-end: a new ground reaches assembled card HTML through the real pipeline
# --------------------------------------------------------------------------- #


def _brand() -> BrandKit:
    return BrandKit(
        profile_id="t",
        display_name="Test SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#FFFFFF",
        short_name="TSC",
    )


def _card() -> dict:
    return {
        "id": "c1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }


@pytest.mark.parametrize("ground", NEW_GROUNDS)
def test_new_ground_reaches_assembled_html_once(monkeypatch, tmp_path, ground):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    import mediahub.graphic_renderer.render as R

    cap: dict[str, str] = {}

    def _fake_png(html, output_path, size):
        cap["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    brand = _brand()
    pack = sp.normalise_pack(ground=ground)  # ground-only, standard density
    assert sp.style_pack_from_id(pack.id) is not None  # it's a buildable pack

    b = generate(_card(), None, brand, profile_id="t", meet_name="Open", variation_seed=0)
    b.layout_template = "big_number_dominant"
    b.style_pack = pack.id
    R.render_brief(b, output_dir=tmp_path, size=(1080, 1350), brand_kit=brand)

    html = cap["html"]
    assert "{{" not in html and "}}" not in html, ground
    # the ground overlay is injected exactly once (its z-index:1 layer)
    assert html.count("z-index:1;pointer-events:none;background:") == 1, ground
    # and it carries this ground's darken-only CSS
    fragment = sp._ground_layer(ground, _STD_ALPHA).split(",")[0][:32]
    assert fragment in html, f"{ground}: ground CSS not present in assembled HTML"
