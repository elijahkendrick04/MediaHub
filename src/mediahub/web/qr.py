"""web.qr — minimal, deterministic QR rendering for in-app pages.

Extracted from the removed ``mediahub.sites.qr`` (the club-microsites feature
was retired; see PR #1109) because the 2FA enrolment page still needs an
inline QR of the ``otpauth://`` provisioning URI (usability finding H-20).

The raw matrix comes from **segno** (a tiny, pure-Python, MIT-licensed
library — in-process, no external service). The brand-colour layer keeps the
scanner-safe contrast guard: dark modules take a brand colour only when it
clears WCAG ≥ 7:1 against the light background, else they fall back to black.
Only the inline-SVG path survives here — no disk cache, no PNG/PDF export,
no logo embedding. The 2FA page embeds the SVG directly so the secret never
appears on a fetchable URL.
"""

from __future__ import annotations

import io
import re
from typing import Optional

from mediahub.theming.contrast import wcag2_ratio

try:  # segno is a light dep; guard so the package still imports without it
    import segno as _segno
except ImportError:  # pragma: no cover - exercised only where the dep is absent
    _segno = None

_MIN_SCAN_CONTRAST = 7.0
_WHITE = "#FFFFFF"
_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


class QRUnavailable(RuntimeError):
    """Raised when the QR backend (segno) is not installed."""


def _require_segno():
    if _segno is None:
        raise QRUnavailable(
            "QR generation needs the 'segno' package. Install it (it is in the project dependencies)."
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
    otherwise they fall back to black. An explicit ``dark`` override is honoured
    if it also passes the bar."""
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
    qr = _require_segno().make(str(data), error="m")
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


def is_available() -> bool:
    return _segno is not None


__all__ = [
    "QRUnavailable",
    "brand_qr_colors",
    "is_available",
    "qr_svg",
]
