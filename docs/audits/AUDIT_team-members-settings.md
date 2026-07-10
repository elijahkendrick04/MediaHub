# Audit — Settings ▸ Team members

**Feature:** "Team members" tile in Settings → the workspace-members admin page.
**Mode:** AUDIT+FIX. **Auditor:** autonomous QA/fix session. **Date:** 2026-07-10.

---

## 1. Scope contract

**Definition.** "Team members" is the Settings surface where a workspace owner (or
the deployment operator) manages *who can sign in to the active organisation and
what they may do*. From the Settings grid the "Team members" tile
(`_settings_card_specs`, web.py) links to `organisation_members_page`
(`GET,POST /organisation/members`, titled "Workspace members"). "Working" means:
an owner can invite a teammate by email and pick their role; an existing account
is added active immediately while an unknown email is stored as an `invited` row
that activates automatically at signup; roles can be changed and members removed;
the last active owner can never be demoted or removed; non-admins and strangers
cannot manage or enumerate members; and every write is CSRF-protected, escaped,
and tenant-isolated.

**Routes/endpoints owned.**
- `GET,POST /organisation/members` → `organisation_members_page` (the whole feature).
  - `POST action=add` — invite/add a member or change a role (shared upsert).
  - `POST action=remove` — remove a member (tombstone).

**Files owned (blast radius).**
- `src/mediahub/web/web.py` — `organisation_members_page` (~40994–41245), helper
  `_send_invite_email` (~40670), the "Team members" settings tile (~29180), and the
  membership access helpers it relies on (`_session_owns_profile`, `_active_role`,
  `_invalidate_memberships_snapshot`).
- `src/mediahub/web/tenancy.py` — `MembershipStore` / `Membership` (the ledger).
- `src/mediahub/collab/permissions.py` — role → capability matrix + labels.

**Shared files depended on but NOT freely rewritten.**
- `web.py` app factory, `_layout` (base template + global form-submit JS/CSRF
  auto-inject), `_csrf_protect`, `src/mediahub/web/auth.py` (`UserStore`,
  `normalize_email`, `_looks_like_email`), `src/mediahub/notify/email.py`.

**Inputs / outputs / persistence.** Input: an email + a role from the admin
forms. Output: rendered member table + flash notices, and an optional invite
email. State: append-only JSON-lines ledger `DATA_DIR/memberships.jsonl`
(last-write-wins per `(email, profile_id)`, `chmod 0600`). No SQL, no profile-JSON
coupling.

**Intended happy path (concrete).**
1. Owner opens Settings → Team members → sees "Workspace members" with the member
   table + "Add a member" form.
2. Owner enters `coach@club.org`, picks a role, submits → row appears as
   *Invited — activates at signup* (or *Active* if that account already exists),
   with an honest notice about whether an invite email was sent.
3. Owner changes a role via the per-row picker, or removes a member (behind a
   confirm) → table + notice update; the last owner is protected server-side.
4. A non-owner member sees the roster read-only; a stranger/anon on an open
   workspace sees neither emails nor admin controls.

**Assumptions (stated, proceeded).**
- Branch naming: the harness "Git Development Branch Requirements" pin the push
  target to `claude/team-members-settings-audit-15v0p1`; the task Hard Rule 1 asks
  for `audit/<slug>`. These are reconciled by landing via a **draft PR to `main`**
  on the harness-designated branch rather than a direct push to `main` (a direct
  `main` push is "a different branch" the harness forbids without explicit
  permission). Recorded in §10.

---

## 2. Environment

- Python 3.11, Flask 3.1.3. Deps from `requirements.txt` installed into the user
  site (the Debian `pip` vs `/usr/local/bin/python` split required
  `python -m pip install --user`).
- App booted locally: `python -m mediahub.web` on **port 5055**, `DATA_DIR` in an
  isolated scratch dir. Operator credentials set via `MEDIAHUB_DEV_USER` +
  `MEDIAHUB_DEV_PASSWORD_HASH` (argon2id, generated locally — never a real secret).
- Offline posture: `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `STRIPE_SECRET_KEY`
  left empty (AI surfaces honest-error; not exercised by this feature). The email
  seam is unconfigured, so `_send_invite_email` returns `False` (honest "share the
  link yourself" copy) — no real mail sent. No paid API calls made.
- Seeded world: a **bound** org `riverside-sc` (owner `owner@riverside.org` +
  active `member2@riverside.org`) and an **unbound/open** org `open-club`.
- Drivers: Flask test client (functional/edge/security matrix) + Playwright via the
  prebaked Chromium at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (the
  Playwright MCP wanted a `chrome` channel that is absent, so Playwright was driven
  directly from Python). Screenshots at desktop 1280px and mobile 390px.

<!-- SECTIONS 3-10 appended after verification completes -->

---

## 3. Test matrix results

| # | Dimension | Result | Note (evidence) |
|---|-----------|--------|-----------------|
| 1 | Functional correctness | PASS | Owner add/invite, role change, remove all produce correct ledger state + honest notices. Verified via test client + Playwright + live probe. |
| 2 | Every interactive control | PASS (after fixes) | Add form, per-row role picker (Update), Remove (confirm), Back link, Log-in CTA enumerated. The picker's Update mis-fired invite emails and could silently downgrade (F5/F7) — fixed. Remove-confirm loader stuck on cancel (F1) — fixed. |
| 3 | Input validation / edge cases | PASS (after fixes) | Empty/missing action, email, role handled cleanly; unknown action → clean error; invalid role coerces to member; unicode ok; un-activatable + line-separator + over-long emails now rejected (F4 + hardening). |
| 4 | UI state handling | PASS (after fixes) | Loading/empty/error/success states render. The full-screen loader no longer sticks after a cancelled confirm (F1); status badges now render as pills (F9); the invite notice shows the signup link it references (F10). |
| 5 | Server-side error handling | PASS | No 500s / stack traces; `TenancyError` surfaces as a clean flash; non-admin POST → 404 (anti-enumeration). |
| 6 | Data integrity | PASS (after fixes) | In matches out; append-only last-write-wins; idempotent view. `invited_by` no longer overwritten on edits (F6); line-separator rows no longer silently lost (hardening); the last-owner-erasure ownerless-workspace P1 fixed with succession (F8). |
| 7 | Security | PASS | Authz on GET+POST for anon/foreign/member/owner/operator; CSRF enforced + auto-injected (tokenless POST → 403); no secrets in responses; XSS escaped via `_h()`; PII gate on open workspaces; tenant isolation held (test_cross_tenant_access green). One owner-privileged enumeration oracle logged (L1). |
| 8 | Performance | PASS-WITH-NOTES | No pathological slowness for realistic club sizes. The route re-parses the small membership ledger several times per request instead of the request-scoped snapshot (L5) and appends without compaction (L6) — logged, not pathological. |
| 9 | Responsive / accessibility | PASS (after fixes) | Mobile 390px: no horizontal overflow (stacked table). Labels now associated (F2), `th scope` added (F3), email `autocomplete` (F2), per-row role `<select>` given an accessible name. Residual a11y polish logged (L12). |
| 10 | Rendered-graphic correctness | N/A | This feature renders no card graphics. |
| 11 | Consistency / copy quality | PASS-WITH-NOTES | British English throughout the route; no TODO/debug/placeholder text. Tenant named four ways across the screen (L10) and one jargon phrase on open workspaces (L11) logged as polish. |

## 4. Findings

Severity: P0 broken/dataloss/security-hole · P1 wrong behaviour or lying control · P2 usability/a11y/error-handling · P3 polish.

### Fixed

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
|----|-----|-------|--------------|------------|--------|--------|
| F1 | P2 | Full-screen loader sticks after a cancelled "Remove" confirm | Open members, click Remove, dismiss the confirm → "Working on it" overlay stayed until the 20s safety timeout | Shared `bindForms` submit handler raised the loader even when an earlier `onsubmit` handler cancelled the submit | Fixed | invite validation + a11y + loader |
| F2 | P2 | Add-member form labels not associated; email lacks autocomplete | Screen reader can't tie "Email"/"Role" to their fields | `<label>` had no `for`; inputs no `id`; no `autocomplete` | Fixed | invite validation + a11y + loader |
| F3 | P3 | Members table headers lack `scope` | Screen-reader table nav ambiguous | `<th>` had no `scope="col"` | Fixed | invite validation + a11y + loader |
| F4 | P3 | Un-activatable invite stored (e.g. `coach@club`, no TLD) | Add `coach@club` → row sits "invited" forever (signup rejects that address) | Store only checks for `@`; route did not pre-validate | Fixed | invite validation + a11y + loader |
| F5 | P2 | Invite email re-sent on every role edit of an invited member | Configure email seam, invite X, click Update on X's row repeatedly → an invite email each time | Picker's `action=add` re-ran the invite branch (no new-vs-edit distinction) | Fixed | harden add path |
| F6 | P3 | `Invited by` overwritten to the last editor on any role change | A invites X; B changes X's role → column shows "Invited by B" | Route always passed `invited_by=<current admin>`; store prefers the passed value | Fixed | harden add path |
| F7 | P3 | Add form silently changes an existing member's role | Type an existing member's email in the Add form (role defaults to Member) → silent downgrade | Add form + picker share `action=add`; blind upsert | Fixed (via `add_form` marker + guard) | harden add path |
| F8 | P1 | Account deletion strands a bound workspace with no owner | Sole owner of a workspace with other active members deletes their account → workspace stays bound but ownerless; every remaining member locked out of all admin, no in-product recovery | `erase_email` (via `privacy.erase_account`) removed the owner with no succession; `is_bound` is role-agnostic | Fixed (ownership succession) | erase succession |
| — | P2 | Member email with U+2028/U+2029/U+0085 silently lost on read-back | Add `a<U+2028>b@club.org` → "success" but row vanishes (`splitlines()` tears the JSON line) | No control/line-separator rejection | Fixed (folded into F5 commit) | harden add path |
| — | P3 | Per-row role `<select>` had no accessible name | Screen reader can't tell which member a role dropdown changes | Bare `<select>` with no label/aria | Fixed (`aria-label="Change role for <email>"`) | harden add path |
| — | P3 | Legacy dotless-domain member's role picker was unusable | After F4, editing a pre-existing `foo@bar` member re-validated and refused | Email validation ran for edits too | Fixed (validate new memberships only) | harden add path |
| — | P3 | No length bound on the member email | An admin could persist an arbitrarily long address | No cap | Fixed (254-char RFC 5321 ceiling) | harden add path |
| F9 | P2 | Status badges render unstyled ("Active" is plain text) | Open members → the Active/Invited status column shows text with no pill shape | The bare `.pill` class has no base CSS rule outside `.mh-profile-card .meta-line` (static CSS defines `.mh-badge`, not `.pill`); "Active" carried no inline style at all | Fixed (self-contained inline pill styling on both badges) | badges + signup link |
| F10 | P2 | Invite notice references a signup link the page never shows | With no email seam, inviting X flashes "share the signup link with them yourself" — but no link appears anywhere | The notice text referred to a link that was never rendered | Fixed (the actual `signup_page` URL is now shown in the notice) | badges + signup link |

*(Commit column uses the commit subject-tag rather than a SHA — hashes churn on each rebase onto the moving `main`. Map to SHAs with `git log origin/main..HEAD`.)*

### Logged (not fixed — with rationale)

| ID | Sev | Title | Disposition |
|----|-----|-------|-------------|
| L1 | P2 | Add-member response is a registered-account enumeration oracle ("added" vs "invited") | By-design: owner-privileged, and the invite-vs-add distinction is necessary UX. Reveals only "does this email have an account". Accept. |
| L2 | P2 | No Post/Redirect/Get: reload re-submits (false "No such membership" after Remove) | App-wide convention — the sibling `/organisation/api` route also renders inline on POST. Browser resubmit-warning mitigates. Needs a repo-wide PRG pass, not a members-only change (footprint discipline). |
| L3 | P2 | "Log in to manage members" is a dead-end CTA on an open workspace | Copy/UX: an open (unbound) workspace has no owners to log in as; only the operator seeds the first membership. Reword recommended. |
| L4 | P3 | Last-owner demotion guard is a non-atomic route check (TOCTOU) | Two owners demoting each other concurrently could both pass. Recommend moving the invariant into `MembershipStore.add` under `_LEDGER_LOCK` (as `remove` does) — but that affects every `add` caller, so coordinate. Window is tiny; operator-recoverable. |
| L5 | P2 | Members route re-parses the ledger ~4x/GET, ~6-7x/POST instead of the `flask.g` snapshot | Perf: the small members ledger (dozens of rows for a real club) makes this non-pathological; scales with member count, not results volume. Recommend routing reads through `_memberships_snapshot`. |
| L6 | P2 | Append-only ledger never compacted on normal writes | By-design (crash-safe audit trail); compaction happens on erase. Grows with the number of edits, not unbounded per request. |
| L7 | P3 | `_active_profile_id()` (a profile disk read) runs ~3x per request | Minor perf; memoise on `flask.g`. |
| L8 | P3 | Role picker + Remove render enabled for the sole/last owner (actions that always fail) | Minor UX; the server guard + clear error message is the safety net. Consider disabling with a tooltip. |
| L9 | P3 | Stale `can_admin` for one render after an owner demotes/removes themselves | Self-heals on the next request (the resolver drops the pin). Cosmetic. |
| L10 | P3 | The tenant is named four ways on one screen (Team / Workspace / organisation / club) | Consistency/copy. The tile says "Team members", the page `<h1>` "Workspace members". |
| L11 | P3 | Open-workspace explanation leaks jargon ("the pre-multi-tenant behaviour") | Copy: meaningless to a coach; only shown on unbound/pilot workspaces. |
| L12 | P3 | Update/Remove buttons share identical accessible names across all rows | A11y minor — the role `<select>` was given a per-member name (fixed); the buttons still read "Update"/"Remove" for every row (adjacent email cell gives row context). |
| L13 | P3 | Bound workspace could revert to open if its last active member were removed | Largely unreachable via the UI (the last owner is remove-guarded); the genuine gap was the erase path (F8), now fixed. |

## 5. Fixes applied

- **`src/mediahub/web/web.py`** — `organisation_members_page` add-branch rewritten to be prior-row aware: validate the address (format + control/separator chars + length) only for a NEW membership; a `via=add_form` marker lets the Add form refuse an existing active member (role changes go through the picker); preserve the original inviter on edits; send the invite email only when the invite is newly created; honest notices for new-vs-edit. Per-row role `<select>` given `aria-label`. (Plus the pre-existing F1-F4 fixes: `_layout` submit-loader guard, add-form label association + autocomplete, `th scope`, email pre-validation.)
- **`src/mediahub/web/tenancy.py`** — `MembershipStore.erase_email` now performs ownership succession: if erasing an owner would leave a still-populated workspace without an owner, the longest-standing remaining active member is promoted. The erased email's rows are still removed in full.
- **`src/mediahub/web/web.py` (F9)** — both status badges are given self-contained inline pill styling (`display:inline-block`, `border-radius`, padding, border, the app's `--good`/`--warn` colours) so "Active"/"Invited" render as pills. The bare `.pill` class has no base rule here, so this is deliberately feature-scoped (no shared-CSS change — see §7).
- **`src/mediahub/web/web.py` (F10)** — when the email seam is unconfigured, the invite notice now renders the real `signup_page` URL instead of referring to a "signup link" the page never showed.

## 6. Tests added / extended

`tests/test_audit_team_members_settings.py` (all green):
- `test_add_member_form_labels_are_associated`, `test_members_table_headers_carry_scope` — F2/F3 a11y.
- `test_invalid_email_is_rejected_not_stored`, `test_valid_email_is_still_invited` — F4.
- `test_submit_loader_bails_when_default_prevented` — F1 (source-level lock).
- `test_editing_invited_member_role_does_not_resend_invite` — F5 (mocks the email seam, asserts one send across an invite + a role edit).
- `test_invited_by_is_preserved_on_role_change` — F6.
- `test_add_form_refuses_an_existing_active_member`, `test_picker_can_still_change_an_active_member_role` — F7 (guard + backward-compat).
- `test_email_with_line_separator_is_rejected` — U+2028 hardening.
- `test_erasing_last_owner_promotes_a_remaining_member`, `test_erasing_sole_member_still_unbinds` — F8 (succession + zero-member model preserved).
- `test_status_badges_are_self_styled` — F9 (both badges carry pill shape).
- `test_invite_notice_shows_the_signup_link_when_mail_unconfigured` — F10 (mocks the mail seam off, asserts the signup URL is rendered).

14 tests total, all green (`python -m pytest tests/test_audit_team_members_settings.py -q` → 14 passed).

## 7. Cross-cutting changes (for reconciliation)

Two edits reach beyond `/organisation/members`; both are minimal and additive:

1. **`_layout` shared submit-loader JS (web.py, F1)** — added a single guard `if (e && e.defaultPrevented) return;` in `bindForms`. Strictly improves every `onsubmit="return confirm(...)"` form across the app (it only *skips* the loader when the submit was already cancelled). No behaviour change on normal submits.
2. **`MembershipStore.erase_email` succession (tenancy.py, F8)** — changes GDPR-erasure behaviour: a workspace that would be left ownerless now promotes a remaining member. Reached through **Settings → Account → delete account** (`privacy.erase_account`), which may be another audit's territory. The membership invariant and fix belong to the store, but flagging for coordination. **Maintainer review of the succession policy is recommended** (promote longest-standing member vs. notify vs. other) — auto-succession was chosen because a GDPR erasure cannot be refused, so keeping the workspace manageable is the only legally-consistent option.
3. **Pre-existing EOF hygiene fix (docs only, not this feature).** The PR's `Hygiene hooks (pre-commit)` check went red on `end-of-file-fixer` — but on two *already-merged, unrelated* audit reports (`docs/audits/AUDIT_meet-recap.md`, `docs/audits/AUDIT_season-wraps.md`), each committed to `main` with a stray trailing blank line. `pre-commit run --all-files` scans the whole repo, so every open PR inherits this red. My own files pass all hooks. I applied the hook's own one-line EOF normalisation to both files to unbreak the shared hygiene gate (zero-risk, docs-only, on merged audits — no active session to conflict with). Flagging loudly since they are outside this feature.

## 8. Residual risks / cross-feature work (not attempted here)

- **L4 (concurrency):** the last-owner invariant is enforced in the route, not atomically in `MembershipStore.add`. Hardening it under `_LEDGER_LOCK` touches every `add` caller and should be done deliberately.
- **L2 (PRG):** the whole settings surface renders inline on POST; a repo-wide Post/Redirect/Get pass (with `_flash_toast`) is the right fix, not a members-only divergence.
- **L5/L6/L7 (perf):** routing members-page reads through the existing `flask.g` membership snapshot and memoising `_active_profile_id()` would cut redundant ledger/profile reads. Non-urgent at realistic club sizes.
- The membership model is an append-only JSONL ledger (no SQL); all of the above ultimately point at a future move to indexed multi-tenant storage (already noted in `docs/TECHNICAL_DEBT.md`).
- **Global `.pill` CSS gap (cross-feature):** the `.pill` class has no base rule in the shared cascade (static CSS defines `.mh-badge`; the only `.pill` rule is scoped to `.mh-profile-card .meta-line`). Every `.pill` badge across the app (this page, `/organisation/api` tokens & webhooks, etc.) is therefore unstyled. This audit fixed only its own badges inline (F9, footprint discipline); a proper repo-wide fix is a single base `.pill` rule in `theme-components.css`, which should be reconciled centrally rather than per-feature.

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The Team-members page is functionally correct, secure (authz, CSRF, anti-enumeration, PII-gated, XSS-safe, tenant-isolated), and now hardened against the invite-email resend, the silent role downgrade, the a11y gaps, and the malformed-address data-loss found in the audit. The one P1 — a bound workspace bricked ownerless when its last owner deleted their account — is fixed via ownership succession, but its trigger lives in the account-deletion feature and the succession policy is flagged for maintainer review. Remaining items are P2/P3 usability, perf, and copy polish, logged with rationale.

## 10. Handover & merge status

- **Branch:** `claude/team-members-settings-audit-15v0p1` (the harness-designated branch; the task's `audit/<slug>` intent is carried on it).
- **Draft PR:** [#1131](https://github.com/elijahkendrick04/MediaHub/pull/1131) → base `main`. Landed via **draft PR**, not a direct `main` push: the harness "Git Development Branch Requirements" forbid pushing to a different branch (`main`) without explicit permission, so the PR is the landing mechanism. Auto-subscribed for CI/review follow-up.
- **Commits (5):** invite validation + a11y + loader (F1-F4) · harden add path (F5-F7 + line-separator/length hardening) · erase succession (F8) · this report · badges + signup link (F9/F10). Map to SHAs with `git log origin/main..HEAD`.
- **Green gate (on the tree rebased onto `origin/main`):** import OK · ruff clean · `tests/test_audit_team_members_settings.py` 14 passed · feature + adjacent regression (tenancy, workspace-invariant, collab roles/permissions, privacy erasure, org lifecycle, cross-tenant) 125 passed · app boots, `/` + `/pricing` smoke-load. Full suite (pre-rebase) 12,509 passed / 10 skipped; the only 6 failures were a pre-existing environmental flake (external `u2net.onnx` 403 in `test_ui_2_1_cutout_compare.py`, unrelated to this change — passes in isolation). Re-rebased onto the moving `main` twice; each delta was unrelated audits + roadmap docs with no members-route overlap.
- **Merge status:** NOT merged — open as a **draft PR** for maintainer review (the succession policy in F8 in particular). Not merged red; not force-landed. CI on the PR will run the full suite.
- **Review the diff:** `git diff origin/main...claude/team-members-settings-audit-15v0p1`
