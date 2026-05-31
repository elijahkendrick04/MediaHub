# ADR 0002 — Decline integrating CloakBrowser (bot-detection-evasion browser)

**Status:** Accepted · **Date:** 2026-05-31 · **Decided by:** `llm-council` skill (unanimous)

# 1. Context

We were asked to evaluate whether [CloakBrowser](https://github.com/CloakHQ/CloakBrowser)
is a "skill" worth integrating into MediaHub, and to run the decision through the
repo's `llm-council` skill (5 advisors → anonymised peer review → chairman
verdict) and follow the chair's call.

**What CloakBrowser actually is:** a modified-Chromium 146 stealth browser — 58
source-level C++ patches whose stated purpose is to "pass every bot detection
test" (reCAPTCHA v3, Cloudflare Turnstile, FingerprintJS, BrowserScan). It does
source-level fingerprint spoofing (canvas / WebGL / audio / fonts / GPU / screen
/ WebRTC / network timing), ships as a drop-in Playwright/Puppeteer replacement
with human-behaviour simulation (`humanize=True`), auto-downloads a ~200MB
binary, and supports proxy/SOCKS5 with timezone/locale spoofing. The wrapper code
is MIT; **the binary ships under a custom license that restricts redistribution.**
It is **not** a Claude/agent skill — it is a software library/binary.

**What MediaHub is:** a swimming-results-to-social-content SaaS whose only browser
use is **server-side Playwright/Chromium rendering MediaHub's own HTML to PNG**
(plus Remotion for video). It does not scrape third-party sites and has no surface
that touches bot detection. Product principle: the intelligence layer is the moat;
everything explainable and auditable; human approval before publishing.

# 2. Decision

**Do not integrate CloakBrowser — in any form, now or "for later".** If we ever
need more meet data, the legitimate path is proper ingestion (official exports,
club uploads, partner feeds), never detection evasion.

# 3. Reasoning (council verdict, unanimous)

- **No use case.** Our only browser use is first-party rendering of our own HTML,
  where we control both ends. Bot-detection evasion solves the *inverse* problem
  — deceiving a hostile third party we never interact with. It is a category
  error, not a marginal fit.
- **Real cost for zero capability.** A 200MB unauditable auto-downloaded binary,
  Chromium-146 version skew against Playwright/Remotion, 58 C++ patches to track,
  and a **no-redistribute binary license inside our hosted Docker image** (the MIT
  wrapper does not cover the binary — a genuine distribution-license problem).
- **Principle violation.** Our moat is explainable / auditable /
  human-approval-before-publishing. A covert-evasion dependency directly
  contradicts that and is reputationally radioactive for a clubs / universities /
  societies SaaS.

# 4. Consequences & follow-up

- This record is itself an auditability asset: a documented "we evaluated and
  declined a bot-evasion dependency" decision for risk-averse institutional
  buyers.
- Follow-up worth considering (council blind-spot): a CI dependency-policy / SBOM
  check that blocks such binaries so a future "drop-in Playwright replacement"
  can't ride in unexamined.

---

# Appendix A — Full council transcript

Run via the `llm-council` skill on 2026-05-31. Five advisors answered in
parallel; responses were anonymised for peer review; a chairman synthesised the
verdict.

## Framed question

Should MediaHub integrate CloakBrowser (a modified-Chromium bot-detection-evasion
browser; ~200MB binary; custom no-redistribute license; not a skill) when its
only browser use is rendering its own HTML to PNG and its principles are
explainable / auditable / human-approval-before-publishing?

## Advisor responses

### The Contrarian
No legitimate use case exists, and that is the entire decision. MediaHub's only
browser usage is rendering its own HTML to PNG — zero need for fingerprint
spoofing, reCAPTCHA evasion, or mouse-curve humanisation. The "drop-in Playwright
replacement" framing is the trap: it sounds like a free upgrade and is actually
scope you will never use. Costs you will pay: a 200MB auto-downloaded binary on a
Render container (cold-start bloat, build-time fetch failures, unauditable
supply-chain exposure); a custom redistribution license inside your Dockerfile is
a legal landmine for a SaaS you intend to sell — your MIT wrapper is irrelevant
when the binary ships in your image. Reputationally radioactive: you serve swim
clubs, universities, committee volunteers. The moment a reviewer, customer, or
auditor greps your deps and finds a Chromium fork advertising "passes every bot
detection test," your "explainable, auditable, human-approval" positioning is
dead. Ask the only question that matters: what feature requires it? There is
none. Hard no. Do not add it.

### The First Principles Thinker
Strip the framing and the real question isn't "should I add CloakBrowser?" It's
"what problem do I have that this solves?" None. MediaHub's browser use is a
cooperative, first-party operation where you control both sides. Bot-detection
evasion solves the inverse problem: deceiving a hostile third party who doesn't
want you there. You'd be installing a lock-pick to open your own front door.
Rebuilt from first principles, this is a category error — orthogonal, not a
marginal fit. The deeper question nobody's asking: why is this even on the table?
Either it was suggested as a generic "Playwright replacement" and the stealth
payload rode in unexamined, or the word "browser" pattern-matched to your
Playwright usage. That's the bug. Second-order: your moat is "explainable and
auditable, human approval before publishing." Shipping a covert-evasion fork into
that codebase is reputationally radioactive. Don't integrate it. Don't shim it.
Don't keep it for "later." Delete the question and find out who put it in front
of you.

### The Expansionist
Even from the most upside-hungry seat on this council, I can't find the bull case
— and that's damning, because finding upside is my entire job. The "expansion"
CloakBrowser unlocks is scraping sites that actively don't want to be scraped.
For MediaHub that's not a new market — it's a different, worse company. Your moat
is the intelligence layer on structured input you're *given*: result files clubs
hand you willingly. The moment you pivot to defeating reCAPTCHA and Cloudflare to
harvest data nobody authorised, you trade an explainable, auditable product for
one whose core technology is deception — that incinerates the thing buyers trust.
The real undervalued asset is your reputation as the *legitimate* automation
layer for clubs, schools, and committees: risk-averse institutional buyers who
will not procure software that ships a bot-evasion binary. The genuine expansion
play is the opposite: lean harder into provenance and auditability — "every card
traceable to a source file" is the moat that scales into adjacent sports,
societies, and businesses. Zero upside, structural downside. Don't integrate it.

### The Outsider
No. This is a stranger walking into a bakery and offering to sell you a
lockpicking kit. Your product takes a swimming spreadsheet and makes a nice
graphic. The thing you're considering is purpose-built to defeat security systems
and impersonate humans to fool fraud detection. Those two do not belong in the
same paragraph. Your only browser use is your own server drawing your own
pictures — you control both ends, there is nothing to sneak past. CloakBrowser's
entire reason to exist (passing reCAPTCHA, spoofing fingerprints, faking mouse
curves) is to deceive a system that doesn't trust you. "Pass every bot detection
test" is the marketing copy of evasion software; stapling it to a product whose
pitch is "explainable, auditable, human-approved" is self-contradicting. Plus a
200MB auto-downloaded binary, a custom redistribution license, and a modified
Chromium you must track and patch — heavy and scary for zero benefit.
Reputational blast radius: you sell to swim clubs and universities. You haven't
described a single task this solves. A solution looking for a problem is an easy
no. Don't add it.

### The Executor
No legitimate Monday-morning task requires this. Walk the integration steps and
they all dead-end. Where does it plug in? MediaHub's only Chromium use is
Playwright rendering your own HTML to PNG — no site to spoof, no CAPTCHA to pass.
You'd swap a working `playwright` call for a 200MB fork to do a job with zero
bot-detection surface. Concretely Monday: auto-download a 200MB binary into your
Render container (slower cold starts, bigger image, license you can't
redistribute), pin Chromium 146 against Remotion/Playwright's expected versions
(version-skew breakage), and maintain 58 C++ patches you didn't write. Pure cost
for zero shipped capability. The licensing alone kills it. The one scenario where
it "works" — scraping protected results sites to auto-ingest meet data — is
exactly what your product principles forbid (explainable, auditable,
human-approved, structured input). First step if you genuinely need more meet
data: build proper ingestion — official exports, club uploads, partner feeds.
Verdict: do not integrate. There is no first step that ends in shipped value.

## Peer review (anonymised mapping: A=Executor, B=Contrarian, C=Outsider, D=First Principles, E=Expansionist)

**Review 1.** Strongest: E — it alone articulates the strategic inversion (the
only "expansion" is becoming a different, worse company) and pairs the rejection
with the correct opposite move: lean into provenance/auditability as the real
moat. Biggest blind spot: D — its "find who put it in front of you" framing is
rhetorically sharp but operationally weak; it leans on category-error rhetoric
over the concrete cost/legal/reputational analysis A, B, and E supply. What all
five missed: the governance/audit angle — *recording* this rejection is itself an
auditability asset, and a CI dependency-policy / SBOM check could block such
binaries so the next "drop-in Playwright replacement" can't ride in unexamined.

**Review 2.** Strongest: A — the only response that names MediaHub-specific
technical dead-ends (Chromium version skew vs Playwright/Remotion, the 58-patch
maintenance burden, Render cold-start cost) while also covering the principle
violation, reputation, and a constructive next step (proper ingestion). Biggest
blind spot: C — pure analogy with no engineering substance; it would lose to
anyone who actually wanted the tool because it never engages the practical case.
What all five missed: the decision can be *enforced*, not just argued — a
CI/dependency guard; that a no-redistribute license in a Render image is a real
distribution-license breach, not merely "optics"; and the provenance question
(who/what proposed it) that prevents recurrence.

## Chairman verdict

**Where the council agrees:** Unanimous, independently from all five lenses —
there is no legitimate use case. MediaHub's only browser use is first-party
rendering it controls both ends of; detection evasion solves the inverse problem.
The "drop-in Playwright replacement" is a trap that smuggles in unused stealth
scope. Concrete costs are real (200MB unauditable binary, Chromium-146 version
skew, 58 C++ patches, a no-redistribute binary license inside a hosted Docker
image). And it is reputationally radioactive for a clubs/universities SaaS whose
moat is "explainable and auditable, human approval before publishing."

**Where the council clashes:** Essentially nowhere on the verdict — only on
emphasis (technical/legal cost vs strategic/identity damage vs plain
self-contradiction). Peer review split only on which rejection was strongest
(A's stack-specific dead-ends vs E's strategic inversion); both are right and
complementary.

**Blind spots caught:** (1) Record the rejection — a documented decline is itself
an auditability asset; (2) enforce it — a CI dependency-policy / SBOM guard could
block such binaries.

**Recommendation:** Do not integrate CloakBrowser. It is not a skill, has no
product fit, violates MediaHub's principles, and imports legal, supply-chain, and
reputational risk for zero shipped capability. Future data needs → legitimate
ingestion, never evasion.

**The one thing to do first:** Record the decision (this ADR) so the "no" is
durable and auditable, and the question cannot quietly recur.
