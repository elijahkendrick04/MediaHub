# MediaHub route performance baseline (2026-05-19)

Branch: `claude/measure-mediahub-performance-khojQ`.

## Setup

Server: `gunicorn mediahub.web:app --workers 1 --threads 4`, single Render
Standard-tier-equivalent worker.

```bash
DATA_DIR=/tmp/perf_data python scripts/perf/seed_test_run.py        # seeds test_club, test_run, big_run
DATA_DIR=/tmp/perf_data PORT=5050 gunicorn mediahub.web:app \
    --bind 127.0.0.1:5050 --workers 1 --threads 4 --daemon

# Warm-up (3x /), then 5 requests per route via curl --write-out timing.
rm -f /tmp/cookies.txt
for i in 1 2 3; do
  curl -s -c /tmp/cookies.txt -b /tmp/cookies.txt -o /dev/null http://localhost:5050/
done
python scripts/perf/bench_routes.py --n 5
```

Test data:
- `test_run` — 30 cards (median real-meet size).
- `big_run` — 100 cards (heavy-meet stress).
- `test_club` profile — `is_ready()=True`, `derived_palette` persisted on disk
  (the post-finalise steady state real users sit in).

## Headline results

| Route | Method | p50 before | p95 before | p50 after | p95 after | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `/` | GET | 127 ms | 234 ms | **15.7 ms** | 16.1 ms | every HTML page benefits — see fix #1 |
| `/organisation/setup` | GET | 126 ms | 134 ms | **14.6 ms** | 16.6 ms | calls `ensure_derived_palette()` directly |
| `/pack/<run>/grouped` (30 cards) | GET | 22 ms | 27 ms | 19.9 ms | 20.6 ms | already fast at this size |
| `/pack/<run>/grouped` (100 cards) | GET | 148 ms | 167 ms | **29 ms** | 39 ms | scaled with theming cost, not cards |
| `/healthz/deps` | GET | 373 ms | 415 ms | **6.7 ms** | 7.3 ms | see fix #2 |
| `/api/runs/<id>/cards/<id>/create-graphic` | POST | 32 s cold, 20 s warm | — | unchanged | — | Playwright render — separate work |
| `/api/runs/<id>/reel?n=3` | POST | 45 s cold, 12 ms cached | — | unchanged | — | Remotion render — separate work |

Numbers measured on the running Render-equivalent gunicorn worker; raw samples
in `scripts/perf/baseline_before.json` and `baseline_after.json`.

## Full route table — AFTER fixes

```
label                               path                                status    p50_ms    p95_ms    max_ms
home                                /                                      200      15.7      16.1      16.1
activity                            /activity                              200      16.5      18.0      18.0
upload (GET)                        /upload                                200      14.4      15.4      15.4
research                            /research                              200      14.1      15.4      15.4
privacy                             /privacy                               200      14.6      14.9      14.9
settings                            /settings                              200      18.6      20.2      20.2
status                              /status                                200      15.1      15.7      15.7
make                                /make                                  200      15.4      15.7      15.7
spotlight (index)                   /spotlight                             200      14.8      15.5      15.5
weekend-preview                     /weekend-preview                       200      15.7      17.0      17.0
sponsor-post                        /sponsor-post                          200      16.0      16.7      16.7
session-update                      /session-update                        200      16.2      17.7      17.7
free-text/quick                     /free-text/quick                       200      16.3      22.7      22.7
free-text                           /free-text                             200      14.6      15.2      15.2
drafts                              /drafts                                200      14.6      16.9      16.9
organisation                        /organisation                          200      14.7      43.7      43.7
organisation/setup                  /organisation/setup                    200      14.6      16.6      16.6
media-library                       /media-library                         200      15.0      15.4      15.4
sign-in                             /sign-in                               200      13.8      14.2      14.2
healthz                             /healthz                               200       7.2      17.0      17.0
healthz/memory                      /healthz/memory                        200       1.1       1.2       1.2
healthz/deps                        /healthz/deps                          200       6.7       7.3       7.3
healthz/usage                       /healthz/usage                         200      15.4      15.6      15.6
health                              /health                                200       8.1      10.0      10.0
api/status                          /api/status                            200       3.3       3.8       3.8
api/settings/llm-status             /api/settings/llm-status               200       2.3       2.7       2.7
api/media-library/list              /api/media-library/list.json           200       2.9       3.2       3.2
pack                                /pack/test_run                         302       2.3       2.5       2.5
pack/grouped                        /pack/test_run/grouped                 200      19.9      20.6      20.6
review                              /review/test_run                       200      22.5      22.7      22.7
audit                               /audit/test_run                        200      14.8      14.9      14.9
api/runs/<id>/cards                 /api/runs/test_run/cards               200       2.7       2.9       2.9
api/runs/<id>/recognition           /api/runs/test_run/recognition         200       3.1       3.1       3.1
api/runs/<id>/export                /api/runs/test_run/export              200       3.4       3.8       3.8
api/runs/<id>/newsletter            /api/runs/test_run/newsletter          200       3.8       4.3       4.3
```

(`/add-input`, `/pack/<id>`, `/recognition/<id>` are 301/302 redirects;
`/runs/<id>` 404s without a DB row — synthetic test data doesn't write one.)

## Bottleneck #1 — `derived_palette` cache dropped on every request

### Symptom

Before the fix, `cProfile` of three `/` requests under the test client:

```
3   0.000   1.144   home          (web.py:4795)
3   0.000   1.131   _layout       (web.py:3923)
3   0.000   1.061   _theme_seed_style_block   (web.py:3810)
3   0.000   1.056   ensure_derived_palette    (brand/kit.py:78)
3   0.000   0.990   derive_theme              (theming/__init__.py:146)
18  0.001   0.762   audit_palette             (theming/quality.py:367)
3   0.001   0.658   repair_palette            (theming/repair.py:184)
```

Roughly **352 ms of every HTML page** went into re-deriving the Adaptive
Theming Engine palette (Material You HCT → 5 tonal palettes × 13 tones →
MD3 role mapping → APCA/WCAG/ΔE/CVD gates → repair loop). The same heavy
work ran on `/pack/<id>/grouped`, `/organisation/setup`, `/activity`, etc.

### Root cause

`BrandKit.ensure_derived_palette()` is idempotent: it returns
`self.derived_palette` when present. `BrandKit` does serialise the field
through `to_dict()`, and `/api/organisation/finalise` writes it back into
`profile.brand_kit` on disk. But `ClubProfile.get_brand_kit()` reassembled
a fresh `BrandKit` from a hand-built `merged` dict that did **not**
include `derived_palette`:

```python
# src/mediahub/web/club_profile.py — before
merged = {
    "profile_id": ...,
    "display_name": ...,
    "primary_colour": primary,
    "secondary_colour": secondary,
    "accent_colour": accent,
    "logo_svg": bk_data.get("logo_svg"),
    "governing_body": ...,
    "short_name": ...,
}
return BrandKit.from_dict(merged)   # derived_palette = None
```

Every request that hit `_layout()` (i.e. every HTML page) called
`prof.get_brand_kit().ensure_derived_palette()`, got a freshly built kit
with `derived_palette=None`, and recomputed the whole pipeline.

### Fix

`src/mediahub/web/club_profile.py:get_brand_kit` — propagate the cached
palette through:

```python
merged = {
    ...,
    "derived_palette": bk_data.get("derived_palette"),
}
```

### Measured impact (steady-state, persisted palette)

| Route | Before | After | Δ |
| --- | ---: | ---: | ---: |
| `/` | 127 ms | 15.7 ms | **−88 %** |
| `/pack/big_run/grouped` (100 cards) | 148 ms | 29 ms | **−80 %** |
| `/organisation/setup` | 126 ms | 14.6 ms | **−88 %** |

Post-fix `cProfile` on `/pack/big_run/grouped` shows zero theming time in
the hot path — the bottleneck shifts to Jinja template compilation (~20 ms)
and `_section_html` formatting (~29 ms), both normal Flask overheads.

### First-time-visit footnote

The fix relies on `derived_palette` already being on disk. For a brand-new
profile that hasn't gone through `/api/organisation/finalise` yet, the
first `/organisation/setup` GET still pays ~126 ms because there's nothing
to read. A follow-up could persist the palette opportunistically inside
`_theme_seed_style_block` on first compute, but the user flow normally
hits `/api/organisation/finalise` before they look at other pages, so
this is a one-off cost in practice.

## Bottleneck #2 — `/healthz/deps` spins up the Playwright driver subprocess

### Symptom

```
3   0.000   1.110   healthz_deps                      (web.py:8252)
3   0.000   1.089   sync_playwright.__exit__          (playwright/_context_manager.py:86)
3   0.000   1.087   stop_sync                         (playwright/_connection.py:316)
9   0.000   1.087   run_until_complete                (asyncio/base_events.py:618)
108 1.061   1.061   epoll.poll                        (selectors.py:451)
```

~360 ms per call. Operators poll `/healthz/deps` (it's the data source
for the captions-tab status dot), so the cost compounds.

### Root cause

The route only wanted to verify the Chromium binary is on disk, but used
the sync Playwright API to read it:

```python
with sync_playwright() as p:
    browser_path = p.chromium.executable_path
    chromium_ok = bool(browser_path and Path(browser_path).exists())
```

`sync_playwright()` forks the Playwright Node driver subprocess, hand-shakes
over a pipe, then tears it down through `asyncio.run_until_complete` — all
to read an attribute. The browser is never launched, so there's no upside.

### Fix

`src/mediahub/web/web.py:healthz_deps` — replace the sync Playwright probe
with a direct filesystem check against `$PLAYWRIGHT_BROWSERS_PATH` (or the
default `~/.cache/ms-playwright`). The actual browser launch happens at
graphic-render time and will still surface deeper issues there.

### Measured impact

| Route | Before | After | Δ |
| --- | ---: | ---: | ---: |
| `/healthz/deps` | 373 ms | 6.7 ms | **−98 %** |

## Heavy POST routes — not a "small fix" problem

These are inherent to the renderers, not a Flask-level issue:

| Route | Cold | Warm/cached | Where the time goes |
| --- | ---: | ---: | --- |
| `POST /api/runs/<id>/cards/<id>/create-graphic` | ~32 s | ~20 s | Playwright launches Chromium per format (square, story, …) and screenshots each |
| `POST /api/runs/<id>/reel?n=3` | ~45 s | ~12 ms | `_motion.render_meet_reel` shells out to Node + Remotion + Chromium for the 3-card composition. Cached at `DATA_DIR/runs/<id>/motion/reel_<n>.mp4` |

Possible follow-up work (not done here — bigger blast radius, deserves
its own PR):

1. **Persistent Chromium browser per worker.** `graphic_renderer` opens a
   fresh `sync_playwright()` context per card and per format. A
   `--preload`-style worker hook (or `worker_int`) could keep one browser
   instance alive across requests; only `browser.new_context()` /
   `new_page()` cost would remain. Best-case 10–15 s saved per
   create-graphic call.
2. **Pre-bundle Remotion at worker boot.** The reel render rebundles the
   Remotion entry every cold call; `bundle()` could be moved into a
   gunicorn `post_fork` hook so the bundle is hot when the first reel
   request arrives. Saves ~5–8 s on the cold path.
3. **Format-parallel screenshots.** `create-graphic` renders each format
   sequentially. Sharing one Chromium and tabbing in parallel pages would
   cut total time roughly to `max(format_times)` instead of `sum(...)`.

These are real, but they're 20–45-second renderer optimisations rather
than the request-routing perf issue this baseline was scoped to.

## Other observations

- `/upload`, `/research`, `/privacy`, `/settings`, etc. all land at
  ~12–18 ms with no work to do. Healthy.
- `/api/*` JSON endpoints are all sub-5 ms p95.
- `/recognition/<id>` and `/pack/<id>` redirect (302) in <2.5 ms.
- `/runs/<id>` 404s when only the JSON exists without a DB row — this is
  expected handling, not a perf issue.
