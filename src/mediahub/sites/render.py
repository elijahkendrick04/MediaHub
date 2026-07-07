"""sites.render — SiteSpec → brand-tokened, **static** responsive HTML.

The deterministic core of the microsite engine (roadmap 1.16). It assembles one
:class:`~sites.models.SitePage` into a self-contained HTML document — brand role
vars + self-hosted fonts (:mod:`sites.theme`) + a block-per-kind renderer — that
the web layer serves publicly (cache-busted, token-routed). It is **static-first**:
the output is a plain HTML string with no external assets; the only scripting is
the small, self-contained inline JS the vetted widgets (:mod:`sites.widgets`,
Build 3) emit, stamped with a per-response CSP ``nonce``.

Block rendering is shared with the document engine: the common block kinds
(heading/text/list/table/chart/card/media/stat/kpi_row/quote/divider/spacer/
columns) are dispatched to :mod:`documents.render` (re-skinned by the site
stylesheet); the site-only kinds (hero, link buttons, card grids, sponsor strips,
QR, forms, widgets…) are rendered here.

Everything is escaped (``markupsafe``) — captions and AI prose are HTML-safe, so a
generated string can never inject markup (CLAUDE.md security focus). Numbers in
data blocks come straight from the spec (the deterministic fact base), never a
template guess.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from markupsafe import escape as _h

# Reuse the document block renderers for shared kinds.
from mediahub.documents.render import _render_block

from .models import Block, SitePage, SiteSection, SiteSpec, slugify
from .theme import resolve_role_vars, site_style

__all__ = ["render_page_html", "render_site_page"]


# ---------------------------------------------------------------------------
# Render context
# ---------------------------------------------------------------------------


def _ctx(
    *,
    role_vars: dict[str, str],
    brand_kit: Any,
    nonce: str,
    page_url: Optional[Callable[[str], str]],
    asset_url: Optional[Callable[[str], str]],
    render_form: Optional[Callable[[str, str], str]],
    render_widget: Optional[Callable[[dict, str], str]],
) -> dict:
    return {
        "role_vars": role_vars,
        "brand_kit": brand_kit,
        "kind": "document",  # so reused document renderers treat embeds as paper
        "nonce": nonce,
        "page_url": page_url or (lambda slug: "./" if not slug else f"./{slug}"),
        # Site srcs are served URLs the *visitor's* browser fetches (never a
        # server-side fetch), so the default resolver is a plain pass-through.
        "asset_url": asset_url or _default_asset_url,
        "render_form": render_form,
        "render_widget": render_widget,
    }


def _default_asset_url(src: str) -> str:
    return str(src or "").strip()


def _asset(ctx: dict, src: str) -> str:
    try:
        return ctx["asset_url"](src) or ""
    except Exception:
        return _default_asset_url(src)


# ---------------------------------------------------------------------------
# Site-specific block renderers
# ---------------------------------------------------------------------------


def _b_hero(p: dict, ctx: dict) -> str:
    kicker = f'<div class="kicker">{_h(p.get("kicker", ""))}</div>' if p.get("kicker") else ""
    subhead = f'<p class="subhead">{_h(p.get("subhead", ""))}</p>' if p.get("subhead") else ""
    media = _asset(ctx, p.get("media_src", ""))
    bg = f'<img class="bgimg" src="{_h(media)}" alt=""/>' if media else ""
    has_media = " has-media" if media else ""
    cta = ""
    c = p.get("cta") or {}
    if isinstance(c, dict) and c.get("label") and c.get("url"):
        cta = f'<a class="site-btn primary" href="{_h(c.get("url"))}">{_h(c.get("label"))}</a>'
    return (
        f'<div class="site-hero{has_media}">{bg}'
        f'<div class="site-wrap"><div class="inner">{kicker}'
        f"<h1>{_h(p.get('headline', ''))}</h1>{subhead}{cta}</div></div></div>"
    )


def _b_link_button(p: dict) -> str:
    style = "primary" if p.get("style") == "primary" else "secondary"
    note = f'<span class="note">{_h(p.get("note", ""))}</span>' if p.get("note") else ""
    return (
        f'<a class="bio-link {style}" href="{_h(p.get("url", ""))}">'
        f"{_h(p.get('label', ''))}{note}</a>"
    )


def _b_link_list(p: dict) -> str:
    items = []
    for link in p.get("links") or []:
        note = f'<span class="note">{_h(link.get("note", ""))}</span>' if link.get("note") else ""
        items.append(
            f'<a class="bio-link" href="{_h(link.get("url", ""))}">'
            f"{_h(link.get('label', ''))}{note}</a>"
        )
    return f'<div class="bio-stack">{"".join(items)}</div>'


def _b_social_links(p: dict) -> str:
    out = []
    for link in p.get("links") or []:
        out.append(f'<a href="{_h(link.get("url", ""))}">{_h(link.get("platform", ""))}</a>')
    return f'<div class="social-row">{"".join(out)}</div>' if out else ""


def _b_card_grid(p: dict, ctx: dict) -> str:
    cols = p.get("columns")
    cls = "card-grid cols-2" if cols == 2 else "card-grid"
    figs = []
    for c in p.get("cards") or []:
        src = _asset(ctx, c.get("src", ""))
        if not src:
            continue
        img = f'<img src="{_h(src)}" alt="{_h(c.get("alt", ""))}" loading="lazy"/>'
        if c.get("href"):
            img = f'<a href="{_h(c.get("href"))}">{img}</a>'
        cap = f"<figcaption>{_h(c.get('caption'))}</figcaption>" if c.get("caption") else ""
        figs.append(f"<figure>{img}{cap}</figure>")
    return f'<div class="{cls}">{"".join(figs)}</div>' if figs else ""


def _b_cta_band(p: dict) -> str:
    btn = p.get("button") or {}
    button = ""
    if isinstance(btn, dict) and btn.get("label") and btn.get("url"):
        button = (
            f'<a class="site-btn primary" href="{_h(btn.get("url"))}">{_h(btn.get("label"))}</a>'
        )
    return f'<div class="cta-band"><p class="t">{_h(p.get("text", ""))}</p>{button}</div>'


def _b_sponsor_strip(p: dict, ctx: dict) -> str:
    title = f'<div class="title">{_h(p.get("title"))}</div>' if p.get("title") else ""
    logos = []
    for logo in p.get("logos") or []:
        src = _asset(ctx, logo.get("src", ""))
        if not src:
            continue
        img = f'<img src="{_h(src)}" alt="{_h(logo.get("alt", ""))}" loading="lazy"/>'
        logos.append(f'<a href="{_h(logo.get("url"))}">{img}</a>' if logo.get("url") else img)
    if not logos:
        return ""
    return f'<div class="sponsor-strip">{title}<div class="logos">{"".join(logos)}</div></div>'


def _b_event_details(p: dict) -> str:
    rows = []
    for key in ("name", "date", "time", "venue"):
        if p.get(key):
            rows.append(
                f'<div class="row"><span class="k">{key.title()}</span>'
                f"<span>{_h(p.get(key))}</span></div>"
            )
    if p.get("address"):
        # Privacy-respecting: a plain text address + a link out, not an embedded
        # third-party map iframe (keeps the page CSP self-only).
        from urllib.parse import quote_plus

        q = quote_plus(str(p.get("address")))
        rows.append(
            '<div class="row"><span class="k">Where</span><span>'
            f"{_h(p.get('address'))} &middot; "
            f'<a class="map-link" rel="noopener" target="_blank" '
            f'href="https://www.openstreetmap.org/search?query={q}">Open in maps</a>'
            "</span></div>"
        )
    return f'<div class="event-card">{"".join(rows)}</div>' if rows else ""


def _b_payment_button(p: dict) -> str:
    note = (
        f'<span class="note" style="display:block;color:var(--site-muted);font-size:.85rem;'
        f'margin-top:.4rem">{_h(p.get("note"))}</span>'
        if p.get("note")
        else ""
    )
    return (
        f'<a class="site-btn primary" rel="noopener" href="{_h(p.get("url", ""))}">'
        f"{_h(p.get('label', ''))}</a>{note}"
    )


def _b_qr(p: dict) -> str:
    data = str(p.get("data", "")).strip()
    if not data:
        return ""
    cap = f'<span class="cap">{_h(p.get("caption"))}</span>' if p.get("caption") else ""
    try:
        from mediahub.sites import qr as _qr  # Build 3

        svg = _qr.qr_svg(data, label=str(p.get("label", "")))
        return f'<div class="qr-block">{svg}{cap}</div>'
    except Exception:
        # Engine present, QR module not yet available → an honest link, never a
        # broken image. (Filled in by Build 3.)
        return f'<div class="qr-block"><a href="{_h(data)}">{_h(data)}</a>{cap}</div>'


def _b_form(p: dict, ctx: dict) -> str:
    form_id = str(p.get("form_id", "")).strip()
    if not form_id:
        return ""
    resolver = ctx.get("render_form")
    title = str(p.get("title", ""))
    if callable(resolver):
        try:
            return resolver(form_id, ctx.get("nonce", "")) or ""
        except Exception:
            pass
    # No resolver wired (engine-only render) → a labelled placeholder, never a
    # silently-missing form. The web layer injects the live form renderer.
    head = f"<h3>{_h(title)}</h3>" if title else ""
    return (
        f'<div class="site-form-placeholder" data-form-id="{_h(form_id)}">{head}'
        '<p style="color:var(--site-muted)">This form will appear here on the published site.</p>'
        "</div>"
    )


def _b_widget(p: dict, ctx: dict) -> str:
    resolver = ctx.get("render_widget")
    if callable(resolver):
        try:
            return resolver(p, ctx.get("nonce", "")) or ""
        except Exception:
            pass
    try:
        from mediahub.sites import widgets as _w  # Build 3

        return _w.render_widget(p, nonce=ctx.get("nonce", ""), role_vars=ctx.get("role_vars")) or ""
    except Exception:
        label = p.get("widget_type") or p.get("widget_id") or "widget"
        return (
            f'<div class="site-widget-placeholder" data-widget="{_h(label)}" '
            'style="color:var(--site-muted)">Interactive widget loads on the published site.</div>'
        )


_SITE_RENDERERS_NEEDING_CTX = {
    "hero": _b_hero,
    "card_grid": _b_card_grid,
    "sponsor_strip": _b_sponsor_strip,
    "form_embed": _b_form,
    "widget_embed": _b_widget,
}
_SITE_RENDERERS_SIMPLE = {
    "link_button": _b_link_button,
    "link_list": _b_link_list,
    "social_links": _b_social_links,
    "cta_band": _b_cta_band,
    "event_details": _b_event_details,
    "payment_button": _b_payment_button,
    "qr_block": _b_qr,
}


def _render_site_block(block: Block, ctx: dict) -> str:
    kind = block.kind
    p = block.props or {}
    if kind in _SITE_RENDERERS_NEEDING_CTX:
        return _SITE_RENDERERS_NEEDING_CTX[kind](p, ctx)
    if kind in _SITE_RENDERERS_SIMPLE:
        return _SITE_RENDERERS_SIMPLE[kind](p)
    # Fall back to the shared document block renderer (heading/text/list/table/
    # chart/card/media/stat/kpi_row/quote/divider/spacer/columns).
    return _render_block(block, ctx)


# ---------------------------------------------------------------------------
# Section + page assembly
# ---------------------------------------------------------------------------


def _bg_class(section: SiteSection) -> str:
    bg = section.background
    if bg in ("surface", "ground"):
        return " bg-surface"
    if bg == "primary":
        return " bg-primary"
    if bg == "accent":
        return " bg-accent"
    return ""


def _section_html(section: SiteSection, ctx: dict) -> str:
    inner = "".join(_render_site_block(b, ctx) for b in section.blocks)
    # A hero section is rendered full-bleed (the hero block carries its own wrap).
    if section.layout == "hero":
        return inner
    bg = _bg_class(section)
    layout = f" layout-{section.layout}" if section.layout != "flow" else ""
    wrap_cls = "site-wrap narrow" if section.layout == "centered" else "site-wrap"
    body = f'<div class="blocks">{inner}</div>' if section.layout == "grid" else inner
    return (
        f'<section class="site-section{bg}{layout}"><div class="{wrap_cls}">{body}</div></section>'
    )


def _nav_html(spec: SiteSpec, page: SitePage, ctx: dict) -> str:
    if page.layout == "link_in_bio":
        return ""  # link-in-bio is a single tall page, no nav chrome
    nav_pages = [p for p in spec.nav_pages()]
    brand_name = spec.meta.get("club_name") or spec.title
    logo_src = _asset(ctx, str(spec.meta.get("logo_src", "")))
    logo = f'<img src="{_h(logo_src)}" alt=""/>' if logo_src else ""
    links = ""
    if len(nav_pages) > 1:
        items = []
        for p in nav_pages:
            href = ctx["page_url"](p.slug if not p.is_home else "")
            cur = ' aria-current="page"' if p.page_id == page.page_id else ""
            items.append(f'<a href="{_h(href)}"{cur}>{_h(p.title)}</a>')
        links = f'<div class="links">{"".join(items)}</div>'
    home_href = ctx["page_url"]("")
    return (
        '<nav class="site-nav"><div class="row">'
        f'<a class="brand" href="{_h(home_href)}">{logo}{_h(brand_name)}</a>'
        f"{links}</div></nav>"
    )


def _foot_html(spec: SiteSpec) -> str:
    name = spec.meta.get("club_name") or spec.title
    return (
        '<footer class="site-foot"><div class="site-wrap">'
        f"<div>&copy; {_h(name)}</div>"
        '<div class="made">Made with MediaHub</div>'
        "</div></footer>"
    )


def _head_html(spec: SiteSpec, page: SitePage, style: str, *, canonical: str = "") -> str:
    title = (
        page.seo.meta_title or f"{page.title} — {spec.title}"
        if not page.is_home
        else (page.seo.meta_title or spec.title)
    )
    desc = page.seo.description or spec.tagline
    meta = [
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{_h(title)}</title>",
    ]
    if desc:
        meta.append(f"<meta name='description' content='{_h(desc)}'>")
        meta.append(f"<meta property='og:description' content='{_h(desc)}'>")
    meta.append(f"<meta property='og:title' content='{_h(title)}'>")
    meta.append("<meta property='og:type' content='website'>")
    og_image = page.seo.og_image
    if og_image:
        meta.append(f"<meta property='og:image' content='{_h(og_image)}'>")
    if page.seo.noindex:
        meta.append("<meta name='robots' content='noindex,nofollow'>")
    if canonical:
        meta.append(f"<link rel='canonical' href='{_h(canonical)}'>")
    return f"<head>{''.join(meta)}<style>{style}</style></head>"


def render_page_html(
    spec: SiteSpec,
    page: SitePage,
    *,
    brand_kit: Any = None,
    role_vars: Optional[dict[str, str]] = None,
    nonce: str = "",
    canonical: str = "",
    page_url: Optional[Callable[[str], str]] = None,
    asset_url: Optional[Callable[[str], str]] = None,
    render_form: Optional[Callable[[str, str], str]] = None,
    render_widget: Optional[Callable[[dict, str], str]] = None,
) -> str:
    """Assemble the full self-contained HTML for one page of ``spec``.

    ``page_url(slug)`` builds inter-page links; ``asset_url(src)`` rewrites image
    sources to publicly-fetchable URLs; ``render_form``/``render_widget`` inject
    the live form/widget renderers (the web layer supplies these). All are
    optional so the engine renders standalone (used by the deterministic tests)."""
    rv = role_vars or resolve_role_vars(brand_kit)
    style = site_style(rv, theme=spec.theme)
    ctx = _ctx(
        role_vars=rv,
        brand_kit=brand_kit,
        nonce=nonce,
        page_url=page_url,
        asset_url=asset_url,
        render_form=render_form,
        render_widget=render_widget,
    )
    nav = _nav_html(spec, page, ctx)
    sections = "".join(_section_html(s, ctx) for s in page.sections)
    foot = _foot_html(spec)
    head = _head_html(spec, page, style, canonical=canonical)
    body = f"<body>{nav}<main>{sections}</main>{foot}</body>"
    return f"<!DOCTYPE html><html lang='en'>{head}{body}</html>"


def render_site_page(
    spec: SiteSpec,
    slug: str = "",
    **kwargs: Any,
) -> str:
    """Render the page at ``slug`` (or the home page). Raises if no such page."""
    page = spec.page_by_slug(slug)
    if page is None:
        raise ValueError(f"no page for slug {slugify(slug)!r}")
    return render_page_html(spec, page, **kwargs)
