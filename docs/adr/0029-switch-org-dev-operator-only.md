# ADR-0029 — "Switch organisation" is a dev-operator-only affordance

Date: 2026-07-12
Status: Accepted
Relates to: ADR-0028 (member-confined org access — supersedes its Decision §2
nav clause and its P4 "switcher" note), ADR-0019 (operator sign-in),
ADR-0014 (org→workspace membership binding)

## Context

ADR-0028 exposed a "Switch organisation" control to any session that could
*technically* switch: the dev operator, an anonymous pilot session, and the
rare account member holding seats in 2+ organisations. It surfaced in two
places in the chrome:

1. The active-organisation account menu (`#mh-orgmenu`) in the top nav, gated
   by a `can_switch_org` template variable computed in `_layout()`.
2. The returning-user home hero, which rendered an ungated "Switch
   organisation" secondary CTA for **every** ready pinned org — including
   single-org members and anonymous pilots, for whom it was a self-looping
   button (clicking it hit `/sign-in`, which auto-pins their only org and
   bounces straight back).

The maintainer's decision is that cross-organisation switching is an operator
capability, not a customer-facing one. Members work inside one club per
session; the switcher added surface area and confusion without a real customer
job behind it.

## Decision

Show the "Switch organisation" affordance to the **authenticated dev operator
only** (`is_dev_operator()`, ADR-0019). Concretely:

- `_layout()` no longer computes a `can_switch_org` variable at all; the
  account-menu "Switch organisation" link is gated directly on `dev_operator`.
  The member-membership-count read and the anonymous-pilot branch are removed.
- The home hero "Switch organisation" CTA is gated on `is_dev_operator()`
  (it is built in Python, not Jinja, so the gate is a Python conditional).
- The `/sign-in` picker route, `sign_in_post`, `sign_out`, `sign_in_delete`,
  the org-ready gate and its ~20 redirect sites, and the `nav.switch_org`
  string catalogue key are all **unchanged** — `/sign-in` is still the
  org-ready-gate destination and the first-org pick, and the operator still
  uses the same route to roam. Only the *advertised switch entry points* for
  non-operators are removed.
- "Leave organisation" (`/sign-out`) is untouched; this ADR is about switching
  between orgs, not leaving the current one.

## Consequences

- Single-org members and anonymous pilot sessions lose a control that did
  nothing useful for them (a no-op / looping button) — a net simplification.
- The rare multi-org member loses the *advertised* nav switcher. No access is
  lost server-side: `/sign-in`, reached directly, still renders the
  `_session_can_use_profile`-filtered picker of their own workspaces (with 2+
  profiles it skips the single-org auto-pin), and the org-ready gate still
  routes an idle-dropped session there. If a first-class multi-org switcher is
  ever wanted for customers, it is a deliberate new feature, not a regression
  to undo.
- The dev operator's cross-org workflow is unchanged.
- No route, redirect target, persisted data shape, or auth path changes; the
  `nav.switch_org` catalogue string stays (the operator nav still uses it), so
  the localisation and auth-vocabulary tests are unaffected. No migration.
