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
# IMPORTANT: keep this exec line in sync with the comments below and
# the Procfile. A merge from main in May 2026 silently dropped
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
exec gunicorn mediahub.web:app \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --threads 4 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --worker-tmp-dir /dev/shm \
  --access-logfile - \
  --access-logformat '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(f)s"'
