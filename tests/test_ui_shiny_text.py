"""Shiny-text — a one-shot sheen swept *through* a heading's glyphs.

MediaHub's motion kit (``theme-motion.css`` + ``ui-kit.js``) is a first-party,
dependency-free re-implementation of the effects worth borrowing from React
component libraries — vanilla CSS + a tiny progressive-enhancement JS layer,
because the web UI is a Flask / f-string-Jinja monolith with no bundler.

Auditing reactbits.dev against that kit, almost everything worth having was
already present (split/blur text, gradient text, rotating words, spotlight,
tilt, glare, compare, count-up, tracing beam, …) or was a decorative WebGL
background / cursor gimmick that the house rules reject ("avoid generic
AI-looking SaaS patterns", "no over-animation — motion only for feedback and
hierarchy"). The one genuine gap: a highlight band that travels *along the
letterforms* — gradient-text is a static fill and glare is a card-level cursor
sheen, but neither sweeps the glyphs. ``ShinyText`` filled it.

This pins the port, ``.mh-shiny-text``:

  1. CSS primitive — adaptive (``currentColor`` base, so the rest state is the
     inherited colour with no recolour), the clip is gated behind ``@supports``
     (legacy engines keep plain text), there is a ``mh-shine`` keyframe, and the
     sweep is stilled under ``prefers-reduced-motion``.
  2. No-JS / pre-init safe — the class never hides its text (no ``opacity:0`` /
     ``visibility:hidden`` and, unlike text-generate, no ``.mh-js`` gate), so the
     heading is always legible whether or not the kit runs.
  3. It rides the shared ``.is-in`` reveal (``ui-kit.js`` ``observe``), so there
     is one reveal convention, not a second bespoke trigger.
  4. Singular, earned home — the athlete-spotlight Content builder wears it on
     exactly one element: the spotlighted swimmer's name, inside the hero
     ``<h1>``. Never a grid (that would be the over-animation the rules forbid).

Presentation-only: the deterministic engine, AI surfaces and explainability
logic are untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod


# --------------------------------------------------------------------------- #
# 1) The CSS primitive ships in the global bundle
# --------------------------------------------------------------------------- #
class TestShinyTextCss:
    def test_primitive_is_defined(self):
        css = webmod.BASE_CSS
        assert ".mh-shiny-text" in css
        # Adaptive base: the gradient is built on currentColor, so the rest
        # state is exactly the inherited colour — no forced recolour.
        assert "currentColor" in css
        assert "@keyframes mh-shine" in css

    def test_clip_is_gated_behind_supports(self):
        # The background-clip:text reveal only applies where it is supported;
        # legacy engines fall through to plain (inherited-colour) text.
        css = webmod.BASE_CSS
        assert re.search(
            r"@supports \(\(-webkit-background-clip: text\) or "
            r"\(background-clip: text\)\) \{[^@]*\.mh-shiny-text",
            css,
            re.DOTALL,
        ), "shiny-text clip is not gated behind an @supports test"

    def test_sweep_stands_down_under_reduced_motion(self):
        css = webmod.BASE_CSS
        assert ".mh-shiny-text.is-in { animation: none; }" in css

    def test_rest_state_never_hides_the_text(self):
        # Unlike text-generate (which hides words until .is-in and is therefore
        # .mh-js-gated), shiny-text's rest state is the fully-visible heading.
        # Guard against a regression that hides it: no opacity:0 / visibility
        # hidden bound to the class, and no .mh-js gate in front of it.
        css = webmod.BASE_CSS
        block = re.search(r"\.mh-shiny-text[^@]*@keyframes mh-shine", css, re.DOTALL)
        assert block, "could not isolate the shiny-text CSS block"
        chunk = block.group(0)
        assert "opacity: 0" not in chunk
        assert "visibility: hidden" not in chunk
        assert ".mh-js .mh-shiny-text" not in css


# --------------------------------------------------------------------------- #
# 2) The kit hooks it into the shared reveal convention
# --------------------------------------------------------------------------- #
class TestShinyTextJs:
    def test_ui_kit_observes_shiny_text(self):
        js = (Path(webmod.__file__).resolve().parent / "static" / "js" / "ui-kit.js").read_text()
        # Registered for the shared IntersectionObserver, alongside the other
        # .is-in reveal effects — so the same observer flips it on view.
        assert ".mh-shiny-text" in js
        assert re.search(r'each\(root,\s*"[^"]*\.mh-shiny-text[^"]*",\s*observe\)', js), (
            "ui-kit.js does not register .mh-shiny-text with the shared observe()"
        )


# --------------------------------------------------------------------------- #
# 3) The singular, earned home: the spotlight athlete name
# --------------------------------------------------------------------------- #
@pytest.fixture
def spotlight_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    rec = {
        "form_data": {
            "source": "athlete_spotlight",
            "swimmer_name": "Alice Marsh",
            "run_id": "r1",
            "swimmer_key": "alice",
            "n_approved": 3,
            "tone": "",
        },
        "cards": [{}],
        "title": "Alice Marsh",
    }
    with webmod.app.test_request_context("/"):
        return webmod._render_content_builder("pk_test", rec, mode="spotlight")


class TestSpotlightWearsShinyText:
    def test_name_is_wrapped_once(self, spotlight_html):
        # Exactly one shiny element on the page — a singular celebratory moment,
        # never sprayed across a grid of cards.
        assert spotlight_html.count("mh-shiny-text") == 1

    def test_shiny_wraps_the_name_in_the_hero_h1(self, spotlight_html):
        assert '<h1><span class="mh-shiny-text">Alice Marsh</span></h1>' in spotlight_html

    def test_name_is_html_escaped(self, tmp_path, monkeypatch):
        # The swimmer name still routes through _h() inside the shiny wrapper —
        # the effect must not open an XSS hole in a user-supplied name.
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
        rec = {
            "form_data": {
                "source": "athlete_spotlight",
                "swimmer_name": '<script>alert(1)</script>',
            },
            "cards": [{}],
        }
        with webmod.app.test_request_context("/"):
            html = webmod._render_content_builder("pk_x", rec, mode="spotlight")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
