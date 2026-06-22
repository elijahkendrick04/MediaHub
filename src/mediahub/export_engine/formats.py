"""export_engine/formats.py — the catalogue of export formats (roadmap 1.19).

One registry every surface reads to know what MediaHub can export and which
per-format options each format honours. This module is **pure data + lookups**:
no rendering happens here. The adapters that actually *produce* each format live
in their home packages — the still renderer (PNG/JPG/WebP/AVIF/SVG/print-PDF),
``documents`` (PDF/PPTX/DOCX), ``audio`` (WAV/MP3/…), ``video``/``visual``
(MP4) and the new ``export_engine.transcode`` (GIF/WebM) — and are wired
together by :mod:`export_engine.engine`.

Keeping the catalogue separate means the UI, the bulk-export planner and the
quick-actions toolbox all agree on exactly one source of truth for "what can we
export, what does it weigh, and which knobs apply".
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The broad families an export belongs to. Drives the UI grouping and tells the
# engine which adapter family to dispatch to.
CATEGORIES: tuple[str, ...] = ("image", "video", "audio", "document", "data", "pack")

# The per-format option knobs a format can honour (see export_engine.options).
OPTION_KEYS: tuple[str, ...] = ("quality", "scale", "transparent", "colour_profile")


class UnknownFormatError(ValueError):
    """An export was requested in a format the engine does not know."""


@dataclass(frozen=True)
class ExportFormat:
    """One exportable format and the truth about what it supports.

    ``accepts`` is the set of :data:`OPTION_KEYS` the format actually honours —
    a JPEG honours ``quality`` but a lossless PNG ignores it; only raster image
    formats honour ``transparent``. The engine uses this to drop no-op options
    so a cache key never churns on an option the format never read.
    """

    key: str
    label: str
    category: str
    suffix: str
    mime: str
    lossy: bool = False
    supports_transparency: bool = False
    accepts: frozenset[str] = field(default_factory=frozenset)

    def honours(self, option_key: str) -> bool:
        return option_key in self.accepts


def _f(
    key: str,
    label: str,
    category: str,
    suffix: str,
    mime: str,
    *,
    lossy: bool = False,
    transparency: bool = False,
    accepts: tuple[str, ...] = (),
) -> ExportFormat:
    return ExportFormat(
        key=key,
        label=label,
        category=category,
        suffix=suffix,
        mime=mime,
        lossy=lossy,
        supports_transparency=transparency,
        accepts=frozenset(accepts),
    )


# The registry. Insertion order is the natural UI order within each category.
FORMATS: dict[str, ExportFormat] = {
    # --- image -------------------------------------------------------------
    "png": _f(
        "png",
        "PNG",
        "image",
        ".png",
        "image/png",
        transparency=True,
        accepts=("scale", "transparent"),
    ),
    "jpg": _f(
        "jpg",
        "JPEG",
        "image",
        ".jpg",
        "image/jpeg",
        lossy=True,
        accepts=("quality", "scale"),
    ),
    "webp": _f(
        "webp",
        "WebP",
        "image",
        ".webp",
        "image/webp",
        lossy=True,
        transparency=True,
        accepts=("quality", "scale", "transparent"),
    ),
    "avif": _f(
        "avif",
        "AVIF",
        "image",
        ".avif",
        "image/avif",
        lossy=True,
        transparency=True,
        accepts=("quality", "scale", "transparent"),
    ),
    "svg": _f(
        "svg",
        "SVG (vector)",
        "image",
        ".svg",
        "image/svg+xml",
        transparency=True,
        accepts=("transparent",),
    ),
    # --- video -------------------------------------------------------------
    "mp4": _f("mp4", "MP4 (H.264)", "video", ".mp4", "video/mp4", lossy=True, accepts=("scale",)),
    "webm": _f(
        "webm",
        "WebM (VP9)",
        "video",
        ".webm",
        "video/webm",
        lossy=True,
        transparency=True,
        accepts=("quality", "scale", "transparent"),
    ),
    "gif": _f("gif", "Animated GIF", "video", ".gif", "image/gif", accepts=("scale",)),
    # --- audio -------------------------------------------------------------
    "wav": _f("wav", "WAV", "audio", ".wav", "audio/wav"),
    "mp3": _f("mp3", "MP3", "audio", ".mp3", "audio/mpeg", lossy=True, accepts=("quality",)),
    "m4a": _f("m4a", "M4A (AAC)", "audio", ".m4a", "audio/mp4", lossy=True, accepts=("quality",)),
    "ogg": _f(
        "ogg", "OGG (Vorbis)", "audio", ".ogg", "audio/ogg", lossy=True, accepts=("quality",)
    ),
    "opus": _f("opus", "Opus", "audio", ".opus", "audio/opus", lossy=True, accepts=("quality",)),
    "flac": _f("flac", "FLAC", "audio", ".flac", "audio/flac"),
    # --- document ----------------------------------------------------------
    "pdf": _f("pdf", "PDF", "document", ".pdf", "application/pdf", accepts=("colour_profile",)),
    "print_pdf": _f(
        "print_pdf",
        "Print PDF (bleed + marks)",
        "document",
        ".pdf",
        "application/pdf",
        accepts=("colour_profile",),
    ),
    "pptx": _f(
        "pptx",
        "PowerPoint (PPTX)",
        "document",
        ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "docx": _f(
        "docx",
        "Word (DOCX)",
        "document",
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    # --- data --------------------------------------------------------------
    "csv": _f("csv", "CSV", "data", ".csv", "text/csv"),
    "json": _f("json", "JSON", "data", ".json", "application/json"),
    "xlsx": _f(
        "xlsx",
        "Excel (XLSX)",
        "data",
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    # --- pack --------------------------------------------------------------
    "zip": _f("zip", "ZIP archive", "pack", ".zip", "application/zip"),
}

# Common spellings that map onto a canonical key.
_ALIASES: dict[str, str] = {
    "jpeg": "jpg",
    "jpe": "jpg",
    "tif": "tiff",
    "htm": "html",
    "mpeg4": "mp4",
    "m4v": "mp4",
    "wave": "wav",
    "print": "print_pdf",
    "printpdf": "print_pdf",
}


def normalise_key(key: str) -> str:
    """Lower-case, strip a leading dot, and resolve a known alias."""
    k = (key or "").strip().lower().lstrip(".")
    return _ALIASES.get(k, k)


def has_format(key: str) -> bool:
    return normalise_key(key) in FORMATS


def get_format(key: str) -> ExportFormat:
    """Look up a format by key (alias-aware). Raises :class:`UnknownFormatError`."""
    k = normalise_key(key)
    try:
        return FORMATS[k]
    except KeyError as exc:
        raise UnknownFormatError(
            f"unknown export format {key!r}; known: {', '.join(sorted(FORMATS))}"
        ) from exc


def all_formats() -> list[ExportFormat]:
    return list(FORMATS.values())


def formats_for_category(category: str) -> list[ExportFormat]:
    cat = (category or "").strip().lower()
    return [f for f in FORMATS.values() if f.category == cat]


def suffix_for(key: str) -> str:
    return get_format(key).suffix


def mime_for(key: str) -> str:
    return get_format(key).mime


__all__ = [
    "CATEGORIES",
    "OPTION_KEYS",
    "ExportFormat",
    "UnknownFormatError",
    "FORMATS",
    "normalise_key",
    "has_format",
    "get_format",
    "all_formats",
    "formats_for_category",
    "suffix_for",
    "mime_for",
]
