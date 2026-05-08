# Swim Content V4 — Open This First

You have a zip with a complete Flask web app that turns a Hytek meet results file into a queue of post-ready, source-cited content cards.

You also have a problem: the Perplexity Computer "Website publishing" feature is disabled at the org level for your account, so I (the agent) cannot host this for you on a `*.pplx.app` URL today. Instead this bundle is set up so you can deploy it yourself in **about 3 minutes** on Render's free tier — no terminal, no code, just click.

## TL;DR — fastest way to a clickable URL

1. Make a free account at [render.com](https://render.com) (GitHub login is fine).
2. Push this folder to a new GitHub repo (drag-and-drop on github.com works), or zip-upload via Render's UI.
3. In Render: **New → Blueprint → connect repo → Apply**. Render reads `render.yaml`, builds, and gives you `https://swim-content-v4.onrender.com` (or whatever name you pick).
4. Open that URL. The top-right of the nav should show a green pill: `backend v4.0.0`.
5. Visit `/health` to see all six backend checks pass.
6. Click **New run**, upload your `.hy3` or `.zip`, and you're off.

Detailed steps with screenshots are in `DEPLOYMENT.md`.

## Why Render?

| Need | How Render handles it |
|---|---|
| Runs Flask | Yes (uses `gunicorn` from `Procfile`) |
| Free tier | Yes — sleeps after 15 min idle, ~30 s cold start. Upgrade to $7/mo to remove that. |
| Persistent disk | Yes — `render.yaml` mounts a 1 GB disk so `data.db`, `runs_v4/`, `.cache/`, and uploads survive redeploys. |
| Auto deploy on git push | Yes |
| HTTPS + custom subdomain | Yes (`*.onrender.com` free; custom domain on paid plan) |
| One-click via blueprint | Yes (`render.yaml` is included) |

Other platforms that will also work with this same bundle: **Railway**, **Fly.io**, **PythonAnywhere**. See `DEPLOYMENT.md` for per-platform notes.

## What's in this bundle

```
swim-content/
├── swim_content_v4/         # V4 code (canonical schema, adapters, pipeline, web app, trust, ground truth)
│   ├── web.py               # Flask app — entry point: swim_content_v4.web:app
│   ├── pipeline_v4.py
│   ├── canonical.py
│   ├── adapters/
│   ├── club_profile.py
│   ├── inference.py
│   ├── trust.py
│   ├── ground_truth.py
│   └── v3_shim.py
├── swim_content/            # V3 modules V4 reuses (parser, detector, captions, PB enrichment)
├── club_profiles/           # JSON profiles — Swansea Uni seed ships in here
├── data/                    # quals.json (qualifying times) + records seeds
├── research/                # parser_roadmap.md (referenced by the /research page)
├── templates/               # Legacy V1/V2/V3 templates (V4 renders inline; kept for compatibility)
├── requirements.txt         # Flask + gunicorn + requests + bs4 + lxml
├── Procfile                 # web: gunicorn swim_content_v4.web:app ...
├── runtime.txt              # python-3.11.9
├── render.yaml              # Render Blueprint — one-click deploy
├── .gitignore               # Excludes data.db, .cache/, runs_v4/, uploads_v4/
├── DEPLOYMENT.md            # Step-by-step for Render / Railway / Fly.io / PythonAnywhere
└── README_OPEN_THIS_FIRST.md  # this file
```

## Test meet

You already have the Swansea Aquatics May Long Course 2026 `.hy3` file. Upload it and you should see roughly:

- **1665** swims parsed
- **88** Swansea / SUNY swims
- **36** swimmers in scope
- **45** content cards
- **38** ready to post / **7** review / **0** hold
- Self-check: **12 pass / 1 warn / 0 fail**

The single warn is expected — the host club (City of Swansea Aquatics, code SWAY) is correctly excluded.

## Backend status pill

Every page shows a small pill in the top-right of the nav:

- **Grey "checking…"** — initial state, before the first health check returns
- **Green "backend v4.0.0"** — backend is up, DB reachable, all dirs writable, profiles loaded
- **Red "backend down" / "backend unreachable"** — something failed; click the pill to see the full `/health` JSON

Click the pill any time to open `/health` in a new tab and see exactly which check failed.

## Sharing with another tester

Once Render gives you a URL, just paste it to the other tester. There is no per-user login (small-team pilot scope) — anyone with the link can upload and review runs. If you want auth, see "Adding auth" in `DEPLOYMENT.md`.

## Privacy

Visit `/privacy` from inside the app. You can:

- See exactly what's stored on disk (each run, each cached PB lookup)
- Delete a single run
- Clear the entire PB cache

The publish snapshot only persists `data.db` (run metadata) — full run JSONs live in `runs_v4/` on the persistent disk.

## If something goes wrong

Open `/health` in your browser. If any check is `false`, the JSON tells you which one and why. Most common causes:

- **`uploads.ok = false`** → persistent disk not mounted; check `render.yaml` is applied
- **`profiles.count = 0`** → first request didn't seed; refresh once, the `seed_default_profiles()` call runs lazily on first profile read
- **`database.ok = false`** → SQLite path is read-only; check Render disk mount path matches `mountPath` in `render.yaml`

For Render-specific deploy errors (build fails, container crashes), check the Render dashboard → your service → **Logs** tab.
