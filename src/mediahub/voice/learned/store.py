"""
voice/learned/store.py — Save / load / list VoiceProfile objects.

Profiles are stored as JSON files under data/voices/<voice_id>.json.
The seed directory data/voices/seed/ is read-only by convention.

Public API
----------
save_voice(profile, base_dir=None) -> Path
load_voice(voice_id, base_dir=None) -> VoiceProfile
load_voice_from_path(path) -> VoiceProfile
list_voices(base_dir=None, include_seed=True) -> list[VoiceProfile]
delete_voice(voice_id, base_dir=None) -> bool
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .models import VoiceProfile

# Default location: <project_root>/data/voices/
# store.py is at <project_root>/voice/learned/store.py → parents[2] is project root
_DEFAULT_BASE = Path(__file__).resolve().parents[4] / "data" / "voices"
if not _DEFAULT_BASE.exists():
    _DEFAULT_BASE = Path(__file__).resolve().parents[2] / "data" / "voices"


def _resolve_base(base_dir: Optional[Path]) -> Path:
    return Path(base_dir) if base_dir is not None else _DEFAULT_BASE


def _profile_path(voice_id: str, base_dir: Path) -> Path:
    return base_dir / f"{voice_id}.json"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_voice(
    profile: VoiceProfile,
    base_dir: Optional[Path] = None,
) -> Path:
    """
    Persist a VoiceProfile to <base_dir>/<voice_id>.json.

    Updates profile.updated_at before writing.
    Returns the Path written.
    """
    base = _resolve_base(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    profile.updated_at = datetime.now(timezone.utc).isoformat()
    path = _profile_path(profile.voice_id, base)
    path.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_voice(
    voice_id: str,
    base_dir: Optional[Path] = None,
) -> VoiceProfile:
    """
    Load a VoiceProfile by voice_id from <base_dir>/<voice_id>.json.

    Raises FileNotFoundError if not found.
    """
    base = _resolve_base(base_dir)
    path = _profile_path(voice_id, base)
    if not path.exists():
        raise FileNotFoundError(f"Voice profile not found: {path}")
    return load_voice_from_path(path)


def load_voice_from_path(path: Path) -> VoiceProfile:
    """Load a VoiceProfile directly from a JSON file path."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return VoiceProfile.from_dict(data)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def list_voices(
    base_dir: Optional[Path] = None,
    include_seed: bool = True,
) -> List[VoiceProfile]:
    """
    Return all saved voice profiles.

    Parameters
    ----------
    base_dir : Path, optional
        Root voices directory.  Defaults to data/voices/.
    include_seed : bool
        When True (default), also loads profiles from <base_dir>/seed/.

    Returns
    -------
    list[VoiceProfile]
        Sorted by display_name.  Seed voices are included after user voices.
    """
    base = _resolve_base(base_dir)
    profiles: List[VoiceProfile] = []

    # User-level voices (direct children of base_dir, not sub-directories)
    for path in sorted(base.glob("*.json")):
        try:
            profiles.append(load_voice_from_path(path))
        except Exception:
            pass

    # Seed voices
    if include_seed:
        seed_dir = base / "seed"
        if seed_dir.is_dir():
            for path in sorted(seed_dir.glob("*.json")):
                try:
                    vp = load_voice_from_path(path)
                    # Only include if not already loaded by voice_id
                    if not any(p.voice_id == vp.voice_id for p in profiles):
                        profiles.append(vp)
                except Exception:
                    pass

    profiles.sort(key=lambda p: p.display_name.lower())
    return profiles


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_voice(
    voice_id: str,
    base_dir: Optional[Path] = None,
) -> bool:
    """
    Remove a voice profile JSON.

    Returns True if deleted, False if file was not found.
    Does NOT delete seed files.
    """
    base = _resolve_base(base_dir)
    path = _profile_path(voice_id, base)
    if path.exists():
        path.unlink()
        return True
    return False


__all__ = [
    "save_voice",
    "load_voice",
    "load_voice_from_path",
    "list_voices",
    "delete_voice",
]
