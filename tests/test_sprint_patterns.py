"""Roadmap R1.4 — motion background-pattern expansion (sprint registry).

Six new frame-pure SVG background patterns drop into
``remotion/src/compositions/sprint/patterns/`` as their own auto-discovered
files. ``StoryCard.tsx``'s ``bgPatternFor`` switch falls through to
``EXTRA_PATTERNS[style]`` for any token it doesn't handle inline, and
``registry.ts`` enumerates the folder via ``require.context`` at build time —
so a pattern file is live the moment a brief emits its ``background_style``
token, with NO edit to the composition.

These tests pin the drop-in contract at the source level (always run) and,
when a Node toolchain is present, actually execute each pattern and validate
the SVG it emits (self-skips in a Node-less lane, like the browser tests).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.parse
import xml.dom.minidom as minidom
from pathlib import Path

import pytest

from mediahub.visual import motion

_COMP = motion.REMOTION_DIR / "src" / "compositions"
PATTERNS_DIR = _COMP / "sprint" / "patterns"
REGISTRY_TS = _COMP / "sprint" / "registry.ts"
STORYCARD_TSX = _COMP / "StoryCard.tsx"

# The six patterns R1.4 ships. checkerboard/diamonds/circuit/organic-waves are
# named in the roadmap; hexmesh/concentric complete the set of six.
REQUIRED = {"checkerboard", "diamonds", "circuit", "organic-waves", "hexmesh", "concentric"}

# Built-in background_style tokens handled inline in bgPatternFor — a sprint
# pattern must not shadow one (the inline branch always wins, so the file would
# be dead).
BUILTINS = {"dots", "diagonal", "stripes", "geometric", "halftone", "grain",
            "water", "radial", "duotone", "clean"}

# Anything that would make a tile non-deterministic / not frame-pure.
IMPURE = ("Math.random", "performance.now", "useCurrentFrame", "new Date",
          "Date.now", "Date(")


def _pattern_files() -> list[Path]:
    return sorted(PATTERNS_DIR.glob("*.ts"))


def _name_literal(src: str) -> str | None:
    m = re.search(r'name:\s*"([^"]+)"', src)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Folder-level invariants
# ---------------------------------------------------------------------------


def test_patterns_dir_exists():
    assert PATTERNS_DIR.is_dir()


def test_at_least_six_patterns():
    assert len(_pattern_files()) >= 6, "R1.4 ships six new background patterns"


def test_required_patterns_present():
    names = {_name_literal(p.read_text()) for p in _pattern_files()}
    missing = REQUIRED - names
    assert not missing, f"missing R1.4 patterns: {sorted(missing)}"


def test_names_unique_and_match_filenames():
    seen: dict[str, Path] = {}
    for p in _pattern_files():
        name = _name_literal(p.read_text())
        assert name == p.stem, f"{p.name}: name {name!r} != filename stem {p.stem!r}"
        assert name not in seen, f"duplicate pattern name {name!r}"
        seen[name] = p


def test_no_builtin_shadowed():
    for p in _pattern_files():
        assert p.stem not in BUILTINS, (
            f"{p.name} shadows the inline bgPatternFor branch {p.stem!r} (dead file)"
        )


# ---------------------------------------------------------------------------
# Per-file drop-in contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _pattern_files(), ids=lambda p: p.stem)
class TestPatternFileContract:
    def test_default_exports_name_and_pattern(self, path: Path):
        src = path.read_text()
        assert "export default" in src
        assert _name_literal(src), "no string `name:` literal in default export"
        assert "pattern" in src, "no `pattern` member"

    def test_imports_roles_type_from_registry(self, path: Path):
        src = path.read_text()
        assert 'from "../registry"' in src
        assert "Roles" in src

    def test_emits_svg_data_uri(self, path: Path):
        src = path.read_text()
        assert "data:image/svg+xml" in src
        assert "url(" in src
        assert ("encodeURIComponent" in src) or ("base64" in src)

    def test_uses_accent_role(self, path: Path):
        assert "roles.accent" in path.read_text()

    def test_frame_pure(self, path: Path):
        src = path.read_text()
        for token in IMPURE:
            assert token not in src, f"{path.name} is not frame-pure: contains {token!r}"

    def test_no_foreign_hex_only_accent(self, path: Path):
        # Monochrome: the only literal hex allowed is the #FFFFFF accent
        # fallback. Every other colour must come from roles.accent.
        hexes = re.findall(r"#[0-9a-fA-F]{3,8}", path.read_text())
        bad = [h for h in hexes if h.upper() != "#FFFFFF"]
        assert not bad, f"{path.name} hardcodes non-accent colour(s): {bad}"


# ---------------------------------------------------------------------------
# The auto-discovery seam stays wired
# ---------------------------------------------------------------------------


def test_registry_autodiscovers_patterns_folder():
    src = REGISTRY_TS.read_text()
    assert 'require.context("./patterns"' in src
    assert "EXTRA_PATTERNS" in src


def test_storycard_falls_through_to_extra_patterns():
    src = STORYCARD_TSX.read_text()
    assert "EXTRA_PATTERNS[style]" in src, (
        "bgPatternFor must consume the sprint pattern registry"
    )


# ---------------------------------------------------------------------------
# Functional: actually execute each pattern (Node, self-skipping)
# ---------------------------------------------------------------------------

_HARNESS = r"""
import { pathToFileURL } from "node:url";
const files = process.argv.slice(2);
const roles = { ground: "#0A2540", surface: "#101418", accent: "#C9A227", onGround: "#FFFFFF" };
const out = [];
for (const f of files) {
  const mod = await import(pathToFileURL(f).href);
  const def = mod.default;
  if (!def || typeof def.name !== "string" || typeof def.pattern !== "function") {
    throw new Error(`bad default export in ${f}`);
  }
  out.push({ name: def.name, css: def.pattern(roles) });
  // The empty-accent fallback path must resolve to the #FFFFFF default, never throw.
  def.pattern({ ground: "", surface: "", accent: "", onGround: "" });
}
console.log(JSON.stringify(out));
"""


def _ts_runtime_ok(tmp: Path) -> bool:
    """True iff this Node can run a `.ts` module (type-stripping, Node ≥ 22.18).

    Probes with a representative `.ts` file so a genuine pattern failure later
    fails the test rather than silently skipping.
    """
    node = shutil.which("node")
    if not node:
        return False
    probe = tmp / "probe.ts"
    probe.write_text("const x: number = 1;\nexport default x;\n")
    runner = tmp / "probe.mjs"
    runner.write_text(
        'import { pathToFileURL } from "node:url";\n'
        "const m = await import(pathToFileURL(process.argv[2]).href);\n"
        'if (m.default !== 1) throw new Error("bad");\n'
        'console.log("ok");\n'
    )
    try:
        r = subprocess.run(
            [node, str(runner), str(probe)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return False
    return r.returncode == 0 and "ok" in r.stdout


def test_patterns_execute_and_emit_valid_svg(tmp_path: Path):
    node = shutil.which("node")
    if not node or not _ts_runtime_ok(tmp_path):
        pytest.skip("Node TypeScript runtime unavailable (needs Node ≥ 22.18)")

    files = [str(p.resolve()) for p in _pattern_files()]
    runner = tmp_path / "harness.mjs"
    runner.write_text(_HARNESS)
    r = subprocess.run(
        [node, str(runner), *files],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"pattern harness failed:\n{r.stderr}"

    data = json.loads(r.stdout)
    assert {d["name"] for d in data} == {p.stem for p in _pattern_files()}

    prefix = 'url("data:image/svg+xml;utf8,'
    for d in data:
        css = d["css"]
        assert css.startswith(prefix) and css.endswith('")'), (
            f"{d['name']}: not a utf8 SVG data URI: {css[:40]!r}…"
        )
        svg = urllib.parse.unquote(css[len(prefix):-2])
        # Well-formed XML whose root is <svg> — a malformed tile would crash the
        # Chromium background-image decode at render time.
        dom = minidom.parseString(svg)
        assert dom.documentElement.tagName == "svg", d["name"]
        # The resolved accent colour reached the markup (monochrome accent role).
        assert "C9A227" in svg.upper(), f"{d['name']}: accent role not painted"


def test_patterns_typecheck_against_registry():
    """`tsc --noEmit` proves the files satisfy the registry `Roles` contract.

    Self-skips when the remotion toolchain isn't installed (CI's Node-less
    pytest lane), like the renderer tests skip without Chromium.
    """
    tsc = motion.REMOTION_DIR / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        pytest.skip("remotion node_modules/typescript not installed")
    r = subprocess.run(
        [str(tsc), "--noEmit", "-p", "tsconfig.json"],
        cwd=str(motion.REMOTION_DIR), capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, f"tsc failed:\n{r.stdout}\n{r.stderr}"
