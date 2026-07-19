"""Organisation pages: setup, editing, members, athletes, invites.

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
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

from mediahub.web import web as W


def org_consent_page():
    # G-9: the consent registry now lives on /athletes as the "Consent
    # records" tab, beside the roster permissions it underpins. This
    # endpoint (and its 404-without-an-organisation gate) is kept so old
    # links, bookmarks and url_for callers still resolve — signed-in
    # officers land on the new tab.
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return W._layout(
            "Consent",
            '<div class="card"><p class="tag bad">Set up your organisation first.</p></div>',
            active="settings",
        ), 404
    return redirect(url_for("athletes_page", tab="records"))


def org_consent_settings():
    pid = W._active_profile_id() or ""
    profile = W.load_profile(pid) if pid else None
    if profile is None:
        return jsonify({"error": "no active organisation"}), 404
    basis_values = ("", "consent", "legitimate_interests", "other")
    pub = request.form.get("lawful_basis_publication") or ""
    enr = request.form.get("lawful_basis_enrichment") or ""
    mode = request.form.get("consent_mode") or ""
    if pub in basis_values:
        profile.lawful_basis_publication = pub
    if enr in basis_values:
        profile.lawful_basis_enrichment = enr
    if mode in ("", "opt_out", "opt_in"):
        profile.consent_mode = mode
    # HTML checkbox truthiness — the form value is "on" or absent, never a
    # NaN literal; bool() is the intended presence test. (pre-existing web.py
    # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    profile.consent_require_parental_for_minors = bool(request.form.get("parental_minors"))
    # HTML checkbox truthiness — the form value is "on" or absent, never a
    # NaN literal; bool() is the intended presence test. (pre-existing web.py
    # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    profile.pb_enrichment_enabled = bool(request.form.get("pb_enrichment_enabled"))
    profile.lawful_basis_notes = (request.form.get("lawful_basis_notes") or "").strip()[:500]
    W.save_profile(profile)
    return redirect(url_for("athletes_page", tab="records"))


def org_child_policy_settings():
    pid = W._active_profile_id() or ""
    profile = W.load_profile(pid) if pid else None
    if profile is None:
        return jsonify({"error": "no active organisation"}), 404
    # HTML checkbox truthiness — the form value is "on" or absent, never a
    # NaN literal; bool() is the intended presence test. (pre-existing web.py
    # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    profile.child_surname_initial = bool(request.form.get("child_surname_initial"))
    # HTML checkbox truthiness — the form value is "on" or absent, never a
    # NaN literal; bool() is the intended presence test. (pre-existing web.py
    # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    profile.child_suppress_age = bool(request.form.get("child_suppress_age"))
    # HTML checkbox truthiness — the form value is "on" or absent, never a
    # NaN literal; bool() is the intended presence test. (pre-existing web.py
    # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    profile.child_exclude_photos = bool(request.form.get("child_exclude_photos"))
    W.save_profile(profile)
    return redirect(url_for("athletes_page", tab="records"))


def org_retention_settings():
    pid = W._active_profile_id() or ""
    profile = W.load_profile(pid) if pid else None
    if profile is None:
        return jsonify({"error": "no active organisation"}), 404
    overrides = dict(profile.retention_overrides or {})
    for cls in ("raw_uploads", "runs"):
        raw = (request.form.get(cls) or "").strip()
        if raw == "":
            overrides.pop(cls, None)
            continue
        try:
            overrides[cls] = max(0, int(raw))
        except ValueError:
            continue
    profile.retention_overrides = overrides
    W.save_profile(profile)
    return redirect(url_for("athletes_page", tab="records"))


def org_consent_record():
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return jsonify({"error": "no active organisation"}), 404
    from mediahub.compliance.consent import ConsentRegistry

    status = request.form.get("status") or ""
    name = (request.form.get("athlete_name") or "").strip()
    if status not in ("granted", "refused", "revoked") or not name:
        return W._layout(
            "Consent",
            '<div class="card"><p class="tag bad">Athlete name and a valid decision are required.</p></div>',
            active="settings",
        ), 400
    recorded_by = ""
    try:
        recorded_by = W._auth.current_user_email() or ""
    except Exception:
        pass
    ConsentRegistry(pid).record(
        athlete_name=name,
        status=status,
        parental=bool(request.form.get("parental")),
        under_18=True if request.form.get("under_18") else None,
        restricted=bool(request.form.get("restricted")),
        note=request.form.get("note") or "",
        recorded_by=recorded_by,
    )
    return redirect(url_for("athletes_page", tab="records"))


def org_athlete_rights():
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return W._layout(
            "Athlete rights",
            '<div class="card"><p class="tag bad">Set up your organisation first.</p></div>',
            active="settings",
        ), 404

    from mediahub.compliance.dsr import DsrRequestLog

    _now = datetime.now(timezone.utc)

    def _due_cell(r) -> tuple:
        """D-9: render the statutory due date with an OVERDUE badge / a
        'due in N days' countdown so a busy officer can't silently blow the
        one-month deadline. Only OPEN requests count down (clock_stopped is
        paused; completed is done). Returns (is_overdue, cell_html)."""
        base = W._h(r.due_at[:10])
        if r.status != "open":
            return False, base
        try:
            due = datetime.fromisoformat(r.due_at)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
        except Exception:
            return False, base
        if due < _now:
            days_late = (_now - due).days
            return True, (
                f'{base} <span class="tag bad">OVERDUE</span>'
                f'<span class="muted" style="font-size:11px"> {days_late}d late</span>'
            )
        days_left = (due - _now).days
        hint = "due today" if days_left == 0 else f"due in {days_left}d"
        _warn = ' style="color:var(--warn)"' if days_left <= 5 else ""
        return (
            False,
            f'{base} <span class="muted" style="font-size:11px"{_warn}>({hint})</span>',
        )

    rows = []
    for r in DsrRequestLog().all(profile_id=pid):
        _is_overdue, _due_html = _due_cell(r)
        status_tag = {
            "open": (
                '<span class="tag bad">OVERDUE</span>'
                if _is_overdue
                else '<span class="tag">open</span>'
            ),
            "clock_stopped": '<span class="tag bad">clock stopped</span>',
            "completed": '<span class="tag ok">completed</span>',
        }.get(r.status, W._h(r.status))
        actions = []
        if r.status != "completed":
            if r.request_type == "access":
                actions.append(
                    f'<form method="post" action="{url_for("org_dsr_action", request_id=r.id)}" style="display:inline">'
                    '<button class="btn secondary" type="submit">Run export</button></form>'
                )
            elif r.request_type == "erasure":
                actions.append(
                    f'<form method="post" action="{url_for("org_dsr_action", request_id=r.id)}" style="display:inline" '
                    "onsubmit=\"return confirm('Erase this athlete from every store? This cannot be undone.')\">"
                    '<button class="btn secondary" type="submit">Run erasure</button></form>'
                )
            elif r.request_type == "restriction":
                actions.append(
                    f'<form method="post" action="{url_for("org_dsr_action", request_id=r.id)}" style="display:inline">'
                    '<button class="btn secondary" type="submit">Apply restriction</button></form>'
                )
            elif r.request_type == "rectification":
                actions.append(
                    f'<form method="post" action="{url_for("org_dsr_action", request_id=r.id)}" style="display:inline">'
                    '<input type="text" name="new_name" placeholder="corrected name" maxlength="200" required>'
                    '<button class="btn secondary" type="submit">Apply</button></form>'
                )
            if r.status == "open":
                actions.append(
                    f'<form method="post" action="{url_for("org_dsr_clock", request_id=r.id)}" style="display:inline">'
                    '<input type="hidden" name="op" value="stop">'
                    '<button class="btn secondary" type="submit" title="Pause the response clock while you wait for clarification or ID">Stop clock</button></form>'
                )
            else:
                actions.append(
                    f'<form method="post" action="{url_for("org_dsr_clock", request_id=r.id)}" style="display:inline">'
                    '<input type="hidden" name="op" value="resume">'
                    '<button class="btn secondary" type="submit">Resume clock</button></form>'
                )
        # D-21 — a completed access request keeps a working download link to
        # its generated SAR export (any status, as long as the snapshot exists).
        if r.request_type == "access" and W._dsr_export_path(pid, r.id).exists():
            actions.append(
                f'<a class="btn secondary" href="{url_for("org_dsr_export_download", request_id=r.id)}" '
                "download>Download export</a>"
            )
        rows.append(
            (
                _is_overdue,
                f"<tr><td><code>{W._h(r.id)}</code></td><td>{W._h(r.request_type)}</td>"
                f"<td>{W._h(r.athlete_name)}</td><td>{W._h(r.received_at[:10])}</td>"
                f"<td>{_due_html}</td><td>{status_tag}</td>"
                f"<td>{''.join(actions) or '—'}</td></tr>",
            )
        )
    # D-9: float overdue requests to the top so a late one can't hide at the
    # bottom of a long list; preserve original order within each group.
    rows.sort(key=lambda t: not t[0])
    _rows_html = "".join(h for _, h in rows)
    table = (
        # I-3: scroll wrapper so the 7-column rights table (with inline action
        # forms) doesn't overflow a phone.
        '<div class="mh-table-scroll"><table><thead><tr><th>Ref</th><th>Type</th><th>Athlete</th><th>Received</th>'
        "<th>Due</th><th>Status</th><th>Actions</th></tr></thead><tbody>"
        + (_rows_html or '<tr><td colspan="7" class="muted">No requests logged.</td></tr>')
        + "</tbody></table></div>"
    )
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Privacy &amp; data</span>
  <h1>Athlete <em class="editorial">rights.</em></h1>
  <p class="lede">When an athlete or parent asks to see, fix, restrict or erase their data, log it here — the deadline (and any time you spend waiting on them for ID) is tracked for you, and the actions reach every store on this deployment.</p>
</section>
<div class="card">
  <h2>Log a request</h2>
  <form method="post" action="{url_for("org_dsr_open")}">
    <label>Athlete name<br><input type="text" name="athlete_name" maxlength="200" required></label><br>
    <label>What did they ask for?<br>
      <select name="request_type">
        <option value="access" title="Subject access request (SAR) — UK GDPR Art 15">See everything we hold about them</option>
        <option value="rectification" title="UK GDPR Art 16 — rectification">Correct their name</option>
        <option value="erasure" title="UK GDPR Art 17 — erasure / right to be forgotten">Delete them everywhere</option>
        <option value="restriction" title="UK GDPR Art 18 — restriction">Pause all use of their data</option>
      </select>
    </label>
    <small class="muted" style="display:block;margin:-4px 0 10px">These are the UK GDPR rights (access, rectification, erasure, restriction) — you don't need to know the article numbers.</small>
    <label>Note<br><input type="text" name="note" maxlength="1000"></label><br>
    <button class="btn" type="submit">Log request</button>
  </form>
</div>
<div class="card"><h2>Requests</h2>{table}
<p class="muted">"Run export" downloads a machine-readable JSON of everything held about the athlete. "Run erasure" removes them from runs, rendered cards, caches, the media library and caption memory, keeps a suppression record so they can't reappear, and reports anything it could not reach — honestly.</p></div>
"""
    return W._layout("Athlete rights", body, active="settings")


def org_dsr_open():
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return jsonify({"error": "no active organisation"}), 404
    from mediahub.compliance.dsr import DsrRequestLog

    name = (request.form.get("athlete_name") or "").strip()
    rtype = request.form.get("request_type") or ""
    if not name or rtype not in ("access", "rectification", "erasure", "restriction"):
        return W._layout(
            "Athlete rights",
            '<div class="card"><p class="tag bad">Athlete name and a valid request type are required.</p></div>',
            active="settings",
        ), 400
    DsrRequestLog().open(
        profile_id=pid,
        athlete_name=name,
        request_type=rtype,
        note=request.form.get("note") or "",
    )
    return redirect(url_for("org_athlete_rights"))


def org_dsr_action(request_id):
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return jsonify({"error": "no active organisation"}), 404
    from mediahub.compliance import dsr as _dsr
    from mediahub.compliance.consent import ConsentRegistry

    log_store = _dsr.DsrRequestLog()
    req = log_store.get(request_id)
    if req is None or req.profile_id != pid:
        return jsonify({"error": "request not found"}), 404
    recorded_by = ""
    try:
        recorded_by = W._auth.current_user_email() or ""
    except Exception:
        pass
    if req.request_type == "access":
        # finding #111 — confine a signed-in regular tenant to its own runs;
        # ownerless (legacy) runs may belong to another club (ADR-0014 §5).
        export = _dsr.export_athlete(
            pid, req.athlete_name, include_ownerless=W._ownerless_run_readable()
        )
        # D-21 — persist the snapshot and redirect back with a confirmation,
        # so the request visibly flips to "completed" and the clock stops,
        # instead of a bare attachment that left the table looking un-actioned.
        export_path = W._dsr_export_path(pid, request_id)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(export, indent=2), encoding="utf-8")
        log_store.complete(request_id, note="export generated")
        from mediahub.compliance.security_log import record_event

        record_event("dsr_export", profile_id=pid, subject=req.athlete_name, actor=recorded_by)
        W._flash_toast(
            "Export ready — request marked complete and the clock stopped. "
            "Download it from the Actions column.",
            "success",
        )
        return redirect(url_for("org_athlete_rights"))
    if req.request_type == "erasure":
        report = _dsr.erase_athlete(
            pid,
            req.athlete_name,
            recorded_by=recorded_by,
            include_ownerless=W._ownerless_run_readable(),
        )
        log_store.complete(request_id, note="erasure executed")
        from mediahub.compliance.security_log import record_event

        record_event("dsr_erasure", profile_id=pid, subject=req.athlete_name, actor=recorded_by)
        import urllib.parse as _up  # noqa: PLC0415

        report_json = json.dumps(report, indent=2)
        report_href = "data:application/json;charset=utf-8," + _up.quote(report_json)
        body = (
            '<div class="card"><h2>What was removed</h2>'
            f"<p class='muted'>Erasure completed for <strong>{W._h(req.athlete_name)}</strong>.</p>"
            # Pass the cascade so the compliant Art-17 summary counts the
            # cascade-only figures (research-cache, result rows, …) instead of
            # showing 0 — same numbers as the /privacy quick-erase sibling.
            + W._erasure_removed_html(report, report.get("cascade"))
            + "<p class='muted'>Remaining mentions inside multi-athlete captions were "
            "redacted. Content already published to social platforms must be deleted "
            "there too.</p>"
            f'<p><a class="btn secondary" href="{report_href}" '
            f'download="erasure-{W._h(request_id)}.json">Download technical report (JSON)</a> '
            f'<a class="btn" href="{url_for("org_athlete_rights")}">Back to athlete rights</a></p>'
            "</div>"
        )
        return W._layout("Erasure report", body, active="settings")
    if req.request_type == "restriction":
        ConsentRegistry(pid).set_restricted(req.athlete_name, True, recorded_by=recorded_by)
        log_store.complete(request_id, note="restriction applied")
        return redirect(url_for("org_athlete_rights"))
    if req.request_type == "rectification":
        new_name = (request.form.get("new_name") or "").strip()
        if not new_name:
            return jsonify({"error": "corrected name required"}), 400
        _dsr.rectify_athlete_name(
            pid, req.athlete_name, new_name, include_ownerless=W._ownerless_run_readable()
        )
        log_store.complete(request_id, note=f"rectified to '{new_name}'")
        return redirect(url_for("org_athlete_rights"))
    return jsonify({"error": "unknown request type"}), 400


def org_dsr_export_download(request_id):
    """D-21 — serve the persisted SAR export snapshot for a completed access
    request (tenant-scoped), so "Run export" can redirect + confirm and the
    officer still gets the file on demand."""
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return jsonify({"error": "no active organisation"}), 404
    from mediahub.compliance import dsr as _dsr

    req = _dsr.DsrRequestLog().get(request_id)
    if req is None or req.profile_id != pid:
        return jsonify({"error": "request not found"}), 404
    path = W._dsr_export_path(pid, request_id)
    if not path.exists():
        return jsonify({"error": "export not generated"}), 404
    resp = current_app.response_class(path.read_text(encoding="utf-8"), mimetype="application/json")
    resp.headers["Content-Disposition"] = f"attachment; filename=sar-{W._h(request_id)}.json"
    return resp


def org_dsr_clock(request_id):
    pid = W._active_profile_id() or ""
    if not pid or W.load_profile(pid) is None:
        return jsonify({"error": "no active organisation"}), 404
    from mediahub.compliance.dsr import DsrRequestLog

    log_store = DsrRequestLog()
    req = log_store.get(request_id)
    if req is None or req.profile_id != pid:
        return jsonify({"error": "request not found"}), 404
    if request.form.get("op") == "stop":
        log_store.stop_clock(request_id)
    else:
        log_store.resume_clock(request_id)
    return redirect(url_for("org_athlete_rights"))


def organisation_page():
    _ORG_TYPES = [
        ("other", "Other / general"),
        ("swimming_club", "Swimming club"),
        ("athletics", "Athletics club"),
        ("football", "Football / rugby / team sport"),
        ("university_society", "University society or sports club"),
        ("corporate_team", "Corporate team"),
    ]
    _PLATFORMS = W._ORG_PLATFORMS
    _TONES = [
        (
            "warm-club",
            "Warm &amp; community &mdash; conversational, member-facing, first-name use",
        ),
        (
            "hype",
            "Energetic &amp; hype &mdash; race-day language, exclamation marks, high energy",
        ),
        ("data-led", "Data-led &mdash; numbers-first, precise, sponsor-friendly"),
    ]

    saved_msg = ""
    capture_preview = ""  # rendered preview HTML when a capture has just run
    capture_error = ""  # rendered error banner when capture failed
    voice_error = ""  # rendered error banner when voice analysis failed
    # D-15: the analyse actions persist their results immediately on
    # success; the values they overwrite are stashed in the session as a
    # one-shot undo behind the "Discard this analysis" button. Failures
    # surface an honest error and persist nothing.
    if request.method == "POST":
        action = (request.form.get("action") or "save").strip().lower()
        raw_id = (request.form.get("profile_id") or "default").strip().lower()
        profile_id = re.sub(r"[^a-z0-9_-]", "-", raw_id).strip("-") or "default"
        _prior_profile = W.load_profile(profile_id)
        _is_new_profile = _prior_profile is None
        if _prior_profile is not None and not W._session_can_use_profile(profile_id):
            # PC.3: a bound org is editable by its members (or the
            # operator) only, and answers like a nonexistent one.
            abort(404)
        existing = _prior_profile or W.ClubProfile(
            profile_id=profile_id,
            display_name=request.form.get("display_name") or profile_id,
            # Children's Code standard 7 (high privacy by default): NEW
            # organisations start with the child content controls ON; the
            # club can relax them deliberately on the Consent records tab
            # of /athletes (G-9).
            child_surname_initial=True,
            child_suppress_age=True,
            child_exclude_photos=False,
        )

        def _persist_profile(prof: W.ClubProfile) -> None:
            """Write the profile and run the PC.3 tenancy tail — shared
            by Save and the analyse actions (D-15): a newly created
            workspace is born bound to its creator (ADR-0014), and the
            session pins the org either way."""
            W.save_profile(prof)
            if _is_new_profile:
                W._bind_creator_if_signed_in(prof.profile_id)
            W._pin_active_profile(prof.profile_id)

        if action == "capture":
            # ---- Brand DNA capture from website URL ----
            target_url = (request.form.get("brand_source_url") or "").strip()
            if not target_url:
                capture_error = (
                    '<p class="tag bad" style="margin-bottom:20px">'
                    "Enter a website URL to analyse.</p>"
                )
                profile = existing
            else:
                try:
                    from mediahub.brand.dna_capture import capture_brand_dna

                    result = capture_brand_dna(target_url, force=False)
                except Exception as e:
                    result = {"brand_capture_status": f"error: {e}"}
                status = (result or {}).get("brand_capture_status", "")
                if status in ("ok", "no_provider", "ok_heuristic"):
                    # D-15: a successful capture persists immediately
                    # (like the setup wizard) — 10-30s of analysis no
                    # longer evaporates unless the user scrolls down and
                    # clicks Save. The values it overwrites ride the
                    # session as a one-shot Discard undo.
                    _capture_fields = (
                        "brand_voice_summary",
                        "brand_keywords",
                        "brand_palette_extracted",
                        "brand_logo_url",
                        "brand_typography_hint",
                        "brand_phrases_to_avoid",
                        "brand_phrases_to_use",
                        "brand_source_url",
                        "brand_captured_at",
                        "brand_capture_status",
                        "brand_palette_sources",
                        "brand_palette_reasoning",
                    )
                    W._org_analysis_stash_previous(
                        existing.profile_id,
                        "brand",
                        {
                            k: getattr(existing, k, None)
                            for k in (
                                *_capture_fields,
                                "brand_primary",
                                "brand_secondary",
                            )
                        },
                    )
                    for k in _capture_fields:
                        if k in result:
                            setattr(existing, k, result[k])
                    # Adopt extracted palette into primary/secondary if
                    # the existing profile is still on the default colours.
                    pal = result.get("brand_palette_extracted") or {}
                    if pal.get("primary") and existing.brand_primary in (
                        "",
                        "#0A2540",
                        "#A30D2D",
                    ):
                        existing.brand_primary = pal["primary"]
                    if pal.get("secondary") and existing.brand_secondary in (
                        "",
                        "#000000",
                    ):
                        existing.brand_secondary = pal["secondary"]
                    _persist_profile(existing)
                    note = (
                        "Captured from website and saved to your organisation "
                        "— Discard beside the preview restores the previous "
                        "values."
                        if status == "ok"
                        else "Captured from website and saved (palette and "
                        "logo only; AI provider not configured, so the voice "
                        "summary and keywords are empty)."
                    )
                    capture_preview = (
                        f'<p class="tag info" style="margin-bottom:20px">{W._h(note)}</p>'
                    )
                else:
                    # Surface the failure clearly but keep the form usable.
                    reason = {
                        "missing_url": "No URL was provided.",
                        "fetch_failed": "Could not reach that URL &mdash; check it loads in a browser.",
                    }.get(status, f"Capture failed ({W._h(status or 'unknown error')}).")
                    capture_error = (
                        f'<p class="tag bad" style="margin-bottom:20px">{W._h(reason)}</p>'
                    )
            profile = existing

        elif action == "capture_socials":
            # ---- Brand DNA capture from website + social links ----
            target_url = (request.form.get("brand_source_url") or "").strip()
            social_links: dict[str, str] = {}
            for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin"):
                v = (request.form.get(f"social_{key}") or "").strip()
                if v:
                    social_links[key] = v
            if not target_url and not social_links:
                capture_error = (
                    '<p class="tag bad" style="margin-bottom:20px">'
                    "Enter a website URL or at least one social link to analyse.</p>"
                )
                profile = existing
            else:
                try:
                    from mediahub.brand.social_dna import capture_from_socials

                    result = capture_from_socials(
                        social_links=social_links,
                        website_url=target_url,
                        force=False,
                    )
                except Exception as e:
                    result = {"brand_capture_status": f"error: {e}"}
                status = (result or {}).get("brand_capture_status", "")
                if status in ("ok", "ok_heuristic"):
                    # D-15: persist immediately on success, stashing the
                    # overwritten values for the one-shot Discard undo.
                    _capture_fields = (
                        "brand_voice_summary",
                        "brand_keywords",
                        "brand_palette_extracted",
                        "brand_logo_url",
                        "brand_typography_hint",
                        "brand_phrases_to_avoid",
                        "brand_phrases_to_use",
                        "brand_source_url",
                        "brand_captured_at",
                        "brand_capture_status",
                    )
                    W._org_analysis_stash_previous(
                        existing.profile_id,
                        "brand",
                        {
                            k: getattr(existing, k, None)
                            for k in (
                                *_capture_fields,
                                "voice_profile",
                                "social_links",
                                "brand_primary",
                                "brand_secondary",
                            )
                        },
                    )
                    for k in _capture_fields:
                        if k in result:
                            setattr(existing, k, result[k])
                    vp = result.get("voice_profile") or {}
                    if isinstance(vp, dict) and vp:
                        existing.voice_profile = vp
                    existing.social_links = social_links
                    pal = result.get("brand_palette_extracted") or {}
                    if pal.get("primary") and existing.brand_primary in (
                        "",
                        "#0A2540",
                        "#A30D2D",
                    ):
                        existing.brand_primary = pal["primary"]
                    if pal.get("secondary") and existing.brand_secondary in ("", "#000000"):
                        existing.brand_secondary = pal["secondary"]
                    _persist_profile(existing)
                    note = (
                        "Re-analysed from website + socials and saved to your "
                        "organisation — Discard beside the preview restores "
                        "the previous values."
                        if status == "ok"
                        else "Re-analysed and saved (no live signal from the sources we tried)."
                    )
                    capture_preview = (
                        f'<p class="tag info" style="margin-bottom:20px">{W._h(note)}</p>'
                    )
                else:
                    reason = {
                        "no_sources": "Add a website URL or at least one social link.",
                        "fetch_failed_all": (
                            "None of the links could be read &mdash; "
                            "they may be blocked or behind login. Try a "
                            "different combination or paste captions manually below."
                        ),
                    }.get(status, f"Capture failed ({W._h(status or 'unknown error')}).")
                    capture_error = (
                        f'<p class="tag bad" style="margin-bottom:20px">{W._h(reason)}</p>'
                    )
            profile = existing

        elif action == "analyse_voice":
            # SRV2-2 — pre-G-5 tabs posted analyse_voice as the ACTION
            # with only the voice fields in the form; letting it fall
            # through to the full save would clear every absent field.
            # The G-5 handler is gone for good — redirect, save nothing.
            W._flash_toast(
                "Voice analysis moved — use the Analyse voice button in the form below.",
                "info",
            )
            return redirect(url_for("organisation_page"))

        else:
            # ---- Save organisation ----
            existing.display_name = (
                request.form.get("display_name") or existing.display_name
            ).strip()
            existing.short_name = (request.form.get("short_name") or "").strip()
            existing.org_type = (request.form.get("org_type") or "other").strip()
            existing.governing_body = (request.form.get("governing_body") or "").strip()
            existing.country = (request.form.get("country") or "").strip()
            # W.13 (generalised): caption language — any web.languages
            # registry code ("en", "cy", "ga", "zh", …) or an English-led
            # bilingual pair ("en+cy", "en+hi", …). The registry
            # normaliser is the single validator: junk falls back to
            # "en", legacy "bilingual" becomes "en+cy".
            from mediahub.web.languages import (
                normalise_language_setting as _norm_lang,
            )

            existing.language = _norm_lang(request.form.get("language"))
            # W.4: which qualifying standards this club cares about
            existing.important_standards = [
                s.strip() for s in request.form.getlist("important_standards") if s.strip()
            ]
            codes_raw = request.form.get("club_codes") or ""
            existing.club_codes = [c.strip() for c in codes_raw.split(",") if c.strip()]
            _new_pri = (
                request.form.get("brand_primary") or existing.brand_primary or "#0A2540"
            ).strip()
            _new_sec = (
                request.form.get("brand_secondary") or existing.brand_secondary or "#000000"
            ).strip()
            # G-4: make the colour pickers actually take effect. The
            # rendered palette resolves brand_palette_manual/extracted
            # BEFORE the legacy brand_primary/secondary, so writing only
            # the legacy fields was a silent no-op for any club that went
            # through AI setup. Pin a *changed* colour into
            # brand_palette_manual (the winning slot); leave manual
            # untouched when the value equals the current effective palette
            # so an unedited save never locks an AI palette. Recompute the
            # derived theme only when something actually changed.
            from mediahub.brand.palette import effective_palette as _eff_save

            _hex_pat = re.compile(r"^#[0-9a-fA-F]{6}$")
            _eff_now = _eff_save(
                manual=getattr(existing, "brand_palette_manual", {}) or {},
                extracted=getattr(existing, "brand_palette_extracted", {}) or {},
            )
            _man = dict(getattr(existing, "brand_palette_manual", {}) or {})
            _palette_changed = False
            for _slot, _val, _eff_cur in (
                ("primary", _new_pri, (_eff_now.get("primary") or "")),
                ("secondary", _new_sec, (_eff_now.get("secondary") or "")),
            ):
                if _hex_pat.fullmatch(_val) and _val.lower() != _eff_cur.lower():
                    _man[_slot] = _val
                    _palette_changed = True
            if _palette_changed:
                existing.brand_palette_manual = _man
            existing.brand_primary = _new_pri
            existing.brand_secondary = _new_sec
            existing.tone = (request.form.get("tone") or "warm-club").strip()
            existing.caption_tone = existing.tone
            existing.platforms = [p.strip() for p in request.form.getlist("platforms") if p.strip()]
            existing.tone_notes = (request.form.get("tone_notes") or "").strip()
            raw_exemplars = (request.form.get("exemplar_captions") or "").strip()
            if raw_exemplars:
                parts = [p.strip() for p in raw_exemplars.split("---") if p.strip()]
                existing.exemplar_captions = parts[:5]
            else:
                existing.exemplar_captions = []
            existing.sponsor_name = (request.form.get("sponsor_name") or "").strip()
            existing.sponsor_guidelines = (request.form.get("sponsor_guidelines") or "").strip()

            # D-15: captured brand DNA persists the moment its analysis
            # succeeds, so the save form no longer carries it through
            # hidden inputs — the loaded profile already holds it and a
            # plain save leaves it untouched.
            from mediahub.brand.voice_imitation import (
                analyse_examples as _analyse_voice,
                redact_pii as _redact_pii,
            )

            # Snapshot the voice fields BEFORE they are overwritten so a
            # successful analysis can stash them as the one-shot undo.
            _prev_voice = {
                "voice_examples": existing.voice_examples or [],
                "voice_profile": existing.voice_profile or {},
            }
            raw_voice_examples = (request.form.get("voice_examples") or "").strip()
            if raw_voice_examples:
                voice_lines = [
                    _redact_pii(line.strip())
                    for line in raw_voice_examples.splitlines()
                    if line.strip()
                ]
                existing.voice_examples = voice_lines[:20]
            else:
                existing.voice_examples = []
                existing.voice_profile = {}
            # Persist any social-link edits made on the full form.
            social_edits: dict[str, str] = {}
            for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin"):
                v = (request.form.get(f"social_{key}") or "").strip()
                if v:
                    social_edits[key] = v
            if social_edits or (request.form.get("social_links_edited") == "1"):
                existing.social_links = social_edits
            # D-15: the analysis persists immediately on success; a
            # failed or unusable analysis is an honest error and this
            # request persists NOTHING (no half-saved form, and never a
            # fabricated voice profile).
            _voice_problem = ""
            if request.form.get("analyse_voice"):
                if len(existing.voice_examples) < 2:
                    _voice_problem = "Paste at least 3 captions (one per line) to analyse voice."
                else:
                    try:
                        _new_vp = _analyse_voice(existing.voice_examples)
                    except Exception as exc:
                        _voice_problem = f"Voice analysis failed: {exc}."
                    else:
                        existing.voice_profile = _new_vp
                        W._org_analysis_stash_previous(existing.profile_id, "voice", _prev_voice)
                        saved_msg = (
                            '<p class="tag good" style="margin-bottom:20px">'
                            "Voice profile analysed and saved.</p>"
                        )
            else:
                saved_msg = '<p class="tag good" style="margin-bottom:20px">Organisation saved.</p>'
            if _voice_problem:
                voice_error = (
                    f'<p class="tag bad" style="margin-bottom:20px">'
                    f"{W._h(_voice_problem)} Nothing was saved.</p>"
                )
            else:
                # Re-derive the AI operating profile whenever the user
                # edits the org. Single LLM call; consumers cache-read.
                try:
                    from mediahub.brand.derived import derive_operating_profile

                    existing.brand_operating_profile = derive_operating_profile(existing)
                except Exception:
                    existing.brand_operating_profile = {
                        "tone_prose": {},
                        "achievement_priorities": {},
                        "type_phrases": {},
                        "artefact_voice": {},
                        "status": "error",
                    }
                # G-4: if the brand colours actually changed, force-recompute
                # the derived theme so the chrome + still/motion renderers pick
                # up the new primary (mirrors the palette-reorder handler).
                if _palette_changed:
                    try:
                        _kit = existing.get_brand_kit()
                        _kit.ensure_derived_palette(force=True)
                        existing.brand_kit = _kit.to_dict()
                    except Exception as e:
                        W.log.warning("organisation save: derived palette recompute failed: %s", e)
                _persist_profile(existing)
            profile = existing
    else:
        # GET: prefer the session-pinned profile; fall back to the
        # most-recent on disk, then to a blank one for the empty state.
        pid_pin = W._active_profile_id()
        profile = W.load_profile(pid_pin) if pid_pin else None
        if profile is None:
            # PC.3: never pre-fill the form from a workspace this
            # session couldn't enter — bound orgs' data must not leak
            # into a foreign/anonymous editor view (ADR-0014).
            profiles = [p for p in W.list_profiles() if W._session_can_use_profile(p.profile_id)]
            profile = (
                profiles[0] if profiles else W.ClubProfile(profile_id="default", display_name="")
            )

    # Build select/checkbox HTML helpers
    def _opt(val, label, selected):
        sel = " selected" if selected else ""
        return f'<option value="{W._h(val)}"{sel}>{W._h(label)}</option>'

    def _radio(name, val, label, checked):
        chk = " checked" if checked else ""
        return (
            f'<label class="mh-choice mh-choice-block">'
            f'<input type="radio" name="{W._h(name)}" value="{W._h(val)}"{chk}>'
            f"<span>{label}</span></label>"
        )

    def _cb(name, val, label, checked):
        chk = " checked" if checked else ""
        return (
            f'<label class="mh-choice mh-choice-inline">'
            f'<input type="checkbox" name="{W._h(name)}" value="{W._h(val)}"{chk}>'
            f"<span>{W._h(label)}</span></label>"
        )

    org_type_opts = "".join(_opt(v, l, v == (profile.org_type or "other")) for v, l in _ORG_TYPES)
    tone_radios = "".join(
        _radio("tone", v, l, v == (profile.tone or "warm-club")) for v, l in _TONES
    )
    platform_cbs = "".join(
        _cb("platforms", v, l, v in (profile.platforms or [])) for v, l in _PLATFORMS
    )
    exemplars_text = "\n---\n".join(profile.exemplar_captions or [])
    voice_examples_text = "\n".join(profile.voice_examples or [])

    # W.13 (generalised): caption language picker — registry-driven
    # (web/languages.py: top-10 world languages + Welsh + Irish), each
    # available alone or bilingual beside English. Adding a language to
    # the registry surfaces it here with no further code change. Legacy
    # "bilingual" profiles normalise to "en+cy" so they preselect
    # correctly.
    from mediahub.web.languages import (
        bilingual_language_options as _bilingual_language_options,
        normalise_language_setting as _norm_lang_setting,
        single_language_options as _single_language_options,
    )

    _lang_now = _norm_lang_setting(getattr(profile, "language", "en"))
    _lang_singles = "".join(_opt(v, l, v == _lang_now) for v, l in _single_language_options())
    _lang_pairs = "".join(_opt(v, l, v == _lang_now) for v, l in _bilingual_language_options())
    language_opts = (
        f'<optgroup label="One language">{_lang_singles}</optgroup>'
        f'<optgroup label="Bilingual — English + a side-by-side translation">'
        f"{_lang_pairs}</optgroup>"
    )

    # W.4: qualifying-standards picker (season packs + quals registry)
    standards_cbs = ""
    try:
        from mediahub.standards import available_standards_summary as _stds_summary

        _picked = set(profile.important_standards or [])
        _rows = []
        for _s in _stds_summary():
            _label = (
                f"{_s['competition']} — {_s['body']}"
                f" ({_s['level']}, {_s['course']}, {_s['season']})"
            )
            _rows.append(_cb("important_standards", _s["id"], _label, _s["id"] in _picked))
        standards_cbs = "".join(_rows)
    except Exception:
        standards_cbs = ""
    if not standards_cbs:
        standards_cbs = (
            '<p class="muted" style="font-size:12px">No qualifying-time tables are '
            "loaded yet. The operator curates them each season — see "
            "<code>data/standards/README.md</code>.</p>"
        )

    # Empty constants — round-7 cleanup. The organisation form used to
    # apply its own inline input styles that overrode the global
    # `input[type=text]` rule, which is why /organisation looked
    # different from every other form on the system. Now we let the
    # globals do their job and just cap width via a style attribute on
    # the rare wide-form input.
    _input_style = "max-width:480px"
    _ta_style = "max-width:600px"

    # D-15: a just-persisted analysis can be undone — the previous values
    # ride the session as a one-shot stash, and the Discard button
    # renders beside whichever preview the stash belongs to.
    _stash_kind = str(W._org_analysis_stash_for(profile.profile_id).get("kind") or "")
    _discard_title = (
        "Restores the values from before this analysis. Best-effort undo "
        "held in your session — it survives one navigation, but not "
        "signing out or another analysis."
    )
    _discard_label = "Discard this analysis — restore previous"
    # CON2-2 — each Discard button posts its own kind, so a second tab's
    # newer analysis of the OTHER kind can never be restored by this one.
    brand_discard_html = ""
    if _stash_kind == "brand":
        brand_discard_html = (
            f'<form method="POST" action="{url_for("organisation_analysis_discard")}" '
            f'style="margin-top:12px">'
            f'<button type="submit" name="kind" value="brand" class="btn secondary" '
            f'title="{W._h(_discard_title)}">'
            f"{W._h(_discard_label)}</button></form>"
        )
    voice_discard_html = ""
    if _stash_kind == "voice":
        # Inside the main save form, so a nested <form> is illegal —
        # formaction routes this submit to the discard endpoint instead.
        voice_discard_html = (
            f'<button type="submit" formaction="{url_for("organisation_analysis_discard")}" '
            f'name="kind" value="voice" '
            f'class="btn secondary" style="margin-left:8px" title="{W._h(_discard_title)}">'
            f"{W._h(_discard_label)}</button>"
        )

    # ---- Brand DNA preview block (rendered when fields are populated) ----
    def _swatch(hexv: str) -> str:
        if not hexv:
            return ""
        return (
            f'<div title="{W._h(hexv)}" style="display:inline-flex;align-items:center;'
            f"gap:6px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;"
            f'margin-right:6px;margin-bottom:6px;background:var(--panel)">'
            f'<span style="display:inline-block;width:18px;height:18px;border-radius:4px;'
            f'background:{W._h(hexv)};border:1px solid rgba(255,255,255,0.15)"></span>'
            f'<code style="font-size:11px;color:var(--ink)">{W._h(hexv)}</code></div>'
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
            f"border:1px solid var(--border);border-radius:999px;font-size:11px;"
            f'color:{colour};background:rgba(255,255,255,0.02)">{W._h(text)}</span>'
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
        swatches = "".join(
            _swatch(pal.get(k, "")) for k in ("primary", "secondary", "accent") if pal.get(k)
        )
        keywords_html = "".join(_chip(k, "neutral") for k in (profile.brand_keywords or [])[:12])
        use_html = "".join(_chip(p, "good") for p in (profile.brand_phrases_to_use or [])[:5])
        avoid_html = "".join(_chip(p, "bad") for p in (profile.brand_phrases_to_avoid or [])[:5])
        logo_html = ""
        if profile.brand_logo_url:
            # The unified logo chip — KEYED silhouette (mirrored first-party,
            # never the raw cross-origin URL the CSP would block) on a
            # contrast-aware, brand-tinted backing, with an initials fallback.
            _extracted = profile.brand_palette_extracted or {}
            _dominant = (_extracted.get("primary") or "").strip() or (
                getattr(profile, "brand_primary", "") or ""
            ).strip()
            from mediahub.brand.logos import mirror_chip_tone as _mct

            _cap = (getattr(profile, "brand_logo_url", "") or "").strip()
            logo_html = W._logo_chip_html(
                url_for("organisation_logo_mirror", profile_id=profile.profile_id, bg=1, chip=1),
                alt="Detected logo",
                size="lg",
                tone=_mct(profile.profile_id, _cap),
                brand_hex=_dominant,
                initials=W._avatar_initials(profile.display_name),
            )
        captured_meta = ""
        if profile.brand_captured_at or profile.brand_source_url:
            src = profile.brand_source_url or ""
            ts = profile.brand_captured_at or ""
            status = profile.brand_capture_status or ""
            captured_meta = (
                f'<p style="font-size:11px;color:var(--ink-dim);margin-top:8px">'
                f'Source: <a href="{W._h(src)}" target="_blank" rel="noopener" '
                f'style="color:var(--ink-dim)">{W._h(src)}</a> &middot; '
                f"captured {W._h(ts)} &middot; status {W._h(status)}"
                f"</p>"
            )
        brand_preview_html = f"""
<div class="card" style="margin-bottom:20px;border:1px dashed var(--border);background:color-mix(in oklab, var(--lane) 3%, transparent)">
  <h3 style="margin-top:0;margin-bottom:12px;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Brand DNA preview</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Voice summary</div>
      <p style="margin:0;font-size:13px;color:var(--ink);line-height:1.5">{W._h(profile.brand_voice_summary or "(no summary yet)")}</p>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Palette</div>
      <div>{swatches or '<span class="dim" style="font-size:12px">(none detected)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Typography hint</div>
      <p style="margin:0;font-size:13px;color:var(--ink)">{W._h(profile.brand_typography_hint or "—")}</p>
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
  {brand_discard_html}
</div>
"""

    # ---- Voice profile preview block ----
    voice_profile_html = ""
    vp = profile.voice_profile or {}
    if vp:

        def _stat_row(label: str, val) -> str:
            return (
                f'<div style="display:flex;justify-content:space-between;'
                f'padding:4px 0;border-bottom:1px solid var(--border);font-size:13px">'
                f'<span style="color:var(--ink-dim)">{W._h(label)}</span>'
                f'<strong style="color:var(--ink)">{W._h(str(val))}</strong></div>'
            )

        openers_html = " ".join(
            _chip(o, "neutral") for o in (vp.get("characteristic_openers") or [])[:6]
        )
        closers_html = " ".join(
            _chip(c, "neutral") for c in (vp.get("characteristic_closers") or [])[:4]
        )
        forbidden_html = " ".join(_chip(f, "bad") for f in (vp.get("forbidden_phrases") or [])[:6])
        hashtags_html = " ".join(_chip(h, "neutral") for h in (vp.get("common_hashtags") or [])[:8])
        address = W._h(vp.get("preferred_swimmer_address") or "first_name")
        cap_style = W._h(vp.get("capitalisation_style") or "sentence")
        n_examples = len(profile.voice_examples or [])
        voice_profile_html = f"""
<div class="card" style="margin-bottom:20px;border:1px dashed var(--border);background:rgba(167,139,250,0.04)">
  <h3 style="margin-top:0;margin-bottom:12px;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Voice profile preview &middot; {n_examples} example{"s" if n_examples != 1 else ""}</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:8px">Style metrics</div>
      {_stat_row("Avg sentence length (words)", vp.get("sentence_length_avg", 0))}
      {_stat_row("Sentence length p90", vp.get("sentence_length_p90", 0))}
      {_stat_row("Avg emoji per caption", vp.get("emoji_rate_per_caption", 0))}
      {_stat_row("Avg hashtags per caption", vp.get("hashtag_count_avg", 0))}
      {_stat_row("Capitalisation style", cap_style)}
      {_stat_row("Swimmer address", address)}
    </div>
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Typical openers</div>
      <div style="margin-bottom:10px">{openers_html or '<span class="dim" style="font-size:12px">(none detected)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Typical closers</div>
      <div style="margin-bottom:10px">{closers_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Common hashtags</div>
      <div style="margin-bottom:10px">{hashtags_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Phrases to avoid</div>
      <div>{forbidden_html or '<span class="dim" style="font-size:12px">(none identified)</span>'}</div>
    </div>
  </div>
</div>
"""

    # Hoist brand-colour fallbacks into locals so the swatch markup and
    # the colour inputs share one literal each (keeps the inline-hex
    # budget in test_theme_tokens green — the literals live in plain
    # assignments, not inline styles).
    # G-4: show the EFFECTIVE palette (what actually renders on cards and
    # reels), not the legacy brand_primary/secondary fields — which lose to
    # any AI-extracted / setup-confirmed palette. Showing the legacy value
    # made the picker display one colour while the cards used another.
    from mediahub.brand.palette import effective_palette as _eff_pal

    _org_eff = _eff_pal(
        manual=getattr(profile, "brand_palette_manual", {}) or {},
        extracted=getattr(profile, "brand_palette_extracted", {}) or {},
    )
    _org_pri = _org_eff.get("primary") or profile.brand_primary or "#0A2540"
    _org_sec = _org_eff.get("secondary") or profile.brand_secondary or "#000000"

    body = f"""
{saved_msg}{capture_preview}{capture_error}{voice_error}
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Organisation profile</span>
  <h1>{W._h(profile.display_name) if profile.display_name else "Your organisation"}</h1>
  <p class="lede">Tell MediaHub about your club, society or team. Every generated caption, graphic, and reel is built from what's set here &mdash; brand voice, palette, sponsor rules, the lot.</p>
</section>

<div class="card" style="margin-bottom:20px;border:1px solid var(--accent);background:color-mix(in oklab, var(--accent) 6%, transparent)">
  <p style="margin:0;font-size:14px;line-height:1.5">
    <strong>This is the classic editor.</strong> The main place to set up your
    brand — palette, logos, voice capture and DNA — is now
    <a href="{url_for("organisation_setup")}" style="text-decoration:underline">Organisation &amp; brand setup</a>.
    Colour and kit governance live on the <a href="{url_for("brand_home_page")}" style="text-decoration:underline">Brand platform</a>.
  </p>
</div>

<div class="card" style="margin-bottom:20px;border:1px solid var(--accent);background:color-mix(in oklab, var(--lane) 4%, transparent)">
  <h2 style="margin-top:0">Re-analyse brand from website + social links</h2>
  <p class="dim" style="margin-bottom:12px;font-size:13px">Paste your club's website URL and/or social profile links. MediaHub reads each link, extracts the palette, tone of voice, characteristic phrases and recent captions, and updates the brand profile below. AI-driven &mdash; no manual style guide needed.</p>
  <form method="POST">
    <input type="hidden" name="action" value="capture_socials"/>
    <input type="hidden" name="profile_id" value="{W._h(profile.profile_id)}"/>
    <input type="hidden" name="display_name" value="{W._h(profile.display_name)}"/>
    <div style="margin-bottom:10px">
      <label>Website</label>
      <input type="url" name="brand_source_url" value="{W._h(profile.brand_source_url or "")}"
             placeholder="https://your-club.example" style="{_input_style};max-width:600px"/>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 18px;max-width:780px">
      <div style="margin-bottom:10px">
        <label>Instagram</label>
        <input type="url" name="social_instagram" value="{W._h((profile.social_links or {}).get("instagram", ""))}"
               placeholder="https://instagram.com/your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label>Facebook</label>
        <input type="url" name="social_facebook" value="{W._h((profile.social_links or {}).get("facebook", ""))}"
               placeholder="https://facebook.com/your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label>Twitter / X</label>
        <input type="url" name="social_twitter" value="{W._h((profile.social_links or {}).get("twitter", ""))}"
               placeholder="https://x.com/your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label>TikTok</label>
        <input type="url" name="social_tiktok" value="{W._h((profile.social_links or {}).get("tiktok", ""))}"
               placeholder="https://tiktok.com/@your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label>LinkedIn</label>
        <input type="url" name="social_linkedin" value="{W._h((profile.social_links or {}).get("linkedin", ""))}"
               placeholder="https://linkedin.com/company/your-club" style="{_input_style}"/>
      </div>
    </div>
    <div style="margin-top:10px">
      <button type="submit" class="btn">Re-analyse &rarr;</button>
      <span class="muted" style="margin-left:8px;font-size:12px">Takes 10&ndash;30 seconds.</span>
    </div>
  </form>
</div>

{brand_preview_html}

<form method="POST">
<input type="hidden" name="action" value="save"/>
<input type="hidden" name="profile_id" value="{W._h(profile.profile_id)}"/>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Identity</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px 24px;max-width:700px">
    <div>
      <label>Organisation name</label>
      <input type="text" name="display_name" value="{W._h(profile.display_name)}" placeholder="e.g. City Aquatics Club"
             style="{_input_style}" required/>
    </div>
    <div>
      <label>Short name</label>
      <input type="text" name="short_name" value="{W._h(profile.short_name)}" placeholder="e.g. City AC"
             style="{_input_style}"/>
    </div>
    <div>
      <label>Organisation type</label>
      <select name="org_type" style="{_input_style}">{org_type_opts}</select>
    </div>
    <div>
      <label>Governing body</label>
      <input type="text" name="governing_body" value="{W._h(profile.governing_body)}" placeholder="e.g. Swim England, UKA"
             style="{_input_style}"/>
    </div>
    <div>
      <label>Country</label>
      <input type="text" name="country" value="{W._h(profile.country)}" placeholder="e.g. United Kingdom"
             style="{_input_style}"/>
    </div>
    <div>
      <label>Caption language</label>
      <select name="language" style="{_input_style}">{language_opts}</select>
      <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Captions and alt text are written in this language. Bilingual options write every caption in English with a side-by-side translation, approved together in one pass.</p>
      <p style="font-size:12px;color:var(--ink-muted);margin-top:4px">This affects generated captions only &mdash; change the app language from the Interface language control.</p>
    </div>
    <div>
      <label>Result file codes</label>
      <input type="text" name="club_codes" value="{W._h(", ".join(profile.club_codes or []))}"
             placeholder="e.g. CMA, COMA" style="{_input_style}"/>
      <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Comma-separated codes that identify your members in results files.</p>
    </div>
    <div>
      <label for="org-brand-primary">Primary colour</label>
      <input id="org-brand-primary" type="color" name="brand_primary" value="{W._h(_org_pri)}"
             style="height:38px;width:80px;padding:2px;border:1px solid var(--border);border-radius:6px;cursor:pointer"/>
    </div>
    <div>
      <label for="org-brand-secondary">Secondary colour</label>
      <input id="org-brand-secondary" type="color" name="brand_secondary" value="{W._h(_org_sec)}"
             style="height:38px;width:80px;padding:2px;border:1px solid var(--border);border-radius:6px;cursor:pointer"/>
    </div>
  </div>
  <div class="mh-brandkit-strip" aria-hidden="true">
    <span class="label">Brand kit</span>
    <span class="mh-brandkit-chip"><span class="sw" id="bk-sw-pri" style="background:{W._h(_org_pri)}"></span><span class="hex" id="bk-hex-pri">{W._h(_org_pri)}</span></span>
    <span class="mh-brandkit-chip"><span class="sw" id="bk-sw-sec" style="background:{W._h(_org_sec)}"></span><span class="hex" id="bk-hex-sec">{W._h(_org_sec)}</span></span>
    <span style="font-size:var(--fs-sm);color:var(--ink-dim);margin-left:auto">This palette flows into every caption graphic and motion reel.</span>
  </div>
  <div style="margin-top:14px;padding:12px 14px;border:1px solid var(--border);border-radius:8px">
    <label style="display:block;margin-bottom:6px">Qualifying standards this club cares about</label>
    <p style="font-size:12px;color:var(--ink-dim);margin:0 0 8px">Tick the competitions whose qualifying times should trigger "Qualified!" cards. Each table names its source document on the card.</p>
    {standards_cbs}
  </div>
  <script>
  (function(){{
    function bind(inp, sw, hex) {{
      var i=document.getElementById(inp), s=document.getElementById(sw), h=document.getElementById(hex);
      if(!i) return;
      i.addEventListener('input', function(){{ if(s) s.style.background=i.value; if(h) h.textContent=i.value.toUpperCase(); }});
    }}
    bind('org-brand-primary','bk-sw-pri','bk-hex-pri');
    bind('org-brand-secondary','bk-sw-sec','bk-hex-sec');
  }})();
  </script>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Voice &amp; Tone</h2>
  <div style="margin-bottom:16px">
    <label>Caption tone</label>
    {tone_radios}
  </div>
  <div style="margin-bottom:16px">
    <label>Active platforms</label>
    {platform_cbs}
  </div>
  <div style="margin-bottom:16px">
    <label>Brand voice notes</label>
    <textarea name="tone_notes" rows="3" placeholder="Any guidelines, phrases you use, things to avoid..."
              style="{_ta_style}">{W._h(profile.tone_notes or "")}</textarea>
  </div>
  <div>
    <label>Example captions</label>
    <textarea name="exemplar_captions" rows="6"
              placeholder="Paste up to 5 past captions that represent your voice.&#10;Separate each one with --- on its own line."
              style="{_ta_style}">{W._h(exemplars_text)}</textarea>
    <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Separate captions with <code>---</code> on its own line. Up to 5 examples.</p>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Voice examples</h2>
  <p class="dim" style="margin-bottom:12px;font-size:13px">
    Paste 5&ndash;20 of your recent Instagram, Facebook or X captions &mdash; one per line.
    MediaHub will learn your sentence length, emoji and hashtag habits, opener
    and closer style, and how you refer to swimmers, then use that profile when
    generating live AI captions. Names are stripped before storage.
  </p>
  <div>
    <label>Past captions (one per line)</label>
    <textarea name="voice_examples" rows="10"
              placeholder="Massive PB from [name] in the 200 free this morning&#10;Hard work pays off &mdash; proud of every swimmer in the pool tonight &#x1F3CA;&#10;..."
              style="{_ta_style}">{W._h(voice_examples_text)}</textarea>
    <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">
      One caption per line, up to 20. Real swimmer names will be replaced with
      <code>[NAME]</code> before saving.
    </p>
  </div>
  <div style="margin-top:12px">
    <button type="submit" name="analyse_voice" value="1" class="btn">Analyse voice</button>
    {voice_discard_html}
    <span class="muted" style="font-size:12px;margin-left:8px">Analyses and saves in one step.</span>
  </div>
  {voice_profile_html}
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Sponsors</h2>
  <p class="muted" style="font-size:13px;margin-top:0">For multiple sponsors with rotation
  across your cards and monthly exposure reports, use the
  <a href="{url_for("sponsors_page")}">sponsor manager</a>. The single name below is the
  legacy field used by the per-card Sponsor Variant.</p>
  <div style="display:grid;grid-template-columns:1fr;gap:16px;max-width:600px">
    <div>
      <label>Primary sponsor name</label>
      <input type="text" name="sponsor_name" value="{W._h(profile.sponsor_name or "")}"
             placeholder="e.g. Acme Sports" style="{_input_style}"/>
    </div>
    <div>
      <label>Sponsor guidelines</label>
      <textarea name="sponsor_guidelines" rows="3"
                placeholder="Hashtags to include, mentions required, things to avoid..."
                style="{_ta_style}">{W._h(profile.sponsor_guidelines or "")}</textarea>
    </div>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Public achievements wall</h2>
  <p class="muted" style="font-size:13px;margin:0">Share your approved cards on a public
  celebration page, embed them in the club website, or syndicate via RSS — opt-in,
  initials-first, instantly revocable. Manage it on the
  <a href="{url_for("public_wall_settings")}">public wall page</a>.</p>
</div>

<div style="margin-top:8px">
  <button type="submit" class="btn">Save organisation</button>
</div>
</form>
"""
    # PC.3: workspace-membership teaser (outside the main form — it is
    # its own page). Only rendered for an org that exists on disk.
    if W.load_profile(profile.profile_id):
        _ms = W._tenancy.MembershipStore()
        _n_members = len(
            [
                m
                for m in _ms.list_for_profile(profile.profile_id)
                if m.status == W._tenancy.STATUS_ACTIVE
            ]
        )
        _bound_label = (
            f"Members-only &middot; {_n_members} active member" + ("s" if _n_members != 1 else "")
            if _ms.is_bound(profile.profile_id)
            else "Open workspace &mdash; becomes members-only when the first membership activates"
        )
        body += (
            '<div class="card" style="margin-top:20px;padding:20px 24px">'
            '<h2 style="margin-top:0;font-size:16px">Workspace members</h2>'
            f'<p class="dim" style="font-size:13px;margin:0 0 12px">{_bound_label}.</p>'
            f'<a class="btn secondary" href="{url_for("organisation_members_page")}">'
            "Manage members &rarr;</a></div>"
        )
        # PC.9 — the club's shareable referral code (the 2-named-intros
        # mechanism, in-product).
        try:
            from mediahub.commercial.referrals import ReferralCodeStore

            _rc = ReferralCodeStore().get_or_create(profile.profile_id, profile.display_name)
            _share_url = url_for("signup_page", ref=_rc.code, _external=True)
            body += (
                '<div class="card" style="margin-top:20px;padding:20px 24px">'
                '<h2 style="margin-top:0;font-size:16px">Refer a club</h2>'
                '<p class="dim" style="font-size:13px;margin:0 0 12px">'
                "Know a club that should be using MediaHub? Share your link — "
                "when they sign up through it and pay for a year, your club "
                "gets <strong>a free month</strong> credited automatically.</p>"
                f'<p style="font-size:13px;margin:0 0 6px">Your code: '
                f"<code>{W._h(_rc.code)}</code></p>"
                '<pre style="white-space:pre-wrap;font-size:12px;background:var(--bg);'
                'padding:10px;border-radius:8px;border:1px solid var(--border);margin:0">'
                f"{W._h(_share_url)}</pre></div>"
            )
        except Exception:
            W.log.warning("referral code card failed", exc_info=True)
        # PC.13 — org takeout + whole-org deletion (owner/operator only).
        if W._org_admin_allowed(profile.profile_id):
            body += f"""
<div class="card" style="margin-top:20px;padding:20px 24px">
  <h2 style="margin-top:0;font-size:16px">Your organisation's data</h2>
  <p class="dim" style="font-size:13px;margin:0 0 12px">Download everything this
  workspace holds — runs, cards and captions, media, the consent registry, sponsor
  ledger, posting log and audit log — as one ZIP (serves subject-access and
  portability requests).</p>
  <a class="btn secondary" href="{url_for("organisation_export")}">Download takeout ZIP</a>
</div>
<div class="card" style="margin-top:20px;padding:20px 24px;border-left:3px solid rgba(255,107,107,0.55)">
  <h2 style="margin-top:0;font-size:16px">Delete this organisation</h2>
  <p class="dim" style="font-size:13px;margin:0 0 12px">Removes the workspace and
  everything in it from this deployment: all runs and rendered content, media
  library, consent registry, athletes, sponsor and audit ledgers, memberships,
  and the public wall (its link stops working immediately). Member accounts
  themselves are not deleted. Billing records stay with Stripe per the DPA.
  <strong>This cannot be undone</strong> — download the takeout ZIP first.</p>
  <form method="post" action="{url_for("organisation_delete")}"
        onsubmit="return confirm('Delete this organisation and ALL of its data? This cannot be undone.')"
        style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--ink-muted)">
      Type the organisation id (<code>{W._h(profile.profile_id)}</code>) to confirm
      <input type="text" name="confirm_profile_id" required autocomplete="off" /></label>
    {W._org_delete_password_field_html()}
    <button class="btn secondary" type="submit"
            style="border-color:rgba(255,107,107,0.4)">Delete organisation</button>
  </form>
</div>"""
    return W._layout("Organisation", body, active="settings")


def organisation_analysis_discard():
    """D-15: one-shot undo for a just-persisted /organisation analysis.

    Consumes the session stash written when "Re-analyse brand" or
    "Analyse voice" saved its result, restores the stashed previous
    values onto the profile, and bounces back to the editor. Best-effort
    by design: a missing stash (expired session, already used) is a
    friendly no-op, never an error page."""
    stash = session.get(W._ORG_ANALYSIS_STASH_KEY)
    if not isinstance(stash, dict) or not stash.get("profile_id"):
        session.pop(W._ORG_ANALYSIS_STASH_KEY, None)
        W._flash_toast("Nothing to discard — no analysis is waiting.", "error")
        return redirect(url_for("organisation_page"))
    # CON2-2 — with two tabs open, a newer analysis of the OTHER kind
    # overwrites the stash; a stale Discard button must not restore that
    # snapshot. Each button posts its kind; a mismatch no-ops honestly
    # (and leaves the stash for the button it actually belongs to). An
    # absent kind (pre-deploy tab) keeps the legacy behaviour.
    posted_kind = str(request.form.get("kind") or "").strip()
    if posted_kind and posted_kind != str(stash.get("kind") or ""):
        W._flash_toast("That analysis was superseded by a newer one — nothing restored.", "error")
        return redirect(url_for("organisation_page"))
    pid = str(stash.get("profile_id"))
    if not W._session_can_use_profile(pid):
        # PC.3: a bound org answers like a nonexistent one to outsiders.
        abort(404)
    prof = W.load_profile(pid)
    if prof is None:
        abort(404)
    # One-shot: the stash is consumed by the restore it belongs to.
    session.pop(W._ORG_ANALYSIS_STASH_KEY, None)
    fields = stash.get("fields")
    if isinstance(fields, dict) and fields:
        for name, value in fields.items():
            if hasattr(prof, name):
                setattr(prof, name, value)
        W.save_profile(prof)
    kind_label = "brand" if stash.get("kind") == "brand" else "voice"
    W._flash_toast(f"Analysis discarded — the previous {kind_label} values are back.")
    return redirect(url_for("organisation_page"))


def organisation_api_tokens_page():
    """Manage the organisation's API tokens (roadmap 1.21).

    Owner-/operator-only. Tokens are org-scoped bearer credentials for the
    public ``/api/v1`` surface; the secret is shown exactly once at creation
    and only its sha256 hash is stored.
    """
    from datetime import timezone

    from mediahub.api_public import scopes as _api_scopes
    from mediahub.api_public.tokens import ApiTokenStore as _ApiTokenStore

    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    store = W._tenancy.MembershipStore()
    user_email = W._auth.current_user_email()
    is_operator = W._auth.is_dev_operator()
    can_admin = is_operator or bool(user_email and store.is_active_owner(user_email, pid))

    from mediahub.webhooks import events as _wh_events
    from mediahub.webhooks.registry import EndpointStore as _EndpointStore

    wh_store = _EndpointStore()
    tok_store = _ApiTokenStore()
    notice, error, new_secret, new_webhook_secret = "", "", "", ""
    if request.method == "POST":
        if not can_admin:
            abort(404)  # anti-enumeration, same as the members gate
        action = (request.form.get("action") or "").strip().lower()
        if action == "create":
            name = (request.form.get("name") or "").strip()
            wanted = _api_scopes.validate_scopes(request.form.getlist("scope"))
            if not wanted:
                error = "Pick at least one scope for the token."
            else:
                expires_at = None
                raw_days = (request.form.get("expires_days") or "").strip()
                if raw_days:
                    try:
                        days = max(1, min(3650, int(raw_days)))
                        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    except ValueError:
                        error = "Expiry must be a whole number of days."
                if not error:
                    _tok, new_secret = tok_store.create(
                        pid,
                        name=name,
                        scopes=wanted,
                        created_by=user_email or W._auth._dev_operator_email(),
                        expires_at=expires_at,
                    )
                    notice = "Token created. Copy it now — it won't be shown again."
        elif action == "revoke":
            token_id = (request.form.get("token_id") or "").strip()
            if tok_store.revoke(token_id, pid):
                notice = "Token revoked."
            else:
                error = "That token could not be revoked."
        elif action == "create_webhook":
            url = (request.form.get("url") or "").strip()
            evs = _wh_events.validate_events(request.form.getlist("event"))
            try:
                ep = wh_store.create(
                    pid,
                    url,
                    events=evs,
                    description=(request.form.get("description") or "").strip(),
                    created_by=user_email or W._auth._dev_operator_email(),
                )
                new_webhook_secret = ep.secret
                notice = "Webhook created. Copy the signing secret now."
            except ValueError as exc:
                error = str(exc)
        elif action == "delete_webhook":
            endpoint_id = (request.form.get("endpoint_id") or "").strip()
            if wh_store.delete(endpoint_id, pid):
                notice = "Webhook deleted."
            else:
                error = "That webhook could not be deleted."
        else:
            error = "Unknown action."

    prof = W._active_profile()
    org_name = W._h(prof.display_name if prof else pid)
    tokens = tok_store.list_for_profile(pid)

    banner = ""
    if new_secret:
        banner = (
            '<div class="card" style="border-color:var(--ok);'
            'background:rgba(16,185,129,0.08);margin-bottom:var(--sp-4)">'
            '<p style="margin:0 0 6px;font-weight:600">Your new API token</p>'
            '<p class="dim" style="margin:0 0 8px;font-size:13px">Copy it now — for '
            "security it is hashed at rest and can never be shown again.</p>"
            f'<code style="display:block;padding:10px 12px;background:var(--bg);'
            "border:1px solid var(--line);border-radius:8px;font-size:13px;"
            f'word-break:break-all">{W._h(new_secret)}</code></div>'
        )
    if new_webhook_secret:
        banner += (
            '<div class="card" style="border-color:var(--ok);'
            'background:rgba(16,185,129,0.08);margin-bottom:var(--sp-4)">'
            '<p style="margin:0 0 6px;font-weight:600">Your webhook signing secret</p>'
            '<p class="dim" style="margin:0 0 8px;font-size:13px">Configure your '
            "receiver to verify the <code>X-MediaHub-Signature</code> header with "
            "this secret.</p>"
            f'<code style="display:block;padding:10px 12px;background:var(--bg);'
            "border:1px solid var(--line);border-radius:8px;font-size:13px;"
            f'word-break:break-all">{W._h(new_webhook_secret)}</code></div>'
        )
    if notice:
        banner += f'<div class="flash ok">{W._h(notice)}</div>'
    if error:
        banner += f'<div class="flash err">{W._h(error)}</div>'

    # Create form (owner/operator only).
    create_form = ""
    if can_admin:
        groups_html = ""
        for group_name, group_scopes in _api_scopes.SCOPE_GROUPS.items():
            checks = "".join(
                '<label style="display:flex;gap:8px;align-items:flex-start;'
                'padding:5px 0;font-size:13px">'
                f'<input type="checkbox" name="scope" value="{W._h(s)}"'
                f"{' checked' if group_name == 'Read-only' else ''}/>"
                f"<span><code>{W._h(s)}</code> — {W._h(_api_scopes.scope_label(s))}</span></label>"
                for s in group_scopes
            )
            groups_html += (
                '<fieldset style="border:1px solid var(--line);border-radius:8px;'
                'padding:10px 12px;margin:0 0 10px">'
                f'<legend style="font-size:12px;color:var(--ink-muted);'
                f'text-transform:uppercase;letter-spacing:0.08em">{W._h(group_name)}</legend>'
                f"{checks}</fieldset>"
            )
        create_form = (
            '<section class="card" style="margin-bottom:var(--sp-4)">'
            '<h3 style="margin:0 0 4px">Create a token</h3>'
            '<p class="dim" style="margin:0 0 12px;font-size:13px">A token acts as '
            f"<strong>{org_name}</strong> with exactly the scopes you grant — nothing more. "
            "Approving via the API still runs the same consent and brand checks as the app.</p>"
            f'<form method="post" action="{url_for("organisation_api_tokens_page")}">'
            '<input type="hidden" name="action" value="create"/>'
            '<label style="display:block;font-size:13px;margin-bottom:4px">Name</label>'
            '<input type="text" name="name" placeholder="e.g. Zapier, Mobile app" '
            'style="width:100%;max-width:360px;padding:8px 10px;margin-bottom:12px;'
            "background:var(--bg);border:1px solid var(--line);border-radius:8px;"
            'color:var(--ink)"/>'
            f"{groups_html}"
            '<label style="display:block;font-size:13px;margin:4px 0">'
            "Expires after (days, optional)</label>"
            '<input type="number" name="expires_days" min="1" max="3650" '
            'placeholder="never" style="width:140px;padding:8px 10px;margin-bottom:12px;'
            "background:var(--bg);border:1px solid var(--line);border-radius:8px;"
            'color:var(--ink)"/><br/>'
            '<button type="submit" class="btn">Create token</button></form></section>'
        )

    # Token list.
    if tokens:
        rows = ""
        for t in tokens:
            scope_pills = " ".join(
                f'<span class="pill" style="font-size:11px">{W._h(s)}</span>' for s in t.scopes
            )
            state = (
                '<span class="pill" style="background:rgba(16,185,129,0.10);'
                'color:var(--ok)">Active</span>'
                if t.is_active()
                else '<span class="pill" style="opacity:0.6">Inactive</span>'
            )
            revoke_html = ""
            if can_admin and t.is_active():
                revoke_html = (
                    f'<form method="post" action="{url_for("organisation_api_tokens_page")}" '
                    'style="display:inline" onsubmit="return confirm('
                    "'Revoke this token? Apps using it will stop working immediately.')\">"
                    '<input type="hidden" name="action" value="revoke"/>'
                    f'<input type="hidden" name="token_id" value="{W._h(t.id)}"/>'
                    '<button type="submit" class="btn secondary" '
                    'style="padding:3px 9px;font-size:11px">Revoke</button></form>'
                )
            rows += (
                "<tr>"
                f"<td><strong>{W._h(t.name or '(unnamed)')}</strong><br>"
                f'<code style="font-size:11px;color:var(--ink-muted)">{W._h(t.token_prefix)}…</code></td>'
                f'<td style="max-width:320px">{scope_pills}</td>'
                f'<td style="font-size:12px;color:var(--ink-muted)">{W._h(t.created_at[:10])}<br>'
                f"last used {W._h((t.last_used_at or '—')[:10])}</td>"
                f"<td>{state}</td><td>{revoke_html}</td></tr>"
            )
        token_list = (
            '<section class="card"><h3 style="margin:0 0 10px">Tokens</h3>'
            '<table style="width:100%;border-collapse:collapse" class="mh-table">'
            "<thead><tr><th>Name</th><th>Scopes</th><th>Created</th><th>Status</th><th></th>"
            f"</tr></thead><tbody>{rows}</tbody></table></section>"
        )
    else:
        token_list = (
            '<section class="card"><div class="empty">No API tokens yet. '
            "Create one above to drive MediaHub from your own tools, Zapier/Make, "
            "or an AI assistant.</div></section>"
        )

    # --- webhooks section ---
    webhook_create = ""
    if can_admin:
        ev_checks = "".join(
            '<label style="display:flex;gap:8px;align-items:center;'
            'padding:4px 0;font-size:13px">'
            f'<input type="checkbox" name="event" value="{W._h(ev)}"/>'
            f"<span><code>{W._h(ev)}</code> — {W._h(_wh_events.event_label(ev))}</span></label>"
            for ev in _wh_events.ALL_EVENTS
        )
        webhook_create = (
            '<section class="card" style="margin-bottom:var(--sp-4)">'
            '<h3 style="margin:0 0 4px">Add a webhook</h3>'
            '<p class="dim" style="margin:0 0 12px;font-size:13px">MediaHub POSTs a '
            "signed JSON payload to your URL when these events happen. Verify the "
            "<code>X-MediaHub-Signature</code> header with the secret shown on create.</p>"
            f'<form method="post" action="{url_for("organisation_api_tokens_page")}">'
            '<input type="hidden" name="action" value="create_webhook"/>'
            '<label style="display:block;font-size:13px;margin-bottom:4px">Endpoint URL</label>'
            '<input type="url" name="url" required placeholder="https://example.com/hooks/mediahub" '
            'style="width:100%;max-width:420px;padding:8px 10px;margin-bottom:12px;'
            'background:var(--bg);border:1px solid var(--line);border-radius:8px;color:var(--ink)"/>'
            '<fieldset style="border:1px solid var(--line);border-radius:8px;'
            'padding:10px 12px;margin:0 0 12px">'
            '<legend style="font-size:12px;color:var(--ink-muted);text-transform:uppercase;'
            f'letter-spacing:0.08em">Events</legend>{ev_checks}</fieldset>'
            '<button type="submit" class="btn">Add webhook</button></form></section>'
        )

    endpoints = wh_store.list_for_profile(pid)
    if endpoints:
        wh_rows = ""
        for ep in endpoints:
            ev_pills = (
                " ".join(
                    f'<span class="pill" style="font-size:11px">{W._h(e)}</span>' for e in ep.events
                )
                or '<span class="dim" style="font-size:12px">all events off</span>'
            )
            del_html = ""
            if can_admin:
                del_html = (
                    f'<form method="post" action="{url_for("organisation_api_tokens_page")}" '
                    'style="display:inline" onsubmit="return confirm('
                    "'Delete this webhook? Events will stop being delivered.')\">"
                    '<input type="hidden" name="action" value="delete_webhook"/>'
                    f'<input type="hidden" name="endpoint_id" value="{W._h(ep.id)}"/>'
                    '<button type="submit" class="btn secondary" '
                    'style="padding:3px 9px;font-size:11px">Delete</button></form>'
                )
            wh_rows += (
                f'<tr><td style="max-width:280px;word-break:break-all">'
                f'<code style="font-size:12px">{W._h(ep.url)}</code></td>'
                f'<td style="max-width:280px">{ev_pills}</td>'
                f'<td style="font-size:12px;color:var(--ink-muted)">{W._h((ep.last_delivery_at or "—")[:10])}</td>'
                f"<td>{del_html}</td></tr>"
            )
        webhook_list = (
            '<section class="card"><h3 style="margin:0 0 10px">Webhooks</h3>'
            '<table style="width:100%;border-collapse:collapse" class="mh-table">'
            "<thead><tr><th>URL</th><th>Events</th><th>Last delivery</th><th></th>"
            f"</tr></thead><tbody>{wh_rows}</tbody></table></section>"
        )
    else:
        webhook_list = (
            '<section class="card"><div class="empty">No webhooks yet. Add one above to '
            "get a signed POST when a run finishes, a card is approved, a pack is "
            "exported, or a form is submitted.</div></section>"
        )

    docs_link = (
        f'<p class="dim" style="font-size:13px;margin-top:var(--sp-4)">'
        f'See the <a href="{url_for("api_docs_page")}">API reference</a>, the '
        f'<a href="{url_for("api_v1.openapi_spec")}">OpenAPI spec</a>, and '
        f'<a href="{url_for("api_docs_page")}">the webhooks guide</a> for the full list.</p>'
    )

    body = (
        '<section class="mh-hero" data-lane="" '
        'style="padding-top:var(--sp-6);padding-bottom:var(--sp-4)">'
        '<span class="mh-hero-eyebrow">Organisation</span>'
        f'<h1>API &amp; webhooks</h1><p class="lede">Programmatic access to {org_name} — '
        "submit results, list and approve cards, export packs, query your data hub, "
        "and get signed event callbacks.</p>"
        "</section>"
        f"{banner}{create_form}{token_list}"
        '<div style="height:var(--sp-5)"></div>'
        f"{webhook_create}{webhook_list}{docs_link}"
    )
    return W._layout("API & webhooks", body, active="")


def organisation_members_page():
    """Who can sign in to the active workspace.

    Owners (and the operator) add members by email — if the email has no
    account yet the row sits ``invited`` and activates itself at signup
    (no email-sending; the owner shares the signup link out-of-band).
    On an unbound (open) workspace only the operator can seed the first
    membership, which is what turns it members-only.
    """
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    store = W._tenancy.MembershipStore()
    user_email = W._auth.current_user_email()
    is_operator = W._auth.is_dev_operator()

    def _is_admin() -> bool:
        """Owner-or-operator, resolved from the per-request membership
        snapshot (one ledger read, shared with the rest of the render)
        instead of a fresh ``store`` read each time."""
        if is_operator:
            return True
        m = W._snap_membership(W._memberships_snapshot(), user_email, pid)
        return bool(m and m.status == W._tenancy.STATUS_ACTIVE and m.role == W._tenancy.ROLE_OWNER)

    can_admin = _is_admin()

    notice, error = "", ""
    if request.method == "POST":
        if not can_admin:
            abort(404)  # same anti-enumeration posture as the other gates
        action = (request.form.get("action") or "").strip().lower()
        target = (request.form.get("email") or "").strip()
        try:
            if action == "add":
                role = (request.form.get("role") or W._tenancy.ROLE_MEMBER).strip().lower()
                # Two forms POST action=add: the "Add a member" form (which
                # carries via=add_form) and the per-row change-role picker
                # (which does not). Read the prior row once so we can tell a
                # brand-new invite from an edit of an existing membership and
                # behave correctly — and safely — for each.
                prior = store.get(target, pid)
                is_edit = prior is not None and prior.status != W._tenancy.STATUS_REMOVED
                # Validate the address only when creating a NEW membership.
                # Reject one that can never activate (e.g. "coach@club" with no
                # TLD — the store only checks for an "@", so it would sit
                # "invited" forever) or that hides a control / line-separator
                # character (U+2028/U+2029/U+0085 split the JSON-lines ledger
                # on read-back, silently losing the row after a "success").
                # An edit targets a row that already exists, so re-validating
                # would wedge the role picker of a legacy dotless address.
                if not is_edit:
                    if not W._auth._looks_like_email(target) or any(
                        (ord(ch) < 0x20 or ch in "\u2028\u2029\u0085") for ch in target
                    ):
                        raise W._tenancy.TenancyError(
                            "Enter a valid email address (like coach@club.org)."
                        )
                    if len(target) > 254:  # RFC 5321 address ceiling
                        raise W._tenancy.TenancyError("That email address is too long.")
                # The "Add a member" form adds someone new — it must never be a
                # silent role change. If the address is already an active
                # member, say so instead of demoting them to the form's default
                # seat; role changes go through the per-row picker.
                if (
                    (request.form.get("via") or "").strip() == "add_form"
                    and prior
                    and prior.status == W._tenancy.STATUS_ACTIVE
                ):
                    raise W._tenancy.TenancyError(
                        f"{prior.email} is already a member — use the role "
                        "selector in their row to change their role."
                    )
                # Don't let the upsert demote the last active owner to a
                # non-owner seat — that would leave the workspace with no
                # admin (the same invariant ``remove`` protects).
                if (
                    role != W._tenancy.ROLE_OWNER
                    and prior
                    and prior.status == W._tenancy.STATUS_ACTIVE
                    and prior.role == W._tenancy.ROLE_OWNER
                ):
                    norm_target = W._tenancy.normalize_email(target)
                    others = [
                        x
                        for x in store.list_for_profile(pid)
                        if x.role == W._tenancy.ROLE_OWNER
                        and x.status == W._tenancy.STATUS_ACTIVE
                        and x.email != norm_target
                    ]
                    if not others:
                        raise W._tenancy.TenancyError(
                            "Make another member an owner before changing " "the last owner's role."
                        )
                has_account = W._user_store().get(target) is not None
                # Stamp the inviter only on a NEW row. On an edit pass "" so
                # the store carries the original inviter forward — the column
                # must show who actually invited them, not whoever last
                # touched their role.
                inviter = "" if is_edit else (user_email or W._auth._dev_operator_email())
                m = store.add(
                    target,
                    pid,
                    role=role,
                    status=(W._tenancy.STATUS_ACTIVE if has_account else W._tenancy.STATUS_INVITED),
                    invited_by=inviter,
                    invited_via_profile_id=pid,
                )
                W._invalidate_memberships_snapshot()
                if m.status == W._tenancy.STATUS_ACTIVE:
                    notice = (
                        f"{m.email} role updated to {m.role}."
                        if is_edit
                        else f"{m.email} added as {m.role}."
                    )
                elif is_edit:
                    # Editing a still-invited member's seat: update the role
                    # but do NOT re-send the invite (that would email them
                    # again on every tweak) and make no fresh "on its way"
                    # claim — the original invite still stands.
                    notice = (
                        f"{m.email} is now {m.role} — still invited, activates "
                        "when they sign up with that email."
                    )
                else:
                    # PC.14: deliver the invite when the email seam is
                    # configured; otherwise say honestly that the link
                    # must be shared out-of-band.
                    notice = (
                        f"{m.email} invited as {m.role} — the membership "
                        "activates when they sign up with that email."
                    )
                    delivered = W._send_invite_email(m.email, pid)
                    if delivered:
                        notice += " An invite email is on its way."
                    else:
                        # No mail seam configured: the owner has to pass the
                        # link on themselves, so actually SHOW it rather than
                        # referring to a "signup link" that appears nowhere on
                        # the page.
                        notice += (
                            " Email delivery isn't configured here, so share the "
                            f"signup link with them: {url_for('signup_page', _external=True)}"
                        )
            elif action == "remove":
                store.remove(target, pid)
                W._invalidate_memberships_snapshot()
                notice = f"{W._tenancy.normalize_email(target)} removed."
            else:
                error = "Unknown action."
        except W._tenancy.TenancyError as exc:
            error = str(exc)

    # Re-resolve admin/membership from a FRESH snapshot for the render: a
    # POST invalidated the per-request cache, so this reflects the just-
    # written state. In particular, an owner who demoted or removed
    # themselves is no longer an admin here, so the stale admin controls
    # don't linger for one render.
    snap = W._memberships_snapshot()
    can_admin = _is_admin()
    # PII gate (ADR-0014 anti-enumeration): an unbound (open) workspace is
    # pinnable by ANY anonymous visitor, so member/invite emails must only
    # render for the operator, an active owner, or an active member —
    # never for a stranger who merely pinned the open org.
    _viewer_row = W._snap_membership(snap, user_email, pid) if user_email else None
    viewer_is_member = bool(_viewer_row and _viewer_row.status == W._tenancy.STATUS_ACTIVE)
    can_view_members = can_admin or viewer_is_member
    # Derive the roster from the same snapshot (matches
    # ``list_for_profile``: profile match, drop tombstones, sort by
    # status then email) rather than a second full ledger parse.
    rows = (
        sorted(
            (m for (e, p), m in snap.items() if p == pid and m.status != W._tenancy.STATUS_REMOVED),
            key=lambda m: (m.status, m.email),
        )
        if can_view_members
        else []
    )
    bound = W._snap_is_bound(snap, pid)
    # The sole active owner can't be demoted or removed (server-guarded), so
    # the row's controls are disabled with an explanation rather than
    # rendered live only to fail (L8).
    _active_owners = [
        m for m in rows if m.status == W._tenancy.STATUS_ACTIVE and m.role == W._tenancy.ROLE_OWNER
    ]
    sole_owner_email = _active_owners[0].email if len(_active_owners) == 1 else None
    prof = W.load_profile(pid)
    org_name = W._h(prof.display_name if prof else pid)

    def _role_cell_html(m):
        """The role column: a label, plus an inline change-role picker for
        admins (re-uses the upsert ``add`` action). The sole active owner
        can't be demoted (the store guards it), so their row shows a static
        label with a hint rather than a picker that could only fail."""
        label = W._h(W._perms.role_label(m.role))
        if not can_admin or m.status == W._tenancy.STATUS_REMOVED:
            return label
        if m.email == sole_owner_email:
            return (
                f'{label} <span class="dim" style="font-size:11px" '
                'title="Make another member an owner before changing the sole '
                'owner&#39;s role.">· sole owner</span>'
            )
        opts = "".join(
            f'<option value="{r}"{" selected" if r == m.role else ""}>'
            f"{W._h(W._perms.role_label(r))}</option>"
            for r in W._perms.assignable_roles()
        )
        return (
            f'<form method="post" action="{url_for("organisation_members_page")}" '
            'style="display:flex;gap:6px;align-items:center;margin:0">'
            '<input type="hidden" name="action" value="add"/>'
            f'<input type="hidden" name="email" value="{W._h(m.email)}"/>'
            f'<select name="role" aria-label="Change role for {W._h(m.email)}" '
            f'style="padding:3px 6px;font-size:12px">{opts}</select>'
            '<button type="submit" class="btn secondary" '
            f'aria-label="Update role for {W._h(m.email)}" '
            'style="padding:3px 9px;font-size:11px">Update</button></form>'
        )

    def _row_html(m):
        role_badge = _role_cell_html(m)
        # These two status badges keep self-contained inline styling (shape +
        # colour) even though a base ``.pill`` rule now exists in the shared
        # cascade: it makes the exact colour role explicit and keeps the badge
        # asserted directly in the rendered HTML (test_status_badges_are_self_styled),
        # not dependent on the external stylesheet loading.
        _pill_base = (
            "display:inline-block;padding:2px 9px;border-radius:999px;"
            "font-size:11px;font-weight:600;border:1px solid "
        )
        status_badge = {
            W._tenancy.STATUS_ACTIVE: (
                f'<span class="pill" style="{_pill_base}rgba(16,185,129,0.30);'
                'background:rgba(16,185,129,0.10);color:var(--good)">Active</span>'
            ),
            W._tenancy.STATUS_INVITED: (
                f'<span class="pill" style="{_pill_base}rgba(245,158,11,0.30);'
                'background:rgba(245,158,11,0.10);color:var(--warn)">'
                "Invited — activates at signup</span>"
            ),
        }.get(m.status, "")
        remove_html = ""
        if can_admin:
            if m.email == sole_owner_email:
                # The sole active owner can't be removed (the store refuses
                # it), so show a disabled control with the reason instead of
                # a live button that would only error.
                remove_html = (
                    '<button type="button" class="btn secondary" disabled '
                    f'aria-label="Remove {W._h(m.email)} — unavailable: make another '
                    'member an owner before removing the sole owner" '
                    'title="Make another member an owner before removing the sole owner." '
                    'style="padding:4px 10px;font-size:12px;opacity:0.5;'
                    'cursor:not-allowed">Remove</button>'
                )
            else:
                remove_html = (
                    f'<form method="post" action="{url_for("organisation_members_page")}" '
                    'style="display:inline" '
                    "onsubmit=\"return confirm('Remove this member from the organisation? "
                    "They lose access immediately.')\">"
                    '<input type="hidden" name="action" value="remove"/>'
                    f'<input type="hidden" name="email" value="{W._h(m.email)}"/>'
                    '<button type="submit" class="btn secondary" '
                    f'aria-label="Remove {W._h(m.email)}" '
                    'style="padding:4px 10px;font-size:12px">Remove</button></form>'
                )
        return (
            "<tr>"
            f'<td data-label="Email" style="padding:8px 12px">{W._h(m.email)}</td>'
            f'<td data-label="Role" style="padding:8px 12px">{role_badge}</td>'
            f'<td data-label="Status" style="padding:8px 12px">{status_badge}</td>'
            f'<td data-label="Invited by" style="padding:8px 12px;font-size:12px;color:var(--ink-muted)">'
            f"{W._h(m.invited_by or '')}</td>"
            f'<td style="padding:8px 12px;text-align:right">{remove_html}</td>'
            "</tr>"
        )

    rows_html = "".join(_row_html(m) for m in rows) or (
        '<tr><td colspan="5" style="padding:14px 12px;color:var(--ink-muted)">'
        "No members yet.</td></tr>"
    )
    if bound:
        state_html = (
            '<p class="lede" style="margin-bottom:var(--sp-6)">'
            f"<strong>{org_name}</strong> is a members-only workspace: only the "
            "people below (and the deployment operator) can sign in to it."
            "</p>"
        )
    else:
        state_html = (
            '<p class="lede" style="margin-bottom:var(--sp-6)">'
            f"<strong>{org_name}</strong> is currently an <strong>open</strong> "
            "workspace — it has no members yet, so anyone using this site can "
            "open it. Add the first member below and it becomes members-only: "
            "from then on, only the people you add (and the deployment "
            "operator) can sign in."
            "</p>"
        )
    add_form_html = ""
    if can_admin:
        add_form_html = (
            '<div class="card" style="padding:20px 24px;margin-top:18px">'
            '<h2 style="margin-top:0;font-size:16px">Add a member</h2>'
            f'<form method="post" action="{url_for("organisation_members_page")}" '
            'style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">'
            '<input type="hidden" name="action" value="add"/>'
            '<input type="hidden" name="via" value="add_form"/>'
            '<div><label for="mh-member-email">Email</label><br/>'
            '<input type="email" id="mh-member-email" name="email" required '
            'autocomplete="email" placeholder="coach@club.org" '
            'style="padding:8px 10px;min-width:min(260px,100%)"/></div>'
            '<div><label for="mh-member-role">Role</label><br/>'
            '<select id="mh-member-role" name="role" style="padding:8px 10px">'
            + "".join(
                f'<option value="{r}"{" selected" if r == W._tenancy.ROLE_MEMBER else ""}>'
                f"{W._h(W._perms.role_label(r))} — {W._h(W._perms.role_description(r))}</option>"
                for r in W._perms.assignable_roles()
            )
            + "</select></div>"
            '<button type="submit" class="btn">Add member</button>'
            "</form>"
            '<p class="dim" style="font-size:12px;margin:10px 0 0">'
            "No account with that email yet? The membership is saved as an "
            "invite and activates automatically when they sign up."
            "</p></div>"
        )
    elif not is_operator and not user_email:
        # Reached only on an OPEN workspace (a members-only one bounces an
        # anonymous visitor before here). There is no owner to "log in as"
        # yet, so say what's actually true: an owner or the operator manages
        # members, and signing in is how you get there.
        add_form_html = (
            '<p class="dim" style="font-size:13px;margin-top:14px">'
            "Only an owner or the deployment operator can add members. "
            f'<a href="{url_for("login_page")}" style="color:var(--accent)">Sign in</a> '
            "if that's you."
            "</p>"
        )
    flash_html = ""
    if notice:
        flash_html = f'<p class="tag good" style="margin-bottom:16px">{W._h(notice)}</p>'
    if error:
        flash_html += f'<p class="tag bad" style="margin-bottom:16px">{W._h(error)}</p>'
    if can_view_members:
        members_html = (
            '<div class="card" style="padding:0;overflow:hidden">'
            '<table class="mh-table-stack" style="width:100%;border-collapse:collapse;font-size:13px">'
            '<thead><tr style="text-align:left;border-bottom:1px solid '
            'rgba(255,255,255,0.08)">'
            '<th scope="col" style="padding:10px 12px">Email</th>'
            '<th scope="col" style="padding:10px 12px">Role</th>'
            '<th scope="col" style="padding:10px 12px">Status</th>'
            '<th scope="col" style="padding:10px 12px">Invited by</th>'
            '<th scope="col" aria-label="Actions"></th>'
            "</tr></thead>"
            f"<tbody>{rows_html}</tbody></table></div>"
        )
    else:
        members_html = (
            '<div class="card" style="padding:20px 24px">'
            '<p class="dim" style="margin:0;font-size:13px">Member details are '
            "hidden. Sign in as a workspace member or owner to see who has "
            "access.</p></div>"
        )
    body = (
        "<h1>Team members</h1>"
        + state_html
        + flash_html
        + members_html
        + add_form_html
        + f'<p style="margin-top:18px"><a class="btn secondary" '
        f'href="{url_for("organisation_page")}">&larr; Back to organisation</a></p>'
    )
    return W._layout("Team members", body, active="settings")


def organisation_export():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    if not W._org_admin_allowed(pid):
        abort(404)  # same anti-enumeration posture as the other org gates
    import tempfile

    from flask import after_this_request

    from mediahub.privacy import org_export_zip

    tmp = tempfile.NamedTemporaryFile(
        prefix=f"mediahub-takeout-{pid}-", suffix=".zip", delete=False
    )
    tmp.close()
    try:
        org_export_zip(pid, Path(tmp.name))
    except Exception:
        W.log.warning("org export failed for %s", pid, exc_info=True)
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return W._layout(
            "Export failed",
            '<div class="card"><p class="tag bad">The takeout export failed — '
            "try again, and contact support if it persists.</p></div>",
            active="settings",
        ), 500

    @after_this_request
    def _cleanup(resp):
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return resp

    return send_file(
        tmp.name,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"mediahub-org-{pid}-takeout.zip",
    )


def organisation_delete():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    if not W._org_admin_allowed(pid):
        abort(404)
    # The typed org id is the universal irreversibility check; a signed-in
    # (non-operator) actor must also re-verify their password so a
    # hijacked session can't destroy the workspace (mirrors account
    # deletion).
    if (request.form.get("confirm_profile_id") or "").strip() != pid:
        return W._layout(
            "Organisation not deleted",
            '<div class="card"><p class="tag bad">The confirmation id did not '
            "match — nothing was deleted.</p>"
            f'<p><a class="btn secondary" href="{url_for("organisation_page")}">'
            "&larr; Back</a></p></div>",
            active="settings",
        ), 400
    email = W._auth.current_user_email()
    if email and not W._auth.is_dev_operator():
        try:
            W._user_store().authenticate(email, request.form.get("password") or "")
        except W._auth.AuthError:
            return W._layout(
                "Organisation not deleted",
                '<div class="card"><p class="tag bad">Password check failed '
                "&mdash; organisation NOT deleted.</p>"
                f'<p><a class="btn secondary" href="{url_for("organisation_page")}">'
                "&larr; Back</a></p></div>",
                active="settings",
            ), 403
    from mediahub.privacy import delete_org

    report = delete_org(pid, delete_run=W._delete_run)
    # delete_org unlinks the profile JSON directly (bypassing save_profile),
    # so drop the cached copy — mirrors the /sign-in/delete fix — before any
    # later read in this request (e.g. _layout's active-profile chrome).
    W._invalidate_profile_cache(pid)
    session.pop("active_profile_id", None)
    db_rows = sum(report.get("db_rows_deleted", {}).values())
    retained = "".join(f"<li>{W._h(r)}</li>" for r in report.get("retained", []))
    body = (
        '<section class="mh-hero" style="padding-top:var(--sp-7);'
        'padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Privacy &amp; data</span>'
        '<h1>Organisation <em class="editorial">deleted.</em></h1></section>'
        '<div class="card"><h2>What was removed</h2><ul>'
        f"<li>{report['runs_deleted']} run(s) with their rendered content, "
        "caches and caption memory</li>"
        f"<li>{report['media_assets_deleted']} media asset(s) and "
        f"{report['logos_deleted']} uploaded logo file(s)</li>"
        f"<li>{db_rows} database row(s) across consent registry, athletes, "
        "club records, corrections, posting and telemetry logs</li>"
        f"<li>{report['memory_rows_deleted']} caption-memory row(s)</li>"
        f"<li>{report['memberships_deleted']} workspace membership(s)</li>"
        "<li>The organisation profile, its brand kit and the public wall "
        "link (now dead)</li>"
        "</ul><h2>Retained</h2>"
        f"<ul>{retained}</ul>"
        "<p class='muted'>Content already published to social platforms must "
        "be deleted there too.</p>"
        f'<p><a class="btn secondary" href="{url_for("home")}">&larr; Home</a></p>'
        "</div>"
    )
    return W._layout("Organisation deleted", body, active="")


def organisation_setup():
    # "Create new organisation" links here with ?fresh=1. The user has
    # explicitly asked for a blank slate, so we must NOT pre-fill the
    # form — or show the "what we learned" preview, the uploaded logo,
    # or the loaded guidelines document — from whatever org they happen
    # to be signed in to. Without this, a brand-new org showed another
    # club's name, links, logo and guidelines on screen (and risked the
    # user building a new org on top of inherited assets). The active
    # session org is left untouched; building with a new name creates a
    # fresh profile as normal.
    prof = None if request.args.get("fresh") else W._active_profile()
    # Pre-fill from any existing profile so refreshing the page doesn't
    # wipe what the user just typed.
    pid = prof.profile_id if prof else ""
    display_name = prof.display_name if prof else ""
    org_type = prof.org_type if prof else "other"
    country = prof.country if prof else ""
    governing_body = prof.governing_body if prof else ""
    website_url = prof.brand_source_url if prof else ""
    social = dict(prof.social_links) if prof and prof.social_links else {}
    brand_logos = list(prof.brand_logos) if prof and prof.brand_logos else []
    mandatory_rules = (
        list(prof.brand_guidelines_mandatory_rules)
        if prof and prof.brand_guidelines_mandatory_rules
        else []
    )
    link_state = dict(prof.link_capture_state) if prof and prof.link_capture_state else {}

    # Honest LLM-availability banner. The whole capture pipeline
    # silently degrades to deterministic heuristics when no key
    # is configured, which leaves the user staring at a blank
    # palette + empty keywords + raw-text voice summary with no
    # explanation of why. Surface the state up front.
    llm_banner_html = ""
    try:
        from mediahub.media_ai.llm import is_available as _llm_available

        llm_ok = _llm_available()
    except Exception:
        llm_ok = False
    if not llm_ok:
        llm_banner_html = (
            '<div style="margin-bottom:14px;padding:12px 14px;'
            "border:1px solid rgba(255,180,84,0.45);border-radius:8px;"
            "background:rgba(255,180,84,0.08);font-size:13px;"
            'color:var(--ink);line-height:1.5">'
            '<strong style="color:var(--warn)">AI features unavailable.</strong> '
            "No cloud LLM provider is configured on this deployment, so the "
            "engine cannot infer your brand voice, palette, or operating "
            "profile. You can still complete setup, but generated content "
            "will fall back to a generic template until "
            '<code style="font-family:var(--font-mono,monospace);font-size:12px">'
            "GEMINI_API_KEY</code> or "
            '<code style="font-family:var(--font-mono,monospace);font-size:12px">'
            "ANTHROPIC_API_KEY</code> is set on the server."
            "</div>"
        )

    # A-1 hardening: surface a one-shot notice when the org-ready gate
    # cancelled a POST (set in _gate_until_org_ready). Popped so it
    # shows exactly once, and prepended to the banner slot that is
    # already rendered at the top of the setup form.
    _gate_notice = session.pop("_setup_gate_notice", "")
    if _gate_notice:
        llm_banner_html = (
            '<div style="margin-bottom:14px;padding:12px 14px;'
            "border:1px solid rgba(255,180,84,0.45);border-radius:8px;"
            "background:rgba(255,180,84,0.08);font-size:13px;"
            'color:var(--ink);line-height:1.5">'
            '<strong style="color:var(--warn)">Not saved.</strong> '
            f"{W._h(_gate_notice)}</div>" + llm_banner_html
        )

    from mediahub.web._countries import COUNTRIES

    # JSON-safe array literal for inlining into the combobox JS.
    # Each country is HTML-escaped because the same string is also
    # rendered into list-item innerHTML below.
    _countries_js_array = (
        "["
        + ",".join('"' + c.replace("\\", "\\\\").replace('"', '\\"') + '"' for c in COUNTRIES)
        + "]"
    )

    # --- Preview block (only when the AI has already run once) ---
    preview_html = ""
    if prof and prof.is_ready():
        kw_chips = "".join(
            f'<span style="display:inline-block;padding:3px 10px;'
            f"margin:2px 4px 2px 0;border:1px solid var(--border);"
            f'border-radius:999px;font-size:12px;color:var(--ink-dim)">'
            f"{W._h(k)}</span>"
            for k in (prof.brand_keywords or [])[:10]
        )
        # Effective palette = manual override slots > AI-detected.
        # Show that as the "Confirmed" row of swatches, with the AI's
        # raw pick rendered separately so the user can see what the
        # engine actually inferred.
        from mediahub.brand import palette as _palette_mod

        extracted_pal = prof.brand_palette_extracted or {}
        manual_pal = prof.brand_palette_manual or {}
        effective_pal = _palette_mod.effective_palette(
            manual=manual_pal,
            extracted=extracted_pal,
        )
        use_fourth = bool(prof.brand_palette_use_fourth)

        slot_labels = _palette_mod.SLOTS
        if (
            use_fourth
            or extracted_pal.get(_palette_mod.FOURTH_SLOT)
            or manual_pal.get(_palette_mod.FOURTH_SLOT)
        ):
            slot_labels = slot_labels + (_palette_mod.FOURTH_SLOT,)

        def _swatch_row(palette: dict) -> str:
            rendered = ""
            for k in slot_labels:
                hexv = palette.get(k)
                if not hexv:
                    continue
                rendered += (
                    f'<span title="{W._h(k)}: {W._h(hexv)}" style="display:inline-flex;'
                    f"align-items:center;gap:6px;padding:3px 8px;margin-right:6px;"
                    f"margin-bottom:4px;border:1px solid var(--border);"
                    f'border-radius:6px;background:var(--panel)">'
                    f'<span style="display:inline-block;width:18px;height:18px;'
                    f"border-radius:4px;background:{W._h(hexv)};"
                    f'border:1px solid rgba(255,255,255,0.15)"></span>'
                    f'<code style="font-size:11px;color:var(--ink)">{W._h(hexv)}</code></span>'
                )
            return rendered or '<span class="dim" style="font-size:12px">(none)</span>'

        ai_row = _swatch_row(extracted_pal)
        effective_row = _swatch_row(effective_pal)

        # Per-source colour breakdown — surface every signal that
        # informed the AI's pick so the user can see "this was
        # mentioned in your style guide, that came off Instagram".
        sources_dict = prof.brand_palette_sources or {}
        sources_html = ""
        if sources_dict:
            rows = []
            for label, hexes in sources_dict.items():
                if not hexes:
                    continue
                chips = "".join(
                    f'<span style="display:inline-flex;align-items:center;'
                    f"gap:4px;padding:2px 6px;margin:2px 4px 2px 0;"
                    f"border:1px solid var(--border);border-radius:4px;"
                    f"font-size:10.5px;font-family:var(--font-mono,monospace);"
                    f'color:var(--ink-dim)">'
                    f'<span style="display:inline-block;width:10px;height:10px;'
                    f"border-radius:2px;background:{W._h(h)};"
                    f'border:1px solid rgba(255,255,255,0.12)"></span>'
                    f"{W._h(h)}</span>"
                    for h in hexes[:8]
                )
                rows.append(
                    f'<div style="margin-bottom:6px"><span style="font-size:11px;'
                    f'color:var(--ink-dim);margin-right:6px">{W._h(label)}</span>{chips}</div>'
                )
            if rows:
                sources_html = (
                    '<details style="margin-top:10px">'
                    '<summary style="cursor:pointer;font-size:12px;color:var(--ink-dim);'
                    'user-select:none">Where these colours came from '
                    f"({len(sources_dict)} source{'s' if len(sources_dict) != 1 else ''})</summary>"
                    f'<div style="margin-top:8px;padding:10px;background:rgba(255,255,255,0.02);'
                    f'border-radius:6px">{"".join(rows)}</div>'
                    "</details>"
                )

        reasoning_html = ""
        if prof.brand_palette_reasoning:
            reasoning_html = (
                f'<p class="muted" style="font-size:11.5px;margin:6px 0 0 0;'
                f'line-height:1.4;font-style:italic">'
                f"Engine reasoning: {W._h(prof.brand_palette_reasoning)}</p>"
            )

        confirm_url = url_for("organisation_setup_palette")

        def _slot_default(slot: str, fallback: str) -> str:
            # Prefer the user's previous manual entry; else fall
            # back to the AI's pick; else a neutral placeholder so
            # the colour picker has something to show.
            v = manual_pal.get(slot) or extracted_pal.get(slot) or fallback
            return v if isinstance(v, str) and v.startswith("#") else fallback

        def _picker_block(
            slot: str,
            label: str,
            default_hex: str,
            *,
            disabled: bool = False,
            max_width: str = "",
        ) -> str:
            attr = "disabled" if disabled else ""
            wrap_style = f"max-width:{max_width};" if max_width else ""
            # The colour picker always needs a concrete value (it can't be
            # empty), so it shows the effective colour (manual override, else
            # the AI's pick). The hex TEXT field is the blankable control:
            # pre-fill it ONLY with a real manual override, so an untouched
            # slot posts blank and defers to the AI — exactly what the form
            # copy promises. The AI's pick is shown as placeholder ghost text.
            _mh = manual_pal.get(slot)
            text_value = _mh if (isinstance(_mh, str) and _mh.startswith("#")) else ""
            return (
                f'<label style="display:flex;flex-direction:column;gap:4px;'
                f'font-size:11.5px;color:var(--ink-dim);{wrap_style}">'
                f"<span>{W._h(label)}</span>"
                f'<span style="display:flex;gap:6px;align-items:center">'
                f'<input type="color" name="palette_{slot}" '
                f'id="palette-{slot}-color" value="{W._h(default_hex)}" {attr} '
                f'style="width:52px;height:44px;padding:0;'
                f"border:1px solid var(--border);border-radius:4px;"
                f'background:var(--panel);cursor:pointer;flex-shrink:0"/>'
                f'<input type="text" name="palette_{slot}_hex" '
                f'id="palette-{slot}-hex" value="{W._h(text_value)}" '
                f'placeholder="{W._h(default_hex)}" '
                f'pattern="^#[0-9a-fA-F]{{6}}$" maxlength="7" '
                f'data-palette-mirror="palette_{slot}" {attr} '
                f'style="flex:1;min-width:0;padding:11px 10px;min-height:44px;'
                f"border:1px solid var(--border);"
                f"border-radius:4px;background:var(--bg);color:var(--ink);"
                f'font-family:var(--font-mono,monospace);font-size:13px"/>'
                f"</span></label>"
            )

        pickers_html = "".join(
            _picker_block(slot, label, _slot_default(slot, fallback))
            for slot, label, fallback in (
                ("primary", "Primary", "#0a2540"),
                ("secondary", "Secondary", "#1a1a1a"),
                ("accent", "Accent", "#d4ff3a"),
            )
        )
        fourth_picker_html = _picker_block(
            "fourth",
            "Fourth colour",
            _slot_default("fourth", "#ffffff"),
            disabled=not use_fourth,
            max_width="33%",
        )
        fourth_checked_attr = "checked" if use_fourth else ""
        fourth_visible_style = "" if use_fourth else "display:none"

        confirm_form_html = f"""
<form method="POST" action="{confirm_url}" data-no-loader="1"
      style="margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.08)">
  <div style="font-size:12px;font-weight:600;color:var(--ink);margin-bottom:6px;
              text-transform:uppercase;letter-spacing:0.04em">
    Override the AI's pick
  </div>
  <p class="muted" style="font-size:11.5px;margin:0 0 10px 0;line-height:1.45">
    The engine reads every link and document you supplied and decides a palette.
    Use the pickers below only if it got it wrong &mdash; otherwise leave them
    as-is and the AI's values keep flowing through to every generated card.
  </p>
  <div class="mh-palette-grid" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;
              margin-bottom:10px">{pickers_html}</div>
  <label style="display:inline-flex;align-items:center;gap:8px;font-size:12px;
                color:var(--ink);cursor:pointer;margin-bottom:8px">
    <input type="checkbox" name="palette_use_fourth" id="palette-use-fourth"
           value="on" {fourth_checked_attr}/>
    <span>Add a fourth brand colour (some clubs use four)</span>
  </label>
  <div id="palette-fourth-row" style="margin-bottom:10px;{fourth_visible_style}">
    {fourth_picker_html}
  </div>
  <button type="submit" class="btn" style="font-size:13px;padding:11px 16px">
    Save brand colours
  </button>
  <span class="muted" style="margin-left:10px;font-size:11.5px">
    Leave any field blank to fall back to the AI's pick for that slot.
  </span>
</form>
<script>{W._PALETTE_PICKER_JS}</script>
"""

        # --- "Arrange brand colours" — swap colours between roles ---
        # One form, several submit buttons, each carrying a pre-computed
        # `order` permutation. No JS: every control is a plain POST, so
        # it works for keyboard / no-script users and can't drift out of
        # sync with the server. Only renders when there are >=2 colours
        # to rearrange.
        reorder_url = url_for("organisation_setup_palette_reorder")
        # Mirror the route's notion of "active slots": every effective
        # slot, minus the 4th unless the org opted into a fourth colour.
        # Keeping these in lock-step means every chip's move button
        # submits an `order` the route will actually honour.
        present_for_reorder = [s for s in _palette_mod.ALL_SLOTS if effective_pal.get(s)]
        if not use_fourth:
            present_for_reorder = [s for s in present_for_reorder if s != _palette_mod.FOURTH_SLOT]
        reorder_block_html = ""
        if len(present_for_reorder) >= 2:
            _n = len(present_for_reorder)
            _role_label = {
                "primary": "Primary",
                "secondary": "Secondary",
                "accent": "Accent",
                "fourth": "Fourth",
            }

            def _swap_order(i: int, j: int) -> str:
                seq = list(present_for_reorder)
                seq[i], seq[j] = seq[j], seq[i]
                return ",".join(seq)

            # Cycle = rotate forward one role: slot k takes the colour
            # from slot k-1, so the primary colour walks to secondary.
            _cycle_order = ",".join(present_for_reorder[(k - 1) % _n] for k in range(_n))

            _arrow_base = (
                "width:30px;height:30px;display:inline-flex;align-items:center;"
                "justify-content:center;border:1px solid var(--border);"
                "border-radius:4px;background:var(--bg);color:var(--ink);"
                "font-size:12px;line-height:1;padding:0"
            )

            def _arrow(i: int, j: int, glyph: str, where: str, role: str, disabled: bool) -> str:
                if disabled:
                    return (
                        f'<button type="button" disabled aria-hidden="true" '
                        f'style="{_arrow_base};opacity:0.22;'
                        f'cursor:not-allowed">{glyph}</button>'
                    )
                return (
                    f'<button type="submit" name="order" '
                    f'value="{W._h(_swap_order(i, j))}" '
                    f'title="Move {role} {where}" '
                    f'aria-label="Move {W._h(role)} colour {where}" '
                    f'style="{_arrow_base};cursor:pointer">{glyph}</button>'
                )

            _chips = []
            for _i, _slot in enumerate(present_for_reorder):
                _hexv = effective_pal.get(_slot)
                _role = _role_label.get(_slot, _slot)
                _left = _arrow(_i, _i - 1, "&#9664;", "left", _role, _i == 0)
                _right = _arrow(_i, _i + 1, "&#9654;", "right", _role, _i == _n - 1)
                _chips.append(
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f"padding:8px 10px;border:1px solid var(--border);"
                    f'border-radius:8px;background:var(--panel)">'
                    f'<span style="display:inline-block;width:22px;height:22px;'
                    f"border-radius:5px;background:{W._h(_hexv)};"
                    f'border:1px solid rgba(255,255,255,0.15);flex-shrink:0"></span>'
                    f'<span style="display:flex;flex-direction:column;line-height:1.2">'
                    f'<span style="font-size:12px;font-weight:600;color:var(--ink)">'
                    f"{_i + 1} &middot; {W._h(_role)}</span>"
                    f'<code style="font-size:10.5px;color:var(--ink-dim)">'
                    f"{W._h(_hexv)}</code></span>"
                    f'<span style="display:flex;gap:3px;margin-left:2px">'
                    f"{_left}{_right}</span>"
                    f"</div>"
                )

            reorder_block_html = f"""
<div style="margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.08)">
  <div style="font-size:12px;font-weight:600;color:var(--ink);margin-bottom:6px;
              text-transform:uppercase;letter-spacing:0.04em">Arrange brand colours</div>
  <p class="muted" style="font-size:11.5px;margin:0 0 10px 0;line-height:1.45">
    Swap your colours between roles &mdash; primary, secondary, third and (when used)
    fourth. Whichever colour is primary drives everything downstream: site chrome,
    result cards, reels and parent emails all follow it.
  </p>
  <form method="POST" action="{reorder_url}" data-no-loader="1">
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;margin-bottom:10px">
      {"".join(_chips)}
    </div>
    <button type="submit" name="order" value="{W._h(_cycle_order)}" class="btn"
            style="font-size:12px;padding:9px 14px">&#8635; Cycle colours</button>
    <span class="muted" style="margin-left:10px;font-size:11.5px">
      Rotates every colour forward one role.
    </span>
  </form>
</div>
"""

        # Phase 1.6 Stage H — resolve the cached theme JSON for
        # this profile so the H3 callout and H2 audit panel can
        # render the engine's decisions in plain English.
        _theme_json_for_audit = None
        try:
            _kit_for_audit = prof.get_brand_kit()
            _theme_json_for_audit = _kit_for_audit.ensure_derived_palette()
        except Exception:
            _theme_json_for_audit = None
        _repair_callout_html = W._theme_repair_callout_html(_theme_json_for_audit)
        _audit_panel_html = W._theme_audit_panel_html(_theme_json_for_audit)
        # G1.18 colour-accessibility report for the brand's resolved --mh-*
        # role set (deterministic; read-only) beside the theme audit.
        _colour_a11y_html = ""
        try:
            from mediahub.graphic_renderer.render import _mh_role_vars

            _colour_a11y_html = W._colour_accessibility_panel_html(
                _mh_role_vars({}, _kit_for_audit)
            )
        except Exception:
            _colour_a11y_html = ""

        preview_html = f"""
<div class="card" style="margin-bottom:24px;border:1px solid var(--accent);
     background:color-mix(in oklab, var(--lane) 4%, transparent)">
  <h3 style="margin-top:0;margin-bottom:8px">What MediaHub learned about {W._h(prof.display_name)}</h3>
  <p style="font-size:14px;color:var(--ink);line-height:1.5;margin:0 0 10px 0">
    {W._h(prof.brand_voice_summary or "(no voice summary yet — capture again from a richer source)")}</p>
  <div style="font-size:12px;color:var(--ink-dim);margin-bottom:4px">Keywords</div>
  <div style="margin-bottom:10px">{kw_chips or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
  <div style="font-size:12px;color:var(--ink-dim);margin-bottom:4px">Palette in use</div>
  <div style="margin-bottom:6px">{effective_row}</div>
  <div style="font-size:11px;color:var(--ink-dim);margin-bottom:4px">AI's pick from all sources</div>
  <div style="margin-bottom:6px">{ai_row}</div>
  {reasoning_html}
  {sources_html}
  <p class="muted" style="font-size:12px;margin:10px 0 0 0">Source: {W._h(prof.brand_source_url or "—")} &middot; captured {W._h((prof.brand_captured_at or "")[:19])}</p>
  {reorder_block_html}
  {confirm_form_html}
  {_repair_callout_html}
  {_audit_panel_html}
  {_colour_a11y_html}
  <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <a class="btn" href="{url_for("make_page")}" data-mh-cascade="finalise">Looks right &mdash; start creating &rarr;</a>
    {W._sample_pack_cta(compact=True, button_label="See it on a sample meet")}
    <span class="muted" style="font-size:12px">Or refine the inputs below and re-analyse.</span>
  </div>
</div>
"""

    _input_style = (
        "width:100%;padding:9px 11px;border:1px solid var(--border);"
        "border-radius:6px;background:var(--bg);color:var(--ink);"
        "font-size:14px;font-family:inherit"
    )

    # Social link inputs — one row per platform, all optional.
    _PLATFORMS = [
        ("instagram", "Instagram", "https://instagram.com/your-club"),
        ("facebook", "Facebook", "https://facebook.com/your-club"),
        ("twitter", "Twitter / X", "https://x.com/your-club"),
        ("tiktok", "TikTok", "https://tiktok.com/@your-club"),
        ("linkedin", "LinkedIn", "https://linkedin.com/company/your-club"),
    ]
    # ---- Logo thumbnail grid (D1) — render existing logos with rename/delete
    _logos_grid_html = ""
    if brand_logos:
        cards = []
        for logo in brand_logos:
            label = logo.get("label") or logo.get("original_filename") or "logo"
            desc = (logo.get("ai_description") or "").strip()
            mime = logo.get("mime") or ""
            delete_url = url_for("organisation_setup_logo_delete", logo_id=logo.get("logo_id", ""))
            preview = ""
            if mime.startswith("image/"):
                # Unified logo chip — the KEYED silhouette (opaque/white
                # backgrounds removed) on a contrast-aware backing, so the upload
                # grid reads consistently whatever each file's colour/format.
                from mediahub.brand.logos import logo_chip_tone as _lct

                _lid = logo.get("logo_id", "")
                preview = W._logo_chip_html(
                    url_for("organisation_setup_logo_serve", logo_id=_lid, bg=1, chip=1),
                    alt=label,
                    size="lg",
                    tone=_lct(prof.profile_id, _lid),
                    brand_hex=(getattr(prof, "brand_primary", "") or ""),
                    initials=W._avatar_initials(prof.display_name),
                )
            else:
                preview = (
                    '<div style="display:flex;align-items:center;justify-content:center;'
                    "height:96px;background:rgba(245,242,232,0.04);border-radius:4px;"
                    "font-family:var(--font-mono,monospace);font-size:11px;"
                    f'color:var(--ink-muted,#7A7869)">{W._h(mime.split("/")[-1] or "FILE")}</div>'
                )
            colours = logo.get("ai_dominant_colours") or []
            colour_swatches = "".join(
                f'<span title="{W._h(c)}" style="display:inline-block;'
                f"width:14px;height:14px;border-radius:2px;"
                f"background:{W._h(c)};border:1px solid rgba(255,255,255,0.15);"
                f'vertical-align:middle;margin-right:3px"></span>'
                for c in colours[:4]
            )
            # ``_h`` is ``markupsafe.escape``; mixing it into ``+``
            # concatenation makes every trailing string literal get
            # HTML-escaped. Built the whole card as a single f-string
            # with the URL pre-strified so attributes like
            # ``data-no-loader`` reach the browser unescaped.
            _desc_html = (
                f'<div class="muted" style="font-size:11px;line-height:1.3" '
                f'title="{str(W._h(desc))}">{str(W._h(desc[:120]))}</div>'
                if desc
                else ""
            )
            _swatches_html = f"<div>{colour_swatches}</div>" if colour_swatches else ""
            _filename_attr = str(W._h(logo.get("original_filename", "")))
            _label_html = str(W._h(label))
            _delete_url_attr = str(W._h(delete_url))
            cards.append(
                f'<div class="mh-logo-card" style="background:var(--surface,var(--panel));'
                f"border:1px solid var(--chrome,var(--border));border-radius:6px;"
                f'padding:10px;display:flex;flex-direction:column;gap:8px">'
                f"{preview}"
                f'<div style="font-size:12px;font-weight:600;color:var(--ink);'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
                f'title="{_filename_attr}">{_label_html}</div>'
                f"{_desc_html}"
                f"{_swatches_html}"
                f'<form method="POST" action="{_delete_url_attr}" data-no-loader="1" '
                f"onsubmit=\"return confirm('Delete this logo?')\">"
                f'<button type="submit" style="font-size:11px;padding:5px 9px;'
                f"background:transparent;border:1px solid rgba(255,107,107,0.3);"
                f"color:#FF6B6B;border-radius:4px;cursor:pointer;"
                f"font-family:var(--font-mono,monospace);text-transform:uppercase;"
                f'letter-spacing:0.10em">Delete</button>'
                f"</form>"
                f"</div>"
            )
        _logos_grid_html = (
            '<div style="margin-top:14px;display:grid;'
            'grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px">'
            + "".join(cards)
            + "</div>"
        )

    # D-16: surface any logo files the last save couldn't use — the upload
    # handler stashes {filename, reason} rejections so they don't just vanish
    # from the grid with no explanation.
    _logo_reject_html = ""
    _rejections = session.pop("logo_rejections", None)
    if isinstance(_rejections, list) and _rejections:
        _items = "".join(
            f"<li><strong>{W._h(str(r.get('filename') or 'file'))}</strong> — "
            f"{W._h(str(r.get('reason') or 'couldn’t be used'))}</li>"
            for r in _rejections[:8]
            if isinstance(r, dict)
        )
        _logo_reject_html = (
            '<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--warn);'
            "border-radius:8px;background:color-mix(in oklab, var(--warn) 7%, transparent);"
            'font-size:12px;line-height:1.5">'
            f'<div style="font-weight:600;color:var(--warn)">'
            f"{len(_rejections)} file{'s' if len(_rejections) != 1 else ''} couldn&rsquo;t be used</div>"
            f'<ul style="margin:6px 0 0;padding-left:18px;color:var(--ink-dim)">{_items}</ul>'
            "</div>"
        )

    # M2 — "Where can AI read you" defaults to OPEN so a first-run
    # user sees the inputs (they're entirely optional but easy to
    # miss if collapsed). Once submitted with at least one link
    # the section stays open so the user can re-edit; if submitted
    # empty, leave it open too so re-entry is one click away.
    _has_links = bool(website_url) or any(social.values())
    _links_section_open = "open"  # always default-open per UX brief
    _links_toggle_verb = "collapse" if _links_section_open else "expand"

    # Existing guidelines status (when the user has already uploaded once)
    _gl_status_html = ""
    if prof and prof.brand_guidelines_filename:
        g = prof.brand_guidelines or {}
        summary = (g.get("summary") or "")[:280]
        attrs = ", ".join((g.get("voice_attributes") or [])[:6]) or "—"
        n_dos = len(g.get("tone_dos") or [])
        n_donts = len(g.get("tone_donts") or [])
        n_prohib = len(g.get("prohibited_words") or [])
        # Surface mandatory rules — the user explicitly asked to see
        # which "MUST follow" statements the AI extracted, so they
        # can sanity-check the engine isn't silently dropping them.
        rules = list(mandatory_rules)
        rules_html = ""
        if rules:
            rule_chips = "".join(
                '<li style="padding:6px 10px;margin:4px 4px 0 0;'
                "display:inline-block;border-radius:4px;"
                "background:color-mix(in oklab, var(--lane) 8%, transparent);border:1px solid color-mix(in oklab, var(--lane) 30%, transparent);"
                f'color:var(--ink);font-size:11.5px;line-height:1.35;max-width:100%">'
                f'<strong style="color:var(--lane,var(--accent))">MUST</strong> &middot; {W._h(r[:240])}'
                "</li>"
                for r in rules[:12]
            )
            more = ""
            if len(rules) > 12:
                more = f'<div class="muted" style="font-size:11px;margin-top:4px">…and {len(rules) - 12} more.</div>'
            rules_html = (
                '<div style="margin-top:10px">'
                '<div style="font-size:11.5px;color:var(--ink);font-weight:600;'
                'letter-spacing:0.02em;margin-bottom:4px">'
                f"Non-negotiable rules the AI extracted ({len(rules)})"
                "</div>"
                f'<ul style="list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap">{rule_chips}</ul>'
                + more
                + '<div class="muted" style="font-size:11px;margin-top:6px">'
                "These are surfaced at the TOP of every system prompt with explicit "
                "override framing &mdash; they will be respected on every generated caption."
                "</div>"
                "</div>"
            )
        _gl_status = prof.brand_guidelines_status or ""
        _gl_failed = _gl_status.startswith(("unsupported_binary", "error:"))
        if _gl_failed:
            # D-30: a rejected guidelines upload is a FAILURE — warning
            # styling, no green "Loaded", and no raw internal status /
            # extractor codes; a plain-English reason instead.
            if _gl_status.startswith("unsupported_binary"):
                _gl_reason = (
                    "It looks like an image or binary file. Brand guidelines must be a "
                    "text document — PDF, DOCX, TXT, RTF or MD."
                )
            else:
                _gl_reason = (
                    "We couldn't read this file. Try a PDF, DOCX, TXT, RTF or MD export "
                    "of your guidelines."
                )
            _gl_status_html = (
                '<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--warn);'
                "border-radius:8px;background:color-mix(in oklab, var(--warn) 7%, transparent);"
                'font-size:12px;line-height:1.5">'
                '<div style="font-weight:600;color:var(--warn)">Couldn&rsquo;t read: '
                f"{W._h(prof.brand_guidelines_filename)}</div>"
                f'<div class="muted" style="margin-top:4px;color:var(--ink-dim)">{W._h(_gl_reason)}</div>'
                "</div>"
            )
        else:
            _gl_status_html = (
                '<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--border);'
                'border-radius:8px;background:rgba(44,201,127,0.05);font-size:12px;line-height:1.5">'
                f'<div style="font-weight:600;color:var(--ink)">Loaded: {W._h(prof.brand_guidelines_filename)}</div>'
                f'<div class="muted" style="margin-top:2px">{W._h(prof.brand_guidelines_uploaded_at[:19] if prof.brand_guidelines_uploaded_at else "")}'
                f" &middot; {W._h(prof.brand_guidelines_status or '')} via {W._h(prof.brand_guidelines_extractor or '')}</div>"
                + (
                    f'<div style="margin-top:6px;color:var(--ink-dim)">{W._h(summary)}</div>'
                    if summary
                    else ""
                )
                + f'<div style="margin-top:6px;color:var(--ink-dim)">Voice attributes: {W._h(attrs)} &middot; '
                f"{n_dos} do{'s' if n_dos != 1 else ''}, {n_donts} don't{'s' if n_donts != 1 else ''}, "
                f"{n_prohib} prohibited word{'s' if n_prohib != 1 else ''}.</div>"
                + rules_html
                + '<div class="muted" style="font-size:11px;margin-top:6px">Upload a new file to replace, or leave blank to keep this one.</div>'
                "</div>"
            )

    # Per-link status chips (M5): map each captured status to a
    # chip styled by severity. The mapping is kept here next to the
    # social_inputs renderer so a missing status falls through to
    # "Idle" without exception.
    _STATUS_CHIP = {
        "real_content": (
            "Learned",
            "rgba(94,227,154,0.12)",
            "rgba(94,227,154,0.45)",
            "var(--good, #5EE39A)",
        ),
        "soft_blocked_spa": (
            "Blocked (JS)",
            "rgba(255,180,84,0.10)",
            "rgba(255,180,84,0.45)",
            "var(--warn, #FFB454)",
        ),
        "hard_blocked": (
            "Blocked",
            "rgba(255,107,107,0.10)",
            "rgba(255,107,107,0.45)",
            "var(--bad, #FF6B6B)",
        ),
        "auth_walled": (
            "Auth required",
            "rgba(255,180,84,0.10)",
            "rgba(255,180,84,0.45)",
            "var(--warn, #FFB454)",
        ),
        "rate_limited": (
            "Rate limited",
            "rgba(255,180,84,0.10)",
            "rgba(255,180,84,0.45)",
            "var(--warn, #FFB454)",
        ),
        "not_found": (
            "Not found",
            "rgba(255,107,107,0.10)",
            "rgba(255,107,107,0.45)",
            "var(--bad, #FF6B6B)",
        ),
        "unknown": (
            "Unknown",
            "rgba(245,242,232,0.04)",
            "rgba(245,242,232,0.14)",
            "var(--ink-dim, #B6B2A6)",
        ),
    }

    def _chip_html_for(platform_key: str, current_url: str) -> str:
        state = (link_state.get(platform_key) or {}) if current_url else {}
        status = (state.get("status") or "").strip()
        label, bg, border, ink = _STATUS_CHIP.get(
            status,
            (
                "Idle",
                "rgba(245,242,232,0.04)",
                "rgba(245,242,232,0.14)",
                "var(--ink-dim, #B6B2A6)",
            ),
        )
        # Per-failure inline hint. Without this, the only signal
        # a user gets that their URL was wrong (typo, DNS error,
        # auth wall) is a small severity-coloured pill — easy to
        # miss. A short message right next to the chip turns it
        # into an actionable error.
        failure_hints = {
            "not_found": "URL not reachable — check the spelling.",
            "hard_blocked": "Site is blocking automated reads.",
            "auth_walled": "Profile needs login to read.",
            "rate_limited": "Rate-limited — try Re-read in a minute.",
            "soft_blocked_spa": "Page renders client-side; only the shell loaded.",
            "unknown": "Couldn't classify the response.",
        }
        hint = failure_hints.get(status, "")
        hint_html = ""
        if hint:
            hint_html = (
                f'<span class="muted" style="display:block;margin-top:4px;'
                f'font-size:11px;line-height:1.4;color:var(--warn)">'
                f"{W._h(hint)}</span>"
            )
        # When a link is populated, allow a per-link "re-read now"
        # button so the user can force a fresh capture without
        # resubmitting the whole form.
        reread = ""
        if current_url:
            try:
                reread_url = url_for("organisation_setup_reread", platform=platform_key)
                reread = (
                    f'<form method="POST" action="{W._h(reread_url)}" '
                    'style="display:inline" data-no-loader="1">'
                    '<button type="submit" '
                    'style="font-size:10.5px;padding:3px 8px;background:transparent;'
                    "border:1px solid var(--chrome,var(--border,rgba(245,242,232,0.14)));"
                    "color:var(--ink-dim,#B6B2A6);border-radius:3px;cursor:pointer;"
                    "font-family:var(--font-mono,monospace);text-transform:uppercase;"
                    'letter-spacing:0.10em" title="Force the AI to re-read this link now">'
                    "Re-read</button></form>"
                )
            except Exception:
                reread = ""
        return (
            '<span style="display:inline-flex;align-items:center;gap:8px;'
            'margin-left:8px;vertical-align:middle;flex-wrap:wrap">'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:3px;'
            f"font-size:10.5px;font-family:var(--font-mono,monospace);"
            f"text-transform:uppercase;letter-spacing:0.10em;"
            f'background:{bg};border:1px solid {border};color:{ink}">{W._h(label)}</span>'
            + reread
            + hint_html
            + "</span>"
        )

    social_inputs = ""
    for key, label, placeholder in _PLATFORMS:
        val = social.get(key, "") or ""
        chip = _chip_html_for(key, val)
        social_inputs += (
            f'<div style="margin-bottom:10px">'
            f'<label for="os-social-{W._h(key)}" style="display:flex;align-items:center;flex-wrap:wrap;'
            f'font-size:13px;color:var(--ink-dim);margin-bottom:4px">'
            f'<span>{W._h(label)} <span class="muted" style="font-size:11px">(optional)</span></span>'
            f"{chip}"
            f"</label>"
            f'<input type="url" id="os-social-{W._h(key)}" name="social_{key}" value="{W._h(val)}" '
            f'placeholder="{W._h(placeholder)}" style="{_input_style}"/>'
            f"</div>"
        )

    # Website status chip — same logic, separate label so it can
    # render above the website input.
    _website_chip = _chip_html_for("website", website_url)

    _ORG_TYPES = [
        ("other", "Other / general"),
        ("swimming_club", "Swimming club"),
        ("athletics", "Athletics club"),
        ("football", "Football / rugby / team sport"),
        ("university_society", "University society or sports club"),
        ("corporate_team", "Corporate team"),
    ]
    org_type_opts = "".join(
        f'<option value="{W._h(v)}"{" selected" if v == org_type else ""}>{W._h(l)}</option>'
        for v, l in _ORG_TYPES
    )

    # ---- Manual-mode prefills (issue: setup needs an explicit
    # "build it myself" path with dropdowns for everything) ----------
    from mediahub.brand.tone import TONE_META

    _manual_pal = dict(prof.brand_palette_manual) if prof and prof.brand_palette_manual else {}
    _hex_ok = re.compile(r"^#[0-9a-fA-F]{6}$")

    def _safe_hex(v: str, fallback: str) -> str:
        v = (v or "").strip()
        return v if _hex_ok.fullmatch(v) else fallback

    _m_primary = _safe_hex(
        _manual_pal.get("primary") or (prof.brand_primary if prof else ""), "#A30D2D"
    )
    _m_secondary = _safe_hex(
        _manual_pal.get("secondary") or (prof.brand_secondary if prof else ""), "#1A1A1A"
    )
    _m_accent = _safe_hex(_manual_pal.get("accent") or "", "#D4FF3A")
    _m_fourth = _safe_hex(_manual_pal.get("fourth") or "", "#F4D58D")
    _m_use_fourth_checked = " checked" if (prof and prof.brand_palette_use_fourth) else ""
    _m_tone = (prof.tone or prof.caption_tone) if prof else "warm-club"
    _tone_opts = "".join(
        f'<option value="{W._h(t.value)}"{" selected" if t.value == _m_tone else ""}>'
        f"{W._h(m['label'])} &mdash; {W._h(m['description'])}</option>"
        for t, m in TONE_META.items()
    )
    _m_platforms = set(prof.platforms or []) if prof else set()
    _platform_checks = "".join(
        f'<label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;'
        f'color:var(--ink-dim);margin:0">'
        f'<input type="checkbox" name="platforms" value="{W._h(key)}"'
        f"{' checked' if key in _m_platforms else ''}/> {W._h(label)}</label>"
        for key, label, _ph in _PLATFORMS
    )
    _m_tone_notes = (prof.tone_notes or "") if prof else ""
    _countries_datalist = "".join(f'<option value="{W._h(c)}"></option>' for c in COUNTRIES)
    manual_url = url_for("organisation_setup_manual")

    # Bottom CTA of the AI form. Once the brand preview exists the
    # primary action down here matches the preview's "Looks right —
    # start creating" (it used to still say "Build my brand", which
    # re-ran capture and read as a broken button); re-analyse stays
    # available as the secondary action.
    if prof and prof.is_ready():
        _bottom_cta_html = (
            '<div style="display:flex;align-items:center;gap:14px;margin-bottom:30px;flex-wrap:wrap">'
            f'<a class="btn" href="{url_for("make_page")}" data-mh-cascade="finalise">'
            "Looks right &mdash; start creating &rarr;</a>"
            '<button type="submit" class="btn secondary">Re-analyse my brand &rarr;</button>'
            '<span class="muted" style="font-size:12px">'
            "Re-analysing takes 10&ndash;30 seconds and refreshes voice, palette and logos."
            "</span></div>"
        )
    else:
        _bottom_cta_html = (
            '<div style="display:flex;align-items:center;gap:14px;margin-bottom:30px;flex-wrap:wrap">'
            '<button type="submit" class="btn">Build my brand &rarr;</button>'
            '<span class="muted" style="font-size:12px">'
            "Takes 10&ndash;30 seconds. MediaHub analyses each link to learn your tone and style."
            "</span></div>"
        )

    capture_url = url_for("organisation_setup_capture")

    # A-2: an org can be created but still "not ready" — a name-only AI
    # submit, or an AI capture that read the links but found no usable
    # brand signal. Previously that left the user on an unchanged form
    # while every nav click bounced silently back here (the org-ready
    # gate), with no explanation — a hard lockout. is_ready() is
    # deliberately strict (no anonymous/generic content), so the fix is
    # to explain exactly what unlocks content and give a one-click path
    # to finish. The manual colours are the fastest route, and the
    # manual form already carries over the name/type/country the user
    # typed, so switching tabs loses nothing.
    not_ready_html = ""
    if prof and not prof.is_ready():
        _cap = (prof.brand_capture_status or "").strip().lower()
        if _cap in ("ok", "ok_heuristic"):
            _lead = (
                "We read your links but couldn't find a usable brand signal "
                "(colours, voice or keywords)."
            )
        elif _cap in ("", "no_sources"):
            _lead = (
                "You've given us your name — now MediaHub needs one real "
                "brand signal before it can create content for you."
            )
        else:
            _lead = "We couldn't read enough from your links to unlock content yet."
        not_ready_html = (
            '<div class="card" id="mh-setup-not-ready" role="status" '
            'style="margin-bottom:20px;border:1px solid rgba(255,180,84,0.5);'
            'background:rgba(255,180,84,0.07)">'
            '<h2 style="margin-top:0;font-size:18px;color:var(--ink)">'
            f"{W._h(prof.display_name or 'Your organisation')} "
            "can&rsquo;t make content yet</h2>"
            '<p style="font-size:14px;line-height:1.55;color:var(--ink);margin:0 0 12px">'
            f"{W._h(_lead)} Add <strong>any one</strong> of these and you&rsquo;re in:</p>"
            '<ul style="font-size:13px;line-height:1.7;color:var(--ink-dim);'
            'margin:0 0 14px 18px">'
            "<li>your brand colours (fastest &mdash; a few taps)</li>"
            "<li>a website or social link the AI can read</li>"
            "<li>a brand-guidelines document (PDF, DOCX, TXT)</li>"
            "<li>a couple of sentences on how your club sounds</li>"
            "</ul>"
            '<button type="button" class="btn" '
            "onclick=\"mhSetupMode('manual');var m="
            "document.getElementById('mh-setup-manual-panel');"
            "if(m){m.scrollIntoView({behavior:'smooth',block:'start'});}\">"
            "Pick your colours now &rarr;</button>"
            "</div>"
        )

    # UK legal baseline: DPA acceptance + lawful-basis attestation block,
    # rendered in BOTH setup forms until this workspace has a record.
    _attestation_html = W._org_attestation_form_html(prof)
    # G-3 — this page is the canonical brand home, not just first-run. For a
    # club that already has a brand, drop the permanent "First-run setup"
    # framing so it reads as the brand editor it actually is.
    _returning = bool(prof and prof.is_ready())
    _hero_eyebrow = "Organisation &amp; brand" if _returning else "First-run setup"
    _hero_heading = (
        'Your organisation<br><em class="editorial">&amp; brand.</em>'
        if _returning
        else 'Tell us about<br><em class="editorial">your club.</em>'
    )
    _hero_lede = (
        (
            "Your brand identity — palette, logos, voice and what you talk about. "
            "The engine uses it on every caption, card and reel it makes. Re-run the "
            "AI capture any time, or edit anything by hand below."
        )
        if _returning
        else (
            "The engine learns who you are from your existing online presence "
            "&mdash; your website and social profiles. Paste whichever links you "
            "have and click <b>Build my brand</b>. The AI reads your posts, palette, "
            "tone of voice, and what you talk about, and uses that on every caption "
            "it writes. You can come back any time to re-run it."
        )
    )
    body = f"""
<div style="max-width:840px;margin:0 auto">
<section class="mh-hero" data-lane="01" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">{_hero_eyebrow}</span>
  <h1>{_hero_heading}</h1>
  <p class="lede">
  {_hero_lede}
  </p>
</section>

{llm_banner_html}
{not_ready_html}
{preview_html}

<div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap" role="tablist" aria-label="How do you want to set up?">
  <button type="button" class="btn" id="mh-mode-btn-ai" role="tab" aria-selected="true"
          onclick="mhSetupMode('ai')">AI build &mdash; read my links</button>
  <button type="button" class="btn secondary" id="mh-mode-btn-manual" role="tab" aria-selected="false"
          onclick="mhSetupMode('manual')">Manual build &mdash; I&rsquo;ll pick everything</button>
</div>
<p class="muted" style="font-size:11px;margin:-8px 0 18px">
  Fields marked <span style="color:var(--warn)">*</span> are required.
</p>

<div id="mh-setup-ai-panel">
<form method="POST" action="{capture_url}" enctype="multipart/form-data"
      data-loader-text="Teaching the AI about your organisation"
      data-loader-sub="Reading links, learning scraping strategies, interpreting guidelines, describing logos. This takes 10&ndash;30 seconds.">
<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">Identity</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 18px">
    <div>
      <label class="req" for="os-display-name">Organisation name</label>
      <input id="os-display-name" type="text" name="display_name" required value="{W._h(display_name)}"
             placeholder="e.g. City Aquatics Swimming Club"/>
    </div>
    <div>
      <label for="ai-org-type">Type</label>
      <select id="ai-org-type" name="org_type" style="{_input_style}">{org_type_opts}</select>
    </div>
    <div class="mh-combobox" data-mh-combobox="country">
      <label for="country-input" style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">
        Country
      </label>
      <input id="country-input" type="text" name="country" value="{W._h(country)}"
             placeholder="Start typing your country…"
             autocomplete="off" spellcheck="false"
             role="combobox" aria-autocomplete="list"
             aria-controls="country-options" aria-expanded="false"
             style="{_input_style}"/>
      <ul id="country-options" role="listbox" class="mh-combobox-options" hidden></ul>
    </div>
    <div>
      <label for="os-governing-body">
        Governing body <span class="muted" style="font-size:11px">(optional)</span>
      </label>
      <input id="os-governing-body" type="text" name="governing_body" value="{W._h(governing_body)}"
             placeholder="e.g. Swim England, UKA, BUCS"
             style="{_input_style}"/>
    </div>
  </div>
</div>

<details class="card mh-optional-section" style="margin-bottom:20px" {_links_section_open}>
  <summary style="cursor:pointer;list-style:none;display:flex;align-items:center;
                   justify-content:space-between;gap:14px;flex-wrap:wrap;margin:-4px 0">
    <span style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span style="font-size:18px;font-weight:700;color:var(--ink)">Where can the AI read you?</span>
      <span style="display:inline-block;padding:2px 8px;border-radius:3px;
                   font-size:10.5px;font-family:var(--font-mono,monospace);
                   text-transform:uppercase;letter-spacing:0.10em;
                   background:rgba(245,242,232,0.04);
                   border:1px solid var(--chrome,var(--border,rgba(245,242,232,0.14)));
                   color:var(--ink-dim,#B6B2A6)">Optional</span>
    </span>
    <span class="muted mh-optional-toggle" style="font-size:12px">
      Click to {_links_toggle_verb}
    </span>
  </summary>
  <p class="dim" style="font-size:13px;line-height:1.5;margin:14px 0 14px 0">
    Skip the links if you&rsquo;d rather &mdash; but MediaHub still needs
    <b>one</b> brand signal to unlock content, so add your colours or a
    guidelines document below instead. If you DO paste a link, the AI reads
    it, picks up your palette, tone of voice, characteristic phrases and the
    things you actually talk about, and uses that on every caption it writes
    &mdash; so you never have to explain &ldquo;this is how we sound&rdquo;.
  </p>
  <div style="margin-bottom:14px">
    <label for="os-website-url" style="display:flex;align-items:center;flex-wrap:wrap;
                  font-size:13px;color:var(--ink-dim);margin-bottom:4px">
      <span>Club website <span class="muted" style="font-size:11px">(optional)</span></span>
      {_website_chip}
    </label>
    <input id="os-website-url" type="url" name="website_url" value="{W._h(website_url)}"
           placeholder="https://your-club.example"
           style="{_input_style}"/>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 18px">
    {social_inputs}
  </div>
</details>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">
    Upload a document with your brand guidelines
    <span class="muted" style="font-size:12px;font-weight:400;margin-left:8px">(optional)</span>
  </h2>
  <p class="dim" style="font-size:13px;line-height:1.5;margin:0 0 10px 0">
    If your team already has a brand or style guide, drop it here &mdash; the AI
    reads it so every caption respects your voice.
  </p>
  <details style="margin:0 0 14px 0">
    <summary style="font-size:12px;color:var(--ink-muted);cursor:pointer">Which formats, and what it reads</summary>
    <p class="dim" style="font-size:13px;line-height:1.5;margin:8px 0 0 0">
      Accepts PDF, Word (.docx), plain text, Markdown, HTML, RTF, or a ZIP of any
      of those, up to 25 MB. It extracts the voice rules, prohibited words,
      sponsor mention rules, and key messages so every piece of content the
      engine writes respects them.
    </p>
  </details>
  <label for="os-brand-guidelines">Brand guidelines (optional)</label>
  <input id="os-brand-guidelines" type="file" name="brand_guidelines_file"
         accept=".pdf,.docx,.txt,.md,.markdown,.rtf,.html,.htm,.zip,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,text/html,application/zip"/>
  {_gl_status_html}
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">
    Logos
    <span class="muted" style="font-size:12px;font-weight:400;margin-left:8px">(optional, multiple)</span>
  </h2>
  <p class="dim" style="font-size:13px;line-height:1.5;margin:0 0 10px 0">
    Drop in every logo variant your club has &mdash; the AI picks the right one
    automatically for each card.
  </p>
  <details style="margin:0 0 14px 0">
    <summary style="font-size:12px;color:var(--ink-muted);cursor:pointer">Which formats, and how they're used</summary>
    <p class="dim" style="font-size:13px;line-height:1.5;margin:8px 0 0 0">
      Full-colour, mono, wordmark, icon, print versions. PNG, JPG, SVG, WEBP,
      GIF, BMP, TIFF, HEIC, AVIF, ICO, PDF, EPS, AI, PSD, INDD, Sketch, Figma,
      XD, Affinity files all accepted &mdash; if it's a logo format, we'll take
      it. The AI describes each one so motion graphics, story cards, and sponsor
      posts pick the right variant automatically (e.g. white mono on dark
      backgrounds, the icon when the layout is square).
    </p>
  </details>
  <label for="logos-input" id="logos-drop-zone" class="mh-drop-zone">
    <div class="mh-drop-zone-inner">
      <strong>Click to choose</strong> or drag files here
      <div class="muted" style="font-size:11px;margin-top:4px">
        As many as you have &middot; up to 50 MB each &middot; any logo format
      </div>
    </div>
  </label>
  <input id="logos-input" type="file" name="brand_logos" multiple
         accept="image/*,application/pdf,application/postscript,application/illustrator,application/x-photoshop,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tiff,.tif,.heic,.heif,.avif,.ico,.jxl,.jp2,.svg,.eps,.ai,.cdr,.wmf,.emf,.pdf,.psd,.indd,.sketch,.fig,.xd,.afdesign,.afphoto,.exr,.tga,.dng"
         style="display:none"/>
  <div id="logos-pending" class="muted" style="font-size:11px;margin-top:8px"></div>
  {_logo_reject_html}
  {_logos_grid_html}
</div>

{_attestation_html}
{_bottom_cta_html}
</form>
</div>

<div id="mh-setup-manual-panel" style="display:none">
<form method="POST" action="{manual_url}" enctype="multipart/form-data">
<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">Identity</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 18px">
    <div>
      <label class="req" for="ms-display-name">Organisation name</label>
      <input id="ms-display-name" type="text" name="display_name" required value="{W._h(display_name)}"
             placeholder="e.g. City Aquatics Swimming Club"/>
    </div>
    <div>
      <label for="ms-org-type">Type</label>
      <select id="ms-org-type" name="org_type" style="{_input_style}">{org_type_opts}</select>
    </div>
    <div>
      <label for="ms-country">Country</label>
      <input id="ms-country" type="text" name="country" value="{W._h(country)}"
             list="mh-countries-list" placeholder="Start typing your country&hellip;"
             autocomplete="off" style="{_input_style}"/>
    </div>
    <div>
      <label for="ms-governing-body">Governing body <span class="muted" style="font-size:11px">(optional)</span></label>
      <input id="ms-governing-body" type="text" name="governing_body" value="{W._h(governing_body)}"
             placeholder="e.g. Swim England, UKA, BUCS" style="{_input_style}"/>
    </div>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">Voice &amp; platforms</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 18px">
    <div>
      <label for="ms-caption-tone">Caption tone</label>
      <select id="ms-caption-tone" name="caption_tone" style="{_input_style}">{_tone_opts}</select>
    </div>
    <div>
      <label id="ms-platforms-label">Platforms you post to</label>
      <div role="group" aria-labelledby="ms-platforms-label"
           style="display:flex;flex-wrap:wrap;gap:12px;margin-top:8px">{_platform_checks}</div>
    </div>
  </div>
  <div style="margin-top:14px">
    <label for="ms-tone-notes">How do you sound? <span class="muted" style="font-size:11px">(optional)</span></label>
    <textarea id="ms-tone-notes" name="tone_notes" rows="3"
              placeholder="e.g. Friendly and proud, first names only, never use exclamation marks, always thank the officials."
              style="{_input_style};resize:vertical">{W._h(_m_tone_notes)}</textarea>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">Brand colours</h2>
  <p class="dim" style="font-size:13px;line-height:1.5;margin:0 0 14px 0">
    Exactly what you pick here is what every graphic, card, and reel uses.
    Nothing is inferred in manual mode.
  </p>
  <div style="display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end">
    <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--ink-dim)">Primary
      <input type="color" name="manual_primary" value="{W._h(_m_primary)}"
             style="width:64px;height:40px;border:1px solid var(--border);border-radius:6px;background:var(--bg);padding:2px"/>
    </label>
    <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--ink-dim)">Secondary
      <input type="color" name="manual_secondary" value="{W._h(_m_secondary)}"
             style="width:64px;height:40px;border:1px solid var(--border);border-radius:6px;background:var(--bg);padding:2px"/>
    </label>
    <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--ink-dim)">Accent
      <input type="color" name="manual_accent" value="{W._h(_m_accent)}"
             style="width:64px;height:40px;border:1px solid var(--border);border-radius:6px;background:var(--bg);padding:2px"/>
    </label>
    <label style="display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-dim);margin:0 0 10px 0">
      <input type="checkbox" name="manual_use_fourth" value="1"{_m_use_fourth_checked}
             onchange="var f=document.getElementById('ms-fourth-wrap'); if (f) f.style.display = this.checked ? 'flex' : 'none';"/>
      Add a fourth brand colour
    </label>
    <label id="ms-fourth-wrap" style="display:{"flex" if _m_use_fourth_checked else "none"};flex-direction:column;gap:6px;font-size:13px;color:var(--ink-dim)">Fourth
      <input type="color" name="manual_fourth" value="{W._h(_m_fourth)}"
             style="width:64px;height:40px;border:1px solid var(--border);border-radius:6px;background:var(--bg);padding:2px"/>
    </label>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">
    Logos
    <span class="muted" style="font-size:12px;font-weight:400;margin-left:8px">(optional, multiple)</span>
  </h2>
  <input type="file" name="brand_logos" multiple
         accept="image/*,application/pdf,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tiff,.svg,.eps,.ai,.pdf"/>
</div>

{_attestation_html}
<div style="display:flex;align-items:center;gap:14px;margin-bottom:30px;flex-wrap:wrap">
  <button type="submit" class="btn">Create my organisation &rarr;</button>
  <span class="muted" style="font-size:12px">
    Instant &mdash; no AI reading involved. You can switch to AI build later to enrich the voice.
  </span>
</div>
</form>
</div>
<datalist id="mh-countries-list">{_countries_datalist}</datalist>
</div>

<script>
function mhSetupMode(mode) {{
  var isAi = mode === 'ai';
  var ai = document.getElementById('mh-setup-ai-panel');
  var man = document.getElementById('mh-setup-manual-panel');
  var bAi = document.getElementById('mh-mode-btn-ai');
  var bMan = document.getElementById('mh-mode-btn-manual');
  if (ai) ai.style.display = isAi ? '' : 'none';
  if (man) man.style.display = isAi ? 'none' : '';
  if (bAi) {{ bAi.className = isAi ? 'btn' : 'btn secondary'; bAi.setAttribute('aria-selected', String(isAi)); }}
  if (bMan) {{ bMan.className = isAi ? 'btn secondary' : 'btn'; bMan.setAttribute('aria-selected', String(!isAi)); }}
  // A-7: remember the chosen mode so a validation redirect or a reload
  // reopens the tab the user was working in (compounds the A-2 "pick your
  // colours" shortcut, which lands on the manual tab).
  try {{ sessionStorage.setItem('mhSetupMode', mode); }} catch (e) {{}}
}}
(function() {{
  // Restore the last-used tab on load: an explicit ?mode= wins, else the
  // remembered pick. Default (AI) needs no action.
  try {{
    var want = (new URLSearchParams(window.location.search)).get('mode')
               || sessionStorage.getItem('mhSetupMode');
    if (want === 'manual') {{ mhSetupMode('manual'); }}
  }} catch (e) {{}}
}})();
</script>

<style>
.mh-combobox {{ position: relative; }}
.mh-combobox-options {{
  position: absolute;
  top: calc(100% + 4px);
  left: 0; right: 0;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  background: var(--surface, var(--panel, #14171F));
  border: 1px solid var(--chrome, var(--border, rgba(245,242,232,0.14)));
  border-radius: 6px;
  max-height: 260px;
  overflow-y: auto;
  box-shadow: 0 14px 32px rgba(0,0,0,0.45);
  z-index: 60;
}}
.mh-combobox-options li {{
  padding: 8px 14px;
  font-size: 14px;
  color: var(--ink, #F5F2E8);
  cursor: pointer;
  line-height: 1.3;
}}
.mh-combobox-options li:hover,
.mh-combobox-options li.mh-combobox-active {{
  background: color-mix(in oklab, var(--lane) 10%, transparent);
  color: var(--lane, var(--accent, #D4FF3A));
}}
.mh-combobox-options li.mh-combobox-empty {{
  color: var(--ink-muted, var(--ink-dim, #7A7869));
  font-style: italic;
  cursor: default;
}}
.mh-combobox-options li.mh-combobox-empty:hover {{
  background: transparent;
  color: var(--ink-muted, var(--ink-dim, #7A7869));
}}

.mh-drop-zone {{
  display: block;
  border: 1px dashed var(--chrome, var(--border, rgba(245,242,232,0.30)));
  border-radius: 8px;
  padding: 22px;
  text-align: center;
  cursor: pointer;
  background:
    repeating-linear-gradient(45deg, color-mix(in oklab, var(--lane) 2%, transparent) 0 10px,
                              transparent 10px 20px),
    var(--surface, var(--panel, #14171F));
  color: var(--ink-dim, var(--ink-muted, #B6B2A6));
  transition: border-color 150ms ease, color 150ms ease, background 150ms ease;
}}
.mh-drop-zone:hover {{
  border-color: var(--lane, var(--accent, #D4FF3A));
  color: var(--ink, #F5F2E8);
}}
.mh-drop-zone.is-dragover {{
  border-color: var(--lane, var(--accent, #D4FF3A));
  background: color-mix(in oklab, var(--lane) 6%, transparent);
  color: var(--ink, #F5F2E8);
}}
.mh-drop-zone-inner strong {{ color: var(--ink, #F5F2E8); font-weight: 600; }}

.mh-logo-card {{
  transition: transform 150ms ease, border-color 150ms ease;
}}
.mh-logo-card:hover {{
  transform: translateY(-1px);
  border-color: var(--lane, var(--accent, #D4FF3A));
}}

/* M2 — collapsible "Where can AI read you" section. The default
   <details> marker is hidden; we surface our own toggle hint on the
   right side of the summary instead. */
.mh-optional-section > summary::-webkit-details-marker {{ display: none; }}
.mh-optional-section > summary {{ list-style: none; }}
.mh-optional-section[open] .mh-optional-toggle::before {{ content: "▾ "; }}
.mh-optional-section:not([open]) .mh-optional-toggle::before {{ content: "▸ "; }}
.mh-optional-section[open] .mh-optional-toggle::after {{ content: ""; }}
.mh-optional-section:not([open]) .mh-optional-toggle::after {{ content: ""; }}
</style>
<script>
(function() {{
  var COUNTRIES = {_countries_js_array};
  var MAX_RENDER = 250;

  function escapeHTML(s) {{
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }}

  document.querySelectorAll('[data-mh-combobox="country"]').forEach(function(box) {{
    var input = box.querySelector('input[name="country"]');
    var listEl = box.querySelector('.mh-combobox-options');
    if (!input || !listEl) return;
    var activeIdx = -1;

    function render(filter) {{
      var q = (filter || '').trim().toLowerCase();
      var matches;
      if (!q) {{
        matches = COUNTRIES.slice();
      }} else {{
        matches = COUNTRIES.filter(function(c) {{
          return c.toLowerCase().indexOf(q) !== -1;
        }});
        matches.sort(function(a, b) {{
          var ap = a.toLowerCase().indexOf(q);
          var bp = b.toLowerCase().indexOf(q);
          if (ap !== bp) return ap - bp;
          return a.localeCompare(b);
        }});
      }}
      if (matches.length === 0) {{
        listEl.innerHTML = '<li class="mh-combobox-empty" role="option" aria-disabled="true">No matches — type a different country.</li>';
      }} else {{
        listEl.innerHTML = matches.slice(0, MAX_RENDER).map(function(c) {{
          var esc = escapeHTML(c);
          return '<li role="option" data-value="' + esc + '" tabindex="-1">' + esc + '</li>';
        }}).join('');
      }}
      listEl.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      activeIdx = -1;
    }}

    function close() {{
      listEl.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      activeIdx = -1;
    }}

    function pick(value) {{
      input.value = value;
      close();
      input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }}

    function updateActive() {{
      var items = listEl.querySelectorAll('li[role="option"]:not([aria-disabled="true"])');
      items.forEach(function(it, i) {{
        if (i === activeIdx) {{
          it.classList.add('mh-combobox-active');
          it.scrollIntoView({{ block: 'nearest' }});
        }} else {{
          it.classList.remove('mh-combobox-active');
        }}
      }});
    }}

    input.addEventListener('input', function() {{ render(input.value); }});
    input.addEventListener('focus', function() {{ render(input.value); }});
    input.addEventListener('blur', function() {{
      // small delay so a click on a <li> registers before we hide
      setTimeout(close, 160);
    }});

    input.addEventListener('keydown', function(e) {{
      var items = listEl.querySelectorAll('li[role="option"]:not([aria-disabled="true"])');
      if (e.key === 'ArrowDown') {{
        e.preventDefault();
        if (listEl.hidden) {{ render(input.value); return; }}
        if (items.length === 0) return;
        activeIdx = (activeIdx + 1) % items.length;
        updateActive();
      }} else if (e.key === 'ArrowUp') {{
        e.preventDefault();
        if (listEl.hidden) {{ render(input.value); return; }}
        if (items.length === 0) return;
        activeIdx = activeIdx <= 0 ? items.length - 1 : activeIdx - 1;
        updateActive();
      }} else if (e.key === 'Enter') {{
        if (!listEl.hidden && activeIdx >= 0 && items[activeIdx]) {{
          e.preventDefault();
          pick(items[activeIdx].getAttribute('data-value'));
        }}
      }} else if (e.key === 'Escape') {{
        if (!listEl.hidden) {{
          e.preventDefault();
          close();
        }}
      }} else if (e.key === 'Tab') {{
        close();
      }}
    }});

    listEl.addEventListener('mousedown', function(e) {{
      var li = e.target.closest('li[role="option"]');
      if (!li || li.getAttribute('aria-disabled') === 'true') return;
      e.preventDefault(); // keep focus on the input
      pick(li.getAttribute('data-value'));
    }});
  }});
}})();

(function () {{
  // ---- Multi-logo drag-and-drop (D1) ----
  var dropZone = document.getElementById('logos-drop-zone');
  var fileInput = document.getElementById('logos-input');
  var pending = document.getElementById('logos-pending');
  if (!dropZone || !fileInput || !pending) return;

  function showPending() {{
    if (!fileInput.files || !fileInput.files.length) {{
      pending.textContent = '';
      return;
    }}
    var names = [];
    for (var i = 0; i < fileInput.files.length; i++) {{
      names.push(fileInput.files[i].name);
    }}
    pending.textContent = names.length + ' file' + (names.length === 1 ? '' : 's')
                          + ' ready to upload: ' + names.join(', ');
  }}

  fileInput.addEventListener('change', showPending);

  ['dragenter', 'dragover'].forEach(function (ev) {{
    dropZone.addEventListener(ev, function (e) {{
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('is-dragover');
    }});
  }});

  ['dragleave', 'drop'].forEach(function (ev) {{
    dropZone.addEventListener(ev, function (e) {{
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('is-dragover');
    }});
  }});

  dropZone.addEventListener('drop', function (e) {{
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    // Replace the input's file list with the dropped files.
    var dt = new DataTransfer();
    for (var i = 0; i < e.dataTransfer.files.length; i++) {{
      dt.items.add(e.dataTransfer.files[i]);
    }}
    fileInput.files = dt.files;
    showPending();
  }});
}})();
</script>
"""
    return W._layout("Set up your organisation", body, active="settings")


def organisation_setup_capture():
    """Run the AI ingestion on the submitted URLs, save the profile,
    pin it into session, and bounce back to the setup page so the
    user can see what was learned before they click through."""
    display_name = (request.form.get("display_name") or "").strip()
    if not display_name:
        # The HTML form already requires it, but defend in depth.
        return redirect(url_for("organisation_setup"))

    # Slug the org name into a stable, filesystem-safe profile id.
    # If the user already has an active profile, reuse its id so
    # we don't pile up duplicates when they re-run setup.
    existing = W._active_profile()
    if existing and existing.display_name.strip().lower() == display_name.lower():
        # Re-running setup for the org we're already signed in to.
        profile_id = existing.profile_id
    else:
        raw = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
        profile_id = raw[:48] or "default"
        # If a profile with this slug already exists for the SAME org
        # name, reuse it. Re-running setup — commonly while signed
        # out, which is now the default state — must UPDATE the real
        # profile rather than orphan a "<slug>-<uuid>" clone that the
        # freshly extracted colours and uploaded logos land on while
        # the original profile stays empty. Only suffix when the slug
        # genuinely collides with a DIFFERENT organisation, so we
        # never clobber someone else's profile.
        slug_match = W.load_profile(profile_id)
        if slug_match is not None and (
            slug_match.display_name.strip().lower() != display_name.lower()
            or not W._session_can_use_profile(profile_id)
        ):
            # Different organisation under this slug — or a bound
            # workspace this session may not touch (PC.3): either way,
            # set up a fresh profile instead of clobbering it.
            profile_id = f"{profile_id}-{W.uuid.uuid4().hex[:6]}"

    blocked = W._require_org_data_attestation(profile_id)
    if blocked is not None:
        return blocked

    _setup_is_new_profile = W.load_profile(profile_id) is None
    prof = W.load_profile(profile_id) or W.ClubProfile(
        profile_id=profile_id,
        display_name=display_name,
    )
    prof.display_name = display_name
    prof.org_type = (request.form.get("org_type") or "other").strip()
    raw_country = (request.form.get("country") or "").strip()
    if raw_country:
        from mediahub.web._countries import COUNTRIES

        # Case-insensitive canonicalisation — if the user typed
        # "united kingdom" the combobox will already have offered the
        # canonical "United Kingdom", but defending in depth in case
        # someone bypasses the dropdown (paste, autofill, JS off).
        canon = next(
            (c for c in COUNTRIES if c.casefold() == raw_country.casefold()),
            None,
        )
        prof.country = canon or raw_country
    else:
        prof.country = ""
    prof.governing_body = (request.form.get("governing_body") or "").strip()

    website_url = (request.form.get("website_url") or "").strip()
    social_links: dict[str, str] = {}
    for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin"):
        v = (request.form.get(f"social_{key}") or "").strip()
        if v:
            social_links[key] = v
    prof.social_links = social_links

    # ---- AI capture (handles its own errors, never raises) ----
    try:
        from mediahub.brand.social_dna import capture_from_socials

        result = capture_from_socials(
            social_links=social_links,
            website_url=website_url,
            force=False,
        )
    except Exception as e:
        result = {"brand_capture_status": f"error: {e}"}

    status = (result or {}).get("brand_capture_status", "")
    # Per-source palette signals from every captured link. Kept in a
    # local so the unified palette resolver below can combine these
    # with the (yet-to-be-ingested) guidelines doc + logos. Survives
    # the "no_sources" branch as an empty dict so resolution still
    # runs when only guidelines / logos were supplied.
    link_palette_signals: dict[str, list[str]] = {}
    link_colour_usage: dict[str, list] = {}
    if status in ("ok", "ok_heuristic"):
        for k in (
            "brand_voice_summary",
            "brand_keywords",
            "brand_palette_extracted",
            "brand_logo_url",
            "brand_typography_hint",
            "brand_phrases_to_avoid",
            "brand_phrases_to_use",
            "brand_source_url",
            "brand_captured_at",
            "brand_capture_status",
        ):
            if k in result:
                setattr(prof, k, result[k])
        vp = result.get("voice_profile") or {}
        if isinstance(vp, dict) and vp:
            prof.voice_profile = vp
        pal = result.get("brand_palette_extracted") or {}
        if pal.get("primary") and prof.brand_primary in ("", "#0A2540", "#A30D2D"):
            prof.brand_primary = pal["primary"]
        if pal.get("secondary") and prof.brand_secondary in ("", "#000000"):
            prof.brand_secondary = pal["secondary"]
        # Per-link audit state for the next-page transfer audits
        # (E6-E8): the user wants to be able to see, for each link,
        # what the AI extracted, which playbook served it, and
        # whether drift detection regenerated the strategy.
        lcs = result.get("link_capture_state") or {}
        if isinstance(lcs, dict):
            prof.link_capture_state = lcs
        sigs = result.get("brand_palette_signals") or {}
        if isinstance(sigs, dict):
            link_palette_signals = {str(k): list(v) for k, v in sigs.items() if isinstance(v, list)}
        usage = result.get("brand_palette_usage") or {}
        if isinstance(usage, dict):
            link_colour_usage = {str(k): list(v) for k, v in usage.items() if isinstance(v, list)}
    elif status == "no_sources":
        # User submitted no links at all — keep the identity fields
        # and let them try again. The gate will keep them here until
        # is_ready() returns True.
        pass
    else:
        # Any other status: still save what we have so we don't lose
        # the identity fields the user just typed. Persist
        # link_capture_state too so per-link diagnostic chips render
        # the actual failure mode (auth_walled, not_found, …)
        # instead of falling back to "Idle".
        prof.brand_capture_status = status
        lcs = result.get("link_capture_state") or {}
        if isinstance(lcs, dict):
            prof.link_capture_state = lcs

    # ---- Optional brand-guidelines document upload ----
    # Additive: the AI consumes whatever file the user provided AND
    # the website/socials separately. If no file is attached, this
    # block is a no-op and any previously-uploaded guidelines stay
    # intact on the profile.
    upload = request.files.get("brand_guidelines_file")
    if upload and upload.filename:
        file_bytes = upload.read() or b""
        # Phase 1.5 — reject obvious binary uploads (PNG/JPG
        # screenshots, MP4, etc.) at the boundary so the binary
        # bytes never reach interpret_guidelines. The downstream
        # guideline parser already has a magic-byte check but
        # surfacing it as a clean user-visible status here is
        # honest: we tell them "that file type isn't supported"
        # rather than silently store a garbage summary that
        # poisons every later caption.
        BINARY_MAGIC = (
            b"\x89PNG\r\n\x1a\n",
            b"\xff\xd8\xff",
            b"GIF87a",
            b"GIF89a",
            b"BM",
            b"\x00\x00\x01\x00",
            b"II*\x00",
            b"MM\x00*",
            b"\x7fELF",
            b"MZ",
        )
        ext = (upload.filename.rsplit(".", 1)[-1] or "").lower() if "." in upload.filename else ""
        IMAGE_EXTS = {
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
            "tiff",
            "tif",
            "bmp",
            "ico",
            "heic",
            "heif",
            "avif",
        }
        looks_binary = ext in IMAGE_EXTS or any(file_bytes.startswith(sig) for sig in BINARY_MAGIC)
        if looks_binary:
            # Friendly status — don't pollute prof.brand_guidelines.
            prof.brand_guidelines_status = (
                f"unsupported_binary: {upload.filename!r} looks like an "
                "image / binary file. Brand guidelines must be a text "
                "document (PDF, DOCX, TXT, RTF, MD)."
            )
            prof.brand_guidelines_filename = upload.filename
            prof.brand_guidelines_byte_size = len(file_bytes)
            # Clear any prior good guidelines? No — preserve them.
        elif file_bytes:
            try:
                from mediahub.brand.guidelines import ingest_guidelines_file

                g_payload = ingest_guidelines_file(upload.filename, file_bytes)
            except Exception as e:
                g_payload = {
                    "brand_guidelines": {},
                    "brand_guidelines_raw_excerpt": "",
                    "brand_guidelines_filename": upload.filename,
                    "brand_guidelines_uploaded_at": "",
                    "brand_guidelines_status": f"error: {e}",
                    "brand_guidelines_extractor": "",
                    "brand_guidelines_byte_size": len(file_bytes),
                }
            for k, v in g_payload.items():
                setattr(prof, k, v)

    # ---- Multi-logo upload (D1) -----------------------------------
    # Accept any number of files under name="brand_logos". Each is
    # persisted under data/club_logos/<profile_id>/ and a metadata
    # dict appended to prof.brand_logos. AI vision (if available)
    # produces a short description + dominant-colour swatches so
    # downstream image/motion generators can pick the right variant.
    logo_uploads = request.files.getlist("brand_logos")
    if logo_uploads:
        from mediahub.brand import logos as _logos_mod

        current_logos = list(prof.brand_logos or [])
        logo_rejections: list[dict] = []
        for upload in logo_uploads:
            if not upload or not upload.filename:
                continue
            try:
                raw = upload.read() or b""
            except Exception:
                logo_rejections.append({"filename": upload.filename, "reason": "couldn’t be read"})
                continue
            if not raw:
                logo_rejections.append(
                    {"filename": upload.filename, "reason": "the file was empty"}
                )
                continue
            try:
                meta = _logos_mod.store_logo(
                    profile_id=prof.profile_id,
                    filename=upload.filename,
                    file_bytes=raw,
                    existing_logos=current_logos,
                )
            except ValueError as e:
                # D-16: stash the reason so it's surfaced on the next render
                # instead of the file silently vanishing from the grid.
                W.log.info("logo rejected: %s", e)
                logo_rejections.append({"filename": upload.filename, "reason": str(e)})
                continue
            except Exception as e:
                W.log.warning("logo store failed: %s", e)
                logo_rejections.append({"filename": upload.filename, "reason": "couldn’t be saved"})
                continue
            current_logos.append(meta)
        prof.brand_logos = current_logos
        if logo_rejections:
            session["logo_rejections"] = logo_rejections

    # ---- Unified palette resolution across ALL sources ------------
    # Previously the palette displayed on the confirmation page came
    # only from the website link (richest single source). The user
    # now expects the AI to reason over every signal the org
    # supplied: website + each social link + the brand-guidelines
    # document + every uploaded logo. ``brand.palette.resolve_palette``
    # does that AI pass; we re-run it here every save so adding a
    # new logo or replacing the guidelines doc updates the pick.
    try:
        from mediahub.brand import palette as _palette

        sources = _palette.gather_colour_sources(
            link_palette_signals=link_palette_signals,
            brand_guidelines=prof.brand_guidelines or {},
            brand_logos=prof.brand_logos or [],
            colour_usage=link_colour_usage,
        )
        if sources:
            # The AI always CONSIDERS a fourth colour and decides
            # itself whether one genuinely exists (the prompt defaults
            # the slot to empty). The user's tickbox on the preview
            # remains a manual override via /organisation/setup/palette.
            resolved = _palette.resolve_palette(
                org_name=prof.display_name,
                voice_summary=prof.brand_voice_summary or "",
                sources=sources,
                allow_fourth=True,
            )
            # Preserve any existing primary/secondary/accent that the
            # resolver didn't fill (e.g. when the user hadn't uploaded
            # anything new and the resolver returned an empty pick).
            if resolved:
                merged = dict(prof.brand_palette_extracted or {})
                for k in _palette.ALL_SLOTS:
                    if resolved.get(k):
                        merged[k] = resolved[k]
                # Mirror the AI's fourth-colour decision, unless the
                # user pinned a fourth manually. "No fourth" must also
                # CLEAR a stale fourth from an earlier capture — that
                # carry-over is exactly how every org ended up with a
                # fourth colour whether it had one or not.
                if not (prof.brand_palette_manual or {}).get(_palette.FOURTH_SLOT):
                    if resolved.get(_palette.FOURTH_SLOT):
                        prof.brand_palette_use_fourth = True
                    else:
                        merged.pop(_palette.FOURTH_SLOT, None)
                        prof.brand_palette_use_fourth = False
                prof.brand_palette_extracted = merged
                prof.brand_palette_reasoning = resolved.get("reasoning", "")
        prof.brand_palette_sources = sources
    except Exception as e:
        # Never block save on palette resolution; fall back silently.
        W.log.info("unified palette resolve failed: %s", e)

    # ---- AI-derive operating profile from the assembled context ----
    # One LLM call here means zero LLM calls per page render. The
    # derived dict carries the org-specific tone prose, ranking
    # weights, type phrases and artefact intents that every content
    # tool consults via the lookup helpers in brand.derived.
    try:
        from mediahub.brand.derived import derive_operating_profile

        prof.brand_operating_profile = derive_operating_profile(prof)
    except Exception as e:
        # Never block save on a derivation failure — consumers
        # transparently fall back to the hardcoded defaults.
        prof.brand_operating_profile = {
            "tone_prose": {},
            "achievement_priorities": {},
            "type_phrases": {},
            "artefact_voice": {},
            "status": f"error: {e}",
        }

    W.save_profile(prof)
    if _setup_is_new_profile:
        # PC.3: setup-created workspaces bind to their signed-in creator.
        W._bind_creator_if_signed_in(prof.profile_id)
    W._pin_active_profile(prof.profile_id)
    return redirect(url_for("organisation_setup"))


def organisation_setup_manual():
    """Create or update an organisation profile with NO AI capture.

    Manual mode: the user picks everything the system needs from
    dropdowns and pickers — type, country, tone, platforms, brand
    colours, logos. Nothing is inferred and nothing is invented:
    the chosen colours land on ``brand_palette_manual`` (the
    user-override slot that wins over any AI pick) and the profile
    is usable immediately.
    """
    display_name = (request.form.get("display_name") or "").strip()
    if not display_name:
        return redirect(url_for("organisation_setup"))

    # Same slug / reuse / collision rules as the AI capture path.
    existing = W._active_profile()
    if existing and existing.display_name.strip().lower() == display_name.lower():
        profile_id = existing.profile_id
    else:
        raw = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
        profile_id = raw[:48] or "default"
        slug_match = W.load_profile(profile_id)
        if slug_match is not None and (
            slug_match.display_name.strip().lower() != display_name.lower()
            or not W._session_can_use_profile(profile_id)
        ):
            profile_id = f"{profile_id}-{W.uuid.uuid4().hex[:6]}"

    blocked = W._require_org_data_attestation(profile_id)
    if blocked is not None:
        return blocked

    _is_new_profile = W.load_profile(profile_id) is None
    prof = W.load_profile(profile_id) or W.ClubProfile(
        profile_id=profile_id,
        display_name=display_name,
    )
    prof.display_name = display_name
    prof.org_type = (request.form.get("org_type") or "other").strip()
    raw_country = (request.form.get("country") or "").strip()
    if raw_country:
        from mediahub.web._countries import COUNTRIES

        canon = next(
            (c for c in COUNTRIES if c.casefold() == raw_country.casefold()),
            None,
        )
        prof.country = canon or raw_country
    else:
        prof.country = ""
    prof.governing_body = (request.form.get("governing_body") or "").strip()

    tone = (request.form.get("caption_tone") or "warm-club").strip()
    if tone not in ("warm-club", "hype", "data-led"):
        tone = "warm-club"
    prof.tone = tone
    prof.caption_tone = tone

    platforms = [
        p
        for p in request.form.getlist("platforms")
        if p in ("instagram", "facebook", "twitter", "tiktok", "linkedin")
    ]
    prof.platforms = platforms

    notes = (request.form.get("tone_notes") or "").strip()
    if notes:
        prof.tone_notes = notes

    # Colours: validate as #rrggbb; invalid entries are dropped, never
    # guessed. Manual picks land on brand_palette_manual (per-slot
    # winner over any AI pick) + the legacy two mirror fields.
    hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")

    def _col(name: str) -> str:
        v = (request.form.get(name) or "").strip()
        return v if hex_re.fullmatch(v) else ""

    manual_pal = dict(prof.brand_palette_manual or {})
    for slot, field_name in (
        ("primary", "manual_primary"),
        ("secondary", "manual_secondary"),
        ("accent", "manual_accent"),
    ):
        v = _col(field_name)
        if v:
            manual_pal[slot] = v
    # HTML checkbox truthiness — the form value is "on" or absent, never a
    # NaN literal; bool() is the intended presence test. (pre-existing web.py
    # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    use_fourth = bool(request.form.get("manual_use_fourth"))
    fourth = _col("manual_fourth") if use_fourth else ""
    if fourth:
        manual_pal["fourth"] = fourth
    elif not use_fourth:
        manual_pal.pop("fourth", None)
    prof.brand_palette_manual = manual_pal
    prof.brand_palette_use_fourth = use_fourth
    if manual_pal.get("primary"):
        prof.brand_primary = manual_pal["primary"]
    if manual_pal.get("secondary"):
        prof.brand_secondary = manual_pal["secondary"]

    # Logos: same ingest as the AI path (storage + optional vision
    # description); skipping AI here would just mean unlabelled logos.
    logo_uploads = request.files.getlist("brand_logos")
    if logo_uploads:
        from mediahub.brand import logos as _logos_mod

        current_logos = list(prof.brand_logos or [])
        logo_rejections: list[dict] = []
        for upload in logo_uploads:
            if not upload or not upload.filename:
                continue
            try:
                raw_bytes = upload.read() or b""
            except Exception:
                logo_rejections.append({"filename": upload.filename, "reason": "couldn’t be read"})
                continue
            if not raw_bytes:
                logo_rejections.append(
                    {"filename": upload.filename, "reason": "the file was empty"}
                )
                continue
            try:
                meta = _logos_mod.store_logo(
                    profile_id=prof.profile_id,
                    filename=upload.filename,
                    file_bytes=raw_bytes,
                    existing_logos=current_logos,
                )
            except ValueError as e:
                # D-16: stash the reason so a rejected logo is explained on
                # the next render rather than silently missing from the grid.
                W.log.info("manual setup: logo rejected: %s", e)
                logo_rejections.append({"filename": upload.filename, "reason": str(e)})
                continue
            except Exception as e:
                W.log.warning("manual setup: logo store failed: %s", e)
                logo_rejections.append({"filename": upload.filename, "reason": "couldn’t be saved"})
                continue
            current_logos.append(meta)
        prof.brand_logos = current_logos
        if logo_rejections:
            session["logo_rejections"] = logo_rejections

    W.save_profile(prof)
    if _is_new_profile:
        W._bind_creator_if_signed_in(prof.profile_id)
    W._pin_active_profile(prof.profile_id)
    return redirect(url_for("organisation_setup"))


def organisation_setup_palette():
    """Persist a user-confirmed brand palette override.

    The AI-driven resolver runs in ``organisation_setup_capture`` over
    every signal the org supplied (links + guidelines doc + logos).
    That pick is shown back to the user on the setup preview card so
    they can confirm or correct. This endpoint accepts:

      - palette_primary / palette_secondary / palette_accent  (hex)
      - palette_use_fourth ("on" when the tickbox is enabled)
      - palette_fourth                                         (hex, optional)

    A blank field clears that slot so the AI's value can resurface on
    the next render. The route never raises; bad inputs are filtered
    out by ``palette.sanitise_manual_palette``.
    """
    prof = W._active_profile()
    if not prof:
        return redirect(url_for("organisation_setup"))

    use_fourth = (request.form.get("palette_use_fourth") or "").strip().lower() in (
        "on",
        "true",
        "1",
        "yes",
    )
    from mediahub.brand import palette as _palette

    # The blankable ``palette_<slot>_hex`` text field is authoritative: the
    # sibling ``<input type="color">`` can never submit an empty value, so
    # reading it would make "leave a slot blank to fall back to the AI's
    # pick" (promised on the form) impossible — every save would freeze the
    # AI palette as a manual override. Prefer the hex mirror when the browser
    # sent it; fall back to the colour input for non-browser callers (and the
    # test corpus) that post only ``palette_<slot>``.
    def _pal_slot(slot: str) -> str:
        hexv = request.form.get(f"palette_{slot}_hex")
        if hexv is not None:
            return hexv.strip()
        return (request.form.get(f"palette_{slot}") or "").strip()

    manual = _palette.sanitise_manual_palette(
        primary=_pal_slot("primary"),
        secondary=_pal_slot("secondary"),
        accent=_pal_slot("accent"),
        fourth=_pal_slot("fourth"),
        include_fourth=use_fourth,
    )
    prof.brand_palette_manual = manual
    prof.brand_palette_use_fourth = use_fourth

    # Unticking the 4th-colour box must always drop the stale 4th
    # slot from the AI's pick — otherwise the next render still
    # surfaces a fourth swatch the user just opted out of. Done
    # outside the re-resolve branch below so the tickbox-only path
    # also clears it.
    if not use_fourth and prof.brand_palette_extracted:
        extracted = dict(prof.brand_palette_extracted)
        if extracted.pop(_palette.FOURTH_SLOT, None) is not None:
            prof.brand_palette_extracted = extracted

    # Re-run the AI resolver only when the user gave us nothing to
    # honour (all slots blank → defer fully to AI) OR explicitly
    # asked for a 4th colour the manual override doesn't supply
    # (we need the AI to surface a candidate). When all three
    # manual slots are set, the visible palette is fully overridden
    # via ``effective_palette`` and an LLM round-trip is pure waste.
    all_slots_blank = not manual
    wants_ai_fourth = use_fourth and not manual.get(_palette.FOURTH_SLOT)
    if all_slots_blank or wants_ai_fourth:
        try:
            signals = {}
            usage_map: dict[str, list] = {}
            lcs = prof.link_capture_state or {}
            for plat, entry in lcs.items():
                if not isinstance(entry, dict):
                    continue
                if entry.get("palette_mentions"):
                    signals[plat] = list(entry["palette_mentions"])
                if entry.get("colour_usage"):
                    usage_map[plat] = list(entry["colour_usage"])
            sources = _palette.gather_colour_sources(
                link_palette_signals=signals,
                brand_guidelines=prof.brand_guidelines or {},
                brand_logos=prof.brand_logos or [],
                colour_usage=usage_map,
            )
            if sources:
                resolved = _palette.resolve_palette(
                    org_name=prof.display_name,
                    voice_summary=prof.brand_voice_summary or "",
                    sources=sources,
                    allow_fourth=use_fourth,
                )
                if resolved:
                    merged = dict(prof.brand_palette_extracted or {})
                    for k in _palette.ALL_SLOTS:
                        if resolved.get(k):
                            merged[k] = resolved[k]
                    if not use_fourth:
                        merged.pop(_palette.FOURTH_SLOT, None)
                    prof.brand_palette_extracted = merged
                    prof.brand_palette_reasoning = resolved.get("reasoning", "")
                prof.brand_palette_sources = sources
        except Exception as e:
            W.log.info("manual palette re-resolve failed: %s", e)

    # Keep the legacy brand_primary / brand_secondary in step so the
    # BrandKit fallback path renders the same colours as the form.
    eff = _palette.effective_palette(
        manual=prof.brand_palette_manual,
        extracted=prof.brand_palette_extracted,
    )
    if eff.get("primary"):
        prof.brand_primary = eff["primary"]
    if eff.get("secondary"):
        prof.brand_secondary = eff["secondary"]

    W.save_profile(prof)
    return redirect(url_for("organisation_setup"))


def organisation_setup_palette_reorder():
    """Swap the brand colours around between roles.

    Lets the user rearrange which colour is primary / secondary /
    accent (third) / optional fourth without re-typing any hex. The
    new arrangement is pinned into ``brand_palette_manual`` (which
    wins per-slot over the AI's pick and survives reloads), the
    legacy ``brand_primary`` / ``brand_secondary`` mirrors are kept
    in step, and the Adaptive Theming Engine palette is force-
    recomputed so the chrome, the on-disk theme store, and the
    static / motion / email renderers all follow the new primary.

    Accepts one form field, ``order`` — a comma-separated permutation
    of the currently-present slot names (e.g. ``secondary,primary,
    accent``). When ``order`` is absent the colours are rotated
    forward one role (the "cycle" shortcut). Only colours that
    already exist are moved; the 4th slot only participates when the
    org has opted into a fourth colour, so a reorder never fabricates
    a colour the user didn't choose.
    """
    prof = W._active_profile()
    if not prof:
        return redirect(url_for("organisation_setup"))

    from mediahub.brand import palette as _palette

    eff = _palette.effective_palette(
        manual=prof.brand_palette_manual or {},
        extracted=prof.brand_palette_extracted or {},
    )
    # The 4th colour is only a real slot when the org opted in.
    if not prof.brand_palette_use_fourth:
        eff.pop(_palette.FOURTH_SLOT, None)

    order_raw = (request.form.get("order") or "").strip()
    if order_raw:
        order = [s.strip() for s in order_raw.split(",") if s.strip()]
        reordered = _palette.reorder_palette(eff, order)
    else:
        # No explicit order → cycle the colours forward one role.
        reordered = _palette.rotate_palette(eff, 1)

    # Pin the new arrangement as a manual override so it wins and
    # persists. Only touch the slots we actually rearranged; never
    # introduce a 4th when the org hasn't opted in.
    manual = dict(prof.brand_palette_manual or {})
    for slot in _palette.ALL_SLOTS:
        if reordered.get(slot):
            manual[slot] = reordered[slot]
    if not prof.brand_palette_use_fourth:
        manual.pop(_palette.FOURTH_SLOT, None)
    prof.brand_palette_manual = manual

    # Keep the legacy mirrors in step so the BrandKit fallback path
    # renders the same colours the form now shows.
    if reordered.get("primary"):
        prof.brand_primary = reordered["primary"]
    if reordered.get("secondary"):
        prof.brand_secondary = reordered["secondary"]

    # Force-recompute the derived theme: the primary may have moved,
    # and that seeds the whole MD3 palette + theme store that the
    # chrome and the static graphic renderer read from. force=True
    # bypasses the cache so nothing downstream goes stale.
    try:
        kit = prof.get_brand_kit()
        kit.ensure_derived_palette(force=True)
        prof.brand_kit = kit.to_dict()
    except Exception as e:
        W.log.warning("palette reorder: derived palette recompute failed: %s", e)

    W.save_profile(prof)
    return redirect(url_for("organisation_setup"))


def organisation_setup_logo_serve(logo_id):
    """Serve a logo file. Logos are namespaced per profile to
    prevent IDOR — a request only returns the file if it belongs
    to the active session's profile.
    """
    prof = W._active_profile()
    if not prof:
        return ("", 404)
    from mediahub.brand.logos import (
        resolve_logo_path,
        logo_bg_silhouette_path,
        transparent_pixel_png,
    )

    # ?bg=1 serves the clean-alpha silhouette used by the signed-in logo
    # wall (transparent for any logo, opaque backgrounds keyed out). It's
    # cached and immutable per logo_id, so it's safe to cache hard. The
    # Content-Type is set explicitly because the response carries nosniff —
    # the silhouette is only ever a PNG (rasterised) or an SVG (passthrough).
    if request.args.get("bg"):
        sil = logo_bg_silhouette_path(prof.profile_id, logo_id)
        if sil:
            resp = send_from_directory(sil.parent, sil.name)
            resp.headers["Content-Type"] = (
                "image/svg+xml" if sil.suffix.lower() == ".svg" else "image/png"
            )
            # Session-gated content: "private" keeps the (per-browser) perf win
            # but forbids shared/CDN caches replaying it across sessions.
            resp.headers["Cache-Control"] = "private, max-age=604800"
            # An uploaded SVG can embed script; sandboxing the response
            # neuters it on direct navigation (a plain <img>/CSS-mask
            # consumer is unaffected — CSP sandbox only applies to
            # document navigation).
            resp.headers["Content-Security-Policy"] = "sandbox"
            return resp
        # The logo can't be rasterised to a paintable silhouette (an exotic or
        # corrupt format). A chrome CHIP (?chip=1) wants a real 404 so its
        # <img> onerror swaps in the org initials; the backdrop wants a
        # transparent pixel (never a 404) so its CSS mask/background loads and
        # the element hides cleanly instead of failing into a solid ink block.
        if request.args.get("chip"):
            return ("", 404)
        return Response(
            transparent_pixel_png(),
            mimetype="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    path = resolve_logo_path(prof.profile_id, logo_id)
    if not path:
        return ("", 404)
    # send_from_directory is the safe primitive — it refuses path
    # traversal automatically. CSP sandbox: an uploaded SVG can embed
    # script, and the global CSP allows 'unsafe-inline' — sandboxing
    # neuters it on direct navigation without affecting <img> consumers.
    resp = send_from_directory(path.parent, path.name)
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


def organisation_logo_serve(profile_id, logo_id):
    """Serve any *session-permitted* org's uploaded logo by id.

    The active-profile route above can only serve the org you're already
    signed into — useless on the sign-in picker, which renders the logos
    of every org you may enter *before* one is active. Gating on
    ``_session_can_use_profile`` keeps the IDOR guard (you only ever see
    logos for orgs this session is allowed to use) while letting the
    picker show real, first-party-served logos instead of broken external
    ones.
    """
    if not W._session_can_use_profile(profile_id):
        return ("", 404)
    from mediahub.brand.logos import (
        resolve_logo_path,
        logo_bg_silhouette_path,
        transparent_pixel_png,
    )

    # ?bg=1 serves the clean-alpha KEYED silhouette (opaque/white backgrounds
    # keyed out) — used by the sign-in picker's logo chip so a white-background
    # upload doesn't show as a white box. ?chip=1 makes an unrenderable logo
    # 404 (so the chip's <img> onerror swaps in the org initials); a bare ?bg=1
    # ships a transparent pixel like the backdrop path. Cached hard.
    if request.args.get("bg"):
        sil = logo_bg_silhouette_path(profile_id, logo_id)
        if sil:
            resp = send_from_directory(sil.parent, sil.name)
            resp.headers["Content-Type"] = (
                "image/svg+xml" if sil.suffix.lower() == ".svg" else "image/png"
            )
            # Session-gated content: "private" keeps the (per-browser) perf win
            # but forbids shared/CDN caches replaying it across sessions.
            resp.headers["Cache-Control"] = "private, max-age=604800"
            # An uploaded SVG can embed script; sandboxing the response
            # neuters it on direct navigation (a plain <img>/CSS-mask
            # consumer is unaffected — CSP sandbox only applies to
            # document navigation).
            resp.headers["Content-Security-Policy"] = "sandbox"
            return resp
        if request.args.get("chip"):
            return ("", 404)
        return Response(
            transparent_pixel_png(),
            mimetype="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    path = resolve_logo_path(profile_id, logo_id)
    if not path:
        return ("", 404)
    resp = send_from_directory(path.parent, path.name)
    # Same SVG-script guard as the sibling routes.
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


def organisation_logo_mirror(profile_id):
    """Serve a session-permitted org's *website-detected* logo, mirrored
    first-party.

    Brand capture stores the club's website logo as an external URL
    (``brand_logo_url``) — never the bytes. The app CSP pins
    ``img-src 'self'``, so that cross-origin URL can't render in our own
    pages (it shows as a broken-image icon); many club sites also
    hot-link-block or 403 a bare <img>. This mirrors the bytes to our own
    origin once (cached, SSRF-safe) so the sign-in picker, signed-in
    chrome, and settings preview show the real logo. A 404 here lets the
    caller's ``onerror`` swap fall back to the org's initials.

    IDOR-gated identically to the sibling route: a session only ever sees
    logos for orgs it is permitted to use.
    """
    if not W._session_can_use_profile(profile_id):
        return ("", 404)
    prof = W.load_profile(profile_id)
    if not prof:
        return ("", 404)
    url = (getattr(prof, "brand_logo_url", "") or "").strip()
    if not url:
        return ("", 404)
    from mediahub.brand.logos import (
        mirror_bg_silhouette_path,
        mirror_content_type,
        mirror_external_logo,
        transparent_pixel_png,
    )

    # ?bg=1 serves the clean-alpha silhouette of the mirrored logo for the
    # signed-in backdrop — the same keyed artwork an uploaded logo gets, so
    # the backdrop works for orgs whose logo was only captured from their site.
    if request.args.get("bg"):
        sil = mirror_bg_silhouette_path(profile_id, url)
        if sil:
            resp = send_from_directory(sil.parent, sil.name)
            resp.headers["Content-Type"] = mirror_content_type(sil)
            # Session-gated content: "private" keeps the (per-browser) perf win
            # but forbids shared/CDN caches replaying it across sessions.
            resp.headers["Cache-Control"] = "private, max-age=604800"
            # An uploaded SVG can embed script; sandboxing the response
            # neuters it on direct navigation (a plain <img>/CSS-mask
            # consumer is unaffected — CSP sandbox only applies to
            # document navigation).
            resp.headers["Content-Security-Policy"] = "sandbox"
            return resp
        # Can't rasterise the mirrored logo. A chrome CHIP (?chip=1) wants a 404
        # so its <img> onerror falls back to the org initials; the backdrop
        # wants a transparent pixel (never a 404) so its mask/background loads
        # and hides cleanly rather than painting a solid ink block.
        if request.args.get("chip"):
            return ("", 404)
        return Response(
            transparent_pixel_png(),
            mimetype="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    path = mirror_external_logo(profile_id, url)
    if not path:
        return ("", 404)
    resp = send_from_directory(path.parent, path.name)
    # Set the type explicitly — the response carries nosniff, so an
    # extension Flask can't map (e.g. .avif) must not be left to guess.
    resp.headers["Content-Type"] = mirror_content_type(path)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    # Mirrored site logos can be SVG too — same script-neutering sandbox.
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


def organisation_setup_reread(platform):
    """M5 — Force the AI to re-read one link without resubmitting
    the whole form. Looks up the URL the user previously saved for
    ``platform``, runs the matching handler, merges the resulting
    per-link state (status chip + voice digest) back onto the
    profile, and invalidates the full-capture social_dna cache for
    this link set — so the next setup save re-derives the combined
    brand DNA from the fresh read instead of replaying the stale
    cached result. Redirects back to the setup page so the new
    status chip is visible.
    """
    prof = W._active_profile()
    if not prof:
        return redirect(url_for("organisation_setup"))
    platform = (platform or "").lower().strip()
    # Resolve the URL the user previously saved
    if platform == "website":
        url = (prof.brand_source_url or "").strip()
    else:
        url = (prof.social_links.get(platform) or "").strip()
    if not url:
        return redirect(url_for("organisation_setup"))
    # Run just this one platform through the handler pipeline.
    try:
        from mediahub.brand import link_handlers as _lh

        handler = _lh.get_handler(platform)
        if handler is not None:
            entry = handler.process(url)
            state = dict(prof.link_capture_state or {})
            state[platform] = {
                "url": entry.get("url", url),
                "status": entry.get("status", "unknown"),
                "playbook_age": entry.get("playbook_age", -1),
                "regenerated": entry.get("regenerated", False),
                "voice_digest": ((entry.get("dna") or {}).get("voice_summary") or "")[:240],
            }
            prof.link_capture_state = state
            W.save_profile(prof)
            # The full-capture cache (no TTL) still holds the OLD combined
            # DNA for this exact link set; without invalidation a later
            # capture_from_socials(force=False) would replay it and the
            # re-read would never reach captions. Drop the entry so the
            # next setup save re-derives brand voice from fresh reads.
            try:
                from mediahub.brand import social_dna as _sdna

                _sdna._cache_path(
                    (prof.brand_source_url or "").strip(),
                    dict(prof.social_links or {}),
                ).unlink(missing_ok=True)
            except Exception:
                W.log.info("social-dna cache invalidation failed for %s", platform)
    except Exception as e:
        W.log.info("re-read for %s failed: %s", platform, e)
    return redirect(url_for("organisation_setup"))


def organisation_setup_logo_delete(logo_id):
    """Remove a logo from the active profile's brand_logos list AND
    delete the on-disk file. Same IDOR guard as the serve route."""
    prof = W._active_profile()
    if not prof:
        return redirect(url_for("organisation_setup"))
    from mediahub.brand.logos import delete_logo as _del

    # Defensively match the entry by id before unlinking.
    remaining = [
        entry
        for entry in (prof.brand_logos or [])
        if isinstance(entry, dict) and entry.get("logo_id") != logo_id
    ]
    if len(remaining) != len(prof.brand_logos or []):
        _del(prof.profile_id, logo_id)
        prof.brand_logos = remaining
        W.save_profile(prof)
    return redirect(url_for("organisation_setup"))


def athletes_page():
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Athletes", W._PW_NO_ORG, active="settings")
    # G-9: two tabs. "Roster & permissions" is what MediaHub enforces on
    # content; "Consent records" holds the signed decisions behind it
    # (moved here from the orphaned /organisation/consent page, which now
    # redirects). /athletes is the record of truth for both.
    if (request.args.get("tab") or "").strip() == "records":
        profile = W.load_profile(pid)
        if profile is None:
            return W._layout("Athletes", W._PW_NO_ORG, active="settings")
        return W._layout(
            "Athletes & consent", W._athletes_records_tab(pid, profile), active="settings"
        )
    from mediahub.athletes import list_athletes
    from mediahub.safeguarding import LEVEL_LABELS, list_consent, regime_active

    roster = list_athletes(pid)
    consent = list_consent(pid)
    regime = regime_active(pid)
    msg = (request.args.get("msg") or "").strip()
    msg_html = f'<p class="tag good" style="margin-bottom:14px">{W._h(msg)}</p>' if msg else ""
    # D-19: list exactly which rows the last consent import couldn't read.
    msg_html += W._import_skipped_html(session.pop("consent_import_skipped", None))

    level_options = list(LEVEL_LABELS.items())
    rows = []
    for rec in roster:
        current = (consent.get(rec.athlete_id) or {}).get("level") or "unknown"
        opts = "".join(
            f'<option value="{W._h(val)}" {"selected" if val == current else ""}>'
            f"{W._h(label)}</option>"
            for val, label in level_options
            if val != "unknown"
        )
        unknown_opt = (
            f'<option value="" {"selected" if current == "unknown" else ""}>'
            f"{W._h(LEVEL_LABELS['unknown'])}</option>"
        )
        aliases = ", ".join(a for a in rec.aliases if a != rec.canonical_name.casefold())
        rows.append(
            "<tr>"
            # B-7: bulk-select checkbox — hidden until the enhancement
            # script reveals it (it does nothing without JS).
            f'<td data-label="Select" class="mh-consent-selcell" hidden>'
            f'<input type="checkbox" class="mh-consent-check" value="{W._h(rec.athlete_id)}"'
            f' aria-label="Select {W._h(rec.canonical_name)}"/></td>'
            f'<td data-label="Athlete"><strong>{W._h(rec.canonical_name)}</strong>'
            + (
                f'<br/><span class="muted" style="font-size:11px">also seen as: {W._h(aliases)}</span>'
                if aliases
                else ""
            )
            + "</td>"
            f'<td data-label="Races">{rec.race_count}</td>'
            f'<td data-label="Born">{W._h(str(rec.birth_year or ""))}</td>'
            # B-7: the form POST stays as the no-JS fallback; with JS the
            # dropdown auto-saves via fetch (no reload, scroll preserved).
            f'<td data-label="Permission"><form method="POST" action="{url_for("athletes_action")}"'
            f' class="mh-consent-form" data-athlete-id="{W._h(rec.athlete_id)}" data-no-loader="1"'
            f' style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
            f'<input type="hidden" name="action" value="set_consent"/>'
            f'<input type="hidden" name="athlete_id" value="{W._h(rec.athlete_id)}"/>'
            f'<select name="level" style="font-size:12px">{unknown_opt}{opts}</select>'
            f'<button type="submit" class="btn secondary mh-consent-save" style="font-size:12px;padding:4px 10px">Save</button>'
            f'<span class="mh-consent-tick" role="status" hidden'
            f' style="font-size:12px;font-weight:600;color:var(--mh-success)">Saved &#10003;</span>'
            f"</form></td>"
            "</tr>"
        )
    rows_html = (
        "".join(rows)
        if rows
        else '<tr><td colspan="5" class="muted">No athletes yet — run a meet '
        "through the pipeline, or click &ldquo;Build from past runs&rdquo; below.</td></tr>"
    )
    # B-7: the bulk bar (one select + Apply) posts once for every ticked
    # swimmer and updates the rows in place. JS-only — revealed by the
    # enhancement script below.
    bulk_opts = "".join(
        f'<option value="{W._h(val)}">{W._h(label)}</option>'
        for val, label in level_options
        if val != "unknown"
    )
    bulk_bar = f"""
  <div id="mh-consent-bulk" style="display:none;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
    <label class="muted" for="mh-consent-bulk-level" style="font-size:12px">Apply permission to selected&hellip;</label>
    <select id="mh-consent-bulk-level" style="font-size:12px">
      <option value="">Pick a permission</option>
      {bulk_opts}
    </select>
    <button type="button" id="mh-consent-bulk-apply" class="btn secondary" style="font-size:12px;padding:4px 10px">Apply</button>
    <span class="muted" style="font-size:12px"><span id="mh-consent-selcount">0</span> selected</span>
  </div>"""

    merge_opts = "".join(
        f'<option value="{W._h(r.athlete_id)}">{W._h(r.canonical_name)} ({r.race_count} races)</option>'
        for r in roster
    )
    regime_note = (
        '<p class="tag good" style="margin:0">Consent enforcement is ACTIVE — '
        "athletes with no consent on file are blocked from content.</p>"
        if regime
        else '<p class="tag warn" style="margin:0">No consent regime yet — cards '
        "behave as before. Import your consent register (or switch enforcement "
        "on) and unknown athletes become most-restricted automatically.</p>"
    )
    # E-7: turning enforcement ON blocks every athlete with no consent on file
    # club-wide. Show the impact ("N of M would be blocked") and confirm before
    # enabling; switching it off needs no confirm (it only unblocks).
    _no_consent = sum(
        1
        for rec in roster
        if ((consent.get(rec.athlete_id) or {}).get("level") or "unknown") == "unknown"
    )
    _enf_msg = (
        f"Turn consent enforcement on? {_no_consent} of {len(roster)} athletes have no "
        "consent on file and would be blocked from all content until you record their "
        "permission. You can switch it back off, but content built while it is on is blocked."
    )
    _enf_attrs = (
        ' onsubmit="return athEnforceConfirm(this)" data-enforcing="0"'
        if regime
        else f' onsubmit="return athEnforceConfirm(this)" data-enforcing="1" data-msg="{W._h(_enf_msg)}"'
    )
    roster_hero = W._ATHLETES_HERO.replace(
        "__LEDE__",
        "One identity per swimmer across every meet. Milestones (debut, "
        "50th race), records and season wraps hang off this roster &mdash; "
        "and so does photo/name permission.",
    )
    body = f"""{roster_hero}
{W._athletes_tabs_html(False)}
<p class="dim" style="margin-bottom:16px;font-size:13px">Permissions on this tab are what
MediaHub enforces on content. The signed decisions behind them &mdash; who said yes or no,
and your lawful basis &mdash; live under
<a href="{url_for("athletes_page", tab="records")}">Consent records</a>.</p>
{msg_html}
<div class="card" style="margin-bottom:16px">{regime_note}
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
    <form method="POST" action="{url_for("athletes_action")}"{_enf_attrs}>
      <input type="hidden" name="action" value="toggle_enforce"/>
      <button type="submit" class="btn secondary">{"Switch enforcement off" if regime else "Switch enforcement on"}</button>
    </form>
    <a class="btn secondary" href="{url_for("athletes_consent_export")}">Welfare-officer export (.csv)</a>
    <form method="POST" action="{url_for("athletes_action")}">
      <input type="hidden" name="action" value="backfill"/>
      <button type="submit" class="btn secondary" title="Scan this organisation's past runs and build the roster">Build from past runs</button>
    </form>
  </div>
</div>
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-top:0">Roster</h2>{bulk_bar}
  <table class="mh-table mh-table-stack" style="width:100%">
    <thead><tr><th class="mh-consent-selcell" hidden style="width:28px"><input type="checkbox" id="mh-consent-check-all" aria-label="Select every athlete"/></th><th>Athlete</th><th>Races logged</th><th>Born</th><th>Photo &amp; name permission</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-top:0">Same swimmer twice?</h2>
  <p class="dim" style="font-size:13px">Results files spell names differently
  ("Maya Patel" / "Patel, Maya"). Merge them and the decision sticks for every
  future upload. Merges are recorded in the audit log.</p>
  <form method="POST" action="{url_for("athletes_action")}" onsubmit="return athMergeConfirm(this)" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <input type="hidden" name="action" value="merge"/>
    <label>Keep</label><select name="keep_id">{merge_opts}</select>
    <label>absorbs</label><select name="merge_id">{merge_opts}</select>
    <button type="submit" class="btn">Merge</button>
  </form>
</div>{W._ATHLETES_CONFIRM_JS}{W._ATHLETES_CONSENT_JS.replace("__CONSENT_URL__", url_for("api_athletes_consent"))}
<div class="card">
  <h2 style="margin-top:0">Import the consent register (.csv)</h2>
  <p class="dim" style="font-size:13px">One row per athlete:
  <code>name, permission[, note]</code> &mdash; permission is one of
  <code>photo ok</code>, <code>no photo</code>, <code>initials only</code>,
  <code>do not feature</code>. Rows we can&rsquo;t read are reported, never guessed.</p>
  <form method="POST" action="{url_for("athletes_action")}">
    <input type="hidden" name="action" value="import_consent"/>
    <textarea name="csv_text" rows="6" style="width:100%;max-width:640px"
      placeholder="Maya Patel, initials only, parent form 2026&#10;Joe Bloggs, photo ok"></textarea>
    <div style="margin-top:8px"><button type="submit" class="btn">Import</button></div>
  </form>
</div>
"""
    return W._layout("Athletes & consent", body, active="settings")


def athletes_action():
    pid = W._phase_w_org()
    if not pid:
        abort(403)
    from mediahub.athletes import backfill_from_runs, merge_athletes
    from mediahub.safeguarding import import_csv as consent_import
    from mediahub.safeguarding import regime_active, set_consent, set_enforce
    from mediahub.safeguarding.consent import LEVELS as _CONSENT_LEVELS

    actor = (session.get("user_email") or "web").strip()
    action = (request.form.get("action") or "").strip()
    msg = ""
    if action == "set_consent":
        athlete_id = (request.form.get("athlete_id") or "").strip()
        level = (request.form.get("level") or "").strip()
        if level in _CONSENT_LEVELS and athlete_id:
            set_consent(pid, athlete_id, level, actor=actor)
            msg = "Consent updated."
        elif athlete_id and not level:
            msg = "Pick a permission level first."
    elif action == "merge":
        keep_id = (request.form.get("keep_id") or "").strip()
        merge_id = (request.form.get("merge_id") or "").strip()
        if keep_id and merge_id and keep_id != merge_id:
            ok = merge_athletes(pid, keep_id, merge_id, actor=actor)
            msg = "Merged — the decision is recorded and persists." if ok else "Merge failed."
        else:
            msg = "Pick two different athletes to merge."
    elif action == "toggle_enforce":
        now_on = regime_active(pid)
        set_enforce(pid, not now_on, actor=actor)
        msg = "Consent enforcement switched " + ("off." if now_on else "on.")
    elif action == "import_consent":
        result = consent_import(pid, request.form.get("csv_text") or "", actor=actor)
        msg = f"Imported {result['imported']} rows."
        if result["skipped"]:
            msg += f" Skipped {len(result['skipped'])} (unreadable level/name)."
            # D-19: stash the failed rows so the page can list exactly which
            # ones need fixing, not just a count.
            session["consent_import_skipped"] = result["skipped"]
    elif action == "backfill":
        prof = W.load_profile(pid)

        def _is_ours(code):
            return prof.is_ours(code, None) if prof else True

        stats = backfill_from_runs(pid, W.RUNS_DIR, is_ours=_is_ours)
        msg = (
            f"Scanned {stats['runs']} past runs — {stats['swims']} swims logged " "into the roster."
        )
    return redirect(url_for("athletes_page", msg=msg))


def athletes_consent_export():
    pid = W._phase_w_org()
    if not pid:
        abort(403)
    from mediahub.safeguarding import export_csv

    out = export_csv(pid)
    resp = make_response(out)
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = 'attachment; filename="consent-register.csv"'
    return resp


def register(app) -> None:
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule(
        "/organisation/consent", endpoint="org_consent_page", view_func=org_consent_page
    )
    app.add_url_rule(
        "/organisation/consent/settings",
        endpoint="org_consent_settings",
        view_func=org_consent_settings,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/consent/child-policy",
        endpoint="org_child_policy_settings",
        view_func=org_child_policy_settings,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/consent/retention",
        endpoint="org_retention_settings",
        view_func=org_retention_settings,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/consent/record",
        endpoint="org_consent_record",
        view_func=org_consent_record,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/athlete-rights", endpoint="org_athlete_rights", view_func=org_athlete_rights
    )
    app.add_url_rule(
        "/organisation/athlete-rights/open",
        endpoint="org_dsr_open",
        view_func=org_dsr_open,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/athlete-rights/<request_id>/run",
        endpoint="org_dsr_action",
        view_func=org_dsr_action,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/athlete-rights/<request_id>/export.json",
        endpoint="org_dsr_export_download",
        view_func=org_dsr_export_download,
    )
    app.add_url_rule(
        "/organisation/athlete-rights/<request_id>/clock",
        endpoint="org_dsr_clock",
        view_func=org_dsr_clock,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation",
        endpoint="organisation_page",
        view_func=organisation_page,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/organisation/analysis/discard",
        endpoint="organisation_analysis_discard",
        view_func=organisation_analysis_discard,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/api",
        endpoint="organisation_api_tokens_page",
        view_func=organisation_api_tokens_page,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/organisation/members",
        endpoint="organisation_members_page",
        view_func=organisation_members_page,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/organisation/export", endpoint="organisation_export", view_func=organisation_export
    )
    app.add_url_rule(
        "/organisation/delete",
        endpoint="organisation_delete",
        view_func=organisation_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/setup",
        endpoint="organisation_setup",
        view_func=organisation_setup,
        methods=["GET"],
    )
    app.add_url_rule(
        "/organisation/setup/capture",
        endpoint="organisation_setup_capture",
        view_func=organisation_setup_capture,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/setup/manual",
        endpoint="organisation_setup_manual",
        view_func=organisation_setup_manual,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/setup/palette",
        endpoint="organisation_setup_palette",
        view_func=organisation_setup_palette,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/setup/palette/reorder",
        endpoint="organisation_setup_palette_reorder",
        view_func=organisation_setup_palette_reorder,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/setup/logo/<logo_id>",
        endpoint="organisation_setup_logo_serve",
        view_func=organisation_setup_logo_serve,
        methods=["GET"],
    )
    app.add_url_rule(
        "/organisation/<profile_id>/logo/<logo_id>",
        endpoint="organisation_logo_serve",
        view_func=organisation_logo_serve,
        methods=["GET"],
    )
    app.add_url_rule(
        "/organisation/<profile_id>/brand-logo",
        endpoint="organisation_logo_mirror",
        view_func=organisation_logo_mirror,
        methods=["GET"],
    )
    app.add_url_rule(
        "/organisation/setup/reread/<platform>",
        endpoint="organisation_setup_reread",
        view_func=organisation_setup_reread,
        methods=["POST"],
    )
    app.add_url_rule(
        "/organisation/setup/logo/<logo_id>/delete",
        endpoint="organisation_setup_logo_delete",
        view_func=organisation_setup_logo_delete,
        methods=["POST"],
    )
    app.add_url_rule("/athletes", endpoint="athletes_page", view_func=athletes_page)
    app.add_url_rule(
        "/athletes/action", endpoint="athletes_action", view_func=athletes_action, methods=["POST"]
    )
    app.add_url_rule(
        "/athletes/consent.csv",
        endpoint="athletes_consent_export",
        view_func=athletes_consent_export,
    )
