"""tests/test_pack_export.py — G1.15 batch pack export (every format + manifest).

Two layers:

1. **Module tests** for ``graphic_renderer.pack_export`` — pure packaging, no
   browser: PNG-dimension reading, slugging, card collection, the manifest
   shape + honest format-coverage, and the ZIP build (structure, ordering,
   per-format sha256, determinism, path-traversal safety).
2. **Route tests** for ``/pack/<run_id>/export.zip`` via the Flask client —
   the happy-path download, the manifest carried through, the empty-state 404,
   and multi-tenant isolation (one org can't export another's run).

No Playwright/Chromium is needed anywhere: the tests synthesise tiny valid
PNGs directly, exactly as the renderer would have written them to disk.
"""

from __future__ import annotations

import io
import json
import struct
import sys
import zlib
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.graphic_renderer import pack_export as pe


# ---------------------------------------------------------------------------
# Helpers — synthesise the on-disk artefacts the renderer would produce
# ---------------------------------------------------------------------------


def _make_png(width: int, height: int, *, fill: int = 0xFF) -> bytes:
    """A minimal but byte-valid PNG with a truthful IHDR (width/height)."""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = (b"\x00" + bytes([fill, 0, 0]) * width) * height
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _write_card(
    visuals_dir: Path,
    brief_id: str,
    *,
    content_item_id: str,
    formats: dict[str, tuple[int, int]],
    sidecar_extra: dict | None = None,
) -> Path:
    """Write one card dir: a visual.json sidecar + one PNG per format."""
    bdir = visuals_dir / brief_id
    bdir.mkdir(parents=True, exist_ok=True)
    sidecar = {
        "id": f"v_{brief_id}",
        "content_item_id": content_item_id,
        "layout_template": "individual_hero",
        "confidence_label": "NEW PB",
        "why_this_design": "Hero shot — single standout swim.",
        "palette": {"--mh-primary": "#0E5BFF", "--mh-ink": "#101820"},
        "text_layers": {"swimmer_name": "Eira Hughes", "event": "200m Freestyle"},
        "sourced_asset_ids": ["asset-1"],
        "safety_notes": [],
    }
    sidecar.update(sidecar_extra or {})
    (bdir / "visual.json").write_text(json.dumps(sidecar), encoding="utf-8")
    for fmt, (w, h) in formats.items():
        (bdir / f"{fmt}.png").write_bytes(_make_png(w, h))
    return bdir


# ===========================================================================
# 1. Module tests — pure packaging
# ===========================================================================


class TestPngDimensions:
    def test_reads_real_dimensions(self):
        assert pe._png_dimensions(_make_png(1080, 1350)) == (1080, 1350)
        assert pe._png_dimensions(_make_png(1080, 1920)) == (1080, 1920)

    def test_non_png_returns_zero(self):
        assert pe._png_dimensions(b"not a png at all") == (0, 0)
        assert pe._png_dimensions(b"") == (0, 0)


class TestSlug:
    def test_sanitises_path_unsafe_text(self):
        # No slashes, dots, or spaces survive into a path component.
        s = pe._slug("../../etc/passwd")
        assert "/" not in s and ".." not in s and " " not in s

    def test_lowercases_and_collapses(self):
        assert pe._slug("Eira  Hughes — 200m Free") == "eira-hughes-200m-free"

    def test_fallback_when_empty(self):
        assert pe._slug("", "", fallback="card") == "card"
        assert pe._slug("!!!", fallback="x") == "x"


class TestCollectPackCards:
    def test_maps_formats_and_reads_metadata(self, tmp_path):
        vdir = tmp_path / "visuals"
        _write_card(
            vdir,
            "brief_a",
            content_item_id="card-A",
            formats={
                "feed_square": (1080, 1080),
                "feed_portrait": (1080, 1350),
                "story": (1080, 1920),
            },
        )
        cards = pe.collect_pack_cards(vdir)
        assert len(cards) == 1
        c = cards[0]
        assert c.content_item_id == "card-A"
        assert c.layout_template == "individual_hero"
        assert c.confidence_label == "NEW PB"
        assert c.palette["--mh-primary"] == "#0E5BFF"
        assert c.formats_present == ["feed_square", "feed_portrait", "story"]
        assert c.formats_missing == []
        # Dimensions came from the PNG headers, not a lookup table.
        dims = {f.format_name: (f.width, f.height) for f in c.formats}
        assert dims["story"] == (1080, 1920)

    def test_reports_missing_standard_formats(self, tmp_path):
        vdir = tmp_path / "visuals"
        _write_card(
            vdir, "brief_b", content_item_id="card-B", formats={"feed_portrait": (1080, 1350)}
        )
        (card,) = pe.collect_pack_cards(vdir)
        assert card.formats_present == ["feed_portrait"]
        assert card.formats_missing == ["feed_square", "story"]

    def test_format_ordering_trio_first_then_extras(self, tmp_path):
        vdir = tmp_path / "visuals"
        _write_card(
            vdir,
            "brief_c",
            content_item_id="card-C",
            formats={
                "story": (1080, 1920),
                "carousel_slide": (1080, 1080),
                "feed_square": (1080, 1080),
                "feed_portrait": (1080, 1350),
            },
        )
        (card,) = pe.collect_pack_cards(vdir)
        # Spec trio first in spec order, then any extras alphabetically.
        assert card.formats_present == ["feed_square", "feed_portrait", "story", "carousel_slide"]

    def test_skips_malformed_sidecar(self, tmp_path):
        vdir = tmp_path / "visuals"
        bad = vdir / "brief_bad"
        bad.mkdir(parents=True)
        (bad / "visual.json").write_text("{not json", encoding="utf-8")
        (bad / "feed_portrait.png").write_bytes(_make_png(1080, 1350))
        assert pe.collect_pack_cards(vdir) == []

    def test_skips_dir_with_sidecar_but_no_pngs(self, tmp_path):
        vdir = tmp_path / "visuals"
        d = vdir / "brief_nopng"
        d.mkdir(parents=True)
        (d / "visual.json").write_text(
            json.dumps({"id": "v1", "content_item_id": "x"}), encoding="utf-8"
        )
        assert pe.collect_pack_cards(vdir) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        assert pe.collect_pack_cards(tmp_path / "does-not-exist") == []

    def test_deterministic_order_by_dir_name(self, tmp_path):
        vdir = tmp_path / "visuals"
        for bid in ("brief_z", "brief_a", "brief_m"):
            _write_card(
                vdir, bid, content_item_id=f"c-{bid}", formats={"feed_portrait": (1080, 1350)}
            )
        cards = pe.collect_pack_cards(vdir)
        assert [c.brief_id for c in cards] == ["brief_a", "brief_m", "brief_z"]


class TestBuildManifest:
    def _cards(self, tmp_path):
        vdir = tmp_path / "visuals"
        _write_card(
            vdir,
            "brief_a",
            content_item_id="card-A",
            formats={
                "feed_square": (1080, 1080),
                "feed_portrait": (1080, 1350),
                "story": (1080, 1920),
            },
        )
        _write_card(
            vdir, "brief_b", content_item_id="card-B", formats={"feed_portrait": (1080, 1350)}
        )
        return pe.collect_pack_cards(vdir)

    def test_top_level_shape(self, tmp_path):
        m = pe.build_manifest(
            "run-1",
            self._cards(tmp_path),
            run_meta={"name": "Manchester Open", "venue": "MAC"},
            club={"name": "Test SC", "primary_colour": "#0E5BFF"},
        )
        assert m["manifest_version"] == pe.MANIFEST_VERSION
        assert m["kind"] == pe.MANIFEST_KIND
        assert m["run_id"] == "run-1"
        assert m["meet"]["name"] == "Manchester Open"
        assert m["club"]["name"] == "Test SC"
        assert m["standard_formats"] == list(pe.STANDARD_FORMATS)
        assert m["summary"]["card_count"] == 2
        assert m["summary"]["image_count"] == 4
        assert m["summary"]["total_image_bytes"] > 0
        assert "generated_at" in m

    def test_per_card_fields_and_coverage(self, tmp_path):
        m = pe.build_manifest("run-1", self._cards(tmp_path))
        by_cid = {c["content_item_id"]: c for c in m["cards"]}
        a = by_cid["card-A"]
        assert a["index"] == 1
        assert a["dir"].startswith("cards/01-")
        assert a["layout_template"] == "individual_hero"
        assert a["confidence_label"] == "NEW PB"
        assert a["why_this_design"]
        assert a["palette"]["--mh-primary"] == "#0E5BFF"
        # The card's actual on-graphic text rides into the manifest (records/search).
        assert a["text"]["swimmer_name"] == "Eira Hughes"
        assert a["text"]["event"] == "200m Freestyle"
        assert a["source_asset_ids"] == ["asset-1"]
        assert a["formats_present"] == ["feed_square", "feed_portrait", "story"]
        assert a["formats_missing"] == []
        # Each format entry carries file path, dims, bytes, sha256.
        f0 = a["formats"][0]
        assert set(f0) >= {"format", "label", "file", "width", "height", "bytes", "sha256"}
        assert len(f0["sha256"]) == 64
        assert by_cid["card-B"]["formats_missing"] == ["feed_square", "story"]

    def test_caption_alt_status_lookup_by_content_item_id(self, tmp_path):
        m = pe.build_manifest(
            "run-1",
            self._cards(tmp_path),
            captions={"card-A": "Eira smashes her 200 free PB!"},
            alt_texts={"card-A": "Swimmer mid-stroke"},
            statuses={"card-A": "approved", "card-B": "approved"},
        )
        by_cid = {c["content_item_id"]: c for c in m["cards"]}
        assert by_cid["card-A"]["caption"] == "Eira smashes her 200 free PB!"
        assert by_cid["card-A"]["alt_text"] == "Swimmer mid-stroke"
        assert by_cid["card-A"]["status"] == "approved"
        # Card with no caption supplied → empty string, never a KeyError.
        assert by_cid["card-B"]["caption"] == ""


class TestBuildPackExport:
    def _vdir(self, tmp_path):
        vdir = tmp_path / "visuals"
        _write_card(
            vdir,
            "brief_a",
            content_item_id="card-A",
            formats={
                "feed_square": (1080, 1080),
                "feed_portrait": (1080, 1350),
                "story": (1080, 1920),
            },
        )
        _write_card(
            vdir, "brief_b", content_item_id="card-B", formats={"feed_portrait": (1080, 1350)}
        )
        return vdir

    def test_zip_structure(self, tmp_path):
        res = pe.build_pack_export(
            "run-1", visuals_dir=self._vdir(tmp_path), captions={"card-A": "Great swim!"}
        )
        assert res.card_count == 2
        assert res.image_count == 4
        zf = zipfile.ZipFile(io.BytesIO(res.zip_bytes))
        names = set(zf.namelist())
        assert "content-pack-run-1/metadata.json" in names
        assert "content-pack-run-1/README.txt" in names
        # Card A: all three formats + a caption.txt
        a_pngs = [n for n in names if "/cards/01-" in n and n.endswith(".png")]
        assert len(a_pngs) == 3
        assert any(n.endswith("/caption.txt") and "/cards/01-" in n for n in names)
        # metadata.json parses and matches the result manifest.
        m = json.loads(zf.read("content-pack-run-1/metadata.json"))
        assert m["run_id"] == "run-1"
        assert m["summary"]["image_count"] == 4

    def test_caption_file_only_when_caption_present(self, tmp_path):
        res = pe.build_pack_export(
            "run-1", visuals_dir=self._vdir(tmp_path), captions={"card-A": "Has a caption"}
        )
        zf = zipfile.ZipFile(io.BytesIO(res.zip_bytes))
        names = set(zf.namelist())
        # card-A got a caption.txt; card-B (no caption) did not.
        cap_files = [n for n in names if n.endswith("/caption.txt")]
        assert len(cap_files) == 1
        assert "/cards/01-" in cap_files[0]

    def test_order_overrides_disk_order(self, tmp_path):
        res = pe.build_pack_export(
            "run-1", visuals_dir=self._vdir(tmp_path), order=["card-B", "card-A"]
        )
        cards = res.manifest["cards"]
        assert [c["content_item_id"] for c in cards] == ["card-B", "card-A"]
        # Folder numbering follows the ranking, not the dir name.
        assert cards[0]["dir"].startswith("cards/01-")
        assert cards[0]["content_item_id"] == "card-B"

    def test_sha256_matches_actual_bytes(self, tmp_path):
        import hashlib

        res = pe.build_pack_export("run-1", visuals_dir=self._vdir(tmp_path))
        zf = zipfile.ZipFile(io.BytesIO(res.zip_bytes))
        for card in res.manifest["cards"]:
            for f in card["formats"]:
                data = zf.read(f"content-pack-run-1/{f['file']}")
                assert hashlib.sha256(data).hexdigest() == f["sha256"]
                assert len(data) == f["bytes"]

    def test_deterministic_with_pinned_timestamp(self, tmp_path):
        vdir = self._vdir(tmp_path)
        kw = dict(
            visuals_dir=vdir,
            generated_at="2026-06-16T00:00:00+00:00",
            captions={"card-A": "x"},
            order=["card-A", "card-B"],
        )
        a = pe.build_pack_export("run-1", **kw)
        b = pe.build_pack_export("run-1", **kw)
        assert a.zip_bytes == b.zip_bytes

    def test_empty_visuals_dir_yields_manifest_only_zip(self, tmp_path):
        empty = tmp_path / "visuals"
        empty.mkdir()
        res = pe.build_pack_export("run-1", visuals_dir=empty)
        assert res.card_count == 0 and res.image_count == 0
        zf = zipfile.ZipFile(io.BytesIO(res.zip_bytes))
        assert "content-pack-run-1/metadata.json" in zf.namelist()
        assert json.loads(zf.read("content-pack-run-1/metadata.json"))["cards"] == []

    def test_svg_sidecar_bundled_and_in_manifest(self, tmp_path):
        """An on-disk <format>.svg sidecar (MEDIAHUB_SVG_SIDECAR) rides into
        the ZIP beside its PNG and is listed in the manifest entry."""
        vdir = self._vdir(tmp_path)
        (vdir / "brief_a" / "story.svg").write_text("<svg/>", encoding="utf-8")
        res = pe.build_pack_export("run-1", visuals_dir=vdir)
        zf = zipfile.ZipFile(io.BytesIO(res.zip_bytes))
        names = set(zf.namelist())
        svg_names = [n for n in names if n.endswith(".svg")]
        assert len(svg_names) == 1
        assert svg_names[0].endswith("/story.svg") and "/cards/01-" in svg_names[0]
        by_cid = {c["content_item_id"]: c for c in res.manifest["cards"]}
        fmts = {f["format"]: f for f in by_cid["card-A"]["formats"]}
        assert fmts["story"]["svg_file"].endswith("/story.svg")
        # Formats without a sidecar carry no svg_file key.
        assert "svg_file" not in fmts["feed_square"]
        assert (
            "svg_file" not in {f["format"]: f for f in by_cid["card-B"]["formats"]}["feed_portrait"]
        )

    def test_rejected_card_excluded_from_zip_and_manifest(self, tmp_path):
        """A human rejected card-B — its images and caption must not ship."""
        res = pe.build_pack_export(
            "run-1",
            visuals_dir=self._vdir(tmp_path),
            statuses={"card-A": "approved", "card-B": "rejected"},
            captions={"card-B": "should not ship"},
        )
        assert res.card_count == 1
        cids = [c["content_item_id"] for c in res.manifest["cards"]]
        assert cids == ["card-A"]
        zf = zipfile.ZipFile(io.BytesIO(res.zip_bytes))
        # Only card-A's three formats made it in; no caption.txt for card-B.
        assert sum(1 for n in zf.namelist() if n.endswith(".png")) == 3
        assert not any(n.endswith("/caption.txt") for n in zf.namelist())

    def test_pending_card_retained_with_status_in_manifest(self, tmp_path):
        res = pe.build_pack_export(
            "run-1",
            visuals_dir=self._vdir(tmp_path),
            statuses={"card-A": "approved", "card-B": "pending"},
        )
        assert res.card_count == 2
        by_cid = {c["content_item_id"]: c for c in res.manifest["cards"]}
        assert by_cid["card-B"]["status"] == "pending"

    def test_path_traversal_in_title_is_neutralised(self, tmp_path):
        vdir = tmp_path / "visuals"
        _write_card(
            vdir,
            "brief_evil",
            content_item_id="card-evil",
            formats={"feed_portrait": (1080, 1350)},
            sidecar_extra={"text_layers": {"swimmer_name": "../../etc", "event": "passwd"}},
        )
        res = pe.build_pack_export("run-1", visuals_dir=vdir)
        for name in zipfile.ZipFile(io.BytesIO(res.zip_bytes)).namelist():
            assert ".." not in name
            assert not name.startswith("/")


# ===========================================================================
# 2. Route tests — /pack/<run_id>/export.zip
# ===========================================================================


@pytest.fixture
def client(app, web_module, tmp_path):
    """Fresh isolated DATA_DIR/RUNS_DIR (canonical fixtures) with the org gate
    enforced and two club profiles seeded."""
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="club-a", display_name="Club A", brand_voice_summary="Friendly.")
    )
    save_profile(
        ClubProfile(profile_id="club-b", display_name="Club B", brand_voice_summary="Serious.")
    )

    runs_dir = tmp_path / "runs_v4"
    with app.test_client() as c:
        yield c, web_module, runs_dir


def _seed_run(runs_dir: Path, run_id: str, profile_id: str, *, with_visuals=True):
    """Write the run JSON + (optionally) a visuals dir with two cards."""
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "meet": {"name": "Manchester Open", "venue": "Manchester Aquatics Centre"},
            }
        ),
        encoding="utf-8",
    )
    if with_visuals:
        vdir = runs_dir / run_id / "visuals"
        _write_card(
            vdir,
            "brief_a",
            content_item_id="card-A",
            formats={
                "feed_square": (1080, 1080),
                "feed_portrait": (1080, 1350),
                "story": (1080, 1920),
            },
        )
        _write_card(
            vdir, "brief_b", content_item_id="card-B", formats={"feed_portrait": (1080, 1350)}
        )


def _pin(client, profile_id: str):
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_json()


class TestPackExportRoute:
    def test_happy_path_streams_zip(self, client):
        c, _wm, runs_dir = client
        _seed_run(runs_dir, "run-a1", "club-a")
        _pin(c, "club-a")
        resp = c.get("/pack/run-a1/export.zip")
        assert resp.status_code == 200
        assert resp.mimetype == "application/zip"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert "run-a1-all-formats.zip" in resp.headers.get("Content-Disposition", "")
        zf = zipfile.ZipFile(io.BytesIO(resp.data))
        names = set(zf.namelist())
        assert "content-pack-run-a1/metadata.json" in names
        assert sum(1 for n in names if n.endswith(".png")) == 4

    def test_manifest_carries_meet_and_run(self, client):
        c, _wm, runs_dir = client
        _seed_run(runs_dir, "run-a1", "club-a")
        _pin(c, "club-a")
        resp = c.get("/pack/run-a1/export.zip")
        zf = zipfile.ZipFile(io.BytesIO(resp.data))
        m = json.loads(zf.read("content-pack-run-a1/metadata.json"))
        assert m["run_id"] == "run-a1"
        assert m["meet"]["name"] == "Manchester Open"
        assert m["summary"]["card_count"] == 2
        # Club brand name is resolved from the profile.
        assert m["club"].get("name") == "Club A"

    def test_404_when_no_visuals(self, client):
        c, _wm, runs_dir = client
        _seed_run(runs_dir, "run-a2", "club-a", with_visuals=False)
        _pin(c, "club-a")
        resp = c.get("/pack/run-a2/export.zip")
        assert resp.status_code == 404

    def test_tenant_isolation_blocks_other_org(self, client):
        """A run owned by club-b must not be exportable from a club-a session."""
        c, _wm, runs_dir = client
        _seed_run(runs_dir, "run-b1", "club-b")
        _pin(c, "club-a")
        resp = c.get("/pack/run-b1/export.zip")
        assert resp.status_code == 404
        # And the rightful owner CAN export it.
        _pin(c, "club-b")
        ok = c.get("/pack/run-b1/export.zip")
        assert ok.status_code == 200

    def test_pack_page_surfaces_export_link(self, client):
        """The new download is wired into the content-builder page."""
        c, wm, runs_dir = client
        _pin(c, "club-a")
        with c.application.test_request_context():
            url = wm.url_for("pack_export_zip", run_id="run-a1")
        assert url == "/pack/run-a1/export.zip"
