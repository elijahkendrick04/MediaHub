"""
Brand store — load and save brand kit + tone + caption templates for a profile.

Storage layout (inside the profile JSON under 'brand_kit', 'tone', 'caption_templates'):
  club_profiles/<profile_id>.json gets extended with:
    "brand_kit": { ...BrandKit fields... }
    "tone": "warm-club"
    "caption_templates": {
      "meet_recap": {
        "warm-club": {"headline": "...", "body": "...", "cta": "..."},
        ...
      },
      ...
    }
    "achievement_priorities": { ... }

We never store brand data in a separate file — it stays with the profile JSON
so there's a single source of truth.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .kit import BrandKit
from .tone import Tone, tone_from_str
from .templates import get_default_templates


def _profiles_dir() -> Path:
    p = os.environ.get("SWIM_CONTENT_PROFILES_DIR")
    if p:
        return Path(p)
    return Path(__file__).resolve().parents[1] / "club_profiles"


def load_brand(profile_id: str) -> tuple[BrandKit, Tone, dict]:
    """
    Load brand kit, active tone, and caption_templates dict from profile JSON.

    Returns (BrandKit, Tone, caption_templates_dict).
    Falls back to safe defaults if any piece is missing.
    """
    path = _profiles_dir() / f"{profile_id}.json"
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except Exception:
            pass

    # BrandKit
    bk_data = raw.get("brand_kit") or {}
    if not bk_data:
        # Synthesise from legacy fields if present
        bk_data = {
            "profile_id": profile_id,
            "display_name": raw.get("display_name", profile_id),
            "primary_colour": raw.get("brand_primary", "#A30D2D"),
            "secondary_colour": raw.get("brand_secondary", "#000000"),
            "governing_body": raw.get("governing_body"),
            "short_name": raw.get("short_name"),
        }
    kit = BrandKit.from_dict({"profile_id": profile_id, **bk_data})

    # Tone
    tone_str = raw.get("tone", "warm-club")
    tone = tone_from_str(tone_str)

    # Caption templates — dict of content_type → tone → slot → template_str
    caption_templates = raw.get("caption_templates") or {}

    return kit, tone, caption_templates


def save_brand(
    profile_id: str,
    kit: Optional[BrandKit] = None,
    tone: Optional[Tone] = None,
    templates_dict: Optional[dict] = None,
) -> None:
    """
    Persist brand kit, tone, and/or caption templates into the profile JSON.

    Partial saves are fine: pass only the pieces you want to update.
    The rest of the profile JSON is preserved.
    """
    path = _profiles_dir() / f"{profile_id}.json"
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except Exception:
            pass

    if kit is not None:
        raw["brand_kit"] = kit.to_dict()
    if tone is not None:
        raw["tone"] = tone.value
    if templates_dict is not None:
        existing = raw.get("caption_templates") or {}
        # Deep-merge: update content_type → tone → slot without clobbering unrelated keys
        for ct, tone_map in templates_dict.items():
            if ct not in existing:
                existing[ct] = {}
            for t, slot_map in tone_map.items():
                if t not in existing[ct]:
                    existing[ct][t] = {}
                existing[ct][t].update(slot_map)
        raw["caption_templates"] = existing

    path.write_text(json.dumps(raw, indent=2))
