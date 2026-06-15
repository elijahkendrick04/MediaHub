"""Style-pack catalog — the combinatorial template layer (Gen Engine v2, Tier A+).

Hand-authoring a thousand standalone layout files is the "Canva template shop"
anti-pattern MediaHub rejects (CLAUDE.md: *the intelligence layer is the moat*).
Instead the template space is **combinatorial and deterministic**:

    template  =  archetype (structural skeleton, ``layouts/v2/<name>.html``)
              ×  style pack (an orthogonal bundle of decorative levers)

A *style pack* is four independent levers — a ground (atmospheric) treatment, a
surface texture, an accent geometry, and an intensity (density) tier — each a
small **closed vocabulary** the renderer knows how to execute. Their pruned,
de-duplicated product is the pack catalog; crossed with the archetype library it
yields the **template catalog**: thousands of stable, addressable, brand-safe,
explainable templates, every one reproducible from its id.

Design rules this module keeps (so it never crosses the deterministic-engine or
legibility lines):

* **Maths renders, AI judges.** Pack selection is a deterministic seeded pick
  (``pick_style_pack`` / ``pick_style_pack_for_card``) — the same no-LLM floor
  shape as :mod:`graphic_renderer.archetypes`. The AI design-spec director still
  picks the *archetype* + colour roles + emphasis; the pack rides deterministically
  on top, so even an AI-directed card gets varied, reproducible styling.
* **Brand colour is never invented.** Pack overlays paint only in
  ``var(--mh-accent)`` (the resolved, APCA-gated accent) and neutral black/white
  alphas. A pack adds *overlay* tokens/markup; it never overrides the seven core
  ``--mh-*`` role tokens, so the still↔motion colour parity and the text-contrast
  guarantee (``on-primary`` vs ``primary``) are untouched by construction.
* **Legibility-safe by construction.** Ground treatments darken only (more
  contrast for light text; gentle enough for dark text), at capped alpha;
  textures are low-opacity ``mix-blend`` overlays (the existing grain precedent);
  accent geometry lives in the safe margins. None of it sits opaque over copy.
* **Deterministic + explainable.** Same pack id → same injected CSS/markup →
  same pixels. Every pack carries a human name + short ``why`` for the trace.

The catalog is **inert until applied**: an empty ``style_pack`` on a brief (the
default, and every legacy/flag-off caller) renders exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# Closed lever vocabularies. Order is fixed — the seeded picker indexes into
# the derived catalog by modulo, so a reorder would change every pick.
# ---------------------------------------------------------------------------

# Atmospheric ground treatment, painted as a *darken-only* overlay so it can
# compose over any archetype root (flat fill, gradient, or photo stage) without
# ever reducing text contrast below the archetype's flat baseline.
GROUNDS: tuple[str, ...] = (
    "flat",
    "top_fade",
    "bottom_fade",
    "corner_fade",
    "vignette",
    "spotlight",
    "twotone",
    "dual_fade",
    "top_corner_fade",
    "edge_frame",
    "diagonal_fade",
)

# Surface micro-texture — a low-opacity, blended overlay (the grain precedent).
TEXTURES: tuple[str, ...] = (
    "none",
    "grain",
    "dots",
    "grid",
    "hatch",
    "halftone",
    "crosshatch",
    "weave",
    "scanline",
    "carbon",
    "chevron",
)

# Accent geometry drawn in the resolved ``--mh-accent``, confined to the margins.
ACCENT_GEOS: tuple[str, ...] = (
    "none",
    "corner_ticks",
    "side_rule",
    "baseline_rule",
    "frame",
    "wedge",
    "ring",
    "corner_blocks",
    "double_rule",
    "dot_row",
    "cross_ticks",
    "corner_arc",
)

# Intensity tier — scales the alphas / weights / sizes of the levers above.
DENSITIES: tuple[str, ...] = ("standard", "bold")

# Per-value "visual weight" (0 = absent/flat, 1 = light, 2 = heavy). The catalog
# keeps only packs whose summed weight stays under a cap, so no template stacks a
# heavy ground + busy texture + heavy geometry into an over-decorated card.
_GROUND_W = {
    "flat": 0,
    "top_fade": 1,
    "bottom_fade": 1,
    "corner_fade": 1,
    "vignette": 2,
    "spotlight": 2,
    "twotone": 2,
    "dual_fade": 1,
    "top_corner_fade": 1,
    "edge_frame": 2,
    "diagonal_fade": 2,
}
_TEXTURE_W = {
    "none": 0,
    "grain": 1,
    "dots": 1,
    "grid": 1,
    "hatch": 1,
    "halftone": 2,
    "crosshatch": 2,
    "weave": 1,
    "scanline": 1,
    "carbon": 2,
    "chevron": 2,
}
_ACCENT_W = {
    "none": 0,
    "corner_ticks": 1,
    "side_rule": 1,
    "baseline_rule": 1,
    "frame": 2,
    "wedge": 2,
    "ring": 2,
    "corner_blocks": 2,
    "double_rule": 1,
    "dot_row": 1,
    "cross_ticks": 1,
    "corner_arc": 2,
}

# Coherence caps: standard density tolerates a little more stacking than bold
# (bold already intensifies whatever is present).
_WEIGHT_CAP_STANDARD = 4
_WEIGHT_CAP_BOLD = 3

# Friendly fragments for the generated pack name / why-line.
_GROUND_LABEL = {
    "flat": "flat",
    "top_fade": "top-lit",
    "bottom_fade": "grounded",
    "corner_fade": "cornered",
    "vignette": "vignetted",
    "spotlight": "spotlit",
    "twotone": "two-tone",
    "dual_fade": "edge-lit",
    "top_corner_fade": "top-cornered",
    "edge_frame": "edge-framed",
    "diagonal_fade": "diagonal",
}
_TEXTURE_LABEL = {
    "none": "clean",
    "grain": "grain",
    "dots": "dotted",
    "grid": "gridded",
    "hatch": "hatched",
    "halftone": "halftone",
    "crosshatch": "crosshatched",
    "weave": "weave",
    "scanline": "scanline",
    "carbon": "carbon",
    "chevron": "chevron",
}
_ACCENT_LABEL = {
    "none": "bare",
    "corner_ticks": "corner ticks",
    "side_rule": "side rule",
    "baseline_rule": "baseline rule",
    "frame": "framed",
    "wedge": "wedge",
    "ring": "ring",
    "corner_blocks": "corner blocks",
    "double_rule": "double rule",
    "dot_row": "dot row",
    "cross_ticks": "register marks",
    "corner_arc": "corner arcs",
}


# ---------------------------------------------------------------------------
# StylePack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StylePack:
    """One bundle of decorative levers. Frozen + hashable so it keys caches."""

    ground: str
    texture: str
    accent_geo: str
    density: str

    @property
    def id(self) -> str:
        """Stable, human-readable id (``"vignette-dots-corner_ticks-bold"``)."""
        return f"{self.ground}-{self.texture}-{self.accent_geo}-{self.density}"

    @property
    def weight(self) -> int:
        return _GROUND_W[self.ground] + _TEXTURE_W[self.texture] + _ACCENT_W[self.accent_geo]

    @property
    def is_bare(self) -> bool:
        """The single undecorated pack — renders byte-identical to no pack."""
        return self.ground == "flat" and self.texture == "none" and self.accent_geo == "none"

    def name(self) -> str:
        """A short title for the gallery / explainability.

        Skips the silent defaults (``flat`` ground / ``clean`` texture) so the
        title names only what the pack actually adds — e.g. ``"Dotted · Bold"``,
        ``"Vignetted · Wedge"`` — and reads as ``"Clean"`` for the bare pack.
        """
        bits: list[str] = []
        if self.ground != "flat":
            bits.append(_GROUND_LABEL[self.ground])
        if self.texture != "none":
            bits.append(_TEXTURE_LABEL[self.texture])
        if self.accent_geo != "none":
            bits.append(_ACCENT_LABEL[self.accent_geo])
        if self.density == "bold":
            bits.append("bold")
        return " · ".join(bits).title() if bits else "Clean"

    def why(self) -> str:
        """One plain line describing what this pack does to the card."""
        g = "" if self.ground == "flat" else f"a {_GROUND_LABEL[self.ground]} ground"
        t = "" if self.texture == "none" else f"a {_TEXTURE_LABEL[self.texture]} surface"
        a = "" if self.accent_geo == "none" else f"{_ACCENT_LABEL[self.accent_geo]} accents"
        parts = [p for p in (g, t, a) if p]
        if not parts:
            return "Clean treatment — the archetype's own composition, undecorated."
        lead = "Bold" if self.density == "bold" else "Subtle"
        return f"{lead} treatment: " + ", ".join(parts) + "."


def normalise_pack(
    ground: str = "flat",
    texture: str = "none",
    accent_geo: str = "none",
    density: str = "standard",
) -> StylePack:
    """Coerce arbitrary lever strings into a valid :class:`StylePack`.

    Any out-of-vocabulary value falls back to its safe default, mirroring
    ``design_spec.normalise`` — a bad value can never produce an unrenderable
    pack. Returns the canonical *bare* pack when everything is default.
    """

    def _one(value, allowed, default):
        v = str(value or "").strip().lower()
        return v if v in allowed else default

    return StylePack(
        ground=_one(ground, GROUNDS, "flat"),
        texture=_one(texture, TEXTURES, "none"),
        accent_geo=_one(accent_geo, ACCENT_GEOS, "none"),
        density=_one(density, DENSITIES, "standard"),
    )


# ---------------------------------------------------------------------------
# The pack catalog — pruned, de-duplicated, deterministically ordered.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def list_style_packs() -> tuple[StylePack, ...]:
    """Every valid style pack, in a stable order.

    The product of the four vocabularies, minus packs over the coherence weight
    cap, minus the duplicate intensity of the *bare* pack (intensity is moot
    when there is nothing to intensify). Stable so the seeded picker is
    reproducible across processes and filesystems.
    """
    packs: list[StylePack] = []
    seen: set[str] = set()
    for ground, texture, accent_geo, density in product(GROUNDS, TEXTURES, ACCENT_GEOS, DENSITIES):
        pack = StylePack(ground, texture, accent_geo, density)
        cap = _WEIGHT_CAP_BOLD if density == "bold" else _WEIGHT_CAP_STANDARD
        if pack.weight > cap:
            continue
        # The bare card has no decoration to intensify, so keep only its
        # standard form — bold-bare would render identically.
        if pack.is_bare and density != "standard":
            continue
        if pack.id in seen:
            continue
        seen.add(pack.id)
        packs.append(pack)
    # Deterministic order: bare first, then by ascending weight, then id, so a
    # modulo walk spreads from quiet → busy rather than clustering.
    packs.sort(key=lambda p: (not p.is_bare, p.weight, p.id))
    return tuple(packs)


def style_pack_count() -> int:
    return len(list_style_packs())


@lru_cache(maxsize=1)
def _pack_by_id() -> dict[str, StylePack]:
    return {p.id: p for p in list_style_packs()}


def style_pack_from_id(pack_id: str) -> Optional[StylePack]:
    """Look up a pack by its id, or ``None`` when unknown."""
    return _pack_by_id().get(str(pack_id or "").strip().lower())


def pick_style_pack(seed: int) -> StylePack:
    """Deterministically pick one pack from a seed (stable, well-spread)."""
    packs = list_style_packs()
    return packs[int(seed) % len(packs)]


def pick_style_pack_avoiding(seed: int, recent: Iterable[str]) -> StylePack:
    """Seeded pick that steps past recently-used pack ids.

    The no-LLM floor for "give me a *fresh* treatment": start at the seeded pack
    and walk forward until one not in ``recent`` is found, so consecutive
    regenerates / cards in a pack vary instead of repeating one look. Fully
    deterministic; degrades to :func:`pick_style_pack` when everything is recent.
    """
    packs = list_style_packs()
    avoid = {str(r).strip().lower() for r in recent if r}
    start = int(seed) % len(packs)
    for offset in range(len(packs)):
        cand = packs[(start + offset) % len(packs)]
        if cand.id not in avoid:
            return cand
    return packs[start]


def _seed_for(key: str, salt: str = "") -> int:
    """A deterministic non-negative seed from a card key (sha256-derived).

    Same key → same seed (re-renders look identical); different keys spread.
    The ``salt`` lets pack selection draw a *different* seed than archetype
    selection from the same card id, so the two axes vary independently.
    """
    import hashlib

    h = hashlib.sha256((salt + "|" + str(key)).encode("utf-8")).hexdigest()[:8]
    return int(h, 16)


def pick_style_pack_for_card(
    card_key: Optional[str], recent: Optional[Iterable[str]] = None
) -> StylePack:
    """Pick a pack for a card: stable per card, spread across a content pack.

    Mirrors ``archetypes.pick_archetype_avoiding`` but on the pack axis, with a
    salted seed so a card's pack and archetype are chosen independently. A
    missing ``card_key`` falls back to a time-seeded pick (a fresh look each
    call) rather than always the bare pack.
    """
    if not card_key:
        import time

        return pick_style_pack(int(time.time() * 1000))
    return pick_style_pack_avoiding(_seed_for(card_key, salt="pack"), recent or ())


# ---------------------------------------------------------------------------
# Template = archetype × style pack (the addressable unit).
# ---------------------------------------------------------------------------

_TEMPLATE_SEP = "/"


@dataclass(frozen=True)
class Template:
    """A concrete, renderable template: a structural archetype + a style pack."""

    archetype: str
    pack: StylePack

    @property
    def id(self) -> str:
        return f"{self.archetype}{_TEMPLATE_SEP}{self.pack.id}"

    def name(self) -> str:
        return f"{self.archetype} — {self.pack.name()}"


def list_templates(archetypes: Sequence[str]) -> list[Template]:
    """The full template catalog for a given archetype library.

    ``archetypes`` is injected (owned by :mod:`graphic_renderer.archetypes`) so
    this module never has to scan the layouts dir. Ordered archetype-major then
    pack order, so it reads as a catalog grouped by structure.
    """
    packs = list_style_packs()
    return [Template(a, p) for a in archetypes for p in packs]


def template_count(archetypes: Sequence[str]) -> int:
    return len(archetypes) * style_pack_count()


def template_from_id(template_id: str, archetypes: Sequence[str]) -> Optional[Template]:
    """Parse ``"<archetype>/<pack-id>"`` into a :class:`Template`, or ``None``."""
    raw = str(template_id or "")
    if _TEMPLATE_SEP not in raw:
        return None
    archetype, pack_id = raw.split(_TEMPLATE_SEP, 1)
    if archetype not in set(archetypes):
        return None
    pack = style_pack_from_id(pack_id)
    return Template(archetype, pack) if pack else None


def pick_template(seed: int, archetypes: Sequence[str]) -> Optional[Template]:
    """Deterministically pick one template (archetype × pack) from a seed."""
    if not archetypes:
        return None
    templates = list_templates(archetypes)
    return templates[int(seed) % len(templates)]


# ---------------------------------------------------------------------------
# Render application — the injected CSS/markup for a pack.
#
# Everything here is one self-contained overlay string dropped into a v2
# archetype's ``{{ACCENT_DECORATION}}`` slot (the last child inside the root,
# which is ``position:relative; overflow:hidden``). Absolutely-positioned,
# pointer-events:none, clipped to the card. No archetype HTML edits required.
# ---------------------------------------------------------------------------

# Grayscale, tileable SVG textures (data URIs). Rendered white-on-transparent
# and blended, so they read as subtle surface texture on the dark-first grounds
# and stay faint (never opaque) over copy.
_TEX_TILES: dict[str, str] = {
    "grain": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
        "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' "
        "numOctaves='2' stitchTiles='stitch'/></filter>"
        "<rect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/></svg>"
    ),
    "dots": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18'>"
        "<circle cx='3' cy='3' r='1.4' fill='white'/></svg>"
    ),
    "grid": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32'>"
        "<path d='M32 0H0V32' fill='none' stroke='white' stroke-width='1'/></svg>"
    ),
    "hatch": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14'>"
        "<path d='M-2 16L16 -2' stroke='white' stroke-width='1.4'/></svg>"
    ),
    "crosshatch": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16'>"
        "<path d='M-2 18L18 -2M-2 -2L18 18' stroke='white' stroke-width='1.1'/></svg>"
    ),
    "halftone": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22'>"
        "<circle cx='6' cy='6' r='3.2' fill='white'/>"
        "<circle cx='17' cy='17' r='1.6' fill='white'/></svg>"
    ),
    "weave": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20'>"
        "<rect x='0' y='8' width='20' height='3' fill='white'/>"
        "<rect x='8' y='0' width='3' height='20' fill='white'/></svg>"
    ),
    "scanline": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='6' height='6'>"
        "<rect width='6' height='1' fill='white'/></svg>"
    ),
    "carbon": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'>"
        "<path d='M0 8L8 0' stroke='white' stroke-width='1'/>"
        "<path d='M-2 2L2 -2' stroke='white' stroke-width='1'/>"
        "<path d='M6 10L10 6' stroke='white' stroke-width='1'/></svg>"
    ),
    "chevron": (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='12'>"
        "<path d='M0 12L12 3L24 12' fill='none' stroke='white' stroke-width='1.4'/></svg>"
    ),
}

# Texture tile background-size (px). Halftone/grain tile larger for presence.
_TEX_SIZE: dict[str, int] = {
    "grain": 160,
    "dots": 18,
    "grid": 32,
    "hatch": 14,
    "crosshatch": 16,
    "halftone": 22,
    "weave": 20,
    "scanline": 6,
    "carbon": 8,
    "chevron": 24,
}


def _ground_layer(ground: str, alpha: float) -> str:
    """A darken-only atmospheric overlay (CSS ``background`` value), or ''.

    All gradients fade to fully transparent, so the lit area keeps the
    archetype's own ground; only edges/surrounds darken — which never lowers
    contrast for light copy and stays gentle enough for dark copy.
    """
    a = round(alpha, 3)
    if ground == "flat":
        return ""
    if ground == "vignette":
        return f"radial-gradient(115% 95% at 50% 45%, rgba(0,0,0,0) 52%, rgba(0,0,0,{a}) 100%)"
    if ground == "spotlight":
        return f"radial-gradient(60% 50% at 50% 38%, rgba(0,0,0,0) 0%, rgba(0,0,0,{a}) 100%)"
    if ground == "top_fade":
        return f"linear-gradient(180deg, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 44%)"
    if ground == "bottom_fade":
        return f"linear-gradient(0deg, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 44%)"
    if ground == "corner_fade":
        return f"radial-gradient(125% 125% at 100% 100%, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 55%)"
    if ground == "twotone":
        # Soft diagonal half-darken (no hard edge → no banded text).
        return f"linear-gradient(122deg, rgba(0,0,0,0) 46%, rgba(0,0,0,{a}) 92%)"
    if ground == "dual_fade":
        # Both ends darken toward a lit centre band — symmetric letterbox feel.
        return (
            f"linear-gradient(180deg, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 30%, "
            f"rgba(0,0,0,0) 70%, rgba(0,0,0,{a}) 100%)"
        )
    if ground == "top_corner_fade":
        return f"radial-gradient(125% 125% at 0% 0%, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 55%)"
    if ground == "edge_frame":
        # All four edges darken via two crossed axis fades (lit centre).
        return (
            f"linear-gradient(90deg, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 18%, "
            f"rgba(0,0,0,0) 82%, rgba(0,0,0,{a}) 100%),"
            f"linear-gradient(180deg, rgba(0,0,0,{a}) 0%, rgba(0,0,0,0) 18%, "
            f"rgba(0,0,0,0) 82%, rgba(0,0,0,{a}) 100%)"
        )
    if ground == "diagonal_fade":
        # Mirror of twotone — darkens the top-left wedge instead of bottom-right.
        return f"linear-gradient(122deg, rgba(0,0,0,{a}) 8%, rgba(0,0,0,0) 54%)"
    return ""


def pack_overlay_html(pack: StylePack, *, width: int, height: int) -> str:
    """Build the overlay markup for ``pack`` (the ``{{ACCENT_DECORATION}}`` fill).

    Returns ``""`` for the bare pack so an undecorated card is byte-identical to
    the no-pack render. Geometry paints in ``var(--mh-accent)`` (defined in the
    injected ``:root{}``); ground/texture use neutral alphas. Everything is
    absolute + ``pointer-events:none``, clipped to the card root.
    """
    if pack.is_bare:
        return ""
    bold = pack.density == "bold"
    layers: list[str] = []

    # 1) Ground atmosphere (z-index 1: above the root fill, below content).
    ground_css = _ground_layer(pack.ground, alpha=(0.34 if bold else 0.24))
    if ground_css:
        layers.append(
            f'<div style="position:absolute;inset:0;z-index:1;pointer-events:none;'
            f'background:{ground_css};"></div>'
        )

    # 2) Surface texture (a faint, blended tile — the grain precedent).
    if pack.texture != "none":
        tile = _TEX_TILES.get(pack.texture, "")
        size = _TEX_SIZE.get(pack.texture, 20)
        if tile:
            opacity = (
                (0.16 if bold else 0.10) if pack.texture != "grain" else (0.18 if bold else 0.12)
            )
            layers.append(
                f'<div style="position:absolute;inset:0;z-index:6;pointer-events:none;'
                f"background-image:url(&quot;{tile}&quot;);background-size:{size}px {size}px;"
                f'background-repeat:repeat;opacity:{opacity};mix-blend-mode:overlay;"></div>'
            )

    # 3) Accent geometry (z-index 8: above texture, confined to the margins).
    geo = _accent_geometry_html(pack.accent_geo, width, height, bold)
    if geo:
        layers.append(geo)

    return "".join(layers)


def _accent_geometry_html(style: str, width: int, height: int, bold: bool) -> str:
    """Accent-coloured framing geometry, drawn only in the safe margins."""
    if style == "none":
        return ""
    acc = "var(--mh-accent)"
    mult = 1.35 if bold else 1.0
    weight = max(3, int(min(width, height) * 0.006 * mult))
    z = "z-index:8;pointer-events:none;"
    if style == "corner_ticks":
        arm = int(min(width, height) * 0.085 * mult)
        off = int(min(width, height) * 0.05)
        return (
            f'<div style="position:absolute;left:{off}px;top:{off}px;width:{arm}px;height:{arm}px;'
            f'border-top:{weight}px solid {acc};border-left:{weight}px solid {acc};{z}"></div>'
            f'<div style="position:absolute;right:{off}px;bottom:{off}px;width:{arm}px;height:{arm}px;'
            f'border-bottom:{weight}px solid {acc};border-right:{weight}px solid {acc};{z}"></div>'
        )
    if style == "corner_blocks":
        sq = int(min(width, height) * 0.05 * mult)
        off = int(min(width, height) * 0.045)
        op = 0.92 if bold else 0.8
        return (
            f'<div style="position:absolute;left:{off}px;top:{off}px;width:{sq}px;height:{sq}px;'
            f'background:{acc};opacity:{op};{z}"></div>'
            f'<div style="position:absolute;right:{off}px;bottom:{off}px;width:{sq}px;height:{sq}px;'
            f'background:{acc};opacity:{op};{z}"></div>'
        )
    if style == "frame":
        inset = int(min(width, height) * 0.035)
        op = 0.7 if bold else 0.5
        return (
            f'<div style="position:absolute;left:{inset}px;right:{inset}px;top:{inset}px;'
            f'bottom:{inset}px;border:{weight}px solid {acc};opacity:{op};{z}"></div>'
        )
    if style == "side_rule":
        bar_w = max(5, int(width * 0.012 * mult))
        inset = int(height * 0.10)
        return (
            f'<div style="position:absolute;left:0;top:{inset}px;bottom:{inset}px;width:{bar_w}px;'
            f'background:{acc};{z}"></div>'
        )
    if style == "baseline_rule":
        bar_h = max(5, int(height * 0.009 * mult))
        inset = int(width * 0.08)
        bottom = int(height * 0.06)
        return (
            f'<div style="position:absolute;left:{inset}px;right:{inset}px;bottom:{bottom}px;'
            f'height:{bar_h}px;background:{acc};{z}"></div>'
        )
    if style == "wedge":
        size = int(min(width, height) * 0.16 * mult)
        return (
            f'<div style="position:absolute;right:0;top:0;width:0;height:0;'
            f"border-top:{size}px solid {acc};border-left:{size}px solid transparent;"
            f'{z}"></div>'
        )
    if style == "ring":
        d = int(min(width, height) * 0.16 * mult)
        off = int(min(width, height) * 0.06)
        op = 0.85 if bold else 0.65
        return (
            f'<div style="position:absolute;right:{off}px;top:{off}px;width:{d}px;height:{d}px;'
            f'border:{weight}px solid {acc};border-radius:50%;opacity:{op};{z}"></div>'
        )
    if style == "double_rule":
        bar_h = max(4, int(height * 0.007 * mult))
        inset = int(width * 0.08)
        bottom = int(height * 0.06)
        gap = bar_h * 3
        return (
            f'<div style="position:absolute;left:{inset}px;right:{inset}px;bottom:{bottom}px;'
            f'height:{bar_h}px;background:{acc};{z}"></div>'
            f'<div style="position:absolute;left:{inset}px;right:{inset}px;bottom:{bottom + gap}px;'
            f'height:{bar_h}px;background:{acc};opacity:0.55;{z}"></div>'
        )
    if style == "dot_row":
        d = max(7, int(min(width, height) * 0.013 * mult))
        bottom = int(height * 0.065)
        gap = d * 2
        dots = "".join(
            f'<span style="width:{d}px;height:{d}px;border-radius:50%;background:{acc};'
            f'display:inline-block;"></span>'
            for _ in range(6)
        )
        return (
            f'<div style="position:absolute;left:0;right:0;bottom:{bottom}px;display:flex;'
            f'justify-content:center;gap:{gap}px;{z}">{dots}</div>'
        )
    if style == "cross_ticks":
        arm = int(min(width, height) * 0.028 * mult)
        off = int(min(width, height) * 0.06)

        def _cross(x_css: str, y_css: str) -> str:
            return (
                f'<div style="position:absolute;{x_css};{y_css};width:{arm * 2}px;height:{weight}px;'
                f'background:{acc};{z}"></div>'
                f'<div style="position:absolute;{x_css};{y_css};width:{weight}px;height:{arm * 2}px;'
                f'background:{acc};{z}"></div>'
            )

        return _cross(f"left:{off}px", f"top:{off}px") + _cross(f"right:{off}px", f"bottom:{off}px")
    if style == "corner_arc":
        arm = int(min(width, height) * 0.11 * mult)
        off = int(min(width, height) * 0.05)
        return (
            f'<div style="position:absolute;left:{off}px;top:{off}px;width:{arm}px;height:{arm}px;'
            f"border-top:{weight}px solid {acc};border-left:{weight}px solid {acc};"
            f'border-top-left-radius:100%;{z}"></div>'
            f'<div style="position:absolute;right:{off}px;bottom:{off}px;width:{arm}px;height:{arm}px;'
            f"border-bottom:{weight}px solid {acc};border-right:{weight}px solid {acc};"
            f'border-bottom-right-radius:100%;{z}"></div>'
        )
    return ""


__all__ = [
    "GROUNDS",
    "TEXTURES",
    "ACCENT_GEOS",
    "DENSITIES",
    "StylePack",
    "Template",
    "normalise_pack",
    "list_style_packs",
    "style_pack_count",
    "style_pack_from_id",
    "pick_style_pack",
    "pick_style_pack_avoiding",
    "pick_style_pack_for_card",
    "list_templates",
    "template_count",
    "template_from_id",
    "pick_template",
    "pack_overlay_html",
]
