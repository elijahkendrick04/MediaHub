# Swim Content v2 — Pilot Rebuild Results

## What runs end-to-end on the real Swansea meet

Input:
- `Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip` (Hytek HY3+CL2)
- 4 SPORTSYSTEMS Club Rankings PDFs (F/M × LC/SC, generated 2026-05-04)

Output:
| Stage | v1 | v2 |
|---|---|---|
| Swims parsed | unknown / unreliable text scrape | **1665** swims, **49** clubs, **494** swimmers |
| Roster filter | none — all swimmers treated as Swansea | **40 SUNY swimmers, 88 swims** (host club excluded) |
| Achievement items | ~80 separate flags | **88 cards → 17 review-ready** (one swim = one card) |
| Captions | leaked codes like `BUCS_LC_2025_26` | phrasebook-only, never internal codes |
| Upload report | none | full report + 16-row "needs confirmation" table |
| Determinism | non-idempotent (PB store mutated mid-detection) | pure functions, re-runnable |

## Files written this turn

```
swim-content/swim_content/
  parsers_hy3.py       # fixed-width HY3 reader (verified col positions)
  parsers_pb_pdf.py    # SPORTSYSTEMS PDF reader (positional, by ASA ID)
  club_filter.py       # single chokepoint for "is this swim ours?"
  detector_v2.py       # pure-function detector, ContentCard model
  ranker.py            # composite scoring + queue/recap/archive thresholds
  content_gen_v2.py    # phrasebook captions, no leaked labels
  upload_report.py     # always-first post-upload screen
  pipeline.py          # orchestrator
  app_v2.py            # Flask app (upload → report → queue)
swim-content/templates/
  home_v2.html, upload_v2.html, report_v2.html, queue_v2.html
swim-content/AUDIT_AND_V2_DESIGN.md     # written in prior turn
```

## Definition of done — pilot

A pilot is "done" when ALL of these are true on a real Swansea Uni meet:

1. **Inputs**: System accepts a Hytek `.zip` directly and 1-4 PB PDFs.
2. **Counts visible**: Upload report shows clubs / swimmers / swims / our-share.
3. **No opposition leaks**: ≥99% of in-queue cards are Swansea Uni; zero `SWAY` (host).
4. **Grouped by swim**: One swim = one card. No type-multiplied duplicates.
5. **Triaged queue**: 10–30 cards in queue, not 80.
6. **Honest PB labels**: PB claims require PB-store evidence (entry times never trusted as PBs).
7. **Clean captions**: No internal codes (`BUCS_LC_2025_26`, etc.) in any caption.
8. **Time-to-approve**: Coach can review the queue + approve/reject in <10 minutes.
9. **Idempotent**: Re-uploading produces the same output. PB store is never mutated by detection.
10. **Confirmation flag**: Cards we cannot fully verify are surfaced under "needs human confirmation" with seed-time context, not auto-published.

The Swansea Aquatics May LC 2026 run hits **1, 2, 3 (zero leaks), 4, 5 (17 cards), 6, 7, 9, 10**. Item 8 needs operator-in-the-loop testing on the real workflow.

## What data I still need from you

To complete the pilot to production-readiness:

### Critical for honest PB detection
1. **A PB-store snapshot dated BEFORE the meet.** The PDFs you provided were exported 2026-05-04, AFTER the meet on 2026-05-02/03 — so they already include the meet's times. The system correctly flags this and refuses to claim PBs in this state. For future meets, please export the PDFs *the day before* the meet and upload them as the PB-store snapshot.

### High value for richer detection
2. **Swansea Uni club records list** (any format). This is the canonical record set. Without it, `CLUB_RECORD` can never fire.
3. **BUCS qualifying times** for the current cycle (PDF or CSV). Required to fire the `QT_MET` reason confidently.
4. **Two more meet archives** — one short course and one smaller open meet — so we can verify the parser holds up across formats.

### To improve voice and presentation
5. **5–15 example past Instagram captions** the team has actually published. The phrasebook is currently club-neutral; with examples we can tune voice without going full-LLM.
6. **Brand kit**: logo file, primary colour (we used the Swansea red `#A30D2D` you'd previously mentioned), heading font.

### Highest leverage validation data
7. **A ground-truth list of 10-15 moments from a recent meet that the team did post about.** This is the best way to measure precision/recall: the system should surface those same moments. If it misses them or surfaces noise instead, we know exactly what to tune.

## Things deliberately NOT built (per your instructions)

- SaaS / multi-tenant / multi-club platform
- Auto-poster (Instagram / Twitter / LinkedIn)
- Adjacent-sport support
- Live results polling / mid-meet content
- swimmingresults.org scraping (no public API; PDFs cover this)
- LLM-generated captions
- Full graphics / image generation
- Persistent DB schema for v2 (in-memory cache; deterministic re-runs are cheap)

## Honest limitations

- **PB detection is only as good as the snapshot.** Without a pre-meet PB export, every PB candidate falls through to "needs confirmation".
- **Barrier-break detection requires a confirmed prior PB above the barrier.** First-time entries to a stroke don't trigger barrier reasons. This is intentional — we'd rather miss a marginal celebration than fabricate one.
- **Only the 17 standard events have barrier thresholds wired up.** Less common events (50 BR LC, 800 IM, etc.) are not covered.
- **CL2 (SDIF) format is not yet supported** — but every Hytek meet zip carries a redundant `.hy3` so this isn't a blocker.
- **Identity is by ASA member ID only.** Swimmers whose meet entry is missing an ASA ID will be skipped (3 swimmers in the test file).
