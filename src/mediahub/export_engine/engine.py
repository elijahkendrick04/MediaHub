"""export_engine/engine.py — the one export/conversion orchestrator (1.19).

The single entry point every surface calls to turn a file into another format.
It owns the *routing* (which adapter produces which target), the *options*
mapping (export knobs → each adapter's own parameters), and a content-addressed
*cache* so the same request never re-encodes twice. The heavy lifting stays in
the adapters that already shipped — Pillow image conversion (:mod:`.images`),
FFmpeg video/GIF transcodes (:mod:`.transcode`), and the audio package's
deterministic transcoder — this module just wires them behind one contract.

What this covers is *file → file* conversion: the conversion engine and the
raster/video/audio side of the quick-actions toolbox. Spec-driven exports that
re-render from a brief (card → SVG / print-PDF / PPTX) are produced by their own
adapters; the format registry here is the shared catalogue they all advertise
through, and :func:`target_formats_for` tells a caller what a given source can
become.

Honest errors throughout: an unavailable engine (no FFmpeg, no AVIF encoder)
raises :class:`ExportUnavailable`; an impossible conversion raises
:class:`ExportError`. Never a silent no-op, never a fabricated file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import cache as _cache
from . import images as _images
from . import transcode as _transcode
from .formats import ExportFormat, get_format, normalise_key
from .options import ExportOptions


class ExportError(RuntimeError):
    """A conversion was requested that the engine cannot perform."""


class ExportUnavailable(ExportError):
    """The engine for a conversion is not installed (FFmpeg/encoder missing)."""


@dataclass(frozen=True)
class ExportResult:
    """The outcome of one export — the file plus the truth about it."""

    path: Path
    fmt: str
    mime: str
    size_bytes: int
    from_cache: bool = False
    note: str = ""


# Source-file suffix → the family the engine routes by. Animated GIF is its own
# family (it converts *to* video, and video converts *to* it).
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp", ".tif", ".tiff"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac"}
_AUDIO_KEYS = frozenset({"wav", "mp3", "m4a", "aac", "ogg", "opus", "flac"})

# Which target format keys each source family can become through convert_file.
# This is the capability map the UI and the bulk planner read.
CONVERSIONS: dict[str, frozenset[str]] = {
    "image": frozenset({"png", "jpg", "webp", "avif"}),
    "video": frozenset({"mp4", "webm", "gif", "wav", "mp3", "m4a", "ogg", "opus", "flac"}),
    "gif": frozenset({"mp4", "webm"}),
    "audio": frozenset({"wav", "mp3", "m4a", "ogg", "opus", "flac"}),
}


def source_category(path: str | Path) -> str:
    """Infer the routing family from a file's suffix: image/video/gif/audio."""
    suffix = Path(path).suffix.lower()
    if suffix == ".gif":
        return "gif"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    return "unknown"


def target_formats_for(source: str | Path) -> list[ExportFormat]:
    """The formats ``source`` (a path or a category name) can be converted to."""
    cat = source if source in CONVERSIONS else source_category(source)
    return [get_format(k) for k in sorted(CONVERSIONS.get(cat, frozenset()))]


def can_convert(source: str | Path, fmt: str) -> bool:
    cat = source if source in CONVERSIONS else source_category(source)
    return normalise_key(fmt) in CONVERSIONS.get(cat, frozenset())


def _dispatch(src: Path, key: str, scat: str, out: Path, opts: ExportOptions) -> str:
    """Run the right adapter for (source family → target key). Returns a note."""
    # --- raster image → raster image -----------------------------------
    if scat == "image" and key in ("png", "jpg", "webp", "avif"):
        _images.convert_image(src, out, fmt=key, options=opts)
        return f"image→{key}"

    # --- video → still/animated video ----------------------------------
    if scat == "video":
        if key == "gif":
            _transcode.video_to_gif(src, out, scale=opts.scale)
            return "video→gif"
        if key == "webm":
            _transcode.to_webm(src, out, quality=opts.quality, scale=opts.scale, transparent=opts.transparent)
            return "video→webm"
        if key == "mp4":
            _transcode.to_mp4(src, out, quality=opts.quality, scale=opts.scale)
            return "video→mp4"
        if key in _AUDIO_KEYS:
            _convert_audio(src, out, key, extract=True)
            return f"video→{key} (audio extract)"

    # --- animated GIF → video ------------------------------------------
    if scat == "gif" and key in ("mp4", "webm"):
        _transcode.gif_to_video(src, out, fmt=key, quality=opts.quality)
        return f"gif→{key}"

    # --- audio → audio --------------------------------------------------
    if scat == "audio" and key in _AUDIO_KEYS:
        _convert_audio(src, out, key, extract=False)
        return f"audio→{key}"

    raise ExportError(f"cannot convert a {scat or 'unknown'} source to {key!r}")


def _convert_audio(src: Path, out: Path, key: str, *, extract: bool) -> None:
    """Delegate to the audio package's deterministic transcoder (1.8)."""
    try:
        from mediahub.audio import ops as audio_ops
    except Exception as exc:  # pragma: no cover - audio package always present
        raise ExportUnavailable(f"audio engine unavailable: {exc}") from exc
    try:
        if extract:
            audio_ops.extract_audio(src, out, fmt=key)
        else:
            audio_ops.convert(src, out, fmt=key)
    except audio_ops.AudioOpError as exc:
        raise ExportUnavailable(str(exc)) from exc


def convert_file(
    src: str | Path,
    fmt: str,
    *,
    options: ExportOptions | None = None,
    out: str | Path | None = None,
    use_cache: bool = True,
) -> ExportResult:
    """Convert ``src`` to ``fmt`` and return an :class:`ExportResult`.

    With ``out`` omitted the result lands in the content-addressed export cache
    (so repeated requests are free); pass ``out`` to write a specific path. The
    cache key folds in the source fingerprint, the target format and the clamped
    options, so any change to any of them produces a fresh file.
    """
    src_path = Path(src)
    target = get_format(fmt)  # validates / raises UnknownFormatError
    key = target.key
    opts = (options or ExportOptions()).clamped()

    if not src_path.is_file():
        raise ExportError(f"source file not found: {src_path}")

    scat = source_category(src_path)
    if not can_convert(scat, key):
        raise ExportError(
            f"a {scat or 'unknown'} source cannot be exported as {key!r}; "
            f"valid targets: {', '.join(sorted(CONVERSIONS.get(scat, frozenset()))) or '(none)'}"
        )

    # Resolve the destination (explicit path, or a cache slot).
    if out is not None:
        out_path = Path(out)
        cache_hit = False
    else:
        out_path = _cache.cached_path(
            target.suffix,
            "convert",
            _cache.file_fingerprint(src_path),
            key,
            opts.cache_token(),
        )
        cache_hit = use_cache and out_path.is_file() and out_path.stat().st_size > 0

    if cache_hit:
        return ExportResult(
            path=out_path,
            fmt=key,
            mime=target.mime,
            size_bytes=out_path.stat().st_size,
            from_cache=True,
            note="cache hit",
        )

    note = _dispatch(src_path, key, scat, out_path, opts)
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise ExportError(f"conversion produced no output for {key!r}")
    return ExportResult(
        path=out_path,
        fmt=key,
        mime=target.mime,
        size_bytes=out_path.stat().st_size,
        from_cache=False,
        note=note,
    )


def engine_status() -> dict:
    """A small diagnostics dict for the UI / health surface."""
    return {
        "ffmpeg": _transcode.available(),
        "avif_encode": _images.can_encode("avif"),
        "webp_encode": _images.can_encode("webp"),
        "conversions": {cat: sorted(keys) for cat, keys in CONVERSIONS.items()},
    }


__all__ = [
    "ExportError",
    "ExportUnavailable",
    "ExportResult",
    "CONVERSIONS",
    "source_category",
    "target_formats_for",
    "can_convert",
    "convert_file",
    "engine_status",
]
