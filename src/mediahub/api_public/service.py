"""mediahub/api_public/service.py — transport-agnostic capability layer.

This is the **single definition of what the public platform can do**. The REST
blueprint (`/api/v1`) is one adapter over it, and the MCP server wraps that REST
surface — so there is one place where "list runs", "approve a card", "export a
pack" is defined.

Two kinds of capability:

* **Reads** are implemented here directly against ``DATA_DIR`` (run JSON, the
  ``runs`` table, brand kits, the data hub) with a **strict tenant check**: the
  caller's ``profile_id`` must equal the resource's owner. This is deliberately
  stricter than the session layer's legacy "unbound org" allowance — a token
  only ever sees its own org. Reading directly keeps this module import-safe
  (it never imports ``web.py``, avoiding the create_app ↔ blueprint cycle).

* **Writes** (start a run, approve/reject/edit a card) are deep in the
  monolith's gated logic — consent/safeguarding, brand-lock, review-task and
  group-approval gates that the public API must honour exactly. Rather than
  duplicate that safety-critical orchestration, ``web.py`` **registers
  callbacks** here from inside ``create_app`` (where those gates live); the
  public API calls through them, so approval-via-API runs the identical gates as
  approval-in-the-UI. If a callback isn't registered, the capability honestly
  reports unavailable — never a fabricated success.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from .errors import bad_request, not_found, unavailable

# --- registered write callbacks (wired by web.create_app) ------------------
# A run starter: (profile_id, file_bytes, file_name, opts) -> run_id
_RunStarter = Callable[..., str]
# A card action: (profile_id, run_id, card_id, action, payload) -> (body, status)
_CardAction = Callable[..., tuple[dict, int]]

# A pack exporter: (profile_id, run_id) -> (zip_bytes, download_name)
_PackExporter = Callable[..., tuple[bytes, str]]

_run_starter: Optional[_RunStarter] = None
_card_action: Optional[_CardAction] = None
_pack_exporter: Optional[_PackExporter] = None


def register_run_starter(fn: _RunStarter) -> None:
    global _run_starter
    _run_starter = fn


def register_card_action(fn: _CardAction) -> None:
    global _card_action
    _card_action = fn


def register_pack_exporter(fn: _PackExporter) -> None:
    global _pack_exporter
    _pack_exporter = fn


# --- storage paths (resolved live so per-test DATA_DIR overrides hold) ------
def _data_dir() -> Path:
    from . import _db

    return _db.data_dir()


def _runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", str(_data_dir() / "runs_v4")))


# --- run reads --------------------------------------------------------------
def _load_run_raw(run_id: str) -> Optional[dict]:
    p = _runs_dir() / f"{run_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _owns(profile_id: str, run_data: Optional[dict]) -> bool:
    """Strict tenant check: the token's org must own the run."""
    if not run_data:
        return False
    return (run_data.get("profile_id") or "") == (profile_id or "")


def list_runs(profile_id: str, *, limit: int = 50, offset: int = 0) -> dict:
    """List this org's runs (newest first) from the ``runs`` table."""
    from . import _db

    limit = max(1, min(200, int(limit or 50)))
    offset = max(0, int(offset or 0))
    items: list[dict] = []
    conn = _db.connect()
    try:
        try:
            try:
                rows = conn.execute(
                    "SELECT id, created_at, finished_at, status, meet_name, our_swims, "
                    "n_achievements, n_standout, error, file_name FROM runs "
                    "WHERE profile_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (profile_id, limit, offset),
                ).fetchall()
            except Exception:
                # A data.db from before the n_standout migration ran (the web
                # app adds the column at startup) — fall back rather than
                # reading a real run list as empty.
                rows = conn.execute(
                    "SELECT id, created_at, finished_at, status, meet_name, our_swims, "
                    "n_achievements, error, file_name FROM runs "
                    "WHERE profile_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (profile_id, limit, offset),
                ).fetchall()
        except Exception:
            # runs table not yet created in this DATA_DIR — honest empty list.
            rows = []
        for r in rows:
            items.append(
                {
                    "id": r["id"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "finished_at": r["finished_at"],
                    "meet_name": r["meet_name"],
                    "swim_count": r["our_swims"],
                    "achievement_count": r["n_achievements"],
                    # Distinct standout swims (deduped) — the honest headline
                    # figure. NULL for rows persisted before the column existed.
                    "standout_count": (r["n_standout"] if "n_standout" in r.keys() else None),
                    "file_name": r["file_name"],
                    "error": r["error"],
                }
            )
    finally:
        conn.close()
    return {"runs": items, "limit": limit, "offset": offset, "count": len(items)}


def get_run(profile_id: str, run_id: str) -> dict:
    """Public, whitelisted view of a single run (no DATA_DIR paths / secrets)."""
    data = _load_run_raw(run_id)
    if not _owns(profile_id, data):
        raise not_found("run")
    assert data is not None
    rec = data.get("recognition_report") or {}
    meet = data.get("meet") or {}
    return {
        "id": run_id,
        "profile_id": profile_id,
        "status": "done" if rec else (data.get("status") or "unknown"),
        "meet_name": data.get("meet_name") or meet.get("name") or "",
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "file_name": data.get("file_name"),
        "swim_count": data.get("our_swim_count"),
        "parsed_swim_count": data.get("parsed_swim_count"),
        "achievement_count": rec.get("n_achievements") or len(rec.get("ranked_achievements") or []),
        "standout_count": _standout_count(rec),
        "error": data.get("error"),
    }


def _standout_count(rec: dict) -> int:
    """Distinct standout swims for a recognition-report dict (deduped;
    recognition.swim_tiers). Fail-soft: a malformed report reads as 0."""
    try:
        from mediahub.recognition.swim_tiers import n_standout_for_report

        return int(n_standout_for_report(rec if isinstance(rec, dict) else None))
    except Exception:
        return 0


def _card_id_of(entry: dict) -> str:
    ach = entry.get("achievement") or {}
    return str(ach.get("swim_id") or entry.get("id") or "")


def _card_view(entry: dict, status: Optional[str] = None, edits: Optional[dict] = None) -> dict:
    """Whitelisted public shape for one ranked-achievement card."""
    ach = entry.get("achievement") or {}
    return {
        "id": _card_id_of(entry),
        "rank": entry.get("rank"),
        "priority_score": entry.get("priority_score"),
        "post_angle": entry.get("post_angle"),
        "status": status or "queue",
        "swimmer_name": ach.get("swimmer_name"),
        "event": ach.get("event"),
        "time": ach.get("time"),
        "achievement_type": ach.get("type"),
        "confidence": ach.get("confidence"),
        "description": ach.get("description"),
        "edited_captions": edits or {},
    }


def _statuses_for(run_id: str) -> dict[str, object]:
    """card_id -> CardWorkflowState (best-effort; empty if store unavailable)."""
    try:
        from mediahub.workflow.store import WorkflowStore

        return WorkflowStore(_runs_dir()).load(run_id)
    except Exception:
        return {}


def list_cards(profile_id: str, run_id: str, *, status: Optional[str] = None) -> dict:
    data = _load_run_raw(run_id)
    if not _owns(profile_id, data):
        raise not_found("run")
    assert data is not None
    rec = data.get("recognition_report") or {}
    ranked = rec.get("ranked_achievements") or []
    states = _statuses_for(run_id)
    cards: list[dict] = []
    for entry in ranked:
        cid = _card_id_of(entry)
        st = states.get(cid)
        st_str = getattr(getattr(st, "status", None), "value", None) or "queue"
        edits = getattr(st, "edited_captions", None) if st else None
        view = _card_view(entry, st_str, edits)
        if status and view["status"] != status:
            continue
        cards.append(view)
    return {"run_id": run_id, "cards": cards, "count": len(cards)}


def get_card(profile_id: str, run_id: str, card_id: str) -> dict:
    res = list_cards(profile_id, run_id)
    for c in res["cards"]:
        if c["id"] == card_id:
            return c
    raise not_found("card")


# --- run + card writes (through registered, gated callbacks) ----------------
def submit_results(
    profile_id: str,
    file_bytes: bytes,
    file_name: str,
    *,
    fetch_pbs: bool = True,
    club_filter: Optional[str] = None,
) -> dict:
    """Trigger a pipeline run from an uploaded results file. Returns the run id.

    Honest-errors (503) if the pipeline starter isn't wired (e.g. the service is
    imported outside the running web app)."""
    if _run_starter is None:
        raise unavailable("Run submission is not available in this context.")
    if not file_bytes:
        raise bad_request("Empty file: provide the results file as the request body.")
    name = (file_name or "results").strip() or "results"
    run_id = _run_starter(
        profile_id,
        file_bytes,
        name,
        fetch_pbs=fetch_pbs,
        club_filter=club_filter,
    )
    return {"id": run_id, "status": "queued"}


def set_card_status(
    profile_id: str,
    run_id: str,
    card_id: str,
    status: str,
    *,
    notes: Optional[str] = None,
    actor_email: str = "",
    actor: str = "",
) -> tuple[dict, int]:
    """Approve / reject / requeue a card — through the SAME gates as the UI.

    ``actor_email`` (the token owner) is recorded as the approver so a group-
    approval rule is enforced against a real identity, never bypassed. ``actor``
    (finding #116) is the machine-distinguishable audit label — e.g.
    ``api-token:<token_id>`` — stamped onto the durable workflow state and the
    approval telemetry so an agent's approval is never mistaken for a human's."""
    if _card_action is None:
        raise unavailable("Card actions are not available in this context.")
    payload = {
        "action": "set_status",
        "status": status,
        "notes": notes,
        "_actor_email": actor_email,
        "_actor": actor,
    }
    return _card_action(profile_id, run_id, card_id, "set_status", payload)


def edit_card(
    profile_id: str,
    run_id: str,
    card_id: str,
    edits: dict,
    *,
    actor_email: str = "",
    actor: str = "",
) -> tuple[dict, int]:
    """Edit a card's caption overrides — through the same gates as the UI.

    ``actor`` is the machine-distinguishable audit label (finding #116), as in
    :func:`set_card_status`."""
    if _card_action is None:
        raise unavailable("Card actions are not available in this context.")
    if not isinstance(edits, dict):
        raise bad_request("`edits` must be an object of caption overrides.")
    payload = {
        "action": "set_edits",
        "edits": edits,
        "_actor_email": actor_email,
        "_actor": actor,
    }
    return _card_action(profile_id, run_id, card_id, "set_edits", payload)


def export_pack(profile_id: str, run_id: str) -> tuple[bytes, str]:
    """Build the run's content-pack ZIP. Returns (zip_bytes, download_name).

    Tenant-checked before any work; honest-errors if the exporter isn't wired or
    the run has no rendered visuals yet."""
    if not _owns(profile_id, _load_run_raw(run_id)):
        raise not_found("run")
    if _pack_exporter is None:
        raise unavailable("Pack export is not available in this context.")
    zip_bytes, name = _pack_exporter(profile_id, run_id)
    if not zip_bytes:
        raise not_found("content pack (no graphics rendered yet)")
    return zip_bytes, name


# --- brand + data reads -----------------------------------------------------
def list_brand_kits(profile_id: str) -> dict:
    """List the org's brand kits (palette/fonts only — no internal paths)."""
    try:
        from mediahub.brand import kits as _kits
        from mediahub.web.club_profile import load_profile

        prof = load_profile(profile_id)
        if prof is None:
            return {"brand_kits": [], "count": 0}
        refs = _kits.list_kits(prof)
        default_id = _kits.default_kit_id(prof)
    except Exception:
        return {"brand_kits": [], "count": 0}
    out = []
    for k in refs or []:
        pal = k.palette or {}
        out.append(
            {
                "id": k.kit_id,
                "name": k.name,
                "role": k.role,
                "is_default": k.kit_id == default_id,
                "primary_colour": pal.get("primary"),
                "secondary_colour": pal.get("secondary"),
                "accent_colour": pal.get("accent"),
                "font_pairing": k.font_pairing or None,
            }
        )
    return {"brand_kits": out, "count": len(out)}


# --- file interop (roadmap 1.21 build 4) -----------------------------------
def _kit_colours(profile_id: str, kit_id: str):
    """Resolve a kit's ordered colours + role names, or raise not_found."""
    from mediahub.brand import kits as _kits
    from mediahub.web.club_profile import load_profile

    prof = load_profile(profile_id)
    if prof is None:
        raise not_found("brand kit")
    kit = _kits.get_kit(prof, kit_id)
    if kit is None:
        raise not_found("brand kit")
    pal = kit.palette or {}
    order = ["primary", "secondary", "accent", "fourth"]
    names = [r for r in order if pal.get(r)]
    colours = [pal[r] for r in names]
    return kit, colours, names


def export_palette(profile_id: str, kit_id: str, fmt: str = "ase") -> tuple[bytes, str, str]:
    """Export a kit's palette. Returns (bytes, mime, download_name)."""
    from mediahub.interop import palette_export

    if fmt not in palette_export.FORMATS:
        raise bad_request(f"format must be one of {palette_export.FORMATS}")
    kit, colours, names = _kit_colours(profile_id, kit_id)
    if not colours:
        raise not_found("palette (kit has no colours)")
    data = palette_export.export(colours, fmt, palette_name=kit.name, names=names)
    return data, palette_export.MIME[fmt], f"{kit_id}-palette{palette_export.EXT[fmt]}"


def export_brand_bundle(profile_id: str, kit_id: str) -> tuple[bytes, str]:
    """Export a kit as a ZIP bundle. Returns (zip_bytes, download_name)."""
    from mediahub.interop import asset_bundle
    from mediahub.web.club_profile import load_profile

    kit, colours, names = _kit_colours(profile_id, kit_id)
    prof = load_profile(profile_id)
    data = asset_bundle.build_brand_bundle(
        kit.name,
        colours,
        font_pairing=kit.font_pairing,
        role_names=names,
        org_name=(getattr(prof, "display_name", "") or ""),
    )
    return data, f"{kit_id}-brand-bundle.zip"


def import_svg_asset(profile_id: str, svg_bytes: bytes, filename: str = "import.svg") -> dict:
    from mediahub.interop.svg_import import SvgImportError, import_svg

    try:
        return import_svg(profile_id, svg_bytes, filename)
    except SvgImportError as e:
        raise bad_request(str(e))


def import_psd_asset(profile_id: str, psd_bytes: bytes, filename: str = "import.psd") -> dict:
    from mediahub.interop.psd_import import PsdImportError, PsdImportUnavailable, import_psd

    try:
        return import_psd(profile_id, psd_bytes, filename)
    except PsdImportUnavailable as e:
        raise unavailable(str(e))
    except PsdImportError as e:
        raise bad_request(str(e))


# --- webhooks (roadmap 1.21 build 2) ---------------------------------------
def list_webhooks(profile_id: str) -> dict:
    from mediahub.webhooks.registry import EndpointStore

    eps = EndpointStore().list_for_profile(profile_id)
    return {"webhooks": [e.to_public_dict() for e in eps], "count": len(eps)}


def create_webhook(
    profile_id: str, url: str, events, *, description: str = "", created_by: str = ""
) -> dict:
    from mediahub.webhooks.registry import EndpointStore

    try:
        ep = EndpointStore().create(
            profile_id, url, events=events, description=description, created_by=created_by
        )
    except ValueError as e:
        raise bad_request(str(e))
    # The signing secret is returned once here so the integrator can configure
    # their receiver; it is also retrievable by the org owner in the app.
    return ep.to_public_dict(include_secret=True)


def get_webhook(profile_id: str, endpoint_id: str) -> dict:
    from mediahub.webhooks.registry import EndpointStore

    ep = EndpointStore().get(endpoint_id)
    if ep is None or ep.profile_id != profile_id:
        raise not_found("webhook")
    return ep.to_public_dict()


def delete_webhook(profile_id: str, endpoint_id: str) -> dict:
    from mediahub.webhooks.registry import EndpointStore

    if not EndpointStore().delete(endpoint_id, profile_id):
        raise not_found("webhook")
    return {"deleted": True, "id": endpoint_id}


def list_webhook_deliveries(profile_id: str, endpoint_id: str, *, limit: int = 50) -> dict:
    from mediahub.webhooks.delivery import DeliveryStore
    from mediahub.webhooks.registry import EndpointStore

    ep = EndpointStore().get(endpoint_id)
    if ep is None or ep.profile_id != profile_id:
        raise not_found("webhook")
    deliveries = DeliveryStore().list_for_endpoint(endpoint_id, limit=limit)
    return {"endpoint_id": endpoint_id, "deliveries": deliveries, "count": len(deliveries)}


def list_data_tables(profile_id: str) -> dict:
    """List the org's data-hub tables (names + row/column counts only)."""
    try:
        from mediahub.data_hub.store import list_org_tables

        tables = list_org_tables(profile_id)
    except Exception:
        return {"tables": [], "count": 0}
    out = []
    for t in tables or []:
        out.append(
            {
                "id": t.get("table_id"),
                "name": t.get("title"),
                "kind": t.get("kind"),
                "row_count": int(t.get("n_rows") or 0),
                "column_count": int(t.get("n_columns") or 0),
                "description": t.get("description") or "",
            }
        )
    return {"tables": out, "count": len(out)}


__all__ = [
    "register_run_starter",
    "register_card_action",
    "register_pack_exporter",
    "list_runs",
    "get_run",
    "list_cards",
    "get_card",
    "submit_results",
    "set_card_status",
    "edit_card",
    "export_pack",
    "list_brand_kits",
    "list_data_tables",
    "list_webhooks",
    "create_webhook",
    "get_webhook",
    "delete_webhook",
    "list_webhook_deliveries",
    "export_palette",
    "export_brand_bundle",
    "import_svg_asset",
    "import_psd_asset",
]
