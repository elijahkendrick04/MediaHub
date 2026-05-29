"""Pluggable coding agent for the autonomous builder/fixer.

By default the coder is **Claude Code on a flat Pro/Max subscription** — it
authenticates from CLAUDE_CODE_OAUTH_TOKEN (a subscription token, NOT an API
key), so there is no per-token API billing. The whole autotest loop (judges,
council, coder) runs on that one subscription token; no API keys are linked.

  AUTOTEST_CODER        claude (default) | gemini
  AUTOTEST_CODER_MODEL  model for the gemini backend, if used
  AUTOTEST_CODER_FLAGS  extra CLI flags (default headless auto-approve)

The gemini backend (Gemini CLI on GEMINI_API_KEY) remains available as an
opt-in for anyone who prefers the free tier over a Claude subscription.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def backend() -> str:
    # Claude-only by default (operator's choice: best code quality, NO Gemini
    # fallback for the coder — a Claude problem must surface, not silently
    # downgrade). Set AUTOTEST_CODER=gemini to override explicitly.
    pref = os.environ.get("AUTOTEST_CODER", "claude").strip().lower()
    return pref if pref in ("gemini", "claude") else "claude"


def available() -> bool:
    return backend() != "none"


def run_coder(prompt: str, *, cwd: Path | None = None, timeout: float | None = None) -> tuple[bool, str]:
    """Drive the configured agentic coder headlessly to edit the repo. Returns
    (ok, output_tail). Never raises."""
    cwd = cwd or REPO_ROOT
    timeout = timeout or float(os.environ.get("AUTOTEST_CODER_TIMEOUT", "1800"))
    be = backend()

    if be == "gemini":
        if not shutil.which("gemini"):
            return False, "gemini CLI not found (npm i -g @google/gemini-cli)"
        model = os.environ.get("AUTOTEST_CODER_MODEL", "gemini-2.5-flash")
        flags = os.environ.get("AUTOTEST_CODER_FLAGS", "--yolo --skip-trust").split()
        env = os.environ.copy()
        # Required for headless/automated runs in an untrusted checkout.
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
        cmd = ["gemini", "-p", prompt, "-m", model, *flags]
    elif be == "claude":
        if not shutil.which("claude"):
            return False, "claude CLI not found (npm i -g @anthropic-ai/claude-code)"
        # Auth is read from the environment by the CLI: CLAUDE_CODE_OAUTH_TOKEN
        # (a Pro/Max SUBSCRIPTION token from `claude setup-token` — flat cost) is
        # preferred; ANTHROPIC_API_KEY (metered) is the fallback. The CI
        # workflows set only the subscription token so billing stays flat.
        # NOTE: --dangerously-skip-permissions is refused under root; acceptEdits
        # auto-approves file edits headlessly and works as root.
        flags = os.environ.get("AUTOTEST_CODER_FLAGS_CLAUDE",
                               "--permission-mode acceptEdits").split()
        env = os.environ.copy()
        cmd = ["claude", "-p", prompt, *flags]
    else:
        return False, "no coding agent available (install gemini-cli or claude-code)"

    try:
        p = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "")[-2000:] + (p.stderr or "")[-1000:]
        return p.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"{be} coder timed out after {timeout:.0f}s"
    except Exception as exc:
        return False, f"{be} coder error: {exc}"


# --- quality discipline (from the vendored ruflo coding skills) --------------
SKILLS_DIR = REPO_ROOT / "autotest" / "skills" / "coding"

CODING_STANDARDS = """\
Write code to a professional standard, following the discipline in the skills under
autotest/skills/coding/ (agent-coder, sparc-methodology, agent-reviewer, agent-tester) —
read them if useful. Core rules:
- Clarity: clear names, single responsibility, small functions; match the surrounding
  code's conventions and style EXACTLY.
- Robustness: handle edge cases and errors; validate inputs; never crash on bad data.
- Tests: add or extend tests for new behaviour; the full suite must stay green.
- MediaHub rules (CLAUDE.md, non-negotiable): do NOT modify the deterministic engine
  (parsers in interpreter/ & pb_discovery/, detectors in recognition*/, the ranker,
  colour-science); route AI through media_ai.llm / ai_core.llm; NEVER hard-code API keys
  (env/.env only); storage via DATA_DIR; internal links via url_for(); HTML-escape output.
- Keep the diff minimal and focused — only what the task needs, no unrelated refactors.
- Do NOT run git; the harness commits.
"""

SPARC_NOTE = """\
This is a non-trivial change: PLAN before coding (SPARC) — briefly establish the
specification, the approach, and the files/interfaces you'll touch, THEN implement.
"""

REVIEW_PROMPT = """\
Now switch roles to a senior code REVIEWER (see autotest/skills/coding/agent-reviewer.md
and agent-analyze-code-quality.md). Inspect the current uncommitted changes — you may run
`git diff` to see them (read-only; do NOT commit, push, or revert) — and FIX any problems
you find, directly in the files. Check: requirement fully met; edge cases + error handling;
security (XSS/injection/IDOR, no leaked secrets); the protected deterministic engine is
untouched; repo conventions followed; tests exist and would pass; no debug/leftover code.
If it's already solid, make no changes.
"""


def write_code(task: str, *, complex: bool = False, review: bool = True,
               cwd: Path | None = None, timeout: float | None = None) -> tuple[bool, str]:
    """Run the coder with the ruflo coding discipline: a standards-guided
    implement pass, then (default) a reviewer/refine pass on the same working
    tree. ``complex=True`` adds a SPARC plan-first instruction (for roadmap
    builds). Returns (ok, combined_log)."""
    cwd = cwd or REPO_ROOT
    parts = [CODING_STANDARDS]
    if complex:
        parts.append(SPARC_NOTE)
    parts.append("TASK:\n" + task)
    ok, out = run_coder("\n\n".join(parts), cwd=cwd, timeout=timeout)
    if not ok:
        return False, out
    log = (out or "")[-1200:]
    if review:
        ok2, out2 = run_coder(REVIEW_PROMPT, cwd=cwd, timeout=timeout)
        log += "\n\n--- self-review/refine pass ---\n" + (out2 or "")[-1200:]
    return True, log
