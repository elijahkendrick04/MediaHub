"""Regression: the hero's 3-step "how it works" strip must use the same
step labels as the live product demo directly below it on the home page.

Before this fix the hero strip called the steps "Upload results" /
"Review the drafts" / "Approve & post" while the looping demo just below
it (``_hero_product_demo()``) called the same three stages "Generate" /
"Review" / "Approve" — a visitor reads two different vocabularies for the
same flow on one screen, above the fold.
"""
from __future__ import annotations

import re
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


def _hero_step_labels(body: str) -> list[str]:
    hero_start = body.index('<ol class="mh-hero-steps"')
    hero_end = body.index("</ol>", hero_start)
    hero_block = body[hero_start:hero_end]
    return re.findall(r'<span class="t">([^<]+)</span>', hero_block)


def _demo_step_labels(body: str) -> list[str]:
    demo_start = body.index('<div class="mh-demo-steps">')
    demo_end = body.index("</div>", demo_start)
    demo_block = body[demo_start:demo_end]
    return re.findall(r'<span class="mh-demo-step s\d">.*?</span>(\w+)</span>', demo_block)


def test_hero_steps_use_the_same_labels_as_the_live_demo_below(app):
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)

    hero_labels = _hero_step_labels(body)
    demo_labels = _demo_step_labels(body)

    assert hero_labels, "could not find the hero's 3-step strip on the home page"
    assert demo_labels, "could not find the live product demo's step indicator"
    assert len(hero_labels) == len(demo_labels) == 3

    assert hero_labels == demo_labels, (
        "the hero's 3-step strip and the live demo's step indicator must use "
        f"identical labels for the same 3 stages; hero={hero_labels!r} "
        f"demo={demo_labels!r}"
    )
