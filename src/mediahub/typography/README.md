# typography — club custom-font upload pipeline

This folder lets a club bring **its own brand typeface** into MediaHub safely.
A committee member uploads a font file; MediaHub checks it's a real, safe font,
shrinks it, and hosts it itself — so the club's cards and reels can use the
club's actual font instead of one of the built-in ones.

The whole thing lives in one file: [`font_intake.py`](font_intake.py).
It is roadmap item **G1.10**.

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

## Where it plugs in

This module is a self-contained **seam** (roadmap tag 🟢 ISOLATED). It does not
edit the web app or the renderer on its own — a later task adds the upload screen
and tells the renderer to use a stored font's `role` (display / body / numeric …)
in place of a built-in family. Everything that task needs is already here:
the stored `FontRecord` and `font_face_css()`.

## Tests

`tests/test_font_intake.py` covers the safety rejections (bad magic, truncated
headers, oversize, declared decompression bombs, restricted-embedding fonts),
the subsetting (glyph reduction, size shrink, deterministic output), storage
round-trips, and the CSS emission (including that an arbitrary human family name
can never inject into the stylesheet). The subset/`.woff2` tests skip cleanly
where `fonttools` isn't installed.
