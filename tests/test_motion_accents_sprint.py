"""R1.5 — motion accent-decoration expansion (sprint/accents registry).

The story/reel engine lets each accent decoration live as its OWN
auto-discovered file under
``remotion/src/compositions/sprint/accents/<name>.tsx``, registered via a
default-exported ``{ name, decoration }`` and dispatched from
``StoryCard.tsx``'s ``accentDecoration`` *default* case through
``EXTRA_ACCENTS[name]``. ``name`` is the ``accent_style`` brief token.

These tests prove the shipped R1.5 expansion pack end to end without Node:

  * the five sizing variants the roadmap names are present, alongside the
    tasteful extras shipped with them;
  * every file obeys the drop-in contract (imports ``AccentDecoration`` from
    the shared registry, ``const decoration: AccentDecoration = …``,
    default-exports ``{ name, decoration }``, filename == token);
  * names are unique and never shadow a built-in switch case (a shadowed file
    is dead code — the inline ``case`` wins before the default lookup);
  * each decoration is frame-pure + deterministic (no ``Math.random`` /
    ``Date.now`` / CSS animation), draws in the **accent role only**, respects
    the supplied ``opacity``, and stays a ``pointer-events:none`` absolute
    overlay sized relative to the canvas;
  * the registry would actually discover them and ``StoryCard``'s default case
    dispatches to ``EXTRA_ACCENTS`` with the documented signature;
  * the real motion props pipeline forwards each new ``accent_style`` token
    (brief → ``props.accentStyle`` → ``StoryCard`` default → ``EXTRA_ACCENTS``);
  * the parity corpus (``StoryCard`` + ``sprint/**``) contains each token, so
    the motion-parity scan counts every accent as executed.

A final, Node-gated test type-checks the whole Remotion project with ``tsc``
when the toolchain is present, so the TSX is proven to compile too.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion


_COMP = motion.REMOTION_DIR / "src" / "compositions"
ACCENTS_DIR = _COMP / "sprint" / "accents"
STORYCARD = _COMP / "StoryCard.tsx"
REGISTRY = _COMP / "sprint" / "registry.ts"

# The five sizing variants R1.5 names explicitly. Extra accents shipped in the
# same pack are allowed and are validated by the generic contract tests below.
ROADMAP_NAMED = {
    "thick_stripe",
    "thin_stripe",
    "large_brackets",
    "small_brackets",
    "offset_badge",
}


def _accent_files() -> list[Path]:
    return sorted(ACCENTS_DIR.glob("*.tsx"))


def _token_of(path: Path) -> str:
    return path.stem


def _default_export_name(src: str) -> str | None:
    m = re.search(r'export\s+default\s*\{\s*name:\s*"([^"]+)"', src)
    return m.group(1) if m else None


def _builtin_switch_cases() -> set[str]:
    """The ``accent_style`` values ``StoryCard.tsx`` handles inline, before the
    ``default`` branch falls through to the ``EXTRA_ACCENTS`` lookup."""
    src = STORYCARD.read_text()
    start = src.index("function accentDecoration(")
    body = src[start:]
    end = body.index("\nfunction ", 1)  # the next top-level function
    body = body[:end]
    return set(re.findall(r'case\s+"([^"]+)":', body))


def _motion_parity_corpus() -> str:
    """``StoryCard.tsx`` ∪ every sprint-registry module — the same union the
    motion-parity test scans (a registered file is a real execution path)."""
    parts = [STORYCARD.read_text()]
    sprint = _COMP / "sprint"
    parts.extend(
        p.read_text() for p in sorted(sprint.rglob("*")) if p.suffix in {".ts", ".tsx"}
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Presence / naming
# ---------------------------------------------------------------------------


def test_accents_dir_has_readme_and_pack():
    assert (ACCENTS_DIR / "README.md").exists(), "the folder README contract must stay"
    files = _accent_files()
    assert len(files) >= len(ROADMAP_NAMED), "the R1.5 pack should ship the named variants"


def test_roadmap_named_sizing_variants_present():
    tokens = {_token_of(p) for p in _accent_files()}
    missing = ROADMAP_NAMED - tokens
    assert not missing, f"R1.5 named accents missing: {sorted(missing)}"


def test_accent_names_unique():
    names = [_default_export_name(p.read_text()) for p in _accent_files()]
    assert all(names), "every accent must declare a string name"
    assert len(names) == len(set(names)), f"duplicate accent names: {names}"


# ---------------------------------------------------------------------------
# Drop-in contract
# ---------------------------------------------------------------------------


def test_every_accent_obeys_dropin_contract():
    for p in _accent_files():
        src = p.read_text()
        token = _token_of(p)
        # Imports the type from the one shared registry module.
        assert 'from "../registry"' in src, f"{p.name}: must import from ../registry"
        assert re.search(r"import\s+type\s*\{[^}]*AccentDecoration", src), (
            f"{p.name}: must `import type {{ AccentDecoration }}` (isolatedModules-safe)"
        )
        # Defines the decoration with the registry's type.
        assert re.search(r"const\s+decoration\s*:\s*AccentDecoration\s*=", src), (
            f"{p.name}: must define `const decoration: AccentDecoration =`"
        )
        # Default-exports { name, decoration } with name == filename token.
        name = _default_export_name(src)
        assert name == token, (
            f"{p.name}: export name {name!r} must equal the filename token {token!r} "
            f"(the name IS the accent_style brief token)"
        )
        assert re.search(r"export\s+default\s*\{[^}]*\bdecoration\b[^}]*\}", src), (
            f"{p.name}: default export must include `decoration`"
        )


def test_accents_never_shadow_builtins():
    builtins = _builtin_switch_cases()
    # Sanity: the known inline cases are detected, so the shadow check is real.
    assert {"stripe", "brackets", "badge", "frame", "minimal"} <= builtins, builtins
    for p in _accent_files():
        token = _token_of(p)
        assert token not in builtins, (
            f"{p.name}: token {token!r} shadows an inline switch case — the "
            f"built-in wins before the EXTRA_ACCENTS default lookup, so the "
            f"registered file would be dead code"
        )


# ---------------------------------------------------------------------------
# Craft rules: accent-role only, frame-pure, opacity-respecting, overlay-safe
# ---------------------------------------------------------------------------


def test_accents_draw_in_the_accent_role_only():
    for p in _accent_files():
        src = p.read_text()
        assert "roles.accent" in src, f"{p.name}: must paint with the accent role"
        for forbidden in ("roles.ground", "roles.surface", "roles.onGround"):
            assert forbidden not in src, (
                f"{p.name}: accents draw in the accent role only (found {forbidden})"
            )


def test_accents_are_frame_pure_and_deterministic():
    for p in _accent_files():
        src = p.read_text()
        assert "Math.random" not in src, f"{p.name}: no Math.random (determinism)"
        assert "Date.now" not in src, f"{p.name}: no Date.now (determinism)"
        # No CSS-driven motion: a frame-pure accent only renders at the supplied
        # opacity; the composition owns the timeline.
        assert "transition" not in src, f"{p.name}: no CSS transition"
        assert "@keyframes" not in src, f"{p.name}: no CSS keyframes"
        assert "animation" not in src.lower(), f"{p.name}: no CSS animation"


def test_accents_respect_opacity_and_are_overlay_safe():
    for p in _accent_files():
        src = p.read_text()
        assert "opacity" in src, f"{p.name}: must honour the supplied opacity"
        assert "pointerEvents" in src and '"none"' in src, (
            f"{p.name}: an accent overlay must be pointer-events:none"
        )
        assert 'position: "absolute"' in src, f"{p.name}: must be an absolute overlay"


def test_accents_are_canvas_relative():
    # Every decoration receives (roles, opacity, width, height); using width and
    # height is what keeps it correct across story/portrait/square/landscape.
    for p in _accent_files():
        src = p.read_text()
        assert "width" in src and "height" in src, (
            f"{p.name}: should size/position relative to the canvas (width/height)"
        )


# ---------------------------------------------------------------------------
# Registry discovery + StoryCard dispatch
# ---------------------------------------------------------------------------


def test_registry_discovers_accents_by_decoration_key():
    reg = REGISTRY.read_text()
    assert '"./accents"' in reg, "registry must enumerate the accents folder"
    assert r"/\.tsx?$/" in reg, "the discovery regex must match .tsx files"
    assert 'byName<AccentDecoration>(accentMods, "decoration")' in reg, (
        "EXTRA_ACCENTS must key registered modules by name -> decoration"
    )


def test_storycard_default_case_dispatches_to_extra_accents():
    src = STORYCARD.read_text()
    assert "EXTRA_ACCENTS" in src
    assert re.search(r"EXTRA_ACCENTS\[\s*style\s*\]", src), (
        "the default branch must look up the registered decoration by style"
    )
    assert re.search(r"extra\s*\?\s*extra\(roles,\s*opacity,\s*width,\s*height\)", src), (
        "the registered decoration must be called with (roles, opacity, width, height)"
    )


# ---------------------------------------------------------------------------
# End-to-end prop pipeline + parity corpus
# ---------------------------------------------------------------------------


_BRAND = BrandKit(
    profile_id="r15",
    display_name="R1.5 SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="R15",
)


def _card() -> dict:
    return {
        "id": "swim-r15-1",
        "swim_id": "swim-r15-1",
        "achievement": {
            "swim_id": "swim-r15-1",
            "swimmer_name": "Eira Hughes",
            "event_name": "100m Freestyle",
            "result_time": "1:01.00",
        },
    }


def test_motion_props_forward_each_new_accent_token():
    """The real shaping path: a brief carrying ``accent_style=<token>`` reaches
    ``props.accentStyle`` unchanged, where ``StoryCard``'s default case resolves
    it through ``EXTRA_ACCENTS[token]`` to the registered decoration."""
    for p in _accent_files():
        token = _token_of(p)
        props = motion._card_to_props(
            _card(), brief={"accent_style": token}, brand_kit=_BRAND
        )
        assert props["accentStyle"] == token, token


def test_each_accent_token_present_in_parity_corpus():
    corpus = _motion_parity_corpus()
    for p in _accent_files():
        token = _token_of(p)
        assert f'"{token}"' in corpus, f"{token!r} absent from the motion parity corpus"


# ---------------------------------------------------------------------------
# Node-gated: the files actually type-check against the real Remotion/React types
# ---------------------------------------------------------------------------


def _tsc_available() -> bool:
    return shutil.which("npx") is not None and (motion.REMOTION_DIR / "node_modules").is_dir()


@pytest.mark.skipif(not _tsc_available(), reason="node/node_modules not available")
def test_accent_files_typecheck_with_tsc():
    proc = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd=str(motion.REMOTION_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"tsc failed:\n{proc.stdout}\n{proc.stderr}"
