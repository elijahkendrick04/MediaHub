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


def _open_bugs(limit: int) -> list[dict]:
    ledger = report.load_ledger()
    bugs = [b for b in ledger["bugs"].values()
            if b.get("status") == "open" and not b.get("fix_pr")]
    bugs.sort(key=lambda b: SEV_ORDER.get(b.get("severity", "low"), 4))
    return bugs[:limit]


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
    builder._git("fetch", "origin", builder.BASE_BRANCH)
    rc, _ = builder._git("checkout", "-B", branch, f"origin/{builder.BASE_BRANCH}")
    if rc != 0:
        builder._git("checkout", "-B", branch)

    ok, out = builder._run_coder(_fix_prompt(bug))
    if not ok:
        return {"fp": fp, "result": "coder-failed", "detail": out[-300:]}
    files, ins = builder._changed_files()
    if not files:
        return {"fp": fp, "result": "no-op"}
    if builder._touches_protected(files):
        builder._git("reset", "--hard", f"origin/{builder.BASE_BRANCH}")
        return {"fp": fp, "result": "aborted: touched protected engine"}
    if len(files) > builder.MAX_FILES or ins > builder.MAX_INSERTIONS:
        builder._git("reset", "--hard", f"origin/{builder.BASE_BRANCH}")
        return {"fp": fp, "result": "aborted: diff too large"}
    gate_ok, tail = builder._test_gate()
    if not gate_ok:
        builder._git("reset", "--hard", f"origin/{builder.BASE_BRANCH}")
        return {"fp": fp, "result": "aborted: tests not green", "tail": tail[-300:]}

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
