"""Gunicorn's `sync` worker class (the default) silently ignores `--threads` —
it serves exactly one connection at a time per worker process. The Docker
entrypoint passes `--workers 2 --threads 4` expecting 2*4 = 8 concurrent
request slots, but without `--worker-class gthread` the deployment only ever
had 2: with two requests in flight (e.g. a slow render), every other route —
including /health — queued behind them until Render's edge gave up and
returned a 502 "document" error to the browser.

This pins `--worker-class gthread` (the flag that makes `--threads` take
effect) in `scripts/docker-entrypoint.sh`, the single production launcher —
the Dockerfile CMD invokes it and Render runs the image directly.
"""
from __future__ import annotations

import shlex
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _ROOT / "scripts" / "docker-entrypoint.sh"


def _gunicorn_args(text: str) -> list[str]:
    line = next(ln for ln in text.splitlines() if "gunicorn mediahub.web:app" in ln)
    # The entrypoint's gunicorn invocation spans multiple backslash-continued
    # shell lines; stitch the continuations back together before shlex-splitting.
    if line.rstrip().endswith("\\"):
        idx = text.index(line)
        block_lines = []
        for ln in text[idx:].splitlines():
            block_lines.append(ln.rstrip("\\").rstrip())
            if not ln.rstrip().endswith("\\"):
                break
        line = " ".join(block_lines)
    return shlex.split(line)


def test_entrypoint_uses_gthread_worker_class():
    args = _gunicorn_args(_ENTRYPOINT.read_text())
    assert "--worker-class" in args, (
        "docker-entrypoint.sh's gunicorn command sets --threads but not "
        "--worker-class gthread; the sync default ignores --threads, capping "
        "the deployment at --workers concurrent requests total."
    )
    assert args[args.index("--worker-class") + 1] == "gthread"
