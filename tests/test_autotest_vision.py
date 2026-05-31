"""Vision judge — the screenshot-grounded QA judge (the UI-TARS-inspired surface,
verdict: autotest/reports/council/ui-tars-desktop-*).

It looks at rendered screenshots via the existing media_ai.llm vision capability
(Gemini/Anthropic) to catch VISUAL defects the deterministic finder and the
text-only semantic judges can't see. These tests prove:

  * honest-skip with no provider key (one info finding, never a fake bug)
  * a clean skip when there are no screenshots to look at
  * a real vision verdict is parsed into bug Findings, low-confidence dropped
  * it never raises, even when the provider errors
"""
from __future__ import annotations

import json

import pytest

from autotest import vision


def test_skips_cleanly_with_no_provider(monkeypatch):
    from mediahub.media_ai import llm
    monkeypatch.setattr(llm, "is_available", lambda: False)

    out = vision.evaluate({"flow_result": "passed", "review_screenshot": "x.png"})
    assert len(out) == 1
    f = out[0]
    assert f.is_bug is False
    assert f.category == "vision_skipped"
    assert "no AI provider" in f.title.lower() or "skip" in f.title.lower()


def test_skips_cleanly_with_no_screenshots(monkeypatch):
    from mediahub.media_ai import llm
    monkeypatch.setattr(llm, "is_available", lambda: True)

    out = vision.evaluate({"flow_result": "passed"})  # no *_screenshot keys
    assert len(out) == 1
    assert out[0].is_bug is False
    assert out[0].category == "vision_skipped"


def test_parses_visual_defects_into_findings(monkeypatch, tmp_path):
    from mediahub.media_ai import llm
    monkeypatch.setattr(llm, "is_available", lambda: True)

    shot = tmp_path / "surface-review.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n fake")  # file just needs to exist

    captured = {}

    def fake_vision(image_paths, prompt, *, system=None, max_tokens=1024):
        captured["paths"] = image_paths
        return json.dumps({"issues": [
            {"title": "Club logo failed to render", "severity": "high",
             "confidence": "high", "expected": "logo visible",
             "actual": "broken-image box top-left", "evidence": "grey box with torn-image icon"},
            {"title": "maybe slightly tight padding", "severity": "low",
             "confidence": "low", "expected": "x", "actual": "y", "evidence": "z"},
        ]})

    monkeypatch.setattr(llm, "generate_vision", fake_vision)

    out = vision.evaluate({"flow_result": "passed", "review_screenshot": str(shot)})
    bugs = [f for f in out if f.is_bug]
    # the high-confidence visual defect is kept; the low-confidence one is dropped
    assert len(bugs) == 1
    f = bugs[0]
    assert f.category == "vision:review"
    assert "logo" in f.title.lower()
    assert f.severity == "high"
    assert f.screenshot  # carries the screenshot path for the report
    # the model was actually handed an absolute path to the screenshot
    assert captured["paths"] == [str(shot)]


def test_never_raises_when_provider_errors(monkeypatch, tmp_path):
    from mediahub.media_ai import llm
    monkeypatch.setattr(llm, "is_available", lambda: True)
    shot = tmp_path / "surface-review.png"
    shot.write_bytes(b"\x89PNG fake")

    def boom(*a, **k):
        raise RuntimeError("vision provider exploded")

    monkeypatch.setattr(llm, "generate_vision", boom)

    out = vision.evaluate({"flow_result": "passed", "review_screenshot": str(shot)})
    # surfaced as a non-bug info finding, never an exception
    assert all(not f.is_bug for f in out)
    assert any(f.category == "vision:review" for f in out)
