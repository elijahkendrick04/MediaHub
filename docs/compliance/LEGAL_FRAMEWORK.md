# MediaHub — UK/EU Data Protection Legal Framework

> **DRAFT — FOR LEGAL REVIEW.** This document was researched and written by an
> engineering agent against primary sources (legislation.gov.uk, ico.org.uk,
> EDPB/EUR-Lex, European Commission) as of **12 June 2026**. It is an
> engineering ground-truth document, not legal advice. Every point requiring
> legal judgment is logged in [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md).

**Scope.** MediaHub is a hosted (operator-managed) multi-tenant SaaS. Clubs
upload swim-meet results containing athlete personal data (names, year of
birth, sex category, club, race times); the platform enriches that data from
swimmingresults.org, detects achievements, renders branded social cards
(including names and, where supplied, photos of athletes — **most of whom are
under 18**), captions them via cloud LLMs (Google Gemini, Anthropic), and
packages them for human approval and export/download — the club then posts the
content manually; MediaHub does not publish to Instagram/Facebook/TikTok
itself. The data subjects at the centre of gravity are **child athletes**.

---

## 1. The UK framework: UK GDPR + DPA 2018 + PECR, as amended by the DUAA 2025

The governing instruments are:

- **UK GDPR** (retained EU Regulation 2016/679, as amended)
- **Data Protection Act 2018 (DPA 2018)**
- **Privacy and Electronic Communications Regulations 2003 (PECR)** (SI 2003/2426)
- **Data (Use and Access) Act 2025 (DUAA)** — Royal Assent 19 June 2025 —
  which amends all three. It does **not** replace them.

### 1.1 DUAA commencement status (verified against SI 2026/82)

The **Data (Use and Access) Act 2025 (Commencement No. 6 and Transitional and
Saving Provisions) Regulations 2026** (SI 2026/82) brought the main data
protection tranche of the DUAA into force:

| In force | Provision | Effect |
|---|---|---|
| **5 Feb 2026** | Sch 4 (lawfulness of processing) | "Recognised legitimate interests" — new Art 6(1) lawful basis with no balancing test for a closed list (Annex 1 UK GDPR): national security/public security/defence, emergencies, crime, safeguarding vulnerable individuals, responding to public-body requests. |
| **5 Feb 2026** | s 76 (time limits for responding to requests) | New **Article 12A** UK GDPR: codified "applicable time period" calculation for data subject requests, including **stop-the-clock** where the controller reasonably requires clarification or ID verification; searches need only be **reasonable and proportionate**. Saving: requests received before 5 Feb 2026 follow the old rules (reg 4). |
| **5 Feb 2026** | s 80 + Sch 6 (automated decision-making) | Article 22 replaced by **Articles 22A–22D**: solely-automated decisions with significant effects are now generally **permitted on any lawful basis** provided safeguards (information, human intervention, right to make representations, right to contest) — **except** decisions based on special category data, which keep the stricter regime. Applies to decisions made on/after 5 Feb 2026 (reg 5). |
| **5 Feb 2026** | s 81 (data protection by design) | **"Children's higher protection matters"** duty — see §2.2 below. |
| **5 Feb 2026** | s 112 + Sch 12 (PECR storage/access) | New PECR exemptions from cookie/storage consent, including a **statistical-purposes (analytics) exemption** — see §1.4. |
| **5 Feb 2026** | s 115 + Sch 13 (PECR enforcement) | **PECR fines raised to UK GDPR levels** (from the old £500,000 cap to up to £17.5m / 4% of global annual turnover). Regime applies based on conduct timing (reg 11). |
| **5 Feb 2026** | s 85 + Schs 7–9 (international transfers) | New transfer regime: third-country protection need only be **"not materially lower"** than the UK standard (replacing "essentially equivalent"). ICO updated its transfers guidance on 15 Jan 2026. |
| **5 Feb 2026** | ss 67–77 (various) | Statutory definition of scientific research; purpose-limitation/compatibility clarifications (when re-use is compatible with the original purpose); DSAR "reasonable and proportionate search" codified. |
| **19 Jun 2026** | s 103 + Sch 10 (complaints) | **New s 164A DPA 2018**: data subjects get a right to complain **to the controller**; controllers must **facilitate complaints (e.g. by providing an electronic complaints form)** and **acknowledge within 30 days**, responding without undue delay. Applies to complaints received on/after 19 June 2026 (reg 7). |

**Engineering consequences for MediaHub** (drives the Phase 1 gap analysis):

- **s 164A (19 June 2026)** — MediaHub needs an electronic complaints intake
  with a 30-day-acknowledgement workflow. This is the only hard *date-driven*
  deliverable (Phase 2 capability `compliance/complaints-and-breach`).
- **Article 12A** — SAR/erasure tooling should carry workflow metadata
  (received date, clarification-requested date, clock state, due date).
- **Articles 22A–22D** — MediaHub's pipeline (detection → ranking → caption)
  is automated *content suggestion*, and a human approves before publication,
  so it should not constitute solely-automated decision-making with
  significant effects; this analysis must be recorded and the human-approval
  gate must be technically unbypassable (Phase 3 `security/llm-pipeline`).
  Logged in OPEN_LEGAL_QUESTIONS (Q9).
- **Recognised legitimate interests** — the *safeguarding* RLI may be
  relevant to MediaHub's minor-protection gating, but RLIs are narrow;
  ordinary Art 6(1)(f) legitimate interests (with balancing) remains the
  realistic basis for most club processing. Logged (Q2).
- **PECR** — fines at UK GDPR level make the cookie audit (Phase 2
  `compliance/transparency-artifacts`) non-optional. See §1.4.

### 1.2 Core UK GDPR obligations that frame this whole programme

Unchanged by the DUAA and central to MediaHub:

- **Art 5** principles (lawfulness/fairness/transparency, purpose limitation,
  minimisation, accuracy, storage limitation, integrity/confidentiality,
  accountability).
- **Art 6** lawful bases; **Art 8** child's consent for information society
  services offered directly to a child — **UK age: 13** (s 9 DPA 2018).
- **Arts 12–14** transparency. **Art 14 applies squarely** to the
  swimmingresults.org enrichment: PB history is personal data **not obtained
  from the data subject**, so the controller owes athletes/parents an Art 14
  notice (source, categories, purposes) within one month/at first
  communication, unless an exemption applies (disproportionate effort is
  hard to claim when the club has direct contact with its own members).
- **Arts 15–22** data subject rights (access, rectification, erasure,
  restriction, portability, objection) — Phase 2 `compliance/data-subject-rights`.
- **Art 25** data protection by design/default (now including children's
  higher protection matters).
- **Art 28** processor contracts — MediaHub must offer clubs a DPA (§5).
- **Art 30** ROPA — Phase 1 deliverable.
- **Arts 32–34** security + breach notification (72 hours to the ICO where
  risk; without undue delay to data subjects where high risk) — Phase 2
  `compliance/complaints-and-breach` breach playbook.
- **Art 35** DPIA — processing children's data on a large scale, AI
  processing, and publication to social media each appear in the ICO's list
  of operations likely to require a DPIA; combined, **a DPIA is effectively
  mandatory** for MediaHub (Phase 2 `compliance/dpia`).

### 1.3 Special category data check

The swim-results data MediaHub processes — name, YOB/age group, sex category,
club, race times, placements, photos — is **not** special category data under
Art 9 as normally processed. Photographs are biometric (Art 9) **only when
processed through specific technical means allowing unique identification**
(e.g. face recognition), which MediaHub must therefore avoid: the
`has_face` detection in the media library must remain a yes/no quality
signal, never identification. Children's data is not "special category" but
attracts heightened protection through Art 8, Recital 38, Art 25(1) as
amended, and the Children's Code. Confirmed as Q5 in OPEN_LEGAL_QUESTIONS.

### 1.4 PECR position (cookies, marketing)

- PECR reg 6 requires consent for storing/accessing information on terminal
  equipment, with exemptions for **strictly necessary** storage (e.g. Flask
  session cookies used for login/security) and — **new from 5 Feb 2026** — a
  narrow **statistical purposes (first-party analytics) exemption**,
  conditional on clear information being given and a **straightforward
  opt-out** being offered. The ICO has signalled enforcement where opt-outs
  are not meaningful or "statistical purposes" is stretched.
- MediaHub's UI currently appears to use only the signed Flask session
  cookie (strictly necessary → exempt). Phase 2 will run a formal cookie
  audit; a consent banner is only needed if non-exempt cookies exist. If
  first-party analytics are ever added, they may fit the new exemption
  (notice + opt-out), **not** silent deployment.
- PECR marketing rules (reg 22) would bite only if MediaHub itself sends
  electronic marketing; transactional service emails are out of scope.

---

## 2. Children's data: the centre of gravity

### 2.1 ICO Children's Code (Age Appropriate Design Code)

A statutory code of practice under s 123 DPA 2018, in force since 2 Sept
2021, with **15 standards**: (1) best interests of the child; (2) DPIAs;
(3) age-appropriate application; (4) transparency; (5) detrimental use of
data; (6) policies and community standards; (7) default settings (high
privacy by default); (8) data minimisation; (9) data sharing; (10)
geolocation; (11) parental controls; (12) profiling; (13) nudge techniques;
(14) connected toys/devices; (15) online tools (to exercise rights).

The Code applies to **information society services likely to be accessed by
children** in the UK. MediaHub's *users* are adult club volunteers/coaches,
but its *data subjects* are largely child athletes, and its *outputs* are
published to platforms children certainly access. Whether MediaHub itself is
in the Code's formal scope is a legal-judgment call (logged as Q3); the
**defensible engineering default is to conform to the Code's standards
regardless**, because (a) the ICO treats Code conformance as the way to
satisfy the new Art 25(1) children's duty, (b) the club controllers MediaHub
serves owe children Recital 38-level protection either way, and (c) the
standards most relevant to MediaHub — best interests, DPIA, transparency,
detrimental use, defaults, minimisation, data sharing, online rights tools —
map directly onto Phase 2 capabilities. The ICO's Children's Code Strategy
progress update (Dec 2025) and the joint Ofcom/ICO statement on age
assurance (26 Mar 2026) confirm active enforcement focus on children's data
through 2026, and the ICO is updating Code guidance for the DUAA during 2026.

### 2.2 DUAA "children's higher protection matters" (Art 25(1) as amended)

From 5 Feb 2026, controllers providing information society services **likely
to be accessed by children** must, in their Art 25 design decisions, have
particular regard to:

1. how children can best be **protected and supported** when using the service;
2. the fact that **children merit specific protection** because they may be
   less aware of the risks and consequences of processing; and
3. the fact that **children have different needs at different ages and
   stages of development**.

ICO guidance states that conforming to the Children's Code satisfies this
duty. For MediaHub the concrete design translation (Phase 2
`compliance/childrens-code`) is per-tenant child-protection policy controls:
surname initialisation, age suppression, photo exclusion for under-18 posts,
the fact that MediaHub does not publish to social at all (minors' content,
like all approved content, is only ever exported for a human to post),
and consent/opt-out enforcement before any child appears on a card.

---

## 3. EU GDPR deltas (where an EU club or athlete is in scope)

The UK framework above governs the operator and UK clubs. If MediaHub
onboards an **EU-established club**, or **targets services at people in the
EU**, EU GDPR applies in parallel (Art 3), with these deltas:

- **Art 27 representative.** A non-EU controller/processor caught by Art 3(2)
  must appoint an EU-established representative, unless processing is
  occasional, does not include large-scale Art 9/10 data, and is unlikely to
  risk rights and freedoms. Regular processing of children's data weakens
  the exemption argument. **Decision needed before onboarding EU clubs**
  (Q6). The mirror-image UK Art 27 representative duty for non-UK
  controllers was **removed by the DUAA** for the UK regime.
- **Art 8 consent ages.** EU GDPR sets the digital-consent age default at
  **16**, with member-state derogations down to **13** (e.g. ~13 in Belgium,
  Denmark, Sweden, Finland, Estonia, Latvia, Malta, Portugal; 14 in Spain,
  Italy, Austria, Bulgaria, Cyprus, Lithuania; 15 in France, Greece,
  Czechia; 16 in Germany, Ireland, Netherlands, Hungary, Poland, Romania,
  Slovakia, Croatia, Luxembourg). The UK age is 13. If consent is the basis
  for any child-directed feature, the per-state age matters; the consent
  registry (Phase 2 `compliance/lawful-basis-and-consent`) therefore models
  **parental consent flags for all under-18s** rather than encoding a single
  age threshold. Exact per-state table to be confirmed at onboarding (Q6).
- **Transfers out of the EU.** EU→UK flows are covered by the **renewed UK
  adequacy decisions adopted 19 Dec 2025, valid to 27 Dec 2031** (with a
  four-year review). Onward transfers from the operator to US providers need
  EU SCCs or DPF (see §4).
- **EU representative for clubs** is the club's problem as controller, but
  MediaHub's Art 28 DPA template must work under both UK GDPR (IDTA/
  Addendum) and EU GDPR (2021 SCCs) — the template ships with both modules.

---

## 4. International transfers

### 4.1 The mechanisms as of June 2026

| Route | Mechanism | Status |
|---|---|---|
| UK → EU/EEA | UK adequacy regulations for the EEA | In force |
| EU → UK | Renewed Commission adequacy decisions (GDPR + LED) | Adopted **19 Dec 2025**, valid to **27 Dec 2031**; 4-year review |
| UK → US | **UK Extension to the EU–US Data Privacy Framework** ("UK–US data bridge", in force 12 Oct 2023) for DPF-certified recipients; otherwise **IDTA** or **EU SCCs + UK Addendum** + transfer risk assessment | In force |
| EU → US | **EU–US DPF** for certified recipients; otherwise 2021 EU SCCs + TIA | DPF upheld by the General Court (**Latombe dismissed, 3 Sept 2025**); appeal pending at the CJEU (**C-703/25 P**, no hearing date as of May 2026) |
| UK domestic test | DUAA "**not materially lower**" data protection test (s 85, from 5 Feb 2026); ICO transfers guidance updated 15 Jan 2026 | In force |

**Residual risk to record:** DPF reliance carries Schrems-style invalidation
risk while C-703/25 P is pending. MediaHub's sub-processor contracts should
prefer **SCCs/IDTA written into the DPA as the fallback mechanism** (which
Anthropic's and Google's standard terms already do), so a DPF invalidation
does not interrupt the lawful basis for transfers.

### 4.2 Where each provider processes personal data (for SUBPROCESSORS.md)

To be confirmed against each provider's current DPA at Phase 1, but the
verified positions:

| Provider | What it receives from MediaHub | Processing location | Mechanism |
|---|---|---|---|
| **Google (Gemini API, paid tier)** | Caption/brief prompts: athlete names, events, times, achievement context; media descriptions | US/global (Google Cloud); EU/UK regional endpoints exist via Vertex AI | Processor under Google's Data Processing Addendum; SCCs + UK Addendum incorporated. Paid-tier prompts are not used for model training; EEA/UK/CH customers get paid-tier data handling even on free tier per Google's regional commitments (verify at procurement) |
| **Anthropic (Claude API)** | Same caption/brief payloads (failover provider) | US | Commercial Terms incorporate DPA with SCCs + UK IDTA/Addendum; no training on API business data by default; sub-processor list in Trust Center |
| **Photoroom** (optional cutout) | Athlete photos (images of identifiable children when used) | France-based provider; transfers outside EEA possible via its sub-processors | GDPR processor terms; confirm DPA + sub-processor list at procurement |
| **Replicate** (optional cutout) | Athlete photos | US | Processor per privacy policy; DPA to be obtained; SCCs/IDTA needed |
| **Render** (hosting, reference target) | Everything (full database, uploads, rendered cards, logs) | US (region-dependent) | DPA with SCCs; **DPF-certified**; ISO 27001. The single most significant transfer: the entire athlete data store lives on the host |
| **swimmingresults.org** | Receives only HTTP requests containing athlete name (+ club) as search parameters; it is a **data source**, not a processor | UK (Swim England rankings) | Not a transfer in the Art 44 sense; the legal issue is Art 14/fairness/lawful basis for the *collection* — see Q4 |
| **ntfy / webhooks** (optional) | Operational notifications — must be kept free of athlete personal data (Phase 2 minimisation) | Configurable | Avoid personal data; else DPA needed |

**Engineering consequence:** LLM/image payload minimisation (Phase 2
`compliance/retention-and-minimisation`) directly shrinks the transfer
surface: DOB/YOB and anything not needed for the caption must be stripped
before a payload leaves the platform.

---

## 5. Controller / processor analysis (recommended allocation)

> Legal judgment — recommendation only; logged as **Q1** in
> OPEN_LEGAL_QUESTIONS.md for solicitor confirmation.

**Operating model:** the operator hosts MediaHub; clubs upload athlete data;
the platform enriches from swimmingresults.org and renders content for club
approval and export/download — the club posts it manually; the platform does
not publish to social channels.

**Recommended allocation (most defensible default):**

1. **Club = controller** for all athlete personal data: the club decides to
   use the service, which athletes' data to upload, whether to enable
   enrichment, what to approve, and what to export and post. The club holds the
   member relationship, determines purposes, and is the natural owner of the
   lawful basis, the Art 13/14 notices, and consent/opt-out collection.
2. **Operator (MediaHub) = processor** for that data, acting on the club's
   documented instructions under an **Art 28 DPA** the platform provides:
   storage, parsing, detection, ranking, rendering, captioning (including
   engaging Google/Anthropic/Photoroom/Replicate/Render as authorised
   **sub-processors**), and export/download of approved content for the club
   to post manually — the platform is not a publication sub-processor.
3. **The swimmingresults.org enrichment** is the delicate step: the platform
   designed it, but it should be framed as processing **on the club's
   documented instructions** — a per-tenant **opt-in** feature described in
   the DPA, so the club (controller) instructs the enrichment and owes the
   Art 14 notice (which MediaHub supplies as a template). If instead the
   operator enriched data for its own purposes (e.g. cross-tenant PB
   intelligence), it would become a **controller** of that processing —
   **the engineering must therefore keep the PB cache per-tenant-scoped** to
   preserve the processor framing. Joint-controllership risk logged (Q4).
4. **Operator = controller** in its own right only for: club **user
   accounts** (emails, passwords, roles), billing, service security logs,
   and aggregate service telemetry. This is standard SaaS dual-role.

This allocation is what the Phase 2 artifacts implement: club-facing Art 28
DPA template, club-facing Art 13 notice template, athlete/parent-facing
Art 14 notice template (mandatory because of the enrichment), sub-processor
disclosure page, and per-tenant lawful-basis + consent registry — i.e. the
platform gives club controllers the tools to actually be compliant.

---

## 6. Primary sources

- [SI 2026/82 — DUAA Commencement No. 6 and Transitional and Saving Provisions Regulations 2026](https://www.legislation.gov.uk/uksi/2026/82/made)
- [Data (Use and Access) Act 2025, s 81](https://www.legislation.gov.uk/ukpga/2025/18/section/81)
- [GOV.UK — DUAA 2025: plans for commencement](https://www.gov.uk/guidance/data-use-and-access-act-2025-plans-for-commencement)
- [ICO — Data (Use and Access) Act 2025 hub](https://ico.org.uk/about-the-ico/what-we-do/legislation-we-cover/data-use-and-access-act-2025/)
- [ICO — Statement on the commencement of the DUAA (Feb 2026)](https://ico.org.uk/about-the-ico/media-centre/news-and-blogs/2026/02/statement-on-the-commencement-of-the-data-use-and-access-act-duaa/)
- [ICO — Age appropriate design code](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/age-appropriate-design-a-code-of-practice-for-online-services/)
- [ICO — Children's Code Strategy progress update, Dec 2025](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/protecting-childrens-privacy-online-our-childrens-code-strategy/children-s-code-strategy-progress-update-december-2025/)
- [European Commission — renewal of UK adequacy decisions, 19 Dec 2025 (IP/25/3059)](https://ec.europa.eu/commission/presscorner/detail/en/ip_25_3059)
- [EDPB — opinions on draft UK adequacy decisions (2025)](https://www.edpb.europa.eu/news/news/2025/draft-uk-adequacy-decisions-edpb-adopts-opinions_en)
- [IAPP — General Court dismisses Latombe challenge to EU–US DPF (3 Sept 2025)](https://iapp.org/news/a/european-general-court-dismisses-latombe-challenge-upholds-eu-us-data-privacy-framework)
- [DLA Piper — commencement of the DUAA data protection provisions (Feb 2026)](https://privacymatters.dlapiper.com/2026/02/uk-commencement-of-the-data-protection-provisions-in-the-data-use-and-access-act/)
- [Google — Gemini API additional terms / Cloud Data Processing Addendum](https://cloud.google.com/terms/data-processing-addendum)
- [Anthropic — Privacy Center: DPA](https://privacy.claude.com/en/articles/7996862-how-do-i-view-and-sign-your-data-processing-addendum-dpa) / [Trust Center](https://trust.anthropic.com/)
- [Render — DPA](https://render.com/dpa) / [DPF certification changelog](https://render.com/changelog/render-achieves-certification-under-the-eu-us-data-privacy-framework)
