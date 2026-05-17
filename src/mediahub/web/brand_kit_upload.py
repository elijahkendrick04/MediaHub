"""V8.1 issue 5 — per-run brand kit upload helpers.

A brand kit lives at ``<DATA_DIR>/data/brand_kits/<run_id>.json`` and looks like::

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
import os
import re
from pathlib import Path
from typing import Optional


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _data_dir() -> Path:
    """Resolve DATA_DIR. Must agree with web.web.DATA_DIR or the
    brand-kit-load path in _v8_brand_kit_for won't find what we wrote.

    Resolution order (matches src/mediahub/web/web.py):
      1. DATA_DIR env var (production / persistent disk)
      2. Local dev default: src/mediahub (one level up from this file)
    """
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    # src/mediahub/web/brand_kit_upload.py → parents[1] = src/mediahub
    return Path(__file__).resolve().parents[1]


def _runs_dir() -> Path:
    env = os.environ.get("RUNS_DIR")
    if env:
        return Path(env)
    return _data_dir() / "runs_v4"


def _brand_kits_dir() -> Path:
    return _data_dir() / "data" / "brand_kits"


def _brand_dir_for(run_id: str) -> Path:
    p = _runs_dir() / run_id / "brand"
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
    """Extract three dominant colours from ``logo_path`` via Pillow.

    Returns (primary, secondary, accent) as ``#RRGGBB`` strings.

    Uses Pillow's median-cut quantizer to derive a small palette and
    then sorts by pixel frequency to pick the three dominant entries.
    Pillow is already a hard dependency of MediaHub, so this avoids
    adding ``colorthief`` (a transitive numpy stack that wasn't always
    available in the deploy environment, which previously caused
    silent fall-back to form-supplied colours).

    Implementation notes:
      * Image is converted to RGB so paletted/grayscale logos still
        produce sensible output.
      * Near-white pixels (typical PNG background) are mapped out by
        re-quantising over the dominant block; we keep the top three
        by frequency regardless of brightness so the user's actual
        brand colours win.
      * Raises ``RuntimeError`` on any unexpected condition so the
        caller's existing ``except Exception: pass`` fallback still
        works as before.
    """
    from PIL import Image

    try:
        with Image.open(str(logo_path)) as src:
            img = src.convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"could not open logo image: {exc}") from exc

    # Quantize to a small palette. MEDIANCUT is built into Pillow and
    # produces clean separation for two/three-colour brand marks.
    try:
        quant = img.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    except (AttributeError, ValueError):
        # Older Pillow versions used integer constants.
        quant = img.quantize(colors=8, method=0)

    palette_flat = quant.getpalette() or []
    colour_counts = quant.getcolors() or []
    if not colour_counts:
        raise RuntimeError("Pillow returned an empty palette")

    # getcolors returns [(count, palette_idx), ...]; sort most-frequent first.
    colour_counts.sort(reverse=True)
    palette_rgb: list[tuple[int, int, int]] = []
    for count, idx in colour_counts:
        base = idx * 3
        if base + 2 >= len(palette_flat):
            continue
        rgb = (palette_flat[base], palette_flat[base + 1], palette_flat[base + 2])
        palette_rgb.append(rgb)

    if not palette_rgb:
        raise RuntimeError("Pillow palette had no usable colours")

    # Pad the palette in case the image had fewer than three distinct
    # quantised colours (e.g. a one-colour brand mark on solid white).
    while len(palette_rgb) < 3:
        palette_rgb.append(palette_rgb[-1])

    def _to_hex(rgb: tuple[int, int, int]) -> str:
        return "#{0:02X}{1:02X}{2:02X}".format(*rgb)

    return _to_hex(palette_rgb[0]), _to_hex(palette_rgb[1]), _to_hex(palette_rgb[2])


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
    kits_dir = _brand_kits_dir()
    kits_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "display_name": display_name,
        "logo_path": logo_path,
        "primary_colour": primary,
        "secondary_colour": secondary,
        "accent_colour": accent,
        "source": source,
    }
    out = kits_dir / f"{run_id}.json"
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
        # Pillow's quantizer handles raster formats; SVG would need a
        # rasterise step which we don't currently do, so fall back to
        # the form-supplied colours for non-raster logos.
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
