"""C4 regression: uploaded logos are analysed for colour via generate_vision.

The old code looked for a non-existent ``describe_image`` helper on the llm
module and always returned ``{}`` — so logos never produced
``ai_dominant_colours`` and the brand never built from the club's image.
These tests pin the real wiring: bytes -> temp file path -> generate_vision
-> JSON -> normalised colours, with no leaked temp file and no raising.
"""
from __future__ import annotations

import os

import mediahub.media_ai.llm as llm
from mediahub.brand.logos import describe_logo_with_ai


def test_describe_logo_parses_colours_and_cleans_temp(monkeypatch):
    calls: dict = {}

    def fake_vision(image_paths, prompt, *, system=None, max_tokens=1024):
        calls["image_paths"] = image_paths
        calls["existed"] = all(os.path.exists(p) for p in image_paths)
        return (
            '{"description":"Blue and gold crest wordmark",'
            '"dominant_colours":["#439dd1","#1b3a5b","#E8B04B"]}'
        )

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "generate_vision", fake_vision)

    out = describe_logo_with_ai(b"fakebytes", "image/png")

    assert out.get("description") == "Blue and gold crest wordmark"
    assert out.get("dominant_colours") == ["#439dd1", "#1b3a5b", "#e8b04b"]

    # bytes were staged to a real temp file with a .png suffix
    paths = calls["image_paths"]
    assert isinstance(paths, list) and len(paths) == 1
    assert paths[0].endswith(".png")
    assert calls["existed"] is True
    # ...and the temp file is cleaned up afterwards
    assert not os.path.exists(paths[0])


def test_describe_logo_vision_raises_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vision exploded")

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "generate_vision", boom)

    assert describe_logo_with_ai(b"fakebytes", "image/png") == {}


def test_describe_logo_unavailable_skips_vision(monkeypatch):
    called = {"n": 0}

    def should_not_run(*a, **k):
        called["n"] += 1
        return "{}"

    monkeypatch.setattr(llm, "is_available", lambda: False)
    monkeypatch.setattr(llm, "generate_vision", should_not_run)

    assert describe_logo_with_ai(b"fakebytes", "image/png") == {}
    assert called["n"] == 0


def test_describe_logo_parses_fenced_json(monkeypatch):
    def fenced(image_paths, prompt, *, system=None, max_tokens=1024):
        return (
            "```json\n"
            '{"description":"Mono icon","dominant_colours":["#000000"]}\n'
            "```"
        )

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "generate_vision", fenced)

    out = describe_logo_with_ai(b"fakebytes", "image/jpeg")
    assert out.get("description") == "Mono icon"
    assert out.get("dominant_colours") == ["#000000"]
