"""graphic_renderer.metadata_embed — EXIF/IPTC + photographer attribution (roadmap G1.16).

Embeds standards-compliant provenance metadata into an exported card so the
picture carries its own credit line wherever it travels: who shot the photo,
who owns the copyright, what it depicts, and that MediaHub rendered it. A club
posts a card, a journalist or sponsor right-clicks → "Get Info", and the
photographer is named and the licence is honest — attribution survives the
re-share that strips a visible caption.

Why this matters for MediaHub
-----------------------------
The product's whole moat is provenance and explainability (CLAUDE.md). A
rendered PNG is the one artifact that leaves the building, so it should be the
one place the credit chain is *self-describing*: the ``MediaAsset`` already
tracks ``photographer`` / ``source_attribution`` / ``source_licence`` /
``source_url``, and this module writes those facts into the file the club
actually publishes.

Design notes
------------
- **Lossless, never a re-encode.** The renderer downsamples with Lanczos to land
  exact pixels — "the same card always comes out the same way". So we do *not*
  re-save through Pillow (which would recompress and change the bytes). Instead
  we splice ancillary metadata into the existing byte stream: PNG ``tEXt`` /
  ``iTXt`` / ``eXIf`` chunks inserted after ``IHDR``; JPEG ``APP1`` (EXIF + XMP)
  segments inserted after ``SOI``. The compressed image data is untouched.
- **Deterministic.** The same :class:`ImageMetadata` always produces the same
  bytes — no ``datetime.now()`` stamp creeps in (a create-date is embedded only
  when the caller supplies one). Re-embedding is idempotent: existing managed
  chunks/segments are dropped before the fresh ones are written.
- **Three carriers, by design.** Standard EXIF ASCII tags (Artist/Copyright/…)
  for maximum reader compatibility; EXIF ``XP*`` tags + an XMP packet for full
  Unicode and the richer IPTC Core fields (creator, credit, source, usage
  terms). Pro tools read XMP first; basic viewers fall back to EXIF/PNG text.
- **Honest + safe.** Only fields backed by real data are written — no empty
  credit lines. Every interpolated value is XML-escaped before it enters the
  XMP packet, so caption/photographer text can never break the RDF or inject
  markup.

Public API
----------
- :class:`ImageMetadata` — the embeddable field set (+ ``to_dict`` / ``from_dict``).
- :func:`metadata_from_brief` / :func:`metadata_from_asset` — build the metadata
  from a ``CreativeBrief`` and/or a ``MediaAsset`` (the photo's provenance).
- :func:`embed_metadata` — write EXIF/IPTC into a PNG or JPEG (in place or to a
  new path); :func:`embed_png` / :func:`embed_jpeg` are the explicit variants.
- :func:`read_metadata` — read it back (round-trip verification / audit).
- :func:`build_xmp_packet` — the deterministic XMP RDF/XML packet (exposed for
  tests and callers that embed elsewhere).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Pillow is a hard dependency of the renderer already; EXIF assembly needs it.
try:  # pragma: no cover - exercised indirectly everywhere
    from PIL import ExifTags, Image
except Exception:  # pragma: no cover - environment-dependent
    Image = None  # type: ignore
    ExifTags = None  # type: ignore


__all__ = [
    "ImageMetadata",
    "UnsupportedImageFormat",
    "embed_metadata",
    "embed_png",
    "embed_jpeg",
    "read_metadata",
    "metadata_from_brief",
    "metadata_from_asset",
    "metadata_for_generated",
    "build_xmp_packet",
    "SOFTWARE_NAME",
    "DIGITAL_SOURCE_TYPES",
]

# The CreatorTool / Software string stamped on every export. Not the model id —
# this is product provenance the customer is happy to carry.
SOFTWARE_NAME = "MediaHub"

# IPTC "Digital Source Type" controlled-vocabulary URIs — the standards-based way
# to declare that an image was made (or composited) with generative AI. Pro
# tooling, platforms and journalists read this property to label synthetic media.
# This is MediaHub's provenance stamp for P6.3 generative imagery (the C2PA-class
# "this was AI-generated" signal), carried losslessly in the XMP packet.
DIGITAL_SOURCE_TYPES = {
    # A straight digital photograph — no AI involvement.
    "digital_capture": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
    # Created wholesale by a generative model (text-to-image).
    "ai_generated": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
    # A real image with AI-generated elements added/edited in (edit/expand/remove).
    "ai_composite": (
        "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
    ),
}

# Canonical xpacket id (the constant Adobe uses); keeps the XMP wrapper stable.
_XPACKET_ID = "W5M0MpCehiHzreSzNTczkc9d"

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8"
_XMP_NS_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
_EXIF_APP1_HEADER = b"Exif\x00\x00"
# 2-byte JPEG segment length field caps a single APP1 at 65533 payload bytes.
_JPEG_SEG_MAX = 0xFFFF - 2


class UnsupportedImageFormat(ValueError):
    """Raised when asked to embed into something that is not a PNG or JPEG."""


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass
class ImageMetadata:
    """The provenance/credit fields embedded into an exported image.

    Every field is optional; only the populated ones are written. ``creator``
    is the photographer (IPTC/EXIF "Creator"/"Artist"); ``credit`` is the
    publisher credit line (the club); ``source`` is where the photo originally
    came from. ``create_date`` is an ISO-8601 string and is embedded verbatim
    — leave it empty to keep the output deterministic.
    """

    title: str = ""
    description: str = ""  # caption / what the picture shows
    creator: str = ""  # photographer — EXIF Artist / dc:creator
    copyright: str = ""  # rights statement — EXIF Copyright / dc:rights
    credit: str = ""  # IPTC Credit line (the publishing club)
    source: str = ""  # IPTC Source — original owner / origin URL
    headline: str = ""  # IPTC Headline — the achievement, short
    keywords: list[str] = field(default_factory=list)
    licence: str = ""  # rights-usage terms — xmpRights:UsageTerms
    web_statement: str = ""  # licence/source URL — xmpRights:WebStatement
    rights_marked: Optional[bool] = None  # xmpRights:Marked (True = rights-managed)
    software: str = SOFTWARE_NAME  # EXIF Software / xmp:CreatorTool
    create_date: str = ""  # ISO-8601; embedded only when supplied
    # IPTC DigitalSourceType — either a key of DIGITAL_SOURCE_TYPES (e.g.
    # "ai_generated") or a full controlled-vocabulary URI. Empty = not declared.
    digital_source_type: str = ""

    def is_empty(self) -> bool:
        """True when there is nothing worth embedding beyond the software tag."""
        return not any(
            (
                self.title.strip(),
                self.description.strip(),
                self.creator.strip(),
                self.copyright.strip(),
                self.credit.strip(),
                self.source.strip(),
                self.headline.strip(),
                [k for k in self.keywords if k and k.strip()],
                self.licence.strip(),
                self.web_statement.strip(),
                self.create_date.strip(),
                self.digital_source_type.strip(),
            )
        )

    def digital_source_uri(self) -> str:
        """Resolve ``digital_source_type`` to its controlled-vocabulary URI.

        Accepts either a short key (``"ai_generated"``) or an already-resolved
        URI; returns ``""`` when nothing is declared.
        """
        v = (self.digital_source_type or "").strip()
        if not v:
            return ""
        return DIGITAL_SOURCE_TYPES.get(v, v)

    def clean_keywords(self) -> list[str]:
        """De-duplicated, order-preserving, whitespace-trimmed keyword list."""
        return _dedupe_keywords(self.keywords)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ImageMetadata":
        if not isinstance(data, dict):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        kw = clean.get("keywords")
        if isinstance(kw, str):
            clean["keywords"] = [s.strip() for s in kw.split(",") if s.strip()]
        return cls(**clean)


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------


def _dedupe_keywords(values: Any) -> list[str]:
    """De-duplicated (case-insensitive), order-preserving, trimmed keyword list."""
    seen: set[str] = set()
    out: list[str] = []
    for k in values or []:
        t = (str(k) if k is not None else "").strip()
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _xml_escape(value: Any) -> str:
    """Escape for XML element text AND attributes (covers ``'`` and ``"``)."""
    s = "" if value is None else str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ---------------------------------------------------------------------------
# XMP packet (IPTC Core via XMP) — deterministic RDF/XML
# ---------------------------------------------------------------------------


def _alt(tag: str, value: str) -> str:
    """A localised ``rdf:Alt`` property (dc:title, dc:rights, …)."""
    return (
        f'   <{tag}><rdf:Alt><rdf:li xml:lang="x-default">'
        f"{_xml_escape(value)}</rdf:li></rdf:Alt></{tag}>\n"
    )


def _seq(tag: str, values: list[str]) -> str:
    """An ordered ``rdf:Seq`` property (dc:creator)."""
    items = "".join(f"<rdf:li>{_xml_escape(v)}</rdf:li>" for v in values)
    return f"   <{tag}><rdf:Seq>{items}</rdf:Seq></{tag}>\n"


def _bag(tag: str, values: list[str]) -> str:
    """An unordered ``rdf:Bag`` property (dc:subject / keywords)."""
    items = "".join(f"<rdf:li>{_xml_escape(v)}</rdf:li>" for v in values)
    return f"   <{tag}><rdf:Bag>{items}</rdf:Bag></{tag}>\n"


def _simple(tag: str, value: str) -> str:
    """A simple text property (photoshop:Credit, xmp:CreatorTool, …)."""
    return f"   <{tag}>{_xml_escape(value)}</{tag}>\n"


def build_xmp_packet(meta: ImageMetadata) -> str:
    """Build the deterministic XMP packet carrying the IPTC Core fields.

    Only populated fields emit a property, in a fixed order, so identical
    metadata always serialises to identical bytes.
    """
    body: list[str] = []
    if meta.title.strip():
        body.append(_alt("dc:title", meta.title.strip()))
    if meta.description.strip():
        body.append(_alt("dc:description", meta.description.strip()))
    if meta.creator.strip():
        body.append(_seq("dc:creator", [meta.creator.strip()]))
    if meta.copyright.strip():
        body.append(_alt("dc:rights", meta.copyright.strip()))
    kws = meta.clean_keywords()
    if kws:
        body.append(_bag("dc:subject", kws))
    if meta.headline.strip():
        body.append(_simple("photoshop:Headline", meta.headline.strip()))
    if meta.credit.strip():
        body.append(_simple("photoshop:Credit", meta.credit.strip()))
    if meta.source.strip():
        body.append(_simple("photoshop:Source", meta.source.strip()))
    if meta.software.strip():
        body.append(_simple("xmp:CreatorTool", meta.software.strip()))
    if meta.create_date.strip():
        body.append(_simple("xmp:CreateDate", meta.create_date.strip()))
    if meta.licence.strip():
        body.append(_alt("xmpRights:UsageTerms", meta.licence.strip()))
    if meta.web_statement.strip():
        body.append(_simple("xmpRights:WebStatement", meta.web_statement.strip()))
    if meta.rights_marked is not None:
        body.append(_simple("xmpRights:Marked", "True" if meta.rights_marked else "False"))
    ds_uri = meta.digital_source_uri()
    if ds_uri:
        body.append(_simple("Iptc4xmpExt:DigitalSourceType", ds_uri))

    return (
        f'<?xpacket begin="﻿" id="{_XPACKET_ID}"?>\n'
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="{_xml_escape(SOFTWARE_NAME)}">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"\n'
        '    xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"\n'
        '    xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/">\n'
        f"{''.join(body)}"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )


# ---------------------------------------------------------------------------
# EXIF assembly
# ---------------------------------------------------------------------------


def _exif_datetime(iso: str) -> str:
    """ISO-8601 → EXIF ``YYYY:MM:DD HH:MM:SS`` (best-effort; '' if unparseable)."""
    s = (iso or "").strip()
    if not s:
        return ""
    from datetime import datetime

    # Drop a trailing timezone / fractional seconds, then try the common shapes.
    cleaned = s.replace("Z", "").split(".")[0].split("+")[0].strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y:%m:%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned).strftime("%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _xp(value: str) -> bytes:
    """Windows XP* EXIF tag encoding: UTF-16-LE, NUL-terminated."""
    return value.encode("utf-16-le") + b"\x00\x00"


def build_exif(meta: ImageMetadata) -> Optional[bytes]:
    """Assemble the EXIF block (``Exif\\x00\\x00`` + TIFF). ``None`` if empty.

    Standard ASCII tags carry maximum compatibility; the ``XP*`` tags carry the
    same values in full Unicode for readers that honour them.
    """
    if Image is None or ExifTags is None:  # pragma: no cover - env without Pillow
        return None
    exif = Image.Exif()
    B = ExifTags.Base
    if meta.creator.strip():
        exif[B.Artist] = meta.creator.strip()
        exif[B.XPAuthor] = _xp(meta.creator.strip())
    if meta.copyright.strip():
        exif[B.Copyright] = meta.copyright.strip()
    if meta.description.strip():
        exif[B.ImageDescription] = meta.description.strip()
        exif[B.XPComment] = _xp(meta.description.strip())
    if meta.title.strip():
        exif[B.XPTitle] = _xp(meta.title.strip())
    if meta.software.strip():
        exif[B.Software] = meta.software.strip()
    kws = meta.clean_keywords()
    if kws:
        # Windows convention: semicolon-separated keyword string.
        exif[B.XPKeywords] = _xp(";".join(kws))
    dt = _exif_datetime(meta.create_date)
    if dt:
        exif[B.DateTime] = dt
    if not dict(exif):
        return None
    return exif.tobytes()


# ---------------------------------------------------------------------------
# PNG chunk surgery (lossless)
# ---------------------------------------------------------------------------

# tEXt / iTXt keywords this module owns — dropped before re-writing so a second
# embed is idempotent rather than additive.
_MANAGED_PNG_KEYWORDS = {
    b"Title",
    b"Author",
    b"Description",
    b"Copyright",
    b"Software",
    b"Source",
    b"Comment",
    b"Creation Time",
    b"XML:com.adobe.xmp",
}


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def _iter_png_chunks(raw: bytes):
    """Yield ``(ctype, data, raw_chunk_bytes)`` for a PNG byte stream."""
    if raw[:8] != _PNG_SIG:
        raise UnsupportedImageFormat("not a PNG (bad signature)")
    pos = 8
    n = len(raw)
    while pos + 8 <= n:
        (length,) = struct.unpack(">I", raw[pos : pos + 4])
        ctype = raw[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > n:
            break
        yield ctype, raw[pos + 8 : pos + 8 + length], raw[pos:end]
        pos = end


def _text_chunk(keyword: str, text: str) -> bytes:
    """A ``tEXt`` chunk for Latin-1 text, else an uncompressed UTF-8 ``iTXt``."""
    try:
        kw = keyword.encode("latin-1")
        body = text.encode("latin-1")
        return _png_chunk(b"tEXt", kw + b"\x00" + body)
    except UnicodeEncodeError:
        return _itxt_chunk(keyword, text)


def _itxt_chunk(keyword: str, text: str) -> bytes:
    """An uncompressed UTF-8 ``iTXt`` chunk (required form for XMP)."""
    kw = keyword.encode("utf-8")
    # keyword \0 compression-flag(0) compression-method(0) lang \0 trans-kw \0 text
    data = kw + b"\x00" + b"\x00" + b"\x00" + b"\x00" + b"\x00" + text.encode("utf-8")
    return _png_chunk(b"iTXt", data)


def _png_metadata_chunks(meta: ImageMetadata) -> list[bytes]:
    chunks: list[bytes] = []
    pairs = [
        ("Title", meta.title),
        ("Author", meta.creator),
        ("Description", meta.description),
        ("Copyright", meta.copyright),
        ("Source", meta.source or meta.web_statement),
        ("Comment", meta.credit),
        ("Software", meta.software),
        ("Creation Time", meta.create_date),
    ]
    for keyword, value in pairs:
        v = (value or "").strip()
        if v:
            chunks.append(_text_chunk(keyword, v))
    xmp = build_xmp_packet(meta)
    chunks.append(_itxt_chunk("XML:com.adobe.xmp", xmp))
    exif_bytes = build_exif(meta)
    if exif_bytes:
        # PNG eXIf chunk data is the bare TIFF blob — strip the JPEG-only
        # "Exif\0\0" prefix that Exif.tobytes() prepends.
        tiff = exif_bytes[6:] if exif_bytes[:6] == _EXIF_APP1_HEADER else exif_bytes
        chunks.append(_png_chunk(b"eXIf", tiff))
    return chunks


def _embed_png_bytes(raw: bytes, meta: ImageMetadata) -> bytes:
    """Return the PNG bytes with metadata chunks spliced in after ``IHDR``."""
    out: list[bytes] = [_PNG_SIG]
    iend: Optional[bytes] = None
    inserted = False
    new_chunks = _png_metadata_chunks(meta)
    for ctype, data, chunk in _iter_png_chunks(raw):
        if ctype == b"IEND":
            iend = chunk
            continue
        # Drop our own previously-written chunks so re-embed is idempotent.
        if ctype == b"eXIf":
            continue
        if ctype in (b"tEXt", b"iTXt"):
            keyword = data.split(b"\x00", 1)[0]
            if keyword in _MANAGED_PNG_KEYWORDS:
                continue
        out.append(chunk)
        if ctype == b"IHDR" and not inserted:
            out.extend(new_chunks)
            inserted = True
    if not inserted:
        # No IHDR: not a real PNG stream. Refuse honestly rather than
        # fabricate chunks around bytes we don't understand — the caller
        # keeps the original file untouched.
        raise UnsupportedImageFormat("malformed PNG (no IHDR chunk) — refusing to embed")
    out.append(iend if iend is not None else _png_chunk(b"IEND", b""))
    return b"".join(out)


# ---------------------------------------------------------------------------
# JPEG segment surgery (lossless)
# ---------------------------------------------------------------------------


def _iter_jpeg_segments(raw: bytes):
    """Yield ``(marker, raw_segment_bytes)`` for a JPEG byte stream.

    Stops handing back length-prefixed segments at SOS — the entropy-coded scan
    (and EOI) is returned as one trailing ``(0xDA, ...)`` block.
    """
    if raw[:2] != _JPEG_SOI:
        raise UnsupportedImageFormat("not a JPEG (bad SOI)")
    pos = 2
    n = len(raw)
    while pos + 1 < n:
        if raw[pos] != 0xFF:
            break
        # Skip fill bytes (a run of 0xFF is legal padding before a marker).
        while pos + 1 < n and raw[pos + 1] == 0xFF:
            pos += 1
        if pos + 1 >= n:
            break
        marker = raw[pos + 1]
        if marker == 0xDA:  # SOS — rest of the file is the scan + EOI
            yield marker, raw[pos:]
            return
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # standalone (TEM / RSTn)
            yield marker, raw[pos : pos + 2]
            pos += 2
            continue
        if pos + 4 > n:
            break
        (length,) = struct.unpack(">H", raw[pos + 2 : pos + 4])
        end = pos + 2 + length
        if end > n:
            break
        yield marker, raw[pos:end]
        pos = end


def _is_managed_app1(seg: bytes) -> bool:
    """True for an APP1 segment we own (EXIF or XMP) — dropped before re-write."""
    payload = seg[4:]  # past FFE1 + 2-byte length
    return payload.startswith(_EXIF_APP1_HEADER) or payload.startswith(_XMP_NS_HEADER)


def _app1_segment(payload: bytes) -> bytes:
    if len(payload) > _JPEG_SEG_MAX:
        raise ValueError("APP1 payload exceeds the 64KB JPEG segment limit")
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _jpeg_metadata_segments(meta: ImageMetadata) -> list[bytes]:
    segs: list[bytes] = []
    exif_bytes = build_exif(meta)
    if exif_bytes:
        # Exif.tobytes() already carries the "Exif\0\0" APP1 header.
        segs.append(_app1_segment(exif_bytes))
    xmp = build_xmp_packet(meta).encode("utf-8")
    payload = _XMP_NS_HEADER + xmp
    if len(payload) <= _JPEG_SEG_MAX:
        segs.append(_app1_segment(payload))
    return segs


def _embed_jpeg_bytes(raw: bytes, meta: ImageMetadata) -> bytes:
    """Return the JPEG bytes with EXIF + XMP APP1 segments spliced after SOI."""
    kept = [
        (m, b) for (m, b) in _iter_jpeg_segments(raw) if not (m == 0xE1 and _is_managed_app1(b))
    ]
    new_segs = _jpeg_metadata_segments(meta)
    body: list[bytes] = []
    i = 0
    # Conventionally APP0 (JFIF) leads; keep it ahead of our APP1 segments.
    while i < len(kept) and kept[i][0] == 0xE0:
        body.append(kept[i][1])
        i += 1
    body.extend(new_segs)
    body.extend(seg for _, seg in kept[i:])
    return _JPEG_SOI + b"".join(body)


# ---------------------------------------------------------------------------
# Public embed / read API
# ---------------------------------------------------------------------------


def _sniff_format(raw: bytes, path: Path) -> str:
    if raw[:8] == _PNG_SIG:
        return "png"
    if raw[:2] == _JPEG_SOI:
        return "jpeg"
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "png"
    if suffix in (".jpg", ".jpeg"):
        return "jpeg"
    raise UnsupportedImageFormat(
        f"metadata_embed supports PNG and JPEG only (got {suffix or 'unknown bytes'})"
    )


def embed_metadata(
    image_path: str | Path,
    meta: ImageMetadata,
    *,
    output_path: Optional[str | Path] = None,
) -> Path:
    """Embed ``meta`` into the PNG/JPEG at ``image_path`` (lossless).

    Writes to ``output_path`` when given, otherwise overwrites in place. The
    image pixels are never re-encoded — only ancillary metadata is spliced in.
    Returns the written path.
    """
    src = Path(image_path)
    raw = src.read_bytes()
    fmt = _sniff_format(raw, src)
    if fmt == "png":
        new = _embed_png_bytes(raw, meta)
    else:
        new = _embed_jpeg_bytes(raw, meta)
    dst = Path(output_path) if output_path is not None else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(new)
    return dst


def embed_png(
    image_path: str | Path, meta: ImageMetadata, *, output_path: Optional[str | Path] = None
) -> Path:
    """Embed into a PNG specifically (raises if the file is not a PNG)."""
    src = Path(image_path)
    raw = src.read_bytes()
    if _sniff_format(raw, src) != "png":
        raise UnsupportedImageFormat("embed_png called on a non-PNG file")
    dst = Path(output_path) if output_path is not None else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(_embed_png_bytes(raw, meta))
    return dst


def embed_jpeg(
    image_path: str | Path, meta: ImageMetadata, *, output_path: Optional[str | Path] = None
) -> Path:
    """Embed into a JPEG specifically (raises if the file is not a JPEG)."""
    src = Path(image_path)
    raw = src.read_bytes()
    if _sniff_format(raw, src) != "jpeg":
        raise UnsupportedImageFormat("embed_jpeg called on a non-JPEG file")
    dst = Path(output_path) if output_path is not None else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(_embed_jpeg_bytes(raw, meta))
    return dst


def _parse_xmp_field(xmp: str, tag: str) -> str:
    import re

    m = re.search(rf"<{tag}>(.*?)</{tag}>", xmp, re.DOTALL)
    if not m:
        return ""
    inner = m.group(1)
    li = re.search(r"<rdf:li[^>]*>(.*?)</rdf:li>", inner, re.DOTALL)
    raw = (li.group(1) if li else inner).strip()
    return (
        raw.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&amp;", "&")
    )


def read_metadata(image_path: str | Path) -> ImageMetadata:
    """Read embedded metadata back out (best-effort), for verification/audit.

    Prefers the full-Unicode XMP packet, falling back to EXIF and PNG text
    chunks. Returns an empty :class:`ImageMetadata` if nothing is present.
    """
    if Image is None:  # pragma: no cover - env without Pillow
        return ImageMetadata()
    src = Path(image_path)
    meta = ImageMetadata(software="")
    with Image.open(src) as img:
        info = dict(getattr(img, "info", {}) or {})
        xmp_raw = info.get("xmp") or info.get("XML:com.adobe.xmp") or b""
        if isinstance(xmp_raw, bytes):
            xmp_raw = xmp_raw.decode("utf-8", "ignore")
        try:
            exif = img.getexif()
        except Exception:
            exif = {}

    if xmp_raw:
        meta.title = _parse_xmp_field(xmp_raw, "dc:title") or meta.title
        meta.description = _parse_xmp_field(xmp_raw, "dc:description") or meta.description
        meta.creator = _parse_xmp_field(xmp_raw, "dc:creator") or meta.creator
        meta.copyright = _parse_xmp_field(xmp_raw, "dc:rights") or meta.copyright
        meta.headline = _parse_xmp_field(xmp_raw, "photoshop:Headline") or meta.headline
        meta.credit = _parse_xmp_field(xmp_raw, "photoshop:Credit") or meta.credit
        meta.source = _parse_xmp_field(xmp_raw, "photoshop:Source") or meta.source
        meta.software = _parse_xmp_field(xmp_raw, "xmp:CreatorTool") or meta.software
        meta.create_date = _parse_xmp_field(xmp_raw, "xmp:CreateDate") or meta.create_date
        meta.licence = _parse_xmp_field(xmp_raw, "xmpRights:UsageTerms") or meta.licence
        meta.web_statement = (
            _parse_xmp_field(xmp_raw, "xmpRights:WebStatement") or meta.web_statement
        )
        meta.digital_source_type = (
            _parse_xmp_field(xmp_raw, "Iptc4xmpExt:DigitalSourceType") or meta.digital_source_type
        )
        import re as _re

        kw_block = _re.search(r"<dc:subject>(.*?)</dc:subject>", xmp_raw, _re.DOTALL)
        if kw_block:
            meta.keywords = [
                k.strip()
                for k in _re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", kw_block.group(1), _re.DOTALL)
                if k.strip()
            ]

    if ExifTags is not None and exif:
        B = ExifTags.Base

        def _g(tag) -> str:
            v = exif.get(tag)
            return v.strip() if isinstance(v, str) else ""

        meta.creator = meta.creator or _g(B.Artist)
        meta.copyright = meta.copyright or _g(B.Copyright)
        meta.description = meta.description or _g(B.ImageDescription)
        meta.software = meta.software or _g(B.Software)

    # PNG text-chunk fallbacks (info keys are the keywords we wrote).
    meta.title = meta.title or (info.get("Title") or "").strip()
    meta.creator = meta.creator or (info.get("Author") or "").strip()
    meta.description = meta.description or (info.get("Description") or "").strip()
    meta.copyright = meta.copyright or (info.get("Copyright") or "").strip()
    meta.source = meta.source or (info.get("Source") or "").strip()
    meta.credit = meta.credit or (info.get("Comment") or "").strip()
    meta.software = meta.software or (info.get("Software") or "").strip()
    return meta


# ---------------------------------------------------------------------------
# Builders — turn product data into ImageMetadata
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = "") -> Any:
    """Read ``key`` from an object (attr) or mapping (item), with a default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        val = obj.get(key, default)
    else:
        val = getattr(obj, key, default)
    return default if val is None else val


def _photographer_from_asset(asset: Any) -> str:
    """Best photographer string from a MediaAsset: explicit field, else parsed."""
    explicit = str(_get(asset, "photographer", "")).strip()
    if explicit:
        return explicit
    # source_attribution often reads "Photo by Jane Doe / CC BY 4.0" — take the
    # human name, dropping a "Photo by"/"©" lead-in and any "/ licence" tail.
    attribution = str(_get(asset, "source_attribution", "")).strip()
    if not attribution:
        return ""
    name = attribution.split("/")[0].strip()
    for lead in ("photo by ", "photograph by ", "image by ", "© ", "(c) "):
        if name.lower().startswith(lead):
            name = name[len(lead) :].strip()
    return name


def metadata_from_asset(asset: Any) -> ImageMetadata:
    """Build photo-provenance metadata from a ``MediaAsset`` (or dict).

    Pulls the photographer, source, licence and origin URL only — the credit
    chain the asset itself carries. Combine with :func:`metadata_from_brief`
    for the full card-level metadata.
    """
    photographer = _photographer_from_asset(asset)
    source_url = str(_get(asset, "source_url", "")).strip()
    attribution = str(_get(asset, "source_attribution", "")).strip()
    licence = str(_get(asset, "source_licence", "")).strip()
    return ImageMetadata(
        creator=photographer,
        source=attribution or source_url,
        licence=licence,
        web_statement=source_url,
        rights_marked=True if (licence or photographer) else None,
    )


def metadata_for_generated(
    operation: str,
    *,
    model: str = "",
    description: str = "",
    base: Optional[ImageMetadata] = None,
) -> ImageMetadata:
    """Build provenance metadata for an AI-generated / AI-edited image (P6.3).

    Sets the IPTC ``DigitalSourceType`` so the file self-declares as synthetic
    media wherever it travels: a wholesale ``generate`` / ``similar`` is
    ``ai_generated`` (trainedAlgorithmicMedia); an edit of a real photo
    (``edit`` / ``expand`` / ``remove`` / ``style_match`` / ``upscale``) is
    ``ai_composite`` (compositeWithTrainedAlgorithmicMedia). ``base`` lets an
    edit carry forward the source photo's credit chain.
    """
    wholesale = operation in ("generate", "similar")
    meta = base or ImageMetadata()
    meta.digital_source_type = "ai_generated" if wholesale else "ai_composite"
    if description and not meta.description.strip():
        meta.description = description
    # Honest, human-readable software/source note naming the model — not a key.
    mdl = (model or "").strip()
    meta.software = f"{SOFTWARE_NAME} ({mdl})" if mdl else SOFTWARE_NAME
    if wholesale and not meta.source.strip():
        meta.source = "Generated with MediaHub"
    return meta


def metadata_from_brief(
    brief: Any,
    *,
    club_name: str = "",
    photo_asset: Any = None,
    caption: str = "",
    year: str = "",
    create_date: str = "",
    software: str = SOFTWARE_NAME,
) -> ImageMetadata:
    """Build full card metadata from a ``CreativeBrief`` (+ optional photo asset).

    Honest by construction: a field is only populated when the underlying datum
    exists. ``caption`` overrides the brief-derived description; ``year`` (or a
    year parsed from ``create_date``) is folded into the copyright line. Nothing
    here calls ``now()`` — output stays deterministic.
    """
    text_layers = _get(brief, "text_layers", {}) or {}
    if not isinstance(text_layers, dict):
        text_layers = {}

    primary_hook = str(_get(brief, "primary_hook", "")).strip()
    achievement = str(_get(brief, "achievement_summary", "")).strip()
    confidence = str(_get(brief, "confidence_label", "")).strip()

    title = primary_hook or achievement
    description = (
        caption.strip()
        or str(text_layers.get("caption", "")).strip()
        or achievement
        or primary_hook
    )

    # Copyright line: "© [year] Club". Year only when we honestly have one.
    yr = (year or "").strip()
    if not yr and create_date.strip():
        head = create_date.strip()[:4]
        if head.isdigit():
            yr = head
    club = (club_name or "").strip()
    if club:
        copyright_line = f"© {yr} {club}".replace("  ", " ").strip() if yr else f"© {club}"
    else:
        copyright_line = ""

    # Keywords: club, athlete name(s), event, achievement label — facts only.
    keywords: list[str] = []
    if club:
        keywords.append(club)
    for layer in ("athlete_name", "swimmer_name", "name", "event_name", "event"):
        v = str(text_layers.get(layer, "")).strip()
        if v:
            keywords.append(v)
    if photo_asset is not None:
        for nm in _get(photo_asset, "linked_athlete_names", []) or []:
            if str(nm).strip():
                keywords.append(str(nm).strip())
    if confidence:
        keywords.append(confidence)

    asset_meta = (
        metadata_from_asset(photo_asset) if photo_asset is not None else ImageMetadata(software="")
    )

    return ImageMetadata(
        title=title,
        description=description,
        headline=achievement or primary_hook,
        creator=asset_meta.creator,
        copyright=copyright_line,
        credit=club,
        source=asset_meta.source,
        keywords=_dedupe_keywords(keywords),
        licence=asset_meta.licence,
        web_statement=asset_meta.web_statement,
        rights_marked=True if (copyright_line or asset_meta.creator) else None,
        software=software,
        create_date=create_date.strip(),
    )
