"""
Stub content types — placeholder ContentType subclasses that render a
real HTML page explaining the input contract and when the feature will
ship. They are routes, not 501 pages.

Classes:
  WeekendPreviewStub
  SponsorPostStub
  SessionUpdateStub
"""
from __future__ import annotations

from .content_types import ContentType, ContentTypeMeta, REGISTRY


class _StubContentType:
    """Base for all stub content types."""

    _type: ContentType

    @classmethod
    def get_meta(cls) -> ContentTypeMeta:
        return REGISTRY[cls._type]

    @classmethod
    def is_ready(cls) -> bool:
        return False

    def render_stub_html(self) -> str:
        """Return an HTML fragment (body only) for the stub page."""
        meta = self.get_meta()
        return f"""
<h1>{meta.title}</h1>
<p class="dim">{meta.description}</p>

<div class="card">
  <h2>What you'll need</h2>
  <p style="white-space:pre-wrap;font-size:14px;color:var(--ink-dim)">{meta.input_contract}</p>
</div>

<div class="card">
  <h2 style="color:var(--warn)">Coming soon</h2>
  <p>This content type is on the roadmap. When it ships, you'll be able to
  access it from the <strong>Make</strong> page.</p>
  <p class="muted" style="font-size:13px">
    In the meantime, use <strong>Meet Recap</strong> to turn full meet results
    into ranked content cards, or <strong>Athlete Spotlight</strong> to focus
    on a single swimmer's weekend.
  </p>
</div>
"""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} ready=False>"


class WeekendPreviewStub(_StubContentType):
    _type = ContentType.WEEKEND_PREVIEW


class SponsorPostStub(_StubContentType):
    _type = ContentType.SPONSOR_POST


class SessionUpdateStub(_StubContentType):
    _type = ContentType.SESSION_UPDATE
