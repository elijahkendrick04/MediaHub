# ADR 0030 — Tier-B (rendered) fetch: pin Chromium DNS per navigation

**Status:** Accepted
**Date:** 2026-07-13
**Deciders:** Operator (task instruction: fix deep-review finding #125). Not
Council-gated — a security hardening on an existing internal fetch path,
reversible, not a deterministic-engine / commercial-surface decision.

## Context

The "results from a link" crawler has two read tiers. Tier A (static,
`results_fetch/fetch.py`) was hardened in batch 14b: it resolves + validates
the host and **pins the socket to the validated IP per redirect hop**
(`web_research/safe_fetch._pinned_open` / `pinned_stream_get`), closing the
classic DNS-rebinding TOCTOU on an attacker-supplied URL.

Deep-review finding **#125** flagged the same TOCTOU still open one tier down.
Tier B (`results_fetch/rendered.py`, headless Chromium) validated the host with
`is_url_safe` — and *cached that verdict per host for 60s* — but then let
**Chromium do its own DNS resolution** at navigation time and for every
sub-request. So an attacker could:

1. return a public IP for our up-front check (verdict cached "safe"), then
2. re-point the host's DNS at an internal/loopback/metadata address, and
3. have the browser reconnect there when it navigates.

The verdict cache widened the window: a host that flipped to internal stayed
trusted for up to 60s.

This is the browser that "never bypasses the human-approval rule" and runs
inside the deployed Render container, so a successful rebind is a route into
the internal network.

## Decision

Pin Chromium's resolver to the validated IP **per navigation**, mirroring what
Tier A does at the socket:

1. **Resolve + pin.** Before each `fetch`, `_apply_navigation_pin` resolves the
   target host to ONE validated public IP via `safe_fetch.resolve_safe_ip`
   (the same primitive Tier A pins to — it returns `None` if the host is
   unresolvable or *any* resolved IP is internal/reserved). `None` → the
   navigation is **refused before the browser connects**.
2. **`--host-resolver-rules`.** The browser is launched with
   `--host-resolver-rules=MAP <host> <ip>`, so Chromium performs **no DNS of its
   own** for the crawl host — it connects to exactly the IP we validated. A
   crawl is same-host scoped (`scope_for`/`in_scope`), so one launch pins the
   whole crawl; a host change tears the browser down and relaunches re-pinned.
   `MAP` matches only that host, so a page's legitimate cross-host CDN /
   subresource fetches still resolve normally (multi-host pages are not broken).
3. **Drop the verdict cache.** `_host_ok` keeps no per-host TTL cache. The
   pinned host is trusted without re-resolving (Chromium is locked to the
   validated IP regardless of what DNS now returns); every *other* host is
   re-validated fresh on each request, so nothing rides a stale "safe" verdict.

### What this closes

* The **top-level navigation** to the attacker-supplied URL — the primary
  finding — connects only to the validated IP. Rebinding cannot move it.
* **Same-host redirects** (the browser follows them under the same pin) and
  **same-host subresources** are covered by the same `MAP` rule.
* **Cross-host document redirects** were already refused by the same-host
  *scope* gate (`route_decision` aborts off-scope `document` requests).

## Consequences / residual risk

**Residual: cross-host (off-scope) subresources on *other* public hosts are
re-validated but not IP-pinned.** `--host-resolver-rules` pins only the crawl
host; a subresource the page pulls from a different public host (`<img>`,
`<script>`, `fetch`, …) is gated by a fresh `_host_ok` re-resolve but then
re-resolved independently by Chromium — a narrow TOCTOU remains. The blast
radius is bounded but **not** merely "blind GET":

* **Method is not restricted.** `route_decision` gates scheme, host safety, and
  (for `document` requests) scope — never the HTTP method. A CORS *simple
  request* — a form-encoded `POST` with no custom headers — is sent with no
  preflight, so the residual includes **state-changing** blind SSRF against an
  unauthenticated, CSRF-tokenless internal endpoint, not just `GET`. (`PUT`/
  `DELETE`/JSON bodies are non-simple and trigger a preflight `OPTIONS`, so they
  only fire if the internal endpoint returns permissive CORS.)
* **Reads are blocked only for non-CORS targets.** "The page cannot read the
  response" holds for opaque cross-origin responses (CORB/ORB). An internal
  endpoint that returns `Access-Control-Allow-Origin` (common for internal JSON
  APIs, dev servers, metrics/search dashboards) is **fully readable** by the
  page's JS, which can then exfiltrate it to a public host — i.e. full-read
  SSRF with exfiltration for that class, not blind.

We accept this for now and record it accurately here rather than ship a guard
that reads as "fully fixed". (Separately, and *pre-existing / out of scope for
this fix*: the page-scoped `route`/`response` handlers don't cover a
`window.open` popup, which is a distinct route-handler-scoping gap, not a
DNS-rebinding one.)

**Options considered to close the residual (not taken now):**

* **Abort all off-scope subresources.** Fully closes it, but breaks legitimate
  multi-host pages (fonts, CDN JS/CSS) and degrades the render the Tier-C AI
  reads — rejected against the "must not break legit multi-host pages"
  requirement.
* **Per-context forward proxy that resolves+pins ALL egress.** Route every
  Chromium request through an in-process proxy that applies `resolve_safe_ip`
  and connects to the validated IP for *every* host (Playwright supports a
  per-context `proxy`). This closes top-level and subresource TOCTOU uniformly,
  but is a materially bigger change (a CONNECT-tunnelling / TLS-preserving
  proxy) with its own surface. Deferred; this ADR is the pointer if the
  subresource residual is later judged worth closing.

The change is reversible (a launch-flag guard) and adds one `getaddrinfo` on the
first navigation to each host (an already-pinned host is accepted without
re-resolving — the browser is locked to the validated IP, so re-resolving would
do no security work and could only fail-close a legit same-host page on a
transient resolver blip). Proven by `tests/test_results_fetch_fetch.py` (offline:
pin derived through the real `resolve_safe_ip`, rebound-internal host refused
before launch, no verdict cache, same-host accepted without re-resolving) and
`tests/test_results_fetch_dns_pin.py` (live Chromium: the pin **overrides a
genuine conflicting resolution** — `localhost`, which resolves to 127.0.0.1, is
pinned to and reaches 127.0.0.2 instead — which is the precedence property
DNS-rebinding turns on).
