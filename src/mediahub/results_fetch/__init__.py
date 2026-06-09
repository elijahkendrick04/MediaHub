"""mediahub.results_fetch — read a competition's results site like a person.

Paste a results-page URL and this package reads the site the way someone with a
browser would: a cheap static fetch first, escalating to a headless-Chromium
render only when the page needs JavaScript to show its data, and (in a later
tier) letting the AI *look* at pages that still won't yield a machine-readable
table. The harvested pages land in a local mirror that is zipped and handed to
the existing upload pipeline unchanged.

This module is the entry point for one page read:

    >>> result = read_page("https://example.org/results/")
    >>> result.tier          # "static" or "rendered"
    >>> result.trigger       # which escalation trigger fired (or None)
    >>> result.page.content  # the bytes the mirror keeps

Everything is inert: importing it adds no route and changes no behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .fetch import (
    ALLOWED_CONTENT_TYPES,
    FetchBackend,
    FetchedPage,
    FetchLimits,
    StaticBackend,
    count_result_shaped_tokens,
    looks_like_html,
    render_trigger,
    visible_text,
)
from .rendered import (
    CapturedResponse,
    RenderedBackend,
    RenderedPage,
    Scope,
    in_scope,
    same_host,
    scope_for,
)

__all__ = [
    "read_page",
    "ReadResult",
    "FetchLimits",
    "FetchedPage",
    "RenderedPage",
    "FetchBackend",
    "StaticBackend",
    "RenderedBackend",
    "CapturedResponse",
    "Scope",
    "scope_for",
    "in_scope",
    "same_host",
    "count_result_shaped_tokens",
    "looks_like_html",
    "visible_text",
    "render_trigger",
    "ALLOWED_CONTENT_TYPES",
]


@dataclass
class ReadResult:
    """The outcome of reading one URL across the static→rendered tiers.

    ``page`` is the harvested resource (``None`` only if even the static fetch
    failed). ``tier`` is the tier the returned ``page`` came from. ``trigger``
    records which escalation trigger fired, if any. ``render_failed`` is True
    when escalation was warranted but the render did not produce a usable page
    (browser missing, budget hit, navigation error) and we fell back to the
    static result — surfaced honestly rather than hidden. ``static_page`` is the
    pre-escalation static page when the returned ``page`` is a render (so the
    crawler can union links the render may have dropped); it is ``None`` when the
    static page IS the returned page.
    """

    url: str
    page: Optional[FetchedPage]
    tier: str
    trigger: Optional[str] = None
    render_failed: bool = False
    static_page: Optional[FetchedPage] = None

    @property
    def ok(self) -> bool:
        return self.page is not None

    @property
    def captures(self) -> list[CapturedResponse]:
        page = self.page
        return list(page.captures) if isinstance(page, RenderedPage) else []


def read_page(
    url: str,
    *,
    limits: Optional[FetchLimits] = None,
    static: Optional[FetchBackend] = None,
    rendered: Optional[RenderedBackend] = None,
) -> ReadResult:
    """Read one URL, escalating static → rendered only as far as needed.

    Tries Tier A (static). If the result is HTML that is thin, a JS shell, or
    carries no result-shaped tokens, escalates to Tier B (rendered). A shared
    ``rendered`` backend should be passed by the crawler so a whole crawl uses a
    single browser and honours one render budget; if omitted, a throwaway
    backend is created for this call and torn down afterwards.
    """
    limits = limits or FetchLimits.from_env()
    static = static or StaticBackend(limits)

    fetched = static.fetch(url)
    if fetched is None:
        return ReadResult(url=url, page=None, tier="static", trigger=None)

    trigger = render_trigger(fetched, limits)
    if trigger is None:
        return ReadResult(url=url, page=fetched, tier="static", trigger=None)

    backend = rendered
    own_backend = False
    if backend is None:
        backend = RenderedBackend(limits)
        own_backend = True
    try:
        rendered_page = backend.fetch(url)
    finally:
        if own_backend:
            backend.close()

    if rendered_page is None:
        # Escalation was warranted but the render didn't land — keep the static
        # page (better than nothing) and flag the failure honestly.
        return ReadResult(url=url, page=fetched, tier="static", trigger=trigger, render_failed=True)
    return ReadResult(
        url=url,
        page=rendered_page,
        tier="rendered",
        trigger=trigger,
        static_page=fetched,
    )
