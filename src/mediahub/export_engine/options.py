"""export_engine/options.py — the per-export option schema (roadmap 1.19).

A small, deterministic value object that captures the knobs Canva/Express
surface on an export — quality (10–100), output scale, transparent background,
and the screen-vs-print colour intent — clamped to safe ranges so a caller can
never push a renderer out of bounds. The engine maps these onto each adapter's
own parameters (see :mod:`export_engine.engine`); a format only reads the knobs
it declares in its registry entry (:mod:`export_engine.formats`).

Like the rest of the engine this is *maths, not judgement*: ``clamped()`` is a
pure normalisation and ``cache_token()`` is a stable short string so two equal
option sets always share a render cache entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Bounds. Quality mirrors the 10–100 slider clubs see in Canva; scale is an
# output-resolution multiplier (1.0 = the format's native size); colour_profile
# is the screen-vs-print intent the still/print renderers already understand.
QUALITY_MIN, QUALITY_MAX = 10, 100
SCALE_MIN, SCALE_MAX = 0.1, 4.0
COLOUR_PROFILES: tuple[str, ...] = ("screen", "print")
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _clamp_int(value: object, lo: int, hi: int, default: int) -> int:
    try:
        n = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clamp_float(value: object, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if n != n:  # NaN
        return default
    return max(lo, min(hi, n))


def _norm_hex(value: object, default: str = "#ffffff") -> str:
    s = str(value or "").strip()
    if not _HEX_RE.match(s):
        return default
    return s if s.startswith("#") else f"#{s}"


@dataclass(frozen=True)
class ExportOptions:
    """The knobs for one export. Construct freely; call :meth:`clamped` to
    normalise before use (the engine always does).

    - ``quality`` — 10–100, honoured by lossy encoders (JPEG/WebP/AVIF/MP3/…).
    - ``scale`` — output-resolution multiplier (0.1–4.0); 1.0 = native size.
    - ``transparent`` — keep an alpha channel where the format supports it;
      otherwise the image is flattened onto ``background``.
    - ``background`` — flatten colour when transparency is dropped (e.g. JPEG).
    - ``colour_profile`` — ``"screen"`` (sRGB, default) or ``"print"`` (the
      print/CMYK-aware PDF path).
    """

    quality: int = 90
    scale: float = 1.0
    transparent: bool = False
    background: str = "#ffffff"
    colour_profile: str = "screen"

    # -- normalisation ------------------------------------------------------
    def clamped(self) -> "ExportOptions":
        prof = str(self.colour_profile or "screen").strip().lower()
        if prof not in COLOUR_PROFILES:
            prof = "screen"
        return ExportOptions(
            quality=_clamp_int(self.quality, QUALITY_MIN, QUALITY_MAX, 90),
            scale=_clamp_float(self.scale, SCALE_MIN, SCALE_MAX, 1.0),
            transparent=bool(self.transparent),
            background=_norm_hex(self.background),
            colour_profile=prof,
        )

    # -- accessors ----------------------------------------------------------
    def quality_fraction(self) -> float:
        """Quality as a 0.1–1.0 fraction (handy for libraries that want 0–1)."""
        return self.clamped().quality / 100.0

    @property
    def is_print(self) -> bool:
        return self.clamped().colour_profile == "print"

    def scaled_size(self, size: tuple[int, int]) -> tuple[int, int]:
        """Apply ``scale`` to a ``(w, h)`` pixel size, clamped to >=1px."""
        s = self.clamped().scale
        w, h = size
        return (max(1, int(round(w * s))), max(1, int(round(h * s))))

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        c = self.clamped()
        return {
            "quality": c.quality,
            "scale": c.scale,
            "transparent": c.transparent,
            "background": c.background,
            "colour_profile": c.colour_profile,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "ExportOptions":
        d = data or {}
        return cls(
            quality=d.get("quality", 90),
            scale=d.get("scale", 1.0),
            transparent=bool(d.get("transparent", False)),
            background=d.get("background", "#ffffff"),
            colour_profile=d.get("colour_profile", "screen"),
        ).clamped()

    def cache_token(self) -> str:
        """A short, stable token for cache keys — only the knobs that bite."""
        c = self.clamped()
        return (
            f"q{c.quality}-s{c.scale:.3f}"
            f"-{'t' if c.transparent else 'o'}{c.background.lstrip('#')}"
            f"-{c.colour_profile}"
        )


__all__ = [
    "ExportOptions",
    "QUALITY_MIN",
    "QUALITY_MAX",
    "SCALE_MIN",
    "SCALE_MAX",
    "COLOUR_PROFILES",
]
