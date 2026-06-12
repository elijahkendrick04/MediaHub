# ADR 0018 — Public, passwordless operator developer sign-in

- **Status:** accepted (2026-06-12)
- **Context:** operator request. PR #412/#416 moved the home-page "Developer
  access" link into the footer, but the link only appears when
  `MEDIAHUB_DEV_KEY` (or `MEDIAHUB_DEV_OPEN`) is set in the Render dashboard —
  the deliberate env gate that kept `/developer` from being a public backdoor.
  The operator did not want to set a Render env var at all and asked to "remove
  the feature where it adds the render password and add it at the bottom." When
  warned (via `AskUserQuestion`) that this turns the unrestricted operator
  sign-in into a public, unlocked door, the operator chose **"No lock at all,
  fully public."**

## Decision

Remove the env gate on the operator developer sign-in. `/developer` is now
**always present and passwordless**: the footer "Developer access →" link
renders on the home page with no configuration, and a single click on
`/developer` grants an unrestricted (Owner-plan) operator session.

- `MEDIAHUB_DEV_KEY` and `MEDIAHUB_DEV_OPEN` are gone (auth, `env_check`,
  `render.yaml`, `.env.example`, env inventory). `MEDIAHUB_DEV_EMAIL` (cosmetic
  operator label) stays.
- `auth.is_dev_operator()` is now purely the signed session cookie; there is no
  key verification (`verify_dev_key`, `dev_login_enabled`, `dev_login_open`
  removed).
- Operator-only consoles (`/operator/commercial`, `/admin/compliance`,
  `/operator/notify-users`) are unchanged in spirit: a non-operator is sent to
  (or 404s short of) the now-public sign-in. They become reachable by anyone
  who clicks through it.

## Accepted risk

This is an **explicit, owner-accepted security regression**, recorded here so it
is never mistaken for an accident:

- Anyone who can reach the deployment can take an **unrestricted operator
  session** — full access to every tenant's runs, cards, brand kits, media and
  consent/DSR records, plus the sell-side commercial console and the
  "notify all users" channel. Multi-tenant isolation is bypassed for whoever
  signs in.
- There is **no password and no env kill-switch**. Re-gating the door is a code
  change, not a dashboard tweak.

What still holds: `_safe_next` blocks open-redirect on the sign-in, operator
logins are logged (S7), and rotating `SECRET_KEY` invalidates every outstanding
session cookie (including operator sessions). The threat model
(`docs/security/THREAT_MODEL.md`, threat E) and the incident runbook are updated
to reflect this posture.

## Rejected alternatives

- **Keep the keyed sign-in (`MEDIAHUB_DEV_KEY`)** — the secure default; the link
  appears at the bottom and only the operator with the key gets in. Rejected by
  the owner, who did not want to set any Render env var.
- **One-click toggle (`MEDIAHUB_DEV_OPEN=1`)** — passwordless but still a
  per-deployment env toggle with instant revocation. Rejected for the same
  reason (still requires touching Render).

## Reversal

Re-gating is a small, self-contained change: restore the `dev_login_enabled()`
predicate (env-backed) and the `if not dev_login_enabled(): abort(404)` guards
on `/developer` and `_require_operator`, and re-add the `MEDIAHUB_DEV_KEY` key
form + `verify_dev_key`. This ADR plus the diff that landed it are the
record to revert against.
