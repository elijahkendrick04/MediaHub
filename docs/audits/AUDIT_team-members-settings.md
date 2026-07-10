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
