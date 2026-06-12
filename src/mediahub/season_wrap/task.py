"""season_wrap/task.py — the monthly recap scheduler task (W.8).

``monthly_wrap_task_handler`` builds and saves the draft for the last
*completed* calendar month. It is idempotent: the draft id is
``monthly-<year>-<month>``, so a re-run simply overwrites the same file.
The handler only ever *drafts* — nothing is published; the draft waits for
a human on the review surface (the standing approval-first rule).

Registration follows the ``workflow.approval`` convention: an exported
``register_season_wrap_task()`` the app calls at startup — never a
side effect of import.
"""

from __future__ import annotations

import calendar
import logging
import os
from datetime import date
from pathlib import Path

from mediahub.season_wrap.drafts import build_monthly_draft, save_draft

log = logging.getLogger(__name__)

TASK_TYPE = "season_wrap_draft"


def _last_completed_month(today: date) -> tuple[int, int]:
    first_of_month = today.replace(day=1)
    if first_of_month.month == 1:
        return first_of_month.year - 1, 12
    return first_of_month.year, first_of_month.month - 1


def _default_runs_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "runs_v4"


def _notify(title: str, message: str) -> None:
    """Best-effort push via every configured channel. Never raises."""
    try:
        from mediahub.notify import channels  # noqa: PLC0415

        n = channels.Notification(title=title, message=message, tags=("calendar",))
        for ch in channels.all_channels():
            try:
                if ch.configured():
                    ch.send(n)
            except Exception:  # one channel's failure must not stop another
                log.warning("season-wrap notify failed on %s", ch.name, exc_info=True)
    except Exception:
        log.warning("season-wrap notify unavailable", exc_info=True)


def monthly_wrap_task_handler(params: dict) -> None:
    """Scheduler handler: draft last month's recap for one workspace.

    ``params``: ``{"profile_id": str, "runs_dir": str?}``.
    """
    profile_id = (params.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("season_wrap_draft task requires a profile_id")
    runs_dir = Path(params["runs_dir"]) if params.get("runs_dir") else _default_runs_dir()

    year, month = _last_completed_month(date.today())
    draft = build_monthly_draft(profile_id, runs_dir, year=year, month=month)
    path = save_draft(profile_id, draft)
    log.info("season wrap draft saved: %s", path)

    month_name = calendar.month_name[month]
    _notify(
        "MediaHub — monthly recap drafted",
        f"Your {month_name} recap draft is ready",
    )


def register_season_wrap_task() -> None:
    """Register the ``season_wrap_draft`` scheduler task type (idempotent)."""
    try:
        from mediahub.scheduler import register_task_type  # noqa: PLC0415

        register_task_type(TASK_TYPE, monthly_wrap_task_handler)
    except Exception as e:  # never block app startup on this
        log.warning("could not register %s task type: %s", TASK_TYPE, e)


__all__ = ["TASK_TYPE", "monthly_wrap_task_handler", "register_season_wrap_task"]
