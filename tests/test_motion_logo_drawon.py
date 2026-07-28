"""svg-shape-decompose — opt-in logo draw-on for the reel cover + outro.

The brand logo is normally an opaque base64-SVG ``<img>``, so no per-path
element exists to trim-path. This feature decomposes the brand's OWN inline SVG
into ordered per-path draw-on data (deterministic, Python-side) for an OPT-IN
stroke draw-on on the two "brand statement" scenes, while the resting frame
stays the exact filled ``<img>`` (brand fidelity + still↔motion parity).

Two halves are verified here:

  * the Python decomposer (``_decompose_logo_svg``) returns ordered paths +
    viewBox for a real SVG, degrades honestly to ``None`` for a raster /
    circle-only / unsupported-command logo, and only enters the reel props +
    cache key when the caller opts in AND the decompose succeeds; and
  * the shared ``LogoDrawOn`` TSX as a SOURCE CONTRACT (no Node needed):
    inactive → the byte-identical ``<img>``; active → strokeDasharray /
    strokeDashoffset draw-on that cross-fades into the ``<img>``; frame-pure.
"""

from __future__ import annotations

import re

import pytest

from mediahub.visual import motion


# ---------------------------------------------------------------------------
# Python: _decompose_logo_svg
# ---------------------------------------------------------------------------

_STROKE_SVG = (
    '<svg viewBox="0 0 100 100">'
    '<path d="M0 0 L100 0 L100 100 Z" fill="#FF0000"/>'
    '<path d="M10 10 L20 20" stroke="#00FF00"/>'
    "</svg>"
)


def test_decompose_returns_ordered_paths_and_viewbox():
    out = motion._decompose_logo_svg(_STROKE_SVG)
    assert out is not None
    assert out["viewBox"] == "0 0 100 100"
    assert [p["d"] for p in out["paths"]] == [
        "M0 0 L100 0 L100 100 Z",
        "M10 10 L20 20",
    ], "paths must preserve document order"
    # Deterministic polyline arc-length (from paths.from_svg), rounded, > 0.
    assert all(p["len"] > 0 for p in out["paths"])
    # Each path keeps its OWN resolved colour — never an invented hue.
    assert out["paths"][0]["stroke"] == "#FF0000"
    assert out["paths"][1]["stroke"] == "#00FF00"


def test_decompose_inherits_ancestor_fill():
    """A path with no own paint inherits the ancestor <g>/<svg> colour — the
    same colour the browser paints the filled img, never a made-up hue."""
    out = motion._decompose_logo_svg(
        '<svg viewBox="0 0 10 10"><g fill="#123456">' '<path d="M0 0 L5 5"/></g></svg>'
    )
    assert out is not None
    assert out["paths"][0]["stroke"] == "#123456"


def test_decompose_derives_viewbox_from_width_height():
    out = motion._decompose_logo_svg('<svg width="50px" height="40px"><path d="M0 0 L10 0"/></svg>')
    assert out is not None
    assert out["viewBox"] == "0 0 50 40"


@pytest.mark.parametrize(
    "svg",
    [
        # circle-only / raster: no <path> to animate
        '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>',
        '<svg viewBox="0 0 10 10"><rect x="0" y="0" width="10" height="10"/></svg>',
        # unsupported command (A / S / T): honest degrade, never a mis-parse
        '<svg viewBox="0 0 10 10"><path d="M0 0 A5 5 0 0 1 10 10"/></svg>',
        '<svg viewBox="0 0 10 10"><path d="M0 0 S1 1 2 2"/></svg>',
        # no viewBox and no width/height → no coordinate space
        '<svg><path d="M0 0 L1 1"/></svg>',
    ],
)
def test_decompose_degrades_to_none(svg):
    assert motion._decompose_logo_svg(svg) is None


@pytest.mark.parametrize("bad", [None, "", "not svg", "data:image/svg+xml;base64,AAA", "<svg"])
def test_decompose_rejects_non_svg(bad):
    # "<svg" is malformed XML → ParseError → None (honest degrade).
    assert motion._decompose_logo_svg(bad) is None


def test_brand_logo_svg_extracts_raw_markup_only():
    assert motion._brand_logo_svg({"logo_svg": "<svg/>"}) == "<svg/>"
    assert motion._brand_logo_svg({"logoSvg": "  <svg/>  "}) == "<svg/>"
    # A data URI / text mark is NOT raw markup → "".
    assert motion._brand_logo_svg({"logo_svg": "data:image/svg+xml;base64,AAA"}) == ""
    assert motion._brand_logo_svg({"logo_svg": "ACME"}) == ""
    assert motion._brand_logo_svg(None) == ""


# ---------------------------------------------------------------------------
# Python: gate + cache-key fold (only present when opted in AND decomposed)
# ---------------------------------------------------------------------------


class _FakeBrand:
    profile_id = ""
    display_name = "Draw Club"
    short_name = "DC"
    primary_colour = "#0A2540"
    secondary_colour = "#000000"
    accent_colour = "#FFFFFF"
    logo_svg = _STROKE_SVG


def _reel_kwargs(**over):
    base = dict(
        cards_props=[{"id": "c1"}],
        brand_dict=motion._brand_to_dict(_FakeBrand()),
        brand_kit=_FakeBrand(),
        meet_name="Meet",
        duration_sec=8.5,
        audio_plan=None,
        briefs_list=[None],
        cta_props={},
        engine="remotion",
        format_name="story",
    )
    base.update(over)
    return base


def _captured_payload(monkeypatch, **over):
    """Drive _render_reel_one_format up to the cache-key computation and capture
    the cache_payload it hashes, without shelling out to Node."""
    captured = {}

    def _fake_hash(payload, *, kind):
        captured["payload"] = payload
        captured["kind"] = kind
        return "deadbeef" * 3  # 24 chars

    monkeypatch.setattr(motion, "_content_hash", _fake_hash)

    # A pre-seeded cache hit short-circuits before any render; make the cache
    # dir return a file that "exists" with size, by stubbing _cache_dir to a
    # tmp dir and pre-writing the file the fake hash names.
    import tempfile

    td = tempfile.mkdtemp()
    from pathlib import Path

    cache_dir = Path(td)
    (cache_dir / f"{'deadbeef' * 3}.mp4").write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(motion, "_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(motion, "_touch_cache_hit", lambda *a, **k: None)
    monkeypatch.setattr(motion, "_finish_cached_video", lambda *a, **k: {})
    monkeypatch.setattr(motion, "_publish", lambda cached, out: cached)

    kwargs = _reel_kwargs(out_path=cache_dir / "out.mp4", **over)
    motion._render_reel_one_format(**kwargs)
    return captured["payload"]


def test_logo_drawon_absent_from_payload_by_default(monkeypatch):
    payload = _captured_payload(monkeypatch, logo_drawon=False)
    assert "logoDrawOn" not in payload, "default reel must stay byte-identical"


def test_logo_drawon_folds_into_payload_when_active(monkeypatch):
    payload = _captured_payload(monkeypatch, logo_drawon=True)
    assert "logoDrawOn" in payload
    assert payload["logoDrawOn"]["viewBox"] == "0 0 100 100"
    assert len(payload["logoDrawOn"]["paths"]) == 2


def test_logo_drawon_stays_absent_when_logo_cannot_decompose(monkeypatch):
    """Opting in on a raster / circle-only logo degrades honestly: nothing
    enters the cache key, so the reel stays byte-identical."""

    class _CircleBrand(_FakeBrand):
        logo_svg = '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'

    payload = _captured_payload(monkeypatch, logo_drawon=True, brand_kit=_CircleBrand())
    assert "logoDrawOn" not in payload


# ---------------------------------------------------------------------------
# TSX source contract — the shared LogoDrawOn component
# ---------------------------------------------------------------------------

_LOGO_DRAWON = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "reel" / "logo_drawon.tsx"
_MEETREEL = motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx"


def _drawon_src() -> str:
    return _LOGO_DRAWON.read_text()


def test_component_file_exists():
    assert _LOGO_DRAWON.is_file(), "svg-shape-decompose builds sprint/reel/logo_drawon.tsx"


def test_exports_logo_drawon_component_and_config_type():
    src = _drawon_src()
    assert "export const LogoDrawOn" in src
    assert "LogoDrawConfig" in src


def test_inactive_branch_renders_the_exact_img():
    """Off (no opt-in / no paths / no logo) → the byte-identical filled
    ``<img>`` DOM the reel drew before this feature."""
    src = _drawon_src()
    # Guards the three inactive conditions and returns the img / null.
    assert re.search(r"if\s*\(\s*!logoDataUri\s*\)", src), "logo-less → null"
    assert "return null" in src
    assert re.search(r"!draw\.on\s*\|\|\s*!draw\.paths\s*\|\|\s*draw\.paths\.length\s*===\s*0", src)
    assert re.search(
        r"return\s*<img\s+src=\{logoDataUri\}\s+alt=\{alt\}\s+style=\{style\}", src
    ), "inactive branch must pass each site's full style through verbatim"


def test_active_branch_draws_on_via_dashoffset_then_crossfades_to_img():
    src = _drawon_src()
    assert "strokeDasharray" in src
    assert "strokeDashoffset" in src
    assert 'fill="none"' in src
    # The stroke uses each path's OWN colour, never an invented hue.
    assert "stroke={path.stroke}" in src
    # Cross-fade the filled <img> in over the tail so the settled frame is the
    # original logo.
    assert "fillIn" in src
    assert re.search(r"opacity:\s*fillIn", src)


def test_pure_function_of_the_frame():
    src = _drawon_src()
    assert "Math.random" not in src
    assert "Date.now" not in src and "new Date" not in src
    # Length comes from data (Python-side arc-length), never getTotalLength().
    assert "getTotalLength" not in src


def test_meetreel_wires_the_shared_component_and_schema():
    reel = _MEETREEL.read_text()
    assert 'from "./sprint/reel/logo_drawon"' in reel
    assert "<LogoDrawOn" in reel
    # Top-level zod fields — MUST NOT be nested in rhythm (zod strips undeclared
    # keys), so activation survives the schema.
    assert "logoDrawOn: z.boolean().default(false)" in reel
    assert 'logoViewBox: z.string().default("")' in reel
    assert "logoPaths" in reel
    # No raw brand.logoDataUri <img> should remain on the cover/outro sites — all
    # route through LogoDrawOn now.
    assert "src={brand.logoDataUri}" not in reel


def test_no_cdn_font_creep():
    src = _drawon_src()
    for needle in ("googleapis", "gstatic", "@remotion/google-fonts", "@fontsource"):
        assert needle not in src, needle
