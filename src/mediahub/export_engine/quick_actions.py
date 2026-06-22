"""export_engine/quick_actions.py — the media-library quick-actions toolbox (1.19).

The one-click utilities a volunteer reaches for *without* making a whole post:
convert / resize / crop a photo, trim / crop / resize / speed / mute / reverse /
merge a clip, turn a clip into a GIF (or a GIF back into a clip), and bundle a
few photos into a PDF. Canva and Adobe Express ship these as a "Quick Actions"
toolbox; this is MediaHub's first-party equivalent.

Zero new philosophy: every action is deterministic code we already own —
``media_library.photo_ops`` (1.3) for image edits, ``video.ops`` (1.6) for clip
edits, ``export_engine.transcode`` for GIF↔video, ``export_engine.images`` for
format conversion, and ``documents.pdf_utils`` (1.15) for images→PDF. This module
just wires them behind one tidy, file-in/file-out surface so the web layer (and
bulk jobs) call one place. Honest errors propagate from the underlying ops.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from . import images as _images
from . import transcode as _transcode
from .formats import normalise_key
from .options import ExportOptions

# ---------------------------------------------------------------------------
# Image quick actions (Pillow — deterministic, no binary needed)
# ---------------------------------------------------------------------------


def _apply_recipe(src: Path, out: Path, op: str, params: dict) -> Path:
    """Apply a single ``photo_ops`` edit op to an image file → ``out``."""
    from mediahub.media_library.photo_ops import EditRecipe

    data = Path(src).read_bytes()
    fmt = Path(out).suffix.lstrip(".").lower() or None
    recipe = EditRecipe().with_op(op, params)
    result = recipe.apply_bytes(data, fmt=fmt)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(result)
    return Path(out)


def convert_image(src: Path, out: Path, *, fmt: str, options: ExportOptions | None = None) -> Path:
    """Convert a photo to another raster format (PNG/JPG/WebP/AVIF)."""
    return _images.convert_image(src, out, fmt=fmt, options=options)


def resize_image(
    src: Path,
    out: Path,
    *,
    width: int = 0,
    height: int = 0,
    scale: float = 0.0,
) -> Path:
    """Resize a photo by explicit ``width``/``height`` or a ``scale`` factor
    (a zero dimension is inferred to preserve aspect — the 1.3 resize op)."""
    if width <= 0 and height <= 0 and scale <= 0:
        raise ValueError("resize needs a width, a height, or a scale")
    return _apply_recipe(
        src, out, "resize", {"width": int(width), "height": int(height), "scale": float(scale)}
    )


def crop_image(src: Path, out: Path, *, x: float, y: float, w: float, h: float) -> Path:
    """Crop a photo to a rectangle given as 0–1 fractions of the image
    (``x``/``y`` = top-left, ``w``/``h`` = size — matches the 1.3 crop op)."""
    return _apply_recipe(src, out, "crop", {"x": x, "y": y, "w": w, "h": h})


def images_to_pdf(sources: Sequence[Path], out: Path) -> Path:
    """Bundle one or more images into a single PDF, one image per page (1.15)."""
    from mediahub.documents.pdf_utils import images_to_pdf as _to_pdf

    srcs = [Path(s) for s in sources]
    if not srcs:
        raise ValueError("images_to_pdf needs at least one image")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    return _to_pdf(srcs, Path(out))


# ---------------------------------------------------------------------------
# Video quick actions (FFmpeg via video.ops — honest-error without a binary)
# ---------------------------------------------------------------------------


def video_trim(src: Path, out: Path, *, start: float = 0.0, end: float | None = None) -> Path:
    from mediahub.video import ops as vops

    return vops.trim(Path(src), Path(out), start=start, end=end)


def video_crop(src: Path, out: Path, *, x: int, y: int, width: int, height: int) -> Path:
    from mediahub.video import ops as vops

    return vops.crop(Path(src), Path(out), x=x, y=y, width=width, height=height)


def video_resize(src: Path, out: Path, *, width: int = 0, height: int = 0, keep_aspect: bool = True) -> Path:
    from mediahub.video import ops as vops

    return vops.resize(Path(src), Path(out), width=width, height=height, keep_aspect=keep_aspect)


def video_speed(src: Path, out: Path, *, factor: float, mute: bool = False) -> Path:
    from mediahub.video import ops as vops

    return vops.change_speed(Path(src), Path(out), factor=factor, mute=mute)


def video_mute(src: Path, out: Path) -> Path:
    from mediahub.video import ops as vops

    return vops.mute(Path(src), Path(out))


def video_reverse(src: Path, out: Path, *, mute: bool = False) -> Path:
    from mediahub.video import ops as vops

    return vops.reverse(Path(src), Path(out), mute=mute)


def video_merge(sources: Sequence[Path], out: Path) -> Path:
    """Join compatible clips end-to-end (best for clips MediaHub rendered)."""
    from mediahub.video import ops as vops

    srcs = [Path(s) for s in sources]
    if not srcs:
        raise ValueError("video_merge needs at least one clip")
    return vops.concat(srcs, Path(out))


# ---------------------------------------------------------------------------
# GIF quick actions (transcode)
# ---------------------------------------------------------------------------


def video_to_gif(src: Path, out: Path, *, fps: int = 12, width: int = 480) -> Path:
    return _transcode.video_to_gif(Path(src), Path(out), fps=fps, width=width)


def gif_to_video(src: Path, out: Path, *, fmt: str = "mp4", quality: int = 80) -> Path:
    key = normalise_key(fmt)
    if key not in ("mp4", "webm"):
        raise ValueError(f"a GIF converts to mp4 or webm, not {fmt!r}")
    return _transcode.gif_to_video(Path(src), Path(out), fmt=key, quality=quality)


# A catalogue of the toolbox actions, grouped for the UI. Each entry names the
# action key the web layer dispatches on and a short human label.
ACTIONS: dict[str, list[tuple[str, str]]] = {
    "image": [
        ("convert", "Convert format"),
        ("resize", "Resize"),
        ("crop", "Crop"),
        ("to_pdf", "Images → PDF"),
    ],
    "video": [
        ("trim", "Trim"),
        ("crop", "Crop"),
        ("resize", "Resize"),
        ("speed", "Change speed"),
        ("mute", "Mute"),
        ("reverse", "Reverse"),
        ("merge", "Merge clips"),
        ("to_gif", "Video → GIF"),
    ],
    "gif": [
        ("to_mp4", "GIF → MP4"),
        ("to_webm", "GIF → WebM"),
    ],
}


__all__ = [
    "ACTIONS",
    "convert_image",
    "resize_image",
    "crop_image",
    "images_to_pdf",
    "video_trim",
    "video_crop",
    "video_resize",
    "video_speed",
    "video_mute",
    "video_reverse",
    "video_merge",
    "video_to_gif",
    "gif_to_video",
]
