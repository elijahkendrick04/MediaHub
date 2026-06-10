# MediaHub: A Hard-Nosed Scaling Diligence

## TL;DR
- **A solo, unfunded founder reaching £1M ARR with MediaHub is *possible but improbable* (~10–20% over 3–5 years); "£1M/month" (~£12M ARR) is effectively unreachable for a solo→small team and should be dropped as a goal.** The swimming-only beachhead is mathematically too small to ever hit £1M ARR; the realistic swimming-only ceiling is roughly £150k–£400k ARR. Crossing £1M requires multi-sport expansion *plus* selling to schools/governing bodies, and almost certainly a second person.
- **No method gives >95% probability of a £1M revenue *outcome*. What deserves >95% confidence are specific *decisions*:** build self-serve billing and true multi-tenancy before scaling, kill or fence the "free self-host" promise, raise prices well above £30/mo, and validate with ~10 paying clubs before generalising. These are near-certain to improve the odds; the revenue target itself never gets above ~20% confidence for a pre-launch solo venture.
- **The single biggest existential risk is not a swim incumbent — it is the horizontal commodity (Canva, Predis.ai, and Gipper's new auto-achievement graphics) combined with the volunteer buyer's near-zero willingness to pay.** Encouraging diligence finding: no swim-data incumbent (SwimTopia, TeamUnify/SportsEngine, Swimcloud, Hy-Tek) currently ships automated social-content generation — the white space is real, but it is narrow and undefended by patents, and it is a head-start, not a wall.

## Key Findings

**1. The swimming beachhead is tiny and caps revenue hard.** Swim England reports "175,653 club members (as of December 2024)" and **931 affiliated clubs** (Swim England Insight); Scottish Swimming ~160, Swim Wales ~80–90, Swim Ireland ~160 — roughly **1,300 UK & Ireland affiliated swim clubs**. USA Swimming had **2,740 club teams in 2024** (up from 2,677 in 2023) and 376,479 individual members, per its 2024 Demographic Report. Global affiliated competitive swim clubs are on the order of ~10,000–15,000. At the contemplated £30/mo "Club" tier, even capturing an implausible 50% of all UK & Ireland swim clubs (~650 clubs) yields only ~£234k ARR. £1M ARR at £30/mo needs **~2,778 paying clubs** — more than double every UK affiliated club, or essentially every USA Swimming club. The arithmetic alone kills "swimming-only £1M."

**2. Willingness-to-pay among volunteer-run clubs is the binding constraint.** Swim Wales club affiliation is just £150/year for the *entire* NGB relationship — that anchors how little a volunteer treasurer expects to pay for anything. Club-management incumbents that touch *money* (registration, billing) can charge more because they are mission-critical: SwimTopia is billed **annually at roughly $150–$699/year** (e.g. summer teams ~$179 first year/$199 thereafter for 50 athletes up to ~$529/$699 for 300 athletes, plus ~$2.50/extra athlete; schools from ~$200/$250), and TeamUnify runs ~$6–12/swimmer/mo. A content tool is "nice-to-have," not "can't-run-the-club-without-it," so it sits lower on the WTP ladder and churns faster.

**3. The closest successful analog, Gipper, took venture capital and sells to schools — not volunteer clubs.** Per Tracxn, Gipper "raised a total funding of $12.1M over 2 rounds… latest funding round was a Series A on Dec 15, 2022 for $8.63M" (led by Telescope Partners; $2.7M seed Nov 2021). It employs ~29–40 people, sells to US K-12/college athletic departments at **$625/year entry (verified on its pricing page)** up to custom quotes around $1,500–$3,000, and claims 20,000+ customers (vendor self-claim; a third-party source lists ~4,000 — a definition/recency gap, unaudited). Its growth came from a recession-resistant buyer (schools with fixed budgets, strong retention) and a sales team — not a free self-host product and not a solo founder. Critically, Gipper now markets itself as "AI & automation powered" and has launched an "Athletic Achievement" auto-graphic template — moving toward MediaHub's exact thesis.

**4. Enterprise sports-content is a different universe, gated by capital.** WSC Sports raised ~$155M with revenue in the "tens of millions"; Greenfly raised ~$14M+ and serves the NBA/MLB/NHL; Hudl is a 9-figure-revenue business (third-party estimates range wildly $132M–$730M, none official) with 300k+ teams and now ships AI auto-highlights and vertical social reels (video, via its Balltime acquisition — adjacent to, but not overlapping, MediaHub's results-to-graphics core). These define the enterprise ceiling and confirm a solo founder cannot enter it directly. Content Stadium (170–200+ sports orgs) sits mid-market with quote-based pricing. **FanWord is the most relevant template:** an AI written-storytelling company working with 190+ college athletic organisations on multi-year deals — a focused content-AI business growing via repeatable institutional sales.

**5. The horizontal commodity is the price-anchor and the real threat.** Predis.ai ($19–$249/mo), AdCreative.ai (acquired by Appier for **$38.7M total, ~$27.3M base, completed March 2025**), Ocoya, Vista Social and Canva all generate branded social content cheaply. They don't ingest HY3/SDIF swim data — that's MediaHub's moat — but they set the buyer's mental price ceiling at $20–60/mo and erode the "AI content is special" narrative.

**6. The bootstrapped solo-SaaS base rates are brutal.** Across ~1,000+ micro-SaaS analysed, ~40% never reach $1k MRR, ~70% sit under $1k MRR, only ~18% reach the $1k–$5k MRR "sustainability zone," and roughly the top 10% break $20k MRR. Median time to $1M ARR for those that get there is ~2 years 9 months; best-in-class ~9 months. Solo founders are ~42–46% of micro-SaaS, so going solo is not disqualifying — but $1M ARR is a top-decile-or-better outcome, hence the ~10–20% ceiling estimate even with strong execution.

**7. SMB/volunteer churn compounds against you.** SMB-focused SaaS runs 3–7% monthly churn (≈31–58% annual); ~70% of SMB churn hits in the first 90 days; annual (not monthly) billing cuts churn ~30–40%. For a seasonal, volunteer-run buyer this is worse than typical SMB, making annual prepay and tight onboarding non-negotiable.

**8. "Free self-host" is value-destroying for a revenue-max goal as currently framed.** Open-source/freemium free-to-paid conversion is ~2–5% (good), 6–8% (great), and often below 1% for developer-grade free tiers. A genuinely free, "no-hidden-fees" self-host option hands the most motivated power users a permanent zero-revenue escape hatch — the inverse of open-core, where the free tier deliberately *lacks* what serious users need (managed hosting, scale, support, integrations).

## Details

### Market sizing (bottom-up, realistic price points)

**UK & Ireland affiliated swim clubs (~1,300):** Swim England 931; Scottish Swimming ~160; Swim Wales ~80–90; Swim Ireland ~160.
- At £30/mo (£360/yr): 100% capture of UK&I ≈ £468k ARR; realistic 20–35% share ≈ £94k–£164k ARR. This is the hard ceiling making swimming-only a lifestyle business at best.

**USA Swimming clubs (~2,740):** the single biggest swim pool. At a more defensible $50/mo, full capture ≈ $1.6M; realistic 15–25% ≈ $247k–$411k. Reaching even this requires US go-to-market a solo UK founder cannot easily run.

**Global competitive swim clubs (~10,000–15,000 est.):** at $50/mo and an optimistic 10% global share ≈ $600k–$900k ARR — still short of £1M and operationally implausible solo.

**Multi-sport UK expansion is where the math changes.** The Sport and Recreation Alliance's Sports Club Survey found **151,000 sports clubs in the UK** across more than 100 sports; rugby union alone has ~2,000 clubs and football thousands of grassroots clubs, plus thousands of secondary schools and universities. This is the only path that makes £1M+ arithmetically credible — but it dilutes the swim-data moat (see risks).

**US schools/colleges (the Gipper market):** NFHS represents ~19,500 high schools; the NCAA ~1,100 member schools, NAIA ~235, plus NJCAA. This is the highest-WTP, highest-volume English-language market and the most defensible for a content product — but the hardest to reach solo and the one where Gipper, FanWord and Hudl already operate.

### SOM verdict
A realistic Serviceable Obtainable Market for a swimming-first tool, sold solo from the UK at £30–50/mo with SMB-grade churn, is on the order of **£150k–£400k ARR within 3–5 years.** Crossing £1M requires either (a) multi-sport UK breadth at higher prices, or (b) cracking US schools/governing bodies — both of which require a second person and a real sales motion.

### Willingness-to-pay ladder (by buyer segment)
- **Volunteer grassroots club:** £0–£40/mo. Anchored by ~£150/yr NGB affiliation and free Canva. Highest churn. Lowest WTP.
- **School athletic dept (US):** $625–$3,000/yr (Gipper-proven), fixed budgets, strong retention, **2–18 month procurement, committee buying.** Best volume + retention combination.
- **University / college athletics:** mid-four to low-five figures/yr (FanWord multi-year deals), relationship-led.
- **National federation/governing body:** five-to-six figures, very long cycles. One deal *could* reach hundreds of clubs, but the *promotional-endorsement* form of this channel is now down-weighted to speculative — see **Evidence refresh — cycle 3** (NGB distribution-channel reality check) below; the *evidenced* NGB mechanism is approved data-API access, not promotion.

### Incumbent-bolts-on-content threat: currently LOW, but watch closely
Diligence found **no swim-data incumbent shipping auto social-content generation.** SwimTopia, TeamUnify/SportsEngine, Swimcloud and Hy-Tek/MeetMobile auto-surface PBs/results (Swimcloud Pro auto best-times; SwimTopia "Best Times"; MeetMobile personal bests) but stop at data display and manual sharing. The white space MediaHub targets is genuinely open. Caveats: (1) SwimTopia's own 2025 marketing already describes auto-flagging records and making them "instantly shareable" as where software "should" go — intent is visible; (2) SportsEngine/TeamUnify changed ownership (PlayMetrics, 2026), which could refocus or de-prioritise swim; (3) any incumbent already holding clean results + PB data could bolt this on faster than MediaHub can build distribution. The moat is a time advantage, not a defensible wall.

### Business-model & architecture pressure tests
- **Single-instance-per-club cannot scale and is the #1 thing to fix.** Manually standing up one deployment per club means per-customer ops, support and infra costs that rise linearly while a solo founder's hours are fixed — margins and sanity collapse somewhere around 15–40 clubs. The standard fix is true multi-tenant SaaS (org→workspace isolation in one shared instance) + self-serve signup + Stripe billing. Until this exists, every new customer makes the founder *poorer* in time.
- **The build/sell imbalance is severe.** 164k lines of code, 2,836 tests, zero billing, zero customers. The evidence on over-building before validation is unambiguous: distribution — not product — kills ~99% of solo ventures; ~72% of successful indie hackers credit distribution over product as decisive. The corrective sequence is to stop building features and start manufacturing pipeline and revenue.
- **Pricing model:** flat monthly is right for clubs (per-seat confuses volunteers); annual prepay is essential for churn; £30/mo is too low to ever reach the goal and underprices the value. Move to ~£49–£99/mo for clubs billed annually, plus a £250+/mo federation/multi-team tier.
- **Free self-host:** as framed ("truly free, no hidden fees"), it cannibalises revenue. If kept at all, it should be a lead-gen/goodwill artifact that deliberately excludes managed hosting, auto-publishing, support SLAs and multi-tenant admin — the things institutions actually pay for.

## Recommendations (staged, with confidence bands and thresholds)

**Stage 0 — Commercialise before generalising (>95% confidence these are the *correct decisions*; do all now)**
1. Build self-serve signup + Stripe billing + true multi-tenancy. **Freeze all multi-sport roadmap work until this ships.** *Benchmark to proceed: a club can sign up, pay, and publish with zero founder involvement.*
2. Reprice: Club tier £49–£99/mo billed annually; Federation £250+/mo. Kill the £30 anchor.
3. Convert "free self-host" into a capped funnel tier (no managed hosting/auto-publish/support). *If you keep true-free self-host, accept that the revenue ceiling drops materially.*
4. Hand-sell to the first ~10 paying Swansea/Wales/England swim clubs yourself. *Benchmark: 10 clubs paying annually before spending a day on football/basketball.*

**Stage 1 — Saturate UK swimming, prove retention (~60–70% confidence this yields a repeatable pipeline; revenue outcome lower)**
5. Engage the governing-body channel as **two distinct mechanisms** (re-weighted cycle 3, see below): **(a)** apply for **approved data-API access** (Swim England’s Oct-2025 approved-systems API, open to commercial orgs) — evidenced, available, and the concrete first action, but it grants *data, not promotion*; **(b)** a *promotional* NGB endorsement that reaches hundreds of clubs — **down-weighted to speculative** (no evidence any NGB promotes a third-party content tool; partner slots are category-exclusive and already held). *Threshold: if no NGB/region will pilot or promote after 6 months, treat the promotional channel as speculative and lean on direct + word-of-mouth.*
6. Target ~150–250 paying UK&I swim clubs at £49–£99/mo annual = **~£90k–£250k ARR.** *This is the realistic swimming-only ceiling; if you stall below ~50 clubs, product-market fit isn't there — fix retention before expanding.*

**Stage 2 — The only credible £1M+ routes (require a second person; mark expansion steps <80% confidence)**
- **Route A — Multi-sport UK grassroots (broadest TAM, weakest moat):** generalise to football/rugby/running clubs and UK schools. ~151,000 UK sports clubs means even a fraction at £49–£99/mo annual reaches £1M. *Risk: per-sport data integrations are non-transferable engineering, and you compete head-on with Canva/Predis. Confidence of £1M: ~15–20%.*
- **Route B — US schools/colleges (highest WTP, proven by Gipper/FanWord):** reposition as results-driven achievement graphics for US athletic departments at $625–$3,000/yr. *Requires US sales presence and competing with funded incumbents, but offers the strongest math and a wedge incumbents lack (auto results-to-graphics). Confidence of £1M solo: <15%; meaningfully higher with a US-based partner/hire.*
- **Route C — Integration/content layer for swim-data incumbents (de-risks distribution):** rather than fight SwimTopia/TeamUnify, license/sell the content engine as the layer they lack. *Trades upside for survival probability and could be the most realistic high-value exit. Confidence it beats going direct: ~50/50.*

**Highest-leverage combination overall:** governing-body **data-API access + incumbent integration (Route C)** (Stage 1 #5) for *distribution* + US-schools repositioning (Route B) for *revenue*. (Earlier drafts named *promotional NGB endorsement* here; cycle 3 down-weighted it to speculative — see below.)

## Caveats
- Several scale figures are vendor self-claims or third-party algorithmic estimates (Gipper's 20,000 customers and ~$4.4M revenue; Hudl's ARR range $132M–$730M; global swim-club totals). Treated as directional, not audited.
- Provisional MediaHub pricing (£30/£250) is from the codebase, not validated with buyers; the repricing recommendation assumes the value is real but unproven.
- The >95% confidence band applies only to the *decisions/tactics* listed, never to a revenue outcome. No pre-launch solo venture can have >95% confidence of any specific ARR.
- Precise UK secondary-school/university counts and an exact global swim-club total could not be fully verified within research budget and are estimated; the strategic conclusions do not hinge on their exact values.
- **"£1M/month" (~£12M ARR) is not a realistic target for a solo→small team in this market on any evidence reviewed, and should be dropped.** Be honest with yourself: the most likely good outcome here is a £150k–£400k sustainable swimming business, with a low-double-digit-percent shot at £1M+ if and only if you expand sport coverage or buyer segment and add a second person.

---

## Evidence refresh — 2026-06-09 (strategy engine)

Re-verified the two load-bearing market-size anchors the swimming-only revenue
ceiling rests on; both still hold, so the £150k–£400k swimming-only cap is unchanged:

- **USA Swimming ≈ 2,740 member clubs/teams** — confirmed for 2024 (the body added 63
  club teams to reach 2,740). Some sources cite "2,800+" or "3,100+ registered via LSCs";
  ~2,740 remains the conservative, defensible figure used here. *[Source: SwimSwam,
  "USA Swimming Membership Stays Stable In 2024", swimswam.com.]*
- **Swim England 1,200+ affiliated clubs** — Swim England states it "supports over 1,200
  affiliated swimming clubs". The roadmap's "~1,300 UK&I affiliated" (England + Wales +
  Scotland + Ireland) is consistent with this once the other home nations are added.
  *[Source: Swim England, swimming.org/swimengland.]*

Implication: no change to the revenue-ceiling math or to Routes A/B/C. The arithmetic
that caps swimming-only at ≈ £150k–£400k ARR (and forces multi-sport breadth +
institutional buyers + a second person for £1M+) stands on current figures. Logged so the
anchors carry a 2026-06 verification date rather than drifting unverified.

---

## Evidence refresh — 2026-06-09 (strategy engine, cycle 2: PC.4 price comparators)

Refreshed the competitor-pricing anchors underpinning the PC.4 repricing hypothesis with
**current, directly-verified vendor pricing** (the prior figures were a mix of dated and
estimated). These feed the sourced comparator table now in ROADMAP §PC.4.

- **Gipper — $625 / $1,500 / $3,000 per year, annual payment only.** Verified directly on
  gipper.com/pricing (2026-06-09): Basic $625/yr (≤2 users), Pro $1,500/yr (≤30 users),
  Premier $3,000/yr (unlimited users); 14-day free trial; "we currently only offer annual
  payment plans." This *replaces* the earlier "$625 entry up to ~$1,500–$3,000 custom
  quote" with exact, current public tiers, and independently confirms two diligence
  conclusions: (a) the proven analog sells to **schools with budgets, not volunteer
  clubs**, and (b) **annual-only billing** is the norm for this buyer (validating PC.4's
  annual-prepay requirement). *[Source: gipper.com/pricing, accessed 2026-06-09.]*
- **Predis.ai — $19 / $40 / $212 per month** (Core / Rise / Enterprise+; annual-billed
  equivalents $230 / $474 / $2,540). Verified directly on predis.ai/pricing (2026-06-09).
  This narrows the earlier "$19–$249/mo" band to a current $19–$212/mo and keeps Predis as
  the **horizontal-commodity price anchor** that caps the volunteer buyer's mental price
  for "AI makes my posts" — it does *not* ingest results/PB data (still MediaHub's wedge),
  but it sets the ~$20–60/mo expectation. *[Source: predis.ai/pricing, accessed 2026-06-09.]*

Unchanged anchors carried forward from the body of this report (not re-verified this
cycle, cited as-is): SwimTopia ~$150–$699/yr annual; Swim Wales NGB affiliation £150/yr;
Canva Free £0.

**Implication for the plan:** no change to the revenue-ceiling math or Routes A/B/C. The
refresh hardens PC.4 from an *assumed reprice* into an *evidence-gated price-discovery
step* — the candidate Club £49–£99/mo / Federation £250+/mo levels remain an explicitly
unvalidated hypothesis, to be confirmed by revealed WTP (≥5 clubs paying annual prepay at
a tested price) before any public list price is locked. The >95% standard attaches to that
gating *decision*, never to the price levels or a revenue outcome.


---

## Evidence refresh — 2026-06-09 (strategy engine, cycle 3: NGB distribution-channel reality check)

**Why:** the body of this report calls a national-governing-body (NGB) "endorsement or
reseller arrangement" *"the single highest-leverage channel (one deal reaches hundreds of
clubs)"* and the roadmap's PC.6 leaned on it as the top distribution play — but that claim
was **asserted, never evidenced.** Distribution is the binding constraint, so this is the
most load-bearing unproven assumption on the revenue path. Reality-checked against current,
dated Swim England / Swim Wales sources.

**Findings (Swim England, the largest UK&I home nation, ~1,200+ affiliated clubs):**

- **There IS a real, dated NGB software channel — but it is a DATA-ACCESS programme, not a
  promotional endorsement.** Swim England launched a **secure "approved-systems" API**
  (announced **1 Oct 2025**, updated 17 Oct 2025) that lets *approved* platforms read
  official swim times/PBs directly from its databases. Initial approved partners are the
  **club-administration platforms Swim Club Manager and Swim Manager.** The announcement
  explicitly invites *"commercial organisations interested in benefiting from the Swim
  England API"* to apply (a named contact route), and states it is *"a small step towards
  our strategic goal of a connected digital eco-system, with more to follow in 2026."*
  *[Source: Swim England, "Swim England teams up with club management systems to simplify
  swim-time access," swimming.org, published 2025-10-01, accessed 2026-06-09.]*
  → **Implication:** approved API access is a high-confidence-available, evidenced first
  NGB action that strengthens MediaHub's deterministic **data moat** + credibility. It is
  **not** a mechanism that pushes the tool to hundreds of clubs.

- **No evidence any NGB *promotes/endorses* a third-party CONTENT tool to its member
  clubs.** Swim England's partner slots are **category-exclusive and already occupied** by
  incumbents: **SportsEngine (ex-TeamUnify) = "preferred technology supplier" for swim
  schools** with discounted pricing for affiliated swim schools *[Source:
  sportsengine.com/motion/uk/swim-england, accessed 2026-06-09]*; **GoCardless = "Official
  Payments Partner"** *[Source: gocardless.com/swim-england-official-payments-partner,
  accessed 2026-06-09]*. The NGB **corporate-partner** tier (Speedo, Sport England,
  SportsHotels) is sponsorship-based and brand-led, with **no content/social category and
  no route found for a solo vendor to have its product endorsed to all clubs** *[Source:
  swimming.org/swimengland/swim-england-corporate-partners, accessed 2026-06-09]*.

- **Swim Wales:** no comparable public approved-supplier/endorsement programme for
  third-party software was found this cycle (searched 2026-06-09). Treated as **unknown —
  do not assert a Swim Wales endorsement mechanism exists** until verified. *(Gap logged.)*

**Re-weighting (the correction this cycle makes):**

| Mechanism | Prior framing | Evidence-based framing |
|---|---|---|
| **Approved data-API access** | implicit / merged into "endorsement" | **Evidenced, dated, open to commercial orgs.** Concrete first NGB action. Grants *data + credibility*, not promotion. **>95% this step is correct/available.** |
| **Promotional NGB endorsement → hundreds of clubs** | *"the single highest-leverage channel"* | **Down-weighted to speculative.** No evidence NGBs promote third-party content tools; partner categories are exclusive and already held by incumbents. Keep the 6-month threshold; do not plan around it as the primary channel. |

**Implication for the plan:** the binding-constraint (distribution) sequence no longer
rests on an unevidenced "endorsement reaches hundreds of clubs" assumption. The *>95%
standard* attaches to the **API-access step** (correct and available) and to the
*decision* to down-weight promotional endorsement; the promotional upside is **quarantined
as speculative**, not deleted. This also **reinforces Route C** — the incumbents who hold
both the NGB partner endorsement *and* (now) the official data integration are the
realistic distribution partners, raising Route C's relative attractiveness vs a direct NGB
content endorsement. No revenue figure changed; the £150k–£400k swimming-only ceiling and
Routes A/B/C stand. Recorded as **[adr/0012](../adr/0012-ngb-distribution-channel-reality-check.md).**

## Evidence refresh — 2026-06-09 (strategy engine, cycle 4: hand-sell funnel base rates — direct + word-of-mouth)

**Why:** after cycle 3 down-weighted promotional NGB endorsement to speculative (ADR-0012),
**direct + word-of-mouth hand-sell became the de-facto *primary* distribution channel** — yet
PC.6 described it in a single sentence ("hand-sell the first ~10 clubs yourself") with **no
funnel, no channel mix, no base rates, and no timeline.** Distribution is the binding
constraint, so the design of the now-primary channel was the most load-bearing under-specified
item on the plan. This cycle grounds it in current, sourced conversion base rates so the
sequence is evidence-banded rather than asserted.

**Findings (current benchmarks; all flagged ESTIMATE where they are external base rates applied
to MediaHub's unproven case):**

- **Cold founder-led outreach converts poorly; warm converts ~10× better.** Cold B2B outreach
  reply rates run **~2–5%** (SaaS as low as ~1.9% due to inbox saturation), and cold-email→meeting
  averages **~0.8%** (>0.4% is "good"). Warm intros / founder-led warm outreach convert at
  **~30–50%**. The founder should personally close the first **10–20** deals before any process is
  declared repeatable. *[Sources: builtforb2b.com B2B cold-email benchmark 2025; martal.ca cold-email
  statistics 2026; justinmckelvey.com / mailshake.com founder-led-sales guides; accessed 2026-06-09.]*
- **Referral / word-of-mouth is the dominant SMB acquisition channel.** **20–50%** of new SaaS
  customers come from referrals/word-of-mouth; **~65%** of B2B new business is referral-driven; **82%**
  of small businesses cite referrals as their main acquisition source; referred customers retain
  **~37%** better. These effects are *amplified* inside tight niche communities. *[Sources: saastr.com;
  thinkimpact.com B2B referral statistics 2026; businessdasher.com; accessed 2026-06-09.]*
- **Reachable population is large and publicly listed, but contactability ≠ conversion.** Swim
  England lists **~1,200+** affiliated clubs and Swim Wales **~80–90** (~11,000 members) in public
  club directories — so the *list* is free, but volunteer-run, no-budget clubs convert cold at the
  low end above. *[Sources: swimming.org; swimwales.org / en.wikipedia.org/wiki/Swim_Wales; accessed
  2026-06-09.]*

**Funnel math (the correction this cycle makes — honest, adversarial):**

| Channel | Per-step rates (ESTIMATE) | Implied volume for the 10-club gate | Verdict |
|---|---|---|---|
| **Local-warm (Swansea / SE Wales)** | warm close ~30–50% | a handful of high-touch contacts → ~3–5 clubs | **Primary; do first.** Founder is locally embedded. |
| **Referral chains** | 2 named intros / signed club × ~30–50% warm close | compounds ~5 → ~10 | **Primary compounding mechanism.** Niche-community amplified. |
| **Cold outreach** | reply ~2–5% × reply→mtg ~30–50% × mtg→paid ~15–30% ≈ **0.3–1.0% cold-to-paid** | ~1,000–3,000 quality contacts to win 10 cold — **infeasible solo at quality** | **Capped supplement only** (book a few discovery calls); never the path to the gate. |

**Implication for the plan:** the now-primary distribution channel is specified as a **warm-first +
referral sequence**, with cold outreach explicitly bounded to a supplement. The **>95% standard**
attaches to the *channel-design decision* (warm + referral over cold broadcast — overwhelmingly
supported by the base rates above); the *outcome* (10 paying clubs in ~3–6+ months at a tested
price) remains **unproven and is itself the validation**, also closing the PC.4 WTP gap. No revenue
figure changed; the £150k–£400k swimming-only ceiling and Routes A/B/C stand. This operationalises
**[adr/0012](../adr/0012-ngb-distribution-channel-reality-check.md)** (which concluded "lean on
direct + word-of-mouth"); it is an elaboration of that recorded decision, not a new strategic
choice, so no new ADR is minted this cycle.

---

## Evidence refresh — 2026-06-10 (external market-and-scalability research pass, cycle 5)

**Why:** cycles 1–4 were internal strategy-engine refreshes. This cycle runs a **fresh
external market-and-scalability pass** against the live web to test whether the diligence
still holds and to sharpen the two thinnest spots: (a) the *white-space* claim that no swim
incumbent auto-generates content from result files, and (b) the under-specified
**platform-API and results-data legal** constraints on the "auto-posting" endgame. Outcome:
the pass **confirms and sharpens** the report — **nothing was overturned, no revenue figure
changed**, and the £150k–£400k swimming-only ceiling + Routes A/B/C stand. This cycle is the
source cited by the ROADMAP's *Phase C → "External research pass — June 2026 (confirms &
sharpens)"* subsection and its P4.2 note.

**Findings (external, dated; ESTIMATE flagged where a benchmark is an external base rate
applied to MediaHub's unproven case):**

- **White-space re-verified, and tightened.** No swim-data incumbent ingests a result file
  and emits branded, ranked content: **SwimTopia, TeamUnify / SportsEngine, Swimcloud,
  Hy-Tek / MeetMobile, Swim Club Manager, Swim Manager** stop at PB/results display +
  *manual* sharing. **Gipper** *does* offer **swimming graphic templates** (meet-day,
  results, commitment) for social — but it is a **design tool that does NOT ingest
  HY3 / SDIF / result files** (result-file import is Hy-Tek / Team Manager / Swimcloud
  territory). So MediaHub's *result-file → ranked, branded content* path is undefended
  **today** — a **time advantage, not a moat**. **Watch item: Gipper adding result-file
  ingestion** would close the head-start. *[Sources: gipper.com/sports-templates/swimming-meet-day-graphic-template;
  hytek.active.com Import Meet Results; support.swimcloud.com "Creating a Hy-Tek Result
  File"; accessed 2026-06-10.]*
- **Instagram auto-posting is gated by a multi-step Meta approval.** Publishing to accounts
  you don't own requires an Instagram **Business/Creator** account + a connected **Facebook
  Page** + a Meta app with **`instagram_business_content_publish`** + **App Review**
  (per-permission, Meta-documented **~2–4 weeks** each, with a screencast) + **Business
  Verification** + **Advanced Access**; ~25 test users before review. Plan ~6–8 weeks of
  go-to-market lead time. *[Source: developers.facebook.com/docs/instagram-platform/app-review/
  and overview; accessed 2026-06-10.]*
- **TikTok auto-posting is restricted until an audit.** An **unaudited** Content-Posting
  API client can only post **private (SELF_ONLY)** and is capped at **≤5 users / 24h**;
  lifting that requires passing TikTok's **audit** (developer-reported ~1–4 weeks, longer on
  rejection — ESTIMATE). *[Source: developers.tiktok.com Content Posting API guidelines /
  get-started; accessed 2026-06-10.]*
  → **Implication (a + b):** validates the roadmap's sequencing of **Bluesky (AT Protocol) +
  Mastodon as the first free publish targets (P4.1)** — open APIs, no review gauntlet —
  **before** Instagram / TikTok (P4.2), all behind human approval. "Launch-day IG/TikTok
  auto-posting" is correctly on the EXCLUDE list.
- **Results-data acquisition carries ToS / CMA / GDPR risk; the official API is the clean
  path.** Scraping competition results risks source-platform **ToS** breaches and, in the
  UK, **CMA** competition scrutiny; the data is largely **minors'** competition data, so
  **GDPR** applies. The evidenced, low-risk route is the **Swim England approved-systems
  API** (cycle 3) rather than scraping — reinforcing the ADR-0012 "apply for data-API
  access" first move and the ADR-0003 minors'-data isolation lock.

**Confirmed (unchanged) anchors:** swimming-only ceiling ≈ **£150k–£400k ARR**; ~1,300 UK&I +
~2,740 USA Swimming affiliated clubs; warm close ~30–50% vs cold ~2–5%; referrals 20–50% of
SaaS customers; annual prepay cuts churn ~30–40%; SMB/volunteer churn 3–7%/mo; candidate Club
price **£49–£99/mo billed annually, UNVALIDATED until ≥5 clubs pay annually** (PC.4); Swim
England approved-systems API (1 Oct 2025; partners Swim Club Manager + Swim Manager; commercial
orgs invited to apply) REAL vs promotional NGB endorsement SPECULATIVE (ADR-0012).

**Implication for the plan:** none of the strategy changes — the pass is a **confirmation +
sharpening**. The >95% standard attaches only to the *decisions* (commercialise first; PC.3
multi-tenancy as the #1 blocking scaling fix, operator/Council-gated; warm + referral over
cold; official API over scraping; free open publish targets before the gated platforms), never
to any revenue outcome. No new ADR is minted: this elaborates the decisions already recorded in
[adr/0011](../adr/0011-commercial-reconcile-revenue-reality.md) and
[adr/0012](../adr/0012-ngb-distribution-channel-reality-check.md).
