"""
Club profile system — replaces V3's per-club hardcoded filter.

A ClubProfile captures everything specific to one client club:
  - canonical club codes that mean "us"
  - exclusion codes (e.g. host club of a meet we attend)
  - human display name + brand colour
  - tone hint for caption style
  - known asa_ids (built up over time from PB store + prior meets)
  - "important" qualification standard ids to surface first
  - (V7) brand_kit dict, tone str, caption_templates dict, achievement_priorities dict

Profiles live as JSON files under /club_profiles/. There is no
auto-seeded demo club; the empty-state UI prompts the user to create
their own profile.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ClubProfile:
    profile_id: str                       # short slug, e.g. 'your-club'
    display_name: str                     # human name, e.g. 'Your Club Swimming'
    short_name: str = ""                  # e.g. 'Your Club'
    club_codes: list[str] = field(default_factory=list)   # canonical codes meaning "us"
    exclude_codes: list[str] = field(default_factory=list) # e.g. host clubs to skip
    known_asa_ids: list[str] = field(default_factory=list)
    brand_primary: str = "#A30D2D"
    brand_secondary: str = "#000000"
    caption_tone: str = "warm-club"       # warm-club | sharp-news | playful-fan
    important_standards: list[str] = field(default_factory=list)
    important_swimmers: list[str] = field(default_factory=list)  # asa_ids to spotlight
    governing_body: str = ""
    country: str = ""
    notes: str = ""

    # ---- V7 extensions (all optional with defaults so old JSON still loads) ----

    # BrandKit dict (matches brand.kit.BrandKit.to_dict() schema)
    brand_kit: dict = field(default_factory=dict)

    # Active tone: "warm-club" | "hype" | "data-led"
    tone: str = "warm-club"

    # Caption templates: {content_type: {tone_str: {slot: template_str}}}
    caption_templates: dict = field(default_factory=dict)

    # Per-achievement-type priority multipliers for the V5 ranker
    # Keys match Achievement.type strings; "_default" is the fallback.
    achievement_priorities: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClubProfile":
        # Tolerant load: ignore unknown keys, default missing ones.
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    # ----- runtime: matches V3 ClubRoster API for drop-in replacement -----

    def is_ours(self, club_code: Optional[str], asa_id: Optional[str]) -> bool:
        if club_code and club_code in self.exclude_codes:
            return False
        if club_code:
            return club_code in self.club_codes
        if asa_id and asa_id in self.known_asa_ids:
            return True
        return False

    def filter_results(self, results, attr_club: str = "club_code",
                       attr_asa: str = "asa_id") -> list:
        keep = []
        for r in results:
            cc = getattr(r, attr_club, None)
            # Result has swimmer_key, not asa_id directly — caller passes
            # already-resolved asa via attr_asa name when needed.
            asa = getattr(r, attr_asa, None) if hasattr(r, attr_asa) else None
            if self.is_ours(cc, asa):
                keep.append(r)
        return keep

    # ---- V7 helpers ----

    def get_achievement_priority(self, achievement_type: str) -> float:
        """Return the club-configured priority multiplier for an achievement type."""
        priorities = self.achievement_priorities
        if not priorities:
            return 1.0
        return float(priorities.get(achievement_type, priorities.get("_default", 1.0)))

    def get_brand_kit(self):
        """Return a BrandKit instance synthesised from this profile's data."""
        from mediahub.brand.kit import BrandKit
        bk_data = self.brand_kit or {}
        if not bk_data:
            bk_data = {
                "profile_id": self.profile_id,
                "display_name": self.display_name,
                "primary_colour": self.brand_primary,
                "secondary_colour": self.brand_secondary,
                "governing_body": self.governing_body or None,
                "short_name": self.short_name or None,
            }
        return BrandKit.from_dict({"profile_id": self.profile_id, **bk_data})

    def get_tone(self):
        """Return the active Tone enum for this profile."""
        from mediahub.brand.tone import tone_from_str
        return tone_from_str(self.tone or self.caption_tone or "warm-club")


# ---------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------

def _profiles_dir() -> Path:
    # Allow override for tests / deployment.
    p = os.environ.get("SWIM_CONTENT_PROFILES_DIR")
    if p:
        d = Path(p)
    else:
        d = Path(__file__).resolve().parents[1] / "club_profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list[ClubProfile]:
    out = []
    for f in sorted(_profiles_dir().glob("*.json")):
        try:
            out.append(ClubProfile.from_dict(json.loads(f.read_text())))
        except Exception:
            continue
    return out


def load_profile(profile_id: str) -> Optional[ClubProfile]:
    p = _profiles_dir() / f"{profile_id}.json"
    if not p.exists():
        return None
    try:
        return ClubProfile.from_dict(json.loads(p.read_text()))
    except Exception:
        return None


def save_profile(profile: ClubProfile) -> Path:
    p = _profiles_dir() / f"{profile.profile_id}.json"
    p.write_text(json.dumps(profile.to_dict(), indent=2))
    return p


# Default achievement-priority weights (used when a profile is
# created via seed_coma_profile_if_empty or any other helper).
# These are generic and not tied to any specific club.
_DEFAULT_PRIORITIES = {
    "pb_confirmed": 1.5,
    "first_sub_barrier": 1.3,
    "biggest_drop_of_meet": 1.3,
    "medal_gold": 1.0,
    "medal_silver": 0.8,
    "medal_bronze": 0.6,
    "qualifying_time": 0.7,
    "qual_hit_in_window": 0.7,
    "qual_hit_out_of_window": 0.5,
    "top_of_field_top_3": 0.7,
    "top_of_field_top_5": 0.6,
    "top_of_field_top_10": 0.5,
    "fastest_since_date": 1.0,
    "multi_pb_weekend": 1.2,
    "return_to_form": 1.1,
    "_default": 1.0,
}


def seed_default_profiles() -> None:
    """
    V8.1: never auto-seeds any specific club. Empty-state UI prompts
    the user to create their own profile (see web.py).
    """
    return


def seed_coma_profile_if_empty() -> ClubProfile:
    """
    Seed City of Manchester Aquatics profile when explicitly requested.
    Returns the profile (existing or freshly created).
    """
    existing = load_profile("coma")
    if existing:
        return existing
    profile = ClubProfile(
        profile_id="coma",
        display_name="City of Manchester Aquatics",
        short_name="COMA",
        club_codes=["CMA", "Co Manch Aq", "COMA"],
        brand_primary="#003DA5",
        brand_secondary="#FFD700",
        caption_tone="warm-club",
        tone="warm-club",
        governing_body="Swim England",
        country="United Kingdom",
        notes="City of Manchester Aquatics — quick-start profile.",
        achievement_priorities=_DEFAULT_PRIORITIES,
    )
    save_profile(profile)
    return profile


def detect_likely_profile(meet_clubs: dict, meet_host_code: Optional[str]) -> Optional[str]:
    """Given a parsed meet, suggest which existing profile is most likely
    the user's club. Returns profile_id or None."""
    profiles = list_profiles()
    best = None
    best_score = 0
    for prof in profiles:
        score = 0
        for cc in prof.club_codes:
            if cc in meet_clubs:
                score += 5
            if cc == meet_host_code:
                # If the user's own club is the host, that's still ok but
                # not a higher signal than just being in the meet.
                score += 1
        if score > best_score:
            best, best_score = prof, score
    return best.profile_id if best else None
