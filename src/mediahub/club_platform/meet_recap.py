"""
MeetRecapContentType — concrete implementation that references the existing
V4 pipeline. This is the original core product: upload → ranked content cards.

No new processing happens here; this module is the registry entry that wires
the existing pipeline into the content-type abstraction layer.
"""
from __future__ import annotations

from .content_types import ContentType, ContentTypeMeta, REGISTRY


class MeetRecapContentType:
    """
    Thin wrapper around the existing V4 pipeline.

    The actual execution happens in swim_content_v4/pipeline_v4.py.
    This class provides a typed handle so that other parts of club_platform
    can introspect the content type without importing the pipeline directly.
    """

    meta: ContentTypeMeta = REGISTRY[ContentType.MEET_RECAP]
    type: ContentType = ContentType.MEET_RECAP

    @classmethod
    def get_meta(cls) -> ContentTypeMeta:
        return cls.meta

    @classmethod
    def is_ready(cls) -> bool:
        return cls.meta.is_implemented

    def __repr__(self) -> str:
        return f"<MeetRecapContentType ready={self.is_ready()}>"
