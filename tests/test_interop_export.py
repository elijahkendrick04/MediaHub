"""1.21 interop — palette export (round-trips the importer) + brand bundle."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from mediahub.brand.palette_file import parse_palette_file
from mediahub.interop import asset_bundle, palette_export as pe

COLOURS = ["#A30D2D", "#000000", "#FFD23F"]


def _ci(seq):
    return [c.lower() for c in seq]


def test_ase_round_trips_through_importer():
    assert _ci(parse_palette_file(pe.to_ase(COLOURS))) == _ci(COLOURS)


def test_json_round_trips_through_importer():
    assert _ci(parse_palette_file(pe.to_json(COLOURS), "p.json")) == _ci(COLOURS)


def test_gpl_is_valid_gimp_palette():
    text = pe.to_gpl(COLOURS, palette_name="Club").decode()
    assert text.startswith("GIMP Palette")
    assert "Name: Club" in text
    # the red 163 13 45 appears as right-aligned columns
    assert "163" in text and "13" in text and "45" in text


def test_export_dispatch_and_bad_format():
    assert pe.export(COLOURS, "ase")[:4] == b"ASEF"
    assert pe.export(COLOURS, "gpl").startswith(b"GIMP")
    assert json.loads(pe.export(COLOURS, "json"))["colors"][0]["hex"] == "#A30D2D"
    with pytest.raises(ValueError):
        pe.export(COLOURS, "psd")


def test_export_skips_malformed_colours():
    assert _ci(parse_palette_file(pe.to_ase(["#A30D2D", "notacolour", ""]))) == ["#a30d2d"]


def test_brand_bundle_contents():
    data = asset_bundle.build_brand_bundle(
        "Club Kit", COLOURS, font_pairing="editorial", role_names=["primary", "secondary", "accent"],
        org_name="Org A",
    )
    z = zipfile.ZipFile(io.BytesIO(data))
    assert set(z.namelist()) == {"brand.json", "README.txt", "palette.ase", "palette.gpl", "palette.json"}
    brand = json.loads(z.read("brand.json"))
    assert brand["name"] == "Club Kit"
    assert brand["org"] == "Org A"
    assert brand["colours"] == COLOURS
    assert brand["roles"]["primary"] == "#A30D2D"
    # the embedded ASE round-trips too
    assert _ci(parse_palette_file(z.read("palette.ase"))) == _ci(COLOURS)


def test_brand_bundle_with_no_colours_still_builds():
    z = zipfile.ZipFile(io.BytesIO(asset_bundle.build_brand_bundle("Empty", [])))
    assert "brand.json" in z.namelist()
    assert "palette.ase" not in z.namelist()  # nothing to export
