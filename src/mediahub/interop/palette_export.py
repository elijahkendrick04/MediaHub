"""mediahub/interop/palette_export.py — export a palette to design-tool formats.

The reverse of ``brand.palette_file`` (which *imports* ``.ase`` / Adobe Color
JSON). A club can pull its MediaHub brand colours into Photoshop / Illustrator
(``.ase``), GIMP / Inkscape (``.gpl``), or a generic JSON palette — first-party
exporters, never a dependency on the other suite.

Round-trips with the importer: ``parse_palette_file(to_ase(colours))`` returns
the same hex list.
"""

from __future__ import annotations

import json
import struct
from typing import Optional

FORMATS = ("ase", "gpl", "json")
MIME = {
    "ase": "application/octet-stream",
    "gpl": "text/plain; charset=utf-8",
    "json": "application/json",
}
EXT = {"ase": ".ase", "gpl": ".gpl", "json": ".json"}


def _hex_to_rgb255(hex_colour: str) -> tuple[int, int, int]:
    h = (hex_colour or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"not a hex colour: {hex_colour!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _clean(colours) -> list[str]:
    out = []
    for c in colours or []:
        try:
            r, g, b = _hex_to_rgb255(c)
        except ValueError:
            continue
        out.append(f"#{r:02X}{g:02X}{b:02X}")
    return out


# --- Adobe Swatch Exchange (.ase) ------------------------------------------
def _ase_colour_block(name: str, hex_colour: str) -> bytes:
    r, g, b = (v / 255.0 for v in _hex_to_rgb255(hex_colour))
    name_utf16 = name.encode("utf-16-be") + b"\x00\x00"  # null-terminated
    name_len = len(name) + 1  # UTF-16 code units incl. the null
    body = (
        struct.pack(">H", name_len)
        + name_utf16
        + b"RGB "
        + struct.pack(">fff", r, g, b)
        + struct.pack(">H", 2)  # colour type: 2 = normal/process
    )
    return struct.pack(">H", 0x0001) + struct.pack(">I", len(body)) + body


def to_ase(colours, names: Optional[list[str]] = None) -> bytes:
    cols = _clean(colours)
    blocks = []
    for i, c in enumerate(cols):
        name = (names[i] if names and i < len(names) else c)
        blocks.append(_ase_colour_block(name, c))
    header = b"ASEF" + struct.pack(">HH", 1, 0) + struct.pack(">I", len(blocks))
    return header + b"".join(blocks)


# --- GIMP / Inkscape (.gpl) ------------------------------------------------
def to_gpl(colours, *, palette_name: str = "MediaHub", names: Optional[list[str]] = None) -> bytes:
    cols = _clean(colours)
    lines = [f"GIMP Palette", f"Name: {palette_name}", "Columns: 0", "#"]
    for i, c in enumerate(cols):
        r, g, b = _hex_to_rgb255(c)
        label = names[i] if names and i < len(names) else c
        lines.append(f"{r:>3} {g:>3} {b:>3}\t{label}")
    return ("\n".join(lines) + "\n").encode("utf-8")


# --- generic JSON ----------------------------------------------------------
def to_json(colours, *, palette_name: str = "MediaHub", names: Optional[list[str]] = None) -> bytes:
    cols = _clean(colours)
    entries = []
    for i, c in enumerate(cols):
        r, g, b = _hex_to_rgb255(c)
        entry = {"hex": c, "r": r, "g": g, "b": b}
        if names and i < len(names):
            entry["name"] = names[i]
        entries.append(entry)
    return json.dumps({"name": palette_name, "colors": entries}, indent=2).encode("utf-8")


def export(colours, fmt: str, *, palette_name: str = "MediaHub", names=None) -> bytes:
    fmt = (fmt or "ase").lower()
    if fmt == "ase":
        return to_ase(colours, names=names)
    if fmt == "gpl":
        return to_gpl(colours, palette_name=palette_name, names=names)
    if fmt == "json":
        return to_json(colours, palette_name=palette_name, names=names)
    raise ValueError(f"unknown palette format: {fmt!r} (use one of {FORMATS})")


__all__ = ["FORMATS", "MIME", "EXT", "to_ase", "to_gpl", "to_json", "export"]
