"""V8.1 issue 5 — per-run brand kit upload helpers.

A brand kit lives at ``data/brand_kits/<run_id>.json`` and looks like::

    {
      "display_name": "City of Manchester Aquatics",
      "logo_path": "runs_v4/<run_id>/brand/logo.png",
      "primary_colour": "#A30D2D",
      "secondary_colour": "#101820",
      "accent_colour": "#FFD86E",
      "source": "upload"
    }

The renderer/brand kit lookup at ``_v8_brand_kit_for(profile_id, run_id=...)``
in :mod:`swim_content_v4.web` reads this file when present.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_BRAND_KITS_DIR = Path("data") / "brand_kits"


def _brand_dir_for(run_id: str) -> Path:
    p = Path("runs_v4") / run_id / "brand"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ext_from_filename(name: str) -> str:
    name = (name or "").lower()
    for ext in (".png", ".jpg", ".jpeg", ".svg"):
        if name.endswith(ext):
            return ext
    return ".png"


def save_logo_bytes(run_id: str, file_bytes: bytes, filename: str) -> Path:
    """Persist the uploaded logo into ``runs_v4/<run_id>/brand/logo.<ext>``."""
    ext = _ext_from_filename(filename)
    dest = _brand_dir_for(run_id) / f"logo{ext}"
    dest.write_bytes(file_bytes)
    return dest


def _normalise_hex(value: Optional[str], fallback: str) -> str:
    """Validate and return a #RRGGBB hex string."""
    v = (value or "").strip()
    if _HEX_RE.match(v):
        return v.upper()
    # Accept short form like #abc
    if re.match(r"^#[0-9A-Fa-f]{3}$", v):
        return ("#" + "".join(ch * 2 for ch in v[1:])).upper()
    return fallback


def extract_palette_from_logo(logo_path: Path) -> tuple[str, str, str]:
    """Use ColorThief to extract three dominant colours.

    Returns (primary, secondary, accent) as #RRGGBB strings. Raises on failure.
    """
    from colorthief import ColorThief

    ct = ColorThief(str(logo_path))
    palette = ct.get_palette(color_count=4, quality=10)
    if not palette:
        raise RuntimeError("colorthief returned empty palette")

    def _to_hex(rgb: tuple[int, int, int]) -> str:
        return "#{0:02X}{1:02X}{2:02X}".format(*rgb)

    while len(palette) < 3:
        palette.append(palette[-1])
    primary = _to_hex(palette[0])
    secondary = _to_hex(palette[1])
    accent = _to_hex(palette[2])
    return primary, secondary, accent


def persist_brand_kit(
    run_id: str,
    *,
    display_name: str,
    logo_path: Optional[str],
    primary: str,
    secondary: str,
    accent: str,
    source: str = "upload",
) -> Path:
    """Persist a per-run brand kit JSON. Returns the path written."""
    _BRAND_KITS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "display_name": display_name,
        "logo_path": logo_path,
        "primary_colour": primary,
        "secondary_colour": secondary,
        "accent_colour": accent,
        "source": source,
    }
    out = _BRAND_KITS_DIR / f"{run_id}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def process_upload(
    run_id: str,
    *,
    logo_bytes: Optional[bytes],
    logo_filename: Optional[str],
    primary_form: Optional[str],
    secondary_form: Optional[str],
    accent_form: Optional[str],
    use_logo_colours: bool,
    display_name: str,
    fallback_primary: str = "#0A2540",
    fallback_secondary: str = "#101820",
    fallback_accent: str = "#FFD86E",
) -> dict:
    """Save the logo + persist a brand kit. Returns the persisted dict."""
    logo_path: Optional[Path] = None
    if logo_bytes:
        logo_path = save_logo_bytes(run_id, logo_bytes, logo_filename or "logo.png")

    primary = _normalise_hex(primary_form, fallback_primary)
    secondary = _normalise_hex(secondary_form, fallback_secondary)
    accent = _normalise_hex(accent_form, fallback_accent)

    if logo_path and use_logo_colours:
        # Only PNG/JPEG are usable by colorthief reliably; skip for SVG.
        if logo_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            try:
                primary, secondary, accent = extract_palette_from_logo(logo_path)
            except Exception:
                # Fall back to whatever the user picked / defaults.
                pass

    persist_brand_kit(
        run_id,
        display_name=display_name,
        logo_path=str(logo_path) if logo_path else None,
        primary=primary,
        secondary=secondary,
        accent=accent,
    )
    return {
        "display_name": display_name,
        "logo_path": str(logo_path) if logo_path else None,
        "primary_colour": primary,
        "secondary_colour": secondary,
        "accent_colour": accent,
        "source": "upload",
    }


__all__ = [
    "process_upload",
    "save_logo_bytes",
    "extract_palette_from_logo",
    "persist_brand_kit",
]
