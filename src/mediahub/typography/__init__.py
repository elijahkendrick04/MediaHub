"""typography — MediaHub's first-party type pipeline.

Houses two halves of the **typography system** (roadmap 1.9):

* the **club custom-font upload pipeline** (roadmap G1.10): validate → subset →
  self-host an uploaded brand typeface, with no Google Fonts CDN and an honest
  error when the subsetting toolchain is absent —
  :mod:`mediahub.typography.font_intake`;
* the **curated self-hosted font catalogue** — the source of truth for the
  first-party faces MediaHub ships across its three surfaces, browsable by
  mood / class / surface and merged with an org's uploads —
  :mod:`mediahub.typography.catalog`.
"""

from .catalog import (
    CatalogError,
    CatalogFont,
    CLASS_VOCAB,
    MOOD_VOCAB,
    ROLE_VOCAB,
    SURFACE_VOCAB,
    for_surface,
    get,
    load_catalog,
    org_catalog,
    search,
    verify_assets,
)
from .font_intake import (
    FontIntakeError,
    FontValidationError,
    FontEmbeddingNotPermitted,
    FontToolingUnavailable,
    FontFacts,
    FontRecord,
    sniff_container,
    structural_scan,
    validate_font_bytes,
    classify_embedding,
    is_font_tooling_available,
    subset_to_woff2,
    default_unicodes,
    font_dir_for,
    store_woff2,
    load_record,
    list_fonts,
    remove_font,
    font_face_css,
    sanitise_family,
    css_family_for,
    intake_font,
    DEFAULT_UNICODE_RANGES,
    ALLOWED_ROLES,
    MAX_UPLOAD_BYTES,
    MAX_DECOMPRESSED_BYTES,
    MAX_TABLES,
)

__all__ = [
    # catalogue
    "CatalogError",
    "CatalogFont",
    "CLASS_VOCAB",
    "MOOD_VOCAB",
    "ROLE_VOCAB",
    "SURFACE_VOCAB",
    "for_surface",
    "get",
    "load_catalog",
    "org_catalog",
    "search",
    "verify_assets",
    # font intake
    "FontIntakeError",
    "FontValidationError",
    "FontEmbeddingNotPermitted",
    "FontToolingUnavailable",
    "FontFacts",
    "FontRecord",
    "sniff_container",
    "structural_scan",
    "validate_font_bytes",
    "classify_embedding",
    "is_font_tooling_available",
    "subset_to_woff2",
    "default_unicodes",
    "font_dir_for",
    "store_woff2",
    "load_record",
    "list_fonts",
    "remove_font",
    "font_face_css",
    "sanitise_family",
    "css_family_for",
    "intake_font",
    "DEFAULT_UNICODE_RANGES",
    "ALLOWED_ROLES",
    "MAX_UPLOAD_BYTES",
    "MAX_DECOMPRESSED_BYTES",
    "MAX_TABLES",
]
