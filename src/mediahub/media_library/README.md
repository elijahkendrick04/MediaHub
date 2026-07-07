# media_library

Stores the photos and other media a user uploads, and remembers what's in each one
(who's in it, what it shows) so the right photo can be picked for a card.

## What's in here

- `models.py` / `store.py` — the `MediaAsset` record and its SQLite storage.
  `store.backfill_measurements()` is the on-demand one-shot that re-measures
  assets saved before the ingest metadata spine existed (dimensions,
  orientation, dominant colours + the quality metrics below).
- `describe.py` — AI-assisted "what's in this photo" tagging (text side).
- `tagger.py` — deterministic image measurement at ingest: EXIF-orientation
  baking (`bake_exif_orientation`), dimensions / orientation / dominant
  colours, and technical-quality metrics (Laplacian sharpness, highlight and
  shadow clipping, luma entropy, 64-bit dHash for burst dedupe) stored in
  `media_meta["quality"]`. Pure Pillow/numpy — no AI, no network.
- `selector.py` — the deterministic maths that scores which photo best fits a
  card: sharpness-aware quality axis, burst-family dedupe (dHash Hamming ≤ 6
  keeps only the sharpest frame), and the wrong-athlete guard (a photo linked
  to a different athlete is hard-demoted; unlinked photos rank below
  name-matched ones and carry "identity unverified" in their reason).
- `photo_ops.py` — the **photo editor engine**: a deterministic, non-destructive
  `EditRecipe` of bounded pixel operations (filters, adjustments, crop/rotate/
  flip/perspective, crop-to-shape, frames, blur brush, eraser, one-click
  `enhance_auto`, and a photo-collage grid composer). Pure Pillow/numpy maths —
  same photo + same recipe → identical pixels, no AI, no network.
- `photo_edit.py` — wires that engine to a stored asset: saves the recipe in the
  `edit_recipe` column (the original file is never changed), materialises the
  edited image into a signature-keyed cache, resolves the *effective* image path
  a card should read, remembers a club's preferred enhance strength, and exports
  derived profile pictures and collages as new draft assets.
- `heic.py` — converts iPhone HEIC/HEIF uploads to web-safe JPEG on the way in
  (honest-errors if the optional `pillow-heif` decoder isn't installed).

The editor's web surface is `web/photo_editor.py` (the page body) plus the
`/media-library/<id>/edit` routes in `web/web.py`. AI image ops (fill / erase /
background) live separately in `media_ai` (the "Studio").
