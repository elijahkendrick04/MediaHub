"""G1.26 — the live archetype × style-pack preview gallery ("Template previews").

Distinct from G1.27's ``/studio`` interactive design *editor* (``web.design_editor``):
this is the browse-only catalog of the whole template space.

Where UI 1.10's ``/templates`` gallery (``web.template_gallery``) shows *schematic*
wireframes of the structural archetypes, this surface shows **live, rendered
preview thumbnails** of the full combinatorial template space — every archetype
crossed with every style pack (``graphic_renderer.archetypes`` ×
``graphic_renderer.style_packs``) — so an operator can actually see what the
engine's compositions look like before creating a pack.

The space is large (20 archetypes × 1,448 packs ≈ 29,000 templates), so the
gallery is a two-axis **explorer**, not a flat 29k-thumbnail wall:

* **Every archetype** — all 20 archetypes, each rendered with the currently
  *pinned* style pack. Pick one to pin it.
* **Every style pack** — the packs (filterable by ground / texture / accent /
  density, paginated), each rendered against the currently *pinned* archetype.
  Pick one to pin it.

Pinning is plain query state (``?archetype=…&pack=…``), so the two rails
cross-reference, every view is shareable, and it works with JavaScript off.
Thumbnails are lazy-loaded live renders served + disk-cached by the ``web.py``
thumb route; a genuine render failure (or a browser-less environment) degrades to
the archetype's honest, self-contained schematic — served by the same route, so
the gallery is never broken.

Everything here is pure / Flask-free so it unit-tests without a request: the route
passes resolved ``url_for(...)`` strings + a thumb-URL builder in, and wraps the
returned body with ``_layout``. It reuses the UI 1.10 helper (categories,
humanize, schematic inner SVG) so the two gallery surfaces never drift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlencode

from markupsafe import escape

from mediahub.graphic_renderer import archetypes as _arch
from mediahub.graphic_renderer import style_packs as _sp
from mediahub.web import template_gallery as _ui110

# ---------------------------------------------------------------------------
# State model — every knob is plain, validated query state.
# ---------------------------------------------------------------------------

# The four orthogonal style-pack levers, in the order they read on the card.
# ``accent`` is the query/UI name for the StylePack ``accent_geo`` field.
LEVERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ground", "Ground", _sp.GROUNDS),
    ("texture", "Texture", _sp.TEXTURES),
    ("accent", "Accent", _sp.ACCENT_GEOS),
    ("density", "Density", _sp.DENSITIES),
)
_LEVER_VOCAB: dict[str, tuple[str, ...]] = {key: vocab for key, _, vocab in LEVERS}

# The sentinel "no filter on this lever" value (kept out of every vocab on
# purpose, so it can never collide with a real lever value).
ANY = "any"

# Default page size for the (large) style-pack rail. Small enough that a cold
# first view only fires a bounded burst of live renders (each then disk-cached),
# and the lazy-loading defers everything below the fold.
PER_DEFAULT = 12
_PER_MAX = 48

# A strong, photogenic archetype to land on first. Falls back to the first
# registered archetype if this one is ever retired.
_PREFERRED_DEFAULT_ARCHETYPE = "split_diagonal_hero"


def default_archetype() -> str:
    """The archetype the gallery pins when none is requested."""
    names = _arch.list_archetypes()
    if not names:
        return ""
    return _PREFERRED_DEFAULT_ARCHETYPE if _PREFERRED_DEFAULT_ARCHETYPE in names else names[0]


def default_pack() -> str:
    """The pack the gallery pins when none is requested — the bare (undecorated)
    pack, which renders the archetype's own composition with no overlay."""
    packs = _sp.list_style_packs()
    return packs[0].id if packs else ""


def valid_archetype(name: str | None) -> str:
    """Coerce a (possibly user-supplied) archetype to a registered one.

    Anything not a real archetype collapses to :func:`default_archetype`, so a
    junk ``?archetype=`` can never render an unknown layout or 500.
    """
    name = (name or "").strip()
    return name if name in set(_arch.list_archetypes()) else default_archetype()


def valid_pack(pack_id: str | None) -> str:
    """Coerce a (possibly user-supplied) pack id to a real one, else the bare pack."""
    pack = _sp.style_pack_from_id((pack_id or "").strip())
    return pack.id if pack else default_pack()


def valid_lever(kind: str, value: str | None) -> str:
    """Coerce a lever filter value to a member of its vocabulary, or :data:`ANY`."""
    vocab = _LEVER_VOCAB.get(kind, ())
    v = (value or "").strip().lower()
    return v if v in vocab else ANY


def lever_label(value: str) -> str:
    """Friendly display label for a lever value (``"corner_ticks"`` → ``"Corner Ticks"``)."""
    if value == ANY:
        return "Any"
    return value.replace("_", " ").title()


def filter_packs(
    ground: str = ANY, texture: str = ANY, accent: str = ANY, density: str = ANY
) -> list[_sp.StylePack]:
    """The catalog packs matching the active lever filters, in catalog order.

    A lever set to :data:`ANY` does not constrain; the unfiltered call returns
    the whole catalog. A specific combination may legitimately match nothing
    (e.g. a heavy ground + heavy accent that the coherence cap pruned) — callers
    handle the empty rail.
    """
    out: list[_sp.StylePack] = []
    for p in _sp.list_style_packs():
        if ground != ANY and p.ground != ground:
            continue
        if texture != ANY and p.texture != texture:
            continue
        if accent != ANY and p.accent_geo != accent:
            continue
        if density != ANY and p.density != density:
            continue
        out.append(p)
    return out


def filters_active(ground: str, texture: str, accent: str, density: str) -> bool:
    """True when any lever filter is narrowing the pack rail."""
    return any(v != ANY for v in (ground, texture, accent, density))


@dataclass(frozen=True)
class Page:
    """One slice of a filtered sequence for the paginated pack rail."""

    items: list
    page: int
    pages: int
    total: int
    per: int

    @property
    def start(self) -> int:
        """1-based index of the first item on this page (0 when empty)."""
        return 0 if self.total == 0 else (self.page - 1) * self.per + 1

    @property
    def end(self) -> int:
        """1-based index of the last item on this page."""
        return min(self.total, self.page * self.per)


def paginate(seq, page: int, per: int = PER_DEFAULT) -> Page:
    """Clamp ``page`` into range and return that slice. ``page`` is 1-based."""
    per = max(1, min(int(per or PER_DEFAULT), _PER_MAX))
    total = len(seq)
    pages = max(1, math.ceil(total / per))
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * per
    return Page(items=list(seq[start : start + per]), page=page, pages=pages, total=total, per=per)


@dataclass(frozen=True)
class StudioState:
    """The fully-validated gallery state, derived once per request."""

    archetype: str
    pack: str
    category: str
    ground: str
    texture: str
    accent: str
    density: str
    page: int
    per: int


def normalise_state(raw: dict | None) -> StudioState:
    """Validate raw query params into a :class:`StudioState`.

    Every field is coerced to a safe, known value so the rest of the module —
    and the renderer — only ever sees catalog members. Used by the route and
    directly testable without a request.
    """
    raw = raw or {}

    def _get(key: str) -> str:
        return str(raw.get(key, "") or "")

    try:
        page = int(_get("page") or "1")
    except (TypeError, ValueError):
        page = 1
    try:
        per = int(_get("per") or PER_DEFAULT)
    except (TypeError, ValueError):
        per = PER_DEFAULT
    return StudioState(
        archetype=valid_archetype(_get("archetype")),
        pack=valid_pack(_get("pack")),
        category=_ui110.valid_category(_get("category")),
        ground=valid_lever("ground", _get("ground")),
        texture=valid_lever("texture", _get("texture")),
        accent=valid_lever("accent", _get("accent")),
        density=valid_lever("density", _get("density")),
        page=max(1, page),
        per=max(1, min(per, _PER_MAX)),
    )


# ---------------------------------------------------------------------------
# Self-contained schematic — the live thumb's honest fallback.
#
# The UI 1.10 schematic SVG styles its shapes via CSS classes defined in
# web.py's stylesheet. That works for an *inline* SVG, but an SVG loaded as an
# <img> src is isolated from page CSS, so it would render unstyled. The thumb
# route serves this self-contained variant (inline <style>, concrete theme
# colours) when a live render is unavailable, so the <img> still shows an
# honest wireframe of the archetype rather than a broken tile.
# ---------------------------------------------------------------------------

_SCHEMATIC_STYLE = (
    ".gd{fill:#11131b}.sf{fill:#1b1e28}.paper{fill:#ece7da}.ph{fill:#313643}"
    ".ac{fill:var(--lane,#d4ff3a)}.onac{fill:#0a0b11}.ik{fill:#5b6172}.ik2{fill:#aeb4c6}"
    ".dk{fill:#2a2e3a}.ln{stroke:#2a2e3a;stroke-width:1}"
    ".acln{fill:none;stroke:var(--lane,#d4ff3a);stroke-width:2}"
    ".dkln{stroke:#9a907c;stroke-width:1}.ln-f{fill:none;stroke:#2a2e3a;stroke-width:1}"
)


def standalone_schematic_svg(name: str) -> str:
    """A complete, self-contained schematic SVG document for ``name``.

    Reuses the UI 1.10 schematic shapes but bakes the theme colours into an
    inline ``<style>`` so it renders correctly when loaded as an ``<img>`` src
    (the live-thumb fallback). Returns a full ``<svg>…</svg>`` string.
    """
    inner = _ui110._SVG.get(name, _ui110._GENERIC_SVG)
    label = f"{_ui110.humanize(name)} layout — schematic preview"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150" '
        'role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="{escape(label)}">'
        f"<style>{_SCHEMATIC_STYLE}</style>{inner}</svg>"
    )


# ---------------------------------------------------------------------------
# HTML rendering — returns a body string the route wraps with _layout.
# ---------------------------------------------------------------------------


def _e(value) -> str:
    """Escape to a plain ``str`` (avoids Markup re-escaping on concat)."""
    return str(escape(value))


def _query(state: StudioState, **over) -> str:
    """A clean, state-preserving query string (with leading ``?``).

    The two pins (archetype + pack) are always emitted so a link is explicit and
    shareable; filters and page only when they differ from their defaults, so the
    URL stays readable. ``over`` overrides individual fields (e.g. pinning a new
    archetype) — a filter change should pass ``page=1`` to reset the pack rail.
    """
    cur = {
        "archetype": state.archetype,
        "pack": state.pack,
        "category": state.category,
        "ground": state.ground,
        "texture": state.texture,
        "accent": state.accent,
        "density": state.density,
        "page": state.page,
    }
    cur.update(over)
    pairs: list[tuple[str, str]] = [("archetype", cur["archetype"]), ("pack", cur["pack"])]
    if cur["category"] != "all":
        pairs.append(("category", cur["category"]))
    for key in ("ground", "texture", "accent", "density"):
        if cur[key] != ANY:
            pairs.append((key, cur[key]))
    if int(cur["page"]) > 1:
        pairs.append(("page", str(cur["page"])))
    return "?" + urlencode(pairs)


def _hero(n_arch: int, n_packs: int, n_templates: int) -> str:
    return (
        '<section class="mh-hero" data-lane="04" '
        'style="padding-top:var(--sp-9);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Template previews · live render</span>'
        f'<h1>See every <em class="editorial">template</em><br>before you make one.</h1>'
        '<p class="lede">These are <strong>live renders</strong>, not wireframes — '
        f"every one of the {n_arch} structural archetypes crossed with every one of "
        f"the {n_packs:,} style packs, for <strong>{n_templates:,} unique, on-brand "
        "templates</strong>. Pin an archetype to see it across packs, or pin a pack "
        "to see it across archetypes. The design director still picks the best one "
        "per moment automatically — this is the range it draws from.</p>"
        "</section>"
    )


def _featured(state: StudioState, *, thumb_url, make_url: str) -> str:
    """The large preview of the currently-pinned archetype × pack."""
    pack = _sp.style_pack_from_id(state.pack)
    arch_title = _ui110.humanize(state.archetype)
    cat = _ui110.category_for(state.archetype)
    pack_name = pack.name() if pack else "Clean"
    pack_why = pack.why() if pack else ""
    img = thumb_url(state.archetype, state.pack, hero=True)
    return (
        '<section class="mh-tpv-featured" aria-label="Pinned template preview">'
        '<div class="mh-tpv-featured-frame">'
        f'<img class="mh-tpv-featured-img" src="{_e(img)}" '
        f'width="560" height="700" loading="eager" decoding="async" '
        f'alt="Live preview of the {_e(arch_title)} archetype with the {_e(pack_name)} style pack"/>'
        "</div>"
        '<div class="mh-tpv-featured-meta">'
        '<span class="mh-tpv-eyebrow">Pinned template</span>'
        f'<h2 class="mh-tpv-featured-title">{_e(arch_title)}</h2>'
        f'<p class="mh-tpv-featured-sub"><span class="mh-arch-tag" data-cat="{_e(cat)}">'
        f"{_e(_ui110.category_label(cat))}</span> <code>{_e(state.archetype)}</code></p>"
        f'<p class="mh-tpv-pack-name">{_e(pack_name)}</p>'
        f'<p class="mh-tpv-pack-why">{_e(pack_why)}</p>'
        f'<code class="mh-tpv-pack-id">{_e(state.pack)}</code>'
        '<div class="mh-tpv-featured-cta">'
        f'<a class="btn" href="{_e(make_url)}">Create a pack &rarr;</a>'
        '<span class="dim">The engine auto-selects per card — you don\'t pick by hand.</span>'
        "</div>"
        "</div>"
        "</section>"
    )


def _category_chips(state: StudioState, *, studio_url: str, entries: list[dict]) -> str:
    """Archetype-category filter chips (All + each category), with counts."""
    counts = _ui110.category_counts(entries)
    rows = [("all", "All")] + [(cid, label) for cid, label, _ in _ui110.CATEGORIES]
    chips = []
    for cid, label in rows:
        href = studio_url + _query(state, category=cid, page=1)
        is_active = cid == state.category
        cls = "mh-arch-chip is-active" if is_active else "mh-arch-chip"
        cur = ' aria-current="true"' if is_active else ""
        chips.append(
            f'<a class="{cls}" href="{_e(href)}" data-cat="{_e(cid)}"{cur}>'
            f"{_e(label)}"
            f'<span class="mh-arch-chip-n" aria-hidden="true">{counts.get(cid, 0)}</span>'
            f'<span class="mh-arch-sr"> ({counts.get(cid, 0)} archetypes)</span>'
            "</a>"
        )
    return (
        '<div class="mh-arch-filters" role="group" aria-label="Filter archetypes by category">'
        + "".join(chips)
        + "</div>"
    )


def _archetype_rail(state: StudioState, *, studio_url: str, thumb_url, entries: list[dict]) -> str:
    """All archetypes, each previewed with the pinned pack. Click to pin."""
    chips = _category_chips(state, studio_url=studio_url, entries=entries)
    tiles = []
    for e in entries:
        name = e["name"]
        hidden = state.category != "all" and e["category"] != state.category
        pinned = name == state.archetype
        classes = "mh-tpv-tile"
        if pinned:
            classes += " is-pinned"
        if hidden:
            classes += " is-hidden"
        href = studio_url + _query(state, archetype=name)
        img = thumb_url(name, state.pack)
        badge = '<span class="mh-tpv-pin-badge">Pinned</span>' if pinned else ""
        aria = ' aria-current="true"' if pinned else ""
        tiles.append(
            f'<a class="{classes}" href="{_e(href)}" data-category="{_e(e["category"])}"{aria}>'
            '<span class="mh-tpv-thumb">'
            f'<img class="mh-tpv-img" src="{_e(img)}" width="384" height="480" '
            f'loading="lazy" decoding="async" '
            f'alt="Live preview of the {_e(e["title"])} archetype"/>'
            f"{badge}"
            "</span>"
            '<span class="mh-tpv-tile-body">'
            f'<span class="mh-tpv-tile-title">{_e(e["title"])}</span>'
            f'<span class="mh-arch-tag" data-cat="{_e(e["category"])}">'
            f"{_e(e['category_label'])}</span>"
            "</span>"
            f'<code class="mh-tpv-tile-slug">{_e(name)}</code>'
            "</a>"
        )
    empty = (
        '<p class="mh-arch-empty" id="mh-tpv-arch-empty" hidden>No archetypes in this category.</p>'
    )
    return (
        '<section class="mh-tpv-section" id="mh-tpv-archetypes" '
        f'data-active="{_e(state.category)}">'
        '<div class="mh-tpv-section-head">'
        '<h2 class="mh-tpv-h2">Every archetype</h2>'
        '<p class="mh-tpv-section-sub">All structural layouts, each rendered with '
        "the pinned style pack. Pick one to preview it across the pack catalog.</p>"
        "</div>"
        f"{chips}"
        f'<div class="mh-tpv-grid" id="mh-tpv-arch-grid">{"".join(tiles)}</div>'
        f"{empty}"
        "</section>"
    )


def _lever_form(state: StudioState, *, studio_url: str) -> str:
    """The style-pack lever filter (4 selects), as a no-JS GET form."""
    selects = []
    for key, label, vocab in LEVERS:
        cur = getattr(state, key)
        opts = [
            f'<option value="{ANY}"{" selected" if cur == ANY else ""}>Any {label.lower()}</option>'
        ]
        for v in vocab:
            sel = " selected" if v == cur else ""
            opts.append(f'<option value="{_e(v)}"{sel}>{_e(lever_label(v))}</option>')
        selects.append(
            '<label class="mh-tpv-field">'
            f'<span class="mh-tpv-field-label">{_e(label)}</span>'
            f'<select class="mh-tpv-select" name="{key}">{"".join(opts)}</select>'
            "</label>"
        )
    # Preserve the pins across a filter submit; page resets (omitted → 1).
    hidden = (
        f'<input type="hidden" name="archetype" value="{_e(state.archetype)}"/>'
        f'<input type="hidden" name="pack" value="{_e(state.pack)}"/>'
    )
    if state.category != "all":
        hidden += f'<input type="hidden" name="category" value="{_e(state.category)}"/>'
    reset_href = studio_url + _query(
        state, ground=ANY, texture=ANY, accent=ANY, density=ANY, page=1
    )
    reset = (
        f'<a class="mh-tpv-reset" href="{_e(reset_href)}">Clear filters</a>'
        if filters_active(state.ground, state.texture, state.accent, state.density)
        else ""
    )
    return (
        f'<form class="mh-tpv-filterform" method="get" action="{_e(studio_url)}" '
        'aria-label="Filter style packs">'
        f"{hidden}"
        f'<div class="mh-tpv-fields">{"".join(selects)}</div>'
        '<div class="mh-tpv-filteractions">'
        '<button type="submit" class="btn secondary">Apply filters</button>'
        f"{reset}"
        "</div>"
        "</form>"
    )


def _pager(state: StudioState, page: Page, *, studio_url: str) -> str:
    if page.pages <= 1:
        return ""
    prev_link = (
        f'<a class="mh-tpv-page-btn" href="{_e(studio_url + _query(state, page=page.page - 1))}" '
        'rel="prev">&larr; Prev</a>'
        if page.page > 1
        else '<span class="mh-tpv-page-btn is-disabled" aria-disabled="true">&larr; Prev</span>'
    )
    next_link = (
        f'<a class="mh-tpv-page-btn" href="{_e(studio_url + _query(state, page=page.page + 1))}" '
        'rel="next">Next &rarr;</a>'
        if page.page < page.pages
        else '<span class="mh-tpv-page-btn is-disabled" aria-disabled="true">Next &rarr;</span>'
    )
    return (
        '<nav class="mh-tpv-pager" aria-label="Style pack pages">'
        f"{prev_link}"
        f'<span class="mh-tpv-page-status">Page {page.page} of {page.pages}</span>'
        f"{next_link}"
        "</nav>"
    )


def _pack_rail(state: StudioState, *, studio_url: str, thumb_url) -> str:
    """The filtered, paginated style packs, each previewed on the pinned archetype."""
    matches = filter_packs(state.ground, state.texture, state.accent, state.density)
    page = paginate(matches, state.page, state.per)
    form = _lever_form(state, studio_url=studio_url)

    if page.total == 0:
        body = (
            '<p class="mh-arch-empty">No style packs match these filters — '
            "the coherence cap prunes over-decorated combinations. "
            f'<a href="{_e(studio_url + _query(state, ground=ANY, texture=ANY, accent=ANY, density=ANY, page=1))}">'
            "Clear filters</a>.</p>"
        )
        count_line = "No packs match the current filters."
    else:
        arch_title = _ui110.humanize(state.archetype)
        tiles = []
        for pack in page.items:
            pinned = pack.id == state.pack
            classes = "mh-tpv-tile mh-tpv-tile--pack"
            if pinned:
                classes += " is-pinned"
            href = studio_url + _query(state, pack=pack.id)
            img = thumb_url(state.archetype, pack.id)
            badge = '<span class="mh-tpv-pin-badge">Pinned</span>' if pinned else ""
            aria = ' aria-current="true"' if pinned else ""
            density_tag = (
                '<span class="mh-tpv-density-tag">Bold</span>' if pack.density == "bold" else ""
            )
            tiles.append(
                f'<a class="{classes}" href="{_e(href)}"{aria}>'
                '<span class="mh-tpv-thumb">'
                f'<img class="mh-tpv-img" src="{_e(img)}" width="384" height="480" '
                f'loading="lazy" decoding="async" '
                f'alt="Live preview of the {_e(pack.name())} pack on the {_e(arch_title)} archetype"/>'
                f"{badge}"
                "</span>"
                '<span class="mh-tpv-tile-body">'
                f'<span class="mh-tpv-tile-title">{_e(pack.name())}</span>'
                f"{density_tag}"
                "</span>"
                f'<code class="mh-tpv-tile-slug">{_e(pack.id)}</code>'
                "</a>"
            )
        body = f'<div class="mh-tpv-grid">{"".join(tiles)}</div>' + _pager(
            state, page, studio_url=studio_url
        )
        suffix = (
            " (filtered)"
            if filters_active(state.ground, state.texture, state.accent, state.density)
            else ""
        )
        count_line = (
            f"Showing {page.start}&ndash;{page.end} of {page.total:,} packs{suffix}, "
            f"each on the <strong>{_e(arch_title)}</strong> archetype."
        )

    return (
        '<section class="mh-tpv-section" id="mh-tpv-packs">'
        '<div class="mh-tpv-section-head">'
        '<h2 class="mh-tpv-h2">Every style pack</h2>'
        f'<p class="mh-tpv-section-sub">{count_line}</p>'
        "</div>"
        f"{form}"
        f"{body}"
        "</section>"
    )


def render_studio_body(
    *,
    studio_url: str,
    gallery_url: str,
    make_url: str,
    thumb_url,
    state: StudioState,
) -> str:
    """Render the full preview-gallery page body.

    Pure string builder. ``studio_url`` / ``gallery_url`` / ``make_url`` are
    pre-resolved ``url_for`` strings; ``thumb_url(archetype, pack_id, hero=False)``
    returns the live-thumbnail URL for a template; ``state`` is already validated
    by :func:`normalise_state`. The returned string is handed to ``_layout``.
    """
    entries = _ui110.gallery_entries()
    n_arch = len(entries)
    n_packs = _sp.style_pack_count()
    n_templates = n_packs * n_arch

    hero = _hero(n_arch, n_packs, n_templates)
    featured = _featured(state, thumb_url=thumb_url, make_url=make_url)
    arch_rail = _archetype_rail(state, studio_url=studio_url, thumb_url=thumb_url, entries=entries)
    pack_rail = _pack_rail(state, studio_url=studio_url, thumb_url=thumb_url)

    schematic_link = (
        '<p class="mh-arch-note">Prefer the structural wireframes? The '
        f'<a href="{_e(gallery_url)}">schematic template gallery</a> shows each '
        "archetype's skeleton without a live render. Your real cards use your club "
        "colours, type, logo and athletes' photos.</p>"
    )

    return (
        f"{_STUDIO_CSS}"
        '<section id="mh-tpv" class="mh-tpv">'
        f"{hero}"
        f"{schematic_link}"
        f"{featured}"
        f"{arch_rail}"
        f"{pack_rail}"
        "</section>"
        f"{_STUDIO_JS}"
    )


# Scoped styles — kept inline (a distinct, self-contained region) rather than in
# web.py's shared stylesheet, so G1.26 never collides with the UI 1.10 CSS block.
# Reuses the global theme tokens + the .mh-arch-* chip/tag classes.
_STUDIO_CSS = """<style>
.mh-tpv-eyebrow, .mh-tpv-section-sub, .mh-tpv-pack-why { font-family: var(--font-body); }
.mh-tpv-featured {
  display: grid; grid-template-columns: minmax(220px, 320px) 1fr;
  gap: var(--sp-6); align-items: start;
  padding: var(--sp-5); margin-bottom: var(--sp-7);
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: var(--radius);
}
.mh-tpv-featured-frame {
  border: 1px solid var(--hairline); border-radius: 10px; overflow: hidden;
  background: var(--bg); aspect-ratio: 4 / 5;
}
.mh-tpv-featured-img { display: block; width: 100%; height: 100%; object-fit: cover; }
.mh-tpv-featured-meta { display: flex; flex-direction: column; gap: 6px; }
.mh-tpv-eyebrow {
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--lane);
}
.mh-tpv-featured-title {
  font-family: var(--font-display); font-size: 28px; font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.01em; color: var(--ink); margin: 2px 0;
}
.mh-tpv-featured-sub { display: flex; align-items: center; gap: 8px; margin: 0 0 6px; }
.mh-tpv-featured-sub code, .mh-tpv-pack-id {
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-dim); opacity: 0.8;
}
.mh-tpv-pack-name {
  font-family: var(--font-display); font-size: 16px; font-weight: 700;
  color: var(--ink); margin: 8px 0 0; text-transform: uppercase; letter-spacing: 0.01em;
}
.mh-tpv-pack-why { font-size: 13.5px; color: var(--ink-dim); line-height: 1.55; margin: 0; }
.mh-tpv-featured-cta {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: var(--sp-4);
}
.mh-tpv-featured-cta .dim { font-size: 12px; color: var(--ink-dim); }
.mh-tpv-section { margin-bottom: var(--sp-8); }
.mh-tpv-section-head { margin-bottom: var(--sp-4); }
.mh-tpv-h2 {
  font-family: var(--font-display); font-size: 20px; font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.02em; color: var(--ink); margin: 0 0 4px;
}
.mh-tpv-section-sub { font-size: 13px; color: var(--ink-dim); line-height: 1.55; margin: 0; max-width: 70ch; }
.mh-tpv-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--sp-4); margin: var(--sp-4) 0 var(--sp-5);
}
.mh-tpv-tile {
  display: flex; flex-direction: column;
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: var(--radius); overflow: hidden; text-decoration: none;
  transition: border-color var(--transition), background var(--transition), transform var(--transition);
}
.mh-tpv-tile:hover { border-color: var(--rule); background: var(--surface-2); text-decoration: none; transform: translateY(-2px); }
.mh-tpv-tile:focus-visible { outline: 2px solid var(--lane); outline-offset: 2px; }
.mh-tpv-tile.is-pinned { border-color: var(--lane); box-shadow: 0 0 0 1px var(--lane) inset; }
.mh-tpv-tile.is-hidden { display: none; }
.mh-tpv-thumb { position: relative; display: block; aspect-ratio: 4 / 5; background: var(--bg); }
.mh-tpv-img { display: block; width: 100%; height: 100%; object-fit: cover; }
.mh-tpv-pin-badge {
  position: absolute; top: 8px; left: 8px;
  font-family: var(--font-mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--lane-ink, #0A0B11); background: var(--lane);
  padding: 3px 7px; border-radius: 999px;
}
.mh-tpv-density-tag {
  font-family: var(--font-mono); font-size: 9px; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-dim);
  border: 1px solid var(--rule); border-radius: 999px; padding: 2px 7px;
}
.mh-tpv-tile-body {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; padding: var(--sp-3) var(--sp-3) 2px;
}
.mh-tpv-tile-title {
  font-family: var(--font-display); font-size: 14px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.01em; color: var(--ink);
}
.mh-tpv-tile-slug {
  font-family: var(--font-mono); font-size: 10px; color: var(--ink-dim);
  opacity: 0.7; padding: 0 var(--sp-3) var(--sp-3); word-break: break-all;
}
.mh-tpv-filterform {
  display: flex; align-items: flex-end; gap: var(--sp-4); flex-wrap: wrap;
  padding: var(--sp-4); margin-bottom: var(--sp-4);
  background: var(--surface); border: 1px solid var(--hairline); border-radius: var(--radius);
}
.mh-tpv-fields { display: flex; gap: var(--sp-3); flex-wrap: wrap; flex: 1 1 auto; }
.mh-tpv-field { display: flex; flex-direction: column; gap: 4px; }
.mh-tpv-field-label {
  font-family: var(--font-mono); font-size: 9.5px; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-dim);
}
.mh-tpv-select {
  font-family: var(--font-body); font-size: 13px; color: var(--ink);
  background: var(--bg); border: 1px solid var(--hairline); border-radius: 8px;
  padding: 8px 10px; min-width: 140px;
}
.mh-tpv-select:focus-visible { outline: 2px solid var(--lane); outline-offset: 1px; }
.mh-tpv-filteractions { display: flex; align-items: center; gap: 14px; }
.mh-tpv-reset { font-family: var(--font-body); font-size: 12.5px; color: var(--ink-dim); }
.mh-tpv-pager {
  display: flex; align-items: center; justify-content: center; gap: var(--sp-4);
  margin-top: var(--sp-3);
}
.mh-tpv-page-btn {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; color: var(--ink); text-decoration: none;
  padding: 8px 14px; border: 1px solid var(--hairline); border-radius: 999px;
  background: var(--surface);
}
.mh-tpv-page-btn:hover { border-color: var(--rule); background: var(--surface-2); text-decoration: none; }
.mh-tpv-page-btn.is-disabled { opacity: 0.4; pointer-events: none; }
.mh-tpv-page-status { font-family: var(--font-mono); font-size: 11px; color: var(--ink-dim); font-variant-numeric: tabular-nums; }
@media (max-width: 640px) { .mh-tpv-featured { grid-template-columns: 1fr; } }
</style>"""

# Progressive enhancement: instant client-side category filtering of the
# archetype rail (the no-JS path already works — the chips are real ?category=
# links the server honours), plus auto-submit of the lever filter form on change.
# All archetype tiles are always in the DOM, so any category is reachable.
_STUDIO_JS = """<script>
(function(){
  var sec = document.getElementById('mh-tpv-archetypes');
  if(sec){
    var grid = document.getElementById('mh-tpv-arch-grid');
    var empty = document.getElementById('mh-tpv-arch-empty');
    var chips = sec.querySelectorAll('.mh-arch-chip');
    var tiles = grid ? grid.querySelectorAll('.mh-tpv-tile') : [];
    var apply = function(cat){
      cat = cat || 'all';
      var shown = 0;
      for(var i=0;i<tiles.length;i++){
        var t = tiles[i];
        var show = (cat === 'all') || (t.getAttribute('data-category') === cat);
        t.classList.toggle('is-hidden', !show);
        if(show) shown++;
      }
      for(var j=0;j<chips.length;j++){
        var ch = chips[j];
        var on = (ch.getAttribute('data-cat') === cat);
        ch.classList.toggle('is-active', on);
        if(on){ ch.setAttribute('aria-current','true'); } else { ch.removeAttribute('aria-current'); }
      }
      if(empty) empty.hidden = (shown !== 0);
    };
    for(var k=0;k<chips.length;k++){
      (function(ch){
        ch.addEventListener('click', function(ev){
          ev.preventDefault();
          var cat = ch.getAttribute('data-cat') || 'all';
          apply(cat);
          try {
            var u = new URL(window.location.href);
            if(cat === 'all'){ u.searchParams.delete('category'); }
            else { u.searchParams.set('category', cat); }
            window.history.pushState({cat:cat}, '', u.toString());
          } catch(_){}
        });
      })(chips[k]);
    }
  }
  var form = document.querySelector('.mh-tpv-filterform');
  if(form){
    var selects = form.querySelectorAll('.mh-tpv-select');
    for(var s=0;s<selects.length;s++){
      selects[s].addEventListener('change', function(){ form.submit(); });
    }
  }
})();
</script>"""


__all__ = [
    "LEVERS",
    "ANY",
    "PER_DEFAULT",
    "StudioState",
    "Page",
    "default_archetype",
    "default_pack",
    "valid_archetype",
    "valid_pack",
    "valid_lever",
    "lever_label",
    "filter_packs",
    "filters_active",
    "paginate",
    "normalise_state",
    "standalone_schematic_svg",
    "render_studio_body",
]
