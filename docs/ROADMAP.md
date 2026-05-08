# Roadmap

Versions reflect the contracts shipped between iterations of the live app.

## V8.x (current)

- ✅ Brand kit upload (V8.1)
- ✅ Two-step upload UI
- ✅ Cutout providers: rembg / Replicate / PhotoRoom
- ✅ Vision-aware creative briefs
- ✅ Variation seed for deterministic regeneration
- ✅ Live AI captions
- ✅ Voice induction from exemplars
- ✅ V8.2 polish: render upgrades, venue search hardening

## V8.3 (planned)

- Open-water swim support (timed lap segments instead of pool events)
- USA Swimming PB source in `pb_discovery`
- Manual swimmer-identity override UI on `/review/<id>`
- Background GC for `runs_v4/` older than 90 days

## V9 (planned, partial in this export)

- ✅ Master handoff package — portable, deployable, maintainable
- Native AI image generation (replace stock photo pull with Stable
  Diffusion / DALL·E for hero images)
- Per-event venue photo enrichment via `venue_search`

## V10 (vision)

- Multi-sport: athletics, cycling, rowing
- Real-time meet feed (live captioning while a session is on)
- Native iOS / Android share-sheet integration

## Long-shelf-life ideas

- Multi-tenant SaaS variant with per-club isolation
- Move from JSON ledgers to Postgres
- WebSocket pipeline status (replace `/api/runs/<id>/status` polling)
- A learnable ranker that takes `like_rate` feedback from posted content
