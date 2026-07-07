"""documents.render — DocumentSpec → brand-tokened paged HTML → PDF / PNG preview.

The deterministic core of the document engine (roadmap 1.15). It assembles a
:class:`~documents.models.DocumentSpec` into one self-contained HTML page —
brand role vars + self-hosted fonts (:mod:`documents.theme`) + a block-per-kind
renderer — and prints it with the shared Playwright pipeline:

  - PDF via ``graphic_renderer.print_export.render_html_to_pdf`` (Chromium
    ``page.pdf``, ``prefer_css_page_size`` so the document's own ``@page`` drives
    pagination); a paper document flows + paginates, a deck is one slide per sheet.
  - per-section PNG previews via ``graphic_renderer.render.render_html_to_png``.

Everything is escaped (``markupsafe``) — captions and report prose are HTML-safe,
so a generated caption can never inject markup (CLAUDE.md security focus). Numbers
in data blocks come straight from the spec (the deterministic fact base), never
from a template guess. Outputs are content-addressed (:mod:`documents.cache`).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from markupsafe import escape as _h

from . import cache
from .models import Block, DocumentSpec, PageGeometry, Section
from .theme import document_style, resolve_role_vars

# ---------------------------------------------------------------------------
# Inline + image helpers
# ---------------------------------------------------------------------------


def _inline(raw: str) -> str:
    """Escape text, then apply a tiny safe inline markup: **bold**, *italic*.

    Escaping first means the markup runs over HTML-safe text — a caption can
    never smuggle in a tag."""
    safe = str(_h(str(raw or "")))
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", safe)
    return safe


def _data_root() -> Path:
    return Path(os.environ.get("DATA_DIR", ".")).resolve()


def _img_src(src: str) -> str:
    """Resolve an image source to something Chromium can fetch under file://.

    Spec srcs are tenant-editable (the advanced JSON editor), so only ``data:``
    URIs and files under the app's own ``DATA_DIR`` resolve. A remote
    ``http(s)://`` URL would be fetched server-side by Chromium (SSRF) and a
    path outside ``DATA_DIR`` would include arbitrary local files — both are
    dropped, matching the network-locked PNG preview path. A blocked image
    renders as nothing, never a fabricated placeholder."""
    s = str(src or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("data:"):
        return s
    if low.startswith(("http://", "https://")):
        return ""
    if low.startswith("file:"):
        from urllib.parse import unquote, urlparse

        try:
            p = Path(unquote(urlparse(s).path))
        except (OSError, ValueError):
            return ""
    else:
        p = Path(s)
    try:
        rp = p.resolve()
        if rp.is_file() and rp.is_relative_to(_data_root()):
            return rp.as_uri()
    except (OSError, ValueError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Block rendering — one function per kind, dispatched by ``_render_block``
# ---------------------------------------------------------------------------


def _b_heading(p: dict) -> str:
    level = int(p.get("level", 2) or 2)
    level = max(1, min(3, level))
    return f'<h{level} class="doc-h{level}">{_inline(p.get("text", ""))}</h{level}>'


def _b_text(p: dict) -> str:
    align = p.get("align", "left")
    cls = f" {align}" if align in ("center", "right", "justify") else ""
    return f'<p class="doc-text{cls}">{_inline(p.get("text", ""))}</p>'


def _b_list(p: dict) -> str:
    tag = "ol" if p.get("ordered") else "ul"
    items = "".join(f"<li>{_inline(i)}</li>" for i in (p.get("items") or []))
    return f'<{tag} class="doc-list">{items}</{tag}>'


def _b_table(p: dict) -> str:
    cols = p.get("columns") or []
    rows = p.get("rows") or []
    head = "".join(f"<th>{_h(c)}</th>" for c in cols)
    thead = f"<thead><tr>{head}</tr></thead>" if head else ""
    body_rows = []
    for r in rows:
        cells = "".join(f"<td>{_h(c)}</td>" for c in r)
        body_rows.append(f"<tr>{cells}</tr>")
    cap = p.get("caption")
    caption = f"<caption>{_h(cap)}</caption>" if cap else ""
    return f'<table class="doc-table">{caption}{thead}<tbody>{"".join(body_rows)}</tbody></table>'


def _b_chart(p: dict, ctx: dict) -> str:
    spec_dict = p.get("chart") or {}
    try:
        from mediahub.charts.models import ChartSpec
        from mediahub.charts.render import render_chart_svg

        spec = ChartSpec.from_dict(spec_dict)
        if spec is None:
            return ""
        svg = render_chart_svg(spec, ctx.get("role_vars"), brand_kit=ctx.get("brand_kit"))
        return f'<div class="doc-chart">{svg}</div>'
    except Exception:
        # An embed that can't render is dropped — never a fabricated chart.
        return ""


def _resolve_src(p: dict, ctx: dict) -> str:
    """Resolve a block's image src via the context's asset resolver.

    The site engine reuses these block renderers for public HTML, where a src
    is a served URL fetched by the *visitor's* browser — its ``asset_url``
    callable keeps those semantics. Document renders (server-side Chromium)
    have no ``asset_url`` and fall through to the locked-down :func:`_img_src`."""
    raw = p.get("src", "")
    fn = ctx.get("asset_url")
    if callable(fn):
        try:
            return str(fn(raw) or "")
        except Exception:
            return _img_src(raw)
    return _img_src(raw)


def _b_card(p: dict, ctx: dict) -> str:
    src = _resolve_src(p, ctx)
    if not src:
        return ""
    alt = _h(p.get("alt", ""))
    cap = p.get("caption")
    figcap = f"<figcaption>{_h(cap)}</figcaption>" if cap else ""
    return f'<figure class="doc-figure"><img src="{_h(src)}" alt="{alt}"/>{figcap}</figure>'


def _b_media(p: dict, ctx: dict) -> str:
    src = _resolve_src(p, ctx)
    if not src:
        return ""
    alt = _h(p.get("alt", ""))
    fit = "cover" if p.get("fit") == "cover" else "contain"
    cap = p.get("caption")
    figcap = f"<figcaption>{_h(cap)}</figcaption>" if cap else ""
    cls = "doc-figure cover" if fit == "cover" else "doc-figure"
    return f'<figure class="{cls}"><img src="{_h(src)}" alt="{alt}"/>{figcap}</figure>'


def _b_stat(p: dict) -> str:
    sub = p.get("sublabel")
    sub_html = f'<span class="s">{_h(sub)}</span>' if sub else ""
    return (
        '<div class="doc-kpis"><div class="doc-kpi">'
        f'<span class="v">{_h(p.get("value", ""))}</span>'
        f'<span class="l">{_h(p.get("label", ""))}</span>{sub_html}'
        "</div></div>"
    )


def _b_kpi_row(p: dict) -> str:
    tiles = []
    for s in p.get("stats") or []:
        sub = s.get("sublabel")
        sub_html = f'<span class="s">{_h(sub)}</span>' if sub else ""
        tiles.append(
            '<div class="doc-kpi">'
            f'<span class="v">{_h(s.get("value", ""))}</span>'
            f'<span class="l">{_h(s.get("label", ""))}</span>{sub_html}'
            "</div>"
        )
    return f'<div class="doc-kpis">{"".join(tiles)}</div>'


def _b_quote(p: dict) -> str:
    who = p.get("attribution")
    who_html = f'<span class="who">— {_h(who)}</span>' if who else ""
    return f'<blockquote class="doc-quote">{_inline(p.get("text", ""))}{who_html}</blockquote>'


def _b_columns(p: dict, ctx: dict) -> str:
    cols = []
    for col in p.get("columns") or []:
        inner = "".join(_render_block(Block.from_dict(b), ctx) for b in (col or []))
        cols.append(f'<div class="doc-col">{inner}</div>')
    return f'<div class="doc-cols">{"".join(cols)}</div>'


def _render_block(block: Block, ctx: dict) -> str:
    kind = block.kind
    p = block.props or {}
    if kind == "heading":
        return _b_heading(p)
    if kind == "text":
        return _b_text(p)
    if kind == "list":
        return _b_list(p)
    if kind == "table":
        return _b_table(p)
    if kind == "chart":
        return _b_chart(p, ctx)
    if kind == "card":
        return _b_card(p, ctx)
    if kind == "media":
        return _b_media(p, ctx)
    if kind == "stat":
        return _b_stat(p)
    if kind == "kpi_row":
        return _b_kpi_row(p)
    if kind == "quote":
        return _b_quote(p)
    if kind == "divider":
        return '<hr class="doc-divider"/>'
    if kind == "spacer":
        size = p.get("size", "md")
        size = size if size in ("sm", "md", "lg") else "md"
        return f'<div class="doc-spacer-{size}"></div>'
    if kind == "columns":
        return _b_columns(p, ctx)
    return ""  # unknown kind → nothing (forward-compatible)


# ---------------------------------------------------------------------------
# Section + page assembly
# ---------------------------------------------------------------------------


def _blocks_html(blocks: list[Block], ctx: dict) -> str:
    return "".join(_render_block(b, ctx) for b in blocks)


def _bg_class(section: Section) -> str:
    bg = section.background
    if bg == "primary":
        return " bg-primary"
    if bg == "accent":
        return " bg-accent"
    return ""


def _deck_slide(section: Section, ctx: dict, *, index: int, total: int) -> str:
    layout = f" layout-{section.layout}" if section.layout != "flow" else ""
    bg = _bg_class(section)
    inner = _blocks_html(section.blocks, ctx)
    num = f'<span class="slide-num">{index + 1} / {total}</span>'
    return f'<div class="doc-sheet{bg}"><div class="doc-pad{layout}">{inner}</div>{num}</div>'


def _doc_section(section: Section, ctx: dict) -> str:
    brk = " brk" if section.break_before else ""
    layout = f" layout-{section.layout}" if section.layout != "flow" else ""
    inner = _blocks_html(section.blocks, ctx)
    return f'<section class="doc-section{brk}{layout}">{inner}</section>'


def _runhead(spec: DocumentSpec) -> str:
    brand = spec.meta.get("club_name") or spec.meta.get("brand_name") or ""
    right = spec.meta.get("date") or spec.meta.get("period") or ""
    if not (brand or right):
        return ""
    return (
        '<div class="doc-runhead">'
        f'<span class="brand">{_h(brand)}</span>'
        f"<span>{_h(right)}</span></div>"
    )


def _sources_footer(spec: DocumentSpec) -> str:
    if not spec.source_refs:
        return ""
    refs = "; ".join(str(r) for r in spec.source_refs[:8])
    return f'<div class="doc-sources">Sources: {_h(refs)}</div>'


def _wrap_html(title: str, style: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{_h(title)}</title><style>{style}</style></head>"
        f"<body>{body}</body></html>"
    )


def render_document_html(
    spec: DocumentSpec,
    *,
    brand_kit: Any = None,
    role_vars: Optional[dict[str, str]] = None,
) -> str:
    """Assemble the full self-contained HTML page for ``spec``."""
    rv = role_vars or resolve_role_vars(brand_kit)
    geom = spec.page_geometry
    ctx = {"role_vars": rv, "brand_kit": brand_kit, "kind": spec.kind, "geom": geom}
    style = document_style(rv, kind=spec.kind, geom=geom)

    if spec.is_deck:
        total = len(spec.sections)
        body = "".join(
            _deck_slide(s, ctx, index=i, total=total) for i, s in enumerate(spec.sections)
        )
    else:
        parts = [_runhead(spec)]
        parts += [_doc_section(s, ctx) for s in spec.sections]
        parts.append(_sources_footer(spec))
        body = '<div class="doc-doc">' + "".join(parts) + "</div>"

    return _wrap_html(spec.title, style, body)


# ---------------------------------------------------------------------------
# PDF + PNG outputs (content-addressed cache)
# ---------------------------------------------------------------------------


def render_document_pdf(
    spec: DocumentSpec,
    out_path: Optional[Path] = None,
    *,
    brand_kit: Any = None,
    role_vars: Optional[dict[str, str]] = None,
    tagged: bool = True,
) -> Path:
    """Render ``spec`` to a multi-page PDF. Cached by content; returns the path.

    ``tagged`` (default on) emits an accessible PDF carrying the document's
    headings + image alt text as screen-reader structure. Raises whatever the
    renderer raises when Playwright/Chromium is unavailable (an honest infra
    error, not a broken file)."""
    html = render_document_html(spec, brand_kit=brand_kit, role_vars=role_vars)
    cached = cache.cached_path(".pdf", "doc-pdf", "tagged" if tagged else "plain", html)
    if not (cached.exists() and cached.stat().st_size > 0):
        from mediahub.graphic_renderer.print_export import render_html_to_pdf

        render_html_to_pdf(html, cached, prefer_css_page_size=True, tagged=tagged)
    if out_path is not None:
        out_path = Path(out_path)
        if out_path.resolve() != cached.resolve():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out_path)
        return out_path
    return cached


def _geom_px(geom: PageGeometry) -> tuple[int, int]:
    """Pixel dimensions for a preview screenshot of one sheet/slide."""

    def to_px(length: str) -> int:
        s = length.strip().lower()
        if s.endswith("px"):
            return int(round(float(s[:-2])))
        if s.endswith("mm"):
            return int(round(float(s[:-2]) * 96.0 / 25.4))
        try:
            return int(round(float(s)))
        except ValueError:
            return 800

    return to_px(geom.width), to_px(geom.height)


def render_section_png(
    spec: DocumentSpec,
    index: int,
    out_path: Optional[Path] = None,
    *,
    brand_kit: Any = None,
    role_vars: Optional[dict[str, str]] = None,
) -> Path:
    """Render one section/slide to a PNG preview at the geometry's pixel size."""
    if not spec.sections:
        raise ValueError("document has no sections to preview")
    index = max(0, min(index, len(spec.sections) - 1))
    section = spec.sections[index]
    rv = role_vars or resolve_role_vars(brand_kit)
    geom = spec.page_geometry
    w, h = _geom_px(geom)
    ctx = {"role_vars": rv, "brand_kit": brand_kit, "kind": spec.kind, "geom": geom}

    # Preview every kind as a single fixed-size sheet (deck-style box) so the
    # screenshot is exactly one page — for a paper doc this is a thumbnail of the
    # section's first sheet (overflow clipped).
    tokens_style = document_style(rv, kind="deck", geom=geom)
    layout = f" layout-{section.layout}" if section.layout != "flow" else ""
    bg = _bg_class(section)
    inner = _blocks_html(section.blocks, ctx)
    sheet = (
        f'<div class="doc-sheet{bg}" style="width:{w}px;height:{h}px">'
        f'<div class="doc-pad{layout}">{inner}</div></div>'
    )
    html = _wrap_html(spec.title, tokens_style, sheet)

    cached = cache.cached_path(".png", "doc-png", w, h, html)
    if not (cached.exists() and cached.stat().st_size > 0):
        from mediahub.graphic_renderer.render import render_html_to_png

        render_html_to_png(html, cached, (w, h), image_format="png")
    if out_path is not None:
        out_path = Path(out_path)
        if out_path.resolve() != cached.resolve():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out_path)
        return out_path
    return cached


__all__ = [
    "render_document_html",
    "render_document_pdf",
    "render_section_png",
]
