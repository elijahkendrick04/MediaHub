"""
PC.10 — public club achievements wall: token resolution + approved-card feed.

A zero-gating distribution surface: a per-club hosted page of *approved*
cards plus an embed and RSS/JSON feed for club websites — first-party Flask,
no platform review anywhere. Opt-in and conservative by default:

- The wall is keyed by an unguessable per-org token
  (``ClubProfile.public_wall_token``); switching the wall off clears the
  token, so old URLs 404. The token scopes exactly one org — nothing
  cross-tenant is reachable through it (ADR-0003 holds).
- Only cards whose workflow state is APPROVED (or POSTED, which is an
  approved card that has since been published) ever appear. QUEUE, EDITED
  and REJECTED never do.
- ``public_wall_initials_only`` (default on) reduces athlete names to
  initials in all wall *text*; the club may also exclude individual cards
  via ``public_wall_excluded_cards`` ("run_id::card_id" keys).
- **Per-athlete consent (W.2 → PC.12) is enforced here too.** When the
  workspace runs a consent regime, every card's athlete is resolved
  against the registry: a blocked athlete (``do_not_feature``, or no
  consent on file under an active regime) never appears on the wall, in
  the feeds, or via the card-image route; an ``initials_only`` athlete is
  initialled even when the blanket toggle is off. The most restrictive of
  the toggle and the athlete's recorded consent always wins — consent can
  only tighten the wall, never loosen it.

Everything here is read-only: no caption-memory capture, no workflow
mutation — a public page load must never have side effects.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Optional

from mediahub.web.club_profile import ClubProfile, list_profiles

# Wall text shows at most this many cards; feeds use the same cap.
WALL_CARD_LIMIT = 60
_RUNS_SCANNED_LIMIT = 30

# Display preference when a card was rendered in several formats.
_FORMAT_PREFERENCE = ("feed_portrait", "feed_square", "story", "reel_cover", "carousel_slide")


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _runs_dir() -> Path:
    return _data_dir() / "runs_v4"


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def card_key(run_id: str, card_id: str) -> str:
    return f"{run_id}::{card_id}"


def initials_of(name: str) -> str:
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return ""
    return ".".join(p[0].upper() for p in parts) + "."


def _consent_policy(profile_id: str, swimmer_name: str):
    """The athlete's enforceable consent policy, or ``None`` when the
    workspace runs no consent regime (legacy behaviour applies).

    Mirrors the generation/publish-gate semantics in
    ``mediahub.safeguarding.consent.effective_policy``; a wholly failed
    lookup (import error etc.) returns ``None`` so a public page never
    500s — the blanket initials-only default still applies.
    """
    name = (swimmer_name or "").strip()
    if not profile_id or not name:
        return None
    try:
        from mediahub.safeguarding import effective_policy, regime_active

        if not regime_active(profile_id):
            return None
        return effective_policy(profile_id, name)
    except Exception:
        return None


def profile_for_token(token: str) -> Optional[ClubProfile]:
    """Resolve a wall token to its (enabled) org. None for anything else.

    A disabled wall keeps no token, so revocation is structural: the old
    URL resolves to nothing.
    """
    token = (token or "").strip()
    if not token:
        return None
    for prof in list_profiles():
        expected = (getattr(prof, "public_wall_token", "") or "").strip()
        if not expected or not getattr(prof, "public_wall_enabled", False):
            continue
        if hmac.compare_digest(expected, token):
            return prof
    return None


def _recent_done_run_ids(profile_id: str, limit: int = _RUNS_SCANNED_LIMIT) -> list[str]:
    """Newest-first finished runs for one org, from the runs DB (fail-soft)."""
    db_path = _data_dir() / "data.db"
    if not db_path.exists():
        return []
    import sqlite3

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT id FROM runs WHERE profile_id = ? AND status = 'done' "
                "ORDER BY created_at DESC LIMIT ?",
                (profile_id, int(limit)),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    return [r[0] for r in rows]


def _load_run_json(run_id: str) -> Optional[dict]:
    runs_dir = _runs_dir()
    for candidate in (runs_dir / f"{run_id}.json", runs_dir / run_id / "run.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _achievements_by_card_id(run_data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    rr = run_data.get("recognition_report") or {}
    for ra in rr.get("ranked_achievements") or []:
        ach = ra.get("achievement") or {}
        cid = ach.get("swim_id") or ra.get("id")
        if cid:
            out[str(cid)] = ach
    for c in run_data.get("cards") or []:
        cid = c.get("swim_id") or c.get("id")
        if cid and str(cid) not in out:
            out[str(cid)] = c
    return out


def _approved_card_ids(run_id: str) -> set[str]:
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    try:
        states = WorkflowStore(_runs_dir()).load(run_id)
    except Exception:
        return set()
    out = set()
    for cid, st in states.items():
        status = getattr(st, "status", None)
        if status in (CardStatus.APPROVED, CardStatus.POSTED):
            out.add(str(cid))
    return out


def _best_visual_for_cards(run_id: str, wanted_card_ids: set[str]) -> dict[str, dict]:
    """Map card_id → {png_path, format_name, recorded_at} for rendered cards.

    Scans the run's visual sidecars (``visuals/<brief_id>/visual.json``);
    when a card was rendered more than once the newest sidecar wins.
    """
    out: dict[str, dict] = {}
    vroot = _runs_dir() / run_id / "visuals"
    if not vroot.is_dir():
        return out
    for brief_dir in vroot.iterdir():
        sidecar = brief_dir / "visual.json"
        if not brief_dir.is_dir() or not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            continue
        cid = str(payload.get("content_item_id") or "")
        if cid not in wanted_card_ids:
            continue
        png_path = None
        format_name = None
        for fmt in _FORMAT_PREFERENCE:
            candidate = brief_dir / f"{fmt}.png"
            if candidate.exists():
                png_path = candidate
                format_name = fmt
                break
        if png_path is None:
            continue
        mtime = sidecar.stat().st_mtime
        if cid in out and out[cid]["_mtime"] >= mtime:
            continue
        out[cid] = {
            "png_path": str(png_path),
            "format_name": format_name,
            "_mtime": mtime,
        }
    return out


def wall_cards(
    profile: ClubProfile,
    limit: int = WALL_CARD_LIMIT,
    *,
    consent_hidden: Optional[list] = None,
) -> list[dict]:
    """The org's public wall feed: approved, rendered, non-excluded cards
    whose athlete's recorded consent allows a public appearance.

    Returns newest-run-first dicts::

        {run_id, card_id, title, alt_text, meet_name, event, time,
         format_name}

    Names in ``title``/``alt_text`` honour the per-athlete consent level
    and the blanket initials-only toggle (most restrictive wins). Cards
    for blocked athletes are dropped; pass ``consent_hidden`` (a list) to
    receive ``{run_id, card_id, athlete, level, reason}`` for each drop —
    the members-only settings page uses it to explain *why* a card is off
    the wall. The PNG itself is served by the wall image route from the
    path this module resolved — paths never leave the server.
    """
    excluded = set(getattr(profile, "public_wall_excluded_cards", None) or [])
    initials_only = bool(getattr(profile, "public_wall_initials_only", True))

    cards: list[dict] = []
    for run_id in _recent_done_run_ids(profile.profile_id):
        if len(cards) >= limit:
            break
        approved = _approved_card_ids(run_id)
        if not approved:
            continue
        run_data = _load_run_json(run_id) or {}
        # Hard tenant check: the run JSON must agree it belongs to this org.
        run_owner = run_data.get("profile_id") or ""
        if run_owner and run_owner != profile.profile_id:
            continue
        achs = _achievements_by_card_id(run_data)
        visuals = _best_visual_for_cards(run_id, approved)
        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name") or ""
        for cid in sorted(approved):
            if len(cards) >= limit:
                break
            if card_key(run_id, cid) in excluded:
                continue
            vis = visuals.get(cid)
            if vis is None:
                continue  # the wall only serves already-rendered cards
            ach = achs.get(cid) or {}
            raw_name = str(ach.get("swimmer_name") or "").strip()
            policy = _consent_policy(profile.profile_id, raw_name)
            if policy is not None and policy.blocked:
                if consent_hidden is not None:
                    consent_hidden.append(
                        {
                            "run_id": run_id,
                            "card_id": cid,
                            "athlete": raw_name,
                            "level": policy.level,
                            "reason": policy.reason,
                        }
                    )
                continue
            use_initials = initials_only or (policy is not None and policy.level == "initials_only")
            display_name = initials_of(raw_name) if use_initials else raw_name
            event = str(ach.get("event") or "").strip()
            time_str = str(ach.get("time") or ach.get("final_time") or "").strip()
            title_bits = [b for b in (display_name, event, time_str) if b]
            title = " — ".join(title_bits) or "Club achievement"
            alt_bits = title_bits + ([f"at {meet_name}"] if meet_name else [])
            cards.append(
                {
                    "run_id": run_id,
                    "card_id": cid,
                    "title": title,
                    "alt_text": ", ".join(alt_bits) or "Achievement card",
                    "meet_name": meet_name,
                    "event": event,
                    "time": time_str,
                    "format_name": vis["format_name"],
                }
            )
    return cards


def wall_image_path(profile: ClubProfile, run_id: str, card_id: str) -> Optional[str]:
    """Resolve the PNG path for one wall card — only if it would appear on
    the wall (approved, rendered, not excluded, owned by this org, and the
    athlete's consent allows a public appearance)."""
    if card_key(run_id, card_id) in set(getattr(profile, "public_wall_excluded_cards", None) or []):
        return None
    if run_id not in _recent_done_run_ids(profile.profile_id, limit=200):
        return None
    approved = _approved_card_ids(run_id)
    if str(card_id) not in approved:
        return None
    run_data = _load_run_json(run_id) or {}
    run_owner = run_data.get("profile_id") or ""
    if run_owner and run_owner != profile.profile_id:
        return None
    ach = _achievements_by_card_id(run_data).get(str(card_id)) or {}
    policy = _consent_policy(profile.profile_id, str(ach.get("swimmer_name") or "").strip())
    if policy is not None and policy.blocked:
        return None  # a blocked athlete's card is unreachable, not just unlisted
    vis = _best_visual_for_cards(run_id, {str(card_id)}).get(str(card_id))
    return vis["png_path"] if vis else None
