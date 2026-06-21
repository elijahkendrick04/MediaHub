"""Roadmap 1.12 build 3 — palette-file import (Adobe .ase / Color JSON)."""

from __future__ import annotations

import json
import struct

import pytest

from mediahub.brand.palette_file import (
    PaletteFileError,
    colours_to_kit_palette,
    parse_ase,
    parse_color_json,
    parse_palette_file,
)


# ---- .ase builder ------------------------------------------------------


def _ase_colour_block(name: str, model: str, values: list[float]) -> bytes:
    name_units = name + "\x00"
    name_bytes = name_units.encode("utf-16-be")
    model_bytes = model.encode("ascii")
    assert len(model_bytes) == 4
    body = struct.pack(">H", len(name_units)) + name_bytes + model_bytes
    body += struct.pack(">" + "f" * len(values), *values)
    body += struct.pack(">H", 2)  # colour type: normal
    return struct.pack(">H", 0x0001) + struct.pack(">I", len(body)) + body


def _ase(blocks: list[bytes]) -> bytes:
    header = b"ASEF" + struct.pack(">HH", 1, 0) + struct.pack(">I", len(blocks))
    return header + b"".join(blocks)


# ---- .ase parsing ------------------------------------------------------


def test_parse_ase_rgb():
    data = _ase(
        [
            _ase_colour_block("Red", "RGB ", [1.0, 0.0, 0.0]),
            _ase_colour_block("Navy", "RGB ", [0.0, 0.0, 0.5]),
        ]
    )
    assert parse_ase(data) == ["#ff0000", "#000080"]


def test_parse_ase_gray_and_cmyk():
    data = _ase(
        [
            _ase_colour_block("Mid", "Gray", [0.5]),
            _ase_colour_block("Cyan", "CMYK", [1.0, 0.0, 0.0, 0.0]),
        ]
    )
    out = parse_ase(data)
    assert out[0] == "#808080"
    assert out[1] == "#00ffff"


def test_parse_ase_rejects_bad_signature():
    with pytest.raises(PaletteFileError):
        parse_ase(b"NOPE" + b"\x00" * 8)


def test_parse_ase_skips_group_blocks():
    group_start = struct.pack(">H", 0xC001) + struct.pack(">I", 2) + struct.pack(">H", 0)
    blocks = [group_start, _ase_colour_block("Red", "RGB ", [1.0, 0.0, 0.0])]
    data = b"ASEF" + struct.pack(">HH", 1, 0) + struct.pack(">I", len(blocks)) + b"".join(blocks)
    assert parse_ase(data) == ["#ff0000"]


# ---- JSON parsing ------------------------------------------------------


def test_parse_json_bare_hex_list():
    assert parse_color_json(json.dumps(["#FF0000", "#00FF00"])) == ["#ff0000", "#00ff00"]


def test_parse_json_colors_key_with_hex_objects():
    text = json.dumps({"name": "Theme", "colors": [{"hex": "#123456"}, {"value": "#abcdef"}]})
    assert parse_color_json(text) == ["#123456", "#abcdef"]


def test_parse_json_rgb_triples_255_and_unit():
    text = json.dumps({"swatches": [{"r": 255, "g": 0, "b": 0}, {"r": 0.0, "g": 0.0, "b": 1.0}]})
    assert parse_color_json(text) == ["#ff0000", "#0000ff"]


def test_parse_json_dedupes_in_order():
    assert parse_color_json(json.dumps(["#ff0000", "#FF0000", "#0000ff"])) == [
        "#ff0000",
        "#0000ff",
    ]


def test_parse_non_json_scrapes_hex_tokens():
    # A CSS-ish blob, not valid JSON, still yields its hex colours.
    assert parse_color_json(":root{--a:#AA1122;--b:#334455;}") == ["#aa1122", "#334455"]


def test_parse_json_no_colours_raises():
    with pytest.raises(PaletteFileError):
        parse_color_json(json.dumps({"name": "empty"}))


# ---- dispatch + slot mapping -------------------------------------------


def test_parse_palette_file_detects_ase_by_signature():
    data = _ase([_ase_colour_block("Red", "RGB ", [1.0, 0.0, 0.0])])
    # no filename → relies on the ASEF signature
    assert parse_palette_file(data) == ["#ff0000"]


def test_parse_palette_file_json_by_extension():
    out = parse_palette_file(json.dumps(["#abcdef"]).encode("utf-8"), "theme.json")
    assert out == ["#abcdef"]


def test_parse_palette_file_empty_raises():
    with pytest.raises(PaletteFileError):
        parse_palette_file(b"", "x.json")


def test_colours_to_kit_palette_maps_in_order():
    pal = colours_to_kit_palette(["#111111", "#222222", "#333333", "#444444", "#555555"])
    assert pal == {
        "primary": "#111111",
        "secondary": "#222222",
        "accent": "#333333",
        "fourth": "#444444",
    }  # only four slots; the fifth swatch is dropped
