"""
voice/store.py — Load and save VoiceProfile per club profile.

Stores voice profiles as JSON sidecar files in the club_profiles/ directory.
Format: club_profiles/<profile_id>.voice.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .profile import VoiceProfile

# Default location relative to project root
_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "club_profiles"


def _voice_path(profile_id: str, base_dir: Optional[Path] = None) -> Path:
    d = base_dir or _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{profile_id}.voice.json"


def load_voice_profile(profile_id: str, base_dir: Optional[Path] = None) -> VoiceProfile:
    """
    Load VoiceProfile for a club profile.
    Returns a default VoiceProfile if no file exists.
    """
    path = _voice_path(profile_id, base_dir)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return VoiceProfile.from_dict(data)
        except Exception:
            pass
    return VoiceProfile(profile_id=profile_id)


def save_voice_profile(vp: VoiceProfile, base_dir: Optional[Path] = None) -> None:
    """Save a VoiceProfile to disk."""
    path = _voice_path(vp.profile_id, base_dir)
    path.write_text(
        json.dumps(vp.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


__all__ = ["load_voice_profile", "save_voice_profile"]
