# Data Processing Agreement (Article 28 UK GDPR) — template

> **DRAFT — FOR LEGAL REVIEW. TEMPLATE — not executable as-is.** The
> Art 28(3) contract between each **club (controller)** and the
> **operator (processor)**. Implements the allocation recommended in
> [`LEGAL_FRAMEWORK.md`](../LEGAL_FRAMEWORK.md) §5 (pending Q1). A
> solicitor must review before first execution.

**Parties.** "Controller": [club legal name]. "Processor": [operator legal
name], providing the MediaHub service at [URL].

## 1. Subject matter, duration, nature and purpose

Processing of athlete and member personal data to generate club social
content (results ingestion, achievement detection, optional PB-history
enrichment, card rendering, AI-assisted captioning, scheduling/export for
publication) for the duration of the service agreement.

## 2. Personal data and data subjects

Categories: identification (name, year of age/age group), affiliation
(club), athletic performance (events, times, placings, PB history),
images. Data subjects: athletes (predominantly **children**), club members
and staff. No special category data is intended to be processed.

## 3. Documented instructions (Art 28(3)(a))

The Processor processes only on the Controller's documented instructions,
which comprise: this agreement; the Controller's configuration in the
service (lawful basis, consent mode, **PB-enrichment on/off**, child-policy
controls, retention overrides); and the per-card approval actions of the
Controller's authorised users. The Processor will inform the Controller if
an instruction in its opinion infringes data protection law.

## 4. Confidentiality; security (Arts 28(3)(b), 32)

Persons authorised to process are bound by confidentiality. Technical and
organisational measures: tenant isolation, role-gated access, encrypted
transport, hardened session management, retention schedule with automatic
purge, security event logging, breach playbook — as documented in the
Processor's `docs/security/SECURITY_REPORT.md` (threat-modelled, ASVS L2
programme; residual risks disclosed there).

## 5. Sub-processors (Art 28(3)(d))

General written authorisation for the sub-processors listed at
**[/legal/subprocessors URL]** (mirrored in `docs/compliance/SUBPROCESSORS.md`).
The Processor gives **[30]** days' notice of additions/replacements; the
Controller may object on reasonable grounds. Equivalent Art 28(3)
obligations flow down. Optional services (cloud photo cutout, Buffer
publishing) engage their sub-processor **only if the Controller enables
them**.

## 6. Data subject rights assistance (Art 28(3)(e))

The service provides the Controller working tooling for access (SAR
export), rectification, erasure (all stores, with honest residuals),
restriction, and objection/opt-out — `/organisation/athlete-rights` — and
the Processor assists with anything beyond the tooling without undue
delay.

## 7. Breach; assistance (Arts 28(3)(f), 32–36)

The Processor notifies the Controller **without undue delay** after
becoming aware of a personal data breach affecting the Controller's data,
with the Art 33(3) particulars as they become available, and assists with
ICO/data-subject notifications and DPIAs. Process:
`docs/compliance/BREACH_PLAYBOOK.md`.

## 8. End of processing (Art 28(3)(g))

On termination, at the Controller's choice, the Processor returns the
Controller's data (machine-readable export) and/or deletes it (and
existing copies), save where law requires retention — and certifies
deletion.

## 9. Audit (Art 28(3)(h))

The Processor makes available the information necessary to demonstrate
compliance (this document set, the ROPA, the security report, audit
ledgers) and allows for and contributes to audits at reasonable notice.

## 10. International transfers

The Processor transfers personal data outside the UK only to the listed
sub-processors under: UK adequacy regulations (incl. the UK–US data bridge
where the recipient is certified), or the **EU SCCs + UK International
Data Transfer Addendum** / **UK IDTA** as recorded per sub-processor. For
EU-establishment clubs, the EU GDPR module applies: 2021 EU SCCs
(Modules 2/3 as applicable) **[attach as Annex]**.

## Annexes

A. Processing details (this document §§1–2 completed per club)
B. Sub-processor list (live page + snapshot at execution)
C. Transfer mechanisms per sub-processor
D. Security measures summary
