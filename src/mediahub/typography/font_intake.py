"""Club custom-font upload pipeline (roadmap G1.10).

Lets a club bring its own brand typeface into MediaHub's renderers. The pipeline
has three pillars, in order:

1. **Security-sandboxed validation** — untrusted uploaded bytes are first run
   through a *pure-Python structural scan* (:func:`structural_scan`) that never
   hands the file to a heavyweight parser until cheap, arithmetic bounds checks
   have passed: magic-number sniffing, header + table-directory parsing with
   strict offset/length bounds (out-of-bounds read guard), a table-count cap, an
   upload-size cap, and a *decompressed-size* cap for WOFF/WOFF2 (the classic
   font "zip bomb" guard — a 2 KB file must not claim to inflate to 2 GB). Only
   after that gate do we read the family name and the OS/2 ``fsType`` embedding
   bits to refuse foundry-restricted fonts.

2. **Subsetting** — the validated font is reduced to MediaHub's Latin glyph set
   (the same ``unicode-range`` the built-in self-hosted families use), with the
   bloaty metadata/glyph-name tables dropped. Output is deterministic so the same
   upload always yields byte-identical WOFF2 (stable hash / cache key). The
   foundry's "no subsetting" ``fsType`` bit is respected — such a font is
   converted to WOFF2 without subsetting rather than against its licence.

3. **First-party self-hosting** — the result is written as a WOFF2 under
   ``DATA_DIR/custom_fonts/<profile_id>/`` with a JSON sidecar, and an
   ``@font-face`` block is emitted. **No Google Fonts CDN, ever** — same rule as
   the built-in families (``web/static/theme/fonts.css``,
   ``graphic_renderer/layouts/_shared.css``, the Remotion reel). The emitted
   ``font-family`` is a collision-safe, per-tenant CSS identifier so a club
   uploading a font literally named "Inter" can never shadow the built-in one,
   and the human family name (which may contain anything) never reaches a CSS
   string — closing CSS-injection by construction.

Honest-error contract (CLAUDE.md): subsetting + WOFF2 encoding need ``fontTools``
+ ``brotli``. When they are absent the productive path raises
:class:`FontToolingUnavailable` rather than degrading to a fake/heuristic result.
The *security* path (rejecting malformed/oversized/bomb/restricted uploads) works
with no third-party dependency at all, so an unsafe file is never accepted even in
a stripped environment.

This module is a self-contained seam (roadmap tag 🟢 ISOLATED — new files only).
It deliberately does **not** edit ``web.py``, ``club_profile.py`` or the
renderer; a later wiring task adds the upload route and maps a stored font's
``role`` onto the renderer's headline/body classes via :func:`font_face_css`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class FontIntakeError(Exception):
    """Base class for every font-intake failure."""


class FontValidationError(FontIntakeError):
    """The uploaded bytes were rejected by the security/structural sandbox."""


class FontEmbeddingNotPermitted(FontValidationError):
    """The font's OS/2 ``fsType`` forbids embedding (foundry-restricted)."""


class FontToolingUnavailable(FontIntakeError):
    """``fontTools`` / ``brotli`` are not installed, so the productive
    subset → WOFF2 path cannot run. Surfaced as an honest error instead of a
    fabricated/heuristic font (CLAUDE.md: never a fake fallback)."""


# --------------------------------------------------------------------------- #
# Limits & constants (the sandbox's hard caps)
# --------------------------------------------------------------------------- #
# A Latin subset is a few dozen KB; a full unhinted variable font with many
# scripts is ~1-2 MB. 5 MiB leaves headroom while bounding abuse.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Reconstructed-sfnt cap for WOFF/WOFF2 (the decompression-bomb guard). A real
# font's uncompressed sfnt is well under this; the cap stops a tiny file that
# *claims* to inflate to gigabytes.
MAX_DECOMPRESSED_BYTES = 30 * 1024 * 1024
# ``numTables`` is a uint16 (max 65535). Real fonts have < ~30 tables; this cap
# rejects garbage counts before we walk a bogus directory.
MAX_TABLES = 256

# Container magic numbers (first 4 bytes).
_MAGIC_TRUETYPE = b"\x00\x01\x00\x00"  # sfnt with TrueType outlines
_MAGIC_OPENTYPE = b"OTTO"  # sfnt with CFF (OpenType/PostScript) outlines
_MAGIC_TRUE = b"true"  # legacy Apple TrueType
_MAGIC_TYP1 = b"typ1"  # legacy Apple Type 1 in sfnt
_MAGIC_WOFF = b"wOFF"  # WOFF 1.0
_MAGIC_WOFF2 = b"wOF2"  # WOFF 2.0
_MAGIC_TTC = b"ttcf"  # TrueType Collection — rejected (single faces only)

_SFNT_MAGICS = (_MAGIC_TRUETYPE, _MAGIC_OPENTYPE, _MAGIC_TRUE, _MAGIC_TYP1)

# The Latin coverage MediaHub self-hosts for every built-in family — kept
# identical to graphic_renderer/layouts/_shared.css so a custom font matches
# their glyph coverage and the renderer's autofit metrics behave the same way.
DEFAULT_UNICODE_RANGES = (
    "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
    "U+0304, U+0308, U+0329, U+2000-206F, U+2074, U+20AC, U+2122, U+2191, "
    "U+2193, U+2212, U+2215, U+FEFF, U+FFFD"
)

# Where a custom font slots in the renderer. The wiring task maps these onto the
# headline / body / numeric CSS classes; here we only validate the label.
ALLOWED_ROLES = ("display", "headline", "body", "numeric", "mono", "accent")

# OS/2 fsType embedding classification.
_EMBED_INSTALLABLE = "installable"  # fsType == 0: no restriction
_EMBED_EDITABLE = "editable"  # bit 3 (0x0008)
_EMBED_PREVIEW_PRINT = "preview_print"  # bit 2 (0x0004)
_EMBED_RESTRICTED = "restricted"  # bit 1 (0x0002): must not be embedded
_EMBED_UNKNOWN = "unknown"  # could not be read (e.g. WOFF2 w/o tooling)


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FontFacts:
    """Read-only facts the validator extracted from an uploaded font."""

    container: str  # 'sfnt' | 'woff' | 'woff2'
    sfnt_flavor: str  # 'truetype' | 'cff' | 'unknown'
    raw_size: int
    num_tables: int
    table_tags: tuple[str, ...]
    declared_sfnt_size: Optional[int]  # WOFF/WOFF2 reconstructed size; None for sfnt
    family_name: Optional[str] = None
    subfamily_name: Optional[str] = None
    full_name: Optional[str] = None
    is_variable: bool = False  # has an 'fvar' table
    glyph_count: Optional[int] = None
    weight: Optional[int] = None  # OS/2 usWeightClass
    style: Optional[str] = None  # 'normal' | 'italic'
    embedding: str = _EMBED_UNKNOWN
    embeddable: bool = False  # read it and it is not restricted
    no_subset: bool = False  # fsType bit 9 (0x0200): subsetting forbidden

    def to_dict(self) -> dict:
        d = asdict(self)
        d["table_tags"] = list(self.table_tags)
        return d


@dataclass
class FontRecord:
    """A successfully ingested, self-hosted custom font."""

    profile_id: str
    slug: str  # stable id: <family>-<weight>-<style>
    family: str  # human family name (for labels/JSON)
    css_family: str  # collision-safe CSS @font-face family
    role: str
    weight: int
    style: str  # 'normal' | 'italic'
    woff2_path: str
    woff2_size: int
    original_size: int
    sha256: str
    unicode_range: str
    subsetted: bool
    created_at: str
    facts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FontRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def font_face(self, *, file_uri: bool = False) -> str:
        """Return this record's ``@font-face`` CSS block.

        ``file_uri=False`` (default) emits a relative ``url(<slug>.woff2)`` —
        for first-party web serving (mirrors ``_shared.css``). ``file_uri=True``
        emits an absolute ``file://`` URL of the stored WOFF2, for the Playwright
        renderer to inline directly.
        """
        if file_uri:
            src = Path(self.woff2_path).resolve().as_uri()
        else:
            src = f"{self.slug}.woff2"
        return (
            "@font-face {\n"
            f"  font-family: '{self.css_family}';\n"
            f"  font-style: {self.style};\n"
            f"  font-weight: {self.weight};\n"
            "  font-display: swap;\n"
            f"  src: url({src}) format('woff2');\n"
            f"  unicode-range: {self.unicode_range};\n"
            "}"
        )


# --------------------------------------------------------------------------- #
# Bounds-checked binary reader (the heart of the OOB-read guard)
# --------------------------------------------------------------------------- #
class _Reader:
    """Reads big-endian ints from a buffer, raising on any out-of-bounds slice."""

    __slots__ = ("d", "n")

    def __init__(self, data: bytes):
        self.d = data
        self.n = len(data)

    def _need(self, off: int, size: int) -> None:
        if off < 0 or off + size > self.n:
            raise FontValidationError(
                f"truncated/out-of-bounds read at offset {off} (+{size}, len {self.n})"
            )

    def u16(self, off: int) -> int:
        self._need(off, 2)
        return int.from_bytes(self.d[off : off + 2], "big")

    def u32(self, off: int) -> int:
        self._need(off, 4)
        return int.from_bytes(self.d[off : off + 4], "big")

    def tag(self, off: int) -> str:
        self._need(off, 4)
        return self.d[off : off + 4].decode("latin-1")


def _printable_tag(tag: str) -> bool:
    """A valid sfnt table tag is four bytes in the printable ASCII range."""
    return len(tag) == 4 and all(0x20 <= ord(c) <= 0x7E for c in tag)


# --------------------------------------------------------------------------- #
# Container sniffing
# --------------------------------------------------------------------------- #
def sniff_container(data: bytes) -> Optional[str]:
    """Return ``'sfnt'`` / ``'woff'`` / ``'woff2'`` from the magic, else ``None``.

    TrueType Collections (``ttcf``) return ``None`` — they are intentionally
    unsupported (we accept a single face per upload).
    """
    if len(data) < 4:
        return None
    head = data[:4]
    if head == _MAGIC_WOFF2:
        return "woff2"
    if head == _MAGIC_WOFF:
        return "woff"
    if head in _SFNT_MAGICS:
        return "sfnt"
    return None


def _flavor_label(magic: bytes) -> str:
    if magic == _MAGIC_OPENTYPE:
        return "cff"
    if magic in (_MAGIC_TRUETYPE, _MAGIC_TRUE):
        return "truetype"
    return "unknown"


# --------------------------------------------------------------------------- #
# Structural scan — the pure-Python security sandbox
# --------------------------------------------------------------------------- #
def _scan_sfnt(r: _Reader) -> dict:
    """Validate an sfnt header + table directory; return facts incl. table offsets."""
    num_tables = r.u16(4)
    if not (1 <= num_tables <= MAX_TABLES):
        raise FontValidationError(f"implausible table count: {num_tables}")
    tags: list[str] = []
    offsets: dict[str, tuple[int, int]] = {}
    for i in range(num_tables):
        rec = 12 + i * 16
        tag = r.tag(rec)
        if not _printable_tag(tag):
            raise FontValidationError(f"non-printable table tag at entry {i}")
        toff = r.u32(rec + 8)
        tlen = r.u32(rec + 12)
        # Bounds: the table body must lie entirely within the file.
        if toff < 0 or tlen < 0 or toff + tlen > r.n:
            raise FontValidationError(f"table {tag!r} out of bounds (off={toff}, len={tlen})")
        tags.append(tag)
        offsets[tag] = (toff, tlen)
    return {"num_tables": num_tables, "tags": tags, "offsets": offsets, "declared_sfnt_size": None}


def _scan_woff(r: _Reader) -> dict:
    """Validate a WOFF 1.0 header + directory; enforce the decompression cap."""
    if r.u32(8) != r.n:
        raise FontValidationError("WOFF length field does not match the file size")
    num_tables = r.u16(12)
    if not (1 <= num_tables <= MAX_TABLES):
        raise FontValidationError(f"implausible WOFF table count: {num_tables}")
    declared = r.u32(16)  # totalSfntSize (reconstructed, uncompressed)
    if declared > MAX_DECOMPRESSED_BYTES:
        raise FontValidationError(
            f"WOFF claims a {declared}-byte decompressed size (bomb guard "
            f"caps at {MAX_DECOMPRESSED_BYTES})"
        )
    tags: list[str] = []
    total_orig = 0
    for i in range(num_tables):
        rec = 44 + i * 20  # WOFF table directory entries are 20 bytes
        tag = r.tag(rec)
        if not _printable_tag(tag):
            raise FontValidationError(f"non-printable WOFF table tag at entry {i}")
        toff = r.u32(rec + 4)
        comp_len = r.u32(rec + 8)
        orig_len = r.u32(rec + 12)
        if toff + comp_len > r.n:
            raise FontValidationError(f"WOFF table {tag!r} compressed body out of bounds")
        total_orig += orig_len
        if total_orig > MAX_DECOMPRESSED_BYTES:
            raise FontValidationError("WOFF decompressed table total exceeds the bomb-guard cap")
        tags.append(tag)
    return {"num_tables": num_tables, "tags": tags, "offsets": {}, "declared_sfnt_size": declared}


# WOFF2 "known table" tags, indexed by the 6-bit flag value (0..62); 63 = custom.
_WOFF2_KNOWN_TAGS = (
    "cmap",
    "head",
    "hhea",
    "hmtx",
    "maxp",
    "name",
    "OS/2",
    "post",
    "cvt ",
    "fpgm",
    "glyf",
    "loca",
    "prep",
    "CFF ",
    "VORG",
    "EBDT",
    "EBLC",
    "gasp",
    "hdmx",
    "kern",
    "LTSH",
    "PCLT",
    "VDMX",
    "vhea",
    "vmtx",
    "BASE",
    "GDEF",
    "GPOS",
    "GSUB",
    "EBSC",
    "JSTF",
    "MATH",
    "CBDT",
    "CBLC",
    "COLR",
    "CPAL",
    "SVG ",
    "sbix",
    "acnt",
    "avar",
    "bdat",
    "bloc",
    "bsln",
    "cvar",
    "fdsc",
    "feat",
    "fmtx",
    "fvar",
    "gvar",
    "hsty",
    "just",
    "lcar",
    "mort",
    "morx",
    "opbd",
    "prop",
    "trak",
    "Zapf",
    "Silf",
    "Glat",
    "Gloc",
    "Feat",
    "Sill",
)


def _read_uint_base128(r: _Reader, off: int) -> tuple[int, int]:
    """Read a WOFF2 UIntBase128; return (value, next_offset). Bounded to 5 bytes."""
    value = 0
    for i in range(5):
        r._need(off, 1)
        b = r.d[off]
        off += 1
        if i == 0 and b == 0x80:
            raise FontValidationError("WOFF2 UIntBase128 has a leading zero")
        if value & 0xFE000000:
            raise FontValidationError("WOFF2 UIntBase128 overflow")
        value = (value << 7) | (b & 0x7F)
        if (b & 0x80) == 0:
            return value, off
    raise FontValidationError("WOFF2 UIntBase128 too long")


def _scan_woff2(r: _Reader) -> dict:
    """Validate a WOFF2 header; enforce the decompression cap.

    Header guards are the load-bearing security checks (``totalSfntSize`` is the
    bomb guard). The variable-length table directory is decoded *best-effort* for
    the tag list (used only to detect a variable font); a decode hiccup there is
    not a rejection — a genuinely corrupt stream is caught later by fontTools.
    """
    if r.u32(8) != r.n:
        raise FontValidationError("WOFF2 length field does not match the file size")
    num_tables = r.u16(12)
    if not (1 <= num_tables <= MAX_TABLES):
        raise FontValidationError(f"implausible WOFF2 table count: {num_tables}")
    declared = r.u32(16)  # totalSfntSize (reconstructed, uncompressed)
    if declared > MAX_DECOMPRESSED_BYTES:
        raise FontValidationError(
            f"WOFF2 claims a {declared}-byte decompressed size (bomb guard "
            f"caps at {MAX_DECOMPRESSED_BYTES})"
        )
    total_compressed = r.u32(20)
    if total_compressed > r.n:
        raise FontValidationError("WOFF2 compressed size exceeds the file size")

    tags: list[str] = []
    try:  # best-effort tag decode (facts only — never a rejection path)
        off = 48  # WOFF2 header is 48 bytes
        for _ in range(num_tables):
            flags = r.d[off]
            off += 1
            if (flags & 0x3F) == 0x3F:
                tags.append(r.tag(off))
                off += 4
            else:
                tags.append(_WOFF2_KNOWN_TAGS[flags & 0x3F])
            _orig, off = _read_uint_base128(r, off)
            # A non-null transform carries a second length; glyf/loca use the
            # transform-version bits (6-7). We skip the transformLength when present.
            xform = (flags >> 6) & 0x03
            tag = tags[-1]
            has_xform_len = (tag in ("glyf", "loca") and xform == 0) or (
                tag not in ("glyf", "loca") and xform != 0
            )
            if has_xform_len:
                _xlen, off = _read_uint_base128(r, off)
    except Exception:
        tags = []  # leave it to fontTools to confirm the directory

    return {"num_tables": num_tables, "tags": tags, "offsets": {}, "declared_sfnt_size": declared}


def structural_scan(data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> dict:
    """Run the pure-Python security sandbox. Raises :class:`FontValidationError`.

    Returns a dict of structural facts (``container``, ``num_tables``, ``tags``,
    ``offsets`` for sfnt, ``declared_sfnt_size``). No third-party dependency —
    this gate works even with ``fontTools`` absent, so a malformed / oversized /
    decompression-bomb upload is rejected before anything heavyweight runs.
    """
    if not data:
        raise FontValidationError("empty upload")
    if len(data) > max_bytes:
        raise FontValidationError(
            f"font is {len(data)} bytes; the {max_bytes}-byte upload cap was exceeded"
        )
    if len(data) >= 4 and data[:4] == _MAGIC_TTC:
        raise FontValidationError("TrueType Collections are not supported — upload a single face")
    container = sniff_container(data)
    if container is None:
        raise FontValidationError("unrecognised font format (not TTF/OTF/WOFF/WOFF2)")

    r = _Reader(data)
    if container == "sfnt":
        scanned = _scan_sfnt(r)
        scanned["sfnt_flavor"] = _flavor_label(data[:4])
    elif container == "woff":
        scanned = _scan_woff(r)
        scanned["sfnt_flavor"] = _flavor_label(data[4:8])  # WOFF 'flavor' field
    else:
        scanned = _scan_woff2(r)
        scanned["sfnt_flavor"] = _flavor_label(data[4:8])  # WOFF2 'flavor' field
    scanned["container"] = container
    return scanned


# --------------------------------------------------------------------------- #
# Pure-Python name + OS/2 extraction (sfnt only — uncompressed tables)
# --------------------------------------------------------------------------- #
def _decode_sfnt_names(data: bytes, name_off: int, name_len: int) -> dict[int, str]:
    """Decode the (uncompressed) 'name' table; return {nameID: best-string}."""
    r = _Reader(data)
    if name_len < 6:
        return {}
    count = r.u16(name_off + 2)
    string_base = name_off + r.u16(name_off + 4)
    best: dict[int, tuple[int, str]] = {}
    for i in range(count):
        rec = name_off + 6 + i * 12
        if rec + 12 > name_off + name_len:
            break
        plat = r.u16(rec + 0)
        lang = r.u16(rec + 4)
        nid = r.u16(rec + 6)
        slen = r.u16(rec + 8)
        soff = r.u16(rec + 10)
        s0 = string_base + soff
        if slen <= 0 or s0 + slen > len(data):
            continue
        raw = data[s0 : s0 + slen]
        try:
            if plat in (0, 3):  # Unicode / Windows → UTF-16BE
                val = raw.decode("utf-16-be")
            elif plat == 1:  # Macintosh → Latin-1 approximation
                val = raw.decode("latin-1")
            else:
                continue
        except Exception:
            continue
        # Prefer Windows platform and English so we don't pick a localised name.
        score = (2 if plat == 3 else 0) + (1 if lang in (0x409, 0) else 0)
        if nid not in best or score > best[nid][0]:
            best[nid] = (score, val.strip("\x00").strip())
    return {nid: v for nid, (s, v) in best.items()}


def classify_embedding(fs_type: int) -> tuple[str, bool]:
    """Map an OS/2 ``fsType`` value to (label, no_subset).

    Embedding-restriction bits (mutually exclusive in practice, low bit wins):
      * 0x0002 bit 1  Restricted License — must not be embedded → ``restricted``
      * 0x0004 bit 2  Preview & Print     → ``preview_print``
      * 0x0008 bit 3  Editable            → ``editable``
      * 0x0000        no restriction      → ``installable``
    Independent bit:
      * 0x0200 bit 9  No subsetting       → ``no_subset=True``
    """
    no_subset = bool(fs_type & 0x0200)
    if fs_type & 0x0002:
        return _EMBED_RESTRICTED, no_subset
    if fs_type & 0x0004:
        return _EMBED_PREVIEW_PRINT, no_subset
    if fs_type & 0x0008:
        return _EMBED_EDITABLE, no_subset
    return _EMBED_INSTALLABLE, no_subset


def _sfnt_facts(data: bytes, scanned: dict) -> dict:
    """Pure-Python family/weight/style/embedding facts from an sfnt's tables."""
    out: dict = {}
    r = _Reader(data)
    offsets: dict[str, tuple[int, int]] = scanned.get("offsets", {})

    if "name" in offsets:
        try:
            names = _decode_sfnt_names(data, *offsets["name"])
            out["family_name"] = names.get(16) or names.get(1)
            out["subfamily_name"] = names.get(17) or names.get(2)
            out["full_name"] = names.get(4)
        except FontValidationError:
            pass

    if "OS/2" in offsets:
        os2_off, os2_len = offsets["OS/2"]
        try:
            if os2_len >= 10:
                out["weight"] = r.u16(os2_off + 4)  # usWeightClass
                embedding, no_subset = classify_embedding(r.u16(os2_off + 8))  # fsType
                out["embedding"] = embedding
                out["embeddable"] = embedding != _EMBED_RESTRICTED
                out["no_subset"] = no_subset
            if os2_len >= 64:
                fs_selection = r.u16(os2_off + 62)
                out["style"] = "italic" if (fs_selection & 0x01) else "normal"
        except FontValidationError:
            pass

    if "maxp" in offsets:
        mp_off, mp_len = offsets["maxp"]
        try:
            if mp_len >= 6:
                out["glyph_count"] = r.u16(mp_off + 4)  # numGlyphs
        except FontValidationError:
            pass

    if out.get("style") is None and "head" in offsets:
        head_off, head_len = offsets["head"]
        try:
            if head_len >= 46:
                mac_style = r.u16(head_off + 44)
                out["style"] = "italic" if (mac_style & 0x02) else "normal"
        except FontValidationError:
            pass

    return out


# --------------------------------------------------------------------------- #
# fontTools availability + deep enrichment (WOFF/WOFF2 names, fsType, glyphs)
# --------------------------------------------------------------------------- #
def is_font_tooling_available() -> bool:
    """True when ``fontTools`` + ``brotli`` (for WOFF2) are importable."""
    try:
        import fontTools  # noqa: F401
        import fontTools.ttLib.woff2  # noqa: F401
        import brotli  # noqa: F401

        return True
    except Exception:
        return False


def _require_tooling() -> None:
    if not is_font_tooling_available():
        raise FontToolingUnavailable(
            "font subsetting/WOFF2 conversion needs the 'fonttools[woff]' package "
            "(fontTools + brotli). Install it (it ships in MediaHub's deploy image) "
            "or the pipeline cannot produce a self-hosted font."
        )


def _enrich_with_fonttools(data: bytes) -> dict:
    """Best-effort deep facts via fontTools (used mainly for WOFF/WOFF2)."""
    out: dict = {}
    try:
        from io import BytesIO
        from fontTools.ttLib import TTFont

        font = TTFont(BytesIO(data), fontNumber=0, lazy=True)
        if "name" in font:
            nt = font["name"]
            fam = nt.getDebugName(16) or nt.getDebugName(1)
            sub = nt.getDebugName(17) or nt.getDebugName(2)
            out["family_name"] = fam
            out["subfamily_name"] = sub
            out["full_name"] = nt.getDebugName(4)
        if "OS/2" in font:
            os2 = font["OS/2"]
            out["weight"] = int(getattr(os2, "usWeightClass", 0)) or None
            embedding, no_subset = classify_embedding(int(getattr(os2, "fsType", 0)))
            out["embedding"] = embedding
            out["embeddable"] = embedding != _EMBED_RESTRICTED
            out["no_subset"] = no_subset
            out["style"] = "italic" if (int(getattr(os2, "fsSelection", 0)) & 0x01) else "normal"
        if "maxp" in font:
            out["glyph_count"] = int(getattr(font["maxp"], "numGlyphs", 0)) or None
        out["is_variable"] = "fvar" in font
        font.close()
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- #
# Public validation entry point
# --------------------------------------------------------------------------- #
def validate_font_bytes(data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> FontFacts:
    """Validate uploaded bytes and return :class:`FontFacts`.

    Runs the pure-Python structural sandbox first, then enriches with metadata
    (family, weight, style, embedding bits, glyph count, variable-axis presence).
    sfnt metadata is read pure-Python; WOFF/WOFF2 metadata is read via fontTools
    when present (additive — never a rejection). Raises
    :class:`FontValidationError` for a malformed/oversized/bomb upload and
    :class:`FontEmbeddingNotPermitted` for a foundry-restricted font we *could*
    read the bits of.
    """
    scanned = structural_scan(data, max_bytes=max_bytes)
    tags = tuple(scanned.get("tags", ()))

    facts: dict = {
        "container": scanned["container"],
        "sfnt_flavor": scanned.get("sfnt_flavor", "unknown"),
        "raw_size": len(data),
        "num_tables": scanned["num_tables"],
        "table_tags": tags,
        "declared_sfnt_size": scanned.get("declared_sfnt_size"),
        "is_variable": "fvar" in tags,
    }

    if scanned["container"] == "sfnt":
        facts.update(_sfnt_facts(data, scanned))
    # A well-formed sfnt is fully read pure-Python above (no fontTools needed).
    # Only reach for fontTools when something is still missing — i.e. a WOFF/
    # WOFF2 (compressed tables) or a names-less sfnt. Enrichment only *fills
    # gaps*; it never overwrites a value the pure-Python pass already trusts.
    if facts.get("family_name") is None or facts.get("embedding") is None:
        for k, v in _enrich_with_fonttools(data).items():
            if v is None:
                continue
            if facts.get(k) in (None, False):
                facts[k] = v

    facts.setdefault("embedding", _EMBED_UNKNOWN)
    facts.setdefault("embeddable", False)
    facts.setdefault("no_subset", False)

    result = FontFacts(
        container=facts["container"],
        sfnt_flavor=facts["sfnt_flavor"],
        raw_size=facts["raw_size"],
        num_tables=facts["num_tables"],
        table_tags=facts["table_tags"],
        declared_sfnt_size=facts["declared_sfnt_size"],
        family_name=facts.get("family_name"),
        subfamily_name=facts.get("subfamily_name"),
        full_name=facts.get("full_name"),
        is_variable=bool(facts.get("is_variable")),
        glyph_count=facts.get("glyph_count"),
        weight=facts.get("weight"),
        style=facts.get("style"),
        embedding=facts["embedding"],
        embeddable=bool(facts["embeddable"]),
        no_subset=bool(facts["no_subset"]),
    )
    return result


# --------------------------------------------------------------------------- #
# Subsetting + WOFF2 emission (needs fontTools + brotli)
# --------------------------------------------------------------------------- #
def default_unicodes() -> set[int]:
    """The Latin codepoints MediaHub subsets to, parsed from
    :data:`DEFAULT_UNICODE_RANGES`."""
    return _parse_unicode_ranges(DEFAULT_UNICODE_RANGES)


def _parse_unicode_ranges(spec: str) -> set[int]:
    """Parse a CSS ``unicode-range``-style spec into a set of codepoints."""
    out: set[int] = set()
    for token in spec.split(","):
        token = token.strip().upper().removeprefix("U+")
        if not token:
            continue
        if "-" in token:
            lo, hi = token.split("-", 1)
            out.update(range(int(lo, 16), int(hi, 16) + 1))
        else:
            out.add(int(token, 16))
    return out


def subset_to_woff2(
    data: bytes,
    *,
    unicodes: Optional[Iterable[int]] = None,
    do_subset: bool = True,
) -> bytes:
    """Subset ``data`` to ``unicodes`` (default Latin) and return WOFF2 bytes.

    Deterministic: the same input yields byte-identical output (timestamp recalc
    off, glyph names dropped), so the hash is a stable cache key. Raises
    :class:`FontToolingUnavailable` when fontTools/brotli are missing and
    :class:`FontValidationError` if the font fails to parse/subset.
    """
    _require_tooling()
    from io import BytesIO
    from fontTools.ttLib import TTFont
    from fontTools import subset as ft_subset

    try:
        font = TTFont(BytesIO(data), fontNumber=0, lazy=True)
    except Exception as exc:
        raise FontValidationError(f"font failed to parse under fontTools: {exc}") from exc

    if do_subset:
        opts = ft_subset.Options()
        opts.recalc_timestamp = False  # deterministic output
        opts.glyph_names = False  # drop 'post' glyph names (smaller)
        opts.name_legacy = True
        opts.notdef_outline = True  # keep the .notdef box for unsupported chars
        opts.layout_features = ["*"]  # keep kerning/ligatures (G1.11 needs them)
        codepoints = set(unicodes) if unicodes is not None else default_unicodes()
        subsetter = ft_subset.Subsetter(options=opts)
        subsetter.populate(unicodes=codepoints)
        try:
            subsetter.subset(font)
        except Exception as exc:
            raise FontValidationError(f"subsetting failed: {exc}") from exc

    # Drop non-deterministic / privacy-bloat metadata tables either way.
    for tag in ("FFTM",):  # FontForge timestamp table
        if tag in font:
            del font[tag]

    font.flavor = "woff2"
    out = BytesIO()
    try:
        font.save(out)
    except Exception as exc:  # brotli missing / encode failure
        raise FontToolingUnavailable(f"WOFF2 encode failed (is brotli installed?): {exc}") from exc
    font.close()
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Family / slug sanitisation
# --------------------------------------------------------------------------- #
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")


def sanitise_family(name: Optional[str]) -> str:
    """Clean a human family name: strip control chars, collapse whitespace, cap
    length. Returns ``""`` when nothing usable remains."""
    if not name:
        return ""
    cleaned = _CONTROL_RE.sub(" ", name)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned[:80]


def _slug(value: str) -> str:
    """Lowercase, ASCII, hyphenated filesystem-safe slug."""
    s = _CONTROL_RE.sub("", value or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "font"


def css_family_for(profile_id: str, family: str) -> str:
    """A collision-safe, per-tenant CSS ``font-family`` identifier.

    Built from slugs (lowercase/ASCII/hyphen) so it can never collide with a
    built-in family ("Inter", "Anton", …) or another tenant's font, and needs no
    CSS-string escaping — the arbitrary human name never enters the stylesheet.
    """
    return f"club-{_slug(profile_id)}-{_slug(family)}"


# --------------------------------------------------------------------------- #
# First-party storage (under DATA_DIR)
# --------------------------------------------------------------------------- #
def _data_dir() -> Path:
    """Resolve DATA_DIR, matching ``web/web.py`` (env var, else ``src/mediahub``)."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    # src/mediahub/typography/font_intake.py → parents[1] == src/mediahub
    return Path(__file__).resolve().parents[1]


def font_dir_for(profile_id: str) -> Path:
    """The per-profile custom-font directory, created on demand."""
    p = _data_dir() / "custom_fonts" / _slug(profile_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_woff2(profile_id: str, *, slug: str, woff2: bytes, record_fields: dict) -> FontRecord:
    """Write the WOFF2 + JSON sidecar; return the persisted :class:`FontRecord`."""
    d = font_dir_for(profile_id)
    woff2_path = d / f"{slug}.woff2"
    woff2_path.write_bytes(woff2)
    rec = FontRecord(
        profile_id=profile_id,
        slug=slug,
        woff2_path=str(woff2_path),
        woff2_size=len(woff2),
        **record_fields,
    )
    (d / f"{slug}.json").write_text(json.dumps(rec.to_dict(), indent=2), encoding="utf-8")
    return rec


def load_record(profile_id: str, slug: str) -> Optional[FontRecord]:
    """Load one stored font record by slug, or ``None`` if absent."""
    p = font_dir_for(profile_id) / f"{slug}.json"
    if not p.is_file():
        return None
    try:
        return FontRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_fonts(profile_id: str) -> list[FontRecord]:
    """Every stored custom font for a profile, sorted by family/weight/style."""
    d = font_dir_for(profile_id)
    records: list[FontRecord] = []
    for p in sorted(d.glob("*.json")):
        try:
            rec = FontRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
        # Only surface records whose WOFF2 is actually on disk.
        if Path(rec.woff2_path).is_file():
            records.append(rec)
    records.sort(key=lambda r: (r.family.lower(), r.weight, r.style))
    return records


def remove_font(profile_id: str, slug: str) -> bool:
    """Delete a stored font (WOFF2 + sidecar). Returns True if anything was removed."""
    d = font_dir_for(profile_id)
    removed = False
    for suffix in (".woff2", ".json"):
        p = d / f"{slug}{suffix}"
        if p.is_file():
            p.unlink()
            removed = True
    return removed


# --------------------------------------------------------------------------- #
# CSS emission
# --------------------------------------------------------------------------- #
def font_face_css(
    records: Union[FontRecord, Iterable[FontRecord]],
    *,
    file_uri: bool = False,
) -> str:
    """Emit the ``@font-face`` CSS for one or many records (first-party only)."""
    if isinstance(records, FontRecord):
        records = [records]
    return "\n".join(rec.font_face(file_uri=file_uri) for rec in records)


# --------------------------------------------------------------------------- #
# Top-level orchestrator
# --------------------------------------------------------------------------- #
def intake_font(
    data: bytes,
    *,
    profile_id: str,
    role: str = "display",
    family: Optional[str] = None,
    weight: Optional[int] = None,
    style: Optional[str] = None,
    allow_restricted: bool = False,
    subset: bool = True,
    unicodes: Optional[Iterable[int]] = None,
) -> FontRecord:
    """Validate → subset → self-host an uploaded font; return its record.

    Parameters
    ----------
    data : the raw uploaded bytes (TTF/OTF/WOFF/WOFF2).
    profile_id : the owning club/tenant id (scopes storage + the CSS family).
    role : where the font slots in the renderer (see :data:`ALLOWED_ROLES`).
    family / weight / style : optional overrides for the detected metadata.
    allow_restricted : process even a foundry-restricted font (operator override
        for a font the club owns the licence to). Default ``False`` → rejected.
    subset : subset to ``unicodes`` (default) or convert without subsetting. A
        font whose licence forbids subsetting is always converted without it.
    """
    if not profile_id or not str(profile_id).strip():
        raise FontValidationError("a profile_id is required to scope the stored font")
    if role not in ALLOWED_ROLES:
        raise FontValidationError(f"unknown role {role!r}; expected one of {ALLOWED_ROLES}")

    facts = validate_font_bytes(data)

    if facts.embedding == _EMBED_RESTRICTED and not allow_restricted:
        raise FontEmbeddingNotPermitted(
            "this font's licence (OS/2 fsType) forbids embedding; upload one you "
            "are licensed to embed, or set allow_restricted=True if you own that licence"
        )

    human = sanitise_family(family) or sanitise_family(facts.family_name) or ""
    if not human:
        raise FontValidationError("could not determine a usable family name for this font")

    resolved_weight = int(weight) if weight else (facts.weight or 400)
    if not (1 <= resolved_weight <= 1000):
        raise FontValidationError(f"implausible font weight: {resolved_weight}")
    resolved_style = (style or facts.style or "normal").lower()
    if resolved_style not in ("normal", "italic"):
        resolved_style = "normal"

    family_slug = _slug(human)
    slug = f"{family_slug}-{resolved_weight}-{resolved_style}"
    css_family = css_family_for(profile_id, human)

    do_subset = bool(subset) and not facts.no_subset
    unicode_set = set(unicodes) if unicodes is not None else default_unicodes()
    woff2 = subset_to_woff2(data, unicodes=unicode_set, do_subset=do_subset)
    sha = hashlib.sha256(woff2).hexdigest()

    return store_woff2(
        profile_id,
        slug=slug,
        woff2=woff2,
        record_fields={
            "family": human,
            "css_family": css_family,
            "role": role,
            "weight": resolved_weight,
            "style": resolved_style,
            "original_size": len(data),
            "sha256": sha,
            "unicode_range": DEFAULT_UNICODE_RANGES,
            "subsetted": do_subset,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "facts": facts.to_dict(),
        },
    )


__all__ = [
    # exceptions
    "FontIntakeError",
    "FontValidationError",
    "FontEmbeddingNotPermitted",
    "FontToolingUnavailable",
    # data structures
    "FontFacts",
    "FontRecord",
    # validation / sandbox
    "sniff_container",
    "structural_scan",
    "validate_font_bytes",
    "classify_embedding",
    "is_font_tooling_available",
    # processing
    "subset_to_woff2",
    "default_unicodes",
    # storage
    "font_dir_for",
    "store_woff2",
    "load_record",
    "list_fonts",
    "remove_font",
    # css + sanitisation
    "font_face_css",
    "sanitise_family",
    "css_family_for",
    # orchestrator
    "intake_font",
    # constants
    "DEFAULT_UNICODE_RANGES",
    "ALLOWED_ROLES",
    "MAX_UPLOAD_BYTES",
    "MAX_DECOMPRESSED_BYTES",
    "MAX_TABLES",
]
