"""QA-011 — the result time must FIT (never clip / wrap / collide) in EVERY
design-studio archetype.

Root cause this pins down: the live studio preview used to render the layout
engine at HALF the native CSS geometry (``PREVIEW_SCALE`` shrank
``StudioParams.size``). The v2 archetypes are authored with fixed-px furniture
(paddings, labels, the hanging quote glyph, the scorebug cells) that does *not*
scale with the canvas, so at half geometry that furniture was double-weighted and
squeezed / clipped / wrapped the result time across ~16 of the 29 archetypes —
broadcast_scorebug clipped "2:08.4" (the final "1" cut), quote_led_recap wrapped
"2:08." / "41" off the bottom edge, full_bleed_photo_lower_third collided the
kicker band with the club lockup and the event with the result chip. The full
download composed correctly because its geometry was native.

The fix composes the preview at the SAME native geometry as the download and
keeps the light, snappy payload via the RASTER (a DPR-1 capture + a final
downsample), so the preview is a faithful, lighter copy of the download — and a
normal 6-7 char swim time fits on one line in all 29 archetypes.

Two tiers:
  * a deterministic geometry guard (always runs) — the preview must compose at
    the native geometry, lightness living in the raster;
  * a real-Chromium structural audit (skips cleanly without Playwright/Chromium)
    — render EVERY archetype with a normal 7-char swim time and assert the time
    sits inside the card on one line, with no horizontal clip and no bottom
    overflow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mediahub.web import design_editor as DE

RESULT = "2:08.41"  # a normal 7-char swim time — the QA-011 repro value


# --------------------------------------------------------------------------- #
# Tier 1 — deterministic geometry guard (no browser)
# --------------------------------------------------------------------------- #
def test_preview_composes_at_native_geometry_not_half_scale():
    """The preview must compose at NATIVE geometry, identical to the download.

    This is the precise regression guard: the bug shrank the composition
    geometry (``PREVIEW_SCALE`` * native), mis-scaling each archetype's fixed-px
    furniture and clipping the result time. Lightness must instead come from the
    raster (``preview_raster_size`` / a DPR-1 ``render_quality``).
    """
    for fmt_id, _label, native in DE.FORMATS:
        prev = DE.coerce_params({"format": fmt_id, "full": False})
        full = DE.coerce_params({"format": fmt_id, "full": True})
        assert prev.size == native, (
            f"{fmt_id}: preview must COMPOSE at native {native}, got {prev.size} "
            "(a shrunken preview geometry clips the result time — QA-011)"
        )
        assert full.size == native
        # the preview stays light at the RASTER, not the geometry
        assert prev.preview_raster_size == (
            round(native[0] * DE.PREVIEW_SCALE),
            round(native[1] * DE.PREVIEW_SCALE),
        )
        assert prev.preview_raster_size != prev.size  # still a lighter payload
        assert full.preview_raster_size == native  # download keeps native pixels
        assert prev.render_quality == "fast"  # light DPR-1 capture
        assert full.render_quality is None  # default profile for the download


def test_downscale_png_is_safe_and_lossless_noop_when_not_needed():
    """The preview downsample never breaks a render: a no-op below target, a
    graceful pass-through on non-image bytes."""
    import io

    from PIL import Image

    im = Image.new("RGB", (1080, 1350), (14, 91, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    native = buf.getvalue()

    small = DE.downscale_png_bytes(native, (540, 675))
    assert Image.open(io.BytesIO(small)).size == (540, 675)
    # already at/below the target → bytes returned unchanged
    assert DE.downscale_png_bytes(small, (540, 675)) == small
    # non-image bytes never raise — a preview never fails over a raster tweak
    assert DE.downscale_png_bytes(b"not-a-png", (540, 675)) == b"not-a-png"


# --------------------------------------------------------------------------- #
# Tier 2 — real-Chromium structural audit of every archetype
# --------------------------------------------------------------------------- #
def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            b.close()
        return True
    except Exception:
        return False


_PLAYWRIGHT = _have_playwright()

# Find the deepest element that OWNS the result text, then report whether it sits
# inside the card on a single line (line count via the element's own text rects).
_MEASURE_JS = r"""
(RESULT) => {
  let node = null;
  for (const el of document.querySelectorAll('*')) {
    const own = [...el.childNodes]
      .filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if (own === RESULT) node = el;
  }
  if (!node) return { found: false };
  const r = node.getBoundingClientRect();
  const rng = document.createRange();
  rng.selectNodeContents(node);
  const tops = new Set(
    [...rng.getClientRects()].filter(x => x.width > 0.5).map(x => Math.round(x.top))
  );
  return {
    found: true,
    right: r.right, bottom: r.bottom,
    scrollW: node.scrollWidth, clientW: node.clientWidth,
    lines: Math.max(1, tops.size),
  };
}
"""


def _capture_preview_html(archetype: str, monkeypatch) -> tuple[str, tuple[int, int]]:
    """Assemble the studio PREVIEW HTML for one archetype (Chromium stubbed)."""
    import mediahub.graphic_renderer.render as R

    params = DE.coerce_params(
        {
            "archetype": archetype,
            "format": "feed_portrait",
            "full": False,
            "text": dict(DE.DEFAULT_TEXT),
        }
    )
    brief = DE.build_brief_from_params(params)
    kit = DE.brand_kit_for_params(params)
    cap: dict = {}

    def _fake_png(html, output_path, size, **kwargs):
        cap["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    with tempfile.TemporaryDirectory() as d:
        R.render_brief(
            brief,
            output_dir=d,
            size=params.size,
            format_name=params.format_id,
            brand_kit=kit,
            quality=params.render_quality,
        )
    return cap["html"], params.size


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_result_time_fits_in_every_studio_archetype(monkeypatch, tmp_path):
    """Render every archetype with a normal 7-char time and assert it fits.

    The audit measures the composed preview DOM (the geometry the studio renders
    at) in a real browser: the result element must sit inside the card, on one
    line, with no horizontal clip. Before the fix (half-scale composition) ~16 of
    29 archetypes failed here; after it, all fit.
    """
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    from playwright.sync_api import sync_playwright

    from mediahub.graphic_renderer import archetypes

    names = archetypes.list_archetypes()
    assert len(names) >= 29, f"expected the full archetype library, got {len(names)}"

    pages: dict[str, tuple[Path, tuple[int, int]]] = {}
    for name in names:
        html, size = _capture_preview_html(name, monkeypatch)
        assert RESULT in html, f"{name}: studio default time {RESULT!r} missing from HTML"
        page_path = tmp_path / f"{name}.html"
        page_path.write_text(html, encoding="utf-8")
        pages[name] = (page_path, size)

    tol = 1.0
    failures: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        try:
            for name, (path, (W, H)) in pages.items():
                page = browser.new_page(
                    viewport={"width": W, "height": H}, device_scale_factor=1
                )
                try:
                    page.goto(path.as_uri(), wait_until="networkidle", timeout=30_000)
                    page.evaluate("async () => { await document.fonts.ready; }")
                    m = page.evaluate(_MEASURE_JS, RESULT)
                finally:
                    page.close()
                if not m.get("found"):
                    failures.append(f"{name}: result text {RESULT!r} not found in DOM")
                    continue
                if m["right"] > W + tol:
                    failures.append(
                        f"{name}: time overflows the right edge ({m['right']:.0f} > {W})"
                    )
                if m["bottom"] > H + tol:
                    failures.append(
                        f"{name}: time overflows the bottom edge ({m['bottom']:.0f} > {H})"
                    )
                if m["scrollW"] > m["clientW"] + tol:
                    failures.append(
                        f"{name}: time clipped horizontally "
                        f"(scrollW {m['scrollW']} > clientW {m['clientW']})"
                    )
                if m["lines"] > 1:
                    failures.append(
                        f"{name}: a 7-char time wrapped onto {m['lines']} lines"
                    )
        finally:
            browser.close()

    assert not failures, "QA-011 result-time fit failures:\n  " + "\n  ".join(failures)
