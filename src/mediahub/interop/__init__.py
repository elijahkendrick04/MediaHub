"""mediahub.interop — first-party file interop (roadmap 1.21).

Importers and exporters that let a club move work in and out of MediaHub without
coupling to another design suite:

- ``palette_export`` — export brand colours to ``.ase`` / ``.gpl`` / JSON
  (the reverse of ``brand.palette_file``'s import)
- ``asset_bundle``   — export a brand kit as a portable ZIP (palettes + brand.json)
- ``svg_import``     — import an SVG as a **sanitised** media asset (XSS/XXE-safe)
- ``psd_import``     — optional, dependency-gated PSD import (flattened raster);
  honest-errors without the ``psd`` extra

Layered SVG/PSD round-trip is a separate later goal (roadmap 1.25); this is the
import/convert/export half of the platform surface.
"""

from __future__ import annotations

from . import asset_bundle, palette_export, psd_import, svg_import

__all__ = ["palette_export", "asset_bundle", "svg_import", "psd_import"]
