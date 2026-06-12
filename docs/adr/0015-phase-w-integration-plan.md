# ADR 0015 — Phase W (W.1–W.14) integration placement, order and scope

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** Maintainer (Council-pressure-tested per `docs/COUNCIL_GOVERNANCE.md`)

## Context

The full Phase W wedge-depth backlog (`docs/ROADMAP.md` — W.1 athlete registry
through W.14 engagement loop) was green-lit to land as one integration pass.
Several items touch the deterministic-engine boundary (new detectors W.1/W.3/W.4),
outward-facing surfaces (W.9 magic links, W.7 live polling) and a safeguarding
surface (W.2), so a full LLM Council was convened (five advisors + anonymous peer
review; transcript under `autotest/reports/council/`) on placement, build order
and scope.

Verdict in brief: the 14 items collapse into **four dependency layers** —
data spine (W.1 registry + W.2 consent, built together, consent enforced before
any athlete-linked output ships), ingestion adapters (W.5 LENEX / W.10 OCR /
W.6 entries — parallel, interpreter-seam only), detectors & engines (W.3 records,
W.4 qualifying, W.8 wraps, W.7 live mode on the scheduler seam), and output/UX
shells (W.9 magic links, W.11 alt-text, W.12 print, W.13 bilingual, W.14
telemetry). Peer review unanimously added two constraints no advisor led with:
**(a)** athlete identity must be an *optional enrichment* with null-identity
defaults so no existing fixture/test path requires a registry row, and **(b)**
the suite must be run per seam, not once at the end, with fixtures authored
before parsers (LENEX fixtures are hand-crafted to the Lenex 3.0 spec).
Volunteer-facing labels are part of correctness, not polish ("photo of printed
results", never "OCR"; "European results file (.lxf)", never bare "LENEX").

## Decision

Placement (all org-scoped under the ADR-0003/ADR-0014 invariants):

| Item | Seam | Surface |
|---|---|---|
| W.1 | new `athletes/` package; tables `athletes`/`athlete_aliases` in `data.db`; milestone detector on the V5 detector bus via precomputed `extra["athlete_milestones"]` | Athletes roster page + review-time merge |
| W.2 | new `safeguarding/` package; `athlete_consent` table; enforcement at selection (`media_library/selector.py`), rendering (initials-only), and a new publish-gate check | Consent manager page + red "blocked: no consent" states + welfare CSV export |
| W.3 | new `club_records/` package; `club_records` table; `ClubRecordDetector` ranked above PB (`_TYPE_MAGNITUDE["club_record"] = 1.1`); update-on-approval only | Records page + CSV import + records-wall block |
| W.4 | versioned datasets `data/standards/<season>/` with provenance; existing `QualifyingTimeDetector` wired via profile standards picker | Settings standards picker + "qualified" cards |
| W.5 | `interpreter/lenex_parser.py` (detect/parse; `.lxf` via `_zip_safety`); registered in sniffing + native parse | Upload (plain-language format label) |
| W.6 | LENEX `entries` + pasted/CSV entry lists pre-filling the `event_preview` stub | "Upload entry file" on the Event Preview surface |
| W.7 | `results_fetch/live_watch.py` + scheduler task type `live_meet_poll`; per-swim dedupe; cards queue-only; ntfy click-URL; auto-expire | Live meet page (create/stop watch, status) |
| W.8 | new `season_wrap/` aggregator over a workspace's runs; monthly scheduler draft through the approval queue | Season wrap page + one-click pack |
| W.9 | `web/magic_links.py` — itsdangerous signed, expiring, run-scoped, revocable tokens; mobile lite review driving the same `WorkflowStore` with audit | "Send approval link" on review + `/m/<token>` |
| W.10 | `interpreter/ocr.py` engine seam (RapidOCR/Tesseract optional, injectable for tests) behind the existing `image-needs-ocr` path; per-row uncertainty flags; honest needs-review when no engine | Upload accepts photos; flagged-rows review |
| W.11 | `alt_text` produced in the *same* caption LLM call (honest-error, no heuristic); threaded through pack ZIP, wall embeds, publish payloads | Editable alt-text beside caption in review |
| W.12 | A4 certificate/poster layouts in `graphic_renderer/layouts/`; Playwright `page.pdf`; consent-honouring batch export | "Print certificates" on the pack page |
| W.13 | `ClubProfile.language` (en/cy/bilingual); both variants from one caption call; gate length checks cover combined text | Settings language picker + dual captions in review |
| W.14 | approval telemetry table via `observability/`; recorded at the workflow seam; preference summary surfaced with explainable reasons | "What this club prefers" panel |

Build order: **W.1+W.2 spine → W.5 → W.10 → W.6 → W.3 → W.4 → W.8 → W.7 →
W.9 → W.11 → W.13 → W.12 → W.14**, with the relevant test subset run after each
seam and the full suite at the end.

**Recorded deviations from the chairman's verdict** (per §3 of the governance
doc):

1. **W.7 ships real, not as a stub.** The chairman recommended a placeholder,
   fearing partial-file parse corruption. The repo design already neutralises
   that failure mode: each poll is a *complete* tier-A fetch of a static page,
   parsed by the existing interpreter with all-or-nothing semantics (a failed
   parse poll = no new cards + an honest status, never partial rows), per-swim
   dedupe keys make carding idempotent, and output is structurally queue-only.
   Built fully deterministic and fixture-tested; the watch UI labels it clearly.
2. **W.11 alt-text stays on the LLM seam** (chairman suggested deterministic
   templating). The roadmap and the standing AI rule are explicit: judgement
   copy rides `media_ai.llm` with honest errors; templated alt-text is exactly
   the heuristic substitution the rules forbid.
3. **W.2 default-most-restrictive applies once a workspace has a consent
   regime** (≥1 consent record imported/set, or enforcement explicitly enabled).
   A blanket most-restrictive default on day zero would blank every card for
   clubs that have not adopted consent tracking yet, killing the primary flow
   the feature is meant to protect.

## Consequences

- The deterministic boundary is untouched: every new detector, parser, differ,
  aggregator and the consent/records stores are pure-deterministic; the only new
  LLM surface is the caption-call extension (alt-text + bilingual variants).
- W.2/W.12/W.11 outputs are consent-aware from birth — no retrofit risk.
- W.5/W.10 broaden the ingestion patterns P3 multi-sport spokes will reuse.
- The roadmap's Phase W rows move to IN PROGRESS/DONE as items land; each item's
  exit criterion in `docs/ROADMAP.md` is the acceptance bar for its tests.
