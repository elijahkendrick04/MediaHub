"""Tests for graphic_renderer.metadata_embed — EXIF/IPTC + attribution (roadmap G1.16).

These run on Pillow-synthesised PNG/JPEG fixtures (no Playwright/Chromium needed),
so the whole suite runs everywhere. They assert the three things that make this
feature trustworthy: the metadata round-trips through real readers, the image
pixels are never touched (lossless splice), and the output is deterministic and
injection-safe.
"""

from __future__ import annotations

import xml.dom.minidom as minidom

import pytest

pytest.importorskip("PIL")

from PIL import ExifTags, Image  # noqa: E402

from mediahub.graphic_renderer.metadata_embed import (  # noqa: E402
    ImageMetadata,
    SOFTWARE_NAME,
    UnsupportedImageFormat,
    build_exif,
    build_xmp_packet,
    embed_jpeg,
    embed_metadata,
    embed_png,
    metadata_from_asset,
    metadata_from_brief,
    read_metadata,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _png(path, *, size=(64, 48), colour=(200, 40, 60)):
    Image.new("RGB", size, colour).save(path, format="PNG")
    return path


def _jpeg(path, *, size=(64, 48), colour=(30, 120, 200), quality=92):
    Image.new("RGB", size, colour).save(path, format="JPEG", quality=quality)
    return path


def _pixels(path):
    with Image.open(path) as im:
        return list(im.convert("RGB").get_flattened_data())


def _sample_meta(**overrides) -> ImageMetadata:
    base = dict(
        title="New PB for Eira Hughes",
        description="Eira Hughes smashes the 200m Free club record.",
        creator="Jane Doe",
        copyright="© 2026 Riverside Swim Club",
        credit="Riverside Swim Club",
        source="https://example.org/photo/42",
        headline="200m Free — New Club Record",
        keywords=["Riverside Swim Club", "Eira Hughes", "200m Freestyle", "NEW PB"],
        licence="CC BY 4.0",
        web_statement="https://example.org/photo/42",
        create_date="2026-06-15T19:30:00",
    )
    base.update(overrides)
    return ImageMetadata(**base)


def _xmp_xml(meta: ImageMetadata) -> str:
    """The XMP packet trimmed to the parseable <x:xmpmeta> element."""
    packet = build_xmp_packet(meta)
    start = packet.find("<x:xmpmeta")
    end = packet.rfind("</x:xmpmeta>") + len("</x:xmpmeta>")
    return packet[start:end]


# ---------------------------------------------------------------------------
# ImageMetadata dataclass
# ---------------------------------------------------------------------------


def test_is_empty_true_for_default_and_software_only():
    assert ImageMetadata().is_empty() is True
    assert ImageMetadata(software="Anything").is_empty() is True


def test_is_empty_false_when_any_field_present():
    assert ImageMetadata(creator="x").is_empty() is False
    assert ImageMetadata(keywords=["a"]).is_empty() is False
    assert ImageMetadata(copyright="© c").is_empty() is False


def test_clean_keywords_dedupes_trims_preserves_order():
    m = ImageMetadata(keywords=[" A ", "b", "a", "", "  ", "B", "c"])
    assert m.clean_keywords() == ["A", "b", "c"]


def test_to_dict_from_dict_roundtrip():
    m = _sample_meta()
    assert ImageMetadata.from_dict(m.to_dict()) == m


def test_from_dict_csv_keywords_and_unknown_keys():
    m = ImageMetadata.from_dict({"keywords": "a, b ,c", "bogus": 1, "creator": "X"})
    assert m.keywords == ["a", "b", "c"]
    assert m.creator == "X"


def test_from_dict_non_dict_returns_default():
    assert ImageMetadata.from_dict("nope") == ImageMetadata()


# ---------------------------------------------------------------------------
# XMP packet
# ---------------------------------------------------------------------------


def test_xmp_is_well_formed_xml():
    minidom.parseString(_xmp_xml(_sample_meta()))


def test_xmp_empty_meta_still_well_formed_and_has_creator_tool():
    packet = build_xmp_packet(ImageMetadata())
    minidom.parseString(_xmp_xml(ImageMetadata()))
    assert "xmp:CreatorTool" in packet
    assert SOFTWARE_NAME in packet


def test_xmp_contains_all_populated_iptc_fields():
    packet = build_xmp_packet(_sample_meta())
    for token in (
        "dc:title",
        "dc:description",
        "dc:creator",
        "dc:rights",
        "dc:subject",
        "photoshop:Headline",
        "photoshop:Credit",
        "photoshop:Source",
        "xmpRights:UsageTerms",
        "xmpRights:WebStatement",
        "Jane Doe",
        "CC BY 4.0",
    ):
        assert token in packet, token


def test_xmp_omits_absent_fields():
    packet = build_xmp_packet(ImageMetadata(creator="Solo"))
    assert "dc:creator" in packet
    assert "dc:rights" not in packet
    assert "photoshop:Credit" not in packet


def test_xmp_is_deterministic():
    assert build_xmp_packet(_sample_meta()) == build_xmp_packet(_sample_meta())


def test_xmp_escapes_xml_metacharacters():
    packet = build_xmp_packet(ImageMetadata(creator="A & B", description='<b>"x"</b>'))
    assert "&amp;" in packet
    assert "&lt;b&gt;" in packet
    assert "&quot;" in packet
    minidom.parseString(_xmp_xml(ImageMetadata(creator="A & B", description='<b>"x"</b>')))


def test_xmp_injection_attempt_is_neutralised():
    evil = "</rdf:li></rdf:Seq></dc:creator><inject/>"
    packet = build_xmp_packet(ImageMetadata(creator=evil))
    # The packet must still parse and must NOT contain a live <inject/> element.
    dom = minidom.parseString(_xmp_xml(ImageMetadata(creator=evil)))
    assert dom.getElementsByTagName("inject") == []
    assert "<inject/>" not in packet


def test_rights_marked_emits_boolean():
    assert "xmpRights:Marked>True<" in build_xmp_packet(ImageMetadata(rights_marked=True))
    assert "xmpRights:Marked>False<" in build_xmp_packet(ImageMetadata(rights_marked=False))
    assert "xmpRights:Marked" not in build_xmp_packet(ImageMetadata(rights_marked=None))


# ---------------------------------------------------------------------------
# EXIF assembly
# ---------------------------------------------------------------------------


def test_build_exif_has_standard_tags():
    raw = build_exif(_sample_meta())
    assert raw is not None and raw[:6] == b"Exif\x00\x00"
    exif = Image.Exif()
    exif.load(raw[6:])
    assert exif.get(ExifTags.Base.Artist) == "Jane Doe"
    assert exif.get(ExifTags.Base.Software) == SOFTWARE_NAME
    assert exif.get(ExifTags.Base.DateTime) == "2026:06:15 19:30:00"


def test_build_exif_none_when_truly_empty():
    assert build_exif(ImageMetadata(software="")) is None


def test_build_exif_xp_tags_carry_unicode():
    raw = build_exif(ImageMetadata(creator="José Müller"))
    exif = Image.Exif()
    exif.load(raw[6:])
    xp = exif.get(ExifTags.Base.XPAuthor)
    assert bytes(xp).decode("utf-16-le").rstrip("\x00") == "José Müller"


# ---------------------------------------------------------------------------
# PNG embedding
# ---------------------------------------------------------------------------


def test_png_embed_is_lossless(tmp_path):
    p = _png(tmp_path / "card.png")
    before = _pixels(p)
    embed_metadata(p, _sample_meta())
    assert _pixels(p) == before


def test_png_roundtrip_core_fields(tmp_path):
    p = _png(tmp_path / "card.png")
    embed_metadata(p, _sample_meta())
    got = read_metadata(p)
    assert got.creator == "Jane Doe"
    assert got.copyright == "© 2026 Riverside Swim Club"
    assert got.title == "New PB for Eira Hughes"
    assert got.licence == "CC BY 4.0"
    assert got.source == "https://example.org/photo/42"
    assert "Eira Hughes" in got.keywords


def test_png_exif_readable_by_pillow(tmp_path):
    p = _png(tmp_path / "card.png")
    embed_metadata(p, _sample_meta())
    with Image.open(p) as im:
        assert im.getexif().get(ExifTags.Base.Artist) == "Jane Doe"


def test_png_xmp_chunk_present_and_parses(tmp_path):
    p = _png(tmp_path / "card.png")
    embed_metadata(p, _sample_meta())
    with Image.open(p) as im:
        xmp = im.info.get("XML:com.adobe.xmp")
    assert xmp and "photoshop:Credit" in xmp
    start = xmp.find("<x:xmpmeta")
    minidom.parseString(xmp[start : xmp.rfind("</x:xmpmeta>") + len("</x:xmpmeta>")])


def test_png_output_is_valid_image(tmp_path):
    p = _png(tmp_path / "card.png")
    embed_metadata(p, _sample_meta())
    with Image.open(p) as im:
        im.verify()


def test_png_embed_is_idempotent(tmp_path):
    p = _png(tmp_path / "card.png")
    embed_metadata(p, _sample_meta())
    once = p.read_bytes()
    embed_metadata(p, _sample_meta())
    assert p.read_bytes() == once


def test_png_embed_is_deterministic(tmp_path):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")
    embed_metadata(a, _sample_meta())
    embed_metadata(b, _sample_meta())
    assert a.read_bytes() == b.read_bytes()


def test_png_output_path_leaves_source_untouched(tmp_path):
    src = _png(tmp_path / "src.png")
    src_bytes = src.read_bytes()
    dst = tmp_path / "out" / "dst.png"
    returned = embed_metadata(src, _sample_meta(), output_path=dst)
    assert returned == dst and dst.exists()
    assert src.read_bytes() == src_bytes  # original not modified
    assert read_metadata(dst).creator == "Jane Doe"


def test_png_unicode_preserved(tmp_path):
    p = _png(tmp_path / "u.png")
    embed_metadata(p, ImageMetadata(creator="José Müller", title="200м Вольный стиль"))
    got = read_metadata(p)
    assert got.creator == "José Müller"
    assert got.title == "200м Вольный стиль"


# ---------------------------------------------------------------------------
# JPEG embedding
# ---------------------------------------------------------------------------


def test_jpeg_embed_is_lossless(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")
    before = _pixels(p)
    embed_metadata(p, _sample_meta())
    assert _pixels(p) == before


def test_jpeg_roundtrip_core_fields(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")
    embed_metadata(p, _sample_meta())
    got = read_metadata(p)
    assert got.creator == "Jane Doe"
    assert got.copyright == "© 2026 Riverside Swim Club"
    assert got.title == "New PB for Eira Hughes"
    assert got.licence == "CC BY 4.0"


def test_jpeg_has_exif_and_xmp_app1(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")
    embed_metadata(p, _sample_meta())
    raw = p.read_bytes()
    assert b"Exif\x00\x00" in raw
    assert b"http://ns.adobe.com/xap/1.0/" in raw
    with Image.open(p) as im:
        assert im.getexif().get(ExifTags.Base.Artist) == "Jane Doe"
        assert "photoshop:Credit" in im.info.get("xmp", b"").decode("utf-8", "ignore")


def test_jpeg_output_is_valid_image(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")
    embed_metadata(p, _sample_meta())
    with Image.open(p) as im:
        im.verify()


def test_jpeg_embed_is_idempotent(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")
    embed_metadata(p, _sample_meta())
    once = p.read_bytes()
    embed_metadata(p, _sample_meta())
    assert p.read_bytes() == once


def test_jpeg_preserves_jfif_app0(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")  # Pillow writes a JFIF APP0
    assert b"JFIF\x00" in p.read_bytes()
    embed_metadata(p, _sample_meta())
    assert b"JFIF\x00" in p.read_bytes()


def test_jpeg_unicode_preserved(tmp_path):
    p = _jpeg(tmp_path / "u.jpg")
    embed_metadata(p, ImageMetadata(creator="José Müller"))
    assert read_metadata(p).creator == "José Müller"


# ---------------------------------------------------------------------------
# Format dispatch + errors
# ---------------------------------------------------------------------------


def test_embed_sniffs_by_content_not_extension(tmp_path):
    # A PNG file with a lying .jpg suffix is still treated as PNG.
    p = tmp_path / "actually_png.jpg"
    Image.new("RGB", (8, 8)).save(p, format="PNG")
    embed_metadata(p, _sample_meta())
    with Image.open(p) as im:
        assert im.format == "PNG"
    assert read_metadata(p).creator == "Jane Doe"


def test_embed_png_rejects_jpeg(tmp_path):
    p = _jpeg(tmp_path / "card.jpg")
    with pytest.raises(UnsupportedImageFormat):
        embed_png(p, _sample_meta())


def test_embed_jpeg_rejects_png(tmp_path):
    p = _png(tmp_path / "card.png")
    with pytest.raises(UnsupportedImageFormat):
        embed_jpeg(p, _sample_meta())


def test_unsupported_format_raises(tmp_path):
    p = tmp_path / "note.txt"
    p.write_bytes(b"this is not an image")
    with pytest.raises(UnsupportedImageFormat):
        embed_metadata(p, _sample_meta())


# ---------------------------------------------------------------------------
# read_metadata
# ---------------------------------------------------------------------------


def test_read_metadata_on_bare_image_is_empty(tmp_path):
    p = _png(tmp_path / "bare.png")
    assert read_metadata(p).is_empty()


# ---------------------------------------------------------------------------
# Constructors — metadata_from_asset / metadata_from_brief
# ---------------------------------------------------------------------------


def test_metadata_from_asset_uses_explicit_photographer():
    m = metadata_from_asset({"photographer": "Sam Rivers", "source_licence": "CC BY 4.0"})
    assert m.creator == "Sam Rivers"
    assert m.licence == "CC BY 4.0"
    assert m.rights_marked is True


def test_metadata_from_asset_parses_attribution_string():
    m = metadata_from_asset(
        {
            "source_attribution": "Photo by Sam Rivers / CC BY-SA 4.0",
            "source_url": "https://commons.example/x",
        }
    )
    assert m.creator == "Sam Rivers"
    assert m.web_statement == "https://commons.example/x"
    assert m.source == "Photo by Sam Rivers / CC BY-SA 4.0"


def test_metadata_from_asset_empty_when_no_provenance():
    m = metadata_from_asset({})
    assert m.creator == "" and m.licence == "" and m.rights_marked is None


def test_metadata_from_brief_full():
    brief = {
        "primary_hook": "NEW PB: 2:08.41",
        "achievement_summary": "Eira Hughes goes 2:08.41 — a new personal best",
        "confidence_label": "NEW PB",
        "text_layers": {"athlete_name": "Eira Hughes", "event_name": "200m Freestyle"},
    }
    asset = {"photographer": "Sam Rivers", "source_licence": "CC BY 4.0"}
    m = metadata_from_brief(
        brief, club_name="Riverside Swim Club", photo_asset=asset, create_date="2026-06-15T19:30:00"
    )
    assert m.title == "NEW PB: 2:08.41"
    assert m.description == "Eira Hughes goes 2:08.41 — a new personal best"
    assert m.copyright == "© 2026 Riverside Swim Club"
    assert m.credit == "Riverside Swim Club"
    assert m.creator == "Sam Rivers"
    assert m.licence == "CC BY 4.0"
    assert "Eira Hughes" in m.keywords and "200m Freestyle" in m.keywords
    assert "NEW PB" in m.keywords
    # athlete only listed once even though it appears in two source fields
    assert m.keywords.count("Eira Hughes") == 1


def test_metadata_from_brief_no_club_no_copyright():
    m = metadata_from_brief({"primary_hook": "Hi"}, club_name="")
    assert m.copyright == ""
    assert m.credit == ""


def test_metadata_from_brief_copyright_without_year_when_no_date():
    m = metadata_from_brief({"primary_hook": "Hi"}, club_name="Riverside SC")
    assert m.copyright == "© Riverside SC"


def test_metadata_from_brief_caption_override():
    m = metadata_from_brief(
        {"primary_hook": "Hook", "achievement_summary": "Summary"},
        club_name="C",
        caption="The approved caption.",
    )
    assert m.description == "The approved caption."


def test_metadata_from_brief_is_deterministic():
    brief = {"primary_hook": "X", "text_layers": {"athlete_name": "A"}}
    a = metadata_from_brief(brief, club_name="C", create_date="2026-01-01")
    b = metadata_from_brief(brief, club_name="C", create_date="2026-01-01")
    assert a == b


def test_metadata_from_brief_honest_when_empty():
    m = metadata_from_brief({}, club_name="")
    assert m.is_empty()


# ---------------------------------------------------------------------------
# Integration with the real CreativeBrief + MediaAsset dataclasses
# ---------------------------------------------------------------------------


def test_integration_real_dataclasses(tmp_path):
    from mediahub.creative_brief.generator import CreativeBrief
    from mediahub.media_library.models import MediaAsset

    asset = MediaAsset(
        id="a1",
        filename="dive.jpg",
        path="/x/dive.jpg",
        type="athlete_action",
        source_attribution="Photo by Sam Rivers / CC BY-SA 4.0",
        source_licence="CC BY-SA 4.0",
        source_url="https://commons.example/dive",
        linked_athlete_names=["Eira Hughes"],
    )
    brief = CreativeBrief(
        id="b1",
        content_item_id="c1",
        profile_id="club1",
        achievement_summary="Eira Hughes goes 2:08.41 — a new personal best",
        objective="celebrate",
        primary_hook="NEW PB: 2:08.41",
        confidence_label="NEW PB",
        tone="hype",
        layout_template="individual_hero",
        inspiration_pattern_id="p1",
        image_treatment="cutout",
        text_hierarchy=["hook"],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=["a1"],
        safety_notes=[],
        why_this_design="leads with the PB delta",
        text_layers={"athlete_name": "Eira Hughes", "event_name": "200m Freestyle"},
        palette={"primary": "#0A2540"},
        format_priority=["feed_portrait"],
    )
    meta = metadata_from_brief(
        brief,
        club_name="Riverside Swim Club",
        photo_asset=asset,
        create_date="2026-06-15T19:30:00",
    )
    p = _png(tmp_path / "real.png")
    embed_metadata(p, meta)
    got = read_metadata(p)
    assert got.creator == "Sam Rivers"
    assert got.copyright == "© 2026 Riverside Swim Club"
    assert got.credit == "Riverside Swim Club"
    assert got.licence == "CC BY-SA 4.0"
    assert "Eira Hughes" in got.keywords


def test_integration_malicious_caption_is_safe(tmp_path):
    """A caption full of XML/markup round-trips as literal text, breaks nothing."""
    evil = 'Bad </dc:description><x>" & <stuff>'
    p = _png(tmp_path / "evil.png")
    embed_metadata(p, ImageMetadata(description=evil, creator="C"))
    with Image.open(p) as im:
        xmp = im.info.get("XML:com.adobe.xmp")
    start = xmp.find("<x:xmpmeta")
    minidom.parseString(xmp[start : xmp.rfind("</x:xmpmeta>") + len("</x:xmpmeta>")])
    assert read_metadata(p).description == evil


# ---------------------------------------------------------------------------
# G1.16 wiring — render_brief stamps every exported card (product reachability)
# ---------------------------------------------------------------------------


def _render_card(monkeypatch, tmp_path, *, asset=None):
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import CreativeBrief
    import mediahub.graphic_renderer.render as R

    def _fake_png(html, output_path, size):  # noqa: ARG001 - signature match
        Image.new("RGB", (64, 80), (10, 37, 64)).save(output_path, "PNG")
        return 1

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    if asset is not None:
        import mediahub.media_library.store as _mls

        class _StubStore:
            def get(self, asset_id):
                return asset if asset_id == "ma_1" else None

        monkeypatch.setattr(_mls, "get_store", lambda: _StubStore())

    brief = CreativeBrief(
        id="cb_g116",
        content_item_id="ci-g116",
        profile_id="g116-club",
        achievement_summary="Eira Hughes — 200m Freestyle — 2:08.41",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template="individual_hero",
        inspiration_pattern_id="p1",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=(["ma_1"] if asset is not None else []),
        safety_notes=[],
        why_this_design="",
        text_layers={"athlete_name": "Eira Hughes", "event_name": "200m Freestyle"},
        palette={"primary": "#0A2540"},
        format_priority=["feed_portrait"],
    )
    brand = BrandKit(
        profile_id="g116-club",
        display_name="Riverside Swim Club",
        primary_colour="#0A2540",
        secondary_colour="#C9A227",
        short_name="RSC",
    )
    res = R.render_brief(brief, output_dir=tmp_path, brand_kit=brand)
    return tmp_path / "feed_portrait.png", res


def test_rendered_card_carries_credit_fields(monkeypatch, tmp_path):
    out, _res = _render_card(monkeypatch, tmp_path)
    got = read_metadata(out)
    assert got.credit == "Riverside Swim Club"
    assert got.copyright == "© Riverside Swim Club"
    assert got.title == "NEW PB"
    assert "Eira Hughes" in got.keywords
    # Still a valid PNG after the splice.
    with Image.open(out) as im:
        im.verify()


def test_rendered_card_carries_photographer_from_sourced_asset(monkeypatch, tmp_path):
    class _Asset:
        photographer = "Sam Rivers"
        source_attribution = "Riverside Gala Media"
        source_licence = "CC BY-SA 4.0"
        source_url = ""
        linked_athlete_names = ["Eira Hughes"]

    out, _res = _render_card(monkeypatch, tmp_path, asset=_Asset())
    got = read_metadata(out)
    assert got.creator == "Sam Rivers"
    assert got.licence == "CC BY-SA 4.0"
    assert got.source == "Riverside Gala Media"


def test_malformed_png_without_ihdr_is_refused(tmp_path):
    """Signature-only / chunk-less bytes must be refused, never 'repaired'."""
    p = tmp_path / "stub.png"
    original = b"\x89PNG\r\n\x1a\n" + b"studio-stub"
    p.write_bytes(original)
    with pytest.raises(UnsupportedImageFormat):
        embed_metadata(p, ImageMetadata(creator="C"))
    assert p.read_bytes() == original  # untouched on refusal
