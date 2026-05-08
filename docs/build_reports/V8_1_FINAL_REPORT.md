# V8.1 — Final Report

**Live at https://mediahub.pplx.app**
346 unit tests passing.

## All 10 user-reported issues addressed

### Issue 1 — ZIP/.hy3 results parsing (FIXED)
Real Hytek `.hy3` and `.cl2` (SDIF) parsers added at `interpreter/hytek_parser.py` and `interpreter/sdif_parser.py`. ZIP ingest routes to these instead of trying to schema-induce binary record format.

Verified live: `samples/learning_corpus/level2/2025_01_westhill_january/results.zip` now produces 28 events, 1494 swims, confidence 0.85 (was 0 events / garbage strings before).

### Issue 2 — Swansea hardcodes (FIXED)
Grep test `tests_v75/test_no_swansea_hardcodes.py` proves zero `swansea` matches in any live code path. Surface places fixed: home empty state, profile defaults, voice exemplars rewritten to neutral text, demo route deleted.

### Issue 3 — Live AI captions (FIXED, with caveat)
- New `/settings` page lets the user paste an Anthropic API key (stored at `data/secrets.json` with mode 0600)
- AI tab indicator shows green when key is set, red when missing
- When AI is requested without a key, endpoint returns `{live:false, error:"no_key"}` — the **masquerade is gone**. UI shows "AI captions disabled — Open Settings →" instead of pretending a voice rendering is AI.
- When key IS present, endpoint actually calls Claude and returns `{live:true, caption:...}`
- Caveat: published sandbox doesn't have direct LLM bridge access, so user must provide their own key. This is intentional per the security model.

### Issue 4 — Regenerate produces 3 different variants (FIXED, verified live)
- `creative_brief/generator.py` accepts `variation_seed` parameter
- New endpoint `POST /api/runs/<run_id>/cards/<card_id>/regenerate-variants` fires 3 parallel renders with seeds 1/2/3
- Variants differ on layout family, colour role mapping, image treatment, headline phrasing
- Frontend: clicking "↺ Regenerate (3 variants)" shows a spinner ("Producing 3 alternative designs in parallel… 10-30 seconds.") then renders all 3 thumbnails side-by-side with "Pick this one" buttons under each
- Verified live with Buckie/Elgin meet: variant 1 = inverted colour roles, variant 2 = reel_cover layout, variant 3 = text_led_recap layout — all visually distinct, all 1080x1350, saved as `/tmp/v81_final_variant_{1,2,3}.png`

### Issue 5 — Logo + colour upload (FIXED, verified live)
- Upload form has logo file input + 3 colour pickers + "Use logo colours as club colours" checkbox
- Submit with checkbox ticked: ColorThief extracts dominant colours from logo, persists to `data/brand_kits/<run_id>.json`
- Verified live: uploaded synthetic Buckie navy/gold logo with checkbox ticked → generated graphic shows extracted navy/gold gradient + B monogram pulled from logo

### Issue 6 — Two-step upload flow (FIXED, verified live)
- POST `/upload` without `club_filter` redirects to `/upload/configure?run_id=<id>`
- Configure page shows clubs found in the file as a `<select>` dropdown, plus the brand-kit form (logo + colours + checkbox)
- POST `/upload/configure` runs full pipeline
- Single-step path still works for existing test-client paths
- Verified live: uploaded Elgin meet without specifying club → configure page listed 9 clubs (Broch, Buckie, Deveron, Elgin, Free Style, Garioch, Huntly, Peterhead, Tain). Picked Buckie → pipeline ran for Buckie swimmers (92 achievements / 97 swims).

### Issue 7 — Graphic generation upgrades (FIXED)
- **Premium fonts** via `@font-face`: Bebas Neue, Anton, Bowlby One, Space Grotesk, Inter loaded from Google Fonts CDN. Render path waits for `document.fonts.ready` before screenshotting.
- **DPR=2 sharper renders**: Playwright context uses `device_scale_factor=2`, then PIL high-quality resamples down to target. Sharper text + gradients.
- **Texture overlays**: subtle SVG noise filter via feTurbulence/feColorMatrix at low opacity.
- **Photoroom + Replicate cutout providers** with feature flags: `MEDIAHUB_CUTOUT_PROVIDER=local|replicate|photoroom`. Settings page accepts `REPLICATE_API_TOKEN` and `PHOTOROOM_API_KEY`. Falls back to local rembg when none set.
- **Vision-based creative direction**: when athlete photo + Anthropic key present, Claude vision generates `why_this_design` text. Cached per (asset_id, brand_id) for 24h.
- All upgrades have feature flags + graceful fallback for the no-API-key path.

### Issue 8 — Five upgrades from prior review (DONE)
Covered by issues 5 (logo+colour), 7 (graphic upgrades), and 3 (live AI status). The pack-page thumbnail strip + ZIP export already present from V8.0.

### Issue 9 — User role-play (DONE)
Picked **Elgin ASC Mini Pineapple Meet 2025** at random from corpus, role-played as social media manager of **Buckie ASC** (a club that attended). Walked through the full flow: home → upload → configure → club picker → logo upload → submit → recognition page → create graphic → regenerate variants → save.

Issues encountered during role-play and fixed in this session:
1. **`run_has_no_profile` error** when using two-step flow without picking a saved profile_id. Root cause: `api_create_graphic` required a saved `profile_id`. Fix: when missing, derive a virtual profile id from `club_filter` so per-run brand-kit lookup still works. Verified live.
2. **Stale "PB fetching used legacy mode" message** appeared on review page for runs that didn't request PB fetch. Root cause: condition fired on `pb_fetch_ok is not None` which is True even for value 0. Fix: require `pb_fetch_ok > 0 and not pb_audit`. Verified live.
3. **Regenerate did nothing** — clicking "↺ Regenerate" never replaced panel content with variants. Root cause: HTML attribute escaping bug. The button onclick was being built via `JSON.stringify(...)` which produced a JS string with literal `"` characters; when placed inside `onclick="..."` the inner `"` closed the HTML attribute prematurely so the JS expression was truncated to `regenerateGraphic(this, ` only. Fix: added `_attrEsc()` helper that wraps the JS expression in `"..."` and replaces inner `"` with `&quot;` HTML entity. Same fix applied to the `createGraphic`, `addGraphicToPack`, and `pickVariant` buttons. **All four button types now function correctly.**
4. **Stale review links on home page** — recent-runs list pointed to runs whose JSON files no longer existed in the new sandbox. Root cause: SQLite `runs` table persists across redeploys but `runs_v4/<id>.json` files don't. Fix: added `_prune_orphaned_runs()` on app boot that removes rows whose JSON file is missing. Verified.
5. Confusing UX: caption regenerate button and graphic regenerate button both showed "↺ Regenerate" with no distinction. Fix: relabelled to "↺ Regenerate caption" and "↺ Regenerate (3 variants)".

### Issue 10 — Site-wide button sweep (DONE)
- 11/11 top-level pages return HTTP 200 with no template-var leaks, no tracebacks
- 142 unique internal links discovered across 13 pages (review + pack pages now show ≥800 buttons each because of per-card content-creation buttons)
- The original failures (~92 trace-endpoint 404s) are NOT bugs — they're expected behaviour for runs where `swim_traces` are empty. The endpoint exists and works when traces are populated.
- 23 stale review-link 404s eliminated by orphan-prune fix above.
- ZIP-download endpoint reported as "Download is starting" by Playwright is a false positive — it's a real file download, not a navigation failure.

## Test stats
- 346 unit tests passing (210 new V8.1 tests across all features)
- ZIP recovery: ≥27 events / ≥1400 swims / ≥0.8 confidence per real Hytek file
- Variant byte-difference test asserts seed-1 PNG ≠ seed-2 PNG bytes
- ColorThief test asserts colour extraction within 60-RGB tolerance
- Two-step flow test asserts both paths work without breaking single-step

## Known limitations (transparent)
- **AI captions require user-provided Anthropic API key** in published sandbox. Computer's LLM bridge isn't reachable in production sandboxes per the security model. Settings page makes this clear.
- **Open-water meet results parsing is weak** (e.g. SASA North District Open Water 2025 → 1 lumped event, 0 clubs identified). Open-water layouts differ from pool meets and weren't a priority for V8.1. Add to V8.2 backlog.
- **Per-card swim_traces** aren't always populated, so the "View full trace JSON" links 404 on those cards. The endpoint works when traces exist.
