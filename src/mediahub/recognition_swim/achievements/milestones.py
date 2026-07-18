"""
recognition_swim/achievements/milestones.py — W.1 milestone detectors.

Deterministic, registry-fed milestones: club debut (first gala), Nth race
(25/50/100/250/500) and first-ever event. The detector consumes the
precomputed ``extra["athlete_milestones"]`` context built from the W.1
athlete registry (`mediahub.athletes.registry.milestone_context`) — when
the workspace has no registry history the context is empty and the
detector stays silent, so identity remains an optional enrichment.

No LLM anywhere in identity or milestone logic (CLAUDE.md rule).
"""

from __future__ import annotations


from swim_content_v5.achievements.base import AchievementDetector
from swim_content_v5.schema import Achievement, AchievementEvidence

from mediahub.athletes.registry import normalise_name

RACE_MILESTONES = (25, 50, 100, 250, 500)

_HISTORY_CAVEAT = (
    "Race counts come from this club's logged history in MediaHub; "
    "meets never uploaded are not counted."
)


def _event_key(swim) -> str:
    """Same composite key the registry logs: e.g. '100FRLC'."""
    return f"{getattr(swim, 'distance', 0)}{getattr(swim, 'stroke', '')}{getattr(swim, 'course', '') or ''}"


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el

    return _el(swim)


def _swim_id(swim, suffix: str) -> str:
    key = getattr(swim, "swimmer_key", "") or ""
    rnd = getattr(swim, "round", "")
    return f"{key}:{_event_key(swim)}:{rnd}{suffix}"


def _own_completed_swims(swim, all_results) -> list:
    """This swimmer's completed swims in the meet, stably ordered."""
    sk = getattr(swim, "swimmer_key", "")
    own = [
        r
        for r in (all_results or [])
        if getattr(r, "swimmer_key", None) == sk
        and not getattr(r, "dq", False)
        and getattr(r, "finals_time_cs", None) is not None
    ]
    own.sort(key=lambda r: (_event_key(r), getattr(r, "round", "") or ""))
    return own


class MilestoneDetector(AchievementDetector):
    """Fires registry-grounded milestone achievements for one swim."""

    name = "athlete_milestone"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []
        ctx_map = (extra or {}).get("athlete_milestones") or {}
        if not ctx_map:
            return []  # no registry history for this workspace

        swimmer_name = (extra or {}).get("swimmer_name", "") or getattr(history, "swimmer_name", "")
        alias = normalise_name(swimmer_name)
        athlete_ctx = ctx_map.get(alias)
        if not athlete_ctx:
            # Unknown to a non-empty registry: could be a genuine first-timer OR a
            # veteran whose logged name drifted (nickname / spelling drift) and so
            # didn't resolve. We cannot tell the two apart from the registry alone,
            # so fire nothing rather than a confident false "First gala" for a
            # name-drift veteran (#61). A confirmed club debut requires the athlete
            # to be KNOWN to the registry WITH zero prior races (a populated entry
            # whose prior_races == 0), which the branches below still honour.
            return []

        own = _own_completed_swims(swim, all_results)
        try:
            ordinal = next(
                i
                for i, r in enumerate(own)
                if r is swim
                or (
                    _event_key(r) == _event_key(swim)
                    and getattr(r, "finals_time_cs", None) == getattr(swim, "finals_time_cs", None)
                    and (getattr(r, "round", "") or "") == (getattr(swim, "round", "") or "")
                )
            )
        except StopIteration:
            return []

        prior_races = int(athlete_ctx["prior_races"])
        prior_events = set(athlete_ctx["prior_events"])
        athlete_id = athlete_ctx.get("athlete_id")
        race_number = prior_races + ordinal + 1
        evt_label = _event_label(swim)

        out: list[Achievement] = []

        # Club debut — attach to the first completed swim of the meet.
        if prior_races == 0 and ordinal == 0:
            out.append(
                Achievement(
                    type="club_debut",
                    swim_id=_swim_id(swim, ":debut"),
                    swimmer_id=getattr(swim, "swimmer_key", ""),
                    swimmer_name=swimmer_name,
                    event=evt_label,
                    headline=f"First gala for {swimmer_name}",
                    angle_hint="A debut — welcome them to racing for the club.",
                    confidence=0.85,
                    confidence_label="medium",
                    evidence=[
                        AchievementEvidence(
                            source_type="registry",
                            source_name="MediaHub athlete registry",
                            statement=(
                                f"No earlier swims logged for {swimmer_name} in this club's history."
                            ),
                            confidence="medium",
                        )
                    ],
                    raw_facts={
                        "athlete_id": athlete_id,
                        "prior_races": prior_races,
                        "race_number": race_number,
                    },
                    uncertainty_notes=[_HISTORY_CAVEAT],
                    detector_name=self.name,
                )
            )

        # Nth race for the club — fires on the swim that crosses the mark.
        if race_number in RACE_MILESTONES:
            out.append(
                Achievement(
                    type=f"race_milestone_{race_number}",
                    swim_id=_swim_id(swim, f":race{race_number}"),
                    swimmer_id=getattr(swim, "swimmer_key", ""),
                    swimmer_name=swimmer_name,
                    event=evt_label,
                    headline=f"{swimmer_name}'s {race_number}th race for the club",
                    angle_hint=(
                        f"A loyalty moment — {race_number} races logged for the club, "
                        f"reached in the {evt_label}."
                    ),
                    confidence=0.85,
                    confidence_label="medium",
                    evidence=[
                        AchievementEvidence(
                            source_type="registry",
                            source_name="MediaHub athlete registry",
                            statement=(
                                f"{prior_races} races logged before this meet; this swim is "
                                f"race number {race_number}."
                            ),
                            confidence="medium",
                        )
                    ],
                    raw_facts={
                        "athlete_id": athlete_id,
                        "milestone": race_number,
                        "prior_races": prior_races,
                        "race_number": race_number,
                    },
                    uncertainty_notes=[_HISTORY_CAVEAT],
                    detector_name=self.name,
                )
            )

        # First time racing this event (known athlete only — debuts covered above).
        if prior_races > 0 and _event_key(swim) not in prior_events:
            out.append(
                Achievement(
                    type="first_event_swim",
                    swim_id=_swim_id(swim, ":firstevent"),
                    swimmer_id=getattr(swim, "swimmer_key", ""),
                    swimmer_name=swimmer_name,
                    event=evt_label,
                    headline=f"First ever {evt_label} for {swimmer_name}",
                    angle_hint="A new event ticked off — every time from here is a PB.",
                    confidence=0.8,
                    confidence_label="medium",
                    evidence=[
                        AchievementEvidence(
                            source_type="registry",
                            source_name="MediaHub athlete registry",
                            statement=f"No earlier {evt_label} swims logged for {swimmer_name}.",
                            confidence="medium",
                        )
                    ],
                    raw_facts={"athlete_id": athlete_id, "event_key": _event_key(swim)},
                    uncertainty_notes=[_HISTORY_CAVEAT],
                    detector_name=self.name,
                )
            )

        return out

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        if not ((extra or {}).get("athlete_milestones") or {}):
            return "no athlete registry history for this workspace"
        return "no milestone crossed by this swim"
