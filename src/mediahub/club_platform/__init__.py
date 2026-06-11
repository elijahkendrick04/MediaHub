"""
club_platform — V7 content type registry and implementation layer.

Exposes:
  ContentType, ContentTypeMeta, REGISTRY  (content_types)
  MeetRecapContentType                    (meet_recap)
  AthleteSpotlightContentType             (athlete_spotlight)
  stub content types                      (stubs)
"""

from .content_types import ContentType, ContentTypeMeta, REGISTRY
from .meet_recap import MeetRecapContentType
from .athlete_spotlight import AthleteSpotlightContentType, build_spotlight_pack
from .stubs import WeekendPreviewStub, SponsorPostStub, SessionUpdateStub

__all__ = [
    "ContentType",
    "ContentTypeMeta",
    "REGISTRY",
    "MeetRecapContentType",
    "AthleteSpotlightContentType",
    "build_spotlight_pack",
    "WeekendPreviewStub",
    "SponsorPostStub",
    "SessionUpdateStub",
]
