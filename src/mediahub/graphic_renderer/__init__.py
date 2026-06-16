"""graphic_renderer — HTML/CSS templates + Playwright HTML→PNG renderer + format variants."""

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
]
