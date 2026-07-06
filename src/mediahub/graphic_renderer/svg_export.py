"""SVG vector export path (roadmap G1.13).

Produces an **editable, outlined-font SVG** alongside the rasterised PNG for any
card the still-graphic renderer draws. The SVG is genuine vector — text is
converted to glyph *outlines* (vector ``<path>`` data, no embedded font, no
``<text>`` element), shapes/backgrounds/dividers are vector ``<path>`` elements,
and the whole document carries no flattened screenshot. The only raster that can
appear is a real embedded photo (an athlete cut-out, a venue shot), and even
that can be dropped for a strictly raster-free export (``embed_images=False``).

How it works
------------
There is no faithful "HTML → SVG" primitive in a browser, so we go through the
one vector format Chromium *does* emit and that we already render with elsewhere
(``print_export.py``): a **PDF**.

1. Chromium renders the exact same card HTML to a single-page **vector PDF**
   (same ``file://`` navigation + ``document.fonts.ready`` wait + renderer
   network lockdown as ``render.render_html_to_png``, so the layout, the
   self-hosted fonts and the brand colours are pixel-identical to the PNG).
2. **PDFium** (``pypdfium2`` — already a dependency, and the same engine family
   Chromium itself uses for PDF) reads the page back. We walk its page objects
   in paint order (recursing into form XObjects with composed transforms) and
   re-emit each as SVG:
     - **text** → for every glyph we pull the outline via
       ``FPDFFont_GetGlyphPath`` and place it with the per-glyph text matrix, so
       fonts are outlined (the SVG needs no font installed to render);
     - **paths** (backgrounds, chips, rules, gradients, photo scrims) → vector
       ``<path>`` with the object's fill/stroke/even-odd rule. PDFium reports a
       meaningless placeholder colour for gradient/pattern/blended fills, so for
       every path we **verify the reported fill against the actually-rendered
       pixels** (one PDFium raster of the page) and use the true sampled colour
       when they disagree — a gradient scrim resolves to the colour it really
       shows, never PDFium's grey stand-in;
     - **images** (photos) → an embedded ``<image>`` of the photo's footprint
       cropped from the rendered page, so its ``object-fit`` crop and any
       non-rectangular clip (a disc, a rounded frame) come out exactly as shown
       without guessing a clip PDFium won't hand us; a labelled placeholder rect
       in strict no-raster mode.

This keeps the deterministic-engine contract: nothing here is an AI guess — it
is a mechanical, reproducible transcription of what Chromium drew, with colours
read from the real rendered pixels. When Playwright/Chromium or PDFium is
missing we raise an honest ``SvgExportUnavailable`` rather than emit a fake SVG
(CLAUDE.md: a clear error beats a stub).

Public API
----------
- ``html_to_svg(html, size, *, embed_images=True, ...)`` → SVG string.
- ``render_html_to_svg(html, output_path, size, ...)`` → write the SVG, return
  its path (the vector sibling of ``render_html_to_png``).
- ``svg_sidecar_path(image_path)`` → the ``<stem>.svg`` path beside a PNG.
- ``export_svg_alongside(image_path, html, size, ...)`` → write the SVG next to
  an already-rendered PNG. ``render_brief`` calls this when
  ``MEDIAHUB_SVG_SIDECAR=1`` so an SVG lands beside every PNG; otherwise it is
  available on demand.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import logging
import os
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional
from xml.sax.saxutils import escape as _xml_escape

log = logging.getLogger(__name__)

# A path's PDFium-reported fill is "trusted" only when it matches the rendered
# pixels to within this per-channel delta; beyond it the fill is a gradient /
# pattern / blended layer and we use the sampled colour instead.
_FILL_MATCH_DELTA = 22


class SvgExportError(RuntimeError):
    """A render-time SVG-export failure (bad input, conversion error)."""


class SvgExportUnavailable(SvgExportError):
    """Playwright/Chromium or PDFium is not installed — no honest SVG possible."""


# ---------------------------------------------------------------------------
# Small formatting / colour / matrix helpers
# ---------------------------------------------------------------------------


def _num(x: float) -> str:
    """Compact fixed-point: 3 d.p., trailing zeros trimmed (``12.50`` → ``12.5``)."""
    s = f"{x:.3f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _hex(r: int, g: int, b: int) -> str:
    return f"#{int(r) & 255:02x}{int(g) & 255:02x}{int(b) & 255:02x}"


def _opacity_attr(name: str, alpha: int) -> str:
    """Return ``" name-opacity=…"`` only when alpha is not fully opaque."""
    if alpha >= 255:
        return ""
    return f' {name}="{_num(alpha / 255.0)}"'


# Affine matrices are 6-tuples ``(a, b, c, d, e, f)`` == [[a c e],[b d f]],
# matching both the PDF and SVG conventions: p' = (a·x + c·y + e, b·x + d·y + f).
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _matmul(m1: tuple, m2: tuple) -> tuple:
    """Compose two affines so that applying the result == apply m2 then m1."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply(m: tuple, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _mat_scale(m: tuple) -> float:
    a, b, c, d, _e, _f = m
    return abs(a * d - b * c) ** 0.5


# ---------------------------------------------------------------------------
# Chromium HTML → single-page vector PDF (in memory)
# ---------------------------------------------------------------------------


def _render_html_to_pdf_bytes(
    html: str, size: tuple[int, int], *, allow_net: bool = False
) -> bytes:
    """Headless-Chromium print-to-PDF at the card's exact pixel size → PDF bytes.

    Mirrors ``render.render_html_to_png`` exactly where it matters: the HTML is
    navigated as a real ``file://`` document (so self-hosted ``file://`` WOFF2
    fonts load), the render waits for ``document.fonts.ready``, and the render
    context is network-locked to ``file:``/``data:``/``about:`` unless the
    operator opts out (``MEDIAHUB_RENDERER_ALLOW_NET=1`` or ``allow_net=True``).
    The page box is set to ``width``px × ``height``px with zero margin so the PDF
    media box is the card 1:1 (in points).
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # pragma: no cover - environment-dependent
        raise SvgExportUnavailable(f"Playwright not installed: {e}") from e

    width, height = size
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="mh_svg_"))
    page_path = tmp / "card.render.html"
    page_path.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--font-render-hinting=none"])
            ctx = browser.new_context()
            # Renderer lockdown (THREAT_MODEL §3) — identical policy to the PNG
            # path: card HTML carries user-influenced text, so the context gets
            # no network beyond file://, data:, about:. Kills SSRF/exfiltration
            # through a template-injected fetch.
            if not allow_net and os.environ.get("MEDIAHUB_RENDERER_ALLOW_NET", "") != "1":

                def _guard(route):
                    url = route.request.url
                    if url.startswith(("file://", "data:", "about:")):
                        route.continue_()
                    else:
                        log.warning(
                            "svg renderer blocked network request: %s", url.split("?")[0][:200]
                        )
                        route.abort()

                ctx.route("**/*", _guard)
            page = ctx.new_page()
            page.goto(page_path.as_uri(), wait_until="networkidle", timeout=30_000)
            try:
                page.evaluate(
                    "() => (document.fonts && document.fonts.ready) "
                    "? document.fonts.ready.then(() => true) : true"
                )
            except Exception:
                try:
                    page.wait_for_timeout(400)
                except Exception:
                    pass
            pdf = page.pdf(
                width=f"{width}px",
                height=f"{height}px",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                prefer_css_page_size=False,
            )
            browser.close()
    finally:
        try:
            page_path.unlink()
        except OSError:
            pass
        try:
            tmp.rmdir()
        except OSError:
            pass
    return pdf


# ---------------------------------------------------------------------------
# PDFium path/segment plumbing
# ---------------------------------------------------------------------------


def _read_segments(
    count: int, get_seg: Callable[[int], object]
) -> list[tuple[int, float, float, int]]:
    """Read ``count`` path segments → ``[(type, x, y, close), …]``.

    Shared by both vector paths (``FPDFPath_*``) and glyph outlines
    (``FPDFGlyphPath_*``) — the segment accessor API is identical for both.
    """
    import pypdfium2.raw as C

    out: list[tuple[int, float, float, int]] = []
    for i in range(count):
        seg = get_seg(i)
        if not seg:
            continue
        x = ctypes.c_float()
        y = ctypes.c_float()
        C.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
        out.append(
            (
                C.FPDFPathSegment_GetType(seg),
                x.value,
                y.value,
                1 if C.FPDFPathSegment_GetClose(seg) else 0,
            )
        )
    return out


def _segments_to_d(
    segments: list[tuple[int, float, float, int]],
    point: Callable[[float, float], tuple[float, float]],
) -> str:
    """Turn PDFium segments into an SVG ``d`` string via ``point`` (raw → svg px).

    PDFium encodes a cubic Bézier as three consecutive ``BEZIERTO`` points
    (two control points + endpoint); we regroup those into one ``C`` command.
    A segment's ``close`` flag appends ``Z``.
    """
    import pypdfium2.raw as C

    parts: list[str] = []
    bez: list[tuple[float, float]] = []
    for stype, rx, ry, close in segments:
        px, py = point(rx, ry)
        if stype == C.FPDF_SEGMENT_MOVETO:
            parts.append(f"M{_num(px)} {_num(py)}")
        elif stype == C.FPDF_SEGMENT_LINETO:
            parts.append(f"L{_num(px)} {_num(py)}")
        elif stype == C.FPDF_SEGMENT_BEZIERTO:
            bez.append((px, py))
            if len(bez) == 3:
                (c1x, c1y), (c2x, c2y), (ex, ey) = bez
                parts.append(
                    f"C{_num(c1x)} {_num(c1y)} {_num(c2x)} {_num(c2y)} {_num(ex)} {_num(ey)}"
                )
                bez = []
        if close:
            parts.append("Z")
    return "".join(parts)


def _d_and_bbox(segments, point) -> tuple[str, tuple[float, float, float, float], bool]:
    """``_segments_to_d`` plus the svg-space bbox and an "axis-aligned rect?" flag.

    The flag marks a plain rectangle (no curves, every vertex on the bbox edge):
    those are the shapes Chromium re-emits as unclipped fills for clipped
    composites, so they get a bitmap corner-check before we trust them. Curved
    shapes (circles, rounded pills) and full-bleed grounds are never mistaken
    for one.
    """
    import pypdfium2.raw as C

    box = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    pts: list[tuple[float, float]] = []
    has_curve = False

    def tracked(x: float, y: float) -> tuple[float, float]:
        sx, sy = point(x, y)
        box[0] = min(box[0], sx)
        box[1] = min(box[1], sy)
        box[2] = max(box[2], sx)
        box[3] = max(box[3], sy)
        pts.append((sx, sy))
        return sx, sy

    for stype, *_rest in segments:
        if stype == C.FPDF_SEGMENT_BEZIERTO:
            has_curve = True
    d = _segments_to_d(segments, tracked)
    bbox = (box[0], box[1], box[2], box[3])
    w = box[2] - box[0]
    h = box[3] - box[1]
    is_rect = (
        not has_curve
        and len(pts) <= 6
        and w > 4
        and h > 4
        and all(
            abs(px - box[0]) <= 0.6
            or abs(px - box[2]) <= 0.6
            or abs(py - box[1]) <= 0.6
            or abs(py - box[3]) <= 0.6
            for px, py in pts
        )
    )
    return d, bbox, is_rect


def _matrix(obj_raw) -> tuple:
    import pypdfium2.raw as C

    m = C.FS_MATRIX()
    C.FPDFPageObj_GetMatrix(obj_raw, ctypes.byref(m))
    return (m.a, m.b, m.c, m.d, m.e, m.f)


def _obj_fill(obj_raw) -> tuple[int, int, int, int]:
    import pypdfium2.raw as C

    r = ctypes.c_uint()
    g = ctypes.c_uint()
    b = ctypes.c_uint()
    a = ctypes.c_uint()
    if not C.FPDFPageObj_GetFillColor(
        obj_raw, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)
    ):
        return 0, 0, 0, 0
    return r.value, g.value, b.value, a.value


def _obj_stroke(obj_raw) -> tuple[str, int, float]:
    import pypdfium2.raw as C

    r = ctypes.c_uint()
    g = ctypes.c_uint()
    b = ctypes.c_uint()
    a = ctypes.c_uint()
    C.FPDFPageObj_GetStrokeColor(
        obj_raw, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)
    )
    w = ctypes.c_float()
    C.FPDFPageObj_GetStrokeWidth(obj_raw, ctypes.byref(w))
    return _hex(r.value, g.value, b.value), a.value, w.value


def _draw_mode(obj_raw) -> tuple[int, bool]:
    import pypdfium2.raw as C

    fillmode = ctypes.c_int()
    stroke = ctypes.c_int()
    C.FPDFPath_GetDrawMode(obj_raw, ctypes.byref(fillmode), ctypes.byref(stroke))
    return fillmode.value, bool(stroke.value)


# ---------------------------------------------------------------------------
# Rendered-pixel sampling — the source of truth for non-solid fills
# ---------------------------------------------------------------------------


def _samples(pil, points) -> list[tuple[int, int, int]]:
    """RGB of each in-bounds sample point."""
    w, h = pil.size
    out: list[tuple[int, int, int]] = []
    for fx, fy in points:
        px, py = int(round(fx)), int(round(fy))
        if 0 <= px < w and 0 <= py < h:
            out.append(tuple(pil.getpixel((px, py))[:3]))
    return out


def _median_of(samples) -> Optional[tuple[int, int, int]]:
    """Per-channel median of pre-collected samples (robust to outliers)."""
    if not samples:
        return None
    rs = sorted(s[0] for s in samples)
    gs = sorted(s[1] for s in samples)
    bs = sorted(s[2] for s in samples)
    m = len(samples) // 2
    return rs[m], gs[m], bs[m]


def _spread(samples) -> int:
    """Largest per-channel range across samples (0 == perfectly uniform)."""
    if not samples:
        return 0
    return max(max(s[c] for s in samples) - min(s[c] for s in samples) for c in (0, 1, 2))


def _median(pil, points) -> Optional[tuple[int, int, int]]:
    return _median_of(_samples(pil, points))


def _corner_points(bbox) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = bbox
    ix = max(3.0, min((x1 - x0) * 0.08, 14.0))
    iy = max(3.0, min((y1 - y0) * 0.08, 14.0))
    return [(x0 + ix, y0 + iy), (x1 - ix, y0 + iy), (x1 - ix, y1 - iy), (x0 + ix, y1 - iy)]


def _perimeter_points(bbox) -> list[tuple[float, float]]:
    """Corners + edge midpoints, inset a little — a shape's *own* edge colour.

    Background/panels are rarely covered at their edges (text and motifs sit
    inboard), so the perimeter is the honest read of the shape's fill even when
    a photo or headline blankets its middle.
    """
    x0, y0, x1, y1 = bbox
    ix = max(3.0, min((x1 - x0) * 0.08, 14.0))
    iy = max(3.0, min((y1 - y0) * 0.08, 14.0))
    x0, y0, x1, y1 = x0 + ix, y0 + iy, x1 - ix, y1 - iy
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (mx, y0), (mx, y1), (x0, my), (x1, my)]


def _center_points(bbox) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = bbox
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = (x1 - x0) * 0.18, (y1 - y0) * 0.18
    return [(mx, my), (mx - dx, my), (mx + dx, my), (mx, my - dy), (mx, my + dy)]


def _close(c1, c2, tol: int = _FILL_MATCH_DELTA) -> bool:
    return max(abs(c1[0] - c2[0]), abs(c1[1] - c2[1]), abs(c1[2] - c2[2])) <= tol


# Sentinel returned by _classify_fill for an unreconstructable clipped composite.
_SKIP = object()
_SOLID_SPREAD = 24  # max perimeter colour range for a fill to read as a flat solid


def _overlaps_image(bbox, image_boxes) -> bool:
    """Does this fill's box mostly cover an already-placed photo footprint?

    A large fill laid over a photo is a scrim / colour treatment the photo shows
    through; we can't honour its blend, so we drop it and keep the photo rather
    than bake an opaque block over it.
    """
    x0, y0, x1, y1 = bbox
    for ix0, iy0, ix1, iy1 in image_boxes:
        ox = max(0.0, min(x1, ix1) - max(x0, ix0))
        oy = max(0.0, min(y1, iy1) - max(y0, iy0))
        inter = ox * oy
        img_area = max(1.0, (ix1 - ix0) * (iy1 - iy0))
        if inter >= 0.6 * img_area:
            return True
    return False


def _classify_fill(obj_raw, bbox, is_rect: bool, has_stroke: bool, ctx, is_top_overlay: bool):
    """Decide a path's fill from PDFium + the rendered pixels.

    Returns ``(#hex, alpha)`` to paint, ``None`` for no fill, or ``_SKIP`` to
    drop the shape. PDFium reports a placeholder colour for gradient / pattern /
    blended fills, so the rendered page raster is the arbiter:

    - the reported colour matches a *uniform* perimeter → a genuine solid (kept
      even when a photo or headline covers the middle);
    - otherwise the fill is a gradient / pattern / blended layer baked to the
      colour it actually shows. The first large fill is always kept — it is the
      base ground. After a ground exists, two layers can't be revectored and are
      dropped rather than painted as a wrong opaque block: a *further* full-bleed
      sheen with nothing painted after it (a top tint / corner-light overlay the
      design shows through), and — once content exists beneath — a plain
      rectangle whose corners disagree with its centre (a fill Chromium clipped
      to a circle/rounded shape but emitted unclipped, its clip unreadable). A
      second ground region (a split background) or a scrim with content stacked
      on it is kept.
    """
    pil = ctx.pil
    r, g, b, a = _obj_fill(obj_raw)
    if a <= 0:
        return None
    reported = (r, g, b)
    peri = _samples(pil, _perimeter_points(bbox))
    peri_med = _median_of(peri)
    if peri_med is None:
        return _hex(r, g, b), a
    x0, y0, x1, y1 = bbox
    big = (x1 - x0) * (y1 - y0) >= 0.55 * ctx.width_px * ctx.height_px
    if _close(reported, peri_med) and _spread(peri) <= _SOLID_SPREAD:
        if big:
            ctx.bg_emitted = True
        return _hex(r, g, b), a  # genuine, uniform solid fill

    # Placeholder fill (gradient / pattern / blended layer).
    cen = _median(pil, _center_points(bbox)) or peri_med
    if big:
        if _overlaps_image(bbox, ctx.image_boxes):
            return _SKIP  # a scrim / treatment over a photo — let the photo show
        if ctx.bg_emitted and is_top_overlay:
            return _SKIP  # a later full-bleed sheen the design shows through
        ctx.bg_emitted = True
        return _hex(*peri_med), 255  # base/secondary ground — bake its edge colour
    if is_rect and not has_stroke and ctx.content_drawn:
        corners = _samples(pil, _corner_points(bbox))
        if corners and sum(1 for c in corners if _close(c, cen)) < len(corners) - 1:
            return _SKIP  # rectangle clipped to a smaller shape, emitted unclipped
    return _hex(*cen), 255  # bake the colour the shape actually shows


# ---------------------------------------------------------------------------
# Per-object SVG emitters
# ---------------------------------------------------------------------------


@dataclass
class _Ctx:
    to_svg: Callable[[float, float], tuple[float, float]]
    pil: object  # rendered page bitmap (PIL RGB) for fill sampling + photo crops
    textpage: object
    obj_chars: dict
    width_px: int
    height_px: int
    embed_images: bool
    clip: bool
    content_drawn: bool = False
    bg_emitted: bool = False
    image_boxes: list = field(default_factory=list)


def _emit_path(obj_raw, eff: tuple, ctx: _Ctx, is_top_overlay: bool = False) -> str:
    """A vector path object → an SVG ``<path>`` (fill + optional stroke)."""
    import pypdfium2.raw as C

    n = C.FPDFPath_CountSegments(obj_raw)
    if n <= 0:
        return ""
    segs = _read_segments(n, lambda i: C.FPDFPath_GetPathSegment(obj_raw, i))

    def point(lx: float, ly: float) -> tuple[float, float]:
        return ctx.to_svg(*_apply(eff, lx, ly))

    d, bbox, is_rect = _d_and_bbox(segs, point)
    if not d:
        return ""

    fillmode, has_stroke = _draw_mode(obj_raw)
    attrs: list[str] = []
    if fillmode == C.FPDF_FILLMODE_NONE:
        attrs.append('fill="none"')
    else:
        fill = _classify_fill(obj_raw, bbox, is_rect, has_stroke, ctx, is_top_overlay)
        if fill is _SKIP:
            return ""
        if fill is None:
            attrs.append('fill="none"')
        else:
            fhex, falpha = fill
            attrs.append(f'fill="{fhex}"{_opacity_attr("fill", falpha)}')
            if fillmode == C.FPDF_FILLMODE_ALTERNATE:
                attrs.append('fill-rule="evenodd"')
    if has_stroke:
        shex, salpha, swidth = _obj_stroke(obj_raw)
        if salpha > 0 and swidth > 0:
            attrs.append(
                f'stroke="{shex}"{_opacity_attr("stroke", salpha)} '
                f'stroke-width="{_num(max(swidth * _mat_scale(eff), 0.1))}"'
            )
    return f'<path {" ".join(a for a in attrs if a)} d="{d}"/>'


def _needs_shaping(u: int) -> bool:
    """Scripts Chromium shapes contextually (Arabic joining forms, Indic
    conjuncts, …). ``FPDFFont_GetGlyphPath`` looks a glyph up by its *unicode
    codepoint*, so these would outline as isolated/default forms — silently
    wrong. Such runs get the raster fallback instead."""
    return (
        0x0590 <= u <= 0x08FF  # Hebrew, Arabic, Syriac, Thaana, NKo, Arabic Extended
        or 0x0900 <= u <= 0x0DFF  # Indic scripts (Devanagari … Sinhala)
        or 0x0E00 <= u <= 0x0EFF  # Thai, Lao
        or 0x0F00 <= u <= 0x0FFF  # Tibetan
        or 0x1000 <= u <= 0x109F  # Myanmar
        or 0x1780 <= u <= 0x17FF  # Khmer
        or 0xFB50 <= u <= 0xFDFF  # Arabic presentation forms A
        or 0xFE70 <= u <= 0xFEFF  # Arabic presentation forms B
    )


def _raster_text_footprint(char_indices, ctx: "_Ctx") -> str:
    """Fidelity fallback: embed the text run's rendered footprint as pixels.

    Used when glyph outlining can't be faithful (shaped script, or a glyph the
    by-unicode lookup can't find). The rendered page already shows the text
    exactly as Chromium shaped it, so cropping the union of the run's char
    boxes — like ``_emit_image`` does for photos — keeps the SVG honest at the
    cost of editability for that one run. Empty string when no usable box.
    """
    import pypdfium2.raw as C

    xs: list[float] = []
    ys: list[float] = []
    left = ctypes.c_double()
    right = ctypes.c_double()
    bottom = ctypes.c_double()
    top = ctypes.c_double()
    for ci in char_indices:
        if not C.FPDFText_GetCharBox(
            ctx.textpage,
            ci,
            ctypes.byref(left),
            ctypes.byref(right),
            ctypes.byref(bottom),
            ctypes.byref(top),
        ):
            continue
        for px, py in (
            (left.value, bottom.value),
            (right.value, top.value),
        ):
            sx, sy = ctx.to_svg(px, py)
            xs.append(sx)
            ys.append(sy)
    if not xs:
        return ""
    W, H = ctx.pil.size
    cx0, cy0 = max(0, int(min(xs)) - 1), max(0, int(min(ys)) - 1)
    cx1, cy1 = min(W, int(round(max(xs))) + 1), min(H, int(round(max(ys))) + 1)
    if cx1 - cx0 < 1 or cy1 - cy0 < 1:
        return ""
    try:
        crop = ctx.pil.crop((cx0, cy0, cx1, cy1))
        buf = BytesIO()
        crop.save(buf, format="PNG", optimize=True)
    except Exception as ex:  # pragma: no cover - defensive
        log.warning("svg export: could not crop text footprint (%s)", ex)
        return ""
    href = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<image class="mh-text-raster" x="{cx0}" y="{cy0}" '
        f'width="{cx1 - cx0}" height="{cy1 - cy0}" '
        f'preserveAspectRatio="none" href="{href}"/>'
    )


def _emit_text_object(obj_raw, char_indices, ctx: "_Ctx") -> str:
    """A text object → one ``<path>`` of outlined glyphs (no font dependency).

    When the run can't be outlined faithfully — a shaped script (Arabic, Indic,
    Thai, …) whose contextual forms a by-unicode lookup would flatten, or a
    printable glyph the font lookup fails on — the whole run falls back to a
    raster embed of its rendered footprint (never a silent glyph drop), with a
    warning logged. Strict no-raster exports keep the degraded outline but log
    the fidelity warning.
    """
    import pypdfium2.raw as C

    textpage = ctx.textpage
    to_svg = ctx.to_svg

    # Skip the invisible OCR text layer if one is ever present.
    if C.FPDFTextObj_GetTextRenderMode(obj_raw) == C.FPDF_TEXTRENDERMODE_INVISIBLE:
        return ""
    font = C.FPDFTextObj_GetFont(obj_raw)
    if not font:
        return ""

    d_parts: list[str] = []
    shaped = 0
    failed = 0
    for ci in char_indices:
        u = C.FPDFText_GetUnicode(textpage, ci)
        if u in (0, 0xFFFE, 0xFFFF) or u < 0x20:
            continue  # control / non-printable: nothing to outline
        if _needs_shaping(u):
            shaped += 1
        is_space = chr(u).isspace()
        gp = C.FPDFFont_GetGlyphPath(font, u, 1.0)
        if not gp:
            if not is_space:
                failed += 1  # a visible glyph the lookup couldn't find
            continue  # space glyph etc. — advances only, no outline
        gn = C.FPDFGlyphPath_CountGlyphSegments(gp)
        if gn <= 0:
            if not is_space:
                failed += 1
            continue
        segs = _read_segments(gn, lambda i: C.FPDFGlyphPath_GetGlyphPathSegment(gp, i))

        fs = C.FPDFText_GetFontSize(textpage, ci)  # font size in points
        m = C.FS_MATRIX()
        C.FPDFText_GetMatrix(textpage, ci, ctypes.byref(m))

        # Glyph outline is em-normalised (0..1, y-up, baseline at y=0). Scale by
        # the font size, then apply the per-glyph text matrix → page points.
        def point(gx: float, gy: float, m=m, fs=fs) -> tuple[float, float]:
            tx = gx * fs
            ty = gy * fs
            return to_svg(m.a * tx + m.c * ty + m.e, m.b * tx + m.d * ty + m.f)

        d_parts.append(_segments_to_d(segs, point))

    if shaped or failed:
        # Outlining would be unfaithful (shaped forms) or lossy (dropped
        # glyphs). Raster-embed the run's rendered footprint instead.
        log.warning(
            "svg export: text run not faithfully outlineable "
            "(%d shaped-script chars, %d failed glyph lookups) — %s",
            shaped,
            failed,
            "raster-embedding its footprint" if ctx.embed_images else
            "keeping degraded outline (strict no-raster export)",
        )
        if ctx.embed_images:
            el = _raster_text_footprint(char_indices, ctx)
            if el:
                return el

    d = "".join(p for p in d_parts if p)
    if not d:
        return ""
    r, g, b, a = _obj_fill(obj_raw)
    if a <= 0:
        return ""
    # Glyph outlines use non-zero winding (the font/PDF convention).
    return f'<path fill="{_hex(r, g, b)}"{_opacity_attr("fill", a)} d="{d}"/>'


def _emit_image(obj_raw, eff: tuple, ctx: _Ctx) -> str:
    """An image object → an embedded ``<image>`` (or placeholder in strict mode).

    We embed the photo as the **rendered pixels of its box on the page**, not
    the raw image stream. PDFium can't hand us the photo's clip or ``object-fit``
    crop, but the rendered page already has both applied — so cropping the page
    raster to the photo's footprint reproduces exactly what the card shows
    (disc-clipped, cover-cropped, colour-managed) with no clip guessing. This is
    the one legitimately-raster element; everything around it stays vector, and
    text drawn over the photo is re-emitted as crisp outlines on top.
    """
    # Axis-aligned footprint of the (possibly rotated) image, in svg px.
    pts = [
        ctx.to_svg(*_apply(eff, u, v)) for u, v in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0f, y0f, x1f, y1f = min(xs), min(ys), max(xs), max(ys)

    if not ctx.embed_images:
        # Strict no-raster: draw the photo's footprint as a labelled placeholder
        # so the SVG stays valid + editable (drop your own image into the box).
        return (
            f'<rect class="mh-image-placeholder" x="{_num(x0f)}" y="{_num(y0f)}" '
            f'width="{_num(x1f - x0f)}" height="{_num(y1f - y0f)}" '
            f'fill="#e8e8ea" stroke="#b8b8be" stroke-dasharray="6 6"/>'
        )

    W, H = ctx.pil.size
    cx0, cy0 = max(0, int(x0f)), max(0, int(y0f))
    cx1, cy1 = min(W, int(round(x1f))), min(H, int(round(y1f)))
    if cx1 - cx0 < 1 or cy1 - cy0 < 1:
        return ""
    try:
        crop = ctx.pil.crop((cx0, cy0, cx1, cy1))
        buf = BytesIO()
        crop.save(buf, format="PNG", optimize=True)
    except Exception as ex:  # pragma: no cover - defensive
        log.warning("svg export: could not crop image footprint (%s)", ex)
        return ""
    href = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<image x="{cx0}" y="{cy0}" width="{cx1 - cx0}" height="{cy1 - cy0}" '
        f'preserveAspectRatio="none" href="{href}"/>'
    )


def _clip_for(obj_raw, to_svg, page_w_px: float, page_h_px: float) -> Optional[str]:
    """Return an SVG clip ``d`` for the object's clip path, or ``None``.

    Chromium emits vector clips (rounded photos, inset panels) as PDF clip
    paths in page space. A clip that covers ~the whole page is the implicit
    page box, not a real inset — we skip those so we don't wrap every element
    in a redundant full-canvas clip.
    """
    import pypdfium2.raw as C

    cp = C.FPDFPageObj_GetClipPath(obj_raw)
    if not cp:
        return None
    npaths = C.FPDFClipPath_CountPaths(cp)
    if npaths <= 0:
        return None
    box = [float("inf"), float("inf"), float("-inf"), float("-inf")]

    def point(x: float, y: float) -> tuple[float, float]:
        sx, sy = to_svg(x, y)
        box[0] = min(box[0], sx)
        box[1] = min(box[1], sy)
        box[2] = max(box[2], sx)
        box[3] = max(box[3], sy)
        return sx, sy

    d_parts: list[str] = []
    for pi in range(npaths):
        nseg = C.FPDFClipPath_CountPathSegments(cp, pi)
        if nseg <= 0:
            continue
        segs = _read_segments(nseg, lambda i, pi=pi: C.FPDFClipPath_GetPathSegment(cp, pi, i))
        d_parts.append(_segments_to_d(segs, point))
    d = "".join(p for p in d_parts if p)
    if not d:
        return None
    area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    if area >= 0.99 * page_w_px * page_h_px:
        return None
    return d


# ---------------------------------------------------------------------------
# Recursive paint-order walk (recurses form XObjects with composed transforms)
# ---------------------------------------------------------------------------


def _flatten(
    count: int, get_obj: Callable[[int], object], ctm: tuple
) -> list[tuple[int, object, tuple]]:
    """Depth-first paint-order list of ``(type, raw, effective_matrix)``.

    Form XObjects are recursed with their transform folded into the children's
    matrices, so the result is the true flat paint order with absolute(-ish)
    transforms ready for emission.
    """
    import pypdfium2.raw as C

    flat: list[tuple[int, object, tuple]] = []
    for i in range(count):
        raw = get_obj(i)
        if not raw:
            continue
        otype = C.FPDFPageObj_GetType(raw)
        if otype == C.FPDF_PAGEOBJ_FORM:
            child_ctm = _matmul(ctm, _matrix(raw))
            flat.extend(
                _flatten(
                    C.FPDFFormObj_CountObjects(raw),
                    lambda j, raw=raw: C.FPDFFormObj_GetObject(raw, j),
                    child_ctm,
                )
            )
        else:
            flat.append((otype, raw, _matmul(ctm, _matrix(raw))))
    return flat


def _walk(count: int, get_obj: Callable[[int], object], ctx: _Ctx, defs: list[str]) -> list[str]:
    import pypdfium2.raw as C

    flat = _flatten(count, get_obj, _IDENTITY)
    # Index of the last text/photo: a full-bleed fill painted after it (with
    # nothing on top) is a translucent top overlay, not a ground.
    last_content = -1
    for idx, (otype, _raw, _eff) in enumerate(flat):
        if otype in (C.FPDF_PAGEOBJ_TEXT, C.FPDF_PAGEOBJ_IMAGE):
            last_content = idx

    out: list[str] = []
    for idx, (otype, raw, eff) in enumerate(flat):
        if otype == C.FPDF_PAGEOBJ_TEXT:
            key = ctypes.cast(raw, ctypes.c_void_p).value
            el = _emit_text_object(raw, ctx.obj_chars.get(key, []), ctx)
            if el:
                ctx.content_drawn = True
        elif otype == C.FPDF_PAGEOBJ_PATH:
            el = _emit_path(raw, eff, ctx, is_top_overlay=idx > last_content)
        elif otype == C.FPDF_PAGEOBJ_IMAGE:
            el = _emit_image(raw, eff, ctx)
            if el:
                ctx.content_drawn = True
                pts = [
                    ctx.to_svg(*_apply(eff, u, v))
                    for u, v in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
                ]
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                ctx.image_boxes.append((min(xs), min(ys), max(xs), max(ys)))
        else:
            el = ""
        if not el:
            continue
        if ctx.clip:
            clip_d = _clip_for(raw, ctx.to_svg, ctx.width_px, ctx.height_px)
            if clip_d:
                cid = f"mhclip{len(defs) + 1}"
                defs.append(f'<clipPath id="{cid}"><path d="{clip_d}"/></clipPath>')
                el = f'<g clip-path="url(#{cid})">{el}</g>'
        out.append(el)
    return out


# ---------------------------------------------------------------------------
# PDF (bytes) → SVG (string)
# ---------------------------------------------------------------------------


def _pdf_bytes_to_svg(
    pdf_bytes: bytes,
    size: tuple[int, int],
    *,
    embed_images: bool,
    clip: bool,
    background: Optional[str],
    title: Optional[str],
) -> str:
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as C
    except Exception as e:  # pragma: no cover - environment-dependent
        raise SvgExportUnavailable(f"pypdfium2 not installed: {e}") from e

    width_px, height_px = size
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except Exception as e:
        raise SvgExportError(f"could not open rendered PDF: {e}") from e
    try:
        if len(doc) == 0:
            raise SvgExportError("rendered PDF has no pages")
        page = doc[0]
        page_w_pt, page_h_pt = page.get_size()
        if page_w_pt <= 0 or page_h_pt <= 0:
            raise SvgExportError("rendered PDF page has no size")
        # Map PDF points onto the requested px canvas exactly (absorbs the ~0.1pt
        # rounding Chromium introduces vs. the ideal px·0.75).
        sx = width_px / page_w_pt
        sy = height_px / page_h_pt

        def to_svg(page_x: float, page_y: float) -> tuple[float, float]:
            # PDF origin bottom-left, y-up → SVG origin top-left, y-down.
            return page_x * sx, (page_h_pt - page_y) * sy

        # One PDFium raster of the page — the ground truth for non-solid fills.
        pil = page.render(scale=sx).to_pil().convert("RGB")

        textpage = C.FPDFText_LoadPage(page)
        try:
            # Map every glyph back to the text object that owns it (paint order
            # comes from the object walk; glyph matrices from the text page).
            obj_chars: dict[int, list[int]] = {}
            for ci in range(C.FPDFText_CountChars(textpage)):
                to = C.FPDFText_GetTextObject(textpage, ci)
                key = ctypes.cast(to, ctypes.c_void_p).value
                if key is not None:
                    obj_chars.setdefault(key, []).append(ci)

            ctx = _Ctx(
                to_svg=to_svg,
                pil=pil,
                textpage=textpage,
                obj_chars=obj_chars,
                width_px=width_px,
                height_px=height_px,
                embed_images=embed_images,
                clip=clip,
            )
            defs: list[str] = []
            body = _walk(
                C.FPDFPage_CountObjects(page),
                lambda i: C.FPDFPage_GetObject(page, i),
                ctx,
                defs,
            )
        finally:
            C.FPDFText_ClosePage(textpage)
    finally:
        doc.close()

    header = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}">'
    )
    meta = f"<title>{_xml_escape(title)}</title>" if title else ""
    defs_block = f"<defs>{''.join(defs)}</defs>" if defs else ""
    bg = (
        f'<rect x="0" y="0" width="{width_px}" height="{height_px}" fill="{background}"/>'
        if background
        else ""
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{header}{meta}{defs_block}{bg}{"".join(body)}</svg>\n'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def html_to_svg(
    html: str,
    size: tuple[int, int],
    *,
    embed_images: bool = True,
    clip: bool = True,
    background: Optional[str] = None,
    title: Optional[str] = None,
    allow_net: bool = False,
) -> str:
    """Render ``html`` at ``size`` (px) → an editable, outlined-font SVG string.

    ``embed_images`` keeps real photos as embedded ``<image>`` (the only raster);
    set it ``False`` for a strictly raster-free export where photos become
    labelled placeholder rects. ``clip`` honours Chromium's vector clips (rounded
    photos, inset panels). ``background`` paints an opaque backdrop rect (e.g.
    ``"#ffffff"``) under the card — leave ``None`` to keep the card's own
    full-bleed background and transparency elsewhere.
    """
    pdf_bytes = _render_html_to_pdf_bytes(html, size, allow_net=allow_net)
    return _pdf_bytes_to_svg(
        pdf_bytes,
        size,
        embed_images=embed_images,
        clip=clip,
        background=background,
        title=title,
    )


def render_html_to_svg(
    html: str,
    output_path: str | Path,
    size: tuple[int, int],
    *,
    embed_images: bool = True,
    clip: bool = True,
    background: Optional[str] = None,
    title: Optional[str] = None,
    allow_net: bool = False,
) -> Path:
    """Write the SVG for ``html`` to ``output_path`` and return it.

    The vector sibling of ``render.render_html_to_png`` — same inputs, an
    ``.svg`` instead of a ``.png``.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    svg = html_to_svg(
        html,
        size,
        embed_images=embed_images,
        clip=clip,
        background=background,
        title=title,
        allow_net=allow_net,
    )
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def svg_sidecar_path(image_path: str | Path) -> Path:
    """The ``<stem>.svg`` path that sits beside a rendered ``<stem>.png``."""
    return Path(image_path).with_suffix(".svg")


# The sidecar's freshness marker: an XML comment stamped after the declaration
# carrying a content hash of everything that shapes the output. When the
# on-disk SVG already carries the same key, the (expensive) cold-Chromium
# print-to-PDF + PDFium pass is skipped — a PNG cache hit stays cheap.
_SIDECAR_KEY_MARK = "mh:svg-key="


def _sidecar_key(
    html: str,
    size: tuple[int, int],
    *,
    embed_images: bool,
    clip: bool,
    background: Optional[str],
    title: Optional[str],
) -> str:
    """Content key for a sidecar: the exact final HTML + every output-shaping input."""
    h = hashlib.sha256()
    h.update(
        repr(
            (int(size[0]), int(size[1]), bool(embed_images), bool(clip), background, title)
        ).encode("utf-8")
    )
    h.update(html.encode("utf-8"))
    return h.hexdigest()


def _sidecar_is_fresh(path: Path, key: str) -> bool:
    """True when ``path`` exists and its head carries this exact content key."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(512)
    except OSError:
        return False
    return f"{_SIDECAR_KEY_MARK}{key}" in head


def export_svg_alongside(
    image_path: str | Path,
    html: str,
    size: tuple[int, int],
    *,
    embed_images: bool = True,
    clip: bool = True,
    background: Optional[str] = None,
    title: Optional[str] = None,
    allow_net: bool = False,
) -> Path:
    """Write ``<stem>.svg`` next to a rendered PNG (the "alongside each PNG" path).

    Keyed on the exact final HTML + size (+ export options): when the existing
    ``<stem>.svg`` already carries the same key it is fresh and returned as-is,
    skipping the Chromium + PDFium pass entirely (the common case on a PNG
    cache hit). Any input change produces a new key and a full re-export.
    """
    out = svg_sidecar_path(image_path)
    key = _sidecar_key(
        html, size, embed_images=embed_images, clip=clip, background=background, title=title
    )
    if _sidecar_is_fresh(out, key):
        return out
    svg = html_to_svg(
        html,
        size,
        embed_images=embed_images,
        clip=clip,
        background=background,
        title=title,
        allow_net=allow_net,
    )
    # Stamp the key just after the XML declaration (still a valid SVG document).
    decl, sep, rest = svg.partition("\n")
    svg = f"{decl}{sep}<!-- {_SIDECAR_KEY_MARK}{key} -->{rest}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return out


__all__ = [
    "SvgExportError",
    "SvgExportUnavailable",
    "html_to_svg",
    "render_html_to_svg",
    "svg_sidecar_path",
    "export_svg_alongside",
]
