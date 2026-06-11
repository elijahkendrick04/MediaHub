"""
voice/learned/induce.py — Exemplar posts → VoiceProfile.

Pure Python; no AI dependency.

Public API
----------
induce_voice(
    voice_id: str,
    display_name: str,
    exemplars: list[str],
    description: str = "",
) -> VoiceProfile
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .feature_extract import extract_features
from .models import VoiceProfile


def induce_voice(
    voice_id: str,
    display_name: str,
    exemplars: List[str],
    description: str = "",
) -> VoiceProfile:
    """
    Analyse exemplar posts and produce a VoiceProfile with induced features.

    Parameters
    ----------
    voice_id : str
        URL-safe slug for this voice, e.g. "yourclub_warm".
    display_name : str
        Human-readable label shown in the UI.
    exemplars : list[str]
        Raw post texts (3+ is recommended for reliable features).
    description : str
        Optional one-line description of this voice.

    Returns
    -------
    VoiceProfile
        A fully-populated profile ready to be saved via store.save_voice().
    """
    now = datetime.now(timezone.utc).isoformat()
    features = extract_features(exemplars)

    return VoiceProfile(
        voice_id=voice_id,
        display_name=display_name,
        description=description,
        exemplars=list(exemplars),
        features=features,
        created_at=now,
        updated_at=now,
    )


__all__ = ["induce_voice"]
