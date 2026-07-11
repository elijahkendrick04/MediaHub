"""G1.27 — the interactive brief / design editor ("Studio").

A hands-on surface that lets a user tweak the four design levers of a single
still graphic — **text layers, palette, archetype and style pack** — and watch
it **re-render live**. Where the template gallery (UI 1.10) is browse-only and
the engine picks the composition per moment, the studio is the explicit,
deterministic playground: choose an archetype, dial the style-pack levers, type
the names/result, nudge the brand colours, pick a format, and the server renders
exactly that card.

It is deliberately built on the *same* deterministic pipeline as the real
content pack — ``creative_brief.CreativeBrief`` → ``graphic_renderer.render_brief``
— so what you preview here is byte-for-byte what the engine would paint from the
same brief. No fabricated people (the studio renders photoless — real imagery is
added from the media library in the full flow), no invented colours (the palette
flows through the same APCA-gated role resolver), and full explainability (the
resolved ``--mh-*`` roles, the pack's *why*, the archetype's structural
signature, and an honest notice when a colour-role assignment is rejected for
legibility).

Everything here is pure / Flask-free so it unit-tests without a request: the
routes in ``web.py`` pass the resolved ``url_for(...)`` strings + the active
profile's palette in, call :func:`build_brief_from_params` / :func:`explain`,
and shell the render through ``render_brief``. The closed vocabularies are
sourced from the engine modules (``archetypes``, ``style_packs``,
``design_spec``) so the editor can never drift from what the renderer executes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from markupsafe import escape

from mediahub.graphic_renderer import archetypes as _arch
from mediahub.graphic_renderer import style_packs as _sp

# ---------------------------------------------------------------------------
# Formats the studio offers. The v2 archetypes are authored to read at portrait
# (1080×1350) and story (1080×1920); square (1080×1080) fits via the same
# proportional autofit. Landscape is intentionally absent — extended aspect
# ratios are a separate, not-yet-built engine task (G1.3), and offering a format
# the renderer can't compose well would be dishonest.
# ---------------------------------------------------------------------------

# (id, label, (width, height))
FORMATS: tuple[tuple[str, str, tuple[int, int]], ...] = (
    ("feed_portrait", "Portrait · 4:5", (1080, 1350)),
    ("feed_square", "Square · 1:1", (1080, 1080)),
    ("story", "Story · 9:16", (1080, 1920)),
)
_FORMAT_SIZES: dict[str, tuple[int, int]] = {fid: size for fid, _, size in FORMATS}
DEFAULT_FORMAT = "feed_portrait"

# Live previews render at half native resolution for a snappy, light payload;
# the download path renders at full native size. Kept ≥ 0 and ≤ 1.
PREVIEW_SCALE = 0.5

# ---------------------------------------------------------------------------
# Editable text layers (the keys the v2 archetypes actually consume — see
# render._fill_v2_archetype / _common_replacements). Each: (key, label,
# placeholder, max_len). The renderer HTML-escapes every one of these at fill
# time, so they are XSS-safe by the time they reach the canvas; the caps here
# stop a runaway paste from bloating the brief or breaking a one-line fit.
# ---------------------------------------------------------------------------

TEXT_FIELDS: tuple[tuple[str, str, str, int], ...] = (
    ("athlete_full_name", "Athlete name", "Eira Hughes", 60),
    ("athlete_surname", "Surname (hero)", "Hughes", 28),
    ("event_name", "Event", "200m Freestyle", 48),
    ("result_value", "Result", "2:08.41", 24),
    ("achievement_label", "Achievement", "NEW PB", 24),
    ("place", "Placing", "1st", 12),
    ("meet_name", "Meet", "Manchester Open", 60),
    ("club_full", "Club", "Manchester Swimming Club", 60),
    ("hero_stat", "Emphasis line", "−0.42s on PB", 40),
)
_TEXT_MAX: dict[str, int] = {key: cap for key, _, _, cap in TEXT_FIELDS}

DEFAULT_TEXT: dict[str, str] = {
    "athlete_full_name": "Eira Hughes",
    "athlete_surname": "Hughes",
    "event_name": "200m Freestyle",
    "result_value": "2:08.41",
    "achievement_label": "NEW PB",
    "place": "1st",
    "meet_name": "Manchester Open",
    "club_full": "Manchester Swimming Club",
    "hero_stat": "",
}

# Neutral navy + gold default palette (matches BrandKit.placeholder()), used when
# no signed-in brand kit is available.
DEFAULT_PALETTE: dict[str, str] = {
    "primary": "#0E2A47",
    "secondary": "#101820",
    "accent": "#C9A227",
}
_PALETTE_KEYS: tuple[str, ...] = ("primary", "secondary", "accent")

# ---------------------------------------------------------------------------
# Friendly presentation labels for the style-pack levers. The *vocabularies*
# (which values exist) are owned by ``style_packs``; these labels are
# presentation-only metadata (the same split the template gallery uses for its
# categories). Any value missing a label falls back to a title-cased token.
# ---------------------------------------------------------------------------

_GROUND_LABELS: dict[str, str] = {
    "flat": "Flat",
    "top_fade": "Top-lit",
    "bottom_fade": "Grounded",
    "corner_fade": "Cornered",
    "vignette": "Vignette",
    "spotlight": "Spotlight",
    "twotone": "Two-tone",
    "dual_fade": "Edge-lit",
    "top_corner_fade": "Top corner",
    "edge_frame": "Edge frame",
    "diagonal_fade": "Diagonal",
}
_TEXTURE_LABELS: dict[str, str] = {
    "none": "None",
    "grain": "Grain",
    "dots": "Dots",
    "grid": "Grid",
    "hatch": "Hatch",
    "halftone": "Halftone",
    "crosshatch": "Crosshatch",
    "weave": "Weave",
    "scanline": "Scanline",
    "carbon": "Carbon",
    "chevron": "Chevron",
}
_ACCENT_GEO_LABELS: dict[str, str] = {
    "none": "None",
    "corner_ticks": "Corner ticks",
    "side_rule": "Side rule",
    "baseline_rule": "Baseline rule",
    "frame": "Frame",
    "wedge": "Wedge",
    "ring": "Ring",
    "corner_blocks": "Corner blocks",
    "double_rule": "Double rule",
    "dot_row": "Dot row",
    "cross_ticks": "Register marks",
    "corner_arc": "Corner arcs",
}
_DENSITY_LABELS: dict[str, str] = {"standard": "Standard", "bold": "Bold"}

# Colour-role assignment: which token role plays each compositional slot. "auto"
# (the empty assignment) keeps the deterministic brand-default roles. The
# token-role vocabulary is owned by ``archetypes.TOKEN_ROLES``.
_ROLE_SLOTS: tuple[tuple[str, str], ...] = (
    ("ground", "Ground"),
    ("surface", "Surface"),
    ("headline", "Headline"),
    ("accent", "Accent"),
)
_TOKEN_ROLE_LABELS: dict[str, str] = {
    "primary": "Primary",
    "secondary": "Secondary",
    "surface": "Surface",
    "accent": "Accent",
    "on_primary": "On-primary",
    "on_surface": "On-surface",
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------------
# Vocabulary accessors (for the route + the embedded client vocab)
# ---------------------------------------------------------------------------


def _label(value: str, labels: dict[str, str]) -> str:
    return labels.get(value) or value.replace("_", " ").title()


def archetype_options() -> list[dict[str, str]]:
    """``[{value, label, summary}]`` for every live v2 archetype."""
    out: list[dict[str, str]] = []
    for name in _arch.list_archetypes():
        out.append(
            {
                "value": name,
                "label": name.replace("_", " ").title(),
                "summary": _arch.archetype_summary(name) or "",
            }
        )
    return out


def _lever_options(values: tuple[str, ...], labels: dict[str, str]) -> list[dict[str, str]]:
    return [{"value": v, "label": _label(v, labels)} for v in values]


def vocabulary() -> dict[str, Any]:
    """The full closed vocabulary the editor exposes, for the client JS.

    Sourced from the engine modules so the editor can never offer a value the
    renderer would reject. Safe to JSON-embed (all values are known enum tokens
    or authored summaries).
    """
    return {
        "archetypes": archetype_options(),
        "grounds": _lever_options(_sp.GROUNDS, _GROUND_LABELS),
        "textures": _lever_options(_sp.TEXTURES, _TEXTURE_LABELS),
        "accent_geos": _lever_options(_sp.ACCENT_GEOS, _ACCENT_GEO_LABELS),
        "densities": _lever_options(_sp.DENSITIES, _DENSITY_LABELS),
        "formats": [{"value": fid, "label": label} for fid, label, _ in FORMATS],
        "token_roles": [
            {"value": r, "label": _TOKEN_ROLE_LABELS.get(r, r)} for r in _arch.TOKEN_ROLES
        ],
        "role_slots": [s for s, _ in _ROLE_SLOTS],
        "text_fields": [k for k, _, _, _ in TEXT_FIELDS],
        "defaults": {
            "text": dict(DEFAULT_TEXT),
            "palette": dict(DEFAULT_PALETTE),
            "archetype": default_archetype(),
            "format": DEFAULT_FORMAT,
        },
    }


def default_archetype() -> str:
    """A stable default archetype: ``individual_hero`` when present, else the
    first in the catalog (empty string if the library is somehow empty)."""
    names = _arch.list_archetypes()
    if "individual_hero" in names:
        return "individual_hero"
    return names[0] if names else ""


# ---------------------------------------------------------------------------
# Parameter coercion — the trust boundary. Every value a request can carry is
# coerced to a known-safe token here BEFORE it reaches the brief / renderer.
# ---------------------------------------------------------------------------


def _resolve_pack(ground: str, texture: str, accent_geo: str, density: str):
    """Resolve four levers to a **catalog-valid** ``StylePack`` (+ whether it was eased).

    The studio's independent lever dropdowns can name a combination heavier than
    the coherence weight cap the catalog enforces (``style_packs`` keeps cards
    tasteful — Bold caps at weight 3, Standard at 4). Such an over-cap pack id is
    NOT in the catalog, so the renderer's catalog lookup (``style_pack_from_id``)
    would drop it silently and paint a bare card that doesn't match the controls.

    Instead, ease deterministically to the nearest catalog pack — first relax
    Bold→Standard (same decoration, lower intensity), then shed the heaviest
    decorative lever (accent geometry, then texture) — so the preview always
    matches the chosen levers as closely as the taste cap allows, and the explain
    panel can honestly say when it eased. Returns ``(pack, eased)``.
    """
    base = _sp.normalise_pack(ground, texture, accent_geo, density)
    if base.is_bare:
        # A bare pack at any density is just the undecorated card — no easing notice.
        return _sp.normalise_pack(), False
    if _sp.style_pack_from_id(base.id) is not None:
        return base, False
    for cand in (
        _sp.normalise_pack(base.ground, base.texture, base.accent_geo, "standard"),
        _sp.normalise_pack(base.ground, base.texture, "none", "standard"),
        _sp.normalise_pack(base.ground, "none", "none", "standard"),
    ):
        if _sp.style_pack_from_id(cand.id) is not None:
            return cand, True
    return _sp.normalise_pack(), True  # worst case: the always-valid bare pack


@dataclass(frozen=True)
class StudioParams:
    """A validated studio request. Every field is renderer-safe."""

    archetype: str
    pack_id: str  # a catalog-valid style-pack id (eased from the raw levers if needed)
    pack_eased: bool  # True when the chosen levers were eased under the taste cap
    format_id: str
    palette: dict[str, str]
    text: dict[str, str]
    role_assignment: dict[str, str]
    full: bool

    @property
    def style_pack_id(self) -> str:
        return self.pack_id

    @property
    def size(self) -> tuple[int, int]:
        """CSS composition geometry — ALWAYS native, preview and download alike.

        The v2 archetypes are authored with fixed-px furniture (paddings,
        labels, the quote glyph, the scorebug cells) that only keeps its
        intended proportions at the native canvas size. Rendering the live
        preview at a shrunken geometry (the old half-scale) mis-weighted that
        furniture and clipped / wrapped / collided the result time across most
        archetypes (QA-011). The preview now composes identically to the
        download and stays light via the RASTER, not the geometry — see
        :pyattr:`render_quality` and :pyattr:`preview_raster_size`.
        """
        return _FORMAT_SIZES.get(self.format_id, _FORMAT_SIZES[DEFAULT_FORMAT])

    @property
    def render_quality(self) -> str | None:
        """Render-quality profile: a light DPR-1 ``"fast"`` capture for the live
        preview, the default profile for the full-resolution download. Both
        compose at the same native :pyattr:`size`; only the raster differs."""
        return None if self.full else "fast"

    @property
    def preview_raster_size(self) -> tuple[int, int]:
        """Final pixel size of the response image. The download keeps native
        pixels; the live preview downsamples the finished native-geometry render
        to ``PREVIEW_SCALE`` for a light, snappy payload — WITHOUT shrinking the
        composition geometry (which is what previously clipped the time)."""
        w, h = self.size
        if self.full:
            return (w, h)
        return (max(2, round(w * PREVIEW_SCALE)), max(2, round(h * PREVIEW_SCALE)))

    def signature(self) -> str:
        """A stable cache key over everything that changes the render payload.

        This keys the ``_studio_render_cache`` entry, which stores the whole
        response — the PNG *and* the explainability ``meta``. ``pack_eased`` does
        not change a single pixel (both the eased and the direct request resolve
        to the same ``pack_id``), but it DOES change ``meta.notices`` (the honest
        "levers were eased" notice). Two requests that resolve to the same pack
        by different routes — e.g. the same decorative levers at Bold (eased) vs
        Standard (direct) — would otherwise share a cache entry and be served the
        wrong notice, so ``pack_eased`` is part of the key.
        """
        payload = {
            "a": self.archetype,
            "p": self.pack_id,
            "eased": self.pack_eased,
            "f": self.format_id,
            "full": self.full,
            "pal": self.palette,
            "txt": self.text,
            "roles": self.role_assignment,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def _clean_hex(value: Any, default: str) -> str:
    """A safe 3/6-digit ``#hex`` or ``default``. Defence-in-depth: this value is
    injected into a CSS ``:root{}`` block downstream, so anything that isn't a
    plain hex (``url()``, ``;``, ``}``) is rejected here too — even though
    ``_mh_role_vars`` also re-validates."""
    if isinstance(value, str) and _HEX_RE.match(value.strip()):
        return value.strip()
    return default


def _clean_text(value: Any, cap: int) -> str:
    """Collapse whitespace and cap length. Non-strings → ``""``."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:cap].strip()


def coerce_params(raw: Any) -> StudioParams:
    """Coerce an arbitrary request dict into renderer-safe :class:`StudioParams`.

    Out-of-vocabulary archetype/format → the safe default; out-of-vocabulary
    style-pack levers → their ``normalise_pack`` defaults; non-hex palette →
    the brand default; over-long / non-string text → cleaned + capped; an
    illegal colour-role token → dropped (slot stays ``auto``). A non-dict
    ``raw`` yields an all-defaults preview request.
    """
    data: dict = raw if isinstance(raw, dict) else {}

    archetypes = _arch.list_archetypes()
    arch = data.get("archetype")
    archetype = arch if isinstance(arch, str) and arch in archetypes else default_archetype()

    fmt = data.get("format")
    format_id = fmt if isinstance(fmt, str) and fmt in _FORMAT_SIZES else DEFAULT_FORMAT

    pack = data.get("pack") if isinstance(data.get("pack"), dict) else {}
    # normalise_pack coerces each lever to its safe default; _resolve_pack then
    # eases any over-cap combination to the nearest catalog-valid pack so the
    # renderer's catalog lookup can never silently drop it.
    resolved_pack, pack_eased = _resolve_pack(
        ground=str(pack.get("ground") or ""),
        texture=str(pack.get("texture") or ""),
        accent_geo=str(pack.get("accent_geo") or ""),
        density=str(pack.get("density") or ""),
    )

    raw_pal = data.get("palette") if isinstance(data.get("palette"), dict) else {}
    palette = {k: _clean_hex(raw_pal.get(k), DEFAULT_PALETTE[k]) for k in _PALETTE_KEYS}

    raw_text = data.get("text") if isinstance(data.get("text"), dict) else {}
    text = {k: _clean_text(raw_text.get(k), _TEXT_MAX[k]) for k in _TEXT_MAX}

    raw_roles = data.get("roles") if isinstance(data.get("roles"), dict) else {}
    valid_roles = set(_arch.TOKEN_ROLES)
    role_assignment = {
        slot: raw_roles[slot]
        for slot, _ in _ROLE_SLOTS
        if isinstance(raw_roles.get(slot), str) and raw_roles[slot] in valid_roles
    }

    return StudioParams(
        archetype=archetype,
        pack_id=resolved_pack.id,
        pack_eased=pack_eased,
        format_id=format_id,
        palette=palette,
        text=text,
        role_assignment=role_assignment,
        # The light preview is the safe default; a full-resolution render must be
        # asked for with an explicit JSON boolean ``true``. Plain ``bool(...)``
        # would treat the string ``"false"`` (and any non-empty junk) as truthy
        # and quietly serve the heavier full render.
        full=data.get("full") is True,
    )


# ---------------------------------------------------------------------------
# Brief construction — bridge StudioParams → a real CreativeBrief the renderer
# executes exactly as it would in the content pack.
# ---------------------------------------------------------------------------


def build_brief_from_params(params: StudioParams, *, profile_id: str = "studio"):
    """Build a renderable ``CreativeBrief`` from coerced studio params.

    Photoless by design (``image_treatment="no-photo"``) — the studio never
    fabricates a person. The palette, archetype, style pack and colour-role
    assignment ride straight onto the brief, so ``render_brief`` paints the same
    pixels it would for an equivalent pipeline brief.
    """
    from mediahub.creative_brief.generator import CreativeBrief

    text = dict(params.text)
    hook = text.get("achievement_label") or text.get("event_name") or "MediaHub Studio"

    return CreativeBrief(
        id="studio_preview",
        content_item_id="studio",
        profile_id=profile_id or "studio",
        achievement_summary=text.get("event_name", ""),
        objective="Interactive studio preview",
        primary_hook=hook,
        confidence_label=text.get("achievement_label", ""),
        tone="data_led",
        layout_template=params.archetype,
        inspiration_pattern_id="",
        image_treatment="no-photo",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="Studio editor preview",
        text_layers=text,
        palette=dict(params.palette),
        format_priority=[params.format_id],
        photo_treatment="no-photo",
        style_pack=params.style_pack_id,
        colour_role_assignment=dict(params.role_assignment),
    )


def brand_kit_for_params(params: StudioParams):
    """A ``BrandKit`` derived from the studio palette + club text (or ``None``).

    The colours equal the brief palette, so the resolved ``--mh-*`` role set is
    identical to the palette-only path — passing this kit changes nothing about
    the colours. Its only job is to give the corner logo a meaningful lettermark
    drawn from the typed club name (e.g. ``MSC``) instead of the generic ``C``
    fallback. Returns ``None`` if the brand module is unavailable, so the render
    degrades cleanly to the palette-only path.
    """
    try:
        from mediahub.brand.kit import BrandKit
    except Exception:
        return None
    club = (params.text.get("club_full") or "").strip() or "Studio Club"
    return BrandKit(
        profile_id="studio",
        display_name=club,
        primary_colour=params.palette["primary"],
        secondary_colour=params.palette["secondary"],
        accent_colour=params.palette["accent"],
    )


def downscale_png_bytes(png: bytes, size: tuple[int, int]) -> bytes:
    """Downsample a PNG to ``size`` (high-quality Lanczos), composition intact.

    This lets the live studio preview stay a light payload while it composes at
    full native geometry (QA-011): the renderer paints the native-geometry card,
    then this shrinks only the raster. Returns the original bytes unchanged when
    Pillow is unavailable, the target is non-positive, or the image is already at
    or below the target — a preview never fails over a raster optimisation; it
    just ships the larger, equally-correct image.
    """
    try:
        import io

        from PIL import Image
    except Exception:
        return png
    try:
        tw, th = int(size[0]), int(size[1])
        if tw <= 0 or th <= 0:
            return png
        with Image.open(io.BytesIO(png)) as im:
            im.load()
            if im.width <= tw and im.height <= th:
                return png
            # match the renderer's own DPR downsample (RGBA + Lanczos + optimize)
            src = im.convert("RGBA") if im.mode != "RGBA" else im
            resized = src.resize((tw, th), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except Exception:
        return png


# ---------------------------------------------------------------------------
# Explainability — what the resolved card actually is (honest, public APIs only)
# ---------------------------------------------------------------------------

# The seven resolved role tokens, in display order, with friendly captions.
_ROLE_VAR_CAPTIONS: tuple[tuple[str, str], ...] = (
    ("--mh-primary", "Ground"),
    ("--mh-surface", "Surface"),
    ("--mh-accent", "Accent"),
    ("--mh-secondary", "Secondary"),
    ("--mh-on-primary", "Text on ground"),
    ("--mh-on-surface", "Text on surface"),
    ("--mh-outline", "Hairline"),
)


def explain(params: StudioParams) -> dict[str, Any]:
    """The explainability sidecar for a studio render.

    Returns the resolved ``--mh-*`` role tokens (the same set the renderer
    paints), the style pack's name + *why*, the archetype's structural summary,
    and an honest notice when a requested colour-role assignment was rejected by
    the deterministic APCA legibility gate. Uses only public engine APIs +
    ``resolved_role_vars_for_brief``.
    """
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    kit = brand_kit_for_params(params)
    brief = build_brief_from_params(params)
    resolved = resolved_role_vars_for_brief(brief, kit)

    notices: list[str] = []
    if params.role_assignment:
        # Re-resolve with the assignment stripped; if the two are identical the
        # gate rejected the assignment (legibility beat the art direction). The
        # medal tint applies equally to both, so the diff isolates the
        # assignment's effect.
        from dataclasses import replace as _dc_replace

        plain = build_brief_from_params(_dc_replace(params, role_assignment={}))
        if resolved_role_vars_for_brief(plain, kit) == resolved:
            notices.append(
                "Your colour-role swap was set aside to keep the text legible — "
                "the deterministic contrast gate kept the brand-default roles."
            )

    if params.pack_eased:
        notices.append(
            "Your style-pack levers were eased to stay under the taste cap — the "
            "renderer used the nearest tasteful pack shown below."
        )

    pack = _sp.style_pack_from_id(params.pack_id) or _sp.normalise_pack()
    roles = [
        {"var": var, "caption": caption, "hex": resolved.get(var, "")}
        for var, caption in _ROLE_VAR_CAPTIONS
    ]
    w, h = params.size
    return {
        "roles": roles,
        "pack": {"id": pack.id, "name": pack.name(), "why": pack.why()},
        "archetype": {
            "name": params.archetype,
            "label": params.archetype.replace("_", " ").title(),
            "summary": _arch.archetype_summary(params.archetype) or "",
        },
        "format": params.format_id,
        "width": w,
        "height": h,
        "notices": notices,
    }


# ---------------------------------------------------------------------------
# The editor page body (Flask-free; the route wraps it with _layout)
# ---------------------------------------------------------------------------


def _safe_json(obj: Any) -> str:
    """JSON for a ``<script>`` block — escape ``<`` so a value can never close
    the tag early (defence-in-depth; our values are all known tokens)."""
    return json.dumps(obj, ensure_ascii=True).replace("<", "\\u003c")


def _select(name: str, options: list[dict[str, str]], selected: str, *, attrs: str = "") -> str:
    """A theme-styled ``<select>``. ``attrs`` carries the JS binding hook
    (``data-studio="…"`` for a main control, ``data-studio-role="…"`` for a role
    slot) — passed explicitly so a control gets exactly one binding attribute."""
    opts = "".join(
        '<option value="{v}"{sel}>{label}</option>'.format(
            v=escape(o["value"]),
            sel=" selected" if o["value"] == selected else "",
            label=escape(o["label"]),
        )
        for o in options
    )
    extra = (" " + attrs) if attrs else ""
    return f'<select class="mh-studio-select" name="{escape(name)}"{extra}>{opts}</select>'


def _text_inputs() -> str:
    rows = []
    for key, label, placeholder, cap in TEXT_FIELDS:
        rows.append(
            '<label class="mh-studio-row"><span class="mh-studio-cap">{label}</span>'
            '<input class="mh-studio-input" type="text" data-studio-text="{key}" '
            'maxlength="{cap}" value="{val}" placeholder="{ph}" autocomplete="off" '
            'spellcheck="false"></label>'.format(
                label=escape(label),
                key=escape(key),
                cap=cap,
                val=escape(DEFAULT_TEXT.get(key, "")),
                ph=escape(placeholder),
            )
        )
    return "".join(rows)


def _palette_inputs(palette: dict[str, str]) -> str:
    rows = []
    captions = {"primary": "Primary", "secondary": "Secondary", "accent": "Accent"}
    for key in _PALETTE_KEYS:
        val = palette.get(key, DEFAULT_PALETTE[key])
        rows.append(
            '<label class="mh-studio-row mh-studio-colour"><span class="mh-studio-cap">{cap}</span>'
            '<span class="mh-studio-colour-pair">'
            '<input type="color" class="mh-studio-swatch" data-studio-colour="{key}" value="{val}">'
            '<input type="text" class="mh-studio-input mh-studio-hex" data-studio-hex="{key}" '
            'aria-label="{cap} colour hex" value="{val}" maxlength="7" spellcheck="false" '
            'autocomplete="off"></span></label>'.format(
                cap=escape(captions[key]), key=escape(key), val=escape(val)
            )
        )
    return "".join(rows)


def _role_inputs() -> str:
    auto = [{"value": "", "label": "Auto"}]
    role_opts = auto + [
        {"value": r, "label": _TOKEN_ROLE_LABELS.get(r, r)} for r in _arch.TOKEN_ROLES
    ]
    rows = []
    for slot, label in _ROLE_SLOTS:
        rows.append(
            '<label class="mh-studio-row"><span class="mh-studio-cap">{label}</span>{sel}</label>'.format(
                label=escape(label),
                sel=_select(
                    f"role_{slot}", role_opts, "", attrs=f'data-studio-role="{escape(slot)}"'
                ),
            )
        )
    return "".join(rows)


def render_editor_body(
    *,
    render_url: str,
    gallery_url: str,
    make_url: str,
    palette: Optional[dict[str, str]] = None,
) -> str:
    """Build the studio editor page body.

    ``render_url`` is the JSON render endpoint (``url_for`` resolved by the
    route); ``gallery_url`` / ``make_url`` link to the browse gallery and the
    create flow. ``palette`` seeds the colour controls from the signed-in
    brand kit when available (falls back to the neutral default).
    """
    pal = {k: _clean_hex((palette or {}).get(k), DEFAULT_PALETTE[k]) for k in _PALETTE_KEYS}
    archetype = default_archetype()

    arch_opts = archetype_options()
    grounds = _lever_options(_sp.GROUNDS, _GROUND_LABELS)
    textures = _lever_options(_sp.TEXTURES, _TEXTURE_LABELS)
    geos = _lever_options(_sp.ACCENT_GEOS, _ACCENT_GEO_LABELS)
    densities = _lever_options(_sp.DENSITIES, _DENSITY_LABELS)
    fmt_opts = [{"value": fid, "label": label} for fid, label, _ in FORMATS]

    pack_count = _sp.style_pack_count()
    template_count = len(arch_opts) * pack_count

    config = _safe_json(
        {
            "renderUrl": render_url,
            "previewScale": PREVIEW_SCALE,
            "defaults": {
                "archetype": archetype,
                "format": DEFAULT_FORMAT,
                "palette": pal,
                "text": DEFAULT_TEXT,
            },
            "vocab": vocabulary(),
        }
    )

    body = f"""
<div class="mh-studio" id="mh-studio">
  <header class="mh-studio-head">
    <div class="mh-studio-head-text">
      <h1 class="mh-studio-title">Design studio</h1>
      <p class="mh-studio-sub">Tweak the text, palette, archetype and style pack — the card
        re-renders live on the real engine. {template_count:,} templates
        ({len(arch_opts)} archetypes × {pack_count:,} style packs).
        <a href="{escape(gallery_url)}">Browse the gallery</a> ·
        <a href="{escape(make_url)}">Start from results</a></p>
    </div>
    <div class="mh-studio-head-actions">
      <button type="button" class="btn ghost" data-studio-action="randomise">Surprise me</button>
      <button type="button" class="btn secondary" data-studio-action="reset">Reset</button>
      <button type="button" class="btn" data-studio-action="download" disabled>Download PNG</button>
    </div>
  </header>

  <div class="mh-studio-grid">
    <aside class="mh-studio-controls" aria-label="Design controls">
      <section class="mh-studio-group">
        <h2 class="mh-studio-h2">Archetype</h2>
        {_select("archetype", arch_opts, archetype, attrs='data-studio="archetype" aria-label="Archetype"')}
        <p class="mh-studio-note" data-studio-archetype-summary></p>
      </section>

      <section class="mh-studio-group">
        <h2 class="mh-studio-h2">Style pack</h2>
        <label class="mh-studio-row"><span class="mh-studio-cap">Ground</span>{_select("ground", grounds, "flat", attrs='data-studio="ground"')}</label>
        <label class="mh-studio-row"><span class="mh-studio-cap">Texture</span>{_select("texture", textures, "none", attrs='data-studio="texture"')}</label>
        <label class="mh-studio-row"><span class="mh-studio-cap">Accent</span>{_select("accent_geo", geos, "none", attrs='data-studio="accent_geo"')}</label>
        <label class="mh-studio-row"><span class="mh-studio-cap">Density</span>{_select("density", densities, "standard", attrs='data-studio="density"')}</label>
      </section>

      <section class="mh-studio-group">
        <h2 class="mh-studio-h2">Format</h2>
        {_select("format", fmt_opts, DEFAULT_FORMAT, attrs='data-studio="format" aria-label="Format"')}
      </section>

      <section class="mh-studio-group">
        <h2 class="mh-studio-h2">Palette</h2>
        {_palette_inputs(pal)}
        <details class="mh-studio-adv">
          <summary>Colour roles (advanced)</summary>
          <p class="mh-studio-note">Reassign which brand colour plays each slot. The contrast
            gate silently keeps the brand defaults if a swap would hurt legibility.</p>
          {_role_inputs()}
        </details>
      </section>

      <section class="mh-studio-group">
        <h2 class="mh-studio-h2">Text layers</h2>
        {_text_inputs()}
      </section>
    </aside>

    <section class="mh-studio-stage" aria-label="Live preview">
      <div class="mh-studio-canvas" data-studio-canvas>
        <img class="mh-studio-preview" data-studio-img alt="Live card preview" />
        <div class="mh-studio-overlay" data-studio-overlay role="status" aria-live="polite" hidden>
          <div class="mh-studio-spinner" aria-hidden="true"></div>
          <p data-studio-status>Rendering…</p>
        </div>
      </div>
      <div class="mh-studio-explain" data-studio-explain hidden>
        <div class="mh-studio-explain-block">
          <h3 class="mh-studio-h3">Resolved palette</h3>
          <div class="mh-studio-roles" data-studio-roles></div>
        </div>
        <div class="mh-studio-explain-block">
          <h3 class="mh-studio-h3">Why this design</h3>
          <p class="mh-studio-why" data-studio-why></p>
          <ul class="mh-studio-notices" data-studio-notices></ul>
        </div>
      </div>
    </section>
  </div>

  <script type="application/json" id="mh-studio-config">{config}</script>
  <script>{_STUDIO_JS}</script>
</div>
{_STUDIO_CSS}
"""
    return body


# ---------------------------------------------------------------------------
# Scoped stylesheet — theme variables only, namespaced under .mh-studio.
# ---------------------------------------------------------------------------

_STUDIO_CSS = """
<style>
.mh-studio { max-width: 1180px; margin: 0 auto; }
.mh-studio-head { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end;
  justify-content:space-between; margin-bottom:20px; }
.mh-studio-title { font-size:1.7rem; margin:0 0 4px; letter-spacing:-0.01em; }
.mh-studio-sub { color:var(--ink-dim); margin:0; max-width:60ch; font-size:0.92rem; line-height:1.5; }
.mh-studio-sub a { color:var(--accent); text-decoration:none; }
.mh-studio-sub a:hover { text-decoration:underline; }
.mh-studio-head-actions { display:flex; gap:8px; flex-wrap:wrap; }
.mh-studio-grid { display:grid; grid-template-columns:minmax(280px, 360px) 1fr; gap:24px; align-items:start; }
.mh-studio-controls { display:flex; flex-direction:column; gap:18px; }
.mh-studio-group { background:var(--panel); border:1px solid var(--border); border-radius:var(--radius-lg);
  padding:14px 16px; }
.mh-studio-h2 { font-size:0.74rem; text-transform:uppercase; letter-spacing:0.09em;
  color:var(--ink-muted); margin:0 0 12px; }
.mh-studio-h3 { font-size:0.74rem; text-transform:uppercase; letter-spacing:0.09em;
  color:var(--ink-muted); margin:0 0 10px; }
.mh-studio-row { display:flex; align-items:center; gap:10px; margin-bottom:9px; }
.mh-studio-row:last-child { margin-bottom:0; }
.mh-studio-cap { flex:0 0 92px; font-size:0.82rem; color:var(--ink-dim); }
.mh-studio-select, .mh-studio-input { flex:1 1 auto; min-width:0; background:var(--surface);
  color:var(--ink); border:1px solid var(--border); border-radius:var(--radius-md);
  padding:7px 9px; font:inherit; font-size:0.86rem; }
.mh-studio-select { width:100%; cursor:pointer; }
.mh-studio-select:focus-visible, .mh-studio-input:focus-visible {
  outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent); }
.mh-studio-note { font-size:0.78rem; color:var(--ink-muted); margin:10px 0 0; line-height:1.45; }
.mh-studio-colour-pair { flex:1 1 auto; display:flex; gap:8px; align-items:center; }
.mh-studio-swatch { flex:0 0 38px; width:38px; height:32px; padding:0; border:1px solid var(--border);
  border-radius:var(--radius-md); background:var(--surface); cursor:pointer; }
.mh-studio-hex { flex:1 1 auto; font-family:var(--mono, ui-monospace, monospace); text-transform:uppercase; }
.mh-studio-adv { margin-top:12px; border-top:1px solid var(--border); padding-top:10px; }
.mh-studio-adv summary { cursor:pointer; font-size:0.82rem; color:var(--ink-dim); }
.mh-studio-adv[open] summary { margin-bottom:10px; }
.mh-studio-stage { position:sticky; top:16px; display:flex; flex-direction:column; gap:16px; }
.mh-studio-canvas { position:relative; display:flex; align-items:center; justify-content:center;
  background:var(--bg-deep, #06070C); border:1px solid var(--border); border-radius:var(--radius-lg);
  min-height:420px; padding:20px; overflow:hidden; }
.mh-studio-preview { max-width:100%; max-height:72vh; border-radius:6px;
  box-shadow:0 18px 50px rgba(0,0,0,0.5); display:block; }
.mh-studio-preview:not([src]) { display:none; }
.mh-studio-overlay { position:absolute; inset:0; display:flex; flex-direction:column; gap:14px;
  align-items:center; justify-content:center; background:rgba(6,7,12,0.62);
  backdrop-filter:blur(2px); color:var(--ink-dim); font-size:0.88rem; }
/* The overlay is toggled by its `hidden` attribute (showOverlay/hideOverlay).
   The `display:flex` above is an author rule that otherwise overrides the UA
   `[hidden]{display:none}`, so hideOverlay() could never actually hide it — the
   "Rendering…" layer stayed stuck over the card forever. Restore the hide. */
.mh-studio-overlay[hidden] { display:none; }
.mh-studio-overlay[data-error] { color:var(--bad); }
.mh-studio-spinner { width:30px; height:30px; border-radius:50%;
  border:3px solid var(--border); border-top-color:var(--accent); animation:mh-studio-spin 0.8s linear infinite; }
.mh-studio-overlay[data-error] .mh-studio-spinner { display:none; }
@keyframes mh-studio-spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .mh-studio-spinner { animation:none; } }
.mh-studio-explain { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.mh-studio-explain-block { background:var(--panel); border:1px solid var(--border);
  border-radius:var(--radius-lg); padding:14px 16px; }
.mh-studio-roles { display:flex; flex-wrap:wrap; gap:8px; }
.mh-studio-role { display:flex; align-items:center; gap:7px; font-size:0.74rem; color:var(--ink-dim); }
.mh-studio-role-chip { width:18px; height:18px; border-radius:4px; border:1px solid var(--border-h); }
.mh-studio-why { font-size:0.86rem; color:var(--ink); margin:0; line-height:1.5; }
.mh-studio-notices { margin:10px 0 0; padding-left:18px; }
.mh-studio-notices li { font-size:0.8rem; color:var(--warn); line-height:1.45; margin-bottom:6px; }
.mh-studio-notices:empty { display:none; }
@media (max-width: 880px) {
  .mh-studio-grid { grid-template-columns:1fr; }
  .mh-studio-stage { position:static; }
  .mh-studio-explain { grid-template-columns:1fr; }
}
</style>
"""

# ---------------------------------------------------------------------------
# Client controller — debounced live re-render against the JSON endpoint.
# ---------------------------------------------------------------------------

_STUDIO_JS = r"""
(function () {
  var root = document.getElementById('mh-studio');
  if (!root) return;
  var cfgEl = document.getElementById('mh-studio-config');
  if (!cfgEl) return;
  var CFG = JSON.parse(cfgEl.textContent);

  var img = root.querySelector('[data-studio-img]');
  var overlay = root.querySelector('[data-studio-overlay]');
  var statusEl = root.querySelector('[data-studio-status]');
  var explain = root.querySelector('[data-studio-explain]');
  var rolesEl = root.querySelector('[data-studio-roles]');
  var whyEl = root.querySelector('[data-studio-why]');
  var noticesEl = root.querySelector('[data-studio-notices]');
  var archSummaryEl = root.querySelector('[data-studio-archetype-summary]');
  var downloadBtn = root.querySelector('[data-studio-action="download"]');

  var HEX_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
  function expandHex(h) {
    // <input type="color"> only accepts #rrggbb — assigning a valid #rgb makes it
    // collapse to #000000 (black), desyncing the swatch from the colour the user
    // typed. Widen #rgb -> #rrggbb so the swatch mirrors the hex field.
    return /^#[0-9a-fA-F]{3}$/.test(h)
      ? '#' + h.slice(1).replace(/./g, function (c) { return c + c; })
      : h;
  }
  var lastBlobUrl = null;
  var reqSeq = 0;
  var debounceTimer = null;

  function val(name) {
    var el = root.querySelector('[data-studio="' + name + '"]');
    return el ? el.value : '';
  }

  function collect(full) {
    var palette = {}, text = {}, roles = {};
    ['primary', 'secondary', 'accent'].forEach(function (k) {
      var el = root.querySelector('[data-studio-hex="' + k + '"]');
      var sw = root.querySelector('[data-studio-colour="' + k + '"]');
      // A hex field left mid-edit / invalid never triggers a re-render (its input
      // handler is HEX_RE-gated), so the shown preview reflects the swatch's last
      // valid colour. Fall back to the swatch for an invalid hex so a Download (or
      // a role/text change) carries that SAME colour instead of being coerced to
      // the server default — which would ship a card that differs from the preview.
      if (el) palette[k] = HEX_RE.test(el.value) ? el.value : (sw ? sw.value : el.value);
    });
    root.querySelectorAll('[data-studio-text]').forEach(function (el) {
      text[el.getAttribute('data-studio-text')] = el.value;
    });
    root.querySelectorAll('[data-studio-role]').forEach(function (el) {
      var v = el.value;
      if (v) roles[el.getAttribute('data-studio-role')] = v;
    });
    return {
      archetype: val('archetype'),
      format: val('format'),
      pack: {
        ground: val('ground'), texture: val('texture'),
        accent_geo: val('accent_geo'), density: val('density')
      },
      palette: palette, text: text, roles: roles, full: !!full
    };
  }

  function showOverlay(msg, isError) {
    overlay.hidden = false;
    if (isError) { overlay.setAttribute('data-error', '1'); }
    else { overlay.removeAttribute('data-error'); }
    if (statusEl) statusEl.textContent = msg;
  }
  function hideOverlay() { overlay.hidden = true; overlay.removeAttribute('data-error'); }

  function paintExplain(meta) {
    if (!meta) return;
    explain.hidden = false;
    rolesEl.innerHTML = '';
    (meta.roles || []).forEach(function (r) {
      if (!r.hex) return;
      var row = document.createElement('span');
      row.className = 'mh-studio-role';
      var chip = document.createElement('span');
      chip.className = 'mh-studio-role-chip';
      chip.style.background = HEX_RE.test(r.hex) ? r.hex : 'transparent';
      var label = document.createElement('span');
      label.textContent = r.caption;
      row.appendChild(chip); row.appendChild(label);
      rolesEl.appendChild(row);
    });
    var why = '';
    if (meta.archetype && meta.archetype.label) why += meta.archetype.label + '. ';
    if (meta.pack && meta.pack.why) why += meta.pack.why;
    whyEl.textContent = why.trim();
    noticesEl.innerHTML = '';
    (meta.notices || []).forEach(function (n) {
      var li = document.createElement('li');
      li.textContent = n;
      noticesEl.appendChild(li);
    });
  }

  function updateArchetypeSummary() {
    if (!archSummaryEl) return;
    var name = val('archetype');
    var found = (CFG.vocab.archetypes || []).find(function (a) { return a.value === name; });
    archSummaryEl.textContent = found ? (found.summary || '') : '';
  }

  function render(full) {
    var seq = ++reqSeq;
    showOverlay('Rendering…', false);
    return fetch(CFG.renderUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },   // application/json is CSRF-exempt
      body: JSON.stringify(collect(full))
    }).then(function (resp) {
      return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    }).then(function (r) {
      if (seq !== reqSeq) return null;            // a newer request superseded this
      if (!r.ok || !r.data || !r.data.ok) {
        // Render error payloads carry `message`; the render-gate 429 busy payload
        // carries `user_message` (and is a "try again in a moment", not a real
        // failure). Read both so a busy worker shows its retry guidance instead of
        // a misleading, dead-end "Render failed."
        var msg = (r.data && (r.data.message || r.data.user_message)) || 'Render failed.';
        showOverlay(msg, true);
        return null;
      }
      return r.data;
    }).catch(function () {
      if (seq === reqSeq) showOverlay('Could not reach the renderer.', true);
      return null;
    });
  }

  function renderPreview() {
    render(false).then(function (data) {
      if (!data) return;
      img.src = data.image;
      hideOverlay();
      paintExplain(data.meta);
      if (downloadBtn) downloadBtn.disabled = false;
    });
  }

  function scheduleRender() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(renderPreview, 280);
  }

  // ---- control wiring ----
  root.querySelectorAll('[data-studio]').forEach(function (el) {
    el.addEventListener('change', function () { updateArchetypeSummary(); scheduleRender(); });
  });
  root.querySelectorAll('[data-studio-text]').forEach(function (el) {
    el.addEventListener('input', scheduleRender);
  });
  root.querySelectorAll('[data-studio-role]').forEach(function (el) {
    el.addEventListener('change', scheduleRender);
  });
  // colour <-> hex two-way binding
  ['primary', 'secondary', 'accent'].forEach(function (k) {
    var swatch = root.querySelector('[data-studio-colour="' + k + '"]');
    var hex = root.querySelector('[data-studio-hex="' + k + '"]');
    if (swatch && hex) {
      swatch.addEventListener('input', function () { hex.value = swatch.value.toUpperCase(); scheduleRender(); });
      hex.addEventListener('input', function () {
        if (HEX_RE.test(hex.value)) { swatch.value = expandHex(hex.value); scheduleRender(); }
      });
    }
  });

  // ---- actions ----
  function setControl(name, value) {
    var el = root.querySelector('[data-studio="' + name + '"]');
    if (el) el.value = value;
  }
  function pick(list) { return list[Math.floor(Math.random() * list.length)].value; }

  root.querySelector('[data-studio-action="randomise"]').addEventListener('click', function () {
    var v = CFG.vocab;
    setControl('archetype', pick(v.archetypes));
    setControl('ground', pick(v.grounds));
    setControl('texture', pick(v.textures));
    setControl('accent_geo', pick(v.accent_geos));
    setControl('density', pick(v.densities));
    updateArchetypeSummary();
    renderPreview();
  });

  root.querySelector('[data-studio-action="reset"]').addEventListener('click', function () {
    setControl('archetype', CFG.defaults.archetype);
    setControl('format', CFG.defaults.format);
    setControl('ground', 'flat'); setControl('texture', 'none');
    setControl('accent_geo', 'none'); setControl('density', 'standard');
    ['primary', 'secondary', 'accent'].forEach(function (k) {
      var swatch = root.querySelector('[data-studio-colour="' + k + '"]');
      var hex = root.querySelector('[data-studio-hex="' + k + '"]');
      if (swatch) swatch.value = CFG.defaults.palette[k];
      if (hex) hex.value = CFG.defaults.palette[k];
    });
    root.querySelectorAll('[data-studio-text]').forEach(function (el) {
      el.value = CFG.defaults.text[el.getAttribute('data-studio-text')] || '';
    });
    root.querySelectorAll('[data-studio-role]').forEach(function (el) { el.value = ''; });
    updateArchetypeSummary();
    renderPreview();
  });

  root.querySelector('[data-studio-action="download"]').addEventListener('click', function () {
    showOverlay('Rendering full resolution…', false);
    render(true).then(function (data) {
      // On failure render() has already put its error message on the overlay and
      // resolved to null; bail BEFORE hideOverlay() so that error stays visible
      // (mirrors renderPreview). Hiding first would erase the only feedback and
      // leave the click a silent no-op — no file, no error.
      if (!data) return;
      hideOverlay();
      var a = document.createElement('a');
      a.href = data.image;
      a.download = (val('archetype') || 'card') + '_' + val('format') + '.png';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
    });
  });

  // ---- initial paint ----
  updateArchetypeSummary();
  renderPreview();
})();
"""


__all__ = [
    "FORMATS",
    "DEFAULT_FORMAT",
    "TEXT_FIELDS",
    "DEFAULT_TEXT",
    "DEFAULT_PALETTE",
    "PREVIEW_SCALE",
    "StudioParams",
    "coerce_params",
    "build_brief_from_params",
    "brand_kit_for_params",
    "downscale_png_bytes",
    "explain",
    "vocabulary",
    "archetype_options",
    "default_archetype",
    "render_editor_body",
]
