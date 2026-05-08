# Swim Content Automation — System Blueprint

**Version:** 0.1 (Swansea pilot)
**Author:** Elijah Kendrick
**Last updated:** May 2026

---

## 1. Product thesis (one paragraph)

Clubs already produce the raw material for great content every weekend — results, PBs, finals, medals, breakthroughs — but turning that raw material into branded, on-voice content takes hours of manual judgement, design and writing. The opportunity is not a template shop; it's an **intelligence layer** that ingests messy results data, separates signal from noise, ranks what's worth posting, and renders it in the club's voice and brand. Swimming is the wedge because the data is structured, achievements are measurable, and the founder has live access to a high-performance pilot environment (Swansea University Swimming).

---

## 2. The hard problem (and why it's defensible)

Anyone can build a Canva template. The defensible work is everything **before** the template:

| Layer | What it does | Why it's hard |
|---|---|---|
| **Ingestion** | Read PDFs, Hytek exports, SPORTSYSTEMS pages, HTML, spreadsheets into a clean schema | Every meet uses a different format; PDFs are layout-dependent; live results change mid-meet |
| **Identity resolution** | Match "J. Smith", "Jonny Smith", "Jonathan A Smith" to the same swimmer across sources | Names are inconsistent; club affiliations change; no canonical ID in most files |
| **Truth-of-PB** | Decide if a swim is a real PB, not just better than the entry time in the file | Entry times lie; meet "best times" can be wrong; SC vs LC; FINA-points context matters |
| **Achievement detection** | Find PBs, medals, finals, records, qualifying-time hits, barrier breaks, biggest improvements, standout relays | Requires multiple reference datasets, not just one file |
| **Content-worthiness ranking** | Decide what deserves a post, a story, a reel, or nothing | This is taste — needs heuristics + learned signal |
| **Voice & brand** | Write captions that sound like the club, not like ChatGPT | Needs few-shot examples from past posts and a brand kit |

Templates and design are commodity. **The defensible IP is the four middle rows.**

---

## 3. Architecture (high level)

```
┌──────────────────────────────────────────────────────────────────────┐
│                      USER (volunteer / coach / staff)                │
│                              ▲          ▲                            │
│                         upload         approve                       │
│                              │          │                            │
│                              ▼          │                            │
│ ┌────────────────────────────────────────────────────────────────┐  │
│ │                     APPROVAL DASHBOARD (web UI)                │  │
│ │   simple, opinionated, one-screen review + approve/reject       │  │
│ └────────────────────────────────────────────────────────────────┘  │
│                              ▲                                       │
│                              │                                       │
│ ┌────────────────────────────┴───────────────────────────────────┐   │
│ │                    CONTENT PACK ASSEMBLER                       │   │
│ │   captions • graphics • stories • reel scripts • recaps         │   │
│ │   priority + format suggestion + "why flagged" explanation      │   │
│ └────────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│ ┌────────────────────────────┴───────────────────────────────────┐   │
│ │                  ACHIEVEMENT DETECTION ENGINE                   │   │
│ │  PB · likely PB · medal · final · record · QT · barrier ·       │   │
│ │  improvement · standout · relay · team stats                    │   │
│ │  → each tagged with confidence + explanation                    │   │
│ └────────────────────────────────────────────────────────────────┘   │
│            ▲                                  ▲                      │
│ ┌──────────┴────────────┐         ┌───────────┴───────────────────┐  │
│ │  CANONICAL DATA STORE │ ◄─────► │  EXTERNAL CROSS-REFERENCE     │  │
│ │  swimmers · races ·   │         │  swimmingresults.org          │  │
│ │  PBs · records · QTs  │         │  britishswimming.org          │  │
│ │  per club, per season │         │  BUCS standards               │  │
│ │  (Postgres / SQLite)  │         │  swimrankings.net             │  │
│ └───────────────────────┘         └───────────────────────────────┘  │
│            ▲                                                         │
│ ┌──────────┴───────────────────────────────────────────────────┐     │
│ │                    INGESTION + PARSER LAYER                   │     │
│ │  PDF · Hytek (CL2/HY3) · SPORTSYSTEMS HTML · CSV · live URL   │     │
│ │  → identity resolution → normalised RaceResult schema         │     │
│ └──────────────────────────────────────────────────────────────┘     │
│            ▲                                                         │
│       UPLOAD FILE / PASTE LIVE URL                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Canonical data model

The single most important architectural decision is keeping **meet data**, **historical data**, **club records**, and **content outputs** in **separate tables** with clean foreign keys. You flagged this and you're right — it's the source of every reliability issue in v1.

### Core entities

```python
Swimmer
  id (uuid)                       # internal canonical id
  display_name                    # "Jonathan Smith"
  also_known_as []                # ["J Smith", "Jonny Smith", ...]
  date_of_birth (optional)
  gender
  club_id
  swim_england_id (optional)      # external link
  swimrankings_id (optional)      # external link

Club
  id, name, short_name, logo_url, brand (jsonb)

Meet
  id, name, venue, course (LC/SC), start_date, end_date
  source_type (pdf | hytek | sportsystems | csv | url)
  source_uri
  status (live | final)

RaceResult                        # one row per swim
  id
  meet_id
  swimmer_id
  event_code (e.g. "M50FR_LC")    # gender + distance + stroke + course
  round (heat | semi | final | timed_final)
  place
  time_centiseconds               # int, always centiseconds, never strings
  reaction_time (optional)
  splits []
  dq (bool) + dq_reason
  entry_time_centiseconds         # what the meet file said the entry was

PersonalBest                      # canonical PB store, NOT derived from one meet
  swimmer_id
  event_code
  course
  best_time_centiseconds
  best_time_date
  source ('meet' | 'imported' | 'swimmingresults.org' | 'manual')
  confidence (0–1)

ClubRecord
  club_id, event_code, course, age_band, time, holder_swimmer_id, date_set

QualifyingTime                    # BUCS, county, regional, national, intl
  standard_set (e.g. "BUCS_LC_2025_26"), event_code, course, time, gender, age_band

Achievement                       # output of detection engine
  id
  meet_id
  swimmer_id (or team)
  race_id
  type (PB | LIKELY_PB | MEDAL | FINAL | RECORD | QT_HIT | BARRIER | IMPROVEMENT | STANDOUT | RELAY)
  evidence (jsonb)                # the exact data points used
  explanation                     # human-readable: "PB by 1.2s, first sub-60"
  confidence (0–1)
  content_worthiness (0–100)      # ranked
  suggested_formats []            # [feed_post, story, reel]

ContentItem
  id
  achievement_id (or composite for recaps)
  format (feed | story | reel_script | caption | recap | newsletter)
  rendered_assets {captions, graphic_url, alt_text}
  approval_status (pending | approved | rejected | edited)
  approved_caption                # final version after human edit
```

### Why this matters

- A new meet writes only to `Meet` and `RaceResult`. It **never overwrites** PBs.
- PBs are recomputed by a separate job that reads `RaceResult` history + imported data + swimmingresults.org pulls and writes to `PersonalBest`.
- One bad meet file can never corrupt the PB store.
- Live/multi-day meets just append `RaceResult` rows; the detector re-runs as needed.
- The system can throw away a specific meet's source URL after ingestion — the canonical data is already in your DB.

---

## 5. The intelligence layer in detail

### 5.1 Identity resolution
- Within a meet: same name + club + DOB if available → same person.
- Across meets: fuzzy match (RapidFuzz) on name + DOB + gender + recent club affiliations.
- Manual override via the approval UI: "Is this the same swimmer?" prompt with confidence score.
- Once confirmed, alias is stored in `Swimmer.also_known_as` so it's never asked again.

### 5.2 PB detection (the hard one)
A swim is flagged with one of:

| Tag | Rule | Confidence |
|---|---|---|
| **CONFIRMED_PB** | We have a `PersonalBest` row sourced from `swimmingresults.org` or prior `RaceResult` history, and this time beats it | 0.95+ |
| **LIKELY_PB** | We only have entry-time / file-derived "best time" to compare against, and this time beats it | 0.6–0.85 |
| **PB_UNVERIFIABLE** | No reliable history — flag for manual confirmation | <0.5 |
| **NOT_PB** | Slower than canonical PB | n/a |

Course (LC vs SC) is **never** mixed — separate PB rows per course. The system must refuse to compare a 25m time to a 50m time.

### 5.3 Cross-reference enrichment (this is what you asked for)
On ingestion of a new meet, for each swimmer the system runs an **enrichment pass**:

1. Try to match swimmer to `swimmingresults.org` profile (Swim England ID once resolved is cached forever).
2. Pull all best times for the relevant events for that swimmer.
3. Pull the relevant **Event Rankings** position to detect "top 100 in country" type signals.
4. Cross-check against:
   - Current British / English / Welsh records
   - Current BUCS qualifying times (the right ones for Swansea)
   - National qualifying times (e.g. British Champs)
5. Cache aggressively — only re-fetch when the swimmer has a new swim.

This is the layer that lets you say things like:
> "James swam 23.45 — that's a PB by 0.3s, ranks him 47th in the country this season, and is 0.15s under the BUCS qualifying time."

without the user typing a single thing.

### 5.4 Achievement detection rules (initial taxonomy)
Every detection has: `type`, `evidence`, `explanation`, `confidence`, `content_worthiness`.

| Type | Detection | Worthiness baseline |
|---|---|---|
| MEDAL_GOLD | place=1 in final | 70 |
| MEDAL_SILVER/BRONZE | place 2/3 in final | 55 |
| RECORD_BROKEN | time < ClubRecord.time | 95 |
| QT_HIT | time ≤ QualifyingTime.time, first time hitting | 85 |
| CONFIRMED_PB | see 5.2 | 50 + bonus by margin |
| BARRIER_BREAK | first sub-60 / sub-30 / sub-2 etc. | 80 |
| BIGGEST_IMPROVEMENT_OF_MEET | rank improvements meet-wide, top 1–3 | 75 |
| FINAL_QUALIFICATION | made A/B final | 40 |
| STANDOUT_VS_FIELD | top 10% of FINA points in meet | 50 |
| RELAY_NOTABLE | medal, record, or all-PB-legs | 70 |
| TEAM_STAT | aggregate (e.g. "23 PBs across the weekend") | 60 |

The `content_worthiness` score is then adjusted by:
- recency of last post about that swimmer (avoid spamming the same name)
- meet importance (BUCS final > random open meet)
- margin of achievement (huge PB > tiny PB)
- novelty (first record this year > 10th)

This ranking is what stops the system over-posting.

### 5.5 Content-worthiness ranking → content format
A simple decision tree for v1:

```
score >= 85  →  feed post + story + reel script
score 70–84  →  feed post + story
score 55–69  →  story only
score 40–54  →  inclusion in recap/weekend-in-numbers only
score < 40   →  archived, not shown to user
```

The user can override every decision in the approval UI.

### 5.6 Voice & captions
- Embed 5–20 past posts from the club as few-shot examples.
- Caption generator gets: achievement evidence, club voice examples, brand do's/don'ts.
- Generates 2–3 caption variants per item; user picks one.
- All captions show "why flagged" inline so the volunteer learns to trust the system.

---

## 6. User experience (approval dashboard)

The interface should feel like **email triage**, not like Excel. Three columns:

```
┌────────────┬──────────────────────────────┬─────────────────┐
│  QUEUE     │   ITEM (focused)             │  APPROVE PANEL  │
│            │                              │                 │
│ 23 items   │  ★★★★★ Club record broken    │  ☐ Feed post    │
│ ▶ priority │  Sarah Jones — 100m Free     │  ☐ Story        │
│   sorted   │  56.42 (was 56.81, 2024)     │  ☐ Reel script  │
│            │                              │                 │
│ • record   │  WHY: Beat club record by    │  Caption v1 ⚪  │
│ • PB +1.2s │  0.39s. Also a PB by 0.6s.   │  Caption v2 ⚪  │
│ • barrier  │  Ranks 31st in UK this year. │  Caption v3 ⚪  │
│ • final    │                              │                 │
│ ...        │  [graphic preview]           │  [Approve all]  │
│            │                              │  [Reject]       │
└────────────┴──────────────────────────────┴─────────────────┘
```

Design rules:
- Never show raw spreadsheet rows.
- Never ask the user to interpret data — only to approve/reject/edit.
- "Why this was flagged" is always visible, never hidden in a tooltip.
- Confidence is shown as a star rating, not a 0.83 number.
- Keyboard shortcuts (A approve, R reject, E edit, J/K next/prev) so a coach can clear 30 items in 5 minutes.

---

## 7. Build sequence (recommended)

A **thin end-to-end slice first**, then deepen each module. Don't build the perfect parser before you know what the detector needs.

### Milestone 1 — *Local proof* (this is what we build today)
- CSV/Hytek-style ingestion (one format, real Swansea data)
- Canonical schema in SQLite
- Manual import of historical PBs (one CSV)
- Detection: PB, medal, barrier, biggest-improvement
- Cross-reference: swimmingresults.org lookup for one swimmer (proof of concept)
- A single-page web app: upload → review → approve. No graphics yet, just captions.

### Milestone 2 — *Pilot at Swansea*
- Add PDF + SPORTSYSTEMS HTML ingestion
- Add club records & BUCS QTs
- Add brand kit + 1 graphic template
- Voice fine-tuning from past Swansea posts
- Run on one real BUCS / open meet end-to-end with a coach approving

### Milestone 3 — *Multi-club*
- Multi-tenancy
- Brand kit per club
- Live results polling for multi-day meets
- Robust identity resolution across clubs

### Milestone 4 — *Productisation*
- Hosted SaaS
- Self-serve onboarding
- Pricing tiers (per meet, per month, per swimmer)

### Milestone 5 — *Adjacent sports / verticals*
- Generalise schema: `Event` instead of swim-specific entities
- Athletics, rowing, triathlon as next wedges (similar structured-data shape)
- Then: gyms, leisure centres, restaurants, estate agents — each with their own ingestion adapter but the same intelligence/voice/brand engine underneath.

---

## 8. Risks and how to mitigate them

| Risk | Mitigation |
|---|---|
| Bad PB labelling damages trust | Confidence levels, never auto-publish, show "why flagged" |
| Format brittleness (new meet breaks parser) | Adapter pattern + golden-file regression tests per format |
| One club's edge cases bleed into product | Multi-tenant from day 1; no per-club code branches |
| Voice sounds robotic | Few-shot from real club posts + human edit step always |
| Live meet results change mid-weekend | Idempotent ingestion; achievements re-derived, not stored as final until meet status=final |
| Swim England / swimrankings TOS for scraping | Cache aggressively, identify the bot, respect rate limits, prefer official data feeds where they exist |
| Founder bottleneck (you doing manual fixes) | Every manual fix becomes a test case → regression suite |
| Spreadsheet temptation | Spreadsheets allowed for *internal* debugging only, never as the user-facing surface |

---

## 9. What we are NOT building

- A scheduler / auto-poster (out of scope until trust is earned)
- A full design tool (Canva is fine; we render templates)
- A CRM / club management system
- An analytics dashboard for coaches (different product)
- A swimmer-facing app

---

## 10. Definition of done for the prototype (Milestone 1)

A volunteer at Swansea can:
1. Drop a results file in the browser.
2. See a list of 10–30 detected achievements, ranked, with explanations.
3. See 2–3 caption options per item, in Swansea's voice.
4. Approve / reject / edit in under 10 minutes.
5. Export the approved content pack as a zip (captions + per-item JSON for now).

If that workflow takes under 10 minutes for a typical meet, the thesis is validated.
