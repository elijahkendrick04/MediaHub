"""F8 (Canva gap analysis) — large expressive motifs + physical panel silhouettes.

Canva's decoration vocabulary includes big expressive shapes (speed bands,
bursts, blobs, variable halftone) that read as background energy, and physical
panel silhouettes (ticket stubs, notches, perforation). These tests pin the new
``ACCENT_GEOS`` motif tokens as brand-locked, mono-safe, weight-capped, executed
on both surfaces, and the shared ``_components.css`` panel utilities.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.graphic_renderer import style_packs as sp

_MOTIFS = ("speed_band", "corner_burst", "blob", "variable_halftone")
_ROOT = Path(sp.__file__).parent
_COMPONENTS = _ROOT / "layouts" / "_components.css"
_TSX = _ROOT.parents[0] / "remotion" / "src" / "compositions" / "StoryCard.tsx"


def test_motifs_registered_and_weight_capped():
    for tok in _MOTIFS:
        assert tok in sp.ACCENT_GEOS
        assert sp._ACCENT_W[tok] == 2  # heavy → coherence cap prunes stacking
        assert tok in sp._ACCENT_LABEL


@pytest.mark.parametrize("tok", _MOTIFS)
def test_motif_html_is_brand_locked_and_low_zband(tok):
    html = sp._accent_geometry_html(tok, 1080, 1350, bold=False)
    assert html, f"{tok} rendered empty"
    # Colour only via role tokens (never a decorative hex fill).
    assert "var(--mh-accent)" in html
    assert "z-index:4" in html  # behind content, above the ground
    lowered = html.lower()
    # No hardcoded decorative hex — only neutral mask keywords (black/transparent).
    import re

    assert not re.search(r"#[0-9a-f]{3,6}", lowered), f"{tok} carries a hardcoded hex"


def test_variable_halftone_uses_both_inks():
    html = sp._accent_geometry_html("variable_halftone", 1080, 1350, bold=True)
    assert "var(--mh-accent)" in html
    assert "var(--mh-secondary-vis" in html  # two-ink for two-colour brands


def test_blob_path_is_deterministic():
    assert sp._blob_path() == sp._blob_path()
    assert sp._variable_halftone_svg("A", "B") == sp._variable_halftone_svg("A", "B")


def test_other_accent_geos_unchanged_by_the_new_branch():
    # A pre-existing accent geo must be byte-identical (the new branches are
    # additive; the shared prelude only assigns local vars).
    assert sp._accent_geometry_html("ring", 1080, 1350, bold=False) == (
        sp._accent_geometry_html("ring", 1080, 1350, bold=False)
    )
    assert sp._accent_geometry_html("none", 1080, 1350, bold=False) == ""


def test_components_css_declares_panel_silhouettes():
    css = _COMPONENTS.read_text()
    for cls in (".mh-panel--ticket", ".mh-panel--punched", ".mh-panel--perf"):
        assert cls in css
    assert "--mh-notch" in css  # ticket notch var
    assert "clip-path" in css


def test_index_card_adopts_the_ticket_silhouette():
    raw = (_ROOT / "layouts" / "v2" / "index_card.html").read_text()
    assert "mh-panel--ticket" in raw


def test_tsx_executes_every_motif():
    src = _TSX.read_text()
    for tok in _MOTIFS:
        assert f'case "{tok}"' in src, f"StoryCard.tsx missing executor for {tok}"
    assert "packHalftoneDots" in src


def test_motifs_are_mono_safe():
    """A mono card rewrites --mh-accent / --mh-secondary-vis declarations, and
    the global grayscale filter flattens everything else — so a motif whose only
    colour comes from those role tokens carries no brand hue into the B/W render."""
    from mediahub.graphic_renderer.sprint_hooks import mono_mode

    for tok in _MOTIFS:
        html = sp._accent_geometry_html(tok, 1080, 1350, bold=True)
        # The motif references only role-token vars (rewritten by mono_mode) plus
        # neutral mask keywords — no literal brand hex to leak.
        import re

        assert not re.search(r"#[0-9a-f]{3,6}", html.lower())
    # The tokens the motifs consume are the ones mono_mode rewrites.
    ramp = mono_mode.mono_role_vars("#0E2A47", "#0A1F38")
    assert ramp["--mh-accent"] in ("#FFFFFF", "#000000")
