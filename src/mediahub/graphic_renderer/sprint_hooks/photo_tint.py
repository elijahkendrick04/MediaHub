"""Photo-derived ground tinting (roadmap G1.7).

A post-render hook that nudges a v2 card's **derived** ground colours a small,
APCA-safe step toward the dominant colour of the photo the card carries — so the
card reads as colour-connected to the swimmer in it, not floating on a generic
slab. The photo's palette comes from :mod:`graphic_renderer.photo_palette`
(deterministic PIL k-means).

Two hard rules:

* **Never overrides a confirmed brand hex.** The club's ``--mh-primary`` brand
  ground is only ever tinted when it is the renderer's *no-brand fallback* (a
  club that supplied no colours at all) — never when it carries the club's real
  brand colour. The colour we always tint is the **derived** ``--mh-surface``
  (``darken(primary, 0.50)``), which is renderer maths, not a brand token. The
  brand colour the operator confirmed is left byte-identical.
* **APCA-gated.** A tint is accepted only if the on-ground ink still clears the
  APCA headline bar (``LC_LARGE``) on the tinted ground *and* loses no meaningful
  contrast versus the untinted ground. If no step in the range is safe, the hook
  opts out and the card renders exactly as before.

Opt-in: the hook is a no-op unless ``MEDIAHUB_PHOTO_TINT`` is truthy, so default
renders stay byte-identical. It only touches v2 cards that actually carry a
photo; everything else passes through untouched. Deterministic: same HTML in →
same HTML out.
"""

from __future__ import annotations

import base64
import os
import re

from . import RenderHookCtx

# Run after structural background hooks (e.g. a future gradient-mesh at 20) so a
# tint grades whatever ground is in place, but before a late desaturate/mono pass.
ORDER = 40

_FALSE = {"", "0", "false", "no", "off"}

# The renderer's no-brand fallback ground (render._mh_role_vars). A ground equal
# to this — with no brand primary on the brief — is the only ``--mh-primary`` we
# treat as unconfirmed and therefore tintable.
_DEFAULT_GROUND = "#0A2540"

# Largest mix toward the photo colour, per ground. Surface (deep, mostly behind
# the photo) tolerates a touch more than the brand-fallback ground. The gate may
# step these down; it never steps them up.
_MAX_SURFACE = 0.20
_MAX_PRIMARY = 0.14

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# Each role var as injected by render.py: ``--mh-surface:#0A1A2A;`` (no spaces).
_ROOT_VAR_RE = re.compile(r"(--mh-[a-z0-9-]+)\s*:\s*([^;{}]+?)\s*;")
# An <img class="… athlete-cutout …"> tag, whatever the attribute order.
_CUTOUT_IMG_RE = re.compile(
    r'<img\b[^>]*\bclass="[^"]*\bathlete-cutout\b[^"]*"[^>]*>', re.IGNORECASE
)
_DATA_URI_RE = re.compile(r'src="data:image/[a-z0-9.+-]+;base64,([A-Za-z0-9+/=]+)"', re.IGNORECASE)


def _enabled() -> bool:
    return os.environ.get("MEDIAHUB_PHOTO_TINT", "").strip().lower() not in _FALSE


def _is_hex(value) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value.strip()))


def _norm(value: str) -> str:
    """Normalise a hex for comparison (uppercase, expand 3→6 digit)."""
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h.upper()


def _parse_root_vars(html: str) -> dict[str, str]:
    """The ``--mh-*`` custom properties from the renderer's injected ``:root{}``.

    Reads the LAST ``:root{…}`` block so we honour the resolved (post-assignment)
    role set, then maps every ``--mh-…:value;`` declaration inside it.
    """
    starts = [m.end() for m in re.finditer(r":root\s*{", html)]
    if not starts:
        return {}
    start = starts[-1]
    end = html.find("}", start)
    if end == -1:
        return {}
    return {m.group(1): m.group(2).strip() for m in _ROOT_VAR_RE.finditer(html[start:end])}


def _hero_photo_bytes(html: str) -> bytes | None:
    """Decode the largest athlete-cutout data URI in ``html`` (the hero photo).

    Picks the longest base64 payload so a duo/relay split's main subject wins.
    Returns ``None`` when the card carries no inlined photo (text-led archetypes).
    """
    best: str | None = None
    for tag in _CUTOUT_IMG_RE.findall(html):
        m = _DATA_URI_RE.search(tag)
        if m and (best is None or len(m.group(1)) > len(best)):
            best = m.group(1)
    if not best:
        return None
    try:
        return base64.b64decode(best)
    except Exception:
        return None


def _ground_is_confirmed(ctx: RenderHookCtx, primary: str) -> bool:
    """True when ``--mh-primary`` is the club's confirmed brand colour.

    A real hex ground is the confirmed brand colour and must never be overridden
    — UNLESS it is exactly the renderer's no-brand fallback *and* the brief
    carries no brand primary of its own, i.e. there is genuinely no brand colour
    to protect (a club that supplied none). Only then may the photo seed it.
    """
    if not _is_hex(primary):
        return False
    palette = getattr(getattr(ctx, "brief", None), "palette", None) or {}
    brief_primary = palette.get("primary") if isinstance(palette, dict) else None
    if _is_hex(brief_primary):
        return True
    return _norm(primary) != _norm(_DEFAULT_GROUND)


def _gated_tint(base: str, target: str, ink: str, max_amount: float) -> str | None:
    """Strongest APCA-safe tint of ``base`` toward ``target``, or ``None``.

    Steps the mix down from ``max_amount``; accepts the first that keeps ``ink``
    above the APCA headline bar on the tinted ground and within a hair of the
    original contrast (a tint may grade a ground, never erode its legibility).
    """
    from mediahub.graphic_renderer.photo_palette import tint_toward
    from mediahub.quality.compliance import LC_LARGE
    from mediahub.theming.contrast import apca

    base_lc = abs(apca(ink, base))
    floor = max(LC_LARGE, base_lc - 2.0)  # never drop more than ~2 Lc below start
    for amount in (max_amount, max_amount * 0.6, max_amount * 0.3):
        cand = tint_toward(base, target, amount)
        if _norm(cand) == _norm(base):
            continue
        if abs(apca(ink, cand)) >= floor:
            return cand
    return None


def apply(html: str, ctx: RenderHookCtx) -> str:
    """Inject an APCA-gated, photo-derived ground tint (G1.7). No-op unless
    enabled, the card is v2, and it carries a photo."""
    if not _enabled() or not getattr(ctx, "is_v2", False):
        return html

    photo = _hero_photo_bytes(html)
    if photo is None:
        return html

    roles = _parse_root_vars(html)
    surface = roles.get("--mh-surface")
    on_surface = roles.get("--mh-on-surface")
    primary = roles.get("--mh-primary")
    on_primary = roles.get("--mh-on-primary")
    if not (_is_hex(surface) and _is_hex(on_surface)):
        return html

    from mediahub.graphic_renderer.photo_palette import extract_palette

    target = extract_palette(photo).tint_target()
    if not target:
        return html

    decls: dict[str, str] = {}

    new_surface = _gated_tint(surface, target, on_surface, _MAX_SURFACE)
    if new_surface:
        decls["--mh-surface"] = new_surface

    # The brand ground is only tinted when it is the unconfirmed no-brand
    # fallback — a confirmed brand hex is left exactly as the operator set it.
    if _is_hex(primary) and _is_hex(on_primary) and not _ground_is_confirmed(ctx, primary):
        new_primary = _gated_tint(primary, target, on_primary, _MAX_PRIMARY)
        if new_primary:
            decls["--mh-primary"] = new_primary

    if not decls:
        return html  # nothing cleared the gate → render unchanged

    # A decorative photo-keyed accent for any downstream hook/element that wants
    # it. Never a brand token, so it can't override a confirmed colour.
    decls["--mh-photo-accent"] = target

    block = "<style>:root{" + "".join(f"{k}:{v};" for k, v in decls.items()) + "}</style>"
    if "</body>" in html:
        return html.replace("</body>", block + "</body>", 1)
    return html + block
