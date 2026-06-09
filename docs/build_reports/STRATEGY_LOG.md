# MediaHub Strategy & Roadmap — Engine Log

Append-only log of the autonomous strategy/roadmap engine. Newest entry at the top.
The engine maintains `docs/ROADMAP.md` against a >95%-confidence-of-correctness standard
(every step evidence-backed and necessary; every figure sourced or flagged as estimate;
sequencing reflects real constraints; speculative bets quarantined, never deleted). It
edits docs only — never code, tests, infra, billing, or deploys.

---

## HANDOFF (current)

- **Integrity state:** the Phase-C badge reconcile (PC.1/PC.2 → ✅, header → 🔵) already
  landed on `main` via a **peer autobuild, PR #275** (merged 2026-06-09 14:47). This cycle
  closed the **two residual consistency gaps PR #275 left behind**: the "Where we are
  today" honesty section still claimed "No commercial layer — zero billing, signup," and
  the Phase C **Goal** paragraph still said "zero billing and zero customers." Both now
  reconciled. No high-confidence-core item is now known to be below standard; PC.3 (true
  multi-tenancy) remains correctly ⚠️ BLOCKING + escalated for operator/Council sign-off.
- **Biggest open evidence gap:** willingness-to-pay by segment at the proposed PC.4 prices
  (Club £49–£99/mo annual; Federation £250+/mo) is still an unvalidated hypothesis — the
  single most load-bearing unproven assumption on the whole revenue path.
- **Highest-impact next correction:** turn PC.4 from an assumed reprice into an explicit,
  evidence-gated *"validate WTP with ≥N real buyers before locking price"* step, with a
  sourced comparator set (Gipper/FanWord/Predis/Canva current pricing).

---

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
