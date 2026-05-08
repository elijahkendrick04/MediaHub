"""
V3 content card model.

Cards are the unit of human approval. A card can be:
  - 'standout_swim'        one notable swim by one swimmer
  - 'athlete_spotlight'    one swimmer with multiple notable swims (sweep / doubles / dominance)
  - 'podium_roundup'       summary of the meet's top podium performances for the club
  - 'pb_roundup'           summary of confirmed PBs across the club
  - 'qual_alert'           qualifying-standard hit(s)
  - 'weekend_in_numbers'   stat summary for the meet
  - 'recap_only'           verifiable but not strong enough for a standalone post
  - 'needs_confirmation'   information looks notable but cannot be verified yet
  - 'archive'              filtered out of the main queue

Cards carry:
  - claims (the structured story atoms — golds, PBs, qualifier hits, etc.)
  - evidence (the source log)
  - score and a short reasons array
  - caption variants (clean / team / hype)
  - approval state
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from .evidence import Evidence


# Card type constants
TYPE_STANDOUT = "standout_swim"
TYPE_SPOTLIGHT = "athlete_spotlight"
TYPE_PODIUM_ROUNDUP = "podium_roundup"
TYPE_PB_ROUNDUP = "pb_roundup"
TYPE_QUAL_ALERT = "qual_alert"
TYPE_WEEKEND_NUMBERS = "weekend_in_numbers"
TYPE_RECAP = "recap_only"
TYPE_NEEDS_CONFIRMATION = "needs_confirmation"
TYPE_ARCHIVE = "archive"

# Suggested formats
FMT_FEED = "feed_post"
FMT_STORY = "story"
FMT_SPOTLIGHT = "athlete_spotlight"
FMT_RECAP = "recap_mention"
FMT_NUMBERS = "weekend_in_numbers"
FMT_HOLD = "hold_for_confirmation"
FMT_ARCHIVE = "archive"


@dataclass
class Claim:
    """One atomic story unit on a card."""
    kind: str               # 'gold', 'silver', 'bronze', 'final', 'pb_confirmed',
                            # 'pb_likely', 'pb_unverified', 'qual_hit', 'big_drop'
    swimmer_name: str
    swimmer_tiref: Optional[str]
    event_label: str        # e.g. "100m Backstroke (LC)"
    distance: int
    stroke: str
    course: str             # LC | SC
    time_str: str
    time_sec: float
    place: Optional[int]
    round: Optional[str]    # 'P' | 'F' | 'S'
    swim_date: Optional[str]
    extra: dict = field(default_factory=dict)


@dataclass
class CaptionVariants:
    clean: str = ""
    team: str = ""
    hype: str = ""

    def all(self) -> dict[str, str]:
        return {"clean": self.clean, "team": self.team, "hype": self.hype}


@dataclass
class ContentCard:
    card_id: str
    card_type: str
    headline: str
    subhead: str = ""
    swimmer_names: list[str] = field(default_factory=list)
    primary_swimmer: Optional[str] = None
    primary_tiref: Optional[str] = None
    claims: list[Claim] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    captions: CaptionVariants = field(default_factory=CaptionVariants)
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)
    confidence: str = "medium"      # high | medium | low
    suggested_format: str = FMT_FEED
    needs_confirmation: bool = False
    bucket: str = "queue"           # queue | recap | needs_confirmation | archive
    approved: Optional[bool] = None # None | True | False
    user_caption: Optional[str] = None  # final edited caption when approved

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claims"] = [asdict(c) for c in self.claims]
        d["evidence"] = [e.to_dict() for e in self.evidence]
        d["captions"] = self.captions.all()
        return d
