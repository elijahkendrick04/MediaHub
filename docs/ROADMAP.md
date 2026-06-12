# MediaHub Roadmap

The plan — **one document, in priority order**. It reads top-to-bottom the way
you should work it: first the two live to-do lists (**things only you can do**,
each with a step-by-step guide, then **things Fable 5 can build**), then the
changelog, then the rules every change must respect, then the in-depth plan
for the open phases — and only at the bottom, the record of everything already
done. Appendices A/B/C (the PAR-\*/SEQ-\*/Step-N build & verification prompts,
kept for AI sessions to read) close the document.

## In plain words (start here)

MediaHub turns a swim meet's results file into ready-to-post club content:
upload the results, the app works out what matters (PBs, medals, club
records), designs branded cards and reels, writes the captions, and a human
approves everything before it goes anywhere.

**Where we are right now (June 2026):** the product is built and live.
Signup, billing code, multi-tenancy, the generative design engine, fourteen
swimming-depth features and a UK legal-compliance baseline have all shipped.
What we do **not** have is a single paying club. The bottleneck is no longer
engineering — the last compliance code tasks (PC.11–PC.14) and the referral
engine (PC.9) shipped on 2026-06-12 and now live under **Completed**. What
remains is (1) a short list of real-world tasks only you can do (choose the
real company name and register the company at Companies House, register with
the ICO, set the Stripe keys, get the legal drafts signed off, buy the
domain, sell to the first clubs), each with its own step-by-step guide, and
(2) two code tasks (PC.15/PC.16) that each wait on one of those founder
decisions. Both lists are right below, in that order.

The plan is organised into phases:

- **Phase C — Commercialise** · 🔵 in progress, top priority: get paid,
  lawfully. Everything else waits behind its three exit gates.
- **Phases 3–6** · ❌ gated: more sports (P3), posting straight to platforms
  (P4), zero-fee local AI (P5), our own full creative suite (P6). None of
  these start until Phase C's gates are met.
- **Phases 0, 1, 2 and W** · ✅ done: cost/licence de-risking, the planning
  brain, the autonomy controls, and fourteen swimming-wedge features. Their
  records are at the bottom under **"Done"**.

Every task carries a badge: ✅ done · 🔵 in progress · ⚠️ stuck · ❌ not
started.

**What updates itself, and what doesn't.** Exactly six marked blocks in this
file are rewritten by a robot on every push to `main`: the **Last updated**
line, the **Recent code activity** table, the **Production findings** list,
and the items inside the **two to-do lists and the Completed list**. List
items move two ways: a `roadmap: <ID> <status>` line in a commit message
(see *Status* below) — or the robot's **sweep**: any to-do item already
marked done with a ✅ badge is moved off its to-do list into the Completed
list automatically, and any human work its line still names is kept on (or
filed into) the founder list. Every other word is written by hand, usually
by Fable 5 in a session — so if a paragraph looks stale, it will not fix
itself; say so and it gets rewritten.

> New here? Read **[START_HERE.md](../START_HERE.md)** first, then come back.
> Odd word? See the **[GLOSSARY](../GLOSSARY.md)**.

## Status (auto-updated)

<!-- ROADMAP:LAST_UPDATED -->
**Last updated:** 2026-06-12 · `ee7c13fa8` · Merge pull request #421 from elijahkendrick04/roadmap-engine/2026-06-12-daily-scan
<!-- /ROADMAP:LAST_UPDATED -->

The stamp above, the activity table in the Changelog, and the list items below
refresh on every push to `main` via
[`.github/workflows/roadmap-autoupdate.yml`](../.github/workflows/roadmap-autoupdate.yml)
(landed through an auto-merge PR — `main` requires PRs). To move an item in
the lists, put a directive line in any commit message:

> `roadmap: <ID> <status>` — `<ID>` is an item ID from the lists below
> (`F.2`, `P4.1`, `P6.3` …); `<status>` is `done` · `wip` · `blocked` ·
> `todo`. `done` **moves the item to Completed** (date-stamped); any other
> status moves it back to its to-do list with the matching badge (`F.*` ids
> return to the founder list, everything else to the Fable 5 list).

No directive is needed for an item that is already *marked* done: on every
push the robot also runs a **completed-item sweep** — any to-do item whose
badge is ✅ (however it got marked) is moved to the Completed list, dated
from its badge. If the item's line names the human work still open
(`Founder half open = F.1/F.6`), those `F.*` items stay on the founder list
and the Completed entry points at them; a free-text remainder
(`founder remainder: <task>`) is filed as a **new** `F.*` founder item,
flagged until its step-by-step guide is written. So a finished item can
never squat on a to-do list — and the human half of a half-human task can
never silently vanish.

## To do — things only you can do

Fable 5 cannot register a business, sign a contract, spend your money, or sit
in front of a swim-club committee. Each item below has a **step-by-step
guide** in the next section. Recommended order (re-prioritised 2026-06-12):
**F.9 → F.10 → F.11** settle the business identity first — the real company
name (MediaHub is a filler), the Companies House company, and the .co.uk
domain — because every filing after them (Stripe, ICO, the solicitor's
letters, the Swim England application) embeds that identity and would have to
be re-done, and re-paid, under a rename. Then **F.1–F.4** make the first sale
lawful (the [ADR-0015](adr/0015-compliance-readiness-sell-gate.md) sell gate —
no club pays before these hold), **F.5 / PC.4 / PC.6** are the selling motion
itself, **F.6–F.8** are housekeeping that runs alongside, and **F.13** (take
the GitHub repo private again) lands at the latest **before the first club
pays** — the children's-data fixtures' documented justification assumes a
private repo. **F.12** (the
cheaper-hosting move off Render) is deliberately sequenced *after* F.11 —
once your own domain fronts the app, changing host is an invisible DNS flip —
and it must never displace a selling week.

<!-- ROADMAP:TODO_FOUNDER -->
- **F.9** · Choose the real company name (MediaHub is a filler): run the four-register name diligence — Companies House, UK trade marks, domain, social handles — and make the call · ❌ **NOT STARTED**
- **F.10** · Register the company at Companies House: verify your identity, file online (£100), then the post-registration basics — Corporation Tax, business bank account, statutory diary · ❌ **NOT STARTED**
- **F.11** · Buy the .co.uk domain in the company's name and point it at the live app (custom domain + TLS on Render today; Stripe webhook and base URL move with it) · ❌ **NOT STARTED**
- **F.12** · Decide and execute the cheaper-hosting move off Render (≈£20/mo → ≈£4–8/mo VPS) via the rehearsed backup-restore cutover — after F.11, never ahead of selling · ❌ **NOT STARTED**
- **F.1** · Turn payments on: create the Stripe account, set the four `STRIPE_*` keys on Render, switch on renewal reminders, decide VAT · ❌ **NOT STARTED**
- **F.2** · Register with the ICO and fill in the business identity (company name, address, contact email, ICO number) · ❌ **NOT STARTED**
- **F.3** · Get the five legal drafts solicitor-reviewed and signed off (Terms, Privacy, Cookies, DPA, DPIA) · ❌ **NOT STARTED**
- **F.4** · Accept each vendor's data-processing terms and pin the hosting region · ❌ **NOT STARTED**
- **F.5** · Adapt and submit the drafted Swim England API application · ❌ **NOT STARTED**
- **PC.4** · Phase C 🥇 — Quote real annual prices to the first clubs and record what clears; the public price unlocks itself once ≥5 clubs have paid annual at a tested price (build side shipped — this is selling) · 🔵 **IN PROGRESS**
- **PC.6** · Phase C 🥇 — Win the first ~10 paying clubs: warm-first hand-sell from the Swansea/South-Wales base + referrals, cold capped (tooling shipped — this is selling) · 🔵 **IN PROGRESS**
- **F.6** · Production ops decisions: retention period, breach owner named in the runbook, insurance, Remotion licence (or the free ffmpeg engine), Render snapshots + off-site backup target · ❌ **NOT STARTED**
- **F.7** · Each season: refresh the qualifying-time tables (recurring; runbook in `data/standards/README.md`) · ❌ **NOT STARTED**
- **F.8** · When direct Instagram/Facebook posting nears (P4.2): start the Meta Business Verification + App Review paperwork early · ❌ **NOT STARTED**
- **F.13** · Take the GitHub repo private again (public today; the children's-data fixtures' lawful-basis note assumes a private repo): pre-flight sweep, CI-minutes plan, the Settings flip, integration re-checks — at the latest before the first club pays · ❌ **NOT STARTED**
<!-- /ROADMAP:TODO_FOUNDER -->

### Step-by-step guides (one per item above)

#### F.9 — Choose the real company name (the naming diligence)

"MediaHub" was always a working title: it is generic, shared by other
companies, and could never be defended as a brand or trade mark. The real
name comes **first** — before Companies House, Stripe, the ICO, the
solicitor's letters and the domain — because every one of those filings
embeds it, and renaming later means re-doing (and re-paying) the lot.

**What "due diligence" means here, in plain words:** before you commit to a
name, check that nobody else already owns it — as a registered company, as a
trade mark, as the domain, or as the obvious social handles — so that no one
can force you to rebrand (or sue you) later, and so you are never pushed into
a worse spelling of your own name. It is an afternoon of free searches, done
in the order below.

1. Longlist 5–10 candidate names. The criteria that actually matter for this
   product: **distinctive** (a coined/invented word beats a descriptive one —
   descriptive names can't be defended and are already taken), **short and
   unambiguous said aloud** (poolside, over the phone, on a committee call),
   **comfortable in Wales** (check the Welsh reading/meaning — the first
   market is Welsh clubs and the product ships Welsh-first captions, W.13),
   and **bigger than swimming** (the vision is sport-agnostic — avoid "swim"
   in the name unless that's a deliberate choice).
2. **Companies House check.** Search the free register at
   find-and-update.company-information.service.gov.uk and run GOV.UK's
   "Check if a company name is available" service. The rules: the registered
   name ends "Ltd"/"Limited" (you can trade without the suffix), it can't be
   the "same as" an existing name, and "sensitive words" (Royal, British,
   Institute, …) need permission. An existing dormant or different-sector
   company with a similar name isn't automatically fatal — but prefer a clear
   field.
3. **Trade mark check — the one that can actually force a rebrand.** Search
   UK trade marks (GOV.UK "Search for a trade mark") in **class 9**
   (software), **class 42** (software-as-a-service) and **class 41**
   (sport/education services). A live mark on a confusingly similar name in
   those classes = drop the candidate. Registering a company name gives you
   **no** trade-mark rights — they are separate systems.
4. **Domain check.** Is the exact-match `.co.uk` free at any registrar
   (≈£5–15/yr)? Don't buy yet — that's F.11, after F.10 locks the name. If
   the `.com` is parked at a four-figure aftermarket price, let it go; the
   `.co.uk` is the brand at home and a sane `.com` variant can come later.
5. **Handles check.** Instagram, Facebook, X, TikTok, Bluesky, YouTube,
   GitHub. The product's whole job is social content — clubs *will* search
   the name. Exact or near-exact handles should be free.
6. **The passing-off sniff test.** Plain web search for the name plus
   "swim", "sport", "club", "software". Anyone already trading under it in an
   adjacent space — even without a registered trade mark — can claim
   "passing off" in the UK. Avoid names with active neighbours.
7. Pick the winner and sleep on it once. Say it in the three sentences it
   must live in: "___ has signed up to ___", "Powered by ___", "___ Ltd".
8. *(Optional, cheap insurance once revenue starts:)* file your own UK trade
   mark — £205 online for one class, +£60 per extra class (fees rose
   1 Apr 2026); classes 9 + 42 first. This can wait for the first paying
   clubs.
9. **Verify:** the name passes all four registers (Companies House, trade
   marks, domain, handles), with screenshots/notes kept in one folder — then
   tell Fable 5 the chosen name so the rebrand sweep (PC.15) can be built and
   F.2's legal placeholders get the real value.

#### F.10 — Register the company at Companies House

About 30 minutes online once F.9 has settled the name. The company is the
legal identity everything else hangs off — Stripe onboarding (F.1), ICO
registration (F.2), the solicitor's sign-off (F.3), the Swim England
application (F.5), insurance (F.6) and the domain registration (F.11). This
supersedes the old "sole trader is fine to start" note in F.2: decided
2026-06-12 — name first, company second, everything files once under it.

1. **Verify your identity first** (mandatory for new directors since
   18 Nov 2025): create a GOV.UK One Login and complete Companies House
   identity verification — you receive a personal code that the
   incorporation filing now requires.
2. Decide the basics — the answers are mostly "you": sole director = you;
   shareholder = you (1 or 100 ordinary £1 shares — either is fine; 100
   makes a future split easier); Person with Significant Control = you.
3. Choose the **registered office address** — it is public, forever. Your
   home address works but is published; a registered-office service
   (≈£20–50/yr, often bundled by accountants) keeps your home address off
   the register. You also need a registered email address (not published).
4. Pick the **SIC code** (what the company does): 62012 "business and
   domestic software development" fits; add 63120 (web portals) if you like —
   up to four, all changeable later.
5. **File online**: GOV.UK "Set up a private limited company" → register the
   company. £100 digital fee (it rose from £50 on 1 Feb 2026), model
   articles of association are fine, and registration usually completes
   within 24 hours. You get the certificate of incorporation + company
   number.
6. **Within 3 months of starting to trade** (the first sale is the trigger):
   register for Corporation Tax — HMRC posts the company's UTR to the
   registered office.
7. **Open a business bank account in the company's name** (Starling, Tide,
   Monzo Business — free tiers are fine). Company money and your money never
   mix; Stripe payouts (F.1) land here.
8. Set up the books and **diary the annual duties** so they never surprise
   you: the confirmation statement each year (£50 online — also where
   directors' ID verification is enforced), annual accounts (micro-entity
   accounts are tiny), and the Corporation Tax return. Simplest: a fixed-fee
   accountant for a micro company (≈£300–700/yr `[ESTIMATE]`); or
   FreeAgent/Xero solo.
9. VAT: nothing to do below the registration threshold — F.1 step 7 already
   covers the decision; just keep records.
10. Feed the new identity into everything queued behind it: Stripe (F.1) as
    the Ltd, ICO (F.2) in the company's name — and give Fable 5 the five
    identity values so the legal placeholders fill — the solicitor (F.3),
    Swim England (F.5), insurance (F.6).
11. **Verify:** the company appears on the public register; the certificate,
    personal code, UTR letter and bank details live in the records folder;
    after F.2 step 4, `/terms` and `/privacy` show the real company name and
    number.

#### F.11 — Own domain: buy the .co.uk and point it at the live app

Today the public URL is the borrowed `mediahub-gzwc.onrender.com`. Your own
domain is the **portable** identity: once every printed QR code, embedded
wall, bookmark and Stripe webhook points at your own `.co.uk`, the hosting
underneath (F.12) can change with a DNS flip and nobody notices. That is why
the domain comes before the host move — and after F.10, so the company owns
it.

1. Register `<name>.co.uk` at any Nominet-accredited registrar (Namecheap,
   Porkbun, Gandi, Ionos/123-reg, Krystal, … ≈£5–15/yr `[ESTIMATE]`).
   Register it **in the company's name** with the company's contact email —
   not as a personal possession; clean ownership matters if you ever sell or
   raise. Take the bare `.uk` too if it's pennies; skip aftermarket-priced
   `.com` offers.
2. Decide the canonical host once: `www.<name>.co.uk` (recommended —
   CNAME-friendly everywhere) with the apex redirecting to it.
3. *(Recommended)* put the DNS on a provider you won't outgrow — Cloudflare's
   free tier works with a domain bought anywhere (add the site, switch the
   two nameservers at the registrar). Registrar DNS also works; pick one.
4. Wire it to Render **now** — don't wait for F.12: Render dashboard → the
   service → Settings → Custom Domains → add `www.<name>.co.uk` (+ apex);
   create the CNAME/A records it shows; TLS certificates are automatic.
5. Update what knows the URL: the `MEDIAHUB_PUBLIC_BASE_URL` env var on
   Render; the Stripe webhook endpoint (F.1 step 4) to
   `https://www.<name>.co.uk/webhooks/stripe`; and when transactional email
   goes live, send as `no-reply@<name>.co.uk` with the SPF + DKIM DNS
   records your email provider gives you (`MEDIAHUB_EMAIL_FROM` — mail from
   your own domain lands in inboxes; mail from borrowed domains lands in
   spam).
6. Ask Fable 5 for the small code half (rides with PC.15): a canonical-host
   redirect so the old `*.onrender.com` URLs 301 to the new domain — every
   old link keeps working forever.
7. **Verify:** `https://www.<name>.co.uk` serves the app with a padlock and
   the apex redirects; `/try`, a `/wall/<token>` page and a Stripe **test**
   webhook all work on the new URL; the old onrender.com URL redirects.

#### F.12 — Move hosting off Render to a cheaper host

The honest numbers first: Render's standard instance — the 2 GB the
Chromium/Remotion renders need — is **$25/mo ≈ £20/mo** plus the disk. A
capable EU VPS runs **€3.79–€7.59/mo** (Hetzner CX22 4 GB → CX32 8 GB,
verified June 2026), so the move saves roughly **£150–200/yr** `[ESTIMATE]`.
Real money, but small against one paying club (~£588–1,188/yr) — which is
why F.12 is queued **behind** the identity work and must never displace a
selling week. The trade: a VPS hands you the ops the platform did (OS
updates, monitoring, disk space). The app is deliberately a single-box shape
— one container, SQLite under `DATA_DIR` — so a single VPS fits it exactly,
and the backup/restore drill (PC.14) already rehearses the actual move.

1. **Decide between three honest options.**
   **(a) EU/UK VPS + Docker** — the recommended target: Hetzner (Germany/
   Finland, EU) at €3.79–7.59/mo, or a UK-soil VPS (≈£5–15/mo `[ESTIMATE]`)
   if "your data stays in the UK" plays better with clubs. Either improves
   on today's hosting, which stores Club Data in the **US** (see the DPA's
   subprocessor register) — the move shrinks F.4's transfer homework.
   **(b) A cheaper managed platform** (Fly.io London, Railway, …) — less ops,
   smaller savings once a persistent volume + 2 GB RAM are priced; check
   their current calculators.
   **(c) Stay on Render and revisit at traction** — £0 effort, a legitimate
   choice while selling time is the binding constraint. If (c): stop here
   and diary it for after the first ~3 paying clubs.
2. If (a) or (b): ask Fable 5 to build **PC.16** (the code half) — the
   compose + reverse-proxy TLS template, the off-site backup-target
   preflight, the log-sentinel log-source seam (it currently reads logs via
   the Render API and must honest-disable or grow a journald/file source off
   Render), the staged subprocessor-register + privacy-notice hosting/region
   update, and the written cutover runbook.
3. Provision the box; deploy the **same Dockerfile** with the same `.env`;
   point a temporary subdomain (e.g. `next.<name>.co.uk`) at it.
4. **Rehearse the move with the shipped drill:** take the latest production
   backup ZIP, `python -m mediahub.backup restore` onto the new box, then
   smoke-test the primary flow (upload → pack → review → approve → export),
   one reel render, `/healthz`, and a Stripe **test** webhook against the
   temporary subdomain.
5. Cut over: lower the DNS TTL the day before; pause uploads briefly (tell
   any live pilot club); final backup → restore → flip the `www` record to
   the new box; watch `/healthz` and the uptime readout.
6. Keep Render alive for ~1 week as the instant rollback (flip DNS back),
   then download a final disk snapshot, delete the service, detach the card.
   Point the off-site backup target somewhere that is **not** the new box —
   a backup living on the machine it protects isn't one.
7. **Verify:** a full green week on the new host (uptime, scheduler runs,
   off-site backups arriving, one real run end-to-end); the DPA's
   subprocessor register and the Privacy Notice name the new host and
   region (PC.16); and the bill actually dropped.

#### F.1 — Turn payments on

The billing code shipped in PR #267 and deliberately refuses to run (an
honest "billing not configured" message) until you give it real Stripe keys.

1. Create an account at stripe.com and complete Stripe's business onboarding
   (it asks for the legal identity you create in F.10 — onboard as the
   limited company from the start, so its KYC never has to be re-done after
   a switch from a personal account).
2. In the Stripe dashboard, create two Products with recurring annual Prices:
   **Club** and **Federation**. Copy each Price id (`price_…`).
3. Developers → API keys: copy the Secret key. Use the `sk_test_…` key first
   if you want to rehearse the whole flow with the card number
   `4242 4242 4242 4242`, then swap to `sk_live_…`.
4. Developers → Webhooks → Add endpoint:
   `https://<your-app-domain>/webhooks/stripe` (the F.11 domain once it's
   live — update the endpoint here if you wire Stripe first), subscribed to
   the checkout/subscription events; copy the Signing secret (`whsec_…`).
5. Render dashboard → your service → Environment: set `STRIPE_SECRET_KEY`,
   `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_CLUB`, `STRIPE_PRICE_FEDERATION`.
   Redeploy.
6. In Stripe → Settings → Billing: switch **on** renewal-reminder emails for
   annual subscriptions (the Terms and `/billing/confirm` promise a reminder
   before renewal — make it true), and confirm the customer-portal
   cancellation flow is enabled (cancelling must stay as easy as signing up).
7. Decide VAT: below the registration threshold, do nothing but keep records;
   otherwise enable Stripe Tax. Confirm Checkout emits an invoice/receipt a
   volunteer treasurer can put through club accounts.
8. **Verify:** `/billing` on the live site no longer shows "billing not
   configured", and a test-mode payment runs end-to-end.

#### F.2 — Register with the ICO + fill in the business identity

You process personal data (largely children's), so UK law requires
registering with the Information Commissioner's Office and paying the small
annual data-protection fee.

1. The business identity is the F.10 limited company (decided 2026-06-12:
   name first, company second, everything else files once under it) — do
   F.9/F.10 before this, so the ICO entry never needs re-registering under
   a rename.
2. Register as a data controller at **ico.org.uk/registration** and pay the
   fee (tier 1 covers a small business; it renews annually).
3. Note the ICO registration number you receive.
4. Give Fable 5 the five values — trading/company name, company number (or
   "sole trader"), business address, contact email, ICO number — and ask it
   to fill the placeholders in `web/legal.py` (one edit fixes every legal
   page and the footer; the canonical list is `legal.PLACEHOLDERS`).
5. **Verify:** open `/terms` and `/privacy` on the live site — no
   `[COMPANY_NAME]`-style brackets remain anywhere.

#### F.3 — Solicitor sign-off on the legal drafts

The five documents are drafted and live, but headed "DRAFT — requires
solicitor review". A human professional must sign them off before the first
paid contract.

1. Find a solicitor with data-protection/commercial experience (the Law
   Society finder, or a fixed-fee online firm; budget a few hundred pounds).
2. Send them the four live pages (`/terms`, `/privacy`, `/cookies`, `/dpa`),
   the DPIA draft (`docs/compliance/DPIA.md`), and the specific open
   questions listed in [`COMPLIANCE_AUDIT.md`](COMPLIANCE_AUDIT.md) §4(d).
3. Feed their edits back through Fable 5 — it updates `web/legal.py` and
   bumps the document version, which automatically routes every signed-in
   account through re-acceptance. That's the mechanism, not a promise.
4. When they sign off, ask Fable 5 to remove the DRAFT banners and record the
   sign-off date.
5. **Verify:** the four pages render without DRAFT banners and carry dated
   versions.

#### F.4 — Vendor data-processing terms + hosting region

MediaHub sends data to a handful of providers; each needs its processing
terms accepted and a lawful UK→US transfer mechanism confirmed.

1. Work down the live-provider list: Google (Gemini API), Anthropic, Stripe,
   Render — plus any you have switched on (Buffer, Photoroom, Replicate,
   ntfy).
2. For each: accept/execute their data-processing terms (usually a dashboard
   checkbox or a published DPA) and keep a dated copy in one folder.
3. For US vendors, confirm UK–US Data Bridge certification, or execute their
   IDTA/UK Addendum.
4. Where a "don't train on my data" toggle exists (Google AI, Anthropic),
   switch it off and screenshot it.
5. In Render: pin the region, confirm disk encryption, confirm TLS/HSTS at
   the edge.
6. **Verify:** every subprocessor named in the Privacy Notice §7 has a
   recorded agreement in your folder — and tell Fable 5 about any provider
   you add or drop so the notice stays true.

#### F.5 — Submit the Swim England API application

Swim England's approved-systems API grants official swim-times data (not
promotion — see [ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)).
The application is already drafted and submission-ready.

> **Daily-scan note (2026-06-12):** Swim England has since announced (4 Mar
> 2026) a Sport:80-built membership platform (live Autumn 2026), a **Rankings
> API** for verified swim times and a swimmingresults.org integration, with a
> SportsEngine announcement expected later in 2026. Before submitting, check
> whether commercial times-data access now routes through the Rankings-API /
> Sport:80 programme rather than the 1 Oct 2025 contact, and expect slower
> replies around the Autumn 2026 migration window.
> Source: [Sport:80 announcement](https://www.swimming.org/swimengland/sport80-membership-platform/).

1. Open [`commercial/SWIM_ENGLAND_API_APPLICATION.md`](commercial/SWIM_ENGLAND_API_APPLICATION.md)
   and fill in the founder/identity details (same values as F.2).
2. Re-verify the submission contact from Swim England's 1 Oct 2025
   approved-systems announcement — it may have moved.
3. Send it, and record "applied" on the operator console
   (`/operator/commercial`).
4. Chase politely after ~4 weeks.
5. The standing threshold: if no NGB movement after ~6 months, deprioritise
   the channel and lean on direct + referrals.

#### PC.4 — Quote real prices (the pricing gate)

Don't publish a price — *discover* one. `/pricing` deliberately shows
"Pricing TBC" until **≥5 clubs have paid an annual prepay at a tested
price**; it then derives the public list price from the highest tested figure
that cleared. Everything below is already built.

1. For each interested club, pick a real annual figure inside the candidate
   band (**£49–£99/mo billed annually ≈ £588–£1,188/yr**) and vary it across
   clubs — that variation *is* the price discovery.
2. Record the quote on `/operator/commercial` (the quote ledger). It gives
   you a per-quote Stripe Checkout link that charges exactly the quoted
   figure (needs F.1 done).
3. Send the link. The signed webhook records the payment automatically,
   idempotently and amount-verified.
4. Record declines too — a "no" at £1,188 teaches as much as a "yes" at £708.
5. Annual prepay is non-negotiable: volunteer-org churn runs 3–7 %/month and
   annual billing cuts it ~30–40 %.
6. **Done when:** the console's pricing gate shows ≥5 paid annual —
   `/pricing` switches itself on at the highest cleared price.

#### PC.6 — Win the first ~10 paying clubs (the traction gate)

This is *the* Phase C exit gate. The evidence says it is reached by warmth
and referrals, never cold broadcast (warm founder-led sales close ~30–50 %;
cold-to-paid runs ~0.3–1 %, which would need 1,000–3,000 quality contacts —
not viable solo).

1. Read [`PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md). The first club doubles as
   the pilot and will surface UX holes no audit can.
2. List 10–15 warm clubs from the Swansea / South-East-Wales network — clubs
   you can reach through someone they already know (Swim Wales has ~80–90
   affiliated clubs; it is a tight community).
3. Book in-person demos. The sharpest demo: open `/try` with **their own
   latest meet results** — watermarked branded cards in front of them, no
   account needed.
4. Close warm leads with PC.4 quotes (annual prepay only). Aim for ~3–5
   paying clubs from the local base, high-touch.
5. Ask every signed club for **two named introductions** to peer clubs — the
   designed route from 5 to 10. Track who still owes intros on
   `/operator/commercial` (the referral-debt readout).
6. Manufacture warmth at county/regional meets: produce real branded output
   for host and visiting clubs at the event.
7. Use cold outreach only as a capped supplement to book a handful of
   discovery calls — the console's cold-share readout flags when it creeps
   up.
8. **Done when:** ≥10 clubs pay annually. Expect ~3–6+ months; the dominant
   failure mode is the motion not being run, not the close rate.

#### F.6 — Production ops decisions

The boring decisions a paying customer silently assumes someone has made.

1. Set `MEDIAHUB_RETENTION_DAYS` on Render to the retention period you want —
   and tell Fable 5 if you change it later, so the Privacy Notice's retention
   table keeps matching what the code does.
2. Name the breach owner (you): the person who notifies affected clubs
   without undue delay and the ICO within 72 hours. Write the name into the
   owner line of [SUPPORT_INCIDENT_RUNBOOK](SUPPORT_INCIDENT_RUNBOOK.md)
   (shipped with PC.14 — it has the slot ready).
3. Get professional-indemnity + cyber insurance quotes (small-SaaS brokers
   cover this cheaply).
4. Decide reels: buy the Remotion company licence, **or** set
   `MEDIAHUB_REEL_ENGINE=ffmpeg` (the free engine). Don't ship for-profit on
   unlicensed Remotion.
5. ~~Open the bundled demo sample and confirm it contains no real children's
   data~~ **Done (PC.12, 2026-06-12):** the public demo sample is now the
   synthetic `samples/demo-meet-results.pdf` (fictional swimmers, generated
   by `scripts/make_demo_sample.py`); the real meet PDF survives only as a
   parser-regression fixture in `sample_data/`, which no route serves. See
   [CHILDRENS_CODE_PASS](compliance/CHILDRENS_CODE_PASS.md).
6. Switch the daily backup on and point it off the Render disk. The backup
   code + rehearsed restore shipped with PC.14, but the scheduled job
   deliberately stays off until you give it a target. In the Render
   dashboard confirm disk snapshots are on, then set two environment
   variables on the service: `MEDIAHUB_BACKUP_UPLOAD_URL` — any HTTPS
   endpoint that accepts an HTTP `PUT` of a ZIP (an S3/R2 presigned URL, a
   WebDAV folder, or any small storage service that gives you one) — and,
   if that endpoint wants auth, `MEDIAHUB_BACKUP_UPLOAD_TOKEN` (sent as a
   `Bearer` token). (Setting only `MEDIAHUB_BACKUP_DIR` also switches the
   job on, but those archives sit on the same disk they protect — off-site
   is the point.) If/when F.12 moves hosting, re-confirm the equivalent
   snapshots + off-site target on the new host.
7. **Verify:** the operator console's backup line shows a recent archive
   with **off-site upload: yes**, and your name is in the runbook's owner
   line.

#### F.7 — Seasonal qualifying-times refresh (recurring)

"Qualified for Counties!" cards (W.4) depend on season-current tables that
are curated, not scraped.

1. Each season, follow the runbook in `data/standards/README.md`: download
   the new county/regional/national qualifying-time PDFs.
2. Hand them to Fable 5 to convert into the versioned dataset format under
   `data/standards/<season>/` with per-table provenance (source URL + date).
3. **Verify:** one known qualifying swim produces a "qualified" card naming
   the new standard and its source.

#### F.8 — Meta verification paperwork (parked until P4.2 nears)

Instagram/Facebook auto-posting needs Meta Business Verification + App
Review — $0 but **weeks of calendar time**, so start the clock early when P4
work approaches. Until then, P4.1 (Bluesky/Mastodon) and P4.6 (Telegram) need
no review at all.

1. Create a Meta Business Portfolio and complete Business Verification
   (company documents — F.10's certificate of incorporation is exactly
   this).
2. Create the Meta app; request `instagram_content_publish` and
   `pages_manage_posts` via App Review, with screen recordings of the
   connect-and-post flow.
3. Expect ~2–4 weeks per permission; one review covers Facebook Pages +
   Instagram (Threads is scoped separately).

#### F.13 — Take the GitHub repo private again

The repo (`github.com/elijahkendrick04/MediaHub`) is **public today** and
needs to return to private; the only open questions are *when* and *what to
check on the way*. Why it matters, in weight order: (1) **compliance** — the
parser fixtures hold real children's personal data from published meets
(`samples/MISM-2024-Results.pdf`, `samples/learning_corpus/level1/*`), and
the documented justification for keeping them
([OPEN_LEGAL_QUESTIONS Q13](compliance/OPEN_LEGAL_QUESTIONS.md),
[DATA_MAP §6](compliance/DATA_MAP.md)) rests on "access control (private
repo)" — a defence that does not hold while the repo is public;
(2) **commercial** — hosted-only
([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md)) treats the
source as the product, and a public repo is a free self-host path that also
hands competitors the pricing strategy and sales playbook committed in
`docs/`; (3) **the clock runs one way** — flipping private recalls nothing,
so everything pushed while public stays permanently clonable by anyone who
took a copy (the full-history gitleaks audit found no real secrets, so the
exposure is the fixtures + strategy, not credentials). **Latest sensible
deadline: before the first club pays** — the sell gate's compliance posture
leans on Q13's "repo stays private". Do it earlier the moment whatever
needed the repo public is finished.

1. Confirm the reason it is public has expired and nobody external still
   needs read access — anyone who does becomes a collaborator instead (repo
   Settings → Collaborators).
2. Ask Fable 5 for the **pre-flight sweep** (one session): re-check forks —
   **0 as of 2026-06-12**; a fork made while public survives the flip as an
   independent public copy, so any that appeared need a decision before
   flipping — and re-confirm nothing fetches this repo's files
   unauthenticated at runtime (none today: the README badges are static
   shields.io, and the Dockerfile's raw.githubusercontent fetch targets the
   SearXNG repo, not ours).
3. **Decide the Actions-minutes plan — the one real cost.** Public repos run
   GitHub-hosted CI free; a private repo on the Free plan gets
   **2,000 min/month**, and today's schedules (autotest every 6 h, nightly
   Lighthouse + cross-browser sweeps, the daily contract suite, the
   half-hourly dependabot-automerge sweep, plus every push/PR) would burn
   that in days. Cheapest first: have Fable 5 trim the schedules (autotest
   6 h → daily, automerge 30 min → 2–6 h, consolidate the nightlies) and
   ship the trim *before* the flip so the quota never silently stalls CI;
   GitHub Pro (~$4/mo, 3,000 min) if trimming isn't enough; heavy jobs onto
   a self-hosted runner (the F.12 box) later if both fall short.
4. Flip it: repo → Settings → General → Danger Zone → **Change visibility →
   Make private** (type the repo name to confirm). Only you can do this
   (admin). Going private permanently drops stars/watchers (currently 0) and
   turns off GitHub's free public-repo secret scanning / push protection —
   the CI security workflow's own scanners keep running.
5. Re-verify everything that reads the repo: trigger a manual Render deploy
   (the Render GitHub App keeps its access to private repos it was granted),
   open a Claude Code session on the repo, push a trivial commit and watch
   CI + the roadmap-autoupdate bot go green, and confirm Dependabot still
   files PRs.
6. Ask Fable 5 to record the public window honestly in the compliance docs
   (Q13 in `OPEN_LEGAL_QUESTIONS.md` + `DATA_MAP` §6): pin the make-public
   date from your account security log (github.com/settings/security-log,
   filter `repo.access` — 90-day retention), or state repo creation
   (2026-05-08) as the conservative start. "Repo stays private" must read
   true again, with its history accurate.
7. **Verify:** a logged-out browser gets a 404 on
   `github.com/elijahkendrick04/MediaHub`; CI is green on the next push; a
   Render deploy succeeded after the flip; Settings → Billing shows the
   month's Actions usage tracking inside budget.

## To do — things Fable 5 can build

Ask in any session ("build PC.15"). The four **sell-gate code remainders**
(PC.11–PC.14) made the founder list's first sale lawful and trustworthy, and
the referral engine (PC.9) runs the intro loop — all five are fully shipped
and now live in the **Completed** list, their open halves founder-only
(F.1–F.4 and F.6 above, each with its step-by-step guide). **PC.15/PC.16
are next up** — Phase C work, *not* behind the exit gates, each waiting only
on its founder input (PC.15 on F.9's chosen name, PC.16 on F.12's go
decision); then the gated expansion phases. **Phases 3–6 are gated** — they
wait until a club can sign up, pay and publish with zero founder
involvement, **and** ≥10 clubs pay annually, **and** the lawful-to-sell gate
holds (see Phase C). Two flagged exceptions: P4.5 (email digests) and P4.6
(Telegram) are review-free, sell-supporting **pull-forward candidates** at
your discretion.

<!-- ROADMAP:TODO -->
- **PC.15** · Phase C — Rebrand sweep, waits on F.9's name: one product-name source of truth threaded through every customer-facing surface (UI chrome, legal pages, wall badge + embeds, email from-name, `/try`, README) plus the F.11 canonical-host redirect; `mediahub` package/env names stay internal · ❌ **NOT STARTED**
- **PC.16** · Phase C — Hosting-cutover code half, waits on F.12's go decision: VPS deploy template (compose + reverse-proxy TLS on the same Dockerfile), off-site backup-target preflight, log-sentinel log-source seam (Render-API-free), staged subprocessor-register + privacy-notice hosting/region update, written cutover runbook · ❌ **NOT STARTED**
- **P3.1** · Phase 3 (gated) — Second-sport engine adapter: `recognition_football`/`_basketball` + `register_sport(...)` · ❌ **NOT STARTED**
- **P3.2** · Phase 3 (gated) — Sports-data API spokes (`nba_api`, openfootball, fixture generators) normalised to `canonical.*` · ❌ **NOT STARTED**
- **P3.3** · Phase 3 (gated) — Running/athletics parsers (chip-timing CSV, client-side FIT) · ❌ **NOT STARTED**
- **P3.4** · Phase 3 (gated) — Normalise all spokes to the canonical schema; flag ambiguous rows for review · ❌ **NOT STARTED**
- **P4.1** · Phase 4 (gated) — Bluesky (AT Protocol) + Mastodon adapters — the free/open posting targets first · ❌ **NOT STARTED**
- **P4.2** · Phase 4 (gated) — Instagram Graph / Facebook / TikTok / YouTube adapters, least-privilege, human-connected · ❌ **NOT STARTED**
- **P4.3** · Phase 4 (gated) — X adapter as a paid, optional target (pay-per-use API) · ❌ **NOT STARTED**
- **P4.4** · Phase 4 (gated) — Demote Buffer to optional; remove it from the critical path · ❌ **NOT STARTED**
- **P4.5** · Phase 4 (gated) — Email digest delivery: the existing newsletter actually sends (member lists, unsubscribe, Resend-seamed) · ❌ **NOT STARTED**
- **P4.6** · Phase 4 (gated) — Telegram channel publishing (free Bot API; native PNG+MP4) + a WhatsApp share stopgap · ❌ **NOT STARTED**
- **P5.1** · Phase 5 (gated) — Ollama local LLM provider behind the existing `ai_core.llm` interface · ❌ **NOT STARTED**
- **P5.2** · Phase 5 (gated) — Piper local TTS replaces edge-tts · ❌ **NOT STARTED**
- **P5.3** · Phase 5 (gated) — whisper.cpp / faster-whisper local ASR for reel captions · ❌ **NOT STARTED**
- **P5.4** · Phase 5 (gated) — Satori graphics fast-path (~100× lighter than headless Chromium; rides the reel-engine seam P0.1 shipped) · ❌ **NOT STARTED**
- **P6.1** · Phase 6 (gated) — Smart format catalogue + format transformer: every Canva/Adobe-class design type as a data-driven club `FormatSpec` (certificates, posters, programmes, yearbooks, per-channel sizes); `turn_into` v2 re-targets any approved design · ❌ **NOT STARTED**
- **P6.2** · Phase 6 (gated) — Conversational creative assistant: agentic spec-patch editing on `ai_core.ask_with_tools`, Magic-Write-class text tools, org assistant memory, voice input via the ASR seam · ❌ **NOT STARTED**
- **P6.3** · Phase 6 (gated) — Generative imagery suite behind our own `media_ai` provider seam: generate / edit / fill / expand / remove / subject-lift / upscale / style-match / mockups, provenance-stamped · ❌ **NOT STARTED**
- **P6.4** · Phase 6 (gated) — Photo editor: deterministic non-destructive edit recipes (filters, adjustments, crop/perspective, collages, blur brush, HEIC) on `media_library` assets · ❌ **NOT STARTED**
- **P6.5** · Phase 6 (gated) — Video suite: footage path + EDL timeline over the shipped reel engines, ASR captions, Clip-Maker-for-sport, saliency reframe, browser recorders, opt-in disclosed avatars · ❌ **NOT STARTED**
- **P6.6** · Phase 6 (gated) — Audio engine: own licence-clean music/SFX pools + rights ledger, voice layer on the TTS seam (catalogue, params, name-pronunciation lexicon), denoise/levelling, consent-gated voice features · ❌ **NOT STARTED**
- **P6.7** · Phase 6 (gated) — Typography system: curated self-hosted font catalogue + per-org uploads, AI pairing, deterministic text-effect tokens (shadow/neon/curve/extrude/warp), formatting depth · ❌ **NOT STARTED**
- **P6.8** · Phase 6 (gated) — Element & stock libraries: brand-token-recolourable sport-editorial packs, own open-collection-seeded stock pools, embedding search, annotate/draw layer · ❌ **NOT STARTED**
- **P6.9** · Phase 6 (gated) — Charts & insights: deterministic brand-styled stat graphics from canonical results/history + grounded AI takeaways and chart recommendations; diagram formats · ❌ **NOT STARTED**
- **P6.10** · Phase 6 (gated) — Motion vocabulary: tokenised animation presets/transitions compiled to Remotion + FFmpeg + CSS, shared-element transitions, motion paths, reduce-motion variants · ❌ **NOT STARTED**
- **P6.11** · Phase 6 (gated) — Brand platform depth: multi-kit (sponsor/event/section co-branding), deterministic brand check + AI auto-fix, token locks, brand home, kit-edit re-render sweep · ❌ **NOT STARTED**
- **P6.12** · Phase 6 (gated) — Document engine: meet programmes / season reports / sponsor proposals / AGM decks, presenter surface (notes, remote, autoplay), PPTX/DOCX round-trip, PDF utilities · ❌ **NOT STARTED**
- **P6.13** · Phase 6 (gated) — Club microsites + link-in-bio + forms + QR + vetted interactive widgets (countdowns, medal tally, polls), data-generated and publish-gated · ❌ **NOT STARTED**
- **P6.14** · Phase 6 (gated) — Email & newsletter composer: email-safe branded HTML auto-assembled from the period's approved content; export-first, send-adapter later · ❌ **NOT STARTED**
- **P6.15** · Phase 6 (gated) — Data hub + bulk personalisation: user-facing canonical tables with provenance, CSV/XLSX round-trip, deterministic derived columns, review-queued bulk generation ("certificates for all 47 PB swimmers") · ❌ **NOT STARTED**
- **P6.16** · Phase 6 (gated) — Planner calendar/board: drag-reschedule through the publish gate, club-aware key dates, per-channel previews + safe zones, first-party performance-analytics loop feeding the planner · ❌ **NOT STARTED**
- **P6.17** · Phase 6 (gated) — Collaboration & review: anchored comments/mentions/tasks, version diff + restore, element locks, roles, group approvers, expiring share tokens · ❌ **NOT STARTED**
- **P6.18** · Phase 6 (gated) — Export & conversion engine: SVG/GIF/PPTX/DOCX/WAV/print-PDF additions, quality/transparency options, bulk export jobs, media-library quick-action utilities · ❌ **NOT STARTED**
- **P6.19** · Phase 6 (gated) — Print & merch pipeline: physical-dimension FormatSpecs, CMYK PDF/X export, deterministic preflight with explanations, mockups; optional flag-gated fulfilment slot later · ❌ **NOT STARTED**
- **P6.20** · Phase 6 (gated) — MediaHub platform surface: versioned public API + signed webhooks + MCP server (drive MediaHub from Claude/ChatGPT/Gemini-class agents), first-party file interop (SVG/PSD/palettes); GWS stays excluded · ❌ **NOT STARTED**
- **P6.21** · Phase 6 (gated) — Mobile PWA: installable share-target capture to media library, offline-tolerant approval queue, mobile-first review/caption/crop; hosted-only stands · ❌ **NOT STARTED**
- **P6.22** · Phase 6 (gated) — AI governance: per-org/per-feature quota ledger on `observability/`, generative moderation, provenance manifests on AI media, role-based feature permissions · ❌ **NOT STARTED**
- **P6.23** · Phase 6 (gated) — Localisation: glossary-protected translation with layout-aware re-render, bilingual approval pairs (Welsh-first), bulk per-language variants, AI-dub pipeline, UI i18n · ❌ **NOT STARTED**
- **P6.24** · Phase 6 (gated) — Pro editor & round-trip: layers/align/guides/page management as validated spec patches, vector node/boolean ops, curves/levels recipes, layered SVG/PSD export-import; deep darkroom/DTP stays a round-trip non-goal · ❌ **NOT STARTED**
<!-- /ROADMAP:TODO -->

## Changelog

### Strategy changelog (hand-written — newest first)

One table row per strategy/roadmap change, added by hand (the daily roadmap
engine or a Fable 5 session). Engineering ships are tracked by the Completed
list and the auto table below, not here.

| Date | Change | Read more |
|---|---|---|
| 2026-06-12 | **Daily scan — Swim England platform move (material):** Swim England announced (4 Mar 2026) a Sport:80-built membership platform launching Autumn 2026, with a new **Rankings API** for verified swim times and a swimmingresults.org integration underway, and a SportsEngine integration announcement expected later in 2026. F.5’s application route should be re-verified against this programme before submitting (dated note added to the F.5 guide); the Swim England↔SportsEngine tie-up is also a fresh input to the queued Route C go/no-go. Competitor watch otherwise quiet (Gipper/SwimTopia/TeamUnify/Swimcloud: no results-ingestion or auto-graphics move); IG Graph API and TikTok Content Posting API policies stable. ⚠️ *Flagged for founder review (not adopted):* PR #418’s public passwordless operator sign-in is an owner-decided demo convenience, but it exposes every tenant’s data and the operator consoles — re-lock it at the latest alongside F.13, before the first club pays (ADR-0015 gate 3). | [Sport:80 announcement](https://www.swimming.org/swimengland/sport80-membership-platform/) · F.5 guide |
| 2026-06-12 | **Repo privacy queued as founder work (F.13):** the GitHub repo is public today and must return to private — at the latest before the first club pays, because the lawful-basis note for the real-children's-data parser fixtures (OPEN_LEGAL_QUESTIONS Q13 / DATA_MAP §6) assumes a private repo, and ADR-0011's hosted-only stance treats the source as the product. The new guide covers the one real cost (private-repo Actions minutes — trim the CI schedules or GitHub Pro), the visibility flip, integration re-verification (Render, Claude Code, CI, Dependabot), and recording the public window honestly in the compliance docs. | Founder guide F.13 · [Q13](compliance/OPEN_LEGAL_QUESTIONS.md) |
| 2026-06-12 | **Sell-gate items closed out + the roadmap now keeps itself honest:** PC.9 and PC.11–PC.14 verified fully shipped on the code side (all 55 pinning tests green) and moved to Completed; their remaining halves are founder-only and live on the founder list with updated step-by-step guides (F.6 gains the breach-owner + off-site-backup steps). The auto-update bot gained a **completed-item sweep**: any to-do item marked ✅ moves itself to Completed on the next push to `main`, and a declared human remainder is kept on — or filed into — the founder list, so finished items can no longer squat on a to-do list. | *Status* section · [`scripts/roadmap_autoupdate.py`](../scripts/roadmap_autoupdate.py) |
| 2026-06-12 | **Business identity, own domain & cheaper hosting prioritised (F.9–F.12 + PC.15/PC.16):** the real company name comes before any further filings (MediaHub is an indefensible filler), then Companies House registration (£100 digital; director ID-verification mandatory since Nov 2025), then the .co.uk domain wired to the live app — so Stripe/ICO/solicitor/Swim England paperwork files **once**, under the real name, and every printed/shared link survives any future host. The Render→VPS move (≈£20/mo → ≈£4–8/mo, prices verified June 2026) is sequenced last, as a DNS flip, and must never displace selling. | Founder guides F.9–F.12 · Phase C section |
| 2026-06-12 | **Sell-gate code remainders + referral engine shipped (PC.9, PC.11–PC.14 code halves):** subprocessor-register guard test (caught 3 undisclosed flows) + unlicensed vendor dirs removed; W.2 consent enforced on the public wall + Children's-Code pass recorded (synthetic `/try` sample replaces real minors' data); whole-org deletion + takeout ZIP; transactional-email seam (password reset / verification / invites / breach channel), daily backups + rehearsed restore, incident runbook; in-product referral engine with auto-granted Stripe rewards. Remaining on the sell gate is founder-only (F.1–F.8). | Phase C section · [CHILDRENS_CODE_PASS](compliance/CHILDRENS_CODE_PASS.md) · [SUPPORT_INCIDENT_RUNBOOK](SUPPORT_INCIDENT_RUNBOOK.md) |
| 2026-06-12 | **UK legal compliance baseline shipped (PR #352):** in-product Terms / accurate Privacy Notice / Cookie Policy / Art. 28 DPA with versioned, recorded acceptance; erasure cascades, account deletion + export; correction/takedown workflow; retention sweep; CCR/DMCCA pre-contract checkout; auth rate-limiting + security headers; DPIA draft. PC.11/PC.13 mostly delivered, PC.12/PC.14 started; the founder half became the F.* list above. | [COMPLIANCE_AUDIT](COMPLIANCE_AUDIT.md) · [COMPLIANCE_HANDOVER](COMPLIANCE_HANDOVER.md) |
| 2026-06-12 | **Compliance-readiness audit:** Phase C had been pushing "go sell" with zero legal surface — compliance had no owning channel because Phase C was composed from a revenue diligence. Fix: a third **lawful-to-sell exit gate** + four sell-gate items **PC.11–PC.14**; no paid contract before gate 3 holds. | [ADR-0015](adr/0015-compliance-readiness-sell-gate.md) |
| 2026-06-11 | **Phase C build-out:** PC.7 try-before-signup demo, PC.8 sponsor manager + exposure reports, PC.10 public achievements wall shipped; `/pricing` now enforces PC.4's revealed-WTP gate (≥5 paid annual); PC.6 audited build-complete. What remains on PC.4/PC.6 is the founder's selling motion. | Phase C section |
| 2026-06-11 | **Phase 6 added:** every content-creation feature in the two competitor inventories (Canva, Adobe Express) gets a MediaHub-shaped, first-party build plan — 24 gated work packages (P6.1–P6.24) with a coverage index. | [CREATIVE_SUITE_PARITY](CREATIVE_SUITE_PARITY.md) |
| 2026-06-11 | **Daily scan — no material change:** competitor watch (Gipper, SwimTopia, TeamUnify, Swimcloud) shows no results-ingestion move; platform policies unchanged; Swim England club-API news only reinforces the queued Route C go/no-go. | [ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md) |

### Recent code activity (auto-updated — newest first)

<!-- ROADMAP:ACTIVITY -->
| Date | Commit | Summary |
|---|---|---|
| 2026-06-12 | `46d3616e7` | fix: a11y: Documents must have <title> element to aid in navigati (#424) |
| 2026-06-12 | `548096e9e` | fix: a11y: Select element must have an accessible name (select-na (#422) |
| 2026-06-12 | `49db59170` | docs(roadmap): 2026-06-12 daily scan — Swim England Sport:80/Rankings API note + changelog row |
| 2026-06-12 | `538a906f9` | Make operator developer sign-in public and passwordless (#418) |
| 2026-06-12 | `2f4302ea5` | Reapply "Make the home-page developer-login link clearly visible" |
| 2026-06-12 | `22224083a` | Revert "Make the home-page developer-login link clearly visible" |
| 2026-06-12 | `1c0dd8c48` | Declare MEDIAHUB_DEV_KEY in render.yaml so it surfaces in the Render dashboard |
| 2026-06-12 | `0c85734c3` | Make the home-page developer-login footer link clearly visible |
| 2026-06-12 | `19947ecf2` | fix: a11y: Form elements must have labels (label) (#409) |
<!-- /ROADMAP:ACTIVITY -->

## The rules we build by

Decisions already made — don't re-open them mid-build. Full reasoning lives
in the linked records. (An **ADR** is an Architecture Decision Record: a
short note of a decision and why, kept in [`docs/adr/`](adr/).)

1. **Hosted only.** Clubs use MediaHub in the browser on our deployment. We
   never offer a copy to run themselves, free or paid — that would hand power
   users a permanent zero-revenue escape hatch.
   ([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md))
2. **Commercialise before generalise.** Phase C outranks all capability
   work. P3–P6 wait for gate 1 (zero-founder onboarding) and gate 2 (≥10
   clubs paying annually).
   ([SCALING_DILIGENCE_2026](research/SCALING_DILIGENCE_2026.md))
3. **Lawful-to-sell before sold.** Gate 3: no paid contract before the legal
   pack, the minors' consent gate, deletion/export rights, and the
   password-reset/breach/backup basics hold.
   ([ADR-0015](adr/0015-compliance-readiness-sell-gate.md))
4. **Stop polishing and sell.** The generative engine cleared the "sellable
   wedge" bar (P1.4); further graphics polish sits strictly behind sell-side
   progress.
5. **Facts are code; judgement is AI; errors are honest.** Parsers,
   detectors, the ranker and the colour-science stay deterministic — never an
   AI guess. Creative judgement goes through `media_ai.llm` / `ai_core.llm`
   (Gemini first, Anthropic failover); with no provider configured the app
   shows an honest error, never a faked caption or palette.
   (See [`../CLAUDE.md`](../CLAUDE.md).)
6. **A human approves before anything publishes. Always.** The single
   exception: a workspace may opt one post type into `fully_autonomous`, and
   even then every post must pass the full publish gate — kill switch,
   provenance, confidence, brand safety, rate caps, and **minors' content
   never auto-publishes**. ([AUTONOMY_MODEL](AUTONOMY_MODEL.md))
7. **Swim England: data yes, promotion no.** Apply for the official data API
   (real, dated — F.5); do not plan around NGB promotional endorsement (no
   evidence it exists for content tools).
   ([ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md))
8. **Do / don't (only what the evidence supports).**
   **DO:** warm-first hand-sell from the Swansea network · annual prepay ·
   a referral engine (2 named intros per signed club) · the Swim England API
   application · Bluesky + Mastodon as the first free publish targets.
   **DON'T:** paid ads · viral-growth assumptions · VC fundraising · US
   expansion before UK validation · multi-sport before ≥10 paying clubs ·
   reliance on NGB promotion · launch-day Instagram/TikTok auto-posting ·
   ToS-breaching scraping of results data.
9. **Honest money expectations (estimates, not promises).** Swimming-only
   saturates at ≈ £150k–£400k ARR (~1,300 UK&I + ~2,740 USA clubs). The old
   "£1M/month" goal is dropped — £1M+ ARR needs multi-sport breadth *and*
   institutional buyers *and* almost certainly a second person. The horizons:

| Horizon | Paying clubs | ARR @ £588–£1,188/club | Outcome probability `[ESTIMATE]` | Binding constraint |
|---|---|---|---|---|
| **H1 — Validation** (≤ ~12 mo) | ~10 (the traction gate) | ≈ £6k–£12k | **~40–55%**, *conditional on the founder actually running the warm + referral motion* | Founder selling-time; first revealed WTP (PC.4) |
| **H2 — Early scale** (~1–2 yr) | ~30–60 | ≈ £18k–£71k | **~25–40%** — needs H1 + referral compounding + retention (annual prepay) | Support capacity (multi-tenancy already shipped — PC.3) |
| **H3 — Swimming ceiling** (~2–4+ yr) | ~125–680 (price-dependent) | **≈ £150k–£400k** | **~10–20%** — needs UK *and* US penetration + a second person | Market size + support capacity |
| **H4 — £1M+ ARR** | (out of wedge) | **≥ £1M** | **low-double-digit-%** — multi-sport (Route A) + institutional buyers (Route B) + a second person | Out-of-wedge expansion |

10. **The head start is real but undefended.** Verified June 2026: no swim
    incumbent ingests a result file and emits branded ranked content — but
    that is a *time advantage, not a moat*. Watch item: Gipper adding
    result-file ingestion would close it.

**Companion docs:** [POST_TYPE_TAXONOMY](POST_TYPE_TAXONOMY.md) ·
[CONTENT_PLANNER](CONTENT_PLANNER.md) · [AUTONOMY_MODEL](AUTONOMY_MODEL.md) ·
[SPORT_PROFILES](SPORT_PROFILES.md) ·
[ARCHITECTURE_TARGET](ARCHITECTURE_TARGET.md) ·
[DEPENDENCY_LICENSING](DEPENDENCY_LICENSING.md) · [THEMING](THEMING.md) ·
[GENERATION](GENERATION.md) ·
[CREATIVE_SUITE_PARITY](CREATIVE_SUITE_PARITY.md) (Phase 6 long-form) ·
evidence base in
[research/SCALING_DILIGENCE_2026.md](research/SCALING_DILIGENCE_2026.md) and
[research/ROADMAP_RESEARCH_2026.md](research/ROADMAP_RESEARCH_2026.md) ·
ideas backlog in
[research/PRODUCT_IDEAS_2026-06.md](research/PRODUCT_IDEAS_2026-06.md).

---

## The plan in depth — open phases

The long-form plan for everything still open, highest priority first.
Completed phases (0, 1, 2, W) and shipped Phase C items live under
**"Done"** at the bottom.

### Phase C — Commercialise & Distribute · PC · 🔵 **IN PROGRESS** · 🥇 TOP PRIORITY

> **Why "Phase C", not a number:** it is lettered because it does not sit
> *after* Phase 5 — it sits **ahead of every numbered expansion phase in
> priority**. Added in the 2026-06 diligence reconcile
> ([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md)); evidence in
> [SCALING_DILIGENCE_2026](research/SCALING_DILIGENCE_2026.md).

**Goal.** Make MediaHub sellable without the founder in the loop — and lawful
to sell.

**State (2026-06-12, second pass).** The engineering is essentially done:
signup/auth (PC.1), Stripe billing code (PC.2), org→workspace multi-tenancy
(PC.3, [ADR-0014](adr/0014-org-workspace-multitenancy-schema.md)), the
revealed-WTP pricing machinery and warm-first funnel tooling on
`/operator/commercial` (PC.4/PC.6 build halves), the `/try` demo (PC.7), the
sponsor manager (PC.8), the public wall (PC.10), the UK legal-compliance
baseline (PR #352), **and now the four sell-gate code remainders
(PC.11–PC.14 code halves) plus the referral engine (PC.9)** — all shipped.
Still open: the founder's identity + selling + paperwork motion (F.1–F.13,
PC.4, PC.6 — founder list) and the two code halves the new identity items
unlock (PC.15 rebrand sweep, PC.16 hosting cutover). **Zero paying clubs
today; code is no longer the excuse.**

**Exit criteria (three hard gates).**

1. **Commercial-readiness gate:** a club can sign up, pay, and publish with
   **zero founder involvement**. No scaling work (P3–P6) starts until this
   holds.
2. **Traction gate:** **≥10 clubs paying annually** before any new sport. If
   the wedge stalls below ~50 clubs over time, that is a retention/PMF
   problem to fix — **not** a signal to add sports.
3. **Compliance-readiness ("lawful-to-sell") gate** (added 2026-06-12,
   [ADR-0015](adr/0015-compliance-readiness-sell-gate.md)): **no paid
   contract** before versioned Terms + Privacy Notice are live and accepted
   at signup, the club DPA exists, ICO registration is done, the minors'
   consent gate enforces end-to-end, deletion + export work, and
   password-reset / breach-notice / verified-backup basics are in place.
   Quotes (PC.4) and the funnel (PC.6) keep moving; a quote may not convert
   to payment until this gate holds.

#### PC.4 — Pricing by revealed willingness-to-pay · 🔵 founder work (guide above)

Build shipped 2026-06-11: a quote ledger (`commercial/wtp.py`,
`DATA_DIR/commercial/wtp_quotes.jsonl`), per-quote Stripe Checkout charging
exactly the quoted figure, an idempotent amount-verified webhook, and both
gates live on `/operator/commercial`. `/pricing` reads the gate and stays at
the honest "Pricing TBC" until **≥5 clubs have paid annual at a tested
price**, then commits the highest cleared figure. The rule (the
>95 %-confidence step): under-pricing is hard to reverse and over-pricing
with no buyers teaches nothing — only revealed WTP from real annual payments
de-risks the tier. The price *levels* remain an unvalidated hypothesis:

| Comparator | Segment | Current price | What it anchors |
|---|---|---|---|
| **Gipper** (closest analog) | US K-12/college athletic depts | **$625 / $1,500 / $3,000 per year, annual-only** *(verified 2026-06-09)* | The institutional ceiling with a sales motion |
| **Predis.ai** (horizontal AI) | Any SMB / creator | **$19 / $40 / $212 per month** *(verified 2026-06-09)* | The buyer's mental ceiling for "AI makes my posts" |
| **SwimTopia** (swim incumbent) | Swim clubs | ~$150–$699/yr annual | What a club pays when software is mission-critical |
| **Canva Free** | Volunteer creator | **£0** | The free substitute every volunteer already has |
| **Swim Wales affiliation** | Whole NGB relationship | £150/yr | The volunteer treasurer's anchor for "what anything costs" |

Read together: the commodity floor and the £150/yr NGB anchor pull the Club
tier down; Gipper proves a far higher institutional ceiling — but only for a
schools/federation buyer with a budget. That gap is why Routes B/C carry the
revenue weight and why the Club tier must be set by revealed WTP, not assumed.

#### PC.6 — Go-to-market / distribution · 🔵 founder work (guide above)

Distribution kills solo ventures, not product gaps. Instrumented 2026-06-11:
lead ledger by source, cold-share readout, referral-debt readout
(`commercial/pipeline.py` on `/operator/commercial`); the Swim England
application is drafted and submission-ready (F.5). The channel evidence:

- **NGB, split in two** (reality-checked, [ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)):
  **(a) data-API access is real — apply** (Swim England approved-systems API,
  announced 1 Oct 2025; grants data + credibility, not promotion);
  **(b) promotional endorsement is speculative** — partner slots are
  category-exclusive and already held; if no NGB movement after ~6 months,
  lean on direct + word-of-mouth. The down-weight reinforces **Route C**
  (incumbent integration) as the realistic distribution partner.
- **Warm-first design** (the >95 %-confidence part): warm/in-person
  founder-led sales convert ~30–50 % vs ~2–5 % cold reply; SaaS referrals
  drive 20–50 % of new B2B customers. Honest funnel to the gate: **~5
  local-warm + ~5 referral**, cold as a capped supplement
  (~0.3–1 % cold-to-paid ⇒ 1,000–3,000 contacts to do it cold — not viable
  solo). Realistic timeline **~3–6+ months**. The *outcome* is unproven and
  IS the validation — it also closes PC.4.

#### F.9–F.12 — Business identity, own domain, cheaper hosting · ❌ founder work (guides above; added & prioritised 2026-06-12) + PC.15/PC.16 code halves

Why this workstream jumped to the head of the founder list:

- **The name is upstream of every filing.** Stripe's KYC (F.1), the ICO
  register entry (F.2), the solicitor-reviewed legal pack (F.3), the Swim
  England application (F.5), insurance (F.6), the Meta verification dossier
  (F.8) and the domain itself (F.11) all embed the legal identity. File them
  under a throwaway name and a later rename re-does — and re-pays — the lot.
  "MediaHub" was always a filler: generic, shared with other companies,
  indefensible as a brand or trade mark. So: **F.9 name → F.10 company →
  F.11 domain → only then the identity-bearing paperwork.**
- **"Due diligence", defined once:** the free checks that prove nobody
  already owns the name — Companies House register, UK trade marks (classes
  9/41/42), the domain, the social handles, and a passing-off web search —
  done *before* committing, so nobody can force a rebrand later. The F.9
  guide is that checklist in order; it costs an afternoon and £0.
- **Domain before host.** Every printed QR code, embedded wall, bookmark and
  webhook that points at `mediahub-gzwc.onrender.com` dies with that
  subdomain. Pointing them at our own `.co.uk` first (F.11 — Render serves
  custom domains + TLS today) makes the later host move an invisible DNS
  flip and unbreaks every link forever.
- **The hosting numbers, honestly** (verified June 2026): Render standard —
  the 2 GB the Chromium/Remotion renders need — is **$25/mo ≈ £20/mo** +
  disk; a capable EU VPS (Hetzner CX22 4 GB → CX32 8 GB) is
  **€3.79–7.59/mo**; UK-soil VPS ≈ £5–15/mo `[ESTIMATE]`. Saving ≈
  **£150–200/yr** `[ESTIMATE]` — real, but less than a fifth of one paying
  club, which is why F.12 sits *behind* the identity work, offers an
  explicit "stay and revisit at traction" option, and may never displace a
  selling week. A side benefit if taken: today's host stores Club Data in
  the **US** (per the DPA's subprocessor register); an EU/UK box simplifies
  F.4's transfer-mechanism homework.
- **The move is already cheap to execute.** The deploy is one Dockerfile
  (compose + `fly.toml` templates exist), all state lives under `DATA_DIR`,
  and PC.14 shipped daily backups with a restore drill rehearsed on every
  test run — restoring a production backup onto a new box *is* the
  migration. PC.16 packages the remainder: reverse-proxy TLS template,
  off-site backup preflight, a Render-API-free log-sentinel source, the
  staged subprocessor/privacy updates, and the cutover runbook.
- **What this is *not*:** a self-host tier. ADR-0011's hosted-only principle
  is untouched — the operator's one deployment changes data centre;
  customers still only ever get a URL.

#### PC.9 — In-product referral engine · ✅ **BUILT (2026-06-12)**

Runs PC.6's compounding mechanism (2 named intros per signed club) inside
the product instead of operator ledgers. **Shipped:**
`commercial/referrals.py` — per-org shareable codes (Organisation page +
`/signup?ref=CODE`), referred signups recorded as `source=referral` leads
with the referrer attributed; the reward (one free month as a Stripe
amount-off coupon via `billing.grant_referral_reward`, valued at the
referrer's own verified annual price / 12 — never an invented figure)
auto-grants when the referred club's first annual payment lands
amount-verified in `commercial/wtp.py` (the idempotent webhook hook **and**
the operator manual-payment path), with honest `pending_manual` records when
the value or the Stripe customer can't be resolved; the referral-debt
readout on `/operator/commercial` counts code-tracked signups as delivered
intros and a live referral section shows codes/signups/rewards. **Exit
met:** a signed club has a shareable code; a paid referral auto-grants the
reward and updates the funnel ledger with zero operator typing
(`tests/test_referrals.py` pins the whole flow end to end).

#### PC.11 — Legal & privacy pack · ✅ **CODE COMPLETE (2026-06-12)** *(sell gate — ADR-0015; founder remainder F.2/F.3/F.4)*

The contractual minimum to take a club's money: MediaHub is a **processor**
for clubs (the controllers) over personal data that is largely **children's**.
**Shipped (PR #352):** `/terms`, `/privacy` (accurate Art. 13/14 notice),
`/cookies`, `/dpa`; versioned signup acceptance recorded in
`legal_acceptances.jsonl` with forced re-acceptance on a `TERMS_VERSION`
bump; per-workspace DPA acceptance + lawful-basis attestation; subprocessor +
transfer disclosures. **Shipped (2026-06-12, code remainder):** the
subprocessor register is now a data structure (`legal.SUBPROCESSORS`) the
DPA table renders from, pinned to the env-flag surface by
`tests/test_subprocessor_register_guard.py` — a provider-shaped env key not
in the register (or the reasoned-exclusion list) turns the build red. The
guard immediately surfaced two undisclosed flows (operator-configured
OpenAI-compatible endpoints; edge-tts voiceover → Microsoft), now disclosed,
and later caught the backup-upload target the same day — working as
designed. The two unlicensed `vendor/` dirs (`agent-skills-main`,
`bencium-marketplace-main`) are removed; `tests/test_vendor_licences.py`
keeps vendor/ licence-clean. **Remaining — founder:** ICO registration +
identity placeholders (F.2), solicitor sign-off (F.3), vendor DPAs (F.4).
**Exit:** an account cannot be created without recorded acceptance of a
versioned ToS + Privacy Notice; an org owner has a recorded DPA acceptance;
the subprocessor guard test is green ✅; ICO registration is logged on the
operator console.

#### PC.12 — Minors' consent & safeguarding gate · ✅ **CODE COMPLETE (2026-06-12)** *(sell gate — W.2 promoted 2026-06-12)*

The product's core output is *publishing children's achievements*; consent
handling stops being optional the day money changes hands. **Shipped:** W.2
itself — the per-athlete consent registry (photo OK / full name / initials-
only / do-not-feature; most-restrictive default; CSV import) enforced
deterministically at generation, in photo scoring and at the publish gate
(see "Done" → W.2) — plus workspace-setup parental-consent attestation
(PR #352). **Shipped (2026-06-12, code remainder):** W.2 consent is enforced
on every public-wall exit — wall text, embed, JSON/RSS feeds and the card
PNG route. A blocked athlete (do-not-feature, or no consent on file under an
active regime) is unreachable, an initials-only athlete is initialled even
with the blanket toggle off (most restrictive always wins), and the
members-only settings page explains each consent-hidden card. The
**Children's-Code pass** over `/wall`, embed, feeds and `/try` is recorded
at [CHILDRENS_CODE_PASS](compliance/CHILDRENS_CODE_PASS.md) with both
findings fixed — including replacing the real-meet `/try` sample (real named
under-18s) with a synthetic deterministic one
(`scripts/make_demo_sample.py`). **Exit met:** a card for a no-consent
athlete cannot render a name/photo, cannot pass the gate, and cannot appear
on the wall; the settings UI explains why; the Children's-Code pass is
recorded; the NGB application's safeguarding claims are all true in code
(`tests/test_wall_consent.py`, `tests/test_childrens_code_public_surfaces.py`).

#### PC.13 — Data lifecycle & rights · ✅ **CODE COMPLETE (2026-06-12)** *(sell gate — ADR-0015)*

The data-subject-rights plumbing a controller club will ask its processor
for. **Shipped (PR #352):** self-serve account deletion (compacting,
tombstone-free), athlete erasure cascading through runs / rendered assets /
PB + research caches / caption memory / posting-log excerpts (test-pinned),
account export, a correction/takedown workflow, and the retention schedule
published in the Privacy Notice + enforced by the `MEDIAHUB_RETENTION_DAYS`
sweep. **Shipped (2026-06-12, code remainder):**
`privacy/org_lifecycle.py` — whole-org deletion (POST `/organisation/delete`,
owner-or-operator with typed-id + password re-verify) cascading runs (through
the per-run erasure cascade), media library, uploaded logos, content packs,
the wall token (structurally — the profile dies), sponsor/exposure ledgers,
the consent + athletes registries, club records, corrections, posting/
telemetry logs, caption memory and memberships, with the Stripe customer and
org-scoped acceptance evidence retained per the DPA and said so; plus the
org-level **takeout ZIP** (GET `/organisation/export` — profile, runs JSON +
workflow states, media blobs, captions, consent CSV, athletes, ledgers,
audit log, manifest) serving SARs and portability in one mechanism. **Exit
met:** a club owner can delete their org or export everything it holds
without founder involvement; deletion verifiably removes the data from
`DATA_DIR` under the ADR-0003/0014 isolation invariants
(`tests/test_org_lifecycle.py` — a second org stays byte-intact); the
published schedule matches what the code does.

#### PC.14 — Operational trust pack · ✅ **CODE COMPLETE (2026-06-12)** *(sell gate — ADR-0015; founder remainder F.1/F.6)*

The boring things a paying customer silently assumes. **Shipped (PR #352):**
the CCR/DMCCA pre-contract checkout (`/billing/confirm`: price honesty,
auto-renewal disclosure, cancellation parity, recorded cooling-off
acknowledgement) and the support contact surfaced in footer/ToS (placeholder
until F.2). **Shipped (2026-06-12, code remainder):**

- **Transactional-email seam** (`notify/email.py` — Resend-style HTTP API
  behind `RESEND_API_KEY` + `MEDIAHUB_EMAIL_FROM`, honest-503 unconfigured,
  P4.5's seam pulled forward): password reset (`/password/forgot` +
  `/password/reset/<token>` — signed expiring single-use tokens, no account
  enumeration), email verification (`/verify-email/<token>`), member-invite
  delivery from the members page, and `/operator/notify-users` — the breach
  channel, every send recorded with per-recipient counts in
  `operator_notices.jsonl` (the ICO 72-hour evidence trail). Resend joined
  the subprocessor register the same day (the PC.11 guard enforced it).
- **Backups + restore drill:** daily `backup_sweep` scheduler task —
  `data.db`/`memory.db` via the SQLite online-backup API, every root JSONL
  ledger, profiles + logos, commercial/sponsor/audit ledgers, runs JSON +
  workflow states (renders/caches excluded as re-derivable) — pruned, with
  optional off-site HTTP PUT; restore via `python -m mediahub.backup
  restore` with a traversal guard, **rehearsed automatically on every test
  run** (`tests/test_backup_restore.py`), state surfaced on the operator
  console.
- **Support + incident runbook:**
  [SUPPORT_INCIDENT_RUNBOOK](SUPPORT_INCIDENT_RUNBOOK.md) (intake, detect →
  contain → assess → notify ICO/clubs, backup/restore procedure, drill log).
- **Billing hygiene:** `/billing` and `/billing/confirm` state where every
  payment's invoice/receipt lives (Stripe customer portal).

**Remaining — founder:** renewal reminders + VAT decision (F.1); breach
owner, insurance, Render disk snapshots and the off-site backup target —
all itemised with steps in F.6's guide. **Exit:** a user can reset their
password unaided ✅; an invite email actually arrives ✅; a restore from
backup has been performed and documented ✅ (automated drill); the support
contact and runbook exist ✅; a test payment produces an expensable invoice
(Stripe portal — verify with the first test payment, F.1).

#### Strategy notes — the three credible £1M+ routes (context, *not* build items)

The only routes the diligence considers arithmetically credible for £1M+,
recorded so the expansion phases stay sequenced with revenue in mind. **All
figures are estimates.**

- **Route A — Multi-sport UK grassroots** (broadest TAM, weakest moat;
  confidence of £1M ~15–20 %) → sequences **P3**.
- **Route B — US schools/colleges** (highest WTP, proven by Gipper/FanWord at
  $625–$3,000/yr; needs US presence; <15 % solo, higher with a partner).
- **Route C — Content/integration layer for swim-data incumbents** (license
  the engine to SwimTopia/TeamUnify rather than fight them; trades upside for
  survival; ~50/50 it beats going direct).

**Highest-leverage combination:** NGB data-API access + incumbent integration
(Route C) for *distribution* + US-schools repositioning (Route B) for
*revenue*.

**Building blocks.** Stripe (Checkout + Customer Portal + webhooks); the
existing `DATA_DIR` ledgers (no SQLAlchemy); the shipped ADR-0003 isolation
invariant; Postiz / Mixpost org→workspace schemas as *reference only* over a
network boundary (never embed AGPL —
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).

**Dependencies.** Upstream of **P3 / P4 / P5 / P6** — all gated behind the
three exit criteria above.

---

### Phase 3 — Broaden ingestion spokes · P3 · ❌ **NOT STARTED (gated)**

**Goal.** Ingest beyond swimming and normalise every spoke to the canonical
schema, so a second sport produces real content end-to-end.

**Exit criterion.** **≥1 non-swimming sport** produces real content
end-to-end from a real data source (football via openfootball, or basketball
via nba_api), with a registered `recognition_<sport>` adapter and its sport
profile wired in.

- **P3.1 — Second-sport engine adapter.** `recognition_football` or
  `recognition_basketball` + `register_sport(...)` (the seam exists —
  [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md)). Bind `engine_sport` in the
  profile.
- **P3.2 — Sports-data API spokes.** `nba_api`, `openfootball`, fixture
  generators; each normalised to `canonical.*`.
- **P3.3 — Running/athletics parsers.** Chip-timing CSV + client-side Garmin
  `FIT` parsing. This sport needs custom parsers — open-source coverage is
  sparse.
- **P3.4 — Normalise all spokes to the canonical schema.** Separate raw
  extraction from cleaned canonical data; flag ambiguous rows for review.

**Building blocks.** `swar/nba_api` (open, keyless — *verify*), `openfootball`
(**public domain**), `ndPPPhz/Fixture-Generator` (MIT). ⚠️ `statsbomb/open-data`
is a **non-OSS data agreement** — use openfootball as the free default.
([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md))

**Dependencies.** Needs **P1 ✅** (sport profiles + taxonomy). Pairs with
**P4** (new sports → new audiences → more publishing targets). Note:
`results_fetch/` already does sport-agnostic *ingestion* from a URL; P3 adds
the per-sport *detector* quality.

---

### Phase 4 — Direct-to-platform publishing · P4 · ❌ **NOT STARTED (gated; P4.5/P4.6 pull-forward candidates)**

**Goal.** Replace the paid Buffer dependency with direct platform adapters,
prioritising the genuinely-free targets.

**Exit criterion.** Posts publish via **direct APIs to ≥2 platforms including
a genuinely-free one** (Bluesky and/or Mastodon), with Buffer demoted to
optional.

#### P4.1 — Bluesky (AT Protocol) + Mastodon adapters · ❌

The free/open posting targets — build these first. **Build detail (June 2026
feasibility pass):** `publishing/bluesky.py` (AT Protocol; app-password or
OAuth — **no app review or business verification exists at all**) and
`publishing/mastodon.py` (per-instance REST; apps register programmatically),
both beside `buffer.py`, both gated by the P2.3 publish gate and writing
`publishing/posting_log.py`; per-workspace account binding in Settings; image
+ W.11 alt-text first, video where the instance allows. Each adapter is days,
not weeks — they rehearse the connector pattern (connect → gate → post → log
→ audit) before the Meta review lands, and they make the autonomy story
demonstrable end-to-end on a zero-risk network.

#### P4.2 — Instagram Graph / Facebook / TikTok / YouTube adapters · ❌

Least-privilege per integration; a human connects each account. **Platform
API policy gates auto-posting (verified June 2026):** Instagram
content-publishing needs a Business/Creator account + a connected Facebook
Page + Meta **App Review** (~2–4 weeks/permission) + **Business
Verification**; TikTok's *unaudited* Content-Posting client can post only
**private (SELF_ONLY), ≤5 users/24h** until it passes an audit. That is *why*
P4.1 ships first and why F.8 starts the Meta paperwork early — the clock runs
in parallel instead of after. Code needs when it opens: a Pillow **JPEG
export** path in `graphic_renderer` (the IG API is JPEG-only), a "Connect
Instagram" flow, and `publishing/meta.py` behind an operator flag + the
publish gate. IG limits are workable (100 API-published posts/24h incl.
Reels/Stories/carousels); group packs as **carousels** by default (the
engagement format in the 2025 benchmarks). **TikTok and YouTube stay deferred
until clubs demand them.**

#### P4.3 — X adapter · ❌

X moved to pay-per-use (6 Feb 2026); treat as a paid, optional target.

#### P4.4 — Demote Buffer to optional · ❌

**Resilience work, not preference:** Buffer's classic developer API has been
closed to new developers since 2019, remaining third-party integrations were
cut off 1 Mar 2025, and the 2026 beta API lacks third-party OAuth — so the
current connector (`publishing/buffer.py`) runs on borrowed time and cannot
onboard new clubs' accounts. P4.1/P4.5/P4.6 are the replacement paths; keep
Buffer only while the legacy token still functions, and surface an honest
error the day it stops.

#### P4.5 — Email digest delivery · ❌ *(pull-forward candidate during Phase C)*

The v7.3 grouped newsletter already builds
(`/api/runs/<run_id>/newsletter`, `content_pack/builder.py`) — nothing can
send it. Email needs no platform review, clubs already run parent lists, and
costs are trivial (Resend: free to 3k emails/mo). **Build:**
`publishing/email.py` behind a provider seam (Resend first; honest-error
unkeyed); a per-workspace member list (CSV import with consent capture,
one-click unsubscribe + suppression list — unsubscribes honoured before any
send); a weekly `scheduler/` job assembling approved-card digests; the PC.8
sponsor slot and W.11 alt text in the template; W.9 approval links ride the
same channel. **Exit:** a club imports members and receives a weekly digest
of approved content; unsubscribes stick; unkeyed deployments honest-error.

#### P4.6 — Telegram channel publishing (+ WhatsApp share stopgap) · ❌ *(pull-forward candidate during Phase C)*

The best effort-to-value publish target found in the June 2026 feasibility
pass: the Telegram Bot API is free, needs no review, and sends **PNG and MP4
natively** — reels currently have no scheduled outlet anywhere. WhatsApp has
no official Channels API, so the legitimate answer today is a share
affordance. **Build:** `publishing/telegram.py` (per-workspace bot token +
channel binding; `sendPhoto`/`sendVideo` with caption + W.11 alt text) behind
the publish gate + posting log; a review-UI "share to WhatsApp" button (copy
caption, download media, open `wa.me`). **Exit:** an approved card *and* a
reel both land in a connected Telegram channel through the gate with full
audit; the WhatsApp button works on mobile.

**Building blocks.** Bluesky / Mastodon (free/open) first; the Telegram Bot
API and a Resend-seamed email channel join the genuinely-free tier; Postiz
adapters as *reference only* (**AGPL** — read the patterns or call over its
API; never embed).

**Dependencies.** Needs **P2 ✅** (autonomy + guardrails govern what may
auto-publish) and **P0 ✅** (Buffer is a flagged, optional paid path).

---

### Phase 5 — Local-AI substitution everywhere · P5 · ❌ **NOT STARTED (gated)**

**Goal.** Give every AI call a zero-cost local path, completing the
no-hidden-fees discipline for the hosted deployment's margins.

**Exit criterion.** With **no cloud keys configured**, the full pipeline
(caption, cutout, voice, graphics, reels) runs **locally end-to-end** —
honest-erroring only where a local model is genuinely unavailable.

- **P5.1 — Ollama LLM provider.** Both wrappers already accept a keyless
  OpenAI-compatible endpoint (`MEDIAHUB_LLM_ENDPOINTS=http://localhost:11434/v1`
  reaches a running Ollama today — P0.4); what remains is shipping/operating
  the model runtime, model-selection defaults, and the operator workflow.
- **P5.2 — Piper TTS replaces edge-tts.** The provider slot is already
  registered (`MEDIAHUB_TTS_PROVIDER=piper` honest-errors until this lands) —
  P5.2 fills the slot with the real backend.
- **P5.3 — whisper.cpp / faster-whisper ASR.** Local transcription for reel
  captions / word-level burn-in. Must land behind a provider seam — the P0.4
  guard fails the build on any unslotted ASR import.
- **P5.4 — Satori graphics fast-path.** ~100× lighter card rendering than
  headless Chromium. A *performance* play, not a licensing one (P0.1's ffmpeg
  engine already removed the Remotion requirement); slots into the same
  `MEDIAHUB_REEL_ENGINE` seam. (The placeholder `satori` engine name was
  removed in the dormant-features audit — register it again when the engine
  actually ships.)

**Building blocks.** All **ADOPT-NOW** licences: Ollama (MIT), Piper (MIT),
whisper.cpp / faster-whisper (MIT), Satori (MPL-2.0). ⚠️ Avoid Coqui XTTS
weights commercially (CPML, non-commercial) — Piper instead.

**Dependencies.** Set up by **P0 ✅** (the local-capable interfaces all
exist — P0.4). Note P5.5 (cutout) shipped long ago — rembg is already the
default; see "Done".

---

### Phase 6 — Creative-suite breadth (our own versions, MediaHub-shaped) · P6 · ❌ **NOT STARTED (gated)**

**Goal.** Build **MediaHub's own first-party version of every
content-creation capability Canva and Adobe Express ship** — re-expressed
through this product's thesis (data in → meaningful, branded, approval-gated
content out), never by integrating their tools or becoming a blank-template
shop. The evidence base is two exhaustive competitor inventories
([Canva](research/CANVA_FEATURE_INVENTORY_2026.md),
[Adobe Express](research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md)); **every
bullet in both** is mapped — feature by feature, with a completeness index —
in [`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md). The 24 one-line
work packages (P6.1–P6.24) are in the Fable 5 to-do list above; the companion
doc carries each package's build depth and per-item exit criterion.

**Gating & order.** Behind the same Phase C gates as P3/P4/P5. Within the
phase, order is **pull-driven** — build what paying clubs ask for first; the
numbering is a default sequence, not a promise. Standing rules hold
everywhere: hosted-only, approval-first publishing + the P2.3 gate, the
deterministic-engine boundary, Gemini→Anthropic honest-error AI, self-hosted
fonts, and the GWS / 9router exclusions. External services appear only as
optional flag-gated provider slots behind our own interfaces where
first-party is impossible (model hosting, platform APIs, print fulfilment,
music rights).

**Exit criterion.** A club can run its **entire content life inside
MediaHub** — social, print, email, microsite, video, documents — without
reaching for Canva/Express; measured per-item (each P6 item carries its own
exit in the companion doc) and in aggregate by wedge clubs actually
cancelling their Canva habit.

**Building blocks.** Almost entirely seams that already ship: the design-spec
director + archetypes (P1.4), `graphic_renderer` + autofit + saliency, both
reel engines (P0.1), the cutout layer, the TTS/ASR/LLM provider slots (P0.4),
`media_library`, `workflow` + publish gate, `scheduler/`, `notify/`,
`observability/`, PC.3 tenancy. New heavy deps stay licence-vetted per
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).

**Dependencies.** Gated behind **Phase C** (all three gates). P6.16's
analytics loop and P6.14's send adapter additionally need **P4** adapters;
P6.2 voice input and P6.5 captions need the **P5.3** ASR seam filled (or a
cloud provider on the same seam). Feeds back into **PC.4** packaging
(quotas/tiers).

---

### Cross-cutting investments (all phases)

| Investment | Status | Notes |
|---|---|---|
| No-hidden-fees discipline | ✅ enforced | The [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) register is pinned by the Phase-0 guard suites: every paid path optional with a free default; every AI surface admits a local provider; no AGPL in-process. |
| Multi-tenancy: org → workspace | ✅ shipped | PC.3 (ADR-0014) on top of the ADR-0003 invariant; pinned by `tests/test_workspace_membership_invariant.py`. |
| Go-to-market / distribution | 🔵 selling open | The #1 risk. Tooling + drafted NGB application live on `/operator/commercial`; the founder's motion (PC.6) and the ≥10-club gate remain open. |
| Safeguarding / minors' data | ✅ locked | ADR-0003 isolation invariant + W.2 consent registry; PC.12 finished the public-surface half (2026-06-12, Children's-Code pass recorded). |
| Explainability & audit trail | ✅ | Every step explainable; autonomous-publish decisions land in the immutable per-org ledger. |
| Product design / UI polish | ❌ open | Targets: Home, Add Input, Content Pack, the autonomy controls. Flask + Jinja stay. |
| Test-suite stability | ✅ | Full suite green (~3,576 passed / 1 skipped, 2026-06-09 — see CLAUDE.md "Running Tests"). Keep green. |
| Operator deployment template | ✅ | `render.yaml` + `.env.example` canonical; one-click Render deploy works. F.12/PC.16 add a cheaper-VPS target on the same Dockerfile (decision pending — see the F.12 guide). |

---

## Done — everything shipped so far

The record of completed work, kept so the plan above stays short. Order:
the live Completed list first, then what's live today, then the completed
phases' condensed records (newest first). Deep detail lives in the linked
ADRs, build reports and tests.

### Completed (the live list)

<!-- ROADMAP:DONE -->
- ✅ **W.1** · Phase W — Athlete registry + milestone detectors (identity across runs; 50th race, debuts, comebacks) *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.2** · Phase W — Consent & safeguarding manager: per-athlete photo/name/initials-only consent enforced at generation + publish gate *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.3** · Phase W — Club records engine + deterministic "NEW CLUB RECORD" detector outranking PBs *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.4** · Phase W — Season-current qualifying-time packs ("Qualified for Counties!") as curated versioned datasets *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.5** · Phase W — LENEX (.lef/.lxf) ingestion: the open SportSystems/European interchange format *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.6** · Phase W — Data-driven meet previews from entry/psych-sheet files (replaces the form-based stub) *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.7** · Phase W — Live meet mode: watch a club-controlled live-results URL, queue cards mid-gala for approval *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.8** · Phase W — Season wraps / monthly recap packs from accumulated run history *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.9** · Phase W — Magic-link mobile approvals (signed expiring review links; no login) *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.10** · Phase W — OCR fallback for scanned/photographed result PDFs with per-row uncertainty flags *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.11** · Phase W — Result-grounded alt-text on every exported/published card *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.12** · Phase W — Print exports: per-swimmer PB certificates + A4 noticeboard posters *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.13** · Phase W — Bilingual captions (Welsh first) per-workspace language setting *(completed 2026-06-12 — Phase W integration pass, ADR-0016)*
- ✅ **W.14** · Phase W — Engagement feedback loop: approval telemetry now; platform metrics after P4.2 *(phase 1 completed 2026-06-12 — Phase W integration pass, ADR-0016; phase 2 waits for P4.2)*
- ✅ **P0.2** · Phase 0 — Cutout free-by-default: in-process rembg is the default (`MEDIAHUB_CUTOUT_PROVIDER=server`); Replicate/PhotoRoom opt-in *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P5.5** · Phase 5 — rembg cutout shipped as the default (MODNet noted as optional upgrade) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P1.1** · Phase 1 — Sport-profile schema + loader + `AutonomyLevel` + swimming/football YAML profiles (inert scaffolding) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P2.1** · Phase 2 — Orchestration backbone the in-process way: `scheduler/` exactly-once SQLite runner + `autonomy/` bounded narrow-tool runner (Temporal rejected by Council) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **PC.1** · Phase C — Self-serve signup + auth: `/signup` `/login` `/logout`, bcrypt, signed session cookie, `users.jsonl` ledger *(completed 2026-06-09, PR #267)*
- ✅ **PC.2** · Phase C — Stripe billing + subscription lifecycle: Checkout, Customer Portal, signed webhook; honest-503 until the operator sets `STRIPE_*` keys *(completed 2026-06-09, PR #267)*
- ✅ **PC.5** · Phase C — Free-self-host tension resolved: **hosted-only**, no customer self-host tier (maintainer decision; ADR-0011) *(completed 2026-06-09)*
- ✅ **P2.4** · Phase 2 — Per-type autonomy controls in the workspace: Settings → Autonomy tab, per-profile per-type policy defaulting to approval_required, publish gate + global kill switch *(completed 2026-06-09, PR #297)*
- ✅ **P1.4** · Phase 1 — Generative Content Engine v2, complete: Appendix A spine SEQ-0→4 (tokens, Tier B director/pool/APCA compliance ranking, gated SEQ-3 cutover with the A/B review approved, data-driven video) + the full PAR-1→8 bucket (12/12 archetype catalog); v2 is the default engine, `MEDIAHUB_GEN_V2=0` is the kill switch; evidence in `build_reports/SEQ_SPINE_2026-06-10.md` and `build_reports/GEN_QUALITY_BASELINE.md` *(completed 2026-06-10, PRs #259/#300/#301)*
- ✅ **P0.1** · Phase 0 — Free reel fallback shipped: `MEDIAHUB_REEL_ENGINE=ffmpeg` renders story cards + meet reels from the cards' own still graphics via FFmpeg (`visual/reel_ffmpeg.py`) — no Node, no Remotion license *(completed 2026-06-10)*
- ✅ **P0.3** · Phase 0 — Every paid dependency provably optional behind a flag with a free default wired — pinned by `tests/test_paid_deps_optional.py` against the DEPENDENCY_LICENSING §2 register *(completed 2026-06-10)*
- ✅ **P0.4** · Phase 0 — Local-capable provider slot on every AI surface: LLM (OpenAI-compatible endpoints incl. Ollama, both wrappers), TTS (`MEDIAHUB_TTS_PROVIDER` with the `piper` slot), ASR (guarded — none may land unslotted), graphics (server-side stills + ffmpeg reel engine + cutout `server` default) — pinned by `tests/test_local_provider_slots.py` *(completed 2026-06-10)*
- ✅ **P0.5** · Phase 0 — AGPL isolation enforced: SearXNG stays a stock, venv-isolated, HTTP-only sidecar; `tests/test_agpl_isolation.py` fails the build on any in-process AGPL import, manifest entry, or Dockerfile drift *(completed 2026-06-10)*
- ✅ **P1.2** · Phase 1 — Realise the post-type taxonomy in code (extend vs layer on `club_platform.content_types` — Council-gated data-model call) *(completed 2026-06-11)*
- ✅ **P1.3** · Phase 1 — Cross-source planner (the strategy brain): fuse own/external/direct signals into a ranked plan keyed by sport profile *(completed 2026-06-11)*
- ✅ **P1.5** · Phase 1 — Brand-DNA-from-URL with no paid API (local scrape + local model + material-color-utilities) *(completed 2026-06-11)*
- ✅ **P2.2** · Phase 2 — Human-approval signal = the autonomy toggle (gated types pause on `workflow.CardStatus` QUEUE → APPROVED → POSTED) *(completed 2026-06-11)*
- ✅ **P2.3** · Phase 2 — Single per-type publish gate: provenance/trust + brand-safety + rate limit + global kill switch on `SafeToPost`; reconcile the two `AutonomyLevel` enums *(completed 2026-06-11)*
- ✅ **PC.3** · Phase C 🥇 — True multi-tenancy: org → workspace in one shared instance (the #1 scaling fix; single-instance-per-club collapses at ~15–40 clubs); Council-pressure-tested + operator-signed-off schema, ADR-0014 *(completed 2026-06-11)*
- ✅ **PC.7** · Phase C 🥇 — Instant try-before-signup demo: paste a results file, get a watermarked 3-card preview, no account *(completed 2026-06-12)*
- ✅ **PC.8** · Phase C 🥇 — Sponsor manager + per-sponsor exposure reports (clubs fund the subscription from sponsor money) *(completed 2026-06-12)*
- ✅ **PC.10** · Phase C 🥇 — Public club achievements page + website embed/RSS of approved cards ("powered by MediaHub") *(completed 2026-06-12)*
- ✅ **PC.11** · Phase C 🥇 (sell gate) — Legal-pack code remainder *(completed 2026-06-12 — founder remainder: F.2/F.3/F.4)*
- ✅ **PC.12** · Phase C 🥇 (sell gate) — Minors'-consent remainder *(completed 2026-06-12)*
- ✅ **PC.13** · Phase C 🥇 (sell gate) — Data-rights remainder *(completed 2026-06-12)*
- ✅ **PC.14** · Phase C 🥇 (sell gate) — Operational-trust remainder *(completed 2026-06-12 — founder remainder: F.1/F.6)*
- ✅ **PC.9** · Phase C 🥇 — In-product referral engine *(completed 2026-06-12)*
<!-- /ROADMAP:DONE -->

**Production findings (auto-filed by the log sentinel)**

Open problems the in-app log sentinel spotted in production logs and filed as
GitHub issues (label `sentinel`) — each is a real, evidenced fault waiting for
a code fix, so treat this list as roadmap to-do items sourced from production
rather than from planning. The block refreshes with the rest of this Status
section; **closing the issue clears it from here**. How the bot works:
[`LOG_SENTINEL.md`](LOG_SENTINEL.md).

<!-- ROADMAP:SENTINEL -->
_No open production findings — the log sentinel has nothing filed._
<!-- /ROADMAP:SENTINEL -->

### What's live today (verified against the code)

- **The pipeline:** upload (HY3 / SDIF / LENEX / PDF / CSV, OCR fallback for
  scans, results-from-a-URL crawl) → deterministic recognition (PBs via
  `pb_discovery/`, club records, milestones, qualifying times) →
  deterministic ranker → branded stills (`graphic_renderer`, 12-archetype
  catalog + design-spec director) and reels (Remotion or the free ffmpeg
  engine) → captions (Gemini→Anthropic, honest errors; Welsh bilingual;
  result-grounded alt text) → approval workflow → export / Buffer / public
  wall / print certificates.
- **Brand intelligence:** brand-DNA-from-URL (SSRF-hardened, evidence-
  grounded), guidelines ingestion, voice imitation, the Adaptive Theming
  Engine (APCA/CIEDE2000-gated, single DTCG palette across web + motion +
  email + graphic), self-hosted fonts on every surface.
- **Platform:** self-serve signup/auth + Stripe billing code, org → workspace
  multi-tenancy (ADR-0014) on the ADR-0003 isolation invariant, per-type
  autonomy + the publish gate + global kill switch, the exactly-once
  scheduler, ntfy/webhook notifications, LLM-usage + uptime observability,
  semantic caption memory, bounded web research, the `/try` demo, sponsor
  manager + exposure reports, the public achievements wall, magic-link mobile
  approvals, live meet mode, season wraps, and the UK legal-compliance
  baseline (PR #352).
- **Substrate capabilities** (shipped outside the numbered phases):
  `ai_core` provider-agnostic LLM client + bounded `ask_with_tools` loop;
  `memory/` semantic caption recall; `web_research/` (DuckDuckGo default,
  optional SearXNG sidecar); `results_fetch/` 3-tier crawl → mirror ZIP →
  pipeline; `scheduler/` + `autonomy/` (queues for review, structurally
  cannot publish); `notify/`; `observability/`.

### Phase C — items already shipped (the build half)

- **PC.1 — Self-serve signup + auth** *(2026-06-09, PR #267)*:
  `/signup` `/login` `/logout`, bcrypt, signed session cookie, `users.jsonl`
  ledger; auth stays optional when no accounts/billing are configured.
- **PC.2 — Stripe billing + subscription lifecycle** *(2026-06-09, PR #267)*:
  Checkout, Customer Portal, signed webhook driving plan state; honest-503
  until the operator sets `STRIPE_*` keys (F.1), so zero added running cost
  until then.
- **PC.3 — True multi-tenancy: org → workspace** *(2026-06-11,
  [ADR-0014](adr/0014-org-workspace-multitenancy-schema.md))*: per-org
  membership binding in one shared instance (`web/tenancy.py`,
  `memberships.jsonl`); orgs with no members behave standalone, so pilots are
  untouched; ADR-0003 strengthened (ownerless legacy runs refuse signed-in
  foreign accounts); pinned by `tests/test_workspace_membership_invariant.py`
  + `tests/test_tenancy.py`. Council-pressure-tested and operator-signed-off.
- **PC.5 — Free-self-host tension resolved: hosted-only** *(2026-06-09,
  [ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md))*: no customer
  self-host tier, free or capped; the old "truly-free self-host" principle is
  retired; `CLAUDE.md` is the authoritative statement.
- **PC.7 — Instant try-before-signup demo** *(2026-06-12)*: public `/try`
  (org-gate-exempt) → watermarked ≤3-card preview from the club's own file or
  the bundled sample; sandboxed `demo-try` org, per-IP + global daily caps,
  per-browser-session visibility, 24h self-cleaning sweep, signup CTA +
  claim-on-conversion. Pinned by `tests/test_try_demo.py`.
- **PC.8 — Sponsor manager + exposure reports** *(2026-06-12)*: sponsor
  registry on `ClubProfile` + `/sponsors` page; deterministic per-card
  sponsor rotation (`club_platform/sponsors.py`) consistent across stills,
  motion and re-renders; exposure ledger + branded monthly per-sponsor report
  joining approvals and the posting log. Pinned by `tests/test_sponsors.py`.
- **PC.10 — Public achievements wall + embed/RSS** *(2026-06-12)*:
  `/wall/<token>` + iframe embed + RSS/JSON feeds, approved-only and
  side-effect-free, initials-first by default, per-card hide/show, token
  revocation 404s the old URL, "powered by MediaHub" badge; cross-tenant
  isolation pinned by `tests/test_public_wall.py`.

### Phase W — Deepen the swimming wedge · ✅ **BUILT (all 14 items, 2026-06-12, one integration pass — [ADR-0016](adr/0016-phase-w-integration-plan.md))**

Wedge-sellability work on existing seams; no new paid dependency; AI surfaces
honest-error. Provenance: the June 2026 ideas research
([`research/PRODUCT_IDEAS_2026-06.md`](research/PRODUCT_IDEAS_2026-06.md), 22
ideas — four became PC.7–PC.10, the distribution slice became P4.5/P4.6).
What each item shipped:

- **W.1 — Athlete registry + milestone detectors:** workspace-scoped athlete
  identity across runs in `data.db` (canonical name + variants, back-filled),
  a review-time "same swimmer?" merge UI with persisted decisions, and
  deterministic milestone detectors (first-ever event, Nth race, first gala,
  comeback). No LLM anywhere in identity or milestones.
- **W.2 — Consent & safeguarding manager:** per-athlete consent registry on
  the W.1 spine (photo / full name / initials-only / do-not-feature;
  most-restrictive default; CSV import), enforced deterministically at
  generation, in photo scoring, and as a publish-gate check; welfare-officer
  export; audited changes. Load-bearing for PC.12.
- **W.3 — Club records engine:** per-workspace records store seeded by CSV
  import, updated **on approval only**; deterministic `ClubRecordDetector`
  ranked above PB; "approaching the record" planner signal; records block on
  the public wall.
- **W.4 — Qualifying-time packs:** versioned curated standards under
  `data/standards/<season>/` with per-table provenance + the seasonal refresh
  runbook (F.7); wired to the existing `QualifyingTimeDetector` + a dedicated
  archetype.
- **W.5 — LENEX ingestion:** `interpreter/lenex_parser.py` (.lef/.lxf via the
  bomb-safe unzip), normalised to the same canonical shape as HY3/SDIF;
  output parity pinned against the HY3 path.
- **W.6 — Data-driven meet previews:** entry files / LENEX entries / PDF
  psych sheets → an approvable "good luck this weekend" pack with zero
  typing; ambiguous rows flagged, never guessed.
- **W.7 — Live meet mode:** a watched club-controlled results URL polled
  politely as a `scheduler/` task; per-swim dedupe; new results → cards
  queued for approval (structurally cannot publish); ntfy push into review;
  watches auto-expire.
- **W.8 — Season wraps / monthly recaps:** deterministic aggregation across
  workspace history (PBs, medals, records, debuts, biggest improver) → a
  recap pack + reel; monthly draft through the autonomy queue.
- **W.9 — Magic-link mobile approvals:** HMAC-signed, expiring, run-scoped
  tokens; a mobile-first approve/edit/reject surface driving the same
  `workflow.CardStatus` transitions with full audit; revocable per run.
- **W.10 — OCR fallback:** Tesseract/RapidOCR behind the interpreter's
  low-confidence path for scans/photos; per-row confidence into the existing
  flag-for-review surface (the engine ships in the Docker image; sandbox runs
  the honest no-engine path).
- **W.11 — Result-grounded alt text:** an `alt_text` field produced in the
  same caption LLM call, threaded through pack ZIP, newsletter, public wall
  and publish payloads; editable in review; honest-error when no provider.
- **W.12 — Print exports:** A4 certificate + noticeboard-poster layouts in
  `graphic_renderer/layouts/` (Playwright prints PDF natively); per-swimmer
  batch export on the pack; BrandKit tokens reused; W.2 consent honoured.
- **W.13 — Bilingual captions (Welsh first):** per-workspace language setting
  (en / cy / bilingual); both variants in one provider call; review shows and
  edits both; gate length checks account for doubled text. *Generalised
  2026-06-12 (PR #363): registry-driven, now covering the top-10 world
  languages + Irish.*
- **W.14 — Engagement feedback loop, phase 1:** per-club approval/edit/reject
  telemetry feeding the caption few-shot store, `memory/` and the planner's
  explainable reasons. *Phase 2 (platform metrics) waits for P4.2.*

### Phase 2 — Autonomy toggles + orchestration backbone · ✅ **COMPLETE (2026-06-11)**

Exit met: a content type can be set to any `AutonomyLevel`;
`fully_autonomous` publishes only when every guardrail + the confidence gate
pass; the kill switch halts instantly; every decision audited. Pinned
end-to-end by
`tests/test_autonomous_publishing.py::test_phase2_exit_criterion_end_to_end`.
Full model: [`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md).

- **P2.1 — In-process scheduler + bounded runner** (instead of Temporal —
  council decision): `scheduler/` atomic-claim SQLite runner + the
  `autonomy/` bounded narrow-tool loop on `ai_core.ask_with_tools`;
  quality-reviewed with five hardening fixes.
- **P2.2 — Approval signal:** `workflow/approval.py::apply_approval_signal`
  on the QUEUE → APPROVED → POSTED transition; gated types pause for a human;
  `fully_autonomous` cards run the gate against the exact caption that would
  ship; autonomy degrades to approval, never the reverse.
- **P2.3 — The publish gate:** `publishing/publish_gate.py` — kill switch →
  per-type policy → provenance (fail-closed) → per-type confidence threshold
  → deterministic brand-safety → safeguarding (minors never auto-publish) →
  per-org rate caps. The two same-named enums reconciled: the runner's reach
  axis renamed `autonomy.tools.RunnerReach`, leaving
  `sport_profiles.autonomy.AutonomyLevel` as the single publishing-policy
  enum.
- **P2.4 — Workspace controls** (PR #297): Settings → Autonomy tab,
  per-profile per-type policy defaulting to `approval_required`, plus the
  per-type confidence threshold and autonomous-channel list.

### Phase 1 — Strategy brain + post-type taxonomy + sport profiles · ✅ **COMPLETE (2026-06-10/11)**

Exit met: a profile-driven planner produces a ranked, explainable content
plan for ≥2 sport profiles, grounded in three signal sources. Pinned by
`tests/test_cross_source_planner.py`; product surface `/plan`.

- **P1.1 — Sport-profile schema + loader:** `mediahub.sport_profiles`
  (`SportProfile`/`PostTypeConfig`, `AutonomyLevel`),
  swimming + football YAML profiles — now live through the planner and P2.4.
  See [`SPORT_PROFILES.md`](SPORT_PROFILES.md).
- **P1.2 — Post-type taxonomy in code** (Council-decided: layer on a
  slug-canonical spine,
  [ADR-0013](adr/0013-post-type-taxonomy-slug-canonical.md)):
  `club_platform/post_types.py`; `ContentType` demoted to the
  implemented-surface badge; two historic renames with read-tolerant aliases.
- **P1.3 — Cross-source planner:** `content_engine` — `signals.py` (own +
  external + direct) fused by `planner.py` into a ranked, explainable
  `ContentPlan`; deterministic scoring (no LLM in the loop); `/plan` +
  `/api/plan/*`. See [`CONTENT_PLANNER.md`](CONTENT_PLANNER.md).
- **P1.4 — Generative Content Engine v2:** the full Appendix A programme —
  DesignTokens contract, 12-archetype catalog, design-spec director with
  candidate pool + APCA compliance ranking, gated SEQ-3 cutover (A/B review
  approved 6/6 vs ≤1/6), data-driven video. v2 is the default;
  `MEDIAHUB_GEN_V2=0` is the kill switch. Evidence:
  [`build_reports/SEQ_SPINE_2026-06-10.md`](build_reports/SEQ_SPINE_2026-06-10.md).
- **P1.5 — Brand-DNA-from-URL, zero paid APIs:** SSRF-hardened local scrape;
  real-pixel palette evidence through `material-color-utilities`; the one
  judgement step on `media_ai.llm` with anti-hallucination validation against
  the evidence universe; honest `no_provider` behaviour.
  `tests/test_brand_dna_local.py`.

### Phase 0 — De-risk licensing & cost · ✅ **COMPLETE (2026-06-10)**

Exit met and **continuously enforced**: zero mandatory paid API in the
critical path; every paid option behind a flag with a free default; AGPL
isolated behind a network boundary. Three guard suites fail the build on any
regression. See [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).

- **P0.1 — Free reel engine:** `MEDIAHUB_REEL_ENGINE=ffmpeg`
  (`visual/reel_ffmpeg.py`) renders story cards + meet reels from the cards'
  own still graphics (Ken Burns + crossfades; CreativeBrief-exact frames) —
  no Node, no Remotion licence; honest `ReelEngineUnavailable` when missing.
- **P0.2 — Cutout free-by-default:** in-process rembg
  (`MEDIAHUB_CUTOUT_PROVIDER=server`); Replicate/PhotoRoom opt-in. (Also
  closes P5.5.)
- **P0.3 — Paid deps provably optional:** `tests/test_paid_deps_optional.py`
  pins, per register row, that with zero paid configuration each paid path is
  off or substituted and honest-errors rather than spending or faking.
- **P0.4 — Local-capable slot on every AI surface:** OpenAI-compatible LLM
  endpoints (incl. keyless Ollama) in both wrappers; the
  `MEDIAHUB_TTS_PROVIDER` seam with `piper` registered; the no-unslotted-ASR
  guard; on-server graphics defaults. `tests/test_local_provider_slots.py`.
- **P0.5 — AGPL isolation:** SearXNG stock + venv-isolated + HTTP-only;
  `tests/test_agpl_isolation.py` fails the build on any in-process AGPL
  import, manifest entry, or Dockerfile drift.

---

## Appendices — status & how they map to Phase 0–5

The previous roadmap revision carried three appendices of runnable build/verification
prompts. They are **retained** below as execution detail (they preserve live
`PAR-*` / `SEQ-*` / `Step N` trailer IDs and link real shipped/in-flight code), with
this lineage note:

- **Appendix A — Generative Content Engine v2.** Current. The build breakdown for
  **P1.4** above (decided in [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md)).
  Its local `§0–§5` / `PAR-*` / `SEQ-*` numbering is self-contained.
- **Appendix B — Growth & Expansion (Steps 8–17).** ⚠️ **Legacy sequence,
  superseded.** Written against the older *Parity → Distinction → Leadership* spine.
  Its still-relevant steps are absorbed by the new phases (commercial/enterprise →
  **Phase C** — Step 7 → PC.1/PC.2/PC.4, Step 14's org→club hierarchy → PC.3; sport
  expansion → **P3**; publishing → **P4**; agentic/autonomy → **P2**).
  Where it conflicts with the new strategy, **the Phase C + 0–5 spine wins.** Retained for
  step-level execution detail only.
- **Appendix C — Adaptive Theming Engine verification.** Current. Verifies the
  **shipped** theming engine summarised under "What's live today" (see
  [`THEMING.md`](THEMING.md)).

> **Lineage in one line:** the new **Phase 0–5** spine supersedes the old **Phase 1
> Parity → Phase 2 Distinction → Phase 3 Leadership** spine; the appendices below are
> the older revision's execution detail, kept and re-mapped, not deleted.

---

## Appendix A — Generative Content Engine v2: Build Prompts

> *Section numbers in this appendix (§0–§5) and item IDs (PAR-\*, SEQ-\*) are local to the appendix. This was previously a standalone doc; it is merged into the roadmap so there is a single reference. It is the build breakdown for **P1.4** (see "Done" above).*

**What this is.** An execution roadmap that turns the recommendations in
`docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md` into ordered,
runnable build stages — *taking the advice in those documents as fact* — with an
implementation prompt and a verification prompt for every stage, and a separate
**parallel bucket** of work that can be run right now, simultaneously, in
different Claude sessions and merged to `main` in any order without conflicts.

**Date:** May 2026 · **Built against:** `main` after PR #137 (the trimmed
CLAUDE.md with the *gated removal process*) and PR #136 (the research docs).

**The problem being solved (from the thesis).** "Click generate" selects a tuple
from a bounded, hand-authored option space dominated by ~6 layout skeletons, with
an LLM constrained to *menu-pick* from fixed enums (`creative_brief/ai_director.py`)
and a renderer that repaints one DOM (`graphic_renderer/render.py`). The fix is to
replace the variation mechanism with: a **brand-token contract** → an **archetype
library + layout intelligence** (Tier A) → an **LLM design-spec director** (Tier B)
→ **generate-a-pool, rank, and compliance-check**, while keeping the deterministic
engine, the captions, Remotion, and the renderer substrate.

---

### 0. How to use this document

There are **two tracks**:

- **The Parallel Bucket (§2)** — additive, file-disjoint work that does **not**
  affect the build because each item ships *new, inert files* (or owns one
  isolated surface). These can be run **now**, each in its own Claude session,
  each on its own branch → PR to `main`. They are wired into the live pipeline
  later by the spine. **Run these first / concurrently.**
- **The Sequential Spine (§3)** — build-order-dependent work that modifies the
  shared files (`generator.py`, `ai_director.py`, `render.py`,
  `content_pack_visual/integration.py`, the `web.py` route) and *wires in* the
  parallel modules. These must be done in order, behind the `MEDIAHUB_GEN_V2`
  flag, and the removal stage follows CLAUDE.md's gated-removal process.

Each stage has a **Context** (what/why + files + thesis ref), an **Implementation
prompt** (paste into a fresh session), and a **Verification prompt** (paste into a
*separate* session to confirm it was done properly).

#### Relationship to the in-flight Adaptive Theming Engine (ROADMAP 1.6)

Do **not** rebuild the brand-token system. ROADMAP §1.6 already delivers the
DTCG-format `derived_palette`, ~25 MD3 role tokens, and a single-source-of-truth
JSON consumed by web/motion/email/graphic (Stage G). The thesis's "Layer 1 — brand
token contract" is **mostly that work, extended** with three generation-specific
additions (logo lockups by theme/form, type pairing, a structured voice profile,
and *semantic role descriptions an LLM can read*). SEQ-0 below extends the theming
token object; it does not duplicate it. If 1.6 Stage G is not yet merged, SEQ-0
coordinates with it rather than forking it.

---

### 1. The shared prompt preamble (every prompt inherits this)

To keep each prompt short, every Implementation and Verification prompt below
**assumes this preamble**. Paste it at the top of the session if the model hasn't
read the repo yet:

> **Preamble — read before doing anything.** You are working in the MediaHub repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md` in full, plus
> `docs/research/mediahub-generative-ai-thesis.md` (the plan) and the file(s) named
> in the task. Hard rules you must follow:
> - **Deterministic engine is off-limits to AI:** never Gemini-ify parsers
>   (`interpreter/`, `pb_discovery/`), detectors (`recognition*/`), the ranker
>   (`legacy/swim_content_v5/ranker_v3.py`), or colour-science (`theming/`,
>   CIEDE2000/APCA). You may *read* their outputs.
> - **Honest error, never a fake fallback:** if an AI provider is unavailable,
>   surface `ProviderNotConfigured`/`ClaudeUnavailableError` or fall back to a
>   *real deterministic* path — never a fabricated caption/graphic.
> - **Judgement goes through `media_ai.llm` / `ai_core.llm`** — never new hardcoded
>   heuristics for "which layout / which copy / which tone."
> - **Removing or replacing a route or data structure** requires CLAUDE.md's
>   *15-step breakage check before* + *15-step verification after* + a *dead-code
>   sweep*. Do not skip it.
> - **Tests:** run `python -m pytest tests/ -q` and add tests for new code; there
>   must be **no new failures** vs `main`, and you must not delete/skip/weaken a
>   test to go green.
> - **Branch & ship:** create a feature branch `claude/<short-name>`, commit with a
>   clear message, push, and **open a PR** (do not merge to `main` without the
>   user's approval — the user merges).
> - **Scope discipline:** touch only the files this task names. If you find you need
>   to modify a file the task says not to touch, stop and report instead.

---

### 2. The Parallel Bucket — run these now, concurrently, one session each

**Why these are safe to run simultaneously and merge in any order:** every item
below either creates **only new files** (inert — nothing imports them yet, so the
build is unaffected) or owns a **single isolated surface** that no other item and
no spine stage touches. The "Files you may touch" / "Files you must NOT touch"
lists guarantee no two parallel PRs edit the same file. Merge them to `main` in any
order; the spine (§3) wires them in afterward.

> **Conflict-safety contract (applies to every PAR item):** You may create/modify
> **only** the files listed under "Owns." You must **NOT** touch `web/web.py`,
> `creative_brief/generator.py`, `creative_brief/ai_director.py`,
> `graphic_renderer/render.py`, or `content_pack_visual/integration.py` (those are
> spine files). Your change must leave the existing build and tests green on its own.

#### PAR-1 · Caption quality pack
**Owns:** `src/mediahub/web/ai_caption.py` (the only item that touches it) + new
`src/mediahub/web/caption_examples.py` + `tests/test_caption_quality.py`.
**Context:** Captions are already strong (thesis §5.6); this adds the verified
brand-voice recipe. Independent of the graphic surgery.

**Implementation prompt:**
> [Preamble.] Extend MediaHub's caption generation (`web/ai_caption.py`) with the
> brand-voice recipe from thesis §5.6, all inside the existing Gemini→Anthropic
> path. Add: (1) **few-shot injection** — accept up to 5 of the club's own past
> captions and inject them verbatim as examples in the system prompt (store/read
> them via a new `web/caption_examples.py` keyed by `profile_id`, persisted under
> `DATA_DIR`); (2) **generate-many-then-dedupe** — generate 4–6 candidates and
> return them ranked, dropping any whose n-gram/embedding similarity to a recent
> caption or to each other is above a threshold; (3) **per-platform variants** —
> given one approved caption, produce feed / story / X / LinkedIn variants with
> per-platform length+tone constraints; (4) an explicit **AI-tell ban-list**
> ("delve", "elevate", "in the world of", reflexive "!"); (5) an **approval-loop**
> hook: a function that appends an edited+approved caption to the club's
> few-shot example store. Keep the existing function signatures working
> (additive params with defaults). Add `tests/test_caption_quality.py` covering
> dedupe, ban-list filtering, and few-shot injection (mock the LLM). Do NOT touch
> any spine file. Branch `claude/gen-par-1-captions`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-1 (caption quality pack) was done properly. Confirm:
> only `web/ai_caption.py`, `web/caption_examples.py`, and the new test were
> changed (no spine files); the existing caption route still works with the new
> defaults; few-shot examples are injected and capped at 5; dedupe actually drops
> near-duplicates; the ban-list filters the listed phrases; the approval-loop
> appends to the store; captions still raise an honest error (no fabricated
> fallback) when no provider is configured. Run the full suite — no new failures.
> Report a pass/fail checklist.

#### PAR-2 · Auto-fit text helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/autofit.py` + `tests/test_autofit.py`.
**Context:** Bannerbear's verified core feature (eval §6.1). A pure function that
computes the font-size (px) that fits a string into a given box at a given
font/weight, so long names/events never break a layout. Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/autofit.py`: a pure, deterministic helper
> `fit_font_px(text, box_w, box_h, *, font_family, weight, min_px, max_px,
> line_height) -> int` that returns the largest integer px size at which `text`
> fits within `box_w × box_h` (binary search; approximate advance-width via a
> char-width table or Pillow `ImageFont.getbbox` if a font file is available, else
> a metric heuristic — but keep it deterministic and documented). Add helpers for
> multi-line wrapping. No network, no LLM (this is layout maths, not judgement).
> Add `tests/test_autofit.py` with golden cases (short vs very long swimmer names,
> narrow vs wide boxes). Create ONLY these two files. Branch
> `claude/gen-par-2-autofit`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-2: only `graphic_renderer/autofit.py` and its test were
> added; `fit_font_px` is deterministic (same inputs → same output), monotonic
> (a longer string never returns a larger size for the same box), respects
> min/max bounds, and has no LLM/network calls. Run the suite — no new failures.

#### PAR-3 · Saliency-aware crop helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/saliency.py` + `tests/test_saliency.py`.
**Context:** Subject-aware crops (eval §6.1, thesis §5.3.1) so one archetype looks
correct and different with every photo. Deterministic maths (consistent with the
colour-science rule). Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/saliency.py`: deterministic helpers that,
> given an image path, return candidate crop rectangles for a set of target aspect
> ratios (e.g. `9:16`, `1:1`, `4:5`) using a saliency/energy heuristic (e.g.
> gradient-magnitude / edge density via Pillow+numpy, or reuse the existing cutout
> alpha if present to bias toward the subject). Expose
> `crops_for(image_path, ratios) -> dict[ratio, (x,y,w,h)]` and a
> `best_crop(image_path, ratio)`. No LLM, no network. Add `tests/test_saliency.py`
> with a couple of synthetic images (subject in different corners) asserting the
> crop tracks the subject and stays within bounds. Create ONLY these two files.
> Branch `claude/gen-par-3-saliency`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-3: only the saliency module + test were added; crops are
> deterministic, stay within image bounds, match the requested aspect ratios, and
> track the subject on the synthetic fixtures; no LLM/network. Suite green.

#### PAR-4 · Design-spec schema + validator (the Tier B contract, inert)
**Owns:** new `src/mediahub/creative_brief/design_spec.py` + `tests/test_design_spec.py`.
**Context:** The structured JSON contract the LLM art-director will emit (thesis
§5.4). Defining it as a standalone schema + normaliser now lets SEQ-2 just call it.
Inert until the director uses it.

**Implementation prompt:**
> [Preamble.] Create `creative_brief/design_spec.py` defining the `DesignSpec`
> dataclass and a strict `normalise(raw: dict, *, archetypes: list[str],
> token_roles: list[str]) -> DesignSpec` that coerces a (possibly hallucinated)
> LLM JSON object into a valid spec — every field constrained to a known enum or a
> token *role* name, with safe defaults on any out-of-vocabulary value (so a bad
> LLM response can never produce an illegal/illegible card). Fields per thesis
> §5.4: `archetype`, `colour_roles` (ground/surface/headline/accent → role names),
> `focal_element`, `crop_intent`, `hero_stat`, `secondary_stats`, `headline_hook`,
> `accent_treatment`, `logo_lockup`, `mood`, `motion_intent`, `rationale`. Provide
> the JSON-schema dict for schema-constrained decoding. No live LLM call here — this
> is the contract + validator only. Add `tests/test_design_spec.py` (valid spec
> round-trips; hallucinated/garbage values normalise to defaults; enums enforced).
> Create ONLY these two files. Branch `claude/gen-par-4-design-spec`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-4: only the design_spec module + test were added; an
> out-of-vocabulary value for every field normalises to a safe default; the schema
> dict matches the dataclass; no card-illegal spec can be produced. Suite green.

#### PAR-5 · Variant metrics module (success-metric instrumentation, inert)
**Owns:** new `src/mediahub/quality/variant_metrics.py` + `tests/test_variant_metrics.py`.
**Context:** Thesis §8C success metrics — archetype diversity and perceptual
distance across a candidate pool. Standalone scoring lib; inert until SEQ-2 wires it.

**Implementation prompt:**
> [Preamble.] Create a new `quality/` package with `variant_metrics.py`:
> deterministic functions `archetype_diversity(specs) -> float` (distinct
> archetypes / candidates) and `perceptual_spread(png_paths) -> float` (mean
> pairwise distance using a cheap perceptual hash or downscaled-LAB histogram
> distance — no heavy ML). Add `caption_repetition(captions) -> float` (max n-gram
> overlap). These power the §8C targets. No LLM/network. Add
> `tests/test_variant_metrics.py`. Create ONLY the new package files + test.
> Branch `claude/gen-par-5-metrics`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-5: only the new `quality/` module + test were added;
> metrics are deterministic and bounded; diversity rises with distinct archetypes;
> spread rises with visually different PNGs. Suite green.

#### PAR-6 · Brand bootstrap extractor (draft from a URL, inert)
**Owns:** new `src/mediahub/brand/bootstrap_extract.py` + `tests/test_bootstrap_extract.py`.
**Context:** "Paste your club URL → draft brand kit" onboarding (thesis §5.3),
modelled on Brandfetch's schema. A pure extractor that returns a **draft**
DesignTokens dict (for human confirmation — never auto-trusted). It may *read* the
existing `brand/link_handlers/` but must not modify them or add a route (wiring is
SEQ work). Inert until onboarding calls it.

**Implementation prompt:**
> [Preamble.] Create `brand/bootstrap_extract.py`: `extract_brand_draft(url) ->
> dict` returning a *draft* token set (palette candidates with semantic guesses,
> logo URLs by inferred form, font guesses) shaped like the DesignTokens contract,
> reusing existing `brand/link_handlers/` for fetching where possible (read-only
> import). Mark every field `"confirmed": false`. No route, no web.py edit, no
> auto-apply. Honest about uncertainty (small-club extraction is unreliable — return
> confidence flags, never silently guess). Add `tests/test_bootstrap_extract.py`
> (mock the fetch; assert draft shape + all `confirmed:false`). Create ONLY these
> two files. Branch `claude/gen-par-6-brand-bootstrap`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-6: only the extractor + test were added; no route/web.py
> change; output is a draft (all `confirmed:false`), shaped like DesignTokens; the
> existing `link_handlers` were imported, not modified. Suite green.

#### PAR-7 · Archetype templates (the fan-out item — one session per archetype)
**Owns (per session):** ONE new file `src/mediahub/graphic_renderer/layouts/v2/<name>.html`
(+ optional `<name>.notes.md`). Run this prompt N times in N sessions, once per
archetype name — each writes a *different* file, so they never conflict.
**Context:** The structural variety the 6 families lack (thesis §5.3.1). Author
each against the **slot convention** below so SEQ-1 can wire them uniformly.

**Slot convention (author against this exactly):** use `{{PLACEHOLDER}}` string
substitution (not Jinja), and reference brand colours **only** via CSS custom
properties (`var(--mh-primary)`, `var(--mh-on-primary)`, `var(--mh-surface)`,
`var(--mh-on-surface)`, `var(--mh-accent)`, `var(--mh-outline)`) — never hardcode a
hex. Available text placeholders: `{{ATHLETE_FULL_NAME}}`, `{{ATHLETE_FIRST_NAME}}`,
`{{ATHLETE_SURNAME_DISPLAY}}`, `{{EVENT_NAME}}`, `{{RESULT_VALUE}}`,
`{{ACHIEVEMENT_LABEL}}`, `{{MEET_NAME}}`, `{{CLUB_FULL}}`, `{{HERO_STAT}}`,
`{{LOGO_BLOCK}}`, `{{ATHLETE_IMG_BLOCK}}`, `{{ACCENT_DECORATION}}`,
`{{SPONSOR_BLOCK}}`. Canvas is `{{WIDTH}}×{{HEIGHT}}`. Include `{{BASE_CSS}}` at the
top. The archetype must read *structurally distinct* from `individual_hero` /
`big_number_hero` at a glance.

**Suggested archetype names (assign one per session):** `split_diagonal_hero`,
`full_bleed_photo_lower_third`, `editorial_numbers_grid`, `centered_medal_spotlight`,
`magazine_cover`, `ticker_strip`, `stat_stack_sidebar`, `triptych_progression`,
`quote_led_recap`, `big_number_dominant`, `duo_athlete_split`, `minimal_type_poster`.

**Progress (PAR-7 catalog):** ✅ **12 of 12 archetypes live — catalog complete** (`duo_athlete_split` added 2026-06-09: a matchday duel poster — the canvas bisected into two equal vertical halves by a hard accent seam, photo bay vs brand data bay, crossed by the one full-width name band that bridges the seam). Representative seeds-0..9 pack archetype-diversity saturated at **1.00**; new archetype nearest-neighbour dHash **0.355** sits above the contemporaneously re-measured pre-existing library floor (**0.285**) so the floor is unchanged (genuine new structure, not a reskin). Every archetype now ships a `.notes.md` director catalog entry (test-enforced). The verification pass also fixed two renderer-wide typography defects (self-hosted fonts never loaded — `set_content` blocked `file://` woff2 fetches; Anton autofit under-measurement clipping long surnames) — see `docs/build_reports/GEN_QUALITY_BASELINE.md`.

**Implementation prompt (template — fill in `<NAME>`):**
> [Preamble.] Author ONE new graphic archetype `graphic_renderer/layouts/v2/<NAME>.html`
> following the slot convention in `docs/ROADMAP.md` (Appendix A → PAR-7)
> exactly (CSS-variable colours only, the listed `{{PLACEHOLDERS}}`, `{{BASE_CSS}}`
> at top). It must be a *structurally distinct* portrait layout (1080×1350 and
> 1080×1920 must both read well) — a genuinely different composition from the
> existing families, not a reskin. Self-contained HTML/CSS; no JS, no network, no
> hex literals. Add a one-paragraph `<NAME>.notes.md` describing the composition and
> when the director should pick it. Create ONLY those file(s) under `layouts/v2/`.
> Do not touch `render.py` or any other file. Branch `claude/gen-par-7-<NAME>`,
> commit, open a PR. (You cannot fully render-test it until SEQ-1 wires `layouts/v2`;
> instead, validate the HTML is well-formed and every placeholder/variable matches
> the convention.)

**Verification prompt:**
> [Preamble.] Verify a PAR-7 archetype: exactly one new `layouts/v2/<NAME>.html`
> (+ notes) was added; it uses ONLY CSS-variable colours (grep for `#` hex literals
> → none in colour positions); every placeholder is on the §PAR-7 allow-list;
> `{{BASE_CSS}}` is present; the layout is structurally distinct from the existing
> families; no other file changed. Suite green (these files are inert, so the suite
> is unaffected — confirm that too).

#### PAR-8 · Documentation + ADR (pure docs, inert)
**Owns:** new `docs/GENERATION.md` + `docs/adr/0001-generation-engine-v2.md`.
**Context:** Single canonical doc for the new engine + an architecture-decision
record. Pure docs; conflicts with nothing.

**Implementation prompt:**
> [Preamble.] Author `docs/GENERATION.md` documenting the v2 generation
> architecture from thesis §5 (the token contract, archetype library, design-spec
> director, pool/rank/compliance, captions, video), the `layouts/v2` slot
> convention (copy it from this roadmap §PAR-7), and the `MEDIAHUB_GEN_V2` flag.
> Also author `docs/adr/0001-generation-engine-v2.md` recording the decision to
> replace the enum-permutation/menu-picker engine with the design-spec director
> (context, decision, alternatives rejected per thesis §4A, consequences). Docs
> only. Branch `claude/gen-par-8-docs`, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-8: only the two docs were added; `GENERATION.md` matches
> thesis §5 and the §PAR-7 slot convention; the ADR records context/decision/
> alternatives/consequences. No code changed.

---

### 3. The Sequential Spine — build in order, behind `MEDIAHUB_GEN_V2`

These stages modify the shared spine files and wire in the parallel modules. They
**cannot** run concurrently with each other (they touch the same files); run them
in order, each as its own PR, after the parallel bucket is merged. Everything that
changes live behaviour is gated by the `MEDIAHUB_GEN_V2` feature flag until SEQ-3's
cutover, so production never regresses.

#### SEQ-0 · DesignTokens contract + feature-flag scaffolding · ✅ **DONE**
**Depends on:** ROADMAP §1.6 Stage G (DTCG `derived_palette` JSON) if merged; else
coordinate. **Touches:** `brand/kit.py`, a new `config`/flag read, `theming/` (read).
**Thesis ref:** §5.3.

**Implementation prompt:**
> [Preamble.] Extend the brand token object (`brand/kit.py` / the theming
> `derived_palette`) into the generation **DesignTokens contract** from thesis §5.3,
> *additively* — keep the existing flat `primary_colour`/`secondary_colour`/
> `accent_colour` as derived aliases so nothing breaks. Add: semantic colour
> **roles** with `brightness` + `when_to_use` text (reuse the existing APCA/ΔE2000
> numbers from `theming/`), **logo lockups** typed by `form`
> (icon/horizontal/stacked/mono) and `theme` (light/dark) — extend
> `theming/logo_chip.py` to *select* the lockup for a given background — a typed
> `type` pairing, and a structured `voice` profile (examples, banned phrases, emoji
> policy) that the caption store (PAR-1) can populate. Add a `MEDIAHUB_GEN_V2`
> feature flag read (env, default off) and a single helper
> `resolve_design_tokens(profile_id) -> dict` that returns the full contract with
> the semantic role descriptions an LLM can consume. No behaviour change yet (flag
> off). This is additive — the gated-removal process is NOT needed here. Add tests
> for `resolve_design_tokens`. Branch `claude/gen-seq-0-tokens`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-0: the old flat BrandKit fields still resolve (back-compat
> alias); `resolve_design_tokens` returns roles with `brightness`+`when_to_use`,
> logo lockups by form/theme, type pairing, and a voice profile; `logo_chip` selects
> a lockup per background; the `MEDIAHUB_GEN_V2` flag exists and defaults off; old
> persisted profiles still load. Suite green (no new failures); the change is purely
> additive (no removals).

#### SEQ-1 · Tier A — archetype library + layout intelligence (the immediate fix) · ✅ **DONE**
**Depends on:** SEQ-0, PAR-2 (autofit), PAR-3 (saliency), PAR-7 (archetypes),
optionally PAR-6. **Touches:** `graphic_renderer/render.py`,
`creative_brief/generator.py`, `legacy/swim_content_v5/ranker_v3.py` (read-only
addition). **Thesis ref:** §5.3.1. **This stage alone is expected to fix "samey."**

**Implementation prompt:**
> [Preamble.] Implement Tier A (thesis §5.3.1), gated behind `MEDIAHUB_GEN_V2`.
> (1) Teach `graphic_renderer/render.py` to load archetypes from
> `graphic_renderer/layouts/v2/*.html` (the PAR-7 files) using the documented slot
> convention, resolving colours from the DesignTokens roles (SEQ-0) as CSS
> variables. (2) Wire in `autofit.fit_font_px` (PAR-2) for headline/name/event
> slots so long strings never overflow. (3) Wire in `saliency.best_crop` (PAR-3) so
> the athlete photo is cropped per the archetype's `crop_intent`. (4) In
> `creative_brief/generator.py`, add a **deterministic archetype-picker** (seeded by
> the existing `auto_variation_seed_for`, stable per card, different across cards)
> that selects among the v2 archetypes — this is the no-AI fallback floor. (5)
> Expose, *read-only*, the ranker's ranked **emphasis angles** (lead with time / PB
> delta / placing / relay split) so the brief can vary the hero stat — do NOT change
> the ranker's scoring. With the flag ON, a content pack should use ≥6 distinct
> archetypes. Add tests asserting archetype diversity across a pack and that autofit
> prevents overflow. Branch `claude/gen-seq-1-tier-a`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-1: with `MEDIAHUB_GEN_V2=1`, rendering a pack uses ≥6
> distinct v2 archetypes; with the flag OFF, behaviour is unchanged (old engine).
> Long swimmer names/events no longer overflow (autofit); photo crops track the
> subject (saliency); the ranker's *scoring is byte-identical* to before (only a
> read-only emphasis-angle accessor was added — confirm no PB/ranking regression per
> CLAUDE.md engine rule). Walk upload→process→review with the flag on; cards render,
> captions/confidence intact. Suite green. Report the archetype-diversity number.

#### SEQ-2 · Tier B — design-spec director + pool, rank, compliance · ✅ **DONE**
**Depends on:** SEQ-1, PAR-4 (design_spec), PAR-5 (variant_metrics). **Touches:**
`creative_brief/ai_director.py`, `content_pack_visual/integration.py`,
`web/web.py` (the create-graphic route response). **Thesis ref:** §5.4–5.5.

**Implementation prompt:**
> [Preamble.] Implement Tier B (thesis §5.4–5.5), gated behind `MEDIAHUB_GEN_V2`.
> (1) Rewrite `ai_director.ai_creative_direction` to emit a **DesignSpec** (use
> `creative_brief/design_spec.py` from PAR-4) under JSON-schema-constrained decoding
> via `ai_core` — the LLM now chooses archetype, colour-role assignment, focal
> element, hero stat (from the ranker's emphasis list), generated hook, crop intent,
> accent, logo lockup, mood, and a `rationale` (which feeds the existing "why this
> design" explainability). Keep the SEQ-1 deterministic archetype-picker as the
> fallback floor when no provider is configured (honest error / real floor — never a
> fabricated card). (2) In `content_pack_visual/integration.py`, emit **N candidate
> specs** (default 5), render the pool (cheap — Playwright), run a **deterministic
> brand-compliance check** (APCA/ΔE2000 contrast, correct logo lockup for the
> background, sponsor-safe zones) that attaches an explainable score to each, score
> diversity with `quality/variant_metrics.py` (PAR-5), rank with the existing ranker,
> and return a **ranked shortlist**. (3) Extend the create-graphic route response in
> `web/web.py` to return the shortlist + per-candidate compliance score (additive
> JSON; keep the old single-visual fields populated from the top candidate so
> existing callers keep working). This stage *replaces* the menu-picker prompt — but
> the old `random_variation_profile`/enum path stays in place as the flag-off route
> until SEQ-3, so this is still additive at the route level. Add tests for spec
> emission (mock LLM), normalisation of a bad LLM response to a legal card, and the
> compliance score. Branch `claude/gen-seq-2-tier-b`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-2: with the flag on, the director emits a schema-valid
> DesignSpec; a deliberately malformed LLM response still yields a legal, legible
> card (PAR-4 normalisation); the pipeline returns a ranked shortlist of ≥4
> structurally distinct candidates each with a compliance score; the top candidate
> populates the legacy single-visual response fields (old callers unaffected); with
> no provider configured it falls back to the deterministic archetype floor (no
> fabricated output). Flag OFF = old behaviour. Suite green. Confirm no spine file
> outside the three named was touched.

#### SEQ-3 · Cutover + gated removal of the dead engine (the "full removal") · ✅ **DONE**
**Depends on:** SEQ-2 proven (A/B beats the old engine in review + suite green).
**Touches (removals):** `creative_brief/generator.py`,
`creative_brief/ai_director.py`. **Thesis ref:** §5.1, §7 cutover. **This is a
route/data-structure-adjacent removal — follow CLAUDE.md's gated process exactly.**

**Implementation prompt:**
> [Preamble.] Cut over to v2 and remove the dead variation engine — this is a
> deliberate replacement, so you MUST run CLAUDE.md's **15-step breakage check
> (Section A) before** touching anything, write the breakage list, then remove and
> run the **15-step verification (Section B) after**, then the **dead-code sweep
> (Section C)**. Steps: (1) flip `MEDIAHUB_GEN_V2` default to ON. (2) Remove the
> now-dead enum-permutation path: `random_variation_profile`, `_legacy_axes_from_seed`,
> `_PHRASE_TABLES`/`_phrase_for_seed`, and the closed-vocabulary menu-picker
> `_system_prompt` in `ai_director.py`; demote `BACKGROUND_STYLES`/`ACCENT_STYLES`/
> `TYPOGRAPHY_PAIRS`/`COMPOSITIONS`/`PHOTO_TREATMENTS` to renderer-internal building
> blocks only if still needed, else remove. (3) Keep the deterministic archetype
> floor. (4) Migrate or tolerate old persisted briefs/`variation_signature` fields
> (decide explicitly per breakage step 13). Do NOT remove the route or the
> `CreativeBrief` dataclass (extend, don't delete — production depends on them).
> Provide the completed A-list, B-list, and dead-code sweep in the PR description.
> Branch `claude/gen-seq-3-cutover`, run the full suite (no new failures, no
> weakened tests), PR.

**Verification prompt:**
> [Preamble.] Independently re-run CLAUDE.md Section B (15-step safe-removal
> verification) against SEQ-3: zero stray refs to the removed symbols (whole-repo
> grep); imports resolve; full suite green with no deleted/skipped/weakened tests;
> the create-graphic route + templates still work; old persisted runs still load (or
> are migrated); engine accuracy (PB detection, ranking) byte-identical; no new
> debug/IDOR exposure, no `ANTHROPIC_API_KEY` leak; diff contains only intended
> edits; dead-code sweep actually happened (no orphaned helpers, `_unused` vars, or
> "removed" placeholder comments). Report the checklist with pass/fail per step.

#### SEQ-4 · Video — data-driven scene structure (+ optional Tier C) · ✅ **DONE**
**Depends on:** SEQ-1/2 (the richer brief). **Touches:** `visual/motion.py`,
`remotion/src/compositions/`, optionally `visual/ai_background.py`. **Thesis ref:**
§5.7.

**Implementation prompt:**
> [Preamble.] Enrich video (thesis §5.7). (1) The richer brief (archetype, hero
> stat, tokens) already flows into `visual/motion.py` props — extend the Remotion
> compositions in `remotion/src/compositions/` to honour the archetype/emphasis so
> the reel's *look* matches the still. (2) Add **data-driven scene structure**: a
> multi-PB weekend produces a structurally different reel (variable
> `durationInFrames`/scene count derived from the number of ranked moments) than a
> single medal — the thing template tools can't do and Remotion can. (3) **Optional,
> behind its own flag** (`MEDIAHUB_GEN_BG`, default off): activate the dormant
> `visual/ai_background.py` hook (already imported at `render.py`) via a
> commercial-safe API (Bria/Recraft) for **backgrounds only**, composited under the
> deterministic text, with the existing contrast guardrails — never the data layer.
> Keep cache-by-content-hash behaviour. Add tests for variable scene count. Branch
> `claude/gen-seq-4-video`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-4: reel scene count varies with the number of ranked
> moments; the reel look matches the still archetype; cache-by-hash still works;
> the optional generative-background path is OFF by default and, when on, only
> affects the background (data text stays deterministic and legible). Suite green.

---

### 4. Dependency graph & sequencing

```
RUN NOW, CONCURRENTLY (each its own session → PR to main, any merge order):
  PAR-1 captions      PAR-2 autofit     PAR-3 saliency    PAR-4 design-spec
  PAR-5 metrics       PAR-6 bootstrap   PAR-7 archetypes×N PAR-8 docs
        (all additive/inert or single-surface — no shared-file conflicts)
                              │
                              ▼
THEN, IN ORDER (each its own PR; gated by MEDIAHUB_GEN_V2):
  SEQ-0 tokens ─▶ SEQ-1 Tier A ─▶ SEQ-2 Tier B ─▶ SEQ-3 cutover+removal ─▶ SEQ-4 video
  (SEQ-0 also coordinates with ROADMAP §1.6 Stage G if not yet merged)
```

**Wiring map (which spine stage consumes which parallel module):**

| Parallel module | Wired in by | Until then it is |
|---|---|---|
| PAR-2 autofit, PAR-3 saliency, PAR-7 archetypes | SEQ-1 | inert new files |
| PAR-4 design-spec, PAR-5 metrics | SEQ-2 | inert new files |
| PAR-6 brand bootstrap | SEQ-0 onboarding (or later) | inert new file |
| PAR-1 captions | already live (own surface) | shipped independently |
| PAR-8 docs | n/a | docs |

**The fastest path to fixing "samey":** PAR-2 + PAR-3 + PAR-7 (in parallel now) →
SEQ-0 → SEQ-1. That delivers Tier A — deterministic, brand-safe, ~$0 marginal cost
— which the thesis expects to resolve the complaint on its own, before any
LLM-director work (SEQ-2).

---

### 5. Acceptance criteria (from thesis §8C)

The overhaul is "done" when, with `MEDIAHUB_GEN_V2` on:

1. **Structural distinctiveness:** a 10-card pack uses ≥6 distinct archetypes; a
   5-candidate pool for one card spans ≥4 archetypes (today ~1–2). Measured by
   `quality/variant_metrics.py` (PAR-5).
2. **On-brand fidelity:** the deterministic compliance check passes ≥99% of shipped
   candidates; off-brand candidates are caught before a human sees them.
3. **Caption non-repetition:** consecutive captions for a card are below the overlap
   threshold; zero ban-list phrases ship.
4. **Human-acceptance rate** (approved without manual redesign) rises vs the old
   engine in the review-UI A/B.
5. **Cost & latency:** marginal API cost/pack < ~$0.50 (Tier A+B); cold render
   within today's 30–90s; cache-hit behaviour preserved.
6. **No moat regression:** rendered data accuracy stays 100% (deterministic), and
   every card keeps its "why this card / why this design" explanation.
7. **Suite green** throughout (no new failures, no weakened tests), and SEQ-3's
   gated-removal checklists are completed and recorded.

---

*Derived from `docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md`, against `main` after
PR #137. Run the Parallel Bucket (§2) now in separate sessions; then walk the
Sequential Spine (§3) in order.*



---

## Appendix B — Growth & Expansion: Build Prompts (legacy sequence — prompts retained)

> *Runnable implementation + verification prompts for the Phase 2/3 growth work (commercial, sport expansion, athlete surfaces, integrations, enterprise, agentic editing, marketplace, sponsor-side). The earlier steps (brand DNA, voice imitation, visible intelligence, output expansion, turn-into, publishing) are already shipped and are intentionally omitted. Step/Phase numbers below are local to this appendix.*

#### Step 7: Commercial Layer — Stripe, Tiers, Self-Serve Signup

##### Context
MediaHub has no commercial layer today. The plan is to ship public pricing, self-serve signup, and a free tier alongside Phase 1's product improvements so commercial pressure surfaces during iteration.

> ⚠️ **Promoted & repriced (2026-06 reconcile).** This step is no longer "alongside
> Phase 1" — it is the front-of-queue **Phase C** (signup → **PC.1**, Stripe → **PC.2**,
> tiers/pricing → **PC.4**). The scaling diligence
> ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)) makes
> it the **top priority**, ahead of expansion. **The `Free / Club £30/mo / Federation
> £250/mo` figures in the prompt below are ⚠️ unvalidated and too low** — candidate
> repricing: **Club £49–£99/mo billed annually, Federation £250+/mo**, with **annual
> prepay** (SMB/volunteer churn is 3–7%/mo; annual billing cuts it ~30–40%). Treat the
> code-block prompt below as legacy execution detail; Phase C and
> [`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md)
> are the current source of truth.

##### Implementation Prompt

```
Add a commercial layer: signup, Stripe billing, three tiers.

GOAL: a new user can land on /, click "Get started", create an account
with email + password, choose a plan (Free / Club £30/mo / Federation
£250/mo), pay via Stripe Checkout, and start using MediaHub on the
hosted service.

FILES TO MODIFY:
- NEW src/mediahub/web/auth.py: minimal email+password auth (use
  passlib bcrypt; sessions via Flask's session cookie with a
  signed secret).
- NEW src/mediahub/web/billing.py: Stripe Checkout session creation,
  webhook handler for subscription events.
- src/mediahub/web/web.py:
  - new GET/POST /signup, /login, /logout
  - new GET /pricing (3-tier table)
  - new GET /billing (current plan, manage subscription via Stripe
    Customer Portal)
  - new POST /webhooks/stripe (verify signature, update subscription
    status)
  - guard premium features (multi-club, enterprise tools — to be
    added in Phase 3) behind a plan check; existing features remain
    open on Free.
- DB: extend the existing DATA_DIR storage with a users.jsonl ledger
  (email, hashed_password, plan, stripe_customer_id, created_at).
  Do not introduce SQLAlchemy.
- environment: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION.
- Free tier limits: 3 runs/month, single brand profile, no Buffer
  scheduling. Soft limit (a banner) — never lock the user out
  permanently on free.

ACCEPTANCE CRITERIA:
- /signup creates a user, hashes the password, logs them in.
- /pricing shows the three tiers with feature lists.
- "Upgrade" buttons start a Stripe Checkout flow (use Stripe test
  mode keys for dev).
- A successful Stripe Checkout webhook updates the user's plan.
- /billing lets the user manage their subscription via Stripe Customer
  Portal.
- Self-hosted deployments (no STRIPE_SECRET_KEY env) continue to
  work — auth is optional, billing routes return 503 with a clear
  "billing is not configured for this deployment" message.

DON'T BREAK:
- Any existing route that was open is still open if no STRIPE_*
  env vars are configured.
- pytest at 253+.
- The Stop hook git push flow continues to work.

TESTS:
- tests/test_auth.py: signup, login, logout, password hashing.
- tests/test_billing.py (mocked Stripe): webhook verification,
  subscription update flow.

```

##### Verification Prompt

```
Verify Step 7 (Commercial layer) end-to-end.

1. Tests: full pytest + tests/test_auth.py + tests/test_billing.py -v.

2. Self-hosted-without-billing path:
   - With STRIPE_SECRET_KEY unset, boot the app.
   - GET /, /add-input, /upload, /organisation, /settings — all 200.
   - GET /pricing and /billing — 200 (show "billing not configured").
   - All caption / motion / Turn-Into routes work as before.

3. Signup / login flow:
   - POST /signup with a fresh email + 12-char password. Confirm
     redirect to /add-input + a session cookie.
   - Log out. Log back in. Confirm session restored.
   - Submit a wrong password. Confirm a clear error, not a 500.
   - Confirm passwords in users.jsonl are bcrypt hashes (not plain).

4. Stripe-mode (test keys):
   - Set STRIPE_SECRET_KEY, STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION
     to Stripe test values.
   - Hit /pricing. Click "Upgrade to Club".
   - Confirm a Stripe Checkout session URL is returned and the test
     mode page renders (open in browser, fill 4242 4242 4242 4242).
   - Complete checkout. Confirm the webhook handler updates the
     user's plan in users.jsonl to "club".

5. Free tier soft limit:
   - On a Free account, create 3 runs. Create a 4th. Confirm a banner
     appears (NOT a hard lock).

6. Buffer scheduling guarded:
   - On Free, the Schedule button must show "Upgrade to schedule
     posts" instead of opening the modal.

7. Security checks:
   - Try to access /billing without a session. Confirm redirect to
     /login.
   - Inspect the session cookie — must be HttpOnly + Secure (when
     served via HTTPS) and signed.
   - Grep the codebase for STRIPE_SECRET_KEY — must only appear in
     billing.py and never logged.

8. Regression sweep: all features from Steps 1-6 still work.

OUTPUT: single report.
```

---

### Phase 2 — Distinction (Steps 8-12, target months 3-9)

#### Step 8: Sport Expansion — Athletics (Track and Field)

##### Context
MediaHub today is swimming-only. Athletics is the natural second sport — overlapping audience (school athletic programmes, multi-sport clubs), similar result-file structure (event, time/distance, place), but a different event vocabulary and a different PB taxonomy.

##### Implementation Prompt

```
Add athletics (track and field) as MediaHub's second sport.

GOAL: a user can upload an athletics result file (CSV or Hytek-format
.txt) on /upload, MediaHub recognises athletes, computes PBs, ranks
achievements, and produces a content pack with athletics-appropriate
language.

FILES TO MODIFY:
- NEW src/mediahub/sports/: refactor the sport-specific bits of the
  existing pipeline out of swimming-implicit code paths. Each sport
  should have:
    sports/<sport>/events.py — canonical event vocabulary
    sports/<sport>/parser.py — result-file parsers
    sports/<sport>/pb_logic.py — PB and record detection
    sports/<sport>/templates.py — celebratory phrase patterns
- src/mediahub/sports/__init__.py: register a SPORTS dict and a
  pick_sport(file_bytes, hint) -> SportModule selector.
- src/mediahub/sports/swimming/: move existing swimming code here
  (preserve all behaviour and tests).
- src/mediahub/sports/athletics/: new athletics implementation.
  Event vocabulary: 100m, 200m, 400m, 800m, 1500m, 3000m, 5000m,
  10000m, hurdles (60m/100m/110m/400m), steeplechase, all field
  events (LJ, TJ, HJ, PV, SP, DT, HT, JT), relays. Distinguish
  TRACK (time-based) from FIELD (distance/height-based) for PB
  comparison logic.
- src/mediahub/web/web.py /upload: detect sport from filename and
  content; allow user to override via a sport dropdown.
- ClubProfile: add primary_sport field; default to "swimming" for
  backward compatibility.

ACCEPTANCE CRITERIA:
- Uploading an athletics result file produces an athletics-specific
  content pack with phrases like "smashed a PB" appropriate to track
  ("ran a personal best") and field ("threw a personal best").
- A field PB is correctly detected (higher = better) vs track PB
  (lower = better).
- All swimming tests still pass — no regression.
- Adding a third sport in future is a matter of creating a new
  sports/<sport>/ subpackage, no refactoring of the platform code.

DON'T BREAK:
- Every existing swimming test (interpreter, recognition, corpus,
  visual, caption) still passes.
- pytest at 253+ (new athletics tests added).
- All Phase 1 features (Brand DNA, voice, visible intelligence,
  Turn-Into, motion, Buffer publishing) work for athletics output.

TESTS:
- tests/test_athletics_parser.py: parse a sample athletics CSV,
  verify event detection.
- tests/test_athletics_pb_logic.py: field PB (higher = better) and
  track PB (lower = better) are correctly classified.
- tests/test_sports_registry.py: pick_sport routes correctly.

```

##### Verification Prompt

```
Verify Step 8 (Athletics support) end-to-end with no swimming regression.

1. Tests:
   - python -m pytest tests/ -q. Must be 253+ plus the new athletics
     tests (target 260+).
   - python -m pytest tests/test_athletics_*.py
     tests/test_sports_registry.py -v.

2. Swimming regression:
   - Upload an existing swimming sample file. Confirm the content pack
     is identical in structure to pre-Step-8 behaviour.
   - All four caption tones generate; visible intelligence shows PB
     reasoning; Turn-Into produces 6-7 artefacts; motion renders.
   - tests/test_interpreter_smoke.py, tests/test_pb_discovery.py,
     tests/test_corpus_recovery.py — all pass.

3. Athletics happy path:
   - Upload a sample athletics CSV. Confirm sport detection routes
     to athletics.
   - Confirm event names include 100m, 800m, LJ, TJ, etc.
   - Confirm PB logic: a long jump of 6.45m beats a previous 6.30m
     (higher = better); a 100m time of 11.40 beats 11.50 (lower = better).
   - Confirm captions use athletics-appropriate language ("ran a
     PB in the 800m" not "swam a PB").

4. Sport switching:
   - Manually override sport from swimming → athletics on the /upload
     page. Confirm the override takes effect.

5. Module structure:
   - ls src/mediahub/sports/ — confirms swimming/ and athletics/
     subpackages.
   - python -c "from mediahub.sports import SPORTS, pick_sport;
     print(list(SPORTS.keys()))"
     — confirms both sports registered.

6. Regression sweep on Phase 1:
   - All 7 Phase 1 steps' features still work (sample one feature
     from each).

OUTPUT: single report.
```

---

#### Step 9: Athlete-Facing Micro-Surfaces

##### Context
Greenfly routes content from a league to athletes for personal sharing. For MediaHub the parallel is letting a swimmer/athlete receive their own personal share-ready cards via a private link, which they post to their own channels. This expands distribution beyond the club account.

##### Implementation Prompt

```
Add athlete-facing micro-surfaces for personal sharing.

GOAL: each swimmer/athlete in a run can be given a personal,
unlisted link to a page that shows their cards for that meet plus
their season-to-date highlights, with a "Share to Instagram" / "Save
to camera roll" affordance per card. No login required for the
swimmer.

FILES TO MODIFY:
- src/mediahub/athlete_pages/: new module.
- Token: per-athlete unlisted token = HMAC(server_secret, run_id +
  athlete_id), 24 chars base32. Stored in run JSON.
- src/mediahub/web/web.py:
  - new GET /a/<token> — renders the athlete page. No auth required.
  - new GET /a/<token>/card/<card_id>/share — returns the card as a
    direct-download image for the athlete to save and post.
  - new POST /api/runs/<run_id>/athlete-tokens — admin route on the
    review page: generate or revoke tokens for athletes in the run.
- Review page: "Send to athlete" button on each card; clicking copies
  the personal share link (or opens a QR code modal for in-person
  hand-off).
- Privacy: the athlete page MUST NOT show any other swimmer's data,
  the original results file, or any club admin surface.

ACCEPTANCE CRITERIA:
- An athlete with a token can see only their own cards.
- The link is unguessable (HMAC + secret rotation).
- An admin can revoke a token; revoked tokens render a "this link has
  been revoked" page.
- Share affordances work on mobile: tapping "Save to camera roll" on
  iOS Safari triggers a long-press save flow; on Android, a direct
  download.
- Page renders correctly on screens 320px wide (smallest common mobile).

DON'T BREAK:
- All earlier features still work.
- Privacy: no PII leakage from athlete page to the rest of the
  system. Specifically: an athlete cannot enumerate other tokens.

TESTS:
- tests/test_athlete_pages.py: token generation determinism, HMAC
  verification, revoked-token handling, isolation between athletes.

```

##### Verification Prompt

```
Verify Step 9 (Athlete pages) end-to-end.

1. Tests: full pytest + tests/test_athlete_pages.py -v.

2. Happy path:
   - On an existing run, generate a token for athlete A and athlete B.
   - GET /a/<token_A> — confirm 200, shows only A's cards.
   - GET /a/<token_B> — confirm 200, shows only B's cards.
   - Try GET /a/<token_A> with one character changed — confirm 404,
     NOT a leak of the original page.

3. Isolation:
   - On A's page, the response body must NOT contain B's swimmer_name.
   - The page must NOT contain the path to the results file.

4. Revocation:
   - Revoke A's token. Re-fetch /a/<token_A> — confirm a clear
     "revoked" page, status 410 or 200 with a message.

5. Mobile rendering:
   - Open /a/<token_A> in a 360x800 viewport. Screenshot.
   - Confirm cards fit, text is readable, the share buttons are
     thumb-sized (≥44px).

6. Share affordance:
   - GET /a/<token>/card/<card_id>/share — must return an image with
     Content-Disposition: attachment.

7. Regression sweep: all Phase 1 + Step 8 features still work.

OUTPUT: single report.
```

---

#### Step 10: Sponsor-Aware Generation

##### Context
Sponsors are a primary revenue driver for clubs and the buyer's biggest stakeholder. A sponsor-aware product variant of every output type — caption with sponsor mention, graphic with sponsor logo, newsletter section with sponsor block — turns MediaHub into a sponsorship-value-realisation tool.

##### Implementation Prompt

```
Make every output type sponsor-aware.

GOAL: when ClubProfile has sponsor_name + sponsor_guidelines set,
every generated caption, graphic, motion, reel, and Turn-Into
artefact has an opt-in sponsor variant. The sponsor variant must
respect the guidelines (e.g. "always include #BrandNameSwim";
"never combine our logo with a competitor's").

FILES TO MODIFY:
- ClubProfile: extend with sponsor_logo_path,
  sponsor_brand_colour (hex), sponsor_required_hashtags (list),
  sponsor_forbidden_phrases (list), sponsor_activation_rate
  (e.g. "every 3rd post"), sponsor_position_preference
  (top|bottom|watermark).
- src/mediahub/sponsor/: new module:
    apply_sponsor_to_caption(caption: str, profile: ClubProfile,
                              activation: bool) -> str
    apply_sponsor_to_graphic(graphic_brief: dict,
                              profile: ClubProfile) -> dict
- Generators (caption, graphic, motion, Turn-Into) call the sponsor
  apply functions when activation=True. Activation is determined by
  the sponsor_activation_rate or explicit user toggle per card.
- review page: a "Sponsor mode" toggle on each card; the entire
  content pack also has a global toggle.
- Compliance: a "Sponsor compliance check" panel lists each generated
  artefact and confirms it satisfies all guidelines or flags
  violations.

ACCEPTANCE CRITERIA:
- With sponsor configured, the sponsor toggle on a card produces a
  sponsor variant that:
  - Includes any required hashtags.
  - Avoids any forbidden phrases.
  - Displays the sponsor logo in the configured position.
  - Uses the sponsor brand colour as a tasteful accent (without
    overriding the club's primary palette).
- The compliance panel surfaces any violation clearly.
- Without a sponsor configured, the toggle is hidden, not greyed out.

DON'T BREAK:
- All earlier features still work.
- pytest at 260+ (athletics tests added in Step 8).

TESTS:
- tests/test_sponsor_pipeline.py: required-hashtag enforcement,
  forbidden-phrase blocking, logo positioning.

output expansion).
```

##### Verification Prompt

```
Verify Step 10 (Sponsor mode) end-to-end.

1. Tests: full pytest + tests/test_sponsor_pipeline.py -v.

2. Configuration round-trip:
   - Set sponsor_name + sponsor_required_hashtags ["#TestSponsor"]
     + sponsor_forbidden_phrases ["beat the competition"].
   - Save, reload /organisation. Confirm the fields persist.

3. Sponsor caption check:
   - Toggle "Sponsor mode" on one card.
   - Confirm the caption now contains "#TestSponsor".
   - Force the LLM (or heuristic) to produce text containing "beat the
     competition" via a test fixture, run the apply function, and
     confirm the phrase is removed or rewritten.

4. Sponsor graphic check:
   - Toggle sponsor mode, regenerate the graphic.
   - Open the image; confirm the sponsor logo appears in the
     configured position.
   - Confirm the sponsor colour appears as an accent (not as
     the primary background).

5. Compliance panel:
   - Configure a deliberate violation (a required hashtag NOT present
     in the caption). Confirm the compliance panel flags it visibly.

6. Sponsor absent:
   - Clear sponsor_name. Confirm the sponsor toggle is hidden, not
     present in the DOM.

7. Regression sweep: all Phase 1 and Steps 8-9 features still work.

OUTPUT: single report.
```

---

#### Step 11: Multi-Sport Architecture Cleanup + Football/Rugby

##### Context
With athletics shipped in Step 8 the sports/ package exists. Adding football and rugby validates that the architecture genuinely scales and unlocks the largest UK market segment (school and university football/rugby).

##### Implementation Prompt

```
Add football and rugby as sports 3 and 4; clean up the sports/
architecture as needed.

GOAL: a user can upload a football match report (CSV / structured
text / one-pager PDF) and get a content pack appropriate to football
(goal scorers, clean sheets, man-of-the-match, league position,
fixture preview). Same for rugby (tries, conversions, line-out
stats, set-piece dominance, man-of-the-match).

FILES TO MODIFY:
- src/mediahub/sports/football/: events.py (match events: goals,
  assists, yellow/red cards, subs), parser.py (parse common
  match-report formats including OPTA-style CSV if available),
  achievement_logic.py (goal-of-the-match, hat-trick detection,
  clean-sheet recognition), templates.py.
- src/mediahub/sports/rugby/: similar structure for rugby union
  (tries, conversions, penalties, man-of-the-match, line-out wins).
- Generalise the existing pb_logic.py — for team sports it's
  achievement_logic.py with different primitives. Refactor the
  swimming/athletics modules to use a common interface
  (sports/<sport>/achievement_logic.py) where appropriate.
- /upload: detect sport from file content + filename.
- /organisation: add a "Sports" multi-select so a club can declare
  it covers multiple sports.

ACCEPTANCE CRITERIA:
- A hat-trick is correctly detected and surfaced as the headline
  achievement in football.
- A clean sheet is correctly attributed to the goalkeeper.
- Rugby man-of-the-match selection prefers tries > conversions >
  metres made if not explicitly named in the input.
- A clean league position (1st in the table) is detected as a
  high-priority achievement.
- All previous sports tests (swimming + athletics) still pass.

DON'T BREAK:
- pytest at the new baseline (target 280+).
- Phase 1 features remain functional on football/rugby output.

TESTS:
- tests/test_football_*.py and tests/test_rugby_*.py covering parsing,
  achievement detection, and caption generation.

```

##### Verification Prompt

```
Verify Step 11 (Football + Rugby) end-to-end.

1. Tests: full pytest. Target 280+ passed.
   - python -m pytest tests/test_football_*.py tests/test_rugby_*.py -v.

2. Hat-trick detection:
   - Upload a football match where player X scored 3 goals.
   - Confirm the top-ranked card mentions a hat-trick.
   - Confirm the visible-intelligence reasoning includes goal count.

3. Clean sheet attribution:
   - Upload a 2-0 win match. Confirm the goalkeeper's card mentions
     "clean sheet".

4. Rugby try detection:
   - Upload a rugby match with 4 tries by player Y. Confirm Y is the
     headline and the caption uses rugby-appropriate language.

5. Multi-sport club:
   - Set a club's sports to ["swimming","football"]. Upload swimming.
     Confirm swimming pipeline. Upload football. Confirm football
     pipeline.

6. Cross-sport caption consistency:
   - Same voice_profile applied to a football caption and a swimming
     caption — the stylistic signature (sentence length, hashtag
     count) should match across both.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 12: Native Publishing APIs (Replace Buffer Dependency)

##### Context
Step 6 shipped Buffer integration to close the publishing gap fast. This step builds direct integrations to Instagram Graph API, Facebook Pages, X (v2), LinkedIn Marketing, and TikTok Business so MediaHub no longer depends on Buffer for the core publishing path.

##### Implementation Prompt

```
Replace Buffer dependency with native publishing APIs.

GOAL: a user can connect Instagram Business, Facebook Pages, X,
LinkedIn (Company Page), and TikTok Business directly. Scheduling
no longer requires a Buffer account.

FILES TO MODIFY:
- src/mediahub/publishing/instagram.py: Graph API; OAuth via
  Facebook Login. Single-image + reels upload + caption.
- src/mediahub/publishing/facebook.py: Pages API; OAuth via
  Facebook Login.
- src/mediahub/publishing/x_twitter.py: v2 API; OAuth 2.0 with PKCE.
- src/mediahub/publishing/linkedin.py: Marketing Developer Platform;
  OAuth 2.0.
- src/mediahub/publishing/tiktok.py: TikTok Business API; OAuth 2.0.
- src/mediahub/publishing/scheduler.py: a unified Scheduler interface
  (queue, schedule_at, dispatch_now) so the UI calls one API
  regardless of platform.
- A background worker (lightweight — Flask-APScheduler or a simple
  cron-style polling thread) that dispatches scheduled posts at
  their scheduled_at time.
- /settings: native "Connect Instagram", "Connect Facebook" etc.
  buttons (in addition to the existing Buffer field, which remains
  as a fallback).

ACCEPTANCE CRITERIA:
- A user can complete the OAuth flow for each platform and the
  resulting access tokens are stored encrypted (Fernet) in
  DATA_DIR / "secrets" / <user_id>.json.
- Scheduling a post via the UI dispatches to the right platform at
  the right time.
- Token refresh is handled before each dispatch.
- Buffer remains available as a fallback channel; users can choose
  per-card whether to dispatch direct or via Buffer.

DON'T BREAK:
- pytest at the new baseline (target 290+ with publishing tests).
- All earlier features still work.

TESTS:
- tests/test_native_publishing.py: mocked OAuth + dispatch, token
  refresh, dispatcher worker.

landscape closing), §6 Workstream 3.x.
```

##### Verification Prompt

```
Verify Step 12 (Native publishing) end-to-end.

1. Tests: full pytest + tests/test_native_publishing.py -v.

2. OAuth flows (mocked):
   - For each of the 5 platforms, simulate the OAuth callback with a
     fixed test token. Confirm the token is stored encrypted (not
     plaintext) in the per-user secrets file.

3. Dispatch (mocked):
   - Schedule a post with scheduled_at = now + 30s.
   - Wait 45s. Confirm the post was dispatched via the mocked API.
   - Confirm the workflow state shows schedule_status=published.

4. Token refresh:
   - Set an expired-token scenario. Confirm the dispatcher refreshes
     the token before dispatching, or surfaces a clear "re-connect"
     error if refresh fails.

5. Buffer fallback:
   - Confirm Buffer is still selectable per-card and the Buffer
     dispatch path still works.

6. Security:
   - grep the codebase for any access_token logging — must be zero.
   - Confirm the encrypted secrets file mode is 0600.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Phase 3 — Leadership (Steps 13-17, target months 9-18)

#### Step 13: Integration Moat — Hy-Tek, TeamUnify, ClubBuzz Importers

##### Context
The single most defensible distribution moat against horizontal entrants is direct integration with the software clubs already use. Hy-Tek MeetManager (results), TeamUnify (club management), ClubBuzz (UK clubs), SwimManager — each integration is one to three engineering weeks and creates a switching cost.

##### Implementation Prompt

```
Build first-class importers for the most-used club software.

GOAL: a user with a TeamUnify or ClubBuzz account can connect MediaHub
once, and every new meet result automatically flows into MediaHub
without a manual upload.

FILES TO MODIFY:
- src/mediahub/integrations/teamunify.py: OAuth or API key auth,
  poll for new meet results, ingest as a new run, run the full
  pipeline.
- src/mediahub/integrations/clubbuzz.py: same pattern.
- src/mediahub/integrations/hytek_meetmanager.py: file-format
  importer for the .hy3 format with deeper coverage than the existing
  parser (handle all common event codes, age groups, time conversions).
- src/mediahub/integrations/splash_meet_manager.py: file-format
  importer for Splash's export format.
- /settings: new "Integrations" section with one-click connect
  buttons.
- A background polling worker for the API-based integrations.

ACCEPTANCE CRITERIA:
- A connected TeamUnify account auto-ingests new meets within 1 hour
  of them appearing in TeamUnify.
- Hytek and Splash file imports produce identical content packs to
  manual uploads.
- A revoked integration cleanly stops polling and surfaces in the UI.

DON'T BREAK:
- Manual file upload still works.
- pytest at the new baseline (target 300+).

TESTS:
- tests/test_integrations_*.py: mocked API responses, end-to-end
  ingestion.

```

##### Verification Prompt

```
Verify Step 13 (Integrations) end-to-end.

1. Tests: full pytest + tests/test_integrations_*.py -v.

2. TeamUnify mocked happy path:
   - Connect with a test API key.
   - Push a fake new-meet event via the mock server.
   - Confirm a new run appears in MediaHub within the polling interval.
   - Confirm the run produces a valid content pack.

3. Hytek parity:
   - Take an existing .hy3 file that worked with the manual uploader.
   - Run it through the new importer. Confirm the resulting content
     pack is identical (same number of achievements, same ranking).

4. Splash importer:
   - Process a sample Splash file. Confirm event detection + PB
     attribution.

5. Disconnection:
   - Revoke the test API key. Confirm polling stops within 1 polling
     cycle and the /settings page shows "Disconnected".

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 14: Enterprise Tier — Multi-Club Orchestration

##### Context
The financial backbone of the strategy. Governing bodies, leagues, federations, and large university athletic departments need multi-club orchestration: branded league templates, federation-wide engagement analytics, sponsorship reporting across clubs.

> ⚠️ **Partly promoted (2026-06 reconcile).** The **Organisation → Club → Run hierarchy /
> multi-tenancy** half of this step is no longer a far-future "leadership" item — it is
> pulled forward to **Phase C · PC.3** as a **blocking prerequisite**, because
> single-instance-per-club can't scale (ops/support rise linearly vs. fixed founder
> hours). The *federation analytics / template-push / sponsorship-report* surfaces remain
> later-stage. See
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md) and
> [`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md).

##### Implementation Prompt

```
Ship the enterprise tier: multi-club orchestration.

GOAL: a Federation user (Stripe enterprise plan from Step 7) can
manage up to 50 clubs from one account, push league-branded templates
to all clubs, view aggregated engagement analytics, and produce
sponsorship reports.

FILES TO MODIFY:
- Data model: introduce Organisation (governing body / league) →
  Club → Run hierarchy. Backward-compatible: a club without an
  organisation is treated as a standalone (today's default).
- src/mediahub/enterprise/: new module:
    OrganisationProfile dataclass
    league_templates.py — manage and distribute templates
    aggregated_analytics.py — engagement metrics across child clubs
    sponsorship_report.py — sponsor-exposure metrics with citations
- new pages:
  /federation — dashboard
  /federation/clubs — manage child clubs
  /federation/templates — push templates
  /federation/analytics — aggregated metrics
  /federation/sponsorship — sponsor reports
- billing: Stripe plan "federation" unlocks these pages.

ACCEPTANCE CRITERIA:
- A federation user can add a child club and the child club's owner
  receives an invite link to accept the relationship.
- Pushing a template to all child clubs makes the template available
  in each club's Turn-Into picker.
- Aggregated analytics correctly sum engagement across all child
  clubs and never double-count.
- A sponsorship report can be exported as a branded PDF.

DON'T BREAK:
- Standalone clubs (no parent organisation) work exactly as before.
- pytest at the new baseline (target 310+).

TESTS:
- tests/test_enterprise_*.py covering hierarchy, template push,
  analytics aggregation, sponsorship report generation.

scale).
```

##### Verification Prompt

```
Verify Step 14 (Enterprise tier) end-to-end.

1. Tests: full pytest + tests/test_enterprise_*.py -v.

2. Hierarchy:
   - Create a federation account and three child clubs.
   - Confirm the federation dashboard shows all three.
   - Sign in as one child club — confirm it can see only its own runs.

3. Template push:
   - Federation pushes a "Meet Recap League Template".
   - Each child club's Turn-Into picker now includes it.

4. Analytics:
   - Federation analytics page sums engagement across the three clubs.
   - Manually verify the sum equals the per-club totals.

5. Sponsorship report:
   - Generate a sponsorship PDF for the federation's headline sponsor.
   - Confirm the PDF includes per-club sponsor activations with
     citations (which post, which date, which platform).

6. Plan guard:
   - On a non-federation plan, the federation pages return a clear
     upgrade prompt, not a 404.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 15: Conversational / Agentic Caption Editing

##### Context
Lately's Kately and Holo's chat-editor demonstrate the next interaction primitive: a conversational layer over the existing content pack. "Make this caption more energetic", "Add a thank-you to the parents", "Generate a TikTok script from this meet" — the user issues natural-language instructions and the agent operates over the existing assets.

##### Implementation Prompt

```
Add a conversational editing surface to the content pack.

GOAL: every card on the review page has a chat panel where the user
can issue natural-language edit commands ("shorter", "more energetic",
"in Spanish", "add a sponsor mention", "generate a TikTok variant").
The agent uses the existing tools (generate_caption_for_tone,
sponsor.apply, motion.render_story_card) rather than free-form
generation.

FILES TO MODIFY:
- src/mediahub/agent/__init__.py
- src/mediahub/agent/tools.py: register the tools the agent can call
  (regenerate_caption, change_tone, translate_caption, add_sponsor,
  generate_motion, generate_reel_variant).
- src/mediahub/agent/runner.py: a small tool-use loop using the
  existing LLM (Gemini or Anthropic) with structured tool calling.
- /review page: a chat panel toggle next to each card.
- Every agent action writes an audit entry (who, when, what tool,
  what arguments, what result) to DATA_DIR/agent_audit/<run_id>.jsonl.

ACCEPTANCE CRITERIA:
- "Make this shorter" produces a caption ≤80% of the original length.
- "Make this in Spanish" produces Spanish output.
- "Add a sponsor mention" calls the sponsor.apply tool and produces
  a sponsor variant.
- The agent NEVER publishes — every change is staged and requires
  the user's Save click.

DON'T BREAK:
- pytest at the new baseline (target 320+).
- All earlier features still work.

TESTS:
- tests/test_agent_*.py: tool invocation, no-publish guarantee,
  audit log integrity.

§6 Workstream 3.3.
```

##### Verification Prompt

```
Verify Step 15 (Agentic editing) end-to-end.

1. Tests: full pytest + tests/test_agent_*.py -v.

2. Edit commands:
   - "shorter" → length reduction confirmed.
   - "more energetic" → tone shift confirmed (compare against baseline).
   - "in Spanish" → output is Spanish (langdetect).
   - "add a sponsor mention" → sponsor hashtag present.

3. No-publish guarantee:
   - Issue 10 agent commands. Confirm NONE of them dispatched a
     publish action. The audit log should show zero publishing tool
     calls.

4. Audit:
   - For each agent action, confirm DATA_DIR/agent_audit/<run_id>.jsonl
     has a corresponding entry with full arguments and result.

5. Tool safety:
   - Try to inject "delete this run" via the chat input. Confirm the
     agent does not call any destructive tool (no such tool exists in
     the registry).

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 16: Template Marketplace

##### Context
Community templates raise switching cost. Once a club has invested in templates that exist only on MediaHub — branded recap layouts, voice profiles, season-narrative arcs — leaving the platform costs them their accumulated content infrastructure.

##### Implementation Prompt

```
Ship a community template marketplace.

GOAL: clubs and federations can publish templates (visual layouts,
voice profiles, Turn-Into recipes, sponsor activation patterns) for
other clubs to fork. Templates are versioned and reviewable.

FILES TO MODIFY:
- src/mediahub/marketplace/: new module.
- Template types: visual_layout (graphic + motion templates),
  voice_profile_template (anonymised voice patterns),
  turn_into_recipe (which 7 artefacts a Turn-Into produces and how),
  sponsor_activation (predefined sponsor variants for common partners).
- /marketplace page: browse, preview, fork.
- /marketplace/submit: submit a template (with review queue).
- /marketplace/admin: review/approve/reject submissions (federation
  + MediaHub admin role).

ACCEPTANCE CRITERIA:
- A submitted template enters a review queue.
- Forking a template clones it into the user's own club profile —
  edits to the fork do not affect the source.
- Templates are versioned; the user can upgrade their fork to a newer
  source version.
- Marketplace search by sport, audience size, language.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_marketplace_*.py covering submission, fork, version
  upgrade, isolation between fork and source.

```

##### Verification Prompt

```
Verify Step 16 (Template marketplace) end-to-end.

1. Tests: full pytest + tests/test_marketplace_*.py -v.

2. Submit + approve:
   - As a club user, submit a visual_layout template.
   - As an admin, approve it.
   - The template now shows in /marketplace.

3. Fork:
   - As another club, fork the template. Confirm the fork lives in
     the new club's profile.
   - Edit the fork. Confirm the source is unchanged.

4. Version upgrade:
   - As the source owner, publish version 2.
   - The fork shows an "upgrade available" badge. Confirm the upgrade
     applies cleanly.

5. Search:
   - Search by sport=athletics. Confirm only athletics templates
     appear.

6. Privacy:
   - Confirm voice_profile_template templates are anonymised (no
     PII / no club name leaked) before they enter the public
     marketplace.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 17: Sponsor-Side Analytics Product

##### Context
The final defensible primitive: a sponsor-facing product that proves to the sponsor the value of their brand exposure across a club's content. Nota and FanWord do not do this at small-club scale; this is a category MediaHub can own.

##### Implementation Prompt

```
Build a sponsor-side product surface.

GOAL: a sponsor (the brand paying the club) can log in and see a
dashboard of all the times their brand appeared in content produced
by clubs they sponsor, with engagement metrics and an estimated
brand-exposure value.

FILES TO MODIFY:
- New user role: sponsor. Sponsor accounts are linked to specific
  club profiles via an invitation flow.
- src/mediahub/sponsor_dashboard/: new module.
- /sponsor — sponsor dashboard.
- /sponsor/exposure — list of every post where this sponsor's brand
  appeared, with date, platform, engagement, and a thumbnail of
  the asset.
- /sponsor/value — estimated brand-exposure value (impressions ×
  CPM-equivalent based on the platform).
- /sponsor/export — branded PDF report.

ACCEPTANCE CRITERIA:
- A sponsor can only see content produced by clubs they sponsor.
- Engagement metrics are pulled from the publishing layer's
  post-success records (Step 12).
- The brand-exposure value calculation is documented and auditable
  (open the value calculation in a tooltip).
- The PDF export is reproducible and includes citations to every
  source post.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_sponsor_dashboard_*.py: scoping (sponsor sees only their
  clubs), metric calculation determinism, PDF export shape.

```

##### Verification Prompt

```
Verify Step 17 (Sponsor-side product) end-to-end.

1. Tests: full pytest + tests/test_sponsor_dashboard_*.py -v.

2. Scoping:
   - Sponsor A is linked to Club 1 and Club 2 (not Club 3).
   - Sponsor A's exposure page shows posts from Club 1 and 2 only.
   - Confirm Club 3's posts do NOT appear in any sponsor query.

3. Metric calculation:
   - For a post with known engagement, manually compute the value
     using the documented formula. Confirm the dashboard matches.

4. PDF export:
   - Export a sponsor report. Confirm it opens, contains citations,
     and is reproducible (re-export, byte-equality of the content
     section).

5. Sponsor cannot leak admin:
   - As a sponsor, attempt to access /federation, /admin,
     /api/runs/<id>/turn-into. All must return 403.

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Final Audit — After Step 17 (or any time after Step 7)

##### Context
At any milestone the full product should be audited end-to-end. This audit is the prompt to run after a major release.

##### Audit Prompt

```
Conduct a full MediaHub product audit.

OBJECTIVE: confirm that every feature shipped to date — every step
in the roadmap that has been completed — still works end-to-end with
no regressions, and that the product as a whole holds up against the
quality bar set by the competitors documented in
docs/research/generation-engine-competitor-evaluation.md.

PHASE A — Automated tests:
1. python -m pytest tests/ -q. Report pass/skip/fail counts.
2. python -c "from mediahub.web.web import create_app; create_app()".
3. Boot the app: python -m mediahub.web.web (background).
4. Confirm 0 ERROR-level log lines on a clean boot.

PHASE B — Route sweep:
For each of these routes, confirm a 200 (or correct 30x/40x):
- GET /, /add-input, /upload, /organisation, /settings, /privacy
- GET /pricing, /signup, /login (if Step 7 shipped)
- GET /free-text, /weekend-preview, /sponsor-post, /session-update
- GET /spotlight (if implemented)
- GET /federation, /federation/clubs (if Step 14 shipped)
- GET /marketplace (if Step 16 shipped)
- GET /sponsor (if Step 17 shipped)

PHASE C — Critical user journeys, for each completed step:
- Brand DNA capture: paste a URL, confirm preview, save. Should work.
- Voice imitation: paste 5 examples, save, confirm voice_profile.
- Visible intelligence: open any run, confirm "Why this card?" works.
- Motion: render a story card; render a reel.
- Turn-Into: produce 6-7 artefacts from a meet.
- Buffer or native publishing: schedule a mocked post.
- Commercial: signup, login, upgrade (Stripe test mode).
- Athletics: upload athletics sample, confirm pipeline.
- Athlete page: generate a token, fetch /a/<token>.
- Sponsor mode: toggle on a card, confirm variant.
- Football/Rugby: upload sample, confirm hat-trick / clean sheet.
- Native publishing OAuth: complete one platform's mock flow.
- Integrations: TeamUnify mocked auto-ingest.
- Enterprise: multi-club orchestration.
- Agent: 5 edit commands all hit tools correctly.
- Marketplace: submit + approve + fork.
- Sponsor dashboard: scope correctness + PDF export.

PHASE D — Cross-cutting quality:
- Visual polish: open / and the review page in a browser; screenshot.
  Compare against tryholo.ai's homepage. List any obvious gaps.
- Performance: time a fresh upload-to-content-pack run end-to-end.
  Target < 90s for a 200-swim meet.
- Security: grep the codebase for hardcoded API keys, exposed
  secrets in logs, Path("data/...") relative paths. Report any.
- Test isolation: confirm tests do not write to the real
  data/secrets.json or club_profiles/*.json.
- Accessibility: run a quick a11y scan on the review page. Report
  contrast and keyboard-nav issues.

PHASE E — Strategic position:
For each of the competitors in `docs/research/generation-engine-competitor-evaluation.md`, evaluate where
MediaHub now stands on a 5-point Leading / Competitive / Adequate /
Underdeveloped / Absent scale across the 6 dimensions:
1. Input modality
2. Intelligence layer
3. Output surface
4. Brand context capture
5. Distribution
6. Commercial model

Cross-reference with the competitor analysis in `docs/research/`. Has MediaHub moved up
the matrix on the dimensions Phase 1 targeted? Are there new gaps
that have opened?

OUTPUT FORMAT:
Return a structured audit report:
- Phase A: automated tests results
- Phase B: route table with status codes
- Phase C: per-step pass/fail table
- Phase D: a quality scorecard (1-5) per cross-cutting area
- Phase E: an updated competitive matrix
- Top 5 regression risks (ordered by severity)
- Top 5 next-step recommendations
- A single "release readiness" verdict: Ship / Hold / Block.
```

---

#### Notes on running this roadmap

**Branching.** Every step is a feature branch off `dev`; never merge to `main` without approval. Use names like `step-01-brand-dna-capture`, `step-06-buffer-publishing`. The verification prompt is run before opening the merge request.

**Sequencing.** Steps 1-7 (Phase 1) should be done strictly in order — each builds on the previous. Steps 8-12 (Phase 2) can be partially parallelised once Step 8 (sports architecture) is in. Steps 13-17 (Phase 3) are highest value when done in the order shown but Step 14 (enterprise tier) is the highest financial priority; consider promoting it earlier if revenue is the limiting factor.

**Test budget.** Maintain ≥ 253 passed at every step. Each step adds 5-15 tests, so by Step 17 expect 350+ passing.

**When verification fails.** Paste the failing report back into the implementation session of the same step. Do not move forward until a clean verification report is produced.

**When you stop following the prompts.** Each step is designed to be readable on its own. If during implementation Claude needs context that the prompt didn't provide, the prompt is at fault — improve the prompt and re-run rather than letting Claude guess.

**Source of truth.** This roadmap and the analyses in `docs/research/` (the competitor evaluation + the generative-AI thesis) are the paired references.

---

## Appendix C — Adaptive Theming Engine (1.6): Verification Prompts

> *Stage IDs in this appendix (A–J) map 1:1 to the previous roadmap revision's §1.6 Stage table. §1.6 (the Adaptive Theming Engine) is **shipped** — all ten stages are in `main`, live by default, and green. Unlike Appendix A (which builds an as-yet-unbuilt engine), this appendix is **verification-only**: paste-into-a-session acceptance audits that independently confirm each shipped stage still meets its part of the §1.6 acceptance criteria. There are no implementation prompts here — the code already exists.*

**What this is.** A per-stage acceptance-audit harness for the now-shipped
Adaptive Theming Engine. Each stage below has a **Context** (what shipped +
the real files) and a **Verification prompt** (paste into a fresh session).
The prompts are read-only audits plus the test suite; none should need to
modify the engine. A final **full-engine acceptance audit** ties the
per-stage checks back to the five numbered acceptance criteria in §1.6.

**Date:** May 2026 · **Built against:** `main` with Stages A–J merged (the
`theming/` package, the five `static/theme/*.css` layers, `theme_store.py`,
and `docs/THEMING.md`).

**Why verify a shipped feature.** The engine touches every rendered page and
four output media (web, motion, email, static graphic). It is exactly the
kind of cross-cutting surface where a later refactor can silently regress
contrast, drift one medium's palette from the others, or break the cascade.
These prompts are the regression harness that proves it still holds.

---

### 1. The shared verification preamble (every prompt inherits this)

> **Preamble — read before doing anything.** You are auditing MediaHub's
> **shipped** Adaptive Theming Engine (ROADMAP §1.6) in the repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md`,
> `docs/THEMING.md`, and the file(s) named in the task. This is a
> **verification** task — read code, run tests, exercise routes, and report a
> pass/fail checklist. Hard rules:
> - **The colour-science engine is deterministic and off-limits to AI.**
>   `theming/` (palette, roles, contrast, cvd, quality, repair, seed_extract,
>   harmony, logo_chip) and the CIEDE2000 / APCA / Machado maths must stay
>   deterministic. If a check fails, **report it** — do **not** "fix" it by
>   routing a judgement through Gemini/Anthropic, and do not add a hand-tuned
>   per-seed override (the point of §1.6 is intelligence in the algorithm,
>   not a lookup table).
> - **No test cheating.** If you run the suite, do not delete, skip, or weaken
>   a test to make it pass. A red test is a finding, not an obstacle.
> - **Determinism is a property under test.** Same seed → byte-identical
>   palette, every time. If you find non-determinism, that is a failure.
> - **Read-only by default.** These prompts should not need to modify the
>   engine. If you find a genuine gap, report it with a minimal repro; only
>   fix it in a **separate, clearly-scoped** branch + PR with the user's
>   go-ahead — never fold an engine change into a verification pass.
> - **Run the tests named in the task plus the full suite**
>   (`python -m pytest tests/ -q`); confirm no new failures vs `main`.
> - **Report format:** a pass/fail checklist, one line per claim, citing the
>   `file:line` or test name that proves each.

---

### 2. Per-stage verification prompts

#### Stage A — Token foundation
**Shipped:** ~25 MD3-style role tokens (`--mh-surface`, `--mh-on-surface`,
`--mh-primary`, …) defined in `static/theme/theme-base.css` and surfaced via
`web/theme_tokens.py`; every animatable seed/colour registered with
`@property { syntax: "<color>"; inherits: true }`. Tests:
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage A (token foundation). Confirm: the ~25 documented
> role tokens all exist in `theme-base.css`; each animatable colour variable
> (the `--mh-*-seed` set and the role tokens that transition) is registered
> via `@property` with `syntax: "<color>"` (grep the `@property` blocks); no
> transitioned colour relies on an untyped custom property; and migrating to
> tokens introduced no visual change for the default brand (the token values
> resolve to the pre-token palette). Run `tests/test_theme_tokens.py` + the
> full suite. Report any token that is missing or unregistered.

#### Stage B — Colour-science library
**Shipped:** the `src/mediahub/theming/` package — `seed_extract.py`,
`palette.py`, `roles.py`, `contrast.py` (APCA Lc + WCAG2), `cvd.py` (Machado
2009), `quality.py` (`PaletteQualityReport`), `repair.py`, `harmony.py`
(Cohen-Or). Deps `materialyoucolor` + `coloraide` in `pyproject.toml` /
`requirements.txt`. Entry point `theming.derive_theme(seed)`. Tests:
`tests/theming/test_palette.py`, `test_contrast.py`, `test_cvd.py`,
`test_quality.py`, `test_repair.py`, `test_seed_extract.py`,
`test_harmony.py`.

**Verification prompt:**
> [Preamble.] Verify Stage B (colour-science package). Confirm: `derive_theme`
> is deterministic (call it twice on one seed → byte-identical `to_json()`);
> the pipeline is seed → HCT → 5×13 tonal palettes → MD3 roles → APCA/ΔE/CVD
> gates → bounded repair loop (`repair_max_iters` honoured, never infinite);
> `contrast.py` APCA Lc and `cvd.py` Machado matrices match their known
> fixtures; no module makes a network/LLM call (grep `theming/` for
> `requests`, `httpx`, `media_ai`, `ai_core` — none); and an empty/garbage
> seed returns the fallback theme rather than raising. Run all
> `tests/theming/test_*` + the full suite. State the determinism result
> explicitly.

#### Stage C — CSS architecture
**Shipped:** the inline `<style>` block is extracted into `static/theme/`
across `theme-base.css`, `theme-derive.css` (the `color-mix(in oklch, …)` +
relative-colour derivation graph), `theme-components.css`, `theme-cascade.css`,
and `theme-fallback.css` (the `@supports not (color: oklch(from red l c h))`
precomputed ramp). `light-dark()` drives surface/ink pairs off
`prefers-color-scheme`. Tests: `tests/test_theme_static_files.py`,
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage C (CSS architecture). Confirm: the bulk of the
> chrome's colours are *derived* in CSS (grep `theme-derive.css` for
> `color-mix(in oklch` and `oklch(from var(--mh-brand-seed)` — the derivation
> graph is present, not a hardcoded ramp); `light-dark()` is used for
> surface/ink pairs and `prefers-color-scheme` is honoured; the Safari
> long-tail fallback lives inside an `@supports not (...)` block in
> `theme-fallback.css` with no JS polyfill; and the CSS is served as static
> files with a cache-busting URL (not re-inlined per request). Run
> `tests/test_theme_static_files.py` + the full suite. Report the count of
> hardcoded brand-colour hex literals found in colour-derivation positions in
> the CSS layers (expected: ~0).

#### Stage D — Theme delivery (Flask)
**Shipped:** a `before_request` hook + `_theme_seed_style_block()` emit an
inline `<style id="mh-theme-seed">` carrying the active org's brand-seed
override into `<head>` *before* the external stylesheet (zero FOUC).
Resolution is three-tier (flag-off → pinned-org palette → generic-default).

**Verification prompt:**
> [Preamble.] Verify Stage D (theme delivery). Boot the app and request a
> page; confirm the inline `<style id="mh-theme-seed">` block appears in
> `<head>` **before** the external `theme-base.css` link (so there is no flash
> of un-themed content) and carries the active organisation's seed. Confirm
> the three-tier resolution in `_theme_seed_style_block()`:
> `MEDIAHUB_ADAPTIVE_THEME=0` emits nothing (falls through to the static
> cascade), a pinned org uses its `derived_palette`, and no-org uses the
> generic-default theme. Confirm the payload is small (hundreds of bytes, not
> the full palette). Report the head ordering and the three-tier behaviour.

#### Stage E — "Looks right" cascade
**Shipped:** the organisation-finalise handler derives + persists the palette
(`ensure_derived_palette(force=True)`) and navigates via
`document.startViewTransition`; `theme-cascade.css` carries
`@view-transition { navigation: auto }`, the `:root` seed `transition`, and
the `prefers-reduced-motion: reduce` instant-swap override. Tests:
`tests/test_theme_cascade.py`, `tests/test_browser_cascade.py`.

**Verification prompt:**
> [Preamble.] Verify Stage E (the cascade). Confirm: the "Looks right — start
> creating" finalise path saves the brand kit, derives + persists
> `derived_palette`, and wraps the navigation in `document.startViewTransition`
> (degrading to a normal nav where unsupported); `theme-cascade.css` contains
> the `@view-transition` rule, the `:root` colour `transition`, and a
> `@media (prefers-reduced-motion: reduce)` block that disables both; and
> because every derived var is a `color-mix`/`oklch(from …)` of the seed,
> changing the seed alone interpolates the whole palette in lockstep. Run
> `tests/test_theme_cascade.py`; run `tests/test_browser_cascade.py` with
> `MEDIAHUB_RUN_BROWSER_TESTS=1` if a browser is available (else note it's
> gated). Report each contract check.

#### Stage F — Logo intelligence
**Shipped:** `theming/logo_chip.py` defaults to a neutral chip behind an
uploaded logo and computes a "safe to drop chip" decision (dominant
non-neutral colour vs active surface in OKLCH; ΔE2000 + APCA Lc gates in both
polarities); MediaHub's own marks use `fill="currentColor"`; uploaded SVG
marks are never recoloured. Tests: `tests/test_logo_chip.py`,
`tests/test_mediahub_mark_theming.py`.

**Verification prompt:**
> [Preamble.] Verify Stage F (logo intelligence). Confirm: `logo_chip.py`
> defaults to a neutral chip and exposes a deterministic "safe to drop chip"
> test driven by ΔE2000 + APCA Lc in both light and dark polarities;
> MediaHub's *own* SVG marks use `fill="currentColor"` so the chrome adapts to
> ink colour; and the path for *uploaded* logos never recolours or injects
> `currentColor` into an unknown mark (it only adds/removes a chip behind it).
> Run `tests/test_logo_chip.py` + `tests/test_mediahub_mark_theming.py` + the
> full suite. Report the chip-decision logic and confirm the "never recolour
> uploaded marks" guarantee holds.

#### Stage G — Single source of truth (motion + email + static graphic)
**Shipped:** `theming/theme_store.py` writes the DTCG palette JSON to
`DATA_DIR/themes/<profile_id>.json`; `visual/motion.py` passes it as
`inputProps` to `render.js`; `brand/newsletter_renderer.py` Premailer-inlines
the resolved hexes; `graphic_renderer/render.py` reads the same JSON instead
of `BrandKit.primary_colour`. Tests: `tests/test_theme_store.py`,
`test_motion_theme_store.py`, `test_newsletter_theme_store.py`,
`test_graphic_renderer_theme_store.py`.

**Verification prompt:**
> [Preamble.] Verify Stage G (single source of truth). Confirm there is
> exactly **one** palette source — the `theme_store.py` JSON at
> `DATA_DIR/themes/<profile_id>.json` — and that all four consumers read it:
> `visual/motion.py` (→ Remotion `inputProps`), `brand/newsletter_renderer.py`
> (Premailer-inlined hexes, since email clients don't support custom
> properties), `graphic_renderer/render.py`, and the web cascade. Pick one
> seed, derive its theme, and assert the **same** role hex appears in the
> motion props, the inlined email HTML, the static graphic, and the CSS seed
> block — **zero drift across media**. Run the four `*_theme_store.py` tests +
> the full suite. Report the cross-media hex comparison.

#### Stage H — Explainability + QA
**Shipped:** `PaletteQualityReport` (`quality.py` `to_summary()` +
`to_detail()`) logs APCA Lc per role pair, the CIEDE2000 matrix for brand ×
{neutral, success, warning, danger}, Machado-CVD ΔE under
deutan/protan/tritan, the Cohen-Or harmonic-fit energy, and a decision trace;
a "Why does my theme look like this?" panel on `/organisation/setup` shows the
decisions + lets a committee member override a role (logged, with a
cultural-clash warning if it lowers a status colour's ΔE); a non-blocking
callout fires when the hostile-seed repair loop ran. Tests:
`tests/test_quality_detail.py`, `test_repair_callout.py`,
`test_org_palette_confirm.py`.

**Verification prompt:**
> [Preamble.] Verify Stage H (explainability + QA). Confirm: every derivation
> produces a `PaletteQualityReport` with APCA Lc per text-on-surface pair, the
> brand×status CIEDE2000 matrix, Machado-CVD ΔE under all three CVD types, the
> Cohen-Or harmonic-fit energy, and a human-readable decision trace; the "Why
> does my theme look like this?" panel renders these on `/organisation/setup`;
> a manual role override is persisted *and* logged, and lowering a status
> colour's ΔE raises a cultural-clash warning; and when the repair loop fires
> on a hostile seed, a non-blocking callout explains *which status colour* was
> nudged and why (never silently rewriting the brand colour). Run
> `tests/test_quality_detail.py` + `test_repair_callout.py` +
> `test_org_palette_confirm.py` + the full suite. Report each explainability
> surface.

#### Stage I — Test coverage
**Shipped:** `tests/theming/` with golden-master snapshots for ~30
representative seeds (incl. fluorescent `#DFFF00`, muddy `#2A3A1A`, near-white
`#FAFAF7`, near-black `#0C0C0C`, brand red `#A30D2D`, brand navy `#0E2A47`, +
real club colours) in `seeds_catalogue.py` / `snapshots/`, plus
APCA/CVD/quality/repair unit tests; `tests/test_browser_cascade.py` is the
Playwright/browser-use end-to-end (gated on `MEDIAHUB_RUN_BROWSER_TESTS=1`).

**Verification prompt:**
> [Preamble.] Verify Stage I (test coverage). Confirm: the golden-snapshot set
> in `tests/theming/` covers the hostile seeds
> (neon/muddy/near-white/near-black/pure-primary) **and** real club colours;
> the gate tests actually assert the §1.6 thresholds (APCA Lc ≥ 75 for
> text-on-surface; CIEDE2000 ≥ 5 between adjacent tonal stops; ≥ 15 between
> brand and each status colour; Machado-deuteranopia ΔE2000 ≥ 10 for the same
> triples; Cohen-Or fit below threshold); the snapshots regenerate
> deterministically (no flakiness); and `tests/test_browser_cascade.py` exists
> and is correctly gated. Run `python -m pytest tests/theming/ -q` and report
> the count + whether any threshold is asserted more weakly than §1.6 states.

#### Stage J — Cutover + polish
**Shipped:** `_adaptive_theme_enabled()` reads `MEDIAHUB_ADAPTIVE_THEME`
(default **on**; `0/false/off/no` rolls back to the static cascade) — J1;
`_default_theme_json()` runs the generic-default BrandKit (`#0E2A47` /
`#C9A227`) through the pipeline for unconfigured first-run — J2;
`docs/THEMING.md` documents the architecture, role-token table,
operator-overridable variables, and academic citations — J3. Tests:
`tests/test_adaptive_theme_flag.py`, `test_default_theme.py`,
`test_theming_md.py`.

**Verification prompt:**
> [Preamble.] Verify Stage J (cutover + polish). Confirm: `MEDIAHUB_ADAPTIVE_THEME`
> defaults **on**, and setting it to `0`/`false`/`off`/`no` cleanly reverts
> every page to the static Stage-A cascade with no errors (the on-disk JSON,
> audit panel, and repair callout keep working regardless); the generic-default
> brand kit is themed through the same pipeline (unconfigured deployments get
> the upgrade, no regression); and `docs/THEMING.md` documents the
> architecture, the role-token table, the variables an operator may safely
> override, and the inline academic citations. Run
> `tests/test_adaptive_theme_flag.py` + `test_default_theme.py` +
> `test_theming_md.py` + the full suite. Report the flag round-trip and the
> default-theme behaviour.

---

### 3. Full-engine acceptance audit (maps to the §1.6 acceptance criteria)

**Verification prompt:**
> [Preamble.] Run the §1.6 "definition of done" end-to-end and report a single
> scorecard against the five acceptance criteria:
> 1. **Hostile-seed gate.** Drive ~30 representative seeds (incl.
>    neon/muddy/near-greyscale/pure-primary) through `derive_theme`; assert
>    APCA Lc ≥ 75 for every text-on-surface role pair, CIEDE2000 ≥ 5 between
>    adjacent tonal stops, ≥ 15 between brand and each of
>    success/warning/danger, Machado-deuteranopia ΔE2000 ≥ 10 for those
>    triples, and Cohen-Or fit below threshold. Report any seed that fails any
>    gate.
> 2. **Live cascade.** Confirm the cascade works in Chromium (run
>    `tests/test_browser_cascade.py` with `MEDIAHUB_RUN_BROWSER_TESTS=1` if
>    available) and degrades to instant nav where View Transitions is
>    unsupported; reduced-motion users get an instant swap.
> 3. **No stray hardcoded brand colour.** Grep the whole repo for
>    brand-colour hex literals outside `theming/repair.py`'s curated-neighbour
>    fallback table; report any found in template/CSS/Python colour positions.
> 4. **Zero cross-media drift.** For one seed, assert the same role hexes
>    appear in web (CSS seed block), motion (`inputProps`), email (inlined
>    HTML), and static graphic.
> 5. **Suite green.** `python -m pytest tests/ -q` — no new failures vs
>    `main`, no weakened/skipped tests masking a structural break.
> Output: a five-row pass/fail table with the proof (test name / `file:line`)
> for each, plus any regression risk you spotted.

---

### 4. If a verification fails

A failure here is a real regression in shipped code, not a build step.
Capture a minimal repro (the seed, the role pair, the failing assertion),
report it against the stage above, and fix it in a **separate** branch + PR
scoped to that regression — keeping the colour-science deterministic and never
substituting an AI judgement or a hand-tuned per-seed override for the
algorithm. Re-run the full-engine audit (§3) before closing.

---

*End of roadmap.*
