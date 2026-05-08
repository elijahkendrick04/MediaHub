"""
swimmingresults.org PB enrichment.

Fetches Swim England Best Times pages by ASA member ID (`tiref`), parses the
LC and SC tables into structured PBs, and caches the result on disk so we do
not re-fetch the same swimmer unnecessarily.

Statuses returned by `compare_to_pb`:
  CONFIRMED_PB    — meet swim is faster than a trusted PB (LC vs LC, SC vs SC)
                    that pre-dates the meet, AND retrieved snapshot is fresh.
  LIKELY_PB       — meet swim is faster than the swimmer's listed PB but the
                    listed PB has the SAME date as the meet (the site has
                    already absorbed the swim, so we cannot prove it was a PB
                    by comparison alone).
  PB_UNVERIFIED   — we have no usable history for that swimmer/event/course.
  NOT_PB          — meet swim is slower than a trusted prior PB.

Hard rules (preserved from V2):
  * LC times never compared with SC times.
  * Entry/seed times are never trusted as PB sources.
  * If `tiref` is missing, status is PB_UNVERIFIED. We never name-match silently.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------- constants ----------
SR_BASE = "https://www.swimmingresults.org"
PB_URL = SR_BASE + "/individualbest/personal_best.php?mode=A&tiref={tiref}"
USER_AGENT = "SwimContentBot/0.1 (contact: pilot@swansea-uni-swimming.example)"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "swimmingresults"
DEFAULT_CACHE_TTL_DAYS = 30
REQUEST_DELAY_SEC = 1.0  # courteous rate-limit between fetches

# Stroke normalisation: site uses "50 Freestyle", we use ("FR", 50)
_STROKE_MAP = {
    "freestyle": "FR",
    "backstroke": "BK",
    "breaststroke": "BR",
    "butterfly": "FL",
    "individual medley": "IM",
    "im": "IM",
}


# ---------- data classes ----------
@dataclass
class PBEntry:
    """A single best-time row from swimmingresults.org."""
    stroke: str          # FR, BK, BR, FL, IM
    distance: int        # 50, 100, 200, 400, 800, 1500
    course: str          # "LC" or "SC"
    time_str: str        # e.g. "1:07.97"
    time_sec: float      # seconds, parsed
    date: str            # "DD/MM/YY" as on the site
    date_iso: Optional[str]  # "YYYY-MM-DD" if parseable
    meet: str
    venue: str
    licence: str
    level: str

    def event_key(self) -> str:
        return f"{self.distance}_{self.stroke}_{self.course}"


@dataclass
class SwimmerPBSnapshot:
    """The full PB snapshot for one swimmer at a point in time."""
    tiref: str
    name: Optional[str]
    pbs: list[PBEntry]
    source_url: str
    retrieved_at: str  # ISO 8601 UTC
    fetch_ok: bool
    error: Optional[str] = None

    def by_event(self) -> dict[str, PBEntry]:
        return {pb.event_key(): pb for pb in self.pbs}


@dataclass
class PBComparison:
    """Result of comparing one meet swim against a swimmer's PB snapshot."""
    status: str  # CONFIRMED_PB | LIKELY_PB | PB_UNVERIFIED | NOT_PB
    prior_time_sec: Optional[float]
    prior_time_str: Optional[str]
    prior_date_iso: Optional[str]
    delta_sec: Optional[float]  # negative means improvement
    source_url: Optional[str]
    retrieved_at: Optional[str]
    note: str = ""


# ---------- time parsing ----------
def parse_swim_time(s: str) -> Optional[float]:
    """Parse '1:07.97' or '57.99' or '5:48.50' to seconds (float)."""
    if not s:
        return None
    s = s.strip()
    m = re.fullmatch(r"(\d+):(\d{2})\.(\d{2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 100.0
    m = re.fullmatch(r"(\d{1,2})\.(\d{2})", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 100.0
    m = re.fullmatch(r"(\d{1,2}:\d{2}:\d{2}\.\d{2})", s)  # 1:23:45.67
    if m:
        h, mm, rest = s.split(":")
        return int(h) * 3600 + int(mm) * 60 + float(rest)
    return None


def parse_site_date(s: str) -> Optional[str]:
    """Site uses DD/MM/YY. Return ISO YYYY-MM-DD."""
    if not s:
        return None
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{2})", s.strip())
    if not m:
        return None
    dd, mm, yy = m.groups()
    year = 2000 + int(yy)  # safe: site shows recent years
    try:
        return datetime(year, int(mm), int(dd)).date().isoformat()
    except ValueError:
        return None


# ---------- HTML parsing ----------
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAGS_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip(html: str) -> str:
    return _WS_RE.sub(" ", _TAGS_RE.sub(" ", html)).strip()


def _parse_event_label(label: str) -> Optional[tuple[int, str]]:
    """'50 Freestyle' -> (50, 'FR')."""
    if not label:
        return None
    m = re.match(r"\s*(\d+)\s+([A-Za-z ]+)\s*$", label)
    if not m:
        return None
    dist = int(m.group(1))
    stroke_raw = m.group(2).strip().lower()
    stroke = _STROKE_MAP.get(stroke_raw)
    if not stroke:
        return None
    if dist not in {50, 100, 200, 400, 800, 1500}:
        return None
    return dist, stroke


def _parse_pb_table(table_html: str, course: str) -> list[PBEntry]:
    """Parse one <table> of LC or SC personal bests."""
    pbs: list[PBEntry] = []
    rows = _ROW_RE.findall(table_html)
    for row in rows:
        cells = [_strip(c) for c in _CELL_RE.findall(row)]
        if len(cells) < 8:
            continue
        # Skip the header row
        if cells[0].strip().lower() == "stroke":
            continue
        # LC row layout:
        # 0 stroke | 1 LC time | 2 conv to SC | 3 LC pts | 4 date | 5 meet | 6 venue | 7 licence | 8 level
        # SC row layout:
        # 0 stroke | 1 SC time | 2 conv to LC | 3 SC pts | 4 date | 5 meet | 6 venue | 7 licence | 8 level
        ev = _parse_event_label(cells[0])
        if not ev:
            continue
        dist, stroke = ev
        time_str = cells[1]
        time_sec = parse_swim_time(time_str)
        if time_sec is None:
            continue
        date_str = cells[4] if len(cells) > 4 else ""
        meet = cells[5] if len(cells) > 5 else ""
        venue = cells[6] if len(cells) > 6 else ""
        licence = cells[7] if len(cells) > 7 else ""
        level = cells[8] if len(cells) > 8 else ""
        pbs.append(PBEntry(
            stroke=stroke,
            distance=dist,
            course=course,
            time_str=time_str,
            time_sec=time_sec,
            date=date_str,
            date_iso=parse_site_date(date_str),
            meet=meet,
            venue=venue,
            licence=licence,
            level=level,
        ))
    return pbs


def _parse_swimmer_name(html: str) -> Optional[str]:
    """Best-effort: page title contains the swimmer's name."""
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if not m:
        return None
    title = _strip(m.group(1))
    # Site title looks like "Swim England :: Personal Best Times :: NAME"
    parts = re.split(r"\s*::\s*", title)
    if len(parts) >= 2:
        return parts[-1].strip() or None
    return title or None


def parse_pb_html(html: str, tiref: str, source_url: str, retrieved_at: str) -> SwimmerPBSnapshot:
    tables = _TABLE_RE.findall(html)
    pbs: list[PBEntry] = []
    if len(tables) >= 1:
        pbs.extend(_parse_pb_table(tables[0], "LC"))
    if len(tables) >= 2:
        pbs.extend(_parse_pb_table(tables[1], "SC"))
    name = _parse_swimmer_name(html)
    return SwimmerPBSnapshot(
        tiref=str(tiref),
        name=name,
        pbs=pbs,
        source_url=source_url,
        retrieved_at=retrieved_at,
        fetch_ok=True,
    )


# ---------- caching + fetch ----------
def _cache_path(tiref: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{tiref}.json"


def _load_cache(tiref: str, cache_dir: Path, ttl_days: int) -> Optional[SwimmerPBSnapshot]:
    p = _cache_path(tiref, cache_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    retrieved_at = data.get("retrieved_at")
    if retrieved_at:
        try:
            ts = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
            if age_days > ttl_days:
                return None
        except Exception:
            pass
    pbs = [PBEntry(**pb) for pb in data.get("pbs", [])]
    return SwimmerPBSnapshot(
        tiref=data["tiref"],
        name=data.get("name"),
        pbs=pbs,
        source_url=data["source_url"],
        retrieved_at=data["retrieved_at"],
        fetch_ok=data.get("fetch_ok", True),
        error=data.get("error"),
    )


def _save_cache(snap: SwimmerPBSnapshot, cache_dir: Path) -> None:
    p = _cache_path(snap.tiref, cache_dir)
    p.write_text(json.dumps(asdict(snap), indent=2))


def fetch_pb_snapshot(
    tiref: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    use_cache: bool = True,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> SwimmerPBSnapshot:
    """Fetch (or load from cache) the PB snapshot for one ASA member ID."""
    tiref = str(tiref).strip()
    if not tiref or not tiref.isdigit():
        return SwimmerPBSnapshot(tiref=tiref, name=None, pbs=[], source_url="",
                                 retrieved_at=datetime.now(timezone.utc).isoformat(),
                                 fetch_ok=False, error="invalid tiref")
    if use_cache:
        cached = _load_cache(tiref, cache_dir, ttl_days)
        if cached is not None:
            return cached

    url = PB_URL.format(tiref=tiref)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        snap = parse_pb_html(html, tiref, url, datetime.now(timezone.utc).isoformat())
        _save_cache(snap, cache_dir)
        if delay_sec:
            time.sleep(delay_sec)
        return snap
    except urllib.error.HTTPError as e:
        snap = SwimmerPBSnapshot(tiref=tiref, name=None, pbs=[], source_url=url,
                                 retrieved_at=datetime.now(timezone.utc).isoformat(),
                                 fetch_ok=False, error=f"HTTP {e.code}")
        return snap
    except Exception as e:
        snap = SwimmerPBSnapshot(tiref=tiref, name=None, pbs=[], source_url=url,
                                 retrieved_at=datetime.now(timezone.utc).isoformat(),
                                 fetch_ok=False, error=repr(e))
        return snap


# ---------- comparison ----------
def compare_to_pb(
    *,
    snapshot: Optional[SwimmerPBSnapshot],
    distance: int,
    stroke: str,
    course: str,
    swim_time_sec: float,
    swim_date_iso: Optional[str],
) -> PBComparison:
    """
    Compare a meet swim against the swimmer's PB snapshot.

    Course must match exactly (LC vs LC, SC vs SC). LC and SC are never mixed.
    """
    if snapshot is None or not snapshot.fetch_ok:
        return PBComparison(
            status="PB_UNVERIFIED", prior_time_sec=None, prior_time_str=None,
            prior_date_iso=None, delta_sec=None, source_url=None, retrieved_at=None,
            note="No PB snapshot available.",
        )
    key = f"{distance}_{stroke}_{course}"
    pb = snapshot.by_event().get(key)
    if pb is None:
        return PBComparison(
            status="PB_UNVERIFIED", prior_time_sec=None, prior_time_str=None,
            prior_date_iso=None, delta_sec=None,
            source_url=snapshot.source_url, retrieved_at=snapshot.retrieved_at,
            note=f"No prior {course} time on file for this event.",
        )
    delta = swim_time_sec - pb.time_sec  # negative = improvement
    # If the listed PB date matches the meet date, the site has already absorbed
    # this swim — we cannot prove it was a PB by comparison alone.
    same_day = swim_date_iso is not None and pb.date_iso == swim_date_iso
    if same_day and delta <= 0.005:
        # Swim equals or beats the listed PB and that PB is from today: the site
        # is showing this very swim as the PB. Likely PB, pending pre-meet snapshot.
        return PBComparison(
            status="LIKELY_PB", prior_time_sec=pb.time_sec, prior_time_str=pb.time_str,
            prior_date_iso=pb.date_iso, delta_sec=delta,
            source_url=snapshot.source_url, retrieved_at=snapshot.retrieved_at,
            note="Site PB is from this meet date; prior history not visible. Likely PB pending pre-meet snapshot.",
        )
    if same_day and delta > 0.005:
        # Listed PB is from today and swim is slower → another swim today was the PB.
        return PBComparison(
            status="NOT_PB", prior_time_sec=pb.time_sec, prior_time_str=pb.time_str,
            prior_date_iso=pb.date_iso, delta_sec=delta,
            source_url=snapshot.source_url, retrieved_at=snapshot.retrieved_at,
            note=f"Slower than the swimmer's other swim from this meet date by {delta:.2f}s.",
        )
    if delta < -0.005:
        return PBComparison(
            status="CONFIRMED_PB", prior_time_sec=pb.time_sec, prior_time_str=pb.time_str,
            prior_date_iso=pb.date_iso, delta_sec=delta,
            source_url=snapshot.source_url, retrieved_at=snapshot.retrieved_at,
            note=f"Improvement of {abs(delta):.2f}s over prior {course} PB.",
        )
    return PBComparison(
        status="NOT_PB", prior_time_sec=pb.time_sec, prior_time_str=pb.time_str,
        prior_date_iso=pb.date_iso, delta_sec=delta,
        source_url=snapshot.source_url, retrieved_at=snapshot.retrieved_at,
        note=f"Slower than prior {course} PB by {delta:.2f}s.",
    )


# ---------- batch helper ----------
def fetch_roster(
    tirefs: list[str],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    use_cache: bool = True,
    delay_sec: float = REQUEST_DELAY_SEC,
    progress_cb=None,
) -> dict[str, SwimmerPBSnapshot]:
    """Fetch PB snapshots for a list of ASA member IDs. Returns dict by tiref."""
    out: dict[str, SwimmerPBSnapshot] = {}
    seen: set[str] = set()
    total = len(tirefs)
    for i, t in enumerate(tirefs):
        t = str(t).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        snap = fetch_pb_snapshot(t, cache_dir=cache_dir, ttl_days=ttl_days,
                                 use_cache=use_cache, delay_sec=delay_sec)
        out[t] = snap
        if progress_cb:
            try:
                progress_cb(i + 1, total, snap)
            except Exception:
                pass
    return out
