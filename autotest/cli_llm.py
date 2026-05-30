"""Text generation via the Claude CLI on the flat subscription token.

The judges + council use THIS instead of an API SDK, so the whole autotest loop
needs only ``CLAUDE_CODE_OAUTH_TOKEN`` (a Pro/Max subscription token from
`claude setup-token`) — there are NO API keys linked anywhere in autotest.

Runs from a neutral temp dir so each call doesn't load the (large) MediaHub
project context, and treats it as a plain prompt→text call. Subscription rate
limits apply, so callers keep the number of calls modest (the loop runs on a
slower cadence and the council uses fewer advisors than the API version did).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


def available() -> bool:
    """True when the Claude CLI is installed (it self-auths from
    CLAUDE_CODE_OAUTH_TOKEN in the environment)."""
    return bool(shutil.which("claude"))


def ask(system: str, user: str, max_tokens: int = 800) -> str:
    """Prompt → text via `claude -p` on the subscription. Raises on failure
    (callers already wrap judge/council calls in try/except). ``max_tokens`` is
    accepted for signature-compatibility with the old API and ignored."""
    if not shutil.which("claude"):
        raise RuntimeError("claude CLI not found (npm i -g @anthropic-ai/claude-code)")
    prompt = f"{system}\n\n{user}" if system else user
    p = subprocess.run(
        ["claude", "-p", prompt],
        cwd=tempfile.gettempdir(),  # neutral dir → don't load the big repo context
        capture_output=True, text=True,
        stdin=subprocess.DEVNULL,   # immediate EOF — else claude blocks reading an inherited pipe
        timeout=float(os.environ.get("AUTOTEST_JUDGE_TIMEOUT", "180")))
    if p.returncode != 0:
        raise RuntimeError(((p.stderr or "") + (p.stdout or ""))[-400:] or "claude -p failed")
    return p.stdout or ""
