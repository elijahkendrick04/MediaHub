# typography — MediaHub's first-party type system

This folder is MediaHub's **typography system** (roadmap **1.9**). It has two
halves:

* **The curated font catalogue** ([`catalog.py`](catalog.py) +
  [`catalog.json`](catalog.json)) — the single source of truth for the
  first-party typefaces MediaHub ships across its three surfaces (the web UI, the
  still-graphic renderer, the reel). Each face is tagged with a class
  (display / sans / serif / mono), mood words, its variable axes, the writing
  scripts it covers, its OFL provenance, and which other faces it pairs well
  with. You can browse it by mood / class / surface, and an org's *uploaded*
  fonts (below) are merged into its own view via `org_catalog(profile_id)`.
* **The club custom-font upload pipeline** ([`font_intake.py`](font_intake.py),
  roadmap **G1.10**) — lets a club bring **its own brand typeface** in safely:
  MediaHub checks it's a real, safe font, shrinks it, and hosts it itself, so the
  club's cards and reels can use the club's actual font.

It also carries the **deterministic rich-text formatting model**
([`formatting.py`](formatting.py)) — the character/paragraph controls (colour,
alignment, weight, lists, links, decimal sizes, line height, gradient fills) and
editor utilities (uppercase, find & replace, copy-style, auto-link, an honest
spellcheck seam) as pure, XSS-safe functions. The browsable surface for all of
this is **Settings → Typography & fonts** in the web app.

Every face — built-in or uploaded — is self-hosted `.woff2`. **Never the Google
Fonts CDN** (a reliability + EU/UK GDPR rule the whole product follows).

## What happens when a font is uploaded (in plain words)

1. **Safety check first.** Before anything heavy looks at the file, a small
   pure-Python scan reads just the font's "table of contents" and checks the
   numbers add up: it's actually a font (right magic bytes), it isn't enormous,
   none of its internal pointers point outside the file, and — for compressed
   `.woff`/`.woff2` fonts — it doesn't *claim* to unzip into something gigantic
   (a "font bomb"). A file that fails any of these is rejected immediately.
   We also read the font's licence bits and refuse a font whose foundry marked
   it "do not embed".
2. **Slim it down (subsetting).** A real font carries thousands of glyphs for
   dozens of languages. MediaHub only needs the Latin letters, numbers and
   punctuation it actually renders, so it throws the rest away. A 200 KB upload
   becomes a few KB. This is the same character set the built-in fonts use, so
   nothing about the layout maths changes.
3. **Host it ourselves.** The slimmed font is saved as a `.woff2` under
   `DATA_DIR/custom_fonts/<club>/`, and a normal `@font-face` CSS rule is
   produced pointing at *our* copy. **Never the Google Fonts CDN** — same rule
   as every other font in MediaHub (it's a reliability + EU/UK GDPR thing).

## How to use it

```python
from mediahub.typography import intake_font, font_face_css, list_fonts

rec = intake_font(uploaded_bytes, profile_id="city-of-manchester", role="display")
print(rec.css_family)            # 'club-city-of-manchester-brand-sans'
print(rec.woff2_size, "bytes")   # the slimmed, self-hosted file

css = font_face_css(list_fonts("city-of-manchester"))  # all of a club's fonts
```

* `validate_font_bytes(data)` — just the safety check; returns the facts it read.
* `intake_font(...)` — the full pipeline (validate → subset → store).
* `font_face_css(records, file_uri=True)` — emit `@font-face` with absolute
  `file://` URLs, the form the Playwright renderer inlines.

## Honest errors, never fakes

Subsetting and `.woff2` packing need the `fonttools` + `brotli` libraries (they
ship in MediaHub's deploy image and are pinned in `requirements.txt`). If they're
ever missing, the pipeline raises `FontToolingUnavailable` rather than inventing
a result — the same "a clear error beats a fake" rule the rest of MediaHub
follows. The *safety* checks need no third-party library at all, so a dangerous
upload is rejected even in a stripped-down environment.

## Using the catalogue

```python
from mediahub.typography import catalog as cat

cat.load_catalog()                      # all built-in faces (validated, cached)
cat.search(klass="display", mood="loud")  # filter by class / mood / surface / role
cat.get("anton")                        # one face by slug
cat.org_catalog("city-of-manchester")   # built-ins + this club's uploaded fonts
cat.verify_assets()                     # [] when catalogue ⇄ disk are in lock-step
```

The catalogue is plain data: no network, no AI. Adding a face is a `catalog.json`
edit plus a run of the matching fetch script
(`scripts/fetch_fonts.py` / `fetch_renderer_fonts.py`) — `tests/test_font_catalog.py`
then proves the new row has its `.woff2` and `@font-face` on every surface it claims.

## Where it plugs in

The catalogue feeds **AI font pairing** (`mediahub.brand.type_pairing`, which can
only propose a face that is in the catalogue) and the **typography web surface**
(browse + upload + preview). The renderer uses a stored upload's `role`
(display / body / numeric …) and `font_face_css(..., file_uri=True)` in place of a
built-in family for that org.

## Tests

* `tests/test_font_catalog.py` — catalogue integrity (controlled vocabularies,
  unique slugs, a valid pairing-affinity graph), the disk lock-step on every
  surface, the query API, and the per-org upload merge with tenant isolation.
* `tests/test_font_intake.py` — the upload safety rejections (bad magic, truncated
  headers, oversize, declared decompression bombs, restricted-embedding fonts),
  the subsetting (glyph reduction, size shrink, deterministic output), storage
  round-trips, and the CSS emission (including that an arbitrary human family name
  can never inject into the stylesheet). The subset/`.woff2` tests skip cleanly
  where `fonttools` isn't installed.
