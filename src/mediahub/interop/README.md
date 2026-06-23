# `interop/` — first-party file interop (roadmap 1.21)

Move work in and out of MediaHub without coupling to another design suite. Every
importer/exporter here is MediaHub's own code.

| File | Does |
|---|---|
| `palette_export.py` | Export brand colours to `.ase` (Adobe), `.gpl` (GIMP/Inkscape), or JSON — the reverse of `brand.palette_file`'s import; round-trips with it |
| `asset_bundle.py` | Export a brand kit as a portable ZIP (the three palette formats + `brand.json` + README) |
| `svg_import.py` | Import an SVG as a **sanitised** media asset — strips `<script>`, `on*` handlers, `javascript:`/external `href`s, `<foreignObject>`, and disables XML entities/network (XXE-safe). Anything it can't safely parse is rejected, never stored |
| `psd_import.py` | Optional, dependency-gated PSD import (flattened raster → media library). Honest-errors without the `psd` extra — never a stub |

## Why sanitise SVG so hard

A stored SVG that's ever served inline is a stored-XSS / data-exfil vector. So
import is sanitise-first: parse with entities + network off, strip every active
vector, then store the cleaned vector. It's a conservative, documented sanitiser,
not a full CSP engine — see the module docstring for the exact rules.

## Where it's exposed

- Platform API ([`api_public/`](../api_public/README.md)): `GET
  /brand-kits/{id}/palette`, `GET /brand-kits/{id}/bundle`, `POST
  /media/import-svg`, `POST /media/import-psd`.
- The read-only **embed** of approved content is the public wall + the `/oembed`
  endpoint (the unguessable wall token is the capability).

Layered SVG/PSD *round-trip* is a separate later goal (roadmap 1.25); this is the
import / convert / export half. Human docs: [`docs/INTEROP.md`](../../../docs/INTEROP.md).
