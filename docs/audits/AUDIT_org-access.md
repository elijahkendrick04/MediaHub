# Audit — Organisation access control and the sign-in experience

Scope: the first-run "create my organisation" page, sign in, sign out, and how
organisation access is enforced. Mode: AUDIT + FIX + CHANGE. Branch:
`claude/mediahub-org-access-control-b1zm6z` (the session's designated branch;
Hard Rule 1 named `audit/org-access`, but the session's own branch directive
pins this branch, so all work landed here and the commit subjects carry the
`[org-access]` label the rule asked for).

Author: senior-engineer session, 2026-07-10.

---

## 1. Current behaviour (Phase 0 baseline, before any change)

MediaHub has **two distinct identities per session**, which is the crux of the
whole area:

- **Account identity** (`auth.py`, PC.1): email + password, stored in
  `DATA_DIR/users.jsonl` (argon2id hashes). Session key `user_email`. Routes:
  `/signup`, `/login`, `/login/2fa`, `/logout`, `/password/forgot`,
  `/account/*`.
- **Active organisation pin** (the "which club's brand is live"): session key
  `active_profile_id`, set only by pinning through `/sign-in` (the picker),
  `POST /api/organisation/active`, or saving org setup. Read through the single
  choke point `_active_profile_id()`, which self-heals (drops the pin on idle
  timeout, on a deleted profile, or when `_session_can_use_profile` fails).

**How sign in / sign out worked.** `/login` authenticates the account, rotates
the session (`session.clear()` then `login_user`), then redirected to
`/make`. Because a brand-new session has no org pinned, `/make` tripped the
org-ready gate and bounced to `/sign-in` — **the picker** — where the member
chose a club. `/logout` answered **GET or POST**, called `logout_user()`
(which popped only the account + dev keys, leaving `active_profile_id` in the
session), and redirected home. `/sign-out` (a separate control) cleared just
the org pin. Session stored: `user_email`, `active_profile_id`,
`login_seen_at`, `_csrf`, `terms_ok_version`, plus 2FA scratch keys.

**How organisation selection worked.** The `/sign-in` picker listed every
saved `ClubProfile` filtered by `_session_can_use_profile(pid)`. That predicate
(ADR-0014): a **bound** org (≥1 active membership) is members-only (or dev
operator); an **unbound** org (zero active memberships — the pilot/standalone
mode) was **open to any session, signed-in or anonymous**. So a signed-in
member could see, pin, and edit *any unbound org*, not just their own.

**How the developer role is authenticated (stated plainly).** The dev operator
is the only role that reaches more than one organisation. It is gated by a
**username + password sign-in at `/developer`** (ADR-0019): the username is
compared with `hmac.compare_digest`, the password verified against a stored
**argon2id hash** (never plaintext), the endpoint is rate-limited, and both
fields are evaluated before combining so a wrong username can't time-leak the
password check. A correct pair sets `session["dev_operator"] = True`;
`is_dev_operator()` read that cookie flag. **There is no route or env setting
that grants organisation-wide access without this authenticated sign-in**
(the earlier passwordless `/developer` of ADR-0018 was reverted by ADR-0019).
So P2 held at baseline — verified directly against the code, early.

**Membership data model (P4).** `memberships.jsonl` is an append-only ledger,
last-write-wins per `(email, profile_id)`, rows `{email, profile_id, role,
status, ...}`. **A single email CAN hold seats in several organisations** —
nothing constrains it to one. So "land directly on their club" needed a
defined multi-org rule (see §9).

**Org-scoped routes and their entitlement checks.** Run-scoped routes gate on
`_can_access_run(run_id, run_data, _active_profile_id())` (regression-locked by
`test_run_route_isolation_invariant.py`). Profile-scoped surfaces derive data
from the pinned `_active_profile_id()`, whose self-heal is the entitlement
check. Members/settings/delete gate on `_session_can_use_profile` /
`_session_owns_profile`. The full 484-route sweep (§3, item 5) confirmed the
per-route checks are present, with two genuine exceptions found and fixed (the
`/api/visual` pair).

**The create-organisation page.** `GET /organisation/setup` renders AI-capture
and manual-build forms. `POST /organisation/setup/manual` and
`.../capture` validate `display_name` (required), slug it to a `profile_id`,
suffix `-<uuid6>` on a genuine slug collision with a different org, require the
DPA + lawful-basis attestation (`_require_org_data_attestation`), save the
profile, and — for a signed-in creator — bind them as owner
(`_bind_creator_if_signed_in`, ADR-0014) before pinning. Colours are validated
`#rrggbb` and dropped if invalid; nothing is invented.

---

## 2. Environment

- Ran the Flask app locally via `python -m mediahub.web` on `PORT=5058`
  (an earlier pass used 5057), `DATA_DIR` pointed at a scratch dir, dummy
  `SECRET_KEY`, no provider keys (AI surfaces honest-error, which is fine —
  no flow here needs the LLM). Dev credentials supplied as
  `MEDIAHUB_DEV_USER=devtest` + a throwaway `MEDIAHUB_DEV_PASSWORD_HASH`
  (argon2id of a local-only password); **no real keys or secrets used**.
- Deps: `pip install -r requirements.txt` + `pip install -e .`; Playwright
  drove Chromium from the prebaked `/opt/pw-browsers/chromium`.
- Test accounts created: `member-a@alpha.test` (owner of bound `alpha-sc`),
  `member-b@beta.test` (owner of bound `beta-sc`), an unbound pilot org
  `gamma-open`, and the `devtest` operator credential — so a member could be
  confined to their own org while the operator moves between all three.
- Tests run with `python -m pytest` (pytest reinstalled after a mid-session
  container refresh, see §12).

---

## 3. Verification matrix

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Create-org: valid creation links creator; invalid/missing rejected; duplicates clean; no half-created state | PASS | Manual create binds creator as owner (`test_workspace_membership_invariant.py::TestCreationBinding`); empty name → redirect to setup; duplicate name from a second account gets a distinct `-<uuid6>` slug, never hijacks the first (live check + `test_organisation_setup_manual.py`) |
| 2 | Sign in: valid succeeds; invalid fails without revealing account existence; correct destination | PASS | Wrong password and unknown email both return 401 "Incorrect email or password." (identical); valid login → `/make` on the member's own org. Live verify §Phase 4 |
| 3 | Sign out: server session cleared; back button / stale cookie don't restore; protected page → sign-in | PASS (now) | `POST /logout` clears whole session + bumps `session_epoch`; replayed pre-logout cookie reports signed-out and `/account/2fa` bounces to `/sign-in`; `test_authn_hardening.py::test_replayed_prelogout_cookie_is_dead` |
| 4 | Post-sign-in routing (NEW): member lands directly on own org, no picker; each member to the correct org | PASS | `member-a`→`alpha-sc`, `member-b`→`beta-sc`; `/sign-in` 302→`/make` for a single-org member; `test_..._invariant.py::test_single_org_member_skips_the_picker_entirely`, `test_authn_hardening.py::test_login_lands_member_directly_on_their_org` |
| 5 | Cross-org access refused at page AND data endpoint (P1) | PASS (2 fixed) | 484-route sweep read each org-scoped handler; all gated except the `/api/visual` pair (Finding F1, now fixed + tested). Data-level tests: `test_cross_tenant_access.py` (incl. new `TestVisualSidecarTenantScoped`), `test_run_route_isolation_invariant.py` |
| 6 | Developer access (A3, P2): signed-in dev opens any org; non-dev and signed-out cannot; no unauthenticated org-wide route | PASS | Dev pins alpha/beta/gamma all 200; member pin of another org 404; `/developer` is username+password (ADR-0019); `test_dev_login.py`, `test_operator_commercial_routes.py` |
| 7 | Membership model (P4): can a user belong to >1 org? landing well-defined | PASS (documented) | Yes — multi-org is possible; landing rule defined and flagged (§9); `test_multi_org_member_picker_lists_only_their_orgs` |
| 8 | Sessions & forms (P3): cookie flags; CSRF on sign-in/out forms; session id refreshed at org-bind; no secret leakage | PASS | `HttpOnly; SameSite=Lax` (Secure when HTTPS); login/logout/sign-out POSTs 403 without CSRF token; `session.clear()` + `login_user` refresh the signed cookie and stamp the epoch at bind; no secrets in any response |
| 9 | Server-side error handling: no unhandled 500s, no stack traces, correct codes, clear messages | PASS | Invalid login 401, no-CSRF 403, cross-org 404, unknown route handling intact; smoke of `/help`, `/healthz`, `/privacy` all 200 |
| 10 | Responsive & a11y basics on these pages | PASS | No horizontal overflow at 375px on `/login`, `/sign-in`, `/organisation/setup`; 0 unlabeled fields on login/signup/developer/org-setup after the label fixes; visible focus present |
| 11 | Copy quality: clear, consistent, British English; no placeholder/debug/TODO | PASS | Confirmation pages and messages in British English, plain hyphens; no TODO/debug strings surfaced |

Cross-organisation and developer-access results called out explicitly:
**a member's request for another organisation (page or the `/api/organisation/active`
data endpoint) returns 404, never the data; a signed-in developer moves freely
between all organisations; a non-developer and a signed-out user cannot.**

---

## 4. The design chosen, and why

The task's core insight is that hiding the picker is not the job — keeping each
member's access on the server is. I made `_session_can_use_profile` the single
authority and **tightened it**: a signed-in account may use only orgs it is an
ACTIVE member of; the dev operator may use any; an anonymous session keeps the
ADR-0014 pilot behaviour (unbound open, bound invisible). This extends
ADR-0014's own "refuse signed-in foreign accounts on ownerless runs" rule from
run routes to the pinning choke point, so it is consistent with the existing
model rather than a new one. Because every org-scoped surface already resolves
through `_active_profile_id()` (which calls this predicate) or `_can_access_run`,
one change closes the roaming gap everywhere at once. Direct landing is then a
thin layer: `_auto_pin_member_org()` pins the member's own org at login /
signup, and `/sign-in` redirects a single-org member straight through — the
picker only survives for the genuinely multi-org member and the operator.
Sign-out was hardened into a real server-side revocation (epoch + dev
watermark) because Flask sessions are client-side and a popped key alone can't
kill a captured cookie.

---

## 5. Findings

| id | sev | title | how it shows up | root cause | status | commit |
|----|-----|-------|-----------------|------------|--------|--------|
| F1 | P1 | Cross-tenant IDOR on `/api/visual/<vid>` and `.../png/<format>` | A signed-in member of org A fetches org B's visual sidecar (caption, alt text, athlete names) and rendered PNG by visual id | Both routes scanned ALL of `RUNS_DIR` and returned the first id match with no `_can_access_run` check (the sibling `/venue-search` had one) | fixed | `647ecc8` |
| F2 | P1 | Signed-in accounts could roam any unbound organisation | A member sees/pins/edits any pilot or freshly-captured org, not just their own | ADR-0014 left unbound orgs open to *every* session; the rule never distinguished anonymous from signed-in-foreign | fixed | `4e30e71` |
| F3 | P1 | Members forced through an org picker after sign-in | Every login landed on `/sign-in`, contradicting the required "land on their own club" behaviour | First-run routing assumed the picker was always the post-login step | fixed | `4e30e71` |
| F4 | P0-adjacent | Sign-out did not end the session server-side | `/logout` left the org pin in the session; a replayed pre-logout cookie restored account + org access; `/logout` also answered GET | `logout_user()` popped only account keys; no server-side revocation for client-side sessions; GET allowed a cross-site link to act | fixed | `4e30e71` |
| F5 | P2 | `/logout` and `/sign-out` acted on GET (no CSRF) | A cross-site link could end (or probe) a session | State change on a GET route | fixed | `4e30e71` |
| F6 | P2 | Signed-in HTML cacheable (back-button after sign-out) | On a shared machine the back button could redisplay a signed-in page | No `Cache-Control` on authenticated HTML | fixed | `4e30e71` |
| F7 | P3 | Unlabeled form fields + a nested duplicate label | Governing-body and 5 social inputs had no programmatic label; org-setup had a broken nested `<label>Club website` | Label markup omitted `for`/`id`; a stray leftover tag | fixed | `4e30e71` |

No P0 "unauthenticated route grants org-wide access" was found — P2 held at
baseline (dev sign-in is properly authenticated, ADR-0019).

---

## 6. Changes and fixes applied

**`src/mediahub/web/auth.py`** (shared)
- `User.session_epoch: int = 0` (+ tolerant `from_record`); `UserStore.bump_session_epoch`.
- Dev-session watermark: `revoke_dev_sessions()` writes `DATA_DIR/.dev_sessions_revoked_at`; `is_dev_operator()` refuses operator cookies minted before it (mtime-cached).
- `login_user` stamps `sess_epoch`; `current_user_email()` enforces the epoch (the identity choke point) with a per-request `flask.g` cache; `logout_user` clears the epoch + dev keys.

**`src/mediahub/web/web.py`** (shared)
- `_session_can_use_profile` rewritten to the member-confined model (F2).
- `_auto_pin_member_org()` helper; wired into `login_post`, `login_2fa`, `signup_post`; `/sign-in` single-org fast-path (F3).
- `/logout` and `/sign-out`: POST-only state change + GET confirmation; logout bumps the account epoch, revokes dev sessions, and `session.clear()`s (F4, F5).
- `Cache-Control: no-store` on signed-in HTML in `_security_headers` (F6).
- Nav: Log out / Developer / Leave-organisation become CSRF POST forms; `can_switch_org` gates the picker/leave entries; new nav-button CSS (F5, plus UX).
- `/api/visual/<vid>` and `.../png/<format>`: `_can_access_run` gate at the match point (F1).
- a11y: `for`/`id` on login/signup + org-setup fields; removed the nested duplicate label (F7).

**Migration / existing data.** `users.jsonl` gains an optional `session_epoch`
int; missing → 0, so every existing account keeps working with no migration.
The dev watermark file is created on first operator logout; absent = nothing
revoked. No membership or profile data shape changed. Existing multi-org
membership rows are honoured by the landing rule (§9), not discarded.

---

## 7. Tests added or extended

- `test_authn_hardening.py`: `test_login_lands_member_directly_on_their_org`
  (A1), `test_get_logout_is_inert_and_post_clears_everything` (F4/F5),
  `test_replayed_prelogout_cookie_is_dead` (P3/F4),
  `test_dev_logout_revokes_outstanding_dev_cookies` (operator revocation),
  `test_signed_in_html_is_no_store_but_anonymous_is_not` (F6); GET→POST logout
  swap across `test_auth.py` / `test_authn_hardening.py` / `test_legal_acceptance_flow.py`.
- `test_workspace_membership_invariant.py`: `test_unbound_org_open_to_anonymous_only`
  (F2 — signed-in foreign refused, operator roams), `test_single_org_member_skips_the_picker_entirely`
  (A1), `test_multi_org_member_picker_lists_only_their_orgs` (P4), and
  strengthened `test_signed_in_non_member_cannot_pin_a_bound_org`,
  `test_sign_in_post_refuses_bound_org_for_non_members`,
  `test_editing_an_unbound_org_does_not_grab_it`,
  `test_signed_in_stranger_on_open_workspace_sees_no_emails`, plus the invite
  first-claim direct-landing assertion.
- `test_cross_tenant_access.py`: new `TestVisualSidecarTenantScoped` — foreign
  org gets 404 on the sidecar and the PNG, the owner still gets 200, and a
  legacy ownerless visual stays readable (F1).

---

## 8. Cross-cutting changes (for reconciliation)

All edits are in the three shared surfaces the task expected to touch, kept
minimal:
- **Sign-in / account (`auth.py`)**: session helpers + `User` gained epoch
  revocation and the dev watermark. The public function signatures are
  unchanged except the new `bump_session_epoch` / `revoke_dev_sessions`.
- **Session / routing (`web.py`)**: `_session_can_use_profile`,
  `_auto_pin_member_org`, `login_post` / `login_2fa` / `signup_post`,
  `sign_in_page`, `logout`, `sign_out`, `_security_headers`, the nav template
  block in `_layout`, and the `/api/visual` pair. No unrelated refactoring.
- **Nav template**: three GET links became POST forms; a `can_switch_org`
  template var was added. Any session editing the top-nav block should note
  the Log out / Developer / Switch / Leave controls changed shape.

---

## 9. Membership decision (P4)

The data model **does allow one account to belong to multiple organisations**
(the `memberships.jsonl` ledger is keyed on `(email, profile_id)` with no
one-org constraint). Rather than force a single-org constraint (which would
break legitimate multi-club operators and any existing multi-seat rows), the
landing behaviour is defined as: **keep the already-pinned org when it is one
of the member's own; otherwise pin the alphabetically-first member org**
(deterministic, safe, never a foreign org). Single-org members — the common
case — never see a picker; multi-org members keep one, confined server-side to
their own workspaces. Flagged here for the operator: if the product intends
strictly one org per member, add a constraint at membership-add time; until
then the deterministic rule above governs. Recorded in ADR-0028.

---

## 10. Residual risks / broader work (not attempted here)

- Run ids and visual ids are 48-bit random, not HMAC-signed (documented
  defence-in-depth gap in `KNOWN_ISSUES.md`). The F1 fix closes the *entitlement*
  hole; signing ids remains a separate hardening task.
- Logout revokes an account **everywhere** (all devices) by design; true
  per-device revocation would need a server-side session table — deliberately
  not built for a flat-file deployment.
- The dev-session watermark is process-file based (mtime-cached); on a
  multi-worker host it is shared via `DATA_DIR`, which is correct, but a
  clock skew across workers could delay a revocation by seconds. Acceptable
  for a break-glass operator control.

---

## 11. Verdict

**WORKS.** Members land directly on their own club with no picker; a member's
request for another organisation is refused at both the page and the data
endpoint; only an authenticated developer can open any organisation; sign-out
ends the session server-side and a replayed cookie is dead. Two pre-existing
cross-tenant gaps (the `/api/visual` IDOR and unbound-org roaming) are closed
and locked with tests.

---

## 12. Handover and merge status

- Branch: `claude/mediahub-org-access-control-b1zm6z`.
- Commits: `647ecc8` (F1 visual IDOR fix + tests), `4e30e71` (member
  confinement + direct landing + real sign-out + a11y + ADR-0028 + tests).
- Note on process: a mid-session container refresh discarded three earlier
  unpushed commits and reset the working tree to a newer branch base (which had
  advanced to include another session's free-text hardening, #1104). All work
  was faithfully reconstructed from the session record against the new base and
  re-verified (145 auth/tenancy tests + 207 broad-regression tests green;
  end-to-end and Playwright checks re-run). The free-text chat routes the
  route sweep first flagged were false positives — that other session had
  already added the `_load_accessible_chat` guard now present in the base.
- Merge: pending Phase 5 (integrate latest `origin/main`, re-run the green
  gate on the integrated result, land via the atomic-push protocol). Merge SHA
  recorded here once landed.
- Review the diff: `git diff origin/main...claude/mediahub-org-access-control-b1zm6z`.
