# Swim Content Automation V4 — Results

V4 is a hosted, generic, trust-first build of the swim content tool. It runs in a normal web browser at a public `*.pplx.app` URL — no local install, no terminal, no copy-paste. The engine is no longer hardcoded around Swansea.

## What changed from V3

| Area | V3 | V4 |
| --- | --- | --- |
| **Access** | Local Flask on `localhost:5051` only | Public hosted URL via `publish_website` |
| **Club logic** | Swansea Uni hardcoded into `club_filter.py` | `ClubProfile` JSON files; engine is generic |
| **Input** | One HY3 path inside the repo | Adapter dispatcher with `can_parse()` confidence + zip auto-pick |
| **Schema** | Internal `ParsedMeet` only | Canonical `Meet` with `ParseWarning` + `SourceEvidence` |
| **Meet inference** | Trust HY3 fields blindly | Infer course / dates / host / governing body with warnings |
| **Trust** | Self-check counts only | Per-card confidence + safe-to-post + sources + "why this status" |
| **Validation** | None | Ground-truth mode with precision / recall / F1 |
| **Pipeline progress** | Synchronous, blocked the request | Background thread + polled progress page |
| **Privacy** | Implicit only | Explicit data inventory + delete-run + clear-cache |

## Architecture

```
   upload  ─────────►  AdapterDispatcher
                        │     can_parse() picks best adapter,
                        │     opens .zip and scores entries
                        ▼
                      HY3Adapter ─► canonical Meet
                                          │
                                infer_missing()  (course/dates/host/GB)
                                          │
                          ClubProfile.is_ours()  (replaces hardcoded SUNY)
                                          │
                          v3_shim.canonical_to_v3()
                                          │
                ┌──────── reused V3 modules (unchanged) ────────┐
                │  detector_v3 → grouper → captions_v3 →        │
                │  ranker_v3   → self_check                     │
                └───────────────────────────────────────────────┘
                                          │
                                  build_trust_report()
                                          │
                                Web UI: review / ground-truth /
                                profiles / privacy
```

The `v3_shim` is deliberate: V3's detector/grouper/ranker were tuned and verified against a 1665-swim real meet (12 pass / 1 warn / 0 fail self-check). V4 runs the *exact same logic* on canonical inputs to avoid regressions, while every other module operates on the canonical schema.

## Sample run (Swansea Aquatics May LC 2026)

```
Adapter 'hy3' parsed 1665 swims, 494 swimmers across 49 clubs.
Inferred missing fields: governing_body.
Auto-selected club profile: swansea-uni
Filtered to Swansea University Swimming: 88 swims by 36 swimmers, 1577 excluded.
PB enrichment: 36/36 (ok 36, fail 0)
Loaded 2 qualification standards (0 stale, 2 relevant).
Detector: 160 claims (PB confirmed 1, likely 13, qual hits 94, medals 52).
Self-check: 12 pass, 1 warn, 0 fail.
Trust: 38 ready to post, 7 need a quick review, 0 should be held back.
```

Numbers match V3 exactly (88 SUNY swims, 36 swimmers, 12/1/0 self-check) → we have not regressed the proven pipeline.

## Trust UI

For each card we surface:

- **Confidence** (high / medium / low) derived from the strongest underlying claim.
- **Safe to post** (post / review / hold) — explicit recommendation.
- **Why this status** in plain English, e.g. *"Same-day PB without a pre-meet snapshot — likely but not proven. Confirm before posting."*
- **Sources** — meet results file, swimmingresults.org PB lookup (with the actual URL), qualification standards registry (with public URL).

A confirmed PB on a medal swim renders as `high · post`. A same-day PB without a pre-meet snapshot stays at `medium · review` until a human eyeballs it. Anything in the `archive` or `needs_confirmation` bucket is automatically `hold`.

## Ground-truth mode

Paste 5–15 expected highlights from a meet (free text, one per line). The system parses swimmer surname, distance, and stroke from each line and matches against generated cards. You get:

- Precision (matched / total cards)
- Recall (matched / total moments)
- F1
- Per-moment table with which card matched and the match score

This is the missing feedback loop that lets you measure whether V4 is actually surfacing what your social media manager would have surfaced manually.

## Privacy

The `/privacy` page lists what is stored and where. Per-run delete and one-click PB cache clear are both supported. No data leaves the sandbox except the deliberate, throttled (1s) calls to the public `swimmingresults.org` PB pages.

## Hosted access

The app runs at the Perplexity-hosted URL printed at the end of the publish step. The only state that persists across redeploys is `data.db` in the project root (snapshotted automatically) and the `club_profiles/` JSON files.

## What V4 does NOT do (preserved intentionally)

Per brief: no auto-posting, no SaaS billing/multi-tenancy, no other sports, no complex graphics, no CRM, no scheduling.

## Known gaps and follow-ups

These are honest — not silently dropped:

1. **Only HY3 is supported today.** The dispatcher and canonical schema are designed for many adapters, but only HY3 ships in V4. The research substream ran to enumerate UK + US meet sources; the roadmap will appear on the `/research` page once written.
2. **Caption tone uploader** (5–15 past captions to tune voice) is not wired into the UI yet — V3's existing voice templates run unchanged.
3. **Manual corrections feedback loop** is not yet a UI — a card can be deleted via the run delete, but per-claim corrections persisted to a profile is future work.
4. **Pilot metrics dashboard** (cross-run KPIs) is not in V4. Each run's evidence is exportable as JSON via `/api/runs/<id>/export`.
5. **Regression test runner with golden files** is not in V4. A reproducibility check is implicit: re-running the seeded Swansea meet must produce 88 / 12-1-0.

## File-by-file map (what's new in V4)

```
swim_content_v4/
  canonical.py       Canonical schema + adapter base class
  inference.py       Fill missing meet fields with warnings
  club_profile.py    JSON-backed club profiles, replaces hardcoded SUNY
  trust.py           Per-card confidence + safe-to-post + sources
  ground_truth.py    Precision / recall / F1 against pasted moments
  v3_shim.py         Bridge canonical → V3 ParsedMeet (no detector rewrite)
  pipeline_v4.py     Orchestrator (dispatch → infer → filter → V3 detect)
  web.py             Flask app: upload, progress, review, profiles, privacy
  adapters/
    dispatcher.py    Picks best adapter via can_parse() + zip auto-pick
    hy3.py           Wraps V3 parsers_hy3 → canonical Meet
club_profiles/
  swansea-uni.json   Seeded automatically; the pilot profile
data.db              SQLite index of runs (snapshotted across deploys)
runs_v4/<id>.json    Per-run audit / evidence export
```

V3 modules are unchanged.
