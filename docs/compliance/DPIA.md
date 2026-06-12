# Data Protection Impact Assessment (Article 35 UK GDPR)

> **DRAFT — FOR HUMAN SIGN-OFF.** Structured on the ICO's DPIA template.
> A DPIA is effectively mandatory here: large-scale processing of
> **children's data**, **AI processing**, and **publication to social
> media** each appear in the ICO's likely-high-risk indicators; MediaHub
> combines all three. This draft was prepared by engineering from the
> evidenced data map; the operator must review, complete the bracketed
> items, and sign. If any risk below remains HIGH after mitigations,
> consult the ICO before processing (Art 36) — tracked as Q11 in
> [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md).

**Processing under assessment:** the MediaHub service — ingestion of swim
meet results, PB-history enrichment from public rankings, achievement
detection, AI-assisted caption/creative generation, branded card/reel
rendering, and human-approved publication to social platforms, operated as
multi-tenant SaaS for clubs whose athletes are predominantly under 18.

**Signed off by:** _[name, role, date]_ — **REQUIRED before production use
with real club data.**

## Step 1 — Identify the need

Clubs already publish children's results manually (meet results are public
sporting records; clubs celebrate them on social media today). MediaHub
systematises this — which raises scale/consistency risks but also creates
the control points manual posting lacks (consent gating, child-identity
controls, audit trails, erasure).

## Step 2 — Describe the processing

Nature, scope, context, purposes: see [`DATA_MAP.md`](DATA_MAP.md)
(authoritative flows/stores) and [`ROPA.md`](ROPA.md) (activities A1–A8,
B1–B6). Data subjects: child and adult athletes; club staff. Sources:
club uploads; swimmingresults.org (data **not** from the data subject —
Art 14 notice template provided). Recipients: see
[`SUBPROCESSORS.md`](SUBPROCESSORS.md); social platforms become
independent controllers on publication.

## Step 3 — Consultation

- Club controllers: consulted via [the pilot programme — operator to
  record].
- Data subjects (athletes/parents): [operator to record — e.g. pilot-club
  parent communications]. The ICO Children's Code expects the best
  interests of the child to be evidenced; parent/athlete feedback should
  be captured during pilots.

## Step 4 — Necessity and proportionality

- Lawful basis: per-tenant, recorded by the club (consent or legitimate
  interests — Q2); enrichment per-tenant opt-in; publication of any
  under-18 gated on recorded (parental) consent in opt-in mode.
- Minimisation: caption payloads stripped of identifiers/DOB-level fields;
  notifications carry no athlete data; child-identity controls reduce
  published identifiability; retention schedule purges all artifact
  classes.
- Rights support: working SAR/rectification/erasure/restriction tooling;
  complaints intake with statutory acknowledgement; transparency
  templates.

## Step 5 — Risks (likelihood × severity → level)

| # | Risk to individuals | L | S | Level |
|---|---|---|---|---|
| R1 | A child is published without parental agreement (consent never collected, or collected wrongly) | possible | significant | **High** |
| R2 | A child's identity (full name + age + club + face) is broadcast and misused (grooming/locating risk) | possible | severe | **High** |
| R3 | Cross-tenant breach exposes one club's athlete data to another tenant | possible | significant | **High** |
| R4 | An erased/opted-out athlete reappears in content (stale caches, caption memory) | possible | significant | Medium-High |
| R5 | Athlete data sent to AI providers is retained/used beyond the contract | unlikely | significant | Medium |
| R6 | Longitudinal PB profiles of children are built without their knowledge (enrichment invisibility) | was probable | moderate | Medium |
| R7 | Indefinite retention accumulates years of children's data on a US-hosted disk | was certain | moderate | Medium |
| R8 | Hosting-provider compromise exposes the whole store | unlikely | severe | Medium |
| R9 | Prompt-injected upload manipulates captions into harmful content about a child | possible | moderate | Medium |

## Step 6 — Mitigations

| Risk | Measures (all shipped unless noted) | Residual |
|---|---|---|
| R1 | Consent registry with parental flags; **opt-in mode blocks approval/pack/publish without recorded parental consent**; minors never auto-publish (safeguarding gate); human approval default for everything | Low — depends on club operating its registry honestly (DPA obliges it) |
| R2 | Child-identity controls (surname initial + age suppression, ON for new orgs; photo exclusion available); consent gate; platform-side copies acknowledged in notices | Medium — published content is public by design; the control is the club's consent decision |
| R3 | Tenant scoping on routes/stores + isolation test suite; Phase 3 hardening (session, headers, isolation regression tests) | Low-Medium |
| R4 | Erasure walks every mapped store incl. caches and caption memory; suppression record blocks reappearance; erasure-propagation tests | Low |
| R5 | Paid-tier/API terms with no-training commitments; SCC/IDTA mechanisms; payload minimisation shrinks exposure | Low-Medium (contract risk, monitored annually) |
| R6 | Enrichment per-tenant opt-in; Art 14 notice template; tenant-scoped, 30-day-bounded caches; erasure reaches them | Low |
| R7 | Retention schedule + daily purge (180d uploads / 730d runs / 30d caches), tenant-tightenable | Low |
| R8 | Provider with ISO 27001 + DPF; 0600 file modes; Phase 3 at-rest/backup measures; breach playbook | Medium — accepted (hosting-provider compromise is a residual risk in any SaaS; documented in SECURITY_REPORT) |
| R9 | Human approval before publication (unbypassable); prompt delimiting + injection screening (Phase 3 `security/llm-pipeline`); output is text-only, never executes | Low-Medium |

## Step 7 — Outcomes

- No risk is assessed as HIGH **after** mitigations — **subject to the
  human reviewer agreeing**. If the reviewer scores any residual as high,
  Art 36 prior consultation with the ICO applies before processing.
- Review cadence: re-run this DPIA on any change to: data categories,
  sub-processors, the enrichment, autonomy levels, or tenant model.
