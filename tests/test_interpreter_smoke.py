"""
test_interpreter_smoke.py — V7.5 interpreter smoke tests.

Three synthetic mini-document fixtures (different layouts) are tested:

  Fixture A — Plain-text tabular layout (column-aligned, space-separated)
  Fixture B — HTML with <table> structure
  Fixture C — CSV-like plain text (comma-separated) with multi-event headers

Each fixture must parse with overall_confidence >= 0.7.

The grep test verifies that no swim-vocabulary literals exist inside any
interpreter/*.py source file.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Path setup — ensure the swim-content project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mediahub.interpreter import interpret_document  # noqa: E402
from mediahub.interpreter.schema_dataclasses import InterpretedMeet  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: make a set of overriding paths so tests use the real ontology/patterns
# ---------------------------------------------------------------------------

ONTOLOGY_ROOT = PROJECT_ROOT / "data" / "ontology"
PATTERNS_PATH = PROJECT_ROOT / "data" / "patterns.jsonl"


def _call(raw: bytes, hint: str) -> InterpretedMeet:
    return interpret_document(
        raw,
        hint=hint,
        ontology_root=ONTOLOGY_ROOT,
        patterns_path=PATTERNS_PATH,
    )


# ===========================================================================
# Fixture A — Plain-text tabular layout
# ===========================================================================

FIXTURE_A_TEXT = textwrap.dedent("""\
    Spring Invitational Championship 2024
    Aquatic Centre, Springfield
    15/03/2024 - 16/03/2024
    LC

    Event 1 - Female 50m Freestyle
    Pos  Name                YoB   Club    Time    RT
    1    Smith Jane          2006  SPAC    27.31   0.63
    2    Johnson Emily       2005  RIVR    27.89   0.71
    3    Williams Sarah      2007  AQUA    28.12   0.68

    Event 2 - Male 100m Backstroke
    Pos  Name                YoB   Club    Time
    1    Brown Thomas        2004  SPAC    58.41
    2    Davis Michael       2003  RIVR    59.17
    3    Wilson Robert       2005  AQUA    1:00.34
""").encode("utf-8")


def test_fixture_a_plain_text():
    """Fixture A: plain-text table with column headers."""
    result = _call(FIXTURE_A_TEXT, hint="text")

    assert isinstance(result, InterpretedMeet), "Must return InterpretedMeet"
    assert result.overall_confidence >= 0.7, (
        f"Expected overall_confidence >= 0.7, got {result.overall_confidence:.4f}"
    )
    # Basic sanity on events
    assert len(result.events) >= 1, "Must detect at least one event"
    # Swims present in at least one event
    total_swims = sum(len(ev.swims) for ev in result.events)
    assert total_swims >= 1, "Must extract at least one swim"


# ===========================================================================
# Fixture B — HTML <table> layout
# ===========================================================================

FIXTURE_B_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html>
    <head><title>Regional Open Meet Results</title></head>
    <body>
    <h1>Regional Open Meet 2024</h1>
    <p>Venue: Riverside Leisure Centre | Date: 22/04/2024 | SC</p>

    <h2>Event 3 - Female 200m Individual Medley Open</h2>
    <table>
      <thead>
        <tr><th>Place</th><th>Name</th><th>YoB</th><th>Club</th><th>Time</th><th>Reaction</th></tr>
      </thead>
      <tbody>
        <tr><td>1</td><td>Adams Claire</td><td>2003</td><td>RIVR</td><td>2:18.45</td><td>0.72</td></tr>
        <tr><td>2</td><td>Baker Fiona</td><td>2004</td><td>COSC</td><td>2:21.11</td><td>0.65</td></tr>
        <tr><td>3</td><td>Carter Grace</td><td>2002</td><td>NWSC</td><td>2:23.78</td><td>0.69</td></tr>
      </tbody>
    </table>

    <h2>Event 4 - Male 400m Freestyle Open</h2>
    <table>
      <thead>
        <tr><th>Place</th><th>Name</th><th>YoB</th><th>Club</th><th>Time</th></tr>
      </thead>
      <tbody>
        <tr><td>1</td><td>Dawson Harry</td><td>2001</td><td>NWSC</td><td>3:58.22</td></tr>
        <tr><td>2</td><td>Evans Ian</td><td>2000</td><td>RIVR</td><td>4:02.88</td></tr>
      </tbody>
    </table>
    </body>
    </html>
""").encode("utf-8")


def test_fixture_b_html():
    """Fixture B: HTML with explicit <table> structure."""
    result = _call(FIXTURE_B_HTML, hint="html")

    assert isinstance(result, InterpretedMeet), "Must return InterpretedMeet"
    assert result.overall_confidence >= 0.7, (
        f"Expected overall_confidence >= 0.7, got {result.overall_confidence:.4f}"
    )
    assert len(result.events) >= 1, "Must detect at least one event"
    total_swims = sum(len(ev.swims) for ev in result.events)
    assert total_swims >= 1, "Must extract at least one swim"


# ===========================================================================
# Fixture C — Multi-event, mixed-width column plain text (different layout)
# ===========================================================================

FIXTURE_C_TEXT = textwrap.dedent("""\
    National Junior Championship 2024 — Results
    National Aquatic Centre
    10/06/2024
    Long Course Meters

    Event 5  Boys 100m Butterfly  Under 16
    Rank  Competitor              Born  Team   Mark     RT
    1     Parker Oliver           2008  NATL   54.32    0.58
    2     Quinn Noah              2009  CENT   55.18    0.61
    3     Reed Samuel             2008  WEST   56.04    0.70
    DQ    Thompson Liam           2009  EAST   DNS

    Event 6  Girls 200m Breaststroke  Senior
    Rank  Competitor              Born  Team   Mark
    1     Underwood Mia           2002  NATL   2:28.15
    2     Vance Lucy              2001  EAST   2:31.44
    3     Watson Ella             2003  WEST   2:34.99
""").encode("utf-8")


def test_fixture_c_plain_text_variant():
    """Fixture C: plain text with 'Rank/Competitor/Born/Team/Mark' headers."""
    result = _call(FIXTURE_C_TEXT, hint="text")

    assert isinstance(result, InterpretedMeet), "Must return InterpretedMeet"
    assert result.overall_confidence >= 0.7, (
        f"Expected overall_confidence >= 0.7, got {result.overall_confidence:.4f}"
    )
    assert len(result.events) >= 1, "Must detect at least one event"
    total_swims = sum(len(ev.swims) for ev in result.events)
    assert total_swims >= 1, "Must extract at least one swim"


# ===========================================================================
# Grep test: no swim-vocabulary literals in interpreter/*.py
# ===========================================================================

# These are the canonical swim-vocabulary terms that must NOT appear as string
# literals inside interpreter/*.py files.  They live only in data/ontology/*.json.
FORBIDDEN_VOCAB = [
    # Stroke names (canonical and common aliases)
    r"\bFreestyle\b",
    r"\bBackstroke\b",
    r"\bBreaststroke\b",
    r"\bButterfly\b",
    r"\bIndividual Medley\b",
    r"\bBFLY\b",
    r"\bFREESTYLE\b",
    r"\bBACKSTROKE\b",
    r"\bBREASTSTROKE\b",
    r"\bBUTTERFLY\b",
    # Course aliases
    r"\bLCM\b",
    r"\bLong Course\b",
    r"\bSCM\b",
    r"\bShort Course\b",
    # Governing-body names
    r"\bSwim England\b",
    r"\bFINA\b",
    r"\bWorld Aquatics\b",
    # Level descriptors from ontology
    r"\bnational\b",
    r"\bregional\b",
    r"\bclub level\b",
]

INTERPRETER_DIR = PROJECT_ROOT / "src" / "mediahub" / "interpreter"


def _get_interpreter_py_files() -> list[pathlib.Path]:
    return sorted(INTERPRETER_DIR.glob("*.py"))


def test_grep_no_swim_vocabulary_in_interpreter():
    """
    Verify that swim-vocabulary literals are NOT hardcoded in interpreter/*.py.

    This test uses a regex grep over the source files.  Any match means the
    vocabulary has leaked out of data/ontology/ and into the Python code.
    """
    py_files = _get_interpreter_py_files()
    assert py_files, f"No .py files found under {INTERPRETER_DIR}"

    violations: list[str] = []

    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        # Strip comments and docstrings for the check — we only care about
        # string literals in executable code.  A simple heuristic: check
        # each non-comment, non-blank line.
        for lineno, raw_line in enumerate(source.splitlines(), 1):
            # Strip inline comments
            code_part = raw_line.split("#")[0]
            # Skip docstring-like lines (triple-quoted) — allowed in tests only
            stripped = code_part.strip()
            # Skip lines that are part of docstrings (crude but effective)
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if stripped.startswith('r"""') or stripped.startswith("r'''"):
                continue

            for vocab_pattern in FORBIDDEN_VOCAB:
                if re.search(vocab_pattern, code_part, re.IGNORECASE):
                    violations.append(
                        f"{py_file.name}:{lineno}: matched {vocab_pattern!r} in: {raw_line.rstrip()!r}"
                    )

    if violations:
        msg = (
            "Swim-vocabulary literals found in interpreter/*.py files.\n"
            "Move them to data/ontology/*.json instead.\n\n"
            + "\n".join(violations[:30])  # show first 30
        )
        pytest.fail(msg)


# ===========================================================================
# Additional: image input graceful degradation
# ===========================================================================

def test_image_input_graceful_degradation():
    """Image bytes without OCR available should return confidence=0 and needs_review."""
    # Use a tiny fake PNG header
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    result = _call(fake_png, hint="png")

    assert isinstance(result, InterpretedMeet)
    assert result.overall_confidence == 0.0
    assert any("ocr" in str(nr).lower() for nr in result.needs_review), (
        "Image input should produce a needs_review entry mentioning OCR"
    )


# ===========================================================================
# Additional: empty / minimal input does not raise
# ===========================================================================

def test_empty_input_does_not_raise():
    """Empty bytes should not raise an exception."""
    result = _call(b"", hint="text")
    assert isinstance(result, InterpretedMeet)


def test_hy3_like_input():
    """hy3-format input is accepted and produces a result without crashing."""
    hy3_bytes = (
        b"A1Springfield Aquatic Club           SC                   "
        b"20240315                \r\n"
        b"B1Event 1   F  050 FR LC             \r\n"
        b"D0  1Smith         Jane          F20060124SPAC  2731  0063\r\n"
    )
    result = _call(hy3_bytes, hint="hy3")
    assert isinstance(result, InterpretedMeet)
