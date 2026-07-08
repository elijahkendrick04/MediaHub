"""D-25 — prompt-led draft cards must not show a fabricated "Model confidence"
badge.

Free-text / chat / spotlight packs used to hardcode confidence (0.9, 0.85, 0.9,
0.5) — no model computed it — and render it as "90% conf" titled "Model
confidence", devaluing the real confidence scores volunteers are trained to
trust in the review flow. The badge is conditional on a real value; the fix
leaves prompt-led confidence unset (None).
"""

from __future__ import annotations

from mediahub.club_platform.stubs import render_cards_html


def test_none_confidence_renders_no_badge():
    html = render_cards_html(
        {"cards": [{"platform": "Instagram", "caption": "Great swim!", "confidence": None}]},
        back_url="/x",
        title="Draft",
    )
    assert "Model confidence" not in html
    assert "% conf" not in html


def test_real_confidence_still_renders_badge():
    # The conditional still shows a badge when a genuine value exists (review flow).
    html = render_cards_html(
        {"cards": [{"platform": "Instagram", "caption": "PB!", "confidence": 0.72}]},
        back_url="/x",
        title="Draft",
    )
    assert "Model confidence" in html
    assert "72% conf" in html


def test_prompt_led_builders_leave_confidence_unset():
    # The prompt-led card builders (spotlight / free-text / chat / turn-into)
    # now leave confidence unset (None) rather than fabricating a constant.
    import pathlib

    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert src.count('"confidence": None') >= 4
