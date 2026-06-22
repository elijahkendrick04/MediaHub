"""print_ready — MediaHub's print-readiness layer (roadmap 1.20).

A club prints constantly: noticeboard posters, meet programmes, PB certificates,
gala banners, fundraising merch. This package is the engineering that lets a
volunteer hand any high-street or online printer a file that **won't bounce** —
without anyone on the committee knowing what "bleed" or "CMYK" means.

It sits on top of the renderer-side print mechanics that already shipped
(``graphic_renderer.print_export`` — trim/bleed/crop-marks/CMYK science/Ghostscript)
and the :class:`~mediahub.club_platform.format_catalog.FormatSpec` catalogue
(which already carries ``bleed_mm`` / ``dpi`` / safe zones). What this package
adds is the **product + intelligence layer**:

- :mod:`.products` — the print/merch product registry: which canvas a product
  prints, on what substrate, by what method, with which ink limit and mockup.
- :mod:`.proof` — the **deterministic auto-proofer** (roadmap 1.20's intelligence
  core): resolution vs physical size, minimum text size at print dpi, bleed/safe
  zone violations, ink-on-paper contrast, CMYK gamut shift, total ink coverage —
  each as a plain-English, explained violation. No model; pure, reproducible
  maths, so the same design + product always proofs the same way.
- :mod:`.pdfx` — PDF/X-3 conformance on the Ghostscript path, honest-erroring
  (never a fake-tagged PDF) when the toolchain isn't present.
- :mod:`.engine` — the orchestrator: design → preflight → bleed/marks/CMYK
  print-ready PDF (+ optional mockup), with an explainability manifest.
- :mod:`.fulfilment` — the *optional, flag-gated* fulfilment slot: an order
  schema + a provider interface behind our own seam. The default product is
  always the print-ready **file download**; no provider is wired, so the slot
  honest-errors until an operator enables one.

The deterministic-engine boundary holds throughout: nothing here calls an LLM,
and every unavailable backend honest-errors rather than faking output.
"""

from __future__ import annotations

from . import products, proof
from .products import (
    FAMILIES,
    PRINT_METHODS,
    Placement,
    PrintProduct,
    all_products,
    families,
    grouped,
    product_for,
    products_in_family,
)
from .proof import (
    ArtworkProfile,
    PreflightReport,
    Violation,
    profile_from_design,
    profile_from_image,
    run_preflight,
    run_preflight_product,
)

__all__ = [
    "products",
    "proof",
    # products
    "FAMILIES",
    "PRINT_METHODS",
    "Placement",
    "PrintProduct",
    "all_products",
    "product_for",
    "products_in_family",
    "families",
    "grouped",
    # proof
    "ArtworkProfile",
    "PreflightReport",
    "Violation",
    "run_preflight",
    "run_preflight_product",
    "profile_from_image",
    "profile_from_design",
]
