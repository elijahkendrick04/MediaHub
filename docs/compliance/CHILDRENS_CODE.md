# Children's Code — design choices against the 15 standards

> **DRAFT — FOR LEGAL REVIEW.** How MediaHub's design answers the ICO Age
> Appropriate Design Code's standards and the DUAA "children's higher
> protection matters" duty (Art 25(1) UK GDPR, in force 5 Feb 2026).
> Scope caveat: whether MediaHub itself is formally in the Code's scope is
> Q3 in [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md); we conform
> regardless — the data subjects are children, and the ICO treats Code
> conformance as satisfying the Art 25(1) duty.

The product reality the standards must answer: clubs publish content
**about** child athletes to public social platforms. The child is rarely
the user; the risk surface is **identifiability of the child in published
content**, plus the longitudinal performance profile the PB enrichment
builds.

| # | Standard | MediaHub's answer |
|---|---|---|
| 1 | **Best interests of the child** | Publication of a child requires a recorded basis (consent registry; opt-in mode for youth squads); minors can **never** be auto-published (safeguarding gate, ADR-0003 — every minor card is a human decision); identity controls reduce identifiability by default. |
| 2 | **DPIAs** | [`DPIA.md`](DPIA.md) (children + AI + social publication makes one effectively mandatory). |
| 3 | **Age appropriate application** | Age (age-at-day) is parsed from results and rides every card's internal facts; under-18 status drives the consent rules, the safeguarding gate and the content controls. Unknown age is treated as under-18 by the consent opt-in mode and the photo control (fail-safe). |
| 4 | **Transparency** | Child-readable athlete/parent notice ([`templates/PRIVACY_NOTICE_ATHLETE_ART14.md`](templates/PRIVACY_NOTICE_ATHLETE_ART14.md)) covering the rankings enrichment, the AI captioning, and the right to say no. |
| 5 | **Detrimental use** | Content celebrates achievement only; the brand-safety gate blocks banned phrasing; no advertising/profiling use of children's data; LLM payloads are minimised (no DOB-level data leaves the platform). |
| 6 | **Policies & community standards** | This document set + the publish gate enforce what the notices promise. |
| 7 | **Default settings (high privacy by default)** | **New organisations default to surname initialisation + age suppression ON** for under-18s ("Eira H.", no age shown). Photo exclusion is per-club opt-in (photos enter only via the club's own permission-tracked media library). Legacy organisations keep prior behaviour until they visit the settings — flagged honestly as a migration decision for the operator. |
| 8 | **Data minimisation** | Art 5(1)(c) work in `compliance/retention-and-minimisation`: caption payloads carry only what the caption needs; ASA IDs/DOB never leave; notifications carry no athlete data. |
| 9 | **Data sharing** | Sub-processor disclosure page (`/legal/subprocessors`); social platforms flagged as independent controllers in the notices; consent gate stands between every child and every share. |
| 10 | **Geolocation** | Not processed (venue of a public meet is event data, not child geolocation). |
| 11 | **Parental controls** | The consent registry models **parental consent explicitly** (grants for under-18s must be marked parental in opt-in mode); parents exercise rights via the club + `/complaints`. |
| 12 | **Profiling** | The PB enrichment builds a performance history: per-tenant **opt-in**, Art 14 notice template provided, caches tenant-scoped and retention-bounded (30 days), erasure reaches them. No behavioural profiling exists. |
| 13 | **Nudge techniques** | None; the UI's only "nudge" is privacy-positive (controls on by default for new orgs). |
| 14 | **Connected toys/devices** | Not applicable. |
| 15 | **Online tools** | Working rights tooling: `/organisation/athlete-rights` (SAR/rectify/erase/restrict), `/complaints` (30-day acknowledged), opt-out honoured everywhere immediately. |

## The three content controls (per tenant)

| Control | Effect | Default (new orgs) |
|---|---|---|
| `child_surname_initial` | Under-18s appear as "Eira H." on cards/captions; full name kept internally (`raw_facts.full_name`) so consent matching and erasure still work | **On** |
| `child_suppress_age` | No age / age-group on content; age kept internally for the safeguarding + consent gates | **On** |
| `child_exclude_photos` | Athlete-photo roles never matched for under-18 (or unknown-age) content — cards render text-led | Off (opt-in) |

Enforcement points: pipeline (achievements transformed **before** cards are
persisted, so stills/captions/reels inherit), the LLM caption boundary
(backstop for legacy runs), and media selection (photo exclusion). The
autonomous publish path cannot carry a minor at all (safeguarding gate), so
these controls govern the human-approved surface.

## Honest limitations

- Legacy profiles keep pre-existing behaviour until the club (or the
  operator) turns the controls on — recorded as an operator migration
  decision, not silently flipped.
- Age unknown ⇒ identity transforms don't apply (no age to key on), but
  the consent opt-in mode and the photo control treat unknown age as
  under-18.
- Once published, platform-side copies are outside MediaHub's control —
  stated in the notices and the erasure report.
