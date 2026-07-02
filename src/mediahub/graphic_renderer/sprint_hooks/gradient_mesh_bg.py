"""Gradient-mesh background render hook (roadmap G1.8).

Auto-discovered post-render transform (see ``sprint_hooks/__init__``). It paints
the deterministic, brand-keyed gradient mesh from :mod:`graphic_renderer.gradient_mesh`
behind a card's content — but only when the brief explicitly opts in via
``background_style``. With every other brief it returns the HTML unchanged, so the
seam stays a no-op and existing renders are byte-identical (the roadmap's 🟢
ISOLATED guarantee for G1.8).

Opt-in contract (``brief.background_style``):

* ``"gradient_mesh"`` / ``"gradient-mesh"`` / ``"mesh"`` — mesh on, mode chosen
  deterministically from the card seed.
* ``"gradient_mesh:radial"`` (``:linear`` / ``:conic``) — force a specific mode.

The reachable production emitter is the style-pack bridge
(``creative_brief.generator._sync_background_style_with_pack``): a card whose
deterministic style pack carries the ``gradient_mesh`` *ground* lever gets the
bare token, so the engine paints the brand-role mesh as the card ground and the
pack's darken-only pools read as atmosphere over it — one composed treatment.

The mesh is injected as a ``background-image`` override on the card's existing
ground element rather than as a floating overlay: v1 layouts paint their ground on
a dedicated ``.bg-gradient`` / ``.bg-primary`` child of an ``isolation:isolate``
``.canvas`` (so a body-level layer can't slot between ground and content), and v2
archetypes paint ``background: var(--mh-primary)`` on their root. Overriding the
ground's image keeps the mesh exactly where the flat ground was — under every
content layer — in both cases. The mesh SVG's own opaque base rect is the brand
ground, so the swap is seamless.

This deliberately stays decoupled from archetype internals (the seam's whole
point): it targets the *ground role* — the root and the v1 ground helpers — never
an archetype's private class names. So every flat-ground archetype and every v1
layout takes the full mesh, while a few panel/split/photo archetypes that tile
their frame with opaque brand-ground *furniture* (e.g. a masthead band or a
split-stage panel) keep that furniture solid-brand and show the mesh on the root
ground beneath it — which is the coherent "brand is sacred, application is yours"
read, and is exactly the kind of card where a flat mesh ground was the least
appropriate anyway.
"""

from __future__ import annotations

from . import RenderHookCtx

# Run early: the mesh is the deepest background layer, so later hooks (overlays,
# badges, inspection) compose on top of it.
ORDER = 20

# Accepted ``background_style`` opt-in tokens (before any ``:mode`` suffix).
_TRIGGERS = frozenset({"gradient_mesh", "gradient-mesh", "mesh"})


def _seed_for(brief) -> str:
    """A stable per-card seed so one card always renders one mesh.

    Keyed to the *stable* card identity (``content_item_id``) and its design
    signature (``variation_signature``) — never ``brief.id``, which is a fresh
    uuid per generation and would re-roll the mesh on every reload. This mirrors
    ``creative_brief.auto_variation_seed_for``: same card → same seed (identical
    on reload), different cards → different seeds (variety within a pack).
    """
    parts = [
        val.strip()
        for attr in ("content_item_id", "variation_signature")
        if isinstance((val := getattr(brief, attr, None)), str) and val.strip()
    ]
    if parts:
        return "|".join(parts)
    # Last resort: a stable digest of the palette so output stays deterministic.
    palette = getattr(brief, "palette", None) or {}
    return "|".join(f"{k}={palette[k]}" for k in sorted(palette)) or "mesh"


def _intensity_for(brief) -> float:
    """Map the brief's ``decoration_strength`` to a mesh intensity.

    A stoic, low-decoration card gets a subtler field; a celebratory one gets
    more tonal spread — the engine APCA-clamps either way.
    """
    try:
        strength = float(getattr(brief, "decoration_strength", 0.5))
    except (TypeError, ValueError):
        strength = 0.5
    return max(0.2, min(0.85, 0.30 + 0.55 * strength))


def _ground_selectors(is_v2: bool) -> str:
    """The CSS selector list whose ``background-image`` the mesh replaces.

    v2 → the archetype root (``body > div:first-child``, whose own background is
    the ground). v1 → the dedicated ground divs inside ``.canvas``. We emit both
    the v2 and v1 selectors regardless (harmless when one shape is absent), with
    the layout's own kind listed first, so an exotic family still gets the mesh.
    """
    v2 = "body > div:first-child"
    v1 = ".canvas .bg-gradient, .canvas .bg-primary, .bg-gradient, .bg-primary"
    return f"{v2}, {v1}" if is_v2 else f"{v1}, {v2}"


def apply(html: str, ctx: RenderHookCtx) -> str:
    raw = (getattr(ctx.brief, "background_style", "") or "").strip().lower()
    if not raw:
        return html
    base, _, mode_hint = raw.partition(":")
    if base not in _TRIGGERS:
        return html  # opt out — this brief didn't ask for the mesh

    # Lazy imports: the engine + the role resolver. Deferred so the module loads
    # cheaply at discovery time and to avoid any import cycle with ``render``.
    from mediahub.graphic_renderer.gradient_mesh import (
        MESH_MODES,
        MeshRoles,
        mesh_data_uri,
        mesh_mode_for_seed,
    )
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    role_vars = resolved_role_vars_for_brief(ctx.brief)
    roles = MeshRoles.from_role_vars(role_vars)
    seed = _seed_for(ctx.brief)
    intensity = _intensity_for(ctx.brief)
    # Resolve "auto" to the concrete mode the engine would pick, so the
    # explainability marker reports the real mode (not "auto"). Passing the
    # concrete mode yields byte-identical output (the engine resolves the same).
    resolved_mode = mode_hint if mode_hint in MESH_MODES else mesh_mode_for_seed(seed)

    uri = mesh_data_uri(
        roles, ctx.width, ctx.height, mode=resolved_mode, seed=seed, intensity=intensity
    )

    selectors = _ground_selectors(ctx.is_v2)
    style = (
        f"<!-- mh:gradient-mesh G1.8 mode={resolved_mode} -->"
        f'<style data-mh-mesh-bg="{resolved_mode}">'
        f"{selectors}{{"
        f"background-image:{uri} !important;"
        "background-size:cover !important;"
        "background-position:center !important;"
        "background-repeat:no-repeat !important;"
        "}"
        "</style>"
    )
    return html.replace("</body>", style + "</body>", 1)
