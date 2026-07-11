"""email_design.grounding — gather *the period's approved content* into facts.

This is the deterministic, source-grounded base a newsletter is built from — the
newsletter's equivalent of :mod:`documents.grounding`. It answers one question:
*for this club, over this date range, what real, human-approved content should the
newsletter carry?* Nothing here is invented or AI-written — it is assembled from:

* **approved cards** across every run whose meet falls in the window (via
  :func:`workflow.pack.build_content_pack`, which already filters to the cards a
  human approved and applies the club's brand captions);
* **headline numbers** counted from those approved cards (PBs, medals, club
  records, athletes, meets) — the only stats the newsletter may show;
* **upcoming fixtures** from the planner calendar (a forward window);
* the active **sponsor** from the club's sponsor registry.

Multi-tenancy is enforced by construction: a run is only gathered when the active
profile owns it (ownerless legacy runs stay readable, matching the rest of the
web layer). The AI editorial pass (:mod:`email_design.draft`) may only *phrase
prose around* these facts — and every number it writes is validated against
:meth:`NewsletterFacts.allowed_numbers`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

# How far ahead "upcoming fixtures" looks by default.
_FIXTURE_WINDOW_DAYS = 56
_MAX_RECAPS = 6
_MAX_SPOTLIGHTS = 3


def _runs_dir(override: Optional[Path] = None) -> Path:
    """Resolve the runs directory the same way the web layer does (so a sidecar
    written by the app is found here too)."""
    if override is not None:
        return Path(override)
    return Path(
        os.environ.get(
            "RUNS_DIR",
            str(Path(os.environ.get("DATA_DIR", ".")).resolve() / "runs_v4"),
        )
    )


def _parse_date(value: Any) -> Optional[date]:
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _meet_date(run_data: dict) -> Optional[date]:
    meet = run_data.get("meet") or {}
    for key in ("date", "start_date", "meet_date"):
        d = _parse_date(meet.get(key))
        if d:
            return d
    # fall back to when the run finished / was created
    for key in ("finished_at", "created_at"):
        d = _parse_date(run_data.get(key))
        if d:
            return d
    return None


def _owns(run_data: dict, profile_id: str) -> bool:
    """Tenant gate: the active profile must own the run (ownerless legacy runs
    stay readable, matching ``_can_access_run``)."""
    owner = str(run_data.get("profile_id") or "")
    if not owner:
        return True
    return owner == str(profile_id or "")


def _period_label(start: date, end: date) -> str:
    """A human label for the window: "June 2026", "Q2 2026" or a date range."""
    if start.year == end.year and start.month == end.month:
        return start.strftime("%B %Y")
    if start.year == end.year:
        return f"{start.strftime('%B')}–{end.strftime('%B %Y')}"
    return f"{start.strftime('%b %Y')} – {end.strftime('%b %Y')}"


# ---------------------------------------------------------------------------
# NewsletterFacts
# ---------------------------------------------------------------------------


@dataclass
class NewsletterFacts:
    """The source-grounded content base for one newsletter (no AI, no invented
    values). Cards carry text + a ``card_ref`` the web layer resolves to a public
    image URL; numbers come only from the approved cards."""

    club_name: str = ""
    period: str = ""
    date_start: str = ""  # ISO
    date_end: str = ""  # ISO
    recaps: list[dict] = field(default_factory=list)  # {title, body, card_ref, href, image_url}
    spotlights: list[dict] = field(default_factory=list)  # {name, body, card_ref}
    stats: list[dict] = field(default_factory=list)  # {value, label}
    fixtures: list[dict] = field(default_factory=list)  # {date, name, venue}
    sponsor: Optional[dict] = None  # {name, href, logo_src}
    source_refs: list[str] = field(default_factory=list)

    def allowed_numbers(self) -> set[float]:
        """Every number the AI editorial pass is allowed to state: the stat
        values, the period years, and 1/2/3 (ordinals)."""
        allowed: set[float] = {1.0, 2.0, 3.0}
        for s in self.stats:
            try:
                allowed.add(float(str(s.get("value", "")).replace(",", "")))
            except ValueError:
                pass
        for iso in (self.date_start, self.date_end):
            d = _parse_date(iso)
            if d:
                allowed.add(float(d.year))
        return allowed

    def facts_block(self) -> str:
        """The plain-text fact sheet handed to the LLM."""
        lines = [f"Club: {self.club_name}", f"Period: {self.period}"]
        if self.stats:
            lines.append("Headline numbers:")
            lines += [f"  - {s.get('value')} {s.get('label')}" for s in self.stats]
        if self.recaps:
            lines.append("Standout results (already approved):")
            lines += [f"  - {r.get('title')}" for r in self.recaps[:6]]
        if self.fixtures:
            lines.append("Upcoming fixtures:")
            lines += [f"  - {f.get('date')} {f.get('name')}".strip() for f in self.fixtures[:5]]
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return not (self.recaps or self.spotlights or self.stats or self.fixtures)


# ---------------------------------------------------------------------------
# Card text extraction (deterministic)
# ---------------------------------------------------------------------------


def _achievement_label(atype: str) -> str:
    t = (atype or "").lower()
    if "official_pb" in t:
        return "official PB"
    if "pb" in t:
        return "personal best"
    if "gold" in t:
        return "gold medal"
    if "silver" in t:
        return "silver medal"
    if "bronze" in t:
        return "bronze medal"
    if "club_record" in t:
        return "club record"
    if "qual" in t:
        return "qualifying time"
    if "final" in t:
        return "final"
    return "standout swim"


def _card_text(card: dict, tone: str) -> tuple[str, str]:
    """A (title, body) for an approved card — preferring the club's brand caption,
    falling back to a plain, fact-derived line."""
    ach = card.get("achievement") or {}
    swimmer = str(ach.get("swimmer_name") or "").strip()
    event = str(ach.get("event") or "").strip()
    atype = str(ach.get("type") or "")

    bc = card.get("brand_captions") or {}
    active = bc.get(tone) if isinstance(bc, dict) else None
    if not isinstance(active, dict) and isinstance(bc, dict) and bc:
        # any tone we have, deterministically (first by sorted key)
        active = bc[sorted(bc.keys())[0]]
    title = ""
    body = ""
    if isinstance(active, dict):
        title = str(active.get("headline") or "").strip()
        body = str(active.get("body") or active.get("caption") or "").strip()
    if not title:
        label = _achievement_label(atype)
        bits = [b for b in (swimmer, event) if b]
        title = " — ".join(bits) if bits else label.capitalize()
        if label and event:
            title = f"{title} ({label})"
    if not body:
        body = str(card.get("caption_only") or "").strip()
    return title, body


# ---------------------------------------------------------------------------
# Gather
# ---------------------------------------------------------------------------


def _runs_in_window(
    profile_id: str, start: date, end: date, runs_dir: Path
) -> list[tuple[str, dict, date]]:
    """Owned runs whose meet date falls in [start, end], newest meet first."""
    out: list[tuple[str, dict, date]] = []
    if not runs_dir.exists():
        return out
    for f in sorted(runs_dir.glob("*.json")):
        if f.name.endswith("__workflow.json") or f.name.startswith("_"):
            continue
        try:
            run_data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(run_data, dict):
            continue
        if not _owns(run_data, profile_id):
            continue
        md = _meet_date(run_data)
        if md is None or not (start <= md <= end):
            continue
        out.append((f.stem, run_data, md))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def _pinned_run(
    profile_id: str, run_id: str, runs_dir: Path
) -> list[tuple[str, dict, Optional[date]]]:
    """The single owned run named by ``run_id`` (H-12 meet pinning), or ``[]``.

    Same shape as one :func:`_runs_in_window` entry so the caller's loop is
    unchanged; the same ``_owns`` tenant gate applies, so a foreign run id
    yields nothing rather than another org's results.
    """
    f = runs_dir / f"{run_id}.json"
    if not f.exists():
        return []
    try:
        run_data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(run_data, dict) or not _owns(run_data, profile_id):
        return []
    return [(run_id, run_data, _meet_date(run_data))]


def _upcoming_fixtures(profile_id: str, sport: str, now: date, runs_dir: Path) -> list[dict]:
    """Forward-looking fixtures from the planner calendar."""
    try:
        from mediahub.content_engine.calendar import build_calendar

        cal = build_calendar(
            profile_id,
            sport or "swimming",
            start=now,
            end=now + timedelta(days=_FIXTURE_WINDOW_DAYS),
            data_dir=runs_dir.parent if runs_dir.name == "runs_v4" else None,
        )
    except Exception:
        return []
    fixtures: list[dict] = []
    for e in getattr(cal, "entries", []) or []:
        if getattr(e, "kind", "") not in ("event", "key_date"):
            continue
        d = _parse_date(getattr(e, "date", ""))
        label = d.strftime("%-d %b") if d else ""
        fixtures.append(
            {
                "date": label,
                "name": str(getattr(e, "title", "") or ""),
                "venue": str((getattr(e, "meta", {}) or {}).get("venue", "")),
            }
        )
    return fixtures[:5]


def _active_sponsor(profile: Any, today: date, asset_url: Optional[Callable]) -> Optional[dict]:
    """The active sponsor (registry first, legacy ``sponsor_name`` fallback)."""
    sponsors = _attr(profile, "sponsors") or []
    for s in sponsors if isinstance(sponsors, list) else []:
        if not isinstance(s, dict):
            continue
        af = _parse_date(s.get("active_from"))
        au = _parse_date(s.get("active_until"))
        if af and today < af:
            continue
        if au and today > au:
            continue
        logo_src = ""
        asset_id = s.get("logo_asset_id")
        if asset_id and asset_url:
            try:
                logo_src = asset_url(asset_id) or ""
            except Exception:
                logo_src = ""
        return {
            "name": str(s.get("name") or ""),
            "href": str(s.get("website") or ""),
            "logo_src": logo_src,
        }
    legacy = _attr(profile, "sponsor_name")
    if legacy:
        return {"name": str(legacy), "href": "", "logo_src": ""}
    return None


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _consent_block_reason(profile_id: str, swimmer_name: str) -> Optional[str]:
    """Why this athlete must not appear in newsletter text at all — or ``None``.

    Same unified check the public wall applies (``compliance.gate.
    consent_block_reason``): a newsletter published at ``/newsletter/<token>``
    is public content, so a consent-blocked athlete's name must not ship in
    its recaps, spotlights or fact sheet. A wholly failed lookup returns
    ``None`` so gathering never 500s.
    """
    name = (swimmer_name or "").strip()
    if not profile_id or not name:
        return None
    try:
        from mediahub.compliance.gate import consent_block_reason

        return consent_block_reason(profile_id, name)
    except Exception:
        return None


def gather_facts(
    profile_id: str,
    *,
    start: date,
    end: date,
    profile: Any = None,
    now: Optional[date] = None,
    runs_dir: Optional[Path] = None,
    tone: str = "warm-club",
    card_image_url: Optional[Callable[[str, str], str]] = None,
    asset_url: Optional[Callable[[str], str]] = None,
    run_id: Optional[str] = None,
) -> NewsletterFacts:
    """Assemble the period's :class:`NewsletterFacts` for ``profile_id``.

    ``card_image_url(run_id, card_id) -> url`` and ``asset_url(asset_id) -> url``
    are optional resolvers the web layer supplies to turn internal refs into
    public image URLs; without them, cards render text-first (still valid email).

    ``run_id`` (H-12) pins the facts to exactly one owned run — the meet-digest
    "which meet?" chooser — instead of every run in the date window; the
    period label then reflects that meet's own date. ``None`` keeps the
    date-window behaviour unchanged.
    """
    if start > end:
        start, end = end, start
    now = now or date.today()
    rd = _runs_dir(runs_dir)
    if profile is None:
        try:
            from mediahub.web.club_profile import load_profile

            profile = load_profile(profile_id)
        except Exception:
            profile = None

    club_name = str(_attr(profile, "display_name") or _attr(profile, "short_name") or "")
    sport = str(_attr(profile, "sport") or "swimming")

    recaps: list[dict] = []
    spotlights: list[dict] = []
    source_refs: list[str] = []
    n_pb = n_medal = n_record = 0
    swimmers: set[str] = set()
    by_swimmer: dict[str, list[dict]] = {}

    consent_cache: dict[str, Optional[str]] = {}

    if run_id:
        runs = _pinned_run(profile_id, run_id, rd)
        # The digest speaks about the meet itself, so the period follows the
        # pinned meet's date (when it has one), not the range picker.
        if runs and runs[0][2] is not None:
            start = end = runs[0][2]
    else:
        runs = _runs_in_window(profile_id, start, end, rd)
    for run_id, _run_data, _md in runs:
        try:
            from mediahub.workflow.pack import build_content_pack

            cards = build_content_pack(run_id, profile_id, runs_dir=rd)
        except Exception:
            cards = []
        if cards:
            source_refs.append(f"run:{run_id}")
        for card in cards:
            ach = card.get("achievement") or {}
            atype = str(ach.get("type") or "").lower()
            name = str(ach.get("swimmer_name") or "").strip()
            if name:
                if name not in consent_cache:
                    consent_cache[name] = _consent_block_reason(profile_id, name)
                if consent_cache[name]:
                    continue  # consent always wins — drop the card entirely
            if "pb" in atype:
                n_pb += 1
            if "medal" in atype or atype in ("medal_gold", "medal_silver", "medal_bronze"):
                n_medal += 1
            if "club_record" in atype:
                n_record += 1
            if name:
                swimmers.add(name)
            title, body = _card_text(card, tone)
            card_ref = f"{run_id}/{card.get('_card_id', '')}"
            image_url = ""
            if card_image_url:
                try:
                    image_url = card_image_url(run_id, str(card.get("_card_id", ""))) or ""
                except Exception:
                    image_url = ""
            recap = {
                "title": title,
                "body": body,
                "card_ref": card_ref,
                "href": "",
                "image_url": image_url,
                "swimmer": name,
            }
            recaps.append(recap)
            if name:
                by_swimmer.setdefault(name, []).append(recap)

    recaps = recaps[:_MAX_RECAPS]

    # spotlights: swimmers with multiple approved cards in the window
    for name, items in by_swimmer.items():
        if len(items) >= 2:
            spotlights.append(
                {
                    "name": name,
                    "body": f"{len(items)} standout swims this period.",
                    "card_ref": items[0]["card_ref"],
                    "n": len(items),
                }
            )
    spotlights.sort(key=lambda s: -s["n"])
    spotlights = spotlights[:_MAX_SPOTLIGHTS]

    stats: list[dict] = []
    if n_pb:
        stats.append({"value": str(n_pb), "label": "PBs" if n_pb != 1 else "PB"})
    if n_medal:
        stats.append({"value": str(n_medal), "label": "Medals" if n_medal != 1 else "Medal"})
    if n_record:
        stats.append(
            {"value": str(n_record), "label": "Club records" if n_record != 1 else "Club record"}
        )
    if swimmers:
        stats.append({"value": str(len(swimmers)), "label": "Swimmers"})
    stats = stats[:4]

    fixtures = _upcoming_fixtures(profile_id, sport, now, rd)
    sponsor = _active_sponsor(profile, now, asset_url)

    return NewsletterFacts(
        club_name=club_name,
        period=_period_label(start, end),
        date_start=start.isoformat(),
        date_end=end.isoformat(),
        recaps=recaps,
        spotlights=spotlights,
        stats=stats,
        fixtures=fixtures,
        sponsor=sponsor,
        source_refs=source_refs,
    )


__all__ = ["NewsletterFacts", "gather_facts"]
