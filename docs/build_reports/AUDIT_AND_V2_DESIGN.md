# Audit + v2 design — Swansea pilot

Honest review of v1 against real Swansea data, the most important fixes
ranked by business impact, and the v2 design that addresses them.

---

## 1. Audit of v1 (what's actually wrong, not what's missing)

### What v1 got right
- Separating `Meet`, `RaceResult`, `PersonalBest`, `ClubRecord`, `QualifyingTime`, `Achievement`, `ContentItem` into distinct tables. This is the single best architectural decision and it survives v2 unchanged.
- Putting "explain why" front-and-centre in the UI. The volunteer-trust story dies without it.
- A three-pane keyboard-driven approval UI that feels like email triage rather than Excel.
- Confidence levels and a `content_worthiness` score that, in principle, can drive ranking.

### What v1 got wrong (and would fail in a real Swansea pilot)

| # | Issue | Severity | Why it would fail |
|---|---|---|---|
| 1 | **Every uploaded swimmer is auto-assigned to Swansea** (`club_id = SUS` in `app.py`). The real meet file has 700+ swimmers from ~30 clubs; only ~30 are "ours". v1 would manufacture content for opposition swimmers. | **Blocker** | Embarrassing in front of a coach. The product is dead on first run. |
| 2 | **No achievement grouping.** A single swim (Sarah's 56.42 100 free) becomes 4 separate review cards: PB, club record, BUCS QT, sub-57 barrier. Reviewing 30 swimmers' good swims = 90+ cards. | **Blocker** | The brief explicitly says "10–30 items, not 80". v1 produces 80+. |
| 3 | **Captions leak database labels** like `BUCS_LC_2025_26` into the user-facing copy. | **Major** | Looks like a bug to a non-technical user. Trust collapses. |
| 4 | **CSV-only ingestion.** Swansea Aquatics' real meet exports as Hytek `.cl2` (SDIF) and `.hy3`. v1 cannot read either. The PDF is unstructured and even messier. | **Major** | The product literally cannot ingest a real Swansea meet. |
| 5 | **Identity resolution by fuzzy name match**, ignoring the ASA member ID that's already in the HY3 file. Two swimmers called "J Smith" become one. | **Major** | Silent data corruption. PB store gets poisoned over time. |
| 6 | **PB import created gender-less event codes (`X_…`)** that didn't match meet-derived codes (`F_…`/`M_…`), so confirmed PBs were silently labelled "likely". I patched this but it shows the canonical-event abstraction is still fragile. | **Major** | Whole PB-truth story is undermined if the comparison key isn't deterministic. |
| 7 | **Online cross-reference (`crossref.py`) was the primary planned PB source.** swimmingresults.org has no public API and scraping is fragile + TOS-grey. The right canonical source is the SPORTSYSTEMS PDFs the club already exports. | **Major** | Whole layer is built on the wrong assumption. |
| 8 | **`FINAL_QUALIFICATION` flag for every final, every semi.** Ten-finalist meet ⇒ 80 noisy flags. | **Major** | This is exactly the "don't drown the user" failure mode. |
| 9 | **No "needs human confirmation" state.** Confidence is shown as stars but the UI treats a 3-star item the same as a 5-star item. | **Moderate** | The judgement layer is half-built — there's no easy way for the volunteer to escalate uncertainty back to a coach. |
| 10 | **No upload report.** After processing, the user sees a queue but no summary of what was parsed, filtered, hidden. | **Moderate** | The system works invisibly, so when it's wrong, you can't tell. |
| 11 | **Built-in barrier table is opinionated and partial.** "First sub-60" only fires for events I happened to encode. Half of Swansea's events have no barrier table. | **Moderate** | Inconsistent behaviour across events undermines trust. |
| 12 | **Multi-tenant `club` table but the upload route hardcodes club_id.** A latent bug: re-using this for any second club will route everything to Swansea. | **Moderate** | Will fail loudly the day a second club is onboarded. |
| 13 | **`detector.py` writes to `personal_best` during detection.** Detection has a side-effect on canonical state. If detection runs twice, the second run sees the just-imported time as the "previous best". | **Moderate** | Re-runs become non-deterministic. Live multi-day meet support breaks. |
| 14 | **Voice profile is hardcoded** (`SWANSEA_VOICE = {…}` in `content_gen.py`). | **Minor** | Tolerable for v1; would block multi-tenancy. |
| 15 | **Templated captions, no LLM.** OK for prototype, but three near-identical variants ("PB!", "PB alert!", "New best!") aren't real choices. | **Minor** | Acceptable for now; flag for v3. |

### The single biggest conceptual error in the v1 blueprint

The blueprint describes the intelligence layer as a chain of independent detectors (`MEDAL`, `RECORD_BROKEN`, `QT_HIT`, `BARRIER_BREAK`, …) that each emit an `Achievement`. **That model is wrong for the user.** The user does not think in achievement-types — they think in *swims*. One swim is one moment to celebrate or not. The detector should produce one **content item per swim**, with the four (or zero) reasons rolled up inside it. v2 fixes this.

---

## 2. Most important fixes, ranked by business impact

In the order I'd ship them.

1. **Club filtering at ingest time.** Every downstream layer is poisoned without it. (Issue 1)
2. **HY3 parser.** Without it the prototype can't ingest a real Swansea meet at all. (Issue 4)
3. **Identity by ASA member ID.** HY3 contains it. Use it. Demote fuzzy matching to a fallback for older/imported PBs. (Issue 5)
4. **Achievement grouping by swim.** This single change collapses 80 cards into 20–30 and makes the queue actually reviewable. (Issue 2)
5. **Real ranking that filters, not just sorts.** Items below a threshold are *hidden* from the queue and folded into "Weekend in numbers" / archive. (Issue 8)
6. **Human-language captions** with no internal labels exposed. (Issue 3)
7. **PB truth from SPORTSYSTEMS PDFs**, not online scraping. (Issue 7)
8. **Detection becomes a pure function** — never writes to canonical state. A separate post-meet job updates PBs only after the meet is finalised. (Issue 13)
9. **Upload test report** — parsed/filtered/included/hidden counts visible after every upload. (Issue 10)
10. **"Needs confirmation" state** for items below a confidence threshold. (Issue 9)

Items 11–15 are deferred — minor, or post-pilot.

---

## 3. v2 technical design (changes from v1)

### 3.1 Data model changes
- New table `team_member` mapping `swimmer_id → club_id` with `affiliation_status` ∈ {`active`, `alumni`, `inactive`}. **A swimmer is "ours" only if there's an `active` row for the selected club.** Replaces the implicit "you uploaded it, it must be ours" assumption.
- `swimmer.swim_england_id` becomes the primary join key. Names are decorative.
- New table `content_card` (replaces `content_item` as the user-visible unit) with a many-to-many link to `achievement` via `content_card_achievement`. **One swim = one card; one card has 1–N reasons.**
- `personal_best.source` extended with `'sportsystems_pdf'` (highest trust).

### 3.2 Pipeline changes

```
upload  ─► parse (HY3 / CL2 / PDF / CSV)
        ─► filter to selected club               ◄── NEW
        ─► identity resolve by ASA ID first      ◄── NEW
        ─► persist RaceResult (canonical)
        ─► detect achievements (PURE — no writes to PB store)  ◄── CHANGED
        ─► group achievements into ContentCard per swim        ◄── NEW
        ─► rank cards; threshold cards into queue / recap / archive  ◄── NEW
        ─► generate captions (no internal labels)              ◄── CHANGED
        ─► render upload report                                ◄── NEW

(separate job, only when meet status = final)
        ─► reconcile_pbs(meet_id) — updates personal_best
```

The separation between "detect" (read-only) and "reconcile" (write) is what makes live/multi-day meets safe and re-runs deterministic.

### 3.3 Ranking with a real threshold

Each `ContentCard` has a single composite score:

```
score = max(reason_score for reason in card.reasons)
       + 0.5 * sum(reason_score for reason in card.reasons[1:])  # bonus for combo
       - recency_penalty                                          # avoid spamming same name
```

Then:

```
score ≥ 70 → in approval queue (the only thing the user sees by default)
score 40–69 → folded into auto-generated "Weekend in numbers" recap
score < 40 → archived; visible only via "show low-priority items" toggle
```

This is the mechanism the brief asks for. v1 only *sorted* by score; v2 *filters* by score.

### 3.4 Reason taxonomy (v2 — tightened)

Each reason has a baseline score and an *eligibility rule* that prevents false positives.

| Reason | Baseline | Rule |
|---|---|---|
| `CLUB_RECORD` | 95 | Time beats existing club record AND record source is trusted (PDF or manual) |
| `BIG_PB` | 85 | Confirmed PB AND margin ≥ 1.0% of previous time |
| `CONFIRMED_PB` | 65 | Confirmed PB, any margin |
| `QT_FIRST_TIME_EVER` | 85 | First time ever under a major standard (BUCS / British) |
| `QT_FIRST_THIS_SEASON` | 60 | First time this season under a standard they've already hit before |
| `MEDAL_GOLD` | 70 | Place 1, in a real final (not just "made the final") |
| `MEDAL_SILVER` | 55 | Place 2 in a final |
| `MEDAL_BRONZE` | 50 | Place 3 in a final |
| `BARRIER_BREAK` | 80 | First sub-X for the swimmer, where X is a *culturally meaningful* round time for that distance/stroke (not just any round number) |
| `BIGGEST_IMPROVEMENT_OF_MEET` | 75 | Top 3 confirmed-PB margins across all club swimmers in this meet |
| `STANDOUT_VS_FIELD` | 50 | FINA points ≥ 90th percentile of this meet's club swims |
| `FINAL_QUALIFICATION` | **REMOVED as a standalone reason** | Reaching a final is now only a *bonus modifier* on a card that already has another reason. Stops 80 noisy flags. |
| `RELAY_NOTABLE` | 70 | Relay medal OR all four legs PB |

Crucially: `LIKELY_PB` is **never** a reason on its own — it gets surfaced in the upload report ("12 likely PBs need confirmation") so the volunteer can decide whether to trust them, but it doesn't pollute the queue.

### 3.5 Captions — no internal labels

Mapping from internal codes to human language is centralised:

```
BUCS_LC_2025_26   → "BUCS standard"
ENG_LC_2026       → "English national qualifying time"
WAL_LC_2026       → "Welsh national time"
CLUB_RECORD       → "club record"
BIG_PB            → "personal best"
SUB_60            → "first time under a minute"
```

The caption template never sees the code, only the phrase. This is enforced by the type signature.

### 3.6 Upload test report

After every upload, the user sees:

```
Welsh Open LC 2026 — processed
─────────────────────────────────────
Races parsed:                    412
Swimmers parsed:                 287
   ├ Swansea Uni swimmers:        24
   └ Other clubs (ignored):      263
Achievements detected:            41
Content cards generated:          22
   ├ in approval queue:           14
   └ folded into recap:            8
Confidence flags:
   ├ likely PBs (need confirm):    3
   └ historical-data gaps:         1   (Owen Hughes — no PB history)
Warnings: none
```

This is non-negotiable: the only way to debug a noisy run is to see the funnel.

### 3.7 What v2 is *not* doing

To respect your scope-fence:
- No graphic generation (still captions only)
- No LLM caption generation (still templated, slightly improved)
- No multi-club switcher (single-tenant Swansea Uni; data model is ready for it)
- No auto-posting, no live polling
- No swimmingresults.org scraping (replaced by SPORTSYSTEMS PDF importer)

---

## 4. Code changes (delivered alongside this doc)

Concrete modules added/rewritten in v2:
- `swim_content/parsers_hy3.py` — HY3 (Hytek native) parser. Captures swimmer name, ASA ID, age, gender, club code, club name, event, course, finals time, seed time, splits, place, DQ status. Deterministic, no regex slop.
- `swim_content/parsers_pb_pdf.py` — SPORTSYSTEMS Club Rankings PDF importer. Builds the canonical PB store *and* the active-roster table (every swimmer with `Ranked: Swansea Uni` is `active`).
- `swim_content/club_filter.py` — single chokepoint that decides "is this swim ours?". Used everywhere downstream.
- `swim_content/detector_v2.py` — pure-function detector. Returns `list[ContentCard]` with grouped reasons. Never writes to canonical state.
- `swim_content/ranker.py` — composite scoring + threshold-based bucketing into `queue` / `recap` / `archive`.
- `swim_content/content_gen_v2.py` — no internal labels, mapped via a phrasebook.
- `swim_content/reconcile.py` — separate post-meet job that updates `personal_best` from finalised meet data.
- Schema additions: `team_member`, `content_card`, `content_card_reason`, plus new columns on `swimmer` and `meet`.

The v1 modules remain in the codebase but are no longer wired in by the v2 app entry point. This makes the diff reviewable.

---

## 5. Definition of done — Swansea pilot v2

Pass = all of the following are true for one real Swansea Uni meet (i.e. a meet with 20+ Swansea Uni swims):

1. **Ingestion**
   - Upload the `.zip` containing `.hy3` + `.cl2` directly. App accepts it without manual conversion.
   - The upload report shows correct counts that a coach can spot-check by eye.

2. **Filtering**
   - At least 90% of in-queue cards are for Swansea Uni swimmers (allowing 10% honest miss for typo-only cases).
   - Zero opposition swimmers in the queue.

3. **Grouping**
   - One swim = one card. A swim with PB + record + QT + barrier shows as one card with four reasons stacked, not four cards.
   - Total queue length is 10–30 cards for a typical meet.

4. **PB truth**
   - Cards labelled "personal best" are based on the SPORTSYSTEMS PDF history, not entry times.
   - Cards labelled "likely PB — needs confirmation" are visually distinct and never the highest-priority item.

5. **Captions**
   - No internal label appears in any caption (`BUCS_LC_2025_26`, `M_50_FR_LC`, etc).
   - Captions read like the club's voice; volunteer can ship one approved variant unchanged.

6. **Time-to-approve**
   - A coach who has never used the system can approve or reject every queued card in under 10 minutes from a cold start.

7. **Determinism**
   - Re-running the upload on the same meet produces the same queue (no PB-store side-effects during detection).

A real coach running through this list with a real meet is the test. If any item fails, v2 isn't done.

---

## 6. What I still need from you to fully validate

| What | Why | Format |
|---|---|---|
| **Confirm pilot team** ✓ already done | Critical | — (Swansea University Swimming) |
| **Two more real meet result archives** (one short course, one open meet with smaller field) | To validate that the parser isn't fragile to one specific meet's quirks. | `.hy3` + `.cl2` ideally |
| **Current BUCS qualifying times for the relevant pool/season** | The `sample_qualifying_times.csv` in v1 is fabricated. Real BUCS standards will land cards correctly in the queue. | PDF or CSV |
| **Swansea Uni club records list, if maintained separately from PDFs** | The PDFs give "all-time best" per swimmer; the club may have a separate authoritative record list. If not, "current PDF #1 per event" is a usable proxy. | PDF, CSV, or "we don't have one" |
| **5–15 example past Instagram captions** from the Swansea Uni account, ideally for medals / PBs / records | Fine-tunes the voice. Without these, captions stay templated. | screenshots or copy-paste text |
| **Brand kit:** logo (PNG/SVG), primary + secondary colours, font name | Needed only when graphic generation lands (Milestone 2). Provide whenever convenient. | files |
| **A "ground truth" of 10–15 moments from a recent meet that the team posted about** | The single best regression test. Tells me whether the engine surfaces the same moments a human would. | list of swimmer + event + meet |

The last item is the highest-leverage thing you can give me. It converts "does this look right?" into "does this match what we actually posted?".

---

## 7. Where the v1 blueprint is overcomplicated

Saying it directly, because the brief asked me to.

- **swimmingresults.org cross-reference layer** — Wrong primary path. There's no API, scraping is fragile and TOS-questionable, and you already have the canonical export the club legitimately licenses (SPORTSYSTEMS PDFs). Demote to "fallback for missing swimmers" or remove until needed. **Cut.**
- **Live results polling for multi-day meets** — Real, but premature. Solve it when a coach actually asks for it during a multi-day meet. Until then, "re-upload at end of day" is fine. **Defer.**
- **Multi-tenant from day one** — The schema has a `club` table, fine. But everything beyond that (per-club brand kits, voice fine-tuning, club admin onboarding) is overhead. **Defer until you have a second pilot club ready to pay.**
- **FINA-points integration** — Mentioned multiple times in v1. Yes, FINA points are useful, but for v2 the simpler "place + margin + PB-or-not" signals are sufficient and explainable. **Defer.**
- **Adjacent verticals (athletics, rowing, gyms, restaurants)** — In a *blueprint*, fine. In a *prototype*, it's a distraction. Every minute spent generalising the schema for restaurants is a minute not spent making the swim engine actually correct on a Swansea meet. **Defer until the swim wedge is paid.**
- **Caption "v1, v2, v3" template variants** — They're cosmetically different but semantically the same. One good caption + an "edit" box is more honest than three faux choices. **Simplify.**
- **Confidence as a 0–1 float surfaced as 5 stars** — Pleasing, but volunteers don't recalibrate based on 4 stars vs 5. The honest UI is binary: "confirmed" or "needs confirmation". Stars are for v3 if at all. **Simplify.**

The v1 blueprint is ambitious, which is a virtue at the strategy layer. But the prototype is supposed to be the part that's deliberately *narrow*. The right move now is to throw away ~30% of v1's surface area and make the remaining 70% actually correct on real Swansea data. That's what v2 does.
