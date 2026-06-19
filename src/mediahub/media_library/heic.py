"""HEIC / HEIF upload ingest (roadmap **1.3**).

Volunteers shoot on iPhones, which save HEIC by default. Pillow can't decode
HEIC without help, so an un-normalised ``.heic`` upload would be a broken asset.
This module registers the optional :mod:`pillow_heif` opener (once, lazily) and
normalises a HEIC/HEIF upload to a web-safe JPEG on the way in.

Honest behaviour when the optional dep is absent (the deterministic-engine /
honest-error rule): a HEIC upload raises :class:`HeicUnsupported` with a clear
message rather than silently saving an unreadable file; every other format is
passed through untouched, so the library keeps working without ``pillow_heif``.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

HEIC_SUFFIXES = (".heic", ".heif", ".hif")

_registered: Optional[bool] = None


class HeicUnsupported(RuntimeError):
    """Raised when a HEIC/HEIF file is uploaded but ``pillow_heif`` isn't installed."""


def is_available() -> bool:
    """True iff HEIC decoding is available (``pillow_heif`` importable)."""
    return register_heif()


def register_heif() -> bool:
    """Register the pillow-heif opener with Pillow once. Returns availability."""
    global _registered
    if _registered is not None:
        return _registered
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
        _registered = True
    except Exception:
        _registered = False
    return _registered


def is_heic(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in HEIC_SUFFIXES


def normalize_upload(path: str | Path) -> Tuple[Path, bool]:
    """If ``path`` is a HEIC/HEIF file, convert it in place to a sibling ``.jpg``.

    Returns ``(new_path, converted)``. Non-HEIC files are returned unchanged with
    ``converted=False``. Raises :class:`HeicUnsupported` when the file is HEIC
    but the decoder isn't installed — never leaves an unreadable asset behind.
    """
    p = Path(path)
    if p.suffix.lower() not in HEIC_SUFFIXES:
        return p, False
    if not register_heif():
        raise HeicUnsupported(
            "HEIC/HEIF images need the optional 'pillow-heif' package, which "
            "isn't installed on this deployment. Re-save the photo as JPEG or PNG."
        )
    with Image.open(p) as im:
        im.load()
        rgb = im.convert("RGB")
    out = p.with_suffix(".jpg")
    rgb.save(out, format="JPEG", quality=92)
    if out != p:
        try:
            p.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
    return out, True


def heic_bytes_to_jpeg(data: bytes) -> bytes:
    """Decode HEIC ``data`` to JPEG bytes (raises :class:`HeicUnsupported`)."""
    if not register_heif():
        raise HeicUnsupported("HEIC decoding needs the optional 'pillow-heif' package.")
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        rgb = im.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


__all__ = [
    "HEIC_SUFFIXES",
    "HeicUnsupported",
    "is_available",
    "register_heif",
    "is_heic",
    "normalize_upload",
    "heic_bytes_to_jpeg",
]
