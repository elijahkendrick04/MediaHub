"""Seed-colour extraction for the Adaptive Theming Engine.

Three branches, in order of preference:

  1. Direct hex     — caller passed ``#RRGGBB`` → return it as-is.
  2. SVG fast-path  — parse fill / stop-color / presentation attributes
                      via lxml, weight by element area, filter near-grey
                      via HCT chroma, feed survivors into Score.score().
  3. Raster fallback — rasterise to 256×256 via Pillow, drop transparent
                      pixels, run QuantizeCelebi → Score → top result.

The "Score" step (from materialyoucolor) is the algorithm Android 12
Monet uses to pick "the best theme colour from a wallpaper" — it
buckets by hue, filters near-grey (chroma < 5), and weights 70%
population × 30% chroma. The exact same logic that the Material Color
Utilities library ships, exposed for our brand-kit pipeline.

Returns a ``SeedResult`` carrying not just the chosen hex but every
candidate the engine considered, with its HCT and score — the
explainability artefact for the "Why does my theme look like this?"
panel.

References:
  - QuantizeCelebi: M. Emre Celebi (2011), "Improving the Performance
    of K-Means for Color Quantization" — arXiv:1101.0395.
  - Score: materialyoucolor.score.score (Apache-2.0, Google) —
    github.com/material-foundation/material-color-utilities/tree/main/
    typescript/score
  - HCT: facelessuser.github.io/coloraide/colors/hct/ — Hue + Chroma
    (CAM16) + Tone (L*).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

from materialyoucolor.hct import Hct
from materialyoucolor.quantize import QuantizeCelebi
from materialyoucolor.score.score import Score, ScoreOptions


__all__ = ["extract_seed", "SeedResult", "SeedCandidate"]


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_HEX3_RE = re.compile(r"^#[0-9A-Fa-f]{3}$")
_FALLBACK_HEX = "#0E2A47"  # matches BrandKit.generic_default() primary


@dataclass
class SeedCandidate:
    hex: str
    hct: tuple[float, float, float]   # (hue, chroma, tone)
    score: float


@dataclass
class SeedResult:
    hex: str
    source_kind: str    # "hex" | "svg" | "raster" | "fallback"
    candidates: list[SeedCandidate] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Hex parsing helpers
# ---------------------------------------------------------------------------


def _normalise_hex(s: str) -> Optional[str]:
    """Return a canonical ``#RRGGBB`` string or None if not parseable."""
    s = s.strip()
    if _HEX_RE.match(s):
        return s.upper()
    if _HEX3_RE.match(s):
        # #abc → #aabbcc
        return ("#" + "".join(ch + ch for ch in s[1:])).upper()
    return None


def _hex_to_argb(hex_str: str) -> int:
    return 0xFF000000 | int(hex_str[1:7], 16)


def _argb_to_hex(argb: int) -> str:
    return f"#{argb & 0xFFFFFF:06X}"


def _hct_of(argb: int) -> tuple[float, float, float]:
    h = Hct.from_int(argb)
    return (h.hue, h.chroma, h.tone)


def _is_brandable(hct: tuple[float, float, float]) -> bool:
    """Mirrors the Score module's filter: low chroma or extreme tone is
    not a brand colour."""
    _, c, t = hct
    return c >= 5.0 and 8.0 <= t <= 95.0


# ---------------------------------------------------------------------------
# Branch 1 — direct hex
# ---------------------------------------------------------------------------


def _try_direct_hex(source: object) -> Optional[SeedResult]:
    if not isinstance(source, str):
        return None
    norm = _normalise_hex(source)
    if norm is None:
        return None
    hct = _hct_of(_hex_to_argb(norm))
    cand = SeedCandidate(hex=norm, hct=hct, score=1.0)
    return SeedResult(
        hex=norm,
        source_kind="hex",
        candidates=[cand],
        trace=[f"direct-hex: accepted {norm} (H={hct[0]:.0f} C={hct[1]:.1f} T={hct[2]:.0f})"],
    )


# ---------------------------------------------------------------------------
# Branch 2 — SVG fast-path
# ---------------------------------------------------------------------------


_SVG_COLOR_ATTRS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color")


def _looks_like_svg(source: object) -> bool:
    if isinstance(source, str):
        return "<svg" in source[:1000].lower()
    if isinstance(source, (bytes, bytearray)):
        return b"<svg" in bytes(source)[:1000].lower()
    return False


def _has_unparseable_features(svg_text: str) -> bool:
    """SVG features that defeat the fast-path: gradients with url()
    references, embedded raster images, filters / masks / patterns.
    When present, fall through to the raster branch so the rasterised
    pixels capture the visual result."""
    lc = svg_text.lower()
    return any(needle in lc for needle in (
        "<lineargradient", "<radialgradient", "<image",
        "filter:url(", "mask:url(", "<pattern",
    ))


def _harvest_svg_colors(svg_text: str) -> list[tuple[str, float]]:
    """Return a list of (hex, weight) pairs from SVG fill / stop-color
    / style attributes. Weight is the element count — a crude but
    cheap proxy for area when bounding-box parsing would be overkill."""
    out: list[tuple[str, float]] = []
    try:
        # defusedxml falls back to lxml.etree internally for parse()
        from lxml import etree  # type: ignore
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(svg_text.encode("utf-8"), parser=parser)
    except Exception:
        return out

    for el in root.iter():
        # Direct color attributes.
        for attr in _SVG_COLOR_ATTRS:
            val = el.get(attr)
            if val:
                norm = _normalise_hex(val)
                if norm:
                    out.append((norm, 1.0))
        # Inline `style="fill:#aaa;…"`.
        style = el.get("style") or ""
        for m in re.finditer(r"(fill|stroke|stop-color):\s*(#[0-9A-Fa-f]{3,6})", style):
            norm = _normalise_hex(m.group(2))
            if norm:
                out.append((norm, 1.0))
    return out


def _try_svg(source: object) -> Optional[SeedResult]:
    if not _looks_like_svg(source):
        return None
    text = source if isinstance(source, str) else source.decode("utf-8", errors="ignore")

    trace: list[str] = []
    if _has_unparseable_features(text):
        trace.append("svg: gradients/images/filters detected → defer to raster branch")
        return None  # let raster branch handle it

    pairs = _harvest_svg_colors(text)
    trace.append(f"svg: harvested {len(pairs)} colour attribute(s)")
    if not pairs:
        return None

    # Filter near-grey / extreme tones, then build a weighted list of
    # ARGB ints for the Score module.
    argbs: list[int] = []
    counts: dict[int, float] = {}
    for hex_str, weight in pairs:
        argb = _hex_to_argb(hex_str)
        if not _is_brandable(_hct_of(argb)):
            continue
        counts[argb] = counts.get(argb, 0.0) + weight
        argbs.append(argb)

    if not counts:
        trace.append("svg: every harvested colour was near-grey/extreme → defer to raster")
        return None

    # Pass a population dict to Score.score (this is how MCU's Score
    # consumes quantizer output).
    try:
        ranked_argbs = Score.score(counts, ScoreOptions(desired=4, filter=True))
    except Exception as e:
        trace.append(f"svg: Score.score failed ({e}); returning highest-weighted candidate")
        ranked_argbs = [max(counts, key=counts.get)]

    candidates: list[SeedCandidate] = []
    for argb in ranked_argbs:
        candidates.append(SeedCandidate(
            hex=_argb_to_hex(argb),
            hct=_hct_of(argb),
            score=counts.get(argb, 1.0),
        ))

    chosen = candidates[0].hex
    trace.append(f"svg: chose {chosen} from {len(candidates)} candidate(s)")

    return SeedResult(
        hex=chosen,
        source_kind="svg",
        candidates=candidates,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# Branch 3 — raster fallback
# ---------------------------------------------------------------------------


def _try_raster(source: object) -> Optional[SeedResult]:
    """Rasterise the source (SVG or PNG/JPEG bytes) to 256×256, drop
    transparent pixels, quantize with Celebi, score with MCU's Score."""
    if isinstance(source, str):
        if _looks_like_svg(source):
            payload = source.encode("utf-8")
            is_svg = True
        else:
            return None
    elif isinstance(source, (bytes, bytearray)):
        payload = bytes(source)
        is_svg = _looks_like_svg(payload)
    else:
        return None

    trace: list[str] = []
    pixels: list[list[int]] = []

    if is_svg:
        try:
            import cairosvg  # type: ignore
            png_bytes = cairosvg.svg2png(bytestring=payload, output_width=256, output_height=256)
            payload = png_bytes
            trace.append("raster: rasterised SVG via cairosvg to 256×256")
        except ImportError:
            trace.append("raster: cairosvg unavailable; cannot rasterise SVG")
            return None
        except Exception as e:
            trace.append(f"raster: SVG rasterisation failed ({e})")
            return None

    try:
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(payload)).convert("RGBA")
        img.thumbnail((256, 256))
        for x in range(img.width):
            for y in range(img.height):
                r, g, b, a = img.getpixel((x, y))
                if a < 16:
                    continue  # transparent → not brand material
                pixels.append([r, g, b])
    except Exception as e:
        trace.append(f"raster: PIL decode failed ({e})")
        return None

    if not pixels:
        trace.append("raster: every pixel was transparent")
        return None

    trace.append(f"raster: {len(pixels)} non-transparent pixels at ≤256×256")
    try:
        result = QuantizeCelebi(pixels, 128)
        # result is {argb: population}
    except Exception as e:
        trace.append(f"raster: QuantizeCelebi failed ({e})")
        return None

    if not result:
        trace.append("raster: quantizer returned no clusters")
        return None

    try:
        ranked_argbs = Score.score(result, ScoreOptions(desired=4, filter=True))
    except Exception as e:
        trace.append(f"raster: Score.score failed ({e}); using top-population cluster")
        ranked_argbs = [max(result, key=result.get)]

    candidates: list[SeedCandidate] = []
    for argb in ranked_argbs:
        candidates.append(SeedCandidate(
            hex=_argb_to_hex(argb),
            hct=_hct_of(argb),
            score=float(result.get(argb, 0.0)),
        ))

    chosen = candidates[0].hex
    trace.append(f"raster: chose {chosen} from {len(candidates)} candidate(s)")

    return SeedResult(
        hex=chosen,
        source_kind="raster",
        candidates=candidates,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_seed(source: str | bytes, *, fallback_hex: str = _FALLBACK_HEX) -> SeedResult:
    """Return the brand seed from a hex string, SVG markup, or raster
    bytes.

    Never raises; on any failure path the caller gets the
    ``fallback_hex`` (default matches ``BrandKit.generic_default()``).
    """
    trace: list[str] = []

    # Branch 1 — direct hex
    r = _try_direct_hex(source)
    if r is not None:
        return r
    trace.append("not a hex string")

    # Branch 2 — SVG fast-path
    r = _try_svg(source)
    if r is not None:
        return r
    trace.append("svg fast-path did not produce a seed")

    # Branch 3 — raster fallback
    r = _try_raster(source)
    if r is not None:
        return r
    trace.append("raster fallback did not produce a seed")

    # Fallback
    norm = _normalise_hex(fallback_hex) or _FALLBACK_HEX
    hct = _hct_of(_hex_to_argb(norm))
    return SeedResult(
        hex=norm,
        source_kind="fallback",
        candidates=[SeedCandidate(hex=norm, hct=hct, score=0.0)],
        trace=trace + [f"fallback: returning generic default {norm}"],
    )
