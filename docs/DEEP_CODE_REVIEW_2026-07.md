# MediaHub — Deep Code Review & Improvement Backlog (2026-07)

**In plain words.** MediaHub was built very fast — ~250 pull requests in about three
weeks, almost all AI-authored. This document is a fresh, base-code-level review of
what that produced: a numbered list of concrete improvements, ranked issues, and
cleanup. Each numbered item is one issue or suggestion. Fix them in roughly severity
order; nothing here is a rewrite — they are targeted, mostly-small changes.

**How it was produced.** Ten subsystem reviewers read the actual source (not just the
docs) across the whole tree — the `web.py` monolith, the AI/LLM layer, the
deterministic engine, the rendering stack, infra/concurrency, tests/CI, and the git
history of the last 250 PRs. Every **High**/**Critical** finding was then
**adversarially re-verified** against the cited code by a second reviewer whose job
was to catch false positives; items that survived are marked **✓ verified**. A handful
were downgraded or corrected during verification and are annotated as such.

**Severity:** Critical = data loss / auth bypass / security hole reachable in prod ·
High = real defect with a concrete failure path · Medium = correctness/robustness gap ·
Low = polish / defence-in-depth · Info = confirmed-good or advisory.

**Standing rules respected.** No suggestion here reintroduces a self-host path,
heuristic AI fallback, or LLM-ification of the deterministic engine, and nothing under
`legacy/` or `vendor/` is touched — those boundaries are deliberate (see `CLAUDE.md`).

> Scope note: line numbers are from the tree at review time (`web.py` = 68,175 lines).
> They drift as the file changes; treat them as anchors, not guarantees.

---

## A. Process, history & governance

*From analysis of PRs #919–#1168 (250 PRs / 969 commits in 21 days).*

1. **[High] Velocity vs. stability.** 16 major surfaces (Roadmap 1.9–1.24) shipped in 4 days as single 2,700–6,600-line PRs (~2h branch-to-merge each), then 2+ weeks of wall-to-wall remediation (122 audit-titled commits, a 159-finding usability backlog, one feature deleted outright). **Fix:** cap feature PRs (~1k lines); require each surface to pass its own audit checklist *before* merge, not weeks later.

2. **[High] The `web.py` monolith is the churn sink.** It grew 23,548 → 68,175 lines (2.9×) in 31 days and absorbed 34% of all commits (327/969); 18 `Merge wt/…` worktree merges + 30 sync commits exist *solely* to parallelise edits on one file. **Fix:** split into Flask blueprints per surface (see §B).

3. **[High] Roadmap-bot commit noise.** The bot wrote 26% of the entire repo history (872/3,311 commits) and consumes 51% of PR numbers; each update lands *two* commits (branch `docs: auto-update roadmap [skip render]` + merge `… (#N)`). **Fix:** push a single `[skip render]` commit straight to a side branch (the pattern `autotest.yml` already uses), fold roadmap regen into the triggering PR, or move roadmap state out of git. (CI-mechanism detail in #139.)

4. **[High] Direct-to-main pushes bypass the CI gate.** 44 direct pushes (07-09→07-11, +5,309/−330) — *including security fixes* like the `/api/visual/<vid>` cross-tenant IDOR and org-confinement — landed on the auto-deploying trunk with no PR and no pre-merge CI, contradicting the repo's own "gated only on green CI" rule (a direct push deploys before CI finishes). **Fix:** branch protection requiring PRs + status checks on `main`, no bypass for the human account.

5. **[Medium] Fix-the-fix chains.** Systematic audit → caveat-fix → re-audit, 2–4 rounds within days (developer-settings 4 passes/12 commits in 48h; free-text #1103→#1104→#1149; the usability saga 6 batches over 4 days). **Fix:** don't merge an audit PR while its own report still logs open caveats — the caveat list *is* the unfinished work.

6. **[Medium] Commit messages that lie.** Completion claims precede the completing work: `AUDIT COMPLETE — 159/159 shipped` is followed in the same branch by four more fix commits; PR #1068's title "implement all 287 verified improvements (281 fixed)" is self-contradictory. **Fix:** ban "COMPLETE / all N" phrasing until after verification; state it once, in the final commit.

7. **[Medium] Build-then-delete churn.** Club microsites: built in ~2h (#990, +6,628 lines), *extended* 07-09 as an audit deliverable, then deleted wholesale ~24h later (#1109, −8,049). **Fix:** freeze audit-driven investment in features under a keep/kill decision; sequence owner decisions *before* the fix sprint.

8. **[Medium] Unreviewable mega-PRs.** Remediation arrived as self-merged giants: #1068 (383 files, +19,975), #1071 (+16,928), #1143 (+11,788, 10 embedded `wt/` merges). No human can review these; CI is the only gate. **Fix:** merge each worktree branch as its own PR — the `wt/` structure shows the natural split already existed.

9. **[Medium] Deploy churn.** ~30 production deploys in a single day (07-10), many from racing direct pushes. **Fix:** a GitHub merge queue (works with merge commits) + batched/manual-promote deploys to decouple merge cadence from deploy cadence.

10. **[Low] `CLAUDE.md` misdescribes its own codebase.** It says `web.py` is "~22,500 lines, 114 routes" (actual: 68,175 / 465) and "~3,500+ passed" (actual: ~10,880 test functions in ~828 files). **Fix:** a CI job that regenerates these counts or fails on >20% drift (the roadmap bot already has the write path).

11. **[Low] Audit-meta commit noise.** 35 "audit report" + 13 "record merge status / SHA" commits whose only content is bookkeeping git already records; per-feature `AUDIT_*.md` churned 8–9× each. **Fix:** verdict-only audit reports; drop the "record merge status" commits (link the PR instead). *(Those audit files are now deleted — see §K.)*

12. **[Low] Bot-PR staleness.** The autotest fixer's last three PRs were authored 07-08/09 but batch-merged 07-11 after `main` moved thousands of lines, relying on CI alone to catch staleness. **Fix:** auto-merge bot PRs when green within 24h, or auto-rebase-and-rerun before batch-merging.

13. **[Info] Merge-method compliance is clean.** All 179 first-parent PR landings are true 2-parent merge commits (zero squashes), matching policy; only 1 revert in the whole history.

14. **[Info] Effectively a single-account repo.** In-range: 588 commits by "Claude", 241 by the maintainer, the rest bots — the same account authors *and* merges everything, so every "review" gate reduces to CI. This is the root cause behind #4, #8 and #9.

---

## B. Architecture — the `web.py` monolith

15. **[High] ✓ `create_app` is a 48,188-line closure** (`web/web.py:19980`, 70.7% of the file) nesting all 464 route handlers **plus** ~250 helper functions as inner defs that close over `create_app`-scoped locals (`_active_profile`, `_memberships_snapshot`, `_active_role`, …). No surface can be split off, unit-tested, or reasoned about in isolation. **Fix:** two steps — (1) hoist the ~250 shared helpers to module level passing `app`/config explicitly (`_load_run`, `_can_access_run`, `_layout` are *already* module-level, proving the pattern); (2) move surfaces to Blueprints largest-first — `api/runs` (72 routes/~5,856L), `organisation` (26/~4,664L), `media-library` (36/~2,357L), `video` (19/~1,260L). Extracting just those four moves ~14,000 lines and 153 routes out of the closure.

16. **[High] ✓ Active profile re-read from disk 4–5× per request, uncached** (`web/web.py:20685`). `_active_profile()` calls `_active_profile_id()` (which loads the profile) then loads it *again*; two `before_request` hooks each reload it; the handler reloads again. Every `load_profile` (`club_profile.py:483`) does a full JSON parse **plus** `_scrub_legacy_secrets_file()` disk I/O. **Fix:** memoize the resolved profile on `flask.g` for the request (mirror `_memberships_snapshot`, which does exactly this 200 lines away); remove the redundant second load; move `_scrub_legacy_secrets_file` to startup.

17. **[High] ✓ `/api/visual/<vid>` walks all of `RUNS_DIR` per request** (`web/web.py:63846`, `:63902`). Both visual routes locate a visual by nested-walking every run dir and `json.loads`-ing every `visual.json` until `vid` matches — O(all-tenant-runs × visuals-per-run) — then redundantly re-parse the run JSON for the tenant gate. These are hot `<img src>` routes emitted N-per-page. **Fix:** maintain a `vid → (run_id, dir, format)` index (small SQLite table or encode `run_id` into `vid`) for O(1) lookup; fold the access check into the indexed lookup.

18. **[Medium] Run-load + tenant guard copy-pasted across ~90 handlers** (`web/web.py:23617` and 89 more). `if not _can_access_run(run_id, _load_run(run_id), _active_profile_id()): return 404` is duplicated verbatim; several handlers then call `_load_run` a *second* time (`api_workflow_set`, `api_venue_search`, `_doc_facts_for`). Because the access check is security-critical, drift between copies is a real IDOR risk. **Fix:** one `@require_run` decorator that resolves the run once, enforces the tenant check, injects `run_data`, and is the single source of truth.

19. **[Medium] Six copy-pasted "nested run.json fallback" blocks are dead code** (`web/web.py:53786, 57996, 58257, 60211, 60285, 63730`). `_load_run` (`:3395`) already reads both the flat and nested forms — its docstring says so — so these ~10-line blocks only fire in the corrupt-flat-but-nested-present case and contradict the centralised design. **Fix:** delete them; if the corrupt-recovery is wanted, add it *inside* `_load_run`.

20. **[Medium] Storage-inventory scan duplicated verbatim and unbounded** (`web/web.py:28387` and `:32816`). The privacy page and data-hub page each inline a full `RUNS_DIR`/`UPLOADS_DIR`/cache glob per request to show a count. **Fix:** factor into one `_storage_counts()` helper, cache briefly, and prefer `SELECT COUNT(*) FROM runs` over globbing.

21. **[Low] Two of three documented feature flags are near-vestigial.** `_club_platform_ok` gates exactly one branch and checks in-package modules (effectively always True); `_v73_ok` gates exactly one branch; only `_v8_ok` is a real gate (86 refs). **Fix:** inline the single checks (removing the flags) or drop them from the `CLAUDE.md` "feature flags" list so only `_v8_ok` is presented as real.

22. **[Info] `url_for` discipline is strong.** 221 `url_for` hrefs / 202 `url_for` redirects vs only 4 hardcoded internal paths and 0 hardcoded redirects. Optionally convert the last 4 stragglers; otherwise no action.

---

## C. Security & multi-tenancy

23. **[High] ✓ Reflected XSS on `GET /drafts/<pack_id>`** (`web/web.py:38820`, source `:38815`). The `photo` query param is read raw and embedded into an inline `<script>` via `json.dumps(_photo)` — which does *not* escape `<`/`</script>` — under a CSP that allows `'unsafe-inline'`. `?photo=</script><script>…` executes in the victim's authenticated org session. Sibling script sinks in the same file already apply `.replace("<","<")`; this one doesn't. **Fix:** add the `<`→`<` escape (a `_json_for_script(obj)` helper used at every `<script>` embed site), and validate `_photo` against the asset-id shape.

24. **[High] ✓ `_run_`-prefixed assets bypass the run access check** (`web/web.py:52258-52271`; reached by the whole `/api/media-library/<asset_id>/*` family, delete route `:52349`, per-card upload `:53834`). `_session_can_access_profile()` returns `True` **unconditionally** for any asset whose `profile_id` starts with `_run_`, so it never applies the ownerless-run rule that `_can_access_run`/`_ownerless_run_readable` enforce — the *same* IDOR class just fixed on `/api/visual/<vid>`, left un-applied here. A signed-in stranger who learns an asset id can read a run's uploaded photos and generated images. **Fix:** for `_run_*` ids, resolve the embedded run id and reuse the real run guard; apply to the read *and* delete routes. *(Found independently by two reviewers.)*

25. **[High] ✓ Password reset does not invalidate existing sessions** (`web/auth.py:501-513`, route `web/web.py:41971`). `set_password` (the only password-change path) re-hashes but never increments `session_epoch`, and the reset handler calls `login_user` with the unchanged epoch — so a stolen/old session cookie stays valid after a "reset your password" recovery. **Fix:** increment `session_epoch` in `set_password` (mirror `bump_session_epoch`) and `session.clear()` before `login_user` in the handler.

26. **[Medium] Committed default operator credential can authorise prod** (`web/auth.py:628-629, 806-807`). A baked-in username + argon2id hash grants an unrestricted `PLAN_OWNER` synthetic user that bypasses every paywall and tenant gate; if `MEDIAHUB_DEV_PASSWORD_HASH` is unset in production the default is live and the hash is offline-crackable by anyone with repo read. **Fix:** in `env_check`, hard-error at boot in production when the dev hash/user is unset or equals the shipped default; consider a required TOTP second factor for operator login.

27. **[Medium] Brute-force brakes are process-local under 2 workers** (`web/auth.py:195, 262`, `web/web.py:41207`; `Procfile` `--workers 2 --max-requests 200`). Account lockout, per-IP limiter, and the TOTP replay guard are in per-worker dicts, so attempts across 2 workers get ~2× the budget, and `--max-requests` recycling wipes the counters mid-attack. The `/login/2fa` POST also lacks the per-IP brake. **Fix:** move the counters to the shared SQLite DB (or Redis) so lockout is cross-worker and restart-durable; add the per-IP brake to the 2FA path.

28. **[Medium] No pixel-dimension cap on image uploads** (`web/web.py:51755-51764, 20059`). `_verify_image_decodes` only calls `Image.open().verify()`, relying on Pillow's default ~178 MP warn threshold; worse, `api_card_photo_upload` inherits the 512 MB *video* body cap. A decompression-bomb image can exhaust worker memory. **Fix:** set `Image.MAX_IMAGE_PIXELS` to ~40–50 MP and reject `DecompressionBomb*` in `_verify_image_decodes`; scope the image body cap to `MAX_CONTENT_LENGTH` (50 MB), not the video cap.

29. **[Low] Three `/healthz/*` diagnostics are public while siblings are gated** (`web/web.py:30698` breaker, `:30741` search, `:30117` memory). `/healthz/breaker` leaks `providers_configured` (which of GEMINI/ANTHROPIC keys are set) + breaker counters; `/healthz/memory` leaks RSS and concurrency limits — whereas `/healthz/deps` and `/healthz/sentinel` redact/gate. **Fix:** keep a minimal public `ok` boolean; gate the provider map, breaker internals, RSS and search backend behind `is_dev_operator()`.

30. **[Low] `GET /api/upload/from-url/<job_id>/status` has no owner binding** (`web/web.py:23556`). It returns crawl progress and the resulting `run_id` to anyone with a (48-bit random) job id — the only async-job route without the `owner` check its siblings (`reel-jobs`, `variant-jobs`, `export-jobs`) all have. **Fix:** bind the job to the creating session's profile at creation and check it here; 404 on foreign/unknown ids.

31. **[Low] `Content-Disposition` filenames interpolate raw ids** (`web/web.py:38906` pack_id, `:52327` asset_id). Not currently exploitable (ids are server-minted and must resolve first), but they bypass `_safe_filename`, unlike every other download route. **Fix:** route the interpolated component through `_safe_filename` / an `[A-Za-z0-9_-]` sanitiser (defence-in-depth against header injection).

---

## D. AI / LLM layer

32. **[High] Gemini→Anthropic failover never fires on connection errors** (`ai_core/llm.py:626-642`). Failover is decided by regexing the error *string*; a transport-level Gemini failure (`ConnectionError`, DNS failure, reset) raised as `ProviderError("Gemini HTTP error: …")` matches none of the transient markers, so `ask()`/`ask_with_tools()` raise immediately without ever trying a configured Anthropic. Anthropic 529 is also unmatched. **Fix:** stop classifying by message text — set a `transient: bool` on `ProviderError` at each raise site (transport + 429/5xx → transient; 400/404 → permanent) and branch on that.

33. **[High] ✓ Gemini API key sent as a URL `?key=` query param in `ai_core`** (`ai_core/llm.py:330, 393`). This is the exact leak vector `media_ai` eliminated by moving to the `x-goog-api-key` header (`media_ai/llm.py:480`, with a comment explaining why) — a URL-borne key rides into exception reprs, access logs and proxy logs; `_redacted()` only cleans MediaHub's own strings. `ai_core`'s own docstring even admits the failing URL "includes its `?key=…`". **Fix:** switch both `ai_core` call sites to the header, matching `media_ai`.

34. **[High] ✓ SSRF: `context_engine` fetches with raw `urllib` while a hardened door exists** (`context_engine/research.py:123-167`). `fetch_text`/`fetch_bytes` use `urllib.request.urlopen` with no IP validation/redirect re-check/scheme restriction, while `web_research/safe_fetch.py` is the SSRF-hardened primitive (blocks RFC-1918/loopback/link-local/metadata, pins to the validated IP to defeat DNS-rebinding, re-validates redirects). `identity.discover_meet_identity` live-fetches URLs seeded from *uploaded-file* meet/venue text (attacker-influenceable). **Fix:** route both through `safe_fetch`/`safe_fetch_bytes`; delete the third unhardened, caller-less `WebResearcher.fetch_url`.

35. **[High] `media_ai.generate()` raises a false "no key configured" on all-provider failure** (`media_ai/llm.py:896-900`). When providers *are* configured but every call fails (Gemini 429 + Anthropic 500, breaker open), it raises `ClaudeUnavailableError("…not configured…")` — a lie, because the call helpers swallow failure detail into `None`. `generate_vision` was explicitly fixed for this; the hot-path `generate()` was not. **Fix:** track attempted providers + last error and distinguish "no key" from "all attempts failed because X" (the honest-error rule).

36. **[High] `ai_core` records zero LLM usage** (`ai_core/llm.py`, whole file). No `record_call` anywhere, so copilot, free-text chat, club Q&A, deep research (up to 8 Gemini calls/run), autonomy and results-triage are invisible to `/healthz/usage` and to the Gemini free-tier daily-request tracker — real RPD can far exceed the dashboard. **Fix:** add best-effort usage recording (provider, model, tokens, duration, error kind) to each `_ask_*`.

37. **[Medium] Tool-loop failover replays side effects** (`ai_core/llm.py:699-707`). On a mid-conversation transient failure, `ask_with_tools` restarts the whole conversation on the next provider, but `on_tool_call` closures already ran with lasting effects — copilot applies + audit-logs ops twice; free-text chat double-appends to `research_log`. **Fix:** only fail over when `convo.tool_calls` is empty (first request failed); otherwise raise or return partial state so callers can reset.

38. **[Medium] Empty Gemini output is swallowed silently** (`ai_core/llm.py:346-347, 417-419`). A safety-blocked or `MAX_TOKENS` response with no text parts returns `""` with no error and no failover — `ai_director` logs "empty output", `build_brief_from_prompt` later fails with a misleading JSON error. `media_ai` treats empty as a failure and walks on. **Fix:** raise a transient `ProviderError` citing `finishReason`/`promptFeedback`.

39. **[Medium] Round-cap exhaustion is a canned sentence masquerading as model output** (`ai_core/llm.py:250,445,568` + `web_research/deep_research.py:37,162`). "(Claude is still gathering evidence…)" is stuffed into `convo.text`; `deep_research` detects it by *substring sniffing* (a real answer containing that phrase gets discarded) and free-text chat persists it verbatim as an assistant message. **Fix:** add `exhausted: bool` to `ToolConversation`, set it at the three cap sites, branch on it downstream.

40. **[Medium] Research surfaces ignore the existing prompt-injection guard** (`web_research/deep_research.py:128-147` + `free_text_chat/agent.py:243-275`). `ai_core/prompt_guard.py` (`delimit_untrusted`, `SYSTEM_GUARD`) exists for exactly this, but neither surface uses it — raw scraped page text/snippets flow straight into the tool loop and into persisted conclusions. **Fix:** wrap tool results in `delimit_untrusted(...)` and add the data/instruction separation to both `_SYSTEM` prompts.

41. **[Medium] Unbounded chat context** (`free_text_chat/agent.py:191-211`). `_render_history_as_prose` serialises the *entire* transcript into every turn with no cap (contrast copilot's `recent_chat(8)`), so long chats grow token cost linearly and eventually exceed the input window with an opaque provider error. **Fix:** cap to the last N messages + a running summary, with an honest "(earlier turns omitted)" note.

42. **[Medium] Learned-authority gate is too cheap** (`web_research/verify.py:28,59-68` + `context_engine/trust.py:104-117`). `(successes+1)/(attempts+2) ≥ 0.8` lets a domain reach "authoritative" after just 3 successful *parses* (format extractability, not provenance) — an attacker site that parses cleanly earns structural trust. **Fix:** require a minimum attempt count (≥10) before the learned score can confer authority; keep operator-declared domains as the only low-evidence path.

43. **[Medium] The two LLM wrappers have materially drifted** (`media_ai/llm.py` vs `ai_core/llm.py`). Beyond #33/#36: `media_ai` honours `MEDIAHUB_GEMINI_TIMEOUT`, `ai_core` hardcodes 45/60s; `ai_core` sends `temperature:0.7`, `media_ai` none; `media_ai` reads the model once at import, `ai_core` per call; the Gemini HTTP transport is duplicated near line-for-line. The shared breaker is also one-directional — `ai_core` reads it but never records failures (`:583-596`), so a Gemini outage seen only via chat/copilot never trips it. **Fix:** extract one shared Gemini/Anthropic transport (the `llm_client.py` seam already proves the pattern) and have both wrappers consume it, recording breaker state from both.

44. **[Low] Import-time env parsing can crash boot** (`media_ai/llm.py:306, 92, 305`). `int(os.environ.get("MEDIAHUB_GEMINI_TIMEOUT","45"))` runs at import; a value like `"45.5"` raises `ValueError` and takes down every importer (`web.py`) at startup. **Fix:** parse per-call with a try/except default (as `ai_core._gemini_model()` does).

45. **[Low] `_call_anthropic` retries the alt model on unrecoverable errors** (`media_ai/llm.py:255`). It retries `ALT_MODEL` on *any* exception including 401/400, burning a second billable call, and retries the identical model when the operator already set it. **Fix:** retry only on model-specific errors (404 not-found, 529 overload); skip when `use_model == ALT_MODEL`.

46. **[Low] `generate_json` hides parse failures** (`media_ai/llm.py:919-926`). It returns `fallback` (`{}`) on unparseable output with no log and no ledger row, so "model returned garbage" is indistinguishable from "empty result" at ~20 call sites; it also never requests provider-native JSON mode. **Fix:** log + record `error_kind="json_parse"`, and use Gemini `responseMimeType`/Anthropic JSON options.

47. **[Low] Batch embedding can misalign text↔vector** (`memory/embedder.py:137-143`). `embed()` drops null rows silently and never checks `len(vectors)==len(texts)` nor honours the OpenAI `index` field — a partial provider response would mis-pair. Latent today (only `embed_one` is used). **Fix:** raise on count mismatch; order by `index`.

48. **[Low] `memory` store path frozen at import** (`memory/store.py:34-35`). `DB_PATH` defaults to the *package* dir at import, so a `DATA_DIR` set later (tests, late bootstrap) is ignored and vectors land in the source tree — unlike every sibling store which resolves per call. **Fix:** make `_db_path()` a function reading the env per call.

49. **[Info] Honest-error rule is mostly upheld** — the gaps above (#35, #38) are the exceptions; the codebase otherwise raises `ClaudeUnavailableError`/`ProviderNotConfigured` rather than fabricating output. Worth a targeted test asserting each AI surface raises (not stubs) when no provider is configured.

---

## E. Deterministic engine (parsers · PB detection · ranking)

*The product's core trust surface — deliberately non-AI. These are accuracy bugs, not style.*

50. **[High] Native parsers fabricate medals by discarding round info** (`interpreter/hytek_parser.py:273`, `sdif_parser.py:274`, `lenex_parser.py:328` + `pipeline/interpreter_bridge.py:415`). HY3 parses the E2 round code but never uses it (and keeps only the first E2 after an E1, so finals are dropped and prelims kept); SDIF hardcodes `prelim_time=None`; LENEX ignores the event round. The bridge then maps every round-less swim to `"timed_final"`, and the legacy medal detector fires on `round in ('final','timed_final')` — so a **heat place-1 surfaces as a gold medal**. The PDF path guards this; the native fast path bypasses the guard. **Fix:** populate `round_hint` from the E2 code / SDIF prelim-vs-finals / LENEX round; bridge prelims to `"heat"`.

51. **[High] Every non-numeric time is collapsed into a DQ** (`pipeline/interpreter_bridge.py:429-430`). `status = "completed" if time_cs else "dq"` erases the DNS/NS/SCR/WD/DNF marker `rows.py` deliberately preserves — a scratch is recorded as a disqualification, and an OCR-garbled time is *silently* a DQ. **Fix:** thread the marker into `RaceResult.status`; emit needs-review when a present time string was unparseable.

52. **[High] Unknown stroke/course silently defaults to Freestyle LC** (`pipeline/interpreter_bridge.py:67-90`). `_stroke_code()→"FR"` and `_course_code()→"LC"` for unresolved input, so every PB comparison for those swims runs under the wrong `(dist,stroke,course)` key — false PBs / false negatives with no flag, violating "never silently guess". **Fix:** return `None`, exclude from PB/medal detection, add a meet warning.

53. **[High] Identity guard self-defeats and returns the wrong swimmer** (`swimmingresults/lookup.py:326`). `pool = plausible or surname_cands`: when the plausibility filter rules out *every* same-surname candidate, it falls back to the ruled-out ones and returns a unique one as the tiref — so the wrong family member's record becomes the PB baseline. Compounded by `names.py:176-189` allowing Levenshtein-2 on surnames ("Wilson"≈"Watson"). **Fix:** `pool = plausible`; return `None` when empty; tighten the surname edit budget to 1.

54. **[High] Schema-path swims bucketed into events by blind chunking** (`interpreter/rows.py:699-707`). The fallback assigns swim N to event `N // (len(swims)//len(events))` regardless of source position → wrong event → wrong key → wrong PB verdict, at full confidence. `_find_event_line_indices` (`:580`) similarly falls back to `found = cursor` on a non-exact header match. **Fix:** carry table/line indices through the schema path (as path B does); cap confidence + needs-review when chunk assignment is used.

55. **[High] "Weekend in numbers" double-counts PBs and finals** (`recognition/weekend_in_numbers.py:45-47,58`). `n_pbs` sums `pb_confirmed` **and** `pb_magnitude_*` **and** `official_pb*` — but `pipeline_v4.py:864` documents `pb_magnitude_*` as *derivatives of the same swim*, so one PB counts 2–3× on the published card; `n_finals` double-counts likewise. **Fix:** dedupe by swim-id prefix, or count only the primary types (as the audit map already does).

56. **[Medium-High] Whole-page course detection contaminates the PB baseline** (`pb_discovery/parse_pbs.py:95-101,145` + `pipeline/pb_bridge.py:171`). `_detect_course` inspects the whole page once, checks LC first, and defaults `"LC"`, so a profile listing both LC and SC tables labels every row LC — SC bests then contaminate the LC baseline (faster ⇒ false "not a PB") and SC events get no baseline. It also takes `time_matches[0]` (first time-shaped token, not the PB column). **Fix:** detect course per table/heading (as `swimmingresults/parse.py` does) and drop unknown-course rows.

57. **[Medium] Positional course fallback contradicts its own docstring** (`swimmingresults/parse.py:219-225`). "no course headings → assume the two tables are LC then SC" directly contradicts the module's stated rule that course is never silently defaulted. One markup change flips every baseline to a guess. **Fix:** flag such entries `course_guessed` (consumed as needs-review) or drop them.

58. **[Medium] Stale open club record → future false record** (`recognition_swim/achievements/club_record.py:103` + `club_records/store.py:366`). A swim breaking both an age-band and the open record keeps only `broken[0]`; the open record stays stale, so a later *slower* swim triggers a false "NEW CLUB RECORD (open)". **Fix:** emit one achievement per broken key and update every eligible key on approval.

59. **[Medium] Season standards packs never reach detection** (`standards/packs.py` + `pipeline/pipeline_v4.py:506`). The pipeline loads standards via `load_registry()` only; `standards_for_profile()` / `load_standard_packs()` are referenced nowhere outside the package, so the W.4 season packs and per-profile filter never affect qual-hit detection. `_standards_dirs` also uses a doubled `$DATA_DIR/data/standards` path. **Fix:** call `standards_for_profile(profile)` from the pipeline; reconcile the path.

60. **[Medium] `OfficialPBDetector` is silently inert on HY3/SDIF runs** (`hytek_parser.py:303`, `sdif_parser.py:122`, `official_pb.py:19-25,185`). `_format_date` emits ambiguous `"dd/mm-or-mm/dd"` strings; `_parse_iso_date` requires ISO and returns `None`, so `meet_start is None` and Rule 0 — the strongest PB confirmation — never fires, and the ±1-day window can't work. **Fix:** normalise all meet dates to ISO at parse time (disambiguate by >12 test + governing-body hint; flag when ambiguous).

61. **[Medium] False "club debut" for name-drift veterans** (`recognition_swim/achievements/milestones.py:92`). `prior_races = … if athlete_ctx else 0`: when the registry is non-empty but this swimmer's alias doesn't resolve (nickname/spelling drift), the veteran is treated as `prior_races=0` → a confident (0.85) "First gala" card. **Fix:** distinguish "unknown to registry" (fire nothing / needs-review) from "known with 0 prior races".

62. **[Medium] Time-shaped points columns overwrite the real time** (`interpreter/rows.py:29,302,422-427`). `_TIME_PLAIN`/`_TIME_TOKEN` accept 3–4 digits before the dot, so a points column ("430.50") is time-shaped; since `_record_to_swim` takes the *last* time-like token, a trailing points column replaces the finals time. **Fix:** for colon-less tokens require value <60s unless the row has no other time.

63. **[Medium] `mm:ss` split parsed as a 100× time error** (`pipeline/interpreter_bridge.py:112`, dup `pb_bridge.py:42`). `_TIME_RE` accepts `:` as the *fraction* separator, so `"23:45"` (a split) parses as 23.45 s. **Fix:** require `.` before the fraction; treat bare `mm:ss` as minutes+seconds or reject.

64. **[Medium] Four diverging stroke/time canonicalisers** (`interpreter_bridge.py:52`, `pb_bridge.py:28`, `swimmingresults/parse.py:24`, `club_records/store.py:31`). Each maps unknown values differently (→"FR" / →"" / →drop / →None) and three near-identical time parsers have different edge behaviour (see #63). **Fix:** one shared strict `canonical_codes.py` returning `None`, consumed by all four — the "FR"/"LC" defaults (#52) die with it.

65. **[Medium] Relays are unmodelled** (`interpreter/events_induce.py:32,151`). "4x50m Medley Relay" parses distance as `None` or a bogus number; named relay lead-offs can enter individual PB detection; SDIF E0/F0 relay records are ignored. **Fix:** detect relays in headers, add `is_relay` to `InterpretedEvent`, exclude relay swims from individual PB keys.

66. **[Low-Medium] Brittle src↔legacy seam** (`recognition_swim/achievements/official_pb.py:190` + `src/mediahub/__init__.py:21` + `pb_discovery/discover.py:30`). The detector reaches into a *private* legacy method (`history._pb_times_for`) wrapped in `except: return None`, so any legacy shape drift silently disables official-PB confirmation; the whole seam rests on `__init__` appending `legacy/` to `sys.path` with `except: pass`. **Fix:** assert the accessor exists at import (fail loudly), log at WARNING in the except, and delete the `discover.py` path hack (its imports are already absolute).

67. **[Low] Confidence floors are cosmetic** (`hytek_parser.py:471`, `sdif_parser.py:380`, `lenex_parser.py:579`). Overall confidence is clamped `max(0.5, …)`, so a parse where nearly every field failed still reports ≥0.5 (above the min-overall gate). **Fix:** remove the floor; let broken parses read as broken.

68. **[Low] Nickname table mis-merges two given names** (`swimmingresults/names.py:68-69`). `{"freya","freddie"}` + first-wins `setdefault` makes "freddie" canonicalise with *freya*, so the intended Freddie↔Frederick equivalence fails. **Fix:** delete the freya set; add "freddie" to the frederick group.

69. **[Low] 2-digit year pivot is a frozen constant** (`interpreter/rows.py:61`, `swimmingresults/parse.py:120`). `yr<=30 → 2000+yr` (and parse.py maps *every* 2-digit year to 20xx), so a masters PB set in "98" becomes 2098. **Fix:** pivot relative to the meet/current year; reject future dates.

---

## F. Rendering stack

70. **[High] ✓ Opt-in audio silently never attaches in production** (`visual/audio_mux.py:606`, temp at `:591`). `apply_audio()` mux temp is created under the default temp dir (`/tmp`) then committed with `os.replace(tmp, video)` onto the `DATA_DIR/motion_cache` MP4. On Render, `/tmp` (container overlay) and `DATA_DIR` (persistent disk) are different mounts, so `os.replace` raises `EXDEV`, which the broad `except` reports as `silent_fallback` — the whole `MEDIAHUB_VOICEOVER`/music feature is dead in the hosted shape. Sibling engines correctly use `shutil.move`. **Fix:** `shutil.move`, or create the tempdir with `dir=str(video.parent)` to keep the atomic rename same-filesystem.

71. **[Medium] `motion_cache` grows without bound** (`visual/motion.py:85`). Every cold render writes `.mp4 + .json + .poster.png + .audio.json + props/.json` and nothing evicts — unlike the still-PNG cache which has an LRU `_prune` (512 entries). On a bounded Render disk this trends to exhaustion, after which all writes fail. **Fix:** add an LRU/size cap mirroring `render_cache._prune` (sweeping all sibling files); touch mtime on cache hits.

72. **[Medium] Render subprocess timeouts leak Chromium** (`visual/motion.py:1697`, `reel_parallel.py:253`). `subprocess.run(node …, timeout=600)` runs with no process-group setup, so on timeout only `node` is SIGKILLed and its Remotion/Chromium children reparent to init and keep holding RAM until OOM. **Fix:** launch with `start_new_session=True` and `os.killpg(os.getpgid(proc.pid), SIGKILL)` on `TimeoutExpired`.

73. **[Medium] Concurrent same-key MP4 renders race on the cache slot** (`visual/motion.py:1850, 2662`). On a miss the render writes directly to the shared `cached` path and the audio pass mutates it in place, with no lock/temp-rename; two requests for the same content hash (double-click, retry, two viewers) can serve/cache a torn MP4 (the `size>1024` gate won't catch it). The still path was hardened against exactly this. **Fix:** render to a per-attempt unique temp then `os.replace` onto `cached`, or lock per key.

74. **[Low] Motion cache key omits the renderer generation** (`visual/motion.py:1814, 2593`). It folds a *manual* revision constant but not the brand-font mtimes or Remotion/Node version, while the still renderer auto-invalidates on those — so a `fetch_renderer_fonts.py` refresh changes reel pixels while the motion cache serves pre-refresh MP4s unless a human bumps the constant. **Fix:** fold a renderer-generation salt (font hashes + Remotion version) into the motion cache key.

75. **[Low] Orphaned Remotion props files** (`visual/motion.py:1676-1679`). `props/<key>.json` is written every cold render and never deleted, accumulating one-per-MP4 with no prune. **Fix:** `unlink` in a `finally` after the subprocess returns, or write into the shared tempdir; ensure any motion-cache prune sweeps `props/`.

*Verified-good (no action): APCA/ΔE2000 colour maths match the spec; TS components are frame-pure (no `Math.random`/`Date.now`); Remotion font loading (single `delayRender`, awaits `document.fonts.ready`) is correct; the Playwright pool is race-hardened; the ffmpeg fallback folds its engine into the cache key.*

---

## G. Concurrency, state & data-safety

*The single scariest cluster: the product's human-approval state can be silently lost.*

76. **[High] ✓ Approval-state torn-write wipe** (`workflow/store.py:58` + `approvals.py:45`; found independently by two reviewers). Both `_save` methods do a non-atomic `write_text(json.dumps(...))` (truncate-then-write) and both `load()` swallow *any* read error to `{}`, guarded only by a per-process `threading.Lock` — but `Procfile` runs `--workers 2`. Failure path: worker A truncates the sidecar mid-write; worker B's concurrent `load()` hits the partial file → `except: {}` → persists only its one card → **every prior approve/reject is permanently erased** (absent == "queue" in the UI). Bulk-approve (`web.py:49439`) does N back-to-back writes, widening the window. This destroys exactly the state `CLAUDE.md` says must never be lost — and the repo already has the fix idiom (`_variant_job_save`, `web.py:2474`, uses tmp+`os.replace`). **Fix:** atomic tmp+`os.replace` in both stores, plus an OS-level (`fcntl.flock`) lock around load→mutate→save, or move this state into the shared SQLite DB.

77. **[Medium] `_persist_run` torn read shows "run not found" at completion** (`web/web.py:3315` writer vs `:3413` reader). The primary run record is written with a non-atomic `write_text` of a large payload; a status poll on the other worker can catch it mid-truncate → `_load_run` returns `None` → the user sees "run not found" the instant their run finishes. Self-corrects next poll, but user-visible. **Fix:** atomic tmp+`os.replace` (one-line change matching `_job_record_write`).

78. **[Medium] Group-approval vote ledger has the same wipe class** (`workflow/approvals.py:39-59`). Corrupt-to-`{}` load + non-atomic write + cross-process-unlocked read-modify-write, on the ledger governance uses to decide auto-approval — concurrent votes (the *expected* workload) drop or reset all votes. **Fix:** as #76 (atomic + file lock / SQLite).

79. **[Medium] `create_task` "validate up front" is false for cron/once** (`workflow/schedule.py:314-316`). For `cron` it just returns `expr.strip()` (no `croniter` parse) and for `once` nothing is validated; at fire time both swallow to `None`, so a malformed schedule is accepted and silently never fires. **Fix:** `croniter(expr)` / `datetime.fromisoformat(expr)` at creation, raising `ValueError`.

80. **[Medium] Autonomy status guard fails *open* to QUEUE** (`autonomy/tools.py:212-217`). Any workflow-read failure (or an empty load from a corrupt sidecar) maps to `CardStatus.QUEUE` — the one status that lets `_queue_for_approval` persist over a card a human APPROVED/REJECTED. The guard fails open exactly when state is least trustworthy. **Fix:** fail closed — skip the card on a read failure.

81. **[Low] Model note clobbers human notes / hijacks the schedule label** (`autonomy/tools.py:414,430`). The model-supplied `note` overwrites `CardWorkflowState.notes` unconditionally, erasing a human's `scheduled:Saturday` label (parsed by `pack.py:131`); a model note beginning `scheduled:` sets the schedule. **Fix:** store runner flags in a distinct field; never overwrite a non-empty human note.

82. **[Low] Autonomy audit-write failure swallowed silently** (`workflow/autonomy.py:123-128`). A read-only FS / full disk makes the council-mandated "immutable audit trail" lossy with no signal. **Fix:** `log.warning` in the `except`.

83. **[Low] `AuditLog.read(limit=0)` returns everything** (`workflow/autonomy.py:140`). `lines[-0:]` is `lines[0:]`. **Fix:** `if limit <= 0: return []`.

84. **[Low] `pack.py` default `runs_dir` ignores `DATA_DIR`** (`workflow/pack.py:68-70`). Defaults to `src/runs_v4`, violating the DATA_DIR rule; latent (callers pass it explicitly). **Fix:** default from `os.environ["DATA_DIR"]`.

85. **[Low] Always-on voice write gated behind an optional import in a swallow-all try** (`workflow/pack.py:144-166`). `record_approved_caption` (documented as working for every club) only runs if `from mediahub.memory import learning` succeeds and nothing earlier in the `except Exception: pass` block raised — a failure in either subsystem silently disables the other on every pack build. **Fix:** separate try blocks + log.

86. **[Low] `_list_runs` leaks its connection and masks DB errors** (`autonomy/app_env.py:62-73`). No `try/finally`; on an `execute` failure the connection leaks and `except: return []` makes a schema/DB failure look like "no runs". **Fix:** `try/finally: conn.close()` + log.

87. **[Low] `_owns_run` compares an unstripped org id** (`autonomy/app_env.py:58`). A whitespace-only `org_id` passes `bool()` and strip-compares equal to an empty `profile_id`, defeating the "unowned runs not accessible" boundary. **Fix:** `bool((org_id or "").strip())`.

88. **[Low] `review_comments.add_comment` TOCTOU on the per-target cap** (`workflow/review_comments.py:225-237`). `SELECT COUNT(*)` then `INSERT` in separate statements can exceed `MAX_COMMENTS_PER_TARGET`. **Fix:** wrap count+insert in a `BEGIN IMMEDIATE` transaction.

89. **[Low] `notify.inbox.mark_read` lacks per-user scoping** (`notify/inbox.py:470-474`). Guarded by `org_id` only (unlike `list_for`/`mark_all_read`), so any org member with a notification id can mark another member's mention read. **Fix:** apply the `_user_clause`.

90. **[Low] ntfy push fails for non-Latin-1 titles** (`notify/channels.py:88-95`). The Title header only strips CR/LF; `requests` encodes headers Latin-1 and raises on emoji/diacritics (caught + logged), so pushes for such club names never arrive. **Fix:** RFC-2047-encode the title, or transliterate.

91. **[Low] Per-process render semaphore doesn't do what its docstring claims** (`web/web.py:2282`). `BoundedSemaphore` is per-worker, but the docstring calls it a "global render slot" holding one heavy render; under 2 workers the real ceiling is 2× `_RENDER_LIMIT`, roughly doubling peak render memory (→ OOM → interrupted-run resume). **Fix:** correct the docstring and size the limit for the 2-worker topology, or make the lease cross-process if true single-flight is intended.

---

## H. Observability, governance, compliance & privacy

92. **[High] Raw production logs posted to GitHub/ntfy with no redaction** (`log_sentinel/github_issues.py:131`, `sentinel.py:107`, `detectors.py:184`). `Finding.evidence` is verbatim access-log/traceback text (query strings can carry `?key=`, signed URLs, session ids, PII) pushed to a permanent external issue tracker — whose titles flow into `docs/ROADMAP.md` — and to ntfy topics. There is *zero* redaction in the package. Violates the "keys/PII never in user-visible text" rule. **Fix:** a redaction pass (mask `key=`/`token=`/`Authorization:`/`sk-ant-`/`AIza`/emails) in `detect()` before evidence enters `Finding`, covering every sink.

93. **[Medium] The disk-full alert kills itself** (`log_sentinel/sentinel.py:130` + `state.py:90`). `_handle` calls `append_audit` (raises `OSError` on ENOSPC) *before* `_notify`, so when the `disk_full` detector fires, the audit write raises first, the cycle aborts, the full-disk notification is never sent, and the cursor never advances (the error repeats forever). **Fix:** make `append_audit` best-effort, or notify before auditing.

94. **[Medium] Traceback evidence is contentless** (`log_sentinel/detectors.py:163` + `sentinel.py:64`). Evidence is built only from lines matching the pattern, but tracebacks are logged line-by-line, so `unhandled_traceback` evidence is up to five copies of the bare header `Traceback (most recent call last):` with no frames — and `_ai_triage` feeds that to the LLM. The suggestion's "shows the surrounding lines" is false. **Fix:** capture a context window (N lines after each match).

95. **[Medium] Quota is check-then-act; concurrency exceeds any limit** (`governance/quota.py:217` + `context.py:121` + `observability/feature_quota.py:139`). The count read (`enforce`) and the usage insert (`record`, after the AI call) are in separate transactions with the whole AI call between them, so N concurrent requests at `used == limit-1` all pass and all execute — the limit is exceedable by the deployment's concurrency width. **Fix:** atomic reserve (`INSERT … WHERE (SELECT COUNT) < ?` or `BEGIN IMMEDIATE` check+insert).

96. **[Low] `render_api` reprocesses unparseable-timestamp lines forever** (`log_sentinel/render_api.py:199`). A line whose timestamp fails to parse gets `epoch=0.0`, always survives the boundary dedupe and never advances `newest`, so a Render timestamp-format change re-detects the same lines every poll. `_parse_epoch` also treats naive datetimes as local time. **Fix:** skip/dedupe `epoch==0.0`; treat naive datetimes as UTC.

97. **[Low] Leader election can pick two leaders** (`log_sentinel/state.py:141`). Write-then-read-back with no `O_EXCL`/`flock` lets two workers interleave and both pass the read-back for one tick (duplicate polls/notifications). **Fix:** `os.open(O_CREAT|O_EXCL)` or `fcntl.flock`.

98. **[Low] A deleted GitHub issue disables escalation forever** (`log_sentinel/sentinel.py:199` + `github_issues.py:116`). `issue_state` returns `None` for any non-200 including a permanent 404, mapped to "retry next window" forever, never re-filing. **Fix:** treat 404 as "gone" (file fresh); reserve retry for 5xx/transport.

99. **[Low] Provenance sidecar written non-atomically** (`governance/provenance.py:198`). No tmp+`os.replace` (unlike `state.py`), so a crash mid-write truncates `*.provenance.json` and `read_sidecar` silently returns `None` — losing the record this module exists to guarantee. **Fix:** tmp + `os.replace`.

100. **[Low] Gemini free-tier headroom computed over the wrong window** (`observability/llm_usage.py:318`). "headroom today" sums Gemini calls over the caller's `window_hours`; a 7/30-day window subtracts a week/month from the 1,500/day ceiling, understating headroom (can report 0 with full headroom). **Fix:** compute from a fixed trailing-24h query.

101. **[Low] Observability stores write inside the package with inconsistent fallbacks** (`observability/llm_usage.py:45`, `uptime.py:51`, `imagine_usage.py:38`, `feature_quota.py:82`, `approval_telemetry.py:28`). The `DATA_DIR` fallback is `parents[1]` = `src/mediahub` (often read-only in the image), while `log_sentinel` falls back to `./data`; three of them also freeze `DATA_DIR` and run `_ensure_schema()` at import, so a late `DATA_DIR` splits the stores across two DBs. **Fix:** resolve `DATA_DIR` lazily per call everywhere with one consistent fallback; drop import-time schema bootstrap.

102. **[High] Consent gate fails *permissive* on a DB error** (`safeguarding/consent.py:326-329`). `except sqlite3.Error: return ConsentPolicy("full", …)` — a transient `SQLITE_BUSY` lets a `do_not_feature` (or no-consent) child be featured; `compliance/gate.py:61` additionally swallows any exception so nothing re-blocks the W.2 level. **Fix:** return the *most-restrictive* policy (or re-raise) on error.

103. **[High] `delete_org` leaves org data behind and out of the takeout** (`privacy/org_lifecycle.py:123-296`). It never deletes `analytics/<org>.json` (post metrics) or `assistant_memory/<profile_id>.json` (standing prefs), and `org_export_zip` omits both — the org's data survives workspace deletion and is absent from its SAR/portability ZIP. **Fix:** unlink both in `delete_org` and add them to the export.

104. **[Medium] Downgraded: export cache torn-write is partially guarded** (`export_engine/engine.py:186-215`). Conversions are written directly into the shared content-addressed cache slot with no tmp+rename — but there *is* an `except BaseException: unlink()` guard **and** a post-write size check, so the residual risk is only an uncatchable SIGKILL/OOM leaving a partial file, or two concurrent identical requests racing the slot. **Fix:** still worth the tmp+`os.replace` idiom (`bulk.py` already uses it) to close the SIGKILL + concurrent-render window.

105. **[Medium] Erasure cascade defaults to the wrong tree** (`privacy/erasure.py:32`, `org_lifecycle.py:48`). `_data_dir()` defaults to cwd-relative `Path("data")` while the rest of the codebase defaults to the package root; with `DATA_DIR` unset the whole erasure cascade scans the wrong tree and no-ops while the app uses the real one. **Fix:** the same `parents[1]` fallback as everywhere else.

106. **[Medium] Analytics store wipes history on a torn write** (`analytics/store.py:170-212`). Non-atomic `write_text` + per-process lock + unlocked read-modify-write; a crash mid-write tears the JSON, `load_metrics` then returns `[]`, and the next `record_metric` silently overwrites the org's entire metrics history with one record. **Fix:** tmp+`os.replace`; hold the lock across load→append→save.

107. **[Medium] Erasure/rectification rewrite run files non-atomically** (`privacy/erasure.py:372`, `compliance/dsr.py:502,534,761`). In-place `write_text` on the run JSON (source of truth) races the web layer and corrupts on a crash mid-erasure. **Fix:** tmp+`os.replace` for every run/workflow rewrite.

108. **[Medium] Erasure deletes the wrong subject via substring match** (`privacy/erasure.py:277-279`). `_card_is_about` uses a bare `frag in text` test, so erasing "Sam Lee" deletes a card about "Sam Leeson" — the exact collision the module's own whole-name rule (`:50`) prevents. **Fix:** use the `(?<![a-z0-9])frag(?![a-z0-9])` boundary pattern here too.

109. **[Medium] Duplicate unsafe account-erasure helper** (`compliance/dsr.py:803-834`). `erase_user_account` re-implements erasure with an unlocked non-atomic rewrite of the auth ledger — it doesn't take `_LEDGER_LOCK` (races a concurrent signup: new account silently erased) and a crash mid-write destroys *every* account. `UserStore.delete` already does this correctly; no production code calls the duplicate. **Fix:** delete it or delegate to `UserStore().delete(email)`.

110. **[Medium] Security-log purge races and aborts on one bad line** (`compliance/retention.py:239-257`). read→filter→`write_text` without the `security_log._LOCK` or atomic rename drops a concurrently-appended event and loses the whole log on a crash; the naive-vs-aware `if ts < cutoff` sits *outside* the parse `try`, so one naive timestamp aborts the entire nightly purge. **Fix:** rewrite via tmp+`os.replace` under the lock; move the comparison inside the try.

111. **[Medium] DSR discloses/mutates unowned runs cross-tenant** (`compliance/dsr.py:170-186`). `_tenant_runs` includes every run whose `profile_id` is empty (`owner == pid or not owner`), so `export_athlete` leaks unowned-run records to whichever tenant asks and `erase/rectify` mutate them on any tenant's request. **Fix:** gate the unowned-run inclusion behind a single-tenant/operator flag.

112. **[Low] `toggle_reaction` check-then-act 500s under concurrency** (`collab/threads.py:550-567`). Two concurrent toggles both miss the `SELECT`; the second `INSERT` raises an uncaught `IntegrityError`. Same for the comment-count cap (`:266`). **Fix:** `INSERT OR IGNORE` + branch on `rowcount`.

113. **[Low] CSV injection in the welfare-officer export** (`safeguarding/consent.py:439-460`). Athlete names/notes are written verbatim; a value beginning `=`/`+`/`-`/`@` executes as a formula in Excel/Sheets. **Fix:** prefix such cells with `'`.

114. **[Low] MCP handlers interpolate ids into the API URL path unencoded** (`mcp_server/tools.py:45-77`). An id containing `/`/`?`/`../` reroutes the call (bounded by token scopes); a missing required arg raises `KeyError` → generic `-32603` instead of `INVALID_PARAMS`. **Fix:** `urllib.parse.quote(id, safe="")` + validate required args.

115. **[Low] `restore_revision` torn write reports false success** (`collab/revisions.py:198`). Plain `write_text` of the "current" brief; a torn write is silently skipped by `_iter_card_briefs`, so restore returns success while the renderer keeps the old version. **Fix:** tmp+`os.replace`.

116. **[Low] MCP approvals aren't stamped as machine-originated** (`mcp_server/tools.py:157-167`). `approve_card` hands the human-publish signal to an external agent with nothing recording that the approval came from a machine (nothing can publish externally — verified). **Fix:** stamp `actor="mcp:<token>"` so the audit trail distinguishes agent from human approvals.

---

## I. Infra — data_hub · interop · api_public · backup · results_fetch

117. **[Medium] CSV/XLSX export formula injection** (`data_hub/portability.py:325,335,316`). Cell display values (largely user-imported / connector-fed) are written verbatim; a leading `=`/`+`/`-`/`@`/tab/CR executes as a formula on open. **Fix:** neutralise dangerous leading characters at export time only (prefix `'`), keeping stored/round-tripped values exact.

118. **[Medium] SVG sanitizer misses `<style>` element text** (`interop/svg_import.py:86`). Inline `style=` attributes are checked against both `_BAD_CSS` and `_URL_HTTP`, but a `<style>` *element*'s text is only checked against `_BAD_CSS`, so `<style>rect{background:url(https://evil/track.png)}</style>` survives — a tracking/exfil vector if rendered inline. **Fix:** apply `_URL_HTTP` to `<style>` element text too; add a regression test.

119. **[Medium] Backup archive not durable or verified** (`backup/__init__.py:121`). `create_backup` opens the ZipFile at its final canonical path and never verifies it (no temp+rename, no `testzip()`); a crash/OOM/full-disk mid-write leaves a truncated archive under the real name that `_prune` then treats as a valid backup. **Fix:** write to `.zip.part`, `testzip()`, `os.replace` into place; delete + error on validation failure.

120. **[Low] Latent SSRF in the CSV-URL connector** (`data_hub/connectors/builtin.py:41`). `requests.get(url, timeout=20)` on a caller-supplied URL with no scheme allow-list, no private-IP block, no redirect cap. Not exposed by any route *today* (`connectors=[]`), but `register_refresh_task()` is wired into `create_app`. **Fix:** add the egress guard (scheme allow-list, private/metadata-IP block, bounded redirects, size cap) *before* any user-facing connector config ships.

121. **[Low] Public-API rate limiter keys on the proxy IP** (`api_public/blueprint.py:60`). It uses `request.remote_addr` directly, which behind Render's proxy is the proxy — so every unauthenticated client shares one bucket (the rest of the app reads the trusted rightmost `X-Forwarded-For` hop). **Fix:** derive the client IP the same way the auth throttle does.

122. **[Low] `list_org_tables` row-count subquery isn't org-scoped** (`data_hub/store.py:197`). The correlated `COUNT(*)` filters on `table_id` only, not `profile_id`, unlike every other query in the module (ADR-0014). Not exploitable today (random table ids) but an isolation smell. **Fix:** add `AND r.profile_id = t.profile_id`.

123. **[Info] `DEFAULT_SCOPES` is documented but never applied** (`api_public/tokens.py:134`, `scopes.py:65`). `validate_scopes(None)` returns `[]`, so a token minted with no scopes gets none, not the documented safe read-only default. **Fix:** apply the default in `create` (`… or list(DEFAULT_SCOPES)`), or remove `DEFAULT_SCOPES` and correct the docs.

124. **[High] ✓ SSRF / DNS-rebinding in results-fetch Tier A** (`results_fetch/fetch.py:408-411`). `StaticBackend.fetch` validates the host with `is_url_safe` (its own `getaddrinfo`) then fetches with `session.get(current)` which re-resolves independently — two lookups, no pinning, classic rebinding TOCTOU on an attacker-supplied results URL. **Fix:** pin to the validated IP — route through `web_research.safe_fetch.pinned_stream_get` (resolves+validates+pins per hop, re-validates redirects).

125. **[Medium] SSRF / DNS-rebinding in results-fetch Tier B** (`results_fetch/rendered.py:241-269`). `_host_ok` resolves via `is_url_safe` then *caches the verdict per host for 60s*; Chromium then does its own DNS + connection for the navigation and every sub-request — same TOCTOU, widened by the cache. **Fix:** pin Chromium to the validated IP per navigation (`--host-resolver-rules` re-derived per fetch); drop/shorten the verdict cache.

126. **[Medium] Slowloris: no total-read deadline** (`results_fetch/fetch.py:331-343`). `_read_capped` streams up to 25 MB with only a *between-bytes* socket timeout, so a server dribbling one chunk every <15s keeps the loop running effectively forever. **Fix:** add a monotonic total-read deadline (mirror `safe_fetch._pinned_get`) and bound `fut.result()` in the prefetcher.

127. **[Low] Screenshots aren't counted against the crawl memory budget** (`results_fetch/crawl.py:650-651`). Up to `max_renders` (60) viewport JPEGs (~1–2 MB each) accumulate in `result.screenshots` on top of `max_total_bytes`, so ~60–120 MB can build in memory. **Fix:** count screenshot bytes against the total budget and stop storing beyond a cap.

---

## J. Tests & CI

128. **[Medium] A test pollutes the real repo working tree** (`tests/test_interpreter_smoke.py:40,48`). It passes `PROJECT_ROOT/data/patterns.jsonl` as `patterns_path`; a low-confidence fixture triggers `propose_patterns → flush()` which *rewrites the developer's real `data/patterns.jsonl`* (confirmed: today's mtime after a run). The real-path `PatternStore` is then cached in the module-global `_store`, which no test resets — order-dependent cross-test contamination. **Fix:** copy patterns into `tmp_path` and pass the copy; add an autouse fixture resetting `interpreter._store = None`. (Test-harness fix only — do not touch the deterministic interpreter.)

129. **[Medium] ~1,300 assertions pin implementation detail** (`tests/`, 176 files). ~938 lines assert literal `mh-*` CSS class strings, ~218 literal HTML tags, ~148 `data-*` strings, ~182 hardcoded URL paths — all pulled from `web.py`'s f-string templates. A pure template refactor breaks huge swaths of the suite, actively blocking the `web.py` decomposition it most needs. **Fix:** assert on stable `data-testid`/semantics via a shared `assert_has_control(html, testid=…)` helper; drop the incidental class-name asserts.

130. **[Medium] Fixture sprawl: 280 files reload the monolith** (`tests/conftest.py`; ~280 files). The only conftest has zero shared app/client/DATA_DIR fixtures, so 280 files copy-paste `setenv(DATA_DIR) + importlib.reload(web) + create_app()` (617 `importlib.reload` calls in 306 files, 286 reloading the ~68k-line monolith). This is the biggest duplication source, a major slowness driver, and a heisenbug source (reload creates new class objects, breaking `isinstance`/singleton identity). **Fix:** hoist a canonical `app`/`client` fixture + an autouse `_isolate_data_dir` into `conftest.py` and migrate files onto them.

131. **[Medium] The production ranker has zero direct tests** (`pipeline/pipeline_v4.py:549`). `swim_content.ranker_v3.rank_cards` — a `CLAUDE.md`-designated crown jewel — has 0 references in `tests/`; it's exercised only transitively by ~139 pipeline tests, none asserting the ordering contract, while ~938 assertions guard CSS class names. **Fix:** add a deterministic unit test feeding known grouped claims (PB, medal, first-time, ordinary swim) and asserting rank order + `rank_score`/`rank_reason` — gives the auto-merge gate a real signal on the engine.

132. **[Medium] The production render engine is under-tested** (`tests/conftest.py:16-27`). The autouse fixture pins the *legacy* engine (`MEDIAHUB_GEN_V2=0`) suite-wide though v2 is the production default; 23 of 34 render test files exercise only v1 — the majority of render coverage validates a path customers don't get. **Fix:** add a v2-default parity layer (run core render/archetype tests under the real default; parametrise key tests over both engines).

133. **[Low] Slow "pure-Python" tests recompute saliency per test** (`tests/test_motion_format_focus.py` 105s; `test_reel_ffmpeg.py` 157s; `test_render_cache.py` 91s). A single assertion-light test costs 77s because deterministic saliency maths runs on freshly-generated PIL images per test. **Fix:** share one computed saliency result / generated image via a module fixture; keep the Remotion stub. (Don't weaken assertions — just stop paying for the recompute.)

134. **[High] ✓ Python version disagreement — CI never tests prod's version** (`Dockerfile:4`, `runtime.txt:1`, `.github/workflows/*`). The image builds on Python 3.14 (`FROM python:3.14-slim`) but every CI job runs 3.12 (unit-suite, security, contract, responsive, hygiene, autotest, motion-VR), and `runtime.txt` says something else again. The gating suite validates a version production doesn't run. **Fix:** pick one Python everywhere — either move all CI to 3.14 or pin the Dockerfile to 3.12; delete the do-nothing `runtime.txt`.

135. **[Medium] Two drifted dependency manifests** (`requirements.txt` vs `pyproject.toml`). Five packages the image installs as core are absent from `pyproject` entirely: `croniter` (the scheduler engine), `rembg` + `onnxruntime` (the default cutout backend), `pdfminer.six`, `gunicorn`; `anthropic`/`replicate`/`playwright` disagree on core-vs-extra. **Fix:** make one manifest authoritative (pip-compile from `pyproject`, or move the five into `pyproject` core).

136. **[Medium] `weasyprint` is a phantom dependency** (`pyproject.toml:122`, `Dockerfile:14,32`). Declared in the `render` extra and blamed for ~3 installed system libs, yet imported nowhere in `src/mediahub` and never pip-installed in the image. **Fix:** remove it from `pyproject` and drop `libpango*/libcairo2` from the Dockerfile (keep `libffi-dev` — argon2/bcrypt need it).

137. **[Medium] Playwright pin comments contradict the pin** (`pyproject.toml:114-121`, `Dockerfile:90-91`). The real pin is `>=1.61.0,<1.62` but the rationale text still describes a 1.56 pin for "chromium-1194" — on exactly the Chromium-alignment invariant `CLAUDE.md` flags as load-bearing. **Fix:** rewrite both comment blocks to describe the current 1.61 pin and its Chromium revision.

138. **[Medium] Dead/divergent deployment configs** (`fly.toml`, `Procfile`, `docker-compose.yml`). For a Render-Docker-only product, `fly.toml` sets no `DATA_DIR` (bypassing first-boot seeding) and pins 1024 MB (below the app's own warning); `docker-compose.yml` omits `GEMINI_API_KEY`. **Fix:** if Render-only, delete `fly.toml`/`Procfile` (fold intent into docs); if kept, fix the `DATA_DIR`/memory/key gaps.

139. **[Medium] Roadmap-bot CI mechanism deposits two commits per update** (`.github/workflows/roadmap-autoupdate.yml:65,142,166`). Fires on every push to `main` and lands each refresh as a merge (squash disabled), so every update = branch commit + merge commit; 872/3,312 commits are roadmap noise (the process side is #3). **Fix:** commit the refresh directly to an unprotected side branch (the pattern `autotest.yml` uses) and render from there, or debounce to a daily batch.

140. **[Low] Node version drift** (`Dockerfile:37` Node 22, `render.yaml:8` comment "Node 20", `motion-visual-regression.yml:66` Node 20). The motion-VR job pixel-diffs Remotion output against baselines on a *different* Node than production renders. **Fix:** pin CI `setup-node` to 22 (or move the image to 20 deliberately); fix the `render.yaml` comment.

141. **[Low] Motion-VR job's non-required justification is obsolete** (`motion-visual-regression.yml:16-22,82-85`). Its comments claim Remotion is unpinned and the lock uncommitted — both now false (`package.json` pins exact versions, a 106 KB `package-lock.json` is committed and used by `npm ci`). **Fix:** switch the job to `npm ci`, update the comments, and consider promoting the gate to required.

142. **[Low] Orphaned and overlapping scripts** (`scripts/`). `build_corpus_index.py` and `eval_corpus.py` are referenced only by the generated INVENTORY — dead; `purge_all_runs.py` and `wipe_all_runs.py` are two overlapping destructive all-tenant reset tools. **Fix:** delete the orphans (or wire into an eval workflow); consolidate purge/wipe into one documented tool.

143. **[Low] OCR pins looser in the image than declared** (`Dockerfile:63` vs `pyproject.toml:87-88`). The image installs `pytesseract>=0.3.10`/`pypdfium2>=4` while `pyproject` declares `>=0.3.13`/`>=5.11.0`, so the image can resolve OCR libs below the project's own minimum. **Fix:** install `.[ocr]` in the image or bump the Dockerfile floors to match.

---

## K. Cleanup performed in this pass

Deleted 26 stale files (~724 KB) that no longer help the repo — all completed and
un-referenced by any living doc, CI, code, or test:

- **21 completed per-feature audit reports** — `docs/audits/AUDIT_*.md` (every one carried a
  WORKS / fixed verdict; the directory is now removed).
- **`docs/USABILITY_AUDIT.md`** — the 161-finding usability work-list, shipped in full
  (per git history, "159/159 live findings shipped").
- **4 dated one-off build sweeps** — `docs/build_reports/{QA_SWEEP_2026-06-22, QA_SWEEP_2026-06-24,
  DATA_HUB_BULK_2026-06-21, AI_GOVERNANCE_1_23_2026-06-24}.md` (not in the `build_reports/README`
  living list; not cited by ROADMAP/GENERATION/ADR).

Link cleanup: reworded the one dangling reference in `docs/adr/0028-member-confined-org-access.md`;
regenerated the auto-generated `docs/INVENTORY.md`. **Deliberately kept** (still load-bearing):
the ADR-linked council transcripts, the code-cited compliance docs (`COMPLIANCE_AUDIT.md`,
`COMPLIANCE_HANDOVER.md`), the living `build_reports/` engine logs, the autotest methodology docs,
and `_env_inventory_security.md` (a hand-written input to the inventory generator).

The freshness guard (`test_inventories_fresh.py`) and the full suite stay green — the only
failures are 4 Playwright browser-mismatch errors specific to the reviewer's sandbox venv
(12,960 passed, 135 skipped), unrelated to these doc changes.

---

## Suggested sequencing

**Do first (verified, prod-reachable):** #76 (approval-state wipe) · #70 (audio dead in prod) ·
#33 (key-in-URL leak) · #34/#124 (SSRF) · #23 (reflected XSS) · #24 (asset IDOR) · #25 (password-reset
session invalidation) · #102 (consent fail-open).
**Then (accuracy & trust):** the §E engine bugs #50–#55 (fabricated medals, DQ collapse, wrong-swimmer
identity, double-counted stats) — these silently ship *wrong content*.
**Then (structural leverage):** #15–#17 (blueprint extraction + the two per-request perf sinks),
#130/#131 (test fixtures + a real ranker test), #43 (converge the two LLM wrappers).
**Ongoing hygiene:** the §A process changes (#3/#4 especially) reduce the churn that produced most of
the above.
