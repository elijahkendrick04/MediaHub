"""export_engine/images.py — deterministic raster image conversion (1.19).

Convert a rendered card (or any image) between PNG / JPEG / WebP / AVIF with the
export options clubs expect: a quality slider for the lossy formats, an output
scale, and transparent-background handling (keep the alpha where the format
supports it, otherwise flatten onto a chosen colour). This is the "convert image
format" quick action and the raster side of the format registry.

Pure Pillow, no model in the loop — same input + options → same bytes for a
given Pillow build. When the running Pillow lacks an encoder (e.g. AVIF on a
build without libavif) we raise :class:`ImageConvertError` rather than writing a
wrong-format or empty file — the engine's honest-error rule.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageColor

from .formats import get_format, normalise_key
from .options import ExportOptions

# Raster formats this module can encode, mapped to the Pillow save format name.
_PIL_FORMAT: dict[str, str] = {
    "png": "PNG",
    "jpg": "JPEG",
    "webp": "WEBP",
    "avif": "AVIF",
}


class ImageConvertError(RuntimeError):
    """An image could not be converted — honest error, never a wrong file."""


def can_encode(fmt: str) -> bool:
    """True when the running Pillow can encode ``fmt`` (AVIF varies by build)."""
    key = normalise_key(fmt)
    name = _PIL_FORMAT.get(key)
    if name is None:
        return False
    if name in ("PNG", "JPEG"):
        return True
    # WEBP/AVIF depend on the build. Pillow registers encoders lazily, so prod
    # the plugin registry first, then probe it.
    Image.init()
    return name in Image.SAVE


def _flatten(img: Image.Image, background: str) -> Image.Image:
    """Composite an image with alpha onto an opaque ``background`` colour."""
    rgba = img.convert("RGBA")
    try:
        bg_rgb = ImageColor.getrgb(background)
    except ValueError:
        bg_rgb = (255, 255, 255)
    canvas = Image.new("RGB", rgba.size, bg_rgb)
    canvas.paste(rgba, mask=rgba.split()[-1])
    return canvas


def _resized(img: Image.Image, scale: float) -> Image.Image:
    if abs(scale - 1.0) < 1e-6:
        return img
    w = max(1, int(round(img.width * scale)))
    h = max(1, int(round(img.height * scale)))
    return img.resize((w, h), Image.LANCZOS)


def _encode(img: Image.Image, fmt_key: str, opts: ExportOptions) -> bytes:
    fmt = get_format(fmt_key)
    name = _PIL_FORMAT[fmt_key]
    keep_alpha = opts.transparent and fmt.supports_transparency

    if keep_alpha:
        work = img.convert("RGBA")
    elif img.mode in ("RGBA", "LA", "P"):
        work = _flatten(img, opts.background)
    else:
        work = img.convert("RGB")

    buf = io.BytesIO()
    if name == "PNG":
        work.save(buf, format="PNG", optimize=True)
    elif name == "JPEG":
        work.save(buf, format="JPEG", quality=opts.quality, optimize=True, progressive=True)
    elif name == "WEBP":
        work.save(buf, format="WEBP", quality=opts.quality, method=6)
    elif name == "AVIF":
        work.save(buf, format="AVIF", quality=opts.quality)
    else:  # pragma: no cover - guarded by can_encode upstream
        raise ImageConvertError(f"no encoder for {fmt_key!r}")
    return buf.getvalue()


def convert_image_bytes(data: bytes, *, fmt: str, options: ExportOptions | None = None) -> bytes:
    """Convert encoded image ``data`` to ``fmt`` and return the new bytes."""
    key = normalise_key(fmt)
    if key not in _PIL_FORMAT:
        raise ImageConvertError(f"{fmt!r} is not a raster image format this engine converts")
    if not can_encode(key):
        raise ImageConvertError(
            f"this Pillow build cannot encode {key.upper()} — install the matching plugin"
        )
    opts = (options or ExportOptions()).clamped()
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure is a clean error
        raise ImageConvertError(f"could not read source image: {exc}") from exc
    work = _resized(src, opts.scale)
    return _encode(work, key, opts)


def convert_image(
    src: str | Path,
    out: str | Path,
    *,
    fmt: str,
    options: ExportOptions | None = None,
) -> Path:
    """Convert image file ``src`` to ``fmt``, writing to ``out``. Returns ``out``."""
    src_path = Path(src)
    if not src_path.is_file():
        raise ImageConvertError(f"source image not found: {src_path}")
    data = src_path.read_bytes()
    encoded = convert_image_bytes(data, fmt=fmt, options=options)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(encoded)
    return out_path


__all__ = [
    "ImageConvertError",
    "can_encode",
    "convert_image",
    "convert_image_bytes",
]
