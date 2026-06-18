# club_platform

The list of content types MediaHub can make — meet recap, swimmer spotlight, meet
preview, sponsor post — and what each one needs.

Two layers since ADR-0013:

- `post_types.py` — the full **post-type vocabulary** (canonical slugs from
  docs/POST_TYPE_TAXONOMY.md): everything the planner can recommend, whether
  or not a button exists for it yet. Also maps old saved names
  ("weekend_preview", "sponsor_post") to their current slugs so old data
  keeps working.
- `content_types.py` — the **implemented surfaces**: the small subset of
  slugs that have a real clickable page today (the Create tiles).

Also here:

- `format_catalog.py` — the **smart format catalogue** (P6.1): every club
  *design format* as data — a per-channel size for each social platform
  (Instagram / Facebook / X / LinkedIn / Pinterest / TikTok / YouTube …) plus
  off-feed formats clubs need (poster, flyer, certificate, coach card, athlete
  one-pager, season calendar, wallpaper). Each is a typed `FormatSpec` (canvas
  size, safe zones, which layouts suit it, and which run data it needs). Pure
  data, no AI — it just tells the renderer what size to paint. `custom_format()`
  builds an any-size canvas (px/mm/cm/in). Per-sport availability comes from the
  sport profile — a certificate only appears for a sport that produces results.
  The "turn this design into that format" transformer that drives the catalogue
  lives in `turn_into/transform.py`.
- `sponsors.py` — the club's sponsor list (who, what tier, when active),
  the fair-rotation rule that decides which sponsor's logo rides which
  card (the same card always gets the same sponsor), and the monthly
  "your sponsor appeared on N posts" exposure report clubs can forward
  to their sponsors.
