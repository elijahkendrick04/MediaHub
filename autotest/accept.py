"""Acceptance — the testing loop's half of the build↔test handshake.

After a normal sweep, the testing loop calls ``process()``. For each pending
handover it:
  1. interprets the handover **against the roadmap intent** and this sweep's
     evidence (regressions, flow result, content) — judged by the LLM Council
     when available, else a single AI judge, else a conservative heuristic;
  2. on PASS + no regression → emits ``roadmap: <id> done`` (an empty commit the
     existing roadmap-autoupdate workflow turns into a ✅ badge) and resolves
     the handover to done/;
  3. on FAIL/regression → AUTO-REVERTS the item's merge on `main` and emits
     ``roadmap: <id> blocked``, resolves to blocked/, and files a bug.

Side-effecting git (push of the directive, the revert) is armed by
AUTOTEST_ACCEPT_APPLY=1 so it never pushes from a dev checkout by accident.
Auto-revert only runs when prod auto-merge is armed (AUTOTEST_BUILD_MERGE=1),
since otherwise nothing landed on main to revert.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from autotest import handover, roadmap
from autotest.report import Finding

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_BRANCH = os.environ.get("AUTOTEST_BASE_BRANCH", "main")


def _git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _regressions(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.is_bug and f.severity in ("critical", "high")]


def _judge(record: dict[str, Any], findings: list[Finding], artifacts: dict[str, Any]) -> dict:
    """Decide if the built item satisfies the roadmap intent and didn't regress.
    Returns {passed: bool, reason: str, via: str}."""
    regs = _regressions(findings)
    # Hard rule: any new critical/high bug this sweep = regression, no AI needed.
    if regs:
        return {"passed": False, "via": "regression-gate",
                "reason": f"{len(regs)} critical/high finding(s) this sweep: "
                          + "; ".join(f.title for f in regs[:3])}
    try:
        from autotest import cli_llm
        if not cli_llm.available():
            # No judge: conservative — accept only if the flow produced content.
            ok = str(artifacts.get("flow_result", "")).startswith("passed") and \
                artifacts.get("flow_result") != "passed-empty"
            return {"passed": ok, "via": "heuristic",
                    "reason": f"flow_result={artifacts.get('flow_result')}, no Claude CLI available"}
        system = ("You are an acceptance tester. Decide if an autonomously-built roadmap item "
                  "is genuinely done and nothing regressed. Be strict but fair. Reply ONLY "
                  'JSON: {"passed":true|false,"reason":"..."}.')
        user = (f"Roadmap item {record.get('item_id')}: {record.get('title')}\n\n"
                f"Intent:\n{record.get('intent', '')[:1500]}\n\n"
                f"Acceptance criteria: {record.get('acceptance_criteria', '')}\n\n"
                f"This sweep — flow={artifacts.get('flow_result')}, "
                f"cards={len((artifacts.get('export_json') or {}).get('cards') or [])}, "
                f"bugs_found={[f.title for f in findings if f.is_bug][:5]}\n\n"
                "Did the item's behaviour land AND nothing break?")
        raw = cli_llm.ask(system=system, user=user, max_tokens=300)
        obj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return {"passed": bool(obj.get("passed")), "via": "ai-judge",
                "reason": str(obj.get("reason", ""))[:300]}
    except Exception as exc:
        return {"passed": False, "via": "judge-error", "reason": str(exc)[:200]}


def _emit_directive(item_id: str, status: str, note: str) -> str:
    """Carry the roadmap directive to main via an empty commit; the existing
    roadmap-autoupdate workflow flips the badge on push. Armed by APPLY."""
    if os.environ.get("AUTOTEST_ACCEPT_APPLY") != "1":
        return f"(not applied) would emit: {roadmap.directive(item_id, status)}"
    _git("fetch", "origin", BASE_BRANCH)
    _git("checkout", BASE_BRANCH)
    _git("pull", "--ff-only", "origin", BASE_BRANCH)
    _git("commit", "--allow-empty", "-m",
         f"test({item_id}): {note}\n\n{roadmap.directive(item_id, status)}\n")
    rc, out = _git("push", "origin", BASE_BRANCH)
    return f"emitted {roadmap.directive(item_id, status)} (push rc={rc})"


def _auto_revert(record: dict[str, Any]) -> str:
    """Revert the item's merge on main when a regression is detected. Only when
    prod auto-merge is armed (else nothing landed) and APPLY is set."""
    if os.environ.get("AUTOTEST_BUILD_MERGE") != "1" or os.environ.get("AUTOTEST_ACCEPT_APPLY") != "1":
        return "auto-revert skipped (prod merge not armed, or accept not applied)"
    item_id = record.get("item_id", "")
    _git("fetch", "origin", BASE_BRANCH)
    _git("checkout", BASE_BRANCH)
    _git("pull", "--ff-only", "origin", BASE_BRANCH)
    # find the build commit for this item on main
    rc, out = _git("log", "--grep", f"build({item_id})", "--format=%H", "-n", "1", BASE_BRANCH)
    sha = out.strip().splitlines()[0] if out.strip() else ""
    if not sha:
        return f"no build commit found for {item_id} — manual revert needed"
    rc, _ = _git("revert", "--no-edit", "-m", "1", sha)
    if rc != 0:
        rc, _ = _git("revert", "--no-edit", sha)
    _git("push", "origin", BASE_BRANCH)
    return f"reverted {sha[:10]} on {BASE_BRANCH}"


def process(findings: list[Finding], artifacts: dict[str, Any]) -> list[Finding]:
    """Resolve every pending handover; return any acceptance findings to log."""
    if os.environ.get("AUTOTEST_ACCEPT", "1") == "0":
        return []
    out: list[Finding] = []
    for path, record in handover.pending():
        verdict = _judge(record, findings, artifacts)
        item_id = record.get("item_id", "?")
        if verdict["passed"]:
            action = _emit_directive(item_id, "done", "verified by the testing loop")
            handover.resolve(path, "done", {**verdict, "action": action})
            out.append(Finding(category="roadmap_accepted", severity="info", is_bug=False,
                               title=f"Roadmap {item_id} accepted & marked done",
                               route="(roadmap)", expected=record.get("acceptance_criteria", ""),
                               actual=f"{verdict['reason']} | {action}",
                               evidence=f"via {verdict['via']}"))
        else:
            revert = _auto_revert(record)
            _emit_directive(item_id, "blocked", "reverted by the testing loop")
            handover.resolve(path, "blocked", {**verdict, "revert": revert})
            out.append(Finding(category="roadmap_regression", severity="high",
                               title=f"Roadmap {item_id} FAILED acceptance — reverted",
                               route="(roadmap)", expected=record.get("acceptance_criteria", ""),
                               actual=verdict["reason"],
                               evidence=f"via {verdict['via']} | {revert}",
                               repro=[f"Build of {item_id} on branch {record.get('branch')}"]))
    return out
