#!/usr/bin/env python3
"""The constant BUILDER loop — the roadmap-executing twin of autotest.loop.

Runs build cycles back-to-back: each cycle picks the next uncompleted roadmap
item, builds it (autotest.builder), and writes a handover the testing loop
(autotest.loop / autotest.run) picks up to validate and mark done — or revert.

Like the testing loop it is crash-isolated (each cycle is a subprocess with a
timeout), honours the `autotest/STOP` kill switch, and persists across restarts.
It deliberately runs SLOWER than the tester (a build is expensive and high-
impact): default cooldown 120s, and it stops itself if the circuit breaker in
builder.py trips.

Run:  python -m autotest.build_loop      (build + open PRs; arm prod with flags)
Stop: Ctrl-C, or `touch autotest/STOP`.

Pairing: run this alongside `python -m autotest.loop` (with AUTOTEST_ACCEPT_APPLY=1
so the tester can mark the roadmap done / revert). Together they form the
"autonomously build my SaaS" pipeline: build → test → mark-done-or-revert.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STOP_FILE = REPO_ROOT / "autotest" / "STOP"

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True
    print("\n[build-loop] stop requested — finishing current cycle then exiting…", flush=True)


def main() -> int:
    from autotest._env import load_dotenv
    load_dotenv()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    cooldown = float(os.environ.get("AUTOTEST_BUILD_COOLDOWN", "120"))
    cycle_timeout = float(os.environ.get("AUTOTEST_BUILD_CYCLE_TIMEOUT", "3600"))
    print(f"[build-loop] starting roadmap builder (cooldown={cooldown:.0f}s, "
          f"apply={os.environ.get('AUTOTEST_BUILD_APPLY', '1')}, "
          f"merge={os.environ.get('AUTOTEST_BUILD_MERGE', '0')}). Ctrl-C or touch autotest/STOP.",
          flush=True)

    while not _stop:
        if STOP_FILE.exists():
            print("[build-loop] STOP file present — halting.", flush=True)
            break
        started = time.time()
        try:
            proc = subprocess.run([sys.executable, "-m", "autotest.builder"],
                                  cwd=str(REPO_ROOT), timeout=cycle_timeout,
                                  capture_output=True, text=True)
            out = (proc.stdout or "").strip()
            print(f"[build-loop] cycle: {out[-600:] or '(no output)'}", flush=True)
            try:
                result = json.loads(out)
                if result.get("halted"):
                    print(f"[build-loop] HALTED: {result['halted']}", flush=True)
                    break
            except (ValueError, IndexError):
                pass
        except subprocess.TimeoutExpired:
            print(f"[build-loop] cycle timed out after {cycle_timeout:.0f}s", flush=True)
        except Exception as exc:
            print(f"[build-loop] cycle error (continuing): {exc}", flush=True)

        if _stop:
            break
        waited = 0.0
        while waited < cooldown and not _stop and not STOP_FILE.exists():
            time.sleep(min(2.0, cooldown - waited))
            waited += 2.0

    print("[build-loop] stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
