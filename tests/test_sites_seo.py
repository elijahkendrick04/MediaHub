"""Microsite engine (roadmap 1.16) — build 3: sitemap & robots."""

from __future__ import annotations

from mediahub.sites import seo
from mediahub.sites.models import PageSEO, SitePage, SiteSpec


def _spec():
    return SiteSpec(
        title="Otters",
        pages=[
            SitePage(title="Home", slug=""),
            SitePage(title="Results", slug="results"),
            SitePage(title="Secret", slug="secret", seo=PageSEO(noindex=True)),
            SitePage(title="Members", slug="members", protected=True),
        ],
    )


def test_indexable_pages_excludes_noindex_and_protected():
    pages = seo.indexable_pages(_spec())
    # the home page's empty slug derives to "home" (still treated as the root)
    assert [p.slug for p in pages] == ["home", "results"]


def test_sitemap_xml():
    xml = seo.sitemap_xml(_spec(), "https://host/site/TKN")
    assert xml.startswith("<?xml")
    assert "<loc>https://host/site/TKN</loc>" in xml  # home → base
    assert "<loc>https://host/site/TKN/results</loc>" in xml
    assert "secret" not in xml  # noindex excluded
    assert "members" not in xml  # password-protected page never advertised


def test_sitemap_escapes():
    spec = SiteSpec(title="x", pages=[SitePage(title="Q", slug="a")])
    xml = seo.sitemap_xml(spec, "https://host/site/TKN?x=1&y=2")
    assert "&amp;" in xml  # ampersand escaped


def test_robots_txt():
    txt = seo.robots_txt("https://host/site/TKN")
    assert "User-agent: *" in txt
    assert "Sitemap: https://host/site/TKN/sitemap.xml" in txt
