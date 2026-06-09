# 12. NGB distribution channel — reality-check and re-weight "governing-body endorsement"

- **Status:** Accepted (docs-only; strategy re-weighting, no code changed). Splits the
  previously-conflated "governing-body endorsement or reseller arrangement" into two
  mechanisms with very different evidence, and re-weights them accordingly. Does **not**
  change the product vision, the revenue-ceiling math, or Routes A/B/C.
- **Date:** 2026-06-09
- **Deciders:** MediaHub autonomous strategy/roadmap engine, on dated primary-source
  evidence (Swim England), per the same research-sourced ADR precedent as
  [`0011`](0011-commercial-reconcile-revenue-reality.md). No outward-facing or
  hard-to-reverse action is taken (no application sent, no spend), so no Council
  pressure-test is owed; this ADR is the durable record of the re-weighting.
- **Context source:** [`../research/SCALING_DILIGENCE_2026.md`](../research/SCALING_DILIGENCE_2026.md)
  — *Evidence refresh — cycle 3 (NGB distribution-channel reality check)*.

## Context

The 2026 scaling diligence and roadmap §PC.6 named a national-governing-body (NGB)
"endorsement or reseller arrangement" as *"the single highest-leverage channel (one deal
reaches hundreds of clubs)."* Distribution is the binding constraint on the whole plan, so
this was the most load-bearing **unproven** assumption on the revenue path — asserted, but
never checked against how NGBs actually work with software vendors.

A dated reality-check of Swim England (the largest UK&I home nation, ~1,200+ affiliated
clubs) found two distinct mechanisms that the prior framing had merged:

1. **An official approved-systems data API** (announced 1 Oct 2025) that lets *approved*
   platforms read official swim times/PBs directly from Swim England's databases. Initial
   partners are the club-admin platforms Swim Club Manager and Swim Manager; the
   announcement explicitly invites *"commercial organisations interested in benefiting from
   the Swim England API"* to apply, and frames it as a step toward a "connected digital
   eco-system, with more to follow in 2026." This is **real, dated, and open** — but it
   grants **data + credibility, not promotion.**
2. **A promotional/endorsement relationship** that would push a vendor's product to member
   clubs. **No evidence any NGB does this for a third-party content tool.** Swim England's
   partner slots are **category-exclusive and already held** (SportsEngine = "preferred
   technology supplier" for swim schools; GoCardless = "Official Payments Partner"); the
   corporate-partner tier (Speedo, Sport England, SportsHotels) is sponsorship-based and
   brand-led, with no content/social category and no route found for a solo vendor to be
   endorsed to all clubs. Swim Wales: no comparable public programme found this cycle.

## Decision

1. **Split PC.6's "governing-body endorsement" into two mechanisms** with separate
   confidence, in both ROADMAP §PC.6 and the diligence:
   - **(a) Apply for approved data-API access** — the concrete, evidenced first NGB action.
     Strengthens the deterministic data moat + credibility. **>95% this step is
     correct/available.**
   - **(b) Promotional NGB endorsement to hundreds of clubs** — **down-weighted to
     speculative.** Keep the existing 6-month threshold; do **not** plan around it as the
     primary distribution channel.
2. **Reinforce Route C** (integration/content layer for swim-data incumbents): the
   incumbents who already hold the NGB partner endorsement *and* (now) the official data
   integration are the realistic distribution partners — raising Route C's relative
   attractiveness versus a direct NGB content endorsement.
3. **Quarantine, don't delete, the promotional-endorsement upside** — it remains a labelled
   speculative possibility with its real (low) probability, per the standing
   speculation-quarantine rule.

## Alternatives rejected

- **Keep "endorsement = the single highest-leverage channel" unchanged.** Rejected: it is
  asserted, not evidenced, and the dated evidence shows the promotional form is not offered
  to third-party content tools. Leaving it would keep a load-bearing optimism in the
  binding-constraint track.
- **Delete the governing-body channel entirely.** Rejected: the *data-API* mechanism is
  real, dated, and valuable (moat + credibility), and the promotional upside is a genuine
  low-probability possibility worth quarantining rather than erasing.

## Consequences

**Positive** — the distribution track no longer rests on an unevidenced "reaches hundreds
of clubs" claim; the first NGB action is now a concrete, available, evidenced step; Route C
is correctly strengthened.

**Neutral / costs** — this is a re-weighting, not new build work. No revenue figure changed;
the £150k–£400k swimming-only ceiling and Routes A/B/C are unchanged. The promotional
upside is now explicitly speculative, which lowers the *stated* (never-proven) distribution
optimism — the honest direction.

**Open** — actually applying for Swim England approved API access, and verifying any Swim
Wales mechanism, are real-world actions for the maintainer; this ADR only re-weights the
plan, it does not take them.
