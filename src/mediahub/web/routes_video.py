"""Video projects & footage: upload, consent, moments, renders.

Carved out of ``web.create_app`` (deep-review finding #15, stage 4).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
the captured ``app`` became ``current_app``. Endpoint names are
PRESERVED — url_for targets, ``request.endpoint`` keying and the
org/terms gate exemption sets depend on them — which is why this is
an ``add_url_rule`` module, not a name-prefixing Blueprint (see
docs/REFACTOR_WEB_BLUEPRINTS.md).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from flask import (
    jsonify,
    request,
    send_file,
    url_for,
)

from mediahub.web import web as W


def video_studio_page():
    """Video Studio — upload/record footage, run Clip-Maker, review + export."""
    if not W._v8_ok:
        return W._recovery_page(
            "Video studio unavailable",
            "The video suite stores footage in the media library, which isn't "
            "enabled on this deployment. Ask your operator to turn on the V8 "
            "media engine.",
            eyebrow="Video",
            primary_cta=("Back to Create", url_for("make_page")),
            secondary_cta=("System status", url_for("status_page")),
            code=503,
        )
    prof = W._active_profile()
    if not prof:
        profs = W.list_profiles()
        if not profs:
            return W._layout(
                "Video studio",
                '<section class="mh-hero"><span class="mh-hero-eyebrow">Video</span>'
                '<h1>No organisation,<br><em class="editorial">no studio.</em></h1>'
                '<p class="lede">The video studio is scoped per organisation. '
                "Set one up, then come back to turn race footage into reels.</p>"
                f'<div class="mh-hero-actions"><a class="mh-cta-primary" '
                f'href="{url_for("organisation_setup")}">Set up organisation &rarr;</a></div>'
                "</section>",
                active="video",
            )
    from mediahub.video.render import available as _video_render_available

    engine_ready = _video_render_available()
    engine_note = (
        ""
        if engine_ready
        else '<p class="muted" style="margin-top:6px">&#x26A0; The render engine '
        "(FFmpeg) isn't available on this deployment yet, so clips can be "
        "planned but not yet rendered. Captions also need server speech-to-text "
        "(<code>MEDIAHUB_ASR_PROVIDER</code>).</p>"
    )
    from mediahub.video.enhance import describe_look, look_names

    look_options = "".join(
        f'<option value="{W._h(n)}">{W._h(describe_look(n))}</option>' for n in look_names()
    )
    # G-7: the OTHER reel — the Meet reel built from result cards on the
    # pack page — gets a cross-link here so the two features stop being
    # two unrelated things both called "reel". Link the latest processed
    # meet's pack when there is one, else Activity.
    _meet_reel_href = url_for("activity_page")
    try:
        conn = W._db()
        try:
            _mr_row = conn.execute(
                "SELECT id FROM runs WHERE profile_id = ? AND status='done' "
                "ORDER BY created_at DESC LIMIT 1",
                (prof.profile_id,),
            ).fetchone()
        finally:
            conn.close()
        if _mr_row:
            _meet_reel_href = url_for("content_pack", run_id=_mr_row["id"])
    except Exception as e:  # noqa: BLE001 - hint only, never block the studio
        W.log.warning("video studio: meet-reel hint lookup failed: %s", e)
    meet_reel_hint = (
        '<p class="muted" style="margin-top:6px">Want a highlights reel from '
        "your result cards instead? "
        f'<a href="{W._h(_meet_reel_href)}">Build a Meet reel &rarr;</a></p>'
    )
    body = (
        W._VIDEO_STUDIO_HTML.replace("__CSRF__", W._h(W._csrf_token()))
        .replace("__FOOTAGE_URL__", url_for("api_video_footage_upload"))
        .replace("__FOOTAGE_LIST_URL__", url_for("api_video_footage_list"))
        .replace(
            "__FOOTAGE_PERM_TMPL__",
            url_for("api_video_footage_permission", asset_id="__AID__"),
        )
        .replace(
            "__FOOTAGE_FRAME_TMPL__",
            url_for("api_video_footage_best_frame", asset_id="__AID__"),
        )
        .replace("__CLIPMAKER_URL__", url_for("api_video_clip_maker"))
        .replace("__REEL_URL__", url_for("api_video_reel"))
        .replace("__PROJECTS_URL__", url_for("api_video_projects_list"))
        .replace(
            "__PROJECT_RENDER_TMPL__", url_for("api_video_project_render", project_id="__PID__")
        )
        .replace(
            "__PROJECT_APPROVE_TMPL__",
            url_for("api_video_project_approve", project_id="__PID__"),
        )
        .replace(
            "__PROJECT_ENHANCE_TMPL__",
            url_for("api_video_project_enhance", project_id="__PID__"),
        )
        .replace(
            "__PROJECT_STABILIZE_JOB_TMPL__",
            url_for("api_video_project_stabilize_job", project_id="__PID__"),
        )
        .replace("__PROJECT_TMPL__", url_for("api_video_project", project_id="__PID__"))
        .replace(
            "__PROJECT_WAVEFORM_TMPL__",
            url_for("api_video_project", project_id="__PID__") + "/clip/__CIDX__/waveform",
        )
        .replace("__PROJECT_FILE_TMPL__", url_for("api_video_project_file", project_id="__PID__"))
        # The two <select> tags take the raw HTML; the JS var must be a valid
        # JS string literal — JSON-encode it so the double-quoted option attrs
        # don't terminate the string (otherwise the whole studio IIFE fails to
        # parse). Replace the JS placeholder first (it is the more specific key).
        .replace("__LOOK_OPTIONS_JS__", json.dumps(look_options))
        .replace("__LOOK_OPTIONS__", look_options)
        .replace("__VIDEO_MAX_MB__", str(W._video_upload_max // (1024 * 1024)))
        .replace("__ENGINE_NOTE__", engine_note)
        .replace("__MEET_REEL_HINT__", meet_reel_hint)
    )
    return W._layout("Video studio", body, active="video")


def api_video_footage_upload():
    """Ingest an uploaded/recorded clip as a `footage` media asset.

    Footage gets a raised per-request body cap (``MEDIAHUB_VIDEO_UPLOAD_MB``,
    default 512 MB) — the app-wide 50 MB limit is for meet exports/images and
    is far too small for real video. The larger cap is applied in the CSRF
    ``before_request`` guard before the multipart body is parsed. The clip is
    streamed straight to disk (never read whole into memory), so the cap bounds
    disk per upload, not RAM.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no_file"}), 400
    profile_id = W._active_profile_id()
    if not profile_id:
        return jsonify({"error": "no_active_profile"}), 400
    from mediahub.video.ingest import ingest_footage_stream, is_video_filename

    filename = f.filename or "clip.webm"
    if not is_video_filename(filename):
        return jsonify(
            {"error": "not_video", "message": "Only video files can be uploaded as footage."}
        ), 415
    # Stream the upload straight to disk (Werkzeug already spooled the part to a
    # temp file, so this is a bounded disk→disk copy) instead of reading the whole
    # clip into memory — peak RAM stays at the copy buffer regardless of clip size.
    try:
        asset = ingest_footage_stream(
            f.stream, filename, profile_id=profile_id, uploaded_by=W._active_profile_id()
        )
    except ValueError as e:
        return jsonify({"error": "bad_footage", "message": str(e)}), 400
    except OSError:
        # The clip couldn't be written to storage (disk full, or a
        # misconfigured/unwritable data path). Surface an honest, specific
        # message — never the generic "internal_error" — and keep the real
        # cause in the server log for the operator.
        W.log.exception("footage upload could not be stored")
        return jsonify(
            {
                "error": "storage_failed",
                "message": (
                    "The clip couldn't be saved on the server — its storage is "
                    "full or unavailable. Please try again; if it keeps "
                    "happening, the deployment status page has the latest "
                    "health signal."
                ),
            }
        ), 500
    except Exception:
        # Any other unexpected failure: don't let it fall through to the
        # generic 500 handler ("internal_error"). Log the traceback and tell
        # the volunteer something they can act on.
        W.log.exception("footage upload failed")
        return jsonify(
            {
                "error": "footage_failed",
                "message": (
                    "The clip couldn't be processed. Please try again, or try a different clip."
                ),
            }
        ), 500
    return jsonify({"ok": True, "asset": W._video_footage_summary(asset)})


def api_video_footage_permission(asset_id: str):
    """One-tap permission editor for a footage tile (M26).

    Sets the clip's ``permission_status`` using the existing media-library
    permission vocabulary — the same statuses the consent gate enforces —
    so a volunteer can record consent (or a do-not-use hold) without
    leaving the studio.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if not asset or asset.type != "footage":
        return jsonify({"error": "footage_not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"error": "forbidden"}), 403
    from mediahub.media_library.models import PERMISSION_STATUSES

    payload = request.get_json(silent=True) or {}
    status = str(payload.get("permission_status") or "").strip()
    if status not in PERMISSION_STATUSES:
        return jsonify(
            {
                "error": "bad_permission",
                "message": f"permission_status must be one of: "
                f"{', '.join(PERMISSION_STATUSES)}",
            }
        ), 400
    asset = store.update_fields(asset_id, {"permission_status": status})
    return jsonify({"ok": True, "asset": W._video_footage_summary(asset)})


def api_video_footage_best_frame(asset_id: str):
    """Extract the clip's best frame as a linked photo asset (M25).

    Deterministic: the top detected moment's centre frame, saved as an
    ``athlete_action`` MediaAsset with the clip's links AND permission
    inherited (never wider). One click on a Video Studio footage tile;
    the same extraction runs automatically on card-linked clip uploads.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if not asset or asset.type != "footage":
        return jsonify({"error": "footage_not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"error": "forbidden"}), 403
    from mediahub.video.best_frame import BestFrameUnavailable, extract_best_frame

    try:
        frame = extract_best_frame(asset, store=store)
    except BestFrameUnavailable as e:
        return jsonify({"error": "best_frame_unavailable", "message": str(e)}), 503
    except Exception as e:
        W.log.warning("best-frame extraction failed for %s: %s", asset_id, e)
        return jsonify({"error": "best_frame_failed", "message": str(e)[:200]}), 500
    return jsonify(
        {
            "ok": True,
            "asset": {
                "id": frame.id,
                "url": url_for("api_media_library_file", asset_id=frame.id),
                "label": frame.description_raw,
                "permission_status": frame.permission_status,
            },
        }
    )


def api_video_footage_list():
    """List the active profile's footage clips (JSON)."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"footage": []})
    store = W._v8_get_media_store()
    try:
        assets = store.list(profile_id=pid, asset_type="footage", limit=200)
    except Exception as e:
        W.log.warning("video footage list failed: %s", e)
        return jsonify({"footage": [], "error": "list_failed"})
    return jsonify({"footage": [W._video_footage_summary(a) for a in assets]})


def api_video_clip_maker():
    """Run Clip-Maker on a footage asset and save the result as a project."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    payload = request.get_json(silent=True) or {}
    asset_id = (payload.get("asset_id") or "").strip()
    if not asset_id:
        return jsonify({"error": "asset_id_required"}), 400
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if not asset or asset.type != "footage":
        return jsonify({"error": "footage_not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"error": "forbidden"}), 403
    if not Path(asset.path).exists():
        return jsonify({"error": "footage_missing_on_disk"}), 410
    # M26 — consent gate: a do_not_use / needs-parental-consent clip can't
    # even be clip-made, with a plain-language, actionable reason.
    _blocked = W._footage_permission_error(asset)
    if _blocked:
        return jsonify(_blocked), 403

    fmt = (payload.get("format") or "story").strip().lower()
    from mediahub.visual.motion import MOTION_FORMATS

    if fmt not in MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    try:
        target_moments = max(1, min(5, int(payload.get("target_moments", 1))))
    except (TypeError, ValueError):
        target_moments = 1
    title = (payload.get("title") or "").strip()[:120]
    with_captions = bool(payload.get("with_captions", True))
    with_reframe = bool(payload.get("with_reframe", True))
    look = W._video_safe_look(payload.get("look"))
    enhance_audio = bool(payload.get("enhance_audio", False))
    with_music = bool(payload.get("with_music", False))
    remove_silence = bool(payload.get("remove_silence", False))
    remove_fillers = bool(payload.get("remove_fillers", False))
    music_mood = (payload.get("music_mood") or "uplifting").strip().lower()[:24]
    caption_style = "karaoke" if payload.get("animated_captions") else "static"
    slow_mo = 0.5 if payload.get("slow_mo") else 1.0

    from mediahub.video.clip_maker import UndecodableClip, clip_maker
    from mediahub.video.probe import ProbeUnavailable

    try:
        result = clip_maker(
            asset.path,
            format_name=fmt,
            target_moments=target_moments,
            title=title,
            with_captions=with_captions,
            with_reframe=with_reframe,
            caption_style=caption_style,
            look=look,
            enhance_audio=enhance_audio,
            with_music=with_music,
            music_mood=music_mood,
            remove_silence=remove_silence,
            remove_fillers=remove_fillers,
            slow_mo=slow_mo,
            colours=W._video_brand_colours(),
        )
    except ProbeUnavailable:
        return jsonify(
            {
                "error": "engine_unavailable",
                "message": "The video engine (FFmpeg) isn't available to analyse "
                "this clip on this deployment.",
            }
        ), 503
    except UndecodableClip as e:
        # The upload probes to nothing (corrupt / not a video). Reject it
        # cleanly here rather than building a doomed timeline that 500s at
        # render.
        return jsonify({"error": "undecodable_clip", "message": str(e)[:200]}), 422
    except Exception as e:  # honest surface; never a fabricated clip
        W.log.warning("clip-maker failed for %s: %s", asset_id, e)
        return jsonify({"error": "clip_maker_failed", "message": str(e)[:200]}), 500

    from mediahub.video.projects import VideoProject

    proj = VideoProject(
        id="",
        profile_id=asset.profile_id,
        name=title or f"Clip from {asset.filename}"[:80],
        edl=result.edl,
        source_asset_id=asset_id,
        format_name=fmt,
    )
    proj = W._video_project_store().save(proj)
    return jsonify({"ok": True, "project_id": proj.id, "manifest": result.manifest})


def api_video_clip_maker_job():
    """J-1/H-19: async twin of api_video_clip_maker.

    The ASR + moment analysis ran synchronously for tens of seconds with the
    button live, so an impatient double-click made duplicate projects. This
    validates in the request thread, returns 202 {job_id, poll_url}, and runs
    the analysis on a background thread the client polls — the button stays
    disabled for the whole run and the finished project id rides the poll.
    The project row is created only on success, so a failed analysis (honest
    engine error) leaves no orphan.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    payload = request.get_json(silent=True) or {}
    asset_id = (payload.get("asset_id") or "").strip()
    if not asset_id:
        return jsonify({"error": "asset_id_required"}), 400
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if not asset or asset.type != "footage":
        return jsonify({"error": "footage_not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"error": "forbidden"}), 403
    if not Path(asset.path).exists():
        return jsonify({"error": "footage_missing_on_disk"}), 410
    _blocked = W._footage_permission_error(asset)
    if _blocked:
        return jsonify(_blocked), 403

    fmt = (payload.get("format") or "story").strip().lower()
    from mediahub.visual.motion import MOTION_FORMATS

    if fmt not in MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    try:
        target_moments = max(1, min(5, int(payload.get("target_moments", 1))))
    except (TypeError, ValueError):
        target_moments = 1
    title = (payload.get("title") or "").strip()[:120]
    with_captions = bool(payload.get("with_captions", True))
    with_reframe = bool(payload.get("with_reframe", True))
    look = W._video_safe_look(payload.get("look"))
    enhance_audio = bool(payload.get("enhance_audio", False))
    with_music = bool(payload.get("with_music", False))
    remove_silence = bool(payload.get("remove_silence", False))
    remove_fillers = bool(payload.get("remove_fillers", False))
    music_mood = (payload.get("music_mood") or "uplifting").strip().lower()[:24]
    caption_style = "karaoke" if payload.get("animated_captions") else "static"
    slow_mo = 0.5 if payload.get("slow_mo") else 1.0

    # Capture everything the detached worker needs (no request context there).
    asset_path = asset.path
    asset_profile_id = asset.profile_id
    asset_filename = asset.filename
    colours = W._video_brand_colours()

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "video-clip",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "project_id": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        from mediahub.video.clip_maker import UndecodableClip, clip_maker
        from mediahub.video.probe import ProbeUnavailable
        from mediahub.video.projects import VideoProject

        try:
            with W._job_heartbeat(job):
                result = clip_maker(
                    asset_path,
                    format_name=fmt,
                    target_moments=target_moments,
                    title=title,
                    with_captions=with_captions,
                    with_reframe=with_reframe,
                    caption_style=caption_style,
                    look=look,
                    enhance_audio=enhance_audio,
                    with_music=with_music,
                    music_mood=music_mood,
                    remove_silence=remove_silence,
                    remove_fillers=remove_fillers,
                    slow_mo=slow_mo,
                    colours=colours,
                )
                proj = VideoProject(
                    id="",
                    profile_id=asset_profile_id,
                    name=title or f"Clip from {asset_filename}"[:80],
                    edl=result.edl,
                    source_asset_id=asset_id,
                    format_name=fmt,
                )
                proj = W._video_project_store().save(proj)
            job["status"] = "done"
            job["project_id"] = proj.id
        except ProbeUnavailable:
            job["status"] = "error"
            job["error"] = "engine_unavailable"
            job["user_message"] = (
                "The video engine (FFmpeg) isn't available to analyse this clip "
                "on this deployment."
            )
        except UndecodableClip as e:
            job["status"] = "error"
            job["error"] = "undecodable_clip"
            job["user_message"] = str(e)[:200]
        except Exception as e:  # honest surface; never a fabricated clip
            job["status"] = "error"
            job["error"] = str(e)[:200]
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"vidclip-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_video_reel():
    """Build an AI-directed reel from several footage clips and save it.

    The headline footage flow: pick a handful of clips, the director (AI
    judgement, honest default) orders the strongest detected moments, picks a
    look, a music mood and a hook, and the deterministic engine assembles a
    branded, captioned, graded, scored vertical reel — for human approval
    before export, like everything else.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("asset_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"error": "asset_ids_required"}), 400
    asset_ids = [str(a).strip() for a in raw_ids if str(a).strip()][:8]
    if not asset_ids:
        return jsonify({"error": "asset_ids_required"}), 400
    store = W._v8_get_media_store()
    paths: list[str] = []
    profile_id = None
    for aid in asset_ids:
        asset = store.get(aid)
        if not asset or asset.type != "footage":
            return jsonify({"error": "footage_not_found", "asset_id": aid}), 404
        if not W._session_can_access_profile(asset.profile_id):
            return jsonify({"error": "forbidden"}), 403
        if not Path(asset.path).exists():
            return jsonify({"error": "footage_missing_on_disk", "asset_id": aid}), 410
        # M26 — consent gate on every clip the reel would consume.
        _blocked = W._footage_permission_error(asset)
        if _blocked:
            return jsonify({**_blocked, "asset_id": aid}), 403
        paths.append(asset.path)
        profile_id = asset.profile_id

    fmt = (payload.get("format") or "story").strip().lower()
    from mediahub.visual.motion import MOTION_FORMATS

    if fmt not in MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    try:
        max_beats = max(1, min(5, int(payload.get("max_beats", 5))))
    except (TypeError, ValueError):
        max_beats = 5
    brief = (payload.get("brief_context") or "").strip()[:200]
    with_captions = bool(payload.get("with_captions", True))
    with_reframe = bool(payload.get("with_reframe", True))
    with_music = bool(payload.get("with_music", True))
    enhance_audio = bool(payload.get("enhance_audio", True))
    caption_style = "static" if payload.get("animated_captions") is False else "karaoke"
    # Caption more of the montage than just the lead beat by default (each
    # window is offset to its place on the timeline); 1 = lead only.
    try:
        caption_beats = max(1, min(max_beats, int(payload.get("caption_beats", 3))))
    except (TypeError, ValueError):
        caption_beats = 3

    from mediahub.video.probe import ProbeUnavailable
    from mediahub.video.reel_builder import make_reel

    try:
        result = make_reel(
            paths,
            format_name=fmt,
            max_beats=max_beats,
            with_captions=with_captions,
            caption_style=caption_style,
            caption_beats=caption_beats,
            with_reframe=with_reframe,
            with_music=with_music,
            enhance_audio=enhance_audio,
            brief_context=brief,
            colours=W._video_brand_colours(),
        )
    except ProbeUnavailable:
        return jsonify(
            {
                "error": "engine_unavailable",
                "message": "The video engine (FFmpeg) isn't available to analyse "
                "footage on this deployment.",
            }
        ), 503
    except Exception as e:  # honest surface; never a fabricated reel
        W.log.warning("reel build failed: %s", e)
        return jsonify({"error": "reel_failed", "message": str(e)[:200]}), 500

    from mediahub.video.projects import VideoProject

    name = (result.plan.hook or brief or "Footage reel").strip()[:80] or "Footage reel"
    proj = VideoProject(
        id="",
        profile_id=profile_id,
        name=name,
        edl=result.edl,
        source_asset_id=asset_ids[0],
        format_name=fmt,
    )
    proj = W._video_project_store().save(proj)
    return jsonify({"ok": True, "project_id": proj.id, "manifest": result.manifest})


def api_video_reel_job():
    """J-1: async twin of api_video_reel (per-clip moment detection + the AI
    director + assembly ran synchronously up to a few minutes). Validates in
    the request thread, returns 202, directs on a background thread the client
    polls; the finished project id rides the poll. The row is created only on
    success, so a failed direction leaves no orphan."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("asset_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"error": "asset_ids_required"}), 400
    asset_ids = [str(a).strip() for a in raw_ids if str(a).strip()][:8]
    if not asset_ids:
        return jsonify({"error": "asset_ids_required"}), 400
    store = W._v8_get_media_store()
    paths: list[str] = []
    profile_id = None
    for aid in asset_ids:
        asset = store.get(aid)
        if not asset or asset.type != "footage":
            return jsonify({"error": "footage_not_found", "asset_id": aid}), 404
        if not W._session_can_access_profile(asset.profile_id):
            return jsonify({"error": "forbidden"}), 403
        if not Path(asset.path).exists():
            return jsonify({"error": "footage_missing_on_disk", "asset_id": aid}), 410
        _blocked = W._footage_permission_error(asset)
        if _blocked:
            return jsonify({**_blocked, "asset_id": aid}), 403
        paths.append(asset.path)
        profile_id = asset.profile_id

    fmt = (payload.get("format") or "story").strip().lower()
    from mediahub.visual.motion import MOTION_FORMATS

    if fmt not in MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    try:
        max_beats = max(1, min(5, int(payload.get("max_beats", 5))))
    except (TypeError, ValueError):
        max_beats = 5
    brief = (payload.get("brief_context") or "").strip()[:200]
    with_captions = bool(payload.get("with_captions", True))
    with_reframe = bool(payload.get("with_reframe", True))
    with_music = bool(payload.get("with_music", True))
    enhance_audio = bool(payload.get("enhance_audio", True))
    caption_style = "static" if payload.get("animated_captions") is False else "karaoke"
    try:
        caption_beats = max(1, min(max_beats, int(payload.get("caption_beats", 3))))
    except (TypeError, ValueError):
        caption_beats = 3
    colours = W._video_brand_colours()
    first_asset_id = asset_ids[0]

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "video-reel",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "project_id": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        from mediahub.video.probe import ProbeUnavailable
        from mediahub.video.projects import VideoProject
        from mediahub.video.reel_builder import make_reel

        try:
            with W._job_heartbeat(job):
                result = make_reel(
                    paths,
                    format_name=fmt,
                    max_beats=max_beats,
                    with_captions=with_captions,
                    caption_style=caption_style,
                    caption_beats=caption_beats,
                    with_reframe=with_reframe,
                    with_music=with_music,
                    enhance_audio=enhance_audio,
                    brief_context=brief,
                    colours=colours,
                )
                name = (result.plan.hook or brief or "Footage reel").strip()[:80] or "Footage reel"
                proj = VideoProject(
                    id="",
                    profile_id=profile_id,
                    name=name,
                    edl=result.edl,
                    source_asset_id=first_asset_id,
                    format_name=fmt,
                )
                proj = W._video_project_store().save(proj)
            job["status"] = "done"
            job["project_id"] = proj.id
        except ProbeUnavailable:
            job["status"] = "error"
            job["error"] = "engine_unavailable"
            job["user_message"] = (
                "The video engine (FFmpeg) isn't available to analyse footage "
                "on this deployment."
            )
        except Exception as e:  # honest surface; never a fabricated reel
            job["status"] = "error"
            job["error"] = str(e)[:200]
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"vidreel-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_video_project_enhance(project_id: str):
    """Apply a colour look / soundtrack / stabilisation to a saved project.

    A post-hoc enhancement pass over any project's timeline (the grade, the
    music bed + voice cleanup, the stabiliser). Like any edit it reopens
    approval (rule 6) so a human re-confirms the changed cut before export.
    """
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    payload = request.get_json(silent=True) or {}
    from mediahub.video.edl import AudioPlan

    edl = proj.edl
    changed = False
    if "look" in payload:
        edl.look = W._video_safe_look(payload.get("look"))
        changed = True
    if payload.get("enhance_audio") is not None or payload.get("with_music") is not None:
        enhance_audio = bool(payload.get("enhance_audio", False))
        with_music = bool(payload.get("with_music", False))
        mood = (payload.get("music_mood") or "uplifting").strip().lower()[:24]
        music_path = ""
        if with_music:
            try:
                from mediahub.video.reel_builder import resolve_music

                music_path = resolve_music(mood, content_key=project_id) or ""
            except Exception:
                music_path = ""
        plan = AudioPlan(
            music=music_path,
            enhance_voice=enhance_audio,
            loudness="social" if enhance_audio else "",
            duck=True,
        )
        edl.audio = None if plan.is_empty() else plan
        changed = True
    if bool(payload.get("stabilize")):
        try:
            W._video_stabilize_edl(edl, project_id)
            changed = True
        except Exception as e:
            return jsonify({"error": "stabilize_failed", "message": str(e)[:200]}), 503
    if changed:
        proj.edl = edl
        proj.status = "draft"  # an edit reopens approval (rule 6)
        store.save(proj)
    return jsonify({"ok": True, "project": proj.to_dict()})


def api_video_project_stabilize_job(project_id: str):
    """J-1: async twin of the enhance route's stabilise branch — two-pass
    vidstab (up to minutes per source) is the studio's heaviest sync op, well
    past the proxy timeout. Validates + returns 202, stabilises on a
    background thread the client polls; the updated project (status reopened
    to 'draft', rule 6) rides the poll. The cheap look/music enhance branches
    stay on the synchronous enhance route.
    """
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "video-stabilize",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "project_id": project_id,
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        from mediahub.video.enhance import VideoEnhanceUnavailable

        try:
            with W._job_heartbeat(job):
                # Hold the shared render slot: two-pass vidstab is a heavy
                # encode, and the async path makes concurrent heavy jobs (a
                # second tab, a queued render) far more likely than the sync
                # route did, so serialise them on the box.
                with W._render_slot("video", project_id, timeout=W._RENDER_TRY_TIMEOUT):
                    p = W._video_project_store().get(project_id)
                    if p is None:
                        raise RuntimeError("project not found")
                    W._video_stabilize_edl(p.edl, project_id)
                    p.status = "draft"  # an edit reopens approval (rule 6)
                    W._video_project_store().save(p)
                    proj_dict = p.to_dict()
            # Single-writer: mutate the job dict only outside the heartbeat block.
            job["project"] = proj_dict
            job["status"] = "done"
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except VideoEnhanceUnavailable as e:
            job["status"] = "error"
            job["error"] = "stabilize_unavailable"
            job["user_message"] = str(e)
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)[:200]
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"vidstab-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_video_project_caption(project_id: str):
    """Correct the burned caption track (text / timing) on a project.

    The ASR transcript is verbatim but not perfect — a name misheard, a cue a
    beat late. These deterministic edits (from ``video.captions``) let a human
    fix the words/timing; like any edit it reopens approval (rule 6).
    """
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    edl = proj.edl
    track = edl.captions
    if not track or not track.get("cues"):
        return jsonify(
            {"error": "no_captions", "message": "This clip has no captions to edit."}
        ), 400
    payload = request.get_json(silent=True) or {}
    op = (payload.get("op") or "").strip().lower()
    from mediahub.video import captions as _cap

    try:
        if op == "edit":
            track = _cap.edit_cue_text(
                track, int(payload.get("index")), str(payload.get("text", ""))[:300]
            )
        elif op == "delete":
            track = _cap.delete_cue(track, int(payload.get("index")))
        elif op == "retime":
            track = _cap.retime_cue(
                track,
                int(payload.get("index")),
                from_frame=int(payload.get("from_frame", 0)),
                dur_frames=int(payload.get("dur_frames", 1)),
            )
        elif op == "shift":
            track = _cap.shift_track(track, int(payload.get("delta_frames", 0)))
        else:
            return jsonify(
                {"error": "bad_op", "message": "op must be edit|delete|retime|shift"}
            ), 400
    except (TypeError, ValueError):
        # A missing/non-numeric index or frame value fails an int() cast;
        # surface an actionable message, never the raw Python cast error.
        return jsonify(
            {
                "error": "bad_params",
                "message": "A caption edit needs a whole-number index (and frame values).",
            }
        ), 400
    edl.captions = track
    proj.edl = edl
    proj.status = "draft"  # an edit reopens approval (rule 6)
    store.save(proj)
    return jsonify({"ok": True, "cues": track.get("cues", [])})


def api_video_projects_list():
    """List the active profile's saved video projects (JSON)."""
    pid = W._active_profile_id()
    projects = W._video_project_store().list(profile_id=pid)
    out = []
    for p in projects:
        rendered = (W._video_render_dir(p.id) / f"{p.format_name}.mp4").exists()
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "format": p.format_name,
                "clips": len(p.edl.clips),
                "duration_ms": p.edl.total_timeline_ms(),
                "rendered": rendered,
                "updated_at": p.updated_at,
                "file_url": url_for("api_video_project_file", project_id=p.id),
            }
        )
    return jsonify({"projects": out})


def api_video_project(project_id: str):
    """Fetch or update a single video project (name / EDL / status)."""
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    if request.method == "GET":
        # M26 — the approve dialog lists each source clip's permission
        # state so the human gate is informed, not blind.
        return jsonify(
            {
                "ok": True,
                "project": proj.to_dict(),
                "source_permissions": W._project_source_states(proj),
            }
        )
    payload = request.get_json(silent=True) or {}
    if "name" in payload:
        proj.name = str(payload["name"])[:120]
    if "edl" in payload and isinstance(payload["edl"], dict):
        from mediahub.video.edl import EDL, EDLError, validate

        try:
            new_edl = EDL.from_dict(payload["edl"])
            validate(new_edl)
        except EDLError as e:
            return jsonify({"error": "invalid_edl", "message": str(e)}), 400
        except (ValueError, TypeError, AttributeError):
            # EDL.from_dict coerces fields (int/float casts, per-clip dicts),
            # so a wrong-typed field ("width": "abc", "clips": "x", a null
            # fps) raises a plain ValueError/TypeError/AttributeError rather
            # than EDLError. Catch those too so a malformed timeline is an
            # honest 400, never an unhandled 500 with a Python-internals trace.
            return jsonify(
                {
                    "error": "invalid_edl",
                    "message": "The timeline is malformed. Reload the studio and try again.",
                }
            ), 400
        # Bind every clip source to one already on this project's saved
        # timeline. The EDL validator only checks a source is non-empty, so
        # without this a caller could point a clip at ANY file on the box
        # (another tenant's footage, any readable media) and have the
        # render / waveform / export engine read it back. A legitimate edit
        # only ever reorders / trims / grades / drops the clips it was given
        # — new footage enters solely via Clip-Maker / the reel (new
        # projects), never by rewriting an existing timeline's sources.
        allowed = {W._video_norm_source(c.source) for c in (proj.edl.clips or [])}
        foreign = next(
            (c.source for c in new_edl.clips if W._video_norm_source(c.source) not in allowed),
            None,
        )
        if foreign is not None:
            return jsonify(
                {
                    "error": "invalid_edl",
                    "message": "A clip points at a source that isn't part of "
                    "this project's footage. Reload the studio and try again.",
                }
            ), 400
        # F-14 — burned caption cues are frame-indexed to the timeline they
        # were built on. When an edit reorders / trims / deletes clips the
        # timeline shifts, so re-time the cues to follow their clip instead of
        # drifting onto the wrong moment. Only fires when the clip structure
        # actually changed (a text / grade-only edit leaves the track exactly
        # as sent, so the render stays byte-identical).
        if new_edl.captions and (new_edl.captions.get("cues")):
            # A structural change is any edit that moves a clip's placement on
            # the timeline: its source, trim window, or the transition that
            # shifts everything after it. Grade / caption-text edits don't.
            def _shape(clips):
                return [
                    (
                        c.source,
                        c.in_ms,
                        c.out_ms,
                        c.transition_in.kind,
                        c.transition_in.duration_ms,
                    )
                    for c in clips
                ]

            if _shape(proj.edl.clips or []) != _shape(new_edl.clips or []):
                from mediahub.video.captions import retime_track_for_edit

                def _clip_descs(edl_obj):
                    offs = edl_obj.clip_start_offsets_ms()
                    return [
                        {
                            "source": c.source,
                            "offset_ms": o,
                            "in_ms": c.in_ms,
                            "out_ms": c.out_ms,
                        }
                        for c, o in zip(edl_obj.clips, offs)
                    ]

                new_edl.captions = retime_track_for_edit(
                    new_edl.captions,
                    _clip_descs(proj.edl),
                    _clip_descs(new_edl),
                    fps=new_edl.fps,
                )
        proj.edl = new_edl
        proj.status = "draft"  # an edit reopens approval (rule 6)
    store.save(proj)
    return jsonify({"ok": True, "project": proj.to_dict()})


def api_video_clip_waveform(project_id: str, clip_index: int):
    """Audio-waveform peaks for one clip's *source*, for the editor's scrubber.

    A deterministic measurement (FFmpeg decode → peak buckets), honest-erroring
    when FFmpeg is absent. Keyed by project + clip index so no disk path is ever
    taken from the client; access is gated by project ownership.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    clips = proj.edl.clips if (proj and proj.edl) else []
    if not (0 <= clip_index < len(clips)):
        return jsonify({"error": "clip_not_found"}), 404
    source = clips[clip_index].source
    if not source or not Path(source).exists():
        return jsonify({"error": "source_missing_on_disk"}), 410
    try:
        buckets = max(16, min(2000, int(request.args.get("buckets", 240))))
    except (TypeError, ValueError):
        buckets = 240

    from mediahub.video.waveform import WaveformUnavailable, extract_peaks

    try:
        peaks = extract_peaks(source, buckets=buckets)
    except WaveformUnavailable as e:
        return jsonify({"error": "engine_unavailable", "message": str(e)[:200]}), 503
    except Exception as e:  # honest surface; never a fabricated waveform
        W.log.warning("waveform failed: %s", e)
        return jsonify({"error": "waveform_failed"}), 500

    # Source duration lets the client map a peak index → time and place the
    # current [in, out] trim window on the strip.
    dur = 0
    try:
        from mediahub.video.probe import probe_clip

        dur = probe_clip(source).duration_ms
    except Exception:
        dur = 0
    return jsonify({"ok": True, "peaks": peaks, "buckets": buckets, "duration_ms": dur})


def api_video_project_render(project_id: str):
    """Render a project's timeline to an MP4 (server-side; honest-error)."""
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    from mediahub.video.render import VideoEngineUnavailable
    from mediahub.video.render import available as _render_available
    from mediahub.video.render import render_edl

    # M26 — consent gate at render time, re-resolving each EDL clip's
    # source: a permission regression AFTER project creation still blocks
    # (checked before the engine so the block is honest on any deployment).
    _blocked = W._project_blocked_source(proj)
    if _blocked:
        return jsonify(_blocked), 403
    if not _render_available():
        return jsonify(
            {
                "error": "engine_unavailable",
                "message": "The video render engine (FFmpeg + renderer) isn't "
                "available on this deployment.",
            }
        ), 503
    # M28 — close the render on the branded club end-card (a dissolve into
    # the club outro rendered by the existing still renderer). Appended at
    # render time on a COPY of the timeline (the saved project is never
    # mutated); the end-card MP4 is an ordinary clip source, so the render
    # cache key folds its fingerprint exactly like music beds. Honest
    # fallback: no brand/renderer/FFmpeg → the timeline renders unchanged.
    from mediahub.video.end_card import append_end_card

    render_edl_input, end_card_note = append_end_card(proj.edl, W._video_brand_kit())
    out_path = W._video_render_dir(project_id) / f"{proj.format_name}.mp4"
    try:
        render_edl(render_edl_input, out_path)
    except VideoEngineUnavailable as e:
        return jsonify({"error": "engine_unavailable", "message": str(e)}), 503
    except Exception as e:
        W.log.warning("video render failed for %s: %s", project_id, e)
        return jsonify({"error": "render_failed", "message": str(e)[:200]}), 500
    return jsonify(
        {
            "ok": True,
            "file_url": url_for("api_video_project_file", project_id=project_id),
            "end_card": "appended" if not end_card_note else "skipped",
            **({"end_card_note": end_card_note} if end_card_note else {}),
        }
    )


def api_video_project_render_job(project_id: str):
    """J-1: the async twin of api_video_project_render.

    A 30-90s render held one HTTP connection open, which reverse proxies
    kill — the button then "did nothing". This returns 202 {job_id,
    poll_url} immediately and renders on a background thread the client
    polls via api_reel_job_status (the same disk-backed job store the reel/
    motion routes use). The three fail-fast gates (tenant / consent /
    engine) and the end-card fold stay in the request thread so a blocked
    source never spawns a doomed job; the rendered MP4 lands at the same
    address the unchanged api_video_project_file already serves, so a cache
    hit for an unchanged EDL is still sub-second.
    """
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    from mediahub.video.render import VideoEngineUnavailable
    from mediahub.video.render import available as _render_available
    from mediahub.video.render import render_edl

    _blocked = W._project_blocked_source(proj)
    if _blocked:
        return jsonify(_blocked), 403
    if not _render_available():
        return jsonify(
            {
                "error": "engine_unavailable",
                "message": "The video render engine (FFmpeg + renderer) isn't "
                "available on this deployment.",
            }
        ), 503
    # Fold the club end-card in the request thread (a COPY of the timeline),
    # exactly like the sync route, so the worker renders byte-identical input
    # and the content-cache key matches — never proj.edl raw.
    from mediahub.video.end_card import append_end_card

    render_edl_input, _end_card_note = append_end_card(proj.edl, W._video_brand_kit())
    out_path = W._video_render_dir(project_id) / f"{proj.format_name}.mp4"
    file_url = url_for("api_video_project_file", project_id=project_id)

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "video-render",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            with W._job_heartbeat(job):
                with W._render_slot("video", project_id, timeout=W._RENDER_TRY_TIMEOUT):
                    render_edl(render_edl_input, out_path)
            if not Path(out_path).exists():
                raise RuntimeError("mp4 missing after render")
            job["status"] = "done"
            job["video_url"] = file_url
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except VideoEngineUnavailable as e:
            job["status"] = "error"
            job["error"] = "engine_unavailable"
            job["user_message"] = str(e)
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)[:200]
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"vidrender-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_video_project_approve(project_id: str):
    """Approve (or reject) a project — the human gate before export (rule 6)."""
    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "approved").strip()
    try:
        updated = store.set_status(project_id, status)
    except ValueError as e:
        return jsonify({"error": "bad_status", "message": str(e)}), 400
    return jsonify({"ok": True, "status": updated.status})


def api_video_project_file(project_id: str):
    """Serve a rendered project MP4 (inline) or poster; export needs approval."""

    store = W._video_project_store()
    proj = store.get(project_id)
    if not W._video_can_access_project(proj):
        return jsonify({"error": "not_found"}), 404
    path = W._video_render_dir(project_id) / f"{proj.format_name}.mp4"
    if not path.exists():
        return jsonify({"error": "not_rendered"}), 404
    if (request.args.get("poster") or "").strip().lower() in {"1", "true", "yes"}:
        poster = path.with_suffix(".poster.png")
        if not poster.exists():
            return jsonify({"error": "poster_not_rendered"}), 404
        return send_file(str(poster), mimetype="image/png")
    download = (request.args.get("download") or "").strip().lower() in {"1", "true", "yes"}
    # Approval-before-export gate (rule 6): inline preview is always allowed
    # for review, but a download/export requires a human approval.
    if download and proj.status != "approved":
        return jsonify(
            {
                "error": "not_approved",
                "message": "Approve this clip before exporting it.",
            }
        ), 403
    # M26 — consent gate at export, re-resolving each EDL clip's source:
    # a permission regression after approval still blocks the download.
    if download:
        _blocked = W._project_blocked_source(proj)
        if _blocked:
            return jsonify(_blocked), 403
    # Strip control characters (newlines especially) from the download name:
    # send_file writes it into the Content-Disposition header, and werkzeug
    # raises on a header value with a newline — an unhandled 500 on export
    # for a project whose name contains one.
    safe_name = re.sub(r"[\x00-\x1f\x7f]+", " ", proj.name[:48]).strip() or "clip"
    return send_file(
        str(path),
        mimetype="video/mp4",
        as_attachment=download,
        download_name=f"{safe_name}.mp4",
    )


def register(app) -> None:
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule("/video", endpoint="video_studio_page", view_func=video_studio_page)
    app.add_url_rule(
        "/api/video/footage",
        endpoint="api_video_footage_upload",
        view_func=api_video_footage_upload,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/footage/<asset_id>/permission",
        endpoint="api_video_footage_permission",
        view_func=api_video_footage_permission,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/footage/<asset_id>/best-frame",
        endpoint="api_video_footage_best_frame",
        view_func=api_video_footage_best_frame,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/footage", endpoint="api_video_footage_list", view_func=api_video_footage_list
    )
    app.add_url_rule(
        "/api/video/clip-maker",
        endpoint="api_video_clip_maker",
        view_func=api_video_clip_maker,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/clip-maker-job",
        endpoint="api_video_clip_maker_job",
        view_func=api_video_clip_maker_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/reel", endpoint="api_video_reel", view_func=api_video_reel, methods=["POST"]
    )
    app.add_url_rule(
        "/api/video/reel-job",
        endpoint="api_video_reel_job",
        view_func=api_video_reel_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/enhance",
        endpoint="api_video_project_enhance",
        view_func=api_video_project_enhance,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/stabilize-job",
        endpoint="api_video_project_stabilize_job",
        view_func=api_video_project_stabilize_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/caption",
        endpoint="api_video_project_caption",
        view_func=api_video_project_caption,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects", endpoint="api_video_projects_list", view_func=api_video_projects_list
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>",
        endpoint="api_video_project",
        view_func=api_video_project,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/clip/<int:clip_index>/waveform",
        endpoint="api_video_clip_waveform",
        view_func=api_video_clip_waveform,
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/render",
        endpoint="api_video_project_render",
        view_func=api_video_project_render,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/render-job",
        endpoint="api_video_project_render_job",
        view_func=api_video_project_render_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/approve",
        endpoint="api_video_project_approve",
        view_func=api_video_project_approve,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/video/projects/<project_id>/file",
        endpoint="api_video_project_file",
        view_func=api_video_project_file,
    )
