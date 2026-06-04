# Results from a link

Paste a results-page URL and MediaHub reads the site the way a person with a
browser would — any structure, any technology, any sport — gathers every result
across the competition, and hands it to the same pipeline that processes an
uploaded file. Nothing downstream has to change: the link becomes a file.

This is for the social-media volunteer who has a *link* to the results, not a
file. They paste it; MediaHub does the rest.

---

## How it reads a page — three escalating tiers

It reads each page in the cheapest way that works and only tries harder when it
has to:

| Tier | What it does | When it kicks in |
|---|---|---|
| **A · Static fetch** | A plain, SSRF-validated HTTP GET. Handles ordinary HTML, PDFs, CSV/XLSX downloads, and raw JSON. | Always first. |
| **B · Rendered fetch** | A real headless Chromium browser runs the page's JavaScript, then captures the finished HTML, the visible text, the data the page fetched in the background (XHR/fetch JSON — usually a SPA's cleanest data), and a screenshot. | When the static page is thin, a "please enable JavaScript" shell, or has no result-shaped content. |
| **C · AI page reading** | The AI *looks* at the page — its text and screenshot — and writes the results out as CSV. | When even rendering yields nothing machine-readable: canvas-drawn tables, hostile markup, or results posted as an image. |

Each tier's output lands in a local **mirror** — a folder of files the existing
interpreter already understands. The mirror is zipped and fed to the same
`interpret_document()` path a Hy-Tek `.zip` upload takes.

```
URL → crawl (Tier A → B → C as needed) → local mirror → ZIP → existing pipeline → review
```

---

## Sport-agnostic by design

Nothing keys on a vendor or a sport. The engine matches the *shapes* competition
results take — times (`1:23.45`), scores (`3 – 1`), placings (`1st`, `14th`),
distances and points (`6.42 m`, `980 pts`) — and the *structure* of a site
(frames, links, tables, JSON APIs). A swimming championship, a football league
table, an athletics spreadsheet, and a darts scoreboard all flow through the
same code.

> Note: ingestion is sport-agnostic, but *detector quality* (which achievements
> are worth a post) for a new sport still comes from registering that sport in
> the recognition engine. Until then, non-swim runs surface generic
> table-derived content honestly.

---

## Deterministic vs AI — where each is used

The deterministic engine stays primary and is never replaced. AI is used only
for genuine judgement, and its output is always re-checked deterministically.

| Step | Deterministic | AI |
|---|---|---|
| Fetch + render | ✅ | |
| Find result-shaped files (the "shape gate") | ✅ | |
| Parse JSON / CSV / XLSX into tables | ✅ | |
| Decide *which links* probably lead to results (when the walk is ambiguous) | | ✅ link triage |
| Read a page that has **no** machine-readable table (image/canvas) | | ✅ page reading |
| Detect PBs / medals / rank cards / colour science | ✅ | |

Tier C's AI output is (a) **marked** with an `extraction:"ai"` sidecar, (b)
**confidence-scored** by a deterministic shape check, (c) re-fed through the
deterministic interpreter and detectors, and (d) human-approved like everything
else. If AI reading is required and no provider is configured, the run fails with
an honest error — never a made-up result.

---

## In the review — provenance you can trust

A run created from a link carries its origin into the review page:

- **Source chip.** The review header shows `Source: <host>`, linked to the exact
  URL the results came from, so every generated card is traceable to where it was
  read.
- **"AI-read from page" marker.** If any results were read by Tier C (the AI
  vision path) rather than parsed deterministically, the header says so and shows
  the average confidence. AI-read rows are *marked*, never hidden — and they were
  still re-checked by the deterministic interpreter like any other input.
- **Re-fetch latest results.** One click re-reads the site and stages a **new**
  run; the run you're looking at is never mutated. Useful when a meet publishes
  updated or additional results.
- **Club pre-select.** On the configure step, the club whose name best matches
  your organisation is pre-selected — abbreviations like "Otter SC" ↔ "Otter
  Swimming Club" included — and you still confirm before running.

---

## Security model

Reading arbitrary websites is a security-sensitive surface. Every fetch is
bounded and validated:

- **SSRF everywhere.** The destination host is resolved and every resulting IP is
  checked; private, loopback, link-local, and cloud-metadata addresses
  (`169.254.169.254`) are refused. Only `http`/`https`. Redirects are followed
  manually, re-validating the host at every hop. This holds inside the browser
  too: Chromium request interception aborts any request to an internal host.
- **Scope.** The crawl stays on the same host, under the entry URL's path prefix.
  The browser is pinned to that scope: off-scope page *navigations* are aborted;
  third-party assets (fonts, images) are allowed to load read-only but are never
  followed as crawl targets.
- **Content-type allowlist.** Only HTML, PDF, plain text, CSV/TSV, JSON, ZIP,
  XLSX, and common image types are kept. Anything else is dropped.
- **ZIP safety.** The mirror ZIP is built inside the existing compression-bomb
  guards (member count, per-member and total uncompressed size, ratio caps).
- **Prompt-injection containment.** All page text is passed to the AI as clearly
  delimited *untrusted data*; the instruction frame lives in the system prompt
  and forbids following instructions found inside the page. The link-triage model
  can only label links *by index* — it can never introduce a URL.
- **Resource budgets.** Page/byte/depth/time caps, a hard rendered-page budget, a
  hard AI-read budget, a politeness delay, and `robots.txt` are all enforced. A
  headless browser is a real cost, so one browser is shared per crawl and the
  whole job has a wall-clock ceiling.
- **Rate limit + kill-switch.** The route is per-session rate-limited, and the
  whole feature can be turned off with one environment variable.

---

## Configuration (environment variables)

All optional; sensible defaults ship. Read once per crawl.

| Variable | Default | What it caps |
|---|---|---|
| `MEDIAHUB_RESULTS_FETCH_ENABLED` | `1` | Master kill-switch. `0` hides the input and 404s the route. |
| `MEDIAHUB_RESULTS_FETCH_MAX_PAGES` | `400` | Pages visited per crawl. |
| `MEDIAHUB_RESULTS_FETCH_MAX_TOTAL_MB` | `50` | Total bytes kept per crawl. |
| `MEDIAHUB_RESULTS_FETCH_TIMEOUT_S` | `180` | Wall-clock ceiling for the crawl. |
| `MEDIAHUB_RESULTS_FETCH_MAX_RENDERS` | `60` | Pages rendered in a real browser per crawl. |
| `MEDIAHUB_RESULTS_FETCH_RENDER_BUDGET_S` | `240` | Total time budget for rendering. |
| `MEDIAHUB_RESULTS_FETCH_MAX_AI_READS` | `12` | Pages the AI may read per crawl. |
| `MEDIAHUB_RESULTS_FETCH_MAX_PAGE_MB` | `25` | Hard per-page byte cap. |

AI provider keys (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) are read from the
environment as usual; Tier C and link triage use the same provider path as the
rest of MediaHub.

---

## Troubleshooting

- **"No competition results were found."** The page may be login-walled or
  paywalled (out of scope — we never bypass logins or CAPTCHAs), or the results
  live on a different URL. Try the specific results/event page rather than the
  club homepage.
- **"This site's results are only in images, and no AI vision provider is
  configured."** The results are a picture and Tier C is needed, but no Gemini or
  Anthropic key is set. Ask your administrator to configure one.
- **The crawl stops early ("render budget reached").** A very large site hit the
  per-crawl render budget. Point at a narrower results section, or raise the
  budget env vars.

---

## Honest limits

- **Login-walled / paywalled sites** are out of scope; the job fails clearly.
- **CAPTCHA / bot-walls** are never bypassed.
- **Infinite-scroll archives**: the rendered fetch does a bounded settle, not
  unbounded scrolling.
- A competition spread across hundreds of event pages is consolidated into a few
  combined documents to stay within the pipeline's ZIP-safety budgets; every
  table is preserved.

---

## Where the code lives

- `src/mediahub/results_fetch/` — the inert engine: `fetch.py` (Tier A) +
  `rendered.py` (Tier B), `crawl.py` (the walker), `triage.py` (AI link triage),
  `ai_read.py` (Tier C), `package.py` (mirror → ZIP).
- `src/mediahub/interpreter/ingest.py` — deterministic JSON/CSV/XLSX ingestion.
- `src/mediahub/web/web.py` — the `/upload/from-url` route, background job, the
  "Paste a results link" input on the upload page, the review-page provenance
  (Source chip + AI-read marker), the club fuzzy pre-select on configure, and the
  `/runs/<id>/refetch` route.

Plain-English words: see [`../GLOSSARY.md`](../GLOSSARY.md).
