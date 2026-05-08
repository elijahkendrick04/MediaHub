"""V8.1: No Swansea hardcodes anywhere in live code paths.

This test greps every in-scope directory (live code + active templates)
for the case-insensitive token ``swansea`` and asserts ZERO matches.
Legacy directories (``swim_content/``, ``swim_content_pb/``,
``swim_content_v5/``, ``legacy_scripts/``) and corpus / discovered-data
directories are excluded \u2014 they may legitimately reference Swansea as a
real club name.
"""
from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Directories that must not contain any Swansea references in active code.
LIVE_DIRS = [
    "swim_content_v4",
    "interpreter",
    "context_engine",
    "pb_discovery",
    "voice",
    "media_ai",
    "media_library",
    "media_requirements",
    "venue_search",
    "inspiration",
    "creative_brief",
    "graphic_renderer",
    "content_pack_visual",
    "recognition",
    "recognition_swim",
    "engine_v4",
    "web_research",
    "content_pack",
    "brand",
    "workflow",
    "club_platform",
    "canonical",
    "history",
    "templates",
    "data/voices/seed",
]

EXCLUDED_DIRS = {
    "__pycache__",
    "node_modules",
    ".venv",
}

# File extensions to scan
INTERESTING_SUFFIXES = {
    ".py", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".css", ".jinja", ".jinja2",
}

PATTERN = re.compile(r"swansea", re.IGNORECASE)


def _scan_directory(root: pathlib.Path) -> list[str]:
    matches: list[str] = []
    if not root.exists():
        return matches
    for path in root.rglob("*"):
        # Skip any path containing an excluded directory component
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in INTERESTING_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                matches.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()[:160]}"
                )
    return matches


def test_no_swansea_hardcodes_in_live_paths() -> None:
    """Fail if any in-scope file references Swansea."""
    all_matches: list[str] = []
    for d in LIVE_DIRS:
        root = PROJECT_ROOT / d
        all_matches.extend(_scan_directory(root))

    if all_matches:
        pytest.fail(
            "Swansea hardcodes found in live code paths:\n\n"
            + "\n".join(all_matches[:60])
            + (f"\n\n(\u2026{len(all_matches) - 60} more)" if len(all_matches) > 60 else "")
        )
