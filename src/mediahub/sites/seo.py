"""sites.seo — sitemap & robots for a published microsite (roadmap 1.16).

Per-page meta (title/description/canonical/OG/robots-noindex) is emitted by the
renderer's ``<head>`` (:mod:`sites.render`). This module adds the site-level SEO
artefacts: an XML **sitemap** of the indexable pages and a **robots.txt** that
points at it. Both are deterministic and fully escaped. A page marked
``seo.noindex`` is kept out of the sitemap (and the renderer adds its noindex meta).
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xe

from .models import SiteSpec


def _page_url(base_url: str, slug: str) -> str:
    base = base_url.rstrip("/")
    return base if not slug or slug in ("index", "home") else f"{base}/{slug}"


def indexable_pages(spec: SiteSpec) -> list:
    """The pages that should appear in search: shown in nav-or-not, but not noindex.

    Password-protected (members-only) pages are excluded by default — a public
    sitemap must not advertise a gated page's slug, whether or not the operator
    also ticked noindex."""
    return [p for p in spec.pages if not p.seo.noindex and not p.protected]


def sitemap_xml(spec: SiteSpec, base_url: str) -> str:
    """An XML sitemap of the site's indexable pages."""
    urls = []
    for p in indexable_pages(spec):
        loc = _xe(_page_url(base_url, p.slug))
        urls.append(f"<url><loc>{loc}</loc></url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{''.join(urls)}</urlset>"
    )


def robots_txt(base_url: str, *, sitemap_url: str = "") -> str:
    """A permissive robots.txt pointing at the sitemap."""
    sitemap = sitemap_url or f"{base_url.rstrip('/')}/sitemap.xml"
    return f"User-agent: *\nAllow: /\nSitemap: {sitemap}\n"


__all__ = ["indexable_pages", "sitemap_xml", "robots_txt"]
