"""Pluggable coding agent for the autonomous fixer.

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

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_stream_json_result(raw: str) -> dict | None:
    """Extract the final ``{"type":"result", ...}`` frame from a `claude -p
    --output-format stream-json` run (the output is JSONL — one event per line).
    That frame carries the assistant's CLOSING TEXT in ``result`` and whether the
    run completed cleanly in ``is_error`` / ``subtype``. Returns the dict, or None
    if the output isn't parseable stream-json (older CLI, a crash, or the gemini
    backend). This is what lets the fixer tell "the coder fixed it" from "the
    coder investigated and concluded there is nothing to fix"."""
    found = None
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{") or '"type"' not in line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            found = obj  # keep the LAST result frame
    return found


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
        #
        # Two headless-`claude -p` hazards this guards against:
        #  1. STDIN — `claude -p` reads stdin as extra prompt input; if it
        #     inherits a non-EOF pipe (as it does under `timeout …` / `… | tee`
        #     in CI) it BLOCKS FOREVER with no output. We pass stdin=DEVNULL
        #     below for an immediate EOF. This was the real cause of the CI hang.
        #  2. PERMISSIONS — --dangerously-skip-permissions bypasses all approval
        #     prompts (the standard headless flag) so the agent never stalls on a
        #     Bash/edit approval. The CLI REFUSES it under root/sudo, so fall back
        #     to acceptEdits only when root (local/container sandboxes).
        # --output-format stream-json --verbose makes claude emit each step live,
        # so a timeout capture shows real progress (plain text buffers to the end,
        # making "no output" indistinguishable from "still working").
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        default_flags = ("--permission-mode acceptEdits" if is_root
                         else "--dangerously-skip-permissions")
        flags = os.environ.get("AUTOTEST_CODER_FLAGS_CLAUDE", default_flags).split()
        env = os.environ.copy()
        cmd = ["claude", "-p", prompt, *flags, "--verbose",
               "--output-format", "stream-json"]
        # Optional model pin for the Claude coder (e.g. "opus" for the hardest
        # bugs, "sonnet" for throughput). Unset → the CLI/subscription default,
        # so existing behaviour is unchanged unless the operator opts in.
        model = os.environ.get("AUTOTEST_CODER_MODEL_CLAUDE", "").strip()
        if model:
            cmd += ["--model", model]
    else:
        return False, "no coding agent available (install gemini-cli or claude-code)"

    try:
        # stdin=DEVNULL is critical: without it claude inherits a non-EOF pipe in
        # CI and hangs reading stdin before producing anything.
        p = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        stdout, stderr = p.stdout or "", p.stderr or ""
        # Surface the coder's ACTUAL conclusion, not CLI metadata. With
        # --output-format stream-json the final {"type":"result",...} frame carries
        # the assistant's closing text + whether it completed cleanly. The old code
        # kept only stdout[-2000:] — the JSON metadata tail (service_tier/
        # terminal_reason) — which is useless for telling "the coder fixed it" from
        # "the coder investigated and found nothing to fix". (Council 2026-06-01.)
        if be == "claude":
            res = _parse_stream_json_result(stdout)
            if res is not None:
                conclusion = str(res.get("result") or "").strip()
                is_err = bool(res.get("is_error"))
                clean = (not is_err) and str(res.get("subtype") or "success") == "success"
                # A trailing, truncation-proof marker the fixer reads to tell a
                # CLEAN no-edit completion (investigated, declined → a candidate
                # false-positive) from an error/timeout (genuine give-up → retry).
                marker = (f"<<CODER_RESULT is_error={'true' if is_err else 'false'} "
                          f"subtype={res.get('subtype', 'success')} turns={res.get('num_turns', '?')}>>")
                body = (conclusion or stdout[-1500:])[-2400:]
                tail = ("\n" + stderr[-500:]) if (stderr and is_err) else ""
                return (p.returncode == 0 or clean), f"{body}{tail}\n{marker}"
        out = stdout[-2000:] + stderr[-1000:]
        return p.returncode == 0, out
    except subprocess.TimeoutExpired as exc:
        # Surface whatever the coder emitted before we killed it: "produced
        # nothing" (blocked at startup / on a permission) vs "was mid-edit"
        # (genuinely slow) is the whole diagnosis.
        def _tail(x: object) -> str:
            if not x:
                return ""
            return x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)
        partial = (_tail(exc.stdout)[-700:] + _tail(exc.stderr)[-400:]).strip()
        detail = (f"; last output before kill: {partial[-700:]}" if partial
                  else " (no output captured — blocked before producing anything)")
        return False, f"{be} coder timed out after {timeout:.0f}s{detail}"
    except Exception as exc:
        return False, f"{be} coder error: {exc}"


# --- quality discipline -------------------------------------------------------
CODING_STANDARDS = """\
Write code to a professional standard. Core rules:
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
Now switch roles to a senior code REVIEWER (see
autotest/skills/coding/agent-analyze-code-quality.md). Inspect the current uncommitted
changes — you may run
`git diff` to see them (read-only; do NOT commit, push, or revert) — and FIX any problems
you find, directly in the files. Check: requirement fully met; edge cases + error handling;
security (XSS/injection/IDOR, no leaked secrets); the protected deterministic engine is
untouched; repo conventions followed; tests exist and would pass; no debug/leftover code.
If it's already solid, make no changes.
"""


def write_code(task: str, *, complex: bool = False, review: bool = True,
               cwd: Path | None = None, timeout: float | None = None) -> tuple[bool, str]:
    """Run the coder with the coding discipline: a standards-guided
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
    # The reviewer/refine pass is a second full coder call. It can be turned off
    # (AUTOTEST_CODER_REVIEW=0) when the per-bug time budget is tight and the
    # green-test gate is already the safety bar — e.g. the CI fixer.
    if review and os.environ.get("AUTOTEST_CODER_REVIEW", "1") != "0":
        ok2, out2 = run_coder(REVIEW_PROMPT, cwd=cwd, timeout=timeout)
        log += "\n\n--- self-review/refine pass ---\n" + (out2 or "")[-1200:]
    return True, log
