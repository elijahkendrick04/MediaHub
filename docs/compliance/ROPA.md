# Record of Processing Activities (Article 30 UK GDPR)

> **DRAFT — FOR LEGAL REVIEW.** Maintained by the operator. Two parts:
> Part A is the operator's **Art 30(2) processor record** (processing carried
> out on behalf of club controllers — the recommended allocation per
> [`LEGAL_FRAMEWORK.md`](LEGAL_FRAMEWORK.md) §5, pending Q1 in
> [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md)). Part B is the
> operator's **Art 30(1) controller record** for its own processing.
> Storage locations and flows are evidenced in [`DATA_MAP.md`](DATA_MAP.md);
> third parties in [`SUBPROCESSORS.md`](SUBPROCESSORS.md).
>
> Operator (processor / controller as indicated): _[legal entity name, address,
> contact]_ — **to be completed by the operator**. No DPO appointed (not
> mandatory at current scale — revisit if processing becomes large-scale;
> logged Q11 context). Last reviewed: 2026-06-12.

## Part A — Processor record (Art 30(2)): processing on behalf of club controllers

Categories of processing carried out on behalf of each club (controller
identity and contact: per-tenant, held in the club profile):

| # | Processing activity | Data subjects | Personal data categories | What happens | Sub-processors involved | Transfers | Security measures (summary) |
|---|---|---|---|---|---|---|---|
| A1 | **Results ingestion & parsing** | Athletes (largely under-18), incl. athletes from *other* clubs present in the same results file | Name, age/year of birth, sex category, club, event, times, placements | Club uploads HY3/SDIF/PDF/HTML/ZIP; deterministic parsers extract structured rows; raw file retained as provenance | Hosting (Render) | UK→US (hosting) | Tenant-scoped storage; access control; retention schedule; see SECURITY_REPORT |
| A2 | **PB enrichment** (per-tenant opt-in) | Athletes of the tenant club | Name, club, historical PB times/dates from public Swim England rankings (swimmingresults.org) — **data not obtained from the data subject** (Art 14 notice duty on the club; template supplied) | Cache-first lookup of public ranking history; tenant-scoped PB cache and trust ledger | Hosting | UK→US (hosting) | Tenant-scoped cache; rate-limited fetching; retention schedule |
| A3 | **Achievement detection & ranking** | Athletes | Parsed results + PB snapshots; derived achievement flags (PB, medal, first-time) with confidence scores | Deterministic detectors/ranker produce content opportunities; explainable, source-grounded | Hosting | UK→US (hosting) | Deterministic, auditable engine; per-run audit trail |
| A4 | **Caption & creative generation (AI)** | Athletes featured on cards | Minimised payload: name (subject to tenant child-policy controls), event, time, achievement context, club tone/brand. **DOB/YOB and unneeded fields stripped at the boundary** | Cloud LLM generates captions/briefs; output escaped and human-reviewed | Google (Gemini), Anthropic (failover) | UK→US (SCCs/IDTA per provider DPA) | Payload minimisation; no training on API data per provider terms; prompt-injection controls |
| A5 | **Photo processing** | Athletes in club-supplied photos (incl. children) | Photo bytes; derived non-identifying metadata (orientation, dominant colours, has_face quality flag — **no face recognition**) | Background removal/cutout for cards; default is in-process on the server | Photoroom or Replicate **only if tenant/operator enables them**; otherwise none | UK→US/FR only when cloud cutout enabled | Default in-process processing; consent/permission status tracked per asset |
| A6 | **Card rendering & content packs** | Athletes featured | Name, achievement, time, club branding, photo | Server-side render (Playwright/Remotion) to PNG/MP4; stored per-run with explainability manifest | Hosting | UK→US (hosting) | Approval workflow; consent gate blocks opted-out/no-consent athletes |
| A7 | **Export of approved content** (human approval default) | Athletes featured on approved cards | Approved card image + caption (name, photo) | On club approval, content is exported/downloaded; the club posts it manually — MediaHub does not publish to social platforms (it is not a publication sub-processor). If the club posts, Meta/TikTok become independent controllers | Hosting (Render) — none for posting | UK→US (hosting) | Unbypassable approval gate; consent gate blocks opted-out/no-consent athletes; immutable audit ledger |
| A8 | **Data subject rights handling** (on club instruction) | Athletes / parents | All of the above for the named athlete | SAR export, rectification, erasure across all stores, restriction flag; Art 12A clock metadata | Hosting | UK→US (hosting) | Erasure-propagation tests; audit trail |

**Retention (per artifact class):** configurable per tenant with conservative
defaults and a scheduled purge — see `compliance/retention-and-minimisation`
(values pending sign-off, Q8).

## Part B — Controller record (Art 30(1)): operator's own processing

| # | Processing activity | Purpose | Lawful basis (proposed) | Data subjects | Categories | Recipients | Retention |
|---|---|---|---|---|---|---|---|
| B1 | **Club user accounts** | Authentication, account management, plan limits | Contract (Art 6(1)(b)) | Club staff/volunteers (adults) | Email, hashed password, role, plan, membership records | Hosting | Life of account + short tail |
| B2 | **Billing** (when enabled) | Subscription management | Contract; legal obligation (tax) | Club billing contacts | Email, customer ID (payment processor holds card data) | Payment processor, hosting | Statutory periods |
| B3 | **Security & access logging** | Security monitoring, abuse prevention, breach investigation | Legitimate interests (Art 6(1)(f)) | Users; indirectly athletes (pseudonymised identifiers only) | Event type, timestamp, user identifier, IP; **athlete identifiers pseudonymised in app logs** | Hosting | Short rolling window (see retention config) |
| B4 | **Service telemetry / LLM usage observability** | Reliability, cost control | Legitimate interests | Users | Aggregate counts, latency, token usage — no prompt contents with personal data | Hosting | Rolling window |
| B5 | **Complaints intake (s 164A DPA 2018)** | Statutory duty to facilitate and acknowledge data-protection complaints (from 19 Jun 2026) | Legal obligation (Art 6(1)(c)) | Complainants (athletes, parents, users) | Name, contact, complaint content | Hosting | Complaint lifecycle + accountability tail |
| B6 | **Incident/breach register** | Art 33(5) documentation duty | Legal obligation | Affected data subjects (by reference) | Incident facts, effects, remedial action | ICO when notifiable | Indefinite (accountability record) |

## Notes

- **General description of technical and organisational security measures**
  (Art 30(1)(g)/(2)(d)): summarised per row above; the full control set is
  the ASVS L2 programme documented in `docs/security/SECURITY_REPORT.md`
  (threat model, defence-in-depth controls, residual-risk register).
- This record must be updated whenever a processing activity, sub-processor,
  or retention default changes; it is reviewed alongside
  [`SUBPROCESSORS.md`](SUBPROCESSORS.md) at least annually.
