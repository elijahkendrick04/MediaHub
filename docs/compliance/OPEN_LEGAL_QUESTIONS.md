# Open Legal Questions — for human / solicitor review

> **DRAFT — FOR LEGAL REVIEW.** Every item here is a point of legal judgment
> that engineering has NOT decided. For each, the implemented behaviour is the
> most defensible default; a solicitor (or the operator, on advice) must
> confirm or redirect. Nothing on this list is to be treated as silently
> settled. Companion document: [`LEGAL_FRAMEWORK.md`](LEGAL_FRAMEWORK.md).

| # | Question | Engineering default implemented | Status |
|---|---|---|---|
| Q1 | **Controller/processor allocation.** Is club = controller, operator = processor (with operator as independent controller only for accounts/billing/security telemetry) the correct allocation? See LEGAL_FRAMEWORK §5. | Built as club-controller / operator-processor: per-tenant lawful-basis config, club-facing Art 28 DPA template, operator never decides publication. | OPEN |
| Q2 | **Lawful basis for clubs.** Which Art 6 basis should clubs rely on for (a) processing results data, (b) the swimmingresults.org enrichment, (c) publishing children's names/photos to social media? Legitimate interests with balancing vs consent — and whether publication of a child's image can ever rest on legitimate interests rather than (parental) consent. | Per-tenant lawful-basis setting with no hardcoded answer; publication of any under-18 athlete is gated on a recorded consent/opt-in with parental flag, the strictest default. | OPEN |
| Q3 | **Children's Code formal scope.** Is MediaHub itself an "information society service likely to be accessed by children" (users are adult volunteers, data subjects are children)? Same question for the DUAA Art 25(1) higher-protection duty. | Conform to the Code's standards regardless of formal scope (ICO treats conformance as satisfying the Art 25 duty). | OPEN |
| Q4 | **swimmingresults.org enrichment.** (a) Lawful basis and fairness of scraping athletes' PB history (data not collected from the data subject); (b) the Art 14 notice route to athletes/parents (via the club) and whether any exemption applies; (c) Swim England website terms / database-right exposure; (d) does the platform's design of the enrichment make the operator a (joint) controller of that step? | Enrichment is per-tenant opt-in, framed as processing on the club's documented instructions; PB cache kept tenant-scoped; Art 14 template notice supplied to clubs; scraping is rate-limited and cache-first. | OPEN |
| Q5 | **Special category data.** Confirm none is processed: sex category in results is not Art 9 data; photos are not biometric data absent identification-by-technical-means; no health inference from performance data. Confirm `has_face` stays a non-identifying quality signal. | Treated as no Art 9 processing; face *recognition* is prohibited in code and docs. | OPEN |
| Q6 | **EU onboarding pre-conditions.** If an EU club or EU-resident athletes come into scope: (a) is an Art 27 EU representative required (children's data weakens the "occasional processing" exemption); (b) which member-state Art 8 consent ages apply; (c) EU SCC module selection in the DPA. | No EU clubs onboarded yet; DPA template ships both UK (IDTA/Addendum) and EU (2021 SCC) modules; consent registry uses parental flags for all under-18s rather than a single age threshold. | OPEN |
| Q7 | **Transfer mechanism preference.** Should the operator rely on the UK–US data bridge / EU–US DPF where available, or on SCCs/IDTA as primary given the pending CJEU appeal (C-703/25 P)? Transfer risk assessments needed per sub-processor under the post-DUAA "not materially lower" test. | Sub-processor records list both; contracts that embed SCCs/IDTA as fallback preferred; TRAs flagged as a Phase 1/2 artifact. | OPEN |
| Q8 | **Retention defaults.** What retention periods are defensible per artifact class (raw uploads, parsed results, rendered cards, PB cache, LLM payload logs, security logs)? Engineering will ship configurable retention with a scheduled purge; the *default values* need sign-off. | Conservative defaults, documented per class in the retention capability; clubs can shorten. | OPEN |
| Q9 | **Automated decision-making (Arts 22A–22D).** Confirm the pipeline (detect → rank → caption → human approval before publication) is not "solely automated decision-making producing legal/significant effects", including the per-type `fully_autonomous` opt-in (which never covers minors and passes a publish gate). If the autonomous path is in scope, the Art 22B/22C safeguards must be formalised. | Human-approval gate enforced in code; autonomous path excludes minors, is per-type opt-in, gated and audited; analysis recorded, not assumed. | OPEN |
| Q10 | **s 164A complaints + Art 12A workflows.** Confirm the complaints intake (electronic form, 30-day acknowledgement) and the SAR stop-the-clock metadata reflect the final ICO guidance, which is still being rolled out through 2026. | Built to the statutory text (SI 2026/82; s 103 DUAA); revisit when ICO publishes final guidance. | OPEN |
| Q11 | **DPIA sign-off.** The draft DPIA (children's data + AI + social publication makes one effectively mandatory) requires a named accountable human reviewer on the operator side, and consultation expectations (e.g. whether residual high risk would require prior ICO consultation under Art 36). | DPIA drafted on the ICO template, marked DRAFT, not self-approved. | OPEN |
| Q12 | **Publication boundary.** On publication to Instagram/Facebook/TikTok, the platforms become independent controllers. Confirm how far the club's notices/consents must go in warning about platform-side processing (indexing, ad profiling of published children's content), and whether per-post parental consent or a standing consent suffices. | Notices template flags platform-side processing; standing per-athlete consent with revocation honoured for *future* packs (published posts are outside MediaHub's control — noted honestly). | OPEN |

## How to use this register

- Each Phase 2 capability that touches one of these questions links back to
  it from the PR and the relevant doc.
- When a question is answered, record the answer, the date, who decided, and
  any change of engineering default; move the row to a "Resolved" section
  rather than deleting it.
- New legal-judgment points discovered during later phases are appended here
  — never silently decided in code.
