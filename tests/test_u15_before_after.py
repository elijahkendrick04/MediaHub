"""U.15 — before/after reveal slider on the landing page.

Pins the U.15 deliverable (presentation-only; the deterministic engine, the
pipeline and every AI surface are untouched): a drag-to-wipe slider on the home
page that reveals between a raw results file (BEFORE) and the finished branded
graphic MediaHub ships back (AFTER). Single vanilla-JS initialiser, no library
— inspired by Lovi (lovi.care).

What these tests hold in place:
  * the figure renders on the landing page for both a fresh visitor and a
    returning pinned organisation (it is a marketing element shown to everyone)
  * the control is genuinely keyboard-accessible (a real <button role="slider">
    with the full ARIA contract), not a mouse-only toy
  * the two panes show the SAME worked example (Tom Davies, 52.41, PB -0.74s),
    so the page reads as one honest "ugly file in, on-brand card out" story and
    stays consistent with the sample card below it
  * the slider degrades safely — the markup is a legible still with JS off, and
    every motion is a no-op under prefers-reduced-motion
  * the CSS + the JS initialiser actually ship in the rendered document, and the
    initialiser is defined exactly once (no drift / duplication)
"""
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.web.club_profile import ClubProfile, save_profile


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_u2_states.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True  # disables CSRF + the login-idle drop
    with app.test_client() as c:
        yield c


def _home(client):
    resp = client.get("/")
    assert resp.status_code == 200, f"/ → {resp.status_code}"
    return resp.get_data(as_text=True)


def _pin_ready_org(client):
    """Persist a ready organisation and pin it into the session."""
    save_profile(ClubProfile(
        profile_id="riverside",
        display_name="Riverside SC",
        brand_voice_summary="A friendly, fast club.",
    ))
    resp = client.post("/api/organisation/active", data={"profile_id": "riverside"})
    assert resp.status_code == 200, resp.get_json()


# =========================================================================== #
# Presence + structure
# =========================================================================== #
def test_home_renders_before_after_figure(client):
    body = _home(client)
    # Exactly one slider figure, opted into the JS via data-mh-ba.
    assert body.count("data-mh-ba") >= 1
    assert '<figure class="mh-ba"' in body
    assert "mh-ba-pane mh-ba-after" in body     # the branded-graphic pane
    assert "mh-ba-pane mh-ba-before" in body    # the raw-file pane (clipped on top)
    assert 'class="mh-ba-handle"' in body       # the drag divider


def test_section_has_drag_to_reveal_framing(client):
    body = _home(client)
    assert "Drag to reveal" in body
    assert "mh-ba-hint" in body                 # the affordance hint line
    # The hint names the keyboard path, not just dragging.
    assert "or focus it and use" in body
    assert "to wipe" in body


def test_slider_appears_after_steps_and_before_bento(client):
    """Narrative order: hero → workflow steps → the literal transformation →
    the bento of outputs. The slider is the worked proof between them."""
    body = _home(client)
    i_steps = body.index("From the results sheet to")     # steps section title
    i_slider = body.index("data-mh-ba")
    i_bento = body.index("A results sheet in.")            # bento section title
    assert i_steps < i_slider < i_bento


# =========================================================================== #
# Accessibility — the handle is a real keyboard slider
# =========================================================================== #
def test_handle_is_a_keyboard_operable_slider(client):
    body = _home(client)
    # A focusable <button>, not a bare div, exposing the slider role + contract.
    assert '<button class="mh-ba-handle" type="button" role="slider"' in body
    for attr in (
        'aria-orientation="horizontal"',
        'aria-valuemin="0"',
        'aria-valuemax="100"',
        'aria-valuenow="50"',          # starts centred
        'aria-valuetext=',             # human-readable position
    ):
        assert attr in body, f"missing {attr} on the slider handle"


def test_figure_carries_a_text_alternative(client):
    body = _home(client)
    # The figure describes itself to assistive tech…
    assert 'aria-label="Before and after:' in body
    # …and the decorative mockups are hidden so they are not double-announced.
    assert 'class="mh-ba-card" aria-hidden="true"' in body
    assert 'class="mh-ba-sheet" aria-hidden="true"' in body


def test_default_position_is_centred(client):
    body = _home(client)
    assert 'aria-valuenow="50"' in body
    # The CSS seeds the custom property at the same midpoint.
    assert "--mh-ba-pos: 50%" in body


# =========================================================================== #
# Honesty — the same worked example flows through both panes
# =========================================================================== #
def test_same_athlete_and_time_in_both_panes(client):
    body = _home(client)
    # The branded card…
    assert "Tom Davies" in body
    assert "52.41" in body
    assert "Personal best" in body
    # …and the raw sheet shows the very same finals time for the same swimmer,
    # so "input → output" is one consistent, honest example (no invented data).
    assert "Davies, Tom" in body
    assert body.count("52.41") >= 2     # appears in the raw sheet AND the card


def test_raw_sheet_reads_like_a_real_export(client):
    body = _home(client)
    assert "HY-TEK" in body                      # the meet-manager provenance
    assert "100 LC Metre Free" in body           # an event header line
    assert "Finals" in body                      # a results column


# =========================================================================== #
# Returning, pinned organisation — the slider is shown to everyone
# =========================================================================== #
def test_slider_renders_for_pinned_org(client):
    _pin_ready_org(client)
    body = _home(client)
    # Returning-user hero copy is in play…
    assert "Ready" in body
    # …and the marketing slider is still present (added unconditionally).
    assert "data-mh-ba" in body
    assert 'class="mh-ba-handle"' in body
    assert "Tom Davies" in body


# =========================================================================== #
# The CSS + JS actually ship in the document
# =========================================================================== #
def test_slider_css_is_in_the_document(client):
    body = _home(client)
    assert ".mh-ba {" in body                                   # the frame rule
    assert "clip-path: inset(0 calc(100% - var(--mh-ba-pos))" in body  # the wipe
    assert ".mh-ba-handle {" in body


def test_slider_js_initialiser_ships_and_is_namespaced(client):
    body = _home(client)
    assert "function bindBeforeAfter()" in body
    assert "MH.bindBeforeAfter = bindBeforeAfter;" in body
    # Idempotent binding guard so a re-init never double-wires a figure.
    assert "data-mh-ba-bound" in body


# =========================================================================== #
# Reduced motion + safe degradation
# =========================================================================== #
def test_reduced_motion_disables_the_decorative_sweep(client):
    body = _home(client)
    # CSS: under reduced motion the animate transition is neutralised.
    assert "prefers-reduced-motion: reduce" in body
    assert ".mh-ba--animate .mh-ba-before" in body
    # JS: the intro "tell" is gated behind the reduced-motion probe.
    src = Path(webmod.__file__).read_text(encoding="utf-8")
    intro = src[src.index("function bindBeforeAfter()"):]
    intro = intro[: intro.index("MH.bindBeforeAfter = bindBeforeAfter;")]
    assert "if (!prefersReduced) {" in intro     # intro hint only when motion allowed


def test_markup_is_a_legible_still_without_js(client):
    """With JS off the figure is just two stacked panes + a centred divider —
    both halves of the worked example are present in the static HTML, so the
    landing still communicates input→output."""
    body = _home(client)
    # Both panes' real content is server-rendered, not injected by JS.
    assert "mh-ba-sheet-body" in body and "mh-ba-card-time" in body


# =========================================================================== #
# No drift — the initialiser is defined exactly once
# =========================================================================== #
def test_initialiser_defined_once():
    src = Path(webmod.__file__).read_text(encoding="utf-8")
    assert src.count("function bindBeforeAfter()") == 1
    assert src.count("MH.bindBeforeAfter = bindBeforeAfter;") == 1


def test_slider_html_built_in_home_route_only():
    """The figure markup lives in the home() builder, not scattered across the
    monolith — one source of truth for the landing element."""
    src = Path(webmod.__file__).read_text(encoding="utf-8")
    assert src.count('<figure class="mh-ba"') == 1
    assert src.count("before_after_html = (") == 1
