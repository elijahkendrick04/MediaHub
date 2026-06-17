"""Tests for the club custom-font upload pipeline (roadmap G1.10).

Two layers:

* **Security sandbox** (no third-party dependency) — magic sniffing, structural
  rejection of malformed / oversized / decompression-bomb / restricted fonts,
  embedding classification, family/slug sanitisation, CSS-injection safety. These
  run everywhere, proving an unsafe upload is refused even with ``fontTools`` absent.
* **Subset → WOFF2 → store** (needs ``fontTools`` + ``brotli``) — glyph
  reduction, deterministic output, storage round-trips, CSS emission. These skip
  cleanly where the toolchain isn't installed; CI installs it via requirements.txt.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from mediahub.typography import font_intake as fi


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a throwaway dir so storage tests never touch the repo."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


try:
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    _HAVE_FONTBUILDER = True
except Exception:  # pragma: no cover - depends on the environment
    _HAVE_FONTBUILDER = False

needs_fontbuilder = pytest.mark.skipif(
    not _HAVE_FONTBUILDER, reason="fontTools.fontBuilder not installed"
)
needs_woff2 = pytest.mark.skipif(
    not fi.is_font_tooling_available(), reason="fontTools + brotli (woff2) not installed"
)


def build_ttf(
    family: str = "Brand Sans",
    *,
    fs_type: int = 0,
    weight: int = 700,
    italic: bool = False,
    glyphs: str = "ABCDEFGHIJabcdefghij 0123456789.:-/",
    variable: bool = False,
) -> bytes:
    """Synthesize a minimal but valid TTF in memory (needs fontTools)."""
    chars = sorted(set(glyphs))
    order = [".notdef"]
    cmap: dict[int, str] = {}
    pens: dict[str, object] = {}

    nd = TTGlyphPen(None)
    nd.moveTo((0, 0)); nd.lineTo((0, 700)); nd.lineTo((500, 700)); nd.lineTo((500, 0)); nd.closePath()
    pens[".notdef"] = nd.glyph()
    for i, ch in enumerate(chars):
        g = f"g{i}"
        order.append(g)
        cmap[ord(ch)] = g
        p = TTGlyphPen(None)
        p.moveTo((0, 0)); p.lineTo((0, 600)); p.lineTo((400, 600)); p.lineTo((400, 0)); p.closePath()
        pens[g] = p.glyph()

    fb = FontBuilder(unitsPerEm=1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(pens)
    fb.setupHorizontalMetrics({g: (500, 0) for g in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    style_name = "Italic" if italic else "Regular"
    fb.setupNameTable({"familyName": family, "styleName": style_name})
    fs_selection = 0x01 if italic else 0x40  # italic vs regular
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        fsType=fs_type,
        usWeightClass=weight,
        fsSelection=fs_selection,
    )
    fb.setupPost()
    if variable:
        fb.setupFvar(axes=[("wght", 400, weight, 900, "Weight")], instances=[])
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def make_sfnt(tables: dict[str, bytes], sfnt_version: bytes = b"\x00\x01\x00\x00") -> bytes:
    """Assemble a structurally-valid sfnt from raw table bodies (no fontTools)."""
    n = len(tables)
    header = sfnt_version + n.to_bytes(2, "big") + b"\x00" * 6  # searchRange etc unused
    body_off = 12 + n * 16
    entries = b""
    bodies = b""
    off = body_off
    for tag, body in tables.items():
        tg = tag.encode("latin-1")
        assert len(tg) == 4
        entries += tg + (0).to_bytes(4, "big") + off.to_bytes(4, "big") + len(body).to_bytes(4, "big")
        bodies += body
        pad = (-len(body)) % 4
        bodies += b"\x00" * pad
        off += len(body) + pad
    return header + entries + bodies


def name_table(family: str) -> bytes:
    """A minimal 'name' table (one Windows/English family record)."""
    s = family.encode("utf-16-be")
    header = (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (18).to_bytes(2, "big")
    rec = (
        (3).to_bytes(2, "big")      # platformID Windows
        + (1).to_bytes(2, "big")    # encodingID Unicode BMP
        + (0x409).to_bytes(2, "big")  # languageID en-US
        + (1).to_bytes(2, "big")    # nameID family
        + len(s).to_bytes(2, "big")  # length
        + (0).to_bytes(2, "big")    # offset into string storage
    )
    return header + rec + s


def os2_table(*, fs_type: int = 0, weight: int = 400) -> bytes:
    """A 10-byte OS/2 stub carrying usWeightClass + fsType."""
    return (
        (4).to_bytes(2, "big")        # version
        + (0).to_bytes(2, "big")      # xAvgCharWidth
        + weight.to_bytes(2, "big")   # usWeightClass
        + (5).to_bytes(2, "big")      # usWidthClass
        + fs_type.to_bytes(2, "big")  # fsType
    )


# --------------------------------------------------------------------------- #
# Container sniffing
# --------------------------------------------------------------------------- #
class TestSniff:
    def test_sfnt_truetype(self):
        assert fi.sniff_container(b"\x00\x01\x00\x00rest") == "sfnt"

    def test_sfnt_opentype(self):
        assert fi.sniff_container(b"OTTOrest") == "sfnt"

    def test_woff(self):
        assert fi.sniff_container(b"wOFFrest") == "woff"

    def test_woff2(self):
        assert fi.sniff_container(b"wOF2rest") == "woff2"

    def test_collection_is_unsupported(self):
        assert fi.sniff_container(b"ttcfrest") is None

    def test_junk(self):
        assert fi.sniff_container(b"%PDF-1.7") is None

    def test_too_short(self):
        assert fi.sniff_container(b"ab") is None


# --------------------------------------------------------------------------- #
# Structural sandbox — rejections (no fontTools needed)
# --------------------------------------------------------------------------- #
class TestStructuralRejections:
    def test_empty(self):
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(b"")

    def test_oversize(self):
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(b"\x00\x01\x00\x00" + b"\x00" * 16, max_bytes=8)

    def test_collection_rejected(self):
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(b"ttcf" + b"\x00" * 20)

    def test_unknown_format(self):
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(b"this is plainly not a font file at all")

    def test_truncated_directory(self):
        # numTables says 5 but there's no directory.
        data = b"\x00\x01\x00\x00" + (5).to_bytes(2, "big")
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(data)

    def test_zero_tables(self):
        data = b"\x00\x01\x00\x00" + (0).to_bytes(2, "big") + b"\x00" * 6
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(data)

    def test_implausible_table_count(self):
        data = b"\x00\x01\x00\x00" + (65535).to_bytes(2, "big") + b"\x00" * 6
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(data)

    def test_table_out_of_bounds(self):
        header = b"\x00\x01\x00\x00" + (1).to_bytes(2, "big") + b"\x00" * 6
        entry = b"glyf" + (0).to_bytes(4, "big") + (1000).to_bytes(4, "big") + (1000).to_bytes(4, "big")
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(header + entry)

    def test_non_printable_tag(self):
        header = b"\x00\x01\x00\x00" + (1).to_bytes(2, "big") + b"\x00" * 6
        entry = b"\x00\x01\x02\x03" + (0).to_bytes(4, "big") + (28).to_bytes(4, "big") + (0).to_bytes(4, "big")
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(header + entry)

    def test_woff_length_mismatch(self):
        # length field (offset 8) lies about the file size.
        data = b"wOFF" + b"\x00\x01\x00\x00" + (9999).to_bytes(4, "big") + b"\x00" * 32
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(data)

    def test_woff_decompression_bomb(self):
        # A 64-byte WOFF that claims to inflate to ~2 GB.
        body = bytearray(64)
        body[0:4] = b"wOFF"
        body[4:8] = b"\x00\x01\x00\x00"          # flavor
        body[8:12] = (64).to_bytes(4, "big")     # length == len(data)
        body[12:14] = (1).to_bytes(2, "big")     # numTables
        body[16:20] = (2_000_000_000).to_bytes(4, "big")  # totalSfntSize → bomb
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(bytes(body))

    def test_woff2_decompression_bomb(self):
        body = bytearray(48)
        body[0:4] = b"wOF2"
        body[4:8] = b"\x00\x01\x00\x00"          # flavor
        body[8:12] = (48).to_bytes(4, "big")     # length == len(data)
        body[12:14] = (1).to_bytes(2, "big")     # numTables
        body[16:20] = (2_000_000_000).to_bytes(4, "big")  # totalSfntSize → bomb
        with pytest.raises(fi.FontValidationError):
            fi.structural_scan(bytes(body))


# --------------------------------------------------------------------------- #
# Structural sandbox — acceptances + pure-Python facts (no fontTools)
# --------------------------------------------------------------------------- #
class TestPurePythonFacts:
    def test_scan_accepts_handmade_sfnt(self):
        data = make_sfnt({"head": b"\x00" * 54, "name": name_table("X")})
        scanned = fi.structural_scan(data)
        assert scanned["container"] == "sfnt"
        assert set(scanned["tags"]) == {"head", "name"}

    def test_name_extraction_without_fonttools(self):
        data = make_sfnt({"name": name_table("Hand Crafted"), "head": b"\x00" * 54})
        facts = fi.validate_font_bytes(data)
        assert facts.family_name == "Hand Crafted"

    def test_os2_embedding_and_weight_without_fonttools(self):
        data = make_sfnt(
            {"OS/2": os2_table(fs_type=0x0002, weight=600), "name": name_table("R")}
        )
        facts = fi.validate_font_bytes(data)
        assert facts.embedding == "restricted"
        assert facts.embeddable is False
        assert facts.weight == 600

    def test_variable_axis_detected_from_tag(self):
        data = make_sfnt({"fvar": b"\x00" * 16, "head": b"\x00" * 54})
        facts = fi.validate_font_bytes(data)
        assert facts.is_variable is True


# --------------------------------------------------------------------------- #
# Embedding classification + sanitisation
# --------------------------------------------------------------------------- #
class TestClassifyEmbedding:
    @pytest.mark.parametrize(
        "fs_type,expected,no_subset",
        [
            (0x0000, "installable", False),
            (0x0002, "restricted", False),
            (0x0004, "preview_print", False),
            (0x0008, "editable", False),
            (0x0200, "installable", True),         # no-subset bit alone
            (0x0002 | 0x0200, "restricted", True),
        ],
    )
    def test_matrix(self, fs_type, expected, no_subset):
        assert fi.classify_embedding(fs_type) == (expected, no_subset)


class TestSanitise:
    def test_strips_control_and_collapses_ws(self):
        assert fi.sanitise_family("  Brand\x00\x07  Sans \n") == "Brand Sans"

    def test_empty(self):
        assert fi.sanitise_family("") == ""
        assert fi.sanitise_family(None) == ""

    def test_length_cap(self):
        assert len(fi.sanitise_family("A" * 500)) == 80

    def test_css_family_is_collision_safe(self):
        fam = fi.css_family_for("City of Manchester!", "Brand Sans")
        assert fam == "club-city-of-manchester-brand-sans"
        assert re.fullmatch(r"club-[a-z0-9-]+", fam)

    def test_css_family_namespaced_per_tenant(self):
        a = fi.css_family_for("club-a", "Inter")
        b = fi.css_family_for("club-b", "Inter")
        assert a != b  # two tenants' "Inter" never collide
        assert "inter" in a and "inter" in b


class TestUnicodeRanges:
    def test_parse_default(self):
        cps = fi.default_unicodes()
        assert ord("A") in cps and ord("z") in cps and ord("0") in cps
        assert 0x20AC in cps  # euro sign from the range spec

    def test_parses_ranges_and_singletons(self):
        cps = fi._parse_unicode_ranges("U+0041-0043, U+00E9")
        assert cps == {0x41, 0x42, 0x43, 0xE9}


# --------------------------------------------------------------------------- #
# Honest-error path (runs even without fontTools)
# --------------------------------------------------------------------------- #
class TestHonestError:
    def test_subset_without_tooling_raises(self, monkeypatch):
        monkeypatch.setattr(fi, "is_font_tooling_available", lambda: False)
        with pytest.raises(fi.FontToolingUnavailable):
            fi.subset_to_woff2(b"\x00\x01\x00\x00anything")

    def test_intake_without_tooling_raises(self, monkeypatch):
        monkeypatch.setattr(fi, "is_font_tooling_available", lambda: False)
        data = make_sfnt(
            {"name": name_table("No Tools"), "OS/2": os2_table(weight=400), "head": b"\x00" * 54}
        )
        with pytest.raises(fi.FontToolingUnavailable):
            fi.intake_font(data, profile_id="club", role="display")


# --------------------------------------------------------------------------- #
# Validation of real fonts (needs fontTools to build the fixture)
# --------------------------------------------------------------------------- #
@needs_fontbuilder
class TestValidateRealFont:
    def test_facts_from_ttf(self):
        facts = fi.validate_font_bytes(build_ttf("Acme Display", weight=800))
        assert facts.container == "sfnt"
        assert facts.family_name == "Acme Display"
        assert facts.weight == 800
        assert facts.style == "normal"
        assert facts.embedding == "installable"
        assert facts.glyph_count and facts.glyph_count > 1
        assert facts.is_variable is False

    def test_italic_detected(self):
        facts = fi.validate_font_bytes(build_ttf("Acme", italic=True))
        assert facts.style == "italic"

    def test_variable_font_detected(self):
        facts = fi.validate_font_bytes(build_ttf("Acme VF", variable=True))
        assert facts.is_variable is True


# --------------------------------------------------------------------------- #
# Subsetting + WOFF2 (needs fontTools + brotli)
# --------------------------------------------------------------------------- #
@needs_woff2
class TestSubset:
    def test_produces_woff2(self):
        out = fi.subset_to_woff2(build_ttf())
        assert out[:4] == b"wOF2"

    def test_reduces_glyphs_and_size(self):
        original = build_ttf(glyphs="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        out = fi.subset_to_woff2(original, unicodes={ord("A"), ord("B")})
        assert len(out) < len(original)
        from fontTools.ttLib import TTFont

        reloaded = TTFont(io.BytesIO(out))
        # .notdef + A + B
        assert reloaded["maxp"].numGlyphs == 3
        assert reloaded.flavor == "woff2"

    def test_deterministic(self):
        data = build_ttf()
        a = fi.subset_to_woff2(data)
        b = fi.subset_to_woff2(data)
        assert a == b

    def test_no_subset_keeps_all_glyphs(self):
        data = build_ttf(glyphs="ABCDEFGHIJ")
        from fontTools.ttLib import TTFont

        full = TTFont(io.BytesIO(data))["maxp"].numGlyphs
        out = fi.subset_to_woff2(data, do_subset=False)
        assert TTFont(io.BytesIO(out))["maxp"].numGlyphs == full


# --------------------------------------------------------------------------- #
# Full intake orchestrator + storage (needs fontTools + brotli)
# --------------------------------------------------------------------------- #
@needs_woff2
class TestIntake:
    def test_happy_path(self, _isolate_data_dir):
        rec = fi.intake_font(build_ttf("Brand Sans", weight=700), profile_id="club-x", role="display")
        assert rec.slug == "brand-sans-700-normal"
        assert rec.css_family == "club-club-x-brand-sans"
        assert rec.role == "display"
        assert rec.weight == 700
        assert rec.subsetted is True
        assert rec.woff2_size < rec.original_size
        assert len(rec.sha256) == 64
        # File + sidecar on disk under DATA_DIR.
        assert Path(rec.woff2_path).is_file()
        assert Path(rec.woff2_path).read_bytes()[:4] == b"wOF2"
        sidecar = Path(rec.woff2_path).with_suffix(".json")
        assert sidecar.is_file()
        assert json.loads(sidecar.read_text())["css_family"] == rec.css_family

    def test_overrides(self):
        rec = fi.intake_font(
            build_ttf("Detected Name", weight=700),
            profile_id="c",
            role="body",
            family="Override Family",
            weight=300,
            style="italic",
        )
        assert rec.family == "Override Family"
        assert rec.weight == 300
        assert rec.style == "italic"
        assert rec.slug == "override-family-300-italic"

    def test_restricted_rejected(self):
        with pytest.raises(fi.FontEmbeddingNotPermitted):
            fi.intake_font(build_ttf(fs_type=0x0002), profile_id="c", role="display")

    def test_restricted_allowed_with_override(self):
        rec = fi.intake_font(
            build_ttf(fs_type=0x0002), profile_id="c", role="display", allow_restricted=True
        )
        assert rec.woff2_size > 0

    def test_no_subset_bit_respected(self):
        rec = fi.intake_font(build_ttf(fs_type=0x0200), profile_id="c", role="display")
        assert rec.subsetted is False

    def test_unknown_role_rejected(self):
        with pytest.raises(fi.FontValidationError):
            fi.intake_font(build_ttf(), profile_id="c", role="banner")

    def test_blank_profile_rejected(self):
        with pytest.raises(fi.FontValidationError):
            fi.intake_font(build_ttf(), profile_id="  ", role="display")

    def test_idempotent_reupload(self):
        data = build_ttf("Repeat", weight=500)
        a = fi.intake_font(data, profile_id="c", role="display")
        b = fi.intake_font(data, profile_id="c", role="display")
        assert a.sha256 == b.sha256
        assert a.slug == b.slug
        assert Path(a.woff2_path).read_bytes() == Path(b.woff2_path).read_bytes()


# --------------------------------------------------------------------------- #
# Storage round-trips (needs fontTools + brotli)
# --------------------------------------------------------------------------- #
@needs_woff2
class TestStorage:
    def test_list_and_load(self):
        fi.intake_font(build_ttf("Alpha", weight=400), profile_id="club", role="display")
        fi.intake_font(build_ttf("Beta", weight=700), profile_id="club", role="body")
        records = fi.list_fonts("club")
        assert [r.family for r in records] == ["Alpha", "Beta"]  # sorted
        loaded = fi.load_record("club", records[0].slug)
        assert loaded is not None and loaded.family == "Alpha"

    def test_list_other_profile_empty(self):
        fi.intake_font(build_ttf("Alpha"), profile_id="club", role="display")
        assert fi.list_fonts("other-club") == []  # tenant isolation

    def test_remove(self):
        rec = fi.intake_font(build_ttf("Gamma"), profile_id="club", role="display")
        assert fi.remove_font("club", rec.slug) is True
        assert fi.load_record("club", rec.slug) is None
        assert not Path(rec.woff2_path).is_file()
        assert fi.remove_font("club", rec.slug) is False  # already gone

    def test_load_missing(self):
        assert fi.load_record("club", "nope-400-normal") is None


# --------------------------------------------------------------------------- #
# CSS emission + injection safety
# --------------------------------------------------------------------------- #
@needs_woff2
class TestCss:
    def test_font_face_relative_and_file_uri(self):
        rec = fi.intake_font(build_ttf("Brand Sans", weight=600), profile_id="club", role="display")
        rel = fi.font_face_css(rec)
        assert "url(brand-sans-600-normal.woff2)" in rel
        assert "club-club-brand-sans" in rel
        assert "googleapis" not in rel and "gstatic" not in rel
        abs_css = fi.font_face_css(rec, file_uri=True)
        assert "url(file://" in abs_css and ".woff2)" in abs_css

    def test_font_face_many_records(self):
        fi.intake_font(build_ttf("Alpha", weight=400), profile_id="club", role="display")
        fi.intake_font(build_ttf("Beta", weight=700), profile_id="club", role="body")
        css = fi.font_face_css(fi.list_fonts("club"))
        assert css.count("@font-face") == 2

    def test_css_injection_is_neutralised(self):
        evil = "Evil', 'x'); } body { display:none } @font-face { font-family: 'pwn"
        rec = fi.intake_font(build_ttf(evil), profile_id="club", role="display")
        css = rec.font_face()
        # The arbitrary human name never reaches the stylesheet; only the slug does.
        assert "display:none" not in css
        assert "body {" not in css
        assert re.fullmatch(r"club-[a-z0-9-]+", rec.css_family)
        # Exactly one @font-face block, one opening brace.
        assert css.count("@font-face") == 1
        assert css.count("{") == 1


# --------------------------------------------------------------------------- #
# Round-trip through compressed containers (needs fontTools + brotli)
# --------------------------------------------------------------------------- #
@needs_woff2
class TestCompressedContainers:
    def test_validate_woff2_reads_family_via_tooling(self):
        woff2 = fi.subset_to_woff2(build_ttf("Compressed Fam", weight=500))
        facts = fi.validate_font_bytes(woff2)
        assert facts.container == "woff2"
        assert facts.family_name == "Compressed Fam"

    def test_intake_from_woff2(self):
        woff2 = fi.subset_to_woff2(build_ttf("From Woff2", weight=500))
        rec = fi.intake_font(woff2, profile_id="club", role="display")
        assert rec.family == "From Woff2"
        assert Path(rec.woff2_path).read_bytes()[:4] == b"wOF2"
