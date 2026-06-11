# ADR 0014 — Org → workspace multi-tenancy: per-org membership binding (PC.3)

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** Operator (task instruction to complete Phase C) + Council-pressure-tested per `docs/COUNCIL_GOVERNANCE.md`

## Context

Roadmap item **PC.3** is the #1 scaling fix: single-instance-per-club rises
linearly in ops cost against fixed founder hours and collapses around 15–40
clubs, so MediaHub must run **org → workspace isolation in one shared
instance**. The remaining gap after PC.1/PC.2 (auth + Stripe, PR #267) was
binding user-account identity to org membership: today `users.jsonl` carries
no org field, **any session — even anonymous — can pin any org** via
`POST /api/organisation/active` / `/sign-in` (a bare `load_profile()`
existence check), the `/sign-in` picker lists every org, and `/organisation`
POST will load-and-edit any `profile_id` sent in the form. That is correct
for the single-instance-per-club deployment model and fatal for a shared
one. The schema touches the locked cross-tenant isolation invariant
([ADR-0003](0003-pilot-safety-invariant-lock.md): `_can_access_run` at every
run route + the auto-discovering sweep test, minors' competition data), so
per the roadmap it required Council pressure-testing and operator sign-off
before implementation. A full Council was convened (five advisors + anonymous
peer review + chairman; the chairman verified the load-bearing code claims
directly). Constraints honoured: no SQLAlchemy (jsonl ledgers are the
convention), auth stays optional when no accounts exist, Step 14 back-compat
("a club without an organisation is a standalone — today's default"), no
AGPL embedding (Postiz/Mixpost schemas were reference-only).

## Decision

**Per-org binding** (the Council's unanimous A2, with its bootstrap
amendment), not a global tenancy flip and not an env flag:

1. **An org with ≥1 ACTIVE membership is "bound" — members-only.** Pinning,
   the picker, settings edits, run stamping, and deletion all require an
   active membership (or the env-gated operator session). An org with zero
   active memberships ("unbound") behaves exactly as today, which keeps
   every pilot deployment and the existing anonymous-fixture test suite
   working unchanged. Unauthorised pin/edit attempts answer the same
   `404 unknown_profile` as a nonexistent org (anti-enumeration, mirroring
   the run-route "not found" contract).
2. **Membership is a relation, stored in its own append-only ledger** —
   `DATA_DIR/memberships.jsonl`, last-write-wins per `(email, profile_id)`,
   mirroring `users.jsonl` (no SQLAlchemy, no profile-JSON coupling). Row:
   `{email, profile_id, role: owner|member, status: active|invited|removed,
   invited_by, invited_via_profile_id, created_at, updated_at}`. The
   `invited_by`/`invited_via_profile_id` stamps are the cheap forward-compat
   instrumentation the Council kept from the Expansionist (audit + future
   referral signal) while burying the federation gold-plating.
3. **The unattended first-claim path is the invite itself — no operator gate
   in the default path.** Peer review caught that "operator gates the first
   claim" contradicts the Phase C exit gate (*zero founder involvement*).
   Resolution: (a) an org **created by a signed-in user is born bound** to
   its creator as owner; (b) for the small set of *existing* unbound pilot
   orgs, the operator pre-binds the club contact's email once as an
   `invited` owner row — the org **stays unbound (open) until that email
   signs up**, at which point the membership activates and the org binds,
   exactly when the real owner arrives. Signup auto-activates pending
   invites. The operator session remains break-glass only. Domain-match /
   bearer-token claiming was considered and rejected: at this scale no
   verifiable signal beats an operator-issued, email-keyed invite, and the
   production instance's new orgs are all born bound anyway.
4. **Entitlement stays strictly per-user (C1).** Plan checks keep reading
   the signed-in actor's plan — the Contrarian's fee-splitting abuse path
   (one paid seat reselling the product across workspaces) is exploitable
   the day inheritance ships, while volunteer-churn only bites at scale.
   Inheritance can be revisited once paying owners exist; the membership
   rows already carry the relationship data, so no migration would be
   needed.
5. **The ownerless-run blast radius is closed, by strengthening (never
   weakening) the ADR-0003 predicate.** "Ownerless legacy runs stay
   readable" was written for a single-org box; on a shared instance the
   same words would mean "readable by any signed-in stranger".
   `_can_access_run`'s ownerless branch now refuses **signed-in regular
   users** (operator and legacy anonymous sessions keep today's behaviour;
   no request context — direct unit calls — stays permissive). Owned-run
   semantics are untouched.
6. **A second invariant sweep pins the pin choke point** — peer review's
   sharpest catch: ADR-0003 sweeps run routes, but profile-*pinning*
   (`_active_profile_id()` / set-active / sign-in / settings-edit) had no
   equivalent. `tests/test_workspace_membership_invariant.py` now pins:
   bound orgs reject anonymous and non-member pins/edits/deletes and vanish
   from foreign pickers; members and the operator retain access; a removed
   membership un-pins the live session at the resolver; invite →
   signup → auto-activation binds an org without founder involvement;
   ownerless runs refuse foreign signed-in users; and legacy mode (no
   accounts, unbound orgs) behaves byte-for-byte as today.
7. **PC.4 revealed-WTP instrumentation ships with the hardening the Council
   made mandatory:** per-quote Stripe Checkout at the operator-quoted
   annual price (`price_data`, subscription mode, `mediahub_quote_id`
   metadata), with the webhook **idempotent per quote** and the recorded
   payment **verified server-side against the quoted amount** before it
   counts toward the ≥5-paid-annual pricing gate — unverified amounts are
   recorded as mismatches and excluded. `/pricing` stays "TBC" until the
   gate is met (decided in [ADR-0011](0011-commercial-reconcile-revenue-reality.md)).

## Consequences

- The Phase C commercial-readiness path is now structurally possible in one
  shared instance: signup → create workspace (born bound) → pay → publish,
  with zero founder involvement; the founder's one-time action for legacy
  pilots is issuing invites from the operator page.
- Cross-tenant exposure of an *unbound* org persists until its owner is
  invited/signs up — transitional by design (it is exactly today's
  exposure); operators should pre-bind real-club orgs promptly. Run ids
  remain 48-bit random (ADR-0003's noted defence-in-depth gap, unchanged).
- Flat-file ledgers reload per request and rely on append-only
  last-write-wins; fine at the ≤hundreds-of-clubs scale Phase C targets,
  and a known cliff (noted by peer review) with a clean later migration
  path because rows are append-only.
- `plan` checks remain honest per-actor; volunteer members of a paid
  owner's workspace see free-tier limits until entitlement inheritance is
  deliberately revisited.
