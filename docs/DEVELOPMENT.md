# Development

Contributor-only setup notes. MediaHub itself is a cloud-hosted SaaS — customers
use it via the deployment URL. This document is for engineers working on the
codebase, not for end users.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install           # pip install -r requirements.txt && pip install -e .
make media-deps        # Playwright Chromium + Remotion node_modules
cp .env.example .env   # add cloud API keys (Gemini and/or Anthropic, Replicate, Photoroom)
make run               # boots the Flask app for development
```

`make media-deps` downloads ~500 MB the first time (Chromium + Remotion). The
HTML→PNG and MP4 pipelines need both; `/healthz/deps` reports which renderers
are available at runtime.

The Flask development server is for engineering iteration only. The customer-
facing product runs on the operator's managed deployment (see
[`DEPLOYMENT.md`](DEPLOYMENT.md)).

## Tests

```bash
make test            # full suite, 287 tests
make test-collect    # collection only
python -m pytest tests/ -q
```

## Motion-graphic / video output (Remotion)

MediaHub generates branded MP4 outputs via Remotion 4.x:
- **Story cards** — 1080×1920, 6 seconds, one card per swimmer/achievement
- **Meet reels** — 1080×1920, 15 seconds, top-3 cards stitched with crossfades

The Node + Remotion stack lives at `src/mediahub/remotion/`. It is invoked
from Python via `src/mediahub/visual/motion.py`, which shells out to
`render.js` and caches outputs under `DATA_DIR/motion_cache/<hash>.mp4`.

### One-time setup

```bash
# Node 18+ (Remotion 4 requirement)
node --version    # must be >= 18

cd src/mediahub/remotion
npm install

# Smoke-test the integration tests (optional)
cd ../../..
MEDIAHUB_RUN_MOTION_TESTS=1 pytest tests/test_motion.py -v
```

If Node is missing, the motion routes return HTTP 500 with a clear
"Node is not installed" error; static graphic generation is unaffected.

### Routes

- `POST /api/runs/<run_id>/card/<card_id>/motion` — render a single story card MP4
- `POST /api/runs/<run_id>/reel` — render the meet reel from the top-N cards
  (default 3, capped at 5; pass `?n=4` to override)

Both endpoints serve the rendered MP4 directly with `Content-Type: video/mp4`.
Cache hits return the existing file (< 30s wall-clock); cold renders take
30–90s depending on the host's CPU.

## API keys for dev

The codebase no longer ships heuristic fallbacks for AI-driven features. To
work on captioning, brand interpretation, creative direction, or any other
AI-mediated surface, configure at least one LLM provider:

- `GEMINI_API_KEY` — default LLM provider (free tier covers most dev work)
- `ANTHROPIC_API_KEY` — optional higher-quality alternative

Without a configured provider, AI-dependent routes surface
`ClaudeUnavailableError` so it's immediately obvious that the provider is
unset rather than silently producing low-quality heuristic output.

## Deployment

Production runs on Render via `render.yaml`; see [`DEPLOYMENT.md`](DEPLOYMENT.md)
for the operator-facing deployment instructions. Branch model: feature branches
from `dev`; never merge to `main` without approval.
