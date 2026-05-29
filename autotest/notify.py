"""Tell the operator when the autonomous loop needs attention — rather than
silently failing, falling back, or burning Claude credits retrying forever.

Opens a GitHub issue via `gh` (so you get a real notification), de-duplicated by
title so the same problem can't spam your inbox, and always appends to a
committed ``autotest/reports/NEEDS_ATTENTION.md`` as a durable record.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ATTENTION = REPO_ROOT / "autotest" / "reports" / "NEEDS_ATTENTION.md"


def notify(title: str, body: str) -> None:
    """Best-effort operator alert. Never raises."""
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    try:
        ATTENTION.parent.mkdir(parents=True, exist_ok=True)
        with open(ATTENTION, "a", encoding="utf-8") as fh:
            fh.write(f"\n## {stamp} — {title}\n\n{body}\n")
    except OSError:
        pass

    if shutil.which("gh"):
        try:
            # Don't open a second issue for a problem already filed.
            existing = subprocess.run(
                ["gh", "issue", "list", "--state", "open", "--search", title,
                 "--json", "number", "-q", ".[].number"],
                capture_output=True, text=True, timeout=60)
            if not (existing.stdout or "").strip():
                subprocess.run(
                    ["gh", "issue", "create", "--title", title,
                     "--body", body + "\n\n— filed automatically by autotest "
                     "(the autonomous loop needs a human)."],
                    capture_output=True, text=True, timeout=60)
        except Exception:
            pass
    print(f"[notify] {title}")
