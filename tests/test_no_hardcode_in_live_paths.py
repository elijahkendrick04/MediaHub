"""
tests_v75/test_no_hardcode_in_live_paths.py
============================================

Asserts that NO source domain or provider is hardcoded anywhere in the live
runtime tree. Trust-ledger preferences are LEARNED at runtime by
``pb_discovery``; live code must never reach for a literal provider name.

This is the canonical V7.5 anti-shortcut guardrail. It greps every Python
source file under the live packages for forbidden literals.

Live packages audited (must contain ZERO hardcoded provider references):
    interpreter/
    context_engine/
    pb_discovery/
    voice/learned/
    swim_content_v4/      (excluding any sub-folder named ``legacy*``)
    swim_content_v5/
    recognition/
    recognition_swim/
    engine_v4/
    voice/                (the wider voice tree)
    web_research/
    content_pack/
    brand/
    workflow/
    club_platform/
    canonical/
    history/

Explicitly EXCLUDED (legacy / dead code or test scaffolding):
    swim_content/            (V7.4 dead path)
    swim_content_pb/         (V7.4 dead path)
    legacy_scripts/          (one-off data-collection scripts moved aside)
    tests/, tests_v4/, tests_v75/   (tests reference legacy code on purpose)
    *.md / docs              (specs/audits document the historical state)
    __pycache__              (binary)

Forbidden literals (case-insensitive):
    swimmingresults.org
    swimcloud.com
    british-swimming.org
    sportsystems.uk.com
    SR_BASE
"""
from __future__ import annotations

from pathlib import Path

import pytest


# After the repo migration, all production packages moved to src/mediahub/*.
# Walk into that subtree so the "no hardcoded paths" sweep still inspects the
# live code (not stale paths at the repo root).
_REPO_ROOT = Path(__file__).resolve().parent.parent / "src" / "mediahub"

# ── Live package roots ────────────────────────────────────────────────────────
_LIVE_PACKAGES = [
    "interpreter",
    "context_engine",
    "pb_discovery",
    # voice/learned is a sub-package of voice/ — keep both so the wider
    # tree is also audited.
    "voice",
    "swim_content_v4",
    "swim_content_v5",
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
]

# Directories whose name (anywhere in the path) marks a file as legacy/excluded.
_EXCLUDED_DIRS = {
    "swim_content",       # V7.4 legacy
    "swim_content_pb",    # V7.4 legacy
    "legacy_scripts",     # one-off helpers moved aside
    "tests",              # unit-test folders intentionally reference legacy
    "tests_v4",
    "tests_v75",
    "__pycache__",
    ".venv",
    ".git",
}

# Case-insensitive forbidden literals.
_FORBIDDEN = [
    "swimmingresults.org",
    "swimcloud.com",
    "british-swimming.org",
    "sportsystems.uk.com",
    "SR_BASE",
]


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & _EXCLUDED_DIRS)


def _live_python_files() -> list[Path]:
    """Return every live .py file under any audited package, minus exclusions."""
    files: list[Path] = []
    for pkg in _LIVE_PACKAGES:
        root = _REPO_ROOT / pkg
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if _is_excluded(p.relative_to(_REPO_ROOT)):
                continue
            files.append(p)
    return sorted(set(files))


def _scan(py_file: Path, needle: str) -> list[tuple[int, str]]:
    needle_lc = needle.lower()
    hits: list[tuple[int, str]] = []
    try:
        text = py_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return hits
    for i, line in enumerate(text.splitlines(), start=1):
        if needle_lc in line.lower():
            hits.append((i, line.rstrip()))
    return hits


def test_live_packages_actually_exist():
    """Core live packages (under src/mediahub) must exist.

    After the v8 src-layout migration, the legacy ``swim_content_v4`` /
    ``swim_content_v5`` packages were absorbed into ``pipeline`` and ``legacy``
    respectively. This test now checks the modern package names.
    """
    must_exist = [
        "interpreter", "context_engine", "pb_discovery",
        "voice", "pipeline", "club_platform",
    ]
    missing = [p for p in must_exist if not (_REPO_ROOT / p).exists()]
    assert not missing, f"Live packages missing from repo: {missing}"


def test_live_python_files_collected():
    """Sanity: the audit must actually find files to audit."""
    files = _live_python_files()
    assert len(files) > 20, (
        f"Audit collected only {len(files)} live .py files — "
        f"either the repo layout changed or the exclusion list is too broad."
    )


@pytest.mark.parametrize("forbidden", _FORBIDDEN)
def test_no_hardcoded_provider_in_live_paths(forbidden: str):
    """No live source file may mention a hardcoded provider domain or constant."""
    offenders: list[str] = []
    for f in _live_python_files():
        hits = _scan(f, forbidden)
        for line_no, line in hits:
            offenders.append(
                f"{f.relative_to(_REPO_ROOT)}:{line_no}: {line.strip()[:160]}"
            )
    if offenders:
        msg = (
            f"\n\nForbidden literal '{forbidden}' found in {len(offenders)} "
            f"live source line(s).\n"
            f"V7.5 contract: trust-ledger preferences are LEARNED at runtime; "
            f"never hardcode a provider.\n\nOffenders:\n  - "
            + "\n  - ".join(offenders)
        )
        pytest.fail(msg)
