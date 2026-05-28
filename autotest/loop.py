#!/usr/bin/env python3
"""The constant loop — run sweeps back-to-back, forever, without going stale.

This is the "constantly testing" driver. Each sweep runs the full finder
(`autotest.run`) as an isolated subprocess (so a hang or crash in one sweep is
contained and timed-out, never killing the loop), rotating the input file and
varying parameters so it doesn't get complacent:

  * input file rotates across the corpus + downloaded files every sweep
  * every Nth sweep injects an edge-case / fuzz upload (validation hardening)
  * every Mth sweep refreshes the input pool from the web (sources + discovery)
  * crawl breadth varies sweep-to-sweep

Sweep state persists under autotest/cache so rotation continues across restarts.
Optionally chains the fix loop after each sweep (AUTOTEST_AUTOFIX=1).

Run:  python -m autotest.loop
Stop: Ctrl-C (finishes the current sweep, then exits cleanly).

This is meant to run on a real machine (your Cowork desktop / a worker) where it
has full browser, web and filesystem access — NOT in a throwaway sandbox.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from autotest import acquire

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path(__file__).resolve().parent / "cache" / "state.json"
FUZZ_DIR = Path(__file__).resolve().parent / "cache" / "fuzz"

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True
    print("\n[loop] stop requested — finishing current sweep then exiting…", flush=True)


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {"sweep": 0}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _sweep_env(sweep: int) -> dict:
    """Vary the environment per sweep so coverage keeps shifting."""
    env = os.environ.copy()
    env["AUTOTEST_SWEEP"] = str(sweep)
    # crawl breadth oscillates 25..60
    env["AUTOTEST_MAX_PAGES"] = str(25 + (sweep * 7) % 36)
    # every 5th sweep: fuzz an edge-case upload instead of a real file
    fuzz_every = int(os.environ.get("AUTOTEST_FUZZ_EVERY", "5"))
    if fuzz_every and sweep % fuzz_every == 0 and sweep > 0:
        kind = acquire.FUZZ_KINDS[(sweep // fuzz_every) % len(acquire.FUZZ_KINDS)]
        env["AUTOTEST_INPUT"] = str(acquire.fuzz_input(kind, FUZZ_DIR))
        print(f"[loop] sweep {sweep}: fuzz input '{kind}'", flush=True)
    else:
        env.pop("AUTOTEST_INPUT", None)
    return env


def _maybe_refresh_pool(sweep: int) -> None:
    refresh_every = int(os.environ.get("AUTOTEST_REFRESH_EVERY", "10"))
    if refresh_every and sweep % refresh_every == 0:
        new = acquire.download_sources()
        new += [Path(u) for u in acquire.discover_online()]
        if new:
            print(f"[loop] refreshed input pool (+{len(new)} files)", flush=True)


def main() -> int:
    from autotest._env import load_dotenv
    load_dotenv()  # so the key propagates into each sweep's subprocess env
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    cooldown = float(os.environ.get("AUTOTEST_LOOP_COOLDOWN", "20"))
    flow_timeout = float(os.environ.get("AUTOTEST_FLOW_TIMEOUT", "210"))
    sweep_timeout = flow_timeout + float(os.environ.get("AUTOTEST_SWEEP_BUFFER", "300"))
    autofix = os.environ.get("AUTOTEST_AUTOFIX") == "1"
    state = _load_state()

    print(f"[loop] starting constant tester (cooldown={cooldown:.0f}s, "
          f"sweep_timeout={sweep_timeout:.0f}s, autofix={autofix}). Ctrl-C to stop.",
          flush=True)

    while not _stop:
        sweep = int(state.get("sweep", 0))
        started = time.time()
        try:
            _maybe_refresh_pool(sweep)
        except Exception as exc:
            print(f"[loop] pool refresh error (ignored): {exc}", flush=True)

        env = _sweep_env(sweep)
        try:
            proc = subprocess.run([sys.executable, "-m", "autotest.run"],
                                  cwd=str(REPO_ROOT), env=env, timeout=sweep_timeout,
                                  capture_output=True, text=True)
            line = (proc.stdout or "").strip().splitlines()
            print(f"[loop] sweep {sweep}: {line[-1] if line else 'no output'}", flush=True)
            if proc.returncode != 0 and proc.stderr:
                print(f"[loop] sweep {sweep} stderr tail: {proc.stderr[-500:]}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"[loop] sweep {sweep} TIMED OUT after {sweep_timeout:.0f}s "
                  "(possible hang — investigate the latest report)", flush=True)
        except Exception as exc:
            print(f"[loop] sweep {sweep} error (ignored, continuing): {exc}", flush=True)

        if autofix and not _stop:
            try:
                subprocess.run([sys.executable, "-m", "autotest.fix_loop"],
                               cwd=str(REPO_ROOT), timeout=1800)
            except Exception as exc:
                print(f"[loop] autofix error (ignored): {exc}", flush=True)

        state["sweep"] = sweep + 1
        state["last_sweep_secs"] = round(time.time() - started, 1)
        _save_state(state)

        if _stop:
            break
        # short cooldown between sweeps; responsive to stop
        waited = 0.0
        while waited < cooldown and not _stop:
            time.sleep(min(1.0, cooldown - waited))
            waited += 1.0

    print("[loop] stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
