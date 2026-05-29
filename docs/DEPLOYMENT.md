# Deployment

MediaHub is a cloud-hosted SaaS. The operator runs the Flask service on a
managed platform; customers access it through their browser at the deployment
URL. This document is the operator's deployment playbook.

For contributor / engineering setup, see [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Render (recommended)

Push to a Git remote that Render is connected to. `render.yaml` is the
blueprint:

```bash
# In a fresh Render workspace:
render blueprint apply
```

Set the secrets in Render's dashboard, in roughly this order of importance:

- `GEMINI_API_KEY` — default LLM provider; required for caption generation
  and brand-guideline interpretation. Without an LLM provider, AI-driven
  surfaces (captions, brand operating profile, creative direction) return
  a clear "AI unavailable" error instead of silently producing low-quality
  output.
- `BUFFER_ACCESS_TOKEN` — required for the `/activity` scheduling surface.
- `ANTHROPIC_API_KEY` — optional Anthropic alternative (set
  `MEDIAHUB_LLM_PROVIDER=anthropic` to prefer it).
- `REPLICATE_API_TOKEN` — optional cloud image / cutout provider.
- `PHOTOROOM_API_KEY` — optional cloud cutout provider.

The blueprint mounts a 1 GB persistent disk at `/var/mediahub` for runtime
state (PB cache, brand kits, voice presets, run state, uploads).

## Docker (operator self-managed)

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

The image installs Playwright + Chromium for the HTML→PNG rendering step. The
deployed container handles all rendering server-side; customers never run
anything on their own machine.

## Fly.io

```bash
fly launch --copy-config --no-deploy
fly secrets set GEMINI_API_KEY=... ANTHROPIC_API_KEY=... REPLICATE_API_TOKEN=... PHOTOROOM_API_KEY=...
fly deploy
```

`fly.toml` declares a `[mounts]` section pointing to a 1 GB volume named
`mediahub_data`. Create it once with:

```bash
fly volumes create mediahub_data --size 1
```

## Persistent volumes

These directories must persist across deploys for the app to retain state:

| Directory | Why |
| --- | --- |
| `data/discovered/` | PB cache + meet/club identity ledgers |
| `data/brand_kits/` | User-uploaded brand kits |
| `data/voices/seed/` | Hand-tuned voice presets |
| `data/secrets.json` | Optional operator-supplied API keys |
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
