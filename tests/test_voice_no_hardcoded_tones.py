"""
tests_v75/test_voice_no_hardcoded_tones.py

Critical constraint check: voice/learned/*.py MUST NOT contain the literal
slug strings "warm-club", "hype", or "data-led".

Those slugs are data — they exist only inside the seed JSON files under
data/voices/seed/.  The engine code must be agnostic to any specific
named voice.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# In V9 the voice package lives under src/mediahub/voice/learned/.
_LEARNED_DIR = _PROJECT_ROOT / "src" / "mediahub" / "voice" / "learned"
if not _LEARNED_DIR.exists():
    _LEARNED_DIR = _PROJECT_ROOT / "voice" / "learned"

# The forbidden slug literals — exactly as they appear in the V7.4 hardcoded tones
_FORBIDDEN_SLUGS = [
    "warm-club",
    "hype",
    "data-led",
]

# We allow these strings ONLY inside seed JSON files; not in .py source files.
_PYTHON_FILES = list(_LEARNED_DIR.glob("*.py"))


def _search_file(path: Path, slug: str) -> list[int]:
    """Return list of line numbers containing the slug."""
    lines_with_matches = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if slug in line:
            lines_with_matches.append(lineno)
    return lines_with_matches


# ---------------------------------------------------------------------------
# Parameterised test — one check per (file, slug) combination
# ---------------------------------------------------------------------------

# Build param list: (py_file, slug)
_params = [
    pytest.param(py_file, slug, id=f"{py_file.name}::{slug!r}")
    for py_file in sorted(_PYTHON_FILES)
    for slug in _FORBIDDEN_SLUGS
]


@pytest.mark.parametrize("py_file,slug", _params)
def test_no_hardcoded_tone_slug_in_python(py_file: Path, slug: str):
    """
    Assert that the given slug does not appear anywhere in the given
    voice/learned/*.py source file.
    """
    matches = _search_file(py_file, slug)
    assert matches == [], (
        f"Found forbidden tone slug {slug!r} at line(s) {matches} in {py_file.name}.\n"
        f"Tone slugs are data — they must only appear in seed JSON files, "
        f"not in engine source code."
    )


# ---------------------------------------------------------------------------
# Aggregate test — convenience single-assertion version
# ---------------------------------------------------------------------------

class TestNoHardcodedTones:
    def test_python_files_exist(self):
        """Sanity check: voice/learned/ must contain at least the four expected files."""
        names = {f.name for f in _PYTHON_FILES}
        for expected in ("__init__.py", "feature_extract.py", "induce.py",
                         "store.py", "render.py"):
            assert expected in names, f"Expected {expected} in voice/learned/ but not found"

    def test_aggregate_zero_matches(self):
        """
        One comprehensive assertion: no forbidden slug appears in any
        voice/learned/*.py file.
        """
        violations: list[str] = []
        for py_file in sorted(_PYTHON_FILES):
            for slug in _FORBIDDEN_SLUGS:
                matches = _search_file(py_file, slug)
                for lineno in matches:
                    violations.append(f"{py_file.name}:{lineno}: {slug!r}")

        assert violations == [], (
            "Hardcoded tone slugs found in voice/learned/*.py:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_seed_files_contain_slugs(self):
        """
        Inverse check: the seed JSON files SHOULD contain these identifiers
        (they are data).  This confirms we are not accidentally over-purging.
        """
        seed_dir = _PROJECT_ROOT / "data" / "voices" / "seed"
        assert seed_dir.is_dir(), f"Seed directory not found: {seed_dir}"

        seed_files = list(seed_dir.glob("*.json"))
        assert len(seed_files) >= 3, "Expected at least 3 seed JSON files"

        # Each seed file should contain its own voice_id
        expected_ids = {"warm_club", "hype", "data_led"}
        found_ids = set()
        for f in seed_files:
            text = f.read_text(encoding="utf-8")
            import json
            data = json.loads(text)
            found_ids.add(data.get("voice_id", ""))

        for vid in expected_ids:
            assert vid in found_ids, f"Seed voice_id {vid!r} not found in seed files"

    def test_models_file_no_hardcoded_tones(self):
        """models.py must not reference specific named voices either."""
        models_file = _LEARNED_DIR / "models.py"
        assert models_file.exists(), "voice/learned/models.py not found"
        for slug in _FORBIDDEN_SLUGS:
            matches = _search_file(models_file, slug)
            assert matches == [], (
                f"models.py contains forbidden slug {slug!r} at lines {matches}"
            )
