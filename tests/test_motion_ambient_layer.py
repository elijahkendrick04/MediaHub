"""R1.24 — Ambient motion programmes (sprint overlay layer).

The ambient layer is an *additive* Remotion overlay
(``remotion/src/compositions/sprint/layers/ambient.tsx``) that paints one slow,
sustained atmosphere per card — drift / pan / temperature shift / breathing glow
/ deliberate stillness — alive through the BREATHE phase of the clip and faded
to nothing across the build and resolve.

These are source-contract + wiring tests (the established motion-test style — no
Node/Chromium needed): the TSX itself is typechecked by ``tsc`` against the real
Remotion types; here we assert the non-negotiables that keep the overlay honest:

  * it follows the auto-discovered layer drop-in contract (``{ Layer, order }``)
    and is actually mounted by ``StoryCard`` and reused on every reel beat;
  * it is a pure function of the frame — no ``Math.random`` / ``Date.now`` / CSS
    animation / wallclock — and derives every choice from ``variationSeed`` /
    ``mood`` (deterministic re-renders);
  * it is brand-locked — every tint is a resolved colour ROLE, never an invented
    warm/cool hue;
  * it is legible every frame — radial glows only (no banding linear gradient),
    a low capped peak alpha, ``pointer-events:none``, and a low paint ``order``;
  * the atmosphere lands in the breathe window (≈30–70%) and is gone by the
    build and resolve, keyed to ``useVideoConfig().durationInFrames`` so it is
    per-beat inside the reel's ``<Sequence>``.
"""

from __future__ import annotations

import re

import pytest

from mediahub.visual import motion


# ---------------------------------------------------------------------------
# Source access (the same union the parity test scans)
# ---------------------------------------------------------------------------

LAYERS_DIR = (
    motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "layers"
)
AMBIENT = LAYERS_DIR / "ambient.tsx"


@pytest.fixture(scope="module")
def src() -> str:
    assert AMBIENT.is_file(), f"ambient layer missing at {AMBIENT}"
    return AMBIENT.read_text()


def _strip_comments(s: str) -> str:
    """Drop // line and /* */ block comments so the 'banned in code' scans
    judge the executable source, not the prose that documents the rules."""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    s = re.sub(r"//[^\n]*", "", s)
    return s


@pytest.fixture(scope="module")
def code(src: str) -> str:
    return _strip_comments(src)


# ---------------------------------------------------------------------------
# Drop-in contract + discovery wiring
# ---------------------------------------------------------------------------


def test_ambient_follows_the_layer_dropin_contract(src: str):
    # Default-exports exactly { Layer, order } per the registry contract.
    assert re.search(r"export default\s*{\s*Layer\s*,\s*order:", src), (
        "ambient must default-export { Layer, order } (layer drop-in contract)"
    )
    assert re.search(r"const Layer\s*:\s*SceneComponent", src), (
        "Layer must be typed as the registry SceneComponent"
    )
    # Types come from the shared registry, never a forked copy.
    assert 'from "../registry"' in src


def test_layer_order_is_low_background_atmosphere(src: str):
    """Ambient is background atmosphere — it must paint beneath later overlays
    (text effects / captions / animated logo), i.e. a low order."""
    m = re.search(r"order:\s*(\d+)", src)
    assert m, "ambient must declare a numeric paint order"
    assert int(m.group(1)) <= 10, "ambient should sit low in the overlay stack"


def test_registry_auto_discovers_the_layers_folder():
    reg = (
        motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "registry.ts"
    ).read_text()
    assert 'require.context("./layers"' in reg
    assert "EXTRA_LAYERS" in reg


def test_storycard_mounts_extra_layers_in_order():
    story = (
        motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx"
    ).read_text()
    assert "EXTRA_LAYERS" in story
    # Layers paint after the scene, mapped over in registry (order-sorted) order.
    assert re.search(r"EXTRA_LAYERS\.map\(", story)


def test_reel_beats_reuse_storycard_so_ambient_rides_every_beat():
    """Each reel card beat renders <StoryCard> inside a <Sequence>, so the
    ambient overlay (and its breathe window) applies per beat, not once."""
    reel = (
        motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx"
    ).read_text()
    assert "<StoryCard" in reel
    assert "<Sequence" in reel


def test_ambient_is_in_the_parity_source_corpus():
    """The motion-parity drift guard scans sprint/**; the new layer must be in
    that union so it counts as executed motion."""
    import tests.test_motion_v2_parity as parity

    corpus = parity._motion_source_corpus()
    assert "R1.24" in corpus
    assert "AMBIENT_PROGRAMMES" in corpus


# ---------------------------------------------------------------------------
# Pure function of the frame / determinism (CLAUDE.md + motion-craft hard bounds)
# ---------------------------------------------------------------------------


def test_ambient_is_a_pure_function_of_the_frame(code: str):
    banned = [
        ("Math.random", "non-deterministic randomness"),
        ("Date.now", "wallclock"),
        ("performance.now", "wallclock"),
        ("requestAnimationFrame", "rAF loop"),
        ("setTimeout", "timer"),
        ("setInterval", "timer"),
        ("useState", "stateful motion"),
        ("useEffect", "effect-driven motion"),
        ("@keyframes", "CSS animation"),
        ("animation:", "CSS animation shorthand"),
        ("transition:", "CSS transition"),
    ]
    for needle, why in banned:
        assert needle not in code, f"ambient must not use {needle} ({why})"


def test_ambient_drives_time_from_frame_and_video_config(src: str):
    # Time comes from the frame + the (Sequence-scoped) video config only.
    assert "useVideoConfig()" in src
    assert "ctx.frame" in src or re.search(r"const\s*{\s*frame", src)
    # Frame-derived oscillation, not a CSS/JS loop.
    assert "Math.sin(" in src
    assert "interpolate(" in src


def test_ambient_variation_is_seeded_not_random(src: str):
    assert "variationSeed" in src, "per-card variety must derive from the seed"
    # The programme is chosen by the seed (deterministic), with a seeded phase.
    assert re.search(r"%\s*AMBIENT_PROGRAMMES\.length", src)


# ---------------------------------------------------------------------------
# Brand-locked colour (roles only — never an invented warm/cool hue)
# ---------------------------------------------------------------------------


def test_ambient_tints_come_only_from_resolved_roles(src: str):
    # Every glow colour is a role channel.
    assert re.search(r"roles\.(accent|surface|ground|onGround)", src)
    # "Temperature" is a crossfade between two brand roles, not a fake hue.
    assert "roles.accent" in src and "roles.surface" in src


def test_ambient_invents_no_brand_hue(code: str):
    """The only hex literal allowed is the safe untinted fallback (#FFFFFF) in
    the alpha helper — never a hardcoded warm/cool/brand colour."""
    hexes = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", code))
    assert hexes <= {"#FFFFFF"}, f"unexpected hardcoded colour(s): {hexes}"
    # No literal warm/cool colour names leaking in as CSS keywords either.
    for kw in ("orange", "warmwhite", "skyblue", "rgb(", "rgba(", "hsl("):
        assert kw not in code.lower()


# ---------------------------------------------------------------------------
# Legible every frame (low alpha, radial only, pointer-events none)
# ---------------------------------------------------------------------------


def test_ambient_peak_alpha_is_capped_low(src: str):
    m = re.search(r"PEAK_ALPHA\s*=\s*([0-9.]+)", src)
    assert m, "ambient must declare a PEAK_ALPHA ceiling"
    peak = float(m.group(1))
    assert 0 < peak <= 0.12, (
        f"peak alpha {peak} too high — the wash must not break text contrast"
    )


def test_ambient_uses_radial_glows_not_banding_linear_gradients(src: str):
    assert "radial-gradient(" in src
    assert "linear-gradient(" not in src, (
        "no full-frame linear gradient — it bands on dark grounds under H.264"
    )


def test_ambient_is_non_interactive_and_clipped(src: str):
    assert 'pointerEvents: "none"' in src
    assert 'overflow: "hidden"' in src


# ---------------------------------------------------------------------------
# Breathe-phase sustain (≈30–70%, gone by build & resolve)
# ---------------------------------------------------------------------------


def test_ambient_envelope_is_keyed_to_clip_duration(src: str):
    # The envelope is built from durationInFrames fractions (per-beat under a
    # Sequence), not a hardcoded frame count.
    assert "durationInFrames" in src
    fracs = re.findall(r"d\s*\*\s*0\.(\d+)", src)
    assert fracs, "envelope must scale with the clip duration"


def test_ambient_is_silent_outside_its_window(src: str):
    """Nothing during the build (no frame-0 jump) and nothing through the
    resolve (clean transition/outro): the layer returns null when the envelope
    is zero."""
    assert re.search(r"if\s*\(\s*env\s*<=\s*0\s*\)\s*{\s*\n?\s*return null", src)


def test_breathe_window_brackets_thirty_to_seventy_percent(src: str):
    """The full-strength plateau must sit inside the breathe phase — ramp in by
    ~32% and start ramping out by ~70%."""
    m = re.search(
        r"\[\s*d\s*\*\s*([0-9.]+),\s*d\s*\*\s*([0-9.]+),\s*d\s*\*\s*([0-9.]+),\s*d\s*\*\s*([0-9.]+)\s*\]",
        src,
    )
    assert m, "envelope must declare its four duration-fraction stops"
    a, b, c, dd = (float(x) for x in m.groups())
    assert a < b < c < dd, "envelope stops must be monotonic"
    assert b <= 0.35, "ambient must reach full strength by ~the start of breathe"
    assert c >= 0.65, "ambient must hold through ~the end of breathe"
    assert dd <= 0.9, "ambient must be gone before the very end (clean resolve)"


# ---------------------------------------------------------------------------
# Programme set — drift / pan / temperature / breathe / stillness
# ---------------------------------------------------------------------------


def test_ambient_declares_the_full_programme_vocabulary(src: str):
    for prog in ("drift", "pan", "temperature", "breathe", "still"):
        assert f'"{prog}"' in src, f"missing ambient programme {prog!r}"


def test_ambient_includes_deliberate_stillness(src: str):
    """'Sometimes stillness' (motion-craft): a static motion intent forces the
    still programme rather than drifting."""
    assert re.search(r'motionIntent[^\n]*===\s*"static"', src)
    assert '"still"' in src


def test_ambient_mood_scales_energy_within_the_house_scale(src: str):
    """Mood flavours speed/amplitude on the same calm↔electric scale the spring
    table uses — not a parallel mechanism."""
    assert "ambientEnergy" in src
    assert re.search(r"calm|minimal|stoic", src)
    assert re.search(r"electric|explosive|fierce", src)
