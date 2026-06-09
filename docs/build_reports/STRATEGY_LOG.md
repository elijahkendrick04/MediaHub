# MediaHub Strategy & Roadmap — Engine Log

Append-only log of the autonomous strategy/roadmap engine. Newest entry at the top.
The engine maintains `docs/ROADMAP.md` against a >95%-confidence-of-correctness standard
(every step evidence-backed and necessary; every figure sourced or flagged as estimate;
sequencing reflects real constraints; speculative bets quarantined, never deleted). It
edits docs only — never code, tests, infra, billing, or deploys.

---

## HANDOFF (current)

- **Integrity state:** no high-confidence-core item is known to be below standard. This
  cycle reality-checked the **binding-constraint (distribution) track**: PC.6's
  "governing-body endorsement = the single highest-leverage channel (reaches hundreds of
  clubs)" was asserted, never evidenced. Split it into **(a) evidenced, dated, open
  approved-data-API access** (Swim England's Oct-2025 approved-systems API — concrete first
  NGB action, grants *data + credibility*, **>95% step correct/available**) and **(b)
  promotional NGB endorsement → DOWN-WEIGHTED to speculative** (no evidence any NGB
  promotes a third-party content tool; partner slots category-exclusive and already held by
  SportsEngine / GoCardless). Recorded in ROADMAP §PC.6, the diligence (Evidence refresh
  cycle 3), and **ADR-0012**. PC.4 remains an evidence-gated price-discovery step; PC.3
  (true multi-tenancy) remains correctly ⚠️ BLOCKING + escalated.
- **Biggest open evidence gap:** revealed willingness-to-pay at the candidate Club tier
  (closable only by the first ~10 hand-sold clubs / real annual payments — PC.6, can't be
  closed from the desk). Secondary gap now logged: **Swim Wales** has no comparable public
  approved-supplier/endorsement programme found — do not assert one exists until verified.
- **Highest-impact next correction:** expand PC.6 into a concrete, evidence-banded
  **direct + word-of-mouth** hand-sell sequence (now the de-facto primary channel after the
  endorsement down-weight), or pressure-test **Route C** (sell/integrate with SportsEngine /
  Swim Manager / Swim Club Manager — who now hold both the NGB endorsement and the official
  data API) as the realistic distribution partner, with a current go/no-go read.
---

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
