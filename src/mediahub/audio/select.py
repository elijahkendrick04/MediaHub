"""audio/select.py — AI music selection to match a reel's emotional arc (1.8).

Picking the *right* track for a reel is a judgement — "this run is three gold
medals and a club record, it wants something triumphant, not a calm pad" — so it
goes through the AI (``media_ai``), exactly as the rest of MediaHub's
judgement surfaces do, and **honest-errors** when no provider is configured. It
is never a hidden hardcoded rule pretending to be smart.

The deterministic content-hash pick (``AudioLibrary.pick``) is the explicit
no-key floor: a stable, reproducible spread across the eligible pool, returned
with ``method="deterministic"`` so the manifest is honest about which path ran.
That mirrors how ``visual/audio_mux`` already picks a bed when no AI is in play —
a legitimate deterministic default, not a fabricated judgement.

What's deterministic here vs. AI:

* **Deterministic** — :func:`describe_arc` summarises the reel's emotional
  content from the cards' own achievement labels/types (medals, PBs, records).
  This is input preparation over verified facts, no invention.
* **AI** — :func:`select_track` hands that summary plus the candidate tracks'
  mood/energy/tags to ``media_ai`` and asks which track best fits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from mediahub.audio.library import AudioLibrary, AudioTrack


class AudioSelectionUnavailable(RuntimeError):
    """No AI provider could choose a track — caller falls back to the floor."""


# Achievement type → mood words, used only to *describe* the reel for the model
# (deterministic input prep over the cards' own verified types — not a pick).
_TYPE_MOOD: dict[str, str] = {
    "medal": "triumphant, celebratory",
    "gold": "triumphant, celebratory",
    "record": "momentous, proud",
    "club_record": "momentous, proud",
    "pb": "uplifting, encouraging",
    "personal_best": "uplifting, encouraging",
    "final": "high-stakes, energetic",
    "qualification": "hopeful, forward-looking",
    "qualified": "hopeful, forward-looking",
}


def _card_type(card: dict[str, Any]) -> str:
    ach = card.get("achievement") if isinstance(card.get("achievement"), dict) else card
    for key in ("type", "achievement_type", "kind"):
        v = ach.get(key) if isinstance(ach, dict) else None
        if v:
            return str(v).strip().lower()
    return ""


def describe_arc(cards_props: list[dict]) -> str:
    """A deterministic one-line emotional summary of the reel from its cards.

    Counts the achievement types present and names the moods they imply, so the
    model gets a faithful, fact-grounded brief ("2 medals, 3 personal bests —
    triumphant, uplifting") rather than us guessing the vibe.
    """
    if not cards_props:
        return "a club highlights reel"
    counts: dict[str, int] = {}
    for card in cards_props:
        t = _card_type(card)
        if t:
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return f"a {len(cards_props)}-moment club highlights reel"
    parts = [f"{n} {t.replace('_', ' ')}" for t, n in sorted(counts.items())]
    moods = sorted({_TYPE_MOOD[t] for t in counts if t in _TYPE_MOOD})
    summary = ", ".join(parts)
    if moods:
        return f"{summary} — feels {'; '.join(moods)}"
    return summary


def _candidates_payload(tracks: list[AudioTrack]) -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "mood": list(t.mood),
            "energy": t.energy,
            "bpm": t.bpm,
            "tags": list(t.tags),
        }
        for t in tracks
    ]


def _parse_choice(raw: dict[str, Any], valid_ids: set[str]) -> Optional[str]:
    for key in ("track_id", "id", "choice", "pick"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip() in valid_ids:
            return val.strip()
    return None


def select_track(
    library: AudioLibrary,
    *,
    cards_props: Optional[list[dict]] = None,
    arc: Optional[str] = None,
    kind: str = "music",
    platform: Optional[str] = None,
    mood_hint: Optional[str] = None,
    commercial_only: bool = True,
) -> AudioTrack:
    """Choose the track that best fits the reel — AI judgement, honest-error.

    Raises :class:`AudioSelectionUnavailable` when no AI provider is configured
    or no candidate survives the filters. Callers wanting a guaranteed result
    use :func:`select_or_default`.
    """
    pool = library.tracks(kind=kind, platform=platform, commercial_only=commercial_only)
    if not pool:
        raise AudioSelectionUnavailable("no candidate tracks after filtering")

    brief = arc if arc is not None else describe_arc(cards_props or [])
    if mood_hint:
        brief = f"{brief} (operator hint: {mood_hint})"

    prompt = (
        "Choose the single best background track for a swimming club's "
        "highlights reel.\n\n"
        f"Reel: {brief}\n\n"
        "Candidate tracks (pick by mood/energy/tags fit):\n"
        f"{json.dumps(_candidates_payload(pool), ensure_ascii=False)}\n\n"
        'Return {"track_id": "<one id from the list>", "reason": "<short why>"}.'
    )
    system = (
        "You are a music supervisor for short-form sport social video. "
        "Match the track's mood and energy to the reel's emotional arc. "
        "Pick exactly one id from the candidates; never invent an id."
    )

    try:
        from mediahub.media_ai import generate_json
        from mediahub.media_ai.llm import ClaudeUnavailableError
    except Exception as exc:  # pragma: no cover - import guard
        raise AudioSelectionUnavailable(f"media_ai unavailable: {exc}") from exc

    try:
        out = generate_json(prompt, system=system, fallback={})
    except ClaudeUnavailableError as exc:
        raise AudioSelectionUnavailable("no LLM provider configured for track selection") from exc

    choice = _parse_choice(out if isinstance(out, dict) else {}, {t.id for t in pool})
    if not choice:
        raise AudioSelectionUnavailable("model returned no valid track id")
    track = library.get(choice)
    if track is None:  # pragma: no cover - defensive
        raise AudioSelectionUnavailable("chosen id not in library")
    return track


@dataclass(frozen=True)
class Selection:
    """The chosen track and how it was chosen — for the explainability manifest."""

    track: Optional[AudioTrack]
    method: str  # "ai" | "deterministic" | "none"
    arc: str = ""
    reason: str = ""


def select_or_default(
    library: AudioLibrary,
    content_key: str,
    *,
    cards_props: Optional[list[dict]] = None,
    kind: str = "music",
    platform: Optional[str] = None,
    mood_hint: Optional[str] = None,
    commercial_only: bool = True,
) -> Selection:
    """AI pick when a provider is available, else the deterministic floor.

    Always returns a :class:`Selection` (never raises): ``method="ai"`` when the
    model chose, ``"deterministic"`` for the content-hash floor, ``"none"`` when
    the pool is empty. The reel pipeline records this in its manifest so every
    render can explain why it has the bed it has.
    """
    arc = describe_arc(cards_props or [])
    try:
        track = select_track(
            library,
            cards_props=cards_props,
            arc=arc,
            kind=kind,
            platform=platform,
            mood_hint=mood_hint,
            commercial_only=commercial_only,
        )
        return Selection(track=track, method="ai", arc=arc)
    except AudioSelectionUnavailable:
        track = library.pick(
            content_key, kind=kind, platform=platform, commercial_only=commercial_only
        )
        return Selection(track=track, method="deterministic" if track else "none", arc=arc)


__all__ = [
    "AudioSelectionUnavailable",
    "Selection",
    "describe_arc",
    "select_track",
    "select_or_default",
]
