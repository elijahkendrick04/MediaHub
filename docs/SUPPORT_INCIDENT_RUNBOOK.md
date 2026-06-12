# Support & incident runbook (PC.14)

The boring promises a paying club silently relies on: where to get help, who
does what when something breaks, and the rehearsed path back from data loss.
Companion docs: [`compliance/BREACH_PLAYBOOK.md`](compliance/BREACH_PLAYBOOK.md)
(the breach **decision** process — 72-hour clock, risk assessment,
notifiability; this runbook is the operational channel and recovery half),
[`docs/compliance/DPIA.md`](compliance/DPIA.md) (risk register),
[`docs/COMPLIANCE_HANDOVER.md`](COMPLIANCE_HANDOVER.md) (founder checklist),
ADR-0015 (the lawful-to-sell gate this implements half of). Every breach —
notifiable or not — is documented in the Art 33(5) incident register
(`compliance/incidents.py`, surfaced on `/admin/compliance`).

**Owner:** the founder/operator (named as breach owner per F.6 — update here
when that changes). **Support contact:** the address in
`legal.CONTACT_EMAIL` (placeholder until F.2), surfaced in the footer and
ToS. **Target first response:** 2 working days (ToS commits to 14 days for
complaints; aim much faster).

---

## 1. Support intake

- Channel: the support email above. No ticketing system at this scale —
  an inbox label ("MediaHub support") and this checklist.
- Triage order: (1) anything safeguarding/consent-related — same day;
  (2) a paying club blocked mid-workflow; (3) data-rights requests
  (point at the self-serve tools first — Privacy page, Organisation page
  takeout/delete); (4) everything else.
- Data-subject requests from **athletes/parents** (not the club): MediaHub
  is processor — acknowledge, pass to the club (controller), assist via the
  product's erasure/correction tools. Keep the email thread as the record.

## 2. Incident response — detect → contain → assess → notify

**Detect.** Signals: uptime monitor (observability/uptime), users reporting
errors, a provider breach notice, anomalous ledger entries
(`DATA_DIR/autonomy_audit/`, posting log), Render alerts.

**Contain.**
1. Publishing: flip the autonomy kill switch (publish gate honours it) and,
   if needed, suspend Buffer channel connections.
2. Access: the operator `/developer` sign-in is public and passwordless
   (ADR-0018), so there is no key to rotate — rotate `SECRET_KEY` to
   invalidate every session cookie (including any outstanding operator
   session) plus magic links and reset tokens; rotate any provider key
   suspected leaked (`.env` only — never code). To close the operator door
   itself, ship a code change re-gating `/developer`.
3. If the host itself is compromised: scale the Render service to zero;
   the data disk persists.

**Assess.** What data, whose, since when? Evidence sources, in order: the
posting log (what actually went out, with caption excerpts), the per-org
autonomy audit ledger, `legal_acceptances.jsonl`, run JSONs, Render logs.
Write a timeline as you go — it becomes the ICO record.

**Notify.**
- **Record first:** open an incident in the Art 33(5) register
  (`/admin/compliance` → incidents; `compliance/incidents.py`) — every
  breach is documented whether or not it's notifiable. The notifiability
  *decision* (risk assessment, 72-hour clock mechanics) follows
  [`compliance/BREACH_PLAYBOOK.md`](compliance/BREACH_PLAYBOOK.md).
- **Clubs (controllers): without undue delay.** Use the operator
  breach channel — `/operator/notify-users` sends to every account email
  and records the send (counts + subject) in
  `DATA_DIR/operator_notices.jsonl`. That ledger is the evidence the DPA
  §8 notification duty was met.
- **ICO: within 72 hours** of awareness where the breach risks people's
  rights (children's data: assume it does unless clearly contained).
  Report at ico.org.uk. The DPIA's risk register maps likely scenarios.
- Keep notifying honestly as facts firm up; partial notification on time
  beats complete notification late.

## 3. Backups

- **What:** `mediahub.backup.create_backup()` — data.db + memory.db
  (SQLite online-backup API, consistent under live writes), every root
  JSONL ledger (users, memberships, legal acceptances, operator notices),
  `club_profiles/`, `club_logos/`, `commercial/`, `sponsors/`,
  `autonomy_audit/`, and `runs_v4/*.json` + workflow sidecars. Rendered
  outputs and caches are deliberately excluded — they re-derive from runs.
- **When:** daily scheduler task `backup_sweep` (04:10 UTC), active once
  `MEDIAHUB_BACKUP_DIR` or `MEDIAHUB_BACKUP_UPLOAD_URL` is set; honest
  no-op (logged) otherwise.
- **Where:** archives in `MEDIAHUB_BACKUP_DIR` (keep `MEDIAHUB_BACKUP_KEEP`,
  default 14), plus an optional HTTP PUT per archive to
  `MEDIAHUB_BACKUP_UPLOAD_URL` — that PUT is the off-site copy; a backup
  on the same disk as the data is not a backup.
- **Render disk snapshots:** confirm they're enabled on the service's disk
  (Render dashboard → service → Disk). They cover whole-disk loss;
  the ZIP layer covers portability + provider loss.
- **State:** the last run's outcome (timestamp, size, uploaded?) is in
  `DATA_DIR/backup_state.json` and shown on `/operator/notify-users`.

## 4. Restore drill — documented AND rehearsed

The drill is automated in `tests/test_backup_restore.py`: every full test
run creates data → backs up → restores into a fresh DATA_DIR → verifies the
ledgers, profiles and runs match. An unrestored backup is a hypothesis;
this one is rehearsed on every CI run.

Human procedure (provider loss / migration):

1. Provision the new host; set the env from your `.env` copy (keys live
   only there — they are not in any backup archive, by design).
2. Fetch the newest archive from the off-site location.
3. `DATA_DIR=/var/mediahub python -m mediahub.backup restore <archive.zip>`
   (add `--force` only when restoring over an existing tree, deliberately).
4. Start the app. Verify: sign in works (users ledger), an org loads with
   its brand kit, a historic run renders its cards, `/wall/<token>` works,
   and the legal-acceptance ledger is intact.
5. Record the drill (date, archive, outcome) in this file's log below.

| Date | Archive | Outcome |
|---|---|---|
| 2026-06-12 | (automated) tests/test_backup_restore.py | restore verified in CI on every run |

## 5. Billing hygiene

- Every Stripe subscription payment generates an invoice; users download
  PDFs from **Billing → Manage billing** (customer portal) — stated on
  `/billing` and `/billing/confirm`.
- Founder half (F.1): enable Stripe's renewal-reminder + receipt emails in
  the dashboard (the ToS promises a reminder before annual renewal — keep
  it true), and implement the VAT decision in Stripe Tax settings.

## 6. Standing rules

- Never test incident steps against production without notice (CLAUDE.md
  security rule).
- After any incident: write the post-mortem into `docs/`, update the DPIA
  risk register if the scenario was new, and re-run the relevant drill.
- Keep this runbook honest: when a referenced surface changes, change this
  file in the same PR.
