"""
voice/multi_tone_renderer.py — V7.5

Pre-renders one caption per LEARNED voice profile for each achievement
card. Voices live in ``data/voices/`` (and ``data/voices/seed/``) on
disk; the engine never assumes any fixed set of tone names.

Public API kept for backwards compatibility:

    from mediahub.voice.multi_tone_renderer import render_all_tones

    captions = render_all_tones(achievement, profile, content_type)

It now returns a dict mapping ``voice_id -> {display_name, caption}``
(plus, for backwards compatibility with V7.4 callers that expected the
old ``{tone: {headline, body, cta}}`` shape, the same headline/body/cta
keys are populated from the rendered caption text).
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mediahub.web.club_profile import ClubProfile


def _achievement_payload(achievement: dict) -> dict:
    """Extract the swim fields the learned-voice renderer expects."""
    src = achievement.get("achievement") or achievement
    swimmer_name = (src.get("swimmer_name", "") or "").strip()
    parts = swimmer_name.split(" ", 1)
    return {
        "swimmer_first": parts[0] if parts else "",
        "swimmer_last": parts[1] if len(parts) > 1 else "",
        "event": src.get("event", ""),
        "time": src.get("time", "") or src.get("swim_time", ""),
        "pb": src.get("prev_pb", ""),
        "club": src.get("club", ""),
        "meet": src.get("meet", "") or achievement.get("meet", ""),
        "place": src.get("place", ""),
        "headline": src.get("headline", ""),
    }


def render_all_tones(
    achievement: dict,
    profile: "ClubProfile",
    content_type: str = "meet_recap",
) -> dict[str, dict[str, str]]:
    """
    Render one caption per learned voice profile available on disk.

    Parameters mirror the V7.4 signature for compatibility, but
    ``profile`` and ``content_type`` are ignored — the voice set is data,
    not derived from the club profile.

    Returns a dict shaped like::

        {
            "<voice_id>": {
                "display_name": str,
                "caption": str,
                "headline": str,   # mirror of caption for V7.4 callers
                "body": "",
                "cta": "",
            },
            ...
        }
    """
    try:
        from mediahub.voice.learned.store import list_voices
        from mediahub.voice.learned.render import render_caption
    except Exception:
        return {}

    payload = _achievement_payload(achievement)
    out: dict[str, dict[str, str]] = {}
    for vp in list_voices():
        try:
            captions = render_caption(payload, vp, n_variants=1, seed=0)
            text = captions[0] if captions else ""
        except Exception:
            text = ""
        out[vp.voice_id] = {
            "display_name": vp.display_name,
            "caption": text,
            "headline": text,
            "body": "",
            "cta": "",
        }
    return out


def render_all_tones_for_run(
    recognition_report: dict,
    profile: "ClubProfile",
    content_type: str = "meet_recap",
) -> dict:
    """Apply :func:`render_all_tones` to every ranked achievement."""
    ranked = recognition_report.get("ranked_achievements") or []
    for ra in ranked:
        if not ra.get("voice_captions"):
            ra["voice_captions"] = render_all_tones(ra, profile, content_type)
    return recognition_report
