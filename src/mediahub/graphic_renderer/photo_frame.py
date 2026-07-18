"""E4 (Canva gap analysis) — deterministic photo-frame shapes for the
windowed-photo archetypes.

Canva made *frames* a first-class element because a shaped photo reads
"designed" where a raw rectangle reads "generated": the arch is editorial, the
organic blob hides an imperfect crop, and a torn edge reads as scrapbook
collage. This module is the pure-maths half of the ``photo_frame_shape`` lever:
it turns a card key + shape token into the exact CSS/SVG geometry the renderer
paints, so the same brief + seed always yields the same PNG.

Nothing here carries brand colour — the shapes are pure geometry. The renderer
fills them with the card's resolved ``--mh-*`` role tokens (the offset accent
echo is ``var(--mh-accent)``; the no-photo surface is ``var(--mh-surface)``),
so brand-lock and APCA gating hold on the still side. ``rect`` (and any absent
lever) produces nothing, keeping legacy briefs byte-identical.

The three shapes:

* ``arch``      — a fixed border-radius (rounded top, flat bottom): the museum
  print / editorial portal. No seed (every arch is the same clean curve).
* ``blob``      — an 8-value border-radius, every value jittered deterministically
  in 35–65 % from ``sha256(card_key|'blob')``. Each card gets its own organic
  silhouette; the same card re-renders identically.
* ``torn_edge`` — an SVG ``feTurbulence`` + ``feDisplacementMap`` filter (the same
  zero-size def-injection path ``render._duotone_defs_svg`` uses), seeded from
  ``sha256(card_key|'frame_torn')`` so the tear pattern is stable per card.
"""

from __future__ import annotations

import hashlib

# The closed vocabulary of frame shapes. ``rect`` is the no-op default (a raw
# rectangular window — byte-identical to the pre-lever render). Kept identical to
# ``creative_brief.design_spec.PHOTO_FRAME_SHAPES`` by ``tests/test_photo_frame.py``.
PHOTO_FRAME_SHAPES: tuple[str, ...] = ("rect", "arch", "blob", "torn_edge")

# The fixed arch curve: a strong rounded top, a flat bottom (elliptical radii so
# the arch keeps its shape on tall AND wide windows). Deterministic — no seed.
_ARCH_RADIUS = "50% 50% 0 0 / 34% 34% 0 0"

# The stable SVG filter id the torn-edge def exposes; referenced from the
# window's CSS ``filter: url(#mh-frame-torn)``. One card renders as its own HTML
# page, so a fixed id (like ``mh-duotone``) never collides.
TORN_FILTER_ID = "mh-frame-torn"


class _Seq:
    """A deterministic stream of unit floats seeded from a card key.

    Walks the sha256 digest of ``key`` four bytes at a time, wrapping with a
    re-hash when exhausted, so an unbounded, reproducible sequence of ``[0, 1)``
    values falls out of one seed — the same walk ``gradient_mesh`` uses for its
    seeded meshes. Same key → same numbers; different keys spread.
    """

    __slots__ = ("_buf", "_i", "_key", "_round")

    def __init__(self, key: str) -> None:
        self._key = str(key)
        self._round = 0
        self._buf = hashlib.sha256(self._key.encode("utf-8")).digest()
        self._i = 0

    def _byte4(self) -> int:
        if self._i + 4 > len(self._buf):
            self._round += 1
            self._buf = hashlib.sha256(
                (self._key + "|" + str(self._round)).encode("utf-8")
            ).digest()
            self._i = 0
        chunk = self._buf[self._i : self._i + 4]
        self._i += 4
        return int.from_bytes(chunk, "big")

    def unit(self) -> float:
        """The next value in ``[0, 1)``."""
        return self._byte4() / 4294967296.0

    def between(self, lo: float, hi: float) -> float:
        """The next value linearly mapped into ``[lo, hi)``."""
        return lo + (hi - lo) * self.unit()


def _seed_int(card_key: str, salt: str) -> int:
    """A stable non-negative int seed from a card key + salt (sha256-derived)."""
    h = hashlib.sha256((salt + "|" + str(card_key)).encode("utf-8")).hexdigest()[:8]
    return int(h, 16)


def blob_radius(card_key: str) -> str:
    """The 8-value organic ``border-radius`` for ``card_key``'s blob window.

    Each of the 8 radii is jittered in 35–65 % from ``sha256(card_key|'blob')``,
    so the window reads as a smooth irregular blob. Deterministic: same key →
    same silhouette.
    """
    seq = _Seq(str(card_key) + "|blob")
    vals = [round(seq.between(35.0, 65.0)) for _ in range(8)]
    horiz = " ".join(f"{v}%" for v in vals[:4])
    vert = " ".join(f"{v}%" for v in vals[4:])
    return f"{horiz} / {vert}"


def frame_radius(shape: str, card_key: str) -> str:
    """The ``border-radius`` value for a radius-based shape, or ``""``.

    ``arch`` is the fixed curve; ``blob`` is the seeded 8-value radius. Every
    other token (including ``torn_edge``, which is a filter not a radius, and
    ``rect``) returns ``""``.
    """
    s = (shape or "").strip().lower()
    if s == "arch":
        return _ARCH_RADIUS
    if s == "blob":
        return blob_radius(card_key)
    return ""


def torn_params(card_key: str) -> tuple[float, float, int]:
    """``(base_frequency, displacement_scale, turbulence_seed)`` for a torn edge.

    Seeded from ``sha256(card_key|'frame_torn')`` so both render surfaces (the
    still SVG def and the motion mirror) build the *identical* filter from the
    same numbers: baseFrequency in 0.028–0.034, displacement scale in 12–18 px,
    and an integer turbulence seed. Returned as data (not baked into the SVG) so
    ``motion.py`` can forward the same three values into the Remotion props.
    """
    seq = _Seq(str(card_key) + "|frame_torn")
    base_freq = round(seq.between(0.028, 0.034), 4)
    scale = round(seq.between(12.0, 18.0), 1)
    turb_seed = _seed_int(card_key, "frame_torn") % 1000
    return base_freq, scale, turb_seed


def torn_filter_svg(card_key: str) -> str:
    """A zero-size SVG carrying this card's torn-edge displacement filter.

    ``feTurbulence`` (fractal noise, 2 octaves, seeded) drives a
    ``feDisplacementMap`` that pushes the window's rendered edge in and out — a
    ripped-paper silhouette. Colourless (displacement only, no flood), so the
    filter introduces no brand colour and composes over any photo grade already
    on the image. Injected via the ``{{ACCENT_DECORATION}}`` slot exactly like
    ``render._duotone_defs_svg``.
    """
    base_freq, scale, turb_seed = torn_params(card_key)
    return (
        '<svg width="0" height="0" style="position:absolute" aria-hidden="true">'
        f'<filter id="{TORN_FILTER_ID}" x="-12%" y="-12%" width="124%" height="124%" '
        'color-interpolation-filters="sRGB">'
        f'<feTurbulence type="fractalNoise" baseFrequency="{base_freq}" numOctaves="2" '
        f'seed="{turb_seed}" result="mh-frame-noise"/>'
        '<feDisplacementMap in="SourceGraphic" in2="mh-frame-noise" '
        f'scale="{scale}" xChannelSelector="R" yChannelSelector="G"/>'
        "</filter></svg>"
    )


__all__ = [
    "PHOTO_FRAME_SHAPES",
    "TORN_FILTER_ID",
    "blob_radius",
    "frame_radius",
    "torn_params",
    "torn_filter_svg",
]
