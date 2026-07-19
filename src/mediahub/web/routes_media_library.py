"""Media library: photo upload/serve/edit, vision tagging, share-target.

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

import os
import re
import time
from pathlib import Path
from typing import Optional

from flask import (
    Response,
    jsonify,
    redirect,
    request,
    send_file,
    session,
    url_for,
)

from mediahub.web import web as W


# Photo-ingest allowlist: attacker-chosen suffixes (.svg, .html, …) must
# never be stored — library files are served back same-origin. HEIC/HEIF
# uploads are additionally accepted via ``heic.is_heic`` and normalised
# to JPEG on the way in.
def api_media_library_upload():
    """Save one or MANY photos into the org's library (M33 multi-upload).

    The form input carries ``multiple``, so 40 gala photos are one submit
    instead of 40 round-trips. The typed description / type apply to every
    file in the batch; rejected files are skipped and counted (the whole
    batch only errors when nothing could be saved).
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req

    files = [f for f in _req.files.getlist("file") if f and (f.filename or "").strip()]
    if not files:
        return jsonify({"error": "no_file"}), 400
    profile_id = (_req.form.get("profile_id") or "").strip()
    if not profile_id:
        return jsonify({"error": "profile_id_required"}), 400
    active_pid = W._active_profile_id() or ""
    # Strict isolation: reject uploads aimed at a different organisation
    # than the one the session is on. Run-scoped synthetic profiles are
    # allowed through since they're tied to a run the user just started.
    if profile_id != active_pid and not profile_id.startswith("_run_"):
        return jsonify({"error": "forbidden"}), 403
    description = _req.form.get("description", "").strip()
    asset_type = _req.form.get("asset_type", "athlete_action").strip()
    # PHOTOS-6: uploads made from a run context stamp the run onto the
    # asset so the evaluator can offer "photos uploaded for this meet".
    run_id = W._run_id_for_upload_stamp(_req.form.get("run_id"))

    saved_assets: list = []
    skipped = 0
    first_error: Optional[W._PhotoRejectedError] = None
    for f in files:
        try:
            saved_assets.append(
                W._save_library_photo(
                    f,
                    profile_id,
                    description=description,
                    asset_type=asset_type,
                    run_id=run_id,
                )
            )
        except W._PhotoRejectedError as e:
            skipped += 1
            if first_error is None:
                first_error = e
    if not saved_assets:
        # Nothing usable in the batch — same honest 415 the single-file
        # contract always returned.
        err = first_error or W._PhotoRejectedError("unreadable_photo", W._PHOTO_UNREADABLE_MSG)
        return jsonify({"error": err.code, "message": err.message}), 415

    # AJAX callers get JSON; plain form submissions redirect back to the library.
    if (
        _req.headers.get("Accept", "").find("application/json") != -1
        or _req.headers.get("X-Requested-With") == "XMLHttpRequest"
    ):
        first = saved_assets[0]
        return jsonify(
            {
                "ok": True,
                # Back-compat single-asset field + the full batch.
                "asset": first.to_dict() if hasattr(first, "to_dict") else first,
                "assets": [a.to_dict() if hasattr(a, "to_dict") else a for a in saved_assets],
                "saved": len(saved_assets),
                "skipped": skipped,
            }
        )
    # The library page's ?shared banner tells the user what landed.
    args = {"profile_id": profile_id, "shared": len(saved_assets)}
    if skipped:
        args["skipped"] = skipped
    return redirect(url_for("media_library_page", **args))


def share_target_receiver():
    """PWA Web Share Target (roadmap 1.22).

    Receives photos shared from the phone's OS share sheet ("share to
    MediaHub") and drops them straight into the active organisation's media
    library — the single highest-value poolside mobile behaviour. The OS
    sends a top-level multipart navigation that can't carry a CSRF token
    (so the path is CSRF-exempt, compensated by the Fetch-Metadata guard
    below) and writes only to the *signed-in* session's own library.
    Non-image, disallowed-type, and unreadable attachments are skipped
    and counted.
    """
    if not W._v8_ok:
        return redirect(url_for("media_library_page"))
    from flask import request as _req

    # Fetch-Metadata guard — the compensating control for the CSRF exemption.
    # Every share_target-capable browser stamps ``Sec-Fetch-Site`` on the
    # top-level share navigation (``none``: user-agent-initiated), so a
    # cross-site page auto-submitting a forged multipart POST arrives as
    # ``cross-site`` and is rejected before anything is saved. An absent
    # header is allowed: browsers that could be CSRF'd always send it —
    # only non-browser clients (which carry no ambient session) omit it.
    sec_fetch_site = (_req.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if sec_fetch_site not in ("", "none", "same-origin"):
        try:
            from mediahub.compliance.security_log import record_event as _sec_event

            _sec_event(
                "share_target_cross_site_rejected",
                detail=sec_fetch_site[:200],
                outcome="blocked",
            )
        except Exception:
            pass
        return (
            "<h1>Request blocked</h1><p>Shared photos are only accepted from "
            "the device share sheet, not from another website.</p>"
        ), 403

    profile_id = W._active_profile_id()
    if not profile_id:
        # Shared while signed out (a lapsed phone session is common). The
        # bytes can't be safely kept without a tenant, so J-11: don't fail
        # silently — flash so the user knows to sign in and re-share, instead
        # of believing the shot is in the library when it was dropped.
        session["sign_in_error"] = (
            "Sign in first, then re-share the photo from your camera roll — it wasn't saved."
        )
        return redirect(url_for("sign_in_page"))

    # Browsers post shared files under the manifest-declared "photos" field;
    # accept "file" too for resilience across share-sheet implementations.
    files = _req.files.getlist("photos") + _req.files.getlist("file")
    # OS share sheets can't carry a run id, but a future share URL might —
    # accept and validate it the same way the library upload does.
    run_id = W._run_id_for_upload_stamp(_req.form.get("run_id"))
    saved = 0
    skipped = 0
    for f in files:
        if not f or not (f.filename or "").strip():
            continue
        ctype = (f.mimetype or "").lower()
        if ctype and not ctype.startswith("image/"):
            skipped += 1  # the OS bundled a non-image attachment — ignore it
            continue
        try:
            W._save_library_photo(
                f, profile_id, description="", asset_type="athlete_action", run_id=run_id
            )
            saved += 1
        except W._PhotoRejectedError:
            skipped += 1
        except Exception:
            W.log.exception("share-target: failed to save a shared photo")
            skipped += 1

    args = {"shared": saved}
    if skipped:
        args["skipped"] = skipped
    return redirect(url_for("media_library_page", **args))


def api_media_library_describe_job():
    """M34 — bulk "Describe N untagged photos" as one background job.

    Runs the same roster-anchored vision pass the per-upload hook uses
    over every untagged photo in the active org's library, with per-photo
    progress via ``api_reel_job_status``. Honest by construction: no
    provider configured → 503 with plain copy (photos stay usable, the
    badge stays); a provider error on a photo lands in the job's
    per-photo ``errors`` — never a fabricated tag. Three consecutive
    provider failures abort the pass instead of hammering a dead key.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    profile_id = W._active_profile_id() or ""
    if not profile_id:
        return jsonify({"error": "no_active_profile"}), 403
    if not W._vision_tagging_available():
        return jsonify(
            {
                "error": "ai_unavailable",
                "user_message": (
                    "AI photo tagging needs a Gemini or Anthropic API key, "
                    "which isn't configured on this deployment. Your photos "
                    "stay fully usable — add the swimmer's name in each "
                    "photo's description instead."
                ),
            }
        ), 503
    store = W._v8_get_media_store()
    untagged = store.list_untagged(profile_id=profile_id)
    if not untagged:
        return jsonify(
            {
                "ok": True,
                "status": "done",
                "total": 0,
                "message": "Every photo in this library already has tags.",
            }
        )
    roster = W._vision_roster_for(profile_id)
    targets = [(a.id, a.path, a.filename or a.id) for a in untagged]

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "describe",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "total": len(targets),
        "done": 0,
        "current": "",
        "tagged": [],
        "errors": {},
        "created_at": time.time(),
        "owner_pid": profile_id,
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        from mediahub.media_library.describe import describe_photo_vision

        consecutive_provider_failures = 0
        try:
            with W._job_heartbeat(job):
                for idx, (aid, path, label) in enumerate(targets, start=1):
                    job["current"] = str(label)
                    W._variant_job_save(job)
                    try:
                        if not path or not os.path.exists(path):
                            job["errors"][aid] = "file missing on disk"
                        else:
                            vision = describe_photo_vision(path, roster=roster)
                            W._apply_vision_result(store, aid, vision)
                            job["tagged"].append(aid)
                            consecutive_provider_failures = 0
                    except Exception as e:
                        from mediahub.media_ai.llm import (
                            ClaudeUnavailableError as _CUE,
                        )

                        job["errors"][aid] = str(e)
                        if isinstance(e, _CUE):
                            consecutive_provider_failures += 1
                            if consecutive_provider_failures >= 3:
                                job["done"] = idx
                                job["status"] = "error"
                                job["error"] = str(e)
                                job["user_message"] = (
                                    "The AI provider kept failing, so tagging "
                                    "stopped early. Photos already tagged are "
                                    "saved; try again later."
                                )
                                W._variant_job_save(job)
                                return
                    job["done"] = idx
                    W._variant_job_save(job)
            if job["tagged"]:
                job["status"] = "done"
            else:
                job["status"] = "error"
                job["error"] = "; ".join(list(job["errors"].values())[:3]) or "no photos tagged"
                job["user_message"] = "No photos could be tagged — see the per-photo errors."
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"describe-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "total": len(targets),
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


# Suffix → served Content-Type for library files. Derived from the stored
# file, never the uploader's declared type: send_file's default guess
# would happily serve a legacy .svg as image/svg+xml (active content,
# same-origin) — anything outside this map downloads as a plain blob.
def api_media_library_file(asset_id: str):
    if not W._v8_ok:
        return "", 503
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return "", 404
    if not W._session_can_access_profile(a.profile_id):
        return "", 403

    # M27 — ?poster=1 serves the deterministic poster frame extracted at
    # footage ingest (mirrors the project-file route's pattern). Honest
    # 404 when no poster was recorded (no FFmpeg at upload time) — the
    # caller keeps its current <video>-tile behaviour.
    if (request.args.get("poster") or "").strip().lower() in {"1", "true", "yes"}:
        meta = a.media_meta if isinstance(a.media_meta, dict) else {}
        # basename only — the sidecar always sits beside the blob, and a
        # tampered meta value must never traverse out of the blob dir.
        poster_name = Path(str(meta.get("poster") or "")).name
        poster = Path(a.path).parent / poster_name if poster_name else None
        if not poster_name or poster is None or not poster.exists():
            return "", 404
        resp = send_file(str(poster), mimetype="image/png")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    suffix = re.sub(r"[^a-z0-9.]", "", Path(a.path).suffix.lower())
    mime = W._IMAGE_SERVE_MIMES.get(suffix)
    try:
        if mime is None:
            # Legacy/unknown type (pre-allowlist upload): never let the
            # browser sniff or render it same-origin — download only.
            resp = send_file(
                a.path,
                mimetype="application/octet-stream",
                as_attachment=True,
                download_name=W._safe_disposition_token(f"{asset_id}{suffix}"),
            )
        else:
            resp = send_file(a.path, mimetype=mime)
            resp.headers["Content-Disposition"] = (
                f'inline; filename="{W._safe_disposition_token(f"{asset_id}{suffix}")}"'
            )
    except Exception:
        return "", 404
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def api_media_library_delete(asset_id: str):
    """Delete a media asset — the record AND its file(s) on disk.

    Wrong photo uploaded? This is the way out. POST (not DELETE verb)
    so a plain HTML form on the library page can call it; AJAX callers
    get JSON back.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req

    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    if not W._session_can_access_profile(a.profile_id):
        return jsonify({"error": "forbidden"}), 403
    for _p in (a.path, getattr(a, "cutout_path", None)):
        if not _p:
            continue
        try:
            Path(_p).unlink(missing_ok=True)
        except Exception:
            pass
    store.delete(asset_id)
    wants_json = (
        _req.headers.get("Accept", "").find("application/json") != -1
        or _req.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    if wants_json:
        return jsonify({"ok": True, "deleted": asset_id})
    return redirect(url_for("media_library_page"))


def api_imagine_info():
    """Capabilities, active provider, style presets, and this org's quota."""
    if not (W._v8_ok and W._imagine_ok):
        return jsonify({"error": "imagine_unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "no_profile"}), 403
    from mediahub.media_ai.imagine_providers.gemini_imagine import STYLE_PRESETS

    return jsonify(
        {
            "available": W._imagine.is_available(),
            "provider": W._imagine.active_provider_name(),
            "operations": sorted(W._imagine.available_operations()),
            "styles": sorted(STYLE_PRESETS.keys()),
            "quota": W._imagine_quota_json(pid),
        }
    )


def api_imagine_generate():
    """Text → image. Saves the result as a provenance-stamped library asset."""
    if not (W._v8_ok and W._imagine_ok):
        return jsonify({"error": "imagine_unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "no_profile"}), 403
    if not W._imagine_role_ok(pid):
        return W._imagine_forbidden(pid)
    # No AI quotas for the signed-in developer/operator: a None org_id makes
    # imagine skip both quota enforcement and the per-org usage record.
    _iq_org = None if W._auth.is_dev_operator() else pid
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return (
            jsonify({"error": "empty_prompt", "user_message": "Describe the image you want."}),
            400,
        )
    style = (body.get("style") or "").strip() or None
    aspect = (body.get("aspect") or "1:1").strip()
    allow_people = bool(body.get("allow_people"))
    try:
        results = W._imagine.generate(
            prompt, style=style, aspect=aspect, n=1, allow_people=allow_people, org_id=_iq_org
        )
    except Exception as exc:
        return W._imagine_error_response(exc)
    asset = W._imagine_persist(results[0], profile_id=pid, prompt=prompt)
    return jsonify(
        {
            "ok": True,
            "asset": asset.to_dict(),
            "url": url_for("api_media_library_file", asset_id=asset.id),
            "quota": W._imagine_quota_json(pid),
        }
    )


def api_imagine_subject_lift(asset_id: str):
    """Magic Grab — deterministic cutout + saliency framing (not metered)."""
    if not (W._v8_ok and W._imagine_ok):
        return jsonify({"error": "imagine_unavailable"}), 503
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    if not W._session_can_access_profile(a.profile_id):
        return jsonify({"error": "forbidden"}), 403
    out, status = W._v8_ensure_cutout(a)
    if status == "unavailable":
        return (
            jsonify(
                {
                    "error": "cutout_unavailable",
                    "user_message": "No background remover is available on this deployment.",
                }
            ),
            503,
        )
    if out is None:
        return jsonify({"error": status or "failed"}), 502
    body = request.get_json(silent=True) or {}
    ratio = (body.get("ratio") or "4:5").strip()
    focus = "center 28%"
    try:
        from mediahub.graphic_renderer.saliency import focus_position

        focus = focus_position(out, ratio)
    except Exception:
        pass
    return jsonify(
        {
            "ok": True,
            "status": status,
            "cutout_url": url_for("api_media_library_cutout", asset_id=asset_id),
            "focus_position": focus,
        }
    )


def api_imagine_asset_op(asset_id: str, op: str):
    """Run a provider-backed edit-family op on an existing library asset.

    ``op`` ∈ {edit, expand, remove, upscale, similar, style_match}. The
    active provider honest-errors (501) for ops it does not support — the
    in-house local diffusion backend (roadmap 1.1) covers the full family.
    """
    if not (W._v8_ok and W._imagine_ok):
        return jsonify({"error": "imagine_unavailable"}), 503
    if op not in W._IMAGINE_ASSET_OPS:
        return jsonify({"error": "unknown_op"}), 404
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "no_profile"}), 403
    if not W._imagine_role_ok(pid):
        return W._imagine_forbidden(pid)
    # No AI quotas for the signed-in developer/operator (see generate route).
    _iq_org = None if W._auth.is_dev_operator() else pid
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    if not W._session_can_access_profile(a.profile_id):
        return jsonify({"error": "forbidden"}), 403
    try:
        data = Path(a.path).read_bytes()
    except Exception:
        return jsonify({"error": "no_source"}), 404
    body = request.get_json(silent=True) or {}
    import base64 as _b64

    mask = None
    if body.get("mask_b64"):
        try:
            mask = _b64.b64decode(body["mask_b64"])
        except Exception:
            mask = None
    img = W._imagine.ImageInput(data=data, mime="image/png", mask=mask)
    try:
        if op == "edit":
            result = W._imagine.edit(
                img,
                (body.get("instruction") or "").strip(),
                allow_people=bool(body.get("allow_people")),
                org_id=_iq_org,
                source_asset_id=a.id,
            )
        elif op == "expand":
            result = W._imagine.expand(
                img,
                aspect=(body.get("aspect") or "1:1").strip(),
                prompt=(body.get("prompt") or "").strip(),
                org_id=_iq_org,
                source_asset_id=a.id,
            )
        elif op == "remove":
            result = W._imagine.remove(img, org_id=_iq_org, source_asset_id=a.id)
        elif op == "upscale":
            result = W._imagine.upscale(
                img, factor=int(body.get("factor") or 2), org_id=_iq_org, source_asset_id=a.id
            )
        elif op == "similar":
            results = W._imagine.similar(
                img,
                prompt=(body.get("prompt") or "").strip(),
                n=1,
                org_id=_iq_org,
                source_asset_id=a.id,
            )
            result = results[0]
        else:  # style_match
            result = W._imagine.style_match(
                img,
                style=(body.get("style") or "editorial").strip(),
                palette=body.get("palette") or None,
                org_id=_iq_org,
                source_asset_id=a.id,
            )
    except Exception as exc:
        return W._imagine_error_response(exc)
    asset = W._imagine_persist(
        result,
        profile_id=pid,
        prompt=body.get("instruction") or body.get("prompt") or "",
        source_asset=a,
    )
    return jsonify(
        {
            "ok": True,
            "asset": asset.to_dict(),
            "url": url_for("api_media_library_file", asset_id=asset.id),
            "quota": W._imagine_quota_json(pid),
        }
    )


def api_imagine_grab_text(asset_id: str):
    """Grab Text — vision-OCR the text out of an image into editable blocks."""
    if not (W._v8_ok and W._imagine_ok):
        return jsonify({"error": "imagine_unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "no_profile"}), 403
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    if not W._session_can_access_profile(a.profile_id):
        return jsonify({"error": "forbidden"}), 403
    try:
        grabbed = W._imagine.grab_text(a.path, org_id=pid)
    except Exception as exc:
        return W._imagine_error_response(exc)
    return jsonify(
        {
            "ok": True,
            "found": grabbed.found,
            "text": grabbed.text,
            "blocks": grabbed.blocks,
            "quota": W._imagine_quota_json(pid),
        }
    )


def api_mockup_templates():
    """List the deterministic product-mockup templates (for the UI picker)."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    try:
        from mediahub.mockups import list_templates

        return jsonify({"templates": list_templates()})
    except Exception:
        return jsonify({"templates": []})


def api_media_library_mockup(asset_id: str, template: str):
    """Composite an asset into a product mockup; serve the PNG directly.

    Deterministic, key-free, brand-tinted — not an AI op, so no quota/stamp.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    if not W._session_can_access_profile(a.profile_id):
        return jsonify({"error": "forbidden"}), 403
    try:
        from mediahub.mockups import compose_mockup, MockupError
    except Exception:
        return jsonify({"error": "mockups_unavailable"}), 503
    try:
        art = Path(a.path).read_bytes()
    except Exception:
        return jsonify({"error": "no_source"}), 404
    try:
        png = compose_mockup(art, template, accent=W._profile_accent_hex())
    except MockupError as e:
        return jsonify({"error": "unknown_template", "user_message": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "mockup_failed", "user_message": str(e)}), 502
    from flask import Response as _Response

    return _Response(
        png,
        mimetype="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


def api_media_library_bulk_delete():
    """UI 1.9 — delete many library assets at once (record + files on disk).

    Mirrors the single-asset delete, profile-scoped per id so one org can't
    reach another's photos even if ids leak. Content-negotiated: fetch() gets
    a per-id result list; a no-JS form POST is redirected with a flash.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    ids = W._bulk_ids_from_request(request, "ids", "asset_ids")
    wants_json = W._req_wants_json(request)
    if not ids:
        if wants_json:
            return jsonify({"error": "no_selection", "results": []}), 400
        W._flash_toast("Select at least one photo first.", "info")
        return redirect(url_for("media_library_page"))
    results: list[dict] = []
    n_ok = 0
    for aid in ids:
        a = store.get(aid)
        if not a:
            results.append({"id": aid, "ok": False, "error": "not_found"})
            continue
        if not W._session_can_access_profile(a.profile_id):
            results.append({"id": aid, "ok": False, "error": "forbidden"})
            continue
        for _p in (a.path, getattr(a, "cutout_path", None)):
            if not _p:
                continue
            try:
                Path(_p).unlink(missing_ok=True)
            except Exception:
                pass
        store.delete(aid)
        results.append({"id": aid, "ok": True})
        n_ok += 1
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "deleted": [r["id"] for r in results if r["ok"]],
                "results": results,
                "n_ok": n_ok,
            }
        )
    W._flash_toast(
        f"Deleted {n_ok} photo{'' if n_ok == 1 else 's'}.",
        "success" if n_ok else "info",
    )
    return redirect(url_for("media_library_page"))


def api_media_library_bulk_approve():
    """UI 1.9 — mark many library assets approved at once.

    Sets ``approval_status='approved'`` (the deterministic photo selector
    weights approved shots highest). Safeguarding: an asset with a hard
    permission block (``do_not_use`` / ``needs_parental_consent``) or one
    flagged not ``safe_for_minors`` is SKIPPED, never silently promoted —
    resolving that block is a deliberate human call, not a bulk one.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    ids = W._bulk_ids_from_request(request, "ids", "asset_ids")
    wants_json = W._req_wants_json(request)
    if not ids:
        if wants_json:
            return jsonify({"error": "no_selection", "results": []}), 400
        W._flash_toast("Select at least one photo first.", "info")
        return redirect(url_for("media_library_page"))
    results: list[dict] = []
    n_ok = 0
    n_skipped = 0
    for aid in ids:
        a = store.get(aid)
        if not a:
            results.append({"id": aid, "ok": False, "error": "not_found"})
            continue
        if not W._session_can_access_profile(a.profile_id):
            results.append({"id": aid, "ok": False, "error": "forbidden"})
            continue
        if a.permission_status in ("do_not_use", "needs_parental_consent") or not getattr(
            a, "safe_for_minors", True
        ):
            results.append({"id": aid, "ok": False, "error": "safeguarding_block"})
            n_skipped += 1
            continue
        store.update_fields(aid, {"approval_status": "approved"})
        results.append({"id": aid, "ok": True})
        n_ok += 1
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "approved": [r["id"] for r in results if r["ok"]],
                "results": results,
                "n_ok": n_ok,
                "n_skipped": n_skipped,
            }
        )
    msg = f"Approved {n_ok} photo{'' if n_ok == 1 else 's'}."
    if n_skipped:
        msg += f" {n_skipped} skipped (safeguarding)."
    W._flash_toast(msg, "success" if n_ok else "info")
    return redirect(url_for("media_library_page"))


def api_media_library_bulk_unapprove():
    """D-29 — move many library assets back to ``approval_status='draft'``.

    The reverse of bulk-approve, so "Mark ready for cards" is undoable. No
    safeguarding gate here: demoting a photo to Draft only makes the picker
    stop preferring it — it can never expose anything.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    ids = W._bulk_ids_from_request(request, "ids", "asset_ids")
    wants_json = W._req_wants_json(request)
    if not ids:
        if wants_json:
            return jsonify({"error": "no_selection", "results": []}), 400
        W._flash_toast("Select at least one photo first.", "info")
        return redirect(url_for("media_library_page"))
    results: list[dict] = []
    n_ok = 0
    for aid in ids:
        a = store.get(aid)
        if not a:
            results.append({"id": aid, "ok": False, "error": "not_found"})
            continue
        if not W._session_can_access_profile(a.profile_id):
            results.append({"id": aid, "ok": False, "error": "forbidden"})
            continue
        store.update_fields(aid, {"approval_status": "draft"})
        results.append({"id": aid, "ok": True})
        n_ok += 1
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "unapproved": [r["id"] for r in results if r["ok"]],
                "results": results,
                "n_ok": n_ok,
            }
        )
    W._flash_toast(
        f"Moved {n_ok} photo{'' if n_ok == 1 else 's'} back to Draft.",
        "success" if n_ok else "info",
    )
    return redirect(url_for("media_library_page"))


def api_media_library_meta(asset_id: str):
    """H-4 — edit a photo's metadata after upload.

    Description, swimmer/athlete link, venue, event and tags used to be
    write-once (set only at upload), yet three pieces of UI copy told users
    they could "review and edit anytime". When AI vision tagged the wrong
    swimmer the only fix was delete + re-upload. This lets a volunteer
    correct those fields in place (a full replace, so a wrong tag can be
    removed — not just added to). Athlete-record ids are left untouched;
    the free-text names are the reviewable display metadata the badges cite.
    """
    if not W._v8_ok:
        return jsonify({"ok": False, "error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if asset is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}

    def _list(raw):
        return [p.strip() for p in re.split(r"[,\n]", str(raw or "")) if p.strip()]

    fields: dict = {}
    if "description" in body:
        fields["description_raw"] = str(body.get("description") or "").strip()
    if "venue" in body:
        fields["linked_venue"] = (str(body.get("venue") or "").strip()) or None
    if "event" in body:
        fields["linked_event"] = (str(body.get("event") or "").strip()) or None
    if "athletes" in body:
        fields["linked_athlete_names"] = _list(body.get("athletes"))
    if "tags" in body:
        fields["tags"] = _list(body.get("tags"))
    if not fields:
        return jsonify({"ok": False, "error": "no_fields"}), 400
    store.update_fields(asset_id, fields)
    updated = store.get(asset_id)
    return jsonify(
        {
            "ok": True,
            "asset": {
                "description": updated.description_raw or "",
                "athletes": ", ".join(updated.linked_athlete_names or []),
                "venue": updated.linked_venue or "",
                "event": updated.linked_event or "",
                "tags": ", ".join(updated.tags or []),
            },
        }
    )


def api_media_library_permission(asset_id: str):
    """H-3 — record consent / permission on a photo asset.

    The only permission writer used to be the Video Studio's footage-only
    endpoint (404 for anything that isn't a clip), so a photo blocked by the
    consent gate (``needs_parental_consent`` / ``do_not_use`` / not
    ``safe_for_minors``) was a hard dead end — the only fix was delete +
    re-upload. This is a sibling writer for photo assets using the same
    PERMISSION_STATUSES vocabulary the gate enforces.
    """
    if not W._v8_ok:
        return jsonify({"ok": False, "error": "v8_unavailable"}), 503
    from mediahub.media_library.models import PERMISSION_STATUSES

    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if asset is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    status = str(body.get("permission_status") or "").strip()
    if status not in PERMISSION_STATUSES:
        return jsonify(
            {"ok": False, "error": "bad_permission", "message": "Unknown permission value."}
        ), 400
    updated = store.update_fields(asset_id, {"permission_status": status})
    # A photo is usable (won't be skipped by bulk-approve / the picker) when
    # it carries no hard block and is safe for minors — mirror the gate.
    usable = status not in ("do_not_use", "needs_parental_consent") and bool(
        getattr(updated, "safe_for_minors", True)
    )
    return jsonify(
        {
            "ok": True,
            "permission_status": status,
            "label": W._MEDIA_PERMISSION_LABELS.get(status, status),
            "usable": usable,
        }
    )


def api_media_library_bulk_export():
    """UI 1.9 — download the selected library photos as one ZIP.

    Streams the original files (profile-scoped per id; assets from another
    org or with a missing file are simply skipped). Always a native
    attachment download, so it works with or without JS.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    import io as _io
    import zipfile as _zip

    store = W._v8_get_media_store()
    ids = W._bulk_ids_from_request(request, "ids", "asset_ids")
    if not ids:
        if W._req_wants_json(request):
            return jsonify({"error": "no_selection"}), 400
        W._flash_toast("Select at least one photo to export.", "info")
        return redirect(url_for("media_library_page"))
    buf = _io.BytesIO()
    used: set[str] = set()
    n = 0
    with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as zf:
        for aid in ids:
            a = store.get(aid)
            if not a or not W._session_can_access_profile(a.profile_id):
                continue
            src = a.path
            if not src or not Path(src).exists():
                continue
            base = re.sub(r"[^A-Za-z0-9_.-]+", "_", (a.filename or Path(src).name or aid)) or aid
            name = base
            i = 1
            while name in used:
                stem, dot, ext = base.rpartition(".")
                name = f"{stem}_{i}.{ext}" if dot else f"{base}_{i}"
                i += 1
            used.add(name)
            try:
                zf.write(src, arcname=name)
                n += 1
            except Exception:
                continue
    if n == 0:
        if W._req_wants_json(request):
            return jsonify({"error": "nothing_to_export"}), 404
        W._flash_toast("None of the selected photos could be exported.", "error")
        return redirect(url_for("media_library_page"))
    pid = W._active_profile_id() or "library"
    fname = "mediahub-photos-" + (re.sub(r"[^A-Za-z0-9_.-]+", "_", pid)[:40] or "library") + ".zip"
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def api_media_library_cutout(asset_id: str):
    """Serve the background-removed cut-out PNG for one asset (UI2.1).

    Generated on first request and cached/persisted, then profile-scoped
    exactly like the original-file route. Returns an honest 503 when no
    background remover is available rather than a fake (pass-through)
    cut-out, and 404 when there is no source or generation produced
    nothing usable.
    """
    if not W._v8_ok:
        return "", 503
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return "", 404
    if not W._session_can_access_profile(a.profile_id):
        return "", 403
    path, status = W._v8_ensure_cutout(a)
    if path is None:
        return "", (503 if status == "unavailable" else 404)

    try:
        resp = send_file(str(path), mimetype="image/png")
        # Derived asset — let the browser cache it; it only changes if the
        # source is re-uploaded (which mints a new asset id).
        resp.headers["Cache-Control"] = "private, max-age=3600"
        return resp
    except Exception:
        return "", 404


def api_photo_edit_preview(asset_id: str):
    """Render a recipe on a downscaled working copy — no persist. Returns PNG."""
    from flask import request as _req, Response

    a, store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    recipe = W._photo_recipe_from_request(_req)
    try:
        from mediahub.media_library.photo_ops import load_image, encode_image

        img = load_image(a.path)
        long_edge = max(img.size)
        if long_edge > W._PHOTO_PREVIEW_MAX:
            scale = W._PHOTO_PREVIEW_MAX / float(long_edge)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        out = recipe.apply(img)
        data, mime = encode_image(out, "PNG")
    except Exception:
        return jsonify({"error": "preview_failed"}), 500
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def api_photo_edit_apply(asset_id: str):
    """Persist the posted recipe on the asset and materialise the edit."""
    from flask import request as _req

    a, store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    recipe = W._photo_recipe_from_request(_req)
    from mediahub.media_library import photo_edit as _pe

    _pe.save_recipe(a, recipe, store)
    a = store.get(asset_id)  # reload with the saved recipe
    # Learn the club's preferred Enhance strength when this save embeds a
    # (possibly scaled) Enhance suggestion — conservative and deterministic,
    # a no-op for unrelated manual edits (closes the Enhance-memory loop).
    _pe.maybe_record_enhance_accepted(a, recipe, store)
    _pe.materialize_edit(a, store)
    return jsonify(
        {
            "ok": True,
            "signature": recipe.signature(),
            "steps": len(recipe.steps),
            "describe": recipe.describe(),
            "edited_url": url_for("api_media_library_edited", asset_id=a.id),
        }
    )


def api_photo_edit_enhance(asset_id: str):
    """Return the deterministic one-click Enhance recipe (club-tuned). No persist."""
    a, store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    from mediahub.media_library import photo_edit as _pe

    try:
        recipe = _pe.suggest_enhance(a, store)
    except Exception:
        return jsonify({"error": "enhance_failed"}), 500
    return jsonify({"ok": True, "recipe": recipe.to_dict(), "describe": recipe.describe()})


def api_photo_edit_reset(asset_id: str):
    """Clear the asset's edit recipe and its materialised caches."""
    a, store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    from mediahub.media_library import photo_edit as _pe

    _pe.clear_recipe(a, store)
    return jsonify({"ok": True})


def api_media_library_edited(asset_id: str):
    """Serve the *effective* (edited) image bytes — original if no recipe.

    This is what cards and exports read so they always show the edited
    photo without knowing whether it was edited.
    """
    if not W._v8_ok:
        return "", 503
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return "", 404
    if not W._session_can_access_profile(a.profile_id):
        return "", 403
    from mediahub.media_library import photo_edit as _pe

    try:
        path = _pe.effective_image_path(a, store)
        return send_file(path)
    except Exception:
        try:
            return send_file(a.path)
        except Exception:
            return "", 404


def api_photo_profile_picture(asset_id: str):
    """Export a profile-picture crop of the asset as a new draft asset."""
    from flask import request as _req

    a, store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    try:
        payload = _req.get_json(silent=True) or {}
    except Exception:
        payload = {}
    preset = str(payload.get("preset") or "avatar_circle")
    from mediahub.media_library import photo_edit as _pe

    try:
        new = _pe.export_profile_picture(a, store, preset=preset)
    except Exception:
        return jsonify({"error": "export_failed"}), 500
    return jsonify(
        {
            "ok": True,
            "asset": new.to_dict() if hasattr(new, "to_dict") else None,
            "edit_url": url_for("photo_editor_page", asset_id=new.id),
        }
    )


def api_media_library_collage():
    """Compose selected library photos into a collage saved as a new draft.

    Content-negotiated like the other library bulk actions: the bulk
    bar's fetch() posts JSON, the no-JS form posts url-encoded ids —
    both carry the selection + a layout, and success lands in the new
    draft's photo editor.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req

    try:
        payload = (_req.get_json(silent=True) or {}) if _req.is_json else {}
    except Exception:
        payload = {}
    asset_ids = W._bulk_ids_from_request(_req, "asset_ids", "ids")
    layout = str(payload.get("layout") or _req.form.get("layout") or "grid_2x2")
    fmt_slug = str(payload.get("format") or _req.form.get("format") or "collage_square")
    wants_json = W._req_wants_json(_req)
    active_pid = W._active_profile_id() or ""
    if not active_pid:
        return jsonify({"error": "no_active_profile"}), 403
    if not asset_ids:
        if wants_json:
            return jsonify({"error": "no_assets"}), 400
        W._flash_toast("Select at least two photos to make a collage.", "info")
        return redirect(url_for("media_library_page"))

    # Dimensions from the format catalogue (falls back to a square canvas).
    width = height = 1080
    try:
        from mediahub.club_platform.format_catalog import format_for

        spec = format_for(fmt_slug)
        if spec:
            width, height = spec.width, spec.height
    except Exception:
        pass

    store = W._v8_get_media_store()
    from mediahub.media_library import photo_edit as _pe

    new = _pe.create_collage(
        asset_ids, store, profile_id=active_pid, layout=layout, width=width, height=height
    )
    if new is None:
        if wants_json:
            return jsonify({"error": "need_two_photos"}), 400
        W._flash_toast("A collage needs at least two of your own photos.", "info")
        return redirect(url_for("media_library_page"))
    if not wants_json:
        return redirect(url_for("photo_editor_page", asset_id=new.id))
    return jsonify(
        {
            "ok": True,
            "asset": new.to_dict() if hasattr(new, "to_dict") else None,
            "edit_url": url_for("photo_editor_page", asset_id=new.id),
        }
    )


def api_import_stock():
    """Import a chosen stock result into the org library, recording its rights.

    Mirrors the venue import, but org-scoped (to the active profile's library)
    and persists a StockRightsRecord so the licence + attribution + commercial
    gate stay auditable per asset.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req
    from mediahub.elements import stock as _stock

    profile_id = W._active_profile_id()
    if not profile_id or not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403

    body = _req.get_json(silent=True) or {}
    direct_url = str(body.get("direct_url") or "").strip()
    if not direct_url.startswith(("http://", "https://")):
        return jsonify({"error": "bad_media_url"}), 400
    kind = "video" if str(body.get("kind") or "photo") == "video" else "photo"
    title = str(body.get("title") or "").strip()
    source_url = str(body.get("source_url") or "").strip()
    source_site = str(body.get("source_site") or "").strip()
    licence = _stock.parse_licence(
        str(body.get("licence") or ""),
        url=str(body.get("licence_url") or ""),
        attribution=str(body.get("attribution") or ""),
        source=source_site,
    )
    # Only licence-clean (commercially usable) assets enter the library.
    if not licence.commercial_ok:
        return jsonify(
            {
                "error": "licence_not_clear",
                "user_message": "That asset's licence isn't cleared for club use.",
            }
        ), 409

    want_prefix = "video/" if kind == "video" else "image/"
    max_bytes = (60 if kind == "video" else 15) * 1024 * 1024
    try:
        # SSRF guard: validate direct_url + every redirect hop before we
        # fetch, so an authed tenant can't turn this into a read primitive
        # against internal / cloud-metadata endpoints.
        resp = W._ssrf_safe_stream_get(direct_url, timeout=20)
        resp.raise_for_status()
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if not ctype.startswith(want_prefix):
            return jsonify({"error": "wrong_media_type"}), 400
        data = resp.raw.read(max_bytes + 1, decode_content=True)
    except ValueError:
        return jsonify({"error": "bad_media_url"}), 400
    except Exception as e:
        return jsonify({"error": f"download_failed: {e}"}), 502
    if len(data) > max_bytes:
        return jsonify({"error": "media_too_large", "max_mb": max_bytes // (1024 * 1024)}), 400

    ext_map = (
        {"video/webm": ".webm", "video/ogg": ".ogv", "video/mp4": ".mp4"}
        if kind == "video"
        else {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    )
    ext = ext_map.get(ctype.split(";")[0].strip(), ".mp4" if kind == "video" else ".jpg")
    upload_dir = W.UPLOADS_DIR / "media_library" / profile_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"stock_{W.uuid.uuid4().hex[:12]}{ext}"
    dest.write_bytes(data)

    store = W._v8_get_media_store()
    from mediahub.media_library.models import MediaAsset

    asset = MediaAsset(
        id="",
        filename=dest.name,
        path=str(dest),
        type="footage" if kind == "video" else "other",
        description_raw=title or "stock asset",
        profile_id=profile_id,
        source_url=source_url or direct_url,
        source_attribution=licence.attribution or None,
        source_licence=licence.name or None,
        permission_status=str(body.get("permission_status") or "approved_public"),
        approval_status="approved",
        tags=["stock", source_site] if source_site else ["stock"],
    )
    asset = store.save(asset)

    try:
        _stock.get_ledger().record(
            _stock.StockRightsRecord(
                asset_id=asset.id,
                profile_id=profile_id,
                source=source_site or "stock",
                source_url=source_url or direct_url,
                kind=kind,
                licence=licence,
            )
        )
    except Exception as e:  # rights record is best-effort; asset already saved
        W.log.warning("stock rights record failed for %s: %s", asset.id, e)

    return jsonify(
        {
            "ok": True,
            "asset": {
                "id": asset.id,
                "url": url_for("api_media_library_file", asset_id=asset.id),
                "label": title or "stock asset",
                "licence": licence.to_dict(),
            },
        }
    )


def api_annotate_asset(asset_id: str):
    """Store a telestration annotation layer on an asset (non-destructive)."""
    from flask import request as _req
    from mediahub.elements.draw import AnnotationLayer

    a, store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    body = _req.get_json(silent=True) or {}
    layer = AnnotationLayer.from_dict(body)
    store.update_fields(a.id, {"annotation": layer.to_dict()})
    return jsonify(
        {
            "ok": True,
            "strokes": len(layer.strokes),
            "annotated_url": url_for("api_asset_annotated", asset_id=a.id),
        }
    )


def api_asset_annotated(asset_id: str):
    """Serve the asset composited with its annotation overlay (PNG)."""
    from flask import Response

    from mediahub.elements import draw as _draw
    from mediahub.media_library import photo_edit as _pe

    a, _store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    layer = _draw.AnnotationLayer.from_dict(getattr(a, "annotation", None) or {})
    try:
        from PIL import Image

        base_path = _pe.effective_image_path(a)
        with Image.open(base_path) as im:
            im.load()
            if layer.is_empty():
                out = im.convert("RGBA")
            else:
                role_vars = W._elements_role_vars(a.profile_id)
                out = _draw.render_onto_image(layer, im, role_vars)
            import io as _io

            buf = _io.BytesIO()
            out.convert("RGBA").save(buf, format="PNG")
            return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": f"render_failed: {e}"}), 500


def api_make_sticker(asset_id: str):
    """Promote a cutout (or any library image) into an org-custom sticker."""
    from flask import request as _req
    from mediahub.elements import stickers as _stickers
    from mediahub.media_library import photo_edit as _pe

    a, _store, err = W._photo_editor_asset(asset_id)
    if err:
        return err
    if not a.profile_id:
        return jsonify({"error": "no_profile"}), 400
    body = _req.get_json(silent=True) or {}
    name = str(body.get("name") or a.description_raw or "Club sticker").strip()
    # Prefer the cut-out (transparent) image for a clean sticker; else edited/original.
    from pathlib import Path as _Path

    src = a.cutout_path if a.cutout_path and _Path(a.cutout_path).is_file() else None
    src = src or str(_pe.effective_image_path(a))
    element = _stickers.promote_image_to_sticker(
        profile_id=a.profile_id, image_path=_Path(src), name=name
    )
    if element is None:
        return jsonify({"error": "sticker_failed"}), 500
    return jsonify({"ok": True, "element": {"id": element.id, "name": element.name}})


def api_media_library_list_json():
    """Return media assets for the active profile as JSON.

    Used by the content-creator tools to render an in-form picker
    without re-uploading. Strictly profile-scoped: only the
    session's active organisation's assets are returned.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable", "assets": []}), 503
    from flask import request as _req

    requested_pid = (_req.args.get("profile_id") or "").strip()
    active_pid = W._active_profile_id() or ""
    profile_id = requested_pid or active_pid
    if not profile_id:
        return jsonify({"profile_id": "", "assets": []})
    if requested_pid and requested_pid != active_pid and not requested_pid.startswith("_run_"):
        return jsonify({"error": "forbidden", "assets": []}), 403
    store = W._v8_get_media_store()
    assets_out = []
    for a in store.list(profile_id=profile_id, limit=200):
        ad = a.to_dict() if hasattr(a, "to_dict") else dict(a)
        assets_out.append(
            {
                "id": ad.get("id", ""),
                "filename": ad.get("filename", ""),
                "type": ad.get("type", ""),
                "linked_athlete_names": ad.get("linked_athlete_names") or [],
                "linked_venue": ad.get("linked_venue") or "",
                "linked_event": ad.get("linked_event") or "",
                "permission_status": ad.get("permission_status", ""),
                "approval_status": ad.get("approval_status", ""),
                "file_url": url_for("api_media_library_file", asset_id=ad.get("id", "")),
            }
        )
    return jsonify({"profile_id": profile_id, "assets": assets_out})


def api_media_library_quick_action(asset_id: str):
    """Run a one-click quick action on a library asset; stream the result.

    Image actions (convert/resize/crop) run anywhere; video/GIF actions need
    FFmpeg and honest-error (503) when it isn't installed. The result is a
    download — a quick action makes you a file, it never posts anything.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return jsonify({"error": "not_found"}), 404
    if not W._session_can_access_profile(a.profile_id):
        return jsonify({"error": "forbidden"}), 403
    src = Path(a.path)
    if not src.is_file():
        return jsonify({"error": "asset_file_missing"}), 404

    body = request.get_json(silent=True) or {}
    action = str(body.get("action") or "").strip().lower()
    from mediahub import export_engine as ee
    from mediahub.export_engine import quick_actions as qa
    from mediahub.export_engine.options import ExportOptions

    # Non-dict options is malformed client JSON — fall back to defaults
    # rather than 500ing inside from_dict.
    raw_opts = body.get("options") or {}
    opts = ExportOptions.from_dict(raw_opts if isinstance(raw_opts, dict) else {})
    cat = ee.source_category(src)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", src.stem)[:50] or "asset"

    def _out(suffix: str) -> Path:
        return W._export_quick_dir() / f"{stem}-{action}-{W.uuid.uuid4().hex[:8]}{suffix}"

    try:
        if action == "convert":
            fmt = ee.normalise_key(str(body.get("format") or "png"))
            out = _out(ee.suffix_for(fmt))
            qa.convert_image(src, out, fmt=fmt, options=opts)
        elif action == "resize" and cat == "image":
            out = _out(src.suffix or ".png")
            qa.resize_image(
                src,
                out,
                width=int(body.get("width", 0) or 0),
                height=int(body.get("height", 0) or 0),
                scale=float(body.get("scale", 0) or 0),
            )
        elif action == "crop" and cat == "image":
            out = _out(src.suffix or ".png")
            qa.crop_image(
                src,
                out,
                x=float(body.get("x", 0) or 0),
                y=float(body.get("y", 0) or 0),
                w=float(body.get("w", 1) or 1),
                h=float(body.get("h", 1) or 1),
            )
        elif action == "to_pdf" and cat == "image":
            out = _out(".pdf")
            qa.images_to_pdf([src], out)
        elif action == "crop" and cat == "video":
            out = _out(".mp4")
            qa.video_crop(
                src,
                out,
                x=int(body.get("x", 0) or 0),
                y=int(body.get("y", 0) or 0),
                width=int(body.get("width", 0) or 0),
                height=int(body.get("height", 0) or 0),
            )
        elif action == "resize" and cat == "video":
            out = _out(".mp4")
            qa.video_resize(
                src,
                out,
                width=int(body.get("width", 0) or 0),
                height=int(body.get("height", 0) or 0),
                keep_aspect=bool(body.get("keep_aspect", True)),
            )
        elif action == "to_gif" and cat == "video":
            out = _out(".gif")
            qa.video_to_gif(
                src,
                out,
                fps=int(body.get("fps", 12) or 12),
                width=int(body.get("width", 480) or 480),
            )
        elif action in ("to_mp4", "to_webm") and cat == "gif":
            fmt = "mp4" if action == "to_mp4" else "webm"
            out = _out(f".{fmt}")
            qa.gif_to_video(src, out, fmt=fmt)
        elif action == "trim" and cat == "video":
            out = _out(".mp4")
            qa.video_trim(src, out, start=float(body.get("start", 0) or 0), end=body.get("end"))
        elif action == "reverse" and cat == "video":
            out = _out(".mp4")
            qa.video_reverse(src, out, mute=bool(body.get("mute", False)))
        elif action == "mute" and cat == "video":
            out = _out(".mp4")
            qa.video_mute(src, out)
        elif action == "speed" and cat == "video":
            out = _out(".mp4")
            qa.video_speed(
                src,
                out,
                factor=float(body.get("factor", 1.0) or 1.0),
                mute=bool(body.get("mute", False)),
            )
        else:
            return jsonify(
                {"error": "bad_action", "message": f"'{action}' not valid for a {cat} asset"}
            ), 400
    except (ee.ExportUnavailable,) as exc:
        return jsonify({"error": "engine_unavailable", "message": str(exc)}), 503
    except Exception as exc:  # noqa: BLE001 - any op failure is a clean 4xx/5xx
        from mediahub.export_engine.images import ImageConvertError

        code = 503 if "FFmpeg" in str(exc) else 400
        if isinstance(exc, (ImageConvertError, ValueError)):
            code = 400
        return jsonify({"error": "quick_action_failed", "message": str(exc)}), code

    if not out.is_file() or out.stat().st_size == 0:
        return jsonify({"error": "no_output"}), 500
    return send_file(str(out), as_attachment=True, download_name=out.name)


def register(app) -> None:
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule(
        "/api/media-library",
        endpoint="api_media_library_upload",
        view_func=api_media_library_upload,
        methods=["POST"],
    )
    app.add_url_rule(
        "/share-target",
        endpoint="share_target_receiver",
        view_func=share_target_receiver,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/describe-job",
        endpoint="api_media_library_describe_job",
        view_func=api_media_library_describe_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/file/<asset_id>",
        endpoint="api_media_library_file",
        view_func=api_media_library_file,
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/delete",
        endpoint="api_media_library_delete",
        view_func=api_media_library_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/imagine/info", endpoint="api_imagine_info", view_func=api_imagine_info
    )
    app.add_url_rule(
        "/api/media-library/imagine/generate",
        endpoint="api_imagine_generate",
        view_func=api_imagine_generate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/imagine/subject-lift",
        endpoint="api_imagine_subject_lift",
        view_func=api_imagine_subject_lift,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/imagine/<op>",
        endpoint="api_imagine_asset_op",
        view_func=api_imagine_asset_op,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/imagine/grab-text",
        endpoint="api_imagine_grab_text",
        view_func=api_imagine_grab_text,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/mockup-templates",
        endpoint="api_mockup_templates",
        view_func=api_mockup_templates,
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/mockup/<template>",
        endpoint="api_media_library_mockup",
        view_func=api_media_library_mockup,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/media-library/bulk-delete",
        endpoint="api_media_library_bulk_delete",
        view_func=api_media_library_bulk_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/bulk-approve",
        endpoint="api_media_library_bulk_approve",
        view_func=api_media_library_bulk_approve,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/bulk-unapprove",
        endpoint="api_media_library_bulk_unapprove",
        view_func=api_media_library_bulk_unapprove,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/meta",
        endpoint="api_media_library_meta",
        view_func=api_media_library_meta,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/permission",
        endpoint="api_media_library_permission",
        view_func=api_media_library_permission,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/bulk-export",
        endpoint="api_media_library_bulk_export",
        view_func=api_media_library_bulk_export,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/cutout/<asset_id>",
        endpoint="api_media_library_cutout",
        view_func=api_media_library_cutout,
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/edit/preview",
        endpoint="api_photo_edit_preview",
        view_func=api_photo_edit_preview,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/edit/apply",
        endpoint="api_photo_edit_apply",
        view_func=api_photo_edit_apply,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/edit/enhance",
        endpoint="api_photo_edit_enhance",
        view_func=api_photo_edit_enhance,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/edit/reset",
        endpoint="api_photo_edit_reset",
        view_func=api_photo_edit_reset,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/edited",
        endpoint="api_media_library_edited",
        view_func=api_media_library_edited,
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/profile-picture",
        endpoint="api_photo_profile_picture",
        view_func=api_photo_profile_picture,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/collage",
        endpoint="api_media_library_collage",
        view_func=api_media_library_collage,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/import-stock",
        endpoint="api_import_stock",
        view_func=api_import_stock,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/annotate",
        endpoint="api_annotate_asset",
        view_func=api_annotate_asset,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/annotated",
        endpoint="api_asset_annotated",
        view_func=api_asset_annotated,
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/make-sticker",
        endpoint="api_make_sticker",
        view_func=api_make_sticker,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/media-library/list.json",
        endpoint="api_media_library_list_json",
        view_func=api_media_library_list_json,
    )
    app.add_url_rule(
        "/api/media-library/<asset_id>/quick-action",
        endpoint="api_media_library_quick_action",
        view_func=api_media_library_quick_action,
        methods=["POST"],
    )
