"""
build_content_pack(run_id, profile_id, runs_dir) → list[dict]

Returns a list of approved cards (status == APPROVED) from the recognition
report, sorted by priority descending, with brand captions applied.

Each returned card is the RankedAchievement dict extended with:
  - 'workflow': the CardWorkflowState dict
  - 'brand_captions': rendered captions for all three tones
  - 'active_caption': captions for the profile's selected tone
  - 'scheduled_for': free-text label (from workflow edits, if set)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from .status import CardStatus
from .store import WorkflowStore

log = logging.getLogger(__name__)


def _capture_memories_async(jobs: list[tuple]) -> None:
    """Run the semantic caption-memory captures out-of-band.

    Each capture makes a blocking HTTP embed call when an embedding backend
    is configured; doing that per card inside pack building (a page render /
    export path) stalls the response — up to the embed timeout per card when
    the endpoint is down. A daemon thread keeps the best-effort, never-raises
    contract; a capture lost on process exit is acceptable for a cache."""

    def _run() -> None:
        try:
            from mediahub.memory import learning as _mem

            for profile_id, ach, cap, card_id, run_id in jobs:
                try:
                    _mem.capture(profile_id, ach, cap, card_id=card_id, run_id=run_id)
                except Exception:
                    pass
        except Exception:
            pass

    threading.Thread(target=_run, name="pack-memory-capture", daemon=True).start()


def build_content_pack(
    run_id: str,
    profile_id: str,
    runs_dir: Optional[Path] = None,
) -> list[dict]:
    """
    Build an ordered list of approved cards with brand captions applied.

    Parameters
    ----------
    run_id : str
    profile_id : str
    runs_dir : Path | None
        Defaults to the env-derived runs dir (RUNS_DIR, else DATA_DIR/runs_v4) —
        the same derivation the web layer uses — so the fallback points at the
        real runtime run storage, never the source tree.

    Returns
    -------
    list[dict]  — approved cards, priority-descending, with brand data.
    """
    if runs_dir is None:
        data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
        runs_dir = Path(os.environ.get("RUNS_DIR", str(data_dir / "runs_v4")))
    runs_dir = Path(runs_dir)

    # Load run JSON
    run_path = runs_dir / f"{run_id}.json"
    if not run_path.exists():
        return []
    try:
        run_data = json.loads(run_path.read_text())
    except Exception:
        return []

    # Load workflow sidecar
    ws = WorkflowStore(runs_dir)
    wf_states = ws.load(run_id)

    # Load brand settings
    try:
        from mediahub.brand.store import load_brand

        kit, tone, caption_templates = load_brand(profile_id)
    except Exception:
        kit = None
        tone = None
        caption_templates = {}

    # Get ranked achievements
    rr = run_data.get("recognition_report") or {}
    ranked_achs = rr.get("ranked_achievements") or []

    # Filter to approved only, sorted by priority desc
    approved: list[dict] = []
    capture_jobs: list[tuple] = []
    for ra in ranked_achs:
        ach = ra.get("achievement") or {}
        card_id = ach.get("swim_id") or ach.get("swimmer_id") or str(ra.get("rank", ""))
        wf = wf_states.get(card_id)
        if wf and wf.status == CardStatus.APPROVED:
            card = dict(ra)
            card["workflow"] = wf.to_dict()
            card["_card_id"] = card_id

            # Apply brand captions
            if kit is not None and tone is not None:
                try:
                    from mediahub.brand.apply import apply_brand

                    card = apply_brand(card, kit, tone, "meet_recap", caption_templates)
                except Exception:
                    pass

            # User-edited captions take precedence
            if wf.edited_captions:
                for key, val in wf.edited_captions.items():
                    # key format: "warm-club_headline"
                    parts = key.rsplit("_", 1)
                    if len(parts) == 2:
                        t_str, slot = parts
                        if "brand_captions" in card and t_str in card["brand_captions"]:
                            card["brand_captions"][t_str][slot] = val

            # Scheduled label (stored in notes as "scheduled:LABEL")
            notes = wf.notes or ""
            scheduled_for = ""
            if notes.startswith("scheduled:"):
                scheduled_for = notes[len("scheduled:") :]
            card["scheduled_for"] = scheduled_for.strip()

            # Cap 2b: remember this approved card's accepted caption (event
            # context -> caption) so future caption generation can recall what
            # worked for similar moments. Off-by-default + best-effort: a no-op
            # unless an embedding backend is configured, and it never raises
            # into pack building. The embed call itself is HTTP-blocking, so
            # captures are queued here and run on a daemon thread after the
            # pack is assembled — never on the render path.
            _bc = card.get("brand_captions") or {}
            _active = _bc.get(tone) if isinstance(_bc, dict) else None
            _cap = ""
            if isinstance(_active, dict):
                _cap = " ".join(
                    str(v).strip() for v in _active.values() if isinstance(v, str) and v.strip()
                )

            # PAR-1 approval loop: the plain few-shot voice store works for
            # EVERY club (no embedding backend, no corpus floor) — the approved
            # caption becomes a voice example injected into future generation.
            # Decoupled from the semantic-memory block below so a memory import
            # failure can never silently skip this cheap, universal local write.
            # Idempotent per caption, best-effort.
            if _cap and profile_id:
                try:
                    from mediahub.web.ai_caption import record_approved_caption

                    record_approved_caption(str(profile_id), _cap)
                except Exception as exc:
                    # Best-effort, but not fully silent — a voice-write failure
                    # shouldn't disappear (it's decoupled from the semantic-memory
                    # capture below so one failing never disables the other).
                    log.warning("PAR-1 voice write failed for profile %s: %s", profile_id, exc)

            # Cap 2b semantic recall: queue the embed capture only when an
            # embedding backend is configured. Off-by-default, best-effort, and
            # independent of the PAR-1 write above.
            if _cap:
                try:
                    from mediahub.memory import learning as _mem

                    if _mem.is_enabled():
                        capture_jobs.append((profile_id, ach, _cap, card_id, run_id))
                except Exception:
                    pass

            approved.append((ra.get("priority", 0.0), card))

    if capture_jobs:
        _capture_memories_async(capture_jobs)

    approved.sort(key=lambda x: -x[0])
    return [card for _, card in approved]
