"""mediahub/interop/svg_import.py — import an SVG as a sanitised media asset.

SVG is XML that can carry scripts, event handlers, external fetches and XML
external-entity (XXE) attacks. Storing a raw uploaded SVG and ever serving it
inline would be a stored-XSS / data-exfiltration hole. So import is
**sanitise-first**: parse with entities and network disabled, strip every active
vector, then store the cleaned vector.

What it removes:
- ``<script>`` and ``<foreignObject>`` elements (the usual script smuggling)
- every ``on*`` event-handler attribute
- ``href`` / ``xlink:href`` values that are ``javascript:``, non-image ``data:``,
  or absolute ``http(s)://`` (external fetch / exfil) — internal ``#refs`` and
  ``data:image/`` stay
- ``style`` attributes and ``<style>`` text referencing ``javascript:``,
  ``expression(``, ``@import`` or an external ``url(http…)``

This is a conservative, documented sanitiser — not a full CSP engine. Anything
it cannot safely parse is rejected with an honest error rather than stored.
"""

from __future__ import annotations

import re

ASSET_TYPE = "graphic"


class SvgImportError(Exception):
    """Raised when input isn't a usable SVG or can't be safely sanitised."""


_DANGEROUS_ELEMENTS = {"script", "foreignobject"}
_URL_HTTP = re.compile(r"url\(\s*['\"]?\s*https?:", re.IGNORECASE)
_BAD_CSS = re.compile(r"(javascript:|expression\(|@import)", re.IGNORECASE)


def _localname(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _bad_href(value: str) -> bool:
    v = (value or "").strip().lower()
    if v.startswith("javascript:"):
        return True
    if v.startswith("data:") and not v.startswith("data:image/"):
        return True
    if v.startswith("http://") or v.startswith("https://"):
        return True
    return False


def sanitize_svg(svg_bytes: bytes) -> bytes:
    """Return a cleaned SVG, or raise ``SvgImportError``."""
    if not svg_bytes or len(svg_bytes) > 5 * 1024 * 1024:
        raise SvgImportError("SVG is empty or larger than 5 MB")
    try:
        from lxml import etree  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - lxml is a hard dependency
        raise SvgImportError(f"SVG parser unavailable: {e}")

    # Entities + network OFF: blocks XXE and external-entity expansion.
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False
    )
    try:
        root = etree.fromstring(svg_bytes, parser=parser)
    except etree.XMLSyntaxError as e:
        raise SvgImportError(f"not well-formed SVG/XML: {e}")
    if _localname(root.tag) != "svg":
        raise SvgImportError("root element is not <svg>")

    # Walk once, collecting elements to drop and scrubbing attributes in place.
    to_remove = []
    for el in root.iter():
        name = _localname(el.tag)
        if name in _DANGEROUS_ELEMENTS:
            to_remove.append(el)
            continue
        if name == "style" and el.text and _BAD_CSS.search(el.text):
            el.text = ""
        for attr in list(el.attrib):
            local = attr.rsplit("}", 1)[-1].lower()
            val = el.attrib[attr]
            if local.startswith("on"):
                del el.attrib[attr]
            elif local in ("href",) and _bad_href(val):
                del el.attrib[attr]
            elif local == "style" and (_BAD_CSS.search(val) or _URL_HTTP.search(val)):
                del el.attrib[attr]
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    cleaned = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    return cleaned


def _dimensions(svg_bytes: bytes) -> tuple[int, int]:
    try:
        from lxml import etree  # noqa: PLC0415

        root = etree.fromstring(svg_bytes)
    except Exception:
        return 0, 0

    def _num(s):
        m = re.match(r"\s*([0-9.]+)", s or "")
        return int(float(m.group(1))) if m else 0

    w = _num(root.get("width"))
    h = _num(root.get("height"))
    if (not w or not h) and root.get("viewBox"):
        parts = re.split(r"[ ,]+", root.get("viewBox").strip())
        if len(parts) == 4:
            w = w or _num(parts[2])
            h = h or _num(parts[3])
    return w, h


def import_svg(profile_id: str, svg_bytes: bytes, filename: str = "import.svg") -> dict:
    """Sanitise an SVG and store it as a media-library asset for ``profile_id``.

    Returns a small summary dict. Raises ``SvgImportError`` on bad/unsafe input."""
    cleaned = sanitize_svg(svg_bytes)
    w, h = _dimensions(cleaned)

    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    store = get_store()
    name = filename if filename.lower().endswith(".svg") else (filename + ".svg")
    path = store.store_blob(cleaned, name, profile_id)
    asset = MediaAsset(
        id="",
        filename=name,
        path=str(path),
        type=ASSET_TYPE,
        profile_id=profile_id,
        width=w,
        height=h,
        notes="Imported SVG (sanitised on import).",
        tags=["svg", "import"],
    )
    saved = store.save(asset)
    return {
        "id": saved.id,
        "filename": saved.filename,
        "type": saved.type,
        "width": w,
        "height": h,
        "sanitized": True,
    }


__all__ = ["SvgImportError", "sanitize_svg", "import_svg", "ASSET_TYPE"]
