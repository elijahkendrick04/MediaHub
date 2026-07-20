"""Regression: the fresh-visitor "Just looking?" demo line on the home page
used to link to /sign-in with the label "browse pinned organisations". That
reused MediaHub's internal jargon for "the org bound into this session"
(``_pin_active_profile`` / "Pinned organisation" eyebrow) to describe a
completely different thing: the /sign-in picker's list of OTHER saved
organisation profiles on this deployment (an anonymous session sees the
unbound/pilot ones). A first-time volunteer has no way to know "pinned"
means "already set up here" rather than "featured" or "partner" clubs, so
the CTA read as unexplained jargon (finding: home / user_brain).

The fix drops "pinned" from the link text so it doesn't collide with the
unrelated internal meaning, without claiming these are curated demo/sample
orgs (they are genuinely other saved profiles on the deployment).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app(web_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    application = web_module.create_app()
    application.config["TESTING"] = True
    return application


def test_home_demo_line_does_not_say_pinned_organisations(app):
    """A fresh, signed-out visitor must not see the unexplained 'pinned
    organisations' phrase — it borrows session-pinning jargon that has no
    meaning established on the page."""
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    assert "mh-demo-line" in body, "fresh visitor should see the demo line"
    assert "pinned organisations" not in body.lower()


def test_home_demo_line_links_to_sign_in_with_clear_label(app):
    """The sign-in link should still be present (functionality unchanged),
    just relabelled so it's understandable without prior context."""
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    start = body.index('class="mh-demo-line"')
    end = body.index("</p>", start)
    demo_line = body[start:end]
    assert '/sign-in' in demo_line
    assert "organisation" in demo_line.lower()
