"""Assorted JSON APIs: audio, brand, documents, data-hub, org, jobs, notifications, assistant.

Carved out of ``web.create_app`` (deep-review finding #15, final stage).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
any captured ``app`` became ``current_app``. Endpoint names are
PRESERVED via ``add_url_rule`` (ADR-0031).
"""

from __future__ import annotations

from pathlib import Path
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from flask import (
    Response,
    abort,
    current_app,
    jsonify,
    redirect,
    request,
    send_file,
    session,
    url_for,
)

from mediahub.web import web as W


def upload_from_url_status(job_id):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id or ""):
        return jsonify({"status": "unknown", "error": "Bad job id"}), 400
    entry = W._url_job_get(job_id)
    if entry is None:
        return jsonify({"status": "unknown"}), 404
    # Owner gate — a job id is 48-bit random, but bind it to the creating
    # session's active org anyway (same posture as the reel/variant/export
    # job routes) so a foreign or guessed id can't read another org's crawl
    # progress or the staged run_id. Report it as "unknown" — indistinguishable
    # from a nonexistent id — so foreign existence isn't revealed (404, not 403).
    if (entry.get("owner_pid") or "") != (W._active_profile_id() or ""):
        return jsonify({"status": "unknown"}), 404
    status = entry.get("status", "unknown")
    # Stall guard: a crawl runs in a background thread, so if it hangs (a
    # render that never settles) or its worker is recycled mid-run, the job
    # can sit in "running"/"queued" forever and the page shows "Reading the
    # site…" with no end. The heartbeat is refreshed on every progress
    # update; if it's gone quiet well past the crawl's own budgets, report
    # an honest terminal error instead of polling into the void.
    if status in ("running", "queued"):
        hb = float(entry.get("heartbeat") or 0.0)
        if hb and (time.time() - hb) > W._URL_JOB_STALL_S:
            status = "error"
            entry = {
                **entry,
                "status": "error",
                "error": (
                    # F-3: no env-var names in customer copy (hosted SaaS —
                    # the customer has no shell). The operator sees the
                    # tunables in the server log.
                    "This site is unusually heavy to read and the fetch didn't "
                    "finish. Try again, or download the results file from the site "
                    "and upload it directly instead."
                ),
            }
    payload = {
        "status": status,
        "phase": entry.get("phase", ""),
        "progress": entry.get("progress", ""),
        "percent": entry.get("percent", 0),
        # Live counters for the progress UI's stat chips (absent → zeros).
        "stats": {
            "pages": entry.get("pages", 0),
            "discovered": entry.get("discovered", 0),
            "kept": entry.get("kept", 0),
            "kb": entry.get("kb", 0),
        },
    }
    if status == "done" and entry.get("run_id"):
        payload["redirect"] = url_for("upload_configure", run_id=entry["run_id"])
    elif status == "error":
        payload["error"] = entry.get("error", "The fetch failed.")
    return jsonify(payload)


def api_status_json():
    """JSON shape of the public status page — for external monitors
    and dashboards that want the raw uptime numbers."""
    from mediahub.observability import uptime as _uptime

    # /api/status is public and unauthenticated. The heartbeat's ``error``
    # field carries the raw deep-/health failure string, which can include
    # an internal filesystem path (e.g. "database: unable to open database
    # file /srv/data/data.db") or an OS error. Drop it from this public
    # surface — the ``ok`` flag already signals the failure honestly, with
    # no internal text. The operator HTML views never rendered it.
    latest = _uptime.latest_heartbeat()
    if isinstance(latest, dict):
        latest.pop("error", None)

    return jsonify(
        {
            "ok": True,
            "version": W.APP_VERSION,
            "latest_heartbeat": latest,
            "windows": {
                "24h": _uptime.uptime_stats(window_hours=24),
                "7d": _uptime.uptime_stats(window_hours=24 * 7),
                "30d": _uptime.uptime_stats(window_hours=24 * 30),
            },
            "recent_gaps": _uptime.recent_gaps(window_hours=24 * 30, limit=10),
        }
    )


def api_notifications():
    """List the active org's notifications plus its unread count.

    Signed-out (no active org) returns an empty, zero-unread payload so the
    header poll is harmless on public pages rather than a 403 the client
    has to special-case.
    """
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": True, "unread": 0, "items": []})
    unread_only = (request.args.get("unread") or "").strip().lower() in ("1", "true", "yes")
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    from mediahub.notify import inbox as _inbox

    # 1.18: scope to what this member may see — org-wide rows plus mentions /
    # tasks addressed to them. Signed-out-but-pinned (pilot) sees org-wide.
    me = W._auth.current_user_email()
    items = _inbox.list_for(pid, limit=limit, unread_only=unread_only, user_email=me)
    for it in items:
        it["link"] = W._notification_link(it)
    return jsonify({"ok": True, "unread": _inbox.unread_count(pid, user_email=me), "items": items})


def api_notifications_read(notif_id: str):
    """Mark one notification read for the active org (tenant-scoped)."""
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.notify import inbox as _inbox

    me = W._auth.current_user_email()
    changed = _inbox.mark_read(pid, notif_id, user_email=me)
    return jsonify(
        {"ok": True, "changed": changed, "unread": _inbox.unread_count(pid, user_email=me)}
    )


def api_notifications_read_all():
    """Mark every unread notification read for the active org."""
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.notify import inbox as _inbox

    me = W._auth.current_user_email()
    n = _inbox.mark_all_read(pid, user_email=me)
    return jsonify({"ok": True, "marked": n, "unread": 0})


# Audio engine (roadmap 1.8) — library, voices, pronunciation lexicon,
# own-audio upload + rights, and consent-gated voice features.
def api_audio_library():
    """List the audio catalogue (bundled CC0 pool + operator directories)."""
    from flask import request as _req

    try:
        from mediahub.audio import load_library
    except Exception as e:
        W.log.warning("audio backend unavailable: %s", e)
        return jsonify({"error": "audio_unavailable"}), 503
    lib = load_library()
    tracks = lib.tracks(
        kind=(_req.args.get("kind") or None),
        mood=(_req.args.get("mood") or None),
        platform=(_req.args.get("platform") or None),
    )
    return jsonify({"ok": True, "tracks": [t.to_dict() for t in tracks]})


def api_audio_track(track_id):
    """Serve a catalogue track file for in-browser preview.

    Only library tracks (bundled + operator directories) are addressable by
    id here — they are deployment-global, not per-org, so there is no IDOR
    surface, and the id resolves to a known file (no path traversal).
    """
    try:
        from mediahub.audio import load_library
    except Exception as e:
        W.log.warning("audio backend unavailable: %s", e)
        return jsonify({"error": "audio_unavailable"}), 503
    track = load_library().get(track_id)
    if track is None or not Path(track.path).is_file():
        return jsonify({"error": "not_found"}), 404
    mime = W._AUDIO_MIME.get(Path(track.path).suffix.lower(), "application/octet-stream")
    return send_file(str(track.path), mimetype=mime, as_attachment=False)


def api_audio_voices():
    """The voice catalogue + the active TTS provider status."""
    try:
        from mediahub.audio import list_voices
        from mediahub.visual import voiceover as _vo
    except Exception as e:
        W.log.warning("audio backend unavailable: %s", e)
        return jsonify({"error": "audio_unavailable"}), 503
    try:
        status = _vo.tts_provider_status()
    except Exception:
        status = {}
    return jsonify({"ok": True, "voices": [v.to_dict() for v in list_voices()], "tts": status})


def api_audio_lexicon():
    """Per-organisation pronunciation lexicon CRUD (org-scoped).

    GET returns the org's map; POST with ``op=set`` (written+spoken) or
    ``op=remove`` (written) mutates it. Form posts redirect back to the
    Audio settings page; XHR/JSON callers get JSON.
    """
    from flask import request as _req

    pid = W._active_profile_id()
    if not pid:
        # SRV-4: a browser form POST must land on the banner, not raw JSON.
        return W._audio_back_or_json(
            {"error": "no_org", "message": "Choose an organisation to manage a lexicon."},
            403,
        )
    try:
        from mediahub.audio.voice import OrgLexicon
    except Exception as e:
        W.log.warning("audio lexicon unavailable: %s", e)
        return W._audio_back_or_json({"error": "audio_unavailable"}, 503)
    lex = OrgLexicon(pid)
    if _req.method == "GET":
        return jsonify({"ok": True, "entries": lex.entries()})
    op = (_req.form.get("op") or _req.values.get("op") or "set").strip().lower()
    try:
        if op == "remove":
            lex.remove((_req.form.get("written") or "").strip())
        else:
            lex.set(
                (_req.form.get("written") or "").strip(),
                (_req.form.get("spoken") or "").strip(),
            )
    except ValueError as e:
        return W._audio_back_or_json(
            {"error": "invalid", "message": str(e)}, 400, flash_status="lexicon_invalid"
        )
    return W._audio_back_or_json(
        {"ok": True, "entries": lex.entries()},
        flash_status="lexicon_removed" if op == "remove" else "lexicon_saved",
    )


def api_audio_upload():
    """Upload an organisation's own audio with a licence attestation (1.8).

    Stored org-scoped under DATA_DIR, fingerprinted, and recorded in the
    rights ledger. Optionally loudness-levelled/denoised via clean.py when
    ``enhance=1`` is set (e.g. a browser voice recording).
    """
    from flask import request as _req

    pid = W._active_profile_id()
    if not pid:
        return W._audio_back_or_json(
            {"error": "no_org", "message": "Choose an organisation to upload audio."}, 403
        )
    f = _req.files.get("file")
    if not f:
        return W._audio_back_or_json(
            {"error": "no_file", "message": "Choose an audio file first."}, 400
        )
    ext = Path(f.filename or "clip.wav").suffix.lower()
    if ext not in W._AUDIO_UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(s.lstrip(".").upper() for s in W._AUDIO_UPLOAD_SUFFIXES))
        return W._audio_back_or_json(
            {
                "error": "bad_type",
                "message": f"That file type isn't supported. Use one of: {allowed}.",
            },
            415,
        )
    try:
        from mediahub.audio import rights as _rights
        from mediahub.audio.library import Licence
    except Exception as e:
        W.log.warning("audio upload backend unavailable: %s", e)
        return W._audio_back_or_json(
            {"error": "audio_unavailable", "message": "Audio isn't available."},
            503,
        )

    import uuid as _uuid

    upload_dir = W.DATA_DIR / "audio_uploads" / pid
    upload_dir.mkdir(parents=True, exist_ok=True)
    asset_id = _uuid.uuid4().hex[:12]
    dest = upload_dir / f"{asset_id}{ext}"
    f.save(str(dest))
    try:
        if dest.stat().st_size > W._AUDIO_UPLOAD_MAX_BYTES:
            dest.unlink(missing_ok=True)
            return W._audio_back_or_json(
                {"error": "too_large", "message": "That audio is over the 25 MB limit."}, 413
            )
    except OSError:
        return W._audio_back_or_json(
            {
                "error": "save_failed",
                "message": "We couldn't save that file — please try again.",
            },
            500,
        )

    # Optional one-tap clean-up (denoise + loudness) for recordings.
    if (_req.form.get("enhance") or "").strip().lower() in {"1", "true", "on", "yes"}:
        try:
            from mediahub.audio import clean as _clean

            cleaned = upload_dir / f"{asset_id}_clean.wav"
            _clean.enhance_voice(dest, cleaned)
            dest.unlink(missing_ok=True)
            dest = cleaned
        except Exception:
            pass  # keep the original on any cleanup failure — never lose the upload

    platforms = tuple(
        p.strip().lower() for p in (_req.form.get("platforms") or "").split(",") if p.strip()
    )
    licence = Licence(
        name=(_req.form.get("licence_name") or "operator-supplied").strip(),
        url=(_req.form.get("licence_url") or "").strip(),
        attribution=(_req.form.get("attribution") or "").strip(),
        source="operator upload",
        commercial_ok=(_req.form.get("commercial_ok") or "").strip().lower()
        in {"1", "true", "on", "yes"},
    )
    check = _rights.check_upload(dest)
    rec = _rights.attest_upload(
        dest,
        asset_id=asset_id,
        profile_id=pid,
        licence=licence,
        platforms=platforms or _rights.PLATFORMS,
        attested_by=pid,
        notes=(_req.form.get("notes") or "").strip(),
    )
    return W._audio_back_or_json(
        {
            "ok": True,
            "asset": rec.to_dict(),
            "duplicate": check.is_duplicate,
            "fingerprint_method": check.fingerprint.method,
        },
        flash_status="audio_added",
    )


def api_audio_upload_file(asset_id):
    """D-7: serve one of the active org's own uploaded audio files for
    in-browser preview. Tenant-scoped by the rights ledger's profile_id —
    an id owned by another org 404s (no IDOR), and the filename resolves to
    a basename inside the org's own directory (no path traversal)."""
    from flask import send_file

    from mediahub.audio import rights as _rights

    pid = W._active_profile_id()
    if not pid:
        abort(404)
    rec = _rights.RightsLedger().get(asset_id)
    if rec is None or rec.profile_id != pid:
        abort(404)
    path = W.DATA_DIR / "audio_uploads" / pid / Path(rec.filename).name
    if not path.is_file():
        abort(404)
    return send_file(str(path))


def api_audio_upload_delete(asset_id):
    """D-7: remove one of the active org's own uploaded audio files and its
    rights-ledger row. Tenant-scoped exactly like the preview route."""
    from mediahub.audio import rights as _rights

    pid = W._active_profile_id()
    if not pid:
        return W._audio_back_or_json({"error": "no_org"}, 403)
    led = _rights.RightsLedger()
    rec = led.get(asset_id)
    if rec is None or rec.profile_id != pid:
        return W._audio_back_or_json({"error": "not_found"}, 404)
    try:
        (W.DATA_DIR / "audio_uploads" / pid / Path(rec.filename).name).unlink(missing_ok=True)
    except OSError:
        pass
    led.delete(asset_id)
    return W._audio_back_or_json({"ok": True}, flash_status="audio_removed")


def api_audio_voice_consent():
    """Grant/revoke the consent that gates voice cloning/changer (org-scoped)."""
    from flask import request as _req

    pid = W._active_profile_id()
    if not pid:
        # SRV-4: a browser form POST must land on the banner, not raw JSON.
        return W._audio_back_or_json({"error": "no_org"}, 403)
    try:
        from mediahub.audio.consent import FEATURES, ConsentStore
    except Exception as e:
        W.log.warning("audio consent store unavailable: %s", e)
        return W._audio_back_or_json({"error": "audio_unavailable"}, 503)
    store = ConsentStore()
    if _req.method == "GET":
        return jsonify(
            {
                "ok": True,
                "features": list(FEATURES),
                "active": [r.to_dict() for r in store.active(pid)],
            }
        )
    feature = (_req.form.get("feature") or "").strip().lower()
    action = (_req.form.get("action") or "grant").strip().lower()
    try:
        if action == "revoke":
            store.revoke(pid, feature, by=pid)
        else:
            store.grant(
                pid,
                feature,
                voice_owner=(_req.form.get("voice_owner") or "").strip(),
                consent_ref=(_req.form.get("consent_ref") or "").strip(),
                granted_by=pid,
            )
    except ValueError as e:
        return W._audio_back_or_json(
            {"error": "invalid", "message": str(e)}, 400, flash_status="consent_invalid"
        )
    return W._audio_back_or_json(
        {"ok": True},
        flash_status="consent_revoked" if action == "revoke" else "consent_recorded",
    )


def api_audio_suggest():
    """Suggest a track for a mood/kind — AI when available, else deterministic.

    Always 200 (never 5xx — a bare GET to this advisory endpoint must not
    pollute uptime): returns the AI mood-matched pick when a provider is
    configured, otherwise the deterministic library pick. ``method`` says
    which path produced the suggestion ("ai" / "deterministic" / "none").
    """
    from flask import request as _req

    try:
        from mediahub.audio import load_library
        from mediahub.audio.select import select_or_default
    except Exception as e:
        W.log.warning("audio library unavailable: %s", e)
        return jsonify({"ok": False, "available": False})
    lib = load_library()
    mood = (_req.args.get("mood") or "").strip()
    kind = (_req.args.get("kind") or "music").strip()
    sel = select_or_default(
        lib, content_key=(mood or "suggest"), kind=kind, mood_hint=(mood or None)
    )
    return jsonify(
        {
            "ok": True,
            "available": sel.track is not None,
            "method": sel.method,
            "arc": sel.arc,
            "track": sel.track.to_dict() if sel.track else None,
        }
    )


def api_llm_status():
    try:
        from mediahub.media_ai.llm import is_available as _llm_available, active_provider
    except Exception:
        return jsonify({"live": False, "provider": None, "provider_label": None})
    provider = active_provider()
    live = _llm_available()
    # Public, stable provider names — gemini (default/free) and
    # anthropic (paid, operator-set). Anything else returns None.
    public_provider = (
        {
            "gemini-api": "gemini",
            "anthropic-api": "anthropic",
        }.get(provider)
        if live
        else None
    )
    provider_label = (
        {
            "gemini-api": "Google Gemini",
            "anthropic-api": "Anthropic (Claude)",
        }.get(provider)
        if live
        else None
    )
    return jsonify(
        {
            "live": live,
            "provider": public_provider,
            "provider_label": provider_label,
        }
    )


def api_channel_preview():
    """Compute a single card's per-platform preview (caption fold, hashtag
    cap, safe zone) for live editor previews. Pure text/geometry rules —
    no stored data read — but org-gated for consistency."""
    if not W._active_profile_id():
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.channel_preview import preview_card

    body = request.get_json(silent=True) or {}
    # Coerce hashtags to a real list: a truthy non-list (a number/bool) would
    # otherwise reach preview_card's ``len([h for h in hashtags ...])`` and raise
    # a TypeError that 500s the endpoint. Only a genuine list carries hashtags.
    raw_tags = body.get("hashtags")
    card = {
        "caption": str(body.get("caption") or ""),
        "hashtags": raw_tags if isinstance(raw_tags, list) else [],
        "platform": body.get("platform_label") or "",
    }
    pv = preview_card(
        card, str(body.get("platform") or "instagram"), format_name=body.get("format")
    )
    if pv is None:
        return jsonify({"error": "Unknown platform."}), 400
    return jsonify({"ok": True, "preview": pv})


def api_studio_render():
    # Render one studio brief to a PNG and return it as a base64 data URI
    # plus its explainability sidecar (resolved --mh-* roles, pack why,
    # archetype signature, honest legibility/taste notices). JSON-bodied, so
    # it is CSRF-exempt by content-type. No tenant data is read or written —
    # the brief is built entirely from the (coerced, renderer-safe) request.
    import base64 as _b64
    import tempfile as _tempfile
    import time as _time

    from mediahub.web import design_editor as _studio

    payload = request.get_json(silent=True)
    params = _studio.coerce_params(payload if isinstance(payload, dict) else {})

    sig = params.signature()
    cached = W._studio_render_cache.get(sig)
    if cached is not None:
        return jsonify(cached)

    try:
        from mediahub.graphic_renderer.render import render_brief
    except Exception:  # pragma: no cover - renderer module import failure
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "renderer_unavailable",
                    "message": "The graphics renderer is unavailable on this server.",
                }
            ),
            503,
        )

    brief = _studio.build_brief_from_params(params)
    brand_kit = _studio.brand_kit_for_params(params)
    t0 = _time.time()
    try:
        # Same Chromium-concurrency gate as every other still/motion
        # render route: each render_brief launches a one-shot Chromium,
        # so ungated concurrent studio previews would pile up unbounded
        # CPU/memory on the worker (the signature cache above only
        # dedupes identical params).
        with W._render_slot("preview", sig, timeout=W._preview_render_timeout()):
            with _tempfile.TemporaryDirectory() as _d:
                result = render_brief(
                    brief,
                    output_dir=_d,
                    size=params.size,
                    format_name=params.format_id,
                    brand_kit=brand_kit,
                    quality=params.render_quality,
                )
                png_bytes = Path(result.visual.file_path).read_bytes()
                # QA-011: the live preview composes at the SAME native geometry
                # as the download (so fixed-px archetype furniture keeps its
                # proportions and the result time never clips / collides). The
                # light, snappy preview payload comes from downsampling the
                # finished native render — never from shrinking the geometry.
                _raster = params.preview_raster_size
                if _raster != params.size:
                    png_bytes = _studio.downscale_png_bytes(png_bytes, _raster)
    except W._RenderBusy:
        return W._render_busy_response("preview")
    except RuntimeError as exc:
        # Playwright/Chromium not installed — surface an honest error rather
        # than ever fabricating a preview image (CLAUDE.md honest-error rule).
        W.log.warning("studio render unavailable: %s", exc)
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "render_unavailable",
                    "message": "Live rendering is temporarily unavailable on this server.",
                }
            ),
            503,
        )
    except Exception:
        W.log.exception("studio render failed")
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "render_failed",
                    "message": "Could not render this design — try a different combination.",
                }
            ),
            500,
        )

    out = {
        "ok": True,
        "image": "data:image/png;base64," + _b64.b64encode(png_bytes).decode("ascii"),
        "meta": _studio.explain(params),
        "render_ms": int((_time.time() - t0) * 1000),
    }
    W._studio_render_cache[sig] = out
    return jsonify(out)


def api_brand_kit_create():
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand.kits import new_kit_id, upsert_kit, normalise_kit

    prof = W._active_profile()
    # A created kit is never the primary: an org has exactly one primary
    # livery (synthesised or materialised), and a second role="primary" kit
    # is undeletable (delete_kit protects every primary). Constrain to the
    # four creatable roles so a hand-crafted/invalid role can't slip past
    # normalise_kit's "unknown → primary" coercion and mint a duplicate.
    role = (request.form.get("role") or "sponsor").strip().lower()
    if role not in ("sponsor", "event", "section", "personal"):
        role = "sponsor"
    raw = {
        "kit_id": new_kit_id(),
        "name": (request.form.get("name") or "").strip(),
        "role": role,
        "palette": W._form_palette(),
    }
    kit = normalise_kit(raw)
    if kit is None:
        return W._brand_redirect(err="A kit needs a name.")
    upsert_kit(prof, kit)
    W.save_profile(prof)
    return W._brand_redirect(msg=f"Created kit “{kit.name}”.")


def api_brand_kit_update(kit_id):
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand.kits import get_kit, upsert_kit, normalise_kit, LOCKABLE_TOKENS

    prof = W._active_profile()
    existing = get_kit(prof, kit_id)
    if existing is None:
        return W._brand_redirect(err="Kit not found.")
    locks = [t for t in request.form.getlist("lock") if t in LOCKABLE_TOKENS]
    from mediahub.workflow.governance import normalise_approver_rule

    # 1.18 per-type overrides: one row per named sensitive type; a row with
    # min_approvers 0/blank is dropped by normalise (inherits the base).
    by_type_raw: dict = {}
    for type_key in ("safeguarding", "sponsor_activation"):
        by_type_raw[type_key] = {
            "min_approvers": request.form.get(f"min_approvers__{type_key}", "0"),
            "require_owner": bool(request.form.get(f"require_owner__{type_key}")),
        }
    approver_rule = normalise_approver_rule(
        {
            "min_approvers": request.form.get("min_approvers", "1"),
            "require_owner": bool(request.form.get("require_owner")),
            "by_type": by_type_raw,
        }
    )
    raw = existing.to_dict()
    raw.update(
        {
            "name": (request.form.get("name") or existing.name).strip(),
            "palette": W._form_palette() or existing.palette,
            "font_pairing": (request.form.get("font_pairing") or "").strip(),
            "tone": (request.form.get("tone") or "").strip(),
            "locks": locks,
            "approver_rule": approver_rule,
        }
    )
    kit = normalise_kit(raw)
    if kit is None:
        return W._brand_redirect(err="A kit needs a name.")
    # F-10 — be honest about anything the normaliser dropped instead of a
    # blanket "Saved kit". With colour pickers + dropdowns this is normally
    # empty, but a palette-file import or a hand-crafted POST can still carry
    # an unreadable value, and the user deserves to know it didn't stick.
    submitted_pal = W._form_palette()
    dropped = [
        slot for slot, val in submitted_pal.items() if val and slot not in (kit.palette or {})
    ]
    upsert_kit(prof, kit)
    W.save_profile(prof)
    if dropped:
        return W._brand_redirect(
            msg=f"Saved kit “{kit.name}” — but could not read the "
            f"{', '.join(dropped)} colour(s); please give a valid #hex."
        )
    return W._brand_redirect(msg=f"Saved kit “{kit.name}”.")


def api_brand_kit_delete(kit_id):
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand.kits import delete_kit

    prof = W._active_profile()
    ok = delete_kit(prof, kit_id)
    if ok:
        W.save_profile(prof)
        return W._brand_redirect(msg="Kit deleted.")
    return W._brand_redirect(err="That kit can't be deleted (the primary kit always stays).")


def api_brand_kit_set_default(kit_id):
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand.kits import set_default_kit

    prof = W._active_profile()
    if set_default_kit(prof, kit_id):
        W.save_profile(prof)
        return W._brand_redirect(msg="Default kit updated.")
    return W._brand_redirect(err="Unknown kit.")


def api_brand_kit_palette_import(kit_id):
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand.kits import get_kit, upsert_kit, normalise_kit
    from mediahub.brand.palette_file import (
        PaletteFileError,
        colours_to_kit_palette,
        parse_palette_file,
    )

    prof = W._active_profile()
    existing = get_kit(prof, kit_id)
    if existing is None:
        return W._brand_redirect(err="Kit not found.")
    f = request.files.get("palette_file")
    if f is None or not f.filename:
        return W._brand_redirect(err="Choose a .ase or Color JSON file to import.")
    data = f.read()
    # Cap the upload so a hostile file can't exhaust memory (palettes are tiny).
    if len(data) > 2 * 1024 * 1024:
        return W._brand_redirect(err="Palette file too large (max 2 MB).")
    try:
        colours = parse_palette_file(data, f.filename)
    except PaletteFileError as e:
        return W._brand_redirect(err=f"Could not read that palette file: {e}")
    raw = existing.to_dict()
    raw["palette"] = colours_to_kit_palette(colours)
    kit = normalise_kit(raw)
    upsert_kit(prof, kit)
    W.save_profile(prof)
    n = len(kit.palette)
    return W._brand_redirect(msg=f"Imported {n} colour(s) into “{kit.name}”.")


def api_brand_kit_resweep_preview(kit_id):
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand import kits as _kits, resweep as _resweep

    prof = W._active_profile()
    kit = _kits.get_kit(prof, kit_id)
    if kit is None:
        return jsonify({"error": "kit_not_found"}), 404
    preview = _resweep.preview_kit_change(prof, kit, runs_dir=W.RUNS_DIR)
    return jsonify(preview.to_dict())


def api_brand_kit_resweep_apply(kit_id):
    pid = W._active_profile_id()
    if not pid or not W._brand_can_admin(pid):
        abort(404)
    from mediahub.brand import kits as _kits, resweep as _resweep
    from mediahub.brand.kits import brand_kit_from_ref

    prof = W._active_profile()
    kit = _kits.get_kit(prof, kit_id)
    if kit is None:
        return jsonify({"error": "kit_not_found"}), 404
    brand_kit_new = brand_kit_from_ref(prof, kit)
    ws = W._get_wf_store()

    def _render_card(run_id: str, card_id: str, brief_dict: dict) -> bool:
        # Approval-first: never re-render (or de-approve) a rejected card.
        try:
            if ws is not None:
                cur = ws.load(run_id).get(card_id)
                if cur is not None and cur.status == W.CardStatus.REJECTED:
                    return False
        except Exception:
            pass
        from mediahub.content_pack_visual.integration import (
            persist_visual,
            visuals_dir_for_run,
        )
        from mediahub.creative_brief.generator import CreativeBrief
        from mediahub.graphic_renderer.render import render_brief

        brief = CreativeBrief.from_dict(brief_dict)
        if brief is None:
            return False
        out = visuals_dir_for_run(run_id) / brief.id
        result = render_brief(brief, output_dir=out, brand_kit=brand_kit_new)
        persist_visual(result.visual, run_id=run_id, brief=brief)
        # Flag the re-rendered card for human re-review — a kit change must
        # never silently alter already-approved content.
        if ws is not None:
            ws.set_status(run_id, card_id, W.CardStatus.EDITED)
        return True

    # Cap the synchronous work so one apply can't tie up a worker past the
    # gunicorn timeout: each affected card is a full Playwright render
    # (seconds each), so the per-call ceiling is small and the page's
    # apply JS walks the affected list in chunks. A re-render does NOT
    # rewrite the stored brief, so the (deterministic) affected list is
    # identical on every call — without the ``offset`` cursor each chunk
    # would redo the same first cards and the backlog would never drain.
    try:
        limit = int(request.args.get("limit", "8"))
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 10))
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    cursor = {"i": 0}

    def _render_card_from(run_id: str, card_id: str, brief_dict: dict) -> bool:
        cursor["i"] += 1
        if cursor["i"] <= offset:
            return False  # handled by an earlier chunk
        return _render_card(run_id, card_id, brief_dict)

    summary = _resweep.apply_kit_change(
        prof, kit, runs_dir=W.RUNS_DIR, render_card=_render_card_from, limit=offset + limit
    )
    d = summary.to_dict()
    # Chunk-local numbers: the first ``offset`` iterations are cursor
    # skips (earlier chunks' work), not real skips.
    d["skipped"] = (d.get("skipped") or [])[offset:]
    d["n_skipped"] = len(d["skipped"])
    d["offset"] = offset
    d["next_offset"] = offset + limit
    return jsonify(d)


def organisation_finalise():
    """Phase 1.6 Stage E — the "Looks right" finalise endpoint.

    Called by the cascade JS handler when the user clicks
    "Looks right — start creating" on /organisation/setup.
    Steps:
      1. Resolve the active profile (400 if none).
      2. Build the BrandKit from the profile.
      3. Ensure the derived palette is computed (Stage B's
         colour-science pipeline) — idempotent, no-op if already
         cached.
      4. Persist the (possibly new) palette back to the profile.
      5. Return the resolved seed hex + repair flag.

    The client doesn't actually need the response body — it
    navigates regardless. The JSON is returned for future Stage
    H ("Why does my theme look like this?") UI and for tests
    verifying persistence end-to-end.
    """
    prof = W._active_profile()
    if not prof:
        return jsonify({"error": "no active organisation"}), 400
    try:
        kit = prof.get_brand_kit()
        palette = kit.ensure_derived_palette()
    except Exception as e:
        W.log.warning("organisation_finalise: ensure_derived_palette failed: %s", e)
        # Log the exception server-side only; never echo str(e) back — it
        # can carry the absolute DATA_DIR path / errno on a disk failure.
        return jsonify({"error": "palette derivation failed"}), 500
    # Write the (possibly newly-cached) palette back to the profile
    # so subsequent requests see it. ensure_derived_palette mutated
    # kit in-place; we serialise that mutation through the profile
    # dict + save_profile.
    try:
        prof.brand_kit = kit.to_dict()
        W.save_profile(prof)
    except Exception as e:
        W.log.warning("organisation_finalise: save_profile failed: %s", e)
        # As above — keep the raw exception (and any leaked path) in the
        # server log, not in the client-visible JSON.
        return jsonify({"error": "profile save failed"}), 500
    return jsonify(
        {
            "seed_hex": (palette or {}).get("seed_hex", ""),
            "was_repaired": bool((palette or {}).get("was_repaired", False)),
        }
    )


def organisation_set_active():
    """Read or change the currently-pinned organisation. POST takes
    ``profile_id`` and pins it into the session; GET returns the
    current pin as JSON."""
    if request.method == "POST":
        pid = (request.form.get("profile_id") or "").strip()
        if not pid and request.is_json:
            body = request.get_json(silent=True) or {}
            pid = str(body.get("profile_id") or "").strip()
        if not pid or not W.load_profile(pid) or not W._session_can_use_profile(pid):
            # A bound org answers exactly like a nonexistent one to
            # non-members (anti-enumeration — ADR-0014).
            return jsonify({"ok": False, "error": "unknown_profile"}), 404
        W._pin_active_profile(pid)
        return jsonify({"ok": True, "profile_id": pid})
    pid = W._active_profile_id()
    prof = W._active_profile()
    return jsonify(
        {
            "ok": True,
            "profile_id": pid,
            "display_name": (prof.display_name if prof else ""),
            "is_ready": bool(prof and prof.is_ready()),
        }
    )


@W.require_run(deny=lambda: (jsonify({"error": "run not found"}), 404))
def api_workflow_set(run_id, card_id):
    """Set workflow status or edits for a card."""
    ws = W._get_wf_store()
    if ws is None:
        return jsonify({"error": "workflow not available"}), 503

    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "set_status")
    # Finding #116: record the signed-in member as the audit actor so the
    # durable workflow state and telemetry can tell a human's change from an
    # agent's ("api-token:<id>", stamped on the public-API path).
    _human_actor = W._auth.current_user_email() or ""

    if action == "set_status":
        status_str = payload.get("status", "queue")
        try:
            status = W.CardStatus(status_str)
        except (ValueError, NameError):
            return jsonify({"error": f"invalid status: {status_str}"}), 400
        # 1.18 role gate: changing a card's status is a sign-off action —
        # only seats with the approve capability (Owner/Member/Approver) may
        # do it. A Viewer/Reviewer/Editor is refused before any state moves.
        denied = W._role_denied_json(W._perms.CAP_APPROVE, run_id)
        if denied:
            return denied
        # F11: the content-resolving gates below key on the SHARED base id
        # (a ~n twin is the same athlete/swim/design as its first
        # occurrence, so consent, brand-lock and review-task decisions are
        # identical). Without this, a twin approved under its ~n id would
        # miss the consent gate (find_card_in_run can't resolve ~n) and
        # bypass it. For a non-duplicate card base == card_id, so behaviour
        # is byte-identical. The per-card approval STATE below (group vote,
        # ledger, stored status) stays keyed on the unique card_id.
        _content_card_id = W._base_card_id(card_id)
        # Consent gate: a card featuring an opted-out or no-consent
        # athlete can never be APPROVED (or marked POSTED). One shared
        # decision function — same rule as pack build + publish gate.
        if status in (W.CardStatus.APPROVED, W.CardStatus.POSTED):
            from mediahub.compliance.gate import (
                consent_block_reason_for_card,
                find_card_in_run,
            )

            run_data = W._load_run(run_id) or {}
            card = find_card_in_run(run_data, _content_card_id)
            reason = consent_block_reason_for_card(run_data.get("profile_id", ""), card)
            if reason:
                W.log.info("consent gate blocked approval run=%s card=%s", run_id, card_id)
                return jsonify({"error": "consent_blocked", "reason": reason}), 403
        # 1.12 brand-lock gate: a kit may lock palette/fonts/logo so a
        # volunteer can't ship off-brand. Opt-in — no locks → no effect.
        if status in (W.CardStatus.APPROVED, W.CardStatus.POSTED):
            brand_reason = W._brand_lock_block_reason(run_id, _content_card_id)
            if brand_reason:
                W.log.info("brand-lock gate blocked approval run=%s card=%s", run_id, card_id)
                return jsonify({"error": "brand_locked", "reason": brand_reason}), 403
        # 1.18 task gate: an open review task ("check lane-4 name") holds the
        # card until it's resolved. Reject/requeue stay allowed.
        if status == W.CardStatus.APPROVED:
            task_reason = W._open_tasks_block_reason(run_id, _content_card_id)
            if task_reason:
                W.log.info("task gate blocked approval run=%s card=%s", run_id, card_id)
                return jsonify({"error": "tasks_open", "reason": task_reason}), 403
        # 1.12 group-approver rule: record this vote; hold the card in QUEUE
        # until the kit's rule is met. Default-safe (no rule / pilot org /
        # operator → no effect).
        if status == W.CardStatus.APPROVED:
            held, info = W._group_approval_block(run_id, card_id)
            if held:
                return jsonify({"ok": True, "status": "queue", **info})
        # A reject or re-queue resets the approval round for this card.
        if status in (W.CardStatus.REJECTED, W.CardStatus.QUEUE):
            _led = W._get_approval_ledger()
            if _led is not None:
                _led.clear(run_id, card_id)
        notes = payload.get("notes")
        ws.set_status(run_id, card_id, status, notes=notes, actor=_human_actor)
        # Phase W: approval telemetry (W.14) + records-on-approval (W.3).
        if status in (W.CardStatus.APPROVED, W.CardStatus.REJECTED, W.CardStatus.QUEUE):
            _action = {
                W.CardStatus.APPROVED: "approved",
                W.CardStatus.REJECTED: "rejected",
                W.CardStatus.QUEUE: "requeued",
            }[status]
            W._phase_w_after_status_change(
                W._run_owner_profile_id(run_id) or W._active_profile_id() or "",
                run_id,
                card_id,
                _action,
                actor=_human_actor,
            )
        summary = ws.summary(run_id)
        return jsonify({"ok": True, "status": status_str, "summary": summary})

    if action == "set_edits":
        # 1.18 role gate: editing captions/overrides needs the edit seat.
        denied = W._role_denied_json(W._perms.CAP_EDIT, run_id)
        if denied:
            return denied
        edits = payload.get("edits", {})
        # 1.18 element locks: an inspector override of a locked element is
        # dropped, so "lock the sponsor strip" holds on this path too — not
        # just against the copilot. Maps inspector keys → lock elements.
        if isinstance(edits, dict) and edits:
            try:
                from mediahub.collab import locks as _locks

                _locked = _locks.locked_elements(run_id, card_id)
                if _locked:
                    _insp_element = {
                        "insp.hideSponsor": "sponsor",
                        "insp.noPhoto": "photo",
                        "insp.focus": "photo",
                        "insp.accent": "accent",
                    }
                    edits = {k: v for k, v in edits.items() if _insp_element.get(k) not in _locked}
            except Exception:
                pass
        ws.set_edits(run_id, card_id, edits, actor=_human_actor)
        W._phase_w_after_status_change(
            W._run_owner_profile_id(run_id) or W._active_profile_id() or "",
            run_id,
            card_id,
            "edited",
            actor=_human_actor,
        )
        # Auto-bump status to 'edited' if currently in queue, so the user
        # sees that this card has been modified. Don't overwrite approved/posted.
        try:
            cur_state = ws.load(run_id).get(card_id)
            cur_status = cur_state.status if cur_state else W.CardStatus.QUEUE
            if cur_status == W.CardStatus.QUEUE:
                ws.set_status(run_id, card_id, W.CardStatus.EDITED, actor=_human_actor)
        except Exception:
            pass
        return jsonify({"ok": True, "status": "edited"})

    return jsonify({"error": "unknown action"}), 400


def api_web_research_submit():
    """Start a background deep-research job; return a job_id to poll.

    Never runs the loop inline (it can take ~a minute and would block one
    of two gunicorn workers — the council verdict)."""
    if not W._research_console_enabled():
        return jsonify({"ok": False, "error": "research_console_disabled"}), 404
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "empty_question"}), 400
    question = question[:500]
    pid = W._active_profile_id()

    # Bound concurrent research WORK (the max_size=32 cache only bounds
    # records): each job holds a daemon thread through a 30-90s LLM +
    # network loop, so unbounded submits mean provider spend and thread
    # pile-up. Saturated callers get an honest 429 + Retry-After, the
    # same posture as _render_busy_response.
    n_running = sum(
        1 for j in W._research_jobs.values() if isinstance(j, dict) and j.get("status") == "running"
    )
    if n_running >= W._RESEARCH_MAX_INFLIGHT:
        resp = jsonify(
            {
                "ok": False,
                "error": "research_busy",
                "message": ("Research is already running — wait for it to finish, then ask again."),
            }
        )
        resp.headers["Retry-After"] = "30"
        return resp, 429

    # The worker thread runs outside the request context, so capture the real
    # app object here (current_app is only a context-local proxy).
    _app = current_app._get_current_object()

    def _do_research(job_id: str, q: str) -> None:
        try:
            with _app.app_context():
                from mediahub.web_research.deep_research import deep_research

                res = deep_research(q)
            record = {
                "status": "done",
                "profile_id": pid,
                "answer": res.answer,
                "complete": res.complete,
                "sources": res.sources,
                "authority_sources": res.authority_sources,
                "rounds": res.rounds,
                "tool_calls": res.tool_calls,
            }
        except Exception as e:
            record = {"status": "error", "profile_id": pid, "error": str(e)}
        W._research_jobs[job_id] = record
        W._job_record_write("research_jobs", job_id, record)

    import uuid as _uuid

    job_id = _uuid.uuid4().hex
    with W._active_lock:
        W._prune_job_records("research_jobs")
    running = {"status": "running", "profile_id": pid}
    W._research_jobs[job_id] = running
    W._job_record_write("research_jobs", job_id, running)
    threading.Thread(target=_do_research, args=(job_id, question), daemon=True).start()
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "status_url": url_for("api_web_research_status", job_id=job_id),
        }
    )


def api_web_research_status(job_id: str):
    """Poll a web-research job: running | done | error."""
    if not W._research_console_enabled():
        return jsonify({"ok": False, "error": "research_console_disabled"}), 404
    job = W._research_jobs.get(job_id) or W._job_record_read("research_jobs", job_id)
    if job is None:
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    # IDOR: a research job belongs to the org that created it. The job_id is
    # an unguessable uuid4, but still don't let another signed-in org read it.
    owner = job.get("profile_id")
    if owner and owner != W._active_profile_id():
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    if job.get("status") == "running":
        return jsonify({"status": "running"})
    if job.get("status") == "error":
        return jsonify({"status": "error", "error": job.get("error", "unknown")}), 500
    return jsonify(
        {
            "ok": True,
            "status": "done",
            **{k: v for k, v in job.items() if k not in ("profile_id", "status")},
        }
    )


def api_club_qa_submit():
    """Start a background club-data Q&A job; return a job_id to poll.

    The bounded tool loop can spend several LLM rounds reading runs, so
    like the research console it never runs inline on a worker."""
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "empty_question"}), 400
    question = question[:400]
    pid = W._active_profile_id()

    # The worker thread runs outside the request context, so capture the real
    # app object here (current_app is only a context-local proxy).
    _app = current_app._get_current_object()

    def _do_answer(job_id: str, q: str) -> None:
        try:
            with _app.app_context():
                from mediahub.ai_core import ProviderNotConfigured
                from mediahub.club_qa import QAEnv, answer_club_question

                try:
                    res = answer_club_question(q, QAEnv(runs_dir=W.RUNS_DIR, profile_id=pid or ""))
                    record = {
                        "status": "done",
                        "profile_id": pid,
                        "answer": res.answer,
                        "runs_consulted": res.runs_consulted,
                        "tool_calls": res.tool_calls,
                        "provider": res.provider,
                    }
                except ProviderNotConfigured:
                    record = {
                        "status": "error",
                        "profile_id": pid,
                        "error": (
                            "AI is not configured on this deployment — the "
                            "operator must set a Gemini or Anthropic API key."
                        ),
                    }
        except Exception as e:
            record = {"status": "error", "profile_id": pid, "error": str(e)}
        W._club_qa_jobs[job_id] = record
        W._job_record_write("club_qa_jobs", job_id, record)

    import uuid as _uuid

    job_id = _uuid.uuid4().hex
    with W._active_lock:
        W._prune_job_records("club_qa_jobs")
    running = {"status": "running", "profile_id": pid}
    W._club_qa_jobs[job_id] = running
    W._job_record_write("club_qa_jobs", job_id, running)
    threading.Thread(target=_do_answer, args=(job_id, question), daemon=True).start()
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "status_url": url_for("api_club_qa_status", job_id=job_id),
        }
    )


def api_club_qa_status(job_id: str):
    """Poll a club-data Q&A job: running | done | error."""
    job = W._club_qa_jobs.get(job_id) or W._job_record_read("club_qa_jobs", job_id)
    if job is None:
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    # IDOR: a Q&A job belongs to the org that asked. The job_id is an
    # unguessable uuid4, but still don't let another signed-in org read it.
    owner = job.get("profile_id")
    if owner and owner != W._active_profile_id():
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    if job.get("status") == "running":
        return jsonify({"status": "running"})
    if job.get("status") == "error":
        return jsonify({"status": "error", "error": job.get("error", "unknown")}), 500
    return jsonify(
        {
            "ok": True,
            "status": "done",
            **{k: v for k, v in job.items() if k not in ("profile_id", "status")},
        }
    )


def api_elements():
    """Browse / search the element library, recoloured to the org brand."""
    from flask import request as _req
    from mediahub.elements import catalog as _el_catalog
    from mediahub.elements import search as _el_search

    profile_id = W._active_profile_id()
    q = (_req.args.get("q") or "").strip()
    kind = (_req.args.get("kind") or "").strip() or None
    sport = (_req.args.get("sport") or "").strip() or None
    role_vars = W._elements_role_vars(profile_id)

    hits = _el_search.search(q, profile_id=profile_id, kind=kind, sport=sport, limit=60)
    payload = [W._element_to_payload(h.element, role_vars, profile_id) for h in hits]
    return jsonify(
        {
            "elements": payload,
            "semantic": _el_search.is_semantic_available(),
            "kinds": _el_catalog.list_kinds(profile_id),
        }
    )


def api_elements_gradients():
    """Brand-palette gradient presets as ready-to-use CSS for the org."""
    from mediahub.elements import gradients as _el_grad

    role_vars = W._elements_role_vars(W._active_profile_id())
    out = [
        {"id": p.id, "name": p.name, "kind": p.kind, "css": _el_grad.gradient_css(p, role_vars)}
        for p in _el_grad.list_presets()
    ]
    return jsonify({"gradients": out})


def api_stock_search():
    """Search the licence-clean stock pool (Openverse/Wikimedia; paid gated)."""
    from flask import request as _req
    from mediahub.elements import stock as _stock

    q = (_req.args.get("q") or "").strip()
    kind = (_req.args.get("kind") or "photo").strip()
    if kind not in ("photo", "video"):
        kind = "photo"
    results = _stock.search(q, kind=kind, limit=24) if q else []
    # Warm the thumbnail cache in the background (off the request threads) so
    # the per-tile proxy serves cache hits by the time the grid requests them.
    if results:
        _stock.prewarm_thumbs(
            [(r.thumb_url or ("" if r.kind == "video" else r.direct_url)) for r in results]
        )
    return jsonify(
        {
            "results": [r.to_dict() for r in results],
            "sources": _stock.available_sources(),
            "kind": kind,
        }
    )


def api_stock_thumb():
    """First-party proxy for licence-clean stock thumbnails.

    The stock results carry cross-origin thumbnail URLs (Wikimedia/Openverse,
    + flag-gated paid). The app CSP pins ``img-src 'self'``, so the browser
    blocks those <img> loads and the grid shows blank tiles. We serve the
    bytes from our own origin — host-allow-listed to the known stock CDNs,
    SSRF-checked, size-capped, image/video-only — without loosening the CSP.

    Cache-only on purpose: a hit is a fast disk read; a miss kicks off
    background warming and 404s so the request thread never blocks on a slow,
    rate-limited upstream fetch (which would starve the small gunicorn pool
    and 502 the service). The client re-requests shortly and the warmed tile
    loads; after a few tries it falls back to a "No preview" placeholder.
    """
    from flask import request as _req
    from mediahub.elements import stock as _stock

    data, ctype = _stock.serve_thumb(_req.args.get("u") or "")
    if not data:
        return ("", 404)
    return Response(
        data,
        mimetype=ctype or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def api_elements_generate():
    """AI element generation — honest seam: unavailable until 1.2 ships."""
    from flask import request as _req
    from mediahub.elements import generate as _gen

    if _req.method == "GET":
        return jsonify(_gen.status().to_dict())
    try:
        _gen.generate_element(str((_req.get_json(silent=True) or {}).get("prompt") or ""))
    except _gen.GenerativeElementsUnavailable as e:
        return jsonify({"error": "generation_unavailable", "user_message": str(e)}), 501
    return jsonify({"error": "unexpected"}), 500


def api_variant_job_status(job_id: str):
    """Progress + results for a background variant job.

    Variants stream into the payload as each render finishes, so the
    UI can show real progress ("option 2 of 3") instead of a blind
    spinner. Job ids are unguessable, but gate on the owning session
    anyway (defense-in-depth, same posture as the run routes).
    """
    job = W._variant_job_load(job_id)
    if job is None:
        return jsonify({"error": "job_not_found"}), 404
    if (job.get("owner_pid") or "") != (W._active_profile_id() or ""):
        return jsonify({"error": "job_not_found"}), 404
    status = job.get("status", "running")
    error = job.get("error") or None
    # A running job whose file hasn't been touched for a long time means
    # the worker process holding its thread was recycled (gunicorn
    # --max-requests). Report it as lost so the UI stops spinning.
    if status == "running" and (
        time.time() - float(job.get("updated_at") or 0.0) > W._VARIANT_JOB_STALL_S
    ):
        status = "error"
        error = "job_lost: the render worker restarted mid-job — try again"
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "status": status,
            "done": job.get("done", 0),
            "total": job.get("total", 3),
            "variants": list(job.get("variants") or []),
            "error": error,
        }
    )


def api_formats():
    """The P6.1 smart format catalogue as JSON, grouped by category.

    Pure static data (canvas sizes + metadata for every club design
    format). ``?sport=<slug>`` filters to the formats that sport's profile
    enables — the per-sport availability the catalogue sources from
    ``sport_profiles``; omitted returns the whole catalogue.
    """
    from mediahub.club_platform import format_catalog as _fc

    sport = (request.args.get("sport") or "").strip() or None
    specs = _fc.formats_for_sport(sport) if sport else list(_fc.all_formats())
    by_cat: dict[str, list] = {}
    for s in specs:
        by_cat.setdefault(s.category, []).append(s.to_dict())
    groups = [
        {
            "category": c,
            "label": W._FORMAT_CATEGORY_LABELS.get(c, c.replace("_", " ").title()),
            "formats": by_cat[c],
        }
        for c in _fc.categories()
        if c in by_cat
    ]
    return jsonify({"groups": groups, "n": len(specs), "sport": sport or ""})


def api_print_products():
    """The print/merch product catalogue + the deployment's print capability."""
    from mediahub.graphic_renderer.print_export import ghostscript_available
    from mediahub.print_ready import fulfilment as _ff
    from mediahub.print_ready import pdfx as _pdfx
    from mediahub.print_ready import products as _pp

    return jsonify(
        {
            "families": _pp.grouped(),
            "capabilities": {
                "cmyk": ghostscript_available(),
                "pdfx": _pdfx.pdfx_available(),
                "colour_modes": ["rgb", "cmyk", "pdfx"],
            },
            "fulfilment": _ff.status(),
        }
    )


def api_print_fulfilment():
    """Honest status of the optional, flag-gated fulfilment slot."""
    from mediahub.print_ready import fulfilment as _ff

    return jsonify(_ff.status())


def api_assistant_memory():
    """The org's assistant preference book — list (GET) or remember (POST).

    Writes are the explicit "remember this" action; the list is the
    org-visible, deletable record the spec calls for. Org-scoped to the
    active profile."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from mediahub.assistant import memory as _amem

    pid = W._active_profile_id() or ""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        item = _amem.remember(pid, (body.get("text") or ""))
        if item is None:
            return jsonify({"error": "empty", "user_message": "Nothing to remember."}), 400
        return jsonify({"ok": True, "item": item.to_dict()})
    return jsonify({"items": [i.to_dict() for i in _amem.list_items(pid)]})


def api_assistant_memory_delete(item_id: str):
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from mediahub.assistant import memory as _amem

    return jsonify({"ok": _amem.forget(W._active_profile_id() or "", item_id)})


def api_assistant_transcribe():
    """Server ASR seam for uploaded audio — honest error until a provider
    lands (the browser's on-device speech capture is the live voice path)."""
    from mediahub.assistant.asr import ASRUnavailable, transcribe

    try:
        text = transcribe(request.get_data() or b"", content_type=request.content_type or "")
        return jsonify({"ok": True, "text": text})
    except ASRUnavailable as e:
        return jsonify({"error": "asr_unavailable", "user_message": str(e)}), 503
    except ValueError:
        # A provider is configured but the upload carried no audio — a client
        # condition, not a server fault. Honest 400, not a 500 stack trace.
        return jsonify({"error": "empty", "user_message": "No audio to transcribe."}), 400


def api_reel_job_status(job_id: str):
    """Progress + outcome for a background render job (same gating as
    variants).

    The generalised status face of the disk-backed job store: the
    single-format ``reel`` job, the multi-format ``reel-batch`` job
    (R1.15), the per-card ``motion`` job (M32), the whole-pack
    ``render-all`` graphics job (M30) and the media-library ``describe``
    vision-tagging job (M34) all poll here. For a batch, ``video_urls``
    maps each produced cut to its ``reel-file`` URL and
    ``formats_failed`` carries the honest reason for any cut the active
    engine couldn't produce; ``video_url`` stays populated (the story
    cut) so single-format pollers keep working unchanged. Jobs with
    per-item progress additionally carry ``total`` / ``done`` /
    ``current`` / ``errors``.
    """
    job = W._variant_job_load(job_id)
    if job is None or job.get("kind") not in (
        "reel",
        "reel-batch",
        "motion",
        # B-5: the per-card all-formats motion batch (4 cuts, one job).
        "motion-batch",
        "render-all",
        "describe",
        # J-1: the Video Studio's async operations poll this same route.
        "video-render",
        "video-clip",
        "video-reel",
        "video-stabilize",
        # D-12: the certificates-ZIP build (one Chromium PDF per card).
        "certificates",
        # D-32: the sponsor-variant page's render + caption job.
        "sponsor-variant",
    ):
        return jsonify({"error": "job_not_found"}), 404
    if (job.get("owner_pid") or "") != (W._active_profile_id() or ""):
        return jsonify({"error": "job_not_found"}), 404
    status = job.get("status", "running")
    error = job.get("error") or None
    if status == "running" and (
        time.time() - float(job.get("updated_at") or 0.0) > W._VARIANT_JOB_STALL_S
    ):
        status = "error"
        error = "job_lost: the render worker restarted mid-job — try again"
    payload = {
        "ok": True,
        "job_id": job_id,
        "kind": job.get("kind") or "",
        "status": status,
        "video_url": job.get("video_url") or "",
        "video_urls": job.get("video_urls") or {},
        "formats_failed": job.get("formats_failed") or {},
        "error": error,
        "user_message": job.get("user_message") or "",
    }
    # Per-item progress for the batch-shaped kinds (render-all / describe).
    if job.get("total") is not None:
        payload["total"] = int(job.get("total") or 0)
        payload["done"] = int(job.get("done") or 0)
        payload["current"] = str(job.get("current") or "")
        payload["errors"] = job.get("errors") or {}
    # J-1: the Video Studio analysis/stabilise jobs hand back a project id
    # (and the stabilise job the updated project) instead of a video_url,
    # since no MP4 exists until a separate render-job runs. Single-format
    # pollers ignore these keys, so nothing else changes.
    if job.get("project_id"):
        payload["project_id"] = job.get("project_id")
    if job.get("project") is not None:
        payload["project"] = job.get("project")
    # D-12: a file-producing job (certificates ZIP) hands back the gated
    # download URL instead of a video_url; other pollers ignore the key.
    if job.get("download_url"):
        payload["download_url"] = job.get("download_url")
    # D-32: the sponsor-variant job hands back the rendered visual +
    # caption (or their plain-copy failure messages) instead of a
    # video_url. Other kinds never carry these keys, so nothing changes
    # for the existing pollers.
    if job.get("kind") == "sponsor-variant":
        payload["image_url"] = (
            url_for(
                "api_visual_png",
                vid=job.get("visual_id"),
                format_name=job.get("format_name") or "feed_portrait",
            )
            if job.get("visual_id")
            else ""
        )
        payload["image_message"] = job.get("image_message") or ""
        payload["caption"] = job.get("caption") or ""
        payload["caption_message"] = job.get("caption_message") or ""
    return jsonify(payload)


def api_export_formats():
    """The export catalogue + capability map the UI renders its options from."""
    from mediahub import export_engine as ee

    cats: dict[str, list] = {}
    for f in ee.all_formats():
        cats.setdefault(f.category, []).append(
            {
                "key": f.key,
                "label": f.label,
                "suffix": f.suffix,
                "mime": f.mime,
                "accepts": sorted(f.accepts),
            }
        )
    return jsonify(
        {
            "ok": True,
            "status": ee.engine_status(),
            "categories": cats,
            "quick_actions": ee.quick_actions.ACTIONS,
        }
    )


def api_export_job_status(job_id: str):
    """Progress + outcome for a background bulk-export job."""
    job = W._variant_job_load(job_id)
    if job is None or job.get("kind") != "bulk_export":
        return jsonify({"error": "job_not_found"}), 404
    if (job.get("owner_pid") or "") != (W._active_profile_id() or ""):
        return jsonify({"error": "job_not_found"}), 404
    status = job.get("status", "running")
    error = job.get("error") or None
    if status == "running" and (
        time.time() - float(job.get("updated_at") or 0.0) > W._VARIANT_JOB_STALL_S
    ):
        status = "error"
        error = "job_lost: the export worker restarted mid-job — try again"
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "status": status,
            "done": int(job.get("done") or 0),
            "total": int(job.get("total") or 0),
            "file_url": job.get("file_url") or "",
            "file_count": int(job.get("file_count") or 0),
            "error_count": int(job.get("error_count") or 0),
            "error": error,
        }
    )


def api_organisation_context():
    """Team Context — the org context the AI reads, surfaced to humans."""
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": True, "context": {"brand": {}, "preferences": [], "recent": []}})
    from mediahub.collab import context as _ctx

    return jsonify({"ok": True, "context": _ctx.team_context(pid)})


def api_visual_get(vid: str):
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    # #17: O(1) indexed resolve (was an O(all-runs × visuals) walk on this
    # hot <img src> route). Tenant isolation (org-access audit) is folded in
    # — a visual belongs to the run that produced it, so a foreign org must
    # not read its payload (caption, alt text, athlete names); an
    # inaccessible run is indistinguishable from a nonexistent one.
    resolved = W._resolve_visual(vid, W._active_profile_id())
    if resolved is None:
        return jsonify({"error": "not_found"}), 404
    _brief_dir, payload = resolved
    return jsonify(payload)


def api_visual_png(vid: str, format_name: str):
    if format_name not in W._VALID_FORMAT_NAMES:
        return "", 400
    if not W._v8_ok:
        return "", 503
    from flask import send_file

    # #17: O(1) indexed resolve + folded tenant gate (was an O(all-runs ×
    # visuals) walk on this hot <img src> route). The rendered PNG carries
    # the same org data as the sidecar, so a run this session can't access
    # is a 404, never served.
    resolved = W._resolve_visual(vid, W._active_profile_id())
    if resolved is None:
        return "", 404
    brief_dir, payload = resolved
    # Determine which format to serve. If vid matches a specific format-id,
    # use that format; else use the requested format_name.
    ids_map = payload.get("visual_ids") or {}
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


def api_data_hub_tables():
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    from mediahub.data_hub import store as _dh_store
    from mediahub.data_hub import tables as _dh_tables

    return jsonify(
        {
            "canonical": _dh_tables.list_canonical_tables(pid, runs_dir=W.RUNS_DIR),
            "org": _dh_store.list_org_tables(pid),
        }
    )


def api_data_hub_import():
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._phase_w_org()
    if not pid:
        return redirect(url_for("data_hub_page", err="Sign in and pick an organisation first."))
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("data_hub_page", err="No file chosen."))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in W._DH_IMPORT_EXTS:
        return redirect(url_for("data_hub_page", err="Upload a .csv or .xlsx file."))
    data = f.read(W._DH_MAX_UPLOAD + 1)
    if len(data) > W._DH_MAX_UPLOAD:
        return redirect(url_for("data_hub_page", err="That file is too large (max 12 MB)."))
    if not data:
        return redirect(url_for("data_hub_page", err="That file was empty."))
    from mediahub.data_hub import store as _dh_store
    from mediahub.data_hub.portability import import_bytes

    result = import_bytes(data, f.filename)
    if result.table is None:
        reason = result.warnings[0].message if result.warnings else "Could not read that file."
        return redirect(url_for("data_hub_page", err=reason))
    if len(result.table.rows) > W._DH_MAX_IMPORT_ROWS:
        return redirect(
            url_for(
                "data_hub_page",
                err=(
                    f"That file has {len(result.table.rows):,} rows — the import "
                    f"limit is {W._DH_MAX_IMPORT_ROWS:,}. Split it into smaller files."
                ),
            )
        )
    tid = _dh_store.create_table(pid, result.table.title, result.table.columns)
    # Batched insert: one connection + transaction (one fsync) for the whole
    # import instead of a connect/commit per row. Row count is already capped
    # to _DH_MAX_IMPORT_ROWS above.
    _dh_store.bulk_insert_rows(pid, tid, list(result.table.rows))
    return redirect(url_for("data_hub_table", table_id=tid))


def api_data_hub_derive(table_id):
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._phase_w_org()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    from mediahub.data_hub import derive as _derive
    from mediahub.data_hub import store as _dh_store

    table = _dh_store.get_org_table(pid, table_id)
    if table is None:
        return jsonify({"error": "Editable table not found."}), 404

    is_json = (request.content_type or "").lower().startswith("application/json")
    body = request.get_json(silent=True) or {} if is_json else {}
    derivation_id = (body.get("derivation_id") or request.form.get("derivation_id") or "").strip()
    output_title = (body.get("output_title") or request.form.get("output_title") or "").strip()
    deriv = _derive.get_derivation(derivation_id)
    if deriv is None:
        return jsonify({"error": f"Unknown derivation: {derivation_id}"}), 400

    if is_json and isinstance(body.get("params"), dict):
        params = body["params"]
    else:  # map the generic form fields onto the derivation's declared params
        col1 = (request.form.get("col1") or "").strip()
        col2 = (request.form.get("col2") or "").strip()
        params = {}
        specials = {
            "sep": request.form.get("sep", " "),
            "ref_year": request.form.get("ref_year", ""),
        }
        ordered = [p for p in deriv.params if p not in ("sep", "ref_year")]
        for i, p in enumerate(ordered):
            if p == "columns":
                params[p] = [c for c in (col1, col2) if c]
            else:
                params[p] = col1 if i == 0 else col2
        if "ref_year" in deriv.params and specials["ref_year"]:
            params["ref_year"] = specials["ref_year"]
        if "sep" in deriv.params:
            params["sep"] = specials["sep"]

    output_key = re.sub(r"[^a-z0-9]+", "_", output_title.lower()).strip("_") or "calc"
    # Never silently overwrite a source column: only a derived column may be
    # replaced in place (the recompute case). Anything else is data loss.
    existing_col = table.column(output_key)
    if existing_col is not None and not existing_col.derived:
        return jsonify(
            {
                "error": (
                    f'A column named "{existing_col.title}" already exists — '
                    "pick a different output title."
                )
            }
        ), 400
    try:
        _derive.apply_derivation(
            table, output_key, output_title or output_key, derivation_id, params
        )
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400
    _dh_store.set_columns(pid, table_id, table.columns)
    row_ids = _dh_store.row_ids_for(table)
    for rid, row in zip(row_ids, table.rows):
        _dh_store.set_cell(pid, table_id, rid, output_key, row[output_key])
    if is_json:
        return jsonify({"ok": True, "column": output_key})
    return redirect(url_for("data_hub_table", table_id=table_id))


def api_data_hub_suggest():
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    body = request.get_json(silent=True) or {}
    table_id = (body.get("table_id") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    table = W._dh_resolve(pid, table_id)
    if table is None:
        return jsonify({"error": "Table not found."}), 404
    from mediahub.ai_core import ProviderError, ProviderNotConfigured
    from mediahub.data_hub import derive as _derive

    try:
        suggestion = _derive.suggest_derivation(table, prompt)
    except (ProviderNotConfigured, ProviderError) as exc:
        return jsonify({"error": f"AI unavailable: {exc}"}), 503
    return jsonify({"ok": suggestion.ok, "suggestion": suggestion.to_dict()})


def api_data_hub_scaffold():
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Describe the table you want."}), 400
    from mediahub.ai_core import ProviderError, ProviderNotConfigured
    from mediahub.data_hub import scaffold as _scaffold

    try:
        res = _scaffold.scaffold_table(prompt)
    except (ProviderNotConfigured, ProviderError) as exc:
        return jsonify({"error": f"AI unavailable: {exc}"}), 503
    return jsonify({"ok": res.ok, "scaffold": res.to_dict()})


def api_data_hub_create_table():
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._phase_w_org()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "New table").strip()
    from mediahub.data_hub import store as _dh_store
    from mediahub.data_hub.models import DataColumn

    cols = []
    for c in body.get("columns", []):
        if isinstance(c, dict) and c.get("title"):
            cols.append(
                DataColumn.from_dict(c)
                if c.get("key")
                else DataColumn(
                    key=re.sub(r"[^a-z0-9]+", "_", str(c["title"]).lower()).strip("_") or "col",
                    title=str(c["title"]),
                    type=str(c.get("type", "text")),
                    editable=True,
                )
            )
    if not cols:
        return jsonify({"error": "Provide at least one column."}), 400
    tid = _dh_store.create_table(pid, title, cols)
    return jsonify({"ok": True, "table_id": tid, "url": url_for("data_hub_table", table_id=tid)})


def api_data_hub_delete(table_id):
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._phase_w_org()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    from mediahub.data_hub import store as _dh_store

    ok = _dh_store.delete_table(pid, table_id)
    if (request.content_type or "").lower().startswith("application/json"):
        return jsonify({"ok": ok})
    return redirect(url_for("data_hub_page", msg="Table deleted." if ok else "Nothing to delete."))


def api_data_hub_bulk():
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._phase_w_org()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    is_json = (request.content_type or "").lower().startswith("application/json")
    body = request.get_json(silent=True) or {} if is_json else {}
    run_id = (body.get("run_id") or request.form.get("run_id") or "").strip()
    format_slug = (
        body.get("format_slug") or request.form.get("format_slug") or "certificate"
    ).strip()
    pb_only = bool(body.get("pb_only")) if is_json else (request.form.get("pb_only") == "1")
    row_query = {"pb_only": True} if pb_only else None
    from mediahub.bulk import bulk_generate

    try:
        # Queue every matching card for review (render happens at approval/export).
        job = bulk_generate(
            pid, run_id, format_slug, row_query=row_query, runs_dir=W.RUNS_DIR, render=False
        )
    except (ValueError, PermissionError) as exc:
        if is_json:
            return jsonify({"error": str(exc)}), 400
        return redirect(url_for("data_hub_page", err=str(exc)))
    if is_json:
        return jsonify({"ok": True, "job": job.to_dict()})
    # D-20: name the human format (not the internal slug) and carry the run
    # id so the page can offer a direct link to the queued cards — otherwise
    # "Queued 24 cards" is a dead end with no path into reviewing them.
    human_format = format_slug.replace("_", " ").replace("-", " ").strip().title()
    return redirect(
        url_for(
            "data_hub_page",
            msg=f"Queued {job.n_queued} card(s) for review from {human_format}.",
            review_run=job.run_id,
        )
    )


def api_data_hub_bulk_status(job_id):
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    from mediahub.bulk import load_job

    job = load_job(pid, job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job.to_dict())


def api_athletes_consent():
    """B-7: inline single + bulk permission saves from the roster.

    JSON body: ``{"athlete_ids": [...], "level": "<level>"}`` (a single
    ``"athlete_id"`` is accepted too). Tenant-gated exactly like the
    /athletes/action form post — active workspace only — and any id that
    isn't on THIS organisation's roster 404s the whole request, so one
    club can never write consent rows against another club's athletes.
    The form post stays as the no-JS fallback.
    """
    pid = W._phase_w_org()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    from mediahub.athletes import list_athletes
    from mediahub.safeguarding import set_consent, set_consent_many
    from mediahub.safeguarding.consent import LEVEL_LABELS as _CONSENT_LABELS
    from mediahub.safeguarding.consent import LEVELS as _CONSENT_LEVELS

    body = request.get_json(silent=True) or {}
    ids = body.get("athlete_ids")
    if ids is None:
        single = str(body.get("athlete_id") or "").strip()
        ids = [single] if single else []
    if not isinstance(ids, list):
        return jsonify({"error": "athlete_ids must be a list."}), 400
    ids = list(dict.fromkeys(str(a).strip() for a in ids if str(a).strip()))
    if not ids:
        return jsonify({"error": "Pick at least one athlete."}), 400
    level = str(body.get("level") or "").strip()
    if level not in _CONSENT_LEVELS:
        return jsonify({"error": "Pick a permission level first."}), 400
    roster_ids = {r.athlete_id for r in list_athletes(pid)}
    if any(a not in roster_ids for a in ids):
        return jsonify({"error": "No such athlete on this organisation's roster."}), 404
    actor = (session.get("user_email") or "web").strip()
    # CON2-4 — a bulk save is all-or-nothing: one transaction, so a
    # failure mid-way writes nothing rather than half the roster. The
    # single save keeps set_consent (same row shape, same audit).
    if len(ids) == 1:
        updated = 1 if set_consent(pid, ids[0], level, actor=actor) else 0
    else:
        try:
            updated = set_consent_many(pid, ids, level, actor=actor)
        except sqlite3.Error:
            W.log.warning("bulk consent save failed; rolled back", exc_info=True)
            return (
                jsonify(
                    {
                        "error": "Could not save those permissions — "
                        "nothing was changed. Try again."
                    }
                ),
                500,
            )
    return jsonify(
        {
            "ok": True,
            "updated": updated,
            "level": level,
            "label": _CONSENT_LABELS.get(level, level),
        }
    )


def api_event_preview_parse_entries():
    """Turn an uploaded entry file into prefilled preview-form fields.

    LENEX entries parse natively; CSV/TSV/plain text pass through with
    light normalisation; anything unreadable returns an honest error.
    Zero typing is the goal (W.6)."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400
    data = f.read()
    name = (f.filename or "").lower()
    meet_name = ""
    entries_text = ""
    n_rows = 0
    try:
        if name.endswith((".lef", ".lxf")) or b"<LENEX" in data[:2048].upper():
            from mediahub.interpreter.lenex_parser import (
                parse_lenex,
                parse_lenex_entries,
            )

            rows = parse_lenex_entries(data)
            try:
                meet_name = parse_lenex(data).meet_name or ""
            except Exception:
                meet_name = ""
            lines = []
            for r in rows:
                bits = [
                    r.get("swimmer_name") or "",
                    f"{r.get('distance_m') or ''}{(' ' + r['stroke']) if r.get('stroke') else ''}".strip(),
                    r.get("entry_time") or "",
                ]
                lines.append(" — ".join(b for b in bits if b))
            entries_text = "\n".join(lines)
            n_rows = len(rows)
        else:
            # Bound the intermediate work: decode at most ~2 MB (well beyond
            # any real entries list) so a large text upload — allowed up to
            # the 50 MB request cap — can't build a giant line list in RAM.
            text = data[:2_000_000].decode("utf-8", errors="replace")
            cleaned = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not cleaned:
                return jsonify(
                    {"ok": False, "error": "Couldn't read any entries from that file."}
                ), 422
            n_rows = len(cleaned)
            entries_text = "\n".join(cleaned[:400])[:20000]
    except Exception:
        W.log.warning("entry-file parse failed", exc_info=True)
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Couldn't read that entry file. Try the LENEX (.lef/.lxf) "
                    "export from the meet organiser, or paste the entries as text."
                ),
            }
        ), 422
    return jsonify(
        {"ok": True, "meet_name": meet_name, "entries_text": entries_text, "rows": n_rows}
    )


def api_documents_generate():
    if not W._documents_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    body = request.get_json(silent=True) or {}
    fmt = (body.get("format") or "").strip()
    scope = (body.get("scope") or "season").strip()
    run_id = (body.get("run_id") or "").strip()
    with_ai = bool(body.get("with_ai", True))
    tone = (body.get("tone") or "editorial").strip()
    from mediahub.documents import store as _docstore
    from mediahub.documents.draft import generate_document
    from mediahub.documents.models import new_document

    if fmt == "blank":
        spec = new_document("Untitled document", "blank", brand_profile_id=pid)
        _docstore.save_document(pid, spec)
        return jsonify(
            {
                "ok": True,
                "doc_id": spec.doc_id,
                "url": url_for("document_view", doc_id=spec.doc_id),
            }
        )

    if fmt not in ("meet_programme", "season_report", "sponsor_proposal", "agm_deck"):
        return jsonify({"ok": False, "error": "bad_format"}), 400
    if fmt == "meet_programme":
        scope = "meet"
        if not run_id:
            return jsonify({"ok": False, "error": "pick_a_meet"}), 400
    if with_ai:  # AI drafting is metered spend — permission + quota first
        denied = W._editorial_ai_gate(pid)
        if denied is not None:
            return denied

    brand_kit = W._doc_brand_kit(pid)
    facts = W._doc_facts_for(pid, brand_kit, scope=scope, run_id=run_id)
    if facts is None:
        return jsonify(
            {
                "ok": False,
                "error": "no_data",
                "message": "No processed meets to build from yet.",
            }
        ), 200
    try:
        spec = generate_document(facts, fmt, brand_profile_id=pid, tone=tone, with_ai=with_ai)
    except Exception as e:  # honest AI-unavailable signal — offer a data-only build
        from mediahub.media_ai.llm import ClaudeUnavailableError

        if isinstance(e, ClaudeUnavailableError):
            return jsonify({"ok": False, "error": "no_ai", "message": str(e)}), 200
        W.log.warning("document generation failed", exc_info=True)
        return jsonify({"ok": False, "error": "generate_failed"}), 500
    if with_ai:
        W._editorial_ai_record(pid, detail=f"document={fmt}")
    _docstore.save_document(pid, spec)
    return jsonify(
        {"ok": True, "doc_id": spec.doc_id, "url": url_for("document_view", doc_id=spec.doc_id)}
    )


def api_document_pdf(doc_id: str):
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return jsonify({"error": "not_found"}), 404
    from mediahub.documents.render import render_document_pdf

    try:
        path = render_document_pdf(spec, brand_kit=W._doc_brand_kit(pid))
    except Exception as e:
        W.log.warning("document pdf render failed", exc_info=True)
        return jsonify({"error": "render_failed", "detail": W._doc_clean_detail(e)}), 503
    dl = request.args.get("dl") == "1"
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=dl,
        download_name=W._safe_filename(spec.title, "pdf"),
    )


def api_document_pptx(doc_id: str):
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return jsonify({"error": "not_found"}), 404
    from mediahub.documents.export import document_pptx

    # Per-request unique name (concurrent exports of the same doc must not
    # race) + unlink after send_file (which opens the file at call time,
    # so the streamed response survives the POSIX unlink).
    out = Path(tempfile.gettempdir()) / f"doc_{secrets.token_hex(8)}.pptx"
    try:
        try:
            document_pptx(spec, out, brand_kit=W._doc_brand_kit(pid))
        except Exception as e:
            return jsonify({"error": "export_failed", "detail": W._doc_clean_detail(e)}), 503
        return send_file(
            out,
            as_attachment=True,
            download_name=W._safe_filename(spec.title, "pptx"),
            mimetype=("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        )
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def api_document_docx(doc_id: str):
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return jsonify({"error": "not_found"}), 404
    from mediahub.documents.export import document_docx

    out = Path(tempfile.gettempdir()) / f"doc_{secrets.token_hex(8)}.docx"
    try:
        try:
            document_docx(spec, out, brand_kit=W._doc_brand_kit(pid))
        except Exception as e:
            return jsonify({"error": "export_failed", "detail": W._doc_clean_detail(e)}), 503
        return send_file(
            out,
            as_attachment=True,
            download_name=W._safe_filename(spec.title, "docx"),
            mimetype=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def api_document_video(doc_id: str):
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return jsonify({"error": "not_found"}), 404
    if not spec.is_deck:
        return jsonify({"error": "not_a_deck"}), 400
    from mediahub.documents.deck_video import deck_to_mp4

    try:
        path = deck_to_mp4(spec, brand_kit=W._doc_brand_kit(pid))
    except Exception as e:
        return jsonify({"error": "video_failed", "detail": W._doc_clean_detail(e)}), 503
    return send_file(
        path,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=W._safe_filename(spec.title, "mp4"),
    )


def api_document_save(doc_id: str):
    if not W._documents_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    body = request.get_json(silent=True) or {}
    raw = body.get("spec")
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "bad_spec"}), 400
    from mediahub.documents.models import DocumentSpec
    from mediahub.documents import store as _docstore

    raw["doc_id"] = doc_id  # never let an edit reassign identity
    # from_dict is total over wrong-typed fields, but a spec the editor sends
    # can still be unparseable in other ways — answer with a clean 400, never
    # an unhandled 500, since this is a user-editable payload.
    try:
        new_spec = DocumentSpec.from_dict(raw)
        _docstore.save_document(pid, new_spec)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_spec"}), 400
    return jsonify({"ok": True})


def api_document_content_edit(doc_id: str):
    """H-5: apply the structured content editor's form onto the document.

    Reads request.form; load → to_dict → apply whitelisted edits by id →
    from_dict → save. Identity id and every non-whitelisted field (tables,
    charts, images, layout of untouched sections) survive verbatim.
    """
    if not W._documents_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        abort(404)
    from mediahub.documents import store as _docstore
    from mediahub.documents.models import DocumentSpec
    from mediahub.web import spec_editor as _se

    data = spec.to_dict()
    _se.apply_structured(data, request.form, "document")
    data["doc_id"] = doc_id
    _docstore.save_document(pid, DocumentSpec.from_dict(data))
    return redirect(url_for("document_view", doc_id=doc_id))


def api_document_delete(doc_id: str):
    if not W._documents_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    from mediahub.documents import store as _docstore

    return jsonify({"ok": _docstore.delete_document(pid, doc_id)})


def api_documents_import():
    if not W._documents_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"ok": False, "error": "no_file"}), 400
    ext = Path(f.filename).suffix.lower().lstrip(".")
    if ext not in ("pdf", "docx", "pptx"):
        return jsonify({"ok": False, "error": "bad_type"}), 400
    tmp = Path(tempfile.gettempdir()) / f"imp_{secrets.token_hex(6)}.{ext}"
    f.save(str(tmp))
    from mediahub.documents.import_doc import import_file
    from mediahub.documents import store as _docstore

    try:
        spec = import_file(tmp)
    except Exception as e:
        return jsonify(
            {"ok": False, "error": "import_failed", "detail": W._doc_clean_detail(e)}
        ), 422
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    from dataclasses import replace as _dc_replace

    spec = _dc_replace(spec, brand_profile_id=pid)
    _docstore.save_document(pid, spec)
    return jsonify(
        {"ok": True, "doc_id": spec.doc_id, "url": url_for("document_view", doc_id=spec.doc_id)}
    )


def api_documents_tool_merge():
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    if not W._active_profile_id():
        return jsonify({"error": "not_signed_in"}), 403
    files = request.files.getlist("files")
    pdfs = [f for f in files if f and (f.filename or "").lower().endswith(".pdf")]
    if len(pdfs) < 2:
        return jsonify({"error": "need_two_pdfs"}), 400

    from mediahub.documents.pdf_utils import merge_pdfs

    paths = []
    for f in pdfs:
        p = Path(tempfile.gettempdir()) / f"mrg_{secrets.token_hex(5)}.pdf"
        f.save(str(p))
        paths.append(p)
    out = Path(tempfile.gettempdir()) / f"merged_{secrets.token_hex(5)}.pdf"
    try:
        try:
            merge_pdfs(paths, out)
        except Exception as e:
            return jsonify({"error": "merge_failed", "detail": W._doc_clean_detail(e)}), 422
        finally:
            for p in paths:
                try:
                    p.unlink()
                except OSError:
                    pass
        return send_file(
            out, mimetype="application/pdf", as_attachment=True, download_name="merged.pdf"
        )
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def api_documents_tool_images_to_pdf():
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    if not W._active_profile_id():
        return jsonify({"error": "not_signed_in"}), 403
    files = request.files.getlist("files")
    imgs = [f for f in files if f and f.filename]
    if not imgs:
        return jsonify({"error": "no_images"}), 400
    from mediahub.documents.pdf_utils import images_to_pdf

    paths = []
    for f in imgs:
        p = Path(tempfile.gettempdir()) / f"img_{secrets.token_hex(5)}{Path(f.filename).suffix}"
        f.save(str(p))
        paths.append(p)
    out = Path(tempfile.gettempdir()) / f"images_{secrets.token_hex(5)}.pdf"
    try:
        try:
            images_to_pdf(paths, out)
        except Exception as e:
            return jsonify({"error": "convert_failed", "detail": W._doc_clean_detail(e)}), 422
        finally:
            for p in paths:
                try:
                    p.unlink()
                except OSError:
                    pass
        return send_file(
            out, mimetype="application/pdf", as_attachment=True, download_name="images.pdf"
        )
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def api_present_slide(session_id: str, i: int):
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    from mediahub.documents import presenter as _pres
    from mediahub.documents import store as _docstore
    from mediahub.documents.render import render_section_png

    session = _pres.get_session(session_id)
    if session is None:
        return jsonify({"error": "no_session"}), 404
    spec = _docstore.load_document(session.owner, session.doc_id)
    if spec is None:
        return jsonify({"error": "no_doc"}), 404
    try:
        path = render_section_png(spec, i, brand_kit=W._doc_brand_kit(session.owner))
    except Exception as e:
        return jsonify({"error": "render_failed", "detail": W._doc_clean_detail(e)}), 503
    return send_file(path, mimetype="image/png")


def api_present_state(session_id: str):
    if not W._documents_ok:
        return jsonify({"error": "unavailable"}), 503
    from mediahub.documents import presenter as _pres

    session = _pres.get_session(session_id)
    if session is None:
        return jsonify({"ended": True, "error": "no_session"}), 404
    return jsonify(session.public_state())


def api_present_action(session_id: str):
    if not W._documents_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    from mediahub.documents import presenter as _pres

    session = _pres.get_session(session_id)
    if session is None:
        return jsonify({"ok": False, "error": "no_session"}), 404
    # owner-gated: only the signed-in presenter who created it may drive here
    if session.owner != (W._active_profile_id() or ""):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    updated = _pres.apply_action(session_id, str(body.get("action", "")), body.get("value"))
    return jsonify({"ok": True, "state": updated.public_state() if updated else None})


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule(
        "/api/upload/from-url/<job_id>/status",
        endpoint="upload_from_url_status",
        view_func=upload_from_url_status,
    )
    app.add_url_rule("/api/status", endpoint="api_status_json", view_func=api_status_json)
    app.add_url_rule(
        "/api/notifications",
        endpoint="api_notifications",
        view_func=api_notifications,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/notifications/<notif_id>/read",
        endpoint="api_notifications_read",
        view_func=api_notifications_read,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/notifications/read-all",
        endpoint="api_notifications_read_all",
        view_func=api_notifications_read_all,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/audio/library", endpoint="api_audio_library", view_func=api_audio_library
    )
    app.add_url_rule(
        "/api/audio/track/<track_id>", endpoint="api_audio_track", view_func=api_audio_track
    )
    app.add_url_rule("/api/audio/voices", endpoint="api_audio_voices", view_func=api_audio_voices)
    app.add_url_rule(
        "/api/audio/lexicon",
        endpoint="api_audio_lexicon",
        view_func=api_audio_lexicon,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/audio/upload",
        endpoint="api_audio_upload",
        view_func=api_audio_upload,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/audio/upload/<asset_id>",
        endpoint="api_audio_upload_file",
        view_func=api_audio_upload_file,
    )
    app.add_url_rule(
        "/api/audio/upload/<asset_id>/delete",
        endpoint="api_audio_upload_delete",
        view_func=api_audio_upload_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/audio/voice-consent",
        endpoint="api_audio_voice_consent",
        view_func=api_audio_voice_consent,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/audio/suggest", endpoint="api_audio_suggest", view_func=api_audio_suggest
    )
    app.add_url_rule(
        "/api/settings/llm-status", endpoint="api_llm_status", view_func=api_llm_status
    )
    app.add_url_rule(
        "/api/channel-preview",
        endpoint="api_channel_preview",
        view_func=api_channel_preview,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/studio/render",
        endpoint="api_studio_render",
        view_func=api_studio_render,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brand/kits",
        endpoint="api_brand_kit_create",
        view_func=api_brand_kit_create,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brand/kits/<kit_id>",
        endpoint="api_brand_kit_update",
        view_func=api_brand_kit_update,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brand/kits/<kit_id>/delete",
        endpoint="api_brand_kit_delete",
        view_func=api_brand_kit_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brand/kits/<kit_id>/default",
        endpoint="api_brand_kit_set_default",
        view_func=api_brand_kit_set_default,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brand/kits/<kit_id>/palette/import",
        endpoint="api_brand_kit_palette_import",
        view_func=api_brand_kit_palette_import,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brand/kits/<kit_id>/resweep/preview",
        endpoint="api_brand_kit_resweep_preview",
        view_func=api_brand_kit_resweep_preview,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/brand/kits/<kit_id>/resweep/apply",
        endpoint="api_brand_kit_resweep_apply",
        view_func=api_brand_kit_resweep_apply,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/organisation/finalise",
        endpoint="organisation_finalise",
        view_func=organisation_finalise,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/organisation/active",
        endpoint="organisation_set_active",
        view_func=organisation_set_active,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/workflow/<run_id>/<card_id>",
        endpoint="api_workflow_set",
        view_func=api_workflow_set,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/web-research",
        endpoint="api_web_research_submit",
        view_func=api_web_research_submit,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/web-research/<job_id>",
        endpoint="api_web_research_status",
        view_func=api_web_research_status,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/club-qa",
        endpoint="api_club_qa_submit",
        view_func=api_club_qa_submit,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/club-qa/<job_id>",
        endpoint="api_club_qa_status",
        view_func=api_club_qa_status,
        methods=["GET"],
    )
    app.add_url_rule("/api/elements", endpoint="api_elements", view_func=api_elements)
    app.add_url_rule(
        "/api/elements/gradients",
        endpoint="api_elements_gradients",
        view_func=api_elements_gradients,
    )
    app.add_url_rule("/api/stock/search", endpoint="api_stock_search", view_func=api_stock_search)
    app.add_url_rule("/api/stock/thumb", endpoint="api_stock_thumb", view_func=api_stock_thumb)
    app.add_url_rule(
        "/api/elements/generate",
        endpoint="api_elements_generate",
        view_func=api_elements_generate,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/variant-jobs/<job_id>",
        endpoint="api_variant_job_status",
        view_func=api_variant_job_status,
        methods=["GET"],
    )
    app.add_url_rule("/api/formats", endpoint="api_formats", view_func=api_formats)
    app.add_url_rule(
        "/api/print/products", endpoint="api_print_products", view_func=api_print_products
    )
    app.add_url_rule(
        "/api/print/fulfilment", endpoint="api_print_fulfilment", view_func=api_print_fulfilment
    )
    app.add_url_rule(
        "/api/assistant/memory",
        endpoint="api_assistant_memory",
        view_func=api_assistant_memory,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/assistant/memory/<item_id>/delete",
        endpoint="api_assistant_memory_delete",
        view_func=api_assistant_memory_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/assistant/transcribe",
        endpoint="api_assistant_transcribe",
        view_func=api_assistant_transcribe,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/reel-jobs/<job_id>",
        endpoint="api_reel_job_status",
        view_func=api_reel_job_status,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/export/formats", endpoint="api_export_formats", view_func=api_export_formats
    )
    app.add_url_rule(
        "/api/export-jobs/<job_id>",
        endpoint="api_export_job_status",
        view_func=api_export_job_status,
    )
    app.add_url_rule(
        "/api/organisation/context",
        endpoint="api_organisation_context",
        view_func=api_organisation_context,
        methods=["GET"],
    )
    app.add_url_rule("/api/visual/<vid>", endpoint="api_visual_get", view_func=api_visual_get)
    app.add_url_rule(
        "/api/visual/<vid>/png/<format_name>", endpoint="api_visual_png", view_func=api_visual_png
    )
    app.add_url_rule(
        "/api/data-hub/tables", endpoint="api_data_hub_tables", view_func=api_data_hub_tables
    )
    app.add_url_rule(
        "/api/data-hub/import",
        endpoint="api_data_hub_import",
        view_func=api_data_hub_import,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/table/<table_id>/derive",
        endpoint="api_data_hub_derive",
        view_func=api_data_hub_derive,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/suggest-derivation",
        endpoint="api_data_hub_suggest",
        view_func=api_data_hub_suggest,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/scaffold",
        endpoint="api_data_hub_scaffold",
        view_func=api_data_hub_scaffold,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/create-table",
        endpoint="api_data_hub_create_table",
        view_func=api_data_hub_create_table,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/table/<table_id>/delete",
        endpoint="api_data_hub_delete",
        view_func=api_data_hub_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/bulk",
        endpoint="api_data_hub_bulk",
        view_func=api_data_hub_bulk,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/data-hub/bulk/<job_id>",
        endpoint="api_data_hub_bulk_status",
        view_func=api_data_hub_bulk_status,
    )
    app.add_url_rule(
        "/api/athletes/consent",
        endpoint="api_athletes_consent",
        view_func=api_athletes_consent,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/event-preview/parse-entries",
        endpoint="api_event_preview_parse_entries",
        view_func=api_event_preview_parse_entries,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/generate",
        endpoint="api_documents_generate",
        view_func=api_documents_generate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/pdf", endpoint="api_document_pdf", view_func=api_document_pdf
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/pptx", endpoint="api_document_pptx", view_func=api_document_pptx
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/docx", endpoint="api_document_docx", view_func=api_document_docx
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/video", endpoint="api_document_video", view_func=api_document_video
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/save",
        endpoint="api_document_save",
        view_func=api_document_save,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/content-edit",
        endpoint="api_document_content_edit",
        view_func=api_document_content_edit,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/<doc_id>/delete",
        endpoint="api_document_delete",
        view_func=api_document_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/import",
        endpoint="api_documents_import",
        view_func=api_documents_import,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/tools/merge",
        endpoint="api_documents_tool_merge",
        view_func=api_documents_tool_merge,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/documents/tools/images-to-pdf",
        endpoint="api_documents_tool_images_to_pdf",
        view_func=api_documents_tool_images_to_pdf,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/present/<session_id>/slide/<int:i>.png",
        endpoint="api_present_slide",
        view_func=api_present_slide,
    )
    app.add_url_rule(
        "/api/present/<session_id>/state", endpoint="api_present_state", view_func=api_present_state
    )
    app.add_url_rule(
        "/api/present/<session_id>/action",
        endpoint="api_present_action",
        view_func=api_present_action,
        methods=["POST"],
    )
