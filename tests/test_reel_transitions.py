"""Reel transition system + expanded style-pack vocabularies (graphic/reel upgrade).

Two coordinated upgrades are pinned here:

  * the meet reel's transition vocabulary grew from the original three
    (crossfade / push / wipe) into a rank- and mood-aware system: the entry
    into the peak (top-ranked) beat earns one bold, mood-chosen cut while the
    connective beats between same-rank moments share a single quiet kind — the
    transitions.md craft contract (one primary character, 1–2 accents);
  * the still↔motion style-pack lever vocabularies (grounds / textures /
    accent geometries) were widened, multiplying the deterministic template
    catalog — and every new lever stays legibility-safe, brand-colour-only,
    and mirrored on both render surfaces.

No Node needed: the TSX is checked as a source contract (the same shape the
existing parity suites use), the rest is pure-Python catalog shaping.
"""

from __future__ import annotations

import re

from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp
from mediahub.visual import motion


def _reel_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()


def _story_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


# --------------------------------------------------------------------------- #
# Reel transition system — richer, rank/mood-aware, still deterministic
# --------------------------------------------------------------------------- #


def test_transition_vocabulary_is_richer_than_the_original_three():
    src = _reel_src()
    # The original three remain (back-compat for the connective handoffs)…
    for kind in ("crossfade", "push", "wipe"):
        assert f'"{kind}"' in src, kind
    # …plus the bold catalog the peak beat draws from.
    for kind in ("blur", "zoom", "whip", "iris"):
        assert f'"{kind}"' in src, f"transition kind {kind!r} not present"


def test_transition_picker_is_rank_and_mood_aware():
    src = _reel_src()
    # transitionFor still exists (deterministic per-beat picker, parity guard)…
    assert "export function transitionFor" in src
    # …and now takes the peak/mood direction the rank-weighted reel supplies.
    assert "peak" in src and "mood" in src
    # The peak beat is the only one that gets the bold cut; the rest share one
    # consistent connective kind derived from the reel.
    assert "const connective = transitionFor(" in src
    assert "isPeak" in src


def test_every_transition_kind_has_a_frame_pure_branch():
    """Each kind must be executed in TransitionWrap as a frame-derived
    transform/opacity/clip — never a CSS transition (which does not render)."""
    src = _reel_src()
    wrap = src.split("const TransitionWrap", 1)[1]
    for kind in ("push", "wipe", "blur", "zoom", "whip", "iris"):
        assert f'kind === "{kind}"' in wrap, f"{kind} not executed in TransitionWrap"
    # No CSS transitions/keyframes sneak in (motion is a pure function of frame).
    assert "transition:" not in wrap and "@keyframes" not in wrap


def test_transitions_stay_within_the_handoff_frame_budget():
    """Transitions ride `fadeInFrames` (≈0.35s) — they must not invent their
    own longer windows that would eat the next beat's build."""
    src = _reel_src()
    wrap = src.split("const TransitionWrap", 1)[1]
    # Every eased value is computed from the shared fadeInFrames window.
    assert "interpolate(frame, [0, fadeInFrames]" in wrap


# --------------------------------------------------------------------------- #
# Expanded style-pack vocabularies — bigger catalog, same guarantees
# --------------------------------------------------------------------------- #

NEW_GROUNDS = ("dual_fade", "top_corner_fade", "edge_frame", "diagonal_fade")
NEW_TEXTURES = ("weave", "scanline", "carbon", "chevron")
NEW_ACCENTS = ("double_rule", "dot_row", "cross_ticks", "corner_arc")


def test_new_levers_are_in_the_vocabularies():
    for g in NEW_GROUNDS:
        assert g in sp.GROUNDS, g
    for t in NEW_TEXTURES:
        assert t in sp.TEXTURES, t
    for a in NEW_ACCENTS:
        assert a in sp.ACCENT_GEOS, a


def test_catalog_grew_well_past_the_thousand_floor():
    # The widened levers multiply the deterministic template catalog.
    assert sp.style_pack_count() > 1000
    assert len(A.list_archetypes()) * sp.style_pack_count() > 10000


def test_every_new_lever_renders_legibility_safe_and_brand_only():
    # A pack built around each new lever must inject a real overlay, never a
    # raw hex (brand colour only via --mh-accent), and stay pointer-safe.
    for g in NEW_GROUNDS:
        html = sp.pack_overlay_html(sp.normalise_pack(ground=g), width=1080, height=1350)
        assert html and "position:absolute" in html, g
        assert not re.search(r"#[0-9a-fA-F]{3,6}", html), g
    for t in NEW_TEXTURES:
        html = sp.pack_overlay_html(sp.normalise_pack(texture=t), width=1080, height=1350)
        assert html and "pointer-events:none" in html, t
        assert not re.search(r"#[0-9a-fA-F]{3,6}", html), t
    for a in NEW_ACCENTS:
        html = sp.pack_overlay_html(sp.normalise_pack(accent_geo=a), width=1080, height=1350)
        assert html and "var(--mh-accent)" in html, a
        assert not re.search(r"#[0-9a-fA-F]{3,6}", html), a


def test_new_levers_are_mirrored_into_the_motion_renderer():
    """Still↔motion parity: a lever the still can emit must be executed in
    StoryCard.tsx, or a card's video would lose its still's decoration."""
    src = _story_src()
    for lever in (*NEW_GROUNDS, *NEW_TEXTURES, *NEW_ACCENTS):
        assert f'"{lever}"' in src, f"{lever} not mirrored in StoryCard.tsx"


def test_new_levers_carry_labels_and_weights():
    # name()/why()/weight must not KeyError on any new lever.
    for g in NEW_GROUNDS:
        p = sp.normalise_pack(ground=g)
        assert p.name() and p.why() and isinstance(p.weight, int)
    for t in NEW_TEXTURES:
        p = sp.normalise_pack(texture=t)
        assert p.name() and p.why()
    for a in NEW_ACCENTS:
        p = sp.normalise_pack(accent_geo=a)
        assert p.name() and p.why()
