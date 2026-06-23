"""mediahub/interop/psd_import.py — first-party PSD import (raster layers).

Honest, optional, and dependency-gated. Photoshop's ``.psd`` is a complex
proprietary format; we read it with the MIT-licensed ``psd-tools`` (the
``psd`` optional extra). With the extra absent the importer **honest-errors**
rather than pretending — never a fabricated import (CLAUDE.md: a clear error
beats a stub).

Fidelity is stated plainly: we extract the **flattened composite** as a raster
image into the media library (and could be extended to per-layer rasters). Full
layered PSD round-trip is a separate, later goal (roadmap 1.25); this is the
"open + convert assets" half of 1.21.
"""

from __future__ import annotations

import io


class PsdImportError(Exception):
    pass


class PsdImportUnavailable(PsdImportError):
    """Raised when the optional ``psd-tools`` backend isn't installed."""


def available() -> bool:
    try:
        import psd_tools  # noqa: F401,PLC0415

        return True
    except Exception:
        return False


def psd_to_png(psd_bytes: bytes) -> bytes:
    """Flatten a PSD to a PNG. Raises PsdImportUnavailable if the dep is absent."""
    if not psd_bytes:
        raise PsdImportError("empty PSD")
    try:
        from psd_tools import PSDImage  # noqa: PLC0415
    except Exception as e:
        raise PsdImportUnavailable(
            "PSD import needs the optional 'psd-tools' backend " "(pip install 'mediahub[psd]')."
        ) from e
    try:
        psd = PSDImage.open(io.BytesIO(psd_bytes))
        composite = psd.composite()
        out = io.BytesIO()
        composite.save(out, format="PNG")
        return out.getvalue()
    except PsdImportUnavailable:
        raise
    except Exception as e:
        raise PsdImportError(f"could not read PSD: {e}") from e


def import_psd(profile_id: str, psd_bytes: bytes, filename: str = "import.psd") -> dict:
    """Flatten a PSD to PNG and store it as a media-library asset."""
    png = psd_to_png(psd_bytes)

    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    store = get_store()
    stem = filename.rsplit(".", 1)[0] or "import"
    name = stem + ".png"
    path = store.store_blob(png, name, profile_id)
    asset = MediaAsset(
        id="",
        filename=name,
        path=str(path),
        type="photo",
        profile_id=profile_id,
        notes="Imported from PSD (flattened composite).",
        tags=["psd", "import"],
    )
    saved = store.save(asset)
    return {"id": saved.id, "filename": saved.filename, "type": saved.type, "from": "psd"}


__all__ = ["PsdImportError", "PsdImportUnavailable", "available", "psd_to_png", "import_psd"]
