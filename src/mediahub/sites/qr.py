"""sites.qr — brand-safe QR codes for posters → pages/forms (roadmap 1.16).

A deterministic QR generator: the raw matrix comes from **segno** (a tiny,
pure-Python, MIT-licensed library — in-process, no external service, no per-call
cost, rule 11), and the brand-colour / contrast-guard / logo-embed / multi-format
layer is MediaHub's own. The dark modules are painted in the club's brand colour
**only when they clear a scanner-safe contrast bar** against the light background
(WCAG ≥ 7:1, via :mod:`theming.contrast`); otherwise they fall back to black —
a pretty code that won't scan is worse than a plain one. Output is PNG / SVG / PDF;
PNG/PDF can carry a centred logo (with error-correction raised so the code still
reads). Exports are content-addressed (:mod:`sites.cache`).
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

from mediahub.theming.contrast import wcag2_ratio

from . import cache

try:  # segno is a light hard dep; guard so the package still imports without it
    import segno as _segno
except ImportError:  # pragma: no cover - exercised only where the dep is absent
    _segno = None

QR_FORMATS = ("png", "svg", "pdf")
_MIN_SCAN_CONTRAST = 7.0
_WHITE = "#FFFFFF"
_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


class QRUnavailable(RuntimeError):
    """Raised when the QR backend (segno) is not installed."""


def _require_segno():
    if _segno is None:
        raise QRUnavailable(
            "QR generation needs the 'segno' package. Install it (it is in requirements.txt)."
        )
    return _segno


def _norm_hex(value: str, default: str = "#000000") -> str:
    s = str(value or "").strip()
    if s and not s.startswith("#"):
        s = "#" + s
    return s.upper() if _HEX_RE.match(s) else default


def brand_qr_colors(
    role_vars: Optional[dict[str, str]] = None, *, dark: str = "", light: str = ""
) -> tuple[str, str]:
    """Resolve (dark, light) QR colours from the brand, with a contrast guard.

    The light background stays white (the safest scan target). The dark modules
    take the brand colour only if it clears ``_MIN_SCAN_CONTRAST`` against white;
    otherwise they fall back to black. An explicit ``dark`` override is honoured if
    it also passes the bar."""
    role_vars = role_vars or {}
    light_hex = _norm_hex(light or _WHITE, _WHITE)
    candidates = [
        dark,
        role_vars.get("--mh-primary", ""),
        role_vars.get("--mh-secondary", ""),
        role_vars.get("--mh-ink", ""),
    ]
    for cand in candidates:
        hexc = _norm_hex(cand, "")
        if hexc and wcag2_ratio(hexc, light_hex) >= _MIN_SCAN_CONTRAST:
            return hexc, light_hex
    return "#000000", light_hex


def _make(data: str, *, with_logo: bool):
    seg = _require_segno()
    # high error correction when a logo will occlude the centre; medium otherwise
    return seg.make(str(data), error="h" if with_logo else "m")


def qr_svg(
    data: str,
    *,
    role_vars: Optional[dict[str, str]] = None,
    dark: str = "",
    light: str = "",
    scale: int = 4,
    border: int = 4,
    label: str = "",
) -> str:
    """An inline SVG string for embedding on a page (no XML declaration)."""
    qr = _make(data, with_logo=False)
    d, lt = brand_qr_colors(role_vars, dark=dark, light=light)
    buf = io.BytesIO()
    qr.save(
        buf,
        kind="svg",
        dark=d,
        light=lt,
        scale=scale,
        border=border,
        xmldecl=False,
        svgns=True,
        title=label or None,
    )
    return buf.getvalue().decode("utf-8")


def qr_png(
    data: str,
    *,
    role_vars: Optional[dict[str, str]] = None,
    dark: str = "",
    light: str = "",
    scale: int = 8,
    border: int = 4,
    logo_path: str = "",
) -> bytes:
    """PNG bytes; with ``logo_path`` a centred logo is composited in."""
    qr = _make(data, with_logo=bool(logo_path))
    d, lt = brand_qr_colors(role_vars, dark=dark, light=light)
    buf = io.BytesIO()
    qr.save(buf, kind="png", dark=d, light=lt, scale=scale, border=border)
    png = buf.getvalue()
    if logo_path:
        png = _overlay_logo(png, logo_path)
    return png


def qr_pdf(
    data: str,
    *,
    role_vars: Optional[dict[str, str]] = None,
    dark: str = "",
    light: str = "",
    scale: int = 8,
    border: int = 4,
    logo_path: str = "",
) -> bytes:
    """Print-ready PDF bytes (the brand PNG wrapped as a single-page PDF)."""
    png = qr_png(
        data,
        role_vars=role_vars,
        dark=dark,
        light=light,
        scale=scale,
        border=border,
        logo_path=logo_path,
    )
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    out = io.BytesIO()
    img.save(out, "PDF", resolution=300.0)
    return out.getvalue()


def _overlay_logo(png: bytes, logo_path: str) -> bytes:
    """Composite a centred logo on a white pad over the QR (best-effort)."""
    try:
        from PIL import Image

        base = Image.open(io.BytesIO(png)).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        w, h = base.size
        target = int(w * 0.22)
        logo.thumbnail((target, target), Image.LANCZOS)
        pad = int(target * 0.14)
        plate = Image.new(
            "RGBA", (logo.width + pad * 2, logo.height + pad * 2), (255, 255, 255, 255)
        )
        plate.alpha_composite(logo, (pad, pad))
        pos = ((w - plate.width) // 2, (h - plate.height) // 2)
        base.alpha_composite(plate, pos)
        out = io.BytesIO()
        base.convert("RGB").save(out, "PNG")
        return out.getvalue()
    except Exception:
        return png  # a missing/unreadable logo never breaks the code


def export_qr(
    data: str,
    fmt: str = "png",
    *,
    role_vars: Optional[dict[str, str]] = None,
    dark: str = "",
    light: str = "",
    scale: int = 8,
    border: int = 4,
    logo_path: str = "",
) -> tuple[bytes, str]:
    """Render + content-cache a QR in ``fmt`` (png/svg/pdf). Returns (bytes, mime)."""
    fmt = fmt if fmt in QR_FORMATS else "png"
    d, lt = brand_qr_colors(role_vars, dark=dark, light=light)
    key = ("qr", fmt, data, d, lt, scale, border, logo_path)
    suffix = {"png": ".png", "svg": ".svg", "pdf": ".pdf"}[fmt]
    mime = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[fmt]
    cached = cache.cached_path(suffix, *key)
    if cached.exists() and cached.stat().st_size > 0:
        return cached.read_bytes(), mime
    if fmt == "svg":
        payload = qr_svg(data, dark=d, light=lt, scale=scale, border=border).encode("utf-8")
    elif fmt == "pdf":
        payload = qr_pdf(data, dark=d, light=lt, scale=scale, border=border, logo_path=logo_path)
    else:
        payload = qr_png(data, dark=d, light=lt, scale=scale, border=border, logo_path=logo_path)
    Path(cached).write_bytes(payload)
    return payload, mime


def is_available() -> bool:
    return _segno is not None


__all__ = [
    "QR_FORMATS",
    "QRUnavailable",
    "brand_qr_colors",
    "qr_svg",
    "qr_png",
    "qr_pdf",
    "export_qr",
    "is_available",
]
