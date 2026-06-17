# Product Ideas Backlog — June 2026 research pass

**Status:** ideas for the maintainer to pick from — nothing here is committed to
build. Each idea was researched against (a) the current codebase, (b) the
competitive landscape, (c) the swimming/multi-sport data ecosystem, and (d)
2025–2026 platform/API feasibility. Sources are linked per claim.

**In plain words:** this is a menu, not a plan. Nineteen things MediaHub could
add next, each one checked against what competitors do, what the data and
platform rules allow, and what the code already has. The owner picks; then we
build the picks.

**How this was researched (2026-06-11):** two full codebase surveys (product
surface + integrations/tenancy inventory) and three web research passes:
competitor landscape (Gipper, Box Out, TeamUnify/SportsEngine, SwimTopia,
Pitchero, Spond, Canva…), data ecosystem (LENEX, Hy-Tek, Swim England,
qualifying times, adjacent sports), and export/AI feasibility (alt-text and
TTS costs, member-list delivery, first-party surfaces).

---

## The market context in one paragraph

The whitespace MediaHub occupies is real and verified: **no tool anywhere
ingests a results file and emits finished branded content**. Gipper
($625–$3,000/yr) and Box Out Sports ($480–$2,400/yr) make humans type every
score into templates ([gipper.com/pricing](https://www.gipper.com/pricing),
[boxoutsports.com/ai-info](https://boxoutsports.com/ai-info)); swim tools
(TeamUnify/SportsEngine Motion, SwimTopia, Swimify, SwimCloud, Meet Mobile) do
ops and data display with zero content output; Pitchero (12,000+ UK clubs) has
no graphics at all ([pitchero.com/pricing](https://www.pitchero.com/pricing)).
Nobody does meaning-detection, ranking, explainability, or safeguarding-aware
approval. Clubs tolerate roughly **£30–£100/mo** for software that demonstrably
saves volunteer hours. The ideas below either widen that moat (intelligence
layer), shorten the path to revenue (Phase C), or own distribution
(post-approval export and first-party surfaces).

---

## Summary table

| # | Idea | Theme | Effort | Depends on |
|---|---|---|---|---|
| 1 | Instant try-it demo (no signup) | Sell & onboard | M | — |
| 2 | Public club achievements page + website embed | Sell & onboard | M | (13 for consent) |
| 3 | Sponsor manager + sponsor exposure reports | Sell & onboard | M | — |
| 4 | In-product referral engine | Sell & onboard | S–M | — |
| 5 | Email digest delivery (newsletter actually sends to the club's own list) | Distribution | M | — |
| 6 | Athlete registry + milestone detection | Intelligence | M–L | — |
| 7 | Club records engine + "NEW CLUB RECORD" cards | Intelligence | M | (6 helps) |
| 8 | Season-current qualifying-time packs | Intelligence | S–M | — |
| 9 | Data-driven meet previews from entry files | Intelligence | M | (10 helps) |
| 10 | LENEX (.lef/.lxf) ingestion | Intelligence | M | — |
| 11 | Live meet mode (watch a results URL mid-gala) | Intelligence | M–L | — |
| 12 | Season wrap / monthly recap packs | Intelligence | M | (6 helps) |
| 13 | Consent & safeguarding manager | Trust & safety | M–L | (6 helps) |
| 14 | Magic-link mobile approvals | Trust & safety | M | — |
| 15 | OCR fallback for scanned PDFs | Quality | M | — |
| 16 | Auto alt-text on every export | Quality | S | — |
| 17 | PB certificates + A4 noticeboard posters | Quality | S–M | — |
| 18 | Bilingual captions (Welsh first) | Quality | S | — |
| 19 | Engagement feedback loop | Intelligence | S now, M later | — |

Effort: S ≈ a day or two · M ≈ up to a week · L ≈ multi-week. All estimates
assume the existing pipeline/renderer/scheduler seams are reused, not rebuilt.

---

## Group 1 — Sell & onboard (Phase-C aligned)

### 1. Instant try-it demo — results file in, watermarked pack out, no signup

**What:** a public "see it on your own meet" surface: a prospect drops a results
file (or clicks a bundled sample meet) and gets a 3-card watermarked preview —
cards + captions + a "why this card" explainer — with a signup CTA. Heavily
rate-limited, sandboxed into a demo workspace, no PB web-verification calls for
anonymous runs.

**Why:** PC.6 is warm hand-selling; the single most persuasive artifact is the
product doing its magic on *the club's own data* within minutes. Competitors are
demo-gated (Greenfly, Crossbar, TeamSnap ONE custom pricing) and that's a known
irritant; nobody can copy this demo because nobody ingests result files
(verified whitespace — see market context). Volunteer-tool guidance says
adoption dies on friction
([vistasocial.com](https://vistasocial.com/insights/social-media-management-tools-for-nonprofits/)).

**How it lands:** new public route + a sandboxed demo org via `web/tenancy.py`;
watermark layer in `graphic_renderer/render.py`; per-IP/day caps; sample HY3
from `samples/`. The pipeline itself is untouched.

**Risks:** abuse/cost — cap anonymous runs, skip `pb_discovery` for them, queue
behind a worker budget. Effort **M**.

### 2. Public club achievements page + website embed

**What:** a hosted, shareable per-club page of *approved* cards ("Latest from
Swansea Aquatics") plus an iframe/script embed and a per-club RSS/JSON feed for
club websites. Only cards that passed approval (and, once idea 13 exists,
consent checks) appear. Optional "powered by MediaHub" badge → referral loop.

**Why:** zero external gating — it's all first-party Flask
(feasibility report §4: RSS/embeds have no platform risk). Clubs on Pitchero/
SwimTopia already embed feeds into their sites; SwimTopia sells website embeds
([swimtopia.com](https://www.swimtopia.com/pricing/)). It also answers the
swim-parent resentment of paywalled results (Meet Mobile backlash —
[SwimSwam](https://swimswam.com/meet-mobile-begin-charging-subscription-fees-meet-results/))
by giving results back as public celebration. Every embed on a club site is a
permanent advert to visiting clubs.

**How it lands:** public blueprint with signed per-club tokens; reads
`workflow` approved states; cached card PNGs already exist on disk; RSS is a
template. Effort **M**. Safeguarding note: public pages must respect consent
flags — ship after or alongside idea 13, or launch with initials-only mode.

### 3. Sponsor manager + sponsor exposure reports

**What:** a sponsor registry per club (logo, tier, active months), automatic
sponsor-slot rotation on cards/reels (the renderer already demos a "Sponsor
Variant" — see `docs/PILOT_PLAYBOOK.md` Day 1 step 3), and a monthly per-sponsor
exposure report (cards featuring the sponsor, approved/exported this month) as a
branded PDF/HTML email the club can forward to the sponsor.

**Why:** this changes the WTP conversation (PC.4): a club that can show its
sponsor "you appeared on 14 posts this month" can *charge the sponsor* more than
MediaHub costs — the subscription becomes revenue-positive for the club.
TeamSnap ONE just added sponsor placement as a 2026 headline feature
([TeamSnap launch notes](https://teamsnapone.launchnotes.io/announcements/march-2026-new-features-enhancements));
Gipper markets sponsor graphics. Nobody reports sponsor exposure at club level.

**How it lands:** sponsor fields on `web/club_profile.py`; rotation rule in
`creative_brief`/generation; `sponsor_activation` content type already exists
(`club_platform/stubs.py`); counting from the `workflow` approval history.
Effort **M**.

### 4. In-product referral engine

**What:** referral codes per club, "2 named intros" tracking on
`/operator/commercial`, automatic reward (free month via Stripe coupon) when a
referred club pays.

**Why:** the roadmap's own INCLUDE list names a referral engine as part of the
PC.6 motion (warm-first, referral compounding is the H2 growth mechanism). Doing
it in-product instead of in a spreadsheet makes the motion run itself.

**How it lands:** follows the `commercial/wtp.py` ledger pattern;
`web/billing.py` already wraps Stripe. Effort **S–M**.

---

## Group 2 — Distribution (own the approve→export loop on first-party surfaces)

MediaHub does not publish or schedule to social channels — approved content is
reviewed by a human and then exported or downloaded for manual posting. The
distribution ideas worth owning are therefore the surfaces MediaHub controls
end-to-end: export and delivery to a club's *own* member list, and the
first-party public surfaces (the achievements wall, embed and RSS from idea 2).

### 5. Email digest delivery — make the newsletter actually send to the club's own list

**What:** the v7.3 grouped HTML newsletter already builds
(`/api/runs/<run_id>/newsletter`, `content_pack/builder.py`) but nothing can
send it. Add: club member list (CSV import + unsubscribe links), a weekly
digest job on the existing scheduler, and delivery via Resend — to the club's
*own* parent/member list, not a social platform.

**Why:** Gipper sells newsletters as a paid-tier feature
([gipper.com/pricing](https://www.gipper.com/pricing)); clubs already run parent
email lists; email to your own list needs no platform review at all. Cost is
trivial: Resend is free to 3k emails/mo, $20/mo for 50k — a 200-member weekly
digest across 50 clubs ≈ 40k/mo ([resend.com/pricing](https://resend.com/pricing)).
This also gives sponsors (idea 3) a second surface.

**How it lands:** a delivery/notify channel (alongside `notify/channels.py`),
member-list store keyed to workspace, scheduler job type, unsubscribe route.
GDPR: import implies consent capture + one-click unsubscribe. Effort **M**.

---

## Group 3 — Intelligence-layer depth (deterministic; the moat)

### 6. Athlete registry + milestone detection

**What:** a lightweight per-club athlete table (canonical name + variants,
optional ASA number, year of birth, active flag) that aggregates across runs.
On top of it, deterministic milestone detectors: first-ever swim in an event,
Nth race for the club (25th/50th/100th), first gala, "PB in every event this
meet", comeback after long absence (extends the existing `ReturnToFormDetector`).

**Why:** today there is **no athlete identity** across runs — names are matched
per-run only (`media_library` linking is name-string based). Per-athlete
celebration at scale is verified whitespace: Gipper markets "equitable
recognition" but every graphic is manual labour. The registry is also the data
spine for ideas 7, 12 and 13. Identity glitches (twins/siblings cross-matching
in PB verification — `docs/KNOWN_ISSUES.md`) get a place to be fixed by a human
once instead of every meet.

**How it lands:** new `athletes/` store in `data.db` (workspace-scoped),
back-filled from `runs_v4` snapshots; detectors join `recognition_swim/
achievements/`; review-time "is this the same swimmer?" merge UI. Effort
**M–L**. Deterministic throughout — no LLM in identity or milestone logic.

### 7. Club records engine + "NEW CLUB RECORD" cards

**What:** per-club records table (event × course × age-group × gender), seeded
by CSV import and/or accumulated from ingested meets; a deterministic
`ClubRecordDetector` that outranks PBs in the ranker; a record-wall section on
the public page (idea 2); "approaching the record" as planner fuel.

**Why:** a club record is the single highest-emotion swim moment a club can
post, and **no detector for it exists** (see `docs/DETECTOR_INVENTORY.md`).
Admin tools display records (TeamUnify et al.) but never generate content from
them. Clubs maintain these tables by hand today; importing one is a perfect
onboarding hook ("upload your records sheet, we'll guard it").

**How it lands:** records store + import UI; detector in
`recognition_swim/achievements/club_record.py`; ranker weight above PB
(deterministic engine extension — allowed, it's a new detector, not an AI
replacement). Effort **M**.

### 8. Season-current qualifying-time packs

**What:** curated, versioned JSON datasets of qualifying times — county,
regional, national — selectable per club, refreshed each season, powering
"Qualified for Counties!" cards. The `QualifyingTimeDetector` already exists
(V5 suite) and `ClubProfile.important_standards` is already a field; what's
missing is the **data**, the seasonal refresh process, and a dedicated card
archetype. Later: USA Swimming motivational times (B–AAAA) for US expansion —
official free PDFs on a fixed 4-year cycle.

**Why:** the data research rates this a **low-risk quick win**: QTs are
published as public seasonal PDFs per region/county (e.g.
[East Region 2026 QTs](https://www.eastswimming.org/wp-content/uploads/2025/11/Qualifying-Times-2026.pdf)),
times are uncopyrightable facts, and third-party aggregators
([swimming-times.com](https://swimming-times.com/qualifying-standards)) prove
demand. "Qualified for X" is a parent-shareable triumph that pure PB detection
misses.

**How it lands:** `data/standards/<season>/<region>.json` + a curation script
with provenance (source PDF URL per table); detector wiring + card archetype.
Effort **S–M** (ongoing seasonal curation is the real cost — document the
refresh runbook).

### 9. Data-driven meet previews from entry files

**What:** parse entry/psych-sheet files (Hy-Tek entries, LENEX `entries`
element, PDF psych sheets) and auto-generate the pre-meet pack: "Good luck this
weekend" cards (who's entered, which events, sessions), a squad-size stat card,
and planner entries for the meet date. The `event_preview` content type exists
today but is a *form-based* stub — a human types everything.

**Why:** it doubles content per meet (before + after) from files clubs already
possess; the README already promises meet previews as part of the wedge; the
planner (P1.3) already wants upcoming-event signals. LENEX explicitly carries
entries ([Lenex 3.0 spec](https://www.southeastswimming.org/wp-content/uploads/2015/07/Lenex_3.0_Technical_Documentation.pdf)).

**How it lands:** interpreter support for entry-shaped files (it already
type-detects results); feed `club_platform` event_preview with parsed data
instead of form input; planner signal. Effort **M**, deterministic parsing.

### 10. LENEX (.lef/.lxf) ingestion

**What:** a parser for LENEX 3.0 — the XML interchange format used by
SportSystems and European federations; `.lxf` is just a zipped `.lef` (the
bomb-safe unzip already exists in `interpreter/_zip_safety.py`).

**Why:** the data research calls this **the highest-value UK ingestion add**:
the spec is explicitly *"open and available for use by all software developers,
free of charge"* ([swimrankings wiki](https://wiki.swimrankings.net/index.php/swimrankings:Lenex)),
SportSystems exports it ([SportSystems KB](https://helpdesk.sportsys.co.uk/knowledgebase.php?article=19)),
and Swim England's own results uploader accepts exactly Hy-Tek + LENEX — so
HY3 + LENEX support means MediaHub can ingest the entire licensed-meet pipeline
upstream of Swim England. It also unlocks European clubs later, and idea 9's
entries come free.

**How it lands:** `interpreter/lenex_parser.py` + the four official example
files as test fixtures. Effort **M**. Deterministic.

### 11. Live meet mode — watch a results URL during the gala

**What:** club pastes the meet's live-results link before the gala (Hy-Tek
"Real-Time Results" static HTML on the host club's site, results.swimming.org
meet pages, swimresults.co.uk); a scheduler job polls politely; new results
are diffed, deduped, run through recognition, and **queued as cards for
approval mid-meet**, with an ntfy push: "3 new PBs in Session 2 — review now."
Day-of story content while parents are still in the building.

**Why:** today ingestion is single-shot — no watching exists. The data research
clears the legal path: Hy-Tek Real-Time pages live on **club-controlled
domains** with no Active ToS attached (LOW–MEDIUM risk with host-club consent),
and results.swimming.org is public SportSystems HTML (MEDIUM). Meet Mobile and
rankings scraping remain hard NOs — this idea deliberately uses only the safe
surfaces. Best-practice guidance tells clubs to post PBs on event day; nobody
can do it without a volunteer glued to a laptop. This is also the single most
theatrical hand-sell demo imaginable.

**How it lands:** `results_fetch` (crawl/robots logic exists) + a scheduler job
type + per-swim dedupe keys + the autonomy queue (which by design never
publishes). Effort **M–L**.

### 12. Season wrap / monthly recap packs

**What:** cross-run aggregate content: "Your club's October — 47 PBs, 12
medals, 3 club records, 5 debuts", biggest improver, end-of-season wrap pack +
reel. The v7.3 "weekend in numbers" exists for single runs; this generalises it
across the season, Spotify-Wrapped style.

**Why:** retention. A club that has accumulated a season of history inside
MediaHub faces real switching costs, and recap content lands exactly when
annual renewal (PC.4 prices annually) comes due. Content with zero new data
required — pure aggregation of what's already stored.

**How it lands:** aggregation over `runs_v4` snapshots + `data.db`; new pack
type + reel sequence; scheduler can draft it monthly via the autonomy queue.
Effort **M** (athlete registry (6) makes the numbers trustworthy).

---

## Group 4 — Trust, safety, compliance

### 13. Consent & safeguarding manager

**What:** a per-athlete consent registry — photo OK / name OK / initials-only /
do-not-feature — imported from the club's existing consent records (CSV),
enforced **deterministically** at generation and again before content is
exported; review UI shows "blocked: no consent on file"; a consent-status
export for the club's welfare officer. Defaults to most-restrictive when unknown.

**Why:** Swim England's own *Social Media Good Club Guide* tells clubs to manage
photo consent and designated-officer sign-off
([swimming.org announcement](https://www.swimming.org/swimengland/new-social-media-good-club-guide-launched/)) —
and **no content tool encodes minors' rules** (verified whitespace #10). Today
the code has only a `safe_for_minors` flag on media assets; there is no consent
ledger. This is simultaneously a trust moat for the youth-sport market, the
strongest possible §4 evidence for the Swim England API application
(`docs/commercial/SWIM_ENGLAND_API_APPLICATION.md`), and the thing that makes
idea 2's public pages safe.

**How it lands:** consent store keyed to the athlete registry (6); a new
deterministic export-time check beside the existing safeguarding rule;
generation-time name/photo redaction (initials-only rendering); audit entries.
Effort **M–L**.

### 14. Magic-link mobile approvals

**What:** tokenised, expiring review links — when a pack is ready, the
designated approver gets an ntfy push / email with a link that opens a
phone-friendly approve/edit/reject view for that run only, no login required.
HMAC-signed tokens (the app already has a signing secret; `notify/channels.py`
already supports click-URLs).

**Why:** the approval bottleneck is the head coach on a Sunday evening, not the
software. Competitor approval workflows exist only at enterprise level
(Greenfly) or generic design tools (Canva Teams) — a volunteer-shaped approval
loop is unclaimed. This also adds the defence-in-depth run-token signing that
`docs/KNOWN_ISSUES.md` flags as a residual gap.

**How it lands:** signed-token route wrapping the existing review surface in a
mobile-first lite view; scoped strictly to one run; audit who approved. Effort
**M**.

---

## Group 5 — Quality & polish

### 15. OCR fallback for scanned PDFs

**What:** when the PDF text layer is garbage (low-DPI scans) or the upload is an
image, run OCR (Tesseract or RapidOCR in the Docker image), then the normal
interpreter — with per-row confidence flags so uncertain rows go to human
review, never silent guesses.

**Why:** `docs/KNOWN_ISSUES.md` calls this out ("PDFs scanned at low DPI
silently parse to gibberish… No OCR fallback yet"); the interpreter already
marks images "needs OCR" but has no OCR. Every failed first upload during the
PC.6 hand-sell motion is a lost club — ingestion robustness is conversion-
critical, and committee secretaries *will* upload phone photos of printouts.

**How it lands:** OCR step in `interpreter/` image/PDF path + Dockerfile dep +
low-confidence row flagging (the "flag ambiguous rows" doctrine already
exists). Effort **M**. Deterministic.

### 16. Auto alt-text on every export

**What:** result-grounded alt text for every card ("Maya Patel, 50m freestyle,
31.24 — a 0.8s personal best at the Swansea Spring Open"), included in the
export ZIP, the newsletter, and the public page/embed.

**Why:** `docs/KNOWN_ISSUES.md`: "Generated images do not include alt-text."
Best practice is purpose-aware alt text under ~125 chars with human review —
which the approval gate already provides
([alt-text guidance](https://www.allaccessible.org/blog/alt-text-best-practices-2025-ai-generator)).
Cards are data-dense graphics, so alt text must restate the result, not
describe pixels — the card's structured data is already in the caption prompt,
so this **piggybacks the existing Gemini call at ~zero marginal cost**. Small
feature, real differentiator for inclusive clubs and committee approval.

**How it lands:** extend the caption generation contract with an `alt_text`
field (AI surface → `media_ai.llm`, honest-error when no provider); thread
through pack/export. Effort **S**.

### 17. PB certificates + A4 noticeboard posters

**What:** print exports: a branded A4 PB/achievement certificate per swimmer per
meet (batch ZIP), and an A4/A3 "weekend round-up" poster for the leisure-centre
noticeboard.

**Why:** parents currently DIY this with generic certificate templates
(123certificates, PosterMyWall — surfaced in the competitor research as the
existing "solution"); a certificate with the club's brand and the verified time
is exactly the artifact parents print and grandparents frame. Zero platform
dependencies; pure renderer reuse; deeply on-brand for "celebrate every kid"
(Gipper's "equitable recognition" pitch, automated for real).

**How it lands:** new A4 layout(s) in `graphic_renderer/layouts/` (Playwright
prints to PDF natively; `reportlab` already an optional dep in tests); batch
export route on the pack. Effort **S–M**.

### 18. Bilingual captions — Welsh first

**What:** per-club caption language settings: English, Cymraeg, or bilingual
(Welsh + English in one caption, the standard pattern for Welsh organisations).
Tone preserved, swim terms correct.

**Why:** the first ten clubs are being hand-sold in **Swansea / South-East
Wales** (PC.6) — bilingual posting is a visible, locally resonant differentiator
no US tool will ever bother with. Cost is negligible: the existing Gemini call
translates in-pipeline with tone preserved (dedicated MT APIs only matter at
scale — DeepL free tier is 500k chars/mo if ever needed,
[DeepL plans](https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans)).

**How it lands:** language field on `ClubProfile`; caption prompt extension +
review UI showing both variants (AI surface, honest-error rule applies). Effort
**S**.

### 19. Engagement feedback loop

**What:** record which tone variant / archetype the club picks and which cards
get approved vs rejected — per-club preference telemetry feeding the existing
caption few-shot store and `memory/`, so the planner learns each club's taste
("this club approves carousel PB cards; reels get edited down") and the next
pack is better-aimed before it's even reviewed.

**Why:** this is the compounding intelligence-layer moat — every approval makes
the next plan better, which no template tool can replicate. It needs no external
APIs at all: the signal is entirely first-party, drawn from the club's own
review decisions.

**How it lands:** approval-seam telemetry → `memory/` + `observability/`.
Effort **S**.

---

## Considered and parked (with reasons)

- **Second sport now** — gated behind Phase C (≥10 paying clubs) by the
  roadmap. Worth recording for when the gate opens: the data research reorders
  P3 by API accessibility — **Basketball England (PlayHQ public API, no auth)**
  and **cricket (official Play-Cricket club-keyed API)** are far easier first
  expansions than football (FA declined an API; official embed widgets only)
  or parkrun/athletics (anti-scraping / API programme on hold).
- **"Ask your club's data" chat** — fun showcase of `ai_core.ask_with_tools`
  over the run history, but no evidence clubs want it yet; the planner already
  answers "what should we post".
- **Multi-meet ZIP splitting, SC/LC conversion, split-time detectors, twin
  disambiguation UI** — real Known-Issues fixes, but lower product impact than
  the list above; bundle them into a robustness sprint when convenient (the
  athlete registry (6) subsumes twin disambiguation).
- **Digital signage / Canva-style template marketplace** — template-shop
  direction explicitly against product principles; signage is served by the
  public page + posters (ideas 2 and 17).

## If only five get built (maintainer's call, but a recommendation)

Phase-C logic says: pick what shortens the sale and deepens what MediaHub owns
end-to-end.

1. **#1 Instant demo** — the sales motion's sharpest tool.
2. **#13 Consent manager** (+ start **#6 athlete registry** underneath it) —
   the objection-killer for committees and the Swim England application.
3. **#5 Email digest** — immediate, review-free distribution to the club's own
   member list, with sponsor value.
4. **#8 Qualifying-time packs** — cheap, deterministic, parent-delighting
   content depth.
5. **#2 Public achievements page + embed** — a first-party distribution surface
   MediaHub owns end-to-end, no platform review, and a permanent advert to every
   visiting club.
