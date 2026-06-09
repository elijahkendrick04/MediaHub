# 11. Commercialise before generalising — reconcile the roadmap with revenue reality

- **Status:** Accepted (docs-only re-prioritisation; no code changed). Adopts the
  core sequencing conclusion of the 2026 scaling diligence: **commercialise before
  generalising.** The expansion phases (P3 multi-sport, P4 direct publishing, P5
  local-AI) are **deferred, not deleted** — gated behind a commercial track.
- **Date:** 2026-06-09
- **Deciders:** MediaHub maintainer (explicit user directive: *"strategy
  reconciliation of MediaHub's roadmap against a new diligence report… adopt its core
  sequencing conclusion: commercialise before generalising"*), grounded in the
  diligence report. Recorded as an ADR per the same precedent as
  [`0004-roadmap-rebuild-multisport-autonomy.md`](0004-roadmap-rebuild-multisport-autonomy.md)
  (maintainer decision, research-sourced).
- **Context source:** [`../research/SCALING_DILIGENCE_2026.md`](../research/SCALING_DILIGENCE_2026.md)
  (market sizing, WTP ladder, incumbent-threat read, architecture pressure-tests, and
  the staged recommendations with confidence bands), weighed against the build-side
  catalogue in [`../research/ROADMAP_RESEARCH_2026.md`](../research/ROADMAP_RESEARCH_2026.md)
  and the existing roadmap ([`../ROADMAP.md`](../ROADMAP.md)).

## On governance (why an ADR, and what is left open for the Council)

[`COUNCIL_GOVERNANCE.md`](../COUNCIL_GOVERNANCE.md) flags **pricing and other
commercial surfaces** and **hard-to-reverse outward-facing changes** as exactly the
class of decision worth a Council pressure-test. This change qualifies — so this ADR
does **two** things, deliberately separated:

1. It **records the decisions that are already made** — the *sequencing* (commercial
   gate before expansion) and the *prerequisites* (self-serve signup, billing, true
   multi-tenancy). These were a maintainer directive backed by a diligence report that
   already performed the clashing-analysis function (market math, base rates, the
   self-host tension, the three £1M+ routes with confidence bands). The maintainer
   outranks the Council; re-counciling a closed, evidence-backed directive would be the
   ceremony the governance warns dulls the mechanism.
2. It **explicitly hands the genuinely-open, expensive-to-reverse choices to the
   Council** (see *Open Council questions* below) — exact pricing, whether to cap or
   keep free self-host, whether to chase US schools, and whether/when to add a second
   person. Those are commercial-surface forks where being wrong is costly; they should
   be pressure-tested *before* they are committed to (a price page, a tier, a hire),
   and the verdict folded back here as an update.

This ADR is the durable record the governance requires; the PR links it. No transcript
artifact is owed for the parts already decided.

## Context

The current roadmap (Phase 0–5) is **100% an engineering plan**: de-risk licensing,
build the strategy brain, autonomy, more sports, direct publishing, local AI. It frames
a "content-strategy brain" ambition with **no commercial or go-to-market track** and
**no revenue-reality check**. The build/sell imbalance is the central finding of the
diligence: **~164k LOC, ~2,836 tests, zero billing, zero customers.** The report's
evidence (treated as an input to weigh, not gospel) establishes that the binding
constraint is **distribution and monetisation, not more capability**:

- **Swimming-only is mathematically capped** at ~£150k–£400k ARR (~1,300 UK&I
  affiliated clubs; ~2,740 USA Swimming clubs). £1M ARR at £30/mo needs ~2,778 paying
  clubs — more than every UK affiliated club. £1M+ requires **multi-sport breadth AND
  institutional buyers (schools/governing bodies) AND almost certainly a second
  person.** "£1M/month" (~£12M ARR) is not realistic for a solo→small team and is
  dropped as a stated goal.
- **Single-instance-per-club cannot scale** (linear ops/support per customer against
  fixed founder hours; margins collapse ~15–40 clubs). True multi-tenancy
  (org→workspace in one shared instance) + self-serve signup + Stripe billing are
  **prerequisites for any scale**, not nice-to-haves.
- **"Truly free, no hidden fees" self-host, as currently framed, cannibalises
  revenue** — it hands power users a permanent zero-revenue escape hatch. Either convert
  it to a capped lead-gen tier (no managed hosting / auto-publish / support SLA /
  multi-tenant admin) or consciously accept the lower ceiling.
- The **£30/£250 tiers are unvalidated and too low**; SMB/volunteer churn (3–7%/mo)
  makes **annual prepay essential**.
- The **incumbent-bolts-on-content threat is currently LOW** (no swim-data incumbent
  ships auto content generation today) but it is a **time advantage, not a moat**; the
  horizontal commodity (Canva/Predis/Gipper's auto-achievement graphics) is the real
  pressure on price and narrative.

All revenue figures here are **hypotheses/estimates**, not facts — see the report's own
caveats. No pre-launch solo venture can have >95% confidence of any specific ARR; the
>95% confidence attaches only to the *decisions* below.

## Decision

1. **Add a front-of-queue commercial phase to the roadmap — Phase C — Commercialise &
   Distribute (`PC`)** — that *precedes the expansion phases in priority*. It is a
   re-prioritisation and an *added* track, **not** a deletion: P0–P5 remain valid
   future work. Phase C **promotes and reconciles** existing roadmap material rather
   than inventing it: Appendix B **Step 7** (Stripe, tiers, self-serve signup), Appendix
   B **Step 14** (multi-club / Organisation→Club orchestration), and the cross-cutting
   **"Multi-tenancy: org → workspace"** item are pulled forward and referenced by their
   existing IDs.
2. **Multi-tenancy + billing + self-serve signup are PREREQUISITES** for any scale.
   The cross-cutting "Multi-tenancy: org → workspace" investment is reclassified from
   *partial / nice-to-have* to a **blocking prerequisite**, and a new **Go-to-market /
   distribution** cross-cutting row is added (governing-body endorsement, annual
   prepay, build/sell rebalance).
3. **Defer P3 (multi-sport), P4 (direct publishing) and P5 (local-AI)** behind the
   commercial gate **and** a *"≥10 clubs paying annually"* exit criterion. **P1.4
   graphics quality is kept but reframed** — finish only to the bar needed to make the
   swim wedge *sellable*; it is no longer the top priority above billing.
4. **Add explicit commercial gates:** *"a club can sign up, pay, and publish with zero
   founder involvement"* before any scaling; *"≥10 clubs paying annually"* before any
   new sport.
5. **Re-price as a hypothesis to validate** (not a fixed price): Club **£49–£99/mo
   billed annually**; Federation **£250+/mo**; annual prepay default. Every existing
   £30/£250 reference is annotated as *unvalidated — see SCALING_DILIGENCE_2026*.
6. **Resolve the free-self-host tension.** Default recommendation: convert "truly free
   self-host" into a **capped lead-gen tier** that deliberately lacks managed hosting,
   auto-publish, support SLAs and multi-tenant admin. The alternative — keep true-free
   self-host and consciously accept a materially lower revenue ceiling — is left as an
   **open Council question** (it touches the standing "no-hidden-fees" product
   principle, so it is not closed unilaterally here).
7. **Record the three credible £1M+ routes as STRATEGY NOTES, not build items** (Route
   A multi-sport UK grassroots; Route B US schools/colleges; Route C content/integration
   layer for swim-data incumbents), each with the report's confidence band, so the
   roadmap carries the revenue-reality context without committing engineering to it.

## Alternatives rejected

- **Keep building capability first (status quo: finish P1.4, then P3–P5), monetise
  later.** Rejected: the diligence's strongest, best-evidenced finding is that
  distribution — not product — kills solo ventures, and that single-instance-per-club
  makes each *new* customer cost the founder time. Adding more sports before a club can
  self-serve-pay multiplies the un-scalable surface.
- **Chase £1M / "£1M/month" head-on as the stated goal.** Rejected as not credible for
  a solo→small team on any evidence reviewed; retained instead as a low-double-digit-%
  *possibility* contingent on multi-sport + institutional buyers + a second person. Honest
  framing beats a motivating-but-false target.
- **Delete the expansion phases (P3–P5) outright** to force focus. Rejected: they are
  valid future work and code-linked (the `register_sport` seam, `results_fetch/`
  ingestion, the local-AI interfaces). Gating ≠ deleting; deletion would orphan real
  seams and the no-hidden-fees thesis.
- **Keep "truly free, no hidden fees" self-host unchanged.** Not rejected outright —
  flagged as the live tension and handed to the Council, because it collides with the
  revenue goal *and* with a standing product principle, so it deserves a deliberate
  call rather than a silent reversal.
- **Adopt the report wholesale as fact.** Rejected: figures are estimates/vendor
  self-claims (Gipper customer counts, Hudl ARR range, global club totals). The
  *sequencing conclusion* is adopted; the *numbers* are carried as hypotheses to
  validate with real buyers.

## Consequences

**Positive**
- The roadmap stops being a pure build plan and gains a commercial spine grounded in
  market math; the binding constraint (distribution/monetisation) is now visible and
  prioritised.
- The prerequisites (multi-tenancy, billing, signup) are named as blocking, so later
  scaling work cannot quietly skip them.
- Revenue expectations are honest and auditable (estimates marked as estimates; the
  un-real "£1M/month" goal retired), matching the standing "every step explainable"
  rule.

**Neutral / costs**
- Phase C uses a `PC`/`PC.n` id that mirrors the visible phase-ID + dotted-item
  convention (`P0` / `P0.1`) but, like the currently hand-run auto-refresh, is **not**
  matched by the `scripts/roadmap_autoupdate.py` directive grammar (which requires a
  digit immediately after the letters, e.g. `P0`/`P0.1`). Status badges are therefore
  hand-maintained for Phase C, exactly as the stalled auto-refresh is already done by
  hand (see the roadmap's 2026-06 automation note). No marker block was edited.
- The roadmap now carries pricing it explicitly labels *unvalidated*; this is
  deliberate (honest-error ethos) but means the price page is still an open decision.
- A standing product principle ("no hidden fees / truly-free self-host") is now in
  tension with the revenue goal and awaits a Council call.

**Deviations from the brief (recorded, not silent)**
- **ADR number.** The brief requested `docs/adr/0005-commercial-reconcile-revenue-reality.md`,
  but `0005` is already taken (`0005-autotest-governed-auto-merge.md`) and the ADR
  series runs sequentially to `0010`. To avoid a duplicate number, this ADR is filed as
  **`0011`** — the next free sequential id. Rename on request.
- **Branch.** Authored on `claude/roadmap-commercial-reconcile` (per the brief),
  branched from the current integration branch so the edits layer onto the *current*
  reconciled roadmap (Phase 2 substrate, Gen-v2 Tier A/B) rather than the older `main`
  snapshot, which would otherwise conflict.

## Open Council questions (pressure-test before committing)

These are the expensive-to-reverse, commercial-surface forks deliberately left open for
a `/llm-council` pass before they are baked into a price page, a tier, or a hire:

1. **Exact pricing.** Is Club £49–£99/mo (annual) / Federation £250+/mo right, or should
   the wedge launch higher/lower? What is the annual-prepay discount, and is there a
   founder/early-bird tier?
2. **Keep or cap free self-host.** Convert to a capped lead-gen tier (default
   recommendation) or consciously keep true-free self-host and accept the lower ceiling?
   This directly touches the standing "no-hidden-fees" principle.
3. **Pursue US schools (Route B)?** Highest WTP and the strongest math, but needs US
   sales presence and competes with funded incumbents (Gipper/FanWord/Hudl). Worth
   sequencing after UK swimming, or a distraction for a solo founder?
4. **Add a second person?** The diligence treats a second person as near-necessary for
   any £1M+ route. When, in what function (sales vs engineering), and funded how?

When a Council pass resolves any of these, fold the verdict back into this ADR (and the
roadmap) rather than leaving the question open.
