# MediaHub — production Docker image
# Build:  docker build -t mediahub:latest .
# Run:    docker run -p 5000:5000 --env-file .env mediahub:latest
FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5000 \
    PYTHONPATH=/app/src

# System deps:
#  - libpangocairo / fonts: WeasyPrint (graphic_renderer fallback)
#  - libnss3 / libxss1 / libgbm1: Chromium/Playwright runtime
#  - poppler-utils: PDF parsing in interpreter
#  - tesseract-ocr: W.10 OCR fallback engine for scanned/photographed
#    result sheets (interpreter/ocr.py, driven via pytesseract below)
#  - libgl1: image/video preprocessing
#  - espeak-ng: phonemizer + voice data for local Piper TTS — the DEFAULT
#    voiceover backend (roadmap 1.7); piper-tts needs it at synthesis time
#  - git: required to pip-install SearXNG from its git repo (below)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    ca-certificates gnupg \
    poppler-utils \
    tesseract-ocr \
    espeak-ng \
    libgl1 \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libffi-dev \
    libnss3 libxss1 libgbm1 libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdrm2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libxshmfence1 libxkbcommon0 \
    fonts-liberation \
  && curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource-setup.sh \
  && bash /tmp/nodesource-setup.sh \
  && rm -f /tmp/nodesource-setup.sh \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Small POSIX retry wrapper used to make the network-dependent, fail-loud build
# steps below survive a single transient blip (dropped TLS handshake, CDN 5xx, a
# flaky mirror) instead of failing the whole build — the shell analog of the
# Python retry in scripts/fetch_piper_voice.py. It stays loud-fail: after the
# retries are spent the step still errors. Copied early (and committed
# executable) so the rembg/Playwright steps — which run before the main scripts
# COPY — can already use it.
COPY scripts/retry.sh /usr/local/bin/retry

# Install Python deps first (better layer caching).
COPY requirements.txt /app/requirements.txt
# The trailing pair is the W.10 OCR fallback (optional everywhere else — see
# the `ocr` extra in pyproject.toml): pytesseract drives the apt tesseract-ocr
# binary above; pypdfium2 rasterises scanned-PDF pages. Installed here so the
# DEPLOYED image OCRs a phone photo of a results sheet instead of dead-ending.
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt \
 && pip install gunicorn \
 && pip install "pytesseract>=0.3.10" "pypdfium2>=4"

# Fail the build LOUDLY if the sqlite-vec extension can't load in this image
# (Capability 2 / semantic memory). It is a young v0.1.x C extension; a load
# failure must surface at build time, never as a silent runtime degrade.
RUN python -c "import sqlite3, sqlite_vec; db=sqlite3.connect(':memory:'); db.enable_load_extension(True); sqlite_vec.load(db); print('sqlite-vec OK', db.execute('select vec_version()').fetchone()[0])"

# Preload rembg's u2net ONNX model (~170 MB) into the image so the
# first cutout request doesn't hang on a GitHub download — Render's
# outbound is slow on cold start and a missed download falls through
# to a silent passthrough (the user gets the original photo back as
# if it were a cutout). Failing the build here is the right loud
# signal; quiet runtime failures are not.
ENV U2NET_HOME=/opt/u2net
RUN retry python -c "from rembg import new_session; new_session('u2net')" \
 && test -f /opt/u2net/u2net.onnx

# Install Playwright + Chromium for graphic_renderer's HTML→PNG step.
#
# Two pins matter:
#   1. PLAYWRIGHT_BROWSERS_PATH=/ms-playwright pins Chromium to a stable
#      absolute path so the runtime discovery works regardless of HOME.
#      Without this, Chromium installs under /root/.cache/ms-playwright
#      at build time and Playwright looks under $HOME/.cache/ms-playwright
#      at runtime — Render's runtime HOME may differ from /root.
#   2. playwright version is pinned in requirements.txt so the Chromium
#      revision Playwright expects matches what `playwright install`
#      downloads. Drifting major versions broke runtime discovery in
#      May 2026; the pin (>=1.56,<1.58) keeps build + runtime aligned.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN retry playwright install --with-deps chromium

# Copy app code.
COPY src/ /app/src/
COPY data/ /app/data/
COPY legacy/ /app/legacy/
COPY samples/ /app/samples/
COPY scripts/ /app/scripts/
COPY pyproject.toml /app/pyproject.toml
COPY deploy/ /app/deploy/

# Install MediaHub itself in editable mode so the console script is wired. The
# [voiceover] extra pulls in piper-tts (GPL-3.0-or-later) — the DEFAULT local
# TTS backend (roadmap 1.7). It is server-side only in this hosted-only image,
# never conveyed to customers, so no GPL source-offer obligation triggers (the
# same basis used for AGPL SearXNG below). onnxruntime already ships (rembg).
RUN pip install -e "/app[voiceover]"

# Bundle the licence-clean default Piper voice (roadmap 1.7) INTO the image so a
# deployment narrates locally out of the box. en_GB-alba-medium is CC BY 4.0
# (commercial use with attribution — recorded in docs/DEPENDENCY_LICENSING.md).
# The voice lives at /opt/piper_voices (image-only, off the small persistent
# disk); MEDIAHUB_PIPER_VOICE_DIR points the runtime auto-discovery at it.
# We then run a REAL end-to-end synth (piper + espeak-ng + ffmpeg, via the app's
# own code path) so a broken local-voice setup fails the build LOUDLY instead of
# degrading silently at runtime — the same loud-build discipline as the rembg /
# sqlite-vec preloads above. Voiceover itself stays opt-in (MEDIAHUB_VOICEOVER=1).
ENV MEDIAHUB_PIPER_VOICE_DIR=/opt/piper_voices
RUN python /app/scripts/fetch_piper_voice.py /opt/piper_voices \
 && DATA_DIR=/tmp/piperverify MEDIAHUB_TTS_PROVIDER=piper python -c "from mediahub.visual import voiceover as v; assert v._piper_available(), 'piper backend not available in image (package/model/ffmpeg missing)'; r = v.synthesize('MediaHub local voice check, one two three.', apply_pronunciation=False); assert r.audio_path.exists() and r.audio_path.stat().st_size > 0 and r.duration_ms > 0, 'piper produced empty audio'; print('piper TTS OK:', r.duration_ms, 'ms ->', r.audio_path)" \
 && rm -rf /tmp/piperverify \
 && test -f /opt/piper_voices/en_GB-alba-medium.onnx

# Install Remotion node modules so /api/.../motion + /reel render MP4s.
RUN cd /app/src/mediahub/remotion && retry npm install --no-audit --no-fund

# --- Optional in-container SearXNG metasearch (Capability 3) -----------------
# Stock, UNMODIFIED SearXNG installed into an ISOLATED virtualenv so its pinned
# dependencies can never clash with MediaHub's. NON-FATAL: if the install fails
# the image still builds and MediaHub just uses DuckDuckGo. SearXNG only RUNS
# when MEDIAHUB_RUN_SEARXNG=1 (see scripts/docker-entrypoint.sh); off => 0 RAM.
# SearXNG is AGPL-3.0 — installed stock, queried only over localhost HTTP, never
# modified.
#
# Install shape matters (June 2026 prod incident): SearXNG's setup.py imports
# the `searx` package itself, so a plain `pip install git+…` fails inside pip's
# isolated build env ("No module named 'msgspec'") — and the `|| echo` below
# swallowed that, shipping images with NO SearXNG while render.yaml still
# pointed MEDIAHUB_SEARCH_ENDPOINT at 127.0.0.1:8888 (log spam + silent DDG
# fallback). Fix: install SearXNG's own pinned requirements.txt FIRST, then
# install with --no-build-isolation so setup.py sees them. SEARXNG_REF is
# pinned to the commit this sequence was verified against (install + boot +
# /search?format=json) — bump deliberately, not via `master`.
ARG SEARXNG_REF=4dd0bf48670727f6ae1086ffa72e76f6eb869741
ENV SEARXNG_VENV=/opt/searxng-venv \
    SEARXNG_SETTINGS_PATH=/app/deploy/searxng/settings.yml
RUN python -m venv "$SEARXNG_VENV" \
 && ( "$SEARXNG_VENV/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel \
   && retry "$SEARXNG_VENV/bin/pip" install --no-cache-dir \
        -r "https://raw.githubusercontent.com/searxng/searxng/${SEARXNG_REF}/requirements.txt" \
   && retry "$SEARXNG_VENV/bin/pip" install --no-cache-dir --no-build-isolation \
        "git+https://github.com/searxng/searxng.git@${SEARXNG_REF}" \
   && "$SEARXNG_VENV/bin/python" -c "import searx; print('searxng OK')" ) \
 || echo "WARN: in-container SearXNG install failed; MediaHub will use DuckDuckGo."

# Create runtime dirs (mounted volumes will overlay these).
RUN mkdir -p /app/runs_v4 /app/uploads_v4 /app/.cache \
 && chmod +x /app/scripts/docker-entrypoint.sh

# Run as a non-root user (THREAT_MODEL §7): a compromised worker must not
# own the container. Only the runtime-writable paths are chowned; the code
# tree stays root-owned/read-only to the app user. A mounted persistent
# disk (DATA_DIR) must be writable by uid 10001 — Render mounts disks
# writable by the container user; for plain `docker run -v`, chown the
# host dir once (`chown -R 10001 ./data`).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin mediahub \
 && chown -R mediahub:mediahub /app/runs_v4 /app/uploads_v4 /app/.cache /app/data \
 && mkdir -p /home/mediahub/.cache && chown -R mediahub:mediahub /home/mediahub
USER mediahub

EXPOSE 5000

# Health check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/healthz || exit 1

# Entrypoint does the persistent-disk setup (mkdir + first-boot seed
# from /app/data) then exec's gunicorn. Keeps the startup behaviour
# in one place that's shared between local docker run and Render.
CMD ["/app/scripts/docker-entrypoint.sh"]
