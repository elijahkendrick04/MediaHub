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
from pathlib import Path
from typing import Optional

from .status import CardStatus
from .store import WorkflowStore


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
        Defaults to <project_root>/runs_v4.

    Returns
    -------
    list[dict]  — approved cards, priority-descending, with brand data.
    """
    if runs_dir is None:
        runs_dir = Path(__file__).resolve().parents[2] / "runs_v4"
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
            # into pack building.
            try:
                from mediahub.memory import learning as _mem

                _bc = card.get("brand_captions") or {}
                _active = _bc.get(tone) if isinstance(_bc, dict) else None
                if isinstance(_active, dict):
                    _cap = " ".join(
                        str(v).strip() for v in _active.values() if isinstance(v, str) and v.strip()
                    )
                    if _cap:
                        _mem.capture(profile_id, ach, _cap, card_id=card_id, run_id=run_id)
                        # PAR-1 approval loop: the plain few-shot voice store
                        # works for EVERY club (no embedding backend, no corpus
                        # floor) — the approved caption becomes a voice example
                        # injected into future generation. Idempotent per
                        # caption, best-effort like the semantic capture.
                        if profile_id:
                            from mediahub.web.ai_caption import record_approved_caption

                            record_approved_caption(str(profile_id), _cap)
            except Exception:
                pass

            approved.append((ra.get("priority", 0.0), card))

    approved.sort(key=lambda x: -x[0])
    return [card for _, card in approved]
