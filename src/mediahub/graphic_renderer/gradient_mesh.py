"""Gradient-mesh background engine (roadmap G1.8).

Deterministic, brand-keyed multi-stop gradient meshes rendered as **pure SVG** in
three modes:

* ``linear``  — two crossing multi-stop linear gradients + a soft corner glow.
* ``radial``  — the classic "mesh-gradient" look: several overlapping radial
  blobs, each keyed to a brand role.
* ``conic``   — an SVG-approximated angular sweep (SVG 1.1 has no native conic
  gradient, so we facet it into fine wedges) around a soft brand core.

This is a *background treatment* — graphic-craft depth layer 1 (see
``.claude/skills/graphic-craft``). It sits **under** the card's text and is keyed
entirely to the resolved ``--mh-*`` brand roles
(``render.resolved_role_vars_for_brief``); it never invents colour. Two
non-negotiables shape the whole module:

* **Deterministic & explainable** — same roles + seed + size → byte-identical
  SVG. Variety comes from the seed (one card → one stable mesh), never from
  process randomness. The seeded sequence is a stable SHA-256 walk, so the output
  is reproducible across Python versions.
* **APCA-gated** — every colour the mesh paints is clamped so the headline ink
  (``on_primary``) stays legible (APCA ``Lc ≥ LC_LARGE``) over the entire field.
  An over-bright stop is blended back toward the brand ground until it reads, so
  the mesh can never break the card's legibility — legibility beats art,
  deterministically (the same ethos as ``render._mh_role_vars``).

The module is self-contained (its own small colour maths) so it imports cheaply
and is trivially unit-testable without Playwright or the big ``render`` module.
The render hook ``sprint_hooks/gradient_mesh_bg.py`` is the only wiring; this file
knows nothing about HTML.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
from dataclasses import dataclass

__all__ = [
    "MESH_MODES",
    "MeshRoles",
    "build_mesh_svg",
    "mesh_data_uri",
    "mesh_mode_for_seed",
]

# The three mesh families the engine renders. ``"auto"`` (accepted by the public
# helpers) resolves to one of these deterministically from the seed.
MESH_MODES: tuple[str, ...] = ("linear", "radial", "conic")

# APCA "Bronze" large-text floor — the same threshold the renderer's role gate
# uses (``quality.compliance.LC_LARGE``). Mirrored here as a fallback so the engine
# stays importable even if that module ever moves; the real gate is used when it
# imports cleanly.
_LC_LARGE = 45.0

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------------
# Self-contained colour maths (kept local so the engine has no heavy imports)
# ---------------------------------------------------------------------------


def _clamp8(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _hex_to_rgb(c: str) -> tuple[int, int, int]:
    c = (c or "#000000").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return 0, 0, 0


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (_clamp8(v) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _norm_hex(value, fallback: str = "#0A2540") -> str:
    """Return a clean ``#RRGGBB`` for ``value`` or ``fallback`` for junk.

    Guarantees every colour the SVG emits is a 6-digit hex, so a malformed role
    can never inject a ``"``/``)``/``;`` into the markup.
    """
    if isinstance(value, str) and _HEX_RE.match(value.strip()):
        return _rgb_to_hex(_hex_to_rgb(value))  # normalise 3-digit → 6-digit, upper-case
    return fallback


def _mix(a: str, b: str, t: float) -> str:
    """Linear RGB blend: ``t=0`` → ``a``, ``t=1`` → ``b``."""
    t = max(0.0, min(1.0, t))
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex((ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t))


def _darken(c: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(c)
    k = 1.0 - max(0.0, min(1.0, amount))
    return _rgb_to_hex((r * k, g * k, b * k))


def _lighten(c: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(c)
    k = max(0.0, min(1.0, amount))
    return _rgb_to_hex((r + (255 - r) * k, g + (255 - g) * k, b + (255 - b) * k))


def _rel_luminance(c: str) -> float:
    """WCAG relative luminance in 0..1 — only the engine's clamp fallback."""

    def _lin(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(c)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _on_color(c: str) -> str:
    return "#0B0B0C" if _rel_luminance(c) > 0.42 else "#FFFFFF"


def _is_legible(ink: str, bg: str, min_lc: float = _LC_LARGE) -> bool:
    """True when ``ink`` clears the APCA floor on ``bg``.

    Uses the real renderer gate (``quality.compliance.is_legible`` → APCA) when it
    imports cleanly; falls back to a WCAG-ratio proxy so the engine never hard-
    depends on that module at import time.
    """
    try:
        from mediahub.quality.compliance import is_legible as _gate

        return _gate(ink, bg, min_lc=min_lc)
    except Exception:
        hi = max(_rel_luminance(ink), _rel_luminance(bg))
        lo = min(_rel_luminance(ink), _rel_luminance(bg))
        ratio = (hi + 0.05) / (lo + 0.05)
        # Map the APCA floor onto a roughly-equivalent WCAG ratio (Lc45 ≈ 3:1).
        return ratio >= (1.0 + (min_lc / 45.0) * 2.0)


def _legible_floor(ink: str, bg: str, anchor: str, min_lc: float = _LC_LARGE) -> str:
    """Blend ``bg`` toward ``anchor`` until ``ink`` reads on it (APCA-gated).

    ``anchor`` is the brand ground (``primary``), which is legible against ``ink``
    by construction (``render._mh_role_vars`` guarantees it). Any candidate mesh
    tone that would drop the headline ink below the floor is pulled back toward
    that anchor in bounded steps — so every point of the mesh keeps the card
    legible. Returns ``anchor`` if even a near-anchor blend fails (defensive).
    """
    if _is_legible(ink, bg, min_lc):
        return bg
    for i in range(1, 9):
        cand = _mix(bg, anchor, i / 8.0)
        if _is_legible(ink, cand, min_lc):
            return cand
    return anchor


# ---------------------------------------------------------------------------
# Deterministic, version-stable sequence (no global random state)
# ---------------------------------------------------------------------------


class _Seq:
    """A reproducible float sequence seeded by ``seed`` via a SHA-256 walk.

    Stable across processes and Python versions (unlike ``random`` internals),
    which is what keeps "same brief → same PNG" honest.
    """

    __slots__ = ("_seed", "_i")

    def __init__(self, seed) -> None:
        self._seed = str(seed)
        self._i = 0

    def unit(self) -> float:
        """Next float in ``[0, 1)``."""
        h = hashlib.sha256(f"{self._seed}:{self._i}".encode("utf-8")).hexdigest()
        self._i += 1
        return int(h[:8], 16) / float(0x1_0000_0000)

    def span(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.unit()

    def pick(self, seq):
        return seq[int(self.unit() * len(seq)) % len(seq)]


def mesh_mode_for_seed(seed) -> str:
    """Pick one of :data:`MESH_MODES` deterministically from ``seed``."""
    return _Seq(f"mode:{seed}").pick(MESH_MODES)


# ---------------------------------------------------------------------------
# Brand roles → mesh field
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeshRoles:
    """The resolved brand colours the mesh keys to.

    Built from the renderer's ``--mh-*`` role set
    (:func:`render.resolved_role_vars_for_brief`) so the mesh shares the exact,
    APCA-gated, medal-aware palette the rest of the card paints — still↔motion
    colour parity holds because both consume the same roles.
    """

    primary: str
    surface: str
    secondary: str
    accent: str
    on_primary: str

    @classmethod
    def from_role_vars(cls, role_vars: dict) -> "MeshRoles":
        rv = role_vars or {}
        primary = _norm_hex(rv.get("--mh-primary"), "#0A2540")
        return cls(
            primary=primary,
            surface=_norm_hex(rv.get("--mh-surface"), _darken(primary, 0.50)),
            secondary=_norm_hex(rv.get("--mh-secondary"), _darken(primary, 0.40)),
            accent=_norm_hex(rv.get("--mh-accent"), _lighten(primary, 0.55)),
            on_primary=_norm_hex(rv.get("--mh-on-primary"), _on_color(primary)),
        )


def _coerce_roles(roles) -> MeshRoles:
    if isinstance(roles, MeshRoles):
        return roles
    if isinstance(roles, dict):
        return MeshRoles.from_role_vars(roles)
    return MeshRoles.from_role_vars({})


def _clamp_intensity(intensity: float) -> float:
    try:
        v = float(intensity)
    except (TypeError, ValueError):
        v = 0.5
    return max(0.15, min(0.9, v))


def _lerp(lo: float, hi: float, t: float) -> float:
    return lo + (hi - lo) * t


def _field(roles: MeshRoles, intensity: float) -> dict[str, str]:
    """The APCA-safe tonal palette the mesh draws from, keyed to brand roles.

    Tones spread *away* from the ground (``primary``) by ``intensity`` toward the
    surface, secondary and accent roles, then each is floored against the headline
    ink so it can never break legibility. The accent stays a subtle tint (a bright
    accent patch under a hero numeral would be the loudest legibility risk).
    """
    p, ink = roles.primary, roles.on_primary

    deep = _mix(p, roles.surface, _lerp(0.45, 1.0, intensity))  # deeper than ground
    sec = _mix(p, roles.secondary, _lerp(0.30, 0.65, intensity))  # hue shift → secondary
    acc = _mix(p, roles.accent, _lerp(0.10, 0.26, intensity))  # gentle accent tint
    # A lift the *opposite* tonal way from `deep`, so the field has range in both
    # directions; the clamp pulls it back on a light ground where it would fail.
    lift = (
        _lighten(p, _lerp(0.06, 0.20, intensity))
        if _rel_luminance(p) < 0.42
        else _darken(p, _lerp(0.06, 0.18, intensity))
    )

    return {
        "base": p,
        "ink": ink,  # carried so builders that interpolate tones can re-clamp
        "deep": _legible_floor(ink, deep, p),
        "sec": _legible_floor(ink, sec, p),
        "acc": _legible_floor(ink, acc, p),
        "lift": _legible_floor(ink, lift, p),
    }


# ---------------------------------------------------------------------------
# SVG builders (one per mode) — all multi-stop, all pure SVG 1.1
# ---------------------------------------------------------------------------


def _fmt(x: float) -> str:
    """Compact fixed-precision number so the SVG stays deterministic & small."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _linear_mesh(f: dict, seq: _Seq, w: int, h: int, intensity: float) -> str:
    a0 = seq.span(110.0, 170.0)  # primary sweep angle
    a1 = a0 + seq.span(55.0, 95.0)  # crossing overlay angle
    cx, cy = seq.span(0.18, 0.42), seq.span(0.12, 0.38)  # corner-glow centre

    def _xy(angle_deg: float) -> tuple[str, str, str, str]:
        a = math.radians(angle_deg)
        dx, dy = math.cos(a), math.sin(a)
        return (
            _fmt(50 - dx * 50),
            _fmt(50 - dy * 50),
            _fmt(50 + dx * 50),
            _fmt(50 + dy * 50),
        )

    x1, y1, x2, y2 = _xy(a0)
    ox1, oy1, ox2, oy2 = _xy(a1)
    ov = 0.34 + 0.30 * intensity
    glow = 0.22 + 0.30 * intensity
    return f"""<defs>
<linearGradient id="lg0" x1="{x1}%" y1="{y1}%" x2="{x2}%" y2="{y2}%">
<stop offset="0%" stop-color="{f['deep']}"/>
<stop offset="38%" stop-color="{f['base']}"/>
<stop offset="72%" stop-color="{f['sec']}"/>
<stop offset="100%" stop-color="{f['deep']}"/>
</linearGradient>
<linearGradient id="lg1" x1="{ox1}%" y1="{oy1}%" x2="{ox2}%" y2="{oy2}%">
<stop offset="0%" stop-color="{f['lift']}" stop-opacity="0"/>
<stop offset="52%" stop-color="{f['lift']}" stop-opacity="{_fmt(ov)}"/>
<stop offset="100%" stop-color="{f['acc']}" stop-opacity="0"/>
</linearGradient>
<radialGradient id="glow" cx="{_fmt(cx * 100)}%" cy="{_fmt(cy * 100)}%" r="78%">
<stop offset="0%" stop-color="{f['acc']}" stop-opacity="{_fmt(glow)}"/>
<stop offset="55%" stop-color="{f['acc']}" stop-opacity="{_fmt(glow * 0.35)}"/>
<stop offset="100%" stop-color="{f['acc']}" stop-opacity="0"/>
</radialGradient>
</defs>
<rect width="{w}" height="{h}" fill="{f['base']}"/>
<rect width="{w}" height="{h}" fill="url(#lg0)"/>
<rect width="{w}" height="{h}" fill="url(#lg1)"/>
<rect width="{w}" height="{h}" fill="url(#glow)"/>"""


def _radial_mesh(f: dict, seq: _Seq, w: int, h: int, intensity: float) -> str:
    # Deterministic blob anchors: pin a few toward corners (where mesh gradients
    # read best) and let the seed jitter each so no two cards share a field.
    anchors = [(0.16, 0.18), (0.84, 0.20), (0.22, 0.82), (0.80, 0.78), (0.50, 0.46)]
    tones = ["deep", "sec", "acc", "lift", "sec"]
    n = 4 + int(seq.unit() * 2)  # 4 or 5 blobs
    defs: list[str] = []
    rects: list[str] = []
    for i in range(n):
        ax, ay = anchors[i % len(anchors)]
        cx = max(0.0, min(1.0, ax + seq.span(-0.12, 0.12)))
        cy = max(0.0, min(1.0, ay + seq.span(-0.12, 0.12)))
        rad = seq.span(0.55, 0.95)
        tone = f[seq.pick(tones)] if i == 0 else f[tones[i % len(tones)]]
        alpha = (0.42 + 0.34 * intensity) * (1.0 if i < 3 else 0.7)
        defs.append(
            f'<radialGradient id="b{i}" cx="{_fmt(cx * 100)}%" cy="{_fmt(cy * 100)}%" '
            f'r="{_fmt(rad * 100)}%">'
            f'<stop offset="0%" stop-color="{tone}" stop-opacity="{_fmt(alpha)}"/>'
            f'<stop offset="55%" stop-color="{tone}" stop-opacity="{_fmt(alpha * 0.40)}"/>'
            f'<stop offset="100%" stop-color="{tone}" stop-opacity="0"/>'
            f"</radialGradient>"
        )
        rects.append(f'<rect width="{w}" height="{h}" fill="url(#b{i})"/>')
    return (
        "<defs>"
        + "".join(defs)
        + "</defs>"
        + f'<rect width="{w}" height="{h}" fill="{f["base"]}"/>'
        + "".join(rects)
    )


def _conic_mesh(f: dict, seq: _Seq, w: int, h: int, intensity: float) -> str:
    # SVG 1.1 has no conic gradient — facet the sweep into fine wedges and let the
    # renderer's anti-aliasing (plus a soft blur) read it as a smooth rotation.
    cx, cy = seq.span(0.40, 0.60) * w, seq.span(0.40, 0.60) * h
    radius = math.hypot(w, h)  # overshoot the frame so wedges fully cover it
    start = seq.span(0.0, 360.0)
    direction = 1 if seq.unit() < 0.5 else -1
    ramp = ["deep", "sec", "base", "lift", "acc", "base", "sec", "deep"]
    segments = 72
    blur = max(2.0, (w + h) / 220.0)

    paths: list[str] = []
    for k in range(segments):
        a0 = math.radians(start + direction * (360.0 * k / segments))
        a1 = math.radians(start + direction * (360.0 * (k + 1) / segments))
        x0 = cx + math.cos(a0) * radius
        y0 = cy + math.sin(a0) * radius
        x1 = cx + math.cos(a1) * radius
        y1 = cy + math.sin(a1) * radius
        t = (k / segments) * (len(ramp) - 1)
        lo = int(t)
        frac = t - lo
        col = _mix(f[ramp[lo]], f[ramp[min(lo + 1, len(ramp) - 1)]], frac)
        # Re-clamp the interpolated wedge: mixing two safe tones is *almost*
        # always safe, but APCA isn't linear, so floor every wedge against the
        # ink to make the "no colour breaks legibility" guarantee airtight.
        col = _legible_floor(f["ink"], col, f["base"])
        sweep = 1 if direction > 0 else 0
        paths.append(
            f'<path d="M{_fmt(cx)} {_fmt(cy)} L{_fmt(x0)} {_fmt(y0)} '
            f'A{_fmt(radius)} {_fmt(radius)} 0 0 {sweep} {_fmt(x1)} {_fmt(y1)} Z" '
            f'fill="{col}"/>'
        )
    core_a = 0.30 + 0.28 * intensity
    return f"""<defs>
<filter id="soft" x="-10%" y="-10%" width="120%" height="120%">
<feGaussianBlur stdDeviation="{_fmt(blur)}"/>
</filter>
<radialGradient id="core" cx="{_fmt(cx / w * 100)}%" cy="{_fmt(cy / h * 100)}%" r="60%">
<stop offset="0%" stop-color="{f['base']}" stop-opacity="{_fmt(core_a)}"/>
<stop offset="100%" stop-color="{f['base']}" stop-opacity="0"/>
</radialGradient>
</defs>
<rect width="{w}" height="{h}" fill="{f['base']}"/>
<g filter="url(#soft)">{''.join(paths)}</g>
<rect width="{w}" height="{h}" fill="url(#core)"/>"""


_BUILDERS = {"linear": _linear_mesh, "radial": _radial_mesh, "conic": _conic_mesh}


# ---------------------------------------------------------------------------
# Public engine API
# ---------------------------------------------------------------------------


def build_mesh_svg(
    roles,
    width: int,
    height: int,
    *,
    mode: str = "auto",
    seed=0,
    intensity: float = 0.5,
) -> str:
    """Return a deterministic, APCA-safe brand-keyed gradient-mesh as an SVG string.

    ``roles`` is a :class:`MeshRoles` or a ``--mh-*`` role-var dict. ``mode`` is
    one of :data:`MESH_MODES` or ``"auto"`` (resolved from ``seed``). The SVG's
    base rect is the opaque brand ground, so it is a complete background on its
    own. Same arguments always yield byte-identical output.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    rls = _coerce_roles(roles)
    inten = _clamp_intensity(intensity)
    chosen = mode if mode in MESH_MODES else mesh_mode_for_seed(seed)
    field = _field(rls, inten)
    body = _BUILDERS[chosen](field, _Seq(f"{chosen}:{seed}"), w, h, inten)
    # C8 (Canva gap analysis) — grainy-gradient dither: a faint fractal-noise
    # layer over the soft colour field breaks the 8-bit banding a long
    # dark-to-dark gradient shows at 1080px+ and reads as print texture.
    # Deterministic (fixed feTurbulence seed, no randomness), self-contained
    # inside the same SVG asset, and quiet enough (5%) that the APCA-clamped
    # stop colours still govern every legibility decision.
    grain = (
        '<filter id="mh-mesh-grain"><feTurbulence type="fractalNoise" '
        'baseFrequency="0.65" numOctaves="2" seed="7" stitchTiles="stitch"/>'
        "</filter>"
        f'<rect width="{w}" height="{h}" filter="url(#mh-mesh-grain)" opacity="0.05"/>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        f'data-mh-mesh="{chosen}">{body}{grain}</svg>'
    )


def mesh_data_uri(
    roles,
    width: int,
    height: int,
    *,
    mode: str = "auto",
    seed=0,
    intensity: float = 0.5,
) -> str:
    """:func:`build_mesh_svg` wrapped as a CSS ``url("data:image/svg+xml;base64,…")``.

    Base64 (not percent-encoding) to match the renderer's other background data
    URIs (``render._background_pattern_for``), so it drops straight into a
    ``background-image`` declaration.
    """
    svg = build_mesh_svg(roles, width, height, mode=mode, seed=seed, intensity=intensity)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'url("data:image/svg+xml;base64,{b64}")'
