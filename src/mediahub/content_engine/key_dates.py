"""Club-aware key dates — the calendar's preloaded hooks (roadmap 1.14).

The planner already knows *what* a club should post (``planner.py``); the 1.14
calendar needs *when*. Two date sources feed it:

* **Curated key-date packs** — shipped, read-only, provenance-stamped YAML under
  ``data/key_dates/<sport>.yaml``: the always-on annual hooks a club can build
  content around (UN/governing-body world days, sport observances). Same
  category as ``data/sport_profiles/`` — human-authored config, not runtime
  state, so it resolves relative to the repo ``data/`` dir (env-overridable for
  tests), never ``DATA_DIR``.
* **Operator-entered dates** — the upcoming events the operator already types on
  the Plan page (``content_engine.inputs``). Those stay the source of truth for
  precise, club-specific fixtures; the packs never invent a club's fixtures.

Every key date resolves to an **exact** calendar date deterministically — either
a ``fixed`` month/day, or an ``nth_weekday`` rule (e.g. "4th Wednesday of
September") computed in code. Nothing is approximated onto the calendar: an
entry whose real date genuinely moves year to year is expressed as a rule that
resolves exactly, or it is left to operator entry. Honesty over volume.
"""

from __future__ import annotations

import calendar as _calmod
import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

# Repo layout: src/mediahub/content_engine/key_dates.py → repo root is parents[3]
# and the shipped packs live at data/key_dates/.
_REPO_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "key_dates"

KEY_DATE_KINDS = ("awareness", "observance", "sport", "governance", "season")


@dataclass(frozen=True)
class KeyDate:
    """One curated annual hook, with how its exact date is derived + provenance."""

    name: str
    kind: str  # one of KEY_DATE_KINDS
    rule: dict  # {"type":"fixed","month":M,"day":D} | {"type":"nth_weekday",...}
    note: str = ""
    source: str = ""  # provenance — where the date/observance comes from

    def resolve(self, year: int) -> Optional[date]:
        """The exact date this hook falls on in ``year`` (None if the rule is
        malformed — an honest skip, never a guessed date)."""
        return _resolve_rule(self.rule, year)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "rule": dict(self.rule),
            "note": self.note,
            "source": self.source,
        }


@dataclass
class KeyDatePack:
    """The shipped pack for one sport: a list of curated :class:`KeyDate`s."""

    sport: str
    display_name: str
    key_dates: list[KeyDate] = field(default_factory=list)


def _resolve_rule(rule: object, year: int) -> Optional[date]:
    if not isinstance(rule, dict):
        return None
    rtype = str(rule.get("type") or "").strip()
    try:
        if rtype == "fixed":
            return date(year, int(rule["month"]), int(rule["day"]))
        if rtype == "nth_weekday":
            return _nth_weekday(year, int(rule["month"]), int(rule["weekday"]), int(rule["n"]))
    except (KeyError, ValueError, TypeError):
        return None
    return None


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> Optional[date]:
    """The ``n``-th ``weekday`` (0=Mon … 6=Sun) of ``month``. ``n`` may be
    negative to count from the end (-1 = last). None if it doesn't exist."""
    if not (1 <= month <= 12) or not (0 <= weekday <= 6) or n == 0:
        return None
    days_in_month = _calmod.monthrange(year, month)[1]
    matches = [d for d in range(1, days_in_month + 1) if date(year, month, d).weekday() == weekday]
    idx = n - 1 if n > 0 else n  # n>0 → 1-based from start; n<0 → from end
    try:
        return date(year, month, matches[idx])
    except IndexError:
        return None


def _packs_dir(base_dir: Optional[os.PathLike | str] = None) -> Path:
    if base_dir is not None:
        return Path(base_dir)
    env = os.environ.get("MEDIAHUB_KEY_DATES_DIR")
    if env:
        return Path(env)
    return _REPO_DATA_DIR


def _clean_key_date(raw: object) -> Optional[KeyDate]:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    rule = raw.get("rule")
    if not name or not isinstance(rule, dict):
        return None
    kind = str(raw.get("kind") or "awareness").strip().lower()
    if kind not in KEY_DATE_KINDS:
        kind = "awareness"
    kd = KeyDate(
        name=name[:160],
        kind=kind,
        rule=dict(rule),
        note=str(raw.get("note") or "").strip()[:280],
        source=str(raw.get("source") or "").strip()[:280],
    )
    # Reject a pack entry whose rule can't resolve — better an honest omission
    # than a hook that silently never lands on the calendar.
    if kd.resolve(2026) is None:
        return None
    return kd


@lru_cache(maxsize=16)
def _load_pack_cached(sport: str, base: str) -> Optional[KeyDatePack]:
    path = Path(base) / f"{sport}.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    dates = [kd for kd in map(_clean_key_date, data.get("key_dates") or []) if kd]
    return KeyDatePack(
        sport=str(data.get("sport") or sport),
        display_name=str(data.get("display_name") or sport.title()),
        key_dates=dates,
    )


def load_key_date_pack(
    sport: str, *, base_dir: Optional[os.PathLike | str] = None
) -> Optional[KeyDatePack]:
    """Load the curated pack for ``sport`` (e.g. ``"swimming"``), or None when no
    pack ships for it — an honest absence, never a fabricated default."""
    if not sport:
        return None
    return _load_pack_cached(str(sport).strip().lower(), str(_packs_dir(base_dir)))


@dataclass(frozen=True)
class ResolvedKeyDate:
    """A :class:`KeyDate` pinned to a concrete date inside the queried window."""

    on: date
    name: str
    kind: str
    note: str
    source: str

    def to_dict(self) -> dict:
        return {
            "date": self.on.isoformat(),
            "name": self.name,
            "kind": self.kind,
            "note": self.note,
            "source": self.source,
        }


def key_dates_in_range(
    sport: str,
    start: date,
    end: date,
    *,
    base_dir: Optional[os.PathLike | str] = None,
) -> list[ResolvedKeyDate]:
    """Every curated key date that falls in ``[start, end]`` (inclusive), each
    resolved to its exact date. Spans year boundaries (resolves the rule for
    every year the window touches). Sorted by date. Empty when no pack ships."""
    pack = load_key_date_pack(sport, base_dir=base_dir)
    if pack is None or start > end:
        return []
    out: list[ResolvedKeyDate] = []
    for year in range(start.year, end.year + 1):
        for kd in pack.key_dates:
            on = kd.resolve(year)
            if on is not None and start <= on <= end:
                out.append(
                    ResolvedKeyDate(
                        on=on, name=kd.name, kind=kd.kind, note=kd.note, source=kd.source
                    )
                )
    out.sort(key=lambda r: (r.on, r.name))
    return out


__all__ = [
    "KeyDate",
    "KeyDatePack",
    "ResolvedKeyDate",
    "KEY_DATE_KINDS",
    "load_key_date_pack",
    "key_dates_in_range",
]
