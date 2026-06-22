#!/bin/sh
# Retry a command with exponential backoff.
#
# Wraps the network-dependent, fail-loud build steps in the Dockerfile (the
# rembg model preload, `playwright install`, the Remotion `npm install`, and the
# SearXNG install) so a single transient blip — a dropped TLS handshake, a CDN
# 5xx, a flaky package mirror — can't fail the whole image build. The 2026-06-22
# Render deploy died exactly that way: one `SSL: UNEXPECTED_EOF_WHILE_READING`
# while pulling a model, with no retry. This is the shell analog of the Python
# retry added to scripts/fetch_piper_voice.py:_get.
#
# It stays LOUD-FAIL: once the attempts are spent it exits with the command's
# own non-zero status, so a genuinely-broken step still reds the build — a quiet
# degrade is worse than an honest failure.
#
# Usage: retry [-n ATTEMPTS] [-s BASE_SLEEP] CMD [ARG...]
#   -n ATTEMPTS    total tries before giving up (default 4)
#   -s BASE_SLEEP  first backoff in seconds, doubled each retry (default 5)

attempts=4
base=5

while [ "$#" -gt 0 ]; do
  case "$1" in
    -n) attempts="$2"; shift 2 ;;
    -s) base="$2"; shift 2 ;;
    --) shift; break ;;
    -*) echo "retry: unknown option '$1'" >&2; exit 2 ;;
    *) break ;;
  esac
done

if [ "$#" -eq 0 ]; then
  echo "retry: no command given" >&2
  exit 2
fi

n=1
delay="$base"
while : ; do
  "$@" && exit 0
  status=$?
  if [ "$n" -ge "$attempts" ]; then
    echo "retry: '$*' failed after $attempts attempt(s) (last exit $status)" >&2
    exit "$status"
  fi
  echo "retry: attempt $n/$attempts of '$*' failed (exit $status); retrying in ${delay}s" >&2
  sleep "$delay"
  n=$((n + 1))
  delay=$((delay * 2))
done
