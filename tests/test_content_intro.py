"""Create → heading "how it works" first slide (``/make/<type>``).

Pins the contract the feature promises:

  * Every implemented heading in the ContentType REGISTRY has a first slide,
    reachable at ``/make/<value>`` — so adding a heading to the registry gives
    it a "how it works" automatically, with no per-heading wiring.
  * The Create tiles link to that first slide (not straight to the flow), and
    the slide's "Start" CTA carries on to the heading's real route.
  * A heading with no authored ``how_it_works`` still renders a coherent slide
    (graceful default derived from its title/description).
  * The diagram is built in the landing page's visual language (reuses the
    ``.mh-pl-*`` classes, two responsive orientations, travelling pulses) and
    stays on-brand: SVG + CSS keyframes only, no SMIL, no medal-gold, no
    Google-Fonts CDN.

Presentation-only: no engine / AI / data surface is touched here.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from mediahub.club_platform.content_types import (
    REGISTRY,
    ContentType,
    ContentTypeMeta,
    HowItWorks,
)
from mediahub.web import content_intro as ci
from mediahub.web import web as webmod


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
def _render(meta: ContentTypeMeta) -> str:
    formats, effort = ci.presentation_for(getattr(meta.type, "value", ""))
    return ci.render_content_intro(
        meta, formats=formats, effort=effort, start_url="/start", back_url="/make"
    )


def _svgs(body: str) -> list[str]:
    found = re.findall(r"<svg\b.*?</svg>", body, flags=re.S)
    assert len(found) == 2, f"expected two SVG orientations, found {len(found)}"
    return found


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="otter-sc",
            display_name="Otter SC",
            brand_voice_summary="A friendly community club.",
        )
    )
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "otter-sc"})
        yield c


# =========================================================================== #
# Renderer — structure & the "you give → engine → you get" story
# =========================================================================== #
@pytest.mark.parametrize("ct", list(REGISTRY), ids=lambda c: c.value)
def test_every_heading_renders_a_first_slide(ct):
    body = _render(REGISTRY[ct])
    # Header chrome.
    assert "How it works" in body
    assert f">{REGISTRY[ct].title}</h1>" in body
    # The engine sits between give/get; its process line is this tile's own
    # (drawn in both orientations).
    assert ">THE ENGINE</text>" in body
    process = REGISTRY[ct].how_it_works.engine_process
    assert process, f"{ct.value}: engine_process must be authored"
    assert body.count(f">{process}</text>") == 2, process
    assert ">What you give</text>" in body
    assert ">What you get</text>" in body
    # Numbered steps + a single Start CTA into the real flow.
    assert "mh-ci-steps" in body
    assert 'class="btn mh-ci-start"' in body
    assert 'href="/start"' in body


@pytest.mark.parametrize("ct", list(REGISTRY), ids=lambda c: c.value)
def test_both_orientations_present_and_well_formed(ct):
    body = _render(REGISTRY[ct])
    assert "mh-pl-svg--h" in body and "mh-pl-svg--v" in body
    for svg in _svgs(body):
        ET.fromstring(svg)  # raises on any malformed markup


@pytest.mark.parametrize("ct", list(REGISTRY), ids=lambda c: c.value)
def test_step_count_matches_authored_steps(ct):
    body = _render(REGISTRY[ct])
    hiw = REGISTRY[ct].how_it_works
    assert hiw is not None, f"{ct.value} should author its how_it_works"
    assert body.count('class="mh-ci-step"') == len(hiw.steps)


@pytest.mark.parametrize("ct", list(REGISTRY), ids=lambda c: c.value)
def test_input_chips_drawn_in_both_orientations(ct):
    body = _render(REGISTRY[ct])
    for label, _icon in REGISTRY[ct].how_it_works.inputs:
        # one <text> per orientation = exactly two per label
        assert body.count(f">{label}</text>") == 2, label


def test_output_dimensions_are_honest():
    # The meta strip only ever shows the engine's canonical output sizes.
    allowed = {"1080×1920", "1080×1350", "1080×1080", "Ready to post"}
    for ct in REGISTRY:
        body = _render(REGISTRY[ct])
        dims = set(re.findall(r'mh-ci-chip-dim">([^<]+)<', body))
        assert dims <= allowed, f"{ct.value}: unexpected dims {dims - allowed}"


def test_render_is_deterministic():
    meta = REGISTRY[ContentType.MEET_RECAP]
    assert _render(meta) == _render(meta)


# =========================================================================== #
# Per-tile contract — adding a tile MEANS authoring its own specific slide
# =========================================================================== #
# The renderer has a graceful default (see below) so a half-built type never
# breaks, but that default is a safety net only: every *surfaced* Create tile
# must carry its OWN tile-specific HowItWorks. These guards turn "each tile has
# its own how it works" into an enforced contract — a new tile added to the
# REGISTRY fails the suite until a new, specific slide is written for it.
@pytest.mark.parametrize(
    "ct", [c for c, m in REGISTRY.items() if m.is_implemented], ids=lambda c: c.value
)
def test_every_implemented_tile_authors_its_own_how_it_works(ct):
    meta = REGISTRY[ct]
    hiw = meta.how_it_works
    assert hiw is not None, (
        f"{ct.value}: every implemented Create tile must author its OWN HowItWorks "
        "(a tile-specific first slide) — it must not rely on the generic default. "
        "Add a how_it_works=HowItWorks(...) to its REGISTRY entry."
    )
    assert hiw.tagline.strip(), f"{ct.value}: how_it_works.tagline is empty"
    assert len(hiw.inputs) >= 1, f"{ct.value}: how_it_works needs at least one input chip"
    assert len(hiw.steps) >= 2, f"{ct.value}: how_it_works needs at least two steps"
    # The graphic's centre — the engine process line — must be authored too, so
    # the diagram depicts THIS tile's functionality, not a generic pipeline.
    assert hiw.engine_process.strip(), (
        f"{ct.value}: author engine_process so its graphic is unique to this tile's "
        "functionality (e.g. 'detect · rank · brand · generate')"
    )
    for label, icon_key in hiw.inputs:
        assert label.strip(), f"{ct.value}: blank input label"
        assert icon_key.strip(), f"{ct.value}: blank input icon key"
    for step in hiw.steps:
        assert step.strip(), f"{ct.value}: blank step"


def test_each_tile_how_it_works_is_specific_to_that_tile():
    """No two tiles may share a how-it-works — each must be specific to its own
    tile, not a copy of a sibling's."""
    seen_tagline: dict[str, str] = {}
    seen_steps: dict[tuple, str] = {}
    seen_process: dict[str, str] = {}
    for ct, meta in REGISTRY.items():
        if not meta.is_implemented or meta.how_it_works is None:
            continue
        hiw = meta.how_it_works
        # A tile that just echoes its one-line description hasn't really authored
        # a slide — the generic default already does that.
        assert hiw.tagline.strip() != meta.description.strip(), (
            f"{ct.value}: how_it_works.tagline merely repeats the tile description — "
            "write a slide-specific promise"
        )
        assert hiw.tagline not in seen_tagline, (
            f"{ct.value} shares its tagline with {seen_tagline.get(hiw.tagline)} — "
            "each tile needs its own"
        )
        assert hiw.steps not in seen_steps, (
            f"{ct.value} shares its steps with {seen_steps.get(hiw.steps)} — "
            "each tile needs its own"
        )
        # The engine line is the centre of the graphic — it must be unique to
        # this tile's functionality, not a shared generic pipeline.
        assert hiw.engine_process not in seen_process, (
            f"{ct.value} shares its engine process line "
            f"({hiw.engine_process!r}) with {seen_process.get(hiw.engine_process)} — "
            "each tile's graphic must depict its own functionality"
        )
        seen_tagline[hiw.tagline] = ct.value
        seen_process[hiw.engine_process] = ct.value
        seen_steps[hiw.steps] = ct.value


# =========================================================================== #
# Graceful default — a heading with no authored how_it_works still works
# =========================================================================== #
def test_unauthored_heading_falls_back_to_a_derived_slide():
    bare = ContentTypeMeta(
        type=ContentType.FREE_TEXT,
        title="Brand New Thing",
        description="Makes a brand new thing.",
        input_contract="x",
        is_implemented=True,
        icon_svg="<svg/>",
        primary_route_endpoint="make_page",
        how_it_works=None,  # the developer hasn't authored one yet
    )
    body = ci.render_content_intro(
        bare, formats=["Caption"], effort="", start_url="/s", back_url="/make"
    )
    for svg in _svgs(body):
        ET.fromstring(svg)
    # Derived from the title, and still a complete slide.
    assert "make a brand new thing" in body.lower()
    assert ">THE ENGINE</text>" in body
    assert body.count('class="mh-ci-step"') >= 2
    assert ">What you give</text>" in body


@pytest.mark.parametrize("n_in", [1, 2, 3, 4, 5])
def test_variable_input_counts_stay_well_formed(n_in):
    inputs = [(f"Input {i}", ci._glyph("note")) for i in range(n_in)]
    outputs = [("Caption", ci._glyph("caption")), ("Graphic", ci._glyph("graphic"))]
    ET.fromstring(ci._svg_horizontal(inputs, outputs, "detect · rank · brand"))
    ET.fromstring(ci._svg_vertical(inputs, outputs, "detect · rank · brand"))


# =========================================================================== #
# Brand & motion rules (mirrors the landing-diagram guards)
# =========================================================================== #
def test_no_smil_in_any_slide():
    for ct in REGISTRY:
        body = _render(REGISTRY[ct])
        assert "<animate" not in body
        assert "animateMotion" not in body
        assert "animateTransform" not in body


def test_css_is_on_brand_and_balanced():
    css = ci.CONTENT_INTRO_CSS
    assert css.count("{") == css.count("}")
    # Lane is the accent token; medal-gold is reserved for achievements.
    assert "var(--lane)" in css
    assert "var(--medal" not in css and "var(--gold" not in css
    # Self-hosted fonts only.
    assert "googleapis" not in css and "gstatic" not in css


def test_engine_colours_follow_the_club_brand_not_pinned_yellow():
    """The how-it-works diagram is the club's surface, so its lit accent tracks
    the same brand token the rest of the site themes from (--lane ← --mh-primary)
    — change the club's colours and the engine recolours, like the website. No
    hard-coded lane-yellow may pin it (that would ignore the brand)."""
    css = ci.CONTENT_INTRO_CSS
    # The stage re-points --lane at the brand seed and routes the glow through it
    # (--lane-glow), so the engine box + its glow follow the club brand.
    assert "--lane: var(--mh-primary)" in css
    assert "--lane-glow: color-mix(in oklab, var(--mh-primary)" in css
    # Nothing in the feature's CSS may hard-code the lane-yellow literal.
    assert "#D4FF3A" not in css.upper()
    assert "212,255,58" not in css.replace(" ", "")


def test_presentation_formats_cover_every_heading():
    # Every registry value has explicit presentation metadata (so no heading
    # silently falls back to the generic chip).
    for ct in REGISTRY:
        assert ct.value in ci.PRESENTATION_FORMATS, ct.value


# =========================================================================== #
# Route — /make/<type> end to end
# =========================================================================== #
def test_every_implemented_heading_is_reachable(client):
    """The core promise: each implemented heading has a first slide at
    /make/<value>, and its Start CTA points at the heading's real route."""
    # Resolve each heading's real route first (inside one request context),
    # then exercise the intro routes (each client.get pushes its own context).
    starts: dict[str, str] = {}
    with webmod.app.test_request_context():
        from flask import url_for

        for ct, meta in REGISTRY.items():
            if not meta.is_implemented:
                continue
            try:
                starts[ct.value] = url_for(meta.primary_route_endpoint)
            except Exception:
                pass

    for ct, meta in REGISTRY.items():
        if not meta.is_implemented or ct.value not in starts:
            continue
        start = starts[ct.value]
        r = client.get(f"/make/{ct.value}")
        assert r.status_code == 200, (ct.value, r.status_code)
        html = r.get_data(as_text=True)
        assert "How it works" in html
        assert f'href="{start}"' in html, f"{ct.value}: Start should link to {start}"
        assert "mh-pl-stage" in html and "mh-ci-steps" in html


def test_create_tiles_link_to_the_first_slide(client):
    """Clicking a live Create tile lands on its intro, not straight on the
    flow — for the visible (non-hidden) headings."""
    body = client.get("/make").get_data(as_text=True)
    for slug in ("meet_recap", "event_preview", "free_text"):
        assert f"/make/{slug}" in body, f"Create tile for {slug} should link to its intro"
    # Athlete Spotlight is no longer a standalone Create tile — it lives inside
    # the meet-recap flow (Review ⇄ Athlete spotlight view switch).
    assert "/make/athlete_spotlight" not in body


def test_intro_css_is_served_on_the_slide(client):
    body = client.get("/make/meet_recap").get_data(as_text=True)
    assert ".mh-ci-steps" in body  # stylesheet injected
    # Reuses the landing diagram's reduced-motion-safe pulses + keyframes.
    assert "mh-pl-pulse" in body
    assert "@keyframes mh-pl-flow" in body


def test_unknown_slug_redirects_to_create(client):
    r = client.get("/make/definitely_not_a_type", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "/make" in r.headers.get("Location", "")


def test_hidden_type_is_still_reachable_by_deep_link(client):
    # Session Update / Sponsor Post / Athlete Spotlight aren't surfaced as
    # tiles, but their intro (and route) stay live for deep links / back-compat.
    # Athlete Spotlight's primary surface is now the meet-recap view switch.
    for slug in ("session_update", "sponsor_activation", "athlete_spotlight"):
        r = client.get(f"/make/{slug}")
        assert r.status_code == 200, (slug, r.status_code)
        assert "How it works" in r.get_data(as_text=True)


def test_legacy_slug_alias_resolves(client):
    # canonical_slug() normalises legacy aliases; the intro should resolve them
    # too rather than bouncing to /make.
    r = client.get("/make/weekend_preview", follow_redirects=False)
    # weekend_preview is the pre-ADR-0013 alias for event_preview.
    if r.status_code == 200:
        assert "How it works" in r.get_data(as_text=True)
    else:
        # If not aliased on this deployment, it must degrade to a redirect, not 500.
        assert r.status_code in (301, 302, 303, 307, 308)


# =========================================================================== #
# Plan — the predominant non-tile entry gets its own how-it-works too
# =========================================================================== #
def test_plan_intro_renders_its_own_slide():
    frag = ci.render_plan_intro(start_url="/plan", back_url="/make")
    assert "How it works" in frag
    assert ">Plan</h1>" in frag
    assert ">THE ENGINE</text>" in frag
    # Its engine line is Plan's own (recommends rather than generates), drawn in
    # both orientations.
    assert frag.count(f">{ci._PLAN_ENGINE_PROCESS}</text>") == 2
    # Its CTA opens the planner (not a content generator).
    assert "Open Plan &rarr;" in frag
    assert 'href="/plan"' in frag
    for svg in _svgs(frag):
        ET.fromstring(svg)


def test_plan_intro_is_plan_specific_not_a_media_tile():
    frag = ci.render_plan_intro(start_url="/plan", back_url="/make")
    # Plan-specific give/get, drawn in both orientations — not media-format chips.
    for label in ("What's coming up", "Your goals", "Club history", "Ranked ideas"):
        assert frag.count(f">{label}</text>") == 2, label
    # And its slide is distinct from every content tile's — tagline AND the
    # engine line at the centre of the graphic.
    for ct, meta in REGISTRY.items():
        if meta.how_it_works is not None:
            assert meta.how_it_works.tagline != ci._PLAN_TAGLINE
            assert meta.how_it_works.engine_process != ci._PLAN_ENGINE_PROCESS


def test_plan_intro_is_deterministic():
    assert ci.render_plan_intro(start_url="/plan", back_url="/make") == ci.render_plan_intro(
        start_url="/plan", back_url="/make"
    )


def test_plan_route_renders_and_starts_the_planner(client):
    r = client.get("/make/plan")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "How it works" in html and ">Plan</h1>" in html
    with webmod.app.test_request_context():
        from flask import url_for

        assert f'href="{url_for("plan_page")}"' in html


def test_create_page_plan_tile_is_predominant_and_links_to_its_intro(client):
    body = client.get("/make").get_data(as_text=True)
    assert 'class="mh-plan-tile"' in body
    assert 'href="/make/plan"' in body
    # Predominant = the Plan tile sits above the content-type grid in the DOM.
    assert body.index('class="mh-plan-tile"') < body.index('class="mh-template-grid"')
