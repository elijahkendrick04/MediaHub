#!/usr/bin/env python3
"""Shared git + PR operations and safety gates for the autonomous coding loop.

The mechanical backbone the bug-fixer (``autotest.fix_loop``) uses to turn a
coding task into a landed PR: drive the coder to a green test suite, prove the
fix exercises the bug, guard the diff (the protected deterministic engine + a
scope cap), classify product-vs-harness for the auto-merge gate, open the PR,
and arm CI-gated auto-merge. It carries no roadmap/build logic — this is the
neutral plumbing that used to live inside the (now removed) roadmap builder.

The ``AUTOTEST_BUILD_*`` environment-variable names are kept verbatim: the
deployed fixer workflow (.github/workflows/autotest.yml) sets them, so renaming
them would silently change the fixer's behaviour on the runner.

Safety gates (the only things between a bad AI change and prod, so strict):
  * kill switch     — an `autotest/STOP` file halts the loop immediately
  * protected paths — the deterministic engine (parsers/detectors/ranker/
                      colour-science) must NOT be touched (CLAUDE.md); a diff
                      that edits them aborts before any merge
  * scope cap       — refuse oversized diffs (runaway guard)
  * test gate       — the suite must stay green or nothing merges
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STOP_FILE = REPO_ROOT / "autotest" / "STOP"
BASE_BRANCH = os.environ.get("AUTOTEST_BASE_BRANCH", "main")

# Deterministic engine — must never be AI-edited without explicit approval
# (CLAUDE.md). A diff touching any of these aborts the cycle.
PROTECTED = (
    "src/mediahub/interpreter/", "src/mediahub/pb_discovery/",
    "src/mediahub/recognition/", "src/mediahub/recognition_swim/",
    "legacy/swim_content_v5/ranker_v3.py", "src/mediahub/theming/logo_chip.py",
    "src/mediahub/media_library/selector.py",
)

# Self-governance ("constitution") set — the files that GOVERN the autonomous loop:
# its merge gate + guards + THIS classifier (gitops.py), the fixer's decision logic
# (fix_loop.py: attempt cap, the A6 corroboration gate), the kill switch, the
# governance docs, CI policy, the deploy/dependency supply-chain, the CODEOWNERS
# boundary, and the deterministic tripwire test. A change touching ANY of these
# requires a HUMAN merge (council 2026-06-02) — the loop must NEVER auto-merge a
# change to the files that decide what the loop may do (including the classifier
# itself, or it would just reclassify its own diff as ordinary code).
#
# This is the IN-REPO half of a TWO-LAYER boundary. The real stop is platform-side:
# GitHub branch protection on `main` + `.github/CODEOWNERS` requiring a human review
# on these paths, with the bot identity holding NO bypass — because an in-repo guard
# is run by the same identity that writes the code (the council peer-review blind spot).
# See autotest/CHANGE_CLASSIFICATION.md + docs/adr/0005-autotest-governed-auto-merge.md.
SELF_GOVERNANCE = (
    "autotest/gitops.py", "autotest/fix_loop.py", "autotest/STOP",
    "autotest/CHANGE_CLASSIFICATION.md", "autotest/AUTONOMY_BOUNDARY.md",
    "autotest/PROOF_CRITERION.md", "autotest/PROOF_VERIFIER.md",
    "tests/test_autonomy_tripwire.py", "tests/test_autotest_change_classification.py",
    ".github/workflows/", ".github/CODEOWNERS",
    "CLAUDE.md", "render.yaml", "Dockerfile",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
)


def _is_self_governance(f: str) -> bool:
    return any(f == p or f.startswith(p) or (p == "CLAUDE.md" and f.endswith("CLAUDE.md"))
               for p in SELF_GOVERNANCE)


def classify_change(files: list[str]) -> str:
    """Apply the human-authored 3-way classification (autotest/CHANGE_CLASSIFICATION.md)
    to a changed-file set. Returns:
      * ``self_governance`` — touches a file that GOVERNS the loop → HUMAN merge required
        (also enforced platform-side via branch protection + CODEOWNERS).
      * ``harness`` — ordinary autotest machinery (finders, judges, the report lifecycle,
        metrics) → auto-merge eligible (the autonomy the operator armed, council 2026-06-02).
      * ``product`` — src/mediahub product code / tests → auto-merge eligible.
    The loop applies this mechanically; it does NOT classify its own changes. Stricter
    wins: ANY self-governance file makes the whole diff ``self_governance``. An empty or
    unknown set fails safe to ``self_governance`` (never auto-merge an unknown change)."""
    if not files:
        return "self_governance"
    stripped = [f.strip() for f in files]
    if any(_is_self_governance(f) for f in stripped):
        return "self_governance"
    if any(f.startswith("autotest/") for f in stripped):
        return "harness"
    return "product"
MAX_FILES = int(os.environ.get("AUTOTEST_BUILD_MAX_FILES", "25"))
MAX_INSERTIONS = int(os.environ.get("AUTOTEST_BUILD_MAX_INSERTIONS", "2000"))


def _git(*args: str, check: bool = False) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _touches_protected(files: list[str]) -> list[str]:
    return [f for f in files if any(f.startswith(p) or p in f for p in PROTECTED)]


def _test_gate() -> tuple[bool, str]:
    p = subprocess.run(["python", "-m", "pytest", "tests/", "-q"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True,
                       timeout=float(os.environ.get("AUTOTEST_BUILD_TEST_TIMEOUT", "1800")))
    tail = (p.stdout or "")[-800:]
    return p.returncode == 0, tail


# Runtime/data areas a gate run, the finder, or an over-eager coder may rewrite.
# They must NEVER ride along in a fix commit to main — only source edits do.
_NO_COMMIT_PATHS = ("autotest/reports", "autotest/screenshots", "autotest/runs", "data")


def _changed_files() -> tuple[list[str], int]:
    _git("add", "-A")
    # Un-stage runtime artifacts so `git add -A` can't sweep a rewritten ledger,
    # screenshot, or tracked data/ file into the commit (audit H2).
    for p in _NO_COMMIT_PATHS:
        _git("reset", "-q", "--", p)
    rc, out = _git("diff", "--cached", "--numstat")
    files, insertions = [], 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            files.append(parts[2])
            if parts[0].isdigit():
                insertions += int(parts[0])
    return files, insertions


def _classify_pr_error(err: str) -> str:
    """Turn a raw `gh pr create` failure into an actionable operator message.
    The common silent killer is the repo policy that blocks the Actions token
    from opening PRs — name it explicitly so the operator knows the exact fix."""
    low = err.lower()
    if "not permitted to create" in low or "createpullrequest" in low:
        return ("GitHub Actions is not permitted to create PRs for this repo. Fix: "
                "enable Settings → Actions → General → 'Allow GitHub Actions to create "
                "and approve pull requests', or add an AUTOTEST_GH_PAT secret (a "
                "fine-grained PAT with PR write) — the workflows prefer it over "
                "GITHUB_TOKEN. Raw: " + (err[:300] or "non-zero exit"))
    if any(s in low for s in ("http 401", "authentication", "gh auth", "bad credentials")):
        return "gh auth/token problem opening the PR. Raw: " + (err[:300] or "non-zero exit")
    return "gh pr create failed: " + (err[:400] or "empty output, non-zero exit")


def _open_pr(branch: str, title: str, body: str) -> tuple[str, str]:
    """Create (or recover) the PR for `branch`. Returns (pr_url, error).

    A non-empty error means NO PR exists — callers must not then claim a merge
    was armed. The old code ignored `gh pr create`'s exit code, so a blocked
    creation silently produced `pr=""` *and* a false 'auto-merge enabled', and
    the fix branch was stranded with nothing landing. The 'already exists' case
    (a re-run on the same branch) recovers the live URL so it reads as success."""
    import shutil
    if not shutil.which("gh"):
        return "", "gh CLI not found — cannot open a PR"
    pr = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", BASE_BRANCH,
                         "--title", title, "--body", body],
                        cwd=str(REPO_ROOT), capture_output=True, text=True)
    url = (pr.stdout or "").strip()
    if pr.returncode == 0 and url.startswith("http"):
        return url, ""
    err = (pr.stderr or pr.stdout or "").strip()
    if "already exists" in err.lower():
        view = subprocess.run(["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"],
                              cwd=str(REPO_ROOT), capture_output=True, text=True)
        existing = (view.stdout or "").strip()
        if existing.startswith("http"):
            return existing, ""
    return "", _classify_pr_error(err)


def _merge_to_main(branch: str, *, has_pr: bool, files: list[str] | None = None) -> str:
    """Arm CI-gated auto-merge for an EXISTING PR (armed by AUTOTEST_BUILD_MERGE=1).
    `gh pr merge --auto` waits for green CI so a red build never lands — but it
    needs a real PR, so this no-ops honestly when none was opened, and verifies
    the command actually succeeded instead of assuming it did.

    Governance gate (council 2026-06-02 + CHANGE_CLASSIFICATION.md): auto-merge is
    armed for a PRODUCT change AND for an ordinary HARNESS change (the operator armed
    the autotest harness as the autonomous zone). It is NEVER armed for a SELF-GOVERNANCE
    change — the loop must not auto-land a change to its own merge/guard logic, kill
    switch, classifier, CI policy, deploy surface, or governance docs. That boundary is
    ALSO enforced platform-side (branch protection + CODEOWNERS), which is the real stop."""
    import shutil
    if os.environ.get("AUTOTEST_BUILD_MERGE") != "1":
        return "merge not armed (set AUTOTEST_BUILD_MERGE=1 to auto-merge to main on green CI)"
    if not has_pr:
        return "no PR opened — auto-merge NOT armed (nothing will land; see the PR error)"
    kind = classify_change(files or [])
    if kind == "self_governance":
        return ("auto-merge NOT armed: this is a SELF-GOVERNANCE change "
                "(CHANGE_CLASSIFICATION.md) — the loop may not auto-merge a change to the "
                "files that govern it; it requires a HUMAN merge (also enforced by GitHub "
                "branch protection + CODEOWNERS). PR opened; left for review.")
    if not shutil.which("gh"):
        return "gh CLI not found — cannot enable CI-gated auto-merge"
    # --delete-branch tidies the loop-owned branch once the auto-merge lands, so
    # these throwaway branches don't accumulate on origin.
    m = subprocess.run(["gh", "pr", "merge", branch, "--auto", "--squash", "--delete-branch"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True)
    if m.returncode != 0:
        return "auto-merge NOT armed: " + ((m.stderr or m.stdout or "").strip()[:300]
                                           or "gh pr merge failed")
    return "auto-merge to main enabled (will land when CI is green)"


def implement_until_green(task: str, *, complex: bool = False,
                          label: str = "change") -> tuple[bool, list[str], int, str]:
    """Implement the task, then ITERATE against the test gate — feeding each
    failure back to the coder to fix the ROOT CAUSE (using the repo's coding
    skills) — until the suite is green or the iteration cap is hit. The
    protected-path and scope guards are re-checked every iteration. Bounded by
    AUTOTEST_GATE_MAX_ITERS so it can never burn credits forever. Returns
    (ok, files, insertions, info)."""
    from autotest import coder
    max_iters = max(1, int(os.environ.get("AUTOTEST_GATE_MAX_ITERS", "3")))
    files: list[str] = []
    ins = 0
    feedback = ""
    for attempt in range(1, max_iters + 1):
        prompt = task if attempt == 1 else feedback
        ok, log = coder.write_code(prompt, complex=(complex and attempt == 1), cwd=REPO_ROOT)
        files, ins = _changed_files()
        if not files:
            # No edits at all. Two very different cases, told apart by the coder's
            # own completion frame (coder._parse_stream_json_result, surfaced as a
            # trailing <<CODER_RESULT ...>> marker):
            #   • CLEAN completion, no edits → the coder investigated and DECLINED
            #     to edit (the finding is likely a false-positive / already-correct).
            #     fix_one quarantines this to needs_disproof instead of retrying it
            #     forever (council 2026-06-01: surface, don't self-acquit).
            #   • error / timeout / CLI-missing → genuine infra failure or give-up →
            #     retry (never-skip), as before.
            clean_noedit = "<<CODER_RESULT" in log and "is_error=false" in log
            tag = "coder-noedit-complete" if clean_noedit else "coder-failed"
            return False, files, ins, f"{tag} (iter {attempt}): {log[-400:]}"
        # The coder MADE edits. Judge them by the TEST GATE, not the CLI exit
        # code: `claude -p` exits non-zero on max-turns/stream quirks even when it
        # produced a perfectly good, suite-passing fix — don't throw that away.
        prot = _touches_protected(files)
        if prot:
            return False, files, ins, f"aborted: touched protected engine {prot}"
        if len(files) > MAX_FILES or ins > MAX_INSERTIONS:
            return False, files, ins, f"aborted: diff too large ({len(files)} files, +{ins})"
        gate_ok, tail = _test_gate()
        if gate_ok:
            return True, files, ins, f"green after {attempt} gate iteration(s)"
        # Feed the failure back so the coder fixes the ROOT CAUSE next iteration.
        feedback = (
            f"Your change to {label} FAILED the test gate. Find and fix the ROOT CAUSE "
            f"so `python -m pytest tests/ -q` passes. Do NOT delete, skip, or weaken any "
            f"test to force a pass — fix the actual problem. Follow the discipline in "
            f"autotest/skills/coding/. Do NOT run git. pytest output:\n{tail[-2500:]}")
    return False, files, ins, f"still failing the gate after {max_iters} iterations"


def _added_test_selectors(parent: str) -> tuple[list[str], list[str]]:
    """(changed test files, names of test_ functions ADDED) between parent..HEAD."""
    rc, out = _git("diff", "--name-only", f"{parent}..HEAD", "--", "tests/")
    test_files = [f for f in out.splitlines() if f.strip().endswith(".py")]
    if not test_files:
        return [], []
    rc, diff = _git("diff", f"{parent}..HEAD", "--", *test_files)
    names = re.findall(r"^\+\s*def (test_\w+)", diff, re.M)
    seen: set[str] = set()
    uniq = [n for n in names if not (n in seen or seen.add(n))]
    return test_files, uniq


def prove_regression(parent: str | None = None) -> tuple[str, str]:
    """Advisory regression-proof (council FIX rule): does the fix's NEW test
    actually exercise the bug — fail/error on the PRE-fix source, pass after?
    "Prove it when you can, never block when you can't."

    Returns (status, detail) where status is one of:
      proven   — a new test fails/errors on pre-fix source (so it exercises the bug)
      hollow   — a new test passes even on pre-fix source (may not exercise the bug)
      no-test  — the fix added no new test_ function (some fixes legitimately can't)
      unproven — couldn't run the proof (no parent, added/deleted-only diff, error)

    Never raises and never rewrites history. It reverts the fix's SOURCE in the
    working tree (the editable install imports from there), runs ONLY the new
    tests, then restores with `git reset --hard HEAD`. Advisory by default; the
    caller hard-blocks only under AUTOTEST_REQUIRE_REGRESSION_PROOF=1."""
    try:
        if parent is None:
            rc, mb = _git("merge-base", "HEAD", f"origin/{BASE_BRANCH}")
            parent = mb.strip() if rc == 0 and mb.strip() else ""
            if not parent:
                rc, p = _git("rev-parse", "HEAD~1")
                parent = p.strip() if rc == 0 else ""
        if not parent:
            return "unproven", "could not determine the parent commit"

        test_files, names = _added_test_selectors(parent)
        if not names:
            return "no-test", "the fix added no new test_ function"

        rc, out = _git("diff", "--name-only", f"{parent}..HEAD")
        src_files = [f for f in out.splitlines() if f.strip() and not f.startswith("tests/")]
        if not src_files:
            return "unproven", "fix changed nothing outside tests/ — nothing to revert"

        # Revert the fix's source to pre-fix, IN PLACE (editable install).
        for f in src_files:
            rc, _ = _git("cat-file", "-e", f"{parent}:{f}")
            if rc == 0:
                _git("checkout", parent, "--", f)          # modified/deleted → parent
            else:
                try:                                       # added-by-fix → remove
                    (REPO_ROOT / f).unlink()
                except OSError:
                    pass
        kexpr = " or ".join(names)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", *test_files, "-k", kexpr,
                 "-q", "-p", "no:cacheprovider"],
                cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
            rc_prefix = proc.returncode
        finally:
            _git("reset", "--hard", "HEAD")                # bulletproof restore to the fix

        if rc_prefix == 5:
            return "no-test", f"no test matched the new selectors ({kexpr})"
        if rc_prefix == 0:
            return "hollow", f"new test(s) ({kexpr}) PASS on pre-fix source — may not exercise the bug"
        # rc 1 (failed) or 2/3 (collection/error, e.g. imports a helper the fix added)
        return "proven", f"new test(s) ({kexpr}) fail/error on pre-fix source, pass with the fix"
    except Exception as e:
        try:
            _git("reset", "--hard", "HEAD")
        except Exception:
            pass
        return "unproven", f"regression proof could not run: {type(e).__name__}: {str(e)[:120]}"
