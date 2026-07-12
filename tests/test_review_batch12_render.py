"""Regression tests for deep-review batch 12 (rendering stack).

#72 visual.proc.run_capture kills the child's whole process GROUP on timeout,
    so a render's grandchild processes (Remotion → Chromium) die too instead of
    leaking; it re-raises TimeoutExpired and returns a CompletedProcess on the
    happy path.

(#70 audio EXDEV fix and #75 props cleanup are exercised by the audio_mux /
 render suites and are behaviourally self-contained.)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from mediahub.visual.proc import run_capture


def test_run_capture_returns_completed_process():
    cp = run_capture([sys.executable, "-c", "print('hello-proc')"], timeout=30)
    assert cp.returncode == 0
    assert "hello-proc" in cp.stdout


def test_run_capture_reports_nonzero_exit():
    cp = run_capture([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
    assert cp.returncode == 3


@pytest.mark.skipif(os.name != "posix", reason="process-group kill is POSIX-only")
def test_run_capture_timeout_kills_the_whole_group(tmp_path):
    # The child spawns a long-lived grandchild. On timeout the WHOLE group must be
    # killed, so the grandchild dies too (a plain subprocess.run would leak it).
    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marker)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_capture([sys.executable, "-c", script], timeout=3)

    assert marker.exists(), "grandchild should have started"
    gc_pid = int(marker.read_text())
    # Poll: the group-kill should reap the grandchild shortly.
    dead = False
    for _ in range(50):
        try:
            os.kill(gc_pid, 0)  # signal 0 = existence probe
        except ProcessLookupError:
            dead = True
            break
        time.sleep(0.1)
    assert dead, "grandchild process was leaked (process group not killed)"
