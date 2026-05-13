"""
turn_into/pipeline.py — orchestrate the 7 artefact builders.

Public surface:

    turn_meet_into_pack(run_data, profile, *, deterministic=False) -> dict
    save_pack(pack, run_id, base_dir=None) -> Path
    load_pack(run_id, pack_id, base_dir=None) -> dict | None
    list_packs(run_id, base_dir=None) -> list[dict]

The pack dict shape::

    {
      "pack_id":          str (uuid),
      "run_id":           str,
      "generated_at":     iso8601 utc,
      "meet_name":        str,
      "profile_id":       str,
      "voice_tone":       str,
      "deterministic":    bool,
      "artefacts":        [ artefact_dict, ... ],
      "skipped":          [ {"type": str, "reason": str}, ... ],
    }

Storage layout under ``DATA_DIR / turn_into_packs / <run_id> / <pack_id>.json``
keeps old packs alongside new ones — the user can re-generate freely.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import templates as _t


# ---------- pack-store helpers -----------------------------------------


def _packs_base_dir(base_dir: Optional[Path] = None) -> Path:
    """Return the root directory for stored Turn-Into packs.

    Priority: explicit override > DATA_DIR env > source-relative fallback.
    """
    if base_dir is not None:
        return Path(base_dir)
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env) / "turn_into_packs"
    return Path(__file__).resolve().parents[1] / "turn_into_packs"


def _pack_dir(run_id: str, base_dir: Optional[Path] = None) -> Path:
    d = _packs_base_dir(base_dir) / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_pack(pack: dict, run_id: str, base_dir: Optional[Path] = None) -> Path:
    """Persist a pack dict to disk and return the resulting path."""
    pack_id = pack.get("pack_id") or uuid.uuid4().hex
    pack["pack_id"] = pack_id
    pack["run_id"] = run_id
    path = _pack_dir(run_id, base_dir) / f"{pack_id}.json"
    path.write_text(json.dumps(pack, indent=2, default=str))
    return path


def load_pack(run_id: str, pack_id: str, base_dir: Optional[Path] = None) -> Optional[dict]:
    path = _pack_dir(run_id, base_dir) / f"{pack_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_packs(run_id: str, base_dir: Optional[Path] = None) -> list[dict]:
    """Return summary dicts for every pack saved for ``run_id``, newest first."""
    d = _pack_dir(run_id, base_dir)
    out: list[dict] = []
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        out.append({
            "pack_id": data.get("pack_id", f.stem),
            "generated_at": data.get("generated_at", ""),
            "n_artefacts": len(data.get("artefacts", []) or []),
            "n_skipped": len(data.get("skipped", []) or []),
            "deterministic": bool(data.get("deterministic", False)),
        })
    out.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
    return out


# ---------- the main pipeline ------------------------------------------


def _meet_summary(run_data: dict) -> dict:
    meet = run_data.get("meet") or {}
    return {
        "name": meet.get("name", "") or "(unknown meet)",
        "start_date": meet.get("start_date", ""),
        "end_date": meet.get("end_date", ""),
        "course": meet.get("course", ""),
        "venue": meet.get("venue", ""),
        "profile_display": run_data.get("profile_display", ""),
    }


def _resolve_voice_profile(profile_id: str):
    """Load the voice profile if available; never crash."""
    try:
        from mediahub.voice.store import load_voice_profile
        return load_voice_profile(profile_id)
    except Exception:
        return None


def _resolve_brand_kit(profile):
    if profile is None:
        return None
    try:
        return profile.get_brand_kit()
    except Exception:
        return None


def turn_meet_into_pack(
    run_data: dict,
    profile,
    *,
    deterministic: bool = False,
) -> dict:
    """Generate the full 7-artefact content pack for one meet.

    Parameters
    ----------
    run_data : dict
        The full persisted run dict (the same shape returned by
        ``mediahub.web.web._load_run``).
    profile : ClubProfile
        Loaded club profile — drives sponsor / voice / next-meet inputs.
    deterministic : bool
        When True, skip every LLM call and use the heuristic fallback in
        every artefact. Tests rely on this.

    Returns
    -------
    dict
        Pack dict (see module docstring).
    """
    meet_summary = _meet_summary(run_data)
    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []

    profile_id = getattr(profile, "profile_id", "") if profile else ""
    voice_profile = _resolve_voice_profile(profile_id) if profile_id else None
    brand_kit = _resolve_brand_kit(profile)

    skipped: list[dict] = []

    # Each builder makes its own LLM calls — they're network-bound, so running
    # them in parallel cuts a 7-artefact pack from ~3 min to ~45s with Gemini.
    # All builders are pure functions of their inputs, so this is safe.
    # Disable via MEDIAHUB_TURNINTO_PARALLEL=0 (e.g. for deterministic tests).
    _parallel = (
        os.environ.get("MEDIAHUB_TURNINTO_PARALLEL", "1") != "0"
        and not deterministic
    )

    _kw = dict(profile=profile, voice_profile=voice_profile,
               brand_kit=brand_kit, deterministic=deterministic)
    # (label, callable) tuples — order here is the order shown in the pack UI.
    _jobs: list[tuple[str, callable]] = [
        ("meet_recap",         lambda: _t.build_meet_recap(meet_summary, ranked, **_kw)),
        ("swimmer_spotlight",  lambda: _t.build_swimmer_spotlights(meet_summary, ranked, **_kw)),
        ("data_thread",        lambda: _t.build_data_thread(meet_summary, ranked, **_kw)),
        ("parent_newsletter",  lambda: _t.build_parent_newsletter(meet_summary, ranked, **_kw)),
        ("sponsor_thank_you",  lambda: _t.build_sponsor_thank_you(meet_summary, ranked, **_kw)),
        ("coach_quote",        lambda: _t.build_coach_quote(meet_summary, ranked, **_kw)),
        ("next_meet_preview",  lambda: _t.build_next_meet_preview(meet_summary, ranked, **_kw)),
    ]
    _skip_reasons = {
        "sponsor_thank_you": "No sponsor_name set on club profile.",
        "next_meet_preview": (
            "No next-meet info on profile. Set a 'next_meet' dict or "
            "add 'Next meet: <name> — <date>' to profile notes."
        ),
    }

    if _parallel:
        from concurrent.futures import ThreadPoolExecutor
        max_workers = int(os.environ.get("MEDIAHUB_TURNINTO_WORKERS", "4"))
        with ThreadPoolExecutor(max_workers=min(max_workers, len(_jobs))) as pool:
            results = list(pool.map(lambda j: (j[0], j[1]()), _jobs))
    else:
        results = [(label, fn()) for label, fn in _jobs]

    artefacts: list[dict] = []
    for label, art in results:
        if art is None:
            skipped.append({"type": label, "reason": _skip_reasons.get(label, "skipped")})
        else:
            artefacts.append(art)

    pack_id = uuid.uuid4().hex
    return {
        "pack_id": pack_id,
        "run_id": run_data.get("run_id", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meet_name": meet_summary["name"],
        "profile_id": profile_id,
        "voice_tone": (voice_profile.tone if voice_profile else
                       (profile.tone if profile else "warm-club")),
        "deterministic": bool(deterministic),
        "artefacts": artefacts,
        "skipped": skipped,
    }


__all__ = [
    "turn_meet_into_pack",
    "save_pack",
    "load_pack",
    "list_packs",
]
