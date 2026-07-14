# ADR 0022 — Require operator credential rotation before go-live

- **Status:** accepted (2026-07-13); **implementation staged.** The decision —
  production must not run on the shipped default operator credential — is
  accepted. Enforcement is **deferred to pre-launch** (roadmap **RP.5**) because
  the product is still in development: during development `env_check` emits a
  production **warning**; at go-live it flips to a hard boot-refusal. When that
  hard error lands it **amends** [ADR-0019](0019-password-protect-operator-signin.md)'s
  "zero deployment config" boot property for the operator credential only.
- **Context:** the 2026-07 deep code review (finding #26) flagged that the
  operator `/developer` credential ships a baked-in default: a username plus an
  argon2id password hash committed in `web/auth.py`. ADR-0019 chose this on
  purpose so a fresh deploy works with nothing set in Render, and accepted "a
  weak operator password is the operator's own risk."

  What ADR-0019 under-weighted: **the repository is public.** The committed
  hash and username are readable by anyone on the internet, so the credential
  is **offline-crackable** — online rate-limiting does nothing against an
  attacker who pulls the hash and cracks it at leisure. ADR-0019 itself notes
  the supplied password is *short*. Public repo + short password + an
  unrestricted `PLAN_OWNER` session on success (every tenant's data, the
  commercial console, "notify all users") makes the shipped default a real
  operator-takeover path if left unrotated once real customer data is present.

## Decision

Production must not run on the shipped default operator credential **by
go-live**. The check lives in `web.env_check`, keyed off
`auth.dev_password_hash_overridden()` (the shipped default stays the single
source of truth in `auth.py`, so there is no duplicated hash to drift):

- **During development (now):** if `is_production()` and the credential is
  unrotated, `env_check` appends a **warning** — the deploy still boots. This
  keeps the in-development Render deploy working on the baked-in default (the
  product is pre-customers, so the offline-crack path exposes no real data yet)
  while making the risk impossible to silently forget.
- **At go-live (roadmap RP.5):** the warning becomes a **hard error** —
  `env_check` raises `EnvConfigError` in production unless
  `MEDIAHUB_DEV_PASSWORD_HASH` is set to a non-empty, non-default value — and
  the operator rotates the hash. This is a one-line change (`warnings.append`
  → `errors.append`) plus setting the env var.
- The **username is not secret** (per ADR-0019) and is not required to rotate —
  only the password hash.
- `render.yaml` declares `MEDIAHUB_DEV_PASSWORD_HASH` (`sync: false`) so the
  operator can set it in the dashboard; `.env.example`, the threat model
  (threat E) and the residual-risk register (`SECURITY_REPORT.md` R12) record
  it as required at launch.

## Why staged rather than enforced now

The exposure only becomes a real breach path once production holds real
customer data. Enforcing the hard boot-refusal today would break the
in-development Render deploy (it sets `RENDER`, so `is_production()` is true)
for no protective benefit while there are no customers. Deferring the hard
error to the pre-launch checklist (RP.5), alongside the repo-private flip
(RP.1–RP.4) that itself collapses most of the offline-crack exposure, is the
maintainer's chosen sequencing.

## Consequences

- No behaviour change to a fresh deploy today beyond a log warning; the online
  sign-in, hashing, and rate-limiting are untouched.
- RP.5 is the tracked, blocking pre-launch task; go-live is gated on it.
- Residual until RP.5 lands: a production deploy that reached real customers
  without rotating would carry the offline-crack risk — bounded by "no
  customers yet" during development and by the repo-private flip thereafter.

## Rejected alternatives

- **Enforce the hard error now** — strongest, but breaks the in-development
  Render deploy for no benefit while there are no customers. Deferred to RP.5.
- **Rotate-only, no boot gate ever** — relies on operator diligence; a future
  fresh deploy silently falls back to the public default. The RP.5 hard error
  removes that failure mode.
- **TOTP second factor** — strongest defence, but requires a non-public seed
  store and an enrolment flow (a real feature and a login-flow change), out of
  scope for this hardening. May be revisited separately.

## Reversal

The warning is self-contained (`dev_password_hash_overridden()` +
one branch in `env_check._problems()`); drop it to revert. Turning it into the
launch-time hard error is the RP.5 one-liner described above.
