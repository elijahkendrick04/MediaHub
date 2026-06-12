# ADR-0015 — Compliance-readiness ("lawful-to-sell") gate on Phase C

- **Status:** accepted (maintainer-instructed audit, 2026-06-12)
- **Date:** 2026-06-12
- **Relates to:** [ADR-0011](0011-commercial-reconcile-revenue-reality.md)
  (commercialise-first), [ADR-0003](0003-pilot-safety-invariant-lock.md)
  (isolation invariant), [ADR-0014](0014-org-workspace-multitenancy-schema.md)
  (multi-tenancy), `docs/ROADMAP.md` Phase C

## Context — how the roadmap came to say "go sell" with no compliance in place

By 2026-06-11 the roadmap declared Phase C's build side "fully closed" and framed
everything remaining as founder selling work ("code can no longer be the excuse").
A maintainer-instructed audit on 2026-06-12 found that, at that moment, the
product had:

- **no Terms of Service** and **no Privacy Notice** — the existing `/privacy`
  route is a data-inventory/delete tool, not a policy;
- **no acceptance of any terms at signup** (`web/auth.py` records email +
  password hash, nothing else);
- **no Data Processing Agreement** for clubs, although MediaHub is a processor
  of personal data that is largely **children's** (names, ages, race
  performance, photos), with that data also sent to Gemini/Anthropic in prompts
  and stored on Render in the US — no subprocessor register, no transfer
  disclosures, no ICO registration tracked anywhere;
- **no account or org deletion, no data export, no retention schedule** beyond
  per-run delete and the 24-hour demo sweep;
- **no transactional email at all** — therefore no password reset, no working
  member-invite delivery, and no channel to notify users of a breach (the ICO's
  72-hour clock);
- **no backup/restore story** beyond the single 1 GB Render disk holding
  `users.jsonl`, the payment/WTP ledgers, and every run.

### Root cause

This was not one missed item; every input channel that composes the roadmap was
framed to optimise either *capability* or *revenue*, and none asked "what must
be true before a UK business processes children's data for money?":

1. **Phase C was born from a revenue diligence.** `SCALING_DILIGENCE_2026`
   asked "what is the binding constraint on growth?" and answered
   "distribution and monetisation" — so Phase C's ten items are all revenue
   mechanics (signup, billing, tenancy, pricing, GTM, referral, demo, sponsors,
   wall). GDPR appears in the diligence exactly once, as a risk to a *data
   acquisition tactic* (scraping minors' results → prefer the official API),
   and that is the only form in which it reached the plan (PC.6(a)).
2. **Safeguarding/consent arrived through the product-ideas channel** (idea
   #16) and was therefore classified as a *sellable feature* — W.2, in the
   explicitly optional Phase W pick-list ("pull an item whenever it helps win
   or keep a club") — rather than as an operating prerequisite.
3. **The exit gates were purely commercial.** "A club can sign up, pay, and
   publish with zero founder involvement" and "≥10 clubs paying annually"
   contain no lawfulness condition, so nothing structural ever forced
   compliance into the critical path, and each completed build item ratcheted
   the pressure toward selling.
4. **The engineering-shaped half of compliance did ship** — ADR-0003 isolation,
   the publish-gate safeguarding rule, initials-first on the public wall,
   session hardening, honest-error billing — because code review and the
   security focus in `CLAUDE.md` own those. The document/contract/registration
   half (terms, privacy notice, DPA, ICO fee, breach process) is not visible to
   code review, the Council pressure-tests architecture and pricing, the
   roadmap engine's daily scan watches competitors and platform policies — so
   it had **no owning channel** and silently fell through.

The lesson is systemic: a roadmap assembled only from "what blocks revenue?"
and "what could we build?" will always route around obligations that are
neither features nor growth levers. The fix must be a *gate*, not a backlog
item, or the same pressure that produced "code can no longer be the excuse"
will defer it again.

## Decision

1. **Phase C gains a third hard exit gate — compliance-readiness ("lawful to
   sell"):** no paid contract before *(a)* versioned Terms + Privacy Notice are
   live and accepted at signup, *(b)* a club DPA exists with recorded per-org
   acceptance, *(c)* ICO registration is done, *(d)* the minors' consent gate
   enforces at generation, on the public wall, and in the publish gate,
   *(e)* account/org deletion and org data export work end-to-end, and
   *(f)* password reset, breach-notification capability, and a verified
   (restored-once) backup exist. Gates 1–2 (commercial-readiness, traction)
   are unchanged. Selling may be *prepared* in parallel — warm conversations,
   the NGB application, demos, even quotes in the PC.4 ledger — but a quote
   may not convert to payment until gate 3 holds.
2. **Four new Phase C items implement the gate:** **PC.11** legal & privacy
   pack (ToS, Privacy Notice, DPA, subprocessor register + transfer
   disclosures, signup acceptance, ICO checklist); **PC.12** minors' consent &
   safeguarding gate (**W.2 promoted from optional to load-bearing**, plus a
   Children's-Code pass on public surfaces; a name-keyed minimal ledger is
   acceptable ahead of W.1's registry); **PC.13** data lifecycle & rights
   (deletion, export, retention); **PC.14** operational trust pack
   (transactional-email seam → password reset / invites / breach notice,
   backups + rehearsed restore, support contact + incident runbook, VAT/invoice
   hygiene).
3. **Standing-context rule added to the roadmap:** *lawful-to-sell before
   sold* — so future roadmap rewrites inherit the gate rather than
   re-deriving Phase C from revenue inputs alone.

## Consequences

- The "build side complete" claim is withdrawn; Phase C's heading reflects the
  reopened build-out. The realistic effect on the PC.6 timeline is small —
  the warm-first funnel was already estimated at ~3–6+ months, and PC.11–PC.14
  are days-to-weeks of work that can run while early conversations happen.
- The drafted Swim England application's safeguarding evidence becomes true in
  code (PC.12) before submission benefits from it.
- Two founder actions cannot be closed by code and are tracked on
  `/operator/commercial`: ICO registration, and professional review of the
  legal documents before the first paid contract.
- Guard tests pin the gate where code can: subprocessor register vs the
  dependency/env surface, deletion completeness under the ADR-0003/0014
  invariants, retention schedule vs scheduler behaviour.
