"""export_engine — MediaHub's one first-party export & conversion engine (1.19).

Every surface that needs to turn content into a downloadable file goes through
here, so there is exactly one source of truth for *what* MediaHub can export,
*which knobs* each format honours, and *how* the request is cached.

Layout:

- :mod:`.formats` — the format catalogue (PNG/JPG/WebP/AVIF/SVG, MP4/GIF/WebM,
  WAV/MP3/…, PDF/print-PDF/PPTX/DOCX, CSV/JSON/XLSX, ZIP) and the per-format
  option-acceptance truth.
- :mod:`.options` — :class:`ExportOptions` (quality / scale / transparency /
  screen-vs-print), clamped and cache-tokenised.
- :mod:`.images` — deterministic raster conversion (Pillow).
- :mod:`.transcode` — deterministic FFmpeg video/GIF transcodes (the one
  renderer that did not already have a home).
- :mod:`.engine` — the orchestrator: :func:`convert_file`, the capability map
  and a content-addressed cache.
- :mod:`.cache` — that content-addressed cache, under ``DATA_DIR/export_cache``.

The deterministic-engine boundary holds: nothing here calls a model. Image and
video conversions are fixed Pillow/FFmpeg maths, so the same input + options
always yields the same bytes. Unavailable engines honest-error rather than
faking a file.
"""

from __future__ import annotations

from .engine import (
    CONVERSIONS,
    ExportError,
    ExportResult,
    ExportUnavailable,
    can_convert,
    convert_file,
    engine_status,
    source_category,
    target_formats_for,
)
from .formats import (
    FORMATS,
    ExportFormat,
    UnknownFormatError,
    all_formats,
    formats_for_category,
    get_format,
    has_format,
    mime_for,
    normalise_key,
    suffix_for,
)
from .options import ExportOptions

__all__ = [
    # options
    "ExportOptions",
    # formats
    "ExportFormat",
    "FORMATS",
    "UnknownFormatError",
    "get_format",
    "has_format",
    "all_formats",
    "formats_for_category",
    "normalise_key",
    "suffix_for",
    "mime_for",
    # engine
    "ExportError",
    "ExportUnavailable",
    "ExportResult",
    "CONVERSIONS",
    "convert_file",
    "can_convert",
    "source_category",
    "target_formats_for",
    "engine_status",
]
