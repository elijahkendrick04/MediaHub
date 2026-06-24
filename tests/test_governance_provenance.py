"""Tests for governance provenance manifests (1.23)."""

from __future__ import annotations

import json

from mediahub.governance import provenance as prov


# ---- card manifest --------------------------------------------------------

_VISUAL = {
    "id": "v1",
    "layout_template": "spotlight",
    "format_name": "feed_portrait",
    "width": 1080,
    "height": 1350,
    "file_path": "/runs/x/v1.png",
    "text_layers": {"caption": "Emma PB!", "event": "200 Back"},
    "palette": {"accent": "#ff0000"},
    "sourced_asset_ids": ["asset-1", "asset-2"],
    "safety_notes": [],
    "why_this_design": "Bold spotlight for a standout PB.",
    "rendered_at": "2026-06-24T10:00:00+00:00",
}


def test_card_manifest_is_honest_deterministic():
    m = prov.build_card_manifest(_VISUAL)
    assert m["kind"] == prov.KIND_CARD
    assert m["render"]["method"] == prov.RENDER_DETERMINISTIC
    assert m["render"]["layout"] == "spotlight"
    assert m["render"]["width"] == 1080
    assert "layout" in m["deterministic_components"]
    assert m["sources"]["photos"] == ["asset-1", "asset-2"]
    assert m["sources"]["photography"] == "real"
    assert m["produced_at"] == "2026-06-24T10:00:00+00:00"
    assert m["text_layers"] == ["caption", "event"]
    assert m["design_rationale"].startswith("Bold")
    # design direction is recorded as AI-assisted; the summary asserts real photos
    assert any(c["component"] == "design_direction" for c in m["ai_components"])
    assert "not ai-generated" in m["summary"].lower() or "not AI-generated" in m["summary"]


def test_card_manifest_accepts_extra_ai_components():
    extra = [{"component": "caption", "provider": "gemini", "model": "g-2.5"}]
    m = prov.build_card_manifest(_VISUAL, ai_components=extra)
    comps = {c["component"] for c in m["ai_components"]}
    assert "caption" in comps and "design_direction" in comps


def test_card_manifest_no_photos_marks_none():
    v = dict(_VISUAL, sourced_asset_ids=[])
    m = prov.build_card_manifest(v)
    assert m["sources"]["photography"] == "none"


# ---- generated-image manifest ---------------------------------------------


def test_generated_image_wholesale_is_ai_generated():
    m = prov.build_generated_image_manifest(
        operation="generate", provider="gemini", model="imagen-4"
    )
    assert m["kind"] == prov.KIND_GENERATED_IMAGE
    assert m["render"]["method"] == prov.RENDER_AI_GENERATED
    assert m["ai_components"][0]["component"] == "image"
    assert prov.normalise(m)["ai"] is True


def test_generated_image_edit_is_composite():
    m = prov.build_generated_image_manifest(operation="expand", source_asset_id="a1")
    assert m["render"]["method"] == prov.RENDER_AI_COMPOSITE
    assert m["sources"]["source_asset_id"] == "a1"


def test_caption_manifest():
    m = prov.build_caption_manifest(provider="gemini", model="g", tone="warm")
    assert m["kind"] == prov.KIND_CAPTION
    assert prov.normalise(m)["ai"] is True


# ---- sidecar I/O ----------------------------------------------------------


def test_sidecar_roundtrip(tmp_path):
    img = tmp_path / "card.png"
    img.write_bytes(b"\x89PNG fake")
    m = prov.build_card_manifest(_VISUAL)
    p = prov.write_sidecar(img, m)
    assert p == tmp_path / "card.png.provenance.json"
    assert p.exists()
    back = prov.read_sidecar(img)
    assert back["kind"] == prov.KIND_CARD
    # valid JSON, stable keys
    assert json.loads(p.read_text())["produced_by"] == "MediaHub"


def test_read_sidecar_missing_is_none(tmp_path):
    assert prov.read_sidecar(tmp_path / "nope.png") is None


def test_write_sidecar_bad_path_returns_none():
    # A path under a file (not a dir) can't be created → best-effort None.
    assert prov.write_sidecar("/dev/null/inside/card.png", {"k": "v"}) is None


# ---- normalise (reads our + imagine + motion manifests) -------------------


def test_normalise_imagine_style():
    imagine = {
        "operation": "generate",
        "provider": "gemini",
        "digital_source_type": "ai_generated",
        "generated_by": "media_ai.imagine",
        "created_at": "2026-06-24T00:00:00Z",
    }
    n = prov.normalise(imagine)
    assert n["ai"] is True
    assert n["kind"] == prov.KIND_GENERATED_IMAGE
    assert n["produced_at"] == "2026-06-24T00:00:00Z"


def test_normalise_motion_reel_style():
    reel = {"kind": "reel", "engine": "remotion", "cards": [{}], "rhythm": "default"}
    n = prov.normalise(reel)
    assert n["kind"] == "reel"
    assert n["ai"] is False  # a reel is a deterministic render


def test_normalise_card_not_ai_when_no_components():
    v = dict(_VISUAL, why_this_design="")
    m = prov.build_card_manifest(v)
    # No design rationale and no extra components → not flagged AI.
    assert prov.normalise(m)["ai"] is False


def test_summarise_fallbacks():
    assert "image" in prov.summarise({"kind": prov.KIND_GENERATED_IMAGE}).lower()
    assert "caption" in prov.summarise({"kind": prov.KIND_CAPTION}).lower()
    assert prov.summarise({}) == "MediaHub output"


# ---- persist_visual wiring ------------------------------------------------


def test_persist_visual_writes_provenance_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    from mediahub.content_pack_visual import integration
    from mediahub.graphic_renderer.render import GeneratedVisual

    vdir = integration.visuals_dir_for_run("run-1") / "brief-1"
    vdir.mkdir(parents=True, exist_ok=True)
    png = vdir / "v1.png"
    png.write_bytes(b"\x89PNG fake")

    visual = GeneratedVisual(
        id="v1",
        brief_id="brief-1",
        content_item_id="item-1",
        profile_id="club-x",
        layout_template="spotlight",
        format_name="feed_portrait",
        width=1080,
        height=1350,
        file_path=str(png),
        text_layers={"caption": "Emma PB!"},
        palette={"accent": "#ff0000"},
        sourced_asset_ids=["asset-1"],
        safety_notes=[],
        why_this_design="Bold spotlight.",
        confidence_label="high",
    )
    integration.persist_visual(visual, run_id="run-1", brief=None)

    sidecar = prov.sidecar_path(png)
    assert sidecar.exists()
    m = json.loads(sidecar.read_text())
    assert m["kind"] == prov.KIND_CARD
    assert m["render"]["method"] == prov.RENDER_DETERMINISTIC
    assert m["sources"]["photos"] == ["asset-1"]
