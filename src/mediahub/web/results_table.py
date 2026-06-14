"""Results data table (UI 1.12) — pure, testable helpers.

Turns one run's parsed swim results into sortable / filterable table rows, each
carrying an athlete-progress sparkline series and a PB / improvement *delta
badge*. The shape is borrowed from Wope's data table: a flat, scannable grid
where every row reads at a glance and the interesting movement (a personal
best, a season's improvement) is colour-coded.

Everything here is **pure** — no Flask, no database, no disk. The route in
``web.py`` does the IO (load the run, pull each athlete's cross-meet history
from the registry) and hands plain dicts in. That keeps the deterministic
display maths — time formatting, the PB / improvement classification, the sort
and filter — unit-testable on its own and well away from the request cycle.

Per the engine conventions this is *display* maths, not the recognition engine:
"is this a PB?" for a generated card still comes from the deterministic
detectors. Here we only compare a swim against the athlete's own logged history
to colour a row, and we are honest about uncertainty (a first swim *on record*
is labelled as such — it is not claimed to be the athlete's first-ever).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Stroke code -> readable display name. Display only — the engine keeps the
# canonical codes (RaceResult.stroke). MEDLEY is the relay value; IM the
# individual-medley one.
STROKE_NAMES: dict[str, str] = {
    "FR": "Free",
    "BK": "Back",
    "BR": "Breast",
    "FL": "Fly",
    "IM": "IM",
    "MEDLEY": "Medley",
}

# Course code -> the short tag shown in the event label.
COURSE_TAGS: dict[str, str] = {"LC": "LC", "SC": "SC", "Y": "SCY"}

# Sort keys the route accepts; anything else falls back to DEFAULT_SORT. One
# source of truth shared by the route and the tests.
SORT_KEYS: tuple[str, ...] = ("event", "name", "time", "place", "age", "delta")
DEFAULT_SORT = "event"
DEFAULT_ORDER = "asc"

# Statuses that mean "no clocked time" — DQ, did-not-start, etc.
_NO_TIME_STATUSES = {"dq", "dns", "dnf", "scratch"}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_time_cs(cs) -> str:
    """Centiseconds -> ``m:ss.cc`` (or ``ss.cc`` under a minute). ``""`` for None."""
    if cs is None:
        return ""
    cs = int(cs)
    if cs < 0:
        return ""
    mins = cs // 6000
    rem = cs - mins * 6000
    secs, frac = rem // 100, rem % 100
    return f"{mins}:{secs:02d}.{frac:02d}" if mins else f"{secs}.{frac:02d}"


def format_delta_cs(cs) -> str:
    """A time *delta* in centiseconds -> seconds with two decimals (``"0.42"``).

    Deltas are typically small; a large drop (distance events) still reads fine
    (``"75.40"``). Always the magnitude — the sign is carried by the badge.
    """
    if cs is None:
        return ""
    return f"{abs(int(cs)) / 100:.2f}"


def event_key(distance, stroke, course) -> str:
    """The registry's event key: ``f"{dist}{STROKE}{COURSE}"`` — e.g. ``100FRLC``.

    Must match ``athletes.registry._swims_from_run_payload`` exactly, so a row's
    key lines up with the keys its athlete's logged swims were stored under.
    """
    return f"{distance if distance is not None else ''}{(stroke or '').upper()}{(course or '').upper()}"


def event_label(distance, stroke, course) -> str:
    """Human event label: ``100m Free (LC)``, ``50y Free (SCY)``, ``200m IM (SC)``."""
    course = (course or "").upper()
    stroke_name = STROKE_NAMES.get((stroke or "").upper(), (stroke or "").title() or "?")
    unit = "y" if course == "Y" else "m"
    dist = f"{distance}{unit}" if distance else ""
    base = f"{dist} {stroke_name}".strip()
    tag = COURSE_TAGS.get(course, course)
    return f"{base} ({tag})" if tag else base


# ---------------------------------------------------------------------------
# Delta badge — PB / improvement classification (deterministic)
# ---------------------------------------------------------------------------


@dataclass
class DeltaBadge:
    """How this swim compares to the athlete's own prior history for the event.

    ``kind`` drives the colour:
      pb          new personal best (faster than every prior outing)  → medal
      improvement off the PB but faster than the *last* outing         → good
      matched     equalled the PB                                      → info
      first       first swim of this event *on record*                 → neutral
      slower      slower than both the PB and the last outing          → bad
      none        no clocked time (DQ / DNS) — nothing to compare      → —
    """

    kind: str = "none"
    delta_cs: int | None = None
    label: str = ""
    title: str = ""


def classify_delta(current_cs, prior_best_cs, prior_last_cs) -> DeltaBadge:
    """Compare one swim to the athlete's prior best and prior most-recent time.

    All three are centiseconds (lower = faster). ``prior_best_cs`` /
    ``prior_last_cs`` are ``None`` when the athlete has no earlier logged swim
    of this event. Pure and deterministic.
    """
    if current_cs is None:
        return DeltaBadge("none")
    current_cs = int(current_cs)
    if prior_best_cs is None:
        return DeltaBadge(
            "first",
            None,
            "First on record",
            "First swim of this event in this club's history on record.",
        )
    prior_best_cs = int(prior_best_cs)
    if current_cs < prior_best_cs:
        d = prior_best_cs - current_cs
        return DeltaBadge(
            "pb",
            d,
            f"PB −{format_delta_cs(d)}",
            f"New personal best — {format_delta_cs(d)}s faster than the previous best.",
        )
    if current_cs == prior_best_cs:
        return DeltaBadge("matched", 0, "= PB", "Equalled the personal best.")
    if prior_last_cs is not None and current_cs < int(prior_last_cs):
        d = int(prior_last_cs) - current_cs
        return DeltaBadge(
            "improvement",
            d,
            f"↑ −{format_delta_cs(d)}",
            f"{format_delta_cs(d)}s faster than the last outing (still off the PB).",
        )
    d = current_cs - prior_best_cs
    return DeltaBadge(
        "slower",
        d,
        f"+{format_delta_cs(d)}",
        f"{format_delta_cs(d)}s off the personal best.",
    )


# ---------------------------------------------------------------------------
# Row model + builder
# ---------------------------------------------------------------------------


@dataclass
class ResultRow:
    swimmer_name: str
    swimmer_key: str
    distance: int | None
    stroke: str
    course: str
    gender: str
    age_band: str
    event_key: str
    event_label: str
    time_cs: int | None
    time_str: str
    place: int | None
    status: str
    is_dq: bool
    delta: DeltaBadge
    # Progression for this athlete + event: prior outings (other meets) then
    # this swim, oldest first. ``series_current_index`` marks this swim.
    series_cs: list[int] = field(default_factory=list)
    series_dates: list[str] = field(default_factory=list)
    series_current_index: int = -1


def _swimmer_name(sw: dict, fallback: str) -> str:
    name = f"{(sw.get('first_name') or '').strip()} {(sw.get('last_name') or '').strip()}".strip()
    return name or fallback or "(unknown)"


def build_rows(meet: dict, history: dict[str, list[dict]], run_id: str) -> list[ResultRow]:
    """Build one ResultRow per individual result in ``meet``.

    ``history`` maps a result's ``swimmer_key`` to that athlete's full registry
    swim log (``[{"event", "swim_date", "time_cs", "run_id"}, ...]``). Only
    *prior* outings — rows whose ``run_id`` differs from this run — count toward
    the PB/improvement comparison; the sparkline then appends this swim as the
    latest point, so it is correct whether or not the registry has synced this
    run yet. Relays are skipped (no single athlete to chart).
    """
    swimmers = meet.get("swimmers") or {}
    rows: list[ResultRow] = []
    for res in meet.get("results") or []:
        sk = res.get("swimmer_key") or ""
        sw = swimmers.get(sk) or {}
        dist = res.get("distance")
        stroke = res.get("stroke") or ""
        course = res.get("course") or ""
        ek = event_key(dist, stroke, course)
        time_cs = res.get("finals_time_cs")
        status = (res.get("status") or "completed").lower()
        is_dq = bool(res.get("dq")) or status in _NO_TIME_STATUSES

        # Prior outings of *this* event from the registry (cross-meet history),
        # oldest first. Exclude this run so we never compare a swim to itself.
        prior = sorted(
            (
                h
                for h in (history.get(sk) or [])
                if h.get("event") == ek
                and h.get("time_cs") is not None
                and h.get("run_id") != run_id
            ),
            key=lambda h: (h.get("swim_date") or ""),
        )
        prior_best = min((int(h["time_cs"]) for h in prior), default=None)
        prior_last = int(prior[-1]["time_cs"]) if prior else None
        delta = classify_delta(time_cs, prior_best, prior_last)

        # Sparkline series = prior outings + this swim (when it has a time).
        series = [(h.get("swim_date") or "", int(h["time_cs"])) for h in prior]
        cur_idx = -1
        if time_cs is not None:
            series.append((res.get("swim_date") or meet.get("start_date") or "", int(time_cs)))
            cur_idx = len(series) - 1

        rows.append(
            ResultRow(
                swimmer_name=_swimmer_name(sw, sk),
                swimmer_key=sk,
                distance=dist,
                stroke=(stroke or "").upper(),
                course=(course or "").upper(),
                gender=(res.get("gender") or sw.get("gender") or "").upper(),
                age_band=res.get("age_band") or "",
                event_key=ek,
                event_label=event_label(dist, stroke, course),
                time_cs=int(time_cs) if time_cs is not None else None,
                time_str=format_time_cs(time_cs) or ("—" if is_dq else ""),
                place=res.get("place"),
                status=status,
                is_dq=is_dq,
                delta=delta,
                series_cs=[c for _, c in series],
                series_dates=[d for d, _ in series],
                series_current_index=cur_idx,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Sort / filter (server-side)
# ---------------------------------------------------------------------------

_INF = float("inf")

# How delta kinds rank when sorting by "delta" (improvement first when desc).
_DELTA_RANK = {"pb": 4, "improvement": 3, "matched": 2, "first": 1, "slower": 0, "none": -1}


def _time_key(r: ResultRow):
    # No clocked time always sorts to the bottom on the default (asc) order.
    return r.time_cs if r.time_cs is not None else _INF


def _place_key(r: ResultRow):
    return r.place if r.place is not None else _INF


def normalise_sort(sort: str | None, order: str | None) -> tuple[str, str]:
    """Clamp raw query params to a valid (sort, order) pair."""
    s = (sort or "").strip().lower()
    o = (order or "").strip().lower()
    return (s if s in SORT_KEYS else DEFAULT_SORT, "desc" if o == "desc" else "asc")


def sort_rows(rows: list[ResultRow], sort: str, order: str = "asc") -> list[ResultRow]:
    """Stable server-side sort. Unknown keys fall back to DEFAULT_SORT."""
    sort, order = normalise_sort(sort, order)
    reverse = order == "desc"
    keymap = {
        "event": lambda r: (r.distance or 0, r.stroke, r.course, _place_key(r)),
        "name": lambda r: (r.swimmer_name.lower(), r.distance or 0, r.stroke),
        "time": _time_key,
        "place": lambda r: (_place_key(r), r.distance or 0, r.stroke),
        "age": lambda r: (r.age_band, r.distance or 0, r.stroke),
        "delta": lambda r: (_DELTA_RANK.get(r.delta.kind, -1), r.delta.delta_cs or 0),
    }
    return sorted(rows, key=keymap[sort], reverse=reverse)


def filter_rows(
    rows: list[ResultRow],
    *,
    event: str = "",
    query: str = "",
    pb_only: bool = False,
) -> list[ResultRow]:
    """Filter by exact event key, swimmer-name substring, and PB/improvement only."""
    out = rows
    event = (event or "").strip()
    if event:
        out = [r for r in out if r.event_key == event]
    q = (query or "").strip().lower()
    if q:
        out = [r for r in out if q in r.swimmer_name.lower()]
    if pb_only:
        out = [r for r in out if r.delta.kind in ("pb", "improvement", "matched")]
    return out


def event_options(rows: list[ResultRow]) -> list[tuple[str, str]]:
    """Distinct ``(event_key, event_label)`` present, for the filter dropdown."""
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r.event_key, r.event_label)
    return sorted(seen.items(), key=lambda kv: kv[1])


def sparkline_series(row: ResultRow) -> dict:
    """Compact JSON-able sparkline payload for one row's ``<canvas>``.

    ``t`` times (cs, oldest first), ``d`` ISO dates, ``cur`` the index of this
    swim, ``kind`` the delta kind (so the current point can be tinted gold for a
    PB). Returned only when there are at least two points to draw a trend.
    """
    return {
        "t": list(row.series_cs),
        "d": list(row.series_dates),
        "cur": row.series_current_index,
        "kind": row.delta.kind,
    }
