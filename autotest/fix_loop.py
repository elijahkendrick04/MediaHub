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

from autotest import builder, report
from autotest._env import load_dotenv

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Ledger changes this run, keyed by fingerprint. The per-bug fix attempt does
# `git reset --hard` (to drop the coder's failed edits), which also wipes any
# in-place ledger write — so we journal every change and re-apply it to a clean
# `main` at the end (_persist_to_main). Without this the attempt-cap and
# human-escalation never persist and the fixer re-picks the same bug forever.
_JOURNAL: dict[str, dict] = {}

# Findings about the tester / AI-judge itself, not the product. The autonomous
# coder can't fix "the AI judge over-flags X" in MediaHub's code, so it must not
# pick these or it flails and burns cycles; they stay in BUGS.md as tester-tuning
# feedback. Matched against the finding's route + title.
_META_MARKERS = (
    "testing framework", "testing infrastructure", "test framework",
    "test harness", "automated testing", "autotest", "ai judge", "ai/testing",
)


def _max_attempts() -> int:
    return int(os.environ.get("AUTOTEST_FIX_MAX_ATTEMPTS", "2"))


def _is_meta_finding(bug: dict) -> bool:
    blob = f"{bug.get('route', '')} {bug.get('title', '')}".lower()
    return any(m in blob for m in _META_MARKERS)


# The headline "content engine produced nothing" cluster — architectural, not a
# one-pass autonomous fix (it spans the pipeline / protected engine). We never
# skip it, but de-prioritise it so the coder lands the tractable fixes first
# instead of burning every run on the one bug it can't one-shot.
_HARD_MARKERS = (
    "0 card", "zero card", "no card", "no content", "empty content", "content pack",
    "produced no", "produced zero", "review page", "review screen", "review pages",
    "blank", "content is empty", "cards=0",
)


def _is_hard_cluster(bug: dict) -> bool:
    blob = f"{bug.get('title', '')} {bug.get('actual', '')}".lower()
    return any(m in blob for m in _HARD_MARKERS)


def _open_bugs(limit: int) -> list[dict]:
    """Open bugs eligible for a fix attempt. NEVER-SKIP policy: every open
    product bug stays eligible forever — we never drop one for having too many
    attempts or for not being reproduced on the latest (input-rotated) sweep.
    The only exclusions are fixes already in flight (``fix_pr``) and meta-findings
    about the tester itself (not product code the coder can fix). Priority is set
    by ORDER, not by exclusion (see below)."""
    ledger = report.load_ledger()
    bugs = [b for b in ledger["bugs"].values()
            if b.get("status") == "open" and not b.get("fix_pr")
            and not _is_meta_finding(b)]
    # NEVER-SKIP ordering (not exclusion). Round-robin by attempts FIRST so every
    # bug gets a fresh shot before any is retried; then tractable bugs before the
    # architectural content-empty cluster (so the coder lands quick wins instead
    # of burning every run on the one bug it can't one-shot); then severity; then
    # reproduced-this-sweep. Nothing is ever dropped — hard bugs just sink.
    bugs.sort(key=lambda b: (
        int(b.get("fix_attempts", 0)),
        1 if _is_hard_cluster(b) else 0,
        SEV_ORDER.get(b.get("severity", "low"), 4),
        0 if b.get("present_last_run", True) else 1,
    ))
    # Collapse near-duplicates: the LLM judge re-files the SAME defect under many
    # fingerprints (different wording), so the 50+ open bugs are really a handful
    # of root causes. Keep one bug per (category, normalised route) so we don't
    # open duplicate PRs or burn attempts on the same defect; the rest resurface
    # next sweep once this one is fixed/in-flight.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for b in bugs:
        key = (b.get("category", ""), report.normalise(b.get("route", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)
    return unique[:limit]


def _update(fingerprint: str, **fields) -> None:
    """Record a ledger change: journal it (so it survives the per-bug `git reset`
    and is re-applied to `main` by _persist_to_main) AND write it through to the
    working-tree ledger best-effort."""
    _JOURNAL.setdefault(fingerprint, {}).update(fields)
    ledger = report.load_ledger()
    entry = ledger["bugs"].get(fingerprint)
    if entry:
        entry.update(fields)
        report.save_ledger(ledger)


def _persist_to_main() -> None:
    """Re-apply this run's fixer memory (attempts, fixing/needs-human, fix_pr)
    onto a clean ``main`` ledger and commit+push it, so the dedup/attempt memory
    survives to the next CI run. The per-bug `git reset --hard` above discards
    the working-tree ledger, so without this nothing the fixer learned persists
    and it loops on the same bug every run."""
    if not _JOURNAL:
        return
    builder._git("checkout", "-f", builder.BASE_BRANCH)
    builder._git("reset", "--hard", f"origin/{builder.BASE_BRANCH}")
    ledger = report.load_ledger()
    changed = False
    for fp, fields in _JOURNAL.items():
        entry = ledger["bugs"].get(fp)
        if entry:
            entry.update(fields)
            changed = True
    if not changed:
        return
    report.save_ledger(ledger)
    builder._git("add", "autotest/reports/ledger.json")
    rc, _ = builder._git("commit", "-m", "autotest: persist fixer memory [skip ci]")
    if rc == 0:
        builder._git("pull", "--rebase", "--autostash", "origin", builder.BASE_BRANCH)
        builder._git("push", "origin", builder.BASE_BRANCH)


def _give_up_or_retry(bug: dict, attempts: int, reason: str) -> dict:
    """A fix attempt failed. NEVER-SKIP: the bug stays ``open`` and is retried on
    a later sweep (de-prioritised by its higher attempt count), never marked
    terminal and dropped. Once it has failed enough we notify the operator ONCE
    for visibility, then keep retrying."""
    fp = bug["fingerprint"]
    if attempts >= _max_attempts() and not bug.get("escalated"):
        _update(fp, escalated=True)   # visibility flag only — status stays "open"
        from autotest import notify
        notify.notify(
            f"Autopilot keeps retrying a hard bug: {bug.get('title', '')[:70]}",
            f"Bug `{fp}` ({bug.get('category')}) at `{bug.get('route')}` has failed "
            f"{attempts} auto-fix attempts; last reason: {reason}.\n\n"
            f"Expected: {bug.get('expected')}\nActual: {bug.get('actual')}\n\n"
            "It will KEEP being retried (de-prioritised, never dropped) — a human eye may help.")
        return {"fp": fp, "result": f"failed-escalated after {attempts} ({reason})"}
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
    _update(fingerprint, status="fixing", fix_branch=branch, fix_pr=pr or branch)


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
        # The "coder error" alarm is ONLY for true infrastructure failures (CLI
        # missing, auth/crash). A coder that RAN but didn't land a clean fix
        # (timed out, hit max-turns, or the gate stayed red) is a normal failed
        # attempt → retry + de-prioritise (never-skip), no alarm.
        infra_err = any(m in info for m in
                        ("CLI not found", "coder error:", "no coding agent"))
        if infra_err:
            from autotest import notify
            notify.notify(
                "Autopilot coder error (Claude)",
                f"The Claude coder could not run for bug `{fp}`. {info}\n\n"
                "Check CLAUDE_CODE_OAUTH_TOKEN and that the claude CLI is installed.")
            return {"fp": fp, "result": "coder-failed", "detail": info}
        return _give_up_or_retry(bug, attempts, info)

    builder._git("commit", "-m", f"fix: {bug.get('title', '')[:60]}\n\nAutonomous fix for autotest "
                 f"finding {fp} ({bug.get('category')}).")
    # Advisory regression-proof (council FIX rule): did the coder's new test
    # actually exercise the bug (fail on PRE-fix source, pass after)? Hollow/no
    # test isn't fatal — many real fixes can't have a failing-first test — so it
    # only hard-blocks under AUTOTEST_REQUIRE_REGRESSION_PROOF=1; otherwise it's
    # surfaced in the PR body + result for the operator to weigh.
    reg_status, reg_detail = builder.prove_regression()
    if os.environ.get("AUTOTEST_REQUIRE_REGRESSION_PROOF") == "1" and reg_status in ("hollow", "no-test"):
        builder._git("reset", "--hard", f"origin/{builder.BASE_BRANCH}")
        return _give_up_or_retry(bug, attempts, f"regression proof {reg_status}: {reg_detail}")
    # Force: the fix branch is loop-owned and rebuilt fresh from main each
    # attempt, so a leftover from a prior attempt (or a stranded no-PR push)
    # must be overwritten — a plain push would be rejected non-fast-forward,
    # which would then open the PR against the STALE branch content.
    builder._git("push", "-u", "--force", "origin", branch)
    pr_url, pr_err = builder._open_pr(
        branch, f"fix: {bug.get('title', '')[:60]}",
        f"Autonomous fix for autotest finding `{fp}` ({bug.get('category')}).\n\n"
        f"**Regression proof:** `{reg_status}` — {reg_detail}")
    merge = builder._merge_to_main(branch, has_pr=bool(pr_url))  # honours AUTOTEST_BUILD_MERGE
    if pr_err:
        # Branch is pushed with the fix, but no PR opened → nothing landed and
        # nothing is in flight. Leave the bug OPEN so the next cycle retries it
        # (fix_attempts is already bumped above, so it de-prioritises but is
        # never skipped). Do NOT _mark_fixing here: the finder never re-opens
        # fix-owned statuses (report.FIX_OWNED_STATUSES), so a false "fixing"
        # would strand the bug in limbo forever — even once PRs work again.
        from autotest import notify
        notify.notify(
            f"Autopilot pushed a fix for `{fp}` but could not open a PR",
            f"Branch `{branch}` carries the fix, but no PR opened so it will not land. {pr_err}")
        return {"fp": fp, "result": "fix-pushed-no-pr", "files": len(files),
                "pr": "", "pr_error": pr_err, "merge": merge, "branch": branch,
                "regression": reg_status}
    _mark_fixing(fp, branch, pr_url)
    return {"fp": fp, "result": "fix-opened", "files": len(files), "pr": pr_url,
            "merge": merge, "regression": reg_status}


def main() -> int:
    load_dotenv()
    if os.environ.get("AUTOTEST_FIX_APPLY", "1") == "0":
        bugs = _open_bugs(int(os.environ.get("AUTOTEST_FIX_MAX", "3")))
        print(json.dumps({"dry_run": True, "would_fix": [b["title"] for b in bugs]}, indent=2))
        return 0
    results = []
    for bug in _open_bugs(int(os.environ.get("AUTOTEST_FIX_MAX", "3"))):
        results.append(fix_one(bug))
    _persist_to_main()   # survive the per-bug resets so attempts/escalation stick
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
