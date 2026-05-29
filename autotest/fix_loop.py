#!/usr/bin/env python3
"""The autonomous BUG-FIXER loop — bugs → Claude Code → PR → merge.

The original ask: the testing loop finds bugs and writes BUGS.md; this loop is
what "puts the bugs into Claude Code" automatically. It reads the dedup ledger,
takes the top open bugs that don't already have a fix in flight, and for each
runs headless Claude Code (`claude -p`) with the bug's fix-ready detail on its
own branch — then reuses the builder's gates (protected-path guard, scope cap,
green test suite) and merge policy (full-auto-to-`main`, armed by
AUTOTEST_BUILD_MERGE=1) to land the fix. The ledger entry is moved to
``fixing`` with its PR so the finder won't re-file it and this loop won't
re-fix it.

This shares all of its git/test/merge machinery with autotest.builder, so the
safety nets are identical. Run:  python -m autotest.fix_loop
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from autotest import builder, report
from autotest._env import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _max_attempts() -> int:
    return int(os.environ.get("AUTOTEST_FIX_MAX_ATTEMPTS", "2"))


def _open_bugs(limit: int) -> list[dict]:
    """Open bugs still worth attempting: not already in-flight, not given up on,
    and under the per-bug attempt cap (so we never keep spending credits on a
    bug that won't fix)."""
    cap = _max_attempts()
    ledger = report.load_ledger()
    bugs = [b for b in ledger["bugs"].values()
            if b.get("status") == "open" and not b.get("fix_pr")
            and int(b.get("fix_attempts", 0)) < cap]
    bugs.sort(key=lambda b: SEV_ORDER.get(b.get("severity", "low"), 4))
    return bugs[:limit]


def _update(fingerprint: str, **fields) -> None:
    ledger = report.load_ledger()
    entry = ledger["bugs"].get(fingerprint)
    if entry:
        entry.update(fields)
        report.save_ledger(ledger)


def _give_up_or_retry(bug: dict, attempts: int, reason: str) -> dict:
    """A fix attempt failed. If we've hit the cap, mark the bug needs-human and
    notify the operator; otherwise leave it open to retry next run."""
    fp = bug["fingerprint"]
    if attempts >= _max_attempts():
        _update(fp, status="needs-human")
        from autotest import notify
        notify.notify(
            f"Autopilot can't auto-fix: {bug.get('title', '')[:70]}",
            f"Gave up after {attempts} attempt(s); last reason: {reason}.\n\n"
            f"Bug `{fp}` ({bug.get('category')}) at `{bug.get('route')}`.\n"
            f"Expected: {bug.get('expected')}\nActual: {bug.get('actual')}\n\n"
            f"Stopped retrying to avoid wasting Claude credits — this one needs a human.")
        return {"fp": fp, "result": f"gave-up after {attempts} ({reason})"}
    return {"fp": fp, "result": f"failed: {reason} (attempt {attempts})"}


def _fix_prompt(bug: dict) -> str:
    repro = "\n".join(f"  {i}. {s}" for i, s in enumerate(bug.get("repro", []), 1)) or "  (see evidence)"
    return (
        "You are an autonomous engineer fixing ONE bug in MediaHub. Fix exactly this and "
        "nothing else.\n\n"
        f"BUG ({bug.get('severity')}): {bug.get('title')}\n"
        f"Where: {bug.get('route')}\n"
        f"Suspected source: {bug.get('suspect') or '(unknown)'}\n"
        f"Expected: {bug.get('expected')}\nActual: {bug.get('actual')}\n"
        f"Repro:\n{repro}\n\nEvidence:\n{bug.get('evidence', '')[:2500]}\n\n"
        "Constraints (CLAUDE.md): keep the full test suite green and add a regression test; "
        "do NOT touch the deterministic engine (parsers/detectors/ranker/colour-science); "
        "AI surfaces via media_ai.llm/ai_core.llm; never hard-code keys; minimal diff. "
        "Do NOT run git — the harness commits, pushes and opens the PR."
    )


def _mark_fixing(fingerprint: str, branch: str, pr: str) -> None:
    ledger = report.load_ledger()
    entry = ledger["bugs"].get(fingerprint)
    if entry:
        entry["status"] = "fixing"
        entry["fix_branch"] = branch
        entry["fix_pr"] = pr or branch
        report.save_ledger(ledger)


def fix_one(bug: dict) -> dict:
    fp = bug["fingerprint"]
    branch = f"autotest/fix-{fp}"
    if builder.STOP_FILE.exists():
        return {"halted": "kill switch"}
    attempts = int(bug.get("fix_attempts", 0)) + 1
    _update(fp, fix_attempts=attempts)   # record before trying, so a crash still counts
    builder._git("fetch", "origin", builder.BASE_BRANCH)
    rc, _ = builder._git("checkout", "-B", branch, f"origin/{builder.BASE_BRANCH}")
    if rc != 0:
        builder._git("checkout", "-B", branch)

    # Implement + iterate to green: a gate failure is fed back to the coder to
    # fix the root cause (repo skills), not abandoned on the first miss.
    ok, files, ins, info = builder.implement_until_green(
        _fix_prompt(bug), complex=False, label=f"bug {fp}")
    if not ok:
        builder._git("reset", "--hard", f"origin/{builder.BASE_BRANCH}")
        if info.startswith("coder-failed"):
            from autotest import notify
            notify.notify(
                "Autopilot coder error (Claude)",
                f"The Claude coder errored fixing bug `{fp}` — no fallback. {info}\n\n"
                "Check ANTHROPIC_API_KEY, credits, and rate limits.")
            return {"fp": fp, "result": "coder-failed", "detail": info}
        return _give_up_or_retry(bug, attempts, info)

    builder._git("commit", "-m", f"fix: {bug.get('title', '')[:60]}\n\nAutonomous fix for autotest "
                 f"finding {fp} ({bug.get('category')}).")
    builder._git("push", "-u", "origin", branch)
    pr_url = ""
    import shutil
    if shutil.which("gh"):
        pr = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", builder.BASE_BRANCH,
                             "--title", f"fix: {bug.get('title', '')[:60]}",
                             "--body", f"Autonomous fix for autotest finding `{fp}`."],
                            cwd=str(REPO_ROOT), capture_output=True, text=True)
        pr_url = (pr.stdout or "").strip()
    merge = builder._merge_to_main(None, branch)  # honours AUTOTEST_BUILD_MERGE
    _mark_fixing(fp, branch, pr_url)
    return {"fp": fp, "result": "fix-opened", "files": len(files), "pr": pr_url, "merge": merge}


def main() -> int:
    load_dotenv()
    if os.environ.get("AUTOTEST_FIX_APPLY", "1") == "0":
        bugs = _open_bugs(int(os.environ.get("AUTOTEST_FIX_MAX", "3")))
        print(json.dumps({"dry_run": True, "would_fix": [b["title"] for b in bugs]}, indent=2))
        return 0
    results = []
    for bug in _open_bugs(int(os.environ.get("AUTOTEST_FIX_MAX", "3"))):
        results.append(fix_one(bug))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
