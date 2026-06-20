"""UI 1.30 — "Weekend at a glance" summary.

A deterministic, at-a-glance digest of a processed meet's key story — top
swims, PBs and medals — assembled **purely from the recognition report the
pipeline already produced**. There is no new LLM call and no external API: the
counts are tallied from the already-ranked achievements, and every line of copy
shown is either a fixed factual template over those counts or a headline that
detection already wrote.

This is *factual aggregation*, not fresh copywriting, so it deliberately stays
deterministic — the same spirit as ``visual/narration.py`` (a fixed template
over verified facts, never an LLM-invented sentence) and the deterministic
recognition counts the review page already surfaces. It is **not** an AI-caption
surface and must never grow one: the roadmap mandate for UI 1.30 is explicitly
"no additional LLM call beyond what the content pack already produced".

The pure helpers here (``build_weekend_glance`` and its classifiers) take a run
dict and return a structured ``WeekendGlance`` (or ``None`` when there is nothing
to summarise); ``render_weekend_glance_html`` renders that to an escaped HTML
panel. Both are unit-tested in ``tests/test_weekend_glance.py``; the wired-in
panel is exercised end-to-end against ``/review/<run_id>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from markupsafe import escape as _h

# Meet names the pipeline stores when it could not read one — treated as "no
# name" so the lede does not read "(unknown meet): 4 personal bests…".
_UNKNOWN_MEET = {"", "(unknown meet)", "unknown meet", "unknown"}

# Medal place -> colour, the single source of truth used by the medal detector
# (``recognition_swim``/``swim_content_v5`` medal_final) when it stamps
# ``raw_facts['place']`` / ``raw_facts['medal']``.
_PLACE_COLOUR = {1: "gold", 2: "silver", 3: "bronze"}

# Display labels for each moment "kind", in priority order (a medal outranks a
# PB outranks a record outranks a generic standout for the single headline chip).
_KIND_LABELS = {
    "gold": "Gold medal",
    "silver": "Silver medal",
    "bronze": "Bronze medal",
    "medal": "Medal",
    "pb": "Personal best",
    "record": "Club record",
    "moment": "Standout",
}


@dataclass(frozen=True)
class GlanceMoment:
    """One "top swim" in the digest — surfaced verbatim from a ranked
    achievement (no new copy is written)."""

    swimmer: str
    event: str
    sub: str  # the already-generated headline (de-duplicated of a leading name)
    kind: str  # gold | silver | bronze | medal | pb | record | moment
    kind_label: str  # human label for ``kind``
    rank: int


@dataclass(frozen=True)
class WeekendGlance:
    """Structured, ready-to-render digest of a meet's key story.

    Every field is a count tallied from, or a string lifted straight out of,
    the recognition report — nothing here is freshly generated.
    """

    meet_name: str  # "" when the pipeline had no real name
    n_analysed: int  # swims the engine looked at
    n_achievements: int  # standout moments detected
    n_pbs: int
    n_medals: int
    n_golds: int
    n_silvers: int
    n_bronzes: int
    lede_stats: str  # fixed-template factual sentence (no meet name, no user text)
    top_moments: tuple[GlanceMoment, ...]


# --------------------------------------------------------------------------- #
# Classification (deterministic — mirrors the detector's own type taxonomy)
# --------------------------------------------------------------------------- #


def _is_pb(type_l: str, angle_l: str) -> bool:
    """True for a personal-best achievement.

    Strict by design: the detector's PB types all carry the ``pb`` token
    (``official_pb_confirmed``, ``pb_confirmed``, ``pb_likely``,
    ``multi_pb_weekend``…) and the V7.3 ``post_angle`` PB family does too
    (``confirmed_official_pb``, ``pb_improvement``, ``likely_pb``,
    ``medal_and_pb_combo``). Milestones like ``first_sub_barrier`` /
    ``biggest_drop`` are counted as standout moments, not padded into the PB
    tally, so "4 personal bests" stays literally true.
    """
    return "pb" in type_l or "pb" in angle_l


def _medal_colour(type_l: str, angle_l: str, raw_facts: dict) -> Optional[str]:
    """The medal colour for an achievement, or ``None`` if it is not a medal.

    Prefers the detector's explicit ``raw_facts`` stamp, then the
    ``medal_<colour>`` token on the type / post-angle, then the finishing place.
    A medal with no resolvable colour (e.g. a bare ``medal_and_pb_combo``)
    reports the generic ``"medal"``.
    """
    raw_medal = str((raw_facts or {}).get("medal") or "").strip().lower()
    if raw_medal in ("gold", "silver", "bronze"):
        return raw_medal
    for colour in ("gold", "silver", "bronze"):
        if f"medal_{colour}" in type_l or f"medal_{colour}" in angle_l:
            return colour
    place = (raw_facts or {}).get("place")
    if isinstance(place, int) and place in _PLACE_COLOUR:
        return _PLACE_COLOUR[place]
    if type_l.startswith("medal") or angle_l.startswith("medal"):
        return "medal"
    return None


def _dedup_headline(headline: str, swimmer: str) -> str:
    """Drop a leading "<swimmer> " from a headline so the digest does not read
    the name twice (the name is shown bold beside it). Deterministic; returns
    the headline unchanged when it does not start with the name."""
    h = (headline or "").strip()
    s = (swimmer or "").strip()
    if s and h.lower().startswith(s.lower()):
        rest = h[len(s) :].lstrip(" ,:;—-–").strip()
        if rest:
            return rest[0].upper() + rest[1:]
    return h


def _join_and(parts: list[str]) -> str:
    """``["a"] -> "a"``; ``["a","b"] -> "a and b"``; ``["a","b","c"] -> "a, b and c"``."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_weekend_glance(run_data: dict, *, top_n: int = 3) -> Optional[WeekendGlance]:
    """Assemble the digest from a run's recognition report.

    Returns ``None`` when the run has no ranked achievements to summarise (a
    failed run, or one where nothing was content-worthy) — the caller then
    renders nothing rather than an empty panel. Never raises on a malformed run
    dict: missing / odd fields degrade to zero counts.
    """
    if not isinstance(run_data, dict):
        return None
    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    if not isinstance(ranked, list) or not ranked:
        return None

    meet_name = str((run_data.get("meet") or {}).get("name") or "").strip()
    if meet_name.lower() in _UNKNOWN_MEET:
        meet_name = ""

    n_analysed = _safe_int(rr.get("n_swims_analysed", run_data.get("our_swim_count", 0)))
    # The "standout moments" count and the jump link both describe the ranked
    # list shown directly below the panel, so base them on what is actually
    # there (== the ranker's n_achievements, but immune to a stale/odd count).
    n_listed = len(ranked)

    n_pbs = n_golds = n_silvers = n_bronzes = n_medals = 0
    moments: list[GlanceMoment] = []
    for idx, ra in enumerate(ranked):
        if not isinstance(ra, dict):
            continue
        a = ra.get("achievement") or {}
        type_l = str(a.get("type") or "").strip().lower()
        angle_l = str(a.get("post_angle") or "").strip().lower()
        raw_facts = a.get("raw_facts") if isinstance(a.get("raw_facts"), dict) else {}

        is_pb = _is_pb(type_l, angle_l)
        colour = _medal_colour(type_l, angle_l, raw_facts)
        if is_pb:
            n_pbs += 1
        if colour is not None:
            n_medals += 1
            if colour == "gold":
                n_golds += 1
            elif colour == "silver":
                n_silvers += 1
            elif colour == "bronze":
                n_bronzes += 1

        # Single headline chip per moment: medal colour > PB > record > standout.
        if colour is not None:
            kind = colour
        elif is_pb:
            kind = "pb"
        elif "record" in type_l or "record" in angle_l:
            kind = "record"
        else:
            kind = "moment"

        swimmer = str(a.get("swimmer_name") or "").strip()
        event = str(a.get("event") or "").strip()
        sub = _dedup_headline(str(a.get("headline") or ""), swimmer) or event
        moments.append(
            GlanceMoment(
                swimmer=swimmer,
                event=event,
                sub=sub,
                kind=kind,
                kind_label=_KIND_LABELS.get(kind, _KIND_LABELS["moment"]),
                rank=_safe_int(ra.get("rank", idx + 1)),
            )
        )

    moments.sort(key=lambda m: m.rank)
    top_moments = tuple(moments[: max(0, top_n)])

    return WeekendGlance(
        meet_name=meet_name,
        n_analysed=n_analysed,
        n_achievements=n_listed,
        n_pbs=n_pbs,
        n_medals=n_medals,
        n_golds=n_golds,
        n_silvers=n_silvers,
        n_bronzes=n_bronzes,
        lede_stats=_build_lede_stats(n_pbs, n_medals, n_listed, n_analysed),
        top_moments=top_moments,
    )


def _build_lede_stats(n_pbs: int, n_medals: int, n_achievements: int, n_analysed: int) -> str:
    """A fixed factual sentence (no meet name, no user-supplied text — safe to
    embed without escaping). E.g. "4 personal bests and 2 medals across 24
    analysed swims." Falls back to a standout-moment count when there are no
    PBs or medals."""
    parts: list[str] = []
    if n_pbs:
        parts.append(_plural(n_pbs, "personal best"))
    if n_medals:
        parts.append(_plural(n_medals, "medal"))
    stats = _join_and(parts) or _plural(max(n_achievements, 0), "standout moment")
    if n_analysed > 0:
        return f"{stats} across {_plural(n_analysed, 'analysed swim')}."
    return f"{stats}."


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #


def render_weekend_glance_html(glance: Optional[WeekendGlance]) -> str:
    """Render the digest to an escaped HTML panel, or ``""`` when there is
    nothing to show. All dynamic text (meet name) is HTML-escaped; the counts
    are integers and the lede is a fixed template.

    The panel is a headline lede + the PB / medal / standout / swims-analysed
    stat tiles. It deliberately no longer reprints the top-ranked moments or a
    "see all" jump link — that preview duplicated the ranked "Top achievements"
    list rendered directly beneath it on the review surface. The structured
    ``glance.top_moments`` are still computed (and unit-tested) for any other
    consumer; this renderer simply doesn't reprint them."""
    if glance is None:
        return ""

    lede_inner = str(_h(glance.lede_stats))
    if glance.meet_name:
        lede_inner = f"{_h(glance.meet_name)}: {lede_inner}"

    medal_title = ""
    if glance.n_medals:
        bits = []
        if glance.n_golds:
            bits.append(f"{glance.n_golds} gold")
        if glance.n_silvers:
            bits.append(f"{glance.n_silvers} silver")
        if glance.n_bronzes:
            bits.append(f"{glance.n_bronzes} bronze")
        if bits:
            medal_title = f' title="{" · ".join(bits)}"'

    # PBs use the stable semantic "good" accent (green bar, high-contrast
    # default numeral) rather than the theme-adaptive lane/primary, which can
    # resolve to a low-contrast colour on a dark-primary club. Medals keep the
    # reserved medal-gold treatment.
    stats_html = (
        f'<div class="stat good"><div class="l">PBs</div>'
        f'<div class="v" data-mh-count="{glance.n_pbs}">{glance.n_pbs}</div></div>'
        f'<div class="stat medal"{medal_title}><div class="l">Medals</div>'
        f'<div class="v" data-mh-count="{glance.n_medals}">{glance.n_medals}</div></div>'
        f'<div class="stat"><div class="l">Standout moments</div>'
        f'<div class="v" data-mh-count="{glance.n_achievements}">{glance.n_achievements}</div></div>'
        f'<div class="stat"><div class="l">Swims analysed</div>'
        f'<div class="v" data-mh-count="{glance.n_analysed}">{glance.n_analysed}</div></div>'
    )

    return f"""
<section class="card mh-glance mh-reveal" aria-labelledby="mh-glance-h">
  <div class="mh-glance-head">
    <span class="mh-glance-eyebrow">Weekend at a glance</span>
    <h2 id="mh-glance-h" class="mh-glance-lede">{lede_inner}</h2>
  </div>
  <div class="stat-block mh-glance-stats">{stats_html}</div>
</section>"""
