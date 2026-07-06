"""Writer-surface behaviour of ``content_engine.generate_content``.

Pins two audit fixes on the brief-led card path:

  * cards carry **no** ``confidence`` key — the writer produces no calibrated
    score, and the old constant (0.8) was a fake signal on a review surface
    built around honest confidence displays. Absent means "unscored"; only
    ranker-scored cards carry a real value.
  * the deterministic §8C caption-repetition metric is recorded alongside the
    generated set (``metrics``), with the worst pair surfaced once it clears
    the flag threshold — metric-only, never a silent gate.

The provider is faked (no network, no key): the fake ``ask_with_tools``
drives ``submit_card`` exactly as a real writer round would.
"""

from __future__ import annotations

import mediahub.ai_core as ai_core
import mediahub.content_engine.engine as engine_mod
from mediahub.content_engine import generate_content


def _run_engine(monkeypatch, captions):
    """Run generate_content with a faked director + writer emitting ``captions``."""
    monkeypatch.setattr(engine_mod, "plan_content_directions", lambda **kw: [])

    def _fake_ask(system, user, *, tools, on_tool_call, **kw):
        for cap in captions:
            on_tool_call(
                "submit_card",
                {"platform": "Instagram", "caption": cap, "hashtags": ["swim"], "notes": ""},
            )
        return None

    # generate_content does `from mediahub.ai_core import ask_with_tools` at
    # call time, so patching the package attribute is what it resolves.
    monkeypatch.setattr(ai_core, "ask_with_tools", _fake_ask)
    return generate_content(
        content_type="free_text",
        brief="test brief",
        brand_context={},
        n_cards=max(1, len(captions)),
    )


def test_engine_cards_carry_no_fake_confidence(monkeypatch):
    res = _run_engine(
        monkeypatch,
        ["Big win for the squad tonight", "A completely different angle on training"],
    )
    assert res["cards"] and len(res["cards"]) == 2
    for card in res["cards"]:
        assert "confidence" not in card
        assert card["caption"]


def test_caption_repetition_metric_recorded(monkeypatch):
    res = _run_engine(
        monkeypatch,
        ["Big win for the squad tonight", "Totally different words about training camp"],
    )
    metrics = res["metrics"]
    assert metrics["caption_repetition"] == 0.0
    # Below the flag threshold there is no repeated pair to surface.
    assert "repeated_pair" not in metrics


def test_caption_repetition_flags_worst_pair(monkeypatch):
    same = "Big win for the squad tonight at the county gala"
    res = _run_engine(
        monkeypatch,
        [same, "Fresh angle on the winter training block", same],
    )
    metrics = res["metrics"]
    assert metrics["caption_repetition"] == 1.0
    assert metrics["repeated_pair"] == [0, 2]
