"""
V4 web app — Flask backend + single-file UI.

Routes:
  GET  /                       Home (recent runs, profiles, status)
  GET  /upload                 Upload form
  POST /upload                 Kick off pipeline in a background thread
  GET  /runs/<id>              Wait/poll page; redirects to /review when done
  GET  /api/runs/<id>/status   JSON progress for poll
  GET  /review/<id>            Review queue (cards) + trust UI
  GET  /api/runs/<id>/cards    JSON of cards
  GET  /api/runs/<id>/trust    JSON of trust report
  GET  /api/runs/<id>/export   JSON evidence + audit export
  GET  /ground-truth/<id>      Ground-truth evaluation page
  POST /ground-truth/<id>      Submit moments and get precision/recall
  GET  /privacy                Data inventory + delete controls
  POST /privacy/run/<id>/delete   Delete a single run
  POST /privacy/cache/clear        Clear PB cache
  GET  /research               Research roadmap page (parser priorities)
  GET  /healthz                health check

State: SQLite at data.db (so publish_website snapshots it across deploys)
       + uploads_v4/ (transient HY3) + runs/<id>.json (full run)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    jsonify, abort, send_file, Response,
)
from markupsafe import escape as _h

from mediahub.pipeline.pipeline_v4 import run_pipeline_v4, PipelineRunV4
from .humanise import humanise as _humanise, format_post_angle as _format_angle, humanise_status as _humanise_status
from .club_profile import (
    ClubProfile, list_profiles, load_profile, save_profile,
    seed_default_profiles,
)
from .ground_truth import evaluate as gt_evaluate
from .canonical import Meet

# V7 imports
try:
    from mediahub.club_platform.content_types import REGISTRY as _CT_REGISTRY, ContentType as _ContentType
    from mediahub.club_platform.athlete_spotlight import build_spotlight_pack, list_swimmers_in_run
    from mediahub.club_platform.stubs import WeekendPreviewStub, SponsorPostStub, SessionUpdateStub, FreeTextStub
    _club_platform_ok = True
except ImportError:
    _club_platform_ok = False

try:
    from mediahub.brand.kit import BrandKit
    from mediahub.brand.tone import Tone, TONE_META, tone_from_str
    from mediahub.brand.templates import get_default_templates, render_template as _render_brand_template
    from mediahub.brand.store import load_brand, save_brand
    from mediahub.brand.apply import apply_brand
    _brand_ok = True
except ImportError:
    _brand_ok = False

try:
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore
    from mediahub.workflow.pack import build_content_pack
    _workflow_ok = True
except ImportError:
    _workflow_ok = False


# V7.3 imports
try:
    from mediahub.content_pack.builder import build_grouped_pack as _build_grouped_pack
    from mediahub.recognition.copy_text import build_caption_text as _build_caption_text
    from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers as _build_win
    from mediahub.voice.store import load_voice_profile as _load_voice_profile, save_voice_profile as _save_voice_profile
    from mediahub.voice.profile import VoiceProfile as _VoiceProfile, VoiceExemplar as _VoiceExemplar
    _v73_ok = True
except ImportError as _v73_err:
    _v73_ok = False
    _build_grouped_pack = None
    _build_caption_text = None
    _build_win = None
    _load_voice_profile = None
    _save_voice_profile = None

# V8: media generation engine
try:
    from mediahub.media_library.store import MediaLibraryStore as _V8MediaStore, get_store as _v8_get_media_store
    from mediahub.media_library.describe import parse_description as _v8_parse_description
    from mediahub.content_pack_visual.integration import (
        attach_visuals_to_pack as _v8_attach_visuals,
        create_visual_for_item as _v8_create_visual_for_item,
        visuals_dir_for_run as _v8_visuals_dir,
    )
    from mediahub.venue_search.search import search as _v8_search_venue
    _v8_ok = True
except ImportError as _v8_err:
    _v8_ok = False
    _V8MediaStore = None
    _v8_get_media_store = None
    _v8_parse_description = None
    _v8_attach_visuals = None
    _v8_create_visual_for_item = None
    _v8_visuals_dir = None
    _v8_search_venue = None


_SRC_ROOT = Path(__file__).resolve().parents[1]   # src/mediahub/ — local dev default
DATA_DIR   = Path(os.environ.get("DATA_DIR",   str(_SRC_ROOT)))
RUNS_DIR   = Path(os.environ.get("RUNS_DIR",   str(DATA_DIR / "runs_v4")))
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(DATA_DIR / "uploads_v4")))
DB_PATH    = DATA_DIR / "data.db"               # MUST be data.db for publish snapshot
RESEARCH_DIR = DATA_DIR / "research"

RUNS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
RESEARCH_DIR.mkdir(exist_ok=True)

# V7: workflow store (sidecar JSON per run)
_wf_store = None  # initialised after imports complete

def _get_wf_store() -> Optional['WorkflowStore']:
    global _wf_store
    if _wf_store is None:
        try:
            from mediahub.workflow.store import WorkflowStore as _WS
            _wf_store = _WS(RUNS_DIR)
        except ImportError:
            pass
    return _wf_store


# ---------------------------------------------------------------------
# In-process run registry (active progress) + persisted run metadata.
# ---------------------------------------------------------------------

_active_runs: dict[str, dict] = {}     # run_id -> {status, log[], profile, error}
_active_lock = threading.Lock()


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            finished_at TEXT,
            status TEXT,             -- queued | running | done | error
            profile_id TEXT,
            meet_name TEXT,
            our_swims INTEGER,
            n_cards INTEGER,
            n_queue INTEGER,
            error TEXT,
            file_name TEXT
        );
    """)
    conn.commit()
    conn.close()


_init_db()


def _prune_orphaned_runs():
    """Remove rows from `runs` whose JSON file no longer exists on disk.

    The published sandbox is ephemeral, so when we redeploy the database may
    survive while the runs/<id>.json files are gone. Without this prune the
    home page lists dozens of broken /review/<id> links.
    """
    try:
        conn = _db()
        rows = conn.execute("SELECT id FROM runs").fetchall()
        stale = []
        for r in rows:
            run_id = r["id"] if hasattr(r, "keys") else r[0]
            json_path = RUNS_DIR / f"{run_id}.json"
            if not json_path.exists():
                stale.append(run_id)
        if stale:
            conn.executemany("DELETE FROM runs WHERE id = ?", [(s,) for s in stale])
            conn.commit()
        conn.close()
    except Exception:
        pass


_prune_orphaned_runs()
# V8.2: seed_default_profiles is a no-op since the profiles UI was removed.
seed_default_profiles()


# ---------------------------------------------------------------------
# V6 PB audit serialisation helper
# ---------------------------------------------------------------------

def _serialise_pb_audit(pb_audit) -> Optional[dict]:
    """Serialise a V6 RunPBAudit to a JSON-safe dict.
    Returns None if pb_audit is None or serialisation fails.
    """
    if pb_audit is None:
        return None
    try:
        from swim_content_pb.audit import run_audit_to_dict
        return run_audit_to_dict(pb_audit)
    except Exception:
        return None


def _deserialise_pb_audit(data: dict) -> Optional[dict]:
    """Return the pb_audit dict as-is (already deserialised from JSON)."""
    return data or None


# ---------------------------------------------------------------------
# Run persistence helpers
# ---------------------------------------------------------------------

def _persist_run(run: PipelineRunV4, file_name: str) -> None:
    """Persist a finished run to runs_v4/<id>.json + DB row."""
    payload = {
        "run_id": run.run_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "profile_id": run.profile_id,
        "profile_display": run.profile_display,
        "file_name": file_name,
        "meet": run.canonical_meet.to_dict() if run.canonical_meet else None,
        "dispatch_log": run.dispatch_log.to_dict() if run.dispatch_log else None,
        "parse_warnings": run.parse_warnings,
        "parsed_swim_count": run.parsed_swim_count,
        "our_swim_count": run.our_swim_count,
        "other_swim_count": run.other_swim_count,
        "n_swimmers_ours": run.n_swimmers_ours,
        "pb_fetch_ok": run.pb_fetch_ok,
        "pb_fetch_failed": run.pb_fetch_failed,
        "pb_fetch_errors": run.pb_fetch_errors,
        "detector_summary": run.detector_summary,
        "self_check": run.self_check,
        "standards_meta": run.standards_meta,
        "cards": [c.to_dict() for c in run.cards],
        "trust": run.trust.to_dict() if run.trust else None,
        "ground_truth_report": run.ground_truth_report,
        "recognition_report": run.recognition_report,
        "recognition_error": run.recognition_error,
        "progress_log": run.progress_log,
        "error": run.error,
        # V6 PB audit (optional — None when fetch_pbs=False)
        "pb_audit": _serialise_pb_audit(getattr(run, "pb_audit", None)),
    }
    out = RUNS_DIR / f"{run.run_id}.json"
    out.write_text(json.dumps(payload, indent=2, default=str))

    n_cards = len(run.cards)
    n_queue = sum(1 for c in run.cards if c.bucket == "queue")
    meet_name = run.canonical_meet.name if run.canonical_meet else "(unknown)"
    status = "error" if run.error else "done"
    conn = _db()
    conn.execute(
        """INSERT OR REPLACE INTO runs
           (id, created_at, finished_at, status, profile_id, meet_name,
            our_swims, n_cards, n_queue, error, file_name)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (run.run_id, run.started_at, run.finished_at, status,
         run.profile_id, meet_name, run.our_swim_count, n_cards, n_queue,
         run.error, file_name),
    )
    conn.commit()
    conn.close()


def _load_run(run_id: str) -> Optional[dict]:
    p = RUNS_DIR / f"{run_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _run_state(run_id: str) -> str:
    """Return one of ``unknown`` | ``in_progress`` | ``done``.

    "unknown" = no DB row and no JSON file. "in_progress" = DB row says
    queued/running OR an entry exists in the in-memory _active_runs dict.
    "done" = JSON file is on disk.

    Used by routes that depend on _load_run to render a friendly
    "still processing" page instead of a misleading 404 while the
    background worker is still running.
    """
    # JSON file present → run is fully persisted.
    if (RUNS_DIR / f"{run_id}.json").exists():
        return "done"
    # In-memory active dict → worker thread is alive in THIS process.
    with _active_lock:
        active = _active_runs.get(run_id)
    if active:
        status = (active.get("status") or "").lower()
        if status in ("queued", "running"):
            return "in_progress"
        if status == "error":
            return "done"  # error is "finished" — caller can read it from DB
    # Fall back to DB row (handles process restart between worker death
    # and persistence — rare, but possible).
    try:
        conn = _db()
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
    except Exception:
        return "unknown"
    if not row:
        return "unknown"
    status = (row["status"] or "").lower()
    if status in ("queued", "running"):
        return "in_progress"
    return "done"


def _in_progress_page(run_id: str, return_url_endpoint: str = "review") -> str:
    """Return a friendly HTML page that auto-refreshes every 4 seconds."""
    try:
        retry_url = url_for(return_url_endpoint, run_id=run_id)
    except Exception:
        retry_url = ""
    status_url = url_for("api_status", run_id=run_id)
    return f"""
<div style="text-align:center;padding:64px 24px">
  <div class="mh-spinner" style="margin:0 auto 24px"></div>
  <h1 style="margin-bottom:10px">Still processing your run</h1>
  <p class="dim" style="max-width:480px;margin:0 auto 24px">
    The pipeline is reading the file, finding your athletes, and drafting
    captions. This usually takes 20&ndash;60 seconds. We&rsquo;ll auto-refresh
    when it&rsquo;s ready.
  </p>
  <a class="btn secondary" href="{retry_url or status_url}">Refresh now</a>
</div>
<script>
  setTimeout(function() {{ location.reload(); }}, 4000);
</script>
"""


def _delete_run(run_id: str) -> bool:
    p = RUNS_DIR / f"{run_id}.json"
    existed = p.exists()
    if existed:
        p.unlink()
    conn = _db()
    conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()
    return existed


# ---------------------------------------------------------------------
# Background pipeline worker
# ---------------------------------------------------------------------

def _start_run(file_bytes: bytes, file_name: str,
               profile_id: Optional[str], use_pb_cache: bool,
               fetch_pbs: bool, club_filter: Optional[str] = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    with _active_lock:
        _active_runs[run_id] = {
            "status": "queued",
            "log": ["Run queued"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "file_name": file_name,
        }
    conn = _db()
    conn.execute(
        """INSERT INTO runs (id, created_at, status, file_name, profile_id)
           VALUES (?,?,?,?,?)""",
        (run_id, _active_runs[run_id]["started_at"], "queued",
         file_name, profile_id or ""),
    )
    conn.commit()
    conn.close()

    def _worker():
        with _active_lock:
            _active_runs[run_id]["status"] = "running"

        def cb(msg: str):
            with _active_lock:
                _active_runs[run_id]["log"].append(msg)

        try:
            run = run_pipeline_v4(
                file_bytes=file_bytes, filename=file_name,
                profile_id=profile_id, use_pb_cache=use_pb_cache,
                fetch_pbs=fetch_pbs, progress_cb=cb, run_id=run_id,
                club_filter=club_filter,
            )
            _persist_run(run, file_name)
            with _active_lock:
                _active_runs[run_id]["status"] = "error" if run.error else "done"
                if run.error:
                    _active_runs[run_id]["error"] = run.error
        except Exception as e:
            import traceback
            traceback.print_exc()
            with _active_lock:
                _active_runs[run_id]["status"] = "error"
                _active_runs[run_id]["error"] = str(e)
            conn = _db()
            conn.execute("UPDATE runs SET status='error', error=? WHERE id=?",
                         (str(e), run_id))
            conn.commit(); conn.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return run_id


# ---------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  /* Surfaces */
  --bg:       #0B1220;
  --panel:    #111A2E;
  --panel2:   #17233D;
  --border:   rgba(255,255,255,0.06);

  /* Text */
  --ink:       #E6ECF5;
  --ink-dim:   #8A95A8;
  --ink-muted: #5A6478;

  /* Accent */
  --accent:    #22D3EE;
  --accent-h:  #06B6D4;

  /* Semantic */
  --good: #22C55E;
  --warn: #F59E0B;
  --bad:  #F43F5E;
  --info: #22D3EE;

  /* Misc */
  --radius:    16px;
  --radius-sm: 10px;
  --shadow:    0 1px 0 rgba(255,255,255,0.03), 0 4px 24px rgba(0,0,0,0.4);
  --transition: 150ms cubic-bezier(0.4,0,0.2,1);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
               Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--ink);
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; transition: color var(--transition); }
a:hover { color: var(--accent-h); text-decoration: none; }

/* TOPNAV */
header.topnav {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0 28px;
  height: 56px;
  border-bottom: 1px solid var(--border);
  background: rgba(11,18,32,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 100;
}
header.topnav .brand {
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.01em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 9px;
  margin-right: 28px;
  text-decoration: none;
  flex-shrink: 0;
}
header.topnav .brand svg { color: var(--accent); flex-shrink: 0; }
header.topnav nav { display: flex; align-items: center; gap: 2px; flex: 1; }
header.topnav nav a {
  color: var(--ink-dim);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  transition: background var(--transition), color var(--transition);
  white-space: nowrap;
}
header.topnav nav a:hover {
  background: rgba(255,255,255,0.05);
  color: var(--ink);
  text-decoration: none;
}
header.topnav nav a.active {
  color: var(--accent);
  background: rgba(34,211,238,0.08);
  border-bottom: 2px solid var(--accent);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  padding-bottom: 4px;
}
#backend-pill {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  color: var(--ink-muted);
  text-decoration: none;
  transition: border-color var(--transition);
  flex-shrink: 0;
}
#backend-pill:hover { border-color: rgba(255,255,255,0.12); text-decoration: none; }
#backend-pill-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--ink-muted);
  flex-shrink: 0;
  transition: background 0.3s;
}

/* MAIN */
main.wrap { max-width: 1200px; margin: 0 auto; padding: 36px 28px 96px; }

/* HEADINGS */
h1 { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 8px; color: var(--ink); }
h2 { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 10px; color: var(--ink); }
h3 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); margin: 20px 0 10px; }

/* CARDS */
.card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow); }
.card h2 { margin: 0 0 10px; }
.card p { color: var(--ink-dim); margin: 0 0 12px; }
.card p:last-child { margin-bottom: 0; }

/* BUTTONS */
.btn {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--accent); color: #081820;
  border: 0; padding: 9px 18px; font-size: 14px; font-weight: 600;
  border-radius: var(--radius-sm); cursor: pointer;
  transition: background var(--transition), transform var(--transition), box-shadow var(--transition);
  font-family: inherit; text-decoration: none; letter-spacing: -0.01em;
}
.btn:hover {
  background: var(--accent-h); color: #081820;
  transform: translateY(-1px); box-shadow: 0 4px 16px rgba(34,211,238,0.2);
  text-decoration: none;
}
.btn:active { transform: translateY(0); }
.btn.secondary { background: transparent; color: var(--ink-dim); border: 1px solid rgba(255,255,255,0.1); }
.btn.secondary:hover { background: rgba(255,255,255,0.05); color: var(--ink); border-color: rgba(255,255,255,0.18); box-shadow: none; }
.btn.danger { background: transparent; color: var(--bad); border: 1px solid rgba(244,63,94,0.3); }
.btn.danger:hover { background: rgba(244,63,94,0.08); border-color: rgba(244,63,94,0.5); box-shadow: none; }

/* LAYOUT */
.row { display: flex; gap: 18px; flex-wrap: wrap; }
.row > * { flex: 1; min-width: 240px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; }
@media (max-width: 860px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
  .row { flex-direction: column; }
}
.divider { height: 1px; background: var(--border); margin: 20px 0; }
.muted { color: var(--ink-muted); }
.dim   { color: var(--ink-dim); }
.empty { padding: 56px 24px; text-align: center; color: var(--ink-muted); font-size: 14px; }

/* TABLES */
table { width: 100%; border-collapse: collapse; font-size: 14px; }
table th { text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); border-bottom: 1px solid var(--border); }
table td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
table tbody tr:nth-child(odd) { background: rgba(255,255,255,0.015); }
table tbody tr:hover { background: rgba(255,255,255,0.03); }

/* TAGS */
.tag { display: inline-flex; align-items: center; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: 0.03em; background: rgba(255,255,255,0.06); color: var(--ink-dim); border: 1px solid var(--border); }
.tag.good { background: rgba(34,197,94,0.12); color: var(--good); border-color: rgba(34,197,94,0.25); }
.tag.warn { background: rgba(245,158,11,0.12); color: var(--warn); border-color: rgba(245,158,11,0.25); }
.tag.bad  { background: rgba(244,63,94,0.12);  color: var(--bad);  border-color: rgba(244,63,94,0.25); }
.tag.info { background: rgba(34,211,238,0.10); color: var(--info); border-color: rgba(34,211,238,0.25); }

/* FORMS */
label { display: block; margin: 14px 0 5px; color: var(--ink-muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; }
input[type=text], input[type=file], textarea, select {
  background: rgba(255,255,255,0.03); color: var(--ink);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: var(--radius-sm); padding: 10px 14px;
  font-size: 14px; font-family: inherit; width: 100%;
  transition: border-color var(--transition), box-shadow var(--transition);
  appearance: none;
}
input[type=text]:focus, textarea:focus, select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(34,211,238,0.18);
}
input[type=checkbox] { width: auto; margin-right: 8px; accent-color: var(--accent); }
textarea { min-height: 120px; resize: vertical; }
select { cursor: pointer; }

/* STATS */
.stat-block { display: flex; gap: 12px; flex-wrap: wrap; }
.stat { background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px; min-width: 110px; }
.stat .l { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); margin-bottom: 4px; }
.stat .v { font-size: 32px; font-weight: 800; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; color: var(--ink); line-height: 1; }

/* KV */
.kv { display: grid; grid-template-columns: 180px 1fr; gap: 6px 16px; font-size: 14px; }
.kv .k { color: var(--ink-muted); font-size: 12px; font-weight: 500; }

/* PROGRESS LOG */
.progress-log {
  background: rgba(0,0,0,0.3); color: #9EB3C8;
  border: 1px solid var(--border); border-radius: 10px; padding: 16px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 12px; white-space: pre-wrap; max-height: 360px; overflow-y: auto; line-height: 1.7;
}

/* CODE */
code, pre { font-family: ui-monospace, 'SF Mono', Menlo, monospace; background: rgba(255,255,255,0.05); padding: 2px 7px; border-radius: 5px; font-size: 12.5px; color: var(--accent); }
pre { padding: 16px; overflow-x: auto; color: var(--ink-dim); border: 1px solid var(--border); border-radius: 10px; }
pre code { background: none; padding: 0; color: inherit; }

/* === Animations === */
@keyframes mh-spin { to { transform: rotate(360deg); } }
@keyframes mh-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
@keyframes mh-fade-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes mh-shimmer { 0% { background-position: -1000px 0; } 100% { background-position: 1000px 0; } }
@keyframes mh-slide-in { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
@keyframes mh-aurora { 0% { transform: translate(0,0) rotate(0deg); } 50% { transform: translate(-30px,40px) rotate(180deg); } 100% { transform: translate(0,0) rotate(360deg); } }

/* Page entry */
main.wrap { animation: mh-fade-in 0.35s ease-out; position: relative; z-index: 1; }
main.wrap > .card { animation: mh-fade-in 0.4s ease-out backwards; }
main.wrap > .card:nth-of-type(1) { animation-delay: 0.05s; }
main.wrap > .card:nth-of-type(2) { animation-delay: 0.10s; }
main.wrap > .card:nth-of-type(3) { animation-delay: 0.15s; }
main.wrap > .card:nth-of-type(4) { animation-delay: 0.20s; }
main.wrap > .card:nth-of-type(5) { animation-delay: 0.25s; }

/* Background accent — subtle aurora */
body::before {
  content: ''; position: fixed; top: -240px; right: -240px;
  width: 640px; height: 640px;
  background: radial-gradient(circle, rgba(34,211,238,0.06) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
  animation: mh-aurora 28s ease-in-out infinite;
}
body::after {
  content: ''; position: fixed; bottom: -320px; left: -240px;
  width: 720px; height: 720px;
  background: radial-gradient(circle, rgba(124,58,237,0.05) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
  animation: mh-aurora 36s ease-in-out infinite reverse;
}

/* Card hover */
.card { transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; }
a.card, .card[data-interactive] { cursor: pointer; }
a.card:hover, .card[data-interactive]:hover {
  transform: translateY(-2px);
  border-color: rgba(34,211,238,0.3);
  box-shadow: 0 12px 36px rgba(0,0,0,0.5), 0 0 0 1px rgba(34,211,238,0.15);
}

/* Loading overlay */
#mh-loader {
  position: fixed; inset: 0;
  background: rgba(11,18,32,0.78);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  z-index: 9999;
  display: none; align-items: center; justify-content: center;
  opacity: 0; transition: opacity 0.25s ease;
}
#mh-loader.show { display: flex; opacity: 1; }
.mh-loader-inner {
  display: flex; flex-direction: column; align-items: center; gap: 22px;
  padding: 36px 48px;
  animation: mh-fade-in 0.4s ease-out;
}
.mh-spinner {
  width: 72px; height: 72px;
  border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 0deg, rgba(34,211,238,0.15) 90deg, var(--accent) 270deg, transparent 360deg);
  -webkit-mask: radial-gradient(circle at center, transparent 26px, black 28px);
  mask: radial-gradient(circle at center, transparent 26px, black 28px);
  animation: mh-spin 1s linear infinite;
  position: relative;
  box-shadow: 0 0 40px rgba(34,211,238,0.25);
}
.mh-spinner::after {
  content: ''; position: absolute; inset: 10px;
  border-radius: 50%;
  background: radial-gradient(circle at center, rgba(34,211,238,0.18), transparent 70%);
  animation: mh-pulse 1.4s ease-in-out infinite;
}
.mh-loader-text {
  font-size: 15px; color: var(--ink); font-weight: 600;
  letter-spacing: -0.01em; text-align: center;
}
.mh-loader-sub {
  font-size: 13px; color: var(--ink-dim);
  max-width: 360px; text-align: center;
  animation: mh-pulse 2.4s ease-in-out infinite;
}

/* Toast */
#mh-toast-container {
  position: fixed; top: 72px; right: 20px;
  z-index: 10000;
  display: flex; flex-direction: column; gap: 10px;
  pointer-events: none; max-width: 380px;
}
.mh-toast {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; color: var(--ink);
  font-size: 14px; line-height: 1.45;
  box-shadow: 0 12px 36px rgba(0,0,0,0.5);
  pointer-events: auto;
  animation: mh-slide-in 0.32s cubic-bezier(0.34, 1.2, 0.64, 1);
  display: flex; align-items: flex-start; gap: 12px;
  min-width: 280px;
}
.mh-toast.success { border-color: rgba(34,197,94,0.45); }
.mh-toast.error   { border-color: rgba(244,63,94,0.45); }
.mh-toast.info    { border-color: rgba(34,211,238,0.45); }
.mh-toast .mh-toast-icon { width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px; }
.mh-toast.success .mh-toast-icon { color: var(--good); }
.mh-toast.error   .mh-toast-icon { color: var(--bad); }
.mh-toast.info    .mh-toast-icon { color: var(--info); }
.mh-toast-close {
  background: none; border: 0; color: var(--ink-muted); cursor: pointer;
  padding: 0; margin-left: 4px; font-size: 18px; line-height: 1;
  transition: color var(--transition);
}
.mh-toast-close:hover { color: var(--ink); }

/* Button loading state */
.btn.loading { pointer-events: none; opacity: 0.72; position: relative; padding-right: 38px; }
.btn.loading::after {
  content: ''; position: absolute; right: 14px; top: 50%;
  width: 14px; height: 14px; margin-top: -7px;
  border: 2px solid currentColor; border-right-color: transparent;
  border-radius: 50%; animation: mh-spin 0.6s linear infinite;
}

/* Skeleton */
.skeleton {
  background: linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.03) 100%);
  background-size: 1000px 100%;
  animation: mh-shimmer 1.6s linear infinite;
  border-radius: 8px;
}

/* Content card (AI-generated stub output) */
.mh-content-card {
  background: linear-gradient(180deg, rgba(34,211,238,0.04), rgba(34,211,238,0.01));
  border: 1px solid rgba(34,211,238,0.15);
  border-radius: var(--radius);
  padding: 22px;
  margin-bottom: 16px;
  position: relative;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.mh-content-card:hover { border-color: rgba(34,211,238,0.35); transform: translateY(-1px); }
.mh-content-card .mh-card-platform {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--accent); margin-bottom: 10px;
}
.mh-content-card .mh-card-caption {
  font-size: 15px; line-height: 1.6; color: var(--ink);
  white-space: pre-wrap; word-wrap: break-word;
}
.mh-content-card .mh-card-tags {
  margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px;
}
.mh-content-card .mh-card-tag {
  font-size: 12px; color: var(--accent);
  background: rgba(34,211,238,0.08);
  border: 1px solid rgba(34,211,238,0.2);
  border-radius: 6px; padding: 3px 8px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
}
.mh-content-card .mh-card-confidence {
  position: absolute; top: 22px; right: 22px;
  font-size: 11px; color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}
.mh-card-actions {
  margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;
  padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);
}
.mh-card-actions button {
  background: transparent; border: 1px solid rgba(255,255,255,0.1);
  color: var(--ink-dim); font-size: 12px; padding: 5px 11px;
  border-radius: 6px; cursor: pointer; font-family: inherit;
  transition: all var(--transition);
}
.mh-card-actions button:hover { color: var(--ink); border-color: rgba(255,255,255,0.2); }
.mh-card-actions button.primary { color: var(--accent); border-color: rgba(34,211,238,0.3); }
.mh-card-actions button.primary:hover { background: rgba(34,211,238,0.08); border-color: var(--accent); }

/* Disabled card / button visual state */
[aria-disabled="true"], .is-disabled {
  opacity: 0.45;
  cursor: not-allowed !important;
  pointer-events: none;
  filter: grayscale(0.3);
}
[aria-disabled="true"]:hover, .is-disabled:hover {
  transform: none !important; box-shadow: none !important;
}

/* === Upload pipeline progress UI === */
.mh-stages {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin: 18px 0 22px;
}
.mh-stage {
  flex: 1; min-width: 130px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  position: relative;
  transition: border-color 0.25s ease, background 0.25s ease, color 0.25s ease;
}
.mh-stage .mh-stage-label {
  font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.07em;
  color: var(--ink-muted); margin-bottom: 4px;
}
.mh-stage .mh-stage-text {
  font-size: 13px; color: var(--ink-dim);
  line-height: 1.4;
}
.mh-stage[data-state="done"] {
  border-color: rgba(34,197,94,0.4);
  background: rgba(34,197,94,0.05);
}
.mh-stage[data-state="done"] .mh-stage-label { color: var(--good); }
.mh-stage[data-state="active"] {
  border-color: rgba(34,211,238,0.55);
  background: rgba(34,211,238,0.06);
  box-shadow: 0 0 24px rgba(34,211,238,0.18);
}
.mh-stage[data-state="active"] .mh-stage-label { color: var(--accent); }
.mh-stage[data-state="active"]::after {
  content: ''; position: absolute; top: 10px; right: 10px;
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent);
  animation: mh-pulse 1.1s ease-in-out infinite;
  box-shadow: 0 0 12px var(--accent);
}
.mh-stage[data-state="error"] {
  border-color: rgba(244,63,94,0.5);
  background: rgba(244,63,94,0.06);
}
.mh-stage[data-state="error"] .mh-stage-label { color: var(--bad); }

.mh-progress-bar {
  position: relative; height: 6px;
  background: rgba(255,255,255,0.06);
  border-radius: 999px; overflow: hidden;
  margin: 14px 0 6px;
}
.mh-progress-bar > span {
  position: absolute; top: 0; left: 0; bottom: 0;
  background: linear-gradient(90deg, var(--accent) 0%, #7c3aed 100%);
  border-radius: 999px;
  transition: width 0.4s ease;
  width: 0;
}
.mh-progress-bar.indeterminate > span {
  width: 30% !important;
  animation: mh-progress-slide 1.6s cubic-bezier(0.4,0,0.2,1) infinite;
}
@keyframes mh-progress-slide {
  0%   { transform: translateX(-110%); }
  100% { transform: translateX(440%); }
}

/* === Mobile responsive — nav + spacing === */
@media (max-width: 720px) {
  main.wrap { padding: 24px 16px 80px; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; }
  header.topnav { padding: 0 12px; height: auto; flex-wrap: wrap; gap: 6px; }
  header.topnav .brand { margin-right: 10px; }
  header.topnav nav {
    width: 100%; gap: 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    padding-bottom: 6px;
  }
  header.topnav nav::-webkit-scrollbar { display: none; }
  header.topnav nav a {
    padding: 5px 10px; font-size: 13px;
    flex-shrink: 0;
  }
  #backend-pill { margin-left: auto; flex-shrink: 0; }
  .card { padding: 18px 16px; }
  .stat .v { font-size: 26px; }
  table { font-size: 12.5px; }
  table th, table td { padding: 8px 10px; }
  .kv { grid-template-columns: 1fr; gap: 2px 8px; }
  .kv .k { margin-top: 8px; }
  .mh-card-confidence { position: static !important; display: block; margin-bottom: 8px; }
  .mh-toast { min-width: 0; }
  #mh-toast-container { left: 12px; right: 12px; max-width: none; top: 60px; }
}
@media (max-width: 480px) {
  .row { gap: 12px; }
  .grid-2, .grid-3 { gap: 12px; }
  .stat-block { gap: 8px; }
  .stat { padding: 10px 12px; min-width: 0; flex: 1; }
}
/* Force inputs/selects to never overflow their container, even with inline max-widths */
input[type=text], input[type=file], textarea, select { max-width: 100%; }

/* === Hero (Holo-style) === */
.mh-hero {
  text-align: center;
  padding: 56px 24px 32px;
  position: relative;
  margin-bottom: 32px;
}
.mh-hero-eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 999px;
  background: rgba(34,211,238,0.08);
  border: 1px solid rgba(34,211,238,0.2);
  font-size: 12px; font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.02em;
  margin-bottom: 22px;
  animation: mh-fade-in 0.6s ease-out;
}
.mh-hero-eyebrow .mh-pulse-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--good);
  box-shadow: 0 0 8px rgba(34,197,94,0.6);
  animation: mh-pulse 1.6s ease-in-out infinite;
}
.mh-hero h1 {
  font-size: clamp(34px, 6vw, 60px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.05;
  margin: 0 0 18px;
  max-width: 820px; margin-left: auto; margin-right: auto;
}
.mh-hero h1 .mh-gradient-text {
  background: linear-gradient(135deg, var(--accent) 0%, #7c3aed 60%, #f43f5e 100%);
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
  -webkit-text-fill-color: transparent;
}
.mh-hero .mh-hero-sub {
  font-size: clamp(15px, 1.6vw, 18px);
  color: var(--ink-dim);
  max-width: 640px; margin: 0 auto 28px;
  line-height: 1.55;
}
.mh-hero-ctas {
  display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;
  margin-bottom: 22px;
}
.mh-hero-ctas .btn {
  font-size: 15px; padding: 12px 22px;
}
.mh-hero-trust {
  display: flex; align-items: center; justify-content: center;
  gap: 18px; flex-wrap: wrap;
  font-size: 12px; color: var(--ink-muted);
  margin-top: 8px;
}
.mh-hero-trust > * { display: inline-flex; align-items: center; gap: 6px; }
.mh-hero-trust svg { width: 13px; height: 13px; }

/* Section heading */
.mh-section-eyebrow {
  display: block; text-align: center;
  font-size: 12px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.12em;
  color: var(--accent);
  margin: 36px 0 8px;
}
.mh-section-title {
  font-size: clamp(22px, 3vw, 30px);
  font-weight: 700;
  letter-spacing: -0.02em;
  text-align: center;
  margin: 0 0 32px;
  max-width: 720px; margin-left: auto; margin-right: auto;
  line-height: 1.2;
}

/* === Numbered step cards (How it works) === */
.mh-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 18px;
  margin-bottom: 48px;
}
.mh-step {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px 22px;
  position: relative;
  transition: border-color 0.25s ease, transform 0.25s ease;
}
.mh-step:hover {
  border-color: rgba(34,211,238,0.4);
  transform: translateY(-2px);
}
.mh-step-num {
  display: inline-flex;
  align-items: center; justify-content: center;
  width: 32px; height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(34,211,238,0.18), rgba(124,58,237,0.18));
  border: 1px solid rgba(34,211,238,0.35);
  color: var(--accent);
  font-weight: 800; font-size: 14px;
  margin-bottom: 14px;
}
.mh-step h3 {
  font-size: 16px; font-weight: 700; color: var(--ink);
  letter-spacing: -0.01em; margin: 0 0 8px;
  text-transform: none;
}
.mh-step p {
  font-size: 13.5px; color: var(--ink-dim);
  line-height: 1.55; margin: 0;
}

/* === Template gallery cards === */
.mh-template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 40px;
}
.mh-template {
  display: flex; flex-direction: column;
  gap: 10px;
  padding: 20px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  text-decoration: none;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.mh-template::before {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(34,211,238,0.06) 0%, transparent 60%);
  opacity: 0; transition: opacity 0.25s ease;
  pointer-events: none;
}
.mh-template:hover {
  border-color: rgba(34,211,238,0.4);
  transform: translateY(-2px);
  text-decoration: none;
}
.mh-template:hover::before { opacity: 1; }
.mh-template-icon {
  width: 38px; height: 38px;
  border-radius: 10px;
  background: rgba(34,211,238,0.1);
  border: 1px solid rgba(34,211,238,0.25);
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--accent); flex-shrink: 0;
  margin-bottom: 4px;
}
.mh-template-icon svg { width: 22px; height: 22px; }
.mh-template h3 {
  font-size: 15px; font-weight: 700; color: var(--ink);
  letter-spacing: -0.01em; margin: 0;
  text-transform: none;
}
.mh-template p {
  font-size: 13px; color: var(--ink-dim);
  line-height: 1.5; margin: 0 0 10px;
  flex: 1;
}
.mh-template-cta {
  font-size: 13px; font-weight: 600;
  color: var(--accent);
  display: inline-flex; align-items: center; gap: 6px;
  margin-top: auto;
}

/* === Provider badge on home === */
.mh-provider-badge {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 10px 16px;
  background: rgba(34,197,94,0.06);
  border: 1px solid rgba(34,197,94,0.25);
  border-radius: 12px;
  font-size: 13px;
  margin-top: 8px;
}
.mh-provider-badge.warn {
  background: rgba(245,158,11,0.06);
  border-color: rgba(245,158,11,0.3);
  color: var(--ink);
}
.mh-provider-badge.warn strong { color: var(--warn); }
.mh-provider-badge .mh-provider-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--good);
}
.mh-provider-badge.warn .mh-provider-dot { background: var(--warn); }

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
"""


def _render_markdown(text: str) -> str:
    """Tiny, dependency-free markdown subset for the research page."""
    import html as _html
    import re as _re

    def _inline(s: str) -> str:
        s = _html.escape(s)
        s = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                    lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', s)
        s = _re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = _re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    table_rows: list[list[str]] = []

    def flush_table():
        if not table_rows:
            return
        head, *rest = table_rows
        rest = [r for r in rest if not all(_re.fullmatch(r":?-+:?", c.strip() or "-") for c in r)]
        out.append('<div style="overflow-x:auto"><table>')
        out.append("<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead>")
        out.append("<tbody>")
        for r in rest:
            out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
        out.append("</tbody></table></div>")
        table_rows.clear()

    in_list = False
    for raw in lines:
        ln = raw.rstrip()
        if ln.startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                out.append('<pre><code>')
            in_code = not in_code
            continue
        if in_code:
            out.append(_html.escape(ln))
            continue
        if ln.startswith("|") and ln.endswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            table_rows.append(cells)
            continue
        if table_rows:
            flush_table()
        m = _re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            if in_list: out.append("</ul>"); in_list = False
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        if ln.startswith("- ") or ln.startswith("* "):
            if not in_list:
                out.append('<ul style="margin-top:6px">'); in_list = True
            out.append(f"<li>{_inline(ln[2:])}</li>")
            continue
        if in_list and not ln.strip():
            out.append("</ul>"); in_list = False
            continue
        if not ln.strip():
            continue
        out.append(f"<p>{_inline(ln)}</p>")

    if table_rows:
        flush_table()
    if in_code:
        out.append("</code></pre>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _layout(title: str, body: str, active: str = "home") -> str:
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{{ title }} — MediaHub</title>
<style>{{ css | safe }}</style>
<script>
  // Detect deployed prefix (e.g. "/port/5000") so XHRs from inline JS use the right base.
  (function(){
    var path = window.location.pathname || '/';
    var m = path.match(/^(\/port\/\d+)/);
    window._API_BASE = m ? m[1] : '';
  })();
</script>
</head>
<body>
<div id="mh-loader" aria-live="polite" aria-busy="true">
  <div class="mh-loader-inner">
    <div class="mh-spinner"></div>
    <div class="mh-loader-text">Working on it</div>
    <div class="mh-loader-sub">This usually takes a few seconds</div>
  </div>
</div>
<div id="mh-toast-container"></div>
<header class="topnav">
  <div class="brand">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M2 12c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>
      <path d="M2 17c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>
      <path d="M2 7c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>
    </svg>
    MediaHub
  </div>
  <nav>
    <a href="{{ url_for('home') }}" class="{{ 'active' if active=='home' else '' }}">Home</a>
    <a href="{{ url_for('add_input_page') }}" class="{{ 'active' if active=='add_input' else '' }}">Add Input</a>
    <a href="{{ url_for('make_page') }}" class="{{ 'active' if active=='create' else '' }}">Create</a>
    <a href="{{ url_for('organisation_page') }}" class="{{ 'active' if active=='organisation' else '' }}">Organisation</a>
    <a href="{{ url_for('media_library_page') }}" class="{{ 'active' if active=='media' else '' }}">Media library</a>
    <a href="{{ url_for('privacy_page') }}" class="{{ 'active' if active=='privacy' else '' }}">Privacy</a>
    <a href="{{ url_for('settings_page') }}" class="{{ 'active' if active=='settings' else '' }}">Settings</a>
    <a id="backend-pill" href="{{ health_url }}" target="_blank" rel="noopener"
       title="Backend status (click for full health JSON)">
      <span id="backend-pill-dot"></span>
      <span id="backend-pill-text">checking…</span>
    </a>
  </nav>
</header>
<main class="wrap">
{{ body | safe }}
</main>
<script>
(function(){
  var HEALTH_URL = {{ health_url|tojson }};
  function check(){
    fetch(HEALTH_URL,{cache:'no-store'}).then(r=>r.json().then(j=>({s:r.status,j:j}))).then(o=>{
      var ok = o.s === 200 && o.j && o.j.ok;
      var dot = document.getElementById('backend-pill-dot');
      var txt = document.getElementById('backend-pill-text');
      if(!dot||!txt) return;
      dot.style.background = ok ? '#2cc97f' : '#ff5d6c';
      txt.textContent = ok ? 'online' : 'offline';
    }).catch(function(){
      var dot = document.getElementById('backend-pill-dot');
      var txt = document.getElementById('backend-pill-text');
      if(!dot||!txt) return;
      dot.style.background = '#ff5d6c'; txt.textContent='offline';
    });
  }
  check(); setInterval(check, 30000);
})();
</script>
<script>
/* === MediaHub UI Framework: loader + toast + form binding === */
(function(){
  var MH = window.MH = window.MH || {};
  var loaderEl = document.getElementById('mh-loader');
  var loaderHideTimer = null;

  MH.showLoader = function(text, sub) {
    if (!loaderEl) return;
    if (loaderHideTimer) { clearTimeout(loaderHideTimer); loaderHideTimer = null; }
    if (text) loaderEl.querySelector('.mh-loader-text').textContent = text;
    if (sub !== undefined) loaderEl.querySelector('.mh-loader-sub').textContent = sub;
    loaderEl.classList.add('show');
  };
  MH.hideLoader = function() {
    if (!loaderEl) return;
    loaderEl.classList.remove('show');
  };

  var toastContainer = document.getElementById('mh-toast-container');
  var ICONS = {
    success: '<svg class="mh-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    error:   '<svg class="mh-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    info:    '<svg class="mh-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };
  MH.toast = function(message, type, ms) {
    if (!toastContainer) return;
    type = type || 'info';
    var t = document.createElement('div');
    t.className = 'mh-toast ' + type;
    t.setAttribute('role', type === 'error' ? 'alert' : 'status');
    t.innerHTML = (ICONS[type] || ICONS.info) +
      '<div style="flex:1;min-width:0">' + message + '</div>' +
      '<button class="mh-toast-close" aria-label="Dismiss">&times;</button>';
    toastContainer.appendChild(t);
    var close = function(){
      t.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
      t.style.opacity = '0'; t.style.transform = 'translateX(16px)';
      setTimeout(function(){ if (t.parentNode) t.remove(); }, 220);
    };
    t.querySelector('.mh-toast-close').addEventListener('click', close);
    setTimeout(close, ms || (type === 'error' ? 7000 : 4500));
  };

  function bindForms() {
    document.querySelectorAll('form').forEach(function(form){
      if (form.dataset.mhBound === '1') return;
      form.dataset.mhBound = '1';
      if (form.dataset.noLoader === '1') return;
      form.addEventListener('submit', function(){
        var method = (form.getAttribute('method') || 'get').toLowerCase();
        if (method === 'get') return;
        var btn = form.querySelector('button[type=submit], input[type=submit]');
        if (btn && !btn.classList.contains('loading')) {
          btn.classList.add('loading');
        }
        var msg = form.dataset.loaderText || 'Working on it';
        var sub = form.dataset.loaderSub || 'This usually takes a few seconds';
        MH.showLoader(msg, sub);
      });
    });
  }
  if (document.readyState !== 'loading') bindForms();
  else document.addEventListener('DOMContentLoaded', bindForms);

  // Re-bind after dynamic content (useful for SPA-like fragments)
  MH.bindForms = bindForms;

  // Wrap fetch for explicit MH usage
  MH.fetch = function(url, options) {
    MH.showLoader();
    return fetch(url, options).then(function(r){
      MH.hideLoader();
      if (!r.ok) MH.toast('Request failed (' + r.status + ')', 'error');
      return r;
    }).catch(function(err){
      MH.hideLoader();
      MH.toast('Network error: ' + (err && err.message || 'unknown'), 'error');
      throw err;
    });
  };

  // Server-flashed messages: any element with data-mh-flash gets shown then removed.
  document.querySelectorAll('[data-mh-flash]').forEach(function(el){
    MH.toast(el.getAttribute('data-mh-message') || el.textContent || '',
             el.getAttribute('data-mh-type') || 'info');
    el.remove();
  });

  // Hide loader when navigating back via bfcache (Safari/Firefox)
  window.addEventListener('pageshow', function(e){
    if (e.persisted) MH.hideLoader();
  });
})();
</script>
</body>
</html>
""", title=title, css=BASE_CSS, body=body, active=active,
               health_url=url_for("healthz"))


# ---------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024   # 50 MB
    app.url_map.strict_slashes = False

    # Persistent SECRET_KEY — survives restarts and redeploys.
    # Priority: env var > persisted file > generated + saved.
    _secret = os.environ.get("SECRET_KEY", "")
    if not _secret:
        _persistent_path = DATA_DIR / ".secret_key"
        if _persistent_path.exists():
            try:
                _secret = _persistent_path.read_text().strip()
            except OSError:
                pass
        if not _secret:
            _secret = os.urandom(32).hex()
            try:
                _persistent_path.write_text(_secret)
            except OSError:
                pass  # writable fallback not available; sessions won't survive restart
    app.config["SECRET_KEY"] = _secret

    # Apply SCRIPT_NAME middleware so url_for generates prefixed URLs when
    # running behind a reverse-proxy. In the published pplx.app environment,
    # the backend is reached via /port/5000/... — default to that unless
    # explicitly overridden.
    _script_name = os.environ.get("SCRIPT_NAME", "/port/5000").rstrip("/")
    if _script_name:
        _real_wsgi = app.wsgi_app

        def _script_name_middleware(environ, start_response):
            environ["SCRIPT_NAME"] = _script_name
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(_script_name):
                environ["PATH_INFO"] = path_info[len(_script_name):] or "/"
            return _real_wsgi(environ, start_response)

        app.wsgi_app = _script_name_middleware  # type: ignore[assignment]

    # ---- HOME ----------------------------------------------------------
    @app.route("/")
    def home():
        conn = _db()
        rows = conn.execute(
            "SELECT id, created_at, finished_at, status, profile_id, "
            "meet_name, our_swims, n_cards, n_queue, error, file_name "
            "FROM runs ORDER BY created_at DESC LIMIT 25"
        ).fetchall()
        conn.close()

        # Build the Holo-style home page. Hero + how-it-works + templates
        # are shared between empty and populated states; recent activity table
        # only appears when there are runs.
        _add_input_url = url_for('add_input_page')
        _org_url = url_for('organisation_page')
        _settings_url = url_for('settings_page')

        # Detect active LLM provider for the live status pill.
        try:
            from mediahub.media_ai.llm import is_available as _llm_available, active_provider as _ap
            _llm_live = _llm_available()
            _llm_provider = _ap()
        except Exception:
            _llm_live = False
            _llm_provider = "heuristic"
        _PROVIDER_PRETTY = {
            "anthropic-api": "Anthropic (Claude)",
            "gemini-api":    "Google Gemini",
            "claude-cli":    "Claude CLI",
            "pplx-bridge":   "Computer bridge",
        }
        _provider_pretty = _PROVIDER_PRETTY.get(_llm_provider, "")
        if _llm_live:
            provider_badge_html = (
                f'<div class="mh-provider-badge">'
                f'<span class="mh-provider-dot"></span>'
                f'<span><strong>Content engine live</strong> &mdash; powered by {_h(_provider_pretty)}</span>'
                f'</div>'
            )
        else:
            provider_badge_html = (
                f'<div class="mh-provider-badge warn">'
                f'<span class="mh-provider-dot"></span>'
                f'<span><strong>Heuristic mode</strong> &mdash; '
                f'<a href="{_settings_url}">add a free Gemini key</a> to enable live AI content</span>'
                f'</div>'
            )

        hero_html = (
            '<section class="mh-hero">'
            '<div class="mh-hero-eyebrow"><span class="mh-pulse-dot"></span> The content engine for clubs and teams</div>'
            '<h1>Turn every result into <span class="mh-gradient-text">ready-to-post content</span> in minutes</h1>'
            '<p class="mh-hero-sub">Upload results, paste an update, or describe a moment. MediaHub finds the moments worth celebrating, drafts on-brand captions, and stops nothing falling through the cracks. Human approval before anything goes out.</p>'
            f'<div class="mh-hero-ctas">'
            f'<a class="btn" href="{_add_input_url}">Create content &rarr;</a>'
            f'<a class="btn secondary" href="{_org_url}">Set up your club</a>'
            f'</div>'
            '<div class="mh-hero-trust">'
            '<span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> Source-grounded captions</span>'
            '<span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> Confidence scoring</span>'
            '<span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> Human approval before posting</span>'
            '</div>'
            f'<div style="margin-top:24px;display:flex;justify-content:center">{provider_badge_html}</div>'
            '</section>'
        )

        steps_html = (
            '<div class="mh-section-eyebrow">How it works</div>'
            '<h2 class="mh-section-title">From results to ready-to-post content, end to end</h2>'
            '<div class="mh-steps">'
            '<div class="mh-step"><div class="mh-step-num">1</div><h3>Add an input</h3>'
            '<p>Upload a Hytek results file, paste a sponsor brief, or describe a moment in your own words. Any sport. Any club.</p></div>'
            '<div class="mh-step"><div class="mh-step-num">2</div><h3>We detect the moments</h3>'
            '<p>The engine spots PBs, medals, first-times, comebacks and standout swims, then ranks them by content-worthiness.</p></div>'
            '<div class="mh-step"><div class="mh-step-num">3</div><h3>On-brand drafts appear</h3>'
            "<p>Captions are written in your club&rsquo;s voice, using your tone, sponsor rules, and example posts you&rsquo;ve shared.</p></div>"
            '<div class="mh-step"><div class="mh-step-num">4</div><h3>Approve and post</h3>'
            '<p>You review, edit, approve. Nothing goes out without you. Export as text, copy to Stories, or download a pack.</p></div>'
            '</div>'
        )

        # Content template gallery (live content types only)
        templates_html = ""
        try:
            from mediahub.club_platform.content_types import REGISTRY as _CT_REGISTRY
        except ImportError:
            _CT_REGISTRY = {}
        tile_html = ""
        for _ct, _meta in (_CT_REGISTRY or {}).items():
            if not getattr(_meta, "is_implemented", False):
                continue
            try:
                _tile_url = url_for(_meta.primary_route_endpoint)
            except Exception:
                _tile_url = "#"
            _icon = _meta.icon_svg.replace('width="28" height="28"', 'width="22" height="22"')
            tile_html += (
                f'<a class="mh-template" href="{_tile_url}">'
                f'<div class="mh-template-icon">{_icon}</div>'
                f'<h3>{_h(_meta.title)}</h3>'
                f'<p>{_h(_meta.description)}</p>'
                f'<span class="mh-template-cta">Start &rarr;</span>'
                f'</a>'
            )
        if tile_html:
            templates_html = (
                '<div class="mh-section-eyebrow">Content templates</div>'
                "<h2 class=\"mh-section-title\">Pick a format and we'll do the rest</h2>"
                f'<div class="mh-template-grid">{tile_html}</div>'
            )

        # Set-up-org callout (only if no profiles yet)
        _has_org = bool(list_profiles())
        _org_cta = ""
        if not _has_org:
            _org_cta = (
                '<div class="card" style="border-color:rgba(34,211,238,0.3);'
                'margin-bottom:24px;display:flex;align-items:center;gap:20px;flex-wrap:wrap">'
                '<div style="flex:1;min-width:240px">'
                '<h2 style="margin-top:0;margin-bottom:6px">Set up your organisation</h2>'
                '<p style="margin:0">Tell MediaHub about your club, tone of voice, and sponsor &mdash; '
                'content will land in your style automatically.</p>'
                '</div>'
                f'<a class="btn" href="{_org_url}">Set up organisation &rarr;</a>'
                '</div>'
            )

        # Empty state: just hero + steps + templates + org-cta. No table.
        if not rows:
            empty_body = hero_html + _org_cta + steps_html + templates_html
            return _layout("Home", empty_body, active="home")

        rows_html = ""
        if not rows:
            rows_html = ('<tr><td colspan="7" class="muted">No runs yet. '
                         '<a href="' + url_for('upload') + '">Upload your first meet &rarr;</a></td></tr>')
        else:
            for r in rows:
                badge = {"done": "good", "running": "info", "queued": "info",
                         "error": "bad"}.get(r["status"], "")
                review_href = url_for('review', run_id=r['id'])
                delete_href = url_for('privacy_delete_run', run_id=r['id'])
                # V8.2: club profiles UI removed; show the stored club
                # filter / profile_id slug as a friendly label.
                prof_display = (r["profile_id"] or "—").replace("-", " ").replace("_", " ")
                if prof_display.startswith(" run "):
                    prof_display = "—"
                rows_html += (
                    f'<tr><td><a href="{review_href}">{_h(r["meet_name"] or r["file_name"] or r["id"])}</a></td>'
                    f'<td><span class="tag {badge}">{_h(r["status"])}</span></td>'
                    f'<td>{_h(prof_display)}</td>'
                    f'<td>{_h(r["our_swims"] or 0)}</td>'
                    f'<td>{_h(r["n_queue"] or 0)} / {_h(r["n_cards"] or 0)}</td>'
                    f'<td class="muted">{_h((r["created_at"] or "")[:19])}</td>'
                    f'<td><form method="post" action="{delete_href}" '
                    f'style="display:inline" data-no-loader="1" onsubmit="return confirm(\'Delete this run? This cannot be undone.\')">'
                    f'<button class="btn danger" type="submit" '
                    f'style="font-size:11px;padding:4px 10px">Delete</button>'
                    f'</form></td></tr>'
                )

        recent_html = (
            '<div class="mh-section-eyebrow">Your activity</div>'
            '<h2 class="mh-section-title">Recent runs</h2>'
            '<div class="card"><table>'
            '<thead><tr><th>Input</th><th>Status</th><th>Organisation</th>'
            '<th>Matched items</th><th>Queue / Total</th><th>Started</th><th></th></tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            '</table></div>'
        )

        body = hero_html + _org_cta + steps_html + templates_html + recent_html
        return _layout("Home", body, active="home")

    # ---- UPLOAD --------------------------------------------------------
    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        # V8.2 issue 3: every upload now goes through /upload/configure.
        # The upload form has only the file input + submit. Branding is
        # collected on the configure step, after we've parsed the file.
        if request.method == "POST":
            f = request.files.get("file")
            if not f or not f.filename:
                return _layout("Upload", '<div class="card"><p class="tag bad">No file selected.</p></div>', active="add_input")
            data = f.read()
            if not data:
                return _layout("Upload", '<div class="card"><p class="tag bad">Uploaded file was empty.</p></div>', active="add_input")

            temp_run_id = uuid.uuid4().hex[:12]
            tmp_dir = RUNS_DIR / temp_run_id
            tmp_dir.mkdir(parents=True, exist_ok=True)
            (tmp_dir / "input.bin").write_bytes(data)
            meta = {
                "filename": f.filename,
                "profile_id": None,
                "use_cache": True,
                "fetch_pbs": True,
                "display_name": "",
            }
            # Light parse: extract clubs from the file. Only clubs that
            # actually appear in this meet are listed on configure.
            try:
                from mediahub.interpreter import interpret_document
                interpreted = interpret_document(data, hint=None)
                clubs: list[str] = []
                seen: set[str] = set()
                for ev in interpreted.events:
                    for sw in ev.swims:
                        c = (sw.club or "").strip()
                        if c and c.lower() not in seen:
                            seen.add(c.lower())
                            clubs.append(c)
                meta["clubs"] = sorted(clubs, key=str.lower)
                meta["meet_name"] = interpreted.meet_name or ""
            except Exception as exc:
                meta["clubs"] = []
                meta["parse_error"] = str(exc)
            (tmp_dir / "upload_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            return redirect(url_for("upload_configure", run_id=temp_run_id))

        body = f"""
<h1>Upload meet file</h1>
<div class="card">
  <form method="post" enctype="multipart/form-data">
    <label>Meet results file</label>
    <input type="file" name="file" accept=".hy3,.zip,.pdf" required />
    <p class="dim" style="margin-top:4px;font-size:12px">Accepted: Hytek Meet Manager .hy3 or .zip export, or a Sportsystems PDF results file.</p>
    <p class="dim" style="margin-top:6px;font-size:12px">
      You'll choose your club, upload your logo, and add photos on the next step — after we read your file.
    </p>
    <div style="margin-top:18px"><button class="btn" type="submit">Continue →</button></div>
  </form>
</div>
"""
        return _layout("Upload", body, active="add_input")

    # ---- UPLOAD CONFIGURE (V8.1 issue 6: two-step; V8.2 issue 6: photos) ---
    def _render_configure(run_id: str, meta: dict, *, error: str = "",
                          selected_club: str = "") -> str:
        clubs = meta.get("clubs") or []
        meet_name = meta.get("meet_name") or ""
        parse_err = meta.get("parse_error") or ""

        # No clubs detected \u2192 render a polished error state, NOT a broken form.
        if not clubs:
            upload_url = url_for("upload")
            err_explain = (
                f'<p class="dim" style="margin-bottom:12px;font-size:13px">'
                f'Reason: <code>{_h(parse_err)}</code></p>'
                if parse_err else ""
            )
            body = f"""
<h1>We couldn't read clubs from that file</h1>
<div class="card">
  <p>The file <code>{_h(meta.get('filename') or '(unknown)')}</code> didn't expose any clubs we can filter on.
     This usually means the format isn't supported, the file is corrupted, or the meet had no club info.</p>
  {err_explain}
  <p class="dim" style="font-size:13px">Supported formats: Hytek Meet Manager <code>.hy3</code>, a <code>.zip</code> containing one, or a Sportsystems PDF results file.</p>
  <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
    <a class="btn" href="{upload_url}">\u2190 Try another file</a>
    <a class="btn secondary" href="{url_for('add_input_page')}">Pick a different input type</a>
  </div>
</div>
"""
            return _layout("Couldn't read file", body, active="add_input")

        # V8.2 issue 4: ONLY clubs from this file are listed.
        opts = "".join(
            f'<option value="{_h(c)}"{" selected" if c == selected_club else ""}>{_h(c)}</option>'
            for c in clubs
        )
        err_html = (
            f'<p class="tag bad" style="margin-bottom:14px">{_h(error)}</p>' if error else ""
        )
        body = f"""
<h1>Configure this run</h1>
<div class="card">
  <p class="dim">{_h(meet_name) or 'Meet uploaded.'} \u2014 {len(clubs)} clubs detected in this file.</p>
  {err_html}
  <form method="post" enctype="multipart/form-data" data-loader-text="Setting up your run" data-loader-sub="Saving config and starting the pipeline\u2026">
    <input type="hidden" name="run_id" value="{_h(run_id)}" />

    <label>Club to feature</label>
    <select name="club_filter" required>{opts}</select>
    <p class="dim" style="margin-top:4px;font-size:12px">Only clubs that actually appear in this meet are listed.</p>

    <fieldset style="margin-top:18px;border:1px solid var(--border);border-radius:8px;padding:14px 18px">
      <legend style="padding:0 8px;font-size:12px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.5px">Branding (required)</legend>
      <p class="dim" style="margin:0 0 10px;font-size:12px">Upload a logo, or pick brand colours \u2014 at least one is required.</p>
      <label>Club logo (PNG / JPG / SVG)</label>
      <input type="file" name="club_logo" accept="image/png,image/jpeg,image/svg+xml" />

      <div style="display:flex;gap:14px;align-items:flex-end;margin-top:12px;flex-wrap:wrap">
        <div><label style="display:block">Primary</label><input type="color" name="primary_colour" value="#0A2540" /></div>
        <div><label style="display:block">Secondary</label><input type="color" name="secondary_colour" value="#101820" /></div>
        <div><label style="display:block">Accent</label><input type="color" name="accent_colour" value="#FFD86E" /></div>
      </div>
      <label style="margin-top:10px;display:block"><input type="checkbox" name="use_logo_colours" value="1" /> Use logo colours as club colours (auto-extract)</label>
    </fieldset>

    <fieldset style="margin-top:18px;border:1px solid var(--border);border-radius:8px;padding:14px 18px">
      <legend style="padding:0 8px;font-size:12px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.5px">Photos (optional)</legend>
      <label>Athlete portraits, action shots, venue images (multi-select)</label>
      <input type="file" name="club_photos" multiple accept="image/*" />
      <p class="dim" style="margin-top:4px;font-size:12px">Uploaded photos will be preferred for graphic generation in this run and saved to your media library.</p>
    </fieldset>

    <div style="margin-top:18px"><button class="btn" type="submit">Run pipeline \u2192</button></div>
  </form>
</div>
"""
        return _layout("Configure run", body, active="add_input")

    @app.route("/upload/configure", methods=["GET", "POST"])
    def upload_configure():
        run_id = request.values.get("run_id", "").strip()
        if not run_id:
            return _layout("Configure", '<div class="card"><p class="tag bad">Missing run_id.</p></div>', active="add_input")
        tmp_dir = RUNS_DIR / run_id
        meta_path = tmp_dir / "upload_meta.json"
        input_path = tmp_dir / "input.bin"
        if not (meta_path.exists() and input_path.exists()):
            return _layout("Configure", '<div class="card"><p class="tag bad">Upload session not found or expired.</p></div>', active="add_input")
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            meta = {}

        if request.method == "POST":
            club_filter = (request.form.get("club_filter") or "").strip() or None
            if not club_filter:
                return _layout("Configure", '<div class="card"><p class="tag bad">Pick a club to feature.</p></div>', active="add_input")

            # V8.2 issue 5: branding is now required. Either a logo or
            # the colour pickers must be filled in.
            logo_file = request.files.get("club_logo")
            logo_bytes = logo_file.read() if (logo_file and logo_file.filename) else None
            logo_filename = logo_file.filename if (logo_file and logo_file.filename) else None
            primary_form = (request.form.get("primary_colour") or "").strip() or None
            secondary_form = (request.form.get("secondary_colour") or "").strip() or None
            accent_form = (request.form.get("accent_colour") or "").strip() or None
            use_logo_colours = request.form.get("use_logo_colours") in ("1", "on", "true", "True")
            display_name_form = (request.form.get("display_name") or club_filter or "").strip()
            has_branding = bool(logo_bytes or primary_form or secondary_form or accent_form)
            if not has_branding:
                return _render_configure(
                    run_id, meta,
                    error="Please upload a logo or pick at least one brand colour before running.",
                    selected_club=club_filter,
                )

            data = input_path.read_bytes()
            profile_id = meta.get("profile_id") or None
            use_cache = bool(meta.get("use_cache", True))
            fetch_pbs = bool(meta.get("fetch_pbs", True))
            filename = meta.get("filename") or "upload.bin"

            # Kick off the real run; reuse the temp run_id.
            new_run_id = _start_run(
                data, filename, profile_id, use_cache, fetch_pbs,
                club_filter=club_filter,
            )

            # Persist the brand kit (logo + colours) for the new run id.
            try:
                from .brand_kit_upload import process_upload as _bk_process
                _bk_process(
                    new_run_id,
                    logo_bytes=logo_bytes,
                    logo_filename=logo_filename,
                    primary_form=primary_form,
                    secondary_form=secondary_form,
                    accent_form=accent_form,
                    use_logo_colours=use_logo_colours,
                    display_name=display_name_form,
                )
            except Exception:
                pass

            # V8.2 issue 6: per-run photo library. Save each uploaded photo
            # to runs_v4/<run_id>/media/ + a metadata sidecar, and persist
            # to the V8 media library with profile_id = the synthetic
            # "_run_<new_run_id>" id used by the renderer.
            try:
                photo_files = request.files.getlist("club_photos")
            except Exception:
                photo_files = []
            saved_photos: list[dict] = []
            if photo_files:
                from datetime import datetime
                import mimetypes as _mt
                media_dir = RUNS_DIR / new_run_id / "media"
                media_dir.mkdir(parents=True, exist_ok=True)
                run_profile_id = re.sub(
                    r"[^a-z0-9_-]", "-",
                    (club_filter or ("_run_" + new_run_id)).lower(),
                ).strip("-") or ("_run_" + new_run_id)
                for pf in photo_files:
                    if not pf or not pf.filename:
                        continue
                    try:
                        body_bytes = pf.read()
                        if not body_bytes:
                            continue
                        suffix = Path(pf.filename).suffix.lower() or ".jpg"
                        safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(pf.filename).stem)
                        dest = media_dir / f"{uuid.uuid4().hex[:8]}_{safe_stem}{suffix}"
                        dest.write_bytes(body_bytes)
                        meta_entry = {
                            "filename": pf.filename,
                            "path": str(dest),
                            "mime": _mt.guess_type(pf.filename)[0] or "",
                            "uploaded_at": datetime.utcnow().isoformat() + "Z",
                            "size": len(body_bytes),
                        }
                        saved_photos.append(meta_entry)
                        # Persist to V8 media library too, keyed by the run-scoped profile_id.
                        try:
                            from mediahub.media_library.store import get_store as _ml_get
                            from mediahub.media_library.models import MediaAsset as _MA
                            ml = _ml_get()
                            asset = _MA(
                                id="",
                                filename=pf.filename,
                                path=str(dest),
                                type="athlete_action",
                                profile_id=run_profile_id,
                                description_raw="User-uploaded photo (configure step)",
                                permission_status="approved_by_club",
                                approval_status="approved",
                                uploaded_at=meta_entry["uploaded_at"],
                            )
                            ml.save(asset)
                        except Exception:
                            pass
                    except Exception:
                        continue
                # Write a sidecar so the run dir is self-describing.
                try:
                    (media_dir / "manifest.json").write_text(
                        json.dumps({"photos": saved_photos}, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            return redirect(url_for("run_status", run_id=new_run_id))

        return _render_configure(run_id, meta)

    # ---- PROGRESS ------------------------------------------------------
    @app.route("/runs/<run_id>")
    def run_status(run_id):
        _status_url = url_for('api_status', run_id=run_id)
        _review_url = url_for('review', run_id=run_id)
        # Five named stages, mapped from log message substrings.
        # Each stage shows "queued" by default, becomes "active" when its
        # keyword first appears in the log, "done" when the next stage's
        # keyword appears (or the run finishes successfully).
        body = f"""
<h1>Run in progress</h1>
<p class="dim" style="margin-bottom:6px">Sit tight — we're parsing, ranking and drafting. This usually takes 20–60 seconds.</p>

<div class="card">
  <div class="mh-stages" id="mh-stages">
    <div class="mh-stage" data-stage="parse"    data-state="queued"><div class="mh-stage-label">1 · Parse</div><div class="mh-stage-text">Reading the file</div></div>
    <div class="mh-stage" data-stage="filter"   data-state="queued"><div class="mh-stage-label">2 · Filter</div><div class="mh-stage-text">Finding your athletes</div></div>
    <div class="mh-stage" data-stage="pb"       data-state="queued"><div class="mh-stage-label">3 · Personal bests</div><div class="mh-stage-text">Checking historical times</div></div>
    <div class="mh-stage" data-stage="detect"   data-state="queued"><div class="mh-stage-label">4 · Detect</div><div class="mh-stage-text">Spotting achievements</div></div>
    <div class="mh-stage" data-stage="generate" data-state="queued"><div class="mh-stage-label">5 · Generate</div><div class="mh-stage-text">Drafting captions</div></div>
  </div>

  <div class="mh-progress-bar indeterminate"><span></span></div>
  <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--ink-muted);margin-top:4px">
    <span id="mh-current-stage">Starting…</span>
    <span id="mh-step-count">0 steps</span>
  </div>

  <details style="margin-top:18px">
    <summary style="cursor:pointer;color:var(--ink-dim);font-size:13px;user-select:none">Show technical log</summary>
    <div class="progress-log" id="log" style="margin-top:10px">Starting…</div>
  </details>

  <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
    <a id="review-link" class="btn" style="display:none" href="{_review_url}">Open review queue →</a>
    <a id="home-link"   class="btn secondary" href="{url_for('home')}">View on home</a>
  </div>
</div>

<script>
(function() {{
  var STATUS_URL = {json.dumps(_status_url)};
  var REVIEW_URL = {json.dumps(_review_url)};
  var STAGES = ['parse','filter','pb','detect','generate'];
  // Keyword → stage. First match wins; we scan each log line.
  var STAGE_PATTERNS = [
    {{re: /interpret|bridg|parse/i,                stage: 'parse'}},
    {{re: /filter|club|swims for/i,                stage: 'filter'}},
    {{re: /PB|personal best|cache/i,               stage: 'pb'}},
    {{re: /detect|recogni|claim|achievement/i,     stage: 'detect'}},
    {{re: /caption|card|generat|render|content/i,  stage: 'generate'}}
  ];
  function detectStage(logLines) {{
    var idx = -1;
    for (var i = 0; i < logLines.length; i++) {{
      for (var k = 0; k < STAGE_PATTERNS.length; k++) {{
        if (STAGE_PATTERNS[k].re.test(logLines[i])) {{
          var s = STAGES.indexOf(STAGE_PATTERNS[k].stage);
          if (s > idx) idx = s;
        }}
      }}
    }}
    return idx;
  }}
  function applyStages(currentIdx, status) {{
    var stageEls = document.querySelectorAll('.mh-stage');
    stageEls.forEach(function(el, i) {{
      if (status === 'error') {{ el.setAttribute('data-state', i <= currentIdx ? 'error' : 'queued'); return; }}
      if (status === 'done')  {{ el.setAttribute('data-state', 'done'); return; }}
      if (i < currentIdx) el.setAttribute('data-state', 'done');
      else if (i === currentIdx) el.setAttribute('data-state', 'active');
      else el.setAttribute('data-state', 'queued');
    }});
    var bar = document.querySelector('.mh-progress-bar');
    if (status === 'done')  {{
      bar.classList.remove('indeterminate');
      bar.firstElementChild.style.width = '100%';
    }} else if (status === 'error') {{
      bar.classList.remove('indeterminate');
      bar.firstElementChild.style.background = 'linear-gradient(90deg, var(--bad), #fb7185)';
      bar.firstElementChild.style.width = '100%';
    }} else {{
      bar.classList.add('indeterminate');
    }}
    var labelEl = document.getElementById('mh-current-stage');
    if (status === 'error') labelEl.textContent = 'Run failed';
    else if (status === 'done') labelEl.textContent = 'Complete';
    else if (currentIdx < 0) labelEl.textContent = 'Starting…';
    else {{
      var labels = ['Reading the file…','Finding your athletes…','Checking personal bests…','Spotting achievements…','Drafting captions…'];
      labelEl.textContent = labels[currentIdx] || 'Working…';
    }}
  }}
  async function poll() {{
    try {{
      var r = await fetch(STATUS_URL, {{cache:'no-store'}});
      var j = await r.json();
      var log = j.log || [];
      var logEl = document.getElementById('log');
      logEl.textContent = log.join('\\n');
      logEl.scrollTop = logEl.scrollHeight;
      document.getElementById('mh-step-count').textContent = log.length + ' step' + (log.length === 1 ? '' : 's');
      var idx = detectStage(log);
      applyStages(idx, j.status);
      if (j.status === 'done') {{
        document.getElementById('review-link').style.display = 'inline-flex';
        if (window.MH) MH.toast('Run complete — opening review queue', 'success', 2500);
        setTimeout(function() {{ location.replace(REVIEW_URL); }}, 1200);
        return;
      }}
      if (j.status === 'error') {{
        logEl.textContent += '\\n\\nERROR: ' + (j.error || 'unknown');
        if (window.MH) MH.toast('Run failed: ' + (j.error || 'see log'), 'error', 8000);
        return;
      }}
    }} catch (e) {{}}
    setTimeout(poll, 800);
  }}
  poll();
}})();
</script>
"""
        return _layout("Run progress", body, active="add_input")

    @app.route("/api/runs/<run_id>/status")
    def api_status(run_id):
        with _active_lock:
            active = _active_runs.get(run_id, {}).copy()
        if active:
            return jsonify(active)
        # Fallback to persisted status
        conn = _db()
        row = conn.execute(
            "SELECT status, error FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({"status": "unknown", "error": "Run not found"}), 404
        return jsonify({"status": row["status"], "error": row["error"], "log": []})

    # ---- REVIEW (V5 Recognition UI) ------------------------------------
    @app.route("/review/<run_id>")
    def review(run_id):
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        meet = data.get("meet") or {}
        cards = data.get("cards") or []
        trust = data.get("trust") or {}
        warnings = data.get("parse_warnings") or []
        sc = data.get("self_check") or {}
        ds = data.get("detector_summary") or {}
        dispatch_log = data.get("dispatch_log") or {}
        rr = data.get("recognition_report") or {}
        recognition_error = data.get("recognition_error") or ""

        # --- Header
        _gt_url = url_for('ground_truth', run_id=run_id)
        _export_url = url_for('api_export', run_id=run_id)
        _rec_json_url = url_for('api_recognition', run_id=run_id)
        _delete_url = url_for('privacy_delete_run', run_id=run_id)
        _status_url = url_for('api_status', run_id=run_id)
        _pack_url = url_for('content_pack', run_id=run_id)
        _reel_url = url_for('api_run_reel', run_id=run_id)
        _turn_into_api = url_for('api_turn_into', run_id=run_id)

        # Prior Turn-Into packs for this run (so the user can revisit them).
        try:
            from mediahub.turn_into import list_packs as _list_ti_packs
            _ti_packs = _list_ti_packs(run_id, base_dir=DATA_DIR / "turn_into_packs")
        except Exception:
            _ti_packs = []

        # --- V7: Workflow state
        _wf_summary = {}
        _wf_states = {}
        _wf_api_base = url_for('api_workflow_set', run_id=run_id, card_id='CARD_ID').replace('CARD_ID', '')
        ws = _get_wf_store()
        if ws is not None:
            _wf_summary = ws.summary(run_id)
            _wf_states = ws.load(run_id)

        # Workflow filter from query param
        _wf_filter = request.args.get('wf', '')   # '' | 'queue' | 'approved' | 'posted' 

        # --- Recognition summary band
        n_elite = rr.get('n_elite', 0)
        n_strong = rr.get('n_strong', 0)
        n_story = rr.get('n_story', 0)
        n_total = rr.get('n_achievements', 0)
        n_analysed = rr.get('n_swims_analysed', data.get('our_swim_count', 0))
        n_cards = len(cards)

        rec_stats_html = "".join([
            f'<div class="stat"><div class="l" style="color:#F59E0B">Elite</div><div class="v" style="color:#F59E0B">{n_elite}</div></div>',
            f'<div class="stat"><div class="l" style="color:#22D3EE">Strong</div><div class="v" style="color:#22D3EE">{n_strong}</div></div>',
            f'<div class="stat"><div class="l" style="color:#A78BFA">Story</div><div class="v" style="color:#A78BFA">{n_story}</div></div>',
            f'<div class="stat"><div class="l">Total achievements</div><div class="v">{n_total}</div></div>',
            f'<div class="stat"><div class="l">Swims analysed</div><div class="v">{n_analysed}</div></div>',
            f'<div class="stat"><div class="l">Cards</div><div class="v">{n_cards}</div></div>',
        ])

        # --- Meet context card
        mctx = rr.get('meet_context') or {}
        ctx_sources = mctx.get('research_sources') or []
        ctx_sources_html = ""
        if ctx_sources:
            ctx_sources_html = '<ul style="margin-top:6px;">'
            for s in ctx_sources[:5]:
                u = _h(s.get('url',''))
                n = _h(s.get('name', s.get('url','')))
                ctx_sources_html += f'<li><a href="{u}" target="_blank" rel="noopener">{n}</a></li>'
            ctx_sources_html += '</ul>'
        elif not mctx.get('research_available'):
            ctx_sources_html = '<p class="muted" style="font-size:12px">No external sources retrieved for this meet. Context derived from results file only.</p>'

        def ctx_badge(val):
            if val:
                return '<span class="tag good">yes</span>'
            return '<span class="tag">no</span>'

        meet_ctx_html = f"""
<div class="card">
  <h2>Meet context</h2>
  <div class="kv">
    <span class="k">Meet level</span><span><span class="tag info">{_h(mctx.get('meet_level','open'))}</span></span>
    <span class="k">Governing body</span><span>{_h(mctx.get('governing_body') or '—')}</span>
    <span class="k">Has finals</span><span>{ctx_badge(mctx.get('has_finals'))}</span>
    <span class="k">Has age groups</span><span>{ctx_badge(mctx.get('has_age_groups'))}</span>
    <span class="k">Age groups</span><span class="muted">{_h(', '.join(mctx.get('age_groups') or []) or '—')}</span>
    <span class="k">Research</span><span>{'<span class="tag good">available</span>' if mctx.get('research_available') else '<span class="tag warn">unavailable</span>'}</span>
  </div>
  {('<div style="margin-top:10px"><span class="k">Sources</span>' + ctx_sources_html + '</div>') if ctx_sources_html else ''}
</div>"""

        # --- Top achievements panel
        ranked_achs = rr.get('ranked_achievements') or []
        top_achs = ranked_achs[:10]

        def band_cls(band):
            return {
                'elite': 'warn',
                'strong': 'info',
                'story': '',
                'nice': '',
                'not_worthy': 'bad',
            }.get(band, '')

        ach_rows_html = ""
        for ra in top_achs:
            a = ra.get('achievement', {})
            band = ra.get('quality_band', 'nice')
            prio = ra.get('priority', 0.0)
            rank = ra.get('rank', 0)
            conf_label = a.get('confidence_label', 'medium')
            conf_cls = {'high': 'good', 'medium': 'warn', 'low': 'bad'}.get(conf_label, '')
            swimmer = _h(a.get('swimmer_name', ''))
            event = _h(a.get('event', ''))
            headline = _h(a.get('headline', ''))
            atype = _h(_humanise(a.get('type', '')))
            swim_id = _h(a.get('swim_id', ''))
            post_type = _h(ra.get('suggested_post_type', ''))
            prio_bar_pct = int(prio * 100)
            _trace_url = url_for('api_swim_trace', run_id=run_id, swim_id=a.get('swim_id','x'))

            # Evidence list
            ev_html = ""
            for ev in (a.get('evidence') or [])[:3]:
                ev_url = ev.get('source_url') or ''
                ev_src = _h(ev.get('source_name', ''))
                ev_stmt = _h(ev.get('statement', ''))
                if ev_url:
                    ev_html += f'<li><a href="{_h(ev_url)}" target="_blank" rel="noopener">{ev_src}</a>: {ev_stmt}</li>'
                else:
                    ev_html += f'<li><strong>{ev_src}</strong>: {ev_stmt}</li>'

            # Factor list
            factors_html = ""
            for f in (ra.get('factors') or [])[:6]:
                fname = _h(f.get('name',''))
                fval = f.get('value', 0.0)
                freason = _h(f.get('reason',''))
                factors_html += f'<tr><td style="font-size:12px">{fname}</td><td style="font-size:12px">{fval:.3f}</td><td style="font-size:12px;color:var(--ink-muted)">{freason}</td></tr>'

            ach_rows_html += f"""
<div class="ach-row" data-type="{a.get('type','')}" data-conf="{conf_label}" data-swimmer="{a.get('swimmer_name','')}" data-event="{a.get('event','')}" data-band="{band}" data-post="{ra.get('suggested_post_type','')}">
  <div style="display:flex;align-items:flex-start;gap:14px;padding:14px 0;border-bottom:1px solid var(--border)">
    <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px;padding-top:2px">#{rank}</div>
    <div style="flex:1">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="tag {band_cls(band)}" style="font-size:10px">{band.upper()}</span>
        <span class="tag info" style="font-size:10px">{atype}</span>
        <span class="tag {conf_cls}" style="font-size:10px">conf: {conf_label}</span>
        <span class="tag" style="font-size:10px">{post_type}</span>
        <div style="flex:1;min-width:80px;max-width:160px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:{prio_bar_pct}%;background:var(--accent)"></div>
        </div>
        <span class="muted" style="font-size:11px">{prio:.2f}</span>
      </div>
      <div style="font-size:13px;font-weight:600;margin-bottom:2px">{swimmer} · {event}</div>
      <div style="font-size:13px;color:var(--ink-dim)">{headline}</div>
      <details style="margin-top:8px">
        <summary style="cursor:pointer;font-size:12px;color:var(--accent);user-select:none">Expand factors &amp; evidence</summary>
        <div style="margin-top:8px;font-size:12px">
          <div style="margin-bottom:6px"><strong>Ranking factors:</strong></div>
          <table style="font-size:12px;margin-bottom:10px"><thead><tr><th>Factor</th><th>Value</th><th>Reason</th></tr></thead><tbody>{factors_html}</tbody></table>
          <div style="margin-bottom:4px"><strong>Evidence:</strong></div>
          <ul style="margin:0;padding-left:18px">{ev_html or '<li class="muted">No evidence items</li>'}</ul>
          <div style="margin-top:8px"><a href="{_trace_url}" target="_blank" rel="noopener" style="font-size:12px">View full trace JSON →</a></div>
        </div>
      </details>
    </div>
  </div>
</div>"""

        if not ach_rows_html:
            if recognition_error:
                ach_rows_html = f'<div class="empty">Recognition engine error: {_h(recognition_error)}</div>'
            elif not rr:
                ach_rows_html = '<div class="empty">No recognition report available. Re-upload the file to generate achievements.</div>'
            else:
                ach_rows_html = '<div class="empty">No achievements detected.</div>'

        # --- Not generated panel
        swim_traces_raw = rr.get('swim_traces') or []
        no_ach_traces = [t for t in swim_traces_raw if t.get('achievement_count', 0) == 0]
        not_gen_rows = ""
        for t in no_ach_traces[:30]:
            not_gen_rows += (
                f'<tr data-swimmer="{t.get("swimmer_name","")}" data-event="{t.get("event","")}">'  
                f'<td>{_h(t.get("swimmer_name",""))}</td>'
                f'<td>{_h(t.get("event",""))}</td>'
                f'<td style="font-family:monospace">{_h(t.get("time_str",""))}</td>'
                f'<td style="font-size:12px;color:var(--ink-muted)">{_h(t.get("summary",""))}</td>'
                f'</tr>'
            )

        # --- Legacy V4 cards (collapsed)
        tcards = {t["card_id"]: t for t in trust.get("cards", [])}
        v4_rows = []
        for c in cards:
            t = tcards.get(c["card_id"], {})
            conf = t.get("confidence", "medium")
            safe = t.get("safe_to_post", "review")
            badge = {"high": "good", "medium": "warn", "low": "bad"}.get(conf, "")
            safe_badge = {"post": "good", "review": "warn", "hold": "bad"}.get(safe, "")
            sources_str = ", ".join(s.get("name", "") for s in (t.get("sources") or [])[:3])
            v4_rows.append(
                f'<tr><td><span class="tag info">{_h(_humanise(c.get("card_type", "")))}</span><br>'
                f'<strong>{_h((c.get("headline") or "")[:80])}</strong>'
                f'<div class="muted" style="font-size:12px">{_h((c.get("subhead") or "")[:120])}</div></td>'
                f'<td><span class="tag {badge}">{_h(conf)}</span></td>'
                f'<td><span class="tag {safe_badge}">{_h(safe)}</span></td>'
                f'<td><span class="tag">{_h(c.get("bucket", ""))}</span></td>'
                f'<td class="dim" style="font-size:12px">{_h((t.get("reason") or "")[:160])}<br>'
                f'<span class="muted">Sources: {_h(sources_str)}</span></td></tr>'
            )

        captions_html = ""
        for c in cards[:3]:
            cap = c.get("captions") or {}
            captions_html += (
                f'<div style="margin-bottom:12px;padding:12px;background:rgba(255,255,255,0.02);border-radius:10px;border:1px solid var(--border)">'
                f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px">{_h(_humanise(c.get("card_type", "")))}</div>'
                f'<strong style="font-size:13px">{_h(c.get("headline", ""))}</strong>'
                f'<div class="dim" style="margin-top:4px;font-size:12px">{_h(c.get("subhead", ""))}</div>'
                f'<div class="grid-3" style="margin-top:10px;gap:10px">'
                f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Clean</div><div style="font-size:12px">{_h(cap.get("clean") or "—")}</div></div>'
                f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Team</div><div style="font-size:12px">{_h(cap.get("team") or "—")}</div></div>'
                f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Hype</div><div style="font-size:12px">{_h(cap.get("hype") or "—")}</div></div>'
                f'</div></div>'
            )

        # Warnings
        warn_html = ""
        if warnings:
            items = []
            for w in warnings[:10]:
                cls = {"info": "info", "warn": "warn", "error": "bad"}.get(w.get("severity"), "")
                items.append(f'<li><span class="tag {cls}">{_h(w.get("severity",""))}</span> '
                             f'<strong>{_h(w.get("code",""))}</strong> — {_h(w.get("message",""))}</li>')
            warn_html = ('<div class="card"><h2>Parse notes</h2>'
                         '<p class="dim">Anything inferred or ambiguous in the source file is shown here.</p>'
                         f'<ul>{"".join(items)}</ul></div>')

        # --- V6 PB Audit panel
        pb_audit_data = data.get('pb_audit') or {}
        pb_audit_html = ""
        if pb_audit_data:
            _audit_url = url_for('pb_audit_page', run_id=run_id)
            _n_swimmers = pb_audit_data.get('swimmers_total', 0)
            _n_verified = pb_audit_data.get('swimmers_matched_verified', 0)
            _n_needs = pb_audit_data.get('swimmers_needs_verification', 0)
            _n_fetch_fail = pb_audit_data.get('swimmers_fetch_failed', 0)
            _n_decisions = pb_audit_data.get('pb_decisions_count', 0)
            _n_confirmed = pb_audit_data.get('pb_confirmed_count', 0)
            _n_official = pb_audit_data.get('pb_confirmed_official_count', 0)
            _n_matched = pb_audit_data.get('pb_matched_count', 0)
            _n_likely = pb_audit_data.get('pb_likely_count', 0)
            _n_not_pb = pb_audit_data.get('pb_not_pb_count', 0)
            _n_unverified = pb_audit_data.get('pb_unverified_count', 0)
            _n_suppressed = pb_audit_data.get('pb_suppressed_count', 0)
            _fetch_secs = pb_audit_data.get('fetch_total_seconds', 0)
            _cache_hits = pb_audit_data.get('cache_hits', 0)
            _cache_misses = pb_audit_data.get('cache_misses', 0)
            _budget_exceeded = pb_audit_data.get('fetch_budget_exceeded', False)

            # Needs-verification swimmers list
            _needs_verif_html = ""
            _needs_verif_swimmers = [
                sa for sa in (pb_audit_data.get('per_swimmer') or [])
                if (sa.get('identity') or {}).get('method') == 'needs_verification'
            ]
            if _needs_verif_swimmers:
                rows = ""
                for sa in _needs_verif_swimmers[:10]:
                    _sw_key = _h(sa.get('asa_id') or f"name:{sa.get('hy3_name','')}")
                    _hy3 = _h(sa.get('hy3_name', ''))
                    _sr = _h(sa.get('sr_name') or '—')
                    _asa = _h(sa.get('asa_id') or '?')
                    _verify_url = url_for('pb_verify_form', run_id=run_id, swimmer_key=_sw_key)
                    rows += (
                        f'<div style="padding:8px 0;border-bottom:1px solid var(--border)">'
                        f'<a class="btn secondary" style="font-size:11px;padding:4px 8px;margin-right:8px" href="{_verify_url}">Verify</a>'
                        f'<strong>{_hy3}</strong> <span class="muted">(id {_asa})</span>'
                        f'<div class="muted" style="font-size:12px;margin-top:2px">SR returned: "{_sr}" → canonical mismatch</div>'
                        f'</div>'
                    )
                _needs_verif_html = (
                    f'<div class="divider"></div>'
                    f'<div><strong style="color:#F59E0B">⚠ {_n_needs} swimmer{"s" if _n_needs != 1 else ""} need verification:</strong>'
                    f'{rows}</div>'
                )

            _budget_note = ' <span class="tag warn">budget exceeded</span>' if _budget_exceeded else ''
            pb_audit_html = f"""
<div class="card">
  <h2>PB Audit</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Swimmers</div><div class="v">{_n_swimmers}</div></div>
    <div class="stat"><div class="l" style="color:#22D3EE">Verified</div><div class="v" style="color:#22D3EE">{_n_verified}</div></div>
    <div class="stat"><div class="l" style="color:#F59E0B">Needs verification</div><div class="v" style="color:#F59E0B">{_n_needs}</div></div>
    <div class="stat"><div class="l">Fetch failed</div><div class="v">{_n_fetch_fail}</div></div>
    <div class="stat"><div class="l">PB decisions</div><div class="v">{_n_decisions}</div></div>
    <div class="stat"><div class="l" style="color:#4ADE80">Confirmed PBs</div><div class="v" style="color:#4ADE80">{_n_confirmed}</div></div>
    <div class="stat" title="Time + date match SR all-time PB — strongest possible confirmation"><div class="l" style="color:#22D3EE">Official PBs</div><div class="v" style="color:#22D3EE">{_n_official}</div></div>
    <div class="stat"><div class="l">Likely PBs</div><div class="v">{_n_likely}</div></div>
    <div class="stat"><div class="l">Not PB</div><div class="v">{_n_not_pb}</div></div>
    <div class="stat"><div class="l">Unverified</div><div class="v">{_n_unverified}</div></div>
    <div class="stat"><div class="l">Suppressed</div><div class="v">{_n_suppressed}</div></div>
    <div class="stat"><div class="l">Fetch time</div><div class="v">{_fetch_secs:.1f}s{_budget_note}</div></div>
    <div class="stat"><div class="l">Cache hits/misses</div><div class="v">{_cache_hits}/{_cache_misses}</div></div>
  </div>
  {_needs_verif_html}
  <div class="divider"></div>
  <a class="btn secondary" href="{_audit_url}">Show all per-swimmer audits ▾</a>
</div>"""
        elif data.get('pb_fetch_ok') and data.get('pb_fetch_ok') > 0 and not data.get('pb_audit'):
            # Run did some PB fetching but produced no audit
            pb_audit_html = (
                '<div class="card"><p class="muted">'
                'PB fetching used legacy mode. Re-run to see the full audit.'
                '</p></div>'
            )

        # Sources panel
        all_sources = rr.get('all_sources') or []
        sources_rows = ""
        for s in all_sources[:20]:
            u = _h(s.get('url', ''))
            n = _h(s.get('name', s.get('url','')))
            uf = _h(s.get('used_for', ''))
            fa = _h((s.get('fetched_at') or '')[:16])
            sources_rows += f'<tr><td><a href="{u}" target="_blank" rel="noopener">{n}</a></td><td class="muted" style="font-size:12px">{uf}</td><td class="muted" style="font-size:12px">{fa}</td></tr>'

        if not sources_rows:
            sources_rows = '<tr><td colspan="3" class="muted">No external sources used (research unavailable or not yet run).</td></tr>'

        # Build filter dropdowns from unique values
        swimmers_set = sorted(set(ra.get('achievement',{}).get('swimmer_name','') for ra in ranked_achs if ra.get('achievement')))
        events_set = sorted(set(ra.get('achievement',{}).get('event','') for ra in ranked_achs if ra.get('achievement')))
        types_set = sorted(set(ra.get('achievement',{}).get('type','') for ra in ranked_achs if ra.get('achievement')))
        bands_set = ['elite','strong','story','nice','not_worthy']
        post_types_set = sorted(set(ra.get('suggested_post_type','') for ra in ranked_achs))

        def opts(items, label):
            o = f'<option value="">All {label}</option>'
            for item in items:
                o += f'<option value="{_h(item)}">{_h(item)}</option>'
            return o

        # --- V7: build workflow summary card and status pill helpers
        _wf_api_base_js = json.dumps(_wf_api_base)
        _wf_n_queue = _wf_summary.get("queue", 0)
        _wf_n_approved = _wf_summary.get("approved", 0)
        _wf_n_rejected = _wf_summary.get("rejected", 0)
        _wf_n_posted = _wf_summary.get("posted", 0)
        _wf_n_edited = _wf_summary.get("edited", 0)
        _wf_n_total = _wf_summary.get("total", 0)

        # Only show workflow card if there's any state or any achievements
        if _wf_summary or ranked_achs:
            _wf_filter_opts = ""
            _review_base = url_for("review", run_id=run_id)
            for _wf_opt in [("", "All"), ("queue", "Queue"), ("approved", "Approved"), ("posted", "Posted"), ("rejected", "Rejected")]:
                _wf_sel = "selected" if _wf_filter == _wf_opt[0] else ""
                _wf_opt_url = _review_base + (f"?wf={_wf_opt[0]}" if _wf_opt[0] else "")
                _wf_filter_opts += f'<option value="{_wf_opt_url}" {_wf_sel}>{_wf_opt[1]}</option>'
            # --- Turn-Into content pack card (top of content pack section) ---
            _ti_prior_html = ""
            if _ti_packs:
                rows = []
                for p in _ti_packs[:5]:
                    _pid = p.get("pack_id", "")
                    _gen = p.get("generated_at", "")
                    _n = p.get("n_artefacts", 0)
                    _skipped = p.get("n_skipped", 0)
                    try:
                        _view = url_for("turn_into_pack_view", run_id=run_id, pack_id=_pid)
                    except Exception:
                        _view = "#"
                    rows.append(
                        f'<li style="font-size:12px;margin-bottom:4px">'
                        f'<a href="{_view}">{_h(_gen)}</a> '
                        f'<span class="muted">— {_n} artefacts'
                        + (f", {_skipped} skipped" if _skipped else "")
                        + '</span></li>'
                    )
                _ti_prior_html = (
                    '<div style="margin-top:14px">'
                    '<div class="muted" style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">'
                    'Previously generated packs</div>'
                    f'<ul style="margin:0;padding-left:20px">{"".join(rows)}</ul>'
                    '</div>'
                )

            turn_into_card = f"""
<div class="card" id="turn-into-card" style="border-left:3px solid var(--accent)">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
    <div style="flex:1;min-width:240px">
      <h2 style="margin-bottom:6px">Content pack</h2>
      <p class="dim" style="margin:0;font-size:13px;max-width:540px">
        Turn this meet into a full pack of 7 derivative artefacts —
        recap, swimmer spotlights, X / LinkedIn thread, parent newsletter,
        sponsor thank-you, coach quote, and next-meet preview.
      </p>
    </div>
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <button id="ti-btn" class="btn" onclick="turnMeetIntoPack()" style="background:linear-gradient(135deg,#8B5CF6,#22D3EE);color:#fff;border:none">
        ✦ Turn meet into content pack
      </button>
      <a class="btn secondary" href="{_pack_url}" style="align-self:flex-end">View workflow pack →</a>
    </div>
  </div>
  <div id="ti-status" style="margin-top:10px;font-size:12px;color:var(--ink-muted);display:none"></div>
  {_ti_prior_html}
</div>
<script>
function turnMeetIntoPack() {{
  var btn = document.getElementById('ti-btn');
  var status = document.getElementById('ti-status');
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating…';
  status.style.display = '';
  status.textContent = 'Building 7 artefacts — this can take up to 60 seconds.';
  fetch({json.dumps(_turn_into_api)}, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{}}),
  }}).then(function(r) {{ return r.json(); }})
    .then(function(j) {{
      if (j && j.pack_url) {{
        status.textContent = 'Done — opening pack…';
        window.location.href = j.pack_url;
      }} else {{
        status.textContent = 'Failed: ' + (j && j.message ? j.message : 'unknown error');
        btn.disabled = false;
        btn.textContent = origText;
      }}
    }})
    .catch(function() {{
      status.textContent = 'Network error generating pack. Please retry.';
      btn.disabled = false;
      btn.textContent = origText;
    }});
}}
</script>"""

            workflow_summary_card = turn_into_card + f"""
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
    <div>
      <h2 style="margin-bottom:10px">Workflow</h2>
      <div class="stat-block">
        <div class="stat"><div class="l">Queue</div><div class="v">{_wf_n_queue or len(ranked_achs)}</div></div>
        <div class="stat"><div class="l" style="color:#22C55E">Approved</div><div class="v" style="color:#22C55E">{_wf_n_approved}</div></div>
        <div class="stat"><div class="l" style="color:#F43F5E">Rejected</div><div class="v" style="color:#F43F5E">{_wf_n_rejected}</div></div>
        <div class="stat"><div class="l" style="color:#22D3EE">Posted</div><div class="v" style="color:#22D3EE">{_wf_n_posted}</div></div>
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <a class="btn" href="{_pack_url}" style="align-self:flex-end">View content pack →</a>
    </div>
  </div>
  <div style="margin-top:14px;display:flex;align-items:center;gap:10px">
    <span class="muted" style="font-size:12px">Filter:</span>
    <select style="width:auto;font-size:13px;padding:6px 10px" onchange="location.href=this.value">
      {_wf_filter_opts}
    </select>
  </div>
</div>"""
        else:
            workflow_summary_card = ""

        # --- V7: add status pills to achievement rows
        # Rebuild ach_rows_html with workflow status pills
        ach_rows_html_wf = ""
        for ra in ranked_achs:
            a = ra.get("achievement", {})
            band = ra.get("quality_band", "nice")
            prio = ra.get("priority", 0.0)
            rank = ra.get("rank", 0)
            conf_label = a.get("confidence_label", "medium")
            conf_cls = {"high": "good", "medium": "warn", "low": "bad"}.get(conf_label, "")
            swimmer = _h(a.get("swimmer_name", ""))
            event = _h(a.get("event", ""))
            headline = _h(a.get("headline", ""))
            atype = _h(_humanise(a.get("type", "")))
            post_type = _h(ra.get("suggested_post_type", ""))
            prio_bar_pct = int(prio * 100)
            _trace_url = url_for("api_swim_trace", run_id=run_id, swim_id=a.get("swim_id","x"))

            # V7: workflow state for this card
            card_id_raw = a.get("swim_id", "")
            card_id_safe = _h(card_id_raw)
            wf_state = _wf_states.get(card_id_raw)
            wf_status = wf_state.status.value if wf_state else "queue"

            # Skip if filtered
            if _wf_filter and wf_status != _wf_filter:
                continue

            band_cls = {"elite": "warn", "strong": "info", "story": "", "nice": "", "not_worthy": "bad"}.get(band, "")

            status_colours = {
                "queue": ("rgba(255,255,255,0.06)", "var(--ink-muted)"),
                "approved": ("rgba(34,197,94,0.15)", "#22C55E"),
                "rejected": ("rgba(244,63,94,0.15)", "#F43F5E"),
                "posted": ("rgba(34,211,238,0.15)", "var(--accent)"),
                "edited": ("rgba(245,158,11,0.15)", "var(--warn)"),
            }
            s_bg, s_fg = status_colours.get(wf_status, status_colours["queue"])

            # Evidence list
            ev_html = ""
            for ev in (a.get("evidence") or [])[:3]:
                ev_url = ev.get("source_url") or ""
                ev_src = _h(ev.get("source_name", ""))
                ev_stmt = _h(ev.get("statement", ""))
                if ev_url:
                    ev_html += f'<li><a href="{_h(ev_url)}" target="_blank" rel="noopener">{ev_src}</a>: {ev_stmt}</li>'
                else:
                    ev_html += f'<li><strong>{ev_src}</strong>: {ev_stmt}</li>'

            # Factor list
            factors_html = ""
            for f in (ra.get("factors") or [])[:7]:
                fname = _h(f.get("name",""))
                fval = f.get("value", 0.0)
                freason = _h(f.get("reason",""))
                factors_html += f'<tr><td style="font-size:12px">{fname}</td><td style="font-size:12px">{fval:.3f}</td><td style="font-size:12px;color:var(--ink-muted)">{freason}</td></tr>'

            # V8: Live caption tone toggle.
            # All tabs (AI, Warm, Hype, Precise) generate captions live via the
            # LLM. No pre-filled template text — clicking a tone tab always
            # triggers a fresh, unique generation. Results are cached per session
            # client-side; "↺ Regenerate" forces a new fetch.
            tone_tabs_html = ""

            card_uuid = card_id_raw.replace(":", "_").replace(",", "_")
            swim_id_safe = _h(card_id_raw)
            _caption_url = url_for("api_live_caption", run_id=run_id, swim_id=card_id_raw)

            tabs_html = ""
            panels_html = ""

            # Standard tones — always shown, always AI-generated on demand.
            # Order: AI (first, active) → Warm → Hype → Precise
            _STD_TONES = [
                ("ai",        "✦ AI",    True,  "tone-tab-ai",
                 "rgba(139,92,246,0.15)", "#A78BFA",
                 "Live AI caption. Generates fresh each time."),
                ("warm-club", "Warm",    False, "",
                 "rgba(34,211,238,0.15)", "var(--accent)",
                 "Warm & community — friendly, first-name, inclusive."),
                ("hype",      "Hype",    False, "",
                 "rgba(34,211,238,0.15)", "var(--accent)",
                 "Energetic & hype — race-day language, high energy."),
                ("data-led",  "Precise", False, "",
                 "rgba(34,211,238,0.15)", "var(--accent)",
                 "Data-led — numbers first, sponsor-friendly, no fluff."),
            ]

            for t_key, t_label, is_active, extra_cls, active_bg, active_fg, title in _STD_TONES:
                init_bg = active_bg if is_active else "transparent"
                init_fg = active_fg if is_active else "var(--ink-dim)"
                active_attr = "active" if is_active else ""
                display = "" if is_active else "display:none"
                status_dot = (
                    '<span class="ai-status-dot" style="display:inline-block;width:7px;height:7px;'
                    'border-radius:50%;background:#ffae3b" aria-hidden="true"></span>'
                    if t_key == "ai" else ""
                )
                tabs_html += (
                    f'<button class="tone-tab {extra_cls} {active_attr}" '
                    f'data-card="{card_uuid}" data-tone="{t_key}" '
                    f'onclick="switchToneLive(this, {repr(_caption_url)}, {repr(card_uuid)})" '
                    f'title="{_h(title)}" '
                    f'style="font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--border);'
                    f'cursor:pointer;background:{init_bg};color:{init_fg};'
                    f'font-family:inherit;margin-right:4px;font-weight:{"600" if is_active else "400"};'
                    f'display:inline-flex;align-items:center;gap:5px">'
                    f'{status_dot}{_h(t_label)}</button>'
                )
                panels_html += (
                    f'<div class="tone-panel" data-tone="{t_key}" data-card="{card_uuid}" style="{display}">'
                    f'<div class="caption-text" style="font-size:12px;color:var(--ink);white-space:pre-wrap">'
                    f'<span class="caption-placeholder" style="color:var(--ink-muted);font-style:italic">'
                    f'Click to generate…</span></div>'
                    f'<textarea class="caption-textarea" style="display:none"></textarea>'
                    f'</div>'
                )

            # V8: Create-graphic API URL (lazy visual generation)
            _create_graphic_url = url_for("api_create_graphic", run_id=run_id, card_id=card_id_raw)
            _motion_url = url_for("api_card_motion", run_id=run_id, card_id=card_id_raw)
            tone_tabs_html = (
                f'<div class="tone-picker" data-caption-url="{_h(_caption_url)}" data-card="{card_uuid}" style="margin-top:10px;padding:12px;background:rgba(34,211,238,0.04);border:1px solid var(--border);border-radius:8px">'
                f'<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px;letter-spacing:0.5px">Caption tone</div>'
                f'<div style="margin-bottom:8px">{tabs_html}</div>'
                f'<div class="tone-panels" data-card="{card_uuid}">{panels_html}</div>'
                f'<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
                f'<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="copyActiveTone(this, \'{card_uuid}\')">Copy caption</button>'
                f'<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="regenerateCaption(this, {repr(_caption_url)}, \'{card_uuid}\')">↺ Regenerate caption</button>'
                f'<button class="btn" style="font-size:11px;padding:4px 10px;background:linear-gradient(135deg,#8B5CF6,#22D3EE);color:#fff;border:none" onclick="createGraphic(this, {repr(_create_graphic_url)}, \'{card_uuid}\')">✦ Create graphic</button>'
                f'<button class="btn" style="font-size:11px;padding:4px 10px;background:linear-gradient(135deg,#F97316,#EF4444);color:#fff;border:none" onclick="generateMotion(this, {repr(_motion_url)}, \'{card_uuid}\')">▶ Generate motion</button>'
                f'<span class="caption-timestamp" style="font-size:10px;color:var(--ink-muted)"></span>'
                f'</div>'
                f'<div class="visual-panel" data-card="{card_uuid}" data-create-url="{_h(_create_graphic_url)}" style="display:none;margin-top:10px;padding:12px;background:rgba(139,92,246,0.04);border:1px solid var(--border);border-radius:8px"></div>'
                f'<div class="motion-panel" data-card="{card_uuid}" data-motion-url="{_h(_motion_url)}" style="display:none;margin-top:10px;padding:12px;background:rgba(249,115,22,0.04);border:1px solid var(--border);border-radius:8px"></div>'
                f'</div>'
            )
            brand_cap_html = tone_tabs_html

            _wf_api_url = url_for("api_workflow_set", run_id=run_id, card_id=card_id_raw)

            ach_rows_html_wf += f"""
<div class="ach-row" data-type="{a.get("type","")}" data-conf="{conf_label}" data-swimmer="{a.get("swimmer_name","")}" data-event="{a.get("event","")}" data-band="{band}" data-post="{ra.get("suggested_post_type","")}" data-status="{wf_status}">
  <div style="display:flex;align-items:flex-start;gap:14px;padding:14px 0;border-bottom:1px solid var(--border)">
    <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px;padding-top:2px">#{rank}</div>
    <div style="flex:1">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="tag {band_cls}" style="font-size:10px">{band.upper()}</span>
        <span class="tag info" style="font-size:10px">{atype}</span>
        <span class="tag {conf_cls}" style="font-size:10px">conf: {conf_label}</span>
        <span class="tag" style="font-size:10px">{post_type}</span>
        <div style="flex:1;min-width:80px;max-width:160px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:{prio_bar_pct}%;background:var(--accent)"></div>
        </div>
        <span class="muted" style="font-size:11px">{prio:.2f}</span>
        <!-- V7: Status pill -->
        <button class="wf-pill" data-run="{_h(run_id)}" data-card="{card_id_safe}" data-status="{wf_status}"
          style="border:none;cursor:pointer;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;background:{s_bg};color:{s_fg};font-family:inherit;transition:opacity 150ms"
          title="Click: queue → approved → posted. Right-click for more options.">{wf_status}</button>
      </div>
      <div style="font-size:13px;font-weight:600;margin-bottom:2px">{swimmer} · {event}</div>
      <div style="font-size:13px;color:var(--ink-dim)">{headline}</div>
      {brand_cap_html}
      <details style="margin-top:8px">
        <summary style="cursor:pointer;font-size:12px;color:var(--accent);user-select:none">Edit caption · view factors &amp; evidence</summary>
        <div style="margin-top:8px;font-size:12px">
          <div style="padding:12px;background:rgba(34,211,238,0.04);border:1px solid var(--border);border-radius:8px;margin-bottom:14px">
            <strong style="font-size:13px">Caption editor</strong>
            <span class="muted" style="font-size:11px;margin-left:6px">(warm-club tone — leave blank to use the default)</span>
            <div style="margin-top:10px">
              <label style="font-size:11px;margin-bottom:4px;display:block">Headline</label>
              <textarea class="cap-edit" data-key="warm-club_headline" style="min-height:48px;font-size:12px" placeholder="Override the headline…"></textarea>
              <label style="font-size:11px;margin-bottom:4px;display:block;margin-top:8px">Body</label>
              <textarea class="cap-edit" data-key="warm-club_body" style="min-height:64px;font-size:12px" placeholder="Override the body text…"></textarea>
            </div>
            <button class="btn" style="font-size:12px;padding:6px 14px;margin-top:10px"
              onclick="saveCaption(this, '{_h(run_id)}', '{card_id_safe}')">Save caption edits</button>
          </div>
          <details style="margin-top:6px">
            <summary style="cursor:pointer;font-size:12px;color:var(--ink-dim);user-select:none">Show ranking factors &amp; evidence</summary>
            <div style="margin-top:8px">
              <div style="margin-bottom:6px"><strong>Ranking factors:</strong></div>
              <table style="font-size:12px;margin-bottom:10px"><thead><tr><th>Factor</th><th>Value</th><th>Reason</th></tr></thead><tbody>{factors_html}</tbody></table>
              <div style="margin-bottom:4px"><strong>Evidence:</strong></div>
              <ul style="margin:0;padding-left:18px">{ev_html or '<li class="muted">No evidence items</li>'}</ul>
              <div style="margin-top:8px"><a href="{_trace_url}" target="_blank" rel="noopener" style="font-size:12px">View full trace JSON →</a></div>
            </div>
          </details>
        </div>
      </details>
    </div>
  </div>
</div>"""

        if not ach_rows_html_wf:
            if _wf_filter:
                ach_rows_html_wf = f'<div class="empty">No cards with status "{_h(_wf_filter)}".</div>'
            elif recognition_error:
                ach_rows_html_wf = f'<div class="empty">Recognition engine error: {_h(recognition_error)}</div>'
            elif not rr:
                ach_rows_html_wf = '<div class="empty">No recognition report available. Re-upload the file to generate achievements.</div>'
            else:
                ach_rows_html_wf = '<div class="empty">No achievements detected.</div>'

        body = f"""
<style>
.ach-row {{ transition: background 100ms; }}
.ach-row:hover {{ background: rgba(255,255,255,0.015); }}
.filters-bar {{ display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;padding:14px 16px;background:var(--panel2);border:1px solid var(--border);border-radius:var(--radius-sm);position:sticky;top:56px;z-index:50; }}
.filters-bar select {{ width:auto;min-width:120px;font-size:13px;padding:6px 10px; }}
.ach-row.hidden {{ display:none; }}
@keyframes spin {{ from {{ transform:rotate(0deg) }} to {{ transform:rotate(360deg) }} }}
</style>

<h1>{_h(meet.get('name', '(unknown meet)'))}</h1>
<p class="dim">
  {_h(data.get('profile_display',''))} ·
  {_h(meet.get('start_date','?'))} – {_h(meet.get('end_date','?'))} ·
  {_h(meet.get('course',''))} ·
  {_h(meet.get('venue') or 'venue unknown')} ·
  source: {_h(dispatch_log.get('chosen_filename') or data.get('file_name',''))}
  ({_h(dispatch_log.get('chosen_adapter','?'))})
</p>

<div class="card">
  <h2>Recognition summary</h2>
  <div class="stat-block">{rec_stats_html}</div>
  <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
    <a class="btn secondary" href="{_export_url}">Download export</a>
    <form method="post" action="{_delete_url}" style="display:inline" onsubmit="return confirm('Delete this run permanently?')">
      <button class="btn danger" type="submit">Delete run</button>
    </form>
  </div>
  <details style="margin-top:12px">
    <summary style="font-size:12px;color:var(--ink-muted);cursor:pointer">Developer tools</summary>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
      <a class="btn secondary" href="{_rec_json_url}" target="_blank" rel="noopener" style="font-size:12px">Download recognition JSON</a>
      <a class="btn secondary" href="{_gt_url}" style="font-size:12px">Run ground-truth check</a>
    </div>
  </details>
</div>

{workflow_summary_card}

{meet_ctx_html}

{pb_audit_html}

{warn_html}

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:8px">
    <h2 style="margin:0">Top achievements</h2>
    <button class="btn" style="font-size:12px;padding:6px 14px;background:linear-gradient(135deg,#F97316,#EF4444);color:#fff;border:none"
            onclick="generateReel(this, {repr(_reel_url)})">▶ Generate reel from this meet</button>
  </div>
  <div id="reel-panel" style="display:none;margin-bottom:14px;padding:14px;background:rgba(249,115,22,0.04);border:1px solid var(--border);border-radius:8px"></div>
  <div class="filters-bar">
    <select id="f-type" onchange="applyFilters()">{opts(types_set, 'types')}</select>
    <select id="f-conf" onchange="applyFilters()"><option value="">All confidence</option><option>high</option><option>medium</option><option>low</option></select>
    <select id="f-swimmer" onchange="applyFilters()">{opts(swimmers_set, 'swimmers')}</select>
    <select id="f-event" onchange="applyFilters()">{opts(events_set, 'events')}</select>
    <select id="f-band" onchange="applyFilters()">{opts(bands_set, 'bands')}</select>
    <select id="f-post" onchange="applyFilters()">{opts(post_types_set, 'post types')}</select>
    <button class="btn secondary" style="font-size:13px;padding:6px 12px" onclick="clearFilters()">Clear</button>
    <span id="f-count" class="muted" style="font-size:12px;align-self:center"></span>
  </div>
  <div id="ach-list">{ach_rows_html_wf}</div>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Legacy content cards <span class="muted" style="font-weight:400;font-size:13px">— {len(cards)} cards</span></summary>
    <div style="margin-top:14px">
      <table>
        <thead><tr><th>Card</th><th>Confidence</th><th>Safe to post</th><th>Bucket</th><th>Why</th></tr></thead>
        <tbody>{"".join(v4_rows) or '<tr><td colspan="5" class="muted">No cards generated.</td></tr>'}</tbody>
      </table>
      <div style="margin-top:14px">{captions_html or '<p class="muted">No captions.</p>'}</div>
    </div>
  </details>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Not generated <span class="muted" style="font-weight:400;font-size:13px">— {len(no_ach_traces)} swims with no achievements</span></summary>
    <div style="margin-top:14px">
      <table>
        <thead><tr><th>Swimmer</th><th>Event</th><th>Time</th><th>Why not generated</th></tr></thead>
        <tbody>{not_gen_rows or '<tr><td colspan="4" class="muted">All swims produced achievements, or no trace data available.</td></tr>'}</tbody>
      </table>
    </div>
  </details>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Sources used <span class="muted" style="font-weight:400;font-size:13px">— {len(all_sources)} source(s)</span></summary>
    <div style="margin-top:14px">
      <table>
        <thead><tr><th>Source</th><th>Used for</th><th>Fetched</th></tr></thead>
        <tbody>{sources_rows}</tbody>
      </table>
    </div>
  </details>
</div>

<script>
function applyFilters() {{
  var fType = document.getElementById('f-type').value;
  var fConf = document.getElementById('f-conf').value;
  var fSwimmer = document.getElementById('f-swimmer').value;
  var fEvent = document.getElementById('f-event').value;
  var fBand = document.getElementById('f-band').value;
  var fPost = document.getElementById('f-post').value;
  var rows = document.querySelectorAll('#ach-list .ach-row');
  var shown = 0;
  rows.forEach(function(row) {{
    var match = true;
    if (fType && row.dataset.type !== fType) match = false;
    if (fConf && row.dataset.conf !== fConf) match = false;
    if (fSwimmer && row.dataset.swimmer !== fSwimmer) match = false;
    if (fEvent && row.dataset.event !== fEvent) match = false;
    if (fBand && row.dataset.band !== fBand) match = false;
    if (fPost && row.dataset.post !== fPost) match = false;
    row.classList.toggle('hidden', !match);
    if (match) shown++;
  }});
  var countEl = document.getElementById('f-count');
  if (countEl) countEl.textContent = shown + ' of ' + rows.length + ' shown';
}}
function clearFilters() {{
  ['f-type','f-conf','f-swimmer','f-event','f-band','f-post'].forEach(function(id) {{
    var el = document.getElementById(id);
    if (el) el.value = '';
  }});
  applyFilters();
}}
applyFilters();

// V7: Workflow pill cycling
// Click-cycle skips rejected/edited (uncommon paths). Right-click cycles back.
const WF_CYCLE = ['queue','approved','posted'];
const WF_COLOURS = {{
  queue:    ['rgba(255,255,255,0.06)','var(--ink-muted)'],
  approved: ['rgba(34,197,94,0.15)','#22C55E'],
  rejected: ['rgba(244,63,94,0.15)','#F43F5E'],
  posted:   ['rgba(34,211,238,0.15)','var(--accent)'],
  edited:   ['rgba(245,158,11,0.15)','var(--warn)'],
}};
const WF_API_BASE = {_wf_api_base_js};
function _wfApply(btn, next) {{
  var cur = btn.dataset.status || 'queue';
  var cardId = btn.dataset.card;
  btn.textContent = next;
  btn.dataset.status = next;
  var cols = WF_COLOURS[next] || WF_COLOURS.queue;
  btn.style.background = cols[0];
  btn.style.color = cols[1];
  var row = btn.closest('.ach-row');
  if (row) row.dataset.status = next;
  var url = WF_API_BASE + encodeURIComponent(cardId);
  fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:'set_status',status:next}})}})
    .then(r=>r.json())
    .then(j=>{{ if(!j.ok){{btn.textContent=cur;btn.dataset.status=cur;}} }})
    .catch(()=>{{btn.textContent=cur;btn.dataset.status=cur;}});
}}

document.addEventListener('click', function(e) {{
  var btn = e.target.closest('.wf-pill');
  if (!btn) return;
  var cur = btn.dataset.status || 'queue';
  // If currently rejected/edited (not in cycle), restart at approved
  var idx = WF_CYCLE.indexOf(cur);
  var next = idx === -1 ? 'approved' : WF_CYCLE[(idx + 1) % WF_CYCLE.length];
  _wfApply(btn, next);
}});

// Right-click cycles: queue → rejected (rare path)
document.addEventListener('contextmenu', function(e) {{
  var btn = e.target.closest('.wf-pill');
  if (!btn) return;
  e.preventDefault();
  var cur = btn.dataset.status || 'queue';
  var next = cur === 'rejected' ? 'queue' : 'rejected';
  _wfApply(btn, next);
}});


// V8: Live caption tone toggle + regenerate
// switchTone() kept for backwards compat (content pack, other pages).
function switchTone(btn) {{
  var cardId = btn.dataset.card;
  var newTone = btn.dataset.tone;
  document.querySelectorAll('.tone-tab[data-card="' + cardId + '"]').forEach(function(tab) {{
    var isActive = tab.dataset.tone === newTone;
    tab.classList.toggle('active', isActive);
    if (isActive) {{
      tab.style.background = tab.classList.contains('tone-tab-ai') ? 'rgba(139,92,246,0.15)' : 'rgba(34,211,238,0.15)';
      tab.style.color = tab.classList.contains('tone-tab-ai') ? '#A78BFA' : 'var(--accent)';
    }} else {{
      tab.style.background = 'transparent';
      tab.style.color = 'var(--ink-dim)';
    }}
  }});
  document.querySelectorAll('.tone-panel[data-card="' + cardId + '"]').forEach(function(panel) {{
    panel.style.display = panel.dataset.tone === newTone ? '' : 'none';
  }});
}}

// V8: switchToneLive — fetches caption from API on click.
// AI tab: always fetches fresh. Warm/Hype/Precise tabs: cached for the session.
// "↺ Regenerate" always forces a fresh fetch via regenerateCaption().
var _captionCache = {{}};
var _AI_TONE_KEYS = {{'ai': true}};  // other tones are cached after first gen

function switchToneLive(btn, captionUrl, cardId) {{
  var newTone = btn.dataset.tone;
  var isAiTone = !!_AI_TONE_KEYS[newTone];

  // Update tab styles
  document.querySelectorAll('.tone-tab[data-card="' + cardId + '"]').forEach(function(tab) {{
    var isActive = tab.dataset.tone === newTone;
    tab.classList.toggle('active', isActive);
    if (isActive) {{
      tab.style.background = tab.classList.contains('tone-tab-ai') ? 'rgba(139,92,246,0.15)' : 'rgba(34,211,238,0.15)';
      tab.style.color = tab.classList.contains('tone-tab-ai') ? '#A78BFA' : 'var(--accent)';
      tab.style.fontWeight = '600';
    }} else {{
      tab.style.background = 'transparent';
      tab.style.color = 'var(--ink-dim)';
      tab.style.fontWeight = '400';
    }}
  }});

  // Show active panel, hide others
  document.querySelectorAll('.tone-panel[data-card="' + cardId + '"]').forEach(function(panel) {{
    panel.style.display = panel.dataset.tone === newTone ? '' : 'none';
  }});

  var panel = document.querySelector('.tone-panel[data-tone="' + newTone + '"][data-card="' + cardId + '"]');
  if (!panel) {{ return; }}

  var cacheKey = cardId + '|' + newTone;

  // AI tab: always fetch fresh — never use cache.
  // Named tones (warm/hype/precise): use session cache after first generation.
  if (!isAiTone && _captionCache[cacheKey]) {{
    _renderCaption(panel, _captionCache[cacheKey]);
    return;
  }}

  // All panels start with a placeholder — fetch if placeholder still present
  // (or if AI tone, always fetch).
  var placeholder = panel.querySelector('.caption-placeholder');
  if (!isAiTone && !placeholder) {{
    return;  // already generated; cache hit handled above
  }}

  _fetchCaption(captionUrl, newTone, panel, cacheKey, isAiTone, cardId);
}}

function _fetchCaption(captionUrl, tone, panel, cacheKey, isAi, cardId) {{
  var captionDiv = panel.querySelector('.caption-text');
  var textarea = panel.querySelector('.caption-textarea');
  if (captionDiv) {{
    captionDiv.innerHTML = '<span style="color:var(--ink-muted);font-style:italic">Generating…<span class="spin" style="display:inline-block;margin-left:6px;animation:spin 0.8s linear infinite">⟳</span></span>';
  }}
  fetch(captionUrl + '?tone=' + encodeURIComponent(tone), {{method: 'POST'}})
    .then(function(r) {{ return r.json(); }})
    .then(function(j) {{
      var text = j.caption || '';
      var ts = j.generated_at ? new Date(j.generated_at).toLocaleTimeString() : '';
      var fallbackNote = '';
      // No-key or LLM unavailable state — prompt to add a key.
      if (j.live === false) {{
        var settingsHref = j.settings_url || ((window._API_BASE || '') + '/settings');
        if (captionDiv) {{
          captionDiv.innerHTML = '<div style="padding:10px;border:1px dashed var(--border);border-radius:6px;background:rgba(255,174,59,0.06);color:var(--ink-muted)">'
            + '<div style="font-weight:600;color:var(--ink);margin-bottom:4px">✦ AI captions need an API key</div>'
            + '<div style="font-size:11px;line-height:1.5">' + (j.message || 'Add a Gemini API key (free at aistudio.google.com) or Anthropic key in Settings.') + '</div>'
            + '<div style="margin-top:8px"><a href="' + settingsHref + '" style="color:var(--accent);font-size:11px;text-decoration:underline">Open Settings →</a></div>'
            + '</div>';
        }}
        document.querySelectorAll('.ai-status-dot').forEach(function(d){{ d.style.background='#ff5d6c'; }});
        return;
      }}
      if (j.fallback && j.fallback_voice) {{
        fallbackNote = '<div style="margin-top:4px;font-size:10px;color:var(--warn);padding:4px 8px;background:rgba(245,158,11,0.08);border-radius:4px">⚠ AI generation unavailable, using ' + j.fallback_voice + '</div>';
      }}
      if (captionDiv) {{
        captionDiv.innerHTML = '<span style="white-space:pre-wrap">' + text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>' + fallbackNote;
      }}
      if (textarea) {{
        textarea.value = text;
      }}
      // Update timestamp
      var picker = panel.closest('.tone-picker');
      if (picker) {{
        var tsEl = picker.querySelector('.caption-timestamp');
        if (tsEl && ts) tsEl.textContent = 'regenerated just now · ' + ts;
      }}
      // Cache named-tone results for this session (not the AI tab — always fresh)
      if (!isAi) {{ _captionCache[cacheKey] = {{text: text}}; }}
    }})
    .catch(function(err) {{
      if (captionDiv) {{
        captionDiv.innerHTML = '<span style="color:var(--ink-muted);font-style:italic">Error generating caption. Please try again.</span>';
      }}
    }});
}}

function _renderCaption(panel, cached) {{
  var captionDiv = panel.querySelector('.caption-text');
  var textarea = panel.querySelector('.caption-textarea');
  if (captionDiv && cached.text) {{
    captionDiv.innerHTML = '<span style="white-space:pre-wrap">' + cached.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
  }}
  if (textarea && cached.text) {{
    textarea.value = cached.text;
  }}
}}

function regenerateCaption(btn, captionUrl, cardId) {{
  // Find the active panel and force a fresh re-fetch (clears session cache).
  var activeToneTab = document.querySelector('.tone-tab.active[data-card="' + cardId + '"]');
  if (!activeToneTab) {{ return; }}
  var tone = activeToneTab.dataset.tone;
  var cacheKey = cardId + '|' + tone;
  delete _captionCache[cacheKey];  // force fresh generation
  var panel = document.querySelector('.tone-panel[data-tone="' + tone + '"][data-card="' + cardId + '"]');
  if (!panel) {{ return; }}
  var isAiTone = !!_AI_TONE_KEYS[tone];
  _fetchCaption(captionUrl, tone, panel, cacheKey, isAiTone, cardId);
}}

function copyActiveTone(btn, cardId) {{
  // Find the active tone panel
  var activePanel = document.querySelector('.tone-panel[data-card="' + cardId + '"]:not([style*="none"])');
  if (!activePanel) {{
    activePanel = document.querySelector('.tone-panel[data-card="' + cardId + '"]');
  }}
  if (!activePanel) {{ return; }}
  // Get text from caption-textarea or caption-text
  var ta = activePanel.querySelector('.caption-textarea');
  var textEl = activePanel.querySelector('.caption-text');
  var text = (ta && ta.value) ? ta.value : (textEl ? textEl.textContent : '');
  // Also check old-style tone-text-ID elements
  if (!text) {{
    var activeTone = activePanel.dataset.tone;
    var oldTa = document.getElementById('tone-text-' + cardId + '-' + activeTone);
    if (oldTa) text = oldTa.value;
  }}
  if (!text) {{ return; }}
  navigator.clipboard.writeText(text).then(function() {{
    var orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }}).catch(function() {{
    var tempTa = document.createElement('textarea');
    tempTa.value = text;
    document.body.appendChild(tempTa);
    tempTa.select();
    document.execCommand('copy');
    document.body.removeChild(tempTa);
    var orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }});
}}

// V7: Caption save
function saveCaption(btn, runId, cardId) {{
  var container = btn.closest('div');
  var edits = {{}};
  container.querySelectorAll('.cap-edit').forEach(function(ta) {{
    if(ta.value.trim()) edits[ta.dataset.key] = ta.value.trim();
  }});
  if(!Object.keys(edits).length) return;
  var url = WF_API_BASE + encodeURIComponent(cardId);
  btn.textContent = 'Saving…';
  fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:'set_edits',edits:edits}})}})
    .then(r=>r.json())
    .then(j=>{{
      btn.textContent = j.ok ? 'Saved!' : 'Error';
      // Reflect auto-bumped 'edited' status on the row's pill if backend set it
      if (j.ok && j.status) {{
        var row = btn.closest('.ach-row');
        if (row) {{
          var pill = row.querySelector('.wf-pill');
          if (pill && pill.dataset.status === 'queue') {{
            pill.textContent = j.status;
            pill.dataset.status = j.status;
            row.dataset.status = j.status;
            var cols = WF_COLOURS[j.status] || WF_COLOURS.queue;
            pill.style.background = cols[0];
            pill.style.color = cols[1];
          }}
        }}
      }}
      setTimeout(function(){{ btn.textContent = 'Save caption edits'; }}, 1800);
    }})
    .catch(()=>{{ btn.textContent = 'Error'; }});
}}

// V8: Lazy visual generation. Cached per (card, format) within session.
var _visualCache = {{}};
function createGraphic(btn, createUrl, cardId, fmt) {{
  fmt = fmt || 'feed_portrait';
  var panel = document.querySelector('.visual-panel[data-card="' + cardId + '"]');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating…';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(139,92,246,0.3);border-top-color:#8B5CF6;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Generating graphic… this may take 5-15 seconds</div>';
  var cacheKey = cardId + '|' + fmt;
  if (_visualCache[cacheKey]) {{
    _renderVisualPanel(panel, _visualCache[cacheKey], cardId, createUrl);
    btn.disabled = false; btn.textContent = origLabel;
    return;
  }}
  fetch(createUrl, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{format: fmt}})}})
    .then(function(r) {{ return r.json().then(function(j){{ return {{ok: r.ok, body: j}}; }}); }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok || res.body.error) {{
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Error: ' + (res.body.error || 'render failed') + '</div>';
        return;
      }}
      _visualCache[cacheKey] = res.body;
      _renderVisualPanel(panel, res.body, cardId, createUrl);
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

// Escape a JS expression so it can safely live inside an HTML onclick="..." attribute.
// JSON.stringify produces a string with literal double quotes; those would close the HTML
// attribute prematurely. We replace inner " with the &quot; entity (the browser decodes
// them back to " before passing to the JS engine).
function _attrEsc(jsExpr) {{
  return '"' + jsExpr.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"';
}}

function _renderVisualPanel(panel, data, cardId, createUrl) {{
  var visuals = data.visuals || [];
  if (!visuals.length) {{
    panel.innerHTML = '<div style="padding:14px;color:var(--ink-muted);font-size:13px">No visuals generated. ' + ((data.errors && data.errors.length) ? 'Errors: ' + data.errors.join('; ') : '') + '</div>';
    return;
  }}
  var v = visuals[0];
  // Use absolute path that respects the deployed /port/5000 prefix; the backend prepends location.pathname's base via window._API_BASE.
  var apiBase = (window._API_BASE || '');
  var imgUrl = apiBase + '/api/visual/' + encodeURIComponent(v.id) + '/png/' + encodeURIComponent(v.format_name || 'feed_portrait');
  var why = (data.brief && data.brief.why_this_design) || v.why_this_design || '';
  var layout = v.layout_template || (data.brief && data.brief.layout_template) || '';
  var formats = ['feed_portrait', 'feed_square', 'story_vertical'];
  var formatLabels = {{'feed_portrait':'Portrait', 'feed_square':'Square', 'story_vertical':'Story'}};
  var tabsHtml = formats.map(function(f) {{
    var active = (f === (v.format_name || 'feed_portrait'));
    return '<button class="vfmt-tab" data-fmt="' + f + '" onclick=' + _attrEsc('createGraphic(this, ' + JSON.stringify(createUrl) + ', ' + JSON.stringify(cardId) + ', ' + JSON.stringify(f) + ')') + ' style="font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--border);cursor:pointer;background:' + (active ? 'rgba(139,92,246,0.15)' : 'transparent') + ';color:' + (active ? '#A78BFA' : 'var(--ink-dim)') + ';font-family:inherit;margin-right:4px">' + formatLabels[f] + '</button>';
  }}).join('');
  panel.innerHTML =
    '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
      '<div style="flex:0 0 220px;max-width:240px">' +
        '<img src="' + imgUrl + '" alt="Generated graphic" style="width:100%;border-radius:6px;border:1px solid var(--border);background:#0a0a0a" />' +
      '</div>' +
      '<div style="flex:1;min-width:200px">' +
        '<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:4px">Generated visual · ' + (layout || 'auto') + '</div>' +
        (why ? '<div style="font-size:12px;color:var(--ink);margin-bottom:8px;line-height:1.4">' + why + '</div>' : '') +
        '<div style="margin-bottom:8px">' + tabsHtml + '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
          '<a class="btn secondary" href="' + imgUrl + '" download style="font-size:11px;padding:4px 10px">Download PNG</a>' +
          '<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick=' + _attrEsc('regenerateGraphic(this, ' + JSON.stringify(createUrl) + ', ' + JSON.stringify(cardId) + ')') + '>↺ Regenerate (3 variants)</button>' +
          '<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick=' + _attrEsc('addGraphicToPack(this, ' + JSON.stringify(v.id) + ')') + '>+ Add to pack</button>' +
        '</div>' +
      '</div>' +
    '</div>';
}}

// Motion-graphic generation: lazy, cached server-side. Streams the resulting
// MP4 into an inline <video> on the card panel.
var _motionCache = {{}};
function generateMotion(btn, motionUrl, cardId) {{
  var panel = document.querySelector('.motion-panel[data-card="' + cardId + '"]');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering motion…';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(249,115,22,0.3);border-top-color:#F97316;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Rendering motion graphic… cached renders return in ~5s, cold renders up to 90s.</div>';
  fetch(motionUrl, {{method:'POST'}})
    .then(function(r) {{
      if (r.ok && r.headers.get('content-type') && r.headers.get('content-type').indexOf('video') !== -1) {{
        return r.blob().then(function(b) {{ return {{ok:true, blob:b}}; }});
      }}
      return r.json().then(function(j){{ return {{ok:false, body:j}}; }});
    }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok) {{
        var msg = (res.body && (res.body.detail || res.body.error)) || 'render failed';
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Motion render error: ' + msg + '</div>';
        return;
      }}
      var url = URL.createObjectURL(res.blob);
      _motionCache[cardId] = url;
      panel.innerHTML =
        '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
          '<div style="flex:0 0 200px;max-width:220px">' +
            '<video src="' + url + '" controls playsinline style="width:100%;border-radius:6px;border:1px solid var(--border);background:#000"></video>' +
          '</div>' +
          '<div style="flex:1;min-width:200px">' +
            '<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:4px">Motion · 1080×1920 · 6s</div>' +
            '<div style="font-size:12px;color:var(--ink);margin-bottom:8px;line-height:1.4">Branded story-format MP4 rendered via Remotion. Same brand colours, palette, and seed as the static card.</div>' +
            '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
              '<a class="btn secondary" href="' + url + '" download="motion-' + cardId + '.mp4" style="font-size:11px;padding:4px 10px">Download MP4</a>' +
            '</div>' +
          '</div>' +
        '</div>';
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

// Meet-reel generation: top-3 cards stitched into a 15-second reel.
function generateReel(btn, reelUrl) {{
  var panel = document.getElementById('reel-panel');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering reel…';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(249,115,22,0.3);border-top-color:#F97316;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Producing 15-second reel from the top 3 cards… cold renders may take up to 90s.</div>';
  fetch(reelUrl, {{method:'POST'}})
    .then(function(r) {{
      if (r.ok && r.headers.get('content-type') && r.headers.get('content-type').indexOf('video') !== -1) {{
        return r.blob().then(function(b) {{ return {{ok:true, blob:b}}; }});
      }}
      return r.json().then(function(j){{ return {{ok:false, body:j}}; }});
    }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok) {{
        var msg = (res.body && (res.body.detail || res.body.error)) || 'render failed';
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Reel render error: ' + msg + '</div>';
        return;
      }}
      var url = URL.createObjectURL(res.blob);
      panel.innerHTML =
        '<div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">' +
          '<div style="flex:0 0 240px;max-width:260px">' +
            '<video src="' + url + '" controls playsinline style="width:100%;border-radius:6px;border:1px solid var(--border);background:#000"></video>' +
          '</div>' +
          '<div style="flex:1;min-width:240px">' +
            '<div style="font-size:11px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:4px">Meet reel · 1080×1920 · 15s</div>' +
            '<div style="font-size:13px;color:var(--ink);margin-bottom:10px;line-height:1.4">Top-3 ranked moments stitched into a branded reel with smooth crossfades, club colours, and the meet headline.</div>' +
            '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
              '<a class="btn secondary" href="' + url + '" download="meet-reel.mp4" style="font-size:12px;padding:4px 12px">Download MP4</a>' +
            '</div>' +
          '</div>' +
        '</div>';
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

function regenerateGraphic(btn, createUrl, cardId) {{
  // V8.1 issue 4: replace single-output regenerate with a 3-variant picker.
  var panel = document.querySelector('.visual-panel[data-card="' + cardId + '"]');
  if (!panel) return;
  panel.style.display = '';
  // Derive the variants endpoint from the create-graphic URL.
  var variantsUrl = createUrl.replace(/\/create-graphic$/, '/regenerate-variants');
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating 3 options…';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(139,92,246,0.3);border-top-color:#8B5CF6;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Producing 3 alternative designs in parallel… 10-30 seconds.</div>';
  fetch(variantsUrl, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:'{{}}'}})
    .then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok, body:j}}; }}); }})
    .then(function(res){{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok || res.body.error) {{
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Error: ' + (res.body.error || 'variants failed') + '</div>';
        return;
      }}
      _renderVariantPicker(panel, res.body.variants || [], cardId, createUrl);
    }})
    .catch(function(err){{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

function _renderVariantPicker(panel, variants, cardId, createUrl) {{
  if (!variants.length) {{
    panel.innerHTML = '<div style="padding:14px;color:var(--ink-muted);font-size:13px">No variants returned.</div>';
    return;
  }}
  var apiBase = (window._API_BASE || '');
  var tilesHtml = variants.map(function(vt) {{
    var v = vt.visual;
    if (!v) {{
      return '<div style="flex:1;min-width:160px;padding:14px;border:1px dashed var(--border);border-radius:8px;text-align:center;color:#F87171;font-size:12px">Variant ' + vt.seed + ' failed: ' + ((vt.errors||[]).join("; ") || 'unknown') + '</div>';
    }}
    var imgUrl = apiBase + '/api/visual/' + encodeURIComponent(v.id) + '/png/' + encodeURIComponent(v.format_name || 'feed_portrait');
    var label = (vt.brief && vt.brief.layout_template) || v.layout_template || ('Variant ' + vt.seed);
    var hook = (vt.brief && vt.brief.primary_hook) || '';
    return (
      '<div class="variant-tile" style="flex:1;min-width:160px;background:rgba(139,92,246,0.04);border:1px solid var(--border);border-radius:8px;padding:8px">' +
        '<img src="' + imgUrl + '" alt="Variant ' + vt.seed + '" style="width:100%;border-radius:6px;background:#0a0a0a;display:block" />' +
        '<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-top:6px">Option ' + vt.seed + ' · ' + label + '</div>' +
        (hook ? '<div style="font-size:11px;color:var(--ink);margin-top:2px">' + hook + '</div>' : '') +
        '<button class="btn" data-pick-vid="' + v.id + '" data-pick-seed="' + vt.seed + '" data-pick-fmt="' + (v.format_name || 'feed_portrait') + '" style="margin-top:6px;width:100%;font-size:11px;padding:5px 0" onclick=' + _attrEsc('pickVariant(this, ' + JSON.stringify(cardId) + ', ' + JSON.stringify(createUrl) + ')') + '>Pick this one</button>' +
      '</div>'
    );
  }}).join('');
  panel.innerHTML =
    '<div style="font-size:11px;color:var(--ink-muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px">Choose a variant</div>' +
    '<div style="display:flex;gap:10px;flex-wrap:wrap">' + tilesHtml + '</div>';
}}

function pickVariant(btn, cardId, createUrl) {{
  var vid = btn.dataset.pickVid;
  var seed = btn.dataset.pickSeed;
  var fmt = btn.dataset.pickFmt || 'feed_portrait';
  var apiBase = (window._API_BASE || '');
  var imgUrl = apiBase + '/api/visual/' + encodeURIComponent(vid) + '/png/' + encodeURIComponent(fmt);
  // Persist the choice in workflow sidecar
  var url = WF_API_BASE + encodeURIComponent(cardId);
  fetch(url, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{action:'set_edits', edits:{{picked_visual_id: vid, picked_variation_seed: seed}}}})}}).catch(function(){{}});
  // Promote to primary view
  var panel = document.querySelector('.visual-panel[data-card="' + cardId + '"]');
  var fakeData = {{
    visuals: [{{id: vid, format_name: fmt, layout_template: btn.parentElement.querySelector('div').textContent || ''}}],
    brief: {{}},
  }};
  _renderVisualPanel(panel, fakeData, cardId, createUrl);
}}

function addGraphicToPack(btn, visualId) {{
  // Visuals are already persisted on render; this just confirms inclusion.
  btn.textContent = '✓ Added to pack';
  btn.disabled = true;
  setTimeout(function() {{ btn.textContent = '+ Add to pack'; btn.disabled = false; }}, 2000);
}}

// Poll LLM status once on page load and colour every AI status dot
// (green = any provider live, red = heuristic fallback only).
(function pollLlmStatus(){{
  try {{
    var url = (window._API_BASE || '') + '/api/settings/llm-status';
    fetch(url, {{cache:'no-store'}})
      .then(function(r){{ return r.json(); }})
      .then(function(j){{
        var dots = document.querySelectorAll('.ai-status-dot');
        var color = j.live ? '#2cc97f' : '#ff5d6c';
        var providerLabel = j.provider_label || 'Anthropic key';
        var title = j.live
          ? ('Live AI enabled — provider: ' + providerLabel)
          : 'Live AI DISABLED — add Anthropic key in Settings, or use this UI inside a Claude Code session.';
        dots.forEach(function(d){{
          d.style.background = color;
          var btn = d.closest('button');
          if (btn) btn.title = title;
        }});
      }})
      .catch(function(){{}});
  }} catch(e){{}}
}})();
</script>
"""
        return _layout("Recognition", body, active="home")

    # ---- V5 API ROUTES -------------------------------------------------
    @app.route("/api/runs/<run_id>/recognition")
    def api_recognition(run_id):
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        rr = data.get("recognition_report")
        if rr is None:
            return jsonify({"error": "no recognition report", "recognition_error": data.get("recognition_error")}), 404
        return jsonify(rr)

    @app.route("/api/runs/<run_id>/swim/<swim_id>/trace")
    def api_swim_trace(run_id, swim_id):
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        rr = data.get("recognition_report") or {}
        traces = rr.get("swim_traces") or []
        # swim_id may have special chars; do substring match
        import urllib.parse as _urlparse
        swim_id_dec = _urlparse.unquote(swim_id)
        for t in traces:
            if t.get("swim_id") == swim_id_dec:
                return jsonify(t)
        # fallback: partial match
        for t in traces:
            if swim_id_dec in (t.get("swim_id") or ""):
                return jsonify(t)
        return jsonify({"error": "trace not found", "swim_id": swim_id_dec}), 404


    # ---- V8 LIVE CAPTION ENDPOINT -----------------------------------

    @app.route("/api/runs/<run_id>/swim/<swim_id>/caption", methods=["POST"])
    def api_live_caption(run_id, swim_id):
        """
        V8 Live Caption endpoint.

        POST /api/runs/<run_id>/swim/<swim_id>/caption?tone=<voice_id|ai>

        Returns JSON: {caption: str, tone: str, generated_at: iso,
                       fallback: bool, fallback_voice: str|None}

        - tone=ai  : generates LIVE via Claude Sonnet (no caching).
        - tone=<id>: renders via voice.learned.render_caption().

        Graceful degradation: if LLM unavailable, ai tone returns a
        randomly-picked voice render with fallback=True.
        """
        import urllib.parse as _up
        from datetime import datetime, timezone as _tz

        tone = request.args.get("tone", "ai").strip()
        swim_id_dec = _up.unquote(swim_id)

        # Load run data
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "run not found"}), 404

        rr = data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []

        # Find the achievement for this swim_id
        achievement = {}
        for ra in ranked:
            a = ra.get("achievement") or {}
            if a.get("swim_id") == swim_id_dec:
                achievement = a
                break
        # Fallback: partial match
        if not achievement:
            for ra in ranked:
                a = ra.get("achievement") or {}
                if swim_id_dec in (a.get("swim_id") or ""):
                    achievement = a
                    break

        # Build achievement dict suitable for caption generation
        ach_dict = {
            "swimmer_first": achievement.get("swimmer_name", "").split()[0] if achievement.get("swimmer_name") else "",
            "swimmer_last": " ".join(achievement.get("swimmer_name", "").split()[1:]) if achievement.get("swimmer_name") else "",
            "swimmer_name": achievement.get("swimmer_name", ""),
            "event": achievement.get("event", ""),
            "time": achievement.get("time", ""),
            "pb": achievement.get("pb", False),
            "club": data.get("profile_display", ""),
            "meet": (data.get("meet") or {}).get("name", ""),
            "place": achievement.get("place", ""),
            "type": achievement.get("type", ""),
            "headline": achievement.get("headline", ""),
        }

        # Club brand hints
        club_brand = {
            "club_name": data.get("profile_display", ""),
            "meet_name": (data.get("meet") or {}).get("name", ""),
        }

        now_iso = datetime.now(_tz.utc).isoformat()

        from mediahub.media_ai.llm import is_available as _llm_available
        from mediahub.web.ai_caption import (
            generate_caption_for_tone as _gen_tone,
            KNOWN_AI_TONES as _AI_TONES,
            ClaudeUnavailableError as _ClaudeUE,  # type: ignore[attr-defined]
        )

        if tone in _AI_TONES:
            # LIVE generation — fresh every call, nonce injected for uniqueness.
            # Works with Gemini (free) or Anthropic API key.
            if not _llm_available():
                return jsonify({
                    "caption": "",
                    "tone": tone,
                    "live": False,
                    "generated_at": now_iso,
                    "error": "no_key",
                    "message": (
                        "Add a Gemini API key (free at aistudio.google.com) or "
                        "Anthropic API key in Settings to generate live AI captions."
                    ),
                    "settings_url": url_for("settings_page"),
                }), 200
            try:
                caption_text = _gen_tone(ach_dict, club_brand, tone=tone)
                return jsonify({
                    "caption": caption_text,
                    "tone": tone,
                    "live": True,
                    "generated_at": now_iso,
                    "fallback": False,
                    "fallback_voice": None,
                })
            except _ClaudeUE as e:
                return jsonify({
                    "caption": "",
                    "tone": tone,
                    "live": False,
                    "generated_at": now_iso,
                    "error": "llm_unavailable",
                    "message": (
                        f"AI provider error: {e}. "
                        "Add a Gemini API key (free) or Anthropic key in Settings."
                    ),
                    "settings_url": url_for("settings_page"),
                }), 200
        else:
            # Voice render — deterministic template, may be cached by client
            try:
                from mediahub.voice.learned.store import list_voices as _lv, load_voice as _load_v
                from mediahub.voice.learned.render import render_caption as _rc
            except ImportError:
                return jsonify({"error": "voice rendering unavailable"}), 503

            profile = None
            try:
                profile = _load_v(tone)
            except FileNotFoundError:
                pass

            if profile is None:
                voices = _lv(include_seed=True)
                for v in voices:
                    if v.voice_id == tone:
                        profile = v
                        break

            if profile is None:
                return jsonify({"error": f"voice not found: {tone}"}), 404

            captions = _rc(ach_dict, profile, n_variants=1)
            caption_text = captions[0] if captions else ""
            return jsonify({
                "caption": caption_text,
                "tone": tone,
                "generated_at": now_iso,
                "fallback": False,
                "fallback_voice": None,
            })

    # ---- V6 PB AUDIT ROUTES ----------------------------------------

    @app.route("/audit/<run_id>")
    def pb_audit_page(run_id):
        """Full PB audit page with per-swimmer drill-down."""
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404
        pb_audit = data.get("pb_audit") or {}
        if not pb_audit:
            return _layout("PB Audit",
                           '<div class="card"><p class="muted">No detailed PB audit for this run. '
                           'Re-run with PB fetching enabled.</p></div>', active="")
        per_swimmer = pb_audit.get("per_swimmer") or []
        _review_url = url_for("review", run_id=run_id)

        rows = ""
        for sa in per_swimmer:
            identity = sa.get("identity") or {}
            method = identity.get("method", "")
            method_cls = {
                "asa_id_verified": "good",
                "needs_verification": "warn",
                "asa_id_unverified": "",
                "no_id": "",
                "manual_override": "info",
            }.get(method, "")
            _sw_key = sa.get('asa_id') or f"name:{sa.get('hy3_name','')}"
            _verify_url = url_for('pb_verify_form', run_id=run_id, swimmer_key=_sw_key)
            _ignore_url = url_for('pb_ignore', run_id=run_id, swimmer_key=_sw_key)
            n_dec = len(sa.get('pb_decisions') or [])
            n_conf = sum(1 for d in (sa.get('pb_decisions') or []) if d.get('status') == 'CONFIRMED_PB')
            rows += (
                f'<tr>'
                f'<td>{_h(sa.get("hy3_name",""))}</td>'
                f'<td class="muted">{_h(sa.get("asa_id") or "—")}</td>'
                f'<td>{_h(sa.get("sr_name") or "—")}</td>'
                f'<td><span class="tag {method_cls}">{_h(method)}</span></td>'
                f'<td>{n_dec}</td>'
                f'<td style="color:#4ADE80">{n_conf}</td>'
                f'<td>'
                f'<a class="btn secondary" style="font-size:11px;padding:3px 8px" href="{_verify_url}">Verify</a>'
                f' <form style="display:inline" method="post" action="{_ignore_url}">'
                f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" type="submit">Ignore PBs</button></form>'
                f'</td>'
                f'</tr>'
            )

        body = f"""
<h1>PB Audit — {_h(pb_audit.get('run_id', run_id))}</h1>
<p class="dim"><a href="{_review_url}">← Back to review</a></p>
<div class="card">
  <div class="stat-block">
    <div class="stat"><div class="l">Swimmers</div><div class="v">{pb_audit.get('swimmers_total',0)}</div></div>
    <div class="stat"><div class="l" style="color:#22D3EE">Verified</div><div class="v" style="color:#22D3EE">{pb_audit.get('swimmers_matched_verified',0)}</div></div>
    <div class="stat"><div class="l" style="color:#F59E0B">Needs verification</div><div class="v" style="color:#F59E0B">{pb_audit.get('swimmers_needs_verification',0)}</div></div>
    <div class="stat"><div class="l">Confirmed PBs</div><div class="v" style="color:#4ADE80">{pb_audit.get('pb_confirmed_count',0)}</div></div>
    <div class="stat"><div class="l">Total decisions</div><div class="v">{pb_audit.get('pb_decisions_count',0)}</div></div>
    <div class="stat"><div class="l">Fetch time</div><div class="v">{pb_audit.get('fetch_total_seconds',0):.1f}s</div></div>
  </div>
</div>
<div class="card">
  <h2>Per-swimmer</h2>
  <table>
    <thead><tr>
      <th>HY3 Name</th><th>ASA ID</th><th>SR Name</th><th>Identity</th><th>Decisions</th><th>Confirmed</th><th>Actions</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""
        return _layout("PB Audit", body, active="")

    @app.route("/audit/<run_id>/verify/<path:swimmer_key>", methods=["GET", "POST"])
    def pb_verify_form(run_id, swimmer_key):
        """Form to enter correct ASA number for a needs-verification swimmer."""
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404
        _review_url = url_for("review", run_id=run_id)
        _audit_url = url_for("pb_audit_page", run_id=run_id)

        if request.method == "POST":
            new_asa = request.form.get("new_asa_id", "").strip()
            note = request.form.get("note", "").strip()
            if new_asa:
                from swim_content_pb.corrections import CorrectionsStore
                cs = CorrectionsStore()
                cs.set_override_asa_id(run_id, swimmer_key, new_asa, note=note)
            return redirect(_audit_url)

        _sw_key_h = _h(swimmer_key)
        _action_url = url_for('pb_verify_form', run_id=run_id, swimmer_key=swimmer_key)

        # Pull this swimmer's audit details so the user can see WHY this needs
        # verification — not just an opaque key.
        pb_audit = data.get("pb_audit") or {}
        per_sw = pb_audit.get("per_swimmer") or []
        target = None
        for sw in per_sw:
            if str(sw.get("asa_id") or "") == swimmer_key or sw.get("hy3_name", "").replace(",", "").replace(" ", "").lower() == swimmer_key.replace(",", "").replace(" ", "").lower():
                target = sw
                break

        context_html = ""
        if target:
            ident = target.get("identity") or {}
            hy3_name = _h(target.get("hy3_name") or "—")
            sr_name = _h(target.get("sr_name") or "— (no record returned)")
            method = _h(ident.get("method") or "—")
            method_pill = {"asa_id_verified": "good", "needs_verification": "warn",
                          "asa_id_unverified": "warn", "no_id": "bad",
                          "manual_override": "info"}.get(ident.get("method", ""), "")
            cur_asa = _h(target.get("asa_id") or "—")
            notes_list = ident.get("notes") or []
            notes_html = "".join(f"<li>{_h(n)}</li>" for n in notes_list) or "<li class='muted'>No notes</li>"
            context_html = f"""
<div class="card" style="margin-bottom:18px">
  <h2 style="font-size:16px;margin-bottom:14px">What we know about this swimmer</h2>
  <table style="width:100%;font-size:13px">
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">In your file (HY3)</td>
        <td><strong>{hy3_name}</strong></td></tr>
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">Currently linked ASA ID</td>
        <td><code>{cur_asa}</code></td></tr>
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">PB source returned</td>
        <td><strong>{sr_name}</strong></td></tr>
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">Match status</td>
        <td><span class="tag {method_pill}">{method}</span></td></tr>
  </table>
  <div style="margin-top:14px;font-size:12px;color:var(--ink-dim)">
    <strong>Why this matters:</strong>
    <ul style="margin:4px 0 0 20px">{notes_html}</ul>
  </div>
</div>"""
        else:
            context_html = f"""
<div class="card" style="margin-bottom:18px">
  <p class="muted">Swimmer key <code>{_sw_key_h}</code> wasn't found in this run's audit data. You can still set a manual override.</p>
</div>"""

        body = f"""
<h1>Verify swimmer identity</h1>
<p class="dim"><a href="{_audit_url}">← Back to audit</a></p>
{context_html}
<div class="card">
  <h2 style="font-size:16px;margin-bottom:8px">Set the correct ASA member ID</h2>
  <p class="dim" style="font-size:13px">This override applies to this meet only. It won't affect other runs.
  If you save this, we'll re-fetch PBs for the corrected ID.</p>
  <form method="post" action="{_action_url}">
    <label>Correct ASA member ID</label>
    <input type="text" name="new_asa_id" placeholder="e.g. 1382076" pattern="[0-9]+" required />
    <label>Note (optional)</label>
    <input type="text" name="note" placeholder="Why this override (e.g. wrong number entered in HY3)" />
    <div style="margin-top:14px;display:flex;gap:10px">
      <button class="btn" type="submit">Save correction</button>
      <a class="btn secondary" href="{_audit_url}">Cancel</a>
    </div>
  </form>
</div>"""
        return _layout("Verify swimmer", body, active="")

    @app.route("/audit/<run_id>/ignore/<path:swimmer_key>", methods=["POST"])
    def pb_ignore(run_id, swimmer_key):
        """Mark 'ignore PBs for this swimmer in this meet'."""
        reason = request.form.get("reason", "User requested ignore")
        from swim_content_pb.corrections import CorrectionsStore
        cs = CorrectionsStore()
        cs.set_ignore_pb(run_id, swimmer_key, reason=reason)
        return redirect(url_for('pb_audit_page', run_id=run_id))

    @app.route("/audit/<run_id>/ground-truth", methods=["GET", "POST"])
    def pb_ground_truth(run_id):
        """Upload a CSV of expected outcomes and run the ground-truth harness."""
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404
        _audit_url = url_for('pb_audit_page', run_id=run_id)
        _action_url = url_for('pb_ground_truth', run_id=run_id)

        report_html = ""
        if request.method == "POST":
            f = request.files.get("csv_file")
            if f and f.filename:
                import tempfile
                from pathlib import Path as _Path
                from swim_content_pb.ground_truth import run_ground_truth
                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                    f.save(tmp.name)
                    csv_path = _Path(tmp.name)
                try:
                    report = run_ground_truth(
                        run_id=run_id,
                        truth_csv_path=csv_path,
                        run_pb_audit_dict=data.get('pb_audit'),
                    )
                    report_html = (
                        f'<div class="card"><h2>Ground Truth Results</h2>'
                        f'<div class="stat-block">'
                        f'<div class="stat"><div class="l">Total entries</div><div class="v">{report.total_entries}</div></div>'
                        f'<div class="stat"><div class="l" style="color:#4ADE80">True positives</div><div class="v" style="color:#4ADE80">{report.true_positives}</div></div>'
                        f'<div class="stat"><div class="l" style="color:#F87171">False positives</div><div class="v" style="color:#F87171">{report.false_positives}</div></div>'
                        f'<div class="stat"><div class="l" style="color:#FBBF24">False negatives</div><div class="v" style="color:#FBBF24">{report.false_negatives}</div></div>'
                        f'<div class="stat"><div class="l">Precision</div><div class="v">{report.precision or "—"}</div></div>'
                        f'<div class="stat"><div class="l">Recall</div><div class="v">{report.recall or "—"}</div></div>'
                        f'<div class="stat"><div class="l">F1</div><div class="v">{report.f1 or "—"}</div></div>'
                        f'</div></div>'
                    )
                except Exception as e:
                    report_html = f'<div class="card"><p class="tag bad">Error: {_h(str(e))}</p></div>'
                finally:
                    try:
                        csv_path.unlink()
                    except Exception:
                        pass

        body = f"""
<h1>Ground Truth — PB Decisions</h1>
<p class="dim"><a href="{_audit_url}">← Back to PB audit</a></p>
<div class="card">
  <p>Upload a CSV with columns: <code>swimmer_name, event_label, result_time, expected_pb, expected_prev_pb, expected_barrier_crossed, notes</code></p>
  <p><code>expected_pb</code>: yes | no | unknown</p>
  <form method="post" enctype="multipart/form-data" action="{_action_url}">
    <input type="file" name="csv_file" accept=".csv" required />
    <div style="margin-top:12px"><button class="btn" type="submit">Run ground truth</button></div>
  </form>
</div>
{report_html}"""
        return _layout("Ground Truth", body, active="")

    @app.route("/recognition/<run_id>")
    def recognition_page(run_id):
        """Standalone recognition page (redirect to review for now)."""
        return redirect(url_for('review', run_id=run_id))

    @app.route("/api/runs/<run_id>/cards")
    def api_cards(run_id):
        state = _run_state(run_id)
        if state == "in_progress":
            return jsonify({"error": "in_progress", "retry_after": 4}), 202
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        return jsonify(data.get("cards", []))

    @app.route("/api/runs/<run_id>/trust")
    def api_trust(run_id):
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        return jsonify(data.get("trust", {}))

    @app.route("/api/runs/<run_id>/export")
    def api_export(run_id):
        state = _run_state(run_id)
        if state == "in_progress":
            return jsonify({"error": "in_progress", "retry_after": 4}), 202
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    # ---- GROUND TRUTH --------------------------------------------------
    @app.route("/ground-truth/<run_id>", methods=["GET", "POST"])
    def ground_truth(run_id):
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        rep_html = ""
        if request.method == "POST":
            text = request.form.get("moments", "")
            from .ground_truth import evaluate
            # Need ContentCard objects: re-hydrate basic shape from saved dicts
            class _Stub:
                pass
            cards = []
            for d in data.get("cards") or []:
                s = _Stub()
                s.card_id = d.get("card_id", "")
                s.headline = d.get("headline", "")
                s.swimmer_names = d.get("swimmer_names") or []
                s.bucket = d.get("bucket", "")
                claims = []
                for cl in d.get("claims") or []:
                    cs = _Stub()
                    cs.distance = cl.get("distance"); cs.stroke = cl.get("stroke")
                    claims.append(cs)
                s.claims = claims
                cards.append(s)
            rep = evaluate(text, cards)
            data["ground_truth_report"] = rep.to_dict()
            (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(data, indent=2, default=str))

            rows = ""
            for m in rep.matches:
                badge = "good" if m.get("matched_card") else "bad"
                rows += (f'<tr><td>{_h(m.get("moment",""))}</td>'
                         f'<td><span class="tag {badge}">'
                         f'{"matched" if m.get("matched_card") else "missed"}</span></td>'
                         f'<td>{_h(m.get("matched_headline") or "—")}</td>'
                         f'<td>{_h(m.get("score",""))}</td></tr>')
            rep_html = f"""
<div class="card">
  <h2>Result</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Precision</div><div class="v">{rep.precision*100:.0f}%</div></div>
    <div class="stat"><div class="l">Recall</div><div class="v">{rep.recall*100:.0f}%</div></div>
    <div class="stat"><div class="l">F1</div><div class="v">{rep.f1*100:.0f}%</div></div>
    <div class="stat"><div class="l">Matched</div><div class="v">{rep.n_matched_moments}/{rep.n_total_moments}</div></div>
  </div>
  <div class="divider"></div>
  <table>
    <thead><tr><th>Expected moment</th><th>Status</th><th>Best card match</th><th>Score</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="muted" style="margin-top:14px">{rep.notes}</p>
</div>
"""

        body = f"""
<h1>Ground-truth check</h1>
<p class="dim">Paste 5–15 expected highlights from this meet. We score how well MediaHub
surfaces them as content cards. One per line.</p>

<div class="card">
  <form method="post">
    <label>Expected moments (one per line)</label>
    <textarea name="moments" placeholder="Eva Davies 100m butterfly PB
Mathew Bradley 200m IM gold
Relay team broke club record"></textarea>
    <div style="margin-top:14px"><button class="btn" type="submit">Score</button></div>
  </form>
</div>
{rep_html}
"""
        return _layout("Ground truth", body, active="home")

    # ---- RESEARCH ------------------------------------------------------
    @app.route("/research")
    def research_page():
        # Try to render a research markdown if present
        md_path = RESEARCH_DIR / "parser_roadmap.md"
        if md_path.exists():
            content = md_path.read_text()
            html = _render_markdown(content)
        else:
            html = """
<h2>Adapter roadmap (interim)</h2>
<p>The research substream is collecting source-format coverage across UK and US meets.
   This page will populate when the roadmap document is written.</p>
<h3>Currently supported</h3>
<ul>
  <li><strong>HY3</strong> — Hytek Meet Manager (UK + US) — full parser with splits.</li>
</ul>
<h3>Planned next</h3>
<ul>
  <li>SDIF / CL2 — sibling format produced by Hytek and used by USA Swimming.</li>
  <li>Meet Mobile / SwimTopia exports (CSV).</li>
  <li>Public meet-result pages from external swim-results sites (HTML adapter).</li>
  <li>USA Swimming Times Search exports.</li>
</ul>
<p class="muted">Each new adapter must implement <code>can_parse()</code> and return the
   canonical Meet schema. No detector / caption code changes are needed.</p>
"""
        body = f'<h1>Research roadmap</h1><div class="card">{html}</div>'
        return _layout("Research", body, active="research")

    # ---- PRIVACY -------------------------------------------------------
    @app.route("/privacy")
    def privacy_page():
        conn = _db()
        n_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        conn.close()
        n_files = sum(1 for _ in RUNS_DIR.glob("*.json"))
        n_uploads = sum(1 for _ in UPLOADS_DIR.iterdir())
        cache_dir = DATA_DIR / ".cache" / "pb_lookup"
        legacy_cache = DATA_DIR / ".cache" / "swimmingresults"
        n_cache = (
            (sum(1 for _ in cache_dir.glob("*.json")) if cache_dir.exists() else 0)
            + (sum(1 for _ in legacy_cache.glob("*.json")) if legacy_cache.exists() else 0)
        )
        body = f"""
<h1>Privacy & data</h1>
<p class="dim">What this system stores, where, and how to delete it.</p>

<div class="card">
  <h2>Inventory</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Runs (DB)</div><div class="v">{n_runs}</div></div>
    <div class="stat"><div class="l">Run JSON files</div><div class="v">{n_files}</div></div>
    <div class="stat"><div class="l">Upload temp files</div><div class="v">{n_uploads}</div></div>
    <div class="stat"><div class="l">PB cache entries</div><div class="v">{n_cache}</div></div>
  </div>
</div>

<div class="card">
  <h2>What we store</h2>
  <ul>
    <li><strong>Run records</strong> — per upload: meet metadata, parsed swims, generated cards, captions, audit log. Deletable per run.</li>
    <li><strong>Club profiles</strong> — your roster + branding. Editable on the Profiles tab.</li>
    <li><strong>PB cache</strong> — local cache of public PB-lookup pages (the active source is chosen at runtime), keyed by member id. Clearable.</li>
    <li><strong>Database</strong> — small SQLite index <code>data.db</code> for the run list.</li>
  </ul>
  <p class="muted">No data is sent to third parties beyond fetching public PB-lookup pages from the configured PB source.</p>
</div>

<div class="card">
  <h2>Actions</h2>
  <form method="post" action="{url_for('privacy_cache_clear')}" style="display:inline" onsubmit="return confirm('Clear the PB cache?')">
    <button class="btn secondary" type="submit">Clear PB cache</button>
  </form>
  <p class="muted" style="margin-top:8px">To delete an individual run, open it from the home page and use the Delete run button.</p>
</div>
"""
        return _layout("Privacy", body, active="privacy")

    @app.route("/privacy/run/<run_id>/delete", methods=["POST"])
    def privacy_delete_run(run_id):
        _delete_run(run_id)
        return redirect(url_for("home"))

    @app.route("/privacy/cache/clear", methods=["POST"])
    def privacy_cache_clear():
        for d in [DATA_DIR / ".cache" / "pb_lookup", DATA_DIR / ".cache" / "swimmingresults"]:
            if d.exists():
                for f in d.glob("*.json"):
                    try: f.unlink()
                    except Exception: pass
        return redirect(url_for("privacy_page"))

    # ---- HEALTH --------------------------------------------------------
    APP_VERSION = "v4.0.0"

    def _health_payload():
        checks = {}
        # backend
        checks["backend"] = {"ok": True, "version": APP_VERSION}
        # db
        try:
            c = _db()
            c.execute("SELECT 1").fetchone()
            c.close()
            try:
                _db_display = str(DB_PATH.relative_to(DATA_DIR))
            except ValueError:
                _db_display = str(DB_PATH)
            checks["database"] = {"ok": True, "path": _db_display}
        except Exception as e:
            checks["database"] = {"ok": False, "error": str(e)}
        # writable dirs
        for label, p in [("uploads", UPLOADS_DIR), ("runs", RUNS_DIR),
                         ("pb_cache", DATA_DIR / ".cache" / "pb_lookup")]:
            try:
                p.mkdir(parents=True, exist_ok=True)
                test = p / ".write_test"
                test.write_text("ok")
                test.unlink()
                # Display path relative to DATA_DIR when possible (production layout);
                # fall back to absolute path when RUNS_DIR / UPLOADS_DIR live outside
                # DATA_DIR (a valid configuration in local dev and tests).
                try:
                    display_path = str(p.relative_to(DATA_DIR))
                except ValueError:
                    display_path = str(p)
                checks[label] = {"ok": True, "path": display_path}
            except Exception as e:
                checks[label] = {"ok": False, "error": str(e)}
        # V8.2: profiles UI removed; health check no longer requires any profiles.
        try:
            profs = list_profiles()
            checks["profiles"] = {"ok": True, "count": len(profs),
                                  "ids": [p.profile_id for p in profs]}
        except Exception as e:
            checks["profiles"] = {"ok": True, "count": 0, "error": str(e)}
        ok_all = all(v.get("ok") for v in checks.values())
        return {
            "ok": ok_all,
            "version": APP_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        }

    @app.route("/health")
    def health():
        payload = _health_payload()
        return jsonify(payload), (200 if payload["ok"] else 503)

    @app.route("/healthz")
    def healthz():
        # Cheap liveness probe (no disk/db work)
        return jsonify({"ok": True, "version": APP_VERSION,
                        "ts": datetime.now(timezone.utc).isoformat()})

    # ---- /settings — user-supplied API keys ---------------------------
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        """Settings page — paste API keys + pick a cutout provider.

        V8.1 Issue 7 expanded this from Anthropic-only to also cover
        Photoroom + Replicate cutout credentials and a provider selector.
        """
        from mediahub.web.secrets_store import (
            get_anthropic_key, set_secret, mask_key, get_secret,
        )
        message_html = ""
        # Fall through to original handler logic (preserved below).
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "clear_anthropic":
                set_secret("anthropic_api_key", None)
                message_html = '<p class="tag good">Anthropic API key cleared.</p>'
            elif action == "clear_photoroom":
                set_secret("photoroom_api_key", None)
                message_html = '<p class="tag good">Photoroom API key cleared.</p>'
            elif action == "clear_replicate":
                set_secret("replicate_api_token", None)
                message_html = '<p class="tag good">Replicate API token cleared.</p>'
            elif action == "clear_gemini":
                set_secret("gemini_api_key", None)
                message_html = '<p class="tag good">Gemini API key cleared.</p>'
            elif action == "save_gemini":
                key = (request.form.get("gemini_api_key") or "").strip()
                if not key:
                    message_html = '<p class="tag bad">No Gemini key submitted.</p>'
                elif len(key) < 20:
                    message_html = (
                        '<p class="tag bad">That looks too short to be a Gemini API key. '
                        'Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com</a>.</p>'
                    )
                else:
                    set_secret("gemini_api_key", key)
                    message_html = (
                        '<p class="tag good">Gemini API key saved. '
                        'Live AI captions are now enabled (free tier).</p>'
                    )
            elif action == "set_cutout_provider":
                choice = (request.form.get("cutout_provider") or "local").strip().lower()
                if choice not in {"local", "replicate", "photoroom"}:
                    choice = "local"
                set_secret("mediahub_cutout_provider", choice)
                message_html = (
                    f'<p class="tag good">Cutout provider set to '
                    f'<code>{choice}</code>.</p>'
                )
            elif action == "save_photoroom":
                key = (request.form.get("photoroom_api_key") or "").strip()
                if not key:
                    message_html = '<p class="tag bad">No Photoroom key submitted.</p>'
                elif len(key) < 8:
                    message_html = (
                        '<p class="tag bad">That looks too short to be a '
                        'Photoroom API key.</p>'
                    )
                else:
                    set_secret("photoroom_api_key", key)
                    message_html = (
                        '<p class="tag good">Photoroom API key saved.</p>'
                    )
            elif action == "save_replicate":
                key = (request.form.get("replicate_api_token") or "").strip()
                if not key:
                    message_html = '<p class="tag bad">No Replicate token submitted.</p>'
                elif not (key.startswith("r8_") and len(key) >= 16):
                    message_html = (
                        '<p class="tag bad">That doesn\'t look like a '
                        'Replicate API token. Tokens start with <code>r8_</code>.</p>'
                    )
                else:
                    set_secret("replicate_api_token", key)
                    message_html = (
                        '<p class="tag good">Replicate API token saved.</p>'
                    )
            else:
                # Default action: save Anthropic key.
                key = (request.form.get("anthropic_api_key") or "").strip()
                if not key:
                    message_html = '<p class="tag bad">No key submitted.</p>'
                elif not (key.startswith("sk-ant-") and len(key) >= 20):
                    message_html = (
                        '<p class="tag bad">That doesn\'t look like an Anthropic API key. '
                        'Keys start with <code>sk-ant-</code>.</p>'
                    )
                else:
                    set_secret("anthropic_api_key", key)
                    message_html = (
                        '<p class="tag good">Anthropic API key saved. '
                        'Live AI captions are now enabled.</p>'
                    )

        # Re-read after any write
        env_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        stored_key = get_secret("anthropic_api_key")
        active_key = get_anthropic_key()

        # Gemini (free LLM) state
        gemini_env = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        gemini_disk = get_secret("gemini_api_key")
        gemini_active = (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if gemini_env else gemini_disk
        )
        gemini_status_dot = "#2cc97f" if gemini_active else "#ffae3b"
        gemini_status_text = "Gemini ENABLED" if gemini_active else "Gemini DISABLED"
        if gemini_env:
            gemini_source = "environment variable"
        elif gemini_disk:
            gemini_source = "saved key"
        else:
            gemini_source = "none — add a key below"
        gemini_masked = _h(mask_key(gemini_active)) if gemini_active else "<em>none</em>"
        gemini_confirm = "Remove the saved Gemini API key?"
        gemini_clear_btn = ""
        if gemini_disk:
            gemini_clear_btn = (
                '<form method="POST" style="display:inline-block;margin-left:0">'
                '<input type="hidden" name="action" value="clear_gemini"/>'
                '<button type="submit" class="btn secondary" '
                f'onclick="return confirm({json.dumps(gemini_confirm)})">'
                'Clear stored key</button></form>'
            )

        # V8.1 Issue 7 — cutout provider state ----------------------------
        photoroom_env = bool(os.environ.get("PHOTOROOM_API_KEY"))
        photoroom_disk = get_secret("photoroom_api_key")
        photoroom_active = (
            os.environ.get("PHOTOROOM_API_KEY") if photoroom_env else photoroom_disk
        )
        photoroom_state = (
            "set (env)" if photoroom_env else ("set (disk)" if photoroom_disk else "absent")
        )
        photoroom_masked_html = (
            f' — <code>{_h(mask_key(photoroom_active))}</code>'
            if photoroom_active else ""
        )

        replicate_env = bool(os.environ.get("REPLICATE_API_TOKEN"))
        replicate_disk = get_secret("replicate_api_token")
        replicate_active = (
            os.environ.get("REPLICATE_API_TOKEN") if replicate_env else replicate_disk
        )
        replicate_state = (
            "set (env)" if replicate_env else ("set (disk)" if replicate_disk else "absent")
        )
        replicate_masked_html = (
            f' — <code>{_h(mask_key(replicate_active))}</code>'
            if replicate_active else ""
        )

        cutout_provider = (
            os.environ.get("MEDIAHUB_CUTOUT_PROVIDER")
            or os.environ.get("MEDIAHUB_BG_PROVIDER")
            or get_secret("mediahub_cutout_provider")
            or "local"
        )

        def _cutout_clear(action: str, label: str, present: bool) -> str:
            if not present:
                return ""
            return (
                '<form method="POST" style="display:inline-block;margin-left:8px">'
                f'<input type="hidden" name="action" value="{action}"/>'
                '<button type="submit" class="btn secondary" '
                f'onclick="return confirm(\'Remove the saved {label}?\')">'
                f'Clear {label}</button></form>'
            )

        photoroom_clear_btn = _cutout_clear(
            "clear_photoroom", "Photoroom API key", bool(photoroom_disk)
        )
        replicate_clear_btn = _cutout_clear(
            "clear_replicate", "Replicate API token", bool(replicate_disk)
        )

        def _opt(value: str) -> str:
            sel = " selected" if value == cutout_provider else ""
            return f'<option value="{value}"{sel}>{value}</option>'

        cutout_card = (
            '<div class="card" style="margin-top:16px">'
            '<h2 style="margin-top:0">Cutout providers (background removal)</h2>'
            '<p class="muted">Choose the engine that strips backgrounds from '
            'athlete photos. <code>local</code> uses the bundled rembg '
            '(free, decent). <code>replicate</code> uses '
            '<code>851-labs/background-remover</code> (paid, premium edges). '
            '<code>photoroom</code> uses the Photoroom API (paid, fastest).</p>'
            '<form method="POST" style="margin-bottom:16px;display:flex;gap:8px;align-items:center">'
            '<input type="hidden" name="action" value="set_cutout_provider"/>'
            '<label for="cutout_provider" style="font-weight:600">Active provider:</label>'
            f'<select id="cutout_provider" name="cutout_provider" style="padding:6px;border:1px solid var(--border);border-radius:6px">{_opt("local")}{_opt("replicate")}{_opt("photoroom")}</select>'
            '<button type="submit" class="btn">Save</button>'
            '</form>'

            '<h3 style="margin-top:18px">Photoroom API key</h3>'
            f'<p>Status: <strong>{photoroom_state}</strong>{photoroom_masked_html}</p>'
            '<form method="POST" style="margin-top:8px">'
            '<input type="hidden" name="action" value="save_photoroom"/>'
            '<input type="password" name="photoroom_api_key" '
            'placeholder="sandbox_xxx …" autocomplete="off" spellcheck="false" '
            'style="width:100%;max-width:560px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:monospace"/>'
            '<p class="muted" style="margin-top:6px;font-size:12px">'
            'Get a key from <a href="https://www.photoroom.com/api" target="_blank" rel="noopener">photoroom.com/api</a>.'
            '</p>'
            '<div style="margin-top:8px">'
            '<button type="submit" class="btn">Save Photoroom key</button>'
            f'{photoroom_clear_btn}'
            '</div>'
            '</form>'

            '<h3 style="margin-top:18px">Replicate API token</h3>'
            f'<p>Status: <strong>{replicate_state}</strong>{replicate_masked_html}</p>'
            '<form method="POST" style="margin-top:8px">'
            '<input type="hidden" name="action" value="save_replicate"/>'
            '<input type="password" name="replicate_api_token" '
            'placeholder="r8_…" autocomplete="off" spellcheck="false" '
            'style="width:100%;max-width:560px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:monospace"/>'
            '<p class="muted" style="margin-top:6px;font-size:12px">'
            'Get a token from <a href="https://replicate.com/account/api-tokens" target="_blank" rel="noopener">replicate.com</a>.'
            '</p>'
            '<div style="margin-top:8px">'
            '<button type="submit" class="btn">Save Replicate token</button>'
            f'{replicate_clear_btn}'
            '</div>'
            '</form>'
            '</div>'
        )
        # Detect ALL providers (not just Anthropic key) so users see the
        # status correctly when the claude CLI bridge is the active provider.
        try:
            from mediahub.media_ai.llm import is_available as _llm_available, active_provider
            llm_live = _llm_available()
            llm_provider = active_provider()
        except Exception:
            llm_live = bool(active_key)
            llm_provider = "anthropic-api" if active_key else "heuristic"

        _PROVIDER_LABEL = {
            "anthropic-api": "Anthropic API key",
            "gemini-api":    "Google Gemini (free tier)",
            "claude-cli":    "Claude CLI (Claude Code session)",
            "pplx-bridge":   "Computer LLM bridge",
            "heuristic":     "Heuristic fallback only",
        }
        provider_pretty = _PROVIDER_LABEL.get(llm_provider, llm_provider)

        status_dot = '#2cc97f' if llm_live else '#ffae3b'
        status_text = (
            "Live AI captions ENABLED" if llm_live else "Live AI captions DISABLED"
        )
        if active_key:
            source = "environment variable" if env_key else "saved key"
        elif llm_provider == "claude-cli":
            source = "claude CLI session (OAuth)"
        elif llm_provider == "pplx-bridge":
            source = "Computer LLM bridge"
        else:
            source = "none — add a key below"
        masked = _h(mask_key(active_key)) if active_key else "<em>none</em>"

        clear_btn = ""
        if stored_key:
            clear_btn = (
                '<form method="POST" style="display:inline-block;margin-left:8px">'
                '<input type="hidden" name="action" value="clear_anthropic"/>'
                '<button type="submit" class="btn secondary" '
                'onclick="return confirm(\'Remove the saved Anthropic API key?\')">'
                'Clear stored key</button></form>'
            )

        body = f"""
<div class="card">
  <h1 style="margin-top:0">Settings</h1>
  <p class="muted">Configure provider credentials. Keys are stored on disk with
     restricted permissions and never sent anywhere except the provider you've configured.</p>
  {message_html}
</div>

<div class="card" style="margin-top:16px;border-color:rgba(34,197,94,0.25)">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px">
    <h2 style="margin:0">Google Gemini — free AI captions</h2>
    <span class="tag good" style="font-size:11px">Recommended (free)</span>
  </div>
  <p style="display:flex;align-items:center;gap:8px;margin:8px 0">
    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{gemini_status_dot}"></span>
    <strong>{gemini_status_text}</strong>
    <span class="muted">— source: {gemini_source}</span>
  </p>
  <p>Current key: {gemini_masked}</p>
  <form method="POST" style="margin-top:12px">
    <input type="hidden" name="action" value="save_gemini"/>
    <label for="gemini_api_key" style="display:block;font-weight:600;margin-bottom:4px">
      Paste your Gemini API key
    </label>
    <input type="password" id="gemini_api_key" name="gemini_api_key"
           placeholder="AIza…" autocomplete="off" spellcheck="false"
           style="width:100%;max-width:560px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:monospace"/>
    <p class="muted" style="margin-top:6px;font-size:12px">
      Get a <strong>free</strong> key from <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com</a>
      — no credit card required. Free tier: 15 requests/min, 1,500/day with Gemini 2.0 Flash.
    </p>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
      <button type="submit" class="btn">Save Gemini key</button>
      {gemini_clear_btn}
    </div>
  </form>
</div>

<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">Anthropic (Claude) — paid AI captions</h2>
  <p style="display:flex;align-items:center;gap:8px;margin:8px 0">
    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{status_dot}"></span>
    <strong>{status_text}</strong>
    <span class="muted">— source: {source}</span>
  </p>
  <p>Current key: {masked}</p>
  <form method="POST" style="margin-top:12px">
    <label for="anthropic_api_key" style="display:block;font-weight:600;margin-bottom:4px">
      Paste your Anthropic API key
    </label>
    <input type="password" id="anthropic_api_key" name="anthropic_api_key"
           placeholder="sk-ant-…" autocomplete="off" spellcheck="false"
           style="width:100%;max-width:560px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:monospace"/>
    <p class="muted" style="margin-top:6px;font-size:12px">
      Higher-quality model, but paid. Get a key from <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>.
      Used in preference to Gemini if both are configured.
    </p>
    <div style="margin-top:10px">
      <button type="submit" class="btn">Save key</button>
      {clear_btn}
    </div>
  </form>
</div>

<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">Status check</h2>
  <ul>
    <li>Active LLM provider: <strong>{_h(provider_pretty)}</strong></li>
    <li>Anthropic key via environment: <strong>{'set' if env_key else 'not set'}</strong></li>
    <li>Anthropic key saved on disk: <strong>{'present' if stored_key else 'absent'}</strong></li>
    <li>Active key source: <strong>{('environment' if env_key else ('disk' if stored_key else 'none'))}</strong></li>
    <li>Photoroom key: <strong>{photoroom_state}</strong>{photoroom_masked_html}</li>
    <li>Replicate token: <strong>{replicate_state}</strong>{replicate_masked_html}</li>
    <li>Cutout provider: <strong>{cutout_provider}</strong></li>
  </ul>
</div>

{cutout_card}
"""
        return _layout("Settings", body, active="settings")

    @app.route("/api/settings/llm-status")
    def api_llm_status():
        """Lightweight endpoint used by caption UI to colour the AI tab dot."""
        from mediahub.web.secrets_store import has_anthropic_key, get_anthropic_key, mask_key
        from mediahub.media_ai.llm import is_available as _llm_available, active_provider
        has_key = has_anthropic_key()
        provider = active_provider()  # 'anthropic-api' | 'claude-cli' | 'pplx-bridge' | 'heuristic'
        live = _llm_available()  # True for any real provider
        # Map internal provider names to the stable PUBLIC api names that
        # existing clients & tests depend on (backwards compatible).
        public_provider = {
            "anthropic-api": "anthropic",
            "gemini-api":    "gemini",
            "claude-cli":    "claude-cli",
            "pplx-bridge":   "pplx",
            "heuristic":     None,
        }.get(provider, provider if live else None)
        provider_label = {
            "anthropic-api": "Anthropic API key",
            "gemini-api":    "Google Gemini (free tier)",
            "claude-cli":    "Claude CLI (OAuth)",
            "pplx-bridge":   "Computer LLM bridge",
            "heuristic":     None,
        }.get(provider)
        return jsonify({
            "live": live,
            "provider": public_provider,
            "provider_label": provider_label,
            "masked": mask_key(get_anthropic_key()) if has_key else "",
            "settings_url": url_for("settings_page"),
        })


    # ====================================================================
    # V7 NEW ROUTES
    # ====================================================================

    # ---- /make — content-type chooser ----------------------------------
    @app.route("/make")
    def make_page():
        try:
            from mediahub.club_platform.content_types import REGISTRY, ContentType
        except ImportError:
            return _layout("Create", '<div class="card"><p class="muted">club_platform package not available.</p></div>', active="create")

        tiles_html = ""
        for ct, meta in REGISTRY.items():
            if meta.is_implemented:
                badge = '<span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:rgba(34,197,94,0.15);color:#22C55E;border:1px solid rgba(34,197,94,0.3)">ready</span>'
                route_url = url_for(meta.primary_route_endpoint)
                action = f'href="{route_url}"'
                opacity = "1"
            else:
                badge = '<span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:rgba(255,255,255,0.06);color:var(--ink-muted);border:1px solid var(--border)">coming soon</span>'
                try:
                    route_url = url_for(meta.primary_route_endpoint)
                    action = f'href="{route_url}"'
                except Exception:
                    action = 'href="#" onclick="return false"'
                opacity = "0.7"
            tiles_html += f"""
<a {action} class="make-tile" style="text-decoration:none;display:flex;flex-direction:column;gap:12px;padding:24px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);transition:border-color 150ms,box-shadow 150ms;opacity:{opacity}">
  <div style="color:var(--accent)">{meta.icon_svg}</div>
  <div style="display:flex;align-items:center;gap:10px">
    <div style="font-size:16px;font-weight:700;color:var(--ink)">{_h(meta.title)}</div>
    {badge}
  </div>
  <div style="font-size:13px;color:var(--ink-dim);line-height:1.5">{_h(meta.description)}</div>
  <div style="font-size:12px;color:var(--ink-muted);margin-top:auto">{_h(meta.input_contract[:120])}{"…" if len(meta.input_contract) > 120 else ""}</div>
</a>"""

        body = f"""
<style>
.make-tile:hover {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
</style>
<h1>What do you want to create?</h1>
<p class="dim" style="margin-bottom:28px">Choose a content type to get started.</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px">
  {tiles_html}
</div>
"""
        return _layout("Create", body, active="create")

    # ---- /spotlight — Athlete Spotlight landing ------------------------
    @app.route("/spotlight")
    def spotlight_landing():
        try:
            from mediahub.club_platform.athlete_spotlight import list_swimmers_in_run
        except ImportError:
            return _layout("Athlete Spotlight", '<div class="card"><p class="muted">club_platform not available.</p></div>', active="create")

        # List recent runs that have a recognition report
        conn = _db()
        recent_runs = conn.execute(
            "SELECT id, meet_name, file_name, created_at FROM runs WHERE status='done' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        conn.close()

        run_id_param = request.args.get("run_id", "")

        # Empty state when no meets have been processed yet
        if not recent_runs:
            empty_body = f"""
<h1>Athlete Spotlight</h1>
<p class="dim">Generate a single-athlete content pack from a processed meet.</p>
<div class="card">
  <h2>No meets yet</h2>
  <p>You'll need to upload a meet results file before you can spotlight a swimmer.
  Once a meet is processed, every swimmer in your club will be available here.</p>
  <a class="btn" href="{url_for('upload')}" style="margin-top:14px">Upload a meet →</a>
</div>"""
            return _layout("Athlete Spotlight", empty_body, active="create")

        runs_opts = '<option value="">Select a meet…</option>'
        for r in recent_runs:
            sel = 'selected' if r["id"] == run_id_param else ''
            label = _h(r["meet_name"] or r["file_name"] or r["id"])
            runs_opts += f'<option value="{_h(r["id"])}" {sel}>{label}</option>'

        swimmers_html = ""
        if run_id_param:
            run_data = _load_run(run_id_param)
            if run_data:
                swimmers = list_swimmers_in_run(run_data)
                if swimmers:
                    _review_url = url_for("review", run_id=run_id_param)
                    swimmers_html = f'<div style="margin-top:20px"><h2>Swimmers in this meet <span class="muted" style="font-weight:400;font-size:13px">({len(swimmers)})</span></h2>'
                    swimmers_html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:12px">'
                    for sw in swimmers:
                        sp_url = url_for("spotlight_view", run_id=run_id_param, swimmer_key=sw["swimmer_key"])
                        swimmers_html += f"""
<a href="{sp_url}" style="display:flex;flex-direction:column;gap:6px;padding:14px;background:var(--panel2);border:1px solid var(--border);border-radius:var(--radius-sm);text-decoration:none;transition:border-color 150ms">
  <div style="font-size:14px;font-weight:600;color:var(--ink)">{_h(sw["swimmer_name"])}</div>
  <div style="font-size:12px;color:var(--ink-dim)">{sw["n_achievements"]} achievement{"s" if sw["n_achievements"] != 1 else ""}</div>
</a>"""
                    swimmers_html += '</div></div>'
                else:
                    swimmers_html = '<div class="card"><p class="muted">No achievements found for this run. The recognition report may not be available.</p></div>'

        change_js = url_for("spotlight_landing")
        body = f"""
<h1>Athlete Spotlight</h1>
<p class="dim">Pick a meet, then pick a swimmer to generate a single-athlete content pack.</p>

<div class="card">
  <h2>Choose a meet</h2>
  <form method="get" action="{url_for('spotlight_landing')}">
    <select name="run_id" onchange="this.form.submit()" style="max-width:480px">
      {runs_opts}
    </select>
    <noscript><button class="btn" type="submit" style="margin-top:10px">Load swimmers →</button></noscript>
  </form>
  {swimmers_html}
</div>
"""
        return _layout("Athlete Spotlight", body, active="create")

    # ---- /spotlight/<run_id>/<swimmer_key> — spotlight view -------------
    @app.route("/spotlight/<run_id>/<path:swimmer_key>")
    def spotlight_view(run_id, swimmer_key):
        try:
            from mediahub.club_platform.athlete_spotlight import build_spotlight_pack
        except ImportError:
            return _layout("Spotlight", '<div class="card"><p class="muted">club_platform not available.</p></div>', active="create"), 501

        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        pack = build_spotlight_pack(run_data, swimmer_key)
        if not pack:
            return _layout("No data", f'<div class="empty">No achievements found for swimmer key "{_h(swimmer_key)}" in this run.</div>'), 404

        _back_url = url_for("spotlight_landing") + f"?run_id={run_id}"
        _review_url = url_for("review", run_id=run_id)
        _pack_url = url_for("content_pack", run_id=run_id)
        _wf_api_base = url_for('api_workflow_set', run_id=run_id, card_id='CARD_ID').replace('CARD_ID', '')
        import json as _json
        _wf_api_base_js = _json.dumps(_wf_api_base)

        # Load workflow state for this run so spotlight cards reflect current status.
        wf_states = {}
        try:
            ws = _get_wf_store()
            if ws:
                wf_states = ws.load(run_id)
        except Exception:
            wf_states = {}

        # Render achievements with full workflow controls.
        WF_PILL_STYLES = {
            "queue":    ("rgba(255,255,255,0.06)", "var(--ink-muted)"),
            "approved": ("rgba(34,197,94,0.15)", "#22C55E"),
            "rejected": ("rgba(244,63,94,0.15)", "#F43F5E"),
            "posted":   ("rgba(34,211,238,0.15)", "var(--accent)"),
            "edited":   ("rgba(245,158,11,0.15)", "var(--warn)"),
        }

        rows_html = ""
        for ra in pack["ranked_achievements"]:
            a = ra.get("achievement", {})
            band = ra.get("quality_band", "nice")
            prio = ra.get("priority", 0.0)
            rank = ra.get("rank", 0)
            band_cls = {"elite": "warn", "strong": "info", "story": "", "nice": "", "not_worthy": "bad"}.get(band, "")
            headline = _h(a.get("headline", ""))
            angle = _h(_humanise(a.get("angle_hint", "") or ""))
            event = _h(a.get("event", ""))
            atype = _h(_humanise(a.get("type", "")))
            card_id_raw = a.get("swim_id") or f"sp:{a.get('type','')}:{a.get('event','')}"
            card_id_safe = _h(card_id_raw)

            # Workflow status
            wf = wf_states.get(card_id_raw)
            wf_status = wf.status.value if wf else "queue"
            s_bg, s_fg = WF_PILL_STYLES.get(wf_status, WF_PILL_STYLES["queue"])

            # Caption text for copy
            cap_text = headline
            if angle:
                cap_text = f"{headline}\\n\\n{angle}"
            cap_text_safe = cap_text.replace('"', '&quot;')

            rows_html += f"""
<div class="sp-row" data-card="{card_id_safe}" style="padding:14px 0;border-bottom:1px solid var(--border);display:flex;gap:14px;align-items:flex-start">
  <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px">#{rank}</div>
  <div style="flex:1">
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap">
      <span class="tag {band_cls}" style="font-size:10px">{band.upper()}</span>
      <span class="tag info" style="font-size:10px">{atype}</span>
      <span class="muted" style="font-size:11px">{prio:.2f}</span>
      <button class="sp-pill wf-pill" data-run="{_h(run_id)}" data-card="{card_id_safe}" data-status="{wf_status}"
        style="border:none;cursor:pointer;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;background:{s_bg};color:{s_fg};font-family:inherit"
        title="Click: queue → approved → posted. Right-click for more options.">{wf_status}</button>
    </div>
    <div style="font-size:14px;font-weight:600;color:var(--ink)">{event}</div>
    <div style="font-size:13px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
      <button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="copySpotlightCaption(this, '{card_id_safe}')">Copy caption</button>
      <span id="sp-cap-{card_id_safe}" style="display:none">{cap_text}</span>
    </div>
  </div>
</div>"""

        body = f"""
<p class="dim"><a href="{_back_url}">← Back to swimmer list</a> · <a href="{_review_url}">Full meet review</a></p>
<h1>Spotlight: {_h(pack["swimmer_name"])}</h1>
<p class="dim">{_h(pack["meet_name"])}</p>

<div class="card">
  <div class="stat-block">
    <div class="stat"><div class="l" style="color:#F59E0B">Elite</div><div class="v" style="color:#F59E0B">{pack["n_elite"]}</div></div>
    <div class="stat"><div class="l" style="color:#22D3EE">Strong</div><div class="v" style="color:#22D3EE">{pack["n_strong"]}</div></div>
    <div class="stat"><div class="l" style="color:#A78BFA">Story</div><div class="v" style="color:#A78BFA">{pack["n_story"]}</div></div>
    <div class="stat"><div class="l">Total</div><div class="v">{pack["n_achievements"]}</div></div>
  </div>
  <div style="margin-top:14px">
    <a class="btn secondary" href="{_pack_url}" style="font-size:13px">Open content pack →</a>
    <span class="muted" style="font-size:12px;margin-left:8px">Approve cards below to add them to the pack.</span>
  </div>
</div>

<div class="card">
  <h2>Achievements</h2>
  {rows_html or '<p class="muted">No achievements.</p>'}
</div>

<script>
const SP_WF_API_BASE = {_wf_api_base_js};
const SP_WF_CYCLE = ['queue','approved','posted'];
const SP_WF_COLOURS = {{
  queue:    ['rgba(255,255,255,0.06)','var(--ink-muted)'],
  approved: ['rgba(34,197,94,0.15)','#22C55E'],
  rejected: ['rgba(244,63,94,0.15)','#F43F5E'],
  posted:   ['rgba(34,211,238,0.15)','var(--accent)'],
  edited:   ['rgba(245,158,11,0.15)','var(--warn)'],
}};
function _spApply(btn, next) {{
  var cur = btn.dataset.status || 'queue';
  var cardId = btn.dataset.card;
  btn.textContent = next;
  btn.dataset.status = next;
  var cols = SP_WF_COLOURS[next] || SP_WF_COLOURS.queue;
  btn.style.background = cols[0];
  btn.style.color = cols[1];
  var url = SP_WF_API_BASE + encodeURIComponent(cardId);
  fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:'set_status',status:next}})}})
    .then(r=>r.json())
    .then(j=>{{ if(!j.ok){{btn.textContent=cur;btn.dataset.status=cur;}} }})
    .catch(()=>{{btn.textContent=cur;btn.dataset.status=cur;}});
}}
document.addEventListener('click', function(e) {{
  var btn = e.target.closest('.sp-pill');
  if (!btn) return;
  var cur = btn.dataset.status || 'queue';
  var idx = SP_WF_CYCLE.indexOf(cur);
  var next = idx === -1 ? 'approved' : SP_WF_CYCLE[(idx + 1) % SP_WF_CYCLE.length];
  _spApply(btn, next);
}});
document.addEventListener('contextmenu', function(e) {{
  var btn = e.target.closest('.sp-pill');
  if (!btn) return;
  e.preventDefault();
  var cur = btn.dataset.status || 'queue';
  _spApply(btn, cur === 'rejected' ? 'queue' : 'rejected');
}});
function copySpotlightCaption(btn, cardIdSafe) {{
  var span = document.getElementById('sp-cap-' + cardIdSafe);
  if (!span) {{ btn.textContent = 'Error'; return; }}
  var text = span.textContent.trim();
  var done = function(ok) {{
    btn.textContent = ok ? 'Copied!' : 'Copy failed';
    setTimeout(function(){{ btn.textContent = 'Copy caption'; }}, 1800);
  }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function(){{done(true);}}).catch(function(){{fb();}});
  }} else {{
    fb();
  }}
  function fb() {{
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try {{ done(document.execCommand('copy')); }} catch (e) {{ done(false); }}
    document.body.removeChild(ta);
  }}
}}
</script>
"""
        return _layout(f"Spotlight: {pack['swimmer_name']}", body, active="create")

    # ---- Stub routes (now functional with real LLM + fallback) ---------
    _STUB_TYPE_BY_CLASS = {
        "WeekendPreviewStub": "weekend_preview",
        "SponsorPostStub":    "sponsor_post",
        "SessionUpdateStub":  "session_update",
        "FreeTextStub":       "free_text",
    }

    def _render_stub(stub_cls_name: str, route_endpoint: str, title: str,
                     active_tab: str = "add_input"):
        """Shared handler for stub routes. GET renders form, POST renders cards."""
        try:
            from mediahub.club_platform import stubs as _stubs_mod
        except Exception as exc:
            body = (
                '<div class="card"><h2>Temporarily unavailable</h2>'
                f'<p class="muted">Content engine failed to load: {_h(str(exc))}</p></div>'
            )
            return _layout(title, body, active=active_tab)

        StubCls = getattr(_stubs_mod, stub_cls_name, None)
        if StubCls is None:
            body = '<div class="card"><p class="muted">This content type is not available.</p></div>'
            return _layout(title, body, active=active_tab)

        stub = StubCls()
        if request.method == "POST":
            form_data = request.form.to_dict(flat=True)
            try:
                cards_payload = stub.generate_cards(form_data)
            except Exception:
                app.logger.exception("stub generate_cards failed")
                cards_payload = {"cards": []}
            # Persist this pack so it survives refresh + is exportable.
            saved = None
            try:
                from mediahub.club_platform.stub_pack_store import save_pack
                saved = save_pack(
                    _STUB_TYPE_BY_CLASS.get(stub_cls_name, "other"),
                    form_data,
                    cards_payload.get("cards") or [],
                )
            except Exception:
                app.logger.exception("stub save_pack failed")
            back = url_for(route_endpoint)
            actions_url = url_for("stub_pack_view", pack_id=saved["pack_id"]) if saved else None
            body = _stubs_mod.render_cards_html(cards_payload, back, f"{title} — drafts")
            if saved:
                _packs_url = url_for("stub_packs_list")
                body = body.replace(
                    f'<a class="btn secondary" href="{_h(back)}">← Start over</a>',
                    (
                        f'<a class="btn" href="{_h(actions_url)}">View & export this pack →</a>'
                        f'<a class="btn secondary" href="{_h(back)}">← Start over</a>'
                        f'<a class="btn secondary" href="{_h(_packs_url)}">All saved drafts</a>'
                    ),
                    1,
                )
            return _layout(title, body, active=active_tab)
        # GET — render form
        body = stub.render_stub_html()
        try:
            _packs_url = url_for("stub_packs_list")
            body += (
                f'<p style="margin-top:16px;display:flex;gap:14px;flex-wrap:wrap">'
                f'<a href="{_packs_url}">View your saved drafts →</a>'
                f'<a href="{url_for("make_page")}">← Back to Make</a>'
                f'</p>'
            )
        except Exception:
            body += f'<p style="margin-top:16px"><a href="{url_for("make_page")}">← Back to Make</a></p>'
        return _layout(title, body, active=active_tab)

    @app.route("/weekend-preview", methods=["GET", "POST"])
    def stub_weekend_preview():
        return _render_stub("WeekendPreviewStub", "stub_weekend_preview", "Event Preview")

    @app.route("/sponsor-post", methods=["GET", "POST"])
    def stub_sponsor_post():
        return _render_stub("SponsorPostStub", "stub_sponsor_post", "Sponsor Post")

    @app.route("/session-update", methods=["GET", "POST"])
    def stub_session_update():
        return _render_stub("SessionUpdateStub", "stub_session_update", "Session Update")

    @app.route("/free-text", methods=["GET", "POST"])
    def stub_free_text():
        return _render_stub("FreeTextStub", "stub_free_text", "Free Text")

    # ---- Saved stub packs — list + view + export -----------------------
    _STUB_TYPE_LABEL = {
        "free_text":        "Free Text",
        "weekend_preview":  "Event Preview",
        "sponsor_post":     "Sponsor Post",
        "session_update":   "Session Update",
    }

    @app.route("/drafts")
    def stub_packs_list():
        from mediahub.club_platform.stub_pack_store import list_packs
        items = list_packs(limit=100)
        if not items:
            body = f"""
<h1>Saved drafts</h1>
<p class="dim">Content packs you generate from Free Text, Event Preview, Sponsor Post and Session Update are saved here.</p>
<div class="card" style="text-align:center;padding:48px 28px">
  <div style="font-size:42px;margin-bottom:12px">📝</div>
  <h2 style="margin-bottom:6px">No drafts yet</h2>
  <p class="dim" style="margin-bottom:18px">Generate your first content cards from the Add Input page.</p>
  <a class="btn" href="{url_for('add_input_page')}">Add input →</a>
</div>
"""
            return _layout("Saved drafts", body, active="add_input")

        rows_html = ""
        for it in items:
            view_url = url_for("stub_pack_view", pack_id=it["pack_id"])
            delete_url = url_for("stub_pack_delete", pack_id=it["pack_id"])
            label = _STUB_TYPE_LABEL.get(it["stub_type"], it["stub_type"])
            ts = (it.get("created_at") or "")[:19].replace("T", " ")
            rows_html += (
                f'<tr><td><a href="{view_url}">{_h(it["title"])}</a></td>'
                f'<td><span class="tag info">{_h(label)}</span></td>'
                f'<td>{it["n_cards"]}</td>'
                f'<td class="muted">{_h(ts)}</td>'
                f'<td><form method="post" action="{delete_url}" style="display:inline" '
                f'onsubmit="return confirm(\'Delete this draft?\')">'
                f'<button class="btn secondary" type="submit" style="font-size:11px;padding:4px 10px;color:var(--bad);border-color:rgba(244,63,94,0.3)">Delete</button>'
                f'</form></td></tr>'
            )

        body = f"""
<h1>Saved drafts</h1>
<p class="dim">{len(items)} pack{'s' if len(items)!=1 else ''} saved.</p>
<div class="card">
  <table>
    <thead><tr><th>Title</th><th>Type</th><th>Cards</th><th>Created</th><th></th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<p style="margin-top:14px"><a class="btn secondary" href="{url_for('add_input_page')}">+ New draft</a></p>
"""
        return _layout("Saved drafts", body, active="add_input")

    @app.route("/drafts/<pack_id>")
    def stub_pack_view(pack_id):
        from mediahub.club_platform.stub_pack_store import load_pack
        from mediahub.club_platform.stubs import render_cards_html
        rec = load_pack(pack_id)
        if not rec:
            body = '<div class="empty">Draft not found.</div>'
            return _layout("Draft not found", body, active="add_input"), 404

        stub_type = rec.get("stub_type", "other")
        type_label = _STUB_TYPE_LABEL.get(stub_type, stub_type)
        # We pass back = saved-list so "Start over" goes somewhere sensible.
        back_url = url_for("stub_packs_list")
        cards_html = render_cards_html(
            {"cards": rec.get("cards") or []},
            back_url,
            rec.get("title") or "Draft pack",
        )
        # Replace the renderer's default footer to add export + regenerate.
        export_url = url_for("stub_pack_export", pack_id=pack_id)
        regenerate_url = url_for({
            "free_text":       "stub_free_text",
            "weekend_preview": "stub_weekend_preview",
            "sponsor_post":    "stub_sponsor_post",
            "session_update":  "stub_session_update",
        }.get(stub_type, "stub_free_text"))
        footer = (
            f'<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">'
            f'<a class="btn" href="{export_url}">Export as text</a>'
            f'<a class="btn secondary" href="{regenerate_url}">Generate new draft</a>'
            f'<a class="btn secondary" href="{back_url}">← All drafts</a>'
            f'</div>'
        )
        # Prepend a context band showing the type + timestamp.
        ts = (rec.get("created_at") or "")[:19].replace("T", " ")
        header = (
            f'<p class="dim" style="margin-bottom:14px">'
            f'<span class="tag info">{_h(type_label)}</span> '
            f'<span style="margin-left:8px">Generated {_h(ts)}</span></p>'
        )
        # Replace the renderer's default action row
        cards_html = cards_html.replace(
            f'<div style="margin-top:24px;display:flex;gap:10px">'
            f'<a class="btn secondary" href="{_h(back_url)}">← Start over</a>'
            f'</div>',
            footer,
            1,
        )
        body = header + cards_html
        return _layout(rec.get("title") or "Draft", body, active="add_input")

    @app.route("/drafts/<pack_id>/export.txt")
    def stub_pack_export(pack_id):
        from mediahub.club_platform.stub_pack_store import load_pack, export_pack_text
        rec = load_pack(pack_id)
        if not rec:
            return ("Pack not found", 404)
        text = export_pack_text(rec)
        return Response(
            text,
            mimetype="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{pack_id}.txt"',
            },
        )

    @app.route("/drafts/<pack_id>/delete", methods=["POST"])
    def stub_pack_delete(pack_id):
        from mediahub.club_platform.stub_pack_store import delete_pack
        delete_pack(pack_id)
        return redirect(url_for("stub_packs_list"))

    # ---- /add-input — multi-input landing page --------------------------
    @app.route("/add-input")
    def add_input_page():
        _INPUT_TYPES = [
            {
                "title": "Meet Results",
                "description": "Upload results from any sport meet, gala, or competition. Ranked content cards with confidence scores.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/>'
                    '<path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
                    '<path d="M4 22h16"/>'
                    '<path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
                    '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
                    '<path d="M18 2H6v7a6 6 0 0 0 12 0V2z"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "upload",
            },
            {
                "title": "Athlete Spotlight",
                "description": "Pick a member from a processed meet and get a single-person achievement pack.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<circle cx="12" cy="8" r="4"/>'
                    '<path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "spotlight_landing",
            },
            {
                "title": "Event Preview",
                "description": "Tease an upcoming event, fixture, or competition before it starts.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
                    '<line x1="16" y1="2" x2="16" y2="6"/>'
                    '<line x1="8" y1="2" x2="8" y2="6"/>'
                    '<line x1="3" y1="10" x2="21" y2="10"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_weekend_preview",
            },
            {
                "title": "Sponsor Post",
                "description": "Create brand-safe sponsor activation content with your partners.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_sponsor_post",
            },
            {
                "title": "Session Update",
                "description": "Share live updates from training or events as they happen.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                    '<polyline points="14 2 14 8 20 8"/>'
                    '<line x1="16" y1="13" x2="8" y2="13"/>'
                    '<line x1="16" y1="17" x2="8" y2="17"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_session_update",
            },
            {
                "title": "Free Text",
                "description": "Describe any moment in your own words and get content suggestions.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<path d="M12 20h9"/>'
                    '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_free_text",
            },
        ]

        cards_html = ""
        for card in _INPUT_TYPES:
            is_live = card["status"] == "live"
            if is_live:
                badge = '<span class="tag good" style="font-size:11px">Live</span>'
                btn_label = "Start →"
            else:
                badge = '<span class="tag" style="font-size:11px">Coming soon</span>'
                btn_label = "Preview →"
            try:
                card_url = url_for(card["endpoint"])
                href_attr = f'href="{card_url}"'
            except Exception:
                href_attr = 'href="#" onclick="return false"'
            cards_html += f"""
<a {href_attr} class="input-type-card" style="text-decoration:none;display:flex;flex-direction:column;
   gap:14px;padding:24px;background:var(--panel);border:1px solid var(--border);
   border-radius:var(--radius);transition:border-color 150ms,box-shadow 150ms">
  <div style="color:var(--accent)">{card['icon']}</div>
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
    <div style="font-size:16px;font-weight:700;color:var(--ink)">{_h(card['title'])}</div>
    {badge}
  </div>
  <div style="font-size:13px;color:var(--ink-dim);line-height:1.5">{_h(card['description'])}</div>
  <div style="margin-top:auto">
    <span class="btn" style="font-size:13px;padding:7px 14px">{btn_label}</span>
  </div>
</a>"""

        body = f"""
<style>
.input-type-card:hover {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
</style>
<h1>Add Input</h1>
<p class="dim" style="margin-bottom:28px">
  Choose the type of content you want to create. Each input type produces a different set of social-ready cards.
</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px">
  {cards_html}
</div>
"""
        return _layout("Add Input", body, active="add_input")

    # ---- /organisation — organisation DNA / club identity ---------------
    @app.route("/organisation", methods=["GET", "POST"])
    def organisation_page():
        _ORG_TYPES = [
            ("other", "Other / general"),
            ("swimming_club", "Swimming club"),
            ("athletics", "Athletics club"),
            ("football", "Football / rugby / team sport"),
            ("university_society", "University society or sports club"),
            ("corporate_team", "Corporate team"),
        ]
        _PLATFORMS = [
            ("instagram", "Instagram"),
            ("tiktok", "TikTok"),
            ("twitter", "Twitter / X"),
            ("facebook", "Facebook"),
            ("linkedin", "LinkedIn"),
        ]
        _TONES = [
            ("warm-club", "Warm &amp; community — conversational, member-facing, first-name use"),
            ("hype", "Energetic &amp; hype — race-day language, exclamation marks, high energy"),
            ("data-led", "Data-led — numbers-first, precise, sponsor-friendly"),
        ]

        saved_msg = ""
        capture_preview = ""      # rendered preview HTML when a capture has just run
        capture_error = ""        # rendered error banner when capture failed
        # The capture preview is kept in-memory only — the user must click
        # "Save organisation" to persist it (no silent writes).
        if request.method == "POST":
            action = (request.form.get("action") or "save").strip().lower()
            raw_id = (request.form.get("profile_id") or "default").strip().lower()
            profile_id = re.sub(r"[^a-z0-9_-]", "-", raw_id).strip("-") or "default"
            existing = load_profile(profile_id) or ClubProfile(
                profile_id=profile_id,
                display_name=request.form.get("display_name") or profile_id,
            )

            if action == "capture":
                # ---- Brand DNA capture from website URL ----
                target_url = (request.form.get("brand_source_url") or "").strip()
                if not target_url:
                    capture_error = (
                        '<p class="tag bad" style="margin-bottom:20px">'
                        'Enter a website URL to analyse.</p>'
                    )
                    profile = existing
                else:
                    try:
                        from mediahub.brand.dna_capture import capture_brand_dna
                        result = capture_brand_dna(target_url, force=False)
                    except Exception as e:
                        result = {"brand_capture_status": f"error: {e}"}
                    status = (result or {}).get("brand_capture_status", "")
                    if status in ("ok", "ok_heuristic"):
                        # Merge captured fields into the in-memory profile so
                        # the preview shows them, but DON'T save until the user
                        # clicks "Save organisation".
                        for k in (
                            "brand_voice_summary", "brand_keywords",
                            "brand_palette_extracted", "brand_logo_url",
                            "brand_typography_hint", "brand_phrases_to_avoid",
                            "brand_phrases_to_use", "brand_source_url",
                            "brand_captured_at", "brand_capture_status",
                        ):
                            if k in result:
                                setattr(existing, k, result[k])
                        # Adopt extracted palette into primary/secondary if
                        # the existing profile is still on the default colours.
                        pal = result.get("brand_palette_extracted") or {}
                        if pal.get("primary") and existing.brand_primary in (
                            "", "#0A2540", "#A30D2D",
                        ):
                            existing.brand_primary = pal["primary"]
                        if pal.get("secondary") and existing.brand_secondary in (
                            "", "#000000",
                        ):
                            existing.brand_secondary = pal["secondary"]
                        note = (
                            "Captured from website — review below and click "
                            "Save organisation to persist."
                            if status == "ok"
                            else "Captured from website (no LLM available, "
                                 "heuristic fallback). Edit and save."
                        )
                        capture_preview = (
                            f'<p class="tag info" style="margin-bottom:20px">'
                            f'{_h(note)}</p>'
                        )
                    else:
                        # Surface the failure clearly but keep the form usable.
                        reason = {
                            "missing_url": "No URL was provided.",
                            "fetch_failed": "Could not reach that URL — check it loads in a browser.",
                        }.get(status, f"Capture failed ({_h(status or 'unknown error')}).")
                        capture_error = (
                            f'<p class="tag bad" style="margin-bottom:20px">'
                            f'{_h(reason)}</p>'
                        )
                profile = existing

            else:
                # ---- Save organisation (existing behaviour) ----
                existing.display_name = (request.form.get("display_name") or existing.display_name).strip()
                existing.short_name = (request.form.get("short_name") or "").strip()
                existing.org_type = (request.form.get("org_type") or "other").strip()
                existing.governing_body = (request.form.get("governing_body") or "").strip()
                existing.country = (request.form.get("country") or "").strip()
                # Club / result codes — comma-separated
                codes_raw = request.form.get("club_codes") or ""
                existing.club_codes = [c.strip() for c in codes_raw.split(",") if c.strip()]
                # Brand colours
                existing.brand_primary = (request.form.get("brand_primary") or existing.brand_primary or "#0A2540").strip()
                existing.brand_secondary = (request.form.get("brand_secondary") or existing.brand_secondary or "#000000").strip()
                # Tone
                existing.tone = (request.form.get("tone") or "warm-club").strip()
                existing.caption_tone = existing.tone
                # Platforms
                existing.platforms = [p.strip() for p in request.form.getlist("platforms") if p.strip()]
                # Voice
                existing.tone_notes = (request.form.get("tone_notes") or "").strip()
                raw_exemplars = (request.form.get("exemplar_captions") or "").strip()
                if raw_exemplars:
                    parts = [p.strip() for p in raw_exemplars.split("---") if p.strip()]
                    existing.exemplar_captions = parts[:5]
                else:
                    existing.exemplar_captions = []
                # Sponsor
                existing.sponsor_name = (request.form.get("sponsor_name") or "").strip()
                existing.sponsor_guidelines = (request.form.get("sponsor_guidelines") or "").strip()
                # Brand DNA — persist any captured fields submitted via hidden
                # inputs from a prior capture preview. We accept simple scalars
                # plus JSON-encoded lists/dicts for the structured fields.
                def _hidden_list(name: str) -> list[str]:
                    raw = (request.form.get(name) or "").strip()
                    if not raw:
                        return []
                    try:
                        v = json.loads(raw)
                        if isinstance(v, list):
                            return [str(x) for x in v]
                    except Exception:
                        return []
                    return []

                def _hidden_dict(name: str) -> dict:
                    raw = (request.form.get(name) or "").strip()
                    if not raw:
                        return {}
                    try:
                        v = json.loads(raw)
                        if isinstance(v, dict):
                            return v
                    except Exception:
                        return {}
                    return {}

                existing.brand_voice_summary = (request.form.get("brand_voice_summary") or "").strip()
                existing.brand_logo_url = (request.form.get("brand_logo_url") or "").strip()
                existing.brand_typography_hint = (request.form.get("brand_typography_hint") or "").strip()
                existing.brand_source_url = (request.form.get("brand_source_url_saved") or "").strip()
                existing.brand_captured_at = (request.form.get("brand_captured_at") or "").strip()
                existing.brand_capture_status = (request.form.get("brand_capture_status") or "").strip()
                existing.brand_keywords = _hidden_list("brand_keywords_json")
                existing.brand_phrases_to_use = _hidden_list("brand_phrases_to_use_json")
                existing.brand_phrases_to_avoid = _hidden_list("brand_phrases_to_avoid_json")
                existing.brand_palette_extracted = _hidden_dict("brand_palette_extracted_json")
                save_profile(existing)
                saved_msg = '<p class="tag good" style="margin-bottom:20px">Organisation saved.</p>'
                profile = existing
        else:
            profiles = list_profiles()
            profile = profiles[0] if profiles else ClubProfile(profile_id="default", display_name="")

        # Build select/checkbox HTML helpers
        def _opt(val, label, selected):
            sel = " selected" if selected else ""
            return f'<option value="{_h(val)}"{sel}>{_h(label)}</option>'

        def _radio(name, val, label, checked):
            chk = " checked" if checked else ""
            return (f'<label style="display:block;margin-bottom:8px;cursor:pointer">'
                    f'<input type="radio" name="{_h(name)}" value="{_h(val)}"{chk} style="margin-right:6px">'
                    f'{label}</label>')

        def _cb(name, val, label, checked):
            chk = " checked" if checked else ""
            return (f'<label style="display:inline-flex;align-items:center;gap:6px;'
                    f'margin-right:16px;margin-bottom:8px;cursor:pointer">'
                    f'<input type="checkbox" name="{_h(name)}" value="{_h(val)}"{chk}>'
                    f'{_h(label)}</label>')

        org_type_opts = "".join(_opt(v, l, v == (profile.org_type or "other")) for v, l in _ORG_TYPES)
        tone_radios = "".join(_radio("tone", v, l, v == (profile.tone or "warm-club")) for v, l in _TONES)
        platform_cbs = "".join(_cb("platforms", v, l, v in (profile.platforms or [])) for v, l in _PLATFORMS)
        exemplars_text = "\n---\n".join(profile.exemplar_captions or [])

        _input_style = "width:100%;max-width:480px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--ink);font-size:14px"
        _ta_style = "width:100%;max-width:600px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--ink);font-family:inherit;font-size:14px"

        # ---- Brand DNA preview block (rendered when fields are populated) ----
        def _swatch(hexv: str) -> str:
            if not hexv:
                return ""
            return (
                f'<div title="{_h(hexv)}" style="display:inline-flex;align-items:center;'
                f'gap:6px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;'
                f'margin-right:6px;margin-bottom:6px;background:var(--panel)">'
                f'<span style="display:inline-block;width:18px;height:18px;border-radius:4px;'
                f'background:{_h(hexv)};border:1px solid rgba(255,255,255,0.15)"></span>'
                f'<code style="font-size:11px;color:var(--ink)">{_h(hexv)}</code></div>'
            )

        def _chip(text: str, tone: str = "neutral") -> str:
            colour = {
                "good": "var(--accent)",
                "warn": "#ffae3b",
                "bad": "#ff5d6c",
                "neutral": "var(--ink-dim)",
            }.get(tone, "var(--ink-dim)")
            return (
                f'<span style="display:inline-block;padding:2px 8px;margin:2px 4px 2px 0;'
                f'border:1px solid var(--border);border-radius:999px;font-size:11px;'
                f'color:{colour};background:rgba(255,255,255,0.02)">{_h(text)}</span>'
            )

        brand_preview_html = ""
        has_brand = bool(
            (profile.brand_voice_summary or "").strip()
            or profile.brand_keywords
            or profile.brand_palette_extracted
            or profile.brand_logo_url
            or profile.brand_phrases_to_use
            or profile.brand_phrases_to_avoid
        )
        if has_brand:
            pal = profile.brand_palette_extracted or {}
            swatches = "".join(_swatch(pal.get(k, "")) for k in ("primary", "secondary", "accent") if pal.get(k))
            keywords_html = "".join(_chip(k, "neutral") for k in (profile.brand_keywords or [])[:12])
            use_html = "".join(_chip(p, "good") for p in (profile.brand_phrases_to_use or [])[:5])
            avoid_html = "".join(_chip(p, "bad") for p in (profile.brand_phrases_to_avoid or [])[:5])
            logo_html = ""
            if profile.brand_logo_url:
                logo_html = (
                    f'<img src="{_h(profile.brand_logo_url)}" alt="Detected logo" '
                    f'style="max-height:60px;max-width:200px;background:var(--panel);'
                    f'padding:6px;border:1px solid var(--border);border-radius:6px"/>'
                )
            captured_meta = ""
            if profile.brand_captured_at or profile.brand_source_url:
                src = profile.brand_source_url or ""
                ts = profile.brand_captured_at or ""
                status = profile.brand_capture_status or ""
                captured_meta = (
                    f'<p style="font-size:11px;color:var(--ink-dim);margin-top:8px">'
                    f'Source: <a href="{_h(src)}" target="_blank" rel="noopener" '
                    f'style="color:var(--ink-dim)">{_h(src)}</a> · '
                    f'captured {_h(ts)} · status {_h(status)}'
                    f'</p>'
                )
            brand_preview_html = f"""
<div class="card" style="margin-bottom:20px;border:1px dashed var(--border);background:rgba(34,211,238,0.03)">
  <h3 style="margin-top:0;margin-bottom:12px;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Brand DNA preview</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Voice summary</div>
      <p style="margin:0;font-size:13px;color:var(--ink);line-height:1.5">{_h(profile.brand_voice_summary or '(no summary yet)')}</p>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Palette</div>
      <div>{swatches or '<span class="dim" style="font-size:12px">(none detected)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Typography hint</div>
      <p style="margin:0;font-size:13px;color:var(--ink)">{_h(profile.brand_typography_hint or '—')}</p>
    </div>
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Detected logo</div>
      <div>{logo_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Keywords</div>
      <div>{keywords_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Phrases to use</div>
      <div>{use_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Phrases to avoid</div>
      <div>{avoid_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
    </div>
  </div>
  {captured_meta}
</div>
"""

        # Hidden inputs that carry the captured brand fields through the
        # next form submission so a click on Save persists them.
        brand_hidden_inputs = (
            f'<input type="hidden" name="brand_voice_summary" value="{_h(profile.brand_voice_summary or "")}"/>'
            f'<input type="hidden" name="brand_logo_url" value="{_h(profile.brand_logo_url or "")}"/>'
            f'<input type="hidden" name="brand_typography_hint" value="{_h(profile.brand_typography_hint or "")}"/>'
            f'<input type="hidden" name="brand_source_url_saved" value="{_h(profile.brand_source_url or "")}"/>'
            f'<input type="hidden" name="brand_captured_at" value="{_h(profile.brand_captured_at or "")}"/>'
            f'<input type="hidden" name="brand_capture_status" value="{_h(profile.brand_capture_status or "")}"/>'
            f'<input type="hidden" name="brand_keywords_json" value="{_h(json.dumps(profile.brand_keywords or []))}"/>'
            f'<input type="hidden" name="brand_phrases_to_use_json" value="{_h(json.dumps(profile.brand_phrases_to_use or []))}"/>'
            f'<input type="hidden" name="brand_phrases_to_avoid_json" value="{_h(json.dumps(profile.brand_phrases_to_avoid or []))}"/>'
            f'<input type="hidden" name="brand_palette_extracted_json" value="{_h(json.dumps(profile.brand_palette_extracted or {}))}"/>'
        )

        body = f"""
{saved_msg}{capture_preview}{capture_error}
<h1>Organisation</h1>
<p class="dim" style="margin-bottom:24px">Tell MediaHub about your club, society or team so the AI can produce on-brand content.</p>

<div class="card" style="margin-bottom:20px;border:1px solid var(--accent);background:rgba(34,211,238,0.04)">
  <h2 style="margin-top:0">Capture from website</h2>
  <p class="dim" style="margin-bottom:12px;font-size:13px">Paste your club's website URL and MediaHub will extract the palette, logo, voice and keywords automatically. The result appears below — review and click Save organisation to persist.</p>
  <form method="POST" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <input type="hidden" name="action" value="capture"/>
    <input type="hidden" name="profile_id" value="{_h(profile.profile_id)}"/>
    <input type="hidden" name="display_name" value="{_h(profile.display_name)}"/>
    <input type="url" name="brand_source_url" value="{_h(profile.brand_source_url or '')}"
           placeholder="https://your-club.example"
           style="{_input_style};max-width:520px;flex:1" required/>
    <button type="submit" class="btn">Analyse →</button>
  </form>
</div>

{brand_preview_html}

<form method="POST">
<input type="hidden" name="action" value="save"/>
<input type="hidden" name="profile_id" value="{_h(profile.profile_id)}"/>
{brand_hidden_inputs}

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Identity</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px 24px;max-width:700px">
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Organisation name</label>
      <input type="text" name="display_name" value="{_h(profile.display_name)}" placeholder="e.g. City Aquatics Club"
             style="{_input_style}" required/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Short name</label>
      <input type="text" name="short_name" value="{_h(profile.short_name)}" placeholder="e.g. City AC"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Organisation type</label>
      <select name="org_type" style="{_input_style}">{org_type_opts}</select>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Governing body</label>
      <input type="text" name="governing_body" value="{_h(profile.governing_body)}" placeholder="e.g. Swim England, UKA"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Country</label>
      <input type="text" name="country" value="{_h(profile.country)}" placeholder="e.g. United Kingdom"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Result file codes</label>
      <input type="text" name="club_codes" value="{_h(', '.join(profile.club_codes or []))}"
             placeholder="e.g. CMA, COMA" style="{_input_style}"/>
      <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Comma-separated codes that identify your members in results files.</p>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Primary colour</label>
      <input type="color" name="brand_primary" value="{_h(profile.brand_primary or '#0A2540')}"
             style="height:38px;width:80px;padding:2px;border:1px solid var(--border);border-radius:6px;cursor:pointer"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Secondary colour</label>
      <input type="color" name="brand_secondary" value="{_h(profile.brand_secondary or '#000000')}"
             style="height:38px;width:80px;padding:2px;border:1px solid var(--border);border-radius:6px;cursor:pointer"/>
    </div>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Voice &amp; Tone</h2>
  <div style="margin-bottom:16px">
    <label style="display:block;font-weight:600;margin-bottom:8px;font-size:14px">Caption tone</label>
    {tone_radios}
  </div>
  <div style="margin-bottom:16px">
    <label style="display:block;font-weight:600;margin-bottom:8px;font-size:14px">Active platforms</label>
    {platform_cbs}
  </div>
  <div style="margin-bottom:16px">
    <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Brand voice notes</label>
    <textarea name="tone_notes" rows="3" placeholder="Any guidelines, phrases you use, things to avoid..."
              style="{_ta_style}">{_h(profile.tone_notes or "")}</textarea>
  </div>
  <div>
    <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Example captions</label>
    <textarea name="exemplar_captions" rows="6"
              placeholder="Paste up to 5 past captions that represent your voice.&#10;Separate each one with --- on its own line."
              style="{_ta_style}">{_h(exemplars_text)}</textarea>
    <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Separate captions with <code>---</code> on its own line. Up to 5 examples.</p>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Sponsors</h2>
  <div style="display:grid;grid-template-columns:1fr;gap:16px;max-width:600px">
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Primary sponsor name</label>
      <input type="text" name="sponsor_name" value="{_h(profile.sponsor_name or '')}"
             placeholder="e.g. Acme Sports" style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Sponsor guidelines</label>
      <textarea name="sponsor_guidelines" rows="3"
                placeholder="Hashtags to include, mentions required, things to avoid..."
                style="{_ta_style}">{_h(profile.sponsor_guidelines or "")}</textarea>
    </div>
  </div>
</div>

<div style="margin-top:8px">
  <button type="submit" class="btn">Save organisation</button>
</div>
</form>
"""
        return _layout("Organisation", body, active="organisation")

    # ---- /pack/<run_id> — content pack (V7.3 grouped is default; old approval-only at /pack/<run_id>/approved) ---
    @app.route("/pack/<run_id>")
    def content_pack(run_id):
        # V7.3: redirect to the grouped pack which shows engine recommendations
        # in 8 buckets (main_feed, stories, athlete_spotlights, weekend_recap,
        # weekend_in_numbers, internal_notes, needs_review, rejected).
        if _v73_ok and _build_grouped_pack is not None:
            return redirect(url_for("content_pack_grouped", run_id=run_id))
        # Pre-V7.3 fallback: legacy approval-based pack
        return content_pack_approved_only(run_id)

    def content_pack_approved_only(run_id):
        """Legacy V7 approval-only pack. Reachable via /pack/<run_id>/approved."""
        if _run_state(run_id) == "in_progress":
            return _layout("Still processing", _in_progress_page(run_id, "content_pack_approved_only"), active="home")
        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        profile_id = run_data.get("profile_id", "")
        try:
            from mediahub.workflow.pack import build_content_pack as _bcp
            approved = _bcp(run_id, profile_id, RUNS_DIR)
        except Exception as e:
            approved = []

        _review_url = url_for("review", run_id=run_id)
        _mark_all_url = url_for("api_workflow_mark_all_posted", run_id=run_id)
        meet_name = _h(run_data.get("meet", {}).get("name", "") or run_data.get("profile_display", ""))

        if not approved:
            body = f"""
<p class="dim"><a href="{_review_url}">← Back to review</a></p>
<h1>Content Pack — {meet_name}</h1>
<div class="card empty">No approved cards yet. Go to <a href="{_review_url}">the review page</a> and approve some cards first.</div>
"""
            return _layout("Content Pack", body, active="home")

        cards_html = ""
        for card in approved:
            ach = card.get("achievement") or {}
            swimmer = _h(ach.get("swimmer_name", ""))
            event = _h(ach.get("event", ""))
            headline = _h(ach.get("headline", ""))
            active_cap = card.get("active_caption") or {}
            brand_captions = card.get("brand_captions") or {}
            cap_headline = _h(active_cap.get("headline", ""))
            cap_body = _h(active_cap.get("body", ""))
            cap_cta = _h(active_cap.get("cta", ""))
            card_id_raw = card.get("_card_id", ach.get("swim_id", ""))
            card_id = _h(card_id_raw)
            card_uuid = str(card_id_raw).replace(":", "_").replace(",", "_")
            wf = card.get("workflow") or {}
            scheduled = _h(card.get("scheduled_for", ""))

            # V7.4: Multi-tone picker for content pack
            if brand_captions:
                tone_labels = {"warm-club": "Warm club", "hype": "Hype", "data-led": "Data-led"}
                pk_tabs = ""
                pk_panels = ""
                for pi, (t_key, t_label) in enumerate(tone_labels.items()):
                    tc = brand_captions.get(t_key) or {}
                    is_active = pi == 0
                    display_style = "" if is_active else "display:none"
                    tc_hl = _h(tc.get("headline", ""))
                    tc_bd = _h(tc.get("body", ""))
                    tc_ct = _h(tc.get("cta", ""))
                    plain = f"{tc.get('headline','') or ''} {tc.get('body','') or ''} {tc.get('cta','') or ''}".strip()
                    pk_tabs += (
                        f'<button class="tone-tab {("active" if is_active else "")}" '
                        f'data-card="pc-{card_uuid}" data-tone="{t_key}" onclick="switchTone(this)" '
                        f'style="font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--border);cursor:pointer;'
                        f'background:{("rgba(34,211,238,0.15)" if is_active else "transparent")};'
                        f'color:{("var(--accent)" if is_active else "var(--ink-dim)")};font-family:inherit;margin-right:4px">'
                        f'{t_label}</button>'
                    )
                    pk_panels += (
                        f'<div class="tone-panel" data-tone="{t_key}" data-card="pc-{card_uuid}" style="{display_style}">'
                        f'<div style="font-size:14px;font-weight:700;margin-bottom:4px">{tc_hl}</div>'
                        f'<div style="font-size:13px;color:var(--ink-dim);margin-bottom:4px">{tc_bd}</div>'
                        f'<div style="font-size:12px;color:var(--accent)">{tc_ct}</div>'
                        f'<textarea id="tone-text-pc-{card_uuid}-{t_key}" style="display:none">{plain}</textarea>'
                        f'</div>'
                    )
                inner_html = (
                    f'<div style="margin-bottom:6px">{pk_tabs}</div>'
                    f'<div class="tone-panels" data-card="pc-{card_uuid}">{pk_panels}</div>'
                )
            else:
                inner_parts = []
                if cap_headline and cap_headline != "—":
                    inner_parts.append(f'<div style="font-size:14px;font-weight:700;margin-bottom:6px">{cap_headline}</div>')
                if cap_body and cap_body != "—":
                    inner_parts.append(f'<div style="font-size:13px;color:var(--ink-dim);margin-bottom:8px">{cap_body}</div>')
                if cap_cta and cap_cta != "—":
                    inner_parts.append(f'<div style="font-size:12px;color:var(--accent)">{cap_cta}</div>')
                inner_html = "".join(inner_parts)
            scheduled_html = (
                f"<span class=\"muted\" style=\"font-size:12px\">Scheduled: {scheduled}</span>"
                if scheduled else ""
            )

            # V7.3: build plain-text copy variants
            if _v73_ok and _build_caption_text:
                try:
                    cap_plain_only = _build_caption_text(card, mode="caption_only")
                    cap_plain_hash = _build_caption_text(card, mode="with_hashtags")
                    cap_plain_full = _build_caption_text(card, mode="full_brief")
                except Exception:
                    cap_plain_only = cap_plain_hash = cap_plain_full = ""
            else:
                _plain_raw = f"{active_cap.get('headline','')} {active_cap.get('body','')} {active_cap.get('cta','')}".strip()
                cap_plain_only = cap_plain_hash = cap_plain_full = _plain_raw

            cards_html += f"""
<div class="card" id="pc-{card_id}" style="page-break-inside:avoid">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:12px">
    <div>
      <div style="font-size:13px;font-weight:700;color:var(--ink)">{swimmer} · {event}</div>
      <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    </div>
    <span class="tag good" style="flex-shrink:0">approved</span>
  </div>
  <div style="padding:14px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px">
    {inner_html}
  </div>
  <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class="btn secondary" style="font-size:12px;padding:5px 12px" onclick="copyActiveTone(this, 'pc-{card_uuid}')">Copy caption</button>
    <button class="btn secondary" style="font-size:12px;padding:5px 12px" onclick="copyCaption(this, 'cap-text-{card_id}-2')">Copy + hashtags</button>
    <button class="btn secondary" style="font-size:12px;padding:5px 12px" onclick="copyCaption(this, 'cap-text-{card_id}-3')">Copy full brief</button>
    <textarea id="cap-text-{card_id}-1" style="display:none">{cap_plain_only}</textarea>
    <textarea id="cap-text-{card_id}-2" style="display:none">{cap_plain_hash}</textarea>
    <textarea id="cap-text-{card_id}-3" style="display:none">{cap_plain_full}</textarea>
    {scheduled_html}
  </div>
</div>"""

        body = f"""
<style>
@media print {{
  .no-print {{ display: none !important; }}
  body {{ background: white; color: black; }}
  .card {{ border: 1px solid #ccc; box-shadow: none; }}
}}
</style>
<div class="no-print">
  <p class="dim"><a href="{_review_url}">← Back to review</a></p>
</div>

<h1>Content Pack — {meet_name}</h1>
<p class="dim">{len(approved)} approved card{"s" if len(approved) != 1 else ""} · ready to post</p>

<div class="no-print" style="margin-bottom:20px;display:flex;gap:10px">
  <form method="post" action="{_mark_all_url}" onsubmit="return confirm('Mark all approved cards as posted?')">
    <button class="btn secondary" type="submit">Mark all posted</button>
  </form>
  <button class="btn secondary" onclick="window.print()">Print / Export PDF</button>
</div>

{cards_html}

<script>
// Robust copy with execCommand fallback for browsers without clipboard API.
function copyCaption(btn, spanId) {{
  var span = document.getElementById(spanId);
  if (!span) {{ btn.textContent = 'Error'; return; }}
  var text = span.textContent.trim();
  var done = function(ok) {{ btn.textContent = ok ? 'Copied!' : 'Copy failed'; setTimeout(function(){{ btn.textContent = 'Copy caption'; }}, 1800); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function(){{ done(true); }}).catch(function(){{ fallback(); }});
  }} else {{
    fallback();
  }}
  function fallback() {{
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }}
    catch (e) {{ done(false); }}
    document.body.removeChild(ta);
  }}
}}
</script>
"""
        return _layout(f"Content Pack — {meet_name}", body, active="home")

    # ---- Workflow API --------------------------------------------------
    @app.route("/api/workflow/<run_id>/<card_id>", methods=["POST"])
    def api_workflow_set(run_id, card_id):
        """Set workflow status or edits for a card."""
        ws = _get_wf_store()
        if ws is None:
            return jsonify({"error": "workflow not available"}), 503

        payload = request.get_json(silent=True) or {}
        action = payload.get("action", "set_status")

        if action == "set_status":
            status_str = payload.get("status", "queue")
            try:
                status = CardStatus(status_str)
            except (ValueError, NameError):
                return jsonify({"error": f"invalid status: {status_str}"}), 400
            notes = payload.get("notes")
            ws.set_status(run_id, card_id, status, notes=notes)
            summary = ws.summary(run_id)
            return jsonify({"ok": True, "status": status_str, "summary": summary})

        if action == "set_edits":
            edits = payload.get("edits", {})
            ws.set_edits(run_id, card_id, edits)
            # Auto-bump status to 'edited' if currently in queue, so the user
            # sees that this card has been modified. Don't overwrite approved/posted.
            try:
                cur_state = ws.load(run_id).get(card_id)
                cur_status = cur_state.status if cur_state else CardStatus.QUEUE
                if cur_status == CardStatus.QUEUE:
                    ws.set_status(run_id, card_id, CardStatus.EDITED)
            except Exception:
                pass
            return jsonify({"ok": True, "status": "edited"})

        return jsonify({"error": "unknown action"}), 400

    @app.route("/api/workflow/<run_id>/mark-all-posted", methods=["POST"])
    def api_workflow_mark_all_posted(run_id):
        ws = _get_wf_store()
        if ws is None:
            return redirect(url_for("review", run_id=run_id))
        ws.mark_all_posted(run_id)
        return redirect(url_for("content_pack", run_id=run_id))

    # ---- Turn-Into: one meet → 7 derivative artefacts -------------------
    @app.route("/api/runs/<run_id>/turn-into", methods=["POST"])
    def api_turn_into(run_id):
        """Generate a Turn-Into pack (up to 7 artefacts) from this run.

        Body (JSON, all optional):
          { "deterministic": bool }   force heuristic mode (no LLM)
        """
        run_data = _load_run(run_id)
        if not run_data:
            return jsonify({"error": "run not found"}), 404

        profile_id = run_data.get("profile_id", "")
        profile = load_profile(profile_id) if profile_id else None
        if profile is None:
            # Fall back to a minimal profile derived from the run's display name
            # so Turn-Into still runs even when no profile is persisted.
            profile = ClubProfile(
                profile_id=profile_id or "default",
                display_name=run_data.get("profile_display", "") or "Club",
            )

        payload = request.get_json(silent=True) or {}
        deterministic = bool(payload.get("deterministic", False))

        try:
            from mediahub.turn_into import turn_meet_into_pack, save_pack
            pack = turn_meet_into_pack(run_data, profile, deterministic=deterministic)
            save_pack(pack, run_id, base_dir=DATA_DIR / "turn_into_packs")
        except Exception as e:
            return jsonify({"error": "turn_into_failed", "message": str(e)}), 500

        return jsonify({
            "ok": True,
            "pack_id": pack["pack_id"],
            "n_artefacts": len(pack.get("artefacts", [])),
            "skipped": [s.get("type") for s in pack.get("skipped", [])],
            "pack_url": url_for("turn_into_pack_view",
                                run_id=run_id, pack_id=pack["pack_id"]),
        })

    @app.route("/api/runs/<run_id>/turn-into/<pack_id>/caption", methods=["POST"])
    def api_turn_into_edit_caption(run_id, pack_id):
        """Inline-edit a caption within a saved pack.

        Body (JSON):
          {
            "artefact_index": int,
            "caption_key":    str,   # e.g. "default" | "instagram" | "swimmer_1"
            "text":           str,
            # OR for x_thread:
            "x_thread_index": int,   # 0-based
            "text":           str,
          }
        """
        from mediahub.turn_into import load_pack, save_pack
        base = DATA_DIR / "turn_into_packs"
        pack = load_pack(run_id, pack_id, base_dir=base)
        if pack is None:
            return jsonify({"error": "pack not found"}), 404

        data = request.get_json(silent=True) or {}
        try:
            idx = int(data.get("artefact_index"))
        except (TypeError, ValueError):
            return jsonify({"error": "artefact_index required"}), 400
        artefacts = pack.get("artefacts") or []
        if idx < 0 or idx >= len(artefacts):
            return jsonify({"error": "artefact_index out of range"}), 400
        text = str(data.get("text", ""))

        artefact = artefacts[idx]
        captions = artefact.setdefault("captions", {})

        if "x_thread_index" in data and data["x_thread_index"] is not None:
            try:
                xi = int(data["x_thread_index"])
            except (TypeError, ValueError):
                return jsonify({"error": "x_thread_index must be int"}), 400
            posts = captions.get("x_thread") or []
            if xi < 0 or xi >= len(posts):
                return jsonify({"error": "x_thread_index out of range"}), 400
            posts[xi] = text
            captions["x_thread"] = posts
        else:
            key = str(data.get("caption_key", "default"))
            captions[key] = text

        artefacts[idx] = artefact
        pack["artefacts"] = artefacts
        save_pack(pack, run_id, base_dir=base)
        return jsonify({"ok": True})

    @app.route("/runs/<run_id>/pack/<pack_id>")
    def turn_into_pack_view(run_id, pack_id):
        """Render a saved Turn-Into pack with the 7 artefacts."""
        from mediahub.turn_into import load_pack
        pack = load_pack(run_id, pack_id, base_dir=DATA_DIR / "turn_into_packs")
        if pack is None:
            return _layout("Not found",
                           '<div class="empty">Turn-Into pack not found.</div>'), 404

        _review_url = url_for("review", run_id=run_id)
        _api_url = url_for("api_turn_into", run_id=run_id)
        _edit_api = url_for("api_turn_into_edit_caption",
                            run_id=run_id, pack_id=pack_id)
        meet_name = _h(pack.get("meet_name", ""))
        gen_at = _h(pack.get("generated_at", ""))

        artefacts = pack.get("artefacts") or []
        skipped = pack.get("skipped") or []

        # --- Skipped notice band
        skipped_html = ""
        if skipped:
            items = "".join(
                f'<li><strong>{_h(s.get("type",""))}</strong>: '
                f'{_h(s.get("reason",""))}</li>'
                for s in skipped
            )
            skipped_html = (
                '<div class="card" style="border-color:var(--warn);background:rgba(245,158,11,0.04)">'
                '<h2 style="margin-top:0">Skipped artefacts</h2>'
                f'<ul style="margin:0">{items}</ul>'
                '</div>'
            )

        # --- Artefact cards
        cards_html = ""
        for art_idx, art in enumerate(artefacts):
            atype = art.get("type", "")
            title = _h(art.get("title", atype))
            captions = art.get("captions") or {}
            cards = art.get("cards") or []
            draft = art.get("draft_flag", "")
            html_block = art.get("html") or ""
            notes_list = art.get("notes") or []

            # Draft badge
            draft_html = ""
            if draft:
                draft_html = (
                    '<div style="margin-bottom:12px;padding:10px 14px;'
                    'background:rgba(245,158,11,0.12);border:1px solid var(--warn);'
                    f'border-radius:8px;font-weight:600;color:var(--warn)">{_h(draft)}</div>'
                )

            # Caption editor blocks — one per key
            caption_blocks = ""
            for cap_key, cap_val in captions.items():
                if cap_key == "x_thread" and isinstance(cap_val, list):
                    # Special-case: numbered thread of posts.
                    sub = ""
                    for ti, post in enumerate(cap_val):
                        post_chars = len(post or "")
                        cls = "good" if post_chars <= 280 else "bad"
                        sub += (
                            f'<div style="margin-bottom:10px">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
                            f'<span class="muted" style="font-size:11px">Post {ti+1}</span>'
                            f'<span class="tag {cls}" style="font-size:10px">{post_chars}/280</span>'
                            f'</div>'
                            f'<textarea class="ti-cap" data-artefact="{art_idx}" '
                            f'data-thread="{ti}" '
                            f'style="width:100%;min-height:60px;font-size:13px;'
                            f'padding:8px;border:1px solid var(--border);border-radius:6px;'
                            f'background:var(--bg);color:var(--ink);font-family:inherit">'
                            f'{_h(post)}</textarea>'
                            f'</div>'
                        )
                    caption_blocks += (
                        '<div style="margin-bottom:14px">'
                        f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;'
                        f'color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:8px">X thread '
                        f'({len(cap_val)} posts, ≤280 chars each)</div>'
                        f'{sub}'
                        '</div>'
                    )
                    continue

                # Single string caption
                if not isinstance(cap_val, str):
                    continue
                key_label = cap_key.replace("_", " ").title()
                char_count = len(cap_val)
                # Show Instagram cap for ig caption.
                cap_limit_html = ""
                if cap_key == "instagram":
                    cls = "good" if char_count <= 2200 else "bad"
                    cap_limit_html = f'<span class="tag {cls}" style="font-size:10px;margin-left:8px">{char_count}/2200</span>'
                caption_blocks += (
                    '<div style="margin-bottom:14px">'
                    f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;'
                    f'color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">'
                    f'{_h(key_label)}{cap_limit_html}</div>'
                    f'<textarea class="ti-cap" data-artefact="{art_idx}" '
                    f'data-key="{_h(cap_key)}" '
                    f'style="width:100%;min-height:80px;font-size:13px;'
                    f'padding:10px;border:1px solid var(--border);border-radius:6px;'
                    f'background:var(--bg);color:var(--ink);font-family:inherit">'
                    f'{_h(cap_val)}</textarea>'
                    '</div>'
                )

            # Optional sub-cards strip (e.g. spotlight series)
            sub_cards_html = ""
            if cards and atype in ("swimmer_spotlight",):
                rows = ""
                for c in cards:
                    rows += (
                        '<div style="padding:10px;background:rgba(255,255,255,0.03);'
                        'border:1px solid var(--border);border-radius:8px;margin-bottom:8px">'
                        f'<div style="font-size:13px;font-weight:700">{_h(c.get("swimmer",""))} '
                        f'· {_h(c.get("event",""))}</div>'
                        f'<div style="font-size:12px;color:var(--ink-dim);margin-top:4px">{_h(c.get("headline",""))}</div>'
                        '</div>'
                    )
                sub_cards_html = f'<div style="margin-bottom:12px">{rows}</div>'

            # Newsletter HTML preview
            html_preview_html = ""
            if html_block:
                # Display rendered HTML in a sandboxed-ish preview area.
                # The templates module HTML-escapes the body, so it's safe here.
                html_preview_html = (
                    '<details style="margin-top:8px">'
                    '<summary style="cursor:pointer;font-size:12px;color:var(--accent)">View HTML preview</summary>'
                    f'<div style="margin-top:10px;padding:14px;border:1px dashed var(--border);'
                    f'border-radius:8px;background:rgba(255,255,255,0.02)">{html_block}</div>'
                    '</details>'
                )

            notes_html = ""
            if notes_list:
                lis = "".join(f"<li>{_h(n)}</li>" for n in notes_list)
                notes_html = (
                    '<details style="margin-top:8px">'
                    '<summary style="cursor:pointer;font-size:12px;color:var(--ink-muted)">Why this artefact?</summary>'
                    f'<ul style="margin:8px 0 0 0;font-size:12px;color:var(--ink-dim)">{lis}</ul>'
                    '</details>'
                )

            cards_html += f"""
<div class="card ti-artefact" data-type="{_h(atype)}" data-artefact-index="{art_idx}" style="margin-bottom:18px">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">
    <h2 style="margin:0">{title}</h2>
    <span class="tag info" style="font-size:11px">{_h(atype)}</span>
  </div>
  {draft_html}
  {sub_cards_html}
  {caption_blocks}
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class="btn" style="font-size:12px;padding:6px 14px"
            onclick="tiSaveArtefact({art_idx})">Save edits</button>
    <span class="ti-status" data-artefact="{art_idx}" style="font-size:11px;color:var(--ink-muted)"></span>
  </div>
  {html_preview_html}
  {notes_html}
</div>"""

        if not cards_html:
            cards_html = '<div class="empty">No artefacts generated.</div>'

        body = f"""
<p class="dim"><a href="{_review_url}">← Back to review</a></p>
<h1>Turn-Into pack — {meet_name}</h1>
<p class="dim">{len(artefacts)} artefacts · generated {gen_at}</p>

<div style="margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
  <button class="btn secondary" onclick="tiRegenerate()">↺ Regenerate pack</button>
</div>

{skipped_html}
{cards_html}

<script>
const TI_EDIT_API = {json.dumps(_edit_api)};
const TI_REGEN_API = {json.dumps(_api_url)};
const TI_REVIEW_URL = {json.dumps(_review_url)};

function tiSaveArtefact(idx) {{
  const root = document.querySelector('.ti-artefact[data-artefact-index="' + idx + '"]');
  if (!root) return;
  const status = root.querySelector('.ti-status');
  status.textContent = 'Saving…';
  const tas = root.querySelectorAll('textarea.ti-cap');
  const tasks = [];
  tas.forEach(function(ta) {{
    const payload = {{ artefact_index: idx, text: ta.value }};
    if (ta.dataset.thread !== undefined) {{
      payload.x_thread_index = parseInt(ta.dataset.thread, 10);
    }} else {{
      payload.caption_key = ta.dataset.key || 'default';
    }}
    tasks.push(fetch(TI_EDIT_API, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload),
    }}).then(r => r.json()));
  }});
  Promise.all(tasks).then(function(results) {{
    const ok = results.every(function(r) {{ return r && r.ok; }});
    status.textContent = ok ? 'Saved.' : 'Some edits failed.';
    setTimeout(function() {{ status.textContent = ''; }}, 2200);
  }}).catch(function() {{ status.textContent = 'Error saving.'; }});
}}

function tiRegenerate() {{
  if (!confirm('Generate a fresh Turn-Into pack? The current pack is preserved.')) return;
  fetch(TI_REGEN_API, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{}}),
  }}).then(r => r.json()).then(function(j) {{
    if (j && j.pack_url) {{
      window.location.href = j.pack_url;
    }} else {{
      alert('Regenerate failed: ' + (j && j.message ? j.message : 'unknown error'));
    }}
  }}).catch(function(err) {{
    alert('Regenerate failed.');
  }});
}}
</script>
"""
        return _layout(f"Turn-Into pack — {meet_name}", body, active="home")

    @app.route("/pack/<run_id>/grouped")
    def content_pack_grouped(run_id):
        """Grouped content pack page — 8 buckets."""
        state = _run_state(run_id)
        if state == "in_progress":
            return _layout("Still processing", _in_progress_page(run_id, "content_pack_grouped"), active="home")
        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        profile_id = run_data.get("profile_id", "")
        meet_name = _h(run_data.get("meet", {}).get("name", "") or run_data.get("profile_display", ""))
        _review_url = url_for("review", run_id=run_id)
        _pack_url = url_for("content_pack", run_id=run_id)
        _reel_url = url_for("api_run_reel", run_id=run_id)

        if not _v73_ok or _build_grouped_pack is None:
            return redirect(_pack_url)

        try:
            grouped = _build_grouped_pack(run_data, profile_id)
        except Exception as e:
            grouped = {}
            import traceback
            traceback.print_exc()

        counts = grouped.get("_counts", {})

        def _section_html(title, items, icon="", empty_msg="None in this category."):
            n = len(items) if isinstance(items, list) else (1 if items else 0)
            items_list = [items] if isinstance(items, dict) else (items or [])
            section_id = title.lower().replace(" ", "_").replace("/", "")
            rows = ""
            for item in items_list:
                if not item:
                    continue
                ach = item.get("achievement") or item
                swimmer = _h(ach.get("swimmer_name") or item.get("swimmer_name") or "")
                evt = _h(ach.get("event") or item.get("event") or "")
                headline = _h(ach.get("headline") or item.get("headline") or "")
                angle = _h(_humanise(item.get("post_angle") or ""))
                s2p = item.get("safe_to_post") or {}
                s2p_level = s2p.get("level", "needs_review") if isinstance(s2p, dict) else "needs_review"
                s2p_reason = _h(s2p.get("reason", "") if isinstance(s2p, dict) else "")
                s2p_cls = {"safe": "good", "needs_review": "warn", "do_not_post": "bad"}.get(s2p_level, "")
                cap_only = _h(item.get("caption_only") or ach.get("headline") or "")
                cap_hash = _h(item.get("caption_with_hashtags") or "")
                cap_full = _h(item.get("caption_full_brief") or "")
                card_id = _h(ach.get("swim_id") or item.get("card_id") or "")
                band = _h(item.get("quality_band") or "")
                prio = item.get("priority", 0)
                n_ach = item.get("n_achievements", 0)
                rows += f"""
<div class="card" style="margin-bottom:12px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
    <div style="flex:1">
      <div style="font-size:13px;font-weight:700">{swimmer}{(" · " + evt) if evt else ""}</div>
      <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
      {f'<span class="tag">{angle}</span>' if angle else ""}
      <span class="tag {s2p_cls}" title="{s2p_reason}">{s2p_level}</span>
      {f'<span class="tag">{band}</span>' if band else ""}
    </div>
  </div>
  <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-1')">Copy caption</button>
    <textarea id="cap-{card_id}-1" style="display:none">{cap_only}</textarea>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-2')">Copy + hashtags</button>
    <textarea id="cap-{card_id}-2" style="display:none">{cap_hash}</textarea>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-3')">Copy full brief</button>
    <textarea id="cap-{card_id}-3" style="display:none">{cap_full}</textarea>
  </div>
</div>"""
            if not rows:
                rows = f'<p class="muted">{_h(empty_msg)}</p>'
            return f"""
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>{icon} {_h(title)}</span>
    <span class="tag" style="font-size:12px">{n}</span>
  </summary>
  {rows}
</details>"""

        win = grouped.get("weekend_in_numbers")
        win_html = ""
        if win:
            stats = win.get("stats", [])
            stats_html = "".join(
                f'<div class="stat"><div class="l">{_h(s["label"])}</div><div class="v">{_h(s["value"])}</div></div>'
                for s in stats
            )
            highlights = win.get("highlights", [])
            hl_html = "".join(f'<li>{_h(h)}</li>' for h in highlights)
            cap_txt = _h(win.get("caption_text", ""))
            win_html = f"""
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none">Weekend in numbers</summary>
  <div class="card">
    <div class="stat-block">{stats_html}</div>
    {f'<ul style="margin-top:10px">'+ hl_html +'</ul>' if hl_html else ""}
    <div style="margin-top:10px;display:flex;gap:8px">
      <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'win-cap')">Copy caption</button>
      <textarea id="win-cap" style="display:none">{cap_txt}</textarea>
    </div>
  </div>
</details>"""

        # Build a thumbnail strip of generated visuals if any exist for this run
        visuals_strip = ""
        try:
            vdir = RUNS_DIR / run_id / "visuals"
            if vdir.is_dir():
                tiles = []
                for brief_dir in sorted(vdir.iterdir()):
                    if not brief_dir.is_dir():
                        continue
                    sidecar = brief_dir / "visual.json"
                    if not sidecar.exists():
                        continue
                    try:
                        v = json.loads(sidecar.read_text())
                    except Exception:
                        continue
                    vid = v.get("id", brief_dir.name)
                    fmt = v.get("format", "feed_portrait")
                    cap = (v.get("caption") or "").strip()[:140]
                    fmt_label = {"feed_square": "Square", "feed_portrait": "Portrait", "story": "Story", "reel_cover": "Reel cover"}.get(fmt, fmt)
                    tiles.append(f'''
<div class="card" style="padding:10px;display:flex;flex-direction:column;gap:8px;width:200px;flex:0 0 200px">
  <img src="{url_for('api_visual_png', vid=vid, format_name=fmt)}" alt="" style="width:100%;border-radius:6px;display:block" loading="lazy">
  <div style="font-size:11px;color:var(--ink-dim)">{_h(fmt_label)}</div>
  <div style="font-size:12px;line-height:1.3">{_h(cap)}</div>
  <a class="btn secondary" style="font-size:12px;padding:4px 10px" target="_blank" rel="noopener" href="{url_for('api_visual_png', vid=vid, format_name=fmt)}">Download PNG</a>
</div>''')
                if tiles:
                    _zip_url = url_for("content_pack_zip", run_id=run_id)
                    visuals_strip = f'''
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>🎨 Generated visuals <span class="tag" style="font-size:11px">{len(tiles)}</span></span>
    <a class="btn" style="font-size:12px;padding:6px 14px" href="{_zip_url}">Download all as ZIP</a>
  </summary>
  <div style="display:flex;gap:12px;overflow-x:auto;padding:8px 0 12px">{"".join(tiles)}</div>
</details>'''
        except Exception:
            visuals_strip = ""

        body = f"""
<p class="dim"><a href="{_review_url}">← Back to review</a> &nbsp;|&nbsp; <a href="{_pack_url}">Classic pack view</a></p>
<h1>Content Pack (grouped) — {meet_name}</h1>

<div class="card" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
  <div>
    <div style="font-size:13px;font-weight:700">Meet reel</div>
    <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">Stitch the top 3 cards into a 15-second branded MP4 reel.</div>
  </div>
  <button class="btn" style="font-size:12px;padding:6px 14px;background:linear-gradient(135deg,#F97316,#EF4444);color:#fff;border:none"
          onclick="generateReelGrouped(this, {repr(_reel_url)})">▶ Generate reel from this meet</button>
</div>
<div id="reel-panel-grouped" style="display:none;margin-bottom:14px;padding:14px;background:rgba(249,115,22,0.04);border:1px solid var(--border);border-radius:8px"></div>

{visuals_strip}

{_section_html("Main feed posts", grouped.get("main_feed", []), icon="📌")}
{_section_html("Stories", grouped.get("stories", []), icon="📖")}
{_section_html("Athlete spotlights", grouped.get("athlete_spotlights", []), icon="🌟", empty_msg="No swimmers with 3+ achievements.")}
{win_html}
{_section_html("Internal notes / nice mentions", grouped.get("internal_notes", []), icon="📝")}
{_section_html("Needs review", grouped.get("needs_review", []), icon="⚠")}
{_section_html("Rejected / not recommended", grouped.get("rejected", []), icon="✕")}

<script>
function copyText(btn, taId) {{
  var ta = document.getElementById(taId);
  if (!ta) {{ btn.textContent = 'Error'; return; }}
  var text = ta.value;
  var origText = btn.textContent;
  var done = function(ok) {{ btn.textContent = ok ? 'Copied!' : 'Copy failed'; setTimeout(function(){{ btn.textContent = origText; }}, 1800); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function(){{ done(true); }}).catch(function(){{ fallback(); }});
  }} else {{ fallback(); }}
  function fallback() {{
    var t = document.createElement('textarea');
    t.value = text; t.style.position = 'fixed'; t.style.left = '-9999px';
    document.body.appendChild(t); t.focus(); t.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }} catch(e) {{ done(false); }}
    document.body.removeChild(t);
  }}
}}
function generateReelGrouped(btn, reelUrl) {{
  var panel = document.getElementById('reel-panel-grouped');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering reel…';
  panel.innerHTML = '<div style="padding:20px;text-align:center;color:var(--ink-muted);font-size:13px">Producing 15-second reel from the top 3 cards… cold renders may take up to 90s.</div>';
  fetch(reelUrl, {{method:'POST'}})
    .then(function(r) {{
      var ct = r.headers.get('content-type') || '';
      if (r.ok && ct.indexOf('video') !== -1) {{ return r.blob().then(function(b){{ return {{ok:true, blob:b}}; }}); }}
      return r.json().then(function(j){{ return {{ok:false, body:j}}; }});
    }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok) {{
        var msg = (res.body && (res.body.detail || res.body.error)) || 'render failed';
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Reel render error: ' + msg + '</div>';
        return;
      }}
      var url = URL.createObjectURL(res.blob);
      panel.innerHTML =
        '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
          '<div style="flex:0 0 220px;max-width:240px">' +
            '<video src="' + url + '" controls playsinline style="width:100%;border-radius:6px;border:1px solid var(--border);background:#000"></video>' +
          '</div>' +
          '<div style="flex:1;min-width:200px">' +
            '<div style="font-size:11px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">Meet reel · 1080×1920 · 15s</div>' +
            '<a class="btn secondary" href="' + url + '" download="meet-reel.mp4" style="font-size:12px;padding:4px 12px">Download MP4</a>' +
          '</div>' +
        '</div>';
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}
</script>
"""
        return _layout(f"Content Pack (grouped) — {meet_name}", body, active="home")

    # ===================================================================
    # V8: Media library + visuals
    # ===================================================================

    def _v8_brand_kit_for(profile_id: str, run_id: Optional[str] = None):
        # V8.2 Issue 5: per-run brand kit is the only source. Saved club profiles
        # are gone; we look up data/brand_kits/<run_id>.json keyed by run_id.
        rk: Dict[str, Any] = {}
        if run_id:
            try:
                run_kit_path = DATA_DIR / "data" / "brand_kits" / f"{run_id}.json"
                if run_kit_path.exists():
                    rk = json.loads(run_kit_path.read_text()) or {}
            except Exception:
                rk = {}
        display_name = (rk.get("display_name")
                        or profile_id.replace("_", " ").replace("-", " ").title())
        primary = rk.get("primary_colour") or "#0A2540"
        secondary = rk.get("secondary_colour") or "#000000"
        accent = rk.get("accent_colour") or "#FFD86E"
        try:
            from mediahub.brand.kit import BrandKit
            bk = BrandKit(profile_id=profile_id, display_name=display_name,
                          primary_colour=primary, secondary_colour=secondary,
                          accent_colour=accent)
        except Exception:
            class _BK:
                pass
            bk = _BK()
            bk.profile_id = profile_id
            bk.display_name = display_name
            bk.primary_colour = primary
            bk.secondary_colour = secondary
            bk.accent_colour = accent
            bk.short_name = ""
            bk.logo_svg = None
        if rk.get("logo_path"):
            try:
                bk.logo_path = rk["logo_path"]  # type: ignore[attr-defined]
            except Exception:
                pass
        return bk

    @app.route("/media-library")
    def media_library_page():
        """Browse and upload reusable media assets."""
        if not _v8_ok:
            return _layout("Media library", '<div class="empty">V8 media engine unavailable.</div>'), 503
        from flask import request as _req
        profile_id = _req.args.get("profile_id")
        if not profile_id:
            # Pick the first available profile as a sensible default; if no
            # profiles exist, show an explicit empty state pointing at the
            # Organisation page instead of silently bouncing back to home.
            _profs = list_profiles()
            if not _profs:
                _org_url = url_for('organisation_page')
                _add_input_url = url_for('add_input_page')
                empty_body = f"""
<h1>Media library</h1>
<p class="dim">Store reusable photos for your organisation so the AI can pull them into content cards.</p>
<div class="card" style="text-align:center;padding:48px 32px">
  <div style="font-size:48px;margin-bottom:16px">&#128247;</div>
  <h2 style="margin-bottom:8px">No organisation set up yet</h2>
  <p class="dim" style="margin-bottom:24px">The media library is scoped per organisation. Set up your organisation first, or add an input to auto-create one.</p>
  <a class="btn" href="{_org_url}">Set up organisation →</a>
  <a class="btn secondary" href="{_add_input_url}" style="margin-left:8px">Or add an input →</a>
</div>
"""
                return _layout("Media library", empty_body, active="media")
            profile_id = _profs[0].profile_id
        store = _v8_get_media_store()
        assets = store.list(profile_id=profile_id)
        rows_html = ""
        for a in assets[:200]:
            ad = a.to_dict() if hasattr(a, "to_dict") else a
            athlete_names = ", ".join(ad.get("linked_athlete_names") or [])
            _file_url = url_for('api_media_library_file', asset_id=ad.get('id', ''))
            rows_html += f"""
<tr>
  <td><img src=\"{_file_url}\" style=\"max-height:60px;border-radius:4px;\" /></td>
  <td>{ad.get('type','')}</td>
  <td>{athlete_names}</td>
  <td>{ad.get('linked_venue') or ad.get('linked_event') or ''}</td>
  <td>{ad.get('permission_status','')}</td>
  <td><code>{ad.get('id','')[:12]}</code></td>
</tr>"""
        body = f"""
<div class=\"card\">
  <h2>Media library — {profile_id}</h2>
  <p>Upload reusable photos. Each gets parsed for athlete/venue/event metadata.</p>
  <form method=\"POST\" action=\"{url_for('api_media_library_upload')}\" enctype=\"multipart/form-data\">
    <p><input type=\"file\" name=\"file\" accept=\"image/*\" required></p>
    <p>Description: <input type=\"text\" name=\"description\" placeholder=\"e.g. Eira Hughes at Welsh National Open\" style=\"width:60%\"></p>
    <p>Type: <select name=\"asset_type\">
      <option value=\"athlete_photo\">athlete_photo</option>
      <option value=\"venue\">venue</option>
      <option value=\"team\">team</option>
      <option value=\"action\">action</option>
      <option value=\"podium\">podium</option>
      <option value=\"logo\">logo</option>
    </select></p>
    <input type=\"hidden\" name=\"profile_id\" value=\"{profile_id}\">
    <button type=\"submit\" class=\"btn\">Upload photo</button>
  </form>
</div>
<div class=\"card\">
  <h3>{len(assets)} assets</h3>
  <table style=\"width:100%\">
    <thead><tr><th>Preview</th><th>Type</th><th>Athlete</th><th>Venue/Event</th><th>Permission</th><th>ID</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""
        return _layout("Media library", body, active="media")

    @app.route("/api/media-library", methods=["POST"])
    def api_media_library_upload():
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import request as _req
        f = _req.files.get("file")
        if not f:
            return jsonify({"error": "no_file"}), 400
        profile_id = (_req.form.get("profile_id") or "").strip()
        if not profile_id:
            return jsonify({"error": "profile_id_required"}), 400
        description = _req.form.get("description", "").strip()
        asset_type = _req.form.get("asset_type", "athlete_photo").strip()

        # Save to disk
        upload_dir = UPLOADS_DIR / "media_library" / profile_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        import uuid as _uuid
        ext = Path(f.filename or "upload.jpg").suffix.lower() or ".jpg"
        dest = upload_dir / f"asset_{_uuid.uuid4().hex[:12]}{ext}"
        f.save(str(dest))

        # Parse metadata
        meta = _v8_parse_description(description) if description else {}
        store = _v8_get_media_store()
        from mediahub.media_library.models import MediaAsset
        athlete_names = list(meta.get("athletes") or [])
        asset = MediaAsset(
            id="",
            filename=Path(f.filename or dest.name).name,
            path=str(dest),
            type=asset_type,
            description_raw=description,
            description_parsed=meta,
            profile_id=profile_id,
            linked_athlete_names=athlete_names,
            linked_venue=meta.get("venue"),
            linked_event=meta.get("event"),
            tags=meta.get("tags") or [],
        )
        asset = store.save(asset)
        # AJAX callers get JSON; plain form submissions redirect back to the library.
        if (_req.headers.get("Accept", "").find("application/json") != -1
                or _req.headers.get("X-Requested-With") == "XMLHttpRequest"):
            return jsonify({"ok": True, "asset": asset.to_dict() if hasattr(asset, "to_dict") else asset})
        return redirect(url_for("media_library_page", profile_id=profile_id))

    @app.route("/api/media-library/file/<asset_id>")
    def api_media_library_file(asset_id: str):
        if not _v8_ok:
            return "", 503
        store = _v8_get_media_store()
        a = store.get(asset_id)
        if not a:
            return "", 404
        from flask import send_file
        try:
            return send_file(a.path)
        except Exception:
            return "", 404

    @app.route("/api/runs/<run_id>/cards/<card_id>/create-graphic", methods=["POST"])
    def api_create_graphic(run_id: str, card_id: str):
        """Render a visual for a single content item / recognition card."""
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import request as _req
        # Resolve run + card. Runs are stored as runs_v4/<run_id>.json;
        # also accept the legacy nested runs_v4/<run_id>/run.json layout.
        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
                return jsonify({"error": "run_not_found"}), 404

        # Find the matching card / achievement
        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        target = None
        for ra in ranked:
            ach = ra.get("achievement") or {}
            if ach.get("swim_id") == card_id or ra.get("id") == card_id:
                target = ra
                break
        if target is None:
            # Fallback: try cards array
            for c in (run_data.get("cards") or []):
                if c.get("swim_id") == card_id or c.get("id") == card_id:
                    target = {"achievement": c}
                    break
        if target is None:
            return jsonify({"error": "card_not_found"}), 404

        # Build a content_item shape that creative_brief expects
        ach = target.get("achievement") or {}
        item = {
            "id": ach.get("swim_id") or card_id,
            "swim_id": ach.get("swim_id") or card_id,
            "achievement": ach,
            "post_angle": ach.get("post_angle") or _req.json.get("post_angle") if _req.is_json else ach.get("post_angle"),
            "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
            "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
        }

        # V8.1: profile_id is optional. If the user used the two-step upload flow with
        # only a club_filter + per-run brand kit (no saved profile), derive a virtual
        # profile id from the club_filter so brand-kit + media-library lookups still work.
        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        # Slugify
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id)

        # Pull media library assets for this profile
        media_assets = []
        try:
            store = _v8_get_media_store()
            assets = store.list(profile_id=profile_id)
            media_assets = [a.to_dict() if hasattr(a, "to_dict") else a for a in assets]
        except Exception:
            pass

        # Accept optional format from JSON body or query string
        req_fmt = None
        try:
            if _req.is_json and _req.json:
                req_fmt = _req.json.get("format")
        except Exception:
            req_fmt = None
        if not req_fmt:
            req_fmt = _req.args.get("format")
        formats_kw = [req_fmt] if req_fmt else None

        # Variation seed. Default behaviour now: pick a UNIQUE per-card seed
        # so every card in a pack looks visibly different (different layout
        # family, palette permutation, headline phrasing) while still using
        # the club's own colours, logo, and photos.
        # Caller can override with ?variation_seed=N (explicit int).
        # Setting variation_seed=0 explicitly restores the legacy "identity"
        # render (no variation), useful for debugging / regression tests.
        seed_raw = _req.args.get("variation_seed")
        if seed_raw is None or seed_raw == "":
            try:
                from mediahub.creative_brief.generator import auto_variation_seed_for
                variation_seed = auto_variation_seed_for(
                    item.get("swim_id") or item.get("id") or card_id
                )
            except Exception:
                variation_seed = 1
        else:
            try:
                variation_seed = int(seed_raw)
            except (TypeError, ValueError):
                variation_seed = 0

        try:
            res = _v8_create_visual_for_item(
                item, brand_kit,
                profile_id=profile_id, run_id=run_id,
                media_assets=media_assets,
                formats=formats_kw,
                variation_seed=variation_seed,
            )
        except Exception as e:
            return jsonify({"error": f"render_failed: {e}"}), 500
        # Include the seed in the response so the UI / debugging can see it.
        return jsonify({"ok": True, "variation_seed": variation_seed, **res})

    @app.route("/api/runs/<run_id>/cards/<card_id>/regenerate", methods=["POST"])
    def api_regenerate_graphic(run_id: str, card_id: str):
        """Same as create-graphic but explicit re-run for an existing card."""
        return api_create_graphic(run_id, card_id)

    @app.route("/api/runs/<run_id>/cards/<card_id>/regenerate-variants", methods=["POST"])
    def api_regenerate_variants(run_id: str, card_id: str):
        """V8.1 issue 4: produce 3 visibly-different design alternatives.

        Fires three renders with seeds 1, 2, 3 in parallel threads and
        returns ``{variants: [{visual, brief}, ...]}``.
        """
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503

        # Resolve run + card the same way create-graphic does.
        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
                return jsonify({"error": "run_not_found"}), 404

        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        target = None
        for ra in ranked:
            ach = ra.get("achievement") or {}
            if ach.get("swim_id") == card_id or ra.get("id") == card_id:
                target = ra
                break
        if target is None:
            for c in (run_data.get("cards") or []):
                if c.get("swim_id") == card_id or c.get("id") == card_id:
                    target = {"achievement": c}
                    break
        if target is None:
            return jsonify({"error": "card_not_found"}), 404

        ach = target.get("achievement") or {}
        item = {
            "id": ach.get("swim_id") or card_id,
            "swim_id": ach.get("swim_id") or card_id,
            "achievement": ach,
            "post_angle": ach.get("post_angle"),
            "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
            "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
        }

        # V8.1: profile_id optional; fall back to club_filter / synthetic id
        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id)

        media_assets = []
        try:
            store = _v8_get_media_store()
            assets = store.list(profile_id=profile_id)
            media_assets = [a.to_dict() if hasattr(a, "to_dict") else a for a in assets]
        except Exception:
            pass

        from concurrent.futures import ThreadPoolExecutor

        def _one(seed: int) -> dict:
            try:
                res = _v8_create_visual_for_item(
                    item, brand_kit,
                    profile_id=profile_id, run_id=run_id,
                    media_assets=media_assets,
                    variation_seed=seed,
                )
                visuals = res.get("visuals") or []
                # Pick the feed_portrait by default if present, else first.
                primary = next((v for v in visuals if v.get("format_name") == "feed_portrait"), visuals[0] if visuals else None)
                return {
                    "seed": seed,
                    "visual": primary,
                    "visuals": visuals,
                    "brief": res.get("brief"),
                    "errors": res.get("errors") or [],
                }
            except Exception as e:
                return {"seed": seed, "visual": None, "visuals": [], "brief": None, "errors": [str(e)]}

        seeds = [1, 2, 3]
        with ThreadPoolExecutor(max_workers=3) as ex:
            variants = list(ex.map(_one, seeds))
        return jsonify({"ok": True, "variants": variants})

    # ------------------------------------------------------------------
    # Motion-graphic + short-form video output (Remotion)
    # ------------------------------------------------------------------
    @app.route("/api/runs/<run_id>/card/<card_id>/motion", methods=["POST", "GET"])
    def api_card_motion(run_id: str, card_id: str):
        """Render (or serve cached) MP4 story for a single card.

        Lazy: returns the cached file on cache hit; renders via Remotion on
        cache miss. Always serves the MP4 with the correct mime type so the
        UI can use <video src=…> or a direct download.
        """
        from flask import send_file
        try:
            from mediahub.visual import motion as _motion
        except Exception as e:
            return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
                return jsonify({"error": "run_not_found"}), 404

        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        target = None
        for ra in ranked:
            ach = ra.get("achievement") or {}
            if ach.get("swim_id") == card_id or ra.get("id") == card_id:
                target = ra
                break
        if target is None:
            for c in (run_data.get("cards") or []):
                if c.get("swim_id") == card_id or c.get("id") == card_id:
                    target = {"achievement": c}
                    break
        if target is None:
            return jsonify({"error": "card_not_found"}), 404

        ach = target.get("achievement") or {}
        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
        card_payload = {
            "id": ach.get("swim_id") or card_id,
            "swim_id": ach.get("swim_id") or card_id,
            "achievement": ach,
            "meet_name": meet_name,
        }

        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        try:
            brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id) if _v8_ok else None
        except Exception:
            brand_kit = None

        # Honour the same per-card variation seed as the static graphic, so
        # the motion render visually aligns with the still card.
        try:
            from mediahub.creative_brief.generator import auto_variation_seed_for
            variation_seed = auto_variation_seed_for(
                ach.get("swim_id") or card_id
            )
        except Exception:
            variation_seed = 1

        out_dir = RUNS_DIR / run_id / "motion"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{card_id}.mp4"

        try:
            mp4 = _motion.render_story_card(
                card_payload,
                brand_kit,
                out_path,
                variation_seed=variation_seed,
            )
        except RuntimeError as e:
            return jsonify({"error": "render_failed", "detail": str(e)}), 500
        except Exception as e:
            return jsonify({"error": "render_failed", "detail": str(e)}), 500

        if not Path(mp4).exists():
            return jsonify({"error": "render_failed", "detail": "mp4 missing after render"}), 500
        return send_file(str(mp4), mimetype="video/mp4", as_attachment=False,
                         download_name=f"{card_id}.mp4")

    @app.route("/api/runs/<run_id>/reel", methods=["POST", "GET"])
    def api_run_reel(run_id: str):
        """Render (or serve cached) a multi-card MP4 reel for the meet.

        Uses the top 3 ranked achievements by default; caller can override
        the count with ?n=<int> up to a hard cap of 5.
        """
        from flask import send_file
        try:
            from mediahub.visual import motion as _motion
        except Exception as e:
            return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
                return jsonify({"error": "run_not_found"}), 404

        try:
            n = int(request.args.get("n", "3"))
        except (TypeError, ValueError):
            n = 3
        n = max(1, min(5, n))

        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        # ranked_achievements is generally already sorted; sort defensively.
        ranked_sorted = sorted(
            ranked,
            key=lambda r: float(r.get("priority", 0.0) or 0.0),
            reverse=True,
        )
        top = ranked_sorted[:n]
        if not top:
            # Fall back to the cards array if no recognition report.
            top = [{"achievement": c} for c in (run_data.get("cards") or [])[:n]]
        if not top:
            return jsonify({"error": "no_cards_for_reel"}), 404

        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
        cards: list[dict] = []
        for ra in top:
            ach = ra.get("achievement") or {}
            cards.append({
                "id": ach.get("swim_id") or ra.get("id") or "",
                "swim_id": ach.get("swim_id") or "",
                "achievement": ach,
                "meet_name": meet_name,
            })

        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        try:
            brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id) if _v8_ok else None
        except Exception:
            brand_kit = None

        out_dir = RUNS_DIR / run_id / "motion"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"reel_{n}.mp4"

        try:
            mp4 = _motion.render_meet_reel(
                cards,
                brand_kit,
                out_path,
                meet_name=meet_name,
            )
        except RuntimeError as e:
            return jsonify({"error": "render_failed", "detail": str(e)}), 500
        except Exception as e:
            return jsonify({"error": "render_failed", "detail": str(e)}), 500

        if not Path(mp4).exists():
            return jsonify({"error": "render_failed", "detail": "mp4 missing after render"}), 500
        return send_file(str(mp4), mimetype="video/mp4", as_attachment=False,
                         download_name=f"meet_reel_{run_id}.mp4")

    @app.route("/api/visual/<vid>")
    def api_visual_get(vid: str):
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            vdir = run_dir / "visuals"
            if not vdir.is_dir():
                continue
            for sub in vdir.iterdir():
                if not sub.is_dir():
                    continue
                sidecar = sub / "visual.json"
                if not sidecar.exists():
                    continue
                try:
                    payload = json.loads(sidecar.read_text())
                except Exception:
                    continue
                ids_map = payload.get("visual_ids") or {}
                if payload.get("id") == vid or vid in ids_map:
                    return jsonify(payload)
        return jsonify({"error": "not_found"}), 404

    _VALID_FORMAT_NAMES = {
        "feed_portrait", "feed_square", "feed_landscape",
        "story_portrait", "story_square",
        "twitter_landscape", "twitter_square",
        "print_a4", "print_letter",
    }

    @app.route("/api/visual/<vid>/png/<format_name>")
    def api_visual_png(vid: str, format_name: str):
        if format_name not in _VALID_FORMAT_NAMES:
            return "", 400
        if not _v8_ok:
            return "", 503
        from flask import send_file
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            vdir = run_dir / "visuals"
            if not vdir.is_dir():
                continue
            for brief_dir in vdir.iterdir():
                if not brief_dir.is_dir():
                    continue
                sidecar = brief_dir / "visual.json"
                if not sidecar.exists():
                    continue
                try:
                    payload = json.loads(sidecar.read_text())
                except Exception:
                    continue
                # Match either the primary id or any id in the visual_ids map
                ids_map = payload.get("visual_ids") or {}
                if payload.get("id") != vid and vid not in ids_map:
                    continue
                # Determine which format to serve. If vid matches a specific format-id, use that format; else use requested format_name.
                if vid in ids_map:
                    fmt = ids_map[vid]
                else:
                    fmt = format_name
                candidate = brief_dir / f"{fmt}.png"
                if candidate.exists():
                    return send_file(str(candidate), mimetype="image/png")
                # Fall back to the requested format_name
                fallback = brief_dir / f"{format_name}.png"
                if fallback.exists():
                    return send_file(str(fallback), mimetype="image/png")
        return "", 404

    @app.route("/api/runs/<run_id>/venue-search")
    def api_venue_search(run_id: str):
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import request as _req
        q = _req.args.get("q", "").strip()
        if not q:
            return jsonify({"results": []})
        try:
            results = _v8_search_venue(q, limit=8)
            return jsonify({"results": [r.__dict__ if hasattr(r, "__dict__") else r for r in results]})
        except Exception as e:
            return jsonify({"error": str(e), "results": []}), 500

    @app.route("/pack/<run_id>/zip")
    def content_pack_zip(run_id: str):
        """Bundle all generated visuals + captions for a run into a zip download.

        Folder structure (from V8 spec):
          /<run_id>/feed/...png
          /<run_id>/stories/...png
          /<run_id>/reel-covers/...png
          /<run_id>/captions/<visual_id>.txt
          /<run_id>/source-assets/...
          /<run_id>/approval-summary.json
        """
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import send_file
        import io, zipfile

        vdir = RUNS_DIR / run_id / "visuals"
        if not vdir.is_dir():
            return _layout(
                "No visuals",
                '<div class="empty">No graphics have been generated for this run yet. Open the recognition page and use "Create graphic" on cards to add some.</div>',
            ), 404

        buf = io.BytesIO()
        approval = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for brief_dir in sorted(vdir.iterdir()):
                if not brief_dir.is_dir():
                    continue
                sidecar = brief_dir / "visual.json"
                if not sidecar.exists():
                    continue
                try:
                    visual = json.loads(sidecar.read_text())
                except Exception:
                    continue
                vid = visual.get("id", brief_dir.name)
                fmt = (visual.get("format") or "").lower()
                if "story" in fmt:
                    sub = "stories"
                elif "reel" in fmt:
                    sub = "reel-covers"
                elif "carousel" in fmt:
                    sub = "carousels"
                else:
                    sub = "feed"
                # Add every PNG in the brief dir
                for png in brief_dir.glob("*.png"):
                    arcname = f"{run_id}/{sub}/{vid}__{png.stem}.png"
                    z.writestr(arcname, png.read_bytes())
                # Caption
                cap = visual.get("caption") or ""
                alt = visual.get("alt_text") or ""
                z.writestr(
                    f"{run_id}/captions/{vid}.txt",
                    f"CAPTION:\n{cap}\n\nALT TEXT:\n{alt}\n",
                )
                approval.append({
                    "id": vid,
                    "format": fmt,
                    "status": visual.get("status", "draft"),
                    "caption": cap,
                    "alt_text": alt,
                    "source_asset_ids": visual.get("source_asset_ids", []),
                    "created_at": visual.get("created_at"),
                })
            z.writestr(
                f"{run_id}/approval-summary.json",
                json.dumps({"run_id": run_id, "items": approval, "count": len(approval)}, indent=2),
            )

        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"content-pack-{run_id}.zip",
            mimetype="application/zip",
        )

    # ---- Global error handlers — keep tracebacks out of the UI ---------
    @app.errorhandler(404)
    def _not_found_page(e):
        accepts = request.headers.get("Accept", "") if request else ""
        if "application/json" in accepts or request.path.startswith("/api/"):
            return jsonify({"error": "not_found", "path": request.path}), 404
        body = f"""
<div style="text-align:center;padding:64px 24px">
  <div style="font-size:72px;font-weight:800;letter-spacing:-0.04em;
              background:linear-gradient(135deg,var(--accent),#7c3aed);
              -webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:8px">404</div>
  <h1 style="margin-bottom:8px">Page not found</h1>
  <p class="dim" style="margin-bottom:24px">The page <code>{_h(request.path)}</code> doesn't exist.</p>
  <a class="btn" href="{url_for('home')}">← Back to home</a>
</div>
"""
        return _layout("Not found", body, active="home"), 404

    @app.errorhandler(500)
    def _server_error_page(e):
        try:
            app.logger.exception("Unhandled server error")
        except Exception:
            pass
        accepts = request.headers.get("Accept", "") if request else ""
        if "application/json" in accepts or request.path.startswith("/api/"):
            return jsonify({"error": "internal_error"}), 500
        body = f"""
<div style="text-align:center;padding:64px 24px">
  <div style="font-size:64px;margin-bottom:12px">⚠️</div>
  <h1 style="margin-bottom:8px">Something went wrong</h1>
  <p class="dim" style="margin-bottom:24px;max-width:480px;margin-left:auto;margin-right:auto">
    The page failed to load. Refresh, or try a different action. Nothing you uploaded was lost.
  </p>
  <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
    <a class="btn" href="{url_for('home')}">← Back to home</a>
    <a class="btn secondary" href="javascript:history.back()">Go back</a>
  </div>
</div>
"""
        return _layout("Error", body, active="home"), 500

    @app.errorhandler(413)
    def _payload_too_large(e):
        accepts = request.headers.get("Accept", "") if request else ""
        if "application/json" in accepts or request.path.startswith("/api/"):
            return jsonify({"error": "file_too_large", "max_mb": 50}), 413
        body = f"""
<div style="text-align:center;padding:64px 24px">
  <div style="font-size:64px;margin-bottom:12px">📦</div>
  <h1 style="margin-bottom:8px">File too large</h1>
  <p class="dim" style="margin-bottom:24px">The upload exceeded 50 MB. Try compressing or trimming the file first.</p>
  <a class="btn" href="{url_for('home')}">← Back to home</a>
</div>
"""
        return _layout("File too large", body, active="home"), 413

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
