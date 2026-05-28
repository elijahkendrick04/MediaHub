"""Minimal .env loader for the autonomous tester.

The MediaHub app reads provider keys (GEMINI_API_KEY, ANTHROPIC_API_KEY, …)
straight from the process environment and does NOT auto-load a .env file. So the
tester loads the repo-root .env itself, before booting the app or calling
ai_core, so a key dropped in .env "just works".

RULE: the key is ONLY ever read from the environment / .env — it is never
hard-coded in source. .env is gitignored, so the secret never enters the repo.
The operator can rotate the key by editing .env alone; no code changes.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: str | Path | None = None) -> None:
    """Populate os.environ from a .env file (does not override already-set vars).
    Silent no-op if the file is missing."""
    p = Path(path) if path else REPO_ROOT / ".env"
    try:
        if not p.exists():
            return
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        return
