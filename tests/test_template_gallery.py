"""UI 1.10 — the visual template / archetype gallery.

Covers the pure ``mediahub.web.template_gallery`` helper (categories, schematic
previews, catalog assembly, the body renderer), the ``archetype_summary``
catalog line it leans on, and the ``/templates`` route + its wiring into the
nav and the Create page. The gallery renders *existing* archetype data only —
these tests pin that contract: every registered archetype is represented,
categorised, and given a distinct schematic, and category filtering works both
server-side (the no-JS path) and via the client-side enhancement.
"""

from __future__ import annotations

import re

import pytest

from mediahub.graphic_renderer import archetypes as A
from mediahub.web import template_gallery as G


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


# Helper: count gallery cards (anchored on the <article> so JS string
# references to ".mh-arch-card" inside the inline <script> never inflate it).
_CARD_RE = re.compile(r'<article class="mh-arch-card\b')
_HIDDEN_CARD_RE = re.compile(r'<article class="mh-arch-card is-hidden\b')


def _cards(html: str) -> int:
    return len(_CARD_RE.findall(html))


def _hidden_cards(html: str) -> int:
    return len(_HIDDEN_CARD_RE.findall(html))


# ---------------------------------------------------------------------------
# archetype_summary — the new catalog line in graphic_renderer.archetypes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", A.list_archetypes())
def test_archetype_summary_present_and_clean(name):
    s = A.archetype_summary(name)
    assert s, f"{name}: empty summary"
    # No markdown noise leaks into the gallery line.
    assert "*" not in s and "`" not in s and "#" not in s
    # Bounded so a gallery card stays compact.
    assert len(s) <= A._SUMMARY_MAX_CHARS + 2  # +2 for the " …" ellipsis
    # It's the "what it is" line, distinct from the "when to pick" line.
    assert s != A.director_note(name)


def test_archetype_summary_strips_leading_section_label():
    # triptych_progression's notes lead with "**Family / structural
    # signature.**" — that label must be stripped, not surfaced as the summary.
    s = A.archetype_summary("triptych_progression")
    assert not s.lower().startswith("family")
    assert "three" in s.lower()


def test_archetype_summary_missing_notes_returns_empty():
    assert A.archetype_summary("does_not_exist_zzz") == ""


# ---------------------------------------------------------------------------
# Categories + catalog data
# ---------------------------------------------------------------------------


def test_every_archetype_has_explicit_category():
    """A new archetype must be deliberately categorised — not silently
    defaulted. This guard fails loudly when one ships without a mapping."""
    known = {cid for cid, _, _ in G.CATEGORIES}
    for name in A.list_archetypes():
        assert name in G.CATEGORY_BY_ARCHETYPE, f"{name} has no category mapping"
        assert G.CATEGORY_BY_ARCHETYPE[name] in known, f"{name} → unknown category"


def test_display_order_covers_every_archetype():
    assert set(G._DISPLAY_ORDER) == set(A.list_archetypes())


def test_categories_are_populated():
    entries = G.gallery_entries()
    counts = G.category_counts(entries)
    assert counts["all"] == len(entries) == len(A.list_archetypes())
    # Each category has at least one archetype (no dead filter chips).
    for cid, _, _ in G.CATEGORIES:
        assert counts[cid] >= 1
    # Counts add up to the total.
    assert sum(counts[cid] for cid, _, _ in G.CATEGORIES) == counts["all"]


def test_valid_category_coercion():
    assert G.valid_category("photo") == "photo"
    assert G.valid_category("PHOTO") == "photo"
    assert G.valid_category(" data ") == "data"
    assert G.valid_category("all") == "all"   # not a real chip id → falls back
    assert G.valid_category("nonsense") == "all"
    assert G.valid_category(None) == "all"
    assert G.valid_category("") == "all"


def test_humanize_and_labels():
    assert G.humanize("split_diagonal_hero") == "Diagonal Hero"
    # Unknown slug falls back to a title-cased name (no crash).
    assert G.humanize("some_new_archetype") == "Some New Archetype"
    assert G.category_label("photo") == "Photo-led"
    assert G.category_label("all") == "All"


# ---------------------------------------------------------------------------
# Schematic previews
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", A.list_archetypes())
def test_archetype_svg_wellformed_and_bespoke(name):
    svg = G.archetype_svg(name)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert 'viewBox="0 0 120 150"' in svg
    assert 'role="img"' in svg and "aria-label=" in svg
    # Bespoke, not the generic placeholder.
    assert name in G._SVG and G._SVG[name] != G._GENERIC_SVG


def test_svgs_are_all_distinct():
    seen = {name: G._SVG[name] for name in A.list_archetypes()}
    assert len(set(seen.values())) == len(seen), "two archetypes share a schematic"


@pytest.mark.parametrize("name", A.list_archetypes())
def test_svg_is_theme_driven_no_hardcoded_colour(name):
    """Schematics colour themselves via scoped CSS classes (theme vars), never
    a baked-in hex or inline fill — so they follow the app theme."""
    inner = G._SVG[name]
    assert not re.search(r"#[0-9a-fA-F]{3,6}", inner), f"{name}: hardcoded hex in svg"
    assert "fill=" not in inner and "style=" not in inner, f"{name}: inline paint in svg"


# ---------------------------------------------------------------------------
# gallery_entries shape
# ---------------------------------------------------------------------------


def test_gallery_entries_shape():
    entries = G.gallery_entries()
    assert len(entries) == len(A.list_archetypes())
    names = [e["name"] for e in entries]
    assert set(names) == set(A.list_archetypes())
    # Curated display order leads (first listed archetype is first).
    assert names[0] == G._DISPLAY_ORDER[0]
    for e in entries:
        for key in ("name", "title", "summary", "when", "category", "category_label", "svg"):
            assert e[key], f"{e['name']}: empty {key}"
        assert e["svg"].startswith("<svg")
        assert len(e["summary"]) <= G._CARD_SUMMARY_MAX + 2
        assert len(e["when"]) <= G._CARD_WHEN_MAX + 2


# ---------------------------------------------------------------------------
# render_gallery_body (pure HTML, no request)
# ---------------------------------------------------------------------------


def test_render_body_structure():
    html = G.render_gallery_body(gallery_url="/templates", make_url="/make")
    assert _cards(html) == len(A.list_archetypes()) == 12
    assert _hidden_cards(html) == 0  # the default "all" view hides nothing
    # Chips for All + every category, with counts.
    assert 'aria-label="Filter templates by category"' in html
    for cid, label, _ in G.CATEGORIES:
        assert f'data-cat="{cid}"' in html
        assert label in html
    assert 'data-cat="all"' in html
    # CTA back into the Create flow.
    assert 'href="/make"' in html and "Create a pack" in html
    # Progressive-enhancement script + the empty-state element are present.
    assert "<script>" in html and "mh-arch-empty" in html
    # Each archetype's slug + friendly title render.
    for name in A.list_archetypes():
        assert f">{name}</code>" in html
        assert G.humanize(name) in html


def test_render_body_server_side_filtering():
    html = G.render_gallery_body(
        gallery_url="/templates", make_url="/make", active_category="photo"
    )
    entries = G.gallery_entries()
    n_photo = sum(1 for e in entries if e["category"] == "photo")
    assert _cards(html) == 12  # all cards still in the DOM …
    assert _hidden_cards(html) == 12 - n_photo  # … non-matching are hidden
    # The active chip is marked.
    assert re.search(r'class="mh-arch-chip is-active"[^>]*data-cat="photo"', html) or \
           re.search(r'data-cat="photo"[^>]*aria-current="true"', html)


def test_render_body_escapes_inputs():
    # The pre-resolved URLs are escaped — a quote can't break out of the attr.
    html = G.render_gallery_body(
        gallery_url='/t"x', make_url='/m"y', active_category="all"
    )
    assert '/t"x' not in html  # raw quote must have been escaped
    assert "&#34;" in html or "&quot;" in html


def test_heading_order_valid():
    """Hero h1 → section h2 → card h3 (axe heading-order)."""
    html = G.render_gallery_body(gallery_url="/templates", make_url="/make")
    i_h1 = html.find("<h1")
    i_h2 = html.find("<h2")
    i_h3 = html.find("<h3")
    assert i_h1 != -1 and i_h2 != -1 and i_h3 != -1
    assert i_h1 < i_h2 < i_h3
    assert html.count("<h1") == 1
    assert _cards(html) == html.count("<h3")  # one h3 per card


# ---------------------------------------------------------------------------
# /templates route
# ---------------------------------------------------------------------------


def test_route_renders(client):
    r = client.get("/templates")
    assert r.status_code == 200
    assert r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert "Template gallery" in html
    assert _cards(html) == 12
    assert _hidden_cards(html) == 0


def test_route_category_filter(client):
    r = client.get("/templates?category=data")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    entries = G.gallery_entries()
    n_data = sum(1 for e in entries if e["category"] == "data")
    assert _hidden_cards(html) == 12 - n_data


def test_route_junk_category_falls_back_to_all(client):
    r = client.get("/templates?category=%3Cscript%3E")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert _hidden_cards(html) == 0  # junk → show everything
    # The junk value is never reflected unescaped (no XSS).
    assert "<script>alert" not in html
    assert "category=<script>" not in html


def test_route_works_with_gen_v2_enabled(client, monkeypatch):
    # list_archetypes() scans the layouts dir regardless of the v2 kill-switch,
    # so the gallery shows the full library whether v2 is on or off.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    html = client.get("/templates").get_data(as_text=True)
    assert _cards(html) == 12


# ---------------------------------------------------------------------------
# Navigation + Create-page wiring
# ---------------------------------------------------------------------------


def test_nav_has_templates_link_and_highlights(client):
    html = client.get("/templates").get_data(as_text=True)
    assert "/templates" in html
    assert "Templates</a>" in html
    # The nav item is marked active on the gallery page.
    assert re.search(r'href="/templates"[^>]*class="active"', html)


def test_make_page_links_to_gallery(client):
    html = client.get("/make").get_data(as_text=True)
    assert "mh-arch-gallery-link" in html
    assert 'href="/templates"' in html
    assert "Browse the template gallery" in html


def test_make_gallery_link_is_not_a_hover_preview_tile(client):
    # The Create page's hover-preview tests scan `.mh-template` anchors; the
    # gallery link must NOT masquerade as one (it has no poster preview).
    html = client.get("/make").get_data(as_text=True)
    m = re.search(r'<a class="mh-arch-gallery-link"[^>]*>', html)
    assert m and "mh-template" not in m.group(0)
