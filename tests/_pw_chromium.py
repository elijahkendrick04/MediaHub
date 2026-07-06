"""Shared resolver for the prebaked Playwright Chromium under /opt/pw-browsers.

The remote container prebakes a matching Chromium (see docs/WEB_INTERACTION.md).
Browser e2e tests used to hardcode ``chromium-1194``; on a prebake revision bump
every one of them would silently skip, losing coverage without a failure. This
resolves the executable dynamically:

1. the ``/opt/pw-browsers/chromium`` symlink when the prebake provides one
   (it points at the chrome binary, or at a revision directory);
2. else the newest ``chromium-<rev>/chrome-linux/chrome`` by revision number;
3. else a path that does not exist — callers keep their existing
   ``.is_file()`` skip guard, so tests still skip cleanly where no browser
   is prebaked.
"""
from __future__ import annotations

from pathlib import Path

_PW_ROOT = Path("/opt/pw-browsers")


def _revision(chrome: Path) -> int:
    # /opt/pw-browsers/chromium-1223/chrome-linux/chrome -> 1223
    name = chrome.parent.parent.name
    try:
        return int(name.split("-", 1)[1])
    except (IndexError, ValueError):
        return -1


def resolve_prebaked_chromium() -> Path:
    """The prebaked Chromium executable, or a non-existent path when absent."""
    link = _PW_ROOT / "chromium"
    try:
        if link.exists():
            target = link.resolve()
            if target.is_file():
                return target
            candidate = target / "chrome-linux" / "chrome"
            if candidate.is_file():
                return candidate
    except OSError:
        pass
    revisions = sorted(
        (p for p in _PW_ROOT.glob("chromium-*/chrome-linux/chrome") if p.is_file()),
        key=_revision,
    )
    if revisions:
        return revisions[-1]
    return _PW_ROOT / "chromium-missing" / "chrome-linux" / "chrome"
