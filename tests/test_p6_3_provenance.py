"""P6.3 — provenance: IPTC DigitalSourceType embed/round-trip + sidecar manifest.

Covers the metadata_embed extension (the lossless AI stamp) and the facade's
``stamp_file`` (embed + ``<file>.imagine.json`` sidecar, with key redaction).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


def _png(path, color=(10, 20, 30)):
    from PIL import Image

    Image.new("RGB", (32, 32), color).save(path)
    return Path(path)


def _png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def test_digital_source_uri_resolution():
    from mediahub.graphic_renderer import metadata_embed as me

    m = me.ImageMetadata(digital_source_type="ai_generated")
    assert m.digital_source_uri() == me.DIGITAL_SOURCE_TYPES["ai_generated"]
    # A pre-resolved URI passes through unchanged.
    full = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
    assert me.ImageMetadata(digital_source_type=full).digital_source_uri() == full
    assert me.ImageMetadata().digital_source_uri() == ""


def test_xmp_packet_carries_digitalsourcetype():
    from mediahub.graphic_renderer import metadata_embed as me

    xmp = me.build_xmp_packet(me.ImageMetadata(digital_source_type="ai_generated"))
    assert "Iptc4xmpExt:DigitalSourceType" in xmp
    assert "trainedAlgorithmicMedia" in xmp
    assert 'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"' in xmp


def test_embed_and_read_back_png(tmp_path):
    from mediahub.graphic_renderer import metadata_embed as me

    p = _png(tmp_path / "g.png")
    me.embed_metadata(p, me.ImageMetadata(digital_source_type="ai_generated"))
    back = me.read_metadata(p)
    assert "trainedAlgorithmicMedia" in back.digital_source_type


def test_embed_and_read_back_jpeg(tmp_path):
    from mediahub.graphic_renderer import metadata_embed as me
    from PIL import Image

    p = tmp_path / "g.jpg"
    Image.new("RGB", (32, 32), (5, 5, 5)).save(p, format="JPEG")
    me.embed_metadata(p, me.ImageMetadata(digital_source_type="ai_composite"))
    back = me.read_metadata(p)
    assert "compositeWithTrainedAlgorithmicMedia" in back.digital_source_type


def test_metadata_for_generated_wholesale_vs_composite():
    from mediahub.graphic_renderer import metadata_embed as me

    gen = me.metadata_for_generated("generate", model="imagen-x", description="hi")
    assert gen.digital_source_type == "ai_generated"
    assert gen.software == "MediaHub (imagen-x)"
    assert gen.description == "hi"

    base = me.ImageMetadata(creator="Jane Doe", copyright="© Club")
    edited = me.metadata_for_generated("edit", model="m", base=base)
    assert edited.digital_source_type == "ai_composite"
    # The source photo's credit chain is carried forward on an edit.
    assert edited.creator == "Jane Doe"
    assert edited.copyright == "© Club"


def test_stamp_file_embeds_and_writes_sidecar(tmp_path):
    import mediahub.media_ai.imagine as im
    from mediahub.graphic_renderer import metadata_embed as me

    p = _png(tmp_path / "out.png")
    result = im.ImagineResult(
        data=p.read_bytes(),
        mime="image/png",
        operation="generate",
        provider="gemini",
        model="imagen-4.0",
        manifest={"operation": "generate", "prompt": "a backdrop", "provider": "gemini"},
    )
    manifest = im.stamp_file(p, result)
    # Embedded IPTC term.
    assert "trainedAlgorithmicMedia" in me.read_metadata(p).digital_source_type
    # Sidecar manifest beside the file.
    sidecar = p.with_suffix(p.suffix + ".imagine.json")
    assert sidecar.exists()
    on_disk = json.loads(sidecar.read_text())
    assert on_disk["operation"] == "generate"
    assert manifest["operation"] == "generate"


def test_manifest_redacts_api_key(monkeypatch):
    import mediahub.media_ai.imagine as im

    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    m = im._manifest(
        operation="generate",
        provider="gemini",
        model="imagen",
        data=_png_bytes(),
        prompt="please use super-secret-key in the scene",
    )
    assert "super-secret-key" not in m["prompt"]
    assert "***" in m["prompt"]
