"""varfont-animation — the supporting weight registers (kicker/meta/data) now
animate their variable ``wght`` axis: they enter transiently lighter and BLOOM
up to the still's exact static target over the first ~20% of the beat, then hold
that target. Because the terminal/held value equals the still's static weight,
still↔motion parity is preserved.

Source-contract discipline (the same the rest of the motion suite uses — see
test_per_glyph_text.py): no Node is needed to assert the TSX behaviour, so these
read the composition source and pin the contract:

* the ``wghtFvs`` helper's terminal-parity (bloom≥1 ⇒ exactly the still weight),
  its inactive ``{}`` path (byte-identical when the register is unspent), and its
  deterministic start-weight clamp;
* the shared ``wghtBloomAt`` curve is frame-pure and off frame 0;
* the channel is wired into ``AnimChannels`` and every call site in BOTH
  compositions (StoryCard kicker/meta + sceneKit data);
* the FFmpeg reel manifest reports the axis as static-weight (honest degrade).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTION_SRC = ROOT / "src" / "mediahub" / "remotion" / "src"
STORY_TSX = (REMOTION_SRC / "compositions" / "StoryCard.tsx").read_text()
SCENEKIT_TSX = (REMOTION_SRC / "compositions" / "sprint" / "sceneKit.tsx").read_text()
REEL_FFMPEG = (ROOT / "src" / "mediahub" / "visual" / "reel_ffmpeg.py").read_text()


def _region(src: str, start_marker: str, end_marker: str) -> str:
    """The slice of ``src`` from ``start_marker`` up to the next ``end_marker``."""
    i = src.index(start_marker)
    j = src.index(end_marker, i + len(start_marker))
    return src[i:j]


# --------------------------------------------------------------------------- #
# wghtFvs — the animated variation-settings helper
# --------------------------------------------------------------------------- #


def test_inactive_register_emits_no_variation_settings():
    # A 0 / undefined register (the still did not spend it) omits the setting
    # entirely, so the scene keeps its static fontWeight and renders
    # byte-identically to the pre-animation reel.
    region = _region(STORY_TSX, "export function wghtFvs(", "export function wghtBloomAt(")
    assert "if (!weight || weight <= 0) {" in region
    assert "return {};" in region


def test_terminal_bloom_equals_still_static_weight():
    # At bloom≥1 the helper yields exactly the still's static target:
    #   w = startW + (target - startW) * min(1, max(0, bloom))  →  target
    # This is the still↔motion parity contract — the held weight is the still's.
    region = _region(STORY_TSX, "export function wghtFvs(", "export function wghtBloomAt(")
    assert "const target = Math.round(weight);" in region
    assert (
        "const w = Math.round(startW + (target - startW) * Math.min(1, Math.max(0, bloom)));"
        in region
    )
    assert "return { fontVariationSettings: `'wght' ${w}` };" in region


def test_start_weight_is_a_deterministic_clamp_to_axis_minimum():
    # ADVERSARIAL-VERIFY correction: startW clamps to 100 — the ABSOLUTE minimum
    # of the wght axis, NOT a guaranteed per-face floor. Only the DATA register
    # is pinned to JetBrains Mono (min 100). KICKER/META inherit the card-root
    # fontStack, which can resolve to Space Grotesk (min 300) / Playfair (min
    # 400) / a static face; for those the BROWSER deterministically clamps the
    # axis to the face's own floor (shallower bloom, or a no-op on a static
    # face). The clamp is deterministic and parity-safe — never a random value.
    region = _region(STORY_TSX, "export function wghtFvs(", "export function wghtBloomAt(")
    assert "const startW = Math.max(100, target - 220);" in region
    # The corrected justification must be recorded on the helper's doc comment
    # (not the old false "only Inter/JetBrains, floor is 100" claim).
    assert "the ABSOLUTE minimum of the wght axis" in STORY_TSX
    assert "DETERMINISTICALLY clamps the axis to the face's own floor" in STORY_TSX


def test_wght_bloom_is_frame_pure():
    # The shared bloom curve is a pure function of the frame: interpolate over
    # the off-frame-0 proportional keyframe helper, clamped extrapolation, fixed
    # easing. No live wallclock / RNG (match the CALL forms — the doc comment
    # names them without parens).
    region = _region(STORY_TSX, "export function wghtBloomAt(", "\n}\n")
    assert "const at = (f: number) => 3 + (durationInFrames - 3) * f;" in region
    assert "interpolate(frame, [at(0.0), at(0.2)], [0, 1]" in region
    assert "easing: Easing.out(Easing.cubic)" in region
    assert "Math.random(" not in region
    assert "Date.now(" not in region
    assert "new Date(" not in region


# --------------------------------------------------------------------------- #
# Channel wiring — both compositions route through the shared helper
# --------------------------------------------------------------------------- #


def test_channel_wired_in_both_compositions():
    # AnimChannels carries the channel and `base` computes it once (every intent
    # spreads ...base), the `static` intent holds its terminal value, and the
    # three StoryCard registers pass anim.wghtBloom into wghtFvs.
    assert "wghtBloom: number;" in STORY_TSX
    assert "wghtBloom: wghtBloomAt(frame, durationInFrames)," in STORY_TSX
    assert "wghtBloom: 1," in STORY_TSX  # static intent terminal hold
    assert "wghtFvs(ctx.card.wghtMeta, anim.wghtBloom)" in STORY_TSX
    assert "wghtFvs(ctx.card.wghtKicker, anim.wghtBloom)" in STORY_TSX
    # sceneKit's data chips import and drive the identical curve — no inline
    # static ternary left behind.
    assert 'import { wghtBloomAt, wghtFvs } from "../StoryCard";' in SCENEKIT_TSX
    # Both data-register sites drive the shared curve (prettier may wrap the
    # call, so normalise whitespace before counting).
    compact = " ".join(SCENEKIT_TSX.split())
    assert compact.count("card.wghtData, wghtBloomAt(frame, durationInFrames)") == 2
    assert "wghtFvs(" in compact
    assert "`'wght' ${Math.round(card.wghtData)}`" not in SCENEKIT_TSX


# --------------------------------------------------------------------------- #
# Honest FFmpeg degrade
# --------------------------------------------------------------------------- #


def test_ffmpeg_manifest_reports_static_weight():
    # The free FFmpeg engine bakes the approved still (which already carries the
    # still's static register weight) and cannot animate an axis, so it reports
    # the capability honestly rather than faking the bloom.
    assert '"variable_axes": "static-weight",' in REEL_FFMPEG
