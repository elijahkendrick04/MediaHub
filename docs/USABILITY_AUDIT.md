# MediaHub Usability Audit — Consolidated Work List

**What this is.** MediaHub turns swim-meet result files into ready-to-post, branded social content for non-technical sports-club volunteers. This document is the deduplicated output of a large usability audit: ~40 auditor and fact-checker agents walked 15 product surfaces, plus one live in-browser walkthrough of the primary flow and three gap-fill rounds (PWA/offline, localization, present/remote). Every claim below is grounded in a concrete `file:line` code fact and, where a fact-checker corrected an auditor, the corrected version is used. It is written to be picked up by an engineering session as a prioritized fix list.

**How it was produced.** 197 raw findings were verified against the code (172 CONFIRMED, 12 ADJUSTED, 13 live-walkthrough observations trusted as directly observed, 1 rejected and dropped). Duplicates that appeared from multiple surfaces (the mandatory interstitial, the overlapping export paths, jargon leakage, native `confirm()`/`alert()` dialogs, silent `fetch` failures) were merged into single findings that cite all the relevant evidence and list every affected surface. The result is **161 unique findings** grouped into ten themes (A first-run: 7, B too-many-steps: 8, C discoverability/IA: 20, D feedback/errors: 35, E destructive/data-safety: 14, F jargon: 14, G consistency: 15, H forms: 23, I mobile/a11y: 9, J dead-ends: 16).

## How to read this

Each finding is one compact block:

> **[ID] Title** — `severity` / `effort`
> Affects: page(s)/surface(s)
> What the user hits: the volunteer's point of view
> Evidence: `file:line` — the code fact
> Fix: concrete and actionable

**Severity**
- **high** — blocks or derails the core flow, or silently loses the user's work / ships wrong content.
- **medium** — causes confusion, retries, or wasted minutes, but the task is still completable.
- **low** — polish; the flow works but feels unfinished or off-brand.

**Effort**
- **quick-win** — a localized change (copy, a guard, a flag, one handler).
- **moderate** — a self-contained feature/handler change across a few call sites.
- **large** — a structural change (new editor, IA re-org, background-job conversion).

Findings tagged **(confirmed live)** were seen in the running app during the walkthrough, not only in code — treat them as real.

---

## Executive summary — the big themes

**1. Three first-run breakages hard-lock brand-new volunteers out of the entire product (confirmed live).** (a) The **Manual-build** org-setup path silently discards the whole form and loops back to setup — its POST endpoint is missing from the org-gate exempt list (`web.py:18039-18060`), so a fresh session never persists anything. (b) An **AI-build with no links** completes but leaves the org "not ready" (`club_profile.py:397-409`), so every nav click bounces back to the same setup form with no explanation — a hard lockout. (c) The content-builder **caption tone buttons fail on a missing CSRF token** (`web.py:17867-17877`) and render a silently empty caption. Nothing else matters until a new user can get in and produce one caption; these are the top of the list.

**2. Feature sprawl — too many steps and too many buttons — is real and measurable (the owner's hypothesis, confirmed).** MediaHub is ~460 Flask routes and ~30 feature areas in one ~60k-line file behind a 5–6 item nav. Getting one finished post out took **~11 clicks across 6 screens** in the live walkthrough, ending in a choice among **six competing download/export buttons** on the content builder (which actually shows ~12 download affordances counting newsletter and certificate links). Every Create tile forces a **"how it works" interstitial on every visit** (`web.py:31737`), adding a page to the most-travelled path; from the nav the upload task costs 7 clicks across 5 pages vs 4 from `/upload`. **Settings is a flat wall of 17 tiles** (`web.py:27924-28057`) with overlapping twins (org/brand vs Brand platform; Billing vs Pricing). `/pack`, `/pack/grouped` and `/review` are three overlapping views of the same cards with duplicated controls.

**3. Working features are undiscoverable — a whole class of URL-only orphans.** Fully-built pages are reachable only by typing the URL or are actively mislabelled "Coming soon": **Live meet** (`/live`, advertised "Coming soon" on Create), **Season wraps** (`/wraps`, shown as a disabled tile), **Drafts** (where all created content lands — no nav/home/Settings link), **Collections**, the **GDPR consent registry and athlete-rights (DSR) pages**, the **public achievements wall**, **Athlete Spotlight**, and the **slide-remote**. Meanwhile club-data tools volunteers use to *make* content (athletes & consent, records, data hub) are filed 3–4 clicks deep under Settings and absent from the nav.

**4. Feedback, loading and error states are a coin-flip that depends on which of ~30 feature areas you wandered into.** The app ships a good shared kit (styled toast, animated progress, focus-trapping modal) but adoption is uneven: error feedback splits three incompatible ways (branded toast on Review/reel; raw `alert()` across Documents/Newsletters; **24 empty `.catch` handlers** that swallow failures in total silence, `web.py:6035`). Several routes dump **raw JSON** into a full-page navigation on error (billing, audio, mockup, chart, DSR erasure), and raw Python exceptions reach customers on the run-failure, chat and demo surfaces. Offline-queued approvals **replay and silently discard** server rejections/holds while the pill reports "All changes synced" (`web.py:26719`). Long AI jobs on Documents/Newsletters/planner/setup show no loading state at all.

**5. Destructive actions are everywhere behind a bare native `confirm()` with no undo — and some ship wrong content.** Deleting a run, all runs, a collection, a photo, a document, a newsletter, a board idea, a sponsor, or a member is one OS confirm away and gone forever (no undo exists anywhere except approval Re-queue). Irreversible club-wide actions (merge athletes, flip consent enforcement, revoke the public wall's shared URL) have no confirmation or impact preview. Worse, two of three whole-pack exports **bundle rejected cards** (`web.py:56424-56448`) and the per-card ZIP **exports the internal headline instead of the caption the volunteer edited** (`web.py:31304-31305`) — the app ships content the club explicitly rejected or never wrote.

**6. Internal vocabulary leaks throughout the customer chrome.** "run" pervades the landing hero, Activity and delete confirms; the review filters show raw engine enums (`medal_gold`, `not_worthy`) and the browser tab reads "Recognition"; env-var names (`MEDIAHUB_REEL_MUSIC_LIBRARY`, `MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`, `STRIPE_PRICE_CLUB`) are printed on customer settings pages of a hosted-only SaaS; GDPR statute citations (Art 6(1)(a), Art 18, SAR) lead the consent forms a non-lawyer must use; captions fail with "AI is in heuristic mode".

**7. Core concepts are fragmented across 2–4 overlapping surfaces that disagree.** Brand is edited on three pages (`/organisation`, `/organisation/setup`, `/brand`) whose colour edits silently override each other. There are two consent stores with no signpost to the authoritative one, two things both called "reel", four ways to publish the same cards with three different publish/unpublish vocabularies, and four differently-named surfaces rendering the same run history.

**8. Mobile and accessibility gaps sit on a product whose users post from poolside phones.** Scheduling and board moves are drag-and-drop only (impossible on touch and keyboard); the review page scrolls sideways at 375px; export/toolbar buttons are ~24px tall; the notifications "dialog" never traps focus; the install chip can't be dismissed by keyboard; and the flagship Welsh localization is reachable only by hand-editing a `?lang=` URL and is only ~20% translated.

---

## Fix-first shortlist

The 15 highest-leverage items: all three severe first-run breakages, the high-severity quick-wins, and the data-safety highs that ship wrong content. Each links to its full finding below.

| # | Issue | Severity | Effort | Where (short) |
|---|-------|----------|--------|---------------|
| 1 | [A-1] Manual-build setup silently discards the whole form, loops to setup | high | quick-win | `web.py:18039-18060` |
| 2 | [A-2] AI-build with no links leaves org "not ready" → hard lockout loop | high | moderate | `club_profile.py:397-409` |
| 3 | [A-3] Caption tone buttons fail on missing CSRF → silently empty caption | high | quick-win | `web.py:17867-17877` |
| 4 | [H-7] "Generate plan" silently discards unsaved events/goals/blackouts | high | quick-win | `web.py:30147-30157` |
| 5 | [H-1] Multi-photo upload silently drops all but the first file | high | quick-win | `mobile-capture.js:148` |
| 6 | [H-2] "Export ZIP" leaves a permanent full-screen "Working on it" overlay | high | quick-win | `web.py:16751` |
| 7 | [H-6] A JSON typo in the site editor throws away all the user's edits | high | quick-win | `web.py:57420-57429` |
| 8 | [E-3] Per-card "Download .zip" exports the headline, not the edited caption | high | moderate | `web.py:31304-31305` |
| 9 | [E-2] Two of three whole-pack exports bundle rejected cards | high | moderate | `web.py:56424-56448` |
| 10 | [G-4] `/organisation` colour pickers are a silent no-op once a palette exists | high | quick-win | `club_profile.py:347-355` |
| 11 | [C-3] Drafts — where all created content lands — unreachable from any nav | high | quick-win | `web.py:13986-14203` |
| 12 | [C-4] Live meet: working page advertised "Coming soon", URL-only | high | quick-win | `web.py:31979-32003` |
| 13 | [C-5] Season wraps: fully built, shown as a disabled "Coming soon" tile | high | quick-win | `web.py:31986-32002` |
| 14 | [E-9] Phone remote "End" is unconfirmed, irreversible, strands the talk | high | quick-win | `web.py:17762` |
| 15 | [C-7] Consent registry & athlete-rights (DSR) pages orphaned, URL-only | high | quick-win | `web.py:25919, 26146` |

---

## Implementation status

**105 of 161 findings shipped** (plus I-4 assessed as already satisfied). Delivered across four merged/merging PRs, each finding as its own commit with a dedicated regression test:

- **PR #1082** (merged) — all of Theme A + the 15-item fix-first shortlist and adjacent high-severity data-safety/discoverability items (23 findings).
- **PR #1085** (merged) — Theme F complete, Theme I complete (bar the I-4 no-op), and the bulk of Theme D feedback/error states (47 findings).
- **PR #1093** (merged) — the remaining high-severity findings plus the owner-decided IA changes: E-4, G-12, B-6, J-2, H-4, H-3, E-1, C-16, G-3, C-1, C-2, C-8, C-13, C-18, and the owner-decided orphans C-14 (sticker/mockup picker) and C-9 (finish Collections) (16 findings). Owner decisions for this batch: customer vocab = "Results"; Developer link on /login only; nav = replace Elements with Activity; Collections = finish; sticker/mockup = wire a picker; brand = /organisation/setup canonical. Pre-merge adversarial review (5 dimensions) confirmed 4 defects (E-1 undo re-insert throw, H-4 badge wipe, C-16 open-redirect, a weak G-3 test) — all fixed.
- **PR #1097** (this branch) — the medium quick-win tail across five themes plus the large high J-1, each with a dedicated regression test: D-10 (Documents/Newsletters AI toggle + busy state + toast, replacing the ambiguous OK/Cancel confirm), E-6 & E-7 (merge-athletes and consent-enforcement confirms with a real impact preview), G-13 (audience autoplay honours the session's configured cadence), G-15 (single demo CTA when signed in), H-21 (board "Add" button + empty-title feedback), H-22 (remote-code client-side validation before it burns a shared-NAT attempt), H-23 (spotlight build disabled with 0 approved), J-5 (export hub links straight to the real export tool), J-7 (channel-preview empty-state escape link), J-10 (Settings "Coming soon" tiles badged), J-13 (console "End presentation"); then **J-1** (the Video Studio's render / make-clip / direct-reel / stabilise now run as disk-backed background jobs the client polls with a branded progress panel) which also resolves **H-19** (the clip button stays disabled for the whole run, and one job maps to one project — no duplicates); and **H-5** (a structured content editor for newsletters / documents — per-section title/text/link fields driven by a per-surface field whitelist, with the raw-JSON textarea kept as the labelled "advanced" hatch); then the contained tail J-12 (offline shell gets a retry + auto-reload + link back), H-8 (a failed free-text build preserves the typed prompt) and E-8 (plain-spoken org-delete confirm + non-owner feedback) (18 findings).

Themes **A**, **F** and **I** are complete. Both large high-severity items (**J-1** background jobs, **H-5** structured editor) are now shipped; remaining work is the medium/low tail across **B** (too-many-steps), **J** (dead-ends), **H** (forms), **G** (consistency), **E** (destructive/data-safety), **C** (discoverability) and **D**.

| Theme | Done | Remaining |
|-------|------|-----------|
| A — First-run & onboarding | 7/7 ✅ | — none — |
| B — Too-many-steps | 1/8 | B-1, B-2, B-3, B-4, B-5, B-7, B-8 |
| C — Discoverability / IA | 13/20 | C-10, C-11, C-12, C-15, C-17, C-19, C-20 |
| D — Feedback & error states | 29/35 | D-11, D-12, D-13, D-15, D-26, D-32 |
| E — Destructive / data-safety | 8/14 | E-5, E-10, E-11, E-12, E-13, E-14 |
| F — Jargon & labels | 14/14 ✅ | — none — |
| G — Consistency | 5/15 | G-1, G-2, G-5, G-6, G-7, G-8, G-9, G-10, G-11, G-14 |
| H — Forms | 12/23 | H-9, H-10, H-11, H-12, H-13, H-14, H-15, H-16, H-17, H-18, H-20 |
| I — Mobile & a11y | 8/9 (+1 N/A) ✅ | — none — |
| J — Dead-ends | 8/16 | J-3, J-4, J-6, J-8, J-9, J-14, J-15, J-16 |

Done findings are marked **✅ DONE (PR #…)** inline on each block below. Everything unmarked is still open.

---

## Findings by theme

Within each theme, most-severe first. IDs are stable references (e.g. B-2).

---

### A. First-run & onboarding breakages

**[A-1] ✅ DONE (PR #1082) — Manual-build setup silently discards the entire form and loops back to setup** — `high` / `quick-win` (confirmed live)
Affects: `/organisation/setup` (Manual build tab)
What the user hits: A volunteer picks "Manual build — I'll pick everything", fills in name, tone, platforms and brand colours, clicks "Create my organisation →", and is returned to the top of the same page on the AI tab with every choice thrown away and no error. The org never becomes usable, so this path can never get them into the product.
Evidence: `web.py:18039-18060` — `_SETUP_EXEMPT_ENDPOINTS` includes `organisation_setup_capture` but NOT `organisation_setup_manual`, so the `_gate_until_org_ready` before_request (`web.py:18436-18494`) intercepts the manual POST and redirects to `/organisation/setup` before the handler (`web.py:42093`) runs; observed live — submit 302'd back with `brand_palette_manual` still `{}` on disk.
Fix: Add `organisation_setup_manual` (and any other setup-page POST endpoints) to `_SETUP_EXEMPT_ENDPOINTS`; add a regression test that a fresh session can complete manual setup end-to-end; make the gate's redirect carry a visible flash whenever it cancels a POST.

**[A-2] ✅ DONE (PR #1082) — AI-build with no links leaves the org "not ready" — every nav click bounces back to setup (silent lockout)** — `high` / `moderate` (confirmed live)
Affects: `/organisation/setup` (AI build)
What the user hits: The copy says "Skip this section entirely… the AI works fine without it", but submitting with only an org name (or when AI capture yields nothing) creates a profile that fails `is_ready()`. The user is bounced back to the identical setup page with no success message and no "what's still missing", and every nav item silently redirects back to this same form — a hard lockout with the only clue being the org chip in the header. (Merges the code-audit twin: "Build my brand" fails completely silently, storing an empty `link_capture_state` and redirecting with no banner.)
Evidence: `web.py:42091` — the capture POST always ends `redirect(url_for("organisation_setup"))`; `web.py:41882-41896` — the `no_sources` branch is `pass` and the error branch only sets `brand_capture_status` + empty `link_capture_state`; `club_profile.py:397-409` — `is_ready()` needs a brand/voice/keywords/guidelines signal a name-only submit never sets; gate at `web.py:18467-18494` keeps redirecting non-ready profiles; observed live — `/make` 302'd back to setup, `/api/notifications` 409'd every 30s.
Fix: After a setup POST render an explicit outcome panel (what was captured, what is still missing to unlock, a working "finish with manual colours" shortcut); never bounce a not-ready user back to an unchanged form; align the "skip the links" copy with what `is_ready()` actually requires (or make a name-only org ready with a default palette). Reuse the existing per-status hint strings at `web.py:41080-41087`.

**[A-3] ✅ DONE (PR #1082) — Caption tone buttons fail on a missing CSRF token and render a silently empty caption** — `high` / `quick-win` (confirmed live)
Affects: `/pack/<run_id>` (content builder)
What the user hits: The core "pick a caption" action is broken. Clicking Warm/Hype/Precise fires a POST the server rejects with 403 (CSRF); the UI's response handler doesn't recognise the error shape, so the "Click to generate…" placeholder is replaced with nothing — button highlights, empty space, no caption, no error, no retry hint. Independent of whether an AI key is set, so it breaks in production too.
Evidence: `web.py:4235` — `_fetchCaption` does `fetch(captionUrl+'?tone=…',{method:'POST'})` with no `X-CSRF-Token` header/JSON content-type; `web.py:17867-17877` rejects it `{"error":"csrf"}` 403; the handler's only error branches (`web.py:4245-4266`) key on `j.error==='transient'` or `j.live===false`, so a csrf error falls through to render `variants=['']` (`web.py:4271-4284`); observed live — console 403, blank caption area.
Fix: Send the CSRF token on this fetch (header or the JSON content-type exemption); add a catch-all error branch in `_fetchCaption` that shows a styled "Couldn't generate — try again" message for any non-ok/unknown JSON instead of rendering an empty caption.

**[A-4] ✅ DONE (PR #1082) — First-run routing bounces new signups through the org gate to a false "no organisations" empty-state** — `high` / `moderate`
Affects: `/signup` → `/make` → `/sign-in` / `/organisation/setup`
What the user hits: `signup_post` redirects to `/make`, but `make_page` isn't gate-exempt, so the gate immediately re-redirects — to `/sign-in` when any profile exists on the deployment (the multi-tenant reality), where the new user reads "No organisation profiles exist on this deployment yet" (factually wrong on a shared deployment, and jargon). No `next` param is carried, so nothing returns them to their task. Measured 6–7 screens / ~8+ clicks before a first upload, and the promised "Create" landing page is never actually shown.
Evidence: `web.py:36614-36615` redirects signup to `make_page`, absent from `_SETUP_EXEMPT_ENDPOINTS`; gate at `web.py:18492-18494` redirects with no `next`; `sign_in_page` filters by membership yet renders "No organisation profiles exist on this deployment yet" whenever the filtered list is empty (`web.py:38616-38623`).
Fix: Send brand-new signups straight to `/organisation/setup` with a "Step 1 of 2 — tell us about your club" framing, skipping the `/make` → gate → `/sign-in` bounce; fix the empty-state copy to "You don't have access to any organisations yet"; make the gate preserve `?next=` so finishing setup resumes the task.

**[A-5] ✅ DONE (PR #1082) — Two auth systems with colliding names ("Log in" vs "Sign in") shown together — and Sign up/Log in shown while a workspace is active** — `high` / `moderate` (confirmed live)
Affects: global nav, `/login`, `/sign-in`
What the user hits: `/login` (account + password, "Log in/Log out") and `/sign-in` (org picker, no password, "Sign in/Sign out/Switch organisation") are different concepts with near-identical names, and the nav shows both vocabularies at once — an account user with no pinned org sees "Sign in" AND "Log out" together; a fully signed-in user sees the org chip + bell AND "Sign up"/"Log in". Clicking "Log out" meaning "switch club" ends the whole session (a plain GET, no confirm); clicking "Sign out" meaning "log out" leaves the account alive.
Evidence: `web.py:14014` renders `nav.sign_in`→`/sign-in` inside the not-signed-in block while `web.py:14019-14021` renders "Log out"→`logout` for any `account_email`, so both appear together; `web.py:14105-14107` puts "Switch organisation" + "Sign out" in the account menu while "Log out" stays in the top bar; standalone branch `web.py:14022-14024` shows "Sign up"/"Log in" to an org-signed-in user; labels at `ui_catalogue.py:31-33`; observed live post-setup: org chip + bell alongside Sign up/Log in.
Fix: Adopt one vocabulary — keep "Log in/Log out" exclusively for the account session; rename `/sign-in` to "Choose / Switch organisation" everywhere (page, hero, buttons, `nav.sign_in`) and `/sign-out`'s action to "Leave organisation". Never show "Sign in" and "Log out" in the same nav state; when a workspace is active, replace Sign up/Log in with a single account state ("Save your workspace — create an account").

**[A-6] ✅ DONE (PR #1082) — Org session silently expires after 30 idle minutes; re-entry loses the destination and dumps the user on home** — `medium` / `moderate`
Affects: `/sign-in` (re-entry loop)
What the user hits: The org pin drops after 30 minutes' inactivity while the account session survives, so a volunteer returning after lunch opens a deep link to a run/review page, gets bounced to the org picker, picks their club — and lands on home, not the page they opened. Every re-entry costs 2–3 extra clicks plus re-navigation, and it recurs because the timeout is per-30-minutes.
Evidence: `web.py:18220-18223` sets `_LOGIN_IDLE_SECONDS` and `web.py:18369-18375` pops `active_profile_id` when exceeded; gate redirects with no `next` (`web.py:18492-18494`); `sign_in_post` unconditionally `redirect(url_for('home'))` (`web.py:38818`).
Fix: Thread the originally-requested path through the bounce (gate → `/sign-in?next=…` → `sign_in_post` redirects to `next` after pinning); consider lengthening the idle window or auto-re-pinning when the account has exactly one accessible org.

**[A-7] ✅ DONE (PR #1082) — Setup form: the AI/Manual tab choice resets on every round-trip, and an orphaned asterisk has no legend** — `low` / `quick-win` (confirmed live)
Affects: `/organisation/setup`
What the user hits: The AI/Manual toggle is a pure client-side display switch, so every failed submit or reload flips the user back to the AI tab — compounding A-1 (the volunteer can't even see the tab where their discarded manual choices lived). A lone "*" renders at the bottom with no "required fields" legend.
Evidence: `web.py:41485-41495` — `mhSetupMode()` only toggles `style.display`/`aria-selected`, nothing persists the mode across the POST/redirect; observed live — page reopened on AI tab after a manual submit, with a bare "*" text node after the submit row.
Fix: Persist the chosen setup mode (query param or `sessionStorage`) so redirects/reloads reopen the tab the user was working in; attach the asterisk to a proper "* required" legend (or drop it).

---

### B. Too many steps / too many buttons (feature sprawl)

**[B-1] Mandatory "how it works" interstitial on every Create flow, every visit — with wrong format guidance** — `medium` / `quick-win` (confirmed live)
Affects: `/make`, `/make/<ct>` (all Create tiles; Plan pays it twice) — merges the home-nav, upload-flow, make-hub and live-walkthrough reports
What the user hits: Every implemented Create tile links to an explainer slide whose only forward action is "Start <type>"; there is no skip, no "don't show again", and no direct path. A volunteer who uploads results every week re-reads the slide on every visit, turning the nav→upload journey into 7 clicks across 5 pages vs 4 from `/upload`. The Meet Recap slide's step 1 even says "Upload your Hytek results file (.hy3) or a zip" while `/upload` accepts PDF, CSV, Excel, SDIF and HTML — a volunteer holding a PDF may conclude at the interstitial that MediaHub can't help them.
Evidence: `web.py:31737` sets every live tile's href to `content_type_intro` unconditionally; `content_intro.py:460-463,510` render only a "Start"/"Back to Create" CTA with no skip; the `content_type_intro` route (`web.py:32092-32138`) has no seen/skip check; the Plan slug also routes through the intro (`web.py:32104-32112`), duplicating the "Open Plan" CTA; observed live — Meet Recap intro lists only `.hy3`/zip.
Fix: Link tiles directly to `meta.primary_route_endpoint` (show the intro only until the org has completed one run of that type, remembered in session/profile), keep a small "How it works" affordance on the tile and destination page, and fix the intro copy to list every accepted format.

**[B-2] Content builder / pack: six-plus overlapping export & download actions with no clear primary** — `medium` / `moderate` (confirmed live)
Affects: `/pack/<run_id>` — merges the pack-export "five-button row" finding and the live-walkthrough "six export actions" finding
What the user hits: For a single approved card the page shows a per-card "⬇ Download .zip", "Download every format + manifest (.zip)", "Download all visuals (.zip)", "Bulk export & convert…", "Print & merch…" and "Print / Export PDF" — plus four newsletter links and two certificate links: ~12 download affordances on one screen. The first two ZIPs differ only in internal folder layout and a `metadata.json` ("manifest" is engineering vocabulary). A volunteer who just wants "the Instagram post" cannot tell which is right; the per-card ZIP even downloads a 622-byte empty file when nothing is rendered.
Evidence: `web.py:43342-43353` — the five-button row; `web.py:56586` docstring has to explain how `export.zip` is "Distinct from content_pack_zip"; `_export_disabled_attr` applied only to the two ZIP links, not the live "Bulk export…" link; observed live at `/pack/72e6f888f1e5` — 6 export actions + 4 newsletter + 2 certificate links for one card.
Fix: Collapse to one primary "Download post (graphic + caption)" per card and a single "Export pack (N approved cards)…" disclosure holding all-formats/convert/print/certificates/newsletter; disable the per-card ZIP until it contains a rendered asset; put every pack-level export under the same rendered-count gate.

**[B-3] `/pack`, `/pack/grouped` and `/review` are three overlapping views with duplicated controls** — `medium` / `large`
Affects: `/pack/<run_id>/grouped`
What the user hits: The grouped "All recommendations" page repeats the builder's newsletter card verbatim (4 buttons), carries its own second reel UI without the builder's composer, and re-renders approve/reject straps that also live on `/review`. A volunteer bounces between "Back to review", "Content builder →" and "All recommendations" with no clear model of which page does what, and every duplicated control is another button to misunderstand.
Evidence: `web.py:45042-45053` duplicates the newsletter block from `43293-43312`; `web.py:45032-45039` is a second reel UI without the composer at `43074-43100`; `_render_wf_actions` at `44907` duplicates the review queue's role.
Fix: Make each page single-purpose — review = triage only, `/pack` = create + export; demote `/pack/grouped` to a read-only "explore all recommendations" view (remove its newsletter/reel/approve duplicates; link to the builder).

**[B-4] Each review card row carries ~9–13 interactive controls around the one decision that matters** — `medium` / `moderate`
Affects: `/review/<run_id>`
What the user hits: A single row renders a checkbox, Approve, Re-queue (always rendered, dimmed-not-hidden even when it does nothing), Inspect, three emoji reactions, a "Why this card?" disclosure (Copy reasoning + Use in next caption), and a "ranking & evidence" disclosure (View full trace JSON) — plus Download once approved. The owner's "too many buttons" instinct is measurably true on the money screen.
Evidence: `web.py:22532-22582` — the row template; Re-queue always rendered via `_disabled_attrs` (`3566-3571`); reaction buttons always rendered (`3690-3701`, only the count span is hidden).
Fix: Slim the default row to Approve + Inspect + the Why disclosure; render Re-queue only on approved/rejected/edited cards; fold reactions and the trace link behind the evidence disclosure (or drop reactions from triage); show the checkbox only in a select/hover mode.

**[B-5] Getting all four motion cuts of one card takes four separate renders — the reel has a one-click batch, per-card motion doesn't** — `medium` / `moderate`
Affects: `/pack/<run_id>`
What the user hits: The reel composer offers "All 4 formats" (one click, one job). A single card's motion only offers per-format chips: to hand a volunteer story + portrait + square + landscape they click Story, wait up to 90s, then click each remaining chip and wait again — ~4 clicks and 4–6 minutes of babysitting per card, multiplied across a pack.
Evidence: `web.py:4853-4866` — `_motionFmtChips` emits one `generateMotion` button per format, no batch; `web.py:53215-53230` — the reel-batch route exists but no motion-batch equivalent (repo grep for "motion-batch" is empty).
Fix: Add a per-card "All 4 formats" button backed by a motion-batch job (mirror `api_run_reel_batch` over the existing motion job store) and surface per-cut progress in the motion panel.

**[B-6] Chat flow's "Accept & generate" button does not generate anything** — `high` / `moderate`
Affects: `/free-text/chat/<chat_id>`
What the user hits: After refining a brief in chat the user clicks "Accept & generate" — but the handler only marks the brief accepted and reloads; they must then find a second "Generate content from this brief →" button, and even then land on the draft with no graphic rendered (a third "Create graphic" click + wait). The quick path auto-renders (`?autographic=1`); the chat path, positioned as the richer option, quietly requires 3 extra undirected steps and a mislabelled button.
Evidence: `web.py:33701` button "Accept & generate"; `free_text_chat_accept` (`33817-33835`) only sets `accepted_brief` and redirects; `free_text_chat_generate` (`33914`) redirects to the pack with NO `?autographic=1`, unlike the quick path (`33589`).
Fix: Make "Accept & generate" actually run generation (merge accept+generate into one POST) and redirect with `?autographic=1` so the chat path ends with a rendered graphic; if two steps must stay, relabel the first "Accept brief".

**[B-7] Setting consent is one athlete at a time with a full page reload each save** — `medium` / `moderate`
Affects: `/athletes`
What the user hits: Each roster row is its own mini-form (permission dropdown + Save) that POSTs and reloads the whole page, losing scroll. For a 200-swimmer club there is no in-roster bulk edit — reviewing consent means up to 200 individual submits and reloads, or falling back to a single opaque CSV textarea. This makes ongoing consent maintenance impractical for exactly the clubs the feature targets.
Evidence: `web.py:57919-57924` per-row `<form method="POST">`; `58016-58021` handles a single `set_consent`; `58052` redirects back to the full page (no AJAX).
Fix: Save consent changes inline via `fetch` (like the run-delete rows already do), or add a "save all changed rows" / "apply to selected" control so a club can process the roster in one pass.

**[B-8] Pairing a presenter phone requires hand-typing a URL + 6-char code — no QR to scan** — `medium` / `moderate`
Affects: `/documents/<id>/present`
What the user hits: The console tells the presenter to read out the pairing details, but the remote URL is shown as static bold text (not even a link) and there is no QR. A poolside volunteer must type the full host URL, tap Go, type the 6-character code and tap Connect across two screens (~30 hand-typed characters).
Evidence: `web.py:17679` renders "Open **__REMOTE_URL__**" as bold text (not an `<a>`); no QR anywhere in `_DOC_PRESENT_CONSOLE` (`17662-17716`).
Fix: Render a QR encoding `/remote/<code>` (deep-link, no code typing) plus a tappable fallback link.

---

### C. Discoverability & information architecture

**[C-1] Pending/in-flight review work is not reachable from home or the nav — no "resume where you left off"** — `medium` / `moderate` (confirmed live)
Affects: `/` (signed-in home), global nav — merges the home-nav "no recent work" finding and the live-walkthrough "pending review unreachable" finding
What the user hits: The most common return visit — "finish approving the pack I started" — gets no help. The signed-in home is a static hero + six fixed tiles + a CTA strip with no recent runs, no "pack awaiting review (N cards)", no resume link; the top nav has no Review/Runs item. The volunteer who closes the tab mid-review must go Home → All activity → find run → reopen review (3+ clicks), while "Elements" (a sticker gallery) holds a nav slot.
Evidence: `web.py:18792-18801` assembles the home from hero + `_home_signed_in_quick_actions_html()` + CTA only; the quick-action grid (`17454-17519`) is six static tiles with no run data; observed live — hero shows odometer stats but no "Continue reviewing…" link.
Fix: Add a "Pick up where you left off" strip to the signed-in home: the latest 1–3 runs with status and queue count, each linking straight into `/review/<id>` (the query `/activity` already runs, limited to 3); consider swapping the Elements nav slot for a Review/Activity item.

**[C-2] Top-nav slots don't match volunteer priorities, and mobile disagrees with desktop** — `medium` / `moderate`
Affects: desktop nav / mobile bottom nav
What the user hits: The desktop nav spends a slot on "Elements" (browse-only from the nav) while Activity (where reviews resume), Plan and Drafts have no desktop item; the mobile bottom nav promotes Activity as one of four items — so the two navigation systems disagree about what's primary. Keyboard shortcuts (`g p`, `g a`) expose destinations the visible nav never surfaces.
Evidence: `web.py:13998` gives Elements a top-nav slot; desktop nav (`13986-14000`) = Home/Create/Media/Elements/My Season(+Research), no Activity; mobile bottom nav (`14195-14197`) makes Activity one of four; `elements_page` docstring (`48174`) confirms add-to-card needs `?run_id&card_id`.
Fix: Align both navs around the volunteer's loop (Create, Activity/Review, Media, Season); demote Elements to a Create-page tile or the card editor where its add-to-card mode works, and give Activity the freed desktop slot.

**[C-3] ✅ DONE (PR #1082) — Saved Drafts — where all created content lands — is unreachable from any navigation** — `high` / `quick-win`
Affects: `/drafts` — merges the home-nav and make-drafts findings
What the user hits: Every free-text, event-preview, sponsor and spotlight output is saved as a draft under `/drafts`, but a volunteer who closes the tab cannot find their work again: no Drafts link in the desktop nav, mobile nav, home, or the Create hub. The only inbound links are small footer links on the generation pages themselves, so returning users plausibly conclude the draft was lost.
Evidence: nav (`13986-14029`) and mobile nav (`14186-14203`) have no Drafts; `/make` body (`32077-32087`) has none; every `url_for("stub_packs_list")` inbound link (`33242`, `33275`, spotlight strap `13439-13440`) is a small footer link on a stub page.
Fix: Add a persistent "Drafts" entry (with count) to the Create hub top strip and the primary/account nav; link each draft-generating success toast back to it; surface drafts under the Create tab on mobile.

**[C-4] ✅ DONE (PR #1082) — Working club-data tools (athletes & consent, records, data hub, ask-the-data) are filed 3–4 clicks deep under Settings, absent from the nav** — `high` / `moderate`
Affects: `/athletes`, `/records`, `/data-hub`, `/qa` — merges the home-nav and data-surfaces findings
What the user hits: A volunteer's mandatory safeguarding job (set photo/name consent per swimmer, keep the register) is hidden under Settings → Privacy, and records/data-hub under Settings → Club data (4 clicks). None appear in the top or mobile nav, so a time-poor committee member has no way to discover MediaHub even tracks consent or records. A volunteer looking for "our records" or "our swimmers" won't think to open Settings.
Evidence: top nav (`13986-14000`) lists only Home/Create/Media/Elements/My Season(+Research); `_render_settings_clubdata_section` (`29195-29227`) is the sole home for `club_records_page`/`club_qa_console`/`data_hub_page`; the only "Manage athletes & consent" link (`29321`) is inside `_render_settings_privacy_section`.
Fix: Promote a first-class "Club data" (records, athletes & consent, data hub, ask-the-data) surface — a home quick-action tile or a top-nav item (e.g. in place of Elements) — and keep only genuine configuration under Settings.

**[C-5] ✅ DONE (PR #1082) — Live meet mode is a working page advertised as "Coming soon" and unreachable except by URL** — `high` / `quick-win`
Affects: `/make`, `/live` — merges the home-nav and data-surfaces findings
What the user hits: A volunteer covering a gala sees a greyed-out "Live meet — Coming soon" tile on Create (the only mention) and concludes the feature doesn't exist — yet `/live` is a complete working page (paste a live-results URL, start a watch, get cards queued during the meet). The UI actively contradicts reality.
Evidence: `web.py:31979-32003` renders "Live meet" as a hardcoded disabled tile with a "Coming soon" tag, while `58182-58250` serves the full working page; a whole-src grep for `live_meet_page`/`/live` returns only the route def and its own redirect — no nav/tile/`url_for` links it.
Fix: Replace the disabled tile with a live tile pointing at `url_for('live_meet_page')` (with a "Ready" badge), or if deliberately unlaunched, gate/remove the route so UI and reality agree.

**[C-6] ✅ DONE (PR #1082) — Season wraps is fully built but shown as a disabled "Coming soon" tile — the page is orphaned** — `high` / `quick-win`
Affects: `/wraps`
What the user hits: `/wraps` is complete (draft last month's wrap, season wrap since 1 Sept, monthly auto-draft toggle, drafts table), but the Create hub renders "Season wraps" as a disabled tile with a "Coming soon" badge and `href='#'`. A volunteer wanting a month-in-numbers poster is told the feature doesn't exist when it does.
Evidence: `web.py:31986-32002` renders the disabled tile; `58306-58369` is the full working `season_wraps_page`; the only reference besides the route def is its own POST redirect (`58430`) — zero inbound links.
Fix: Flip the tile to live and link `url_for('season_wraps_page')` (gated on the same availability check), or if deliberately unlaunched, remove the route so the tile isn't lying either way.

**[C-7] ✅ DONE (PR #1082) — Consent registry & athlete-rights (DSR) pages are orphans — unreachable from any nav, footer, or Settings link** — `high` / `quick-win`
Affects: `/organisation/consent`, `/organisation/athlete-rights`
What the user hits: The two pages a safeguarding officer needs most — recording a parent's consent (grant/refuse/revoke, lawful basis, child controls, retention) and logging a deadline-tracked "delete/export my child's data" request — can only be opened by typing the URL. Nothing in the nav, footer, or the Settings "Privacy & data" section points to them, so in practice they're unreachable.
Evidence: `web.py:25919` and `26146` define the routes; a repo-wide grep shows they appear only as route defs and redirect targets, never as a navigational `<a href>`; the Settings privacy card (`29315-29322`) links solely to `athletes_page`.
Fix: Add "Consent & lawful basis" and "Athlete data requests" cards to Settings → Privacy & data and to the `/privacy` hub, so both are reachable in one or two clicks.

**[C-8] The public achievements wall is effectively orphaned — its only entry link is prose buried in Organisation settings** — `medium` / `quick-win`
Affects: `/public-wall`
What the user hits: The wall is a flagship shareable output (free public celebration page, embed, RSS/JSON), yet the only link to it anywhere is a sentence halfway down the long Organisation settings page: "Manage it on the public wall page." It's not in the nav, not a Create tile (where Newsletters/Documents both have tiles), not on Home. Reaching it takes account → Settings → Organisation → scroll → prose link.
Evidence: `web.py:36175` — the sole `public_wall_settings` href sits in Organisation-page prose; the Create page builds first-class tiles for Documents/Newsletters but none for the wall (`31882-31958`); the wall page even highlights "Home" in the nav (`49761`).
Fix: Give the wall a Create-page tile alongside Newsletters/Documents, link it from the review/export flow ("share these approved cards publicly"), and set a correct active-nav state.

**[C-9] `/collections` is a fully working page with zero inbound links and no way to fill it** — `medium` / `large`
Affects: `/collections` — merges the home-nav and pack-export findings
What the user hits: The Collections page (create/delete folders grouping meets and packs) can only be reached by typing the URL. Anyone who stumbles in can create folders they can't find again, and no page offers an "Add to collection" action, so every collection stays at "0 items" forever — the create/delete effort is wasted.
Evidence: a whole-repo grep for `url_for("collections_page")` returns only the route def (`55052-55053`); rows render name+count+Delete only, not clickable (`55062-55077`); `add_item` (`55026-55029`) has no UI caller anywhere.
Fix: Either finish it (nav/My-Season entry, "Add to collection" on run rows, clickable contents) or remove the page and its APIs until the feature is real.

**[C-10] Athlete Spotlight is buried (Review view-switch only) and silently limited to meets from the last 31 days** — `medium` / `quick-win`
Affects: `/spotlight`
What the user hits: Spotlight has no Create tile (reachable only via the Review page's view switch or URL), and its meet picker filters runs to the last 31 days. A volunteer wanting a "swimmer of the season" post about a meet from six weeks ago finds it absent from the dropdown with only a muted "Showing meets from the last month" hint — the run still works via a direct URL.
Evidence: `web.py:31704-31709` removes the spotlight tile (`_hidden_cts`); `32457` computes a 31-day cutoff applied in the runs query (`32462-32477`); the only hint is the muted caption at `32620`.
Fix: Drop or extend the cutoff (or add a "Show older meets" toggle) and surface Spotlight as a Create tile or an explicit link on each processed meet in Activity.

**[C-11] Half-hidden content types (Sponsor Post, Session Update) are unreachable for new users but still referenced everywhere; Free Text exists twice** — `medium` / `moderate`
Affects: `/make`, `/drafts`, `/sponsor-post`, `/session-update`
What the user hits: Those tiles were removed from Create ("Free Text now interprets any such prompt"), yet the routes remain live and the UI keeps pointing at them: the Drafts empty state names them, draft rows show those labels, and "Generate new draft" on an old sponsor pack links back into the hidden form. Free Text itself exists twice (chat landing + a "legacy quick generator" link), so a volunteer sees three overlapping describe-it paths and two invisible form paths.
Evidence: `web.py:31709` `_hidden_cts`; live routes at `33358`/`33362`; drafts empty state (`33976-33980`); regenerate mapping back into the hidden forms (`34096-34105`); "legacy quick generator →" (`33479-33483`).
Fix: Pick one story — either retire the hidden forms (redirect to `/free-text` with a prefilled hint, update the empty-state copy) or restore them as tiles; fold the "legacy quick" page away since the chat landing already embeds the same one-shot form.

**[C-12] Top-nav "Elements" is a look-don't-touch dead end from the nav, while the useful Stock browser is buried behind it** — `medium` / `moderate`
Affects: `/elements`, `/stock`
What the user hits: Elements holds one of five core nav slots, but opened from the nav (no `?run_id&card_id`) every element is display-only — the "Add to card" button is omitted, with no CTA or explanation. The Stock browser (the tool that actually gets a club usable photos) is reachable only via one "Browse stock photos →" link on the Elements page, and is invisible from the Media library where a volunteer would look.
Evidence: `elements_browser.py:167-169` omits "Add to card" outside card context; `web.py:48211` is the sole `stock_page` reference; add-to-card toast "Added — re-render the card to see it" (`elements_browser.py:214`) doesn't link back.
Fix: When Elements is opened without a card, show a hero explaining where elements appear plus a CTA into the card flow; add a "Find stock photos" entry on the Media library (or swap Stock into the Elements nav slot); make the add toast link back to the card.

**[C-13] Media library is missing from the mobile bottom nav despite being the designed poolside surface** — `medium` / `quick-win`
Affects: `/media-library` (mobile nav)
What the user hits: The mobile bottom nav is Home/Create/Activity/Settings only. Yet the media library is the surface built for phones — camera capture, the PWA share-target, upload copy that says "take a photo or share one straight from your camera roll". A poolside volunteer must open the hamburger to reach the one page designed for their phone-in-hand moment.
Evidence: `web.py:14186-14203` — the bottom nav contains exactly Home/Create/Activity/Settings; mobile-first upload copy (`45656`); `/share-target` redirects onto the library (`46128-46180`).
Fix: Add Media library (camera icon) to the mobile bottom nav, or swap it in for Settings (already in the account menu).

**[C-14] Sticker and mockup features are orphans; the one mockup link dead-ends in raw JSON** — `medium` / `moderate`
Affects: `/media-library/generated`
What the user hits: The make-sticker API has zero UI callers (unreachable). The mockup picker endpoint is unconsumed; the only mockup affordance is a hardcoded "Poster mockup" anchor that points a new browser tab straight at the API route — on any failure the volunteer's tab shows raw JSON like `{"error":"mockups_unavailable"}` with no styling or way back.
Evidence: `web.py:48494` — `api_make_sticker`'s only reference is its own route def; `46761-46763` — the templates endpoint has no UI consumer; `46870` — the anchor links directly to a route returning `jsonify` errors (`46809`, `46817-46819`).
Fix: Either wire a real sticker/mockup picker into the library/cut-out page (using the existing templates endpoint) or remove the orphan routes; render mockups in-page with a styled failure state.

**[C-15] Five planner sub-views with no shared navigation — Board and Grid are hidden behind the calendar** — `medium` / `quick-win`
Affects: `/plan` and its sub-views
What the user hits: The planner is five pages, each linking to a different arbitrary subset: `/plan` offers only Calendar + Performance; Board and Grid are reachable only from calendar-toolbar buttons; analytics links back only to `/plan`. A volunteer on the ranked plan never learns Board/Grid exist. It reads as five stitched pages, not one tool.
Evidence: `web.py:29938-29939`, `30402-30404`, `30691`, `30850`, `31065` — the ad-hoc per-page link subsets.
Fix: Render one shared sub-nav strip (Plan · Calendar · Board · Grid · Performance) with an active state on all five pages, replacing the per-page links.

**[C-16] Interface language can only be changed by hand-typing `?lang=`, and it pins with no off-ramp** — `high` / `moderate`
Affects: global chrome, `/settings` — merges the two localization discoverability findings
What the user hits: MediaHub ships a real Welsh interface layer, but a volunteer has no deliberate way to turn it on: no interface-language control in the nav, footer, account menu, or Settings. The only deliberate control is typing `?lang=cy` onto a URL, which then pins to the session with no visible way back to English (you'd have to know to type `?lang=en`). The one Settings picker is labelled "Caption language" and reads as caption output.
Evidence: `web.py:13511-13554` — `_ui_locale()` reads only `?lang=`, a session pin, or the caption-language fallback; no route sets the UI locale from a click; nav (`13986-14111`) has no language control; the sole picker (`36055-36056`) is "Caption language"; the pin is written at `13532` and re-read at `13539-13541` with no clear/display.
Fix: Add a visible interface-language switcher (account/org dropdown + Settings) populated from `available_ui_locales()`, POSTing to a route that sets `session['ui_lang']`; English is always an option (the off-ramp); label the existing control "Caption language" vs a new "Interface language".

**[C-17] Reel AI-dub language is also URL-only, and an unsupported language dead-ends in raw JSON** — `low` / `moderate`
Affects: reel export (`POST /api/runs/<id>/reel?lang=`)
What the user hits: Reel narration dubbing is reachable only by appending `?lang=` to the render request — no dub-language picker exists, so the shipped capability is undiscoverable, and a bad `?lang=` returns a bare 400 JSON with no styled path, so the reel simply fails to appear.
Evidence: `web.py:52643` reads the dub language only from `request.args.get('lang')`; undubbable language returns `jsonify({'error':'bad_language'})` 400 (`52656-52664`); the reel-generate JS (`5081-5085`) sends only format + composer.
Fix: If dubbing is supported, add a dub-language selector (reusing the caption-language registry) with an inline styled error; otherwise keep it operator-only and documented.

**[C-18] Present and Slide-remote surfaces have no nav entry — the remote is discoverable only by typing `/remote`** — `low` / `quick-win`
Affects: `/remote`, `/documents/<id>/present`
What the user hits: Neither the presenter surface nor the slide remote appears in any nav. Present is at least a button on a deck's document page, but `/remote` is reachable only by typing the URL — a volunteer who missed the on-screen instruction has no in-app path to it.
Evidence: `web.py:60056` defines `/remote` wrapped with `active='create'` but no nav item links it; the only Present entry is a button on the document page (`59636`).
Fix: Add a "Slide remote" / "Present" shortcut to the account/tools menu so a phone user can reach the pairing screen without knowing the URL.

**[C-19] Settings landing is a flat wall of 17 undifferentiated tiles with overlapping twins** — `medium` / `moderate` (confirmed live)
Affects: `/settings` — merges the settings-status and live-walkthrough findings
What the user hits: A signed-in user sees 17 equal-weight tiles (18 for operators) in one flat grid with no grouping or ordering: "Organisation & brand" sits apart from "Brand platform"; "Billing & plan" next to "Pricing & plans". Reaching the right one of ~5 settings that matter takes 3 clicks when guessed right and 5+ when the wrong twin opens first. The hero even titles the page "Operations & data".
Evidence: `web.py:27924-28057` — `_settings_card_specs` emits 17/18 tiles while its docstring still claims 12; overlapping tiles at `27933-27945` and `28003-28020`; hero H1 "Operations & data" (`28079`); observed live — 17 tiles listed.
Fix: Group the grid under 3–4 headed clusters (Your club / Content / Account & billing / System); merge or clearly differentiate the two brand tiles and the billing/pricing pair; demote status/governance/coming-soon items to a compact bottom row.

**[C-20] The Create page presents three competing "start here" prompts** — `low` / `quick-win` (confirmed live)
Affects: `/make`
What the user hits: A first-time user sees a full-width "Plan · Start here" hero, a "START HERE" ribbon on the Meet Recap tile, and a "Generate a sample pack →" card — all at once among ~12 tiles. Two elements literally labelled "start here" point at different destinations, so the one decision the page exists to support (where do I begin?) is ambiguous.
Evidence: observed live — "Plan · Start here" hero and "START HERE" ribbon on Meet Recap render simultaneously; `web.py:31739-31741` gives the first implemented tile the primary ribbon independent of the Plan hero above it.
Fix: Keep exactly one "Start here" affordance (Meet Recap for this audience); relabel the Plan hero to something distinct ("Not sure what to post? Plan it").

---

### D. Feedback, loading & error states

**[D-1] ✅ DONE (PR #1085) — Blocked approvals surface raw error codes and wrong "try again" advice, with no path to resolve the block** — `high` / `moderate`
Affects: `/review/<run_id>`
What the user hits: When an approval is refused by the consent gate, brand lock, or an open review task, the volunteer sees "Workflow update failed: consent_blocked" (or `brand_locked`/`tasks_open`) plus a contradictory "Could not save — reverted. Try again." — retrying a permanent safeguarding block. The server actually sends a plain-English reason the JS never reads, and the tasks UI that could clear the block only exists on the Content builder, so from review there is no way to resolve it.
Evidence: `web.py:15485` — `mhWorkflowSet` builds the toast from `o.body.error||o.body.message`, never `o.body.reason`, while the server returns `{error:…, reason:<human text>}` at `43472/43479/43486`; the generic catch toasts at `15559-15566`; the comments/tasks panel is mounted only in the builder (`6521`).
Fix: Prefer `o.body.reason` over the error code; suppress the generic "Try again" toast for 4xx gate responses; for `tasks_open` add an affordance to view/resolve the card's tasks from review (or deep-link to the builder card).

**[D-2] ✅ DONE (PR #1085) — "Approve all in queue" fires one POST and one toast per card instead of using the existing bulk endpoint** — `high` / `moderate`
Affects: `/review/<run_id>`
What the user hits: "Approve all in queue" simulates a click on every queued card. On the 150–250 card meets the code itself calls typical, that launches 150+ fetches at once and stacks up to 150 success toasts (unbounded), with no aggregate progress and no failure summary — any card that fails reverts silently in the pile. A single-request bulk API that returns per-card gate results already exists and is used by the neighbouring bulk bar.
Evidence: `web.py:23184-23188` — `queued.forEach(... btn.click())`; each click toasts (`15549-15557`); `MH.toast` appends unboundedly (`14563-14576`); `api_cards_bulk_status` (`43563`) + `afterReview()` (`16704-16729`) already do it in one request.
Fix: Make "Approve all in queue" collect the queued ids and POST once to `api_cards_bulk_status`, repaint rows from the results, and show one summary toast ("Approved 148, 2 blocked (consent)").

**[D-3] ✅ DONE (PR #1085) — Single-card approve shows "Approved ✓" even when the server held the card for another approver** — `medium` / `quick-win`
Affects: `/review/<run_id>`
What the user hits: With a group-approver rule, approving records a vote and returns `ok:true, status:'queue'` (held). The per-card handler never reads the returned status, so the optimistic paint stands (button flips to "Approved ✓", toast "Marked as approved", card moves to Approved) — then silently reverts to the queue on next reload. The bulk-bar path handles the same response correctly, so the two paths disagree about the truth.
Evidence: `web.py:15549-15558` checks only `result.queued`, never `result.status`; server returns `{ok:true,status:'queue'}` for a held card (`43490-43493`); the bulk handler groups by `r.status` (`16708-16717`).
Fix: In the success handler call `paintState(result.status||status)` and, when the returned status differs from requested, toast the held-for-approval detail the API already returns.

**[D-4] ✅ DONE (PR #1085) — Offline-queued approvals replay silently, discarding every server rejection or hold — the pill then lies "All changes synced"** — `high` / `moderate`
Affects: review queue (offline replay via `/sw.js`)
What the user hits: A volunteer approves cards poolside with no signal. On reconnect the service worker replays each queued approval and deletes the entry on ANY response below 500 — including a 403 consent/brand/task block or a 200 "held for another approver" vote. The volunteer is never told the card was blocked or is still pending; the "N changes waiting" pill just flips to "All changes synced". Their approval intent is silently lost.
Evidence: `web.py:26719` — `if (res && res.status < 500) { await idbDelete(it.id); }` drops the entry on 4xx too; server returns 403 (`43472/43479/43486`) and `{ok:true,status:'queue'}` (`43493`), yet the SW comment claims replay "is always safe" (`26625-26626`); `offline-queue.js:37` shows "All changes synced".
Fix: Treat only true successes as drainable — on replay inspect the JSON body (`ok:false`/`error`/`status!=='approved'`) and on a 4xx or held result keep a record and surface it ("X approvals couldn't be saved (consent/brand/another approver) — review needed") instead of blindly deleting and reporting success.

**[D-5] ✅ DONE (PR #1085) — On iOS, offline approvals never replay if the app is reopened while already online — stranded with no manual retry** — `high` / `moderate`
Affects: review queue (offline queue) on iOS Safari
What the user hits: iOS has no Background Sync, so replay depends on a JS nudge that only fires on an offline→online transition. On load the client only asks for the queue count, never triggers a replay, and there's no "Sync now" control. A volunteer who approves offline, locks the phone, then reopens the installed app at home (already online) sees "N changes waiting to sync" while their approvals sit in IndexedDB until the connection happens to drop and return.
Evidence: `offline-queue.js:61-65` only pings for count on load; the only replay nudge is the `window 'online'` listener (`69-70`); the SW replays solely on `sync` (`web.py:26757`, absent on iOS) or a `mediahub-queue-replay` message (`26768-26769`).
Fix: On `serviceWorker.ready` (and when queue count > 0 while `navigator.onLine`) post `mediahub-queue-replay` to drain immediately; add a tappable "Sync now" on the pending pill.

**[D-6] ✅ DONE (PR #1085) — A failed pipeline run forces a full re-upload and leaks the raw internal error on refresh** — `high` / `moderate`
Affects: `/runs/<run_id>` — merges the "forced re-upload" and "raw error on refresh" findings
What the user hits: When the pipeline errors, both failure surfaces send the volunteer back to `/upload` to re-upload from scratch ("Try another file"), even though the input file is persisted server-side (`input.bin` + `resume.json`) and the "Re-run a recent meet" list is filtered to `status='done'`, excluding failed runs. A poolside volunteer who uploaded from a phone download may no longer have the file. And if they refresh the failed page, the server branch renders the raw pipeline exception in a `<pre>` with no dev gate — the same failure the live poller carefully hides.
Evidence: `web.py:21395` failure CTA is `Try another file`→`/upload`; `7229-7238` writes `input.bin`+`resume.json` for every run; `20228-20231` recent-list SQL is `status='done'`; `21382-21404` renders `<pre>{_err_msg}</pre>` with no `IS_DEV` check while `21562-21576` gates the same text for the JS path.
Fix: Add a one-click "Run this file again" to both failure surfaces (re-launch from `resume.json`; `_maybe_resume_stale_run` already does this); include recent failed runs in the "Re-run" list; apply the `_is_dev` gate to the server-rendered failure page (friendly copy for customers, raw error operator-only).

**[D-7] ✅ DONE (PR #1085) — Uploaded club audio disappears: no success confirmation and no UI ever lists it** — `high` / `moderate`
Affects: `/settings/audio`
What the user hits: After a successful audio upload the form redirects back to `/settings/audio` with no success message, and the page has no section listing the org's own uploaded audio (the list is built solely from the deployment-global catalogue). The volunteer can't confirm it worked, preview it, or delete it — and likely re-uploads the same track assuming it failed.
Evidence: `web.py:28666-28673` — success returns a bare redirect; `28756` — the track list iterates only `lib.all()` (catalogue); a repo-wide grep for `audio_uploads` finds only the write site (`28621`).
Fix: Add a "Your uploaded audio" list to `_render_settings_audio_section` (reading the rights ledger / `DATA_DIR/audio_uploads/<pid>`) with preview players and Remove, and show a "Track added" banner after redirect (the `?status=` pattern typography already uses).

**[D-9] ✅ DONE (PR #1082) — The athlete-rights table shows a due date but no overdue/countdown warning — the officer can silently blow the statutory deadline** — `high` / `moderate`
Affects: `/organisation/athlete-rights`
What the user hits: Each request's "Due" date is plain text with only open/clock-stopped/completed tags. Nothing turns red or flags "overdue" when the one-month deadline passes, so a busy volunteer has no visual cue a request is late — the exact failure GDPR penalises. The page's lede even promises "the due date… are tracked for you".
Evidence: `web.py:26159-26163` `status_tag` has only open/clock_stopped/completed; `26200-26203` renders the due date as bare text with no overdue styling — unlike the operator complaints table which computes `overdue_ids` (`25821`) and badges "ACK OVERDUE" (`25830`).
Fix: Compute overdue status from `DsrRequestLog.due_at` (mirroring `overdue()`) and render a red "OVERDUE" badge + "due in N days" countdown; sort/highlight overdue requests to the top.

**[D-10] ✅ DONE (PR #1097) — Documents/Newsletters use raw `alert()`/`confirm()` for errors and a product choice, with no busy state — double-clicks make duplicates** — `medium` / `moderate`
Affects: `/documents`, `/newsletters` — merges the cross-cutting "three error systems", the distribution "confirm/alert generation" and the "no loading state" findings
What the user hits: Which error UI a volunteer sees depends on which feature they opened: Review/reel show a branded toast, but the whole Documents+Newsletters area throws the browser's raw `alert()` for every failure and uses a native `confirm()` to make a *product* decision — "OK = AI draft · Cancel = build from data only" — where OK/Cancel give no hint which is which, and Cancel doesn't cancel (it still generates). After the dialog nothing changes while a multi-second AI job runs (buttons stay enabled, no spinner), so a double-click quietly creates duplicate documents. Failures can show raw codes (`generate_failed`, `need_two_pdfs`).
Evidence: `web.py:17540/17608` — `confirm('…OK = AI draft · Cancel = build from data only')`, still generating on Cancel; `17538-17556` — no button-disable/progress, `alert(...)` on failure; `59174/59611/59841` return bare error codes; because they aren't form submits, the auto-loader (`14586`) never fires; contrast reel `5056/5064` (renderProgress) and motion `4879-4880`.
Fix: Replace the `confirm()` chooser with an inline "Write with AI" checkbox per Generate button; disable the button and show "Generating…" while the request runs; render failures as styled inline messages / `MH.toast` with plain-English text.

**[D-11] Empty fetch `.catch` handlers swallow failures in total silence, app-wide; the comments feature is inconsistent with itself** — `medium` / `moderate`
Affects: `/review` card comments and other POST handlers app-wide (also folds the silent-`Enhance` case)
What the user hits: When one of these actions fails (offline poolside, server hiccup) the volunteer sees nothing — no error, no state change — and assumes it worked. Comments post surfaces "Network error" but comment delete/react fails silently, so a delete that didn't take just leaves the comment sitting there. The photo-editor "✦ Enhance" likewise fails with an empty catch.
Evidence: `web.py:6035` `commentsMutate` ends `.catch(function(){})` and `6042` `commentsReact` the same, while comment-send at `6028` surfaces "Network error"; 24 truly-empty `.catch(function(){})` handlers exist (of 124 catches); `photo_editor.py:525-529` — Enhance's error-JSON branch and network catch are both silent.
Fix: Audit the empty catches; for any user-initiated mutation surface `MH.toast("Couldn't save — check your connection","error")`. Reserve silent catches for genuine fire-and-forget polls.

**[D-12] 30–90s renders hide behind plain links with zero progress UI** — `medium` / `moderate`
Affects: `/pack/<run_id>/grouped`, `/pack/<run_id>`
What the user hits: On the grouped page, "Motion video" is a plain GET link opening a new tab that synchronously renders the MP4 — the tooltip admits "First time can take 30-90s" during which the user sees a blank tab and will re-click. "Download certificates (.zip of PDFs)" is likewise a plain `<a>` that renders one Chromium PDF per approved card inside the request — many seconds of dead silence. The same actions on the Content builder use a proper polling job with a progress bar.
Evidence: `web.py:44838-44844` grouped motion is `<a href>` to a sync GET (`51121`); `43322-43324` + `58671-58706` certificates loop `render_html_to_pdf` synchronously behind a plain link.
Fix: Point the grouped motion button at the existing motion-job + poll UI; turn the certificates ZIP into the same background-job pattern with a progress readout.

**[D-13] An in-flight reel/motion render is lost on navigation — returning users see nothing running and retries error "renderer busy"** — `medium` / `moderate`
Affects: `/pack/<run_id>`
What the user hits: The job survives server-side, but the page only re-attaches to FINISHED files on load. Someone who starts a 90s reel, navigates away (phone tab discarded) and returns sees no progress panel; clicking "Generate reel" again errors "Another video is rendering right now". The client poll also gives up at 4–6 min while the server job may still finish.
Evidence: `web.py:43361-43386` restore only checks finished MP4s; `2262` `_RENDER_TRY_TIMEOUT=0.75s` and `53179-53184` errors the second job; client caps at `4901`/`5147` while the server heartbeat keeps the job alive to 600s (`53144-53147`).
Fix: Persist the active `job_id` (localStorage or a per-run "latest jobs" endpoint) and re-attach the progress panel on load; on a renderer-busy click for the same run, resume polling the existing job; extend the client poll cap to the server's 600s.

**[D-14] ✅ DONE (PR #1085) — Audio upload errors dump raw JSON and lose typed fields — symptomatic of routes returning JSON to full-page navigations** — `high` / `moderate`
Affects: `/settings/audio` (also billing, mockup, chart, DSR erasure, reel-dub) — merges the audio and billing findings and names the cross-surface pattern
What the user hits: The audio upload is a plain form POST; picking an unsupported type, forgetting the file, or exceeding 25 MB navigates the browser to a bare JSON body (`{"error":"bad_type",…}`) with no styling, no upfront limit, no back link, and all typed licence/attribution fields lost. The same shape recurs: `/billing/confirm` etc. return `{"error":"billing_not_configured"}` 503 to full-page navigations; the mockup, chart, and DSR-erasure routes do the same on failure.
Evidence: `web.py:28610-28612`/`28629` return `jsonify(...)` 415/413 instead of routing through `_audio_back_or_json`; `38353-38354`/`38434-38435`/`38474-38475` return `_billing_unconfigured_response()` (503 JSON) to browser navigations.
Fix: For non-JSON / `Accept: text/html` requests, return the same styled `_layout` error card the graceful pages use, keeping the JSON body only for `Accept: application/json` callers; state the 25 MB / file-type limits next to the audio input.

**[D-15] 10–30s brand analysis on `/organisation` is discarded unless the user scrolls down and clicks "Save organisation"** — `medium` / `moderate`
Affects: `/organisation`
What the user hits: "Re-analyse brand" and "Analyse voice" run 10–30s of AI work then hold the result only in memory (a small tag says "click Save organisation to persist"), riding through hidden inputs in a separate form whose submit sits at the very bottom of a ~10-card page. A volunteer who glances at the preview and navigates away silently loses everything. The setup wizard, by contrast, persists immediately — same action, opposite semantics.
Evidence: `web.py:35256-35257` comment "kept in-memory only"; info tags at `35331-35332`, `35407-35408`, `35463-35464`; results survive only via hidden inputs (`35870-35883`); the setup wizard saves immediately (`42086`).
Fix: Persist capture results immediately (as setup does) with an explicit "Discard", or at minimum a sticky save bar + `beforeunload` warning while a preview is pending.

**[D-16] ✅ DONE (PR #1085) — Rejected logo uploads vanish silently** — `medium` / `moderate`
Affects: `/organisation/setup`
What the user hits: When a logo upload is rejected (bad/oversized/corrupt), the handler logs and `continue`s — nothing is stored and the redirect shows the setup page with the file simply absent from the grid. The inline comment claims the problem will be "surfaced on the next render" but no rejection state is persisted. A volunteer who dropped in six variants must visually diff the grid against their folder to notice one is missing, with no clue why.
Evidence: `web.py:42001-42008` — `except…: log; continue` despite the "surface on next render" comment; only successful metas are appended (`42009-42010`); no rejection is written anywhere.
Fix: Collect per-file rejection reasons during the POST, stash them (session flash or transient field), and render a warning list above the grid ("2 of 6 files couldn't be used: crest.bmp (unsupported), banner.png (over 50 MB)").

**[D-17] ✅ DONE (PR #1085) — When AI is unconfigured, the only explanation lives in a hover tooltip on a tiny dot** — `medium` / `moderate`
Affects: captions AI status dot, `/settings/governance`
What the user hits: The llm-status poller paints `.ai-status-dot` red and sets the button's `title` to "Live AI DISABLED — contact your administrator". A title tooltip needs a mouse hover (poolside phones never see it), and nothing in Settings surfaces AI availability — AI governance shows usage/roles but never whether a provider is live. So when captioning fails, there is no discoverable page explaining why.
Evidence: `web.py:5666-5670` sets only `d.style.background` and `btn.title` (tooltip-only); `28087-28217` — governance renders usage/roles/provenance with no provider-liveness row.
Fix: Add a visible "AI status" row (provider, live/disabled, plain-language next step) to AI governance and an inline banner on the captions tab when `live=false`.

**[D-18] ✅ DONE (PR #1085) — Downloading the email HTML before publishing silently drops every card image** — `medium` / `quick-win`
Affects: `/newsletters/<newsletter_id>`
What the user hits: Card images are resolved to public URLs only when the newsletter is published; for an unpublished draft the download leaves each `src` empty and the renderer omits the `<img>`. So generate → "Download email HTML" → paste into Mailchimp produces an email with all result-card images missing, with no warning — while the preview iframe (which passes `?preview=1`) shows images fine, actively misleading the user.
Evidence: `web.py:59308-59314` sets `published_token` only when published; `59265-59297` resolves card srcs only in preview/published branches; `email_design/render.py:225-227` sets `img_html=''` when src is empty.
Fix: When unpublished, warn on the Download button ("Card images need the hosted version — publish first") and offer one-click publish-and-download, or embed images as data URIs for the download path.

**[D-19] ✅ DONE (PR #1085) — Consent/records import reports only a count of skipped rows, never which rows failed** — `medium` / `quick-win`
Affects: `/athletes`, `/records`
What the user hits: The import copy promises "Rows we can't read are reported, never guessed", but the feedback is a single toast — "Imported 188 rows. Skipped 12 (unreadable level/name)." The user is never told WHICH rows failed. For a safeguarding consent register this silently leaves specific swimmers with no permission on file and no way to find them.
Evidence: `web.py:58037-58040` builds the message from `imported` and only `len(skipped)`, discarding the detail list; same for records (`58143-58146`); the promise is at `57992`.
Fix: Render the skipped rows (line number + raw text + reason) on the page after import so the user can correct and re-import.

**[D-20] ✅ DONE (PR #1085) — Data-hub bulk generate is a dead end — no link to the queued cards, and job rows aren't clickable** — `medium` / `quick-win`
Affects: `/data-hub`
What the user hits: After "Generate & queue", the user gets a toast naming an internal slug ("Queued 24 card(s) for review from certificate.") but no link to where those cards now live. The "Recent bulk jobs" rows are plain text, not links — so there's no path from "I just made 24 cards" into actually reviewing them.
Evidence: `web.py:57119-57124` redirects with a msg and no review URL; `data_hub_ui.py:206-215` renders each job row as plain `<td>` text with no link.
Fix: Make the success toast link to the run's review page and each job row link to the queued cards; replace the raw slug with the human format name.

**[D-21] ✅ DONE (PR #1085) — Running a SAR export downloads a file but leaves the request looking un-actioned** — `medium` / `moderate`
Affects: `/organisation/athlete-rights` (Run export)
What the user hits: "Run export" streams a JSON attachment and marks the request complete server-side, but returns no redirect or page update — the officer is left on the old table where the request still shows open with the same buttons, with no confirmation the export succeeded or that the clock stopped.
Evidence: `web.py:26278-26286` — `export_athlete()` → `log_store.complete()` → an attachment response with no redirect, so the table never refreshes.
Fix: After generating, redirect back with a success flash ("Export downloaded — request marked complete") and provide the JSON via a one-time download link on that page.

**[D-22] ✅ DONE (PR #1085) — Unparseable file gets a misleading "parsed OK — looks like a meet preview" diagnosis plus a raw parser exception** — `medium` / `quick-win`
Affects: `/upload/configure`
What the user hits: When `interpret_document` throws (corrupt PDF, weird encoding), the configure gate fires and, for any file over 2 KB, asserts "The file parsed OK but doesn't contain any events with results" and says they "uploaded an entry list, a heat sheet…" — while printing "Parser error: <raw exception>" directly beneath, contradicting itself. The volunteer is told to wait for the meet to finish when the file is actually corrupt. The page also under-reports supported formats.
Evidence: `web.py:20648` gate catches parse crashes in the same branch as zero-event files; `20663-20677` renders the "parsed OK" / entry-list copy plus the raw parser error; `20683` lists 3 formats vs the 12-extension allowlist at `20153-20166`.
Fix: Branch on `meta['parse_error']` — when the parser crashed, say "We couldn't read this file" with plain-language causes, keep the raw exception operator-only, and make the supported-formats line match the real allowlist.

**[D-23] ✅ DONE (PR #1085) — Raw internal exception text is shown verbatim to customers on the chat, graphic and demo surfaces** — `medium` / `quick-win`
Affects: `/free-text/chat/<chat_id>`, draft graphic panel, `/try/<run_id>` — merges the chat/graphic and demo raw-error findings
What the user hits: When the chat agent fails, the raw Python exception is appended as an assistant bubble ("Error: …"), reading like the bot broke with developer internals; a failed draft graphic shows "Error: render_failed: <exception>". The anonymous `/try` demo — the top of the acquisition funnel — shows the raw pipeline error in a `<code>` block and "Parser said: <raw exception>", and hard-reloads every 3s with no progress bar, so first-time visitors see the least polished, most engineer-flavoured screens.
Evidence: `web.py:33813`/`33855` add `f"Error: {e}"` bubbles; `34427` returns `render_failed: {e}` rendered verbatim by `_VISUAL_PANEL_JS` (`12706-12708`); `50246-50253` hard-reload with no progress; `50260`/`50116` show raw errors to anonymous users.
Fix: Map provider/render failures to friendly copy with a Retry button (the reel job's `user_message` already does this) and log the raw exception server-side only; reuse the real run-status poller for `/try/<run_id>`.

**[D-24] ✅ DONE (PR #1085) — The blackout-date warning flashes for 1.2 seconds then is wiped by the reload** — `medium` / `quick-win`
Affects: `/plan/calendar`
What the user hits: Dropping a draft on a blackout date is the soft gate's one moment to warn, but the warning renders in 12.5px status text for exactly 1200ms before the page reloads and erases it. After reload the only trace is a small ⚠ whose explanation lives in a title tooltip (invisible on touch), so a volunteer can schedule onto their own blackout day without reading why.
Evidence: `web.py:30446` shows the warning then `setTimeout(reload, 1200)`; `30302-30307` — the post-reload chip carries only `title="On a blackout date you set"`.
Fix: Persist the warning across the reload (flash/toast on the reloaded page), or skip the reload and update the cell in place with a visible inline banner.

**[D-25] ✅ DONE (PR #1085) — Fabricated "90% conf" badges on free-text, chat and spotlight drafts** — `medium` / `quick-win`
Affects: `/drafts/<pack_id>`
What the user hits: Draft cards display a badge titled "Model confidence" (e.g. "90% conf"), but for free-text/chat/spotlight packs the value is a hardcoded constant (0.9, 0.85, 0.9) — no model computed it. Volunteers are trained to trust confidence scores in the review flow; a fake one devalues the real ones.
Evidence: `web.py:33556` (0.9 quick), `33876` (0.85 chat), `32393` (0.9 spotlight), rendered as "<pct>% conf" titled "Model confidence" at `stubs.py:591-594` — directly under a comment (`588-589`) saying brief-led cards deliberately carry no confidence because "the engine refuses to fabricate one".
Fix: Set `confidence` to `None` for prompt-led packs so the badge (already conditional on a real value) doesn't render, or replace it with "AI draft — review before posting".

**[D-26] Every planner micro-interaction forces a full page reload, making batch work slow and lossy** — `medium` / `moderate`
Affects: `/plan/board`, `/plan/calendar`, `/plan/analytics`
What the user hits: Each calendar drag, board add/move/delete/promote, and analytics log/remove ends in `window.location.reload()`. A committee member triaging ten ideas eats a full reload per action and loses scroll each time; the analytics form resets to defaults after every entry, so post type and date must be re-picked for each log.
Evidence: `web.py:30446-30447`, `30867-30872`, `31113-31117`/`31119-31123` all reload on success, and the reload resets the log form.
Fix: Update the DOM in place on success (append/remove the row, move the card, re-render the cell); at minimum keep the analytics form values after logging.

**[D-27] ✅ DONE (PR #1085) — The planner's AI buttons' `data-loader-text` is inert — long LLM calls show only a tiny status line** — `low` / `quick-win`
Affects: `/plan` — merges the planner-loader and setup-loader findings
What the user hits: "Generate plan", "Interpret & fill in" (LLM + web research, tens of seconds) and the analytics "AI performance digest" carry `data-loader-text` for the shared loader, but the loader only binds to form submit events and these are `type=button` onclick handlers outside any form — so the intended loading treatment never fires. The same is true of the setup page's "Re-read" and "Save brand colours" (which carry `data-no-loader="1"`): multi-second AI work with only a tiny status span, inviting double-clicks, and failing silently on error.
Evidence: `web.py:14586-14602` binds the loader only to form `submit`; the buttons at `29937/29957/31085` are `type=button` outside any form; setup forms at `41104-41105`/`40660` carry `data-no-loader="1"` while their routes run inline AI work (`42675`, `42305-42310`) and redirect silently on failure.
Fix: Call `MH.showLoader(btn.dataset.loaderText)`/`MH.hideLoader()` (or an in-button spinner) inside the planner handlers; drop `data-no-loader` from the two setup forms and flash a reason on failure.

**[D-28] ✅ DONE (PR #1082) — The public status page reports "Website operational" even when status data is unavailable** — `low` / `quick-win`
Affects: `/status`, `/settings/status`
What the user hits: The public status renderer defaults `operational=True` and, if reading the uptime store throws, the except branch explicitly sets `operational=True` — so a deployment whose observability layer is broken shows a green dot and "Everything is running normally." A volunteer checking status during an outage could be told all is well when the system simply can't tell.
Evidence: `web.py:29273` initial `operational=True`; `29286-29287` `except: operational=True`; only green/red cards exist (no "unknown"), unlike the operator "no data yet" pill (`29070-29071`).
Fix: Add a third neutral state ("Status unavailable — we can't confirm right now") for the no-data/exception path instead of defaulting to green.

**[D-29] ✅ DONE (PR #1085) — Bulk "Approve" in the media library produces no visible state change and cannot be undone** — `medium` / `quick-win`
Affects: `/media-library`
What the user hits: Bulk Approve sets `approval_status='approved'` (which weights the automatic photo picker), but the table has no approval column — after the toast fades, approved and draft photos look identical, so volunteers can't tell what they approved or what still needs it, and there is no unapprove action. The label also collides with the card-review "Approve" (a different meaning).
Evidence: `web.py:45733` header row has no approval column; `46988` `update_fields(...,{"approval_status":"approved"})`; `16691-16698` JS only toasts and unchecks; no unapprove writer exists.
Fix: Add an approval badge column (Draft/Approved), update it in place after bulk approve, add an "Unapprove" bulk action, and rename the button ("Mark ready for cards").

**[D-30] ✅ DONE (PR #1085) — Rejected brand-guidelines upload is reported inside a green success box with raw internal status codes** — `medium` / `quick-win`
Affects: `/organisation/setup`
What the user hits: Upload a PNG as your "brand guidelines" and the server correctly rejects it — but the next render shows the rejection inside the green-tinted box headed "Loaded: <filename>" with the raw status ("unsupported_binary: 'guide.png' looks like an image…") in muted text. A volunteer scanning the page sees green + "Loaded" and reasonably concludes their style guide was ingested when it was not.
Evidence: `web.py:41946-41954` sets the status string while still setting the filename; the box is guarded only by `if prof.brand_guidelines_filename` (`40956`) so it renders on the reject path, drawing green "Loaded" (`40995-41011`) with the raw status verbatim.
Fix: Branch the box on success vs failure — failures get warning styling, "Couldn't read <filename>", a plain-English reason, and no "Loaded" wording; hide the internal status/extractor identifiers.

**[D-31] ✅ DONE (PR #1085) — Remote and console action taps swallow all errors — a dead button gives zero feedback** — `medium` / `quick-win`
Affects: `/remote/<code>`, `/documents/<id>/present`
What the user hits: The remote's `act()` does `fetch → r.json() → if(j.state) setPos` with no try/catch and no else, so when the request fails (offline wifi, a 429/404 with `ok:false` and no `state`) the tap does nothing and the position never changes — the presenter can't tell whether the slide advanced, whether they lost connection, or whether they've been rate-limited. The console's `act()` is the same.
Evidence: `web.py:17765` remote `act()` has no catch and no `j.ok===false` branch (a 429 returns `{ok:false,error:'rate_limited'}` with no `state`); `17693` console `act()` fires and re-polls with no error handling.
Fix: Catch fetch failures and non-ok responses in `act()`; surface a brief inline state ("Reconnecting…", "Too many attempts — wait a moment", "Not connected").

**[D-32] The sponsor variant page renders the graphic and AI caption synchronously inside the page load** — `medium` / `moderate`
Affects: `/runs/<run_id>/card/<card_id>/sponsor-variant`
What the user hits: Opening the sponsor variant runs the full visual render pipeline plus an LLM caption call inside the GET handler before any HTML returns, so a cold render leaves the volunteer staring at a browser spinner (renders take 30–90s elsewhere) with no progress or skeleton. The page's own regenerate instruction is "Generated on demand — refresh to regenerate", repeating the whole blocking wait; failures surface as "render_failed: <exception>".
Evidence: `web.py:49203-49204` route defaults to GET; `49299` and `49358` call render + caption inline before `_layout`; `49411` "refresh to regenerate"; `49347` renders `render_failed: {e}`.
Fix: Return the page shell immediately with a loading state and fetch the visual/caption asynchronously (the motion endpoints already do this), replacing "refresh to regenerate" with a Regenerate button that shows progress.

**[D-33] ✅ DONE (PR #1085) — Chart PNG/SVG exports dead-end into a raw JSON error, with no busy state and cryptic size glyphs** — `medium` / `moderate`
Affects: `/runs/<run_id>/charts` — merges the chart error-state and chart glyph findings
What the user hits: Each chart tile's export is a plain anchor. When PNG rasterisation fails (Chromium missing — the route's own documented gap), the browser navigates off the charts page onto a raw JSON blob (`{"error":"png_unavailable"}`) with no way back, and there is zero feedback during the multi-second cold raster. The buttons themselves are bare geometric glyphs ("PNG ◫", "▣", "▮", "SVG") whose meaning lives only in `title` tooltips — useless on the poolside phone.
Evidence: `web.py:53061-53068` tiles emit `<a href>` exports with size meaning only in `title`; `52896-52906` returns `jsonify({error:'png_unavailable'})` 503 so the anchor lands on raw JSON.
Fix: Fetch exports via JS (blob download) so failures render inline with an "download SVG instead" fallback and a busy state; label buttons by intent ("Post 4:5", "Square 1:1", "Story 9:16") with the pixel size secondary and demote SVG to "Vector (for designers)".

**[D-34] ✅ DONE (PR #1082) — Empty states are inconsistent — a polished shared helper exists but sponsors and collections show a bare grey line** — `low` / `quick-win`
Affects: `/settings/sponsors`, `/collections`
What the user hits: On a first visit some zero-data pages get a designed empty state (art, headline, guidance, CTA) while sponsors and collections get a single flat grey sentence — exactly the first-run moment where a new volunteer decides whether the product feels finished.
Evidence: the `_empty_state` helper (art + headline + sub + CTA) is at `web.py:16223`; yet sponsors empties to `<tr><td class="dim">No sponsors yet…` (`49469`) and collections to `<p class="lede">No collections yet…` (`55078`), neither using the helper.
Fix: Render both through `_empty_state` with an explicit primary CTA ("Add your first sponsor" / "Create a collection").

**[D-35] ✅ DONE (PR #1085) — Minor feedback gaps: no reset confirmation, no signup-email notice, unexplained "leave page" copy, silent Enhance** — `low` / `quick-win`
Affects: `/password/reset/<token>`, `/signup`, `/runs/<run_id>` progress
What the user hits: After a password reset the user is silently logged in and redirected with no "password updated" confirmation; signup fires a verification email but the UI never says one was sent or why verifying matters, so most accounts never verify. The pipeline progress page (which can run 8+ minutes) never says the run survives leaving the page — its only escape is an ambiguous "View on home".
Evidence: `web.py:36995-36998` login + redirect with no flash; `36600-36602`/`36615` send the verification email with no message (the `_flash_toast` mechanism at `16157-16172` is unused); progress page copy at `21445`/`21590` frames waiting-on-page as the mechanism, escape button "View on home" at `21458`.
Fix: Use `_flash_toast` for "Password updated — you're signed in" and "Account created — we've sent a verification link to <email>"; add one line to the progress page ("You can leave — the run keeps going and the finished pack appears on Home") and relabel the button.

---

### E. Destructive actions & data safety

**[E-1] Irreversible deletes are guarded only by a native `confirm()`, with no undo anywhere** — `high` / `moderate`
Affects: app-wide — run list, clear-all-runs, `/collections`, media library, `/documents`, `/newsletters`, `/plan/board`, `/plan/analytics`, sponsors, members
What the user hits: Deleting a run, ALL runs, a collection, a photo, a document, a newsletter, a board idea, an analytics record, a sponsor, or removing a member gives nothing but the browser's grey OS `confirm()` — the dialog people reflexively dismiss — and once they tap OK the data is gone with no way back. Run-delete even yanks the row out of the DOM instantly (the ideal moment for an Undo toast) yet offers none. On a phone the native confirm is a jarring, fat-fingerable system sheet. (Organisation delete is the exception — it adds a type-the-org-id challenge + password re-verify.)
Evidence: `web.py:4076` run delete `confirm()` then optimistic row removal (`4086-4089`); `4106` clear-all; `55103` collection; `45460` photo; `17597` doc; `17649` newsletter; `30816-30817` board idea; `31119` analytics; `49462-49465` sponsor remove (no confirm at all); `39308-39317` member remove (no confirm); the only undo anywhere is approval Re-queue (`3596`).
Fix: Replace the highest-stakes deletes (run, clear-all-runs, collection) with the styled modal helper; since the run row is already removed optimistically, show a "Run deleted · Undo" toast (MH.toast supports an action) that soft-deletes for ~8s; add `confirm()` to the sponsor and member removes at minimum.

**[E-2] ✅ DONE (PR #1082) — Two of three whole-pack exports bundle rejected cards** — `high` / `moderate`
Affects: `/pack/<run_id>/zip`, `/export/<run_id>`
What the user hits: A volunteer who approves a card, renders its graphic, then rejects it after spotting a problem (misspelled name, parent complaint) still gets that card in "Download all visuals (.zip)" and the Bulk export ZIP — both walk every visuals directory with no workflow-status filter, and rejecting a card never removes its rendered files. Only the "every format + manifest" ZIP filters rejected cards. Three buttons that all read as "download my pack" silently apply three different rules about what the club approved.
Evidence: `web.py:56424-56448` — `content_pack_zip` iterates every subdir with no status check; `53787-53806` — `_bulk_items_for_run` adds one item per subdir, no filter; `pack_export.py:462-467` filters only rejected; `43494-43500` — rejecting clears the ledger but never touches the visuals dir.
Fix: Apply one rule everywhere — build the card-id allowlist from workflow status (approved/posted) in `content_pack_zip` and `_bulk_items_for_run`, exactly as `pack_export` already excludes rejected; state the rule in the button copy ("includes your N approved cards").

**[E-3] ✅ DONE (PR #1082) — Per-card "Download .zip" exports the internal headline, not the caption the volunteer wrote** — `high` / `moderate`
Affects: `/pack/<run_id>`, `/review/<run_id>`
What the user hits: The Content builder's whole point is picking a caption tone and editing the text — yet the per-card "Download .zip for manual posting" writes `caption.txt` from a `?caption=` query param no caller ever passes, falling back to the achievement headline. The README inside the ZIP claims "the .txt file contains the ready-to-post caption", so a poolside volunteer posts the raw internal headline and their edit is silently lost. The run-level `export.zip` pulls real captions, so the two exports contradict each other.
Evidence: `web.py:31304-31305` — `caption = request.args.get("caption") or ach.get("headline")`; README claim at `31337`; both callers (`3578`, `42944`) omit the param; the run-level ZIP fetches real captions via `build_content_pack` (`56523-56534`).
Fix: Make `api_card_download` read the persisted workflow `edited_captions` / active-tone caption (same source as `_build_run_pack_zip`); keep `?caption=` only as an override.

**[E-4] The phone remote's "End" button is unconfirmed, irreversible, and permanently strands the remote** — `high` / `quick-win`
Affects: `/remote/<code>`
What the user hits: On the phone remote a big "End" button sits in the same row and weight as "Blackout", one fat-finger tap away. Tapping it immediately ends the live presentation for the whole audience with no confirmation. There is no undo — `apply_action`'s "end" has no inverse, and once ended the pairing code stops resolving, so reloading gives "Code not found". The volunteer must walk back to the laptop and start a fresh session with a new code mid-talk.
Evidence: `web.py:17762` renders Blackout + End with no `confirm()`, both `flex:1`; `presenter.py:209-210` sets `s.ended=True` with no inverse; `presenter.py:140` filters ended sessions so the code no longer resolves.
Fix: Require a confirmation ("End presentation for everyone?"); visually separate/deprioritise End from Blackout; route the ended remote to a friendly "presentation ended" screen instead of "Code not found".

**[E-5] Share links: no copy button, expiry invisible, and export-ZIP tokens can't be revoked from any UI** — `medium` / `moderate`
Affects: `/export/<run_id>`, `/pack/<run_id>`
What the user hits: Creating a share link (which exposes club content — often children's images — outside the workspace) gives only a readonly input to click-select; the API returns `expires_at` but no UI shows when a link dies. The run-wide token minted by "Create share link" on a bulk export appears in no list (the only listing UI filters to card-scoped tokens), so an export share can never be seen again or revoked — even though the revoke endpoint exists. A failed revoke is silently swallowed.
Evidence: `bulk_export.js:89-98` — readonly input, `expires_at` unused, no copy/revoke; `web.py:6171` — `shareLoad` filters to `card_id`, hiding run-wide tokens; `6205-6206` — `shareRevoke` ignores the body and has an empty `.catch`.
Fix: Add a Copy button and an "expires <date>" label wherever a share URL renders; list run-wide tokens (with revoke) in the bulk-export result or a per-run "Active share links" section; surface revoke failures.

**[E-6] ✅ DONE (PR #1097) — Merging two athletes is irreversible yet has no confirmation and no undo** — `medium` / `quick-win`
Affects: `/athletes`
What the user hits: The "Same swimmer twice?" merge is two dropdowns and a button. Picking the wrong pair fuses two distinct swimmers' entire race histories, and the copy states the decision "sticks for every future upload" with no undo. A non-technical volunteer can silently corrupt the roster with one mis-click and a bare success toast.
Evidence: `web.py:57980-57985` — the merge form has no `onsubmit` confirm; `58024-58029` executes `merge_athletes` and returns "Merged — the decision is recorded and persists." with no undo.
Fix: Add a confirmation showing both names and their race counts ("Merge Patel, Maya (14 races) into Maya Patel (9 races)? This can't be undone"); ideally an unmerge for a grace period.

**[E-7] ✅ DONE (PR #1097) — The consent-enforcement toggle flips a club-wide content block with one unconfirmed click** — `medium` / `quick-win`
Affects: `/athletes`
What the user hits: "Switch enforcement on" is a bare button. Turning it on means every athlete with no consent on file is blocked from content — potentially suppressing most of the roster instantly — with no confirmation and no preview of how many athletes would be affected, so a volunteer can accidentally break their whole content pipeline and only see a one-line toast.
Evidence: `web.py:57957-57960` — the toggle form has no confirm; `57938-57944` describes the ACTIVE state; `58032-58035` flips it and returns only a success message.
Fix: Confirm before enabling, and show the impact ("N of M athletes currently have no consent and would be blocked").

**[E-8] ✅ DONE (PR #1097) — Permanent org-profile delete is one native confirm away, adjacent to the primary "Sign in" button, and fails silently for members** — `medium` / `moderate`
Affects: `/sign-in`
What the user hits: Every org card on the picker carries a small × delete button directly beside the primary "Sign in" button. One `confirm()` later the profile is permanently unlinked — a fully configured brand gone with no undo — and the confirm copy uses jargon ("Its runs stay on disk but it disappears from this picker"). A non-owner member who clicks delete is silently bounced with no message, so the button appears to do nothing.
Evidence: `web.py:38742-38753` renders the delete form with a native `confirm()` in the same `.actions` row as sign-in; `38842-38845` unlinks with no soft-delete; `38836-38839` silently bounces non-owners.
Fix: Move delete behind a per-card overflow menu, require typing the club name (or a styled modal stating what is lost), implement soft-delete/undo (runs already survive), and flash "Only the workspace owner can delete this organisation" for bounced members.

**[E-9] ✅ DONE (PR #1082) — Account delete: two inconsistent forms, a missing required password, an error page that bounces to the wrong page, and silent success** — `medium` / `moderate`
Affects: `/settings` (account), `/privacy`, `/account/delete`
What the user hits: Account deletion exists on two surfaces with different labels. The Settings variant's password field lacks `required`, so a volunteer can click Delete empty, pass the confirm, and hit a full-page "Password check failed" whose only exit is "← Back" to the Privacy page (not the Settings page they came from). On success the user is silently redirected to signed-out home with no confirmation.
Evidence: `web.py:29261` password input has no `required` (the `/privacy` twin at `25510` has it); the failure page (`26488-26498`) hardcodes a back-link to `privacy_page`; success (`26501-26504`) redirects to home with no message.
Fix: Consolidate to one delete form, add `required`, return validation errors inline on the originating page with focus, and land the deleted user on a dedicated "Your account has been deleted" page.

**[E-10] Photo editor "Reset" wipes the saved recipe with no confirm, and unsaved edits are lost on a mis-click** — `medium` / `quick-win`
Affects: `/media-library/<asset_id>/edit`
What the user hits: Edits exist only client-side until "Apply & save" — there is no `beforeunload` guard, and the "← Library" link sits directly above the canvas, so one mis-click throws away all slider/crop/brush work. "Reset" immediately POSTs and permanently clears the asset's persisted recipe and caches — no confirm, and client-side Undo can't restore it after leaving.
Evidence: `photo_editor.py:545-550` — recipe persisted only by Apply; `531-539` — Reset fetches with no `confirm`; `web.py:47520-47529` — the reset route clears the recipe + caches; no `beforeunload` handler exists.
Fix: Track a dirty flag with a `beforeunload` prompt; put a confirm on Reset distinguishing "discard current tweaks" from "delete the saved edit"; offer the saved recipe back via Undo after a reset.

**[E-11] "Regenerate (fresh angles)" replaces every draft card with one click — no confirm, no undo — beside a near-identical "Generate new draft"** — `medium` / `quick-win`
Affects: `/drafts/<pack_id>`
What the user hits: The draft footer offers both "Regenerate (fresh angles)" and "Generate new draft". The first immediately replaces all current cards (approval statuses included) with a fresh set; prior cards are archived only as platform+caption in a `card_history` field no page ever displays, so approved captions are gone with no confirm and no undo. The second button, despite the name, just opens the blank source form.
Evidence: `web.py:34108-34119` renders both; `mhRegenerateDraft` (`12755-12774`) POSTs with no confirm; `replace_cards` (`35203`) has no confirmation; `stub_pack_store.py:261-286` archives only `{platform, caption}` into `card_history`, only ever read as an engine avoid-set (`35184`).
Fix: Add a confirm to Regenerate ("This replaces all N cards and clears approvals"); show a "previous versions" expander fed from `card_history`; rename "Generate new draft" to "Start a new draft from the form".

**[E-12] "Switch off & revoke the link" has no confirmation and permanently kills every shared wall URL and embed** — `medium` / `quick-win`
Affects: `/public-wall`
What the user hits: The disable button is a bare form submit — one accidental click clears the wall token, instantly 404ing the public page, the club-website iframe embed, the RSS/JSON feeds and any QR codes distributed. Re-enabling mints a brand-new token, so nothing shared ever works again; the embed pasted into the club's site must be found and replaced. No confirm, no undo.
Evidence: `web.py:49723-49726` — the form has no `onsubmit` confirm; `49775-49779` — disable sets `public_wall_token=''` (comment "the old URL resolves to nothing (404)"); `49771-49774` — re-enable only mints a token `if not prof.public_wall_token`, so it always differs after a disable.
Fix: Add a confirmation spelling out the consequence ("Your public link, website embed and feeds will stop working; switching back on creates a different link"); consider a soft-off that pauses the wall while retaining the token so re-enabling restores embeds.

**[E-13] Per-card translate saves and exports translated alt-text the approver never sees (a human-approval bypass)** — `medium` / `moderate`
Affects: review / content-pack page (`POST /runs/<id>/card/<id>/translate`)
What the user hits: MediaHub's core principle is human approval before export. The per-card translate control sends caption and alt-text to the route, which persists the entire returned variant onto the card so it rides into export — but the review UI only renders the translated caption. A volunteer therefore approves and exports translated accessibility text they never saw or corrected. RTL languages compound this: `dir` is applied only to the caption span.
Evidence: `web.py:4339` adds `alt_text` to the POST; the route builds slots from caption/alt_text/headline/subhead (`24349`) and persists all via `ws.set_translation(...)` (`24451`); the review handler reads only `jj.slots.caption` (`4350`) and sets `dir` only on the caption span (`4308`, `4355`).
Fix: Render every translated slot the route saved (caption, alt-text, headline, subhead) back in the review card before approval, each with its own `dir` — or stop persisting slots the UI cannot display.

**[E-14] Cross-store athlete erasure is a plain "secondary" button behind a one-line confirm; adding a same-named sponsor silently overwrites the existing entry** — `low` / `quick-win`
Affects: `/privacy` (Erase an athlete), `/sponsors`
What the user hits: "Erase an athlete" wipes a named person from every run, rendered file, cache, caption memory and posting log irreversibly, yet the trigger is an ordinary secondary button next to an optional text field, guarded only by a generic `confirm()` that doesn't enumerate what will be destroyed. Separately, submitting the Add-sponsor form with an existing name silently replaces that entry (de-duped by id), so a volunteer "adding" a second entry unknowingly wipes the original's tier/logo/website.
Evidence: `web.py:25456-25463` — erase form is a `btn secondary` behind a one-line confirm with no scope breakdown; `49561-49569` — `sponsors_add` filters out same-`sponsor_id` entries before appending, with no notice.
Fix: Give erase danger styling and a scope preview (or require typing the athlete name); on same-name sponsor add, flash "Updated existing sponsor Acme Sports" or open an explicit Edit mode.

---

### F. Jargon & labels

**[F-1] ✅ DONE (PR #1085) — Pipeline jargon "run" pervades the customer-facing chrome** — `medium` / `moderate`
Affects: app-wide (landing hero, `/activity`, delete confirms)
What the user hits: The landing hero counts "003 total runs", the Activity toggle is "Runs table", the empty state says "No runs yet for this organisation", and the delete confirm asks "Delete this run?". A club volunteer thinks in uploads and meets, not pipeline runs.
Evidence: `web.py:18676-18679` hero "total runs"; `19420` "Runs table"; `19128-19132` "No runs yet"; `4076` "Delete this run?".
Fix: A copy sweep replacing user-facing "run" with "meet"/"upload" ("Meets processed", "Meet history", "Delete this meet's results?"), keeping "run" only in operator/developer surfaces.

**[F-2] ✅ DONE (PR #1085) — The review surface leaks raw engine enums, a "Recognition" tab title, "None – None" dates, and the org slug** — `medium` / `quick-win` (confirmed live)
Affects: `/review/<run_id>`, `/media-library` header — merges the review-jargon and live-walkthrough findings
What the user hits: The band and post-type filters render internal values verbatim ("elite / strong / story / nice / not_worthy", "medal_gold", "top_of_field_top_3", "main_feed") complete with underscores, where every other part of the page has humanised copy. The browser tab is titled "Recognition"; the header shows "None – None" when the file has no dates; the media library header shows the raw profile slug "riverside-swimming-club" and a zero-padded "000 assets".
Evidence: `web.py:22290` `bands_set` fed raw through `opts()` (`22322-22326`); page title "Recognition" (`23259`); `22746` passes `None` through as "None – None"; observed live at `/review/72e6f888f1e5` and `/media-library`.
Fix: Map enum values to display labels in `opts()` (reuse `_BAND_MEANING` / the "Gold medal"/"Top-3 finish"/"Feed post" labels); render "—" or "dates not in file" when dates are missing; show the org display name, not the slug; title the page "Review — <meet name>".

**[F-3] ✅ DONE (PR #1085) — Operator env-var jargon is leaked to customers across multiple surfaces** — `medium` / `quick-win`
Affects: `/upload` (results-from-a-link), `/media-library`, `/settings/audio` (and the `/pricing` tooltip) — merges three findings
What the user hits: A hosted-SaaS customer has no shell, yet the UI tells them to set env vars: a stalled crawl says "ask your administrator to raise `MEDIAHUB_RESULTS_FETCH_TIMEOUT_S`…"; the library's image panel says "set `MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`"; the audio page embeds "`MEDIAHUB_REEL_MUSIC_LIBRARY=1`… point `MEDIAHUB_AUDIO_LIBRARY_DIR`" and tags voices "(local)"/"(online)"; the pricing TBC tooltip says "Set `STRIPE_PRICE_CLUB` to enable".
Evidence: `web.py:21082-21087` (crawl env vars → visible error region); `45481-45484` (library panel, unconditional) vs `image_studio.py:287-296` (dev-gated with "ask your operator"); `28772-28774`/`28781` (audio); `38094-38102` (pricing tooltip).
Fix: Replace each with customer-relevant copy (e.g. "This site is unusually heavy to read — upload the results file instead"; "ask your operator"; "upload your own tracks below"; "Pricing is being finalised") and move env-var remediation to the operator-only Developer surface / server log; relabel local/online as "built-in"/"premium".

**[F-4] ✅ DONE (PR #1085) — "See what the engine does" / footer "Roadmap" open an internal parser-adapter research page** — `medium` / `quick-win`
Affects: `/` (signed-out) → `/research`, footer — merges the two roadmap findings
What the user hits: The signed-out hero's "Just looking? See what the engine does" sends a non-technical volunteer to a page about HY3 parsers, SDIF/CL2 formats and `can_parse()` implementation notes. The same route is labelled "Roadmap" in the footer, so one destination carries two promises and the misleading one sits on the first-time visitor's evaluation path.
Evidence: `web.py:18697-18699` links "See what the engine does" → `research_page`; `24952-24985` renders "Adapter roadmap" content including `can_parse()`, HY3, SDIF/CL2; `14143` labels the same route "Roadmap".
Fix: Point "See what the engine does" at the on-page product demo (`#mh-see-it-work`) or the Help explainer; rewrite `/research` as a user-facing "What files can I upload?" page and keep parser detail on `/developer/api`, or drop the public footer link.

**[F-5] ✅ DONE (PR #1085) — Bulk "Export" (review) downloads a developer JSON file while the per-card "Download" delivers the actual content** — `medium` / `moderate`
Affects: `/review/<run_id>`
What the user hits: The bulk bar's "Export" returns a machine-readable JSON dump (rank, quality_band, factors, status) as `mediahub-cards-<run>.json`. A social-media volunteer selecting approved cards and clicking Export expects the postable content (images + captions) — which is what the per-card "Download" button provides. Same surface, two different words, and the more prominent bulk one yields a file the target user cannot post.
Evidence: `web.py:43770-43774` — `api_cards_bulk_export` responds with a JSON attachment (button at `22797-22798`), while per-card "Download" links `api_card_download` (`3578-3583`, "caption + visual as a .zip").
Fix: Rename the bulk button "Export data (JSON)" and move it into an overflow; add a bulk "Download content (.zip)" that packages each selected card's caption + visual.

**[F-6] ✅ DONE (PR #1085) — Plan items wear internal signal vocabulary: OWN/EXTERNAL/DIRECT, "baseline", "approval required", "horizon 14d"** — `low` / `quick-win`
Affects: `/plan`
What the user hits: Each ranked item shows unexplained chips (OWN/EXTERNAL/DIRECT — the engine's signal-source taxonomy), falls back to a bare "baseline" tag, and shows an "approval required" autonomy tag — alarming in a product that never auto-posts, implying some types might not require approval. The meta line adds "horizon 14d". None are defined on the page.
Evidence: `web.py:29755-29759` (src chips, no legend); `29798-29799` ("baseline"); `29804-29819` ("approval required"); `29838` ("horizon {n}d").
Fix: Rename chips to plain language ("from your results", "from the calendar", "you told us"), drop/reword the autonomy tag (everything requires approval), and spell out "next 14 days".

**[F-7] ✅ DONE (PR #1085) — PB audit/verify screens leak raw internal enums and jargon with no plain-language trust key** — `medium` / `quick-win`
Affects: `/audit/<run_id>`, `/audit/<run_id>/verify/<key>`
What the user hits: The Verify screen shows the raw identity enum ("needs_verification", "asa_id_verified") as "Match status", even though the audit table one screen earlier renders the same value as a friendly label ("Needs check", "Verified"). More broadly the surface is full of swim-federation/engine jargon (HY3 Name, ASA ID, "reconciliation", "Confirmed") and never explains in plain language what a confirmed vs unconfirmed PB means.
Evidence: `web.py:24671`/`24696` render the raw `method` enum under "Match status" while the friendly map (`24518-24525`) is used only in the audit table; the "Confirmed" count (`24505-24510`) has no on-page legend.
Fix: Reuse the label map everywhere (never render the raw enum) and add a short plain-language legend ("Confirmed PB = matched to an official record; Needs check = we couldn't confirm the swimmer's ID"); rename HY3/ASA-ID columns where possible.

**[F-8] ✅ DONE (PR #1085) — GDPR article citations and acronyms lead the consent and rights UI a non-lawyer must use** — `medium` / `quick-win`
Affects: `/organisation/consent`, `/organisation/athlete-rights`
What the user hits: The forms a club safeguarding officer must use carry legal shorthand — "Consent (Art 6(1)(a))", "Restrict processing (Art 18)", "stop-the-clock rules (Article 12A)", "Access — export everything we hold (SAR)". The target user is explicitly a non-lawyer; the lawful-basis selector in particular leads with statute references.
Evidence: `web.py:25979` ("Consent (Art 6(1)(a))"), `26042` ("Restrict processing (Art 18)"), `26215` ("Article 12A"), `26223/26226` (SAR / Art 18).
Fix: Lead each option with plain-English meaning and demote the legal citation to a muted tooltip ("They said yes / consent given", "Pause all use of their data").

**[F-9] ✅ DONE (PR #1085) — The formal DSR erasure result is a raw JSON dump while the identical quick-erase shows a friendly summary** — `medium` / `quick-win`
Affects: `/organisation/athlete-rights` (Run erasure)
What the user hits: When an officer runs an erasure through the proper Article-12A workflow, the confirmation is a pre-formatted raw JSON blob of the internal report — meaningless to a welfare officer. The same erasure launched from `/privacy` renders a plain-English "What was removed" bullet list, so the compliant path gives the worse experience.
Evidence: `web.py:26293-26298` builds the response as `<pre>` + `json.dumps(report, indent=2)`; the quick-erase path (`26379-26389`) renders a human-readable list.
Fix: Reuse the human-readable "What was removed" builder for the DSR erasure response; offer the JSON only as an optional "download technical report" link.

**[F-10] ✅ DONE (PR #1085) — Brand-kit create/edit is an expert form: bare "#hex" fields, internal IDs, and governance jargon** — `medium` / `moderate`
Affects: `/brand`
What the user hits: Everywhere else volunteers get native colour pickers, but the kit forms ask for palette values in bare text inputs placeholdered "primary #hex" — a typo or the word "red" is silently dropped by normalisation while the page still flashes "Saved kit…". The form also asks for a "font pairing id (optional)" (an internal identifier with no list), a free-text "tone override", raw "Lock tokens (block off-brand approval)" checkboxes, and "Min approvers / require an owner" rows.
Evidence: `web.py:39756-39779` — bare `#hex` text inputs, font-pairing id, tone override, lock tokens, approver rows; `_form_palette` (`39970-39976`) → `normalise_kit` silently drops invalid slots (`kits.py:91-100`) while the route always flashes "Saved kit…" (`40039-40044`).
Fix: Reuse the setup wizard's paired colour-picker + validated hex component; make font pairing a dropdown of the real catalogue and tone a `TONE_META` select; relabel locks in plain language; report which submitted values were ignored instead of blanket success.

**[F-11] ✅ DONE (PR #1085) — Bulk-export form: a quality slider with no value readout, format keys as jargon** — `low` / `quick-win`
Affects: `/export/<run_id>`
What the user hits: The Quality control is a bare range input — the user can't see whether they picked 90 or 45 — and the format checkboxes are raw codec labels (PNG/JPG/WebP/AVIF) with no guidance about which Instagram or Facebook wants; only JPG being pre-checked hints at a default.
Evidence: `web.py:54233-54234` — `<input type="range">` with no `output`; `bulk_export.js:15/117` read `.value` only; format checkboxes built from engine keys (`54218-54222`).
Fix: Add a live value label beside the slider and one-line plain-English hints per format ("JPG — smallest, works everywhere; PNG — sharpest text").

**[F-12] ✅ DONE (PR #1085) — Hidden wall cards are listed as raw internal keys instead of card names** — `low` / `quick-win`
Affects: `/public-wall`
What the user hits: The "Hidden cards" table renders each excluded card as its internal `card_key` in a `<code>` tag (a run-id:card-id compound), while the "Cards on the wall" table above shows friendly titles and meet names. A volunteer who hid three cards sees only opaque ID strings, making "Show again" a guessing game.
Evidence: `web.py:49677-49685` emits `<code>{key}</code>` straight from `sorted(excluded)`, next to a "Show again" button; the visible-cards table (`49664-49675`) shows `title`/`meet_name`.
Fix: Resolve each excluded key to its card title and meet name (the `wall_cards` helper already loads this) and show the same columns, falling back to the key only when the run no longer exists.

**[F-13] ✅ DONE (PR #1085) — Footer HUD (build hash, per-second UTC clock) and a public "Developer access" operator link sit in customer chrome** — `low` / `quick-win`
Affects: `_layout` footer (every page), `/developer` — merges the home-nav HUD finding and the developer-login finding
What the user hits: Every page — including the marketing landing — ends with a monospace HUD showing a live clock, "Online/Offline", a deployment Build identifier and a per-second UTC clock, plus a "Developer access →" operator sign-in link on the home footer. None helps a volunteer post content; it reads as internal tooling. For the operator the flow is also a dead end (visiting `/developer` while signed in, or logging in, both redirect to Create).
Evidence: `web.py:14158-14184` HUD with Build/UTC; `14509-14536` ticks both clocks every second; `14128-14130` "Developer access →" link; `37178-37179`/`37193-37196` redirect the operator to `make_page`.
Fix: Collapse the HUD to a single "All systems operational" link to `/status` (build/UTC belong on the Developer settings section); move "Developer access" off the customer landing footer; default the post-login redirect to the Developer section.

**[F-14] ✅ DONE (PR #1085) — "Developer sign-in →" link is offered to every customer on the login page** — `low` / `quick-win`
Affects: `/login`
What the user hits: The standard customer login page always appends a "Developer sign-in →" link. A non-technical volunteer who can't log in will plausibly try it and land on an "Operator" page demanding operator credentials they don't have — a confusing dead end on the most stress-prone page. The home footer already exposes the same link for the operator.
Evidence: `web.py:36629-36633` unconditionally appends the `developer_login` link; the operator page (`37140-37147`) is headed "Developer sign-in… for the operator running this deployment".
Fix: Remove the developer link from `/login` (the footer link already covers the operator) or gate it behind an `?operator=1` param.

---

### G. Consistency across surfaces

**[G-1] Reject exists only as a bulk action; there is no per-card Reject, and rejected cards vanish into a state with no tab, count, or filter** — `medium` / `moderate` (confirmed live)
Affects: `/review/<run_id>` — merges the review-flow and live-walkthrough findings
What the user hits: The per-card flow was redesigned approve-only (cards show only Approve / Re-queue / Inspect + three emoji reactions), yet the bulk bar still offers Reject. To dismiss one obviously-wrong card the volunteer must discover that the checkbox drives a separate bulk bar. The filter tabs are All/Queue/Approved only, `?wf=rejected` falls back to "show all", the stat block omits rejected, and the live recount writes to an element that doesn't exist on this page. The home-page marketing mock even shows Edit/Reject/Approve on every card.
Evidence: `web.py:22794-22796` bulk `op='rejected'`; `21909-21911` restricts the filter to ''/queue/approved ("Reject was removed from the review flow entirely"); tabs only All/Queue/Approved (`22369-22373`); `mhRecountReview` sets `mh-wf-n-rejected` which exists nowhere else (`15461`); per-card actions render only Approve + Re-queue (`3585-3598`); observed live — card strap shows only Approve/Re-queue/Inspect + reactions.
Fix: Either remove Reject from the bulk bar to match the approve-only design, or make rejection first-class (a Rejected tab with a live count and a bulk "Re-queue"); reconcile the marketing mock; reconsider whether three emoji reactions per card earn their space.

**[G-2] Four differently-named surfaces render the same run history, and Activity/status are duplicated inside Settings** — `medium` / `moderate`
Affects: `/activity`, `/activity/feed`, `/season`, Settings → Activity/Status — merges the run-history and activity/status-mirror findings
What the user hits: A volunteer's meet history appears as "Runs table" (`/activity`), "Feed" (`/activity/feed`), "My Season" (`/season`, a nav item), and again as a table inside Settings → Activity — four lenses with different names and capabilities (delete on several, approvals only in the feed, celebration only in Season). System status likewise renders at both `/status` and `/settings/status`. Users must learn which one to open for which job.
Evidence: `web.py:19764-19772` (`/season` is a lens on the same runs); `19411-19425` (Runs/Feed toggle); `28993-29005` (Settings run table with per-row delete); `28936-28940` (Settings activity "Mirrors /activity"); `27328-27334` (`/status` and `/settings/status` render the same section).
Fix: Consolidate to one Activity surface with view tabs (Table / Feed / Season story); make the Settings tiles link to the canonical `/activity` and `/status` instead of maintaining mirror renderers.

**[G-3] Brand management is fragmented across three overlapping pages that edit the same profile through different data models** — `high` / `large`
Affects: `/organisation`, `/organisation/setup`, `/brand`
What the user hits: Three surfaces edit the same brand: the "Organisation & brand" tile → `/organisation/setup` (slot palette, per-link capture, logo grid); the "Brand platform" tile → `/brand` (kits, locks, approver rules); and many in-app links (configure page, home CTAs, empty states) → the legacy `/organisation` (2-colour picker, a different capture engine, in-memory previews). A volunteer cannot tell which is authoritative, and edits on one don't show on another. The setup page even permanently brands itself "First-run setup / Tell us about your club" for long-standing clubs.
Evidence: `web.py:27932-27945` (two adjacent tiles → `organisation_setup` / `brand_home_page`); many links target `organisation_page` (`18627, 20817, 20851, 29741, 40328, 40341, 45314, 49252, 55326`); `41230-41231` hardcodes "First-run setup".
Fix: Pick one canonical brand home (setup is most complete), fold the still-relevant legacy `/organisation` sections into it or Settings, repoint every `organisation_page` link, and rename the hero contextually ("Your organisation" when a profile exists).

**[G-4] ✅ DONE (PR #1082) — Colour pickers on `/organisation` are a silent no-op once a palette has been captured** — `high` / `quick-win`
Affects: `/organisation`
What the user hits: The legacy page offers Primary/Secondary colour pickers and a strip promising "This palette flows into every caption graphic and motion reel." But those inputs write only the legacy `brand_primary/secondary` fields, which lose to any AI-extracted or setup-confirmed palette in the resolution order. Any club that went through default AI setup has `brand_palette_extracted` set, so a volunteer who changes colours here sees "Organisation saved." while every card and reel keep the old palette — a silent no-op that erodes trust and wastes retries.
Evidence: `web.py:36066-36080` (colour inputs + the "flows into every graphic" claim); save writes them straight to `brand_primary/secondary` (`35493-35497`) and flashes "Organisation saved." (`35584`); `club_profile.py:347-355` — `get_brand_kit()` resolves `effective_palette(manual, extracted)` first and only falls back to `brand_primary/secondary` when both are empty.
Fix: Make these inputs write to `brand_palette_manual` (the slot that wins), or replace them with a read-only swatch row + an "Edit brand colours" link to the setup palette section. Never show an editable control whose value is known to be overridden.

**[G-5] Duplicated voice-training UI on `/organisation`: two "Analyse voice" buttons, two identical caption textareas, and the same preview card rendered twice** — `medium` / `moderate`
Affects: `/organisation`
What the user hits: The page has a standalone "Analyse voice from past posts" card (analyses without saving) AND a second "Voice examples" card inside the save form with its own textarea (also named `voice_examples`) and its own "Analyse voice" button (analyses AND saves). The same "Voice profile preview" panel is injected after both, so the identical block appears twice; the first-built variant is dead code. A volunteer has no way to know which same-labelled button to use or why results differ.
Evidence: `web.py:36008-36017` vs `36134-36144` (two `voice_examples` textareas + two analyse buttons); `{voice_profile_html}` interpolated at both `36020` and `36146`; the panel built at `35710-35749` is overwritten at `35886` before render (dead code).
Fix: Keep one voice-examples textarea and one "Analyse voice" action (persisting immediately), render the preview once, and delete the dead first-built panel.

**[G-6] Draft cards use a click-to-cycle status pill (with right-click-only reset) while the rest of the app uses explicit Approve buttons** — `medium` / `moderate`
Affects: `/drafts/<pack_id>` (and stub card pages)
What the user hits: Run-review and spotlight rows use labelled Approve / Re-queue buttons; stub draft cards instead show a small pill whose text is the raw status word ("queue"/"approved"), toggling on click and resetting only via right-click — undiscoverable, unavailable on touch, and explained only in a tooltip. A "rejected" style exists but no interaction can set it. Same content in two places, different vocabulary, states and gestures.
Evidence: `stubs.py:624-631` pill with title "Click: queue ↔ approved. Right-click to reset"; `550-554` label is the raw status word; `687` `NEXT` map has no path INTO "rejected"; `714-718` binds reset to `contextmenu`; run/spotlight rows use `_render_wf_actions` (`web.py:3543`).
Fix: Replace the pill with the same Approve/Re-queue button strip used on run cards (shared component), keep status as a badge not a control, and drop the right-click gesture.

**[G-7] Two different features are both called "reel", and the Video Studio has no nav highlight** — `medium` / `quick-win`
Affects: `/video`, `/pack/<run_id>`
What the user hits: The pack page builds a "Meet reel" from approved result cards; the Video Studio builds an "AI reel" from uploaded race footage. Same word, different inputs, pages and engines — a volunteer told to "make the reel" has no cue which is meant, and neither surface cross-links. The studio is invisible in the nav (deliberately) so it's reachable only via a Create tile; once inside, `active='video'` matches no nav item, so nothing is highlighted.
Evidence: `web.py:43078` ("Meet reel") vs `11868` ("AI reel"); `13992-13996` nav comment; `55389` `_layout(...,active='video')` while the nav tests only home/create/media/elements/season/research.
Fix: Rename one flow ("Footage reel" / "Meet recap reel"), add a cross-link on each, and make `active='video'` highlight Create so the studio keeps a home in the IA.

**[G-8] A third, drifted copy of the reel generator lives on the All-recommendations page with wrong copy and a broken portrait label** — `low` / `quick-win`
Affects: `/pack/<run_id>/grouped`
What the user hits: The grouped page has its own "Generate reel from this meet": no composer (fixed top 3), no "All 4 formats", copy promising a "15-second" reel (the actual default is ~16.5s), and a dims lookup that omits "portrait" so the portrait cut shows an empty size caption. Volunteers who learn the reel on one page find a different, less capable version on the other.
Evidence: `web.py:45035` ("15-second") vs `5258-5260` (≈16.5s); `45092` `dims` has no "portrait" key while the chips iterate it (`45109`), so `dims['portrait']` is undefined (`45124`).
Fix: Reuse the shared `generateReel`/`mhRenderReel` functions and `_MOTION_FMT_DIMS` on the grouped page, or link the grouped reel card to the pack composer.

**[G-9] Two parallel, differently-named consent stores with no signpost to the authoritative one** — `medium` / `large`
Affects: Settings → Athletes & consent (`/athletes`) vs `/organisation/consent`
What the user hits: Settings' "Athletes & consent" links to `/athletes`, which sets per-athlete "permission levels" via the safeguarding module. The orphaned `/organisation/consent` records granted/refused/revoked decisions with lawful basis via a separate compliance registry. An officer who finds one has no way of knowing the other exists or which is legally authoritative — a real compliance-integrity risk, not just a UX wrinkle.
Evidence: `web.py:29321` links to `athletes_page` (imports `mediahub.safeguarding`, `57885`); `/organisation/consent` uses `mediahub.compliance.consent.ConsentRegistry` (`25929`).
Fix: Consolidate to one consent surface, or at minimum cross-link the two and state which is the record of truth.

**[G-10] Welsh mode is only half-translated — nav items and the core Approve/Reject/Export verbs stay English** — `medium` / `moderate`
Affects: global chrome, review / content-pack page
What the user hits: Even a volunteer who discovers `?lang=cy` gets an incoherent bilingual app. Only a handful of nav strings are wired to the translator; "Media library", "Elements", "My Season", "Research", "Help", the notifications header, and the entire page body — including Approve / Reject / Export — stay hardcoded English. The Welsh catalogue even defines `action.approve/reject/export` keys that are never referenced. For a Welsh-club wedge, it reads as broken.
Evidence: `t()` is invoked at only ~7 sites, all in the nav shell (`13987-14107`); adjacent nav items hardcoded (`13997-13999`, `14104`); the `action.*` keys (`ui_catalogue.py:54-59`) have zero `t('action.*')` calls.
Fix: Translate the whole chrome (wire the remaining nav labels and the review Approve/Reject/Export through `t()`, adding keys to `_CY`), or gate the language switcher to locales whose catalogue covers the primary flow.

**[G-11] Setting "Caption language" to Welsh silently flips the interface to (half-)Welsh, with no hint the two are coupled** — `medium` / `moderate`
Affects: `/settings` (organisation)
What the user hits: `_ui_locale()` falls back to the org's primary caption language when that locale has a UI catalogue, so a club that sets the Settings "Caption language" picker to the monolingual "Cymraeg (Welsh)" option finds its whole interface silently switch to the partial Welsh chrome on the next page load — even though they only meant to change caption output. Nothing warns that the picker also changes the display language.
Evidence: `web.py:13544-13551` — with no `?lang`/session pin, `_ui_locale()` returns `primary_language_for(profile)` if `has_ui_locale()`; the picker is saved at `36055-36056`; a monolingual Welsh option exists (`languages.py:197-199`).
Fix: Decouple interface language from caption language (give the interface its own explicit setting defaulting to English), OR add a clear note on the Caption-language field that choosing Welsh also switches the interface, plus an override.

**[G-12] Reloading the presenter console mints a new session + code, silently desyncing the live audience projector** — `high` / `moderate`
Affects: `/documents/<id>/present`
What the user hits: `document_present` calls `create_session` on every page load, so any reload (accidental refresh, laptop lid-close/wake) creates a new session with a NEW pairing code. The already-open audience view and paired phone keep polling the OLD session while the reloaded console drives the NEW one — so Next/Prev stops moving the projector with no warning. Recovering means re-opening the audience view and re-pairing.
Evidence: `web.py:59932` calls `create_session` with no check for an existing live session; `presenter.py:164-165` always mints a fresh `session_id` + `pairing_code` on every GET.
Fix: Reuse an existing non-ended session for the same doc+owner on reload (resume rather than remint), or warn before discarding a live session; keep the audience URL and pairing code stable across console reloads.

**[G-13] ✅ DONE (PR #1097) — Audience autoplay advances every 6s, ignoring the session's configured 8s cadence** — `low` / `quick-win`
Affects: `/present/<session_id>`
What the user hits: When the presenter toggles Autoplay, the audience view advances on a hardcoded 6-second interval, but the session model stores `autoplay_seconds` (default 8.0) and even exposes it in `public_state`. A kiosk/foyer loop runs faster than configured, and any future per-deck timing setting is silently ignored.
Evidence: `web.py:17732` — `setInterval(..., 6000)`; `presenter.py:60` defines `autoplay_seconds: float = 8.0`, published in `public_state` (`88`) but never consumed by the audience poll.
Fix: Drive the audience autoplay interval from `state.autoplay_seconds` instead of a hardcoded 6000ms.

**[G-14] Busy-button states are reinvented many times instead of the shared MH.btnState helper** — `low` / `moderate`
Affects: app-wide (review, media library, reel, video suite, comments/share, meet-recap)
What the user hits: Every long-running button hand-rolls its own "working" state, so behaviour is subtly inconsistent page to page — some disable the button, some don't; the loading word is spelled "Rendering…" (ellipsis) some places and "Rendering..." (three dots) others. It makes the product feel stitched together.
Evidence: `web.py:4879` "Rendering motion…", `5063` "Rendering reel…", `12246` "Rendering..." (three dots), `6192` "Creating…", `44683` "Saving…" — all ad-hoc; the shared `MH.btnState` (`ui-kit.js:436`) has only 3 references in web.py.
Fix: Standardise on `MH.btnState(btn,'busy'|'idle')` (or one `mhBusy(btn,label)` wrapper) so every action button gets the same disable + label + spinner and one ellipsis spelling.

**[G-15] ✅ DONE (PR #1097) — Signed-in users on the demo preview see both "Sign up — keep your preview" and "Keep this preview in my workspace"** — `low` / `quick-win`
Affects: `/try/<run_id>`
What the user hits: The demo footer renders the "Sign up — keep your preview →" primary button unconditionally, and additionally renders the "Keep this preview in my workspace" claim button when a profile is active. An already-signed-in user sees two near-identical CTAs, one of which leads to an account flow they've already completed.
Evidence: `web.py:50354-50368` — `claim_html` is gated on an active profile but the `signup_page` button renders in all cases.
Fix: When a profile is active, replace the signup button with the claim button (single primary CTA); show the signup CTA only to anonymous visitors.

---

### H. Forms & input handling

**[H-1] ✅ DONE (PR #1082) — Multi-photo upload silently discards all but the first file on any modern browser/phone** — `high` / `quick-win`
Affects: `/media-library` — merges the media-library and PWA findings
What the user hits: The form says "Pick several at once", the input is `multiple`, and the server supports batches ("40 gala photos are one submit") — but the mobile-capture enhancement intercepts every submit when a file is chosen and the browser can downscale (all modern browsers, desktop included), uploads only `files[0]`, and redirects to `?shared=1`. A volunteer selecting 30 gala photos gets 1 uploaded, a banner saying "1 photo added", and 29 silently dropped.
Evidence: `mobile-capture.js:144-148` — `preventDefault` then `processAndUpload(fileInput.files[0])`; `uploadBlob` appends a single file (`86-103`); input is `multiple` (`web.py:45661`), copy "Pick several at once" (`45656`), server reads `getlist('file')` (`46053-46064`).
Fix: In `mobile-capture.js`, skip the intercept when `files.length > 1` (let the native batch submit run) or loop `processAndUpload` over all files and redirect with the real saved/skipped counts.

**[H-2] ✅ DONE (PR #1082) — "Export ZIP" leaves a permanent full-screen "Working on it" overlay** — `high` / `quick-win`
Affects: `/media-library`
What the user hits: The global form binder shows a fixed, z-index 9999, full-viewport loader on every POST submit unless the form opts out (the bulk form doesn't). The bulk bar leaves "Export ZIP" as a native submit so the browser downloads the file — but a `Content-Disposition: attachment` response never navigates the page, and the loader is only hidden on bfcache restore. So after a successful export the page sits behind an opaque blurred scrim saying "Working on it" forever; the volunteer thinks the app crashed and reloads.
Evidence: `web.py:14586-14601` binds a loader to all POST forms (only exempting `data-no-loader`); `16751` `if (action === 'export') return;` (native submit); `47062-47066` responds with an attachment; `9380-9390` the fixed loader; `14693-14696` auto-hides only on `pageshow` with `e.persisted`.
Fix: Exempt download submits from the global loader (add `data-no-loader` to the bulk form / attachment buttons), or auto-hide the loader after a few seconds when the submit target is a file download.

**[H-3] Photo consent/permission state is enforced but impossible to view meaningfully or change** — `high` / `moderate`
Affects: `/media-library`
What the user hits: Every photo defaults to permission "unknown", the table shows the raw snake_case enum ("needs_parental_consent") with no explanation, and bulk Approve silently skips any photo with a consent block or `safe_for_minors=False` ("N skipped (safeguarding)"). Yet the only permission editor rejects anything that isn't footage — there is no UI or API to record consent on a photo. A volunteer holding a signed consent form hits a hard dead end: the photo can never be unblocked except by delete + re-upload.
Evidence: `web.py:45449` renders the raw enum read-only; `models.py:87` default "unknown"; `46982-46987` bulk approve skips as "safeguarding_block"; `55486-55499` the only permission route returns 404 for `type != "footage"`; no other photo permission writer exists.
Fix: Extend the footage permission endpoint (or add a sibling) to photo assets, expose a plain-English permission select per row/asset, and link the "skipped (safeguarding)" toast to the blocked photos so the volunteer can resolve them.

**[H-4] Asset metadata is write-once, though three pieces of UI copy tell users to edit it** — `high` / `moderate`
Affects: `/media-library`
What the user hits: Description, athlete link, venue and tags can only be set at upload time. The AI "auto" badge says "review and edit anytime", the "untagged" badge says "add a description with the swimmer's name", and the empty state's step 2 says "Put the swimmer's name in the description" — but no edit route or UI exists for any of these fields on an existing photo. When AI vision tags the wrong swimmer, the only fix is delete + re-upload.
Evidence: `web.py:45394-45401` (badge copy), `45748-45750` (empty-state), and the whole `/api/media-library` inventory (`46051-53833`) contains no endpoint to update an existing photo's metadata.
Fix: Add an inline metadata editor per asset (a small `POST /api/media-library/<id>/meta` + an edit affordance on the row / a per-asset detail view), and make the "auto" badge open it.

**[H-5] ✅ DONE (PR #1097) — Editing a newsletter or document requires hand-editing raw spec JSON** — `high` / `large`
Affects: `/newsletters/<id>`, `/documents/<id>`
What the user hits: Newsletters and documents hide a raw-spec-JSON textarea behind an "Edit… (advanced — spec JSON)" toggle, so there is NO non-advanced edit path: to fix a typo in a newsletter intro you must edit JSON. For the stated non-technical audience these are generate-only surfaces.
Evidence: `web.py:59249-59252`/`59651-59654` — newsletter/document "advanced — spec JSON" textareas.
Fix: Ship a minimal structured editor (per-section text fields, image pickers, block add/remove/reorder generated from the spec schema) keeping the JSON textarea as the genuine "advanced" escape hatch; start with titles, intro text and links.

**[H-7] ✅ DONE (PR #1082) — "Generate plan" silently discards unsaved events/goals/blackouts** — `high` / `quick-win`
Affects: `/plan`
What the user hits: A volunteer types upcoming events (or uses "Interpret & fill in", which only adds DOM rows), then clicks the big primary "Generate plan". Generate posts only the sport and reloads on success — every unsaved row is wiped and the plan is built from the old persisted inputs, so their meet never appears and their typing is gone. The only protection is a 12.5px status hint saying "review, then Save inputs".
Evidence: `web.py:30015-30023` `mhPlanAddEvent` only appends a DOM row; `30054-30067` `mhPlanSaveInputs` is the sole persistence call; `30147-30157` `mhPlanGenerate` POSTs only `{sport}` then reloads, with no unsaved-input guard.
Fix: Have `mhPlanGenerate` auto-save the current on-page inputs before generating, or block with "You have unsaved inputs — save first?" when DOM rows differ from persisted state.

**[H-8] ✅ DONE (PR #1097) — AI failure on the quick path throws away the prompt the volunteer typed** — `medium` / `quick-win`
Affects: `/free-text/quick-build`
What the user hits: If the LLM errors or is unconfigured when "Generate graphic" is submitted, the handler stashes the error in the session and redirects to the landing page, where the textarea renders empty. A poolside volunteer's carefully written multi-sentence prompt (and photo selections) is gone; they must retype everything to retry.
Evidence: `web.py:33544-33547` catches the provider error, sets a session error, redirects to `free_text_chat_page`; the landing textarea (`33432-33434`) has no value/restoration; the prompt is never stashed back.
Fix: Stash the submitted prompt alongside the error and re-populate the textarea (and re-list attached photo names) on the bounce-back so retry is one click.

**[H-9] The quick path promises "edit the caption… from there" but draft cards have no caption editing** — `medium` / `moderate`
Affects: `/drafts/<pack_id>`
What the user hits: The free-text form says "You'll land on a draft with the graphic rendered — edit the caption, swap the photo, change format, approve, or export from there." On the draft page the caption is plain text with only "Copy caption" and "Create graphic"; the caption/assist/tone APIs return 400 `unsupported_type` for anything that isn't an athlete-spotlight pack. A volunteer wanting to fix one word must copy the caption into another app.
Evidence: `web.py:33444-33445` the promise; `stubs.py:660-678` card actions offer no caption-edit; `web.py:34462-34463`/`34536-34537` both return `unsupported_type` unless `source=='athlete_spotlight'`, and quick packs carry `source='quick'`.
Fix: Add inline caption editing (textarea + `update_pack`, which exists) to every stub pack card and extend the tone/assist endpoints beyond the spotlight-only guard — or soften the promise until it's true.

**[H-10] Caption editing is hidden behind a gear labelled "Inspect", and its edit history is unreachable from review** — `medium` / `moderate`
Affects: `/review/<run_id>`
What the user hits: The only way to read or edit a card's caption on review is the "⚙ Inspect" button — a label that says nothing about captions (the row never displays the caption). Inside, Save writes into three internal tone slots with a tiny "Caption saved"/"Save failed" status ("Save failed" gives no reason), and overwriting is permanent — the revisions/diff/restore panel is mounted only on the Content builder.
Evidence: `web.py:22559-22566` entry point "⚙ Inspect"; `saveCaption` (`6865-6884`) writes tone-slot headlines with only "Caption saved"/"Save failed"; the revisions routes (`54629-54671`) surface only via the builder's history panel.
Fix: Rename to "Edit card" (or split "Edit caption"), show the saved caption on the row once one exists, include the failure reason, and mount the revisions panel (or a one-step "Restore previous caption") inside the drawer.

**[H-11] "Use in next caption" produces a caption that is never saved anywhere, with an off-brand "heuristic mode" error** — `medium` / `moderate`
Affects: `/review/<run_id>`
What the user hits: Inside "Why this card?", "Use in next caption" asks the AI to weave the reasoning into a fresh caption — but the result renders in a read-only panel whose only action is Copy. It is not persisted, and the place a caption can be saved is the separate Inspect drawer, so using it properly means generate → Copy → open Inspect → paste → Save (5 steps). When no AI key is set the panel says "AI is in heuristic mode. Contact your administrator to enable AI." — internal vocabulary, unlike the standard no-key copy elsewhere.
Evidence: `web.py:14649-14674` builds a caption div + Copy only; nothing POSTs to `set_edits`; `14645-14646` hardcodes "AI is in heuristic mode…" vs "AI captions are unavailable on this deployment." at `23779`.
Fix: Add a "Save to card" action beside Copy that persists via the existing `set_edits` route, and align the no-key message with the standard wording.

**[H-12] The "Meet digest" newsletter offers no way to pick which meet** — `medium` / `moderate`
Affects: `/newsletters`
What the user hits: The Meet digest tile promises "One meet: the standout swims…", but the generate call sends only format, date range and `with_ai` — no meet selector, so which meet you get is decided by whatever falls in the date range. A volunteer wanting a digest of last Saturday's gala when two meets happened that month cannot choose it. The Documents page proves the pattern is easy — its "Meet programme" tile has a per-run `<select>`.
Evidence: `web.py:17621-17624` posts only `{format, range, with_ai}`; `59141-59151` derives dates with no `run_id`; contrast `59511-59516` (documents `<select id="prog-run">`).
Fix: Add the same meet `<select>` to the Meet digest tile (pass `run_id` through), defaulting to "latest meet in range".

**[H-13] There is no brand-kit choice at upload/configure — using a sponsor/event kit means flipping the org-wide default back and forth** — `medium` / `moderate`
Affects: `/upload/configure`, `/brand`
What the user hits: The point of multiple kits (sponsor co-brand, event sub-brand) is applying a different livery to a specific pack, but runs always resolve the org's default kit, and configure offers only raw one-off colour pickers. A volunteer producing a sponsor-branded gala pack must: Settings → Brand platform → "Make default" on the sponsor kit → run the pack → return → restore the club kit — and nothing at upload even says which kit will be applied.
Evidence: `web.py:39461-39473` — `_resolved_kit_for_run` uses the default kit; configure form (`20848-20868`) renders only primary/secondary/accent colour inputs, no kit selector.
Fix: Add a "Brand kit for this run" dropdown to configure (default = current default, options = all kits), store the choice on the run, and show the resolved kit name/swatches before the pipeline runs.

**[H-14] Performance logging can't record which platform or which post, though the backend supports both** — `medium` / `moderate`
Affects: `/plan/analytics`
What the user hits: The manual logging form asks only for post type, date, optional hour and five raw counts — no platform field and no link to the draft that was posted, even though the store and API accept `platform` and `pack_id`. A volunteer who posted the same card to Instagram and Facebook logs two indistinguishable rows, and the "recent" list shows only type + date + score.
Evidence: `web.py:31106-31111` omits `pack_id`/`platform` while the API accepts them (`30919-30921`) and the store models them (`analytics/store.py:52-53`); the recent row (`31044-31050`) renders only type/date/score.
Fix: Add a platform select and an optional "which draft?" picker (prefill both when arriving from a draft), and show platform in the recent list.

**[H-15] Pronunciation-lexicon and voice-consent form errors are silently swallowed** — `medium` / `moderate`
Affects: `/settings/audio`
What the user hits: The "Name pronunciation" add/remove and "Voice cloning" grant/revoke controls are plain form posts. On a `ValueError` the handler builds a 400 error payload — but for a non-XHR form post `_audio_back_or_json` ignores both the payload and the status and returns a plain redirect. The volunteer submits an invalid entry, the page reloads, nothing was added, and no message says why. There is also no success confirmation.
Evidence: `web.py:28499-28508` — `_audio_back_or_json` returns a bare redirect for non-JSON callers, discarding the payload and 400 status passed at `28588-28590` and `28709-28711`.
Fix: Make `_audio_back_or_json` carry the error/success message through the redirect (a `?status=` code rendered as a banner, like `_typography_banner`).

**[H-16] AI font pairing suggests a pairing the user cannot apply, and failure shows raw exception text** — `medium` / `moderate`
Affects: `/settings/typography`
What the user hits: "Suggest a pairing" ends on a result page listing headline/body/numeral families with a reason and a single "Back to typography" link — there is no "Use this pairing" action and no persistence, so the advice cannot be acted on. On failure (e.g. no AI provider) the page prints the raw exception string.
Evidence: `web.py:28471-28481` — result body + a back link only, no persistence in the route (`28445-28481`); `28460-28461` renders `AI pairing is unavailable: {str(e)[:200]}`.
Fix: Add an "Apply this pairing to my brand" button that persists the trio to the brand kit, and map provider-not-configured exceptions to plain-language copy.

**[H-17] Correction and erase forms fail silently — bad input bounces to `/privacy` with no message and loses what was typed** — `medium` / `moderate`
Affects: `/privacy` (Erase an athlete / Correct a published card)
What the user hits: If the officer submits the correction form with a run/card id that doesn't match the expected shape (easy with a copy-paste that grabs a stray space), the server redirects back to `/privacy` showing nothing — no error, no explanation, and the reason text they typed is discarded. They can't tell whether it worked or why nothing happened.
Evidence: `web.py:26412-26417` — validates with `re.fullmatch` and on mismatch redirects with no flash and no preserved input (the run/card ids have no client-side pattern); `26354-26357` similarly redirects on empty name.
Fix: On validation failure re-render `/privacy` with a styled error ("That run/card id doesn't look right — copy it from the run page") and preserved field values.

**[H-18] Upload validation is contradictory: server rejections are dead-end pages, the client preview contradicts the server, and it flags supported `.xlsx` as "Unknown"** — `medium` / `quick-win`
Affects: `/upload` — merges the two upload-validation findings
What the user hits: All three server-side rejections (no file, unsupported extension, empty file) replace the whole upload page with a one-line error card — no form, no dropzone, no "try again". Drag-and-drop bypasses the file picker's `accept` filter, so a dropped `.docx` lands here in practice. Meanwhile the instant preview tells users with an unrecognised extension "we'll try every adapter; results may be partial" (implying it'll proceed, though the server 400s), and its `inferFormat` has no `.xlsx` branch — so a legitimate Excel file (advertised in the lede and `accept` attr) is greeted with "Unknown extension".
Evidence: `web.py:20144-20148`/`20169-20174`/`20176-20181` return a bare error card with no form; `14754-14762` drop handler bypasses `accept`; `20566` fallback "results may be partial" vs `20168-20174` 400; `inferFormat` (`20554-20566`) omits `.xlsx` (in `accept` at `20495`).
Fix: Re-render the full upload page with the error inline above the dropzone (the client `showError()` at `20540` exists); make `inferFormat` mirror the server allowlist exactly (add a "good" `.xlsx` branch, turn the unknown-extension branch into an honest blocker that disables submit).

**[H-19] ✅ DONE (PR #1097) — "Make clip" button stays enabled during the long clip-maker run — double-clicks create duplicate projects** — `medium` / `quick-win`
Affects: `/video`
What the user hits: The Make clip handler never disables its button while the synchronous analysis runs (tens of seconds). An impatient volunteer who clicks again fires a second clip-maker run and ends up with duplicate projects in "Your clips", each needing its own render/approve — and there's no delete button on project tiles to remove the extra.
Evidence: `web.py:12153-12174` — `vs-make` sets status text but never `btn.disabled` (contrast `vs-reel-make` at `12187`); `55651-55659` every POST creates a new project unconditionally; `12219-12225` project tiles have no delete control.
Fix: Disable the Make clip button (show the existing `.btn.loading` style at `9485`) for the request duration, re-enabling in both `.then` and a new `.catch`.

**[H-20] 2FA setup demands manually typing a raw 32-character secret (no QR) and issues no recovery codes** — `medium` / `moderate`
Affects: `/account/2fa`
What the user hits: The 2FA page prints the raw base32 secret and the `otpauth://` URI as plain text and says "add this secret to your authenticator app". Non-technical volunteers expect a QR; hand-typing 32 chars from desktop to phone is error-prone. Worse, enabling generates no backup/recovery codes and no recovery path exists — a volunteer who loses their phone is permanently locked out (password reset parks on the TOTP prompt).
Evidence: `web.py:36815-36827` renders the secret in `<code>` and the URI as muted text with no image, with no QR here; no "recovery/backup code" in `auth.py`; `login_post` always routes TOTP users to `/login/2fa` (`36694-36696`).
Fix: Render the URI as a QR (the module exists), keep the secret as a copyable fallback, generate 8–10 one-time recovery codes at enable time, and accept a recovery code on `/login/2fa`.

**[H-21] ✅ DONE (PR #1097) — Adding a board idea works only by pressing Enter — there is no visible Add button** — `low` / `quick-win`
Affects: `/plan/board`
What the user hits: The Ideas column's "New idea…" input submits solely via an Enter keydown; nothing on screen indicates how to confirm, and a volunteer who types an idea and clicks elsewhere loses it silently (empty-title submits also return silently). On mobile soft keyboards the action key isn't always an obvious "Enter".
Evidence: `web.py:30826-30830` — a lone `<input>` with `onkeydown` and no button; `30874-30877` `mhBoardAdd` returns silently on empty input.
Fix: Add a small "Add" button beside the input (sharing `mhBoardAdd`) and a hint "press Enter to add"; show a status message when the title is empty.

**[H-22] ✅ DONE (PR #1097) — The remote landing has no length check — a typo submits and burns a shared-IP failure attempt** — `low` / `quick-win`
Affects: `/remote`
What the user hits: The code-entry field accepts up to 6 characters but Connect fires with no client-side validation, so a partial or mistyped code navigates to `/remote/<code>`, fails the lookup, increments the per-IP failure counter, and shows "Code not found". Because the rate-limit budget is shared across a venue's NAT, careless typos erode everyone's remaining attempts.
Evidence: `web.py:60070-60071` — Connect is `location.href='/remote/'+value.toUpperCase()` with no length/format guard; `60091` a failed lookup calls `_remote_code_failed()`.
Fix: Disable Connect until 6 valid characters are entered and validate format client-side, so obvious typos never reach the server or consume the shared budget.

**[H-23] ✅ DONE (PR #1097) — "Build spotlight post" with nothing approved lands on a full-page 400 error** — `low` / `quick-win`
Affects: `/spotlight/<run_id>/<swimmer_key>`
What the user hits: The build button is always active; if the user hasn't approved any achievements, the POST navigates to a bare error page ("No achievements approved yet…") with a back link, losing their tone selection and page position. The precondition is known client-side (the page renders the approved count).
Evidence: `web.py:32844-32848` — the always-enabled build form; the empty-approved branch returns a full `_layout` 400 (`32209-32216`); the inline helper copy already exists at `32850`.
Fix: Disable the build button while 0 achievements are approved and show the existing helper line as the reason; keep the server check as a fallback.

---

### I. Mobile & accessibility

**[I-1] ✅ DONE (PR #1085) — Scheduling drafts and moving board cards is drag-and-drop only — impossible on phones and keyboards** — `high` / `moderate`
Affects: `/plan/calendar`, `/plan/board`
What the user hits: The only way to set/move/clear a draft's planned date is HTML5 drag-and-drop onto a calendar cell; the only way to move a board card between columns is drag between columns. HTML5 drag events don't fire from touch, and no polyfill or click alternative exists (tapping a chip navigates away). A volunteer posting from a poolside phone cannot schedule anything or progress a board card at all; keyboard-only users are equally locked out.
Evidence: `web.py:30234` `set_planned_date` reachable only via the drop handlers (`30450-30468`); board moves only via `mhBoardDrop` (`30891-30896`); the click listener (`30470-30473`) navigates to the draft.
Fix: Add a non-drag path — a "Plan for…" date field on the draft chip posting to the same schedule API, and "Move to →" buttons (or a select) on board cards; keep drag as the desktop enhancement.

**[I-2] ✅ DONE (PR #1085) — The review page scrolls horizontally on a phone** — `medium` / `quick-win` (confirmed live)
Affects: `/review/<run_id>` (375px viewport)
What the user hits: At 375px the whole review page overflows sideways by ~25px, so the page wobbles horizontally while the volunteer scrolls. The overflow comes from unwrapped monospace token strings in the parse-notes/diagnostics sections (one span measures 1159px wide) and a 398px table.
Evidence: observed live — `document.scrollWidth` 400 vs `innerWidth` 375; widest offenders `SPAN.mh-tok-string` w=1159 and `TABLE` w=398 (from the parse note `Meet course is mixed: {'SC': 25, 'LC': 5}`).
Fix: Add `overflow-wrap:anywhere` (or `overflow-x:auto` on the parse-notes/diagnostics containers) for `.mh-tok-string` and wrap wide tables in their own scroll container so the page body never scrolls sideways.

**[I-3] ✅ DONE (PR #1085) — Compliance tables are non-responsive multi-column tables with inline action forms — unusable from a phone** — `medium` / `moderate`
Affects: `/organisation/athlete-rights`, `/organisation/consent`
What the user hits: Volunteers act on data requests from poolside phones, but the athlete-rights table is a 7-column raw `<table>` with action forms in the last cell, and the consent registry is a similar 5-column table. Neither uses the responsive stacking the roster table uses, so on a narrow screen columns and action buttons overflow off-screen.
Evidence: `web.py:26205-26210` (7-column table, cells `26200-26203` carry no `data-label`); `25953-25960` (5-column registry) — whereas the roster table tags cells with `data-label` (`57910-57919`).
Fix: Apply the roster table's responsive treatment (`data-label` cells + stacking, or an `overflow-x` wrapper) to the athlete-rights and consent tables.

**[I-4] ⚪ N/A (already satisfied) — Export and toolbar buttons are ~24px tall — hard to tap from poolside** — `low` / `moderate`
Affects: `/pack/<run_id>`, `/pack/<run_id>/grouped`
What the user hits: Nearly every action on the export surface — per-card Download .zip, the caption/graphic/motion toolbar, grouped-page copy buttons — is styled at 11–12px with 3–6px vertical padding (~22–26px tap targets, well under ~44px). Dense rows of tiny adjacent buttons invite mis-taps (hitting "Generate motion" instead of "Copy caption").
Evidence: `web.py:6501-6503` (toolbar `font-size:11px;padding:4px 10px`); `42971` (per-card download); `44910-44915` (grouped copy buttons).
Fix: Add a mobile media query raising `min-height` to 44px and spacing on `.btn` within card toolbars and the export row (the layouts already flex-wrap).

**[I-5] ✅ DONE (PR #1085) — On a phone the sticky review filter bar can occupy a third of the viewport above the queue** — `low` / `quick-win`
Affects: `/review/<run_id>`
What the user hits: The filters bar — six selects, Clear, a count, and the Expand-all toggle — is `position:sticky`. On ≤700px screens it pins to `top:0` and each select grows to 50% width, so the nine controls wrap into ~four rows that stay fixed over the content while scrolling, on the same screen where the floating action dock claims the bottom edge.
Evidence: `web.py:22692` `.filters-bar{position:sticky;top:56px}`; the mobile override (`22724-22726`) sets `top:0` and `select{flex:1 1 calc(50% - 8px)}`; the bar holds 6 selects + Clear + count + "Expand all reasoning" (`22772-22783`).
Fix: On small screens collapse the dropdowns behind a single "Filters" disclosure (keeping count + Clear visible), or make the bar non-sticky on ≤700px.

**[I-6] ✅ DONE (PR #1085) — The header notification `role=dialog` never moves focus into the panel (no trap), unlike the app's own modal helper** — `medium` / `quick-win`
Affects: global header (every signed-in page)
What the user hits: A keyboard/screen-reader user who opens the notifications bell hits a control announced as a "dialog", but focus stays on the bell and Tab walks them backwards into the page nav instead of into the notification list. The app already has a correct focus-trapping modal (used by the "?" overlay), so this is an adoption gap.
Evidence: `web.py:14049` panel has `role="dialog"` but its controller `setOpen` (`14417-14435`) only sets `hidden=false` with no `focus()` and no Tab trap; compare `MH.openModal` (`14794-14828`) which focuses, traps and restores.
Fix: Route the notification popover through `MH.openModal`, or (since it's really a non-modal popover) drop `role=dialog` for a listbox/menu pattern and move focus to the first item on open.

**[I-7] ✅ DONE (PR #1085) — The install chip's dismiss (×) is mouse-only; keyboard users can't dismiss it and Enter always installs** — `medium` / `quick-win`
Affects: global install chip
What the user hits: The "Install MediaHub" / iOS A2HS chip is one button with a × drawn inside. Dismissal is detected via `e.target === close`, which only happens on a mouse click on the × span. A keyboard user tabbing to the chip and pressing Enter always triggers install, and the × is `aria-hidden` with no separate control — so there's no keyboard path to dismiss the persistent chip.
Evidence: `pwa-install.js:58-65` branches on `e.target === close`; the chip is a single `<button>` (`42`) and the × span is `aria-hidden='true'` with no role/label (`51-55`).
Fix: Make the × a real nested `<button aria-label='Dismiss'>` (stop propagation) separate from the install button, so it's keyboard-focusable and Enter on the chip installs while Enter on the × dismisses.

**[I-8] ✅ DONE (PR #1085) — The Convert menu is an unlabelled injected div with no Escape or focus handling** — `low` / `quick-win`
Affects: `/media-library`
What the user hits: The per-row "⇄ Convert" button injects a positioned div of format buttons on click, with no role/aria, no `aria-expanded` on the trigger, no Escape-to-close (only clicking elsewhere), and no focus moved into it — so a keyboard/screen-reader user gets no announcement and no keyboard dismissal. Conversion errors are shown only by rewriting a button's label in place.
Evidence: `web.py:16826-16833` creates the menu with no role/aria and no `focus()`; the only close path is a document click listener (`16816-16821`); trigger (`45455-45457`) has no `aria-haspopup/aria-expanded`.
Fix: Give the trigger `aria-haspopup/aria-expanded`, the menu `role="menu"`, move focus to the first item on open, close on Escape returning focus to the trigger, and surface errors via `MH.toast`.

**[I-9] ✅ DONE (PR #1085) — Pipeline stage announcements aren't exposed to screen readers** — `low` / `quick-win`
Affects: `/runs/<run_id>`
What the user hits: During the multi-minute pipeline the visible status line is updated continuously by JS — including the terminal "3 moments found — ready to review" and "Something went wrong" — but the element has no `aria-live` region, so screen-reader users hear nothing as the run progresses or completes. Only the bare percent counter is `aria-live`.
Evidence: `web.py:21449` the stage `<span>` sits in a `div.strap.live` with no `aria-live`/`role=status` (the "live" class is CSS-only), while `21451` gives `aria-live="polite"` only to the percent readout.
Fix: Add `role="status" aria-live="polite"` to the stage container (mirroring the from-URL card at `20341`, which does this correctly).

---

### J. Dead ends & orphaned features

**[J-1] ✅ DONE (PR #1097) — The Video Studio's render/analysis buttons block on synchronous endpoints with no progress for multi-minute waits** — `high` / `large`
Affects: `/video`
What the user hits: Clicking Render holds one HTTP request open for the entire FFmpeg render; Make clip and Direct the reel do the same for ASR + moment analysis; Stabilise runs two-pass vidstab inline. The volunteer sees only a caption swap ("Rendering...") — no progress, no ETA, no way to leave and come back — while the rest of the app renders this class of work through background jobs precisely because (per the code's own comment) proxies kill 30–90s held connections and the button then "does nothing".
Evidence: `web.py:56036-56042` (`render_edl()` inline, no job); `12245-12251` (`renderProject` awaits the sync jpost); `55764-55795`/`55837-55842` (stabilise inline); contrast `53109-53111` docstring warning about held connections.
Fix: Give the Video Studio the same disk-backed job + poll pattern the reel/motion routes use (reuse `_variant_job_save` + `api_reel_job_status` + `MH.renderProgress`): POST returns 202 `{job_id, poll_url}`, the tile shows the branded progress panel, completion flips to the preview.

**[J-2] Video Studio failures surface as browser `alert()`, stuck buttons, or silence — fetch handlers have no `.catch`** — `high` / `moderate`
Affects: `/video`
What the user hits: If the render/clip/AI-reel request fails at the network level (the likely outcome of the sync endpoints above), the promise rejects with no handler: the Render button stays disabled on "Rendering..." forever, and "Analysing footage…" never clears, so the volunteer can't tell whether their clip is coming. When the server does answer with an error, the studio shows it via `window.alert()` or a bare status string; permission-change failures also `alert()`.
Evidence: `web.py:12245-12251` (`renderProject` chain has no `.catch`, errors via `alert`); `12153-12174` (`vs-make` no `.catch`); `12183-12198` (`vs-reel-make` re-enables only in `.then`); `12113-12114` (permission change `alert()`).
Fix: Add `.catch` handlers that re-enable the button and write a styled inline error ("Network error — the render may still be running; reload to check"); replace `alert()`/`confirm()` with the inline error panels/dialogs the pack page uses. (Complementary to J-1: catch handlers + styled errors vs. background jobs.)

**[J-3] No pagination: a big meet renders every card into one page, and deep rows may never get their preview** — `medium` / `large`
Affects: `/review/<run_id>`
What the user hits: The review list renders all ranked achievements with no slice or paging — the code's own note records a 249-card meet producing a ~70,000px scroll. Every row also queues a real-graphic thumbnail at 2 concurrent fetches; a cold render occupies the small render gate, so rows deep in the queue retry a 429 six times then permanently show "Renderer busy — refresh to retry". On exactly the meets where triage matters most, the volunteer scrolls a huge page whose lower half shows placeholder previews.
Evidence: `web.py:22457` renders every ranked achievement unsliced; `22703-22708` documents the ~70,000px wall; the thumb loader caps at `MAXC=2` (`23109`) and gives up after 6 retries (`23121-23126`).
Fix: Page or progressively reveal the queue (25 per page or a "Show next 25" loader) ordered by rank, so thumbnail renders concentrate on the visible page; keep tab counts computed from full run state server-side.

**[J-4] The repurpose-pack output page is a dead end: no copy or download on any artefact, `alert()` errors, three names for one feature** — `medium` / `moderate`
Affects: `/runs/<run_id>/pack/<pack_id>`
What the user hits: The Turn-Into pack promises "edit each caption before using it", but each artefact offers only a "Save edits" button — no copy-to-clipboard and no download, so the volunteer must manually drag-select textarea text to use the recap/thread/newsletter it generated. "Regenerate pack" fires a synchronous LLM request with no loading state after a `confirm()`, and failure surfaces as a raw `alert('Regenerate failed: …')`. The feature is named three ways ("Turn this meet into more" / "Repurpose pack" / "Turn-Into pack") with "artefacts" as the item label.
Evidence: `web.py:44644-44648` (only Save edits per artefact); `44706-44720` (`tiRegenerate`: confirm → sync fetch → alert on failure); naming at `44658`/`44724`/`6983`; "artefacts" at `44661`.
Fix: Add a Copy button per caption block (the `copyText` helper exists) and a download for the newsletter HTML; make regenerate use the async job + inline status the builder has; pick one user-facing name and one item word.

**[J-5] ✅ DONE (PR #1097) — The `/export` hub is a no-CTA catalogue that misdirects users to the wrong page** — `medium` / `quick-win`
Affects: `/export`
What the user hits: The "Export & convert" page — reachable only from a button at the bottom of Help — lists format chips and FFmpeg engine status, with no run picker and no link to any actual export. Its one instruction, "Open a meet's review page to bulk-export its content pack", is wrong: the bulk-export entry lives on the Content builder (`/pack`), not review, so a volunteer following it lands on review and finds nothing.
Evidence: `web.py:54165-54200` renders only chips + engine status + the wrong "review page" copy; `export_run_tool_page` is linked solely from the pack page (`42987`); `export_center_page`'s only inbound link is the Help strip (`18888`).
Fix: Fix the copy to point at the Content builder and add a recent-runs list linking straight to `/export/<run_id>`, or delete the hub page and its Help link.

**[J-6] Plan promises "open the right tool with that idea" but Create links open the tool blank** — `medium` / `moderate`
Affects: `/plan`
What the user hits: The hero's step 3 says "Click Create on an item to open the right tool with that idea", and each ranked item shows a "Create →" button. The link is a bare route to the tool's start page with no parameters — none of the item's title, reasoning, or context carries over, so the volunteer lands on an empty form and must remember and retype what the plan suggested.
Evidence: `web.py:29931` the promise; `29791-29794` `create_link` is `url_for(meta.primary_route_endpoint)` with no query params or seed payload.
Fix: Pass the plan item's title/reason as query params the target tool prefills (seed the free-text field), or soften the copy until seeding exists.

**[J-7] ✅ DONE (PR #1097) — The channel-preview empty state is a dead end while the ad-variants equivalent offers a way out** — `low` / `quick-win`
Affects: `/plan/preview/<pack_id>`
What the user hits: A draft with no cards renders just "This draft has no cards to preview yet." with no link or action, whereas the ad-variants page's identical situation links back to the draft to "Add or regenerate cards". Same product, same condition, one page helps and the other strands the user.
Evidence: `web.py:30594` the preview fallback is a bare `<p>` with no link, vs `31196-31201` where the ad-variants fallback links to `stub_pack_view`.
Fix: Mirror the ad-variants pattern — add "Add or regenerate cards →" linking to the draft in the preview's empty state.

**[J-8] The `/print` catalogue is a dead end, and the run page shows two adjacent "Print" buttons that do completely different things** — `medium` / `quick-win`
Affects: `/print`, `/pack/<run_id>`
What the user hits: The Print & merch reference page lists product chips and says "Open a meet's print tool to proof and export a card" — but contains no link, meet picker, or button to any `/print/<run_id>` tool; its own inbound link is buried in Help. Meanwhile on the run page, "Print & merch…" (the real print tool) sits directly next to "Print / Export PDF" (a `window.print()` of the web page) — two "Print" buttons where the wrong one gives a browser print dialog instead of print-ready PDFs.
Evidence: `web.py:52101-52113` (catalogue is chips only); `print_run_tool_page` linked only from the run page (`42988`, rendered at `43350`); `18890` the sole inbound link is the Help strip; `43350-43352` the two adjacent Print controls.
Fix: On `/print`, list the user's recent meets with "Open print tool" links; on the run page rename "Print / Export PDF" to "Print this page" or move it out of the export row.

**[J-9] Three overlapping ways to publish the same cards, each with different verbs and homes — plus two separate newsletter systems** — `medium` / `large`
Affects: `/public-wall`, `/newsletters`
What the user hits: The public wall and a published newsletter both produce a token-URL public page of the club's approved cards, but they live in different places and name the same action different ways: the wall "Switch[es] on"/"Switch[es] off & revoke[s]", newsletters "Publish"/"Take offline". On top, the app has two unrelated newsletter features (the run page's `/api/runs/<run_id>/newsletter` export and the standalone `/newsletters` composer). A volunteer asking "how do I share results with parents?" faces several near-equivalent answers.
Evidence: `web.py:49750`/`49725` (wall) vs `web.py:59215/59226` (Take offline/Publish); a second run-scoped generator at `44364-44365` alongside `newsletters_home` (`59009`).
Fix: Standardise the publish/unpublish vocabulary across all token-URL surfaces; add a single "Share publicly" chooser (on the review/export flow) explaining when to use the wall vs a newsletter; fold the run-page newsletter export into the composer as a "meet digest for this run" shortcut.

**[J-10] ✅ DONE (PR #1097) — Two full-size Settings tiles lead only to "Coming soon" placeholder pages and still say "Open →"** — `low` / `quick-win` (confirmed live)
Affects: `/settings`, `/settings/scheduling`, `/settings/autonomy` — merges the two "coming soon tile" findings
What the user hits: "Auto scheduling" and "Autonomy" occupy two of the 17 tiles with the same visual weight and the same "Open →" affordance as working features; clicking either costs a page load to reach a single placeholder card with no notify-me and nothing to configure. For a time-poor volunteer scanning the grid these are wasted clicks that inflate the sense of surface area.
Evidence: `web.py:27979-27990` appends both tiles unconditionally; `29165-29193` both section renderers return only `_coming_soon_card(...)`; the badge lives inside the destination, not on the grid tiles; observed live — both show "Open →".
Fix: Put a visible "Coming soon" badge on the tiles themselves (or collapse both into one muted strip at the bottom) and disable/soften the "Open" CTA so the state is clear before the click.

**[J-11] ✅ DONE (PR #1097) — A photo shared to MediaHub while signed out is silently thrown away** — `medium` / `moderate`
Affects: `/share-target`
What the user hits: The OS share sheet is pitched as "the single highest-value poolside mobile behaviour". If the session has lapsed (common on a phone), the receiver discards the shared photo and bounces to sign-in with no message. After signing in the user lands on the normal post-login page, never back at their photo, with no hint it wasn't saved — so they believe the shot is in the library when it's gone.
Evidence: `web.py:46144-46149` — with no active profile it `redirect(url_for('sign_in_page'))` and the comment states "the photo isn't kept"; no flash, no stash, no return-to-share flow.
Fix: Stash the shared file (a short-lived pending upload keyed to the session) and, after sign-in, complete the drop and land on the library with the "1 photo added" banner — or at minimum flash "Sign in first, then re-share the photo".

**[J-12] ✅ DONE (PR #1097) — The offline shell page is a dead end — no retry, no auto-refresh, no way back into the app** — `low` / `quick-win`
Affects: offline navigation shell
What the user hits: When a volunteer taps a link while offline, the service worker replaces the page with a bare "You are offline" screen with no reload/retry button, no link back to the review queue, and no auto-refresh when connectivity returns — so the user is stranded on a static page until they know to pull-to-refresh, even though the connection may already be back.
Evidence: `web.py:26794-26804` — the navigate fallback returns fixed inline HTML with only an `<h1>You are offline</h1>` and a paragraph; no button, link, or `online` listener.
Fix: Add a "Try again" button (`location.reload`) and a small script that auto-reloads on the `online` event, plus a link back to the review queue.

**[J-13] ✅ DONE (PR #1097) — There is no way to end the presentation from the console; closing the tab leaves the projector stuck on the last slide** — `medium` / `quick-win`
Affects: `/documents/<id>/present`
What the user hits: The console exposes Prev, Next, Blackout, Autoplay and Reset timer but no "End presentation" — only the phone remote can end. A presenter driving from the laptop who closes the tab leaves the session live (6-hour TTL), so the projector keeps displaying the final slide indefinitely with no clean "that's a wrap" state.
Evidence: `web.py:17667-17671` — the console button row has no "end" action and no back-to-document link; `presenter.py:31` `SESSION_TTL_SECONDS = 6*3600`.
Fix: Add an "End presentation" button (with confirm) to the console that fires "end" and returns the presenter to the document.

**[J-14] The per-public-IP code rate limit can lock out every phone behind a venue's shared NAT, and recovery loops back into the same wall** — `medium` / `moderate`
Affects: `/remote/<code>`, `/remote` — merges the rate-limit and recovery-loop findings
What the user hits: Failed pairing-code lookups are throttled at 20 per 5 minutes keyed on the client IP, which at a meet resolves to the venue's single public NAT — so a handful of mistyped codes exhausts the budget for everyone, and the limit is checked BEFORE validation, so even a CORRECT code is refused with "Too many attempts". Both failure exits ("Code not found", "Too many attempts") send the user to a "Try again" button that returns to code entry and the same block, with no wait-time shown, so they retry in a loop.
Evidence: `web.py:60083` checks `_remote_code_limited()` before `get_by_pairing_code` (`60089`); `60035-60036` sets 20/300s keyed on `_client_ip()` (`36443`); `60084-60088` the recovery CTA routes straight back to `remote_landing` and the same block.
Fix: Validate the code first and only throttle confirmed-wrong attempts; scope the budget per-code rather than per-IP; never block a correct code; show the actual retry-after time and suppress "Try again" until the window elapses.

**[J-15] Paid tiers can read "Pricing TBC" with a disabled CTA and no alternative action** — `medium` / `moderate`
Affects: `/pricing`
What the user hits: Until an internal evidence gate is met, both paid tiers show "Pricing TBC" and the upgrade CTA renders as a disabled "Not yet available" pill, giving a club treasurer who wants to pay nothing to do — no contact link, no waitlist, no "talk to us". The hero also claims "Annual prepay keeps it cheaper" when no monthly SKU exists to be cheaper than. (The TBC tooltip's env-var leak is covered in F-3.)
Evidence: `web.py:38156-38160` renders the `pointer-events:none` "Not yet available" div with no fallback; `38257-38258` hardcodes "Annual prepay keeps it cheaper." while the monthly pane is derived annually (`38088-38089`).
Fix: When a tier isn't purchasable, replace the dead CTA with a mailto/contact CTA ("Talk to us about pricing") using the existing `CONTACT_EMAIL`; soften the hero line to match reality.

**[J-16] 2FA error paths are dead-end interstitial pages instead of inline form errors, and `/login/2fa` has no way back** — `low` / `moderate`
Affects: `/login/2fa`, `/account/2fa`
What the user hits: A wrong TOTP code at login produces a bare full-page card ("That code didn't match") whose only control is a "Try again" link — an extra page and click for every typo. Enabling/disabling 2FA behaves the same. The `/login/2fa` prompt offers no "cancel / back to log in" escape, so a user who realises they picked the wrong account is stuck on the code prompt.
Evidence: `web.py:36748-36753` returns a full-page card with a "Try again" link instead of re-rendering the form; `36780-36798` does the same for enable/disable; the GET form (`36722-36731`) has only the input and Verify, no cancel link.
Fix: Re-render the code form with an inline error and the input focused/cleared on failure, and add a "Back to log in" link on `/login/2fa` that clears `pending_2fa_email`.

---

## Coverage & method

**Scope covered.** The audit walked **15 product surfaces** — home/nav/IA; signup/login/account/billing/pricing; upload & pipeline; review & approval; content pack & export; motion/reels/video/charts; media library & image tools; organisation & brand setup; settings/developer/status; the content planner; the Create hub/free-text/drafts/spotlight; distribution (wall/newsletters/documents/print/sponsors); data & records (athletes/records/live/data-hub/season/activity/audit); privacy/consent/compliance/legal; and cross-cutting interaction patterns (feedback/errors/dialogs/a11y/mobile) — plus **one live in-browser walkthrough** of the primary flow (fresh `DATA_DIR`, no AI key, Playwright-driven) and **three gap-fill rounds** for surfaces that started with zero coverage: the installable-PWA / offline-approval / share-target / poolside-capture stack; interface localization (Welsh UI + per-card translate); and document presentation / slide-remote pairing.

**Verification.** 197 raw findings were fact-checked against the code: **172 CONFIRMED**, **12 ADJUSTED** (severity or evidence corrected — e.g. the Settings tile count raised from ~14 to 17; the empty-`.catch` count corrected to 24; organisation delete recognised as well-protected and removed from the weak-delete list), **1 rejected and dropped**, and **13 live-walkthrough observations** carried no code-fact verdict and are trusted because they were directly observed in the running app (marked *(confirmed live)*). Those 197 were deduplicated to **161 unique findings** by merging cross-surface repeats (the mandatory interstitial appeared from 4 surfaces; "drafts unreachable", "collections orphan", "live meet orphan", the env-var jargon leak, and the raw-JSON error page each appeared from 2–3). No unique issue was dropped in the merge.

**Out of scope / could not be verified here.**
- **Production-only behaviours** couldn't be exercised in the fresh-`DATA_DIR`, no-AI-key sandbox: live Stripe/billing checkout paths, real multi-tenant profile isolation across accounts, email delivery (verification/invite/reset), and the CSRF failure in A-3 was reproduced live but its production-key behaviour is inferred from code, not run against production.
- **No live security testing** was performed against the production Render deployment or any customer environment; security-adjacent findings (IDOR-shaped share tokens, the operator-login footer leak, the rate-limit lockout) are documented from code as proof-of-concept only, not exploited.
- **iOS Background-Sync behaviour (D-5)** and **PWA install/share-target flows** were reasoned from the service-worker and JS source plus platform constraints, not driven on physical iOS/Android hardware.
- **Deterministic-engine internals are intentionally excluded** — this audit is about the UI/UX shell around the pipeline, not the accuracy of parsers, detectors, the ranker, or colour-science (which the project pins as deliberately non-AI and out of usability scope).
- **Render fidelity / visual-design quality** of the generated graphics and motion (composition, "samey"-ness) was not assessed here; it belongs to the graphic-craft / motion-craft review, not this usability pass.
