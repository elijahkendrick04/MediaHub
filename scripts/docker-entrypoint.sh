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

exec gunicorn mediahub.web:app \
  --bind "0.0.0.0:${PORT}" \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  --graceful-timeout 60 \
  --max-requests 800 \
  --max-requests-jitter 200
