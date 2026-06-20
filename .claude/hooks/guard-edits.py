#!/usr/bin/env python3
"""PreToolUse guard for Edit / Write / MultiEdit.

Adapted from two ideas in the ECC agent-harness project (MIT-licensed,
https://github.com/affaan-m/ECC): a secrets-detection pre-tool hook and a
"generic SaaS template" design-quality hook. ECC's versions are Node/JS and
target a generic stack; this is a dependency-free Python rewrite wired to two
rules MediaHub already states in CLAUDE.md, so the harness enforces them
instead of relying on a reviewer to remember:

  1. SECRET LEAK (blocks the edit)  -- "API keys are env/.env only, NEVER
     hard-coded ... A key committed to the repo is a leak even if later
     removed." We block any edit that would write a real provider-key literal
     (an `sk-ant-...` / `AIza...` token, or `GEMINI_API_KEY = "<literal>"`).

  2. BANNED CDN ON A UI SURFACE (warns, does not block) -- "Avoid generic
     AI-looking SaaS patterns (Tailwind defaults)" + "Fonts are self-hosted on
     every surface, never the Google Fonts CDN." We warn early (before the
     pytest font guard hard-fails) when a UI edit reintroduces a Google Fonts
     or Tailwind CDN.

Hook contract (Claude Code):
  - stdin: JSON with `tool_name` and `tool_input`.
  - exit 2 + stderr  -> block the tool call, show stderr to Claude.
  - exit 0           -> allow; stderr (if any) is surfaced as a non-blocking note.
Any parse/IO error defaults to ALLOW (exit 0) so the guard can never wedge edits.
"""
from __future__ import annotations

import json
import re
import sys

# --- 1. Secret-leak patterns (strong, low-false-positive signals) ----------
# Real key shapes. `sk-ant-` / `AIza` alone are too short to match, so the
# regexes below never trip on this file or on a pattern written in prose.
_KEY_TOKEN_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{30,}"), "Google/Gemini API key"),
]
# `GEMINI_API_KEY = "<16+ char literal>"`. The key name must be a bare
# identifier followed by `=`/`:` then a quoted literal, so legitimate env
# reads like os.environ["ANTHROPIC_API_KEY"] / getenv("GEMINI_API_KEY") (where
# the name sits *inside* quotes) are not matched.
_KEY_ASSIGN_PATTERN = re.compile(
    r"\b(GEMINI_API_KEY|ANTHROPIC_API_KEY)\b\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
)

# --- 2. Banned-CDN patterns on UI surfaces ---------------------------------
_BANNED_CDN_PATTERNS = [
    (re.compile(r"fonts\.googleapis\.com"), "Google Fonts CDN (fonts must be self-hosted)"),
    (re.compile(r"fonts\.gstatic\.com"), "Google Fonts CDN (fonts must be self-hosted)"),
    (re.compile(r"cdn\.tailwindcss\.com"), "Tailwind Play CDN (banned generic-SaaS pattern)"),
]


def _is_env_file(path: str) -> bool:
    """Skip .env / .env.* — the one legitimate home for a real key literal."""
    name = path.rsplit("/", 1)[-1]
    return name == ".env" or name.startswith(".env.")


def _is_ui_surface(path: str) -> bool:
    p = path.lower()
    if p.endswith((".css", ".html", ".js", ".jsx", ".ts", ".tsx")):
        return True
    return ("web/web.py" in p) or ("web/static" in p) or ("graphic_renderer" in p)


def _added_text(tool_name: str, tool_input: dict) -> str:
    """The text this tool would introduce into the file."""
    if tool_name == "Write":
        return str(tool_input.get("content", ""))
    if tool_name == "Edit":
        return str(tool_input.get("new_string", ""))
    if tool_name == "MultiEdit":
        return "\n".join(str(e.get("new_string", "")) for e in tool_input.get("edits", []))
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block on a malformed payload

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return 0

    path = str(tool_input.get("file_path", ""))
    added = _added_text(tool_name, tool_input)
    if not added:
        return 0

    # --- Blocking check: hard-coded provider key -------------------------
    if not _is_env_file(path):
        hits = [label for rx, label in _KEY_TOKEN_PATTERNS if rx.search(added)]
        if _KEY_ASSIGN_PATTERN.search(added):
            hits.append("provider API key assigned to a string literal")
        if hits:
            sys.stderr.write(
                "BLOCKED: this edit would hard-code a secret into the repo "
                f"({'; '.join(sorted(set(hits)))}).\n"
                "CLAUDE.md: API keys are env/.env only, NEVER hard-coded — a key "
                "committed is a leak even if later removed. Read it from the "
                "process environment (os.environ / getenv) instead, and put the "
                "value in the gitignored .env.\n"
            )
            return 2

    # --- Non-blocking check: banned CDN on a UI surface ------------------
    if _is_ui_surface(path):
        notes = [label for rx, label in _BANNED_CDN_PATTERNS if rx.search(added)]
        if notes:
            sys.stderr.write(
                "NOTE (not blocked): this UI edit reintroduces a banned CDN — "
                f"{'; '.join(sorted(set(notes)))}.\n"
                "CLAUDE.md self-hosts all fonts and bans generic-SaaS CDNs; "
                "tests/test_self_hosted_fonts.py will hard-fail on the font CDNs. "
                "Serve assets first-party instead.\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
