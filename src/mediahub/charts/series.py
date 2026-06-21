"""charts.series — build ChartSpecs from a processed run's real data (roadmap 1.11).

The bridge from MediaHub's canonical store to a render-ready
:class:`~charts.models.ChartSpec`. Every builder reads the **deterministic facts**
(``charts.aggregates`` over the recognition report, the canonical meet's results /
relays / splits, and the club-records book) and emits a spec whose every point is a
real number with a ``source_ref`` back to where it came from. No builder ever
fabricates a series: when the data isn't there it returns ``None`` (an honest
absence, not a fake line — the "never silently guess" rule).

:func:`build_chart_candidates` assembles whichever charts a given run can support;
the AI recommender (build 3) and the web layer (build 4) choose among them — but the
*data* is settled here, deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .aggregates import MeetAggregates, compute_aggregates
from .models import Axis, ChartSpec, DataPoint, Series, format_time_cs

_STROKE_NAMES = {"FR": "Free", "BK": "Back", "BR": "Breast", "FL": "Fly", "IM": "IM", "MEDLEY": "Medley"}
_COURSE_TAGS = {"LC": "LC", "SC": "SC", "Y": "SCY"}
_SOURCE = "Source: meet results file"


@dataclass
class ChartCandidate:
    """One chart a run can support, with the metadata the recommender chooses on."""

    chart_id: str  # stable id, e.g. "pbs_per_swimmer"
    title: str  # human title
    kind: str  # chart kind (matches spec.kind)
    summary: str  # what it shows, one line (for the AI + the UI)
    headline_stat: str  # the single key number ("8 PBs")
    spec: ChartSpec
    n_points: int  # how much data backs it (helps rank / filter)

    def to_dict(self) -> dict:
        return {
            "chart_id": self.chart_id,
            "title": self.title,
            "kind": self.kind,
            "summary": self.summary,
            "headline_stat": self.headline_stat,
            "n_points": self.n_points,
            "spec": self.spec.to_dict(),
        }


# --------------------------------------------------------------------------- #
# individual builders (each returns None when the data can't back it)
# --------------------------------------------------------------------------- #
def pbs_per_swimmer_chart(agg: MeetAggregates, *, top: int = 10) -> Optional[ChartSpec]:
    """Bar: how many personal bests each swimmer set (top N)."""
    if not agg.pbs_by_swimmer:
        return None
    rows = sorted(agg.pbs_by_swimmer.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    pts = tuple(
        DataPoint(label=name, value=float(n), display=str(n), source_ref=f"pbs:{name}")
        for name, n in rows
    )
    return ChartSpec(
        kind="bar",
        title="Personal bests",
        subtitle=_meet_sub(agg),
        series=(Series(name="PBs", points=pts, role="accent"),),
        y_axis=Axis(title="PBs", value_format="integer"),
        x_axis=Axis(kind="category"),
        source_note=_SOURCE,
        chart_id="pbs_per_swimmer",
    )


def medal_split_chart(agg: MeetAggregates) -> Optional[ChartSpec]:
    """Pie: the gold/silver/bronze split of the medal haul."""
    if agg.n_medals <= 0:
        return None
    pts = []
    for label, n in (("Gold", agg.n_gold), ("Silver", agg.n_silver), ("Bronze", agg.n_bronze)):
        if n > 0:
            pts.append(DataPoint(label=label, value=float(n), display=str(n), source_ref=f"medal:{label}"))
    if not pts:
        return None
    return ChartSpec(
        kind="pie",
        title="Medal haul",
        subtitle=f"{agg.n_medals} medals",
        series=(Series(points=tuple(pts)),),
        y_axis=Axis(value_format="integer"),
        source_note=_SOURCE,
        chart_id="medal_split",
    )


def medal_table_chart(agg: MeetAggregates, *, top: int = 10) -> Optional[ChartSpec]:
    """Medal table: per-swimmer gold/silver/bronze, ranked."""
    if not agg.medals_by_swimmer:
        return None
    ranked = sorted(
        agg.medals_by_swimmer.items(),
        key=lambda kv: (-kv[1]["gold"], -kv[1]["silver"], -kv[1]["bronze"], kv[0]),
    )[:top]
    rows = tuple(
        (name, str(m["gold"]), str(m["silver"]), str(m["bronze"]))
        for name, m in ranked
    )
    return ChartSpec(
        kind="medal_table",
        title="Medal table",
        subtitle=_meet_sub(agg),
        columns=("Swimmer", "Gold", "Silver", "Bronze"),
        rows=rows,
        source_note=_SOURCE,
        chart_id="medal_table",
    )


def biggest_drops_chart(run_data: dict, *, top: int = 8) -> Optional[ChartSpec]:
    """Horizontal bars: the biggest time improvements of the meet (seconds dropped)."""
    drops = _collect_drops(run_data)
    if not drops:
        return None
    drops.sort(key=lambda d: -d["seconds"])
    pts = tuple(
        DataPoint(
            label=f"{d['swimmer']} · {d['event']}".strip(" ·"),
            value=round(d["seconds"], 2),
            display=f"−{d['seconds']:.2f}s",
            source_ref=d["source_ref"],
        )
        for d in drops[:top]
    )
    return ChartSpec(
        kind="hbar",
        title="Biggest time drops",
        subtitle="Seconds off a previous best",
        series=(Series(name="Drop", points=pts, role="accent"),),
        x_axis=Axis(value_format="seconds"),
        source_note=_SOURCE,
        chart_id="biggest_drops",
    )


def club_record_board_chart(records, *, title: str = "Club records", top: int = 14) -> Optional[ChartSpec]:
    """Table: the club-record book (from ``club_records.list_records``)."""
    rows = []
    for r in (records or [])[:top]:
        event = _event_label(_attr(r, "distance"), _attr(r, "stroke"), _attr(r, "course"))
        age = _attr(r, "age_group") or "Open"
        gender = _gender_word(_attr(r, "gender"))
        time_str = _record_time(r)
        holder = str(_attr(r, "holder") or "")
        rows.append((event, f"{gender} {age}".strip(), time_str, holder))
    if not rows:
        return None
    return ChartSpec(
        kind="table",
        title=title,
        subtitle=f"{len(rows)} records",
        columns=("Event", "Category", "Time", "Holder"),
        rows=tuple(rows),
        source_note="Source: club records book",
        chart_id="club_record_board",
    )


def split_ladder_chart(run_data: dict) -> Optional[ChartSpec]:
    """Split ladder: per-50 splits for the most informative individual swim or relay."""
    meet = run_data.get("canonical_meet") or {}
    # Prefer an individual swim with real splits.
    for r in meet.get("results") or []:
        splits = r.get("splits") or []
        diffs = [s for s in splits if s.get("differential_cs")]
        if len(diffs) >= 2:
            pts = tuple(
                DataPoint(
                    label=f"{s['distance_marker']}m",
                    value=float(s["differential_cs"]),
                    display=format_time_cs(int(s["differential_cs"])),
                    source_ref=f"split:{r.get('swimmer_key','')}:{s['distance_marker']}",
                )
                for s in diffs
            )
            swimmers = meet.get("swimmers") or {}
            name = _swimmer_name(swimmers.get(r.get("swimmer_key"), {}))
            event = _event_label(r.get("distance"), r.get("stroke"), r.get("course"))
            return ChartSpec(
                kind="split_ladder",
                title="Split ladder",
                subtitle=f"{name} · {event}".strip(" ·"),
                series=(Series(points=pts),),
                y_axis=Axis(value_format="time_cs"),
                source_note=_SOURCE,
                chart_id="split_ladder",
            )
    # Fall back to the fastest relay's legs.
    relays = [r for r in (meet.get("relays") or []) if (r.get("legs") and r.get("finals_time_cs"))]
    if relays:
        relay = min(relays, key=lambda r: r.get("finals_time_cs") or 1 << 30)
        legs = [leg for leg in relay["legs"] if leg.get("leg_time_cs")]
        if len(legs) >= 2:
            swimmers = meet.get("swimmers") or {}
            pts = tuple(
                DataPoint(
                    label=_leg_label(leg, swimmers),
                    value=float(leg["leg_time_cs"]),
                    display=format_time_cs(int(leg["leg_time_cs"])),
                    source_ref=f"relayleg:{leg.get('leg_index')}",
                )
                for leg in sorted(legs, key=lambda x: x.get("leg_index", 0))
            )
            event = _event_label(relay.get("distance"), relay.get("stroke"), relay.get("course"))
            return ChartSpec(
                kind="split_ladder",
                title="Relay splits",
                subtitle=event,
                series=(Series(points=pts),),
                y_axis=Axis(value_format="time_cs"),
                source_note=_SOURCE,
                chart_id="relay_split_ladder",
            )
    return None


def progression_chart(
    swimmer_name: str,
    points: list[tuple[str, int]],
    *,
    event: str = "",
) -> Optional[ChartSpec]:
    """Progression line for a swimmer's times (lower is better). ``points`` is an
    ordered list of ``(date_or_label, time_cs)`` — provided by the caller from real
    history; this builder never invents intermediate points."""
    clean = [(str(lbl), int(cs)) for lbl, cs in (points or []) if cs and int(cs) > 0]
    if len(clean) < 2:
        return None
    pts = tuple(
        DataPoint(label=lbl, value=float(cs), display=format_time_cs(cs), x=float(i),
                  source_ref=f"history:{swimmer_name}:{lbl}")
        for i, (lbl, cs) in enumerate(clean)
    )
    return ChartSpec(
        kind="progression",
        title=swimmer_name.strip() or "Season progression",
        subtitle=event,
        series=(Series(name=event or "Time", points=pts, role="accent"),),
        y_axis=Axis(title="Time", value_format="time_cs", lower_is_better=True),
        x_axis=Axis(kind="time"),
        source_note="Source: club history",
        chart_id="progression",
    )


# --------------------------------------------------------------------------- #
# candidate assembler
# --------------------------------------------------------------------------- #
def build_chart_candidates(run_data: dict, *, records=None) -> list[ChartCandidate]:
    """Every chart this run can support, with the metadata the recommender ranks on."""
    agg = compute_aggregates(run_data)
    out: list[ChartCandidate] = []

    def add(spec: Optional[ChartSpec], summary: str, headline: str) -> None:
        if spec is None or spec.is_empty():
            return
        n = len(spec.rows) if spec.kind in ("table", "medal_table") else len(spec.all_points())
        out.append(
            ChartCandidate(
                chart_id=spec.chart_id or spec.kind,
                title=spec.title,
                kind=spec.kind,
                summary=summary,
                headline_stat=headline,
                spec=spec,
                n_points=n,
            )
        )

    add(pbs_per_swimmer_chart(agg), "Personal bests set, by swimmer", f"{agg.n_pbs} PBs")
    add(medal_split_chart(agg), "Gold / silver / bronze split of the medal haul", f"{agg.n_medals} medals")
    add(medal_table_chart(agg), "Per-swimmer medal tally, ranked", f"{agg.n_gold} gold")
    add(biggest_drops_chart(run_data), "The biggest time improvements of the meet", _drop_headline(agg))
    add(split_ladder_chart(run_data), "Per-50 splits for a standout swim or relay", "splits")
    if records:
        add(club_record_board_chart(records), "The club-record book", f"{len(list(records))} records")
    return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _collect_drops(run_data: dict) -> list[dict]:
    report = (run_data or {}).get("recognition_report") or {}
    out: list[dict] = []
    for ra in report.get("ranked_achievements") or []:
        a = (ra.get("achievement") or {}) if isinstance(ra, dict) else {}
        raw = a.get("raw_facts") or {}
        secs = None
        for key in ("drop_seconds", "improvement_seconds", "pb_drop_seconds"):
            if raw.get(key) is not None:
                try:
                    secs = abs(float(raw[key]))
                except (TypeError, ValueError):
                    secs = None
                break
        if secs and secs > 0:
            out.append({
                "swimmer": str(a.get("swimmer_name", "")).strip(),
                "event": str(a.get("event", "")).strip(),
                "seconds": secs,
                "source_ref": str(a.get("swim_id") or f"drop:{a.get('swimmer_name','')}"),
            })
    # de-dup identical (swimmer,event) keeping the largest drop
    best: dict[tuple, dict] = {}
    for d in out:
        k = (d["swimmer"], d["event"])
        if k not in best or d["seconds"] > best[k]["seconds"]:
            best[k] = d
    return list(best.values())


def _drop_headline(agg: MeetAggregates) -> str:
    if agg.biggest_drop:
        return f"−{float(agg.biggest_drop.get('seconds', 0)):.2f}s"
    return "improvements"


def _meet_sub(agg: MeetAggregates) -> str:
    return agg.meet_name or ""


def _event_label(distance, stroke, course) -> str:
    course = (str(course or "")).upper()
    stroke_name = _STROKE_NAMES.get(str(stroke or "").upper(), (str(stroke or "").title() or "?"))
    unit = "y" if course == "Y" else "m"
    dist = f"{distance}{unit}" if distance else ""
    base = f"{dist} {stroke_name}".strip()
    tag = _COURSE_TAGS.get(course, course)
    return f"{base} ({tag})" if tag else base


def _gender_word(g: str) -> str:
    return {"M": "Boys", "F": "Girls", "X": "Open"}.get(str(g or "").upper(), "")


def _swimmer_name(sw: dict) -> str:
    if not isinstance(sw, dict):
        return ""
    fn = str(sw.get("first_name", "")).strip()
    ln = str(sw.get("last_name", "")).strip()
    return f"{fn} {ln}".strip()


def _leg_label(leg: dict, swimmers: dict) -> str:
    name = _swimmer_name(swimmers.get(leg.get("swimmer_key"), {}))
    if name:
        return name.split()[-1]  # surname for compactness
    return f"Leg {int(leg.get('leg_index', 0)) + 1}"


def _record_time(r) -> str:
    ts = _attr(r, "time_str")
    if ts:
        return str(ts)
    cs = _attr(r, "time_cs")
    return format_time_cs(int(cs)) if cs else ""


def _attr(obj, name: str):
    """Read ``name`` from a dataclass/object or a dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


__all__ = [
    "ChartCandidate",
    "build_chart_candidates",
    "pbs_per_swimmer_chart",
    "medal_split_chart",
    "medal_table_chart",
    "biggest_drops_chart",
    "club_record_board_chart",
    "split_ladder_chart",
    "progression_chart",
]
