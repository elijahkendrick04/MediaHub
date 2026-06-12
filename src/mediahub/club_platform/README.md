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

- `sponsors.py` — the club's sponsor list (who, what tier, when active),
  the fair-rotation rule that decides which sponsor's logo rides which
  card (the same card always gets the same sponsor), and the monthly
  "your sponsor appeared on N posts" exposure report clubs can forward
  to their sponsors.
