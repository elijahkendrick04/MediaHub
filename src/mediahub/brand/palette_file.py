"""brand/palette_file.py — import colour themes from palette files (roadmap 1.12).

Canva/Adobe let you import a colour theme from Adobe Color. MediaHub's version
reads two interchange formats a club is likely to have exported:

* **Adobe Swatch Exchange (`.ase`)** — the binary format Illustrator/Photoshop
  export. Parsed natively here (RGB/CMYK/Gray/LAB swatches → sRGB hex).
* **Adobe Color JSON** — the JSON a theme exports as. Tolerantly scanned for
  hex strings and RGB triples so the several shapes Adobe has shipped over the
  years all resolve.

This is *evidence-grounded*: the colours come from the user's own file, never
invented — so the deterministic, ordered mapping in :func:`colours_to_kit_palette`
(first swatch → primary, then secondary/accent/fourth) is honest with no LLM in
the loop. The result feeds a :class:`~mediahub.brand.kits.BrandKitRef` palette.
"""

from __future__ import annotations

import json
import re
import struct
from typing import Optional

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
_HEX3_RE = re.compile(r"#[0-9a-fA-F]{3}\b")

# Order swatches map onto kit palette slots.
_KIT_SLOTS: tuple[str, ...] = ("primary", "secondary", "accent", "fourth")


class PaletteFileError(ValueError):
    """Raised when a palette file cannot be parsed into any colours."""


# --------------------------------------------------------------------------
# Colour-model conversions → sRGB hex
# --------------------------------------------------------------------------


def _clamp_byte(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _rgb_hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % (_clamp_byte(r), _clamp_byte(g), _clamp_byte(b))


def _rgb01_hex(r: float, g: float, b: float) -> str:
    return _rgb_hex(r * 255, g * 255, b * 255)


def _cmyk_hex(c: float, m: float, y: float, k: float) -> str:
    # Naive CMYK→RGB (no ICC profile); fine for screen-preview swatch import.
    r = 255 * (1 - c) * (1 - k)
    g = 255 * (1 - m) * (1 - k)
    b = 255 * (1 - y) * (1 - k)
    return _rgb_hex(r, g, b)


def _gray_hex(g: float) -> str:
    v = _clamp_byte(g * 255)
    return "#%02x%02x%02x" % (v, v, v)


def _lab_hex(L: float, a: float, b: float) -> Optional[str]:
    try:
        from coloraide import Color

        srgb = Color("lab", [L, a, b]).convert("srgb")
        srgb.fit()  # clip out-of-gamut into sRGB
        r, g, bl = (srgb["red"], srgb["green"], srgb["blue"])
        return _rgb01_hex(r, g, bl)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Hex normalisation
# --------------------------------------------------------------------------


def _norm_hex(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v if re.fullmatch(r"#[0-9a-f]{6}", v) else None


def _dedupe(colours: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in colours:
        n = _norm_hex(c)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# --------------------------------------------------------------------------
# Adobe Swatch Exchange (.ase) — binary
# --------------------------------------------------------------------------


def parse_ase(data: bytes) -> list[str]:
    """Parse an Adobe ``.ase`` swatch file into an ordered list of hex colours."""
    if len(data) < 12 or data[:4] != b"ASEF":
        raise PaletteFileError("not an ASE file (missing ASEF signature)")
    # header: signature(4) version_major(uint16) version_minor(uint16) blocks(uint32)
    (block_count,) = struct.unpack_from(">I", data, 8)
    pos = 12
    colours: list[str] = []
    for _ in range(block_count):
        if pos + 6 > len(data):
            break
        block_type = struct.unpack_from(">H", data, pos)[0]
        block_len = struct.unpack_from(">I", data, pos + 2)[0]
        body_start = pos + 6
        body_end = body_start + block_len
        if body_end > len(data):
            break
        if block_type == 0x0001:  # colour entry
            hexv = _parse_ase_colour_block(data[body_start:body_end])
            if hexv:
                colours.append(hexv)
        # 0xC001 group start / 0xC002 group end carry no colour — skipped.
        pos = body_end
    out = _dedupe(colours)
    if not out:
        raise PaletteFileError("no colours found in ASE file")
    return out


def _parse_ase_colour_block(body: bytes) -> Optional[str]:
    try:
        # name length is in UTF-16 code units incl. the trailing null.
        name_len = struct.unpack_from(">H", body, 0)[0]
        off = 2 + name_len * 2  # skip the UTF-16BE name
        model = body[off : off + 4].decode("ascii", "ignore").strip()
        off += 4
        if model == "RGB":
            r, g, b = struct.unpack_from(">fff", body, off)
            return _rgb01_hex(r, g, b)
        if model == "CMYK":
            c, m, y, k = struct.unpack_from(">ffff", body, off)
            return _cmyk_hex(c, m, y, k)
        if model == "LAB":
            L, a, b = struct.unpack_from(">fff", body, off)
            # ASE stores L in 0..1; scale to the 0..100 LAB lightness range.
            return _lab_hex(L * 100.0, a, b)
        if model == "Gray":
            (g,) = struct.unpack_from(">f", body, off)
            return _gray_hex(g)
    except struct.error:
        return None
    return None


# --------------------------------------------------------------------------
# Adobe Color JSON (tolerant)
# --------------------------------------------------------------------------


def _colours_from_obj(obj) -> list[str]:
    """Walk an arbitrary JSON structure, collecting hex strings and RGB triples
    in document order."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, str):
            for m in _HEX_RE.findall(node) or _HEX3_RE.findall(node):
                out.append(m)
            return
        if isinstance(node, dict):
            # Common shapes: {"hex": "..."}, {"value": "..."},
            # {"r":..,"g":..,"b":..} (0..255 or 0..1), {"rgb":{...}}.
            hexish = node.get("hex") or node.get("value") or node.get("color")
            if isinstance(hexish, str) and (_HEX_RE.findall(hexish) or _HEX3_RE.findall(hexish)):
                out.append((_HEX_RE.findall(hexish) or _HEX3_RE.findall(hexish))[0])
            if all(k in node for k in ("r", "g", "b")):
                rgb = _rgb_triple(node["r"], node["g"], node["b"])
                if rgb:
                    out.append(rgb)
            for v in node.values():
                if not isinstance(v, str):
                    walk(v)
            return
        if isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(obj)
    return out


def _rgb_triple(r, g, b) -> Optional[str]:
    try:
        rf, gf, bf = float(r), float(g), float(b)
    except (TypeError, ValueError):
        return None
    # Heuristic: values <= 1 are 0..1 floats, otherwise 0..255.
    if max(rf, gf, bf) <= 1.0:
        return _rgb01_hex(rf, gf, bf)
    return _rgb_hex(rf, gf, bf)


def parse_color_json(text: str) -> list[str]:
    """Parse Adobe Color / generic JSON (or a hex list) into ordered hexes."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # Not valid JSON — fall back to scraping any hex tokens from the text.
        found = _HEX_RE.findall(text) or _HEX3_RE.findall(text)
        out = _dedupe(found)
        if not out:
            raise PaletteFileError("no colours found in file")
        return out
    out = _dedupe(_colours_from_obj(obj))
    if not out:
        raise PaletteFileError("no colours found in JSON")
    return out


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------


def parse_palette_file(data: bytes, filename: str = "") -> list[str]:
    """Dispatch on signature/extension; return an ordered list of hex colours."""
    if not data:
        raise PaletteFileError("empty file")
    name = (filename or "").lower()
    if data[:4] == b"ASEF" or name.endswith(".ase"):
        return parse_ase(data)
    return parse_color_json(data.decode("utf-8", "ignore"))


def colours_to_kit_palette(colours: list[str]) -> dict:
    """Map an ordered colour list onto kit palette slots (primary→fourth)."""
    out: dict = {}
    for slot, hexv in zip(_KIT_SLOTS, _dedupe(colours)):
        out[slot] = hexv
    return out


__all__ = [
    "PaletteFileError",
    "parse_ase",
    "parse_color_json",
    "parse_palette_file",
    "colours_to_kit_palette",
]
