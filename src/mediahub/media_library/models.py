"""MediaAsset dataclass — the single source of truth for an uploaded image.

Sport-agnostic. `linked_athlete_ids` / `linked_meet_ids` are opaque strings.
Fields are *all optional with defaults* so partial dicts deserialise cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

ASSET_TYPES = (
    "athlete_headshot",
    "athlete_action",
    "team_photo",
    "venue_photo",
    "logo",
    "sponsor_logo",
    "brand_pattern",
    "exemplar_post",
    "ai_generated",  # P6.3: produced/edited by the generative-imagery seam
    "footage",  # 1.6: an uploaded/recorded video clip for the video suite
    "other",
)

PERMISSION_STATUSES = (
    "user_owned",
    "approved_public",
    "approved_by_club",
    "approved_by_photographer",
    "needs_approval",
    "needs_parental_consent",
    "internal_only",
    "do_not_use",
    "unknown",
)

APPROVAL_STATUSES = ("approved", "draft", "rejected", "pending")

ORIENTATIONS = ("portrait", "landscape", "square", "unknown")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MediaAsset:
    """A single image asset in the media library."""

    id: str
    filename: str
    path: str  # absolute or workspace-relative
    type: str = "other"  # one of ASSET_TYPES
    description_raw: str = ""  # what the user typed
    description_parsed: dict = field(default_factory=dict)  # AI-extracted tags
    linked_athlete_ids: list[str] = field(default_factory=list)
    linked_athlete_names: list[str] = field(default_factory=list)
    linked_meet_ids: list[str] = field(default_factory=list)
    linked_venue: Optional[str] = None
    linked_event: Optional[str] = None
    profile_id: Optional[str] = None  # club/team this belongs to
    permission_status: str = "unknown"
    approval_status: str = "draft"
    width: int = 0
    height: int = 0
    orientation: str = "unknown"
    dominant_colours: list[str] = field(default_factory=list)
    has_face: Optional[bool] = None
    safe_for_minors: bool = True
    cutout_path: Optional[str] = None  # set after rembg
    edit_recipe: dict = field(default_factory=dict)  # 1.3: non-destructive photo-edit recipe
    media_meta: dict = field(default_factory=dict)  # 1.6: video probe (duration_ms, fps, has_audio…)
    source_url: Optional[str] = None  # web-sourced (e.g. Wikimedia)
    source_attribution: Optional[str] = None
    source_licence: Optional[str] = None
    photographer: Optional[str] = None
    uploaded_at: str = field(default_factory=_now)
    uploaded_by: Optional[str] = None
    used_in: list[str] = field(default_factory=list)  # generated_visual ids
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    # ---- factory helpers ----

    @classmethod
    def from_dict(cls, d: dict) -> "MediaAsset":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean: dict[str, Any] = {}
        for k, v in d.items():
            if k not in known:
                continue
            if k in ("description_parsed", "edit_recipe", "media_meta") and isinstance(v, str):
                try:
                    v = json.loads(v) if v else {}
                except Exception:
                    v = {}
            # A migrated-in NULL dict column → the empty-dict default
            # (keeps the field honouring its declared dict type).
            if k in ("edit_recipe", "media_meta") and v is None:
                v = {}
            if k in (
                "linked_athlete_ids",
                "linked_athlete_names",
                "linked_meet_ids",
                "dominant_colours",
                "used_in",
                "tags",
            ) and isinstance(v, str):
                try:
                    v = json.loads(v) if v else []
                except Exception:
                    v = [s.strip() for s in v.split(",") if s.strip()]
            clean[k] = v
        # ensure required
        if "id" not in clean:
            clean["id"] = ""
        if "filename" not in clean:
            clean["filename"] = ""
        if "path" not in clean:
            clean["path"] = ""
        return cls(**clean)

    def to_dict(self) -> dict:
        return asdict(self)

    def is_usable_for_post(self) -> bool:
        """True if permission and approval allow public-facing use."""
        if self.permission_status in ("do_not_use", "needs_parental_consent"):
            return False
        if self.approval_status == "rejected":
            return False
        return True


__all__ = [
    "MediaAsset",
    "ASSET_TYPES",
    "PERMISSION_STATUSES",
    "APPROVAL_STATUSES",
    "ORIENTATIONS",
]
