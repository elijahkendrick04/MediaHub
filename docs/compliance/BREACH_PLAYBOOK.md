# Personal Data Breach Playbook

> **DRAFT — FOR LEGAL REVIEW.** Operator-facing runbook for suspected or
> confirmed personal data breaches (Arts 33–34 UK GDPR; ICO reporting).
> The incident register lives at `/admin/compliance` (engine:
> `mediahub/compliance/incidents.py`, ledger `DATA_DIR/compliance/incidents.jsonl`).
> Most data here concerns **children** — treat severity accordingly.

## What counts as a breach

A breach of security leading to accidental or unlawful destruction, loss,
alteration, unauthorised disclosure of, or access to, personal data —
confidentiality, integrity, **or availability**. Examples for MediaHub:
a cross-tenant read of another club's runs; a leaked `users.jsonl`;
a published card for an opted-out child; a lost/unrestorable data volume;
a compromised provider API key that exposes prompt payloads.

## The clock

- **T0 = awareness**: the moment the operator becomes aware a breach
  *may* have occurred. Open an incident at `/admin/compliance` immediately
  with `detected_at = T0` — this timestamps the 72-hour clock evidence.
- **T0 + 72h**: deadline to notify the **ICO** if the breach is *likely to
  result in a risk* to people's rights and freedoms. Notify in phases if
  facts are incomplete (Art 33(4)); a late notification must explain the
  delay. Report via ico.org.uk/for-organisations/report-a-breach
  (or +44 303 123 1113).
- **Without undue delay**: tell **affected data subjects** (via the club
  controller — see roles below) if the breach is likely to result in a
  *high* risk (Art 34). For under-18 athletes, communicate to
  parents/guardians in clear, plain language: what happened, likely
  consequences, what we are doing, what they can do, contact point.

## Roles (per the recommended allocation — LEGAL_FRAMEWORK §5)

- For tenant athlete data, the **club is the controller**: the operator
  (processor) must notify the affected club(s) **without undue delay**
  (Art 33(2)) and assist with their ICO/data-subject notifications. The
  club makes the Art 33/34 notifications for its athletes.
- For operator-controller data (user accounts, complaints records), the
  **operator notifies the ICO/subjects directly**.

## Procedure

1. **Contain** — kill switch (`MEDIAHUB_PUBLISH_KILL_SWITCH=1`) if
   publication is implicated; rotate exposed credentials (`.env` only —
   no code change needed); suspend the affected route/feature; preserve
   logs and the audit ledger (never delete — they are evidence).
2. **Record** — open the incident in the register: facts, scope (which
   tenants, which data subjects, children involved?), `detected_at`.
   Art 33(5) requires documenting **every** breach, even ones assessed as
   non-notifiable.
3. **Assess risk** — likelihood × severity for the people affected
   (children's data weights severity up). Document the assessment and the
   notify / don't-notify decision in the incident record.
4. **Notify** — per the clock and roles above. The ICO notification needs:
   nature of the breach, categories and approximate numbers of data
   subjects and records, DPO/contact point, likely consequences, measures
   taken or proposed.
5. **Remediate & review** — fix the cause, add a regression test, update
   the threat model and this playbook, record `remedial_action`, close the
   incident.

## Notification decision aid

| Scenario | ICO? | Data subjects? |
|---|---|---|
| Cross-tenant read of athlete data (children) | Likely yes | Likely yes (high risk — children) |
| Card published for an opted-out/no-consent child | Likely yes | Yes, via the club |
| Encrypted backup lost, key safe | Document only | No |
| Provider key leaked, no evidence of prompt-log access | Assess; phased notification if unclear | Assess |
| Brief availability outage, no data exposure | Document only | No |

> Legal-judgment points (when in doubt): notify-or-not assessments should
> err toward notifying and be checked with a solicitor — log the case in
> [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md) if a recurring
> pattern emerges.
