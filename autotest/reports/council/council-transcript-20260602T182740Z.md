# Council transcript

## Framed question
DECISION: How should MediaHub build Capability 3 — a self-hosted SearXNG metasearch backend AND a bounded deep-research (ReAct) loop on top of it?

CONTEXT — MediaHub is a Flask monolith SaaS (synchronous, single Gunicorn worker + threads; NO async, no Celery) deployed on Render via a Docker render.yaml blueprint. It turns swimming-meet results into post-ready social content. Relevant existing pieces:
- A search seam: web_research.WebResearcher.search() today scrapes DuckDuckGo HTML (single-engine, brittle) with 30-day caching, returning SearchResult(url,title,snippet,source). It feeds context_engine (identity + a trust ledger) and pb_discovery (personal-best verification against swimmingresults.org).
- Capability 1 (shipped): a provider-agnostic OpenAI-compatible LLM client with a BOUNDED tool-calling loop: ai_core.ask_with_tools(tools, on_tool_call, max_rounds).
- A trust ledger (context_engine.trust) — only VERIFIED facts should ever be written to it.

LOCKED product decisions (do NOT relitigate — judge the engineering within them):
- Full scope: ship BOTH the SearXNG search backend and the deep-research ReAct loop.
- SearXNG runs as a SEPARATE, UNMODIFIED daemon. It is AGPL-3.0; its network-copyleft means we must NEVER fork or bundle it — we run stock SearXNG and query it over HTTP (format=json). It will be added as a SECOND service inside the EXISTING mediahub Render blueprint (not a new project), turnkey.
- When SearXNG is configured but unreachable, fall back to the existing DuckDuckGo search (real, non-fabricated results; logged degraded).
- Off-by-default: with MEDIAHUB_SEARCH_ENDPOINT unset, existing DDG behavior is unchanged.

PROPOSED ARCHITECTURE (pressure-test it):
- New web_research.searxng_client: a thin requests-based JSON client (GET {endpoint}/search?q=...&format=json), normalized to the existing SearchResult shape. SearXNG must have search.formats:[html,json] enabled (JSON is off by default) — via config, not code changes.
- WebResearcher gains SearXNG as the PREFERRED backend when configured, DDG fallback when down; reuses the existing cache.
- Deep-research loop (web_research.deep_research): built ON TOP of Cap-1's bounded ask_with_tools — expose two narrow tools to the model (search via WebResearcher, fetch_url), bound by max_rounds, synthesize a cited multi-source answer. Model-agnostic (any /v1 chat model via Cap-1). Outputs feed context_engine/pb_discovery, but ONLY verified facts reach the trust ledger.
- render.yaml: add a SearXNG service (stock searxng/searxng image via runtime:image) as a PRIVATE service (internal-only, not publicly exposed), MEDIAHUB_SEARCH_ENDPOINT wired via fromService. Redis optional at our low volume.
- Likely a 3a (SearXNG backend + render service) / 3b (deep-research loop) PR split.

QUESTIONS:
1. Is building the ReAct loop on Cap-1's ask_with_tools (search+fetch tools, bounded rounds) right, vs a hand-rolled IterResearch loop? Failure modes (runaway cost, looping, shallow synthesis)?
2. SearXNG as a PRIVATE Render service (internal-only) — right for security (avoid an open metasearch proxy)? Is Redis needed at small-club scale, or skip it?
3. How should deep-research outputs be gated before touching the trust ledger / PB verification, to avoid poisoning it with unverified web claims?
4. 3a/3b split, or one PR?
5. Biggest risk or blind spot for a small sports-club SaaS (ops burden, AGPL, loop cost, security)?

## Advisor responses
### The Contrarian
**The synchronous worker is the silent killer and nobody's talking about it.**

Deep research with multiple search + `fetch_url` rounds in a single Gunicorn worker thread doesn't just slow one user down — it locks the entire application for every other user for the duration of the loop. Five rounds × (search latency + page fetch latency) = potentially 45–90 seconds of worker blockage per invocation. On Render's typical starter setup, that's a denial-of-service you're shipping to yourself. This isn't a tuning problem; it's an architecture mismatch the proposal waves past entirely.

**`fetch_url` as an LLM tool is an SSRF waiting to happen.** The model will happily fetch Render's internal metadata endpoints, localhost, or any private Render service URL the model "decides" to try. You need an allowlist or at minimum a blocklist of RFC-1918 ranges and cloud metadata addresses. The proposal doesn't mention this once.

**The trust ledger gate is theatrical.** "Only verified facts reach the trust ledger" — verified *by what*? The model deciding a web page confirms a personal best is not verification. For PB data specifically, swimmingresults.org is your only authoritative source. The gate needs to be *structural* (source URL must match a known authority domain, not model judgment) or you're just laundering hallucinations through a ReAct wrapper.

**SearXNG without Redis means the upstream engines will throttle it immediately.** Google and Bing block bot traffic aggressively. At even modest usage, stock SearXNG without caching hammers the same upstream queries repeatedly and gets rate-limited. "Redis optional at small scale" undersells this — it's required for SearXNG to function reliably at all.

**The 3a/3b split ships infrastructure with zero user-visible value in 3a.** If 3b slips, you've paid the ops burden for nothing.


### The Outsider
The thing nobody's asking: **why does a swimming-meet social-content tool need a self-hosted metasearch engine at all?**

I'll take that as locked. Fine. Here's what actually jumps out:

**The sync/threading trap is the real risk.** A Flask monolith, single Gunicorn worker, NO async — and you're proposing a ReAct loop that fires multiple web fetches per round, up to N rounds, inside a request thread. One user triggers deep-research, and that thread is locked for potentially minutes. Every other user waits. This isn't a "failure mode" — it's the default behavior. The architecture section treats this like a background concern; it's actually the load-bearing beam.

**On the ReAct loop vs hand-rolled:** Cap-1's bounded ask_with_tools is the right call precisely because it's already bounded. Hand-rolling adds nothing except more code to debug. The failure modes (runaway cost, shallow synthesis) are real but are solved by the bounds — the question is whether the bounds are set correctly, not which loop structure you use.

**Redis at small-club scale:** Skip it. You said low volume. Redis is ops surface area you don't need yet. Add it when you have evidence you need it.

**Trust ledger gating:** This is undersolved in the proposal. "Only verified facts reach the trust ledger" is a principle, not a mechanism. Who verifies? The model? That's circular. You need an explicit human-or-rule confirmation step before any deep-research output touches the ledger — not just a "synthesis" flag.

**AGPL exposure:** Running unmodified stock SearXNG over HTTP is clean. Don't let anyone convince you to patch it "just slightly."

Biggest blind spot: the sync threading problem. Everything else is tunable.


### The Executor
**Ship it. Here's what you do Monday morning:**

**Q1 — ReAct on Cap-1:** Yes. You already have the bounded loop. Don't rewrite it. Two tools: `search(query)` → WebResearcher, `fetch_url(url)` → requests with a 5s timeout and a ~50KB truncation cap. The failure modes are real: runaway rounds (already solved by max_rounds), shallow synthesis (prompt engineering, not architecture), and fetch_url hitting paywalls/garbage (truncate + log, the model handles it). The only thing you add is a `deep_research(question, context) -> DeepResearchResult` wrapper that calls ask_with_tools, collects citations from tool responses, and returns structured output. Done.

**Q2 — Private service, no Redis:** Correct. Private internal URL only, never exposed. Redis at small-club volume is noise — SearXNG's in-process cache is fine. Skip it. Add it later if you hit rate limits.

**Q3 — Trust ledger gating:** Simple explicit whitelist. DeepResearchResult has a `verified_claims: list[Claim]` field. A Claim only gets written to the trust ledger if it has ≥2 independent source URLs AND the caller explicitly passes `verified=True`. PB verification stays on swimmingresults.org hits only — deep research can *suggest* PBs, never *assert* them. One guard function: `context_engine.trust.write_verified(claim)` that checks the flag. Nothing implicit.

**Q4 — Split PRs:** Yes. 3a is infrastructure (SearXNG service, searxng_client, fallback wiring). 3b is the ReAct loop. You can deploy 3a and immediately get multi-engine search before a line of ReAct code exists. Do it.

**Q5 — Biggest risk:** Synchronous fetch_url inside a Gunicorn thread during a deep-research loop. A 10-round loop fetching slow URLs will tie up your worker. Set aggressive timeouts (5s connect, 10s read) and cap total fetch time per research call. That's your Monday morning first line of code.


### The First Principles Thinker
The wrong question is buried in question 5, and nobody's saying it loudly enough: **a synchronous, single-worker Gunicorn process cannot safely run a multi-round ReAct loop inline with a web request.**

A bounded loop of `max_rounds=5` with two tool calls each — search (cached miss: ~1-2s), fetch_url (~1-3s), LLM round-trip (~3-8s) — means a single deep-research invocation blocks your only worker for **30-60 seconds**. During that window, every other MediaHub user gets a 504. This isn't a theoretical risk; it's the arithmetic of your deployment.

The architecture needs to acknowledge this directly and make a deliberate choice: either deep-research is **explicitly a background or async operation** (webhook trigger, polling endpoint, background thread with care), or it's invoked only in administrative/batch contexts where monopolizing the worker is acceptable. Don't build a user-facing call path that triggers it without solving this first.

On the actual questions:

**Cap-1's ask_with_tools is correct** for the loop — don't hand-roll. The failure modes (runaway cost, looping) are already handled by `max_rounds`. The real gap is **shallow synthesis**: the model will summarize search snippets, not verify claims. That's the gating problem.

**Trust ledger gating must be structural, not prompt-based.** Deep-research output should produce a `ResearchDraft` with a `confidence` field and explicit `sources`. A *separate, deterministic* function — not the LLM — decides what gets written to the ledger. If a claim has no source URL that returns a parseable result, it never touches the ledger. The model synthesizes; code verifies.

**SearXNG private-only is correct.** Skip Redis at this scale — disk/memory cache is fine.

**3a/3b split is mandatory**, not optional. The sync-worker problem must be resolved in 3b's design, not assumed away.


### The Expansionist
The trust ledger is the sleeper asset here, and the deep-research loop is what finally lets you fill it at scale. Everyone's treating this as an infrastructure upgrade — better search, less brittleness. That's underselling it by an order of magnitude.

**On Cap-1 vs hand-rolled:** Cap-1 is correct and the upside is enormous. You already have a bounded, model-agnostic tool loop. The moment you expose `search` and `fetch_url` as tools, you've built a swimmer-profile research agent that can pull from SwimmingWorld, state association sites, club pages, and meet archives *in one call*. Hand-rolling IterResearch means you own the loop forever. Let the model decide when it has enough — that's the whole point.

**SearXNG private-only is undersold:** Running it internal means you can tune its engine list specifically for aquatics sources (SwimmingWorld, USA Swimming, Swimrankings, Hytek result dumps). Most SearXNG deployments are generic. Yours can be the best swimming-specific metasearch in existence. That's a real product moat if you ever expose researcher features to coaches.

**The trust ledger gating IS the product:** The gate between web claims and verified facts isn't a liability constraint — it's what makes your content trustworthy when every AI content tool is flooding feeds with hallucinations. "Verified PBs only" is a marketing line. Build the verification pipeline robustly (source attestation, round-trip confirmation against swimmingresults.org), and you can advertise accuracy as a feature.

**3a/3b split is right** — ship the search backend first so you have real multi-source data flowing before you build the reasoning layer on top of it.

The blind spot everyone's ignoring: swimmer data coverage compounds. Every verified fact you write to the ledger makes the next deep-research call cheaper and faster. This isn't a one-time upgrade — it's a flywheel.


## Peer reviews (anonymisation: A=The Executor, B=The Contrarian, C=The Outsider, D=The Expansionist, E=The First Principles Thinker)
### Review 1
## Council Review

**1. Strongest: Response B**

B is the sharpest because it catches three issues no other response adequately addresses: the SSRF risk on `fetch_url` (the model will try to fetch Render's internal metadata endpoints — nobody else mentions this), the Redis argument (correctly frames it as *required* for SearXNG upstream reliability, not optional), and the trust ledger critique ("theatrical" is exactly right — model judgment is not verification). B also uniquely questions the 3a business value if 3b slips. E is a close second for the sync arithmetic, but B has more unique findings.

**2. Biggest Blind Spot: Response D**

D never engages with the sync-worker problem at all. It reframes every engineering constraint as product opportunity (flywheel! moat!), but a 45-second worker blockage is not a flywheel — it's a DoS. It's the only response that could mislead a team into shipping without addressing the architecture mismatch.

**3. What All Responses Missed**

`fetch_url` content extraction is underspecified. Raw `requests` against arbitrary URLs returns noisy HTML — nav, ads, scripts — and silently fails on JS-rendered pages. Many swimming results archives (HyTek exports, state association sites) are either JS-heavy or non-standard formats. No response asks: *what does the model actually receive from fetch_url, and how is it extracted?* Without an HTML-stripping step and a clear failure mode for JS-rendered pages, the tool will quietly return garbage on a large fraction of the URLs the model will attempt to fetch.


### Review 2
**1. Strongest: B**, narrowly over E. B is the only response to flag SSRF on `fetch_url` — a critical omission in the proposal — and correctly reframes Redis as *required* for SearXNG upstream reliability, not optional. Its "theatrical trust gate" critique is the most precise: "≥2 sources + verified=True flag" (A's proposal) is still model-driven, not structural. E has the best arithmetic on the sync-worker problem (30–60s blocking math) and the clearest structural remedy.

**2. Biggest blind spot: D.** It's the only response that doesn't flag the synchronous worker problem at all, treating the deployment constraints as solved. Its "product moat" framing is interesting but papers over the engineering risks entirely. The trust ledger section actively misleads — calling robust verification "a marketing line" without specifying the mechanism.

**3. What all missed: prompt injection via `fetch_url`.** If MediaHub fetches arbitrary web pages and feeds their content to an LLM that writes to a trust ledger, an adversary who knows this can serve a malicious page designed to override the synthesis. The trust ledger isn't just vulnerable to hallucination — it's a write target for anyone who can get a URL into the research loop. No response mentions sanitizing or sandboxing fetched content before it reaches the model.


### Review 3
**1. Strongest: Response B**
B is uniquely valuable for two findings others either miss or soft-pedal. First, the SSRF risk on `fetch_url` — the model will happily fetch Render's internal metadata endpoints or other private services; no other response names this. Second, B's Redis argument is substantively different from the others' "skip it": SearXNG's upstream engines (Google, Bing) aggressively throttle bot traffic, and without caching you'll get rate-limited into unreliability, not just slowed down. E is a close second for its arithmetic on the sync-worker blocking problem.

**2. Biggest blind spot: Response D**
D ignores the sync-worker problem entirely while pitching product moats. For a Flask monolith with one Gunicorn worker, this isn't a footnote — it's the blocker. D's enthusiasm is misplaced without addressing it.

**3. What all responses missed**
Cache coherence across the fallback boundary: if SearXNG goes down *mid-loop*, DDG kicks in for subsequent rounds, and results from different engines get mixed inside a single research session. Nobody addresses this. Also absent: LLM token cost accounting per deep-research invocation — on a per-club SaaS, an unbounded cost-per-call is a business risk distinct from the `max_rounds` engineering bound.


### Review 4
**1. Strongest: B**
B is the most valuable response. It uniquely identifies the SSRF vulnerability in `fetch_url` — the model will happily fetch Render metadata endpoints or internal service URLs, and the proposal never mentions this. It also correctly calls out that Redis isn't optional for SearXNG (upstream engines throttle bot traffic aggressively), directly contradicting A and C's "skip it" advice. Its trust ledger critique ("laundering hallucinations through a ReAct wrapper") is the sharpest framing.

**2. Biggest blind spot: D**
D barely acknowledges the synchronous worker problem — the issue every other response flags as load-bearing. It reframes the whole architecture as a product moat opportunity while waving past the fact that a single deep-research invocation can deny service to all other users. Enthusiasm without load arithmetic is a liability.

**3. What all missed**
None address mid-loop failure recovery: if `fetch_url` times out on round 3 of 5, what happens? Do you return partial results, raise, or silently truncate? This matters for the trust ledger — partial synthesis is arguably more dangerous than no synthesis, since it looks complete. The proposal needs an explicit incomplete-research state and a discard-rather-than-poison policy.


### Review 5
## Council Review

**1. Strongest: Response B.**
B catches the SSRF vulnerability in `fetch_url` that every other response misses entirely — an LLM-directed fetch tool will happily request Render's internal metadata endpoints or private service URLs. B also correctly challenges the consensus that Redis is optional; at any real usage, SearXNG hammers upstream engines and gets throttled without caching. Its critique of the trust ledger gating as "theatrical" is the sharpest framing of a real problem.

**2. Biggest blind spot: Response D.**
D is almost entirely product vision. It barely acknowledges the synchronous worker problem (one vague mention) and completely ignores SSRF. Enthusiasm about a "swimming-specific metasearch moat" does not substitute for engineering analysis of the constraints actually given.

**3. What all responses missed:**
**Cost observability.** Nobody put numbers on LLM token consumption per `max_rounds` loop. For a small sports-club SaaS, a single deep-research call at max_rounds=10 could consume more tokens than the rest of the day's usage combined. There is no mention of per-call token budgeting, cost caps, or logging that would let the team detect runaway spend before it shows up on the bill. This is a concrete operational risk that deserves a first-class answer.


## Chairman verdict
## Where the Council Agrees

**Cap-1's ask_with_tools is the right foundation.** Don't hand-roll a loop you already have. The bounded structure solves runaway cost and rounds by construction; shallow synthesis is a prompt problem, not an architecture problem. This is unanimous.

**SearXNG as a private internal service is correct.** No public exposure, internal URL only, AGPL compliance via stock unmodified image over HTTP. No dissent.

**3a/3b PR split is right.** 3a ships multi-engine search as an immediately usable improvement to the existing search path. 3b is the ReAct loop on top. These are genuinely separable and the split is the correct delivery sequence.

**Trust ledger gating must be structural, not model-based.** The model synthesizes; deterministic code decides what reaches the ledger. This is unanimous and the proposal's hand-wave here is its weakest point.

**The synchronous worker is a first-class architectural constraint.** A multi-round ReAct loop inside a single Gunicorn worker thread will block every other user for 30–90 seconds per invocation. This is not a tuning problem.

---

## Where the Council Clashes

**Redis: required or optional?** The Outsider and Executor say skip it at low volume. The Contrarian says it's required for SearXNG to function reliably because Google and Bing throttle bot traffic aggressively — and every SearXNG query fans out to multiple upstream engines simultaneously. The Contrarian is right. "Low volume" at the MediaHub level is still repeated identical queries across users and sessions; without caching, upstream engines see undifferentiated bot traffic and start blocking. Redis is not a scaling luxury here — it's what keeps SearXNG's upstream engines from rate-limiting you into the fallback path you were trying to escape. Ship it in 3a.

**3a standalone value:** The Contrarian argues 3a ships ops burden with no user-visible value if 3b slips. The Executor and others disagree — multi-engine search via SearXNG replaces brittle DDG HTML scraping and is independently valuable. The Executor is correct. Better search results flow immediately to existing features (context_engine, pb_discovery) the moment 3a deploys.

---

## Blind Spots the Council Caught

These were missed by the original proposal and deserve first-class treatment:

**SSRF on fetch_url** (Contrarian, confirmed by all five peer reviews): An LLM-directed HTTP fetch tool will follow whatever URLs the model generates — including Render's internal metadata endpoint (`169.254.169.254`), RFC-1918 addresses, and other internal Render services. The proposal never mentions this. You need an explicit blocklist before fetch_url ships: RFC-1918 ranges, link-local ranges, and cloud metadata addresses. This is not optional.

**Prompt injection via fetched content** (Peer Review 2): Fetched web pages fed directly to the LLM that writes to the trust ledger are an adversarial attack surface. Anyone who can get a URL into the research loop can serve a page designed to override synthesis. Fetched content must be sanitized before it reaches the model context — at minimum, strip HTML to plain text and enforce a hard token cap on what any single fetch contributes.

**fetch_url content quality** (Peer Review 1): Raw requests against arbitrary URLs returns noisy HTML. Swimming results archives frequently use JS-rendered pages (HyTek, state association sites) that return nothing useful. The proposal assumes fetch_url works; it will silently return garbage on a meaningful fraction of URLs. You need HTML-to-text extraction and an explicit failure state when content is unparseable.

**Mid-loop failure recovery** (Peer Review 4): If fetch_url times out on round 3 of 5, what is the output state? Partial synthesis looks complete and is more dangerous to the trust ledger than no synthesis. You need an explicit `IncompleteResearch` state and a discard-rather-than-poison policy before any partial result is considered for the ledger.

**Per-call token cost observability** (Peer Review 5): max_rounds bounds loop count, not token spend. At max_rounds=10 with large context windows, a single deep-research invocation can consume more tokens than the rest of a day's usage. There is no mention of per-call token budgeting or cost logging. For a small-club SaaS with thin margins, this is a business risk that needs a hard cap and logging from day one.

**Cache coherence across the fallback boundary** (Peer Review 3): If SearXNG goes down mid-loop, DDG kicks in for subsequent rounds. Results from two different engines now mix inside a single research session with different freshness, coverage, and reliability characteristics. The fallback is correct as a session-level decision, not a round-level one.

---

## The Recommendation

**Ship the architecture as proposed, with these non-negotiable modifications:**

**Before 3b ships, resolve the sync worker problem explicitly.** Deep-research cannot be a synchronous user-facing request path in a single-worker Gunicorn process. Pick one: (a) expose it only in administrative/batch contexts where monopolizing the worker is acceptable, (b) run it in a background thread with a polling endpoint, or (c) accept that it's a low-concurrency internal tool and document that constraint. Do not ship 3b without making this a named, deliberate choice with the tradeoffs written down.

**fetch_url requires three additions before it ships:** SSRF blocklist (RFC-1918 + link-local + cloud metadata), HTML-to-text extraction with a hard per-fetch token cap (~2000 tokens), and an explicit failure state for JS-rendered or unparseable pages. These are not polish — the tool is insecure and unreliable without them.

**Redis in 3a, not later.** SearXNG without Redis will get throttled by upstream engines. This undermines the entire point of 3a. Wire it in the render.yaml from the start.

**Trust ledger gating must be structural:** PB claims require a source URL that matches a known authority domain (swimmingresults.org) AND a round-trip confirmation hit — model judgment does not count. General research claims require ≥2 independent source URLs, an explicit `verified=True` flag set by calling code (not the model), and must pass through a single guard function `context_engine.trust.write_verified(claim)`. Partial research results (from mid-loop failures) are discarded, never written.

**Add per-call token logging from day one.** Log input tokens, output tokens, and rounds consumed for every deep-research invocation. Set a hard per-call token cap in 3b's implementation. You cannot manage a cost you cannot see.

The Expansionist's flywheel framing is correct as product vision — verified swimmer data compounds — but it is contingent on the trust ledger being reliable. The ledger's reliability is contingent on the structural gating above. Get the gate right first; the flywheel follows from that, not from shipping fast.

---

## The One Thing to Do First

**Decide synchronous vs. background for deep-research before writing a line of 3b code.**

Every other risk — SSRF, trust ledger poisoning, token costs, partial results — is bounded and fixable. The sync-worker problem is architectural: if you build 3b as a user-facing synchronous call path, you will either need to rip it out later or accept that one research invocation denies service to all other users for a minute or more. That decision shapes everything about 3b's interface, its calling conventions, and how it integrates with the rest of the product. Make it explicitly, document it, and then build.
