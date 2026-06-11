"""
PC.7 — instant try-before-signup demo: caps, the sandbox demo org, and the
self-cleaning sweep.

The sales motion's sharpest tool: a stranger drops a results file on a
public page (no account) and gets a watermarked 3-card preview. This module
holds the parts that are not routes:

- **Caps** — per-IP and global daily counters (JSON state under
  ``DATA_DIR/demo_try/``), so anonymous traffic is bounded. Defaults are
  deliberately small; override via ``MEDIAHUB_TRY_IP_DAILY_CAP`` /
  ``MEDIAHUB_TRY_GLOBAL_DAILY_CAP``. ``MEDIAHUB_TRY_DEMO=0`` switches the
  whole surface off.
- **Demo org** — one sandboxed, *unbound* profile (`demo-try`): the
  ``web/tenancy.py`` zero-member model already behaves anonymously, and
  demo runs are stamped to it so they can never collide with a real org's
  runs (ADR-0003: a bound org's session can't read them, and the demo org
  never binds).
- **Sweep** — ``sweep_demo_runs`` deletes demo runs older than the
  retention window; web.py registers it as a daily scheduler task.

Demo runs always skip ``pb_discovery`` web-verification (no third-party
calls on unauthenticated traffic) — the route passes ``fetch_pbs=False``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

DEMO_PROFILE_ID = "demo-try"
DEMO_DISPLAY_NAME = "MediaHub demo"
WATERMARK_TEXT = "MEDIAHUB PREVIEW"
DEMO_CARD_LIMIT = 3
DEMO_RUN_RETENTION_HOURS = 24

# Accepted demo upload types — the same formats the real upload takes.
ALLOWED_EXTENSIONS = (".hy3", ".zip", ".pdf", ".csv", ".xls", ".xlsx")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

_CAPS_LOCK = threading.Lock()


def demo_enabled() -> bool:
    return os.environ.get("MEDIAHUB_TRY_DEMO", "1") != "0"


def _ip_daily_cap() -> int:
    try:
        return max(1, int(os.environ.get("MEDIAHUB_TRY_IP_DAILY_CAP", "5")))
    except ValueError:
        return 5


def _global_daily_cap() -> int:
    try:
        return max(1, int(os.environ.get("MEDIAHUB_TRY_GLOBAL_DAILY_CAP", "40")))
    except ValueError:
        return 40


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _caps_path() -> Path:
    return _data_dir() / "demo_try" / "caps.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _load_caps() -> dict:
    path = _caps_path()
    state = {"date": _today(), "total": 0, "by_ip": {}}
    if not path.exists():
        return state
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return state
    if not isinstance(loaded, dict) or loaded.get("date") != _today():
        return state  # new day: counters reset
    loaded.setdefault("total", 0)
    loaded.setdefault("by_ip", {})
    return loaded


def claim_demo_slot(ip: str) -> tuple[bool, str]:
    """Atomically check + count one demo attempt for ``ip``.

    Returns ``(allowed, reason)`` — reason is a human-readable refusal for
    the page when not allowed. Counters reset at UTC midnight.
    """
    ip = (ip or "unknown").strip() or "unknown"
    with _CAPS_LOCK:
        state = _load_caps()
        if int(state["total"]) >= _global_daily_cap():
            return False, (
                "The demo has reached today's global limit. "
                "Please try again tomorrow — or sign up, which has no demo cap."
            )
        if int(state["by_ip"].get(ip, 0)) >= _ip_daily_cap():
            return False, (
                "You've reached today's demo limit from this network. "
                "Sign up for a free account to keep going."
            )
        state["total"] = int(state["total"]) + 1
        state["by_ip"][ip] = int(state["by_ip"].get(ip, 0)) + 1
        try:
            path = _caps_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            # If the counter can't persist, fail CLOSED — an unbounded
            # anonymous surface is worse than a refused demo.
            return False, "The demo is temporarily unavailable. Please try again later."
        return True, ""


def ensure_demo_profile():
    """Create (or return) the sandboxed demo org. Unbound by design."""
    from mediahub.web.club_profile import ClubProfile, load_profile, save_profile

    prof = load_profile(DEMO_PROFILE_ID)
    if prof is not None:
        return prof
    prof = ClubProfile(
        profile_id=DEMO_PROFILE_ID,
        display_name=DEMO_DISPLAY_NAME,
        short_name="Demo",
        notes=(
            "Sandboxed org for the public try-before-signup demo (PC.7). "
            "Runs in here are watermarked previews and are swept daily."
        ),
        # A neutral, deliberately generic palette: the demo brands cards
        # with the meet's data, not a real club's identity.
        brand_primary="#0A2540",
        brand_secondary="#102E4A",
        brand_palette_manual={"primary": "#0A2540", "secondary": "#102E4A", "accent": "#3EC1D3"},
    )
    save_profile(prof)
    return prof


def list_demo_run_ids(older_than_hours: Optional[float] = None) -> list[str]:
    """Demo-org run ids from the runs DB (optionally only stale ones)."""
    db_path = _data_dir() / "data.db"
    if not db_path.exists():
        return []
    import sqlite3

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT id, created_at FROM runs WHERE profile_id = ?",
                (DEMO_PROFILE_ID,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    if older_than_hours is None:
        return [r[0] for r in rows]
    import datetime as _dt

    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=older_than_hours)
    out = []
    for run_id, created_at in rows:
        try:
            created = _dt.datetime.fromisoformat(str(created_at))
            if created.tzinfo is None:
                created = created.replace(tzinfo=_dt.timezone.utc)
        except (TypeError, ValueError):
            out.append(run_id)  # unparseable age: treat as stale
            continue
        if created < cutoff:
            out.append(run_id)
    return out


def sweep_demo_runs(
    delete_run: Callable[[str], bool],
    *,
    older_than_hours: float = DEMO_RUN_RETENTION_HOURS,
) -> int:
    """Delete stale demo runs via the app's run-deletion function.

    Returns the number of runs deleted. Only ever touches runs stamped to
    the demo org — a real org's runs are structurally out of reach.
    """
    deleted = 0
    for run_id in list_demo_run_ids(older_than_hours=older_than_hours):
        try:
            if delete_run(run_id):
                deleted += 1
        except Exception:
            continue
    return deleted
