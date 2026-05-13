"""
tests_v75/test_no_hardcoded_sources.py — Verify zero hardcoded source references.

Greps context_engine/, pb_discovery/, and interpreter/ for forbidden literal
substrings. Asserts zero matches in any Python source file under those packages.

Forbidden literals:
- swimmingresults
- swimcloud
- british-swimming
- sportsystems
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Repo root
# After the repo migration, all production packages moved to src/mediahub/*.
_REPO_ROOT = Path(__file__).resolve().parent.parent / "src" / "mediahub"

# Packages to audit
_PACKAGES = ["context_engine", "pb_discovery", "interpreter"]

# Forbidden literal substrings (case-insensitive search in source files)
_FORBIDDEN = [
    "swimmingresults",
    "swimcloud",
    "british-swimming",
    "sportsystems",
]


def _get_python_files(package_name: str) -> list[Path]:
    """Return all .py files under a package directory (if it exists)."""
    package_dir = _REPO_ROOT / package_name
    if not package_dir.exists():
        return []
    return list(package_dir.rglob("*.py"))


def _search_forbidden(py_file: Path, forbidden: str) -> list[tuple[int, str]]:
    """
    Search a Python file for a forbidden literal substring.
    Returns list of (line_number, line_content) for matches.
    """
    matches = []
    try:
        content = py_file.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), start=1):
            if forbidden.lower() in line.lower():
                matches.append((i, line.rstrip()))
    except (OSError, UnicodeDecodeError):
        pass
    return matches


# ── Parametrised tests ────────────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", _FORBIDDEN)
@pytest.mark.parametrize("package", _PACKAGES)
def test_no_hardcoded_source_in_package(package: str, forbidden: str):
    """
    Assert that no Python file in the given package contains the forbidden literal.

    If the package directory does not exist (e.g. interpreter not yet built),
    the test passes with a note — zero files means zero violations.
    """
    package_dir = _REPO_ROOT / package
    if not package_dir.exists():
        pytest.skip(
            f"Package '{package}' directory does not exist yet "
            f"(may be built by parallel subagent) — skipping, zero violations assumed."
        )

    py_files = _get_python_files(package)
    if not py_files:
        # Empty package — no violations possible
        return

    all_violations: list[str] = []
    for py_file in py_files:
        matches = _search_forbidden(py_file, forbidden)
        for line_num, line_content in matches:
            rel = py_file.relative_to(_REPO_ROOT)
            all_violations.append(f"  {rel}:{line_num}: {line_content}")

    assert len(all_violations) == 0, (
        f"Found hardcoded reference to '{forbidden}' in package '{package}':\n"
        + "\n".join(all_violations)
    )


def test_no_hardcoded_in_context_engine():
    """
    Aggregate test: context_engine must have zero hardcoded source references.
    """
    violations: list[str] = []
    py_files = _get_python_files("context_engine")
    for forbidden in _FORBIDDEN:
        for py_file in py_files:
            matches = _search_forbidden(py_file, forbidden)
            for line_num, line_content in matches:
                rel = py_file.relative_to(_REPO_ROOT)
                violations.append(f"  [{forbidden}] {rel}:{line_num}: {line_content}")

    assert len(violations) == 0, (
        "Hardcoded source references found in context_engine/:\n"
        + "\n".join(violations)
    )


def test_no_hardcoded_in_pb_discovery():
    """
    Aggregate test: pb_discovery must have zero hardcoded source references.
    """
    violations: list[str] = []
    py_files = _get_python_files("pb_discovery")
    for forbidden in _FORBIDDEN:
        for py_file in py_files:
            matches = _search_forbidden(py_file, forbidden)
            for line_num, line_content in matches:
                rel = py_file.relative_to(_REPO_ROOT)
                violations.append(f"  [{forbidden}] {rel}:{line_num}: {line_content}")

    assert len(violations) == 0, (
        "Hardcoded source references found in pb_discovery/:\n"
        + "\n".join(violations)
    )


def test_no_hardcoded_in_interpreter_if_exists():
    """
    If interpreter/ exists, it must have zero hardcoded source references.
    (If it doesn't exist yet, this test passes automatically.)
    """
    package_dir = _REPO_ROOT / "interpreter"
    if not package_dir.exists():
        # Interpreter not built yet — cannot have violations
        return

    violations: list[str] = []
    py_files = _get_python_files("interpreter")
    for forbidden in _FORBIDDEN:
        for py_file in py_files:
            matches = _search_forbidden(py_file, forbidden)
            for line_num, line_content in matches:
                rel = py_file.relative_to(_REPO_ROOT)
                violations.append(f"  [{forbidden}] {rel}:{line_num}: {line_content}")

    assert len(violations) == 0, (
        "Hardcoded source references found in interpreter/:\n"
        + "\n".join(violations)
    )


def test_all_packages_checked():
    """
    Meta-test: ensure we checked all required packages (even if some are missing).
    This documents which packages are in scope.
    """
    checked = []
    for package in _PACKAGES:
        package_dir = _REPO_ROOT / package
        if package_dir.exists():
            checked.append(package)

    # At minimum, context_engine and pb_discovery should exist
    assert "context_engine" in checked, "context_engine package must exist"
    assert "pb_discovery" in checked, "pb_discovery package must exist"
    # interpreter may or may not exist (parallel build) — no assertion here
