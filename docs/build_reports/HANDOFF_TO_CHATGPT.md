# Swim Content V4 — Handoff to ChatGPT 5.5

**Owner:** Elijah Kendrick (marketing, Swansea University Swimming pilot)
**Date:** 5 May 2026
**Status:** Live and working at https://mediahub.pplx.app
**Source bundle:** the project zip the user will paste alongside this doc

---

## 0. Read this first (60-second briefing)

You are taking over a working, published Flask web app that turns Hytek swim-meet result files into verified, post-ready social-media content cards for a swim club's marketing team. It is **already deployed and functional** — your job is ongoing development, not a from-scratch build.

The user wants you to fully understand:
1. What the product does and why
2. The exact technical state right now (deployment, routing, architecture)
3. The full editing history of what's been done in the prior session
4. How to make changes safely (especially around the deployment proxy quirk)

Do **not** re-architect or re-deploy without reading sections 4 and 6. There is a non-obvious URL-prefix landmine.

---

## 1. Product in one paragraph

A solo marketing person at Swansea University Swimming uploads a Hytek Meet Manager file (`.hy3` or a zip containing `.hy3`). The app parses every swim, filters down to the club's swimmers using a configurable "club profile", looks up qualification standards and personal-best context, and emits a queue of content cards (athlete spotlights, medal counts, PB confirmations, etc.) — each with three caption variants (clean / hype / team), a confidence rating, sources, and a "safe to post / review / hold" recommendation. The whole point is to **eliminate manual fact-checking** before posting. Every claim is sourced and labelled.

---

## 2. The exact deployed state right now

| Thing | Value |
|---|---|
| Live URL | https://mediahub.pplx.app |
| Site ID (for redeploys) | `e287696a-e61f-4108-bdb1-ee3bdd82d2af` |
| App slug | `mediahub` |
| Hosting | Perplexity `pplx.app` published-website infrastructure (gunicorn in an isolated sandbox, static `dist/public/` redirect on S3 fronting it) |
| Run command | `gunicorn swim_content_v4.web:app --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 300` |
| Install | `pip install -r requirements.txt` |
| Python | 3.11.9 (`runtime.txt`) |
| Health | `GET /port/5000/health` → `{ok: true, version: "v4.0.0"}` |
| End-to-end verified numbers | 1665 swims parsed, 88 Swansea, 36 swimmers, 45 cards, 18 in queue (Swansea Aquatics May LC 2026 zip) |

**Deployment quirk you must know:** the published proxy serves the Flask backend at `/port/5000/...` on the public domain. The S3 root (`https://mediahub.pplx.app/`) is just a tiny `dist/public/index.html` page that redirects to `/port/5000/`. Every internal link in the app goes through Flask's `url_for(...)`, and a WSGI middleware in `create_app()` injects `SCRIPT_NAME=/port/5000` so `url_for` automatically prefixes URLs. **Don't put hardcoded `/path` strings in HTML or JS** — they'll 404 on S3.

---

## 3. Architecture map

Single-package Flask app. ~2,500 LOC across these files in `swim_content_v4/`:

```
web.py             1239 lines  Flask routes, HTML templates (inline render_template_string), CSS
pipeline_v4.py      293        Main orchestration: parse → filter → infer → detect → trust
canonical.py        236        Canonical schema for swims, swimmers, clubs
trust.py            171        Confidence scoring, "safe to post" gating, self-checks
ground_truth.py     163        Precision/recall scoring vs user-pasted expected highlights
club_profile.py     153        Per-club config: codes to include/exclude, brand, tone
inference.py        110        Filling missing fields (governing body, etc.)
v3_shim.py           99        Backwards compat for v3 data
adapters/                      Format adapters (currently just hy3 parser)
```

Storage:
- `data.db` — SQLite, run index. Schema in `schema.sql`. **Persists across redeploys** because file is named `data.db` in project root (Perplexity convention).
- `runs_v4/<run_id>.json` — full run output per upload
- `uploads_v4/` — raw uploaded files
- `.cache/swimmingresults/` — cached PB lookups from swimmingresults.org
- `club_profiles/*.json` — one file per profile (currently only `swansea-uni.json`)

Routes (all under `/port/5000` on the live URL):

```
/                         Home — recent runs table + upload CTA
/upload          GET/POST File upload form, kicks off background pipeline
/runs/<id>                Progress page, polls /api/runs/<id>/status, auto-redirects to /review when done
/review/<id>              Trust summary, parse notes, content cards table
/ground-truth/<id> GET/POST  Paste expected moments, get precision/recall/F1
/profiles        GET/POST List + create/update club profiles
/research                 Static research roadmap page (parser priorities)
/privacy                  Data inventory + delete controls
/api/runs/<id>/status     Poll JSON
/api/runs/<id>/cards      Cards JSON (list of 45 items for Swansea test)
/api/runs/<id>/trust      Trust report JSON
/api/runs/<id>/export     Full evidence + audit JSON dump
/privacy/run/<id>/delete  POST — hard-delete run
/privacy/cache/clear      POST — wipe PB cache
/health                   Liveness + DB/cache/profiles checks
/healthz                  Minimal liveness
```

---

## 4. The URL-prefix landmine — read before editing

**Symptom if you get this wrong:** the app 503s on first deploy or every link 404s in the browser.

**Mechanism:**
- Public URL: `https://mediahub.pplx.app/port/5000/upload`
- The proxy strips `/port/5000` and forwards `PATH_INFO=/upload` to gunicorn
- But the user's browser sees URLs as `/port/5000/...`, so any HTML link the app emits **must** be prefixed
- A WSGI middleware in `web.py` (~line 617) sets `SCRIPT_NAME=/port/5000` (default, override via env var). This makes `url_for()` produce prefixed URLs, while route matching still works because the middleware also strips the prefix from `PATH_INFO` if present

**Rules:**
1. Never write `href="/something"`, `action="/something"`, `fetch('/api/...')`, or `location.replace('/...')` directly in HTML/JS.
2. Always use `url_for('endpoint_name', ...)`. For JS, compute the URL in Python and inject as a JS const, e.g.:
   ```python
   status_url = url_for('api_status', run_id=run_id)
   # inside template:
   const STATUS_URL = "{status_url}";
   fetch(STATUS_URL)
   ```
3. The `SCRIPT_NAME` default of `/port/5000` is set in code so the run command needs no env-var prefix. If you want to run locally without the prefix, set `SCRIPT_NAME=` (empty) when invoking gunicorn or `python run.py`.

**Verification snippet** (run after any HTML/JS edit):

```bash
cd /path/to/swim-content
grep -nE 'href="/[a-z]|action="/[a-z]' swim_content_v4/web.py | grep -v '^\s*#'   # should be empty
grep -nE "fetch\('/|fetch\(\"/" swim_content_v4/web.py | grep -v '^\s*#'           # should be empty
python3 -c "import ast; ast.parse(open('swim_content_v4/web.py').read())"
```

Plus a smoke test:
```bash
python3 -c "
from swim_content_v4.web import create_app
app = create_app()
c = app.test_client()
for p in ['/','/health','/upload','/profiles','/research','/privacy']:
    print(p, c.get(p).status_code)
print('home contains /port/5000/upload:', '/port/5000/upload' in c.get('/').get_data(as_text=True))
"
```

---

## 5. What changed in the previous (Perplexity Computer) session

Starting state was a freshly-zipped V4 bundle that had never been deployed. The Computer session did, in order:

1. **Initial publish** at `https://mediahub.pplx.app` with the run command
   `gunicorn swim_content_v4.web:app --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 300`.
   Health endpoint passed. Backend booted clean.
2. **End-to-end pipeline test** with the Swansea zip via the API: confirmed 1665/88/36 numbers exactly match V4_RESULTS.md.
3. **Discovered the URL-prefix bug** — every internal nav link was a relative `/path` and 404'd against S3.
4. **Refactored every hardcoded path to `url_for(...)`** in `web.py`. JS strings (poll loop, redirects, copy-button targets) were converted to inject Python-computed URLs as JS consts.
5. **Added a `_script_name_middleware` WSGI wrapper** in `create_app()` that reads `SCRIPT_NAME` from env (defaulting to `/port/5000`) and injects it into request environ + strips it from `PATH_INFO`.
6. **Full UI redesign** in the inline `BASE_CSS` — new dark-navy palette (`#0B1220` base, `#22D3EE` accent), Inter typography from Google Fonts, sticky frosted topnav, custom inline-SVG triple-wave logo using `currentColor`, 16px-radius cards, 11px uppercase labels, tabular numerals on stats, semantic status pills, 2px teal focus rings.
7. **Security hardening** — wrapped every user-derived/file-derived string in `_h()` before f-string interpolation in the `/review/<id>` route. This closes the stored-XSS vector flagged by the pre-publish security review (filenames in malicious zips can no longer execute JS in the review page).
8. **Republished, then full Playwright walkthrough**: clicked every nav page, uploaded the Swansea zip via the actual file input, watched it auto-redirect upload → progress → review, opened ground-truth and submitted a sample, hit the JSON export endpoint. **Zero console errors, zero 4xx/5xx responses.**

Backed-up files left in the project from the Computer session:
- `web.py.bak` — pre-redesign Flask file
- `patch_web.py`, `patch2_web.py`, `patch3_web.py`, `patch4_web.py` — intermediate diff scripts (safe to delete)

---

## 6. How to redeploy after edits

**Use the same `site_id`** (`e287696a-e61f-4108-bdb1-ee3bdd82d2af`) so the URL stays at `mediahub.pplx.app` and `data.db` is preserved.

In Perplexity Computer, the calls would be:
```
deploy_website(project_path=".../swim-content/dist/public", site_name="Swim Content V4", entry_point="index.html")
publish_website(
  project_path=".../swim-content",
  dist_path=".../swim-content/dist/public",
  install_command="pip install -r requirements.txt",
  run_command="gunicorn swim_content_v4.web:app --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 300",
  port=5000,
  app_name="Swim Content V4",
  site_id="e287696a-e61f-4108-bdb1-ee3bdd82d2af"
)
```

**ChatGPT 5.5 cannot call those tools directly.** Your job there is to:
- Make code edits
- Provide the user with the ready-to-paste Computer commands above when a redeploy is needed
- Or guide the user to deploy via Render (`render.yaml` is already configured) or any Python host

For non-Perplexity hosting (Render, Fly, Railway), the user can drop the `SCRIPT_NAME=/port/5000` requirement entirely — set `SCRIPT_NAME=""` as an env var so `url_for` produces plain `/upload` etc.

---

## 7. Known issues / nice-to-haves to pick up next

These are non-blocking but were left open at handoff:

1. **`/ground-truth/<id>` highlights "Home" in nav.** The route doesn't pass an `active=` value matching any tab. Either add `active="upload"` (it's a per-run page reachable from review) or extend `_layout` to accept `active=None` for "no tab".
2. **JSON export route is named `/api/runs/<id>/export` but returns JSON, not a zip.** Filename when downloaded is `export` with no extension. Suggest renaming or sending `Content-Disposition: attachment; filename="<run_id>.json"` header.
3. **`SECRET_KEY` regenerates on every restart** (line ~43 in `web.py`). Flask sessions/flash messages don't survive redeploys. Set `SECRET_KEY` as a persistent deployment env var.
4. **`app_v3.py`, `swim_content/` (v3 package), `pipeline.py`, `pipeline_v3.py`** are still in the bundle but not used by the deployed v4 entry point. The pre-publish review flagged a path-traversal in `app_v3.py:86` (uses raw `f.filename` without `secure_filename`). Either delete those files or apply `werkzeug.utils.secure_filename`.
5. **No tests run in CI yet.** `tests_v4/` exists. Suggest a GitHub Actions workflow on push.
6. **`pipeline.py` and `pipeline_v3.py` use `zf.extract()`** without zip-slip protection. Not reachable from the v4 entry point but should be deleted or hardened if v3 is ever revived.
7. **Single-tenant / no auth.** Anyone with the URL can upload, view runs, edit profiles, delete data. Fine for the pilot but if more clubs join, you need at least basic Flask-Login + per-profile scoping.

---

## 8. The Swansea ground-truth numbers (don't re-verify, they're stable)

From the `Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip` end-to-end:

```
Adapter:        hy3
Total swims:    1665
Total swimmers: 494
Total clubs:    49
Inferred:       governing_body
Filtered to Swansea University Swimming:
  88 swims, 36 swimmers (1577 excluded)
Qual standards loaded: 2 (0 stale, 2 relevant)
Detector:       146 claims (PB confirmed 0, likely 0, qual hits 94, medals 52)
Self-check:     11 pass, 2 warn, 0 fail
Cards:          45
Queue:          18
Trust summary:  37 ready to post, 8 need review, 0 hold
```

Match these on every regression run.

---

## 9. Source-of-truth files in the bundle

In priority order if you only read a few:

1. `swim_content_v4/web.py` — everything user-facing, including the new CSS
2. `swim_content_v4/pipeline_v4.py` — the orchestration logic
3. `BLUEPRINT.md` — original product spec
4. `V4_RESULTS.md` — what V4 was meant to fix vs V3
5. `DEPLOYMENT.md` — original deploy instructions (note: predates the `/port/5000` middleware fix; supplement with section 4 of this doc)
6. `AUDIT_AND_V2_DESIGN.md` — design rationale for trust/confidence scoring
7. `schema.sql` — DB schema

Old/dead code you can ignore: `app_v3.py`, `swim_content/`, `pipeline.py`, `pipeline_v3.py`, `templates/`, `static/` (the v4 app inlines all CSS/JS into `web.py`), `run_with_demo.py`, `seed.py`.

---

## 10. Quick-start for ChatGPT 5.5 — first 5 minutes

1. Read `swim_content_v4/web.py` lines 1–500 (config, CSS, layout helper, helpers)
2. Skim lines 500–1100 (routes)
3. Read `pipeline_v4.py` end-to-end
4. Skim `BLUEPRINT.md` and `V4_RESULTS.md`
5. Run the smoke test in section 4. If it passes, you're synced with reality.
6. Ask the user what they want to change next.

Welcome to the project. Be surgical with `web.py` — every route is in one file and HTML is inline f-strings, so a careless brace can break templating across the whole app.
