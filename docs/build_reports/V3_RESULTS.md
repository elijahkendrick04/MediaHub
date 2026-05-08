# Swim Content Intelligence — V3 Results

**Pilot:** Swansea University Swimming (SUNY)
**Test meet:** Swansea Aquatics May Long Course 2026 (HY3 zip, 1665 swims, 49 clubs, 494 swimmers)
**Stack:** Python 3 / Flask / Jinja / vanilla JS sprinkles · Playwright for E2E test
**Server:** `python3 app_v3.py` → http://localhost:5051

---

## What V3 actually does

V3 turns a meet results file into a reviewed queue of social-ready posts in four stages:

1. **Upload** — choose `.hy3` (or `.zip` containing one), club, output preferences.
2. **Verification** — see what the pipeline found, with all 13 self-checks visible, **before** any captions are shown.
3. **Dashboard** — content cards with three caption voices, evidence trail, and approve/reject/edit per card.
4. **Output** — copy-ready captions split by `ready_to_post` / `needs_confirmation` / `recap`, downloadable as `.txt`, `.json`, or zipped bundle of per-card files.

The defensible product is the intelligence layer underneath. Everything is sourced; nothing is invented.

---

## Live numbers from the test run

| Metric | Value |
|---|---|
| Total swims parsed | 1,665 |
| Filtered to SUNY | 88 (1,577 excluded; SWAY host correctly excluded) |
| Swimmers in scope | 36 |
| PB histories fetched live from swimmingresults.org | 36 / 36 |
| Confirmed PBs | 1 |
| Likely PBs (same-day or unverified prior) | 13 |
| Qualification hits (BUCS LC + Aquatics GB Champs) | 94 |
| Content cards generated | 45 |
| In queue (target 8–20) | **19** |
| Recap mentions | 26 |
| Archived | 0 |

**Self-check:** 12 pass · 1 warn · 0 fail. The single warning is the legitimate flag that 13 Aquatics-GB qualification hits fell outside that competition's window (window closed 12 April 2026; meet is 3 May 2026) — exactly the surface the brief asked for: "if a fact cannot be verified, say so, but don't dominate the queue".

---

## Definition of Done — checklist against the brief

| Brief requirement | Status | Where it lives |
|---|---|---|
| Interactive web interface with four main stages | ✅ | `app_v3.py` + 4 templates in `templates/` |
| Live PB enrichment from swimmingresults.org | ✅ | `swim_content/enrichment_swimmingresults.py` |
| Status taxonomy: CONFIRMED_PB / LIKELY_PB / PB_UNVERIFIED / NOT_PB | ✅ | `enrichment_swimmingresults.compare_to_pb` |
| Never compare LC and SC PBs directly | ✅ | hard rule in `compare_to_pb` |
| Never treat entry time as a trusted PB | ✅ | only swimmingresults.org best history is trusted |
| Don't silently fail on PB enrichment | ✅ | `pb_fetch_failed` and `pb_fetch_errors` surfaced in verification stage |
| Cache PB lookups | ✅ | `.cache/swimmingresults/{tiref}.json`, 30-day TTL, 1s rate-limit |
| Qualification registry with sources | ✅ | `data/quals.json` seeded with BUCS LC 2026-27 + AGB Champs 2026, source PDFs cached in `data/quals_sources/` |
| Auto-search + confirm for stale standards | ✅ | `swim_content/quals_updater.py` (proposes, never auto-commits) |
| Importance-based qualifier ranking (national > university > open) | ✅ | `Standard.level` field used in ranker |
| Evidence log on every claim | ✅ | `swim_content/evidence.py`, attached in `evidence_aggregate.py` |
| Storyline grouping (sweeps, doubles, multi-event spotlights) | ✅ | `swim_content/grouper.py` |
| PB roundup (4+) and podium roundup (5+) | ✅ | `grouper.py` |
| Weekend in numbers | ✅ | `grouper.py` |
| Context-aware ranker with anti-spam | ✅ | `swim_content/ranker_v3.py` |
| Anti-spam: spotlight demotes standalone cards by 25 | ✅ | `ranker_v3.rank_cards` |
| Queue cap 8–20 | ✅ | `queue_cap=20`, overflow → recap |
| Three caption voices (clean / team / hype) | ✅ | `swim_content/captions_v3.py` |
| No internal codes in captions | ✅ | covered by self-check C11 |
| 13-check self-verification layer | ✅ | `swim_content/self_check.py` (codes C1–C13) |
| Self-check shown before dashboard | ✅ | verification stage |
| Output pack: copy-ready text + JSON + zip | ✅ | `swim_content/output_pack.py` |
| Approve / reject / edit per card | ✅ | dashboard `/api/<run>/cards/<id>/decide` |
| Per-card: headline, swimmer, event, time, why, evidence, sources, last-checked, confidence, format, score, captions | ✅ | dashboard card layout |

**Out of scope (per user instruction):** auto-posting, SaaS multi-tenancy, adjacent sports, live polling, scheduling, CRM, full graphics generation. None of these were built.

---

## Architecture (V3)

```
upload → run_pipeline() → PipelineRun → verification → dashboard → output_pack
              │
              ├─ parsers_hy3        (SD3/HY3 parser inherited from V2)
              ├─ club_filter        (SUNY roster, excludes host SWAY)
              ├─ enrichment_swimmingresults  (live PB fetch + cache)
              ├─ quals_registry     (loads data/quals.json)
              ├─ detector_v3        (medals, PBs, qual hits → flat Claim list)
              ├─ grouper            (claims → ContentCards by storyline)
              ├─ evidence_aggregate (attaches source URLs from claims onto cards)
              ├─ captions_v3        (three voices per card type)
              ├─ ranker_v3          (base scores + modifiers + anti-spam + bucket)
              └─ self_check         (C1–C13 guardrails)
```

The only network-dependent module is `enrichment_swimmingresults`. Everything else is local.

### Key invariants

- **`tiref` is identity.** No name-matching across clubs.
- **LC and SC are never compared** for PB status.
- **Same-day PB** = LIKELY_PB, never CONFIRMED, because we lack a pre-meet snapshot.
- **Queue cap 20** with anti-spam demotion is enforced, not optional.
- **Every card carries evidence**, including the meet file as the primary record. C10 of the self-check fails if any card has zero evidence rows.

---

## Files added/changed this build

```
swim-content/
  app_v3.py                                     ← Flask V3 server
  templates/
    _layout_v3.html                             ← shared layout with 4-stage nav
    upload_v3.html                              ← stage 1
    verification_v3.html                        ← stage 2
    dashboard_v3.html                           ← stage 3 (cards, voices, approve)
    output_v3.html                              ← stage 4
  static/style.css                              ← extended with V3 styles
  swim_content/
    enrichment_swimmingresults.py               ← live PB fetch + cache + status
    evidence.py                                 ← Evidence dataclass + confidence buckets
    quals_registry.py                           ← Standard model, lookups, freshness
    quals_updater.py                            ← auto-search proposal generator
    cards.py                                    ← ContentCard, Claim, CaptionVariants
    grouper.py                                  ← storyline grouping
    ranker_v3.py                                ← context-aware scoring
    captions_v3.py                              ← 3-voice generators
    detector_v3.py                              ← claim production
    evidence_aggregate.py                       ← evidence rollup onto cards
    self_check.py                               ← 13 checks
    output_pack.py                              ← txt/json/zip exports
    pipeline_v3.py                              ← orchestrator
  data/
    quals.json                                  ← BUCS LC 2026-27 + AGB Champs 2026 (seeded with real times)
    quals_sources/                              ← cached source PDFs

V2 files preserved untouched (parsers_hy3.py, club_filter.py, parsers_pb_pdf.py, app_v2.py, V2 templates).
```

---

## Sample captions produced (post-fix)

**Athlete spotlight, Dominic Morgan — backstroke clean sweep** (score 98)

- Clean: "Dominic Morgan sweeps the Backstroke events: 50m Backstroke (27.06), 200m Backstroke (2:09.26), 100m Backstroke (57.99)."
- Team: "What a meet from Dominic Morgan — a clean sweep of the Backstroke events. 3 golds across 3 notable swims. Take a bow."
- Hype: "DOMINIC MORGAN. BACKSTROKE CLEAN SWEEP. 3 GOLDS. UNREAL."

**Standout swim, Ruby Laverick — 50m Freestyle gold + confirmed PB + qual hit** (score 66)

The single card carries gold + pb_confirmed + qual_hit claims for the same swim, *not three separate cards* — the grouping bug found mid-build was fixed and verified.

---

## Bugs fixed during the build

1. **C8 false positive (duplicate-standalone check):** the original implementation iterated all claims on a card and flagged the same key on the second iteration even when it was the same card. Fix: dedupe claim keys per-card before comparing across cards (`self_check.py`, lines 182–196). Now passes with 0 reported duplicates.
2. **BUCS qualification window 2025-26 → 2026-27:** the seed had the wrong season for a May 2026 meet, so all BUCS hits were marked out-of-window. Fixed by re-seeding `data/quals.json` after re-downloading the canonical BUCS PDF.
3. **Spotlight captions failed when 0 PBs:** rewrote `captions_v3.spotlight_*` to lead with the strongest *available* signal (medals, then PBs, then qual hits) instead of assuming PBs exist.
4. **Same-day PB ambiguity:** if the listed PB date on swimmingresults.org equals the meet date, status is LIKELY_PB, not CONFIRMED, because the page may already include the meet's swim. Documented in `compare_to_pb`.
5. **`meet.swimmers` is a dict, not a list:** detector originally iterated incorrectly; fixed in `pipeline_v3.run_pipeline`.

---

## Remaining gaps & honest caveats

1. **Confirmed PB ratio is low (1/14).** Most PBs come back as LIKELY because swimmingresults.org records the new PB on the meet date itself, and we don't have a pre-meet snapshot for this run. Fix is operational, not code: snapshot the roster before the meet, store under `.cache/swimmingresults/<tiref>.json`, then run V3 — every PB beaten in the meet will be CONFIRMED.
2. **Aquatics GB window legitimately excludes this meet** (window ended 12 April 2026; meet is 3 May 2026). The 13 hits are flagged as out-of-window and surface in the warn channel — this is correct behaviour, not a defect, but it limits the qualification storyline angle for this specific meet.
3. **Pipeline runs synchronously on upload.** For a 36-swimmer roster with cache, end-to-end is under 2 seconds. With cold cache it's ~40s. For larger clubs the upload form should hand off to a background job and poll for progress; current setup blocks the request thread.
4. **Auto-search confirm flow** (`quals_updater.py`) is implemented and tested as a function but not wired into a UI screen. The proposal data is ready to render — adding a fifth admin screen is half a day's work.
5. **In-memory run store.** Runs live in `RUNS` dict; restarting the server discards them. Fine for the pilot; needs Redis or SQLite for multi-instance.
6. **No per-event live ratings** (e.g., national rank). swimmingresults.org's rankings page is reachable but parsing it is more involved; deferred.
7. **No diving / synchro / open-water support.** Pilot is pool only.
8. **Single locale.** Captions are British English, hard-coded.

---

## How to run locally

```bash
cd /home/user/workspace/swim-content
pip install -r requirements.txt   # flask + requests + bs4 (already installed)
python3 app_v3.py                  # serves on http://0.0.0.0:5051
```

Then upload `Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip`.

---

## Screenshots

Four full-page captures plus two interaction states are in `screenshots_v3/`:

- `01_upload.png` — stage 1
- `02_verification.png` — stage 2 (stats + 13 self-checks)
- `03_dashboard_queue.png` — stage 3 with all 19 queue cards
- `04_dashboard_approved.png` — first card with "Approved" status pill
- `05_dashboard_hype.png` — same card with hype voice selected
- `06_dashboard_recap.png` — recap-mentions tab
- `07_output.png` — stage 4 with download buttons
