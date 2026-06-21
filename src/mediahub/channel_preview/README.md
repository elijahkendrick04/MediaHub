# channel_preview

Shows a card the way each social platform will, **before** the club posts it by
hand (roadmap **1.14**). MediaHub never posts for you — this is a review aid, so
what you copy across looks right the first time.

For each platform it knows:

- the **crops** it accepts (e.g. Instagram feed 4:5, story 9:16) and their sizes;
- the **safe zone** — where the app's own chrome (profile row, caption, buttons)
  covers a full-screen story/reel, so you keep key content clear of it;
- where the **caption folds** behind a "… more", and the hard caption limit;
- the **hashtag cap**, and what a valid **@-mention** looks like.

Plus an Instagram-style **grid preview** of the planned feed.

## Files

- `specs.py` — the platform data: `PlatformSpec` / `PlatformFormat` / `SafeZone`
  and the `PLATFORMS` registry (Instagram, TikTok, X, Facebook, LinkedIn).
  `platform(slug)` looks one up (alias-tolerant).
- `preview.py` — pure functions over the specs: `truncate_caption`,
  `hashtag_status`, `validate_handle`, `preview_card`, `instagram_grid`.

It is all **plain data + pure functions**: deterministic, offline, no AI —
mechanical platform geometry and text rules (CLAUDE.md keeps the AI path for
judgement calls only). The web layer (`/plan/preview/<pack>`, `/plan/grid`,
`/api/channel-preview`) turns these into the preview frames.

> **Honesty note.** Truncation thresholds and safe-zone insets are *display
> heuristics* — platforms tweak them and they vary by device. Each `PlatformSpec`
> carries a `source` so the numbers can be checked and refreshed; they are for
> preview only, never a promise of exact parity with the live app.

Tests: `tests/test_channel_preview.py`.
