"""mediahub/interop/asset_bundle.py — export a brand kit as a portable ZIP.

A first-party "take your brand elsewhere" bundle: the kit's palette in three
design-tool formats, a machine-readable ``brand.json``, and a plain-English
README. Mirrors the pack-export pattern (a ZIP + manifest), never a dependency on
another suite.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Optional

from . import palette_export


def build_brand_bundle(
    kit_name: str,
    colours,
    *,
    font_pairing: str = "",
    role_names: Optional[list[str]] = None,
    org_name: str = "",
) -> bytes:
    """Build a brand-kit ZIP and return its bytes."""
    cols = [c for c in (colours or []) if c]
    safe_name = (kit_name or "brand").strip() or "brand"

    brand_json = {
        "name": safe_name,
        "org": org_name,
        "colours": cols,
        "roles": dict(zip(role_names, cols)) if role_names else {},
        "font_pairing": font_pairing or None,
        "generated_by": "MediaHub",
    }
    readme = (
        f"{safe_name} — brand bundle\n"
        f"{'=' * (len(safe_name) + 16)}\n\n"
        "This bundle holds your MediaHub brand colours in formats other tools read:\n\n"
        "  palette.ase   Adobe Swatch Exchange (Photoshop, Illustrator, InDesign)\n"
        "  palette.gpl   GIMP / Inkscape palette\n"
        "  palette.json  generic JSON (hex + RGB)\n"
        "  brand.json    the full kit (colours, roles, fonts) as machine-readable JSON\n\n"
        f"Colours ({len(cols)}): " + ", ".join(cols) + "\n\n"
        "Exported by MediaHub. Re-export any time from Organisation -> API & webhooks\n"
        "or the platform API.\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("brand.json", json.dumps(brand_json, indent=2))
        z.writestr("README.txt", readme)
        if cols:
            z.writestr("palette.ase", palette_export.to_ase(cols, names=role_names))
            z.writestr("palette.gpl", palette_export.to_gpl(cols, palette_name=safe_name, names=role_names))
            z.writestr("palette.json", palette_export.to_json(cols, palette_name=safe_name, names=role_names))
    return buf.getvalue()


__all__ = ["build_brand_bundle"]
