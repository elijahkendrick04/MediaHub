#!/bin/sh
# MediaHub container entrypoint.
#
# When DATA_DIR points to a persistent disk that's separate from the
# image's bundled /app/data (the standard Render setup is DATA_DIR=
# /var/mediahub), make sure the runtime sub-dirs exist and seed the
# disk from the image's bundled data on first boot. Then hand off to
# gunicorn.
#
# Kept here (not in render.yaml's dockerCommand) because Render's
# dockerCommand is passed as a single argv to the container's exec
# form, which the shell then can't parse — see the May 2026 deploy
# log where "sh: 1: mkdir -p ... timeout 300: not found".
set -e

: "${PORT:=5000}"

if [ -n "$DATA_DIR" ] && [ "$DATA_DIR" != "/app/data" ]; then
  mkdir -p "$DATA_DIR" \
           "${RUNS_DIR:-$DATA_DIR/runs_v4}" \
           "${UPLOADS_DIR:-$DATA_DIR/uploads_v4}"
  # -n = don't overwrite existing files (idempotent on every boot).
  cp -rn /app/data/. "$DATA_DIR/" 2>/dev/null || true
fi

# Gunicorn — Phase 1.5 hardened, re-tuned for Render Standard (2 GB
# RAM, 1 CPU).
#
# The flag set below was originally chosen for the Starter tier
# (512 MB, 1 CPU). The Standard upgrade raised the OOM ceiling to 2 GB
# but did NOT add a second CPU, so the worker count stays at 2 (one
# more than Starter could survive, but anything higher trades CPU
# contention for nothing on a single core). If you see RSS pressure in
# /healthz/memory or container SIGTERMs return, revert --workers
# 2 → 1 before touching anything else — Playwright + Chromium during a
# pipeline render can still spike to ~800 MB per worker.
#
# IMPORTANT: keep this exec line in sync with the comments below. This is
# the single production launcher (the Dockerfile CMD invokes it; Render runs
# the image directly). A merge from main in May 2026 silently dropped
# --worker-tmp-dir/--access-log* and bumped max-requests 200→800; the
# result was the "Worker was sent SIGTERM! / container restarts ~40
# minutes later" pattern the user reported. The flags ARE the fix —
# don't strip them again.
#
# Why these flags:
#   --workers 2         Two processes on Standard's 2 GB / 1 CPU. On
#                       the old 512 MB Starter this had to be 1 — a
#                       second worker OOM-killed almost immediately.
#                       Don't go higher on a single CPU: extra workers
#                       only contend for the same core.
#   --worker-class gthread  Gunicorn's default worker class is `sync`, which
#                       ignores --threads entirely (one connection at a
#                       time per worker process). Without this flag the
#                       box only ever serves 2 concurrent requests total
#                       (one per --workers process); a couple of in-flight
#                       renders then starve every other route — including
#                       /health — until Render's edge gives up and returns
#                       502. gthread is what makes --threads below actually
#                       take effect.
#   --threads 4         gthread workers share memory across threads,
#                       so 4 concurrent requests share one process.
#   --timeout 300       Pipeline runs can take 60s+; cap at 5 min so a
#                       wedged request doesn't hold a thread forever.
#   --graceful-timeout 30  Give in-flight requests 30s to finish before
#                       SIGKILL. Matches Render's own SIGTERM→SIGKILL
#                       grace window; longer values just delay the
#                       restart without saving requests.
#   --max-requests 200 --max-requests-jitter 50
#                       Recycle each worker after ~200-250 requests.
#                       Mitigates slow memory creep (Playwright /
#                       Pillow / SQLite buffer pool) so per-worker RSS
#                       stays well under the 2 GB Standard ceiling —
#                       especially important now that two workers
#                       share that ceiling.
#   --worker-tmp-dir /dev/shm
#                       Render's disk I/O is slow; keep the worker
#                       heartbeat file in tmpfs to avoid spurious
#                       worker timeouts when the disk is busy
#                       (Playwright temp files, pack writes, etc.).
#   --access-logfile -  Log requests to stdout so Render captures them.
#                       Without this, request traffic is invisible and
#                       you can't correlate restarts with actual load.
#   --access-logformat ...
#                       Include request time so a single hung route
#                       shows up in logs.
# --- Optional in-container SearXNG metasearch (Capability 3) ---
# Start stock SearXNG as a localhost-only background process when enabled.
# Non-fatal: any problem just means MediaHub uses DuckDuckGo. Off unless
# MEDIAHUB_RUN_SEARXNG=1 (zero RAM when off). See docs/SEARXNG.md + render.yaml.
SEARXNG_VENV="${SEARXNG_VENV:-/opt/searxng-venv}"
SEARXNG_UP=0
if [ "${MEDIAHUB_RUN_SEARXNG:-0}" = "1" ]; then
  if [ -x "$SEARXNG_VENV/bin/python" ] && "$SEARXNG_VENV/bin/python" -c "import searx" 2>/dev/null; then
    echo "Starting in-container SearXNG on 127.0.0.1:8888 ..."
    SEARXNG_SETTINGS_PATH="${SEARXNG_SETTINGS_PATH:-/app/deploy/searxng/settings.yml}" \
      "$SEARXNG_VENV/bin/python" -m searx.webapp >/tmp/searxng.log 2>&1 &
    # Bounded readiness wait (verified ~3s in practice) so boot-time searches
    # don't trip the SearXNG circuit breaker while it's still starting.
    i=0
    while [ "$i" -lt 20 ]; do
      if curl -sS -o /dev/null --max-time 1 "http://127.0.0.1:8888/" 2>/dev/null; then
        SEARXNG_UP=1
        echo "SearXNG is up (after ~${i}s)."
        break
      fi
      i=$((i + 1))
      sleep 1
    done
    if [ "$SEARXNG_UP" != "1" ]; then
      echo "WARN: SearXNG did not answer on 127.0.0.1:8888 within 20s; MediaHub will use DuckDuckGo."
      echo "----- tail /tmp/searxng.log -----"
      tail -n 20 /tmp/searxng.log 2>/dev/null || true
      echo "---------------------------------"
    fi
  else
    echo "MEDIAHUB_RUN_SEARXNG=1 but SearXNG is not installed; using DuckDuckGo."
  fi
fi
# Config must match reality: render.yaml points MEDIAHUB_SEARCH_ENDPOINT at the
# in-container SearXNG. If that SearXNG is NOT running (install failed, crashed
# at boot, or MEDIAHUB_RUN_SEARXNG=0), drop the endpoint so the search client is
# honestly inert instead of probing a dead localhost port on every query.
# A bring-your-own EXTERNAL endpoint (any non-127.0.0.1 host) is left alone.
if [ "$SEARXNG_UP" != "1" ]; then
  case "${MEDIAHUB_SEARCH_ENDPOINT:-}" in
    http://127.0.0.1:8888*|http://localhost:8888*)
      echo "Unsetting MEDIAHUB_SEARCH_ENDPOINT — in-container SearXNG is not running."
      unset MEDIAHUB_SEARCH_ENDPOINT
      ;;
  esac
fi

exec gunicorn mediahub.web:app \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --worker-class gthread \
  --threads 4 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --worker-tmp-dir /dev/shm \
  --access-logfile - \
  --access-logformat '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(f)s"'
