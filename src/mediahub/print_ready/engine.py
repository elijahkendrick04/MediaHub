"""The print-ready orchestrator (roadmap 1.20).

One front desk for "make this design ready for the printer". Hand it artwork and
a product, and it:

1. **proofs** the artwork against the product (:mod:`mediahub.print_ready.proof`)
   and, unless the caller forces it, refuses to render when a *blocking* error is
   found — a human still approves, but we never ship a file we know will bounce;
2. **renders** the print-ready PDF — the artwork laid into a bleed-expanded media
   box with crop/registration marks and a CMYK colour bar, reusing the existing
   ``graphic_renderer.print_export`` furniture and Playwright PDF path;
3. **converts colour** to the requested mode — RGB, true DeviceCMYK (Ghostscript),
   or PDF/X-3 — *honestly downgrading* and recording why when the toolchain isn't
   present, never faking conformance;
4. optionally composes a **mockup** preview; and
5. writes a ``<hash>.json`` **explainability manifest** beside the PDF and
   content-addresses the output so an identical request is a cache hit.

The deterministic-engine boundary holds: nothing here calls a model. The only
external touch is the optional Ghostscript hop for CMYK/PDF/X, behind an honest
error.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from mediahub.export_engine.cache import content_key
from mediahub.graphic_renderer.print_export import (
    CmykUnavailable,
    PrintGeometry,
    cmyk_convert_pdf,
    print_furniture_svg,
    render_html_to_pdf,
)
from mediahub.print_ready.pdfx import PdfXUnavailable, export_pdfx
from mediahub.print_ready.products import PrintProduct, product_for
from mediahub.print_ready.proof import (
    ArtworkProfile,
    PreflightReport,
    profile_from_design,
    profile_from_image,
    run_preflight,
)

COLOUR_MODES = ("rgb", "cmyk", "pdfx")
_DEFAULT_MARK_LEN_MM = 4.0


# ---------------------------------------------------------------------------
# Request / result value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrintRequest:
    """One print-ready export request.

    ``artwork`` is PNG/JPEG bytes or a path. ``colour_mode`` is ``rgb`` | ``cmyk``
    | ``pdfx``. ``force`` exports even when preflight finds a blocking error (a
    human has chosen to override). ``design`` enriches the proof with the brief's
    palette; ``min_text_px`` / ``full_bleed`` pass through facts the renderer knows.
    """

    artwork: Union[bytes, str, Path]
    product_slug: str
    placement_slug: str = ""
    colour_mode: str = "rgb"
    bleed_mm: float = -1.0  # <0 → use the format's own bleed
    crop_marks: bool = True
    force: bool = False
    design: Optional[dict] = None
    min_text_px: int = 0
    full_bleed: Optional[bool] = None


@dataclass(frozen=True)
class PrintResult:
    """The outcome — the file plus the honest truth about it."""

    product_slug: str
    placement_slug: str
    preflight: PreflightReport
    rendered: bool
    pdf_path: Optional[Path] = None
    colour_mode_requested: str = "rgb"
    colour_mode_used: str = "rgb"
    note: str = ""
    mockup_path: Optional[Path] = None
    from_cache: bool = False
    manifest: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        """True when a blocking error stopped the render (and it wasn't forced)."""
        return not self.rendered

    def to_dict(self) -> dict:
        return {
            "product": self.product_slug,
            "placement": self.placement_slug,
            "rendered": self.rendered,
            "blocked": self.blocked,
            "pdf": str(self.pdf_path) if self.pdf_path else None,
            "colour_mode_requested": self.colour_mode_requested,
            "colour_mode_used": self.colour_mode_used,
            "note": self.note,
            "mockup": str(self.mockup_path) if self.mockup_path else None,
            "from_cache": self.from_cache,
            "preflight": self.preflight.to_dict(),
        }


# ---------------------------------------------------------------------------
# Geometry + HTML for a raster artwork
# ---------------------------------------------------------------------------


def geometry_for_placement(
    product: PrintProduct, placement, *, bleed_mm: float = -1.0
) -> PrintGeometry:
    """A :class:`PrintGeometry` for one placement — trim = the print area (mm).

    Bleed defaults to the format's own ``bleed_mm`` (override with ``bleed_mm``
    ≥ 0). Products with no bleed (apparel/merch) get no crop-mark slug, so the
    media box is exactly the trim.
    """
    spec = placement.format
    bleed = spec.bleed_mm if bleed_mm < 0 else bleed_mm
    mark_len = _DEFAULT_MARK_LEN_MM if bleed > 0 else 0.0
    return PrintGeometry(
        trim_w_mm=placement.area_w_mm,
        trim_h_mm=placement.area_h_mm,
        bleed_mm=bleed,
        mark_len_mm=mark_len,
    )


def _data_uri_png(data: bytes) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _f(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def build_raster_print_html(
    artwork_uri: str,
    geom: PrintGeometry,
    *,
    brand: Optional[dict] = None,
    crop_marks: bool = True,
    info_label: str = "",
) -> str:
    """Lay a raster artwork into a bleed-expanded print page (pure, no I/O).

    The image covers the *bleed rectangle* (trim + bleed) so a full-bleed design
    runs naturally past the cut; the unprinted slug carries the crop/registration
    marks and CMYK colour bar via the existing ``print_furniture_svg``. When the
    geometry has no bleed (merch), the marks are skipped and the page is exactly
    the artwork at its physical size.
    """
    mw, mh = geom.media_w_mm, geom.media_h_mm
    art_offset = geom.bleed_rect_left_mm  # symmetric (== mark_len) on every side
    art_w, art_h = geom.bleed_rect_w_mm, geom.bleed_rect_h_mm
    marks_on = crop_marks and geom.bleed_mm > 0 and geom.mark_len_mm > 0
    if marks_on:
        svg = print_furniture_svg(
            geom,
            brand=brand,
            crop_marks=True,
            registration=True,
            colour_bar=True,
            info=True,
            info_label=info_label,
        )
        marks = f'<div class="marks">{svg}</div>'
    else:
        marks = ""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<style>"
        f"@page{{margin:0;size:{_f(mw)}mm {_f(mh)}mm}}"
        "html,body{margin:0;padding:0}"
        f".media{{position:relative;width:{_f(mw)}mm;height:{_f(mh)}mm;"
        "overflow:hidden;background:#FFFFFF}"
        f".art{{position:absolute;left:{_f(art_offset)}mm;top:{_f(art_offset)}mm;"
        f"width:{_f(art_w)}mm;height:{_f(art_h)}mm;object-fit:cover;object-position:center}}"
        f".marks{{position:absolute;left:0;top:0;width:{_f(mw)}mm;height:{_f(mh)}mm;"
        "pointer-events:none}"
        ".marks svg{width:100%;height:100%;display:block}"
        "</style></head><body>"
        f'<div class="media"><img class="art" src="{artwork_uri}" alt="">{marks}</div>'
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# Colour-mode conversion (honest downgrade)
# ---------------------------------------------------------------------------


def _apply_colour_mode(pdf: Path, mode: str, *, title: str) -> tuple[str, str]:
    """Convert ``pdf`` in place to ``mode``; return (mode_used, honest_note).

    Downgrades pdfx → cmyk → rgb (and cmyk → rgb) when the toolchain is missing,
    recording why — never a fake-tagged file.
    """
    if mode == "cmyk":
        try:
            cmyk_convert_pdf(pdf)
            return "cmyk", ""
        except CmykUnavailable as e:
            return "rgb", f"CMYK unavailable, kept RGB: {e}"
    if mode == "pdfx":
        try:
            export_pdfx(pdf, title=title)
            return "pdfx", ""
        except PdfXUnavailable:
            try:
                cmyk_convert_pdf(pdf)
                return "cmyk", "PDF/X unavailable; produced DeviceCMYK with marks instead."
            except CmykUnavailable:
                return "rgb", "PDF/X and CMYK unavailable; produced the RGB print PDF instead."
    return "rgb", ""


# ---------------------------------------------------------------------------
# Building the artwork profile
# ---------------------------------------------------------------------------


def _read_artwork(source: Union[bytes, str, Path]) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    return bytes(source)


def build_profile(art_bytes: bytes, request: PrintRequest) -> ArtworkProfile:
    """Profile the artwork from the image, enriched by any design/known facts."""
    base = profile_from_image(art_bytes)
    inks, paper = base.ink_colours, base.paper_colour
    if request.design:
        d = profile_from_design(request.design, width_px=base.width_px, height_px=base.height_px)
        if d.ink_colours:
            inks = d.ink_colours
        if d.paper_colour:
            paper = d.paper_colour
    full_bleed = request.full_bleed if request.full_bleed is not None else base.full_bleed
    return ArtworkProfile(
        width_px=base.width_px,
        height_px=base.height_px,
        ink_colours=inks,
        paper_colour=paper,
        min_text_px=max(0, request.min_text_px),
        content_inset_px=-1,
        full_bleed=full_bleed,
    )


# ---------------------------------------------------------------------------
# Cache + orchestration
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "print_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(art_bytes: bytes, request: PrintRequest, geom: PrintGeometry) -> str:
    import hashlib

    art_hash = hashlib.blake2b(art_bytes, digest_size=16).hexdigest()
    return content_key(
        art_hash,
        request.product_slug,
        request.placement_slug,
        request.colour_mode,
        request.crop_marks,
        round(geom.trim_w_mm, 3),
        round(geom.trim_h_mm, 3),
        round(geom.bleed_mm, 3),
    )


def prepare_print(
    request: PrintRequest,
    *,
    out_dir: Optional[Path] = None,
    mockup: bool = False,
    brand: Optional[dict] = None,
) -> PrintResult:
    """Proof → (gate) → render the print-ready PDF (+ optional mockup + manifest)."""
    product = product_for(request.product_slug)
    if product is None:
        raise ValueError(f"unknown print product: {request.product_slug!r}")
    if request.colour_mode not in COLOUR_MODES:
        raise ValueError(f"unknown colour mode: {request.colour_mode!r}")
    placement = (
        product.placement(request.placement_slug)
        if request.placement_slug
        else product.primary_placement
    )
    if placement is None:
        raise ValueError(f"product {product.slug!r} has no placement {request.placement_slug!r}")

    art_bytes = _read_artwork(request.artwork)
    profile = build_profile(art_bytes, request)
    report = run_preflight(profile, product, placement)

    # Gate: a blocking error stops the render unless the human forced it.
    if not report.ok and not request.force:
        return PrintResult(
            product_slug=product.slug,
            placement_slug=placement.slug,
            preflight=report,
            rendered=False,
            colour_mode_requested=request.colour_mode,
            colour_mode_used="",
            note="Blocked by a preflight error — fix it or export with force=True.",
            manifest=_manifest(product, placement, report, request, None, "", ""),
        )

    geom = geometry_for_placement(product, placement, bleed_mm=request.bleed_mm)
    key = _cache_key(art_bytes, request, geom)
    out = (Path(out_dir) if out_dir else _cache_dir()) / f"{key}.pdf"

    if out.exists():
        # The key holds the REQUESTED mode; the sidecar records what the cold
        # render actually achieved. Only a hit whose recorded outcome matches
        # the request may be served — a recorded downgrade (or a missing /
        # corrupt sidecar) falls through to a fresh render, so a later-installed
        # CMYK/PDF-X toolchain re-converts instead of the hit claiming a mode
        # the file doesn't have.
        cached = _cached_colour_outcome(out, request.colour_mode)
        if cached is not None:
            used, note = cached
            manifest = _manifest(product, placement, report, request, out, used, note)
            return PrintResult(
                product_slug=product.slug,
                placement_slug=placement.slug,
                preflight=report,
                rendered=True,
                pdf_path=out,
                colour_mode_requested=request.colour_mode,
                colour_mode_used=used,
                note=note,
                from_cache=True,
                mockup_path=_existing_mockup(out) if mockup else None,
                manifest=manifest,
            )

    info = f"{product.title.upper()} · {placement.label} · MediaHub"
    html = build_raster_print_html(
        _data_uri_png(art_bytes),
        geom,
        brand=brand,
        crop_marks=request.crop_marks,
        info_label=info,
    )
    render_html_to_pdf(
        html,
        out,
        width=f"{_f(geom.media_w_mm)}mm",
        height=f"{_f(geom.media_h_mm)}mm",
    )
    used, note = _apply_colour_mode(out, request.colour_mode, title=info)

    mockup_path = None
    if mockup:
        mockup_path = _compose_mockup(art_bytes, product, out)

    manifest = _manifest(product, placement, report, request, out, used, note)
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return PrintResult(
        product_slug=product.slug,
        placement_slug=placement.slug,
        preflight=report,
        rendered=True,
        pdf_path=out,
        colour_mode_requested=request.colour_mode,
        colour_mode_used=used,
        note=note,
        mockup_path=mockup_path,
        manifest=manifest,
    )


def _cached_colour_outcome(out: Path, requested: str) -> Optional[tuple[str, str]]:
    """The ``(used, note)`` a cache hit may honestly report, or ``None`` to re-render."""
    try:
        m = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        used = str(m.get("colour_mode_used") or "")
        note = str(m.get("note") or "")
    except Exception:
        return None
    if used != requested:
        return None
    return used, note


def _compose_mockup(art_bytes: bytes, product: PrintProduct, pdf_out: Path) -> Optional[Path]:
    """Compose a mockup preview; honest-skip when the scene isn't available."""
    if not product.mockup_template:
        return None
    try:
        from mediahub.mockups.compose import compose_mockup

        png = compose_mockup(art_bytes, product.mockup_template)
    except Exception:
        return None  # unknown scene / unreadable art → no preview, no crash
    path = pdf_out.with_suffix(".mockup.png")
    path.write_bytes(png)
    return path


def _existing_mockup(pdf_out: Path) -> Optional[Path]:
    path = pdf_out.with_suffix(".mockup.png")
    return path if path.exists() else None


def _manifest(
    product: PrintProduct,
    placement,
    report: PreflightReport,
    request: PrintRequest,
    pdf: Optional[Path],
    colour_used: str,
    note: str,
) -> dict:
    spec = placement.format
    return {
        "product": product.slug,
        "product_title": product.title,
        "placement": placement.slug,
        "substrate": product.substrate,
        "print_method": product.print_method,
        "trim_mm": [placement.area_w_mm, placement.area_h_mm],
        "bleed_mm": spec.bleed_mm if request.bleed_mm < 0 else request.bleed_mm,
        "target_dpi": product.target_dpi,
        "colour_mode_requested": request.colour_mode,
        "colour_mode_used": colour_used,
        "note": note,
        "fulfilment_sku": product.fulfilment_sku,
        "pdf": str(pdf) if pdf else None,
        "preflight": report.to_dict(),
    }


__all__ = [
    "COLOUR_MODES",
    "PrintRequest",
    "PrintResult",
    "prepare_print",
    "geometry_for_placement",
    "build_raster_print_html",
    "build_profile",
]
