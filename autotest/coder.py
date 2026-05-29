"""Pluggable coding agent — keep the autonomous fixer FREE.

The tester, subagents and council already run on Gemini (via ai_core). The
builder/fixer needs an *agentic coder* that edits files — and that does NOT have
to be Claude (which bills per token on the API). Google's Gemini CLI is an
agentic coder too, and runs on the same GEMINI_API_KEY you already use, on
Gemini's free tier. So by default the fixer uses Gemini — one free key powers
the whole loop. Claude stays available as an opt-in (AUTOTEST_CODER=claude).

  AUTOTEST_CODER       gemini (default) | claude | auto
  AUTOTEST_CODER_MODEL gemini model (default gemini-2.5-flash — best free limits)
  AUTOTEST_CODER_FLAGS extra CLI flags (default headless auto-approve)

Cost note: with a GEMINI_API_KEY this uses Gemini's API free tier (generous,
rate-limited); heavy use could exceed the free quota. It is free/again-cheap
versus the Claude API, and nothing here ever bills Anthropic unless you opt in.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def backend() -> str:
    pref = os.environ.get("AUTOTEST_CODER", "auto").strip().lower()
    if pref in ("gemini", "claude"):
        return pref
    # auto: prefer the FREE agent.
    if shutil.which("gemini"):
        return "gemini"
    if shutil.which("claude"):
        return "claude"
    return "none"


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
            return False, "claude CLI not found"
        flags = os.environ.get("AUTOTEST_CODER_FLAGS_CLAUDE",
                               "--permission-mode acceptEdits --dangerously-skip-permissions").split()
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
