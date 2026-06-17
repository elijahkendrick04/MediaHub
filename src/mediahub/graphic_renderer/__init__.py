"""graphic_renderer — HTML/CSS templates + Playwright HTML→PNG renderer + format variants.

Also exposes the G1.13 SVG vector export path (``svg_export``): an editable,
outlined-font SVG counterpart for each rendered PNG.
"""

from .render import (
    render_brief,
    render_html_to_png,
    render_pool_session,
    warm_render_pool,
    shutdown_render_pool,
    render_pool_active,
    RenderResult,
    GeneratedVisual,
)
from .variants import render_all_formats, FORMAT_SIZES
from .svg_export import (
    SvgExportError,
    SvgExportUnavailable,
    export_svg_alongside,
    html_to_svg,
    render_html_to_svg,
    svg_sidecar_path,
)

__all__ = [
    "render_brief",
    "render_html_to_png",
    "render_pool_session",
    "warm_render_pool",
    "shutdown_render_pool",
    "render_pool_active",
    "render_all_formats",
    "RenderResult",
    "GeneratedVisual",
    "FORMAT_SIZES",
    "html_to_svg",
    "render_html_to_svg",
    "export_svg_alongside",
    "svg_sidecar_path",
    "SvgExportError",
    "SvgExportUnavailable",
]
