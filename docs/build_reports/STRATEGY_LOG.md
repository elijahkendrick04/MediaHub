# MediaHub Strategy & Roadmap — Engine Log

Append-only log of the autonomous strategy/roadmap engine. Newest entry at the top.
The engine maintains `docs/ROADMAP.md` against a >95%-confidence-of-correctness standard
(every step evidence-backed and necessary; every figure sourced or flagged as estimate;
sequencing reflects real constraints; speculative bets quarantined, never deleted). It
edits docs only — never code, tests, infra, billing, or deploys.

---

## HANDOFF (current)

- **Integrity state:** no high-confidence-core item is known to be below standard. This cycle
  operationalised the now-**primary** distribution channel: after cycle 3 down-weighted
  promotional NGB endorsement (ADR-0012), **direct + word-of-mouth hand-sell** became the
  de-facto primary channel but PC.6 still described it in one asserted sentence. Expanded it
  into a **warm-first + referral funnel** with sourced base rates (cold B2B reply ~2–5% vs warm
  founder-led close ~30–50%; referrals = 20–50% of SaaS new customers / ~65% of B2B), an honest
  cold-to-paid funnel (~0.3–1.0% → ~1,000–3,000 contacts to win 10 cold = infeasible solo), and a
  realistic ~3–6+ month timeline. The >95% standard attaches to the *channel-design decision*
  (warm+referral over cold broadcast); the *outcome* stays the unproven validation. Edited
  ROADMAP §PC.6 + diligence (Evidence refresh cycle 4). No new ADR — elaboration of ADR-0012.
- **Biggest open evidence gap:** still revealed willingness-to-pay at the candidate Club tier —
  closable only by the first ~10 hand-sold clubs / real annual payments (PC.6/PC.4), not from the
  desk. Secondary desk gap unchanged: Swim Wales has no public approved-supplier/endorsement
  programme found — do not assert one exists until verified.
- **Highest-impact next correction:** a current go/no-go pressure-test of **Route C** (sell/
  integrate the content engine with SportsEngine / Swim Manager / Swim Club Manager — who now
  hold both the NGB endorsement *and* the official data API), OR convert the £150k–£400k ceiling
  + probability bands into an explicit per-horizon table tied to the warm-first funnel's realistic
  club-count trajectory.
---

## 2026-06-09 — Cycle 4 (PC.6: hand-sell funnel — direct + word-of-mouth, base-rate-grounded)

**Assessed:** full roadmap against the standard; confirmed the prior handoff's #1 queued
correction. Cycle 3 made direct + word-of-mouth the *de-facto primary* channel by down-weighting
promotional NGB endorsement — but PC.6 still specified that primary channel as a single asserted
sentence ("hand-sell the first ~10 clubs yourself"), with no funnel, channel mix, base rates, or
timeline. On the binding-constraint (distribution) track, the design of the now-primary channel
was the most load-bearing under-specified item.

**Evidence gap researched + findings (captured in `research/SCALING_DILIGENCE_2026.md`, Evidence
refresh cycle 4; current, dated, accessed 2026-06-09):** cold B2B outreach reply ~2–5% (SaaS as
low as ~1.9%), cold-email→meeting ~0.8%; warm/founder-led close ~30–50% (≈10× cold); founder
should personally close first 10–20 deals. Referral/word-of-mouth = 20–50% of new SaaS customers,
~65% of B2B new business, ~37% better retention, amplified in niche communities. Reachable
population is public but volunteer-run: Swim England ~1,200+ clubs, Swim Wales ~80–90 (~11,000
members). *(Sources: builtforb2b.com, martal.ca, justinmckelvey.com, mailshake.com, saastr.com,
thinkimpact.com, businessdasher.com, swimming.org, swimwales.org.)*

**Improvement made:** rewrote PC.6's hand-sell line into a four-part **warm-first + referral
sequence** — (i) local-warm base (Swansea/SE Wales) for the first ~3–5 clubs; (ii) a referral
engine (2 named intros per signed club) to compound 5→10; (iii) meet/event presence as warmth-
manufacture; (iv) cold outreach explicitly **capped to a supplement** with the honest ~0.3–1.0%
cold-to-paid funnel showing ~1,000–3,000 contacts would be needed to win 10 cold (infeasible
solo). Added an honest ~3–6+ month timeline and an explicit confidence split (design >95%-correct;
outcome unproven = the validation). Added a funnel-math table to the diligence.

**How it moved toward the standard:** the now-primary distribution channel is no longer asserted
in one line — it is a defensible, base-rate-grounded sequence a hard-nosed operator would keep,
with cold-broadcast (the tempting-but-wrong path) explicitly bounded by its own brutal math. The
>95% standard cleanly attaches to the *channel-design decision*; the *outcome* stays the honest
unproven validation that also closes PC.4's WTP gap. No revenue figure changed; vision unchanged;
PC.3/PC.4 untouched; auto-update stamp/activity blocks not hand-edited.

**Self-verify:** coherence ✓ (PC.6 funnel is internally consistent — local-warm + referral = the
~10; cold supplements; sequencing references real public directories + ADR-0012; no un-built
prereq); evidence ✓ (every external rate cited to a dated 2026-06-09 source and flagged ESTIMATE
when applied to MediaHub's unproven case); standard ✓ (design >95%-correct; outcome quarantined as
unproven validation); honesty ✓ (no inflated number; the cold-funnel math *lowers* apparent reach,
the honest direction; timeline flagged as estimate, not a commitment); vision ✓ (unchanged —
multi-sport, multi-tenant, human-gated content brain).

**Discipline note:** no new ADR minted — this elaborates ADR-0012's already-recorded "lean on
direct + word-of-mouth" decision rather than making a new strategic choice (avoids ADR inflation).

**Realistic revenue ceiling + probability bands (unchanged this cycle, restated honestly):**
swimming-only sustainable ≈ **£150k–£400k ARR** (most likely good outcome); **£1M+ ARR**
low-double-digit-% and only via multi-sport breadth + institutional buyers + a second person;
**£1M/month (~£12M ARR)** not realistic for a solo→small team on any evidence reviewed —
directional north star only.

**Queued next:** a current go/no-go pressure-test of Route C (SportsEngine / Swim Manager / Swim
Club Manager as distribution partners), or convert the revenue ceiling + bands into an explicit
per-horizon table tied to the warm-first funnel's realistic club-count trajectory.

## 2026-06-09 — Cycle 3 (PC.6: NGB distribution-channel reality check + re-weight)

**Assessed:** full roadmap against the standard; confirmed the prior handoff's queued
correction (reality-check the governing-body-endorsement assumption) was the highest-impact
open item. Distribution is the binding constraint, and PC.6 leaned on a national-governing-
body "endorsement or reseller arrangement" as *"the single highest-leverage channel (one
deal reaches hundreds of clubs)"* — a load-bearing claim that was **asserted, never
evidenced.**

**Evidence gap researched + findings (captured in `research/SCALING_DILIGENCE_2026.md`,
Evidence refresh cycle 3; all primary-source, dated, access 2026-06-09):**
- Swim England launched a secure **approved-systems API** (announced 1 Oct 2025) — approved
  platforms read official swim times/PBs directly from its databases; initial partners are
  the club-admin platforms Swim Club Manager + Swim Manager; it **explicitly invites
  "commercial organisations… to apply"** and is "a step towards a connected digital
  eco-system, with more to follow in 2026." → a REAL, dated NGB channel, but it grants
  **data + credibility, not promotion.** *(swimming.org)*
- **No evidence any NGB promotes/endorses a third-party CONTENT tool to member clubs.** Swim
  England partner slots are **category-exclusive and already held**: SportsEngine =
  "preferred technology supplier" (swim schools); GoCardless = "Official Payments Partner";
  corporate tier (Speedo, Sport England, SportsHotels) is sponsorship/brand, no content
  category. *(sportsengine.com, gocardless.com, swimming.org)* Swim Wales: no comparable
  public programme found — logged as unknown, not asserted.

**Improvement made:** split PC.6's "governing-body endorsement" into two mechanisms with
separate confidence — **(a)** apply for approved data-API access (concrete, evidenced,
>95%-correct first NGB action; data moat + credibility), **(b)** promotional endorsement →
**down-weighted to speculative** with the 6-month threshold kept. Reinforced **Route C**
(incumbents hold both the endorsement and the data API → realistic distribution partners).
Edited ROADMAP §PC.6 + the "highest-leverage combination" line, the diligence (inline
caveats on the three "highest-leverage channel" assertions + Evidence refresh cycle 3 with
a re-weighting table), and recorded **ADR-0012**.

**How it moved toward the standard:** the single most load-bearing *unproven* assumption on
the binding-constraint track is no longer asserted — it is split so the >95% standard
attaches to the **API-access step** (correct/available) and to the **decision to
down-weight** promotional endorsement, while the promotional upside is **quarantined as
speculative**, not deleted. No revenue figure changed; product vision unchanged; PC.3/PC.4
untouched; auto-update stamp/activity blocks not hand-edited.

**Self-verify:** coherence ✓ (PC.6 references real, dated programmes + Route C; no un-built
prereq; "highest-leverage combination" lines in ROADMAP and diligence now consistent with
the re-weight); evidence ✓ (every claim cited to a dated primary source, accessed
2026-06-09; Swim Wales gap flagged unknown, not asserted); standard ✓ (API step
>95%-correct; promotional endorsement quarantined as speculative with its low probability);
honesty ✓ (no inflated number; lowers *stated* distribution optimism, the honest
direction; outcome odds untouched); vision ✓ (unchanged — still the multi-sport,
multi-tenant, human-gated content brain).

**Realistic revenue ceiling + probability bands (unchanged this cycle, restated honestly):**
swimming-only sustainable ≈ **£150k–£400k ARR** (most likely good outcome); **£1M+ ARR**
low-double-digit-% and only via multi-sport breadth + institutional buyers + a second
person; **£1M/month (~£12M ARR)** not realistic for a solo→small team on any evidence
reviewed — directional north star only.

**Queued next:** expand PC.6 into a concrete evidence-banded direct + word-of-mouth
hand-sell sequence (now the de-facto primary channel), or a current go/no-go pressure-test
of Route C against SportsEngine / Swim Manager / Swim Club Manager.

## 2026-06-09 — Cycle 2 (PC.4: assumed reprice → evidence-gated price discovery)

**Assessed:** full roadmap against the standard; confirmed the prior handoff's queued
correction was the highest-impact open item. PC.4 named candidate prices and said
"validate, don't assume" but defined **no validation method, no buyer threshold, and no
current sourced comparator** — so the load-bearing WTP assumption was asserted, not gated.

**Evidence gap researched + findings (captured in `research/SCALING_DILIGENCE_2026.md`,
Evidence refresh cycle 2):** verified current competitor pricing directly from vendor
pages. **Gipper = $625 / $1,500 / $3,000 per year, annual-only** (gipper.com/pricing) —
exact public tiers replacing the old "$625 up to ~$3,000 quote" estimate, and confirming
the proven analog sells to budgeted schools, not volunteer clubs, on annual billing.
**Predis.ai = $19 / $40 / $212 per month** (predis.ai/pricing) — narrows the old
"$19–$249/mo" commodity band to current figures.

**Improvement made:** rewrote ROADMAP §PC.4 as an evidence gate — (1) candidate prices
flagged as a hypothesis to test, not publish; (2) explicit validation method (first ~10
hand-sold PC.6 clubs as live price discovery, recording *revealed* WTP); (3) a hard gate
(keep `/pricing` at the live honest "Pricing TBC" until ≥5 clubs pay annual prepay at a
tested price, then lock the highest cleared point); (4) a sourced, dated comparator table
(Gipper, Predis, SwimTopia, Canva Free, Swim Wales affiliation).

**How it moved toward the standard:** the single most load-bearing *unproven* assumption
on the revenue path is no longer asserted — it is fenced behind an explicit, dated,
sourced gate that a hard-nosed operator would keep. Confidence is split cleanly: the
*gating step* is >95%-confidence-correct; the *price levels* stay an unvalidated
hypothesis. No revenue figure inflated; product vision unchanged; speculative Routes A/B/C
untouched; auto-update stamp/activity blocks not hand-edited.

**Self-verify:** coherence ✓ (PC.4 references PC.6 + the live "Pricing TBC" state, both
real; no un-built prereq); evidence ✓ (Gipper/Predis verified today and cited with access
date; SwimTopia/Canva/Swim Wales cited to the diligence; price levels flagged estimate);
standard ✓ (step >95%-correct, hypothesis quarantined as such); honesty ✓ (no inflated
number; outcome odds untouched); vision ✓ (unchanged).

**Realistic revenue ceiling + probability bands (unchanged this cycle, restated honestly):**
swimming-only sustainable ≈ **£150k–£400k ARR** (most likely good outcome); **£1M+ ARR**
low-double-digit-% and only via multi-sport breadth + institutional buyers + a second
person; **£1M/month (~£12M ARR)** not realistic for a solo→small team on any evidence
reviewed — directional north star only.

**Queued next:** expand the PC.6 GTM/distribution track into a concrete evidence-banded
sequence, or reality-check the governing-body-endorsement assumption against current Swim
Wales / Swim England partner-programme terms.

## 2026-06-09 — Cycle 1 (Phase-C reality reconcile — residual consistency pass)

**Assessed:** full roadmap item-by-item against the standard, plus shipped-vs-inert
reality on `main` (git log + code grep). Found that PR #267 (merged 2026-06-09) shipped
self-serve signup + auth (`web/auth.py`: `/signup` `/login` `/logout`, bcrypt, signed
session cookie, `users.jsonl`) and Stripe billing (`web/billing.py`: Checkout + Customer
Portal + signed `/webhooks/stripe`), verified in code. During this cycle a **peer
autobuild merged PR #275** which already flipped the Phase C header (❌→🔵) and the PC.1 /
PC.2 badges (❌→✅) and added a PC.3 escalation note — so that edit was **not duplicated**.

**Residual drift this cycle fixed (the part PR #275 left inconsistent):**
- "Where we are today" still listed **"No commercial layer — zero billing, signup..."**
  under *Not yet shipped (❌)* — now false. Split into a new ✅ *Verified shipped* bullet
  (signup + auth + Stripe billing, PR #267) and a trimmed ❌ bullet covering only the
  still-missing parts (PC.3 multi-tenancy, PC.4 pricing, PC.6 GTM, zero *paying* customers
  while billing is unconfigured).
- Phase C **Goal** paragraph still said **"zero billing and zero customers"** — replaced
  with an honest build-half-closed / sell-side-open framing consistent with the badges
  PR #275 already flipped.

**Evidence gap researched + findings:** re-verified the two market-size anchors the
swimming-only revenue ceiling rests on. **USA Swimming ≈ 2,740 clubs** (2024, SwimSwam)
and **Swim England 1,200+ affiliated clubs** (swimming.org) both hold → the £150k–£400k
swimming-only cap and Routes A/B/C are unchanged. Captured with citations in
`research/SCALING_DILIGENCE_2026.md` (Evidence refresh, 2026-06-09).

**How it moved toward the standard:** the plan's "where we are today" and the Phase C
Goal are now factually correct on the binding constraint (monetisation) and internally
consistent with the badges. Honesty preserved — explicitly kept "zero paying customers /
zero revenue until keys are set"; no revenue figure inflated; speculative Routes A/B/C
untouched and still quarantined; product vision unchanged. No badge re-flipped (avoided
clobbering PR #275). Auto-update stamp/activity blocks not hand-edited.

**Self-verify:** coherence ✓ (no item depends on an un-built prereq; exit gates intact;
"Where we are today" now agrees with the Phase C badges); evidence ✓ (signup+billing
verified against merged code + git history; market anchors sourced); standard ✓ (touched
items >95%-confidence-correct; speculative tail fenced); honesty ✓ (no inflated numbers;
outcome odds untouched); vision ✓ (unchanged).

**Realistic revenue ceiling + probability bands (unchanged this cycle, restated honestly):**
- Swimming-only sustainable business: **≈ £150k–£400k ARR** — the most likely *good*
  outcome.
- **£1M+ ARR:** low-double-digit-% only, and only via multi-sport breadth *and*
  institutional buyers *and* (almost certainly) a second person.
- **£1M/month (~£12M ARR):** not realistic for a solo→small team on any evidence reviewed;
  remains a dropped goal / directional north star only.

**Queued next:** (1) PC.4 — convert assumed reprice into an evidence-gated WTP-validation
step with a sourced competitor-pricing comparator; (2) operator may close the now-redundant
branch `claude/pc-reconcile-billing-isolation-test` (its docs reconcile landed via PR #275;
it also bundled out-of-scope template/test code).
