#!/usr/bin/env python3
"""The builder — one autonomous build cycle against the roadmap.

Pick the next uncompleted roadmap item → implement it with headless Claude Code
(`claude -p`) → guard the diff → gate on the test suite → commit + open a PR →
write a handover for the testing loop. Production merge is full-auto-to-`main`
(operator's explicit choice, overriding the council's warning) but armed by a
single env flag so it doesn't merge to prod before it's been watched once.

Safety nets the operator accepted (the only things between a bad AI change and
prod, so they are strict):
  * kill switch     — an `autotest/STOP` file halts immediately
  * circuit breaker — N consecutive failed cycles halts and asks for a human
  * protected paths — the deterministic engine (parsers/detectors/ranker/
                      colour-science) must NOT be touched (CLAUDE.md); if the
                      AI edits them, the cycle aborts before any merge
  * scope cap       — refuse oversized diffs (runaway guard)
  * test gate       — the suite must stay green or nothing merges
  * auto-revert     — handled by the testing loop post-merge (autotest/accept.py)

Flags:  AUTOTEST_BUILD_APPLY (default 1: run claude + commit + push + PR;
        set 0 for a dry-run plan) · AUTOTEST_BUILD_MERGE (default 0: set 1 to
        auto-merge the PR to main on green CI) · AUTOTEST_BUILD_ITEM (force id).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from autotest import handover, roadmap
from autotest._env import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
STOP_FILE = REPO_ROOT / "autotest" / "STOP"
# Tracked (not under cache/) so the circuit breaker survives stateless cloud
# runs — the workflow commits it back. Otherwise a failing item retries forever.
STATE_PATH = REPO_ROOT / "autotest" / "reports" / "builder_state.json"
BASE_BRANCH = os.environ.get("AUTOTEST_BASE_BRANCH", "main")

# Deterministic engine — must never be AI-edited without explicit approval
# (CLAUDE.md). A diff touching any of these aborts the cycle.
PROTECTED = (
    "src/mediahub/interpreter/", "src/mediahub/pb_discovery/",
    "src/mediahub/recognition/", "src/mediahub/recognition_swim/",
    "legacy/swim_content_v5/ranker_v3.py", "src/mediahub/theming/logo_chip.py",
    "src/mediahub/media_library/selector.py",
)
MAX_FILES = int(os.environ.get("AUTOTEST_BUILD_MAX_FILES", "25"))
MAX_INSERTIONS = int(os.environ.get("AUTOTEST_BUILD_MAX_INSERTIONS", "2000"))
BREAKER_LIMIT = int(os.environ.get("AUTOTEST_BUILD_BREAKER", "3"))


def _git(*args: str, check: bool = False) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"consecutive_failures": 0}


def _save_state(s: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")


def _record(ok: bool) -> None:
    s = _state()
    s["consecutive_failures"] = 0 if ok else int(s.get("consecutive_failures", 0)) + 1
    _save_state(s)


def _touches_protected(files: list[str]) -> list[str]:
    return [f for f in files if any(f.startswith(p) or p in f for p in PROTECTED)]


def _build_prompt(item: roadmap.RoadmapItem) -> str:
    return (
        f"You are an autonomous engineer on MediaHub. Implement EXACTLY this one "
        f"roadmap item and nothing else.\n\n"
        f"ROADMAP ITEM {item.id}: {item.title}\n---\n{item.body[:4000]}\n---\n\n"
        "Hard constraints (from CLAUDE.md — non-negotiable):\n"
        "- Keep the FULL test suite green: `python -m pytest tests/ -q`. Add tests for new behaviour.\n"
        "- Do NOT modify the deterministic engine: parsers (interpreter/, pb_discovery/), "
        "detectors (recognition/, recognition_swim/), the ranker, or colour-science. They are protected.\n"
        "- AI surfaces go through media_ai.llm / ai_core.llm. NEVER hard-code an API key (env/.env only).\n"
        "- Storage via DATA_DIR; internal links via url_for(); HTML-escape generated output.\n"
        "- Keep scope SMALL — only this item. Do not refactor unrelated code.\n"
        "- Match existing conventions in web/web.py and the package layout.\n\n"
        "Make the change and ensure tests pass. Do NOT run git — the harness commits, "
        "pushes and opens the PR."
    )


def _run_claude(prompt: str) -> tuple[bool, str]:
    import shutil
    if not shutil.which("claude"):
        return False, "claude CLI not found on this runner"
    flags = os.environ.get("AUTOTEST_CLAUDE_FLAGS", "--permission-mode acceptEdits").split()
    try:
        p = subprocess.run(["claude", "-p", prompt, *flags], cwd=str(REPO_ROOT),
                           capture_output=True, text=True,
                           timeout=float(os.environ.get("AUTOTEST_BUILD_CLAUDE_TIMEOUT", "1800")))
        return p.returncode == 0, (p.stdout or "")[-2000:] + (p.stderr or "")[-1000:]
    except subprocess.TimeoutExpired:
        return False, "claude -p timed out"


def _test_gate() -> tuple[bool, str]:
    p = subprocess.run(["python", "-m", "pytest", "tests/", "-q"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True,
                       timeout=float(os.environ.get("AUTOTEST_BUILD_TEST_TIMEOUT", "1800")))
    tail = (p.stdout or "")[-800:]
    return p.returncode == 0, tail


def _changed_files() -> tuple[list[str], int]:
    _git("add", "-A")
    rc, out = _git("diff", "--cached", "--numstat")
    files, insertions = [], 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            files.append(parts[2])
            if parts[0].isdigit():
                insertions += int(parts[0])
    return files, insertions


def _merge_to_main(item: roadmap.RoadmapItem, branch: str) -> str:
    """Full-auto-to-main, armed by AUTOTEST_BUILD_MERGE=1. Prefers `gh pr merge
    --auto` (waits for green CI) so a red build never lands."""
    import shutil
    if os.environ.get("AUTOTEST_BUILD_MERGE") != "1":
        return "merge not armed (set AUTOTEST_BUILD_MERGE=1 to auto-merge to main on green CI)"
    if not shutil.which("gh"):
        return "gh CLI not found — cannot enable CI-gated auto-merge"
    subprocess.run(["gh", "pr", "merge", branch, "--auto", "--squash"],
                   cwd=str(REPO_ROOT), capture_output=True, text=True)
    return "auto-merge to main enabled (will land when CI is green)"


def build_cycle() -> dict:
    load_dotenv()
    apply = os.environ.get("AUTOTEST_BUILD_APPLY", "1") != "0"

    if STOP_FILE.exists():
        return {"halted": "kill switch (autotest/STOP present)"}
    if _state().get("consecutive_failures", 0) >= BREAKER_LIMIT:
        return {"halted": f"circuit breaker: {BREAKER_LIMIT} consecutive failures — human needed"}

    item = roadmap.next_item()
    if item is None:
        return {"result": "nothing-to-build (roadmap has no actionable items)"}
    branch = f"autotest/build-{item.id.replace(' ', '-').lower()}"
    prompt = _build_prompt(item)
    plan = {"item": item.id, "title": item.title, "branch": branch, "apply": apply}

    if not apply:
        plan["result"] = "dry-run (set AUTOTEST_BUILD_APPLY=1 to build)"
        plan["prompt_preview"] = prompt[:400]
        return plan

    # fresh branch off the latest base
    _git("fetch", "origin", BASE_BRANCH)
    rc, _ = _git("checkout", "-B", branch, f"origin/{BASE_BRANCH}")
    if rc != 0:
        _git("checkout", "-B", branch)

    ok, claude_out = _run_claude(prompt)
    if not ok:
        _record(False)
        return {**plan, "result": "claude-failed", "detail": claude_out[-400:]}

    files, insertions = _changed_files()
    if not files:
        _record(False)
        return {**plan, "result": "no-op (claude made no changes)"}
    protected = _touches_protected(files)
    if protected:
        _git("reset", "--hard", f"origin/{BASE_BRANCH}")
        _record(False)
        return {**plan, "result": "aborted: touched protected engine paths", "protected": protected}
    if len(files) > MAX_FILES or insertions > MAX_INSERTIONS:
        _git("reset", "--hard", f"origin/{BASE_BRANCH}")
        _record(False)
        return {**plan, "result": f"aborted: diff too large ({len(files)} files, +{insertions})"}

    gate_ok, gate_tail = _test_gate()
    if not gate_ok:
        _git("reset", "--hard", f"origin/{BASE_BRANCH}")
        _record(False)
        return {**plan, "result": "aborted: test suite not green", "pytest_tail": gate_tail}

    # commit (carry the existing roadmap directive: WIP until the tester confirms)
    msg = (f"build({item.id}): {item.title[:60]}\n\n"
           f"Autonomously implemented roadmap item {item.id}.\n"
           f"{roadmap.directive(item.id, 'wip')}\n")
    _git("commit", "-m", msg)
    _git("push", "-u", "origin", branch)

    pr_url = ""
    import shutil
    if shutil.which("gh"):
        pr = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", BASE_BRANCH,
                             "--title", f"build({item.id}): {item.title[:60]}",
                             "--body", f"Autonomous build of roadmap {item.id}. "
                             f"{roadmap.directive(item.id, 'wip')}"],
                            cwd=str(REPO_ROOT), capture_output=True, text=True)
        pr_url = (pr.stdout or "").strip()

    merge_status = _merge_to_main(item, branch)
    handover.write({
        "item_id": item.id, "title": item.title,
        "intent": item.body[:2000], "summary": claude_out[-600:],
        "files_changed": files, "insertions": insertions,
        "branch": branch, "pr": pr_url, "base": BASE_BRANCH,
        "merge_target": "main", "merge_status": merge_status,
        "acceptance_criteria": f"The behaviour described in roadmap {item.id} works "
                               f"end-to-end and no existing flow regressed.",
    })
    _record(True)
    return {**plan, "result": "built", "files": len(files), "insertions": insertions,
            "pr": pr_url, "merge": merge_status}


def main() -> int:
    print(json.dumps(build_cycle(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
