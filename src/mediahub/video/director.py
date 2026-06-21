"""video/director.py — the AI judgement that turns clips into a reel plan (1.6).

Everything *factual* about the footage path is deterministic: which two seconds
are the highlight (``moments``), where the subject is (``reframe``), the timeline
maths (``edl``), the colour science (``edl.ColorAdjust``), the soundtrack DSP
(``audio_post``). What is left is **judgement** — given the moments we already
detected across one or several clips, *which order tells the best story, which
look suits the vibe, what music mood fits, and what hook goes on screen.* That is
exactly the kind of creative call MediaHub routes through the AI, honestly.

So this module is the footage twin of the reel's creative director:

* It **never fabricates a fact.** It only ever *orders and selects among the
  moments it is handed* (and names a look/mood/hook). It cannot invent an event,
  a time, or a result — the moments came from deterministic detection.
* It is **honest about the AI.** With no provider configured it returns a
  deterministic default plan (strongest moments first, a tasteful default look),
  marked ``source="default"`` — never a pretend-AI plan, never an error that
  blocks the reel.
* Its output is **validated and clamped** to the real clips/moments before use,
  so a hallucinated index can never reach the renderer.

The plan is data (:class:`ReelPlan`); ``reel_builder`` turns it into an EDL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mediahub.video.edl import LOOKS

DEFAULT_LOOK = "punch"
DEFAULT_MOOD = "uplifting"
MAX_BEATS = 5
_PER_CLIP_CAP = 2  # at most N beats from one clip, so a montage keeps variety
MIN_WEIGHT = 0.6  # a beat can be tightened to 60% of its detected length…
MAX_WEIGHT = 1.8  # …or held up to 180% (the "money shot" earns more screen time)


def clamp_weight(value: object) -> float:
    """Coerce a model's per-beat emphasis into the safe ``[MIN, MAX]`` range.

    The weight is the director's *virality judgement* over a real moment — how
    much screen time it deserves relative to the others — never a fabricated fact.
    Anything unparseable falls back to ``1.0`` (even emphasis), so a missing or
    garbage weight leaves the beat at its detected length.
    """
    try:
        w = float(value)
    except (TypeError, ValueError):
        return 1.0
    if w != w:  # NaN
        return 1.0
    return max(MIN_WEIGHT, min(MAX_WEIGHT, w))


@dataclass(frozen=True)
class ClipBeat:
    """One beat of the reel: clip ``asset_index``'s moment ``moment_index``.

    ``weight`` is the director's per-beat emphasis (1.0 = the moment's own
    detected length; >1 holds it longer, <1 tightens it) — the AI's cross-clip
    virality judgement turned into screen time. It only *scales* a real moment;
    it never invents one.
    """

    asset_index: int
    moment_index: int
    weight: float = 1.0

    def to_dict(self) -> dict:
        d = {"asset_index": self.asset_index, "moment_index": self.moment_index}
        # Omit an even (1.0) weight so an un-weighted plan serialises exactly as
        # before this feature existed (and reel cache keys stay byte-identical).
        if self.weight != 1.0:
            d["weight"] = round(self.weight, 3)
        return d


@dataclass
class ReelPlan:
    """A validated plan for assembling a reel from detected moments.

    ``order`` is the beat sequence; ``look`` is a named grade; ``music_mood`` is
    a mood word for the bed; ``hook`` is a short on-screen title ("" = none);
    ``rationale`` explains the choice; ``source`` is ``"ai"`` or ``"default"``.
    """

    order: list[ClipBeat] = field(default_factory=list)
    look: str = DEFAULT_LOOK
    music_mood: str = DEFAULT_MOOD
    hook: str = ""
    rationale: str = ""
    source: str = "default"

    def to_dict(self) -> dict:
        return {
            "order": [b.to_dict() for b in self.order],
            "look": self.look,
            "music_mood": self.music_mood,
            "hook": self.hook,
            "rationale": self.rationale,
            "source": self.source,
        }


def _moment_score(m: dict) -> float:
    try:
        return float(m.get("score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def default_order(clips_meta: list[dict], *, max_beats: int = MAX_BEATS) -> list[ClipBeat]:
    """Deterministic beat order: strongest moments first, capped per clip. Pure.

    Flattens every (clip, moment) pair, ranks by the moment's deterministic
    score, and greedily takes the top ``max_beats`` while keeping at most
    ``_PER_CLIP_CAP`` from any one clip — so a single multi-moment clip still
    yields variety and a multi-clip montage spreads across sources. Ties break by
    (clip index, moment index) so the order is fully reproducible.
    """
    pairs: list[tuple[float, int, int]] = []
    for ci, cm in enumerate(clips_meta):
        for mi, m in enumerate(cm.get("moments") or []):
            pairs.append((_moment_score(m), ci, mi))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    out: list[ClipBeat] = []
    per_clip: dict[int, int] = {}
    for _score, ci, mi in pairs:
        if len(out) >= max_beats:
            break
        if per_clip.get(ci, 0) >= _PER_CLIP_CAP:
            continue
        out.append(ClipBeat(ci, mi))
        per_clip[ci] = per_clip.get(ci, 0) + 1
    return out


def _default_plan(clips_meta: list[dict], *, max_beats: int) -> ReelPlan:
    return ReelPlan(
        order=default_order(clips_meta, max_beats=max_beats),
        look=DEFAULT_LOOK,
        music_mood=DEFAULT_MOOD,
        hook="",
        rationale="Strongest detected moments first (no AI provider configured).",
        source="default",
    )


def _sanitise_hook(text: object) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip().strip('"').strip()
    return s[:60]


def _valid_beats(raw_order: object, clips_meta: list[dict], *, max_beats: int) -> list[ClipBeat]:
    """Coerce a model's ``order`` into real, in-range, de-duplicated beats.

    A per-item ``weight`` (optional) is clamped to the safe emphasis range; an
    absent or unparseable weight defaults to even (1.0). The clip/moment indices
    are validated against the real clips so a hallucinated index can never reach
    the renderer.
    """
    beats: list[ClipBeat] = []
    seen: set[tuple[int, int]] = set()
    n_clips = len(clips_meta)
    for item in raw_order or []:
        try:
            ci = int(item.get("clip"))
            mi = int(item.get("moment"))
        except (AttributeError, TypeError, ValueError):
            continue
        if not (0 <= ci < n_clips):
            continue
        n_moments = len(clips_meta[ci].get("moments") or [])
        if not (0 <= mi < n_moments):
            continue
        if (ci, mi) in seen:
            continue
        seen.add((ci, mi))
        beats.append(ClipBeat(ci, mi, weight=clamp_weight(item.get("weight"))))
        if len(beats) >= max_beats:
            break
    return beats


def _clips_payload(clips_meta: list[dict]) -> list[dict]:
    """The compact, fact-only view of the clips handed to the model."""
    payload: list[dict] = []
    for ci, cm in enumerate(clips_meta):
        moments = []
        for mi, m in enumerate(cm.get("moments") or []):
            moments.append(
                {
                    "moment": mi,
                    "reason": str(m.get("reason", "")),
                    "kind": str(m.get("kind", "")),
                    "score": round(_moment_score(m), 3),
                    "label": str(m.get("label", "")),
                    "seconds": round(
                        max(0, int(m.get("end_ms", 0)) - int(m.get("start_ms", 0))) / 1000, 1
                    ),
                }
            )
        payload.append(
            {
                "clip": ci,
                "name": str(cm.get("name", f"clip {ci}")),
                "orientation": str(cm.get("orientation", "")),
                "moments": moments,
            }
        )
    return payload


def plan_reel(
    clips_meta: list[dict],
    *,
    brief_context: str = "",
    max_beats: int = MAX_BEATS,
) -> ReelPlan:
    """Plan a reel from per-clip detected moments. AI judgement; honest default.

    ``clips_meta`` is one dict per source clip: ``{"name", "orientation",
    "moments": [moment.to_dict(), ...]}``. Returns a validated :class:`ReelPlan`.
    With no AI provider (or on any provider/parse error) it returns the
    deterministic default plan rather than raising — the reel is always
    buildable; the AI only makes it *better*.
    """
    if not clips_meta or all(not (c.get("moments") or []) for c in clips_meta):
        return ReelPlan(order=[], source="default", rationale="No detected moments to arrange.")

    max_beats = max(1, min(MAX_BEATS, int(max_beats)))
    try:
        from mediahub.media_ai import llm as _llm

        if not _llm.is_available():
            return _default_plan(clips_meta, max_beats=max_beats)

        prompt = (
            "You are a sports club's short-form video editor. Below are clips with "
            "their already-detected highlight moments (facts from analysis). Choose "
            "the best ORDER of moments for a punchy vertical reel, a colour LOOK, a "
            "music MOOD, and a short on-screen HOOK.\n\n"
            "Hard rules:\n"
            "- Only ORDER and SELECT among the moments given. NEVER invent an event, "
            "time, name, or result.\n"
            f"- Use at most {max_beats} beats. Lead with the strongest hook.\n"
            "- Give each beat a 'weight' from "
            f"{MIN_WEIGHT} to {MAX_WEIGHT}: ~1.0 normal, higher for the standout "
            '"money shot" (it earns more screen time), lower to tighten a filler beat.\n'
            f"- 'look' MUST be one of: {sorted(LOOKS)}.\n"
            "- 'hook' is <= 6 words, grounded only in the context; '' if unsure.\n\n"
            f"Context: {brief_context or 'club sport footage'}\n"
            f"Clips: {json.dumps(_clips_payload(clips_meta))}\n\n"
            'Return JSON: {"order":[{"clip":int,"moment":int,"weight":float}],'
            '"look":str,"music_mood":str,"hook":str,"why":str}'
        )
        data = _llm.generate_json(prompt, max_tokens=400, fallback={})
    except Exception:
        # ClaudeUnavailableError or any provider/parse error → deterministic plan.
        return _default_plan(clips_meta, max_beats=max_beats)

    beats = _valid_beats(data.get("order"), clips_meta, max_beats=max_beats)
    if not beats:
        # The model answered but gave nothing usable — keep the honest default
        # order, but carry its look/mood/hook if those are valid.
        beats = default_order(clips_meta, max_beats=max_beats)

    look = str(data.get("look", "")).strip().lower()
    if look not in LOOKS:
        look = DEFAULT_LOOK
    mood = (
        re.sub(r"[^a-z ]", "", str(data.get("music_mood", "")).strip().lower())[:24] or DEFAULT_MOOD
    )
    return ReelPlan(
        order=beats,
        look=look,
        music_mood=mood,
        hook=_sanitise_hook(data.get("hook")),
        rationale=_sanitise_hook(data.get("why"))[:200] or "AI-ordered reel.",
        source="ai",
    )


def suggest_hook(context: str) -> str:
    """A short on-screen hook via the AI — judgement, so optional and honest.

    Returns ``""`` when no provider is configured. Like ``moments.label_moment``:
    decoration over the facts, never a fabricated claim, never reel-blocking.
    """
    try:
        from mediahub.media_ai import llm as _llm

        if not _llm.is_available():
            return ""
        out = _llm.generate(
            "In <= 6 words, write a punchy, literal on-screen hook for a sports club "
            "reel. Be factual; no hype words you can't support.\n"
            f"Context: {context or 'club sport highlights'}",
            max_tokens=20,
        )
        return _sanitise_hook(out)
    except Exception:
        return ""


__all__ = [
    "DEFAULT_LOOK",
    "DEFAULT_MOOD",
    "MAX_BEATS",
    "MIN_WEIGHT",
    "MAX_WEIGHT",
    "ClipBeat",
    "ReelPlan",
    "clamp_weight",
    "default_order",
    "plan_reel",
    "suggest_hook",
]
