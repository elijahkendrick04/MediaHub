"""Subprocess launch that kills the whole process GROUP on timeout.

A plain ``subprocess.run(timeout=…)`` SIGKILLs only the direct child on timeout.
For the Remotion render (``node`` → Remotion → Chromium children) that leaves the
Chromium processes reparented to init, holding RAM until the worker OOMs. Launch
the child in its own session (a new process group) and, on timeout, kill the
whole group so the children die too.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Optional, Sequence, Union


def _kill_group(proc: "subprocess.Popen") -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover - non-POSIX dev fallback
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


def run_capture(
    cmd: Sequence[str],
    *,
    cwd: Optional[Union[str, Path]] = None,
    timeout: float,
    env: Optional[dict] = None,
) -> "subprocess.CompletedProcess":
    """Drop-in for ``subprocess.run(cmd, capture_output=True, text=True,
    timeout=…)`` that, on timeout, kills the child's whole process group (so
    Remotion/Chromium children die too), then re-raises ``TimeoutExpired``.

    ``start_new_session=True`` puts the child in its OWN process group, so the
    ``killpg`` targets only the child and its descendants — never this process.
    """
    kwargs: dict = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        list(cmd),
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        **kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:  # reap the killed group so no zombies linger
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise
    return subprocess.CompletedProcess(list(cmd), proc.returncode, stdout, stderr)


__all__ = ["run_capture"]
