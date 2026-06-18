"""U.9 — cycling hero accent word.

Pins the U.9 deliverable (presentation-only; the deterministic engine, AI
surfaces and explainability logic are untouched): the signed-out landing
hero's content-type noun is the gold serif-italic accent (``.editorial``) and
crossfades through what MediaHub makes — stories / reels / graphics / captions
— with a CSS opacity crossfade driven by a tiny inline script.

What the tests guard:

  * the rotator markup on the signed-out hero — one ``.editorial`` word per
    content type, in the spec order, the first ``is-active`` (so it shows with
    no JavaScript), the rest ``aria-hidden`` decorative cycles
  * accessibility — exactly one word is readable by assistive tech, so a screen
    reader hears a sensible single phrase rather than four stacked words
  * the crossfade is CSS (opacity transition on the stacked grid items) and the
    box auto-sizes to the widest word so the trailing "out." never reflows
  * the script honours reduced motion, degrades without JS, and pauses while the
    tab is backgrounded — and it ships ONLY when the rotator is on the page
  * the returning-user "Ready to file." hero stays static (no rotator, no
    script) — U.9 scopes to the landing hero a prospective customer sees
"""
from __future__ import annotations

import re

import pytest

from mediahub.web import web as webmod
from mediahub.web.club_profile import ClubProfile, save_profile


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_u2_states.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh deployment with no organisations → the signed-out landing hero."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def ready_client(tmp_path, monkeypatch):
    """A pinned, ready organisation → the returning-user dashboard hero."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    save_profile(
        ClubProfile(
            profile_id="wycombe",
            display_name="Wycombe District SC",
            brand_voice_summary="Friendly competitive club.",
            brand_capture_status="ok_heuristic",
        )
    )
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "wycombe"
        yield c


@pytest.fixture
def orgs_present_client(tmp_path, monkeypatch):
    """A deployment that already has an organisation, viewed *signed out* (no
    active profile in the session). The landing still shows the
    prospective-customer hero — so the rotator and its script must ship here
    too, not only on a brand-new deployment with zero organisations.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    save_profile(
        ClubProfile(
            profile_id="wycombe",
            display_name="Wycombe District SC",
            brand_voice_summary="Friendly competitive club.",
            brand_capture_status="ok_heuristic",
        )
    )
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        # No session_transaction → the visitor is signed out.
        yield c


def _home(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, f"/ → {resp.status_code}"
    return resp.get_data(as_text=True)


def _hero_h1(html: str) -> str:
    m = re.search(r"<h1>.*?</h1>", html, re.DOTALL)
    assert m, "hero <h1> not found"
    return m.group(0)


# A word span inside the rotator: captures the class attr and the word text.
_ITEM_RE = re.compile(
    r'<span class="([^"]*\bmh-word-cycle-item\b[^"]*)"([^>]*)>([^<]+)</span>'
)


# =========================================================================== #
# Helper + constants (pure — no app, no request)
# =========================================================================== #
def test_content_words_match_the_spec_exactly():
    # The roadmap pins the cycle: stories / reels / graphics / captions.
    assert webmod._HERO_CONTENT_WORDS == ("stories", "reels", "graphics", "captions")


def test_helper_is_pure_and_deterministic():
    assert webmod._hero_word_cycle_html() == webmod._hero_word_cycle_html()


def test_helper_emits_one_editorial_word_per_content_type_in_order():
    html = webmod._hero_word_cycle_html()
    items = _ITEM_RE.findall(html)
    assert [w for _, _, w in items] == list(webmod._HERO_CONTENT_WORDS)
    # Every cycling word reuses the shared gold serif-italic accent class so it
    # is styled identically to the rest of the app's editorial emphasis.
    assert all("editorial" in cls for cls, _, _ in items)


def test_helper_marks_only_the_first_word_active():
    html = webmod._hero_word_cycle_html()
    items = _ITEM_RE.findall(html)
    active = [w for cls, _, w in items if "is-active" in cls]
    assert active == ["stories"], "exactly the first word ships active (no-JS fallback)"


def test_helper_container_carries_the_script_hook():
    html = webmod._hero_word_cycle_html()
    assert 'class="mh-word-cycle"' in html
    assert "data-mh-word-cycle" in html  # the [data-mh-word-cycle] JS selector


# =========================================================================== #
# Accessibility — a screen reader hears one sensible word, not four
# =========================================================================== #
def test_only_the_first_word_is_readable_rest_aria_hidden():
    html = webmod._hero_word_cycle_html()
    items = _ITEM_RE.findall(html)
    readable = [w for _, attrs, w in items if "aria-hidden" not in attrs]
    hidden = [w for _, attrs, w in items if 'aria-hidden="true"' in attrs]
    assert readable == ["stories"], "AT reads exactly the one canonical word"
    assert hidden == ["reels", "graphics", "captions"], "the cycles are decorative"


# =========================================================================== #
# Signed-out landing hero — the rotator + its script ship
# =========================================================================== #
def test_signed_out_hero_renders_the_rotator(client):
    h1 = _hero_h1(_home(client))
    # Reads "Results in. On-brand <cycling word> out."
    assert "Results in." in h1
    assert "On-brand" in h1
    assert h1.rstrip().endswith("out.</h1>")
    assert "data-mh-word-cycle" in h1
    for word in webmod._HERO_CONTENT_WORDS:
        assert f">{word}</span>" in h1


def test_signed_out_hero_accent_moved_off_on_brand_onto_the_cycle(client):
    """The single editorial accent now lives on the cycling word, not 'On-brand'
    (one editorial move per hero — the eye follows the animation)."""
    h1 = _hero_h1(_home(client))
    assert "<em class=\"editorial\">On-brand</em>" not in h1
    items = _ITEM_RE.findall(h1)
    assert [w for _, _, w in items] == list(webmod._HERO_CONTENT_WORDS)


def test_signed_out_hero_ships_the_cycle_script(client):
    body = _home(client)
    assert "<script>" in body
    assert "data-mh-word-cycle" in body
    # the script targets the rotator and toggles the active word
    assert "querySelectorAll('.mh-word-cycle-item')" in body
    assert "is-active" in body


def test_cycle_script_present_exactly_once(client):
    body = _home(client)
    assert body.count(webmod._HERO_WORD_CYCLE_JS) == 1


# =========================================================================== #
# The script's safety guards (reduced motion, no-JS, off-screen pause)
# =========================================================================== #
def test_script_honours_reduced_motion():
    js = webmod._HERO_WORD_CYCLE_JS
    assert "prefers-reduced-motion: reduce" in js
    assert "matchMedia" in js
    # the guard returns BEFORE any timer starts
    guard = js[: js.index("setInterval")]
    assert "return" in guard and "reduce" in guard


def test_script_pauses_when_tab_backgrounded():
    js = webmod._HERO_WORD_CYCLE_JS
    assert "visibilitychange" in js
    assert "document.hidden" in js
    assert "clearInterval" in js


def test_script_is_a_noop_without_a_rotator():
    js = webmod._HERO_WORD_CYCLE_JS
    # bails when the hook is absent and when there is nothing to cycle
    assert "if (!box) return;" in js
    assert "items.length < 2" in js


# =========================================================================== #
# CSS — pure-CSS crossfade, auto-sizing stack
# =========================================================================== #
def test_css_defines_the_stacked_crossfade():
    css = webmod.BASE_CSS
    assert ".mh-word-cycle" in css
    # stacked in one auto-sizing cell so "out." never reflows as the word changes
    assert "inline-grid" in css
    assert "grid-area: 1 / 1" in css
    # the crossfade itself is a CSS opacity transition
    assert "transition: opacity" in css
    assert ".mh-word-cycle-item.is-active" in css


def test_css_default_item_is_transparent_active_is_opaque():
    css = webmod.BASE_CSS
    # base item hidden (opacity 0), active item shown (opacity 1) → crossfade
    base = re.search(r"\.mh-hero h1 \.mh-word-cycle-item\s*\{[^}]*\}", css)
    active = re.search(r"\.mh-hero h1 \.mh-word-cycle-item\.is-active\s*\{[^}]*\}", css)
    assert base and "opacity: 0" in base.group(0)
    assert active and "opacity: 1" in active.group(0)


# =========================================================================== #
# Returning-user hero — static, no rotator, no script
# =========================================================================== #
def test_ready_org_hero_does_not_cycle(ready_client):
    body = _home(ready_client)
    h1 = _hero_h1(body)
    assert "Wycombe District SC" in h1
    assert "<em class=\"editorial\">Ready</em>" in h1
    # no rotator markup, and crucially no cycle script on this page
    assert "data-mh-word-cycle" not in body
    assert webmod._HERO_WORD_CYCLE_JS not in body
    assert "mh-word-cycle-item" not in h1


def test_ready_org_display_name_is_escaped(ready_client, tmp_path):
    """Defence-in-depth: the returning-user hero interpolates the org name, so
    it must stay HTML-escaped (the cycling words are constants and need none)."""
    save_profile(
        ClubProfile(
            profile_id="xss",
            display_name='<script>alert(1)</script>',
            brand_voice_summary="x",
            brand_capture_status="ok_heuristic",
        )
    )
    with ready_client.session_transaction() as s:
        s["active_profile_id"] = "xss"
    body = _home(ready_client)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


# =========================================================================== #
# Scope: the rotator follows the *signed-out* state, not the *zero-org* state
# =========================================================================== #
def test_signed_out_hero_cycles_even_when_an_org_exists(orgs_present_client):
    """The rotator is scoped to the prospective-customer (signed-out) hero, not
    to a brand-new zero-org deployment. Once a club exists but nobody is signed
    in, the landing still shows that hero — so the cycle and its script ship.
    """
    body = _home(orgs_present_client)
    h1 = _hero_h1(body)
    # The prospective-customer hero, not the returning-user "Ready to file." one.
    assert "Results in." in h1
    assert "<em class=\"editorial\">Ready</em>" not in h1
    # "Sign in" is still present on the n_orgs > 0 signed-out branch (as a
    # secondary CTA) — it proves this is the with-orgs path, distinct from
    # the zero-org fixture.
    assert "Sign in" in body
    # …and the full rotator + its one script still ship.
    assert "data-mh-word-cycle" in h1
    for word in webmod._HERO_CONTENT_WORDS:
        assert f">{word}</span>" in h1
    assert body.count(webmod._HERO_WORD_CYCLE_JS) == 1


# =========================================================================== #
# The crossfade's behavioural contract: cadence + wrap-around
# =========================================================================== #
def test_script_cadence_and_wrap_are_pinned():
    """The crossfade cadence (a calm 2.6s dwell, not a frantic flicker) and the
    wrap-around — advancing modulo the word count so it loops back to the first
    word rather than running off the end — are part of the behavioural contract.
    """
    js = webmod._HERO_WORD_CYCLE_JS
    assert "setInterval(step, 2600)" in js, "2.6s dwell between words"
    # i = (i + 1) % items.length → advance one, wrapping to the first word.
    assert "(i + 1) % items.length" in js
