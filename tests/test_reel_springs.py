"""R1.26 — Easing-curve customisation + expanded mood → spring vocabulary.

A Remotion spring's ``{ damping, stiffness, mass }`` *is* its easing curve:
damping governs overshoot, stiffness governs speed/aggression, mass governs
inertia/weight. R1.26 ships one tuned easing curve per mood as its own
auto-discovered file under ``sprint/springs/<mood>.ts`` (the registry's
``EXTRA_SPRINGS``), with NO edit to ``StoryCard.tsx``'s ``springConfigFor``.

These tests are the drift guard for that seam. They prove:

  * every shipped spring file is well-formed and on the documented contract
    (``{ name, config }`` with three numeric fields, name == filename stem);
  * the easing curves are genuinely customised — pairwise distinct and never a
    copy of the neutral default;
  * the vocabulary actually expanded: every mood the director can emit today
    (``design_spec.MOODS``) resolves to an *intentional* curve (a built-in
    cluster, a dedicated file, or the explicit ``neutral`` baseline), and the
    roadmap-named new moods each have a file;
  * the folder carries no inert/dead files (a mood a built-in already wins);
  * the consumer wiring (registry ``EXTRA_SPRINGS`` + StoryCard lookup *after*
    the built-ins) is intact, so built-ins still win;
  * the ``.ts`` files compile under the project's strict tsconfig (Node-gated;
    skipped where the Remotion toolchain is absent).

No Node is needed for the contract tests — they read the TS as source text,
matching the repo's existing motion-parity idiom.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mediahub.creative_brief import design_spec as ds
from mediahub.visual import motion

# --- the seam under test --------------------------------------------------

SPRINGS_DIR = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "springs"
STORYCARD = motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx"
REGISTRY = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "registry.ts"

# Moods the director already emits (design_spec.MOODS) that the built-in
# springConfigFor does NOT recognise — so they fell through to the bare default
# until R1.26 gave each its own easing curve. These ship as live files.
EXPECTED_LIVE_MOODS = {"explosive", "fierce", "stoic", "precise", "warm", "minimal"}

# The roadmap-named vocabulary expansion (forward-looking; resolved the moment
# the director emits one — the springs registry exists for exactly this).
ROADMAP_NEW_MOODS = {"melancholic", "energetic", "victorious", "contemplative"}

ALL_EXPECTED_MOODS = EXPECTED_LIVE_MOODS | ROADMAP_NEW_MOODS

# Built-in mood-keyword clusters in StoryCard.springConfigFor — these always
# win, so a sprint file named for one of them would be inert (dead code).
BUILTIN_MOOD_KEYWORDS = (
    "calm", "weighty", "composed",
    "electric", "snappy", "kinetic",
    "celebratory", "bold", "triumph",
)

# The neutral baseline returned by springConfigFor's final fallback. A shipped
# easing curve identical to this would be a non-customisation.
DEFAULT_SPRING = (18.0, 90.0, 0.7)

# Generous physical bounds: comfortably contain the built-ins and the shipped
# curves while still catching a typo'd / nonsensical value.
DAMPING_RANGE = (5.0, 50.0)
STIFFNESS_RANGE = (30.0, 260.0)
MASS_RANGE = (0.3, 2.0)


# --- helpers --------------------------------------------------------------

def _spring_files() -> list[Path]:
    return sorted(p for p in SPRINGS_DIR.glob("*.ts"))


def _parse_spring(path: Path) -> tuple[str, tuple[float, float, float]]:
    """Extract (name, (damping, stiffness, mass)) from a spring module."""
    src = path.read_text()
    name_m = re.search(r'export\s+default\s*\{\s*name:\s*"([^"]+)"', src)
    assert name_m, f"{path.name}: no `export default {{ name: \"…\" }}`"
    def field(key: str) -> float:
        m = re.search(rf"\b{key}:\s*(-?[0-9]+(?:\.[0-9]+)?)", src)
        assert m, f"{path.name}: spring config missing numeric `{key}`"
        return float(m.group(1))
    return name_m.group(1), (field("damping"), field("stiffness"), field("mass"))


def _spring_map() -> dict[str, tuple[float, float, float]]:
    return {name: cfg for name, cfg in (_parse_spring(p) for p in _spring_files())}


def _builtin_catches(mood: str) -> bool:
    return any(kw in mood for kw in BUILTIN_MOOD_KEYWORDS)


# --- tests ----------------------------------------------------------------

def test_springs_dir_exists():
    assert SPRINGS_DIR.is_dir(), f"missing springs registry folder: {SPRINGS_DIR}"


def test_all_expected_mood_files_present():
    names = set(_spring_map())
    missing = sorted(ALL_EXPECTED_MOODS - names)
    assert not missing, f"R1.26 spring files not shipped: {missing}"


def test_each_spring_file_well_formed():
    for path in _spring_files():
        src = path.read_text()
        name, (damping, stiffness, mass) = _parse_spring(path)
        # name is the lowercased mood token and equals the filename stem
        assert re.fullmatch(r"[a-z]+", name), f"{path.name}: name {name!r} not a lowercase token"
        assert name == path.stem, f"{path.name}: name {name!r} != filename stem {path.stem!r}"
        # imports the shared SpringConfig type from the registry, one level up
        assert 'from "../registry"' in src, f"{path.name}: must import from ../registry"
        assert "SpringConfig" in src, f"{path.name}: must type config as SpringConfig"
        # all three numeric channels parsed
        for label, val in (("damping", damping), ("stiffness", stiffness), ("mass", mass)):
            assert isinstance(val, float), f"{path.name}: {label} not numeric"


def test_spring_values_in_sane_range():
    for name, (damping, stiffness, mass) in _spring_map().items():
        assert DAMPING_RANGE[0] <= damping <= DAMPING_RANGE[1], f"{name}: damping {damping} out of range"
        assert STIFFNESS_RANGE[0] <= stiffness <= STIFFNESS_RANGE[1], f"{name}: stiffness {stiffness} out of range"
        assert MASS_RANGE[0] <= mass <= MASS_RANGE[1], f"{name}: mass {mass} out of range"


def test_roadmap_named_moods_present():
    """The roadmap explicitly names these as the vocabulary to expand to."""
    names = set(_spring_map())
    missing = sorted(ROADMAP_NEW_MOODS - names)
    assert not missing, f"roadmap-named moods without a spring file: {missing}"


def test_currently_unsprung_director_moods_now_have_springs():
    """Every mood the director emits today that the built-ins ignored now has a
    dedicated easing curve — this is the live half of the expansion."""
    # keep the expectation honest against the real Python vocabulary
    assert EXPECTED_LIVE_MOODS <= set(ds.MOODS), (
        "EXPECTED_LIVE_MOODS drifted from design_spec.MOODS: "
        f"{sorted(EXPECTED_LIVE_MOODS - set(ds.MOODS))}"
    )
    # and they must genuinely be moods the built-ins do NOT already catch
    for mood in EXPECTED_LIVE_MOODS:
        assert not _builtin_catches(mood), f"{mood!r} is already a built-in cluster — file would be inert"
    names = set(_spring_map())
    missing = sorted(EXPECTED_LIVE_MOODS - names)
    assert not missing, f"director moods still on the bare default spring: {missing}"


def test_every_director_mood_resolves_to_an_intentional_spring():
    """No mood the director can emit animates with an *accidental* curve: each is
    either caught by a built-in cluster, has a dedicated file, or is the explicit
    `neutral` baseline."""
    names = set(_spring_map())
    for mood in ds.MOODS:
        m = mood.lower()
        resolved = (m == "neutral") or _builtin_catches(m) or (m in names)
        assert resolved, f"mood {mood!r} has no intentional spring (built-in/file/neutral)"


def test_builtin_keywords_still_present_in_storycard():
    """Drift guard: the keyword clusters this test relies on must still exist in
    springConfigFor (otherwise the 'built-ins win' reasoning is stale)."""
    src = STORYCARD.read_text()
    for kw in BUILTIN_MOOD_KEYWORDS:
        assert f'"{kw}"' in src or f"'{kw}'" in src or kw in src, (
            f"built-in mood keyword {kw!r} no longer in StoryCard.springConfigFor"
        )


def test_no_inert_spring_files():
    """The folder must carry no dead files — a mood a built-in already wins."""
    for name in _spring_map():
        assert not _builtin_catches(name), (
            f"spring file {name!r} duplicates a built-in cluster (built-ins win → inert)"
        )


def test_spring_curves_are_distinct_and_customised():
    """Each easing curve is a real customisation: pairwise distinct and never a
    copy of the neutral default."""
    cfgs = _spring_map()
    for name, cfg in cfgs.items():
        assert cfg != DEFAULT_SPRING, f"{name}: identical to the neutral default — not customised"
    seen: dict[tuple[float, float, float], str] = {}
    for name, cfg in cfgs.items():
        clash = seen.get(cfg)
        assert clash is None, f"{name} and {clash} share an identical spring {cfg}"
        seen[cfg] = name


def test_registry_consumes_springs_contract():
    """The auto-discovery consumer is intact: EXTRA_SPRINGS, the three-field
    SpringConfig, and the ./springs require.context."""
    src = REGISTRY.read_text()
    assert "EXTRA_SPRINGS" in src, "registry no longer exports EXTRA_SPRINGS"
    assert 'require.context("./springs"' in src, "registry no longer enumerates ./springs"
    for field in ("damping", "stiffness", "mass"):
        assert field in src, f"SpringConfig contract lost field {field!r}"


def test_storycard_resolves_extra_springs_after_builtins():
    """springConfigFor must consult EXTRA_SPRINGS only AFTER the built-in
    clusters, so the README promise 'built-ins always win' holds — and the seam
    is wired with no StoryCard edit required by R1.26."""
    src = STORYCARD.read_text()
    assert "EXTRA_SPRINGS" in src, "StoryCard no longer imports/uses EXTRA_SPRINGS"
    extra_at = src.index("EXTRA_SPRINGS[")
    # a built-in cluster check must appear before the extra lookup
    calm_at = src.index('"calm"')
    assert calm_at < extra_at, "EXTRA_SPRINGS is consulted before the built-in moods — built-ins must win"


@pytest.mark.skipif(
    shutil.which("npx") is None or not (motion.REMOTION_DIR / "node_modules").is_dir(),
    reason="Remotion toolchain (npx + node_modules) not available in this environment",
)
def test_spring_files_typecheck_under_strict_tsconfig():
    """The shipped .ts compile under the project's strict tsconfig (noEmit)."""
    proc = subprocess.run(
        ["npx", "tsc", "--noEmit", "-p", "tsconfig.json"],
        cwd=motion.REMOTION_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, f"tsc failed:\n{proc.stdout}\n{proc.stderr}"
