# media_library

Stores the photos and other media a user uploads, and remembers what's in each one
(who's in it, what it shows) so the right photo can be picked for a card.

## What's in here

- `models.py` / `store.py` — the `MediaAsset` record and its SQLite storage.
- `describe.py` / `tagger.py` — AI-assisted "what's in this photo" tagging.
- `selector.py` — the deterministic maths that scores which photo best fits a card.
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
