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

# Gunicorn — Phase 1.5 hardened for Render free-tier (512 MB RAM).
#
# Why these flags:
#   --workers 1         Single worker on 512 MB. Multi-worker on free
#                       tier OOM-kills almost immediately.
#   --threads 4         gthread workers share memory across threads,
#                       so 4 concurrent requests share one process.
#   --timeout 300       Pipeline runs can take 60s+; cap at 5 min so a
#                       wedged request doesn't hold a thread forever.
#   --graceful-timeout 30  Give in-flight requests a chance to finish
#                       before SIGKILL on shutdown.
#   --max-requests 200 --max-requests-jitter 50
#                       Recycle each worker after ~200-250 requests.
#                       Mitigates any slow memory creep (Playwright /
#                       Pillow / SQLite buffer pool) without a full
#                       container restart, so logs stay quiet.
#   --worker-tmp-dir /dev/shm
#                       Render's disk I/O is slow; keep worker
#                       heartbeat in tmpfs to avoid spurious worker
#                       timeouts when disk is busy.
#   --access-logfile -  Log requests to stdout so Render captures them
#                       (they were silent before, making it impossible
#                       to correlate restarts with actual user traffic).
#   --access-logformat ...
#                       Include request time so a single hung route
#                       shows up in logs (the actual cause of the
#                       6-minute restarts the user reported).
exec gunicorn mediahub.web:app \
  --bind "0.0.0.0:${PORT}" \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --worker-tmp-dir /dev/shm \
  --access-logfile - \
  --access-logformat '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(f)s"'
