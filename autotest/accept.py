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


# Council MERGE rule: a CONTENT regression (baseline:regression) only justifies
# reverting a merge that plausibly CAUSED it -- one that touched content-affecting
# product code. A docs/test/config-only merge must never be reverted for a content
# drop (likely a data/LLM drift, not the merge).
_CONTENT_PREFIXES = ("src/mediahub/", "legacy/")
# Per-sweep cap on auto-reverts -- never thrash main (the council's #1 blind spot).
REVERT_CAP = int(os.environ.get("AUTOTEST_ACCEPT_REVERT_CAP", "1"))


def _touches_content(sha: str) -> bool:
    """True if commit `sha` changed content-affecting product code (so a content
    regression after it is plausibly its fault). Unknown/empty -> True, failing
    safe toward the existing crash-revert behaviour."""
    if not sha:
        return True
    rc, out = _git("show", "--name-only", "--format=", sha)
    files = [f.strip() for f in out.splitlines() if f.strip()]
    if not files:
        return True
    return any(f.startswith(_CONTENT_PREFIXES) and not f.startswith("tests/") for f in files)


def _judge(record: dict[str, Any], findings: list[Finding], artifacts: dict[str, Any]) -> dict:
    """Decide if the built item satisfies the roadmap intent and didn't regress.
    Returns {passed: True|False|None, reason, via}. ``None`` = INCONCLUSIVE — we
    leave the item as-is: don't false-accept it as done, don't wrongly revert."""
    # Regression = unambiguous SERVER breakage this sweep (a build that broke the
    # app). NOT the pile of pre-existing UX/content bugs — gating on those would
    # block every single build forever.
    crashes = [f for f in findings if f.is_bug and f.category in
               ("server_traceback", "http_5xx", "navigation_error")]
    # Council MERGE: also gate on a SILENT content regression (the FIND baseline
    # diff) -- a golden-input card/achievement collapse the subagents don't flag.
    content = [f for f in findings if f.is_bug and f.category.startswith("baseline:regression")]
    if crashes or content:
        regs = crashes + content
        return {"passed": False, "via": "regression-gate",
                "reason": f"{len(regs)} regression(s) this sweep: "
                          + "; ".join(f.title for f in regs[:3]),
                # crashes always revert; a content-ONLY regression additionally
                # requires the merge to have touched content code (checked at revert).
                "content_only": not crashes}
    try:
        from autotest import cli_llm
        if not cli_llm.available():
            # No judge → INCONCLUSIVE. Never auto-mark an item "done" without
            # verifying its acceptance criteria; leave it wip to be re-verified
            # when a judge is available (in CI it always is).
            return {"passed": None, "via": "no-judge",
                    "reason": "no Claude CLI — left wip for re-verification (not auto-marked done)"}
        system = ("You are an acceptance tester. Decide if an autonomously-built roadmap item "
                  "is genuinely done and nothing regressed. Be strict but fair. Reply ONLY "
                  'JSON: {"passed":true|false,"reason":"..."}.')
        user = (f"Roadmap item {record.get('item_id')}: {record.get('title')}\n\n"
                f"Intent:\n{record.get('intent', '')[:1500]}\n\n"
                f"Acceptance criteria: {record.get('acceptance_criteria', '')}\n\n"
                f"This sweep — flow={artifacts.get('flow_result')}, "
                f"cards={len((artifacts.get('export_json') or {}).get('cards') or [])}.\n"
                f"Known site bugs (these MAY be pre-existing and unrelated — do NOT fail the "
                f"item merely because they exist): {[f.title for f in findings if f.is_bug][:5]}\n\n"
                "PASS if THIS item's behaviour landed and the build introduced no NEW breakage. "
                "Pre-existing, unrelated bugs are NOT grounds to fail. Reply JSON only.")
        raw = cli_llm.ask(system=system, user=user, max_tokens=300)
        obj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return {"passed": bool(obj.get("passed")), "via": "ai-judge",
                "reason": str(obj.get("reason", ""))[:300]}
    except Exception as exc:
        # A flaky judge must NOT revert good work → inconclusive, retry next sweep.
        return {"passed": None, "via": "judge-error",
                "reason": f"judge errored, left wip: {str(exc)[:160]}"}


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


def _auto_revert(record: dict[str, Any], *, content_only: bool = False) -> str:
    """Revert the item's merge on main when a regression is detected. Only when
    prod auto-merge is armed (else nothing landed) and APPLY is set. A content-ONLY
    regression is reverted only if the merge plausibly caused it (touched content
    code); otherwise it's left in place + the operator notified. The revert/push
    rc is checked and reported HONESTLY -- never a false 'reverted'. Every outcome
    notifies -- never silent."""
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
    from autotest import notify
    if content_only and not _touches_content(sha):
        notify.notify(
            f"Content regression NOT auto-reverted -- {item_id} didn't touch content code",
            f"A content regression followed build {item_id} ({sha[:10]}), but that merge changed "
            "no content-affecting product code -- likely a data/LLM drift, not this merge. Left in "
            "place for a human (an auto-revert would remove good work without fixing the metric).")
        return f"revert skipped: {sha[:10]} touched no content paths (regression likely not its fault)"
    # The revert ITSELF can fail (conflict, push race). Check both rcs and report
    # honestly -- a "reverted" message that didn't push is the #177 false-success bug.
    rc, rout = _git("revert", "--no-edit", "-m", "1", sha)
    if rc != 0:
        rc, rout = _git("revert", "--no-edit", sha)
    if rc != 0:
        notify.notify(
            f"Autopilot FAILED to revert build {item_id} -- needs a human NOW",
            f"A regression followed {sha[:10]} but the revert did not apply (conflict?). "
            f"{BASE_BRANCH} is UNCHANGED and still carries the regression. {rout[:300]}")
        return f"revert FAILED for {sha[:10]} (did not apply; {BASE_BRANCH} still regressed)"
    prc, pout = _git("push", "origin", BASE_BRANCH)
    if prc != 0:
        notify.notify(
            f"Autopilot reverted build {item_id} locally but PUSH FAILED -- needs a human",
            f"The revert of {sha[:10]} committed locally but did NOT push to {BASE_BRANCH}, "
            f"which still carries the regression. {pout[:300]}")
        return f"revert committed but PUSH FAILED for {sha[:10]} ({BASE_BRANCH} still regressed)"
    notify.notify(
        f"Autopilot AUTO-REVERTED build {item_id} after a post-merge regression",
        f"Reverted {sha[:10]} on {BASE_BRANCH}. Reason: {record.get('title', item_id)}. "
        "Review before re-attempting -- the item is now marked blocked.")
    return f"reverted {sha[:10]} on {BASE_BRANCH}"


def process(findings: list[Finding], artifacts: dict[str, Any]) -> list[Finding]:
    """Resolve every pending handover; return any acceptance findings to log."""
    if os.environ.get("AUTOTEST_ACCEPT", "1") == "0":
        return []
    out: list[Finding] = []
    reverts_done = 0   # council MERGE: per-sweep auto-revert cap so we never thrash main
    for path, record in handover.pending():
        verdict = _judge(record, findings, artifacts)
        item_id = record.get("item_id", "?")
        if verdict["passed"] is None:
            # Inconclusive — leave the build in place AND the handover pending so
            # it's re-verified next sweep. Never false-`done`, never false-revert.
            out.append(Finding(category="roadmap_unverified", severity="info", is_bug=False,
                               title=f"Roadmap {item_id} built — acceptance inconclusive, will re-verify",
                               route="(roadmap)", expected=record.get("acceptance_criteria", ""),
                               actual=verdict["reason"], evidence=f"via {verdict['via']}"))
            continue
        if verdict["passed"]:
            action = _emit_directive(item_id, "done", "verified by the testing loop")
            handover.resolve(path, "done", {**verdict, "action": action})
            out.append(Finding(category="roadmap_accepted", severity="info", is_bug=False,
                               title=f"Roadmap {item_id} accepted & marked done",
                               route="(roadmap)", expected=record.get("acceptance_criteria", ""),
                               actual=f"{verdict['reason']} | {action}",
                               evidence=f"via {verdict['via']}"))
        else:
            if reverts_done >= REVERT_CAP:
                from autotest import notify
                notify.notify(
                    "Autopilot revert cap reached -- NOT reverting further this sweep",
                    f"{item_id} failed acceptance ({verdict['reason']}), but {reverts_done} "
                    f"revert(s) already happened this sweep (cap {REVERT_CAP}). Stopping to avoid "
                    "thrashing main -- left in place, needs a human.")
                revert = "skipped (per-sweep revert cap reached)"
            else:
                revert = _auto_revert(record, content_only=verdict.get("content_only", False))
                if revert.startswith("reverted"):
                    reverts_done += 1
            _emit_directive(item_id, "blocked", "reverted by the testing loop")
            handover.resolve(path, "blocked", {**verdict, "revert": revert})
            out.append(Finding(category="roadmap_regression", severity="high",
                               title=f"Roadmap {item_id} FAILED acceptance — reverted",
                               route="(roadmap)", expected=record.get("acceptance_criteria", ""),
                               actual=verdict["reason"],
                               evidence=f"via {verdict['via']} | {revert}",
                               repro=[f"Build of {item_id} on branch {record.get('branch')}"]))
    return out
