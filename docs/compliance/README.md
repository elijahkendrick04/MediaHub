# docs/compliance — UK legal compliance records

The data-protection paper trail for MediaHub. In plain words: MediaHub
handles swimmers' names, ages and photos — many of them children — so the
law (UK GDPR and friends) says we must know exactly what data we hold, why
we're allowed to hold it, and how a swimmer or parent can say "stop". These
documents are that proof, written so a regulator or a club committee could
read them.

Everything legal-shaped in here is marked **DRAFT — FOR LEGAL REVIEW**: an
engineer wrote it from primary sources, and a solicitor must confirm it
before anyone treats it as final.

## The programme documents

- [`LEGAL_FRAMEWORK.md`](LEGAL_FRAMEWORK.md) — the law as it stands (UK
  GDPR, DPA 2018, PECR, the Data (Use and Access) Act 2025 changes, the
  ICO Children's Code, EU rules, international transfers), verified
  against primary sources.
- [`DATA_MAP.md`](DATA_MAP.md) — where personal data lives and flows,
  store by store, with code evidence.
- [`ROPA.md`](ROPA.md) — the Article 30 record of processing activities.
- [`SUBPROCESSORS.md`](SUBPROCESSORS.md) — every third party, what it
  receives, where, and the transfer safeguard (public page:
  `/legal/subprocessors`).
- [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) → [`COMPLIANCE_SUMMARY.md`](COMPLIANCE_SUMMARY.md)
  — each gap, the capability that closed it, and the evidence.
- [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md) — every judgment
  call we have NOT made. Nothing legal is decided silently.
- [`DPIA.md`](DPIA.md) — the Data Protection Impact Assessment draft (ICO
  structure). Needs controller sign-off.
- [`CHILDRENS_CODE.md`](CHILDRENS_CODE.md) — the 15 standards, answered.
- [`BREACH_PLAYBOOK.md`](BREACH_PLAYBOOK.md) + [`COOKIE_AUDIT.md`](COOKIE_AUDIT.md)
  — incident response and the PECR position.
- [`templates/`](templates/) — Art 13/14 privacy-notice and Art 28 DPA
  templates for clubs.

## Related records elsewhere

- The UK-legal audit that ordered the parallel remediation:
  [`../COMPLIANCE_AUDIT.md`](../COMPLIANCE_AUDIT.md); what it built and
  what remains operational: [`../COMPLIANCE_HANDOVER.md`](../COMPLIANCE_HANDOVER.md).
- The customer-facing legal documents live in code
  (`src/mediahub/web/legal.py`) so they can never drift from the routes
  that serve them (`/terms`, `/privacy`, `/cookies`, `/dpa`).
- Security evidence: [`../security/`](../security/README.md) (threat
  model, ASVS L2 report, residual-risk register).
