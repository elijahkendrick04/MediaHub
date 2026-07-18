"""Pin `--worker-class gthread` in scripts/docker-entrypoint.sh — as an
*explicitness* guarantee, and pin the fact that the flag is a runtime no-op.

Gunicorn (>=19; requirements.txt pins >=26) auto-promotes the `sync` default
worker class to gunicorn.workers.gthread.ThreadWorker whenever --threads > 1,
so the pre-PR-#1083 command (`--workers 2 --threads 4`, no --worker-class)
already ran gthread with 2*4 = 8 concurrent request slots. The explicit flag
exists purely so the worker class is stated in the single production launcher
(the Dockerfile CMD invokes the entrypoint; Render runs the image directly)
rather than implied by gunicorn's promotion rule.

Adding the flag therefore did NOT fix the production /health 502 (autotest
finding bfff9fa5d517) — that root cause remains undiagnosed; see the
candidate leads in the entrypoint's comment block. The resolution test below
parses the entrypoint's real flag set through gunicorn's own Config, with and
without the explicit flag, and asserts both resolve to ThreadWorker — so the
"sync ignores --threads, the box only serves 2 concurrent requests"
misdiagnosis cannot recur.
"""
from __future__ import annotations

import shlex
from pathlib import Path

import pytest

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


def _resolve_worker_class(argv: list[str]):
    """Resolve the worker class exactly as gunicorn's own CLI loader does."""
    from gunicorn.config import Config

    cfg = Config()
    ns = cfg.parser().parse_args(argv)
    for key, value in vars(ns).items():
        if value is None or key == "args":
            continue
        cfg.set(key.lower(), value)
    return cfg.worker_class


def test_entrypoint_uses_gthread_worker_class():
    args = _gunicorn_args(_ENTRYPOINT.read_text())
    assert "--worker-class" in args, (
        "docker-entrypoint.sh's gunicorn command no longer states "
        "--worker-class gthread. Removing it leaves runtime behaviour "
        "unchanged (gunicorn auto-promotes sync to gthread when "
        "--threads > 1), but the worker class becomes implicit again — "
        "keep it explicit in the single production launcher."
    )
    assert args[args.index("--worker-class") + 1] == "gthread"


def test_gthread_flag_is_a_runtime_noop_auto_promotion_already_applies():
    """The explicit flag and gunicorn's sync→gthread auto-promotion resolve
    to the identical ThreadWorker class — pinning that PR #1083's flag
    addition changed nothing at runtime (and so could not have fixed the
    /health 502)."""
    pytest.importorskip("gunicorn")
    from gunicorn.workers.gthread import ThreadWorker

    args = _gunicorn_args(_ENTRYPOINT.read_text())
    flags = args[args.index("gunicorn") + 1 :]

    with_flag = _resolve_worker_class(flags)

    # Drop "--worker-class gthread" — the pre-PR-#1083 flag set.
    idx = flags.index("--worker-class")
    without_flag = _resolve_worker_class(flags[:idx] + flags[idx + 2 :])

    assert with_flag is ThreadWorker
    assert without_flag is ThreadWorker
    assert with_flag is without_flag, (
        "gunicorn resolved different worker classes with and without the "
        "explicit --worker-class flag; the entrypoint comment's 'explicitness "
        "only' claim would then be wrong — re-check gunicorn's sync→gthread "
        "auto-promotion (Config.worker_class) before trusting either."
    )
