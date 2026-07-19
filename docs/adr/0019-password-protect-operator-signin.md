# ADR 0019 — Password-protect the operator developer sign-in

- **Status:** accepted (2026-06-12) — supersedes
  [ADR-0018](0018-public-passwordless-operator-signin.md). **To be amended by
  [ADR-0022](0022-require-operator-credential-rotation.md)** (decided 2026-07-13,
  enforcement staged): because the repo is public the shipped default hash is
  offline-crackable, so at go-live the "zero deployment config" boot property
  below is dropped in production — it will refuse to boot until
  `MEDIAHUB_DEV_PASSWORD_HASH` is rotated (roadmap RP.5). During development it
  is a warning only, so this ADR's zero-config boot still holds for now.
  Everything else in this ADR stands.
- **Context:** ADR-0018 made `/developer` public and passwordless at the
  operator's request. The operator then reversed that the same day: *"password
  protect the developer login at the bottom of the page."* A specific username
  and password were supplied.

## Decision

`/developer` requires a **username + password**. A correct pair grants the
unrestricted (Owner-plan) operator session; the footer "Developer access" link
stays where it is (bottom of the home page) and now leads to a credentialed
form rather than a one-click button.

- **The password is stored only as an argon2id hash**, never as plaintext —
  the repo-secret rule (`CLAUDE.md`) covers passwords, and a plaintext
  credential in git history is a permanent leak even after removal. The hash is
  produced by the project's own `auth.hash_password` (argon2id, ASVS L2 V2.4)
  and verified with `auth.verify_password`.
- The **username is not secret** and is stored as a literal.
- Verification (`auth.verify_dev_credentials`) compares the username with
  `hmac.compare_digest` and the password against the stored hash, evaluating
  both before combining so a wrong username can't short-circuit (and time-leak)
  the slow password check. The `/developer` POST is **rate-limited**
  (`_auth_rate_limited`) so the online endpoint can't be brute-forced.
- **Zero deployment config**: the credential is baked in (as a hash), so the
  sign-in works on a fresh deploy with nothing set in Render — matching the
  operator's standing preference not to manage env vars. Optional
  `MEDIAHUB_DEV_USER` / `MEDIAHUB_DEV_PASSWORD_HASH` env vars rotate either field
  without a code change.
- `is_dev_operator()` is unchanged (the signed session cookie); the gate is at
  sign-in time.

## Consequences / residual risk

- This restores a real lock on full operator access — the public-backdoor risk
  recorded in ADR-0018 is closed.
- The supplied password is short; the protections that matter for a short
  secret are in place (slow argon2id hash + online rate-limiting + no plaintext
  in the repo), but a stronger password is recommended and is a one-liner to
  rotate (see `.env.example`). A weak operator password remains the operator's
  own risk (threat model E).
- Tests never carry the real password: `tests/test_dev_login.py` drives the
  full sign-in through a throwaway credential set via the env override, and a
  separate assertion checks the committed default is an argon2id hash, not
  plaintext.

## Rejected alternatives

- **Hardcode the plaintext password** (as literally requested) — rejected: a
  committed plaintext credential is a permanent secret leak (git history). The
  hash gives the operator the exact same login with none of that exposure.
- **Require a Render env var for the credential** — rejected: the operator does
  not want to manage env vars; the baked-in hash works with zero config, with
  env override available for rotation.
