"""Gunicorn's `sync` worker class (the default) silently ignores `--threads` —
it serves exactly one connection at a time per worker process. The Docker
entrypoint and Procfile both pass `--workers 2 --threads 4` expecting 2*4 = 8
concurrent request slots, but without `--worker-class gthread` the deployment
only ever had 2: with two requests in flight (e.g. a slow render), every other
route — including /health — queued behind them until Render's edge gave up
and returned a 502 "document" error to the browser.

This pins `--worker-class gthread` (the flag that makes `--threads` take
effect) in both files that launch the production process, and keeps them in
sync with each other as scripts/docker-entrypoint.sh's own comment requires.
"""
from __future__ import annotations

import shlex
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _ROOT / "scripts" / "docker-entrypoint.sh"
_PROCFILE = _ROOT / "Procfile"


def _gunicorn_args(text: str) -> list[str]:
    line = next(ln for ln in text.splitlines() if "gunicorn mediahub.web:app" in ln)
    # The entrypoint's gunicorn invocation spans multiple backslash-continued
    # shell lines; the Procfile's is a single line. Both are valid shlex input
    # once continuations are stitched back together.
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


def test_procfile_uses_gthread_worker_class():
    args = _gunicorn_args(_PROCFILE.read_text())
    assert "--worker-class" in args
    assert args[args.index("--worker-class") + 1] == "gthread"


def test_entrypoint_and_procfile_gunicorn_flags_match():
    """The entrypoint's own comment requires these two stay in sync.

    Compares flag *names* only (``--bind``'s value legitimately differs in
    form: ``0.0.0.0:${PORT}`` vs. ``0.0.0.0:$PORT``).
    """
    entry_flags = {a for a in _gunicorn_args(_ENTRYPOINT.read_text()) if a.startswith("--")}
    proc_flags = {a for a in _gunicorn_args(_PROCFILE.read_text()) if a.startswith("--")}
    assert entry_flags == proc_flags
