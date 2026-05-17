# Deployment

MediaHub is a single Flask service. Anywhere you can run a Python web app, you
can run MediaHub.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
make run
```

Default port is 5000. Browse to http://localhost:5000.

## Docker

```bash
docker build -t mediahub:latest .
docker run -p 5000:5000 --env-file .env mediahub:latest
```

Or with compose for persistent volumes:

```bash
docker compose up --build
```

The compose file mounts:
- `./data` for ontology + voices + brand kits + discovered cache
- `./runs_v4` for per-upload state
- `./uploads_v4` for original blobs
- `./.cache` for the PB lookup runtime cache

The image installs Playwright + Chromium for the HTML→PNG rendering step. If
you only need the WeasyPrint fallback, comment out the `playwright install`
line in `Dockerfile` to halve the image size.

## Render

Push to a Git remote that Render is connected to. `render.yaml` is the
blueprint:

```bash
# In a fresh Render workspace:
render blueprint apply
```

Set the secrets in Render's dashboard, in roughly this order of importance:

- `GEMINI_API_KEY` — default LLM provider; required for caption generation.
- `BUFFER_ACCESS_TOKEN` — required for the `/activity` scheduling surface.
- `ANTHROPIC_API_KEY` — optional Anthropic fallback (set
  `MEDIAHUB_LLM_PROVIDER=anthropic` to prefer it).
- `REPLICATE_API_TOKEN` — image generation provider.
- `PHOTOROOM_API_KEY` — cutout provider.

The blueprint mounts a 1 GB persistent disk at
`/opt/render/project/src/data`.

## Fly.io

```bash
fly launch --copy-config --no-deploy
fly secrets set ANTHROPIC_API_KEY=... REPLICATE_API_TOKEN=... PHOTOROOM_API_KEY=...
fly deploy
```

`fly.toml` declares a `[mounts]` section pointing to a 1 GB volume named
`mediahub_data`. Create it once with:

```bash
fly volumes create mediahub_data --size 1
```

## VPS (bare metal / cloud Linux)

1. Install Python 3.12, Poppler (`apt install poppler-utils`), and (optional)
   Chromium dependencies for Playwright.
2. `git clone` the repo.
3. `pip install -r requirements.txt && pip install -e . && pip install gunicorn`.
4. Add a `systemd` unit:

   ```ini
   [Unit]
   Description=MediaHub
   After=network.target

   [Service]
   WorkingDirectory=/srv/mediahub
   Environment="PYTHONPATH=/srv/mediahub/src"
   EnvironmentFile=/srv/mediahub/.env
   ExecStart=/srv/mediahub/.venv/bin/gunicorn mediahub.web:app \
       --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 300
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

5. Front it with nginx for TLS termination.

## Vercel

Vercel is **not** a great fit for MediaHub's backend (long-running threads,
persistent disk, Chromium). Use the included `vercel.json` only to host the
static landing page in `dist/public/`. Deploy the backend on Render, Fly, or
your own Docker host.

## Persistent volumes

These directories must persist across deploys for the app to retain state:

| Directory | Why |
| --- | --- |
| `data/discovered/` | PB cache + meet/club identity ledgers |
| `data/brand_kits/` | User-uploaded brand kits |
| `data/voices/seed/` | Hand-tuned voice presets |
| `data/secrets.json` | Optional user-supplied API keys |
| `runs_v4/` | Pipeline run state + rendered PNGs |
| `uploads_v4/` | Original uploaded files |

Everything else is rebuilt on demand and safe to put on ephemeral storage.

## Scaling

The app is single-tenant by design — a club uploads, a club receives content.
Horizontal scaling is supported by:

1. Using a shared volume (e.g. AWS EFS) for the directories above.
2. Running multiple Gunicorn instances behind a sticky-session load balancer
   so polling `/runs/<id>` lands on the same worker that owns the upload.

For multi-tenant SaaS use, you would also want:
- A real database in place of the JSON ledgers (the V8 `media_library` already
  uses SQLite — extend that).
- Per-tenant directory namespacing.

## Health check

`GET /healthz` — returns 200 + `{"status":"ok"}` when the app is ready.
