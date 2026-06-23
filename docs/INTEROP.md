# File interop & embed (`1.21`)

First-party importers/exporters so a club can move work in and out of MediaHub —
and a read-only way to embed approved content on a club website. No coupling to
another design suite; the GWS exclusion holds (no Drive/Photos). Part of the
platform surface; see [`PUBLIC_API.md`](PUBLIC_API.md).

## Palette export

Pull your brand colours into other tools:

```bash
# Adobe Swatch Exchange (Photoshop/Illustrator/InDesign)
curl "$BASE/api/v1/brand-kits/$KIT_ID/palette?format=ase" -H "Authorization: Bearer $TOKEN" -o palette.ase
# GIMP / Inkscape
curl "$BASE/api/v1/brand-kits/$KIT_ID/palette?format=gpl" -H "Authorization: Bearer $TOKEN" -o palette.gpl
# generic JSON
curl "$BASE/api/v1/brand-kits/$KIT_ID/palette?format=json" -H "Authorization: Bearer $TOKEN" -o palette.json
```

`brand:read` scope. The exporters round-trip with MediaHub's palette *importer*
(`brand.palette_file`), so a palette out and back in is loss-free.

## Brand bundle

A portable ZIP of the kit — the three palette formats, a machine-readable
`brand.json`, and a README:

```bash
curl "$BASE/api/v1/brand-kits/$KIT_ID/bundle" -H "Authorization: Bearer $TOKEN" -o brand-bundle.zip
```

## SVG import (sanitised)

```bash
curl -X POST "$BASE/api/v1/media/import-svg?filename=logo.svg" \
  -H "Authorization: Bearer $TOKEN" --data-binary @logo.svg
```

`media:write` scope. The SVG is **sanitised on import** — `<script>`, `on*`
handlers, `javascript:`/external `href`s and `<foreignObject>` are stripped, and
XML entities/network are disabled (XXE-safe) — then stored as a media asset.
Unsafe or malformed SVG is rejected (`400`), never stored.

## PSD import (optional)

```bash
curl -X POST "$BASE/api/v1/media/import-psd?filename=poster.psd" \
  -H "Authorization: Bearer $TOKEN" --data-binary @poster.psd
```

`media:write` scope. Reads a `.psd` and stores its flattened composite as a media
asset. Requires the optional `psd` extra (`pip install 'mediahub[psd]'`,
MIT-licensed `psd-tools`); without it the endpoint honest-errors `503` rather
than pretending. Full layered round-trip is a later goal (roadmap 1.25).

## Embed (read-only) + oEmbed

Approved content embeds on a club website through the **public achievements
wall** — an iframe keyed by an unguessable wall token (the "signed" capability;
only `approved` cards ever show). Enable it under *Organisation → Public wall*.

For CMSes that speak oEmbed (WordPress, etc.), point them at the discovery
endpoint:

```
GET /oembed?url=https://your-mediahub.example/wall/<token>&format=json
```

It returns oEmbed `rich` JSON whose `html` is the wall's embed iframe (JSON only;
XML oEmbed returns `501`). An unknown or disabled wall returns `404`.

## Not in scope (yet)

- **Layered round-trip** (editable SVG/PSD back out) → roadmap 1.25.
- **GWS** (Drive/Photos/Gmail/Calendar) → permanently excluded; cloud-file import
  is generic remote-fetch + upload, calendars are ICS export.
- **Editable embed SDK** → deferred; the embed is read-only.
