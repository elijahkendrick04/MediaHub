"""elements.stickers — promote a club cutout into a custom sticker (roadmap 1.10, build 4).

Canva has "custom emojis / stickers". MediaHub's version is a **club mascot/crest
sticker**: take a cutout (or any library image) and register it as an org-custom
element so it can be dropped onto cards like any other element. It rides the
build-1 org-custom pack mechanism (``DATA_DIR/element_packs/<profile>/``), so no
new storage path or render path is needed.

A mascot is the club's own imagery, not a recolourable line drawing, so the
sticker is a ``kind="sticker"`` element with **no token slots** — the cutout is
embedded as a base64 data-URI inside a tiny self-contained SVG wrapper, so it
renders inline in a card exactly like the bundled elements. Deterministic and
offline (just image encode + catalogue write).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from .models import Element

_MAX_EDGE = 512  # cap the embedded sticker so the data-URI stays reasonable


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2])))


def _org_pack_dir(profile_id: str) -> Path:
    return _data_dir() / "element_packs" / str(profile_id)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or "sticker"


def make_sticker_svg(image_path: Path, *, max_edge: int = _MAX_EDGE) -> Optional[str]:
    """Wrap a raster image as a self-contained SVG (base64 data-URI <image>)."""
    try:
        from PIL import Image
    except Exception:  # pragma: no cover - Pillow always present
        return None
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGBA")
            w, h = im.size
            scale = min(1.0, max_edge / float(max(w, h) or 1))
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
                w, h = im.size
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}">'
        f'<image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>'
        f"</svg>"
    )


def promote_image_to_sticker(
    *,
    profile_id: str,
    image_path: Path,
    name: str,
    tags: Optional[list[str]] = None,
) -> Optional[Element]:
    """Register ``image_path`` as an org-custom sticker element for ``profile_id``.

    Returns the new :class:`Element` (or ``None`` if the image can't be read).
    The sticker is immediately visible to ``catalog.load_catalog(profile_id)``.
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        return None
    svg = make_sticker_svg(image_path)
    if not svg:
        return None

    pack_dir = _org_pack_dir(profile_id)
    svg_dir = pack_dir / "svg"
    svg_dir.mkdir(parents=True, exist_ok=True)
    eid = f"sticker.{_slug(name)}_{uuid.uuid4().hex[:6]}"
    svg_file = f"{eid.replace('.', '_')}.svg"
    (svg_dir / svg_file).write_text(svg, encoding="utf-8")

    element = Element(
        id=eid,
        name=name.strip() or "Club sticker",
        kind="sticker",
        sport="general",
        svg_file=svg_file,
        tags=tuple(t for t in (tags or ["mascot", "club"]) if t),
        keywords=f"{name} club mascot sticker custom",
        slots=(),  # club imagery — not token-recoloured
        source="org_custom",
        pack=f"{profile_id}-custom",
    )
    _append_to_org_catalog(pack_dir, element)
    return element


def _append_to_org_catalog(pack_dir: Path, element: Element) -> None:
    """Insert/replace an element in the org-custom catalog.json."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    path = pack_dir / "catalog.json"
    data: dict = {"pack": element.pack, "elements": []}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
                data.setdefault("elements", [])
        except (OSError, ValueError):
            pass
    entries = [e for e in data.get("elements", []) if e.get("id") != element.id]
    entries.append(element.to_dict())
    data["elements"] = entries
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_org_stickers(profile_id: str) -> list[Element]:
    """Org-custom sticker elements for a profile."""
    from . import catalog as _catalog

    return [
        el
        for el in _catalog.load_catalog(profile_id)
        if el.source == "org_custom" and el.kind == "sticker"
    ]


__all__ = [
    "make_sticker_svg",
    "promote_image_to_sticker",
    "list_org_stickers",
]
