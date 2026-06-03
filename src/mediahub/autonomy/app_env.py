"""mediahub/autonomy/app_env.py — wire the autonomy engine to the live app.

Builds an :class:`AutonomyEnv` for a given organisation from MediaHub's real
data (runs on disk, the runs DB, the workflow store, the caption surface) and
registers an ``autonomy`` scheduler task type so a club can schedule a
"prepare my pack for review" run on a cadence (the Sunday-morning inbox).

Deliberately does NOT import ``mediahub.web.web`` — it reads runs/db directly
(same paths web.py uses) and imports only the leaf modules it needs, so there is
no import cycle and the wiring is testable on its own.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

from mediahub.autonomy.run_loop import AutonomyResult, is_enabled, run_autonomy
from mediahub.autonomy.tools import AutonomyEnv, AutonomyLevel
from mediahub.workflow.autonomy import AuditLog

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))


def _runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", str(_data_dir() / "runs_v4")))


def _db_path() -> Path:
    return _data_dir() / "data.db"


def _load_run(run_id: str) -> Optional[dict]:
    try:
        p = _runs_dir() / f"{run_id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text())
    except Exception:
        return None


def _owns_run(org_id: str, run_id: str) -> bool:
    """Strict ownership: the run must be stamped with this org's profile_id.
    Unowned/legacy runs are NOT accessible to the autonomy runner (conservative
    multi-tenant default — the runner only ever acts on a club's own runs)."""
    data = _load_run(run_id)
    if not data:
        return False
    return (data.get("profile_id") or "").strip() == (org_id or "").strip() and bool(org_id)


def _list_runs(org_id: str) -> list[dict]:
    try:
        conn = sqlite3.connect(str(_db_path()), timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, meet_name, n_achievements, finished_at FROM runs "
            "WHERE profile_id = ? AND status = 'done' ORDER BY created_at DESC LIMIT 20",
            (org_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _org_tone(org_id: str) -> str:
    try:
        from mediahub.web.club_profile import load_profile  # noqa: PLC0415

        prof = load_profile(org_id)
        return (
            getattr(prof, "tone", "") or getattr(prof, "caption_tone", "") or "warm-club"
        ).strip()
    except Exception:
        return "warm-club"


def _make_gen_caption(org_id: str):
    def gen(achievement: dict, instruction: str) -> str:
        from mediahub.web.ai_caption import generate_caption_for_tone  # noqa: PLC0415
        from mediahub.web.club_profile import load_profile  # noqa: PLC0415

        prof = load_profile(org_id)
        tone = _org_tone(org_id)
        club_brand = {"club_name": getattr(prof, "display_name", "") if prof else ""}
        return generate_caption_for_tone(
            achievement,
            club_brand,
            tone=tone,
            club_profile=prof,
            requirements=instruction or "",
        )

    return gen


def _make_notify(org_id: str):
    def notify(org: str, session_id: str, summary: str) -> None:
        try:
            from mediahub.notify import notify_pack_ready  # noqa: PLC0415

            # Surfaced like a normal "pack ready" ping — the human still reviews
            # everything; nothing was posted.
            notify_pack_ready(f"autonomy:{session_id}")
        except Exception:
            pass

    return notify


def build_env(org_id: str) -> AutonomyEnv:
    """Construct an AutonomyEnv bound to ``org_id`` from the live app data."""
    from mediahub.workflow.store import WorkflowStore  # noqa: PLC0415

    tone = _org_tone(org_id)
    return AutonomyEnv(
        load_run=_load_run,
        list_runs=_list_runs,
        owns_run=_owns_run,
        workflow=WorkflowStore(_runs_dir()),
        gen_caption=_make_gen_caption(org_id),
        draft_slot=f"{tone}_headline",
        audit=AuditLog(),
        notify=_make_notify(org_id),
    )


def run_for_org(
    org_id: str, goal: str, level: AutonomyLevel = AutonomyLevel.PREPARE
) -> AutonomyResult:
    """Build the live env and run one autonomy session for an org."""
    return run_autonomy(org_id, goal, level, build_env(org_id))


def _autonomy_task_handler(params: dict) -> None:
    """Scheduler task handler for a scheduled autonomy run. Inert when autonomy
    is disabled (so a scheduled task can't error-loop while the feature is off)."""
    if not is_enabled():
        return
    org_id = (params.get("org_id") or "").strip()
    if not org_id:
        raise ValueError("autonomy task requires an org_id")
    goal = params.get("goal") or "Prepare this organisation's best recent content for review."
    level = AutonomyLevel(int(params.get("level", int(AutonomyLevel.PREPARE))))
    run_for_org(org_id, goal, level)


def register_autonomy_task() -> None:
    """Register the ``autonomy`` scheduler task type (idempotent)."""
    try:
        from mediahub.scheduler import register_task_type  # noqa: PLC0415

        register_task_type("autonomy", _autonomy_task_handler)
    except Exception as e:  # never block app startup on this
        log.warning("could not register autonomy task type: %s", e)


__all__ = ["build_env", "run_for_org", "register_autonomy_task"]
