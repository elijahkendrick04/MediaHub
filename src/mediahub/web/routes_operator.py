"""Operator/admin surfaces: operator console, audits, billing, webhooks, settings.

Carved out of ``web.create_app`` (deep-review finding #15, final stage).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
any captured ``app`` became ``current_app``. Endpoint names are
PRESERVED via ``add_url_rule`` (ADR-0031).
"""

from __future__ import annotations

from markupsafe import escape as _h
import json
from flask import (
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from mediahub.web import web as W


@W.require_run(
    deny=lambda: (
        W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    ),
    require_exists=True,
)
def pb_audit_page(run_id, run_data):
    """Full PB audit page with per-swimmer drill-down."""
    data = run_data
    pb_audit = data.get("pb_audit") or {}
    if not pb_audit:
        empty_body = (
            '<section class="mh-hero" data-lane="--" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
            '<span class="mh-hero-eyebrow">PB audit</span>'
            "<h1>No PB audit on file</h1>"
            '<p class="lede">'
            "This run was processed without PB fetching, so there's nothing to "
            "reconcile here. Re-run the same input from the upload page with PB "
            "fetching enabled and the audit detail will appear."
            "</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{url_for("upload")}">'
            "Re-upload with PB fetching &rarr;</a>"
            f'<a class="mh-cta-secondary" href="{url_for("review", run_id=run_id)}">'
            "Back to the review queue</a>"
            "</div>"
            "</section>"
        )
        return W._layout("PB Audit", empty_body, active="")
    per_swimmer = pb_audit.get("per_swimmer") or []
    _review_url = url_for("review", run_id=run_id)

    # Discovery-path audits carry no identity matches (identity is None
    # for every swimmer). The Verify / Ignore controls write ASA-id
    # corrections that only the legacy SR identity flow reads — on a
    # discovery run they promised a re-fetch that never happened. Render
    # the lookup truth instead; keep the legacy table (and its controls)
    # for old persisted runs that do carry identity data.
    has_identity = any(sa.get("identity") for sa in per_swimmer)

    def _n_confirmed(sa: dict) -> int:
        # All V7.3 confirmed flavours + the legacy status count as
        # confirmed here, matching aggregate_run_audit's summary set.
        return sum(
            1
            for d in (sa.get("pb_decisions") or [])
            if d.get("status")
            in ("CONFIRMED_OFFICIAL_PB", "CONFIRMED_PB_IMPROVEMENT", "CONFIRMED_PB")
        )

    rows = ""
    if has_identity:
        for sa in per_swimmer:
            identity = sa.get("identity") or {}
            method = identity.get("method", "")
            # F-7: one shared label map (see _pb_match_status_meta) so this
            # table and the Verify screen never show different words.
            method_label, method_cls = W._pb_match_status_meta(method)
            _sw_key = sa.get("asa_id") or f"name:{sa.get('hy3_name', '')}"
            _verify_url = url_for("pb_verify_form", run_id=run_id, swimmer_key=_sw_key)
            _ignore_url = url_for("pb_ignore", run_id=run_id, swimmer_key=_sw_key)
            rows += (
                f"<tr>"
                f"<td>{_h(sa.get('hy3_name', ''))}</td>"
                f'<td class="muted">{_h(sa.get("asa_id") or "—")}</td>'
                f"<td>{_h(sa.get('sr_name') or '—')}</td>"
                f'<td><span class="tag {method_cls}">{_h(method_label)}</span></td>'
                f"<td>{len(sa.get('pb_decisions') or [])}</td>"
                f'<td style="color:var(--good)">{_n_confirmed(sa)}</td>'
                f"<td>"
                f'<a class="btn secondary" style="font-size:11px;padding:3px 8px" href="{_verify_url}">Verify</a>'
                f' <form style="display:inline" method="post" action="{_ignore_url}">'
                f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" type="submit">Ignore PBs</button></form>'
                f"</td>"
                f"</tr>"
            )
        table_head = (
            "<th>HY3 Name</th><th>ASA ID</th><th>SR Name</th><th>Identity</th>"
            "<th>Decisions</th><th>Confirmed</th><th>Actions</th>"
        )
    else:
        for sa in per_swimmer:
            n_events = len(sa.get("events_fetched") or [])
            if sa.get("fetch_ok"):
                if sa.get("no_history") or n_events == 0:
                    outcome = '<span class="tag">No online history</span>'
                else:
                    outcome = (
                        f'<span class="tag good">Found {n_events} '
                        f"event{'s' if n_events != 1 else ''}</span>"
                    )
            else:
                _err = _h(sa.get("fetch_error") or "lookup failed")
                outcome = f'<span class="tag warn" title="{_err}">Failed</span>'
            src_urls = [u for u in (sa.get("source_urls") or []) if str(u).startswith("http")]
            if src_urls:
                src_cell = (
                    f'<a href="{_h(src_urls[0])}" target="_blank" rel="noopener noreferrer" '
                    f'class="muted" style="font-size:11px">source &#x2197;</a>'
                )
            else:
                src_cell = '<span class="muted">—</span>'
            rows += (
                f"<tr>"
                f"<td>{_h(sa.get('hy3_name', ''))}</td>"
                f"<td>{outcome}</td>"
                f"<td>{len(sa.get('pb_decisions') or [])}</td>"
                f'<td style="color:var(--good)">{_n_confirmed(sa)}</td>'
                f"<td>{src_cell}</td>"
                f"</tr>"
            )
        table_head = (
            "<th>Swimmer</th><th>Lookup</th><th>Decisions</th><th>Confirmed</th><th>Source</th>"
        )

    if has_identity:
        ident_stats = (
            f'<div class="stat live"><div class="l">Verified</div><div class="v">{pb_audit.get("swimmers_matched_verified", 0)}</div></div>'
            f'<div class="stat warn"><div class="l">Needs verification</div><div class="v">{pb_audit.get("swimmers_needs_verification", 0)}</div></div>'
        )
    else:
        ident_stats = (
            f'<div class="stat warn"><div class="l">Lookups failed</div><div class="v">{pb_audit.get("swimmers_fetch_failed", 0)}</div></div>'
            f'<div class="stat"><div class="l">No online history</div><div class="v">{pb_audit.get("swimmers_no_history", 0)}</div></div>'
        )

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">PB audit</span>
  <h1>Personal-best reconciliation</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>run {_h(pb_audit.get("run_id", run_id)[:12])}</span><span class="sep">/</span>
    <a href="{_review_url}" style="color:var(--ink-muted);text-decoration:none">← Back to review</a>
  </div>
</section>
<div class="card">
  <div class="stat-block">
    <div class="stat"><div class="l">Swimmers</div><div class="v">{pb_audit.get("swimmers_total", 0)}</div></div>
    {ident_stats}
    <div class="stat good"><div class="l">Confirmed PBs</div><div class="v">{pb_audit.get("pb_confirmed_count", 0)}</div></div>
    <div class="stat"><div class="l">Total decisions</div><div class="v">{pb_audit.get("pb_decisions_count", 0)}</div></div>
    <div class="stat"><div class="l">Fetch time</div><div class="v">{pb_audit.get("fetch_total_seconds", 0):.1f}s</div></div>
  </div>
  {W._PB_TRUST_KEY_HTML}
</div>
<div class="card">
  <h2>Per-swimmer</h2>
  <table>
    <thead><tr>
      {table_head}
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""
    return W._layout("PB Audit", body, active="")


@W.require_run(
    deny=lambda: (
        W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    ),
    require_exists=True,
)
def pb_verify_form(run_id, swimmer_key, run_data):
    """Form to enter correct ASA number for a needs-verification swimmer."""
    data = run_data
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
    _action_url = url_for("pb_verify_form", run_id=run_id, swimmer_key=swimmer_key)

    # Pull this swimmer's audit details so the user can see WHY this needs
    # verification &mdash; not just an opaque key.
    pb_audit = data.get("pb_audit") or {}
    per_sw = pb_audit.get("per_swimmer") or []
    target = None
    for sw in per_sw:
        if (
            str(sw.get("asa_id") or "") == swimmer_key
            or sw.get("hy3_name", "").replace(",", "").replace(" ", "").lower()
            == swimmer_key.replace(",", "").replace(" ", "").lower()
        ):
            target = sw
            break

    context_html = ""
    if target:
        ident = target.get("identity") or {}
        hy3_name = _h(target.get("hy3_name") or "—")
        sr_name = _h(target.get("sr_name") or "— (no record returned)")
        # F-7: show the SAME friendly label the audit table shows, never the
        # raw `needs_verification` / `asa_id_verified` enum.
        _method_label, method_pill = W._pb_match_status_meta(ident.get("method", ""))
        method = _h(_method_label)
        cur_asa = _h(target.get("asa_id") or "—")
        notes_list = ident.get("notes") or []
        notes_html = (
            "".join(f"<li>{_h(n)}</li>" for n in notes_list) or "<li class='muted'>No notes</li>"
        )
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
  {W._PB_TRUST_KEY_HTML}
</div>"""
    else:
        context_html = f"""
<div class="card" style="margin-bottom:18px">
  <p class="muted">Swimmer key <code>{_sw_key_h}</code> wasn't found in this run's audit data. You can still set a manual override.</p>
</div>"""

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Verify swimmer</span>
  <h1>Confirm the <em class="editorial">identity</em>.</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{_sw_key_h}</span><span class="sep">/</span>
    <a href="{_audit_url}" style="color:var(--ink-muted);text-decoration:none">← Back to audit</a>
  </div>
</section>
{context_html}
<div class="card">
  <h2 style="font-size:16px;margin-bottom:var(--sp-2)">Set the correct ASA member ID</h2>
  <p class="dim" style="font-size:13px;margin-bottom:var(--sp-4)">This override applies to this meet only. It won't affect other runs.
  If you save this, we'll re-fetch PBs for the corrected ID.</p>
  <form method="post" action="{_action_url}" data-loader-text="Saving correction">
    <label class="req" for="vf-asa">Correct ASA member ID</label>
    <input id="vf-asa" type="text" name="new_asa_id" placeholder="e.g. 1382076" pattern="[0-9]+" required />
    <label for="vf-note">Note (optional)</label>
    <input id="vf-note" type="text" name="note" placeholder="Why this override (e.g. wrong number entered in HY3)" />
    <div style="margin-top:var(--sp-4);display:flex;gap:var(--sp-3)">
      <button class="btn" type="submit">Save correction &rarr;</button>
      <a class="btn secondary" href="{_audit_url}">Cancel</a>
    </div>
  </form>
</div>"""
    return W._layout("Verify swimmer", body, active="")


@W.require_run(deny=lambda: (redirect(url_for("home"))), require_exists=True)
def pb_ignore(run_id, swimmer_key):
    """Mark 'ignore PBs for this swimmer in this meet'."""
    # Refuse to mutate corrections for a run that isn't ours or doesn't
    # exist &mdash; a missing run must not persist a CorrectionsStore row
    # keyed to a fabricated id (mirrors pb_verify_form's require_exists).
    reason = request.form.get("reason", "User requested ignore")
    from swim_content_pb.corrections import CorrectionsStore

    cs = CorrectionsStore()
    cs.set_ignore_pb(run_id, swimmer_key, reason=reason)
    return redirect(url_for("pb_audit_page", run_id=run_id))


@W.require_run(
    deny=lambda: (
        W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    ),
    require_exists=True,
)
def pb_ground_truth(run_id, run_data):
    """Upload a CSV of expected outcomes and run the ground-truth harness."""
    data = run_data
    _audit_url = url_for("pb_audit_page", run_id=run_id)
    _action_url = url_for("pb_ground_truth", run_id=run_id)

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
                    run_pb_audit_dict=data.get("pb_audit"),
                )
                report_html = (
                    f'<div class="card"><h2>Ground Truth Results</h2>'
                    f'<div class="stat-block">'
                    f'<div class="stat"><div class="l">Total entries</div><div class="v">{report.total_entries}</div></div>'
                    f'<div class="stat good"><div class="l">True positives</div><div class="v">{report.true_positives}</div></div>'
                    f'<div class="stat bad"><div class="l">False positives</div><div class="v">{report.false_positives}</div></div>'
                    f'<div class="stat warn"><div class="l">False negatives</div><div class="v">{report.false_negatives}</div></div>'
                    f'<div class="stat"><div class="l">Precision</div><div class="v">{report.precision or "&mdash;"}</div></div>'
                    f'<div class="stat"><div class="l">Recall</div><div class="v">{report.recall or "&mdash;"}</div></div>'
                    f'<div class="stat"><div class="l">F1</div><div class="v">{report.f1 or "&mdash;"}</div></div>'
                    f"</div></div>"
                )
            except Exception as e:
                report_html = f'<div class="card"><p class="tag bad">Error: {_h(str(e))}</p></div>'
            finally:
                try:
                    csv_path.unlink()
                except Exception:
                    pass

    body = f"""
<h1>Ground Truth &mdash; PB Decisions</h1>
<p class="dim"><a href="{_audit_url}">&larr; Back to PB audit</a></p>
<div class="card">
  <p>Upload a CSV with columns: <code>swimmer_name, event_label, result_time, expected_pb, expected_prev_pb, expected_barrier_crossed, notes</code></p>
  <p><code>expected_pb</code>: yes | no | unknown</p>
  <form method="post" enctype="multipart/form-data" action="{_action_url}">
    <input type="file" name="csv_file" accept=".csv" required />
    <div style="margin-top:12px"><button class="btn" type="submit">Run ground truth</button></div>
  </form>
</div>
{report_html}"""
    return W._layout("Ground Truth", body, active="")


def admin_compliance():
    if not W._auth.is_dev_operator():
        return W._layout(
            "Not found", '<div class="card"><p class="tag bad">No such page.</p></div>'
        ), 404
    from mediahub.compliance.complaints import ComplaintsStore
    from mediahub.compliance.incidents import IncidentRegister

    store = ComplaintsStore()
    complaints = store.all()
    overdue_ids = {c.id for c in store.overdue()}
    rows = []
    for c in complaints:
        badge = {
            "received": '<span class="tag">received</span>',
            "acknowledged": '<span class="tag ok">acknowledged</span>',
            "responded": '<span class="tag ok">responded</span>',
            "closed": '<span class="tag">closed</span>',
        }.get(c.status, _h(c.status))
        late = ' <span class="tag bad">ACK OVERDUE</span>' if c.id in overdue_ids else ""
        ack_form = ""
        if c.status == "received":
            ack_form = (
                f'<form method="post" action="{url_for("admin_compliance_ack", complaint_id=c.id)}" style="display:inline">'
                '<input type="text" name="via" placeholder="how (e.g. email sent)" maxlength="300">'
                '<button class="btn secondary" type="submit">Mark acknowledged</button></form>'
            )
        rows.append(
            f"<tr><td><code>{_h(c.id)}</code></td><td>{_h(c.received_at[:10])}<br>"
            f"<span class='muted'>ack by {_h(c.ack_due_at[:10])}</span>{late}</td>"
            f"<td>{_h(c.name)}<br><span class='muted'>{_h(c.relationship)} — {_h(c.contact)}</span></td>"
            f"<td>{_h(c.club)}</td><td style='max-width:420px'>{_h(c.details[:600])}</td>"
            f"<td>{badge}{ack_form}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Ref</th><th>Received</th><th>From</th><th>Club</th>"
        "<th>Details</th><th>Status</th></tr></thead><tbody>"
        + ("".join(rows) or '<tr><td colspan="6" class="muted">No complaints.</td></tr>')
        + "</tbody></table>"
    )
    from mediahub.compliance.security_log import read_events as _read_sec_events

    _events = list(reversed(_read_sec_events(limit=100)))
    _event_rows = (
        "".join(
            f"<tr><td>{_h(e.get('ts', '')[:19])}</td><td>{_h(e.get('event', ''))}</td>"
            f"<td>{_h(e.get('actor', ''))}</td><td><code>{_h(e.get('subject_pseudonym', ''))}</code></td>"
            f"<td>{_h(e.get('profile_id', ''))}</td><td>{_h(e.get('outcome', ''))}</td>"
            f"<td class='muted'>{_h(e.get('detail', '')[:120])}</td></tr>"
            for e in _events
        )
        or '<tr><td colspan="7" class="muted">No events.</td></tr>'
    )
    events_table = (
        "<table><thead><tr><th>When</th><th>Event</th><th>Actor</th><th>Subject</th>"
        "<th>Org</th><th>Outcome</th><th>Detail</th></tr></thead>"
        f"<tbody>{_event_rows}</tbody></table>"
    )
    incidents = IncidentRegister().all()
    inc_rows = (
        "".join(
            f"<tr><td><code>{_h(i.id)}</code></td><td>{_h(i.opened_at[:10])}</td>"
            f"<td>{_h(i.title)}</td><td>{_h(i.severity)}</td>"
            f"<td>{'yes' if i.personal_data_involved else 'no'}</td>"
            f"<td>{_h(i.status)}</td></tr>"
            for i in incidents
        )
        or '<tr><td colspan="6" class="muted">No incidents recorded.</td></tr>'
    )
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Operator</span>
  <h1>Compliance <em class="editorial">desk.</em></h1>
  <p class="lede">Data-protection complaints (acknowledge within 30 days — s.164A DPA 2018) and the incident register (Art 33(5)). Breach process: docs/compliance/BREACH_PLAYBOOK.md.</p>
</section>
<div class="card"><h2>Security events (last 100)</h2>
<p class="muted">Logins, failures, lockouts, exports, erasures, publishes, CSRF rejections. Data subjects appear as pseudonyms only; full stream: <code>DATA_DIR/security_log/events.jsonl</code>.</p>
{events_table}</div>
<div class="card"><h2>Complaints</h2>{table}</div>
<div class="card"><h2>Incident register</h2>
<table><thead><tr><th>Ref</th><th>Opened</th><th>Title</th><th>Severity</th><th>Personal data</th><th>Status</th></tr></thead>
<tbody>{inc_rows}</tbody></table>
<form method="post" action="{url_for("admin_compliance_incident")}" style="margin-top:12px">
  <input type="text" name="title" placeholder="Incident title" maxlength="300" required>
  <select name="severity"><option>low</option><option selected>medium</option><option>high</option><option>critical</option></select>
  <label><input type="checkbox" name="personal_data" value="1"> personal data involved</label>
  <button class="btn secondary" type="submit">Open incident</button>
</form>
</div>
"""
    return W._layout("Compliance desk", body, active="privacy")


def admin_compliance_ack(complaint_id):
    if not W._auth.is_dev_operator():
        return W._layout(
            "Not found", '<div class="card"><p class="tag bad">No such page.</p></div>'
        ), 404
    from mediahub.compliance.complaints import ComplaintsStore

    ComplaintsStore().acknowledge(complaint_id, via=request.form.get("via") or "")
    return redirect(url_for("admin_compliance"))


def admin_compliance_incident():
    if not W._auth.is_dev_operator():
        return W._layout(
            "Not found", '<div class="card"><p class="tag bad">No such page.</p></div>'
        ), 404
    from mediahub.compliance.incidents import IncidentRegister

    title = (request.form.get("title") or "").strip()
    if title:
        IncidentRegister().open(
            title=title,
            severity=request.form.get("severity") or "medium",
            personal_data_involved=bool(request.form.get("personal_data")),
        )
    return redirect(url_for("admin_compliance"))


# Settings — consolidated operations surface.
#
# Brings together the four operator-facing surfaces that used to
# live as separate top-nav items:
#
#   * Activity   — recent runs scoped to the active organisation
#   * Status     — backend uptime and last-incident summary
#   * Privacy    — inventory and delete actions for stored data
#   * Deployment — version, dependency health, and links to deep
#                  operator dashboards (/healthz/usage etc.)
#
# Settings stays reachable without a pinned organisation (it's in
# `_SETUP_EXEMPT_ENDPOINTS`) so the user can audit deployment
# health and clear caches before completing first-run setup.
# Sections that need a profile (Activity) render an inline "sign
# in to see this" stub instead of crashing.
# Settings is a card grid like Create: each heading is a tile you click
# into for the detail. The detail pages are served by ``settings_section``
# below (plus a few that link straight to an existing full page). This
# keeps every heading short and scannable instead of one long scroll.
# Detail pages behind the settings cards. ``developer`` is operator-only;
# everything else is org-scoped and degrades gracefully with no org.
def settings_page():
    return W._render_settings_page()


def set_interface_language():
    """C-16 — set the interface (chrome) language deliberately, with English
    always an off-ramp. Distinct from the org's caption-output language."""
    from mediahub.localize.ui_catalogue import has_ui_locale

    choice = (request.form.get("ui_lang") or "").strip().lower()
    if has_ui_locale(choice):
        session["ui_lang"] = choice.split("-", 1)[0]
    # Return the user to the page they switched from, taken from the Referer
    # (never echoed into a rendered response — see _interface_language_
    # switcher_html). Only a same-origin Referer is honoured; otherwise fall
    # back to Settings so the redirect can't be pointed off-site.
    dest = url_for("settings_page")
    ref = request.referrer or ""
    if ref:
        try:
            from urllib.parse import parse_qsl, urlencode, urlsplit

            parts = urlsplit(ref)
            path = parts.path or ""
            # Same-origin only, and a plain absolute path — reject "//host"
            # and "/\host" which browsers resolve as protocol-relative
            # (an open-redirect vector).
            same_origin = not parts.netloc or parts.netloc == request.host
            safe_path = path.startswith("/") and not path.startswith(("//", "/\\"))
            if same_origin and safe_path:
                # Drop any ``?lang=`` from the referring URL. This POST is the
                # user's deliberate choice; _ui_locale gives ?lang= top
                # precedence and re-pins the session from it, so a stale
                # ?lang=cy in the Referer (e.g. they arrived on a shared
                # /pricing?lang=cy link, then picked English) would silently
                # revert the switch on the very next request. Preserve every
                # other query param.
                kept = [
                    (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "lang"
                ]
                query = urlencode(kept)
                dest = path + (("?" + query) if query else "")
        except Exception:
            dest = url_for("settings_page")
    return redirect(dest)


def settings_section(section):
    renderers = {
        "activity": ("Activity", lambda prof: W._render_settings_activity_section(prof)),
        "audio": ("Audio & voiceover", lambda prof: W._render_settings_audio_section(prof)),
        "scheduling": (
            "Auto scheduling",
            lambda prof: W._render_settings_scheduling_section(prof),
        ),
        "autonomy": ("Autonomy", lambda prof: W._render_settings_autonomy_section(prof)),
        "clubdata": ("Club data", lambda prof: W._render_settings_clubdata_section()),
        "typography": (
            "Typography & fonts",
            lambda prof: W._render_settings_typography_section(prof),
        ),
        "privacy": ("Privacy & data", lambda prof: W._render_settings_privacy_section()),
        "governance": (
            "AI governance",
            lambda prof: W._render_settings_governance_section(prof),
        ),
        "account": ("Account", lambda prof: W._render_settings_account_section()),
        "developer": ("Developer", lambda prof: W._render_settings_developer_section()),
    }
    # G-2: /settings/status used to render the exact same public
    # status card as /status — one canonical page now; old links
    # follow it there.
    if section == "status":
        return redirect(url_for("status_page"))
    entry = renderers.get(section)
    if entry is None:
        return redirect(url_for("settings_page"))
    if section == "developer" and not W._auth.is_dev_operator():
        return redirect(url_for("settings_page"))
    title, render = entry
    prof = W._active_profile()
    back = (
        f'<a href="{url_for("settings_page")}" '
        'style="display:inline-flex;align-items:center;gap:6px;font-size:13px;'
        'color:var(--ink-muted);text-decoration:none;margin-bottom:14px">'
        "&larr; All settings</a>"
    )
    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-6);padding-bottom:var(--sp-3);margin-bottom:var(--sp-2)">'
        '<span class="mh-hero-eyebrow">Settings</span>'
        f'<h1 style="margin-bottom:0">{_h(title)}</h1>'
        "</section>" + back + render(prof)
    )
    return W._layout(f"{title} · Settings", body, active="settings")


def typography_upload_font():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("settings_page"))
    from mediahub.typography import font_intake as _fi

    f = request.files.get("font_file")
    if not f or not f.filename:
        return redirect(url_for("settings_section", section="typography", status="no-file"))
    if not request.form.get("attest"):
        return redirect(url_for("settings_section", section="typography", status="no-attest"))
    role = (request.form.get("role") or "display").strip()
    if role not in _fi.ALLOWED_ROLES:
        role = "display"
    try:
        data = f.read() or b""
    except Exception:
        data = b""
    if not data:
        return redirect(url_for("settings_section", section="typography", status="no-file"))
    try:
        _fi.intake_font(data, profile_id=prof.profile_id, role=role)
    except _fi.FontToolingUnavailable:
        return redirect(url_for("settings_section", section="typography", status="no-tooling"))
    except Exception as e:  # validation / embedding / parse — honest, not fatal
        W.log.info("typography font upload rejected: %s", str(e)[:200])
        return redirect(url_for("settings_section", section="typography", status="bad-font"))
    return redirect(url_for("settings_section", section="typography", status="font-added"))


def typography_remove_font(slug):
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("settings_page"))
    from mediahub.typography import font_intake as _fi

    try:
        _fi.remove_font(prof.profile_id, slug)
    except Exception:
        pass
    return redirect(url_for("settings_section", section="typography", status="font-removed"))


def typography_pair():
    prof = W._active_profile()
    name = prof.display_name if prof else ""
    mood = (request.form.get("mood") or "").strip()[:60]
    back = url_for("settings_section", section="typography")
    from mediahub.brand import design_tokens as _dt
    from mediahub.brand.type_pairing import PairingContext

    try:
        result = _dt.ai_type_pairing(PairingContext(club_name=name, mood=mood))
    except Exception as e:
        # H-16: honest, plain-English failure — the raw exception goes to
        # the server log only, never the page (and never a fabricated
        # pairing).
        W.log.warning("AI font pairing failed: %s", e, exc_info=True)
        from mediahub.ai_core import ProviderNotConfigured as _PNC
        from mediahub.media_ai.llm import ClaudeUnavailableError as _CUE

        if isinstance(e, (_PNC, _CUE)):
            msg = "AI suggestions are unavailable on this deployment."
        else:
            msg = "We could not suggest a pairing just now — please try again in a moment."
        body = (
            '<section class="mh-hero"><span class="mh-hero-eyebrow">Typography</span>'
            '<h1 style="margin-bottom:0">AI pairing</h1></section>'
            f'<div class="card"><p style="color:var(--bad)">{_h(msg)}</p>'
            f'<a class="btn" href="{back}">Back to typography</a></div>'
        )
        return W._layout("Typography · pairing", body, active="settings")
    corrected = (
        '<p style="font-size:12px;color:var(--ink-muted)">(adjusted to the nearest '
        "catalogue faces)</p>"
        if result.get("corrected")
        else ""
    )
    # H-16: the suggestion is applicable, not a dead end — the form carries
    # the trio to typography_pair_apply, which persists it to the brand kit.
    apply_form = (
        f'<form method="post" action="{url_for("typography_pair_apply")}" '
        'style="display:inline-block;margin-right:8px">'
        f'<input type="hidden" name="pairing" value="{_h(result.get("pairing") or "")}">'
        f'<input type="hidden" name="headline_family" value="{_h(result["headline_family"])}">'
        f'<input type="hidden" name="body_family" value="{_h(result["body_family"])}">'
        f'<input type="hidden" name="numeral_family" value="{_h(result["numeral_family"])}">'
        '<button class="btn" type="submit">Apply this pairing to my brand</button></form>'
    )
    body = (
        '<section class="mh-hero"><span class="mh-hero-eyebrow">Typography</span>'
        '<h1 style="margin-bottom:0">Suggested pairing</h1></section>'
        '<div class="card"><p style="font-size:15px">'
        f"<strong>Headline:</strong> {_h(result['headline_family'])}<br>"
        f"<strong>Body:</strong> {_h(result['body_family'])}<br>"
        f"<strong>Numerals:</strong> {_h(result['numeral_family'])}</p>"
        f'<p style="color:var(--ink-dim)">{_h(result["reason"])}</p>{corrected}'
        f'{apply_form}<a class="btn ghost" href="{back}">Back to typography</a></div>'
    )
    return W._layout("Typography · pairing", body, active="settings")


def typography_pair_apply():
    """H-16: persist an AI-suggested pairing to the active club's brand kit.

    The trio is re-validated against the self-hosted catalogue (family
    names only — a form value can't smuggle an arbitrary font), then saved
    through the brand write path everything else uses (``save_brand`` on
    the profile JSON). ``resolve_design_tokens`` surfaces it as the
    club's ``type`` block.
    """
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("settings_page"))
    from mediahub.typography import catalog as _cat

    families = {f.family for f in _cat.load_catalog()}
    headline = (request.form.get("headline_family") or "").strip()
    body_family = (request.form.get("body_family") or "").strip()
    numeral = (request.form.get("numeral_family") or "").strip()
    if not ({headline, body_family, numeral} <= families):
        return redirect(url_for("settings_section", section="typography", status="pairing-invalid"))
    # The renderer override key the AI path emits (Pairing.typography_pair).
    pairing_key = (request.form.get("pairing") or "").strip().lower()
    if pairing_key not in {"anton-inter", "bebas-grotesk", "bowlby-inter"}:
        pairing_key = "anton-inter"
    from mediahub.brand.store import load_brand, save_brand

    kit, _tone_unused, _templates_unused = load_brand(prof.profile_id)
    kit.type_pairing = {
        "pairing": pairing_key,
        "headline_family": headline,
        "body_family": body_family,
        "numeral_family": numeral,
        "source": "ai",
    }
    save_brand(prof.profile_id, kit=kit)
    # save_brand writes the profile JSON directly (not via save_profile), so
    # the save hook never fires — drop the cached copy ourselves so any
    # later read in this request sees the new type pairing, not the pre-save
    # brand_kit.
    W._invalidate_profile_cache(prof.profile_id)
    return redirect(url_for("settings_section", section="typography", status="pairing-applied"))


def operator_notify_users():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.backup import last_backup_state
    from mediahub.notify.email import EmailNotConfigured, email_configured, send_to_many

    emails = W._user_store().all_emails()
    sent_html = ""
    if request.method == "POST":
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()
        if not subject or not message:
            sent_html = (
                '<p class="tag bad" style="margin-bottom:16px">Subject and '
                "message are both required.</p>"
            )
        else:
            try:
                result = send_to_many(emails, subject, message)
            except EmailNotConfigured:
                return W._email_unavailable_page("Notify users unavailable")
            W._record_operator_notice(subject, result)
            failed = result["failed"]
            sent_html = (
                f'<p class="tag good" style="margin-bottom:16px">Sent to '
                f"{result['sent']} of {len(emails)} account(s)."
                + (f" Failed: {_h(', '.join(failed))}." if failed else "")
                + " Recorded in the notice ledger.</p>"
            )
    seam_line = (
        '<p class="tag good">Email delivery is configured.</p>'
        if email_configured()
        else '<p class="tag bad">Email delivery is NOT configured '
        "(set RESEND_API_KEY + MEDIAHUB_EMAIL_FROM) — sending will fail "
        "honestly until it is.</p>"
    )
    backup_state = last_backup_state()
    backup_line = (
        f"Last backup: <strong>{_h(str(backup_state.get('last_backup_at')))}</strong> "
        f"({int(backup_state.get('bytes') or 0):,} bytes; "
        f"off-site upload: {'yes' if backup_state.get('uploaded') else 'no'})"
        if backup_state
        else "No backup has run yet on this deployment."
    )
    # Ledger tail (newest 5) so the operator sees the evidence trail.
    rows = ""
    try:
        if W._operator_notices_path().exists():
            lines = W._operator_notices_path().read_text(encoding="utf-8").splitlines()
            for ln in lines[-5:][::-1]:
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                rows += (
                    f"<tr><td>{_h(str(rec.get('sent_at')))}</td>"
                    f"<td>{_h(str(rec.get('subject')))}</td>"
                    f"<td>{int(rec.get('recipients_sent') or 0)}</td></tr>"
                )
    except OSError:
        pass
    ledger_html = (
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        "<thead><tr style='text-align:left'><th>Sent</th><th>Subject</th>"
        "<th>Recipients</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows
        else '<p class="dim" style="font-size:13px">No notices sent yet.</p>'
    )
    body = f"""
<h1 style="margin-bottom:4px">Notify all users</h1>
<p class="dim" style="margin-bottom:20px;max-width:640px">The breach-notification
channel (incident runbook step 4): one message to every account email on this
deployment. Every send is recorded. Use plain language — what happened, what data,
what you're doing, what they should do.</p>
{seam_line}
{sent_html}
<div class="card" style="max-width:640px;margin-bottom:20px">
  <form method="post" action="{url_for("operator_notify_users")}"
        onsubmit="return confirm('Send this to ALL {len(emails)} account(s)?')">
    <label style="display:block;font-size:12px;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink-muted);margin-bottom:6px">Subject</label>
    <input type="text" name="subject" required style="width:100%;margin-bottom:14px" />
    <label style="display:block;font-size:12px;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink-muted);margin-bottom:6px">Message (plain text)</label>
    <textarea name="message" required rows="10" style="width:100%"></textarea>
    <button type="submit" class="btn" style="margin-top:16px">Send to {len(emails)} account(s)</button>
  </form>
</div>
<div class="card" style="max-width:640px;margin-bottom:20px">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Recovery state</h3>
  <p style="font-size:13px">{backup_line}</p>
</div>
<div class="card" style="max-width:640px">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Notice ledger (latest 5)</h3>
  {ledger_html}
</div>
"""
    return W._layout("Notify all users", body, active="")


def operator_cache_purge():
    """Permanently delete every re-derivable cache, site-wide.

    Operator-only: this clears the cache for the whole deployment — all
    organisations, all runs. Only re-derivable performance caches are
    touched (PB lookups, motion/graphic renders, brand-DNA captures,
    narration, web research); runs, uploads, the databases, the media
    library and the ledgers are never removed. The engine re-derives what
    it needs on the next request.
    """
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.privacy.cache_purge import purge_all_caches

    try:
        report = purge_all_caches()
    except Exception as e:  # honest failure rather than a silent no-op
        W.log.warning("site-wide cache purge failed: %s", e, exc_info=True)
        W._flash_toast(f"Cache purge failed: {e}", "error")
        return redirect(url_for("settings_section", section="developer"))

    # Drop this process's own derived caches too, so a purge doesn't leave
    # the worker serving "why this card" / perf-context strings or
    # design-studio render previews from memory. (The graphic-renderer
    # module caches are dropped inside purge_all_caches; these BoundedCaches
    # live in web.py and can't be imported there without a cycle.)
    try:
        W._perf_context_cache.clear()
        W._explanation_cache.clear()
        W._studio_render_cache.clear()
        W._cache_tally_cache.clear()
    except Exception:
        pass

    files = int(report.get("files_deleted") or 0)
    mb = (report.get("bytes_reclaimed") or 0) / (1024 * 1024)
    W._flash_toast(
        f"Site-wide cache cleared — {files:,} file(s) deleted, {mb:.1f} MB "
        "reclaimed; this worker's in-process caches dropped from memory "
        "(any sibling worker refreshes as its own entries expire).",
        "success",
    )
    return redirect(url_for("settings_section", section="developer"))


def operator_data_purge():
    """Permanently delete every run and every draft, site-wide.

    Operator-only. Unlike the cache purge, this removes SOURCE data — every
    organisation's processed runs (the Activity history) and every saved
    draft (the Drafts tab) — and it is NOT re-derivable. Each run goes
    through the same full deletion cascade a single-run delete uses (run
    file + per-run sidecars + PB cache, caption memory, motion cache, emoji
    reactions, in-memory progress); each draft pack file is removed.
    Uploads, club profiles, brand kits, the media library and the databases'
    own schema are untouched.
    """
    guard = W._require_operator()
    if guard is not None:
        return guard

    runs_deleted = 0
    drafts_deleted = 0
    try:
        # Enumerate every run id: DB rows ∪ on-disk run files, so a run
        # tracked in only one place is still reached.
        run_ids: set[str] = set()
        try:
            conn = W._db()
            for row in conn.execute("SELECT id FROM runs").fetchall():
                rid = row["id"]
                if rid:
                    run_ids.add(str(rid))
            conn.close()
        except Exception:
            W.log.warning("data purge: run-table scan failed", exc_info=True)
        try:
            for p in W.RUNS_DIR.glob("*.json"):
                # Skip per-run sidecars (<run_id>__workflow.json,
                # <run_id>__approvals.json, …) so they aren't counted as
                # phantom runs — the same `__` guard every other RUNS_DIR
                # scanner uses. Their real run id is reached via <run_id>.json
                # or the DB row, and _delete_run removes the sidecars anyway.
                if "__" in p.name:
                    continue
                run_ids.add(p.stem)
        except OSError:
            pass
        for rid in run_ids:
            try:
                W._delete_run(rid)
                runs_deleted += 1
            except Exception:
                W.log.warning("data purge: failed to delete run %s", rid, exc_info=True)

        # Every draft pack across all organisations.
        from mediahub.club_platform.stub_pack_store import delete_pack, list_packs

        for it in list_packs(limit=1_000_000):
            pack_id = it.get("pack_id", "")
            if pack_id and delete_pack(pack_id):
                drafts_deleted += 1
    except Exception as e:  # honest failure rather than a silent no-op
        W.log.warning("site-wide data purge failed: %s", e, exc_info=True)
        W._flash_toast(f"Data purge failed: {e}", "error")
        return redirect(url_for("settings_section", section="developer"))

    W._flash_toast(
        f"All runs and drafts cleared site-wide — {runs_deleted:,} run(s) and "
        f"{drafts_deleted:,} draft(s) deleted across every organisation. "
        "Activity and Drafts are now empty.",
        "success",
    )
    return redirect(url_for("settings_section", section="developer"))


def operator_commercial():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.commercial import ngb as _ngb
    from mediahub.commercial.pipeline import (
        LeadStore,
        VALID_SOURCES,
        VALID_STATUSES as LEAD_STATUSES,
        funnel_summary,
        referral_debt,
        warm_first_discipline,
    )
    from mediahub.commercial.wtp import QuoteStore, pc4_pricing_gate, traction_gate

    notice = session.pop("op_notice", "")
    error = session.pop("op_error", "")
    quotes = QuoteStore().list_all()
    leads = LeadStore().list_all()
    pc4 = pc4_pricing_gate(quotes)
    traction = traction_gate(quotes)
    funnel = funnel_summary(leads)
    discipline = warm_first_discipline(leads)
    debt = referral_debt(leads)
    ngb_state = _ngb.load_state()

    def _gate_card(title, n, req, met, detail):
        colour = "var(--good)" if met else "var(--warn)"
        badge = "MET" if met else "OPEN"
        return (
            '<div class="card" style="padding:18px 22px;flex:1;min-width:min(260px,100%)">'
            f'<h2 style="margin:0 0 6px;font-size:15px">{title}</h2>'
            f'<div style="font-size:28px;font-weight:700">{n}<span '
            f'style="font-size:15px;color:var(--ink-muted)"> / {req}</span> '
            f'<span class="pill" style="color:{colour};border-color:{colour}">'
            f"{badge}</span></div>"
            f'<p class="dim" style="font-size:12px;margin:8px 0 0">{detail}</p></div>'
        )

    tested = ", ".join(W._pence_str(p) for p in pc4["tested_prices_pence"]) or "none yet"
    gates_html = (
        '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px">'
        + _gate_card(
            "PC.4 pricing gate — publish a list price only when met",
            pc4["paid_clubs"],
            pc4["required"],
            pc4["met"],
            f"Distinct clubs paid annual at a tested price. Tested prices: {_h(tested)}. "
            "Until met, /pricing stays at “Pricing TBC” (ADR-0011).",
        )
        + _gate_card(
            "Traction gate — Phase C exit (gates P3/P4/P5)",
            traction["paying_clubs"],
            traction["required"],
            traction["met"],
            "Distinct clubs paying annually. No new sport before this is met.",
        )
        + "</div>"
    )

    # ---- quotes table ------------------------------------------------
    q_rows = ""
    for q in quotes:
        status_colour = {
            "paid": "var(--good)",
            "payment_mismatch": "var(--bad, #f87171)",
            "declined": "var(--ink-muted)",
        }.get(q.status, "var(--warn)")
        actions = (
            f'<form method="post" action="{url_for("operator_commercial_quote_update")}" '
            'style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
            f'<input type="hidden" name="quote_id" value="{_h(q.quote_id)}"/>'
            '<button class="btn secondary" style="padding:3px 8px;font-size:11px" '
            'name="op" value="accepted">Accepted</button>'
            '<button class="btn secondary" style="padding:3px 8px;font-size:11px" '
            'name="op" value="declined">Declined</button>'
            '<button class="btn secondary" style="padding:3px 8px;font-size:11px" '
            'name="op" value="checkout">Checkout link</button>'
            '<span style="white-space:nowrap"><input name="paid_pounds" '
            'placeholder="£ paid" style="width:70px;padding:3px 6px;font-size:11px"/>'
            '<button class="btn secondary" style="padding:3px 8px;font-size:11px" '
            'name="op" value="paid_manual">Record payment</button></span>'
            "</form>"
        )
        link_html = (
            f'<div style="font-size:10px;word-break:break-all;color:var(--ink-muted)">'
            f"{_h(q.last_checkout_url)}</div>"
            if q.last_checkout_url
            else ""
        )
        paid_html = f"{W._pence_str(q.paid_amount_pence)} ({_h(q.method)})" if q.method else "—"
        q_rows += (
            "<tr>"
            f'<td style="padding:7px 10px">{_h(q.club_name)}'
            f'<div style="font-size:11px;color:var(--ink-muted)">{_h(q.contact_email)}</div></td>'
            f'<td style="padding:7px 10px">{W._pence_str(q.amount_pence)}/yr</td>'
            f'<td style="padding:7px 10px"><span class="pill" '
            f'style="color:{status_colour};border-color:{status_colour}">'
            f"{_h(q.status)}</span></td>"
            f'<td style="padding:7px 10px">{paid_html}</td>'
            f'<td style="padding:7px 10px">{actions}{link_html}</td>'
            "</tr>"
        )
    if not q_rows:
        q_rows = (
            '<tr><td colspan="5" style="padding:12px;color:var(--ink-muted)">'
            "No quotes yet — quote a real annual price to every prospect club "
            "and record the outcome here.</td></tr>"
        )
    quotes_html = (
        '<div class="card" style="padding:20px 24px;margin-bottom:22px">'
        '<h2 style="margin-top:0;font-size:16px">Revealed-WTP quotes (PC.4)</h2>'
        '<p class="dim" style="font-size:12px;margin:0 0 12px">'
        "Vary the annual price across clubs; only a verified payment at the "
        "quoted amount counts. “Checkout link” creates a Stripe Checkout at "
        "exactly the quoted annual price (requires STRIPE_SECRET_KEY).</p>"
        '<table style="width:100%;border-collapse:collapse;font-size:12px">'
        '<thead><tr style="text-align:left;border-bottom:1px solid rgba(255,255,255,0.08)">'
        "<th style='padding:7px 10px'>Club</th><th style='padding:7px 10px'>Quoted</th>"
        "<th style='padding:7px 10px'>Status</th><th style='padding:7px 10px'>Paid</th>"
        "<th style='padding:7px 10px'>Actions</th></tr></thead>"
        f"<tbody>{q_rows}</tbody></table>"
        f'<form method="post" action="{url_for("operator_commercial_quote_add")}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:14px">'
        '<div><label style="font-size:11px">Club</label><br/>'
        '<input name="club_name" required style="padding:6px 8px"/></div>'
        '<div><label style="font-size:11px">Contact email</label><br/>'
        '<input name="contact_email" type="email" style="padding:6px 8px"/></div>'
        '<div><label style="font-size:11px">Annual price (£)</label><br/>'
        '<input name="pounds" required placeholder="588" style="padding:6px 8px;width:90px"/></div>'
        '<div><label style="font-size:11px">Notes</label><br/>'
        '<input name="notes" style="padding:6px 8px;min-width:min(200px,100%)"/></div>'
        '<button class="btn" type="submit">Add quote</button></form></div>'
    )

    # ---- pipeline ------------------------------------------------------
    src_counts = (
        " &middot; ".join(f"{_h(k)}: {v}" for k, v in funnel["by_source"].items() if v) or "none"
    )
    status_counts = (
        " &middot; ".join(f"{_h(k)}: {v}" for k, v in funnel["by_status"].items() if v) or "none"
    )
    discipline_html = (
        f'<p class="tag bad" style="margin:8px 0 0">Cold share '
        f"{discipline['cold_share']:.0%} exceeds the capped-supplement threshold "
        f"({discipline['threshold']:.0%}) — the gate is reached warm + referral, "
        "not cold broadcast.</p>"
        if discipline["warn"]
        else (
            f'<p class="dim" style="font-size:12px;margin:8px 0 0">Cold share '
            f"{discipline['cold_share']:.0%} (capped-supplement threshold "
            f"{discipline['threshold']:.0%}).</p>"
        )
    )
    debt_html = ""
    if debt:
        items = "".join(
            f"<li>{_h(d['club_name'])} — {d['intros_recorded']}/2 intros "
            f"({d.get('intros_code_tracked', 0)} code-tracked, "
            f"{d['intros_recorded'] - d.get('intros_code_tracked', 0)} typed)</li>"
            for d in debt
        )
        debt_html = (
            '<p class="tag warn" style="margin:10px 0 4px">Referral debt — each '
            "signed club owes 2 named intros (code-tracked signups count "
            f"automatically):</p><ul style='font-size:12px'>{items}</ul>"
        )
    # PC.9 — live referral state: codes, code-tracked signups, rewards.
    referral_html = ""
    try:
        from mediahub.commercial.referrals import (
            ReferralCodeStore,
            ReferralRewardStore,
        )

        _codes = ReferralCodeStore()._by_profile()
        _rewards = ReferralRewardStore().list_all()
        referred = [ld for ld in leads if ld.source == "referral"]
        code_rows = "".join(
            f"<tr><td style='padding:6px 10px'><code>{_h(rc.code)}</code></td>"
            f"<td style='padding:6px 10px'>{_h(rc.club_name or rc.profile_id)}</td>"
            f"<td style='padding:6px 10px;font-size:11px;color:var(--ink-muted)'>"
            f"{_h(url_for('signup_page', ref=rc.code, _external=True))}</td></tr>"
            for rc in sorted(_codes.values(), key=lambda r: r.club_name.lower())
        ) or (
            "<tr><td colspan='3' style='padding:10px;color:var(--ink-muted)'>"
            "No codes minted yet — each org gets one the first time its "
            "Organisation page renders.</td></tr>"
        )
        referred_rows = "".join(
            f"<tr><td style='padding:6px 10px'>{_h(ld.club_name)}</td>"
            f"<td style='padding:6px 10px'>{_h(ld.referrer_club)}</td>"
            f"<td style='padding:6px 10px'>{_h(ld.status)}</td></tr>"
            for ld in referred
        ) or (
            "<tr><td colspan='3' style='padding:10px;color:var(--ink-muted)'>"
            "No code-tracked signups yet.</td></tr>"
        )
        reward_rows = "".join(
            f"<tr><td style='padding:6px 10px'>{_h(rw.referrer_club)}</td>"
            f"<td style='padding:6px 10px'>{_h(rw.referred_club)}</td>"
            f"<td style='padding:6px 10px'>{_h(rw.status)}"
            + (
                f"<div style='font-size:11px;color:var(--ink-muted)'>{_h(rw.reason)}</div>"
                if rw.reason
                else ""
            )
            + "</td>"
            f"<td style='padding:6px 10px'>{W._pence_str(rw.amount_off_pence) if rw.amount_off_pence else '—'}</td></tr>"
            for rw in _rewards
        ) or (
            "<tr><td colspan='4' style='padding:10px;color:var(--ink-muted)'>"
            "No rewards yet — the first verified referred payment grants one "
            "automatically.</td></tr>"
        )
        referral_html = (
            '<div class="card" style="padding:20px 24px;margin-bottom:22px">'
            '<h2 style="margin-top:0;font-size:16px">Referral engine (PC.9)</h2>'
            '<p class="dim" style="font-size:12px;margin:0 0 10px">Codes are shared '
            "by clubs from their Organisation page; signups through a code land in "
            "the pipeline automatically and a verified annual payment grants the "
            "referrer one free month (Stripe coupon) with zero typing.</p>"
            '<table style="width:100%;border-collapse:collapse;font-size:12px">'
            "<thead><tr style='text-align:left'><th style='padding:6px 10px'>Code</th>"
            "<th style='padding:6px 10px'>Org</th><th style='padding:6px 10px'>Share link</th></tr></thead>"
            f"<tbody>{code_rows}</tbody></table>"
            '<h3 style="font-size:13px;margin:14px 0 4px">Code-tracked signups</h3>'
            '<table style="width:100%;border-collapse:collapse;font-size:12px">'
            "<thead><tr style='text-align:left'><th style='padding:6px 10px'>Lead</th>"
            "<th style='padding:6px 10px'>Referred by</th><th style='padding:6px 10px'>Stage</th></tr></thead>"
            f"<tbody>{referred_rows}</tbody></table>"
            '<h3 style="font-size:13px;margin:14px 0 4px">Rewards</h3>'
            '<table style="width:100%;border-collapse:collapse;font-size:12px">'
            "<thead><tr style='text-align:left'><th style='padding:6px 10px'>Referrer</th>"
            "<th style='padding:6px 10px'>Referred club</th><th style='padding:6px 10px'>Status</th>"
            "<th style='padding:6px 10px'>Value</th></tr></thead>"
            f"<tbody>{reward_rows}</tbody></table></div>"
        )
    except Exception:
        W.log.warning("referral console section failed", exc_info=True)
    l_rows = ""
    for lead in leads:
        sel = "".join(
            f'<option value="{s}"{" selected" if s == lead.status else ""}>{s}</option>'
            for s in sorted(LEAD_STATUSES)
        )
        l_rows += (
            "<tr>"
            f'<td style="padding:7px 10px">{_h(lead.club_name)}'
            f'<div style="font-size:11px;color:var(--ink-muted)">{_h(lead.region)}</div></td>'
            f'<td style="padding:7px 10px">{_h(lead.source)}'
            + (
                f'<div style="font-size:11px;color:var(--ink-muted)">via {_h(lead.referrer_club)}</div>'
                if lead.referrer_club
                else ""
            )
            + "</td>"
            f'<td style="padding:7px 10px">'
            f'<form method="post" action="{url_for("operator_commercial_lead_update")}" '
            'style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
            f'<input type="hidden" name="lead_id" value="{_h(lead.lead_id)}"/>'
            f'<select name="status" style="padding:3px 6px;font-size:11px">{sel}</select>'
            f'<input name="intros" placeholder="2 named intros, comma-sep" '
            f'value="{_h(", ".join(lead.intros))}" style="padding:3px 6px;font-size:11px;min-width:min(170px,100%)"/>'
            '<button class="btn secondary" style="padding:3px 8px;font-size:11px">Update</button>'
            "</form></td></tr>"
        )
    if not l_rows:
        l_rows = (
            '<tr><td colspan="3" style="padding:12px;color:var(--ink-muted)">'
            "No leads yet — start with the local-warm Swansea / South-East-Wales "
            "base, then compound through referrals.</td></tr>"
        )
    src_options = "".join(f'<option value="{s}">{s}</option>' for s in sorted(VALID_SOURCES))
    pipeline_html = (
        '<div class="card" style="padding:20px 24px;margin-bottom:22px">'
        '<h2 style="margin-top:0;font-size:16px">Warm-first pipeline (PC.6)</h2>'
        f'<p class="dim" style="font-size:12px;margin:0">Sources — {src_counts}</p>'
        f'<p class="dim" style="font-size:12px;margin:4px 0 0">Stages — {status_counts}</p>'
        + discipline_html
        + debt_html
        + '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:12px">'
        '<thead><tr style="text-align:left;border-bottom:1px solid rgba(255,255,255,0.08)">'
        "<th style='padding:7px 10px'>Club</th><th style='padding:7px 10px'>Source</th>"
        "<th style='padding:7px 10px'>Stage / intros</th></tr></thead>"
        f"<tbody>{l_rows}</tbody></table>"
        f'<form method="post" action="{url_for("operator_commercial_lead_add")}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:14px">'
        '<div><label style="font-size:11px">Club</label><br/>'
        '<input name="club_name" required style="padding:6px 8px"/></div>'
        '<div><label style="font-size:11px">Region</label><br/>'
        '<input name="region" placeholder="Swansea" style="padding:6px 8px;width:110px"/></div>'
        '<div><label style="font-size:11px">Source</label><br/>'
        f'<select name="source" style="padding:6px 8px">{src_options}</select></div>'
        '<div><label style="font-size:11px">Referrer (if referral)</label><br/>'
        '<input name="referrer_club" style="padding:6px 8px"/></div>'
        '<button class="btn" type="submit">Add lead</button></form></div>'
    )

    # ---- NGB + workspace binding --------------------------------------
    ngb_opts = "".join(
        f'<option value="{s}"{" selected" if s == ngb_state["status"] else ""}>{s}</option>'
        for s in _ngb.VALID_STATUSES
    )
    ngb_html = (
        '<div class="card" style="padding:20px 24px;margin-bottom:22px">'
        '<h2 style="margin-top:0;font-size:16px">Swim England approved-systems API (PC.6a)</h2>'
        '<p class="dim" style="font-size:12px;margin:0 0 10px">'
        "Official data-API access is real — apply (ADR-0012). It grants data + "
        "credibility, not promotion. Application draft: "
        f"<code style='font-size:11px'>{_h(_ngb.APPLICATION_DOC)}</code>"
        + (f" &middot; applied {_h(ngb_state['applied_at'])}" if ngb_state["applied_at"] else "")
        + "</p>"
        f'<form method="post" action="{url_for("operator_commercial_ngb")}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">'
        '<div><label style="font-size:11px">Status</label><br/>'
        f'<select name="status" style="padding:6px 8px">{ngb_opts}</select></div>'
        '<div><label style="font-size:11px">Notes</label><br/>'
        f'<input name="notes" value="{_h(ngb_state["notes"])}" '
        'style="padding:6px 8px;min-width:min(260px,100%)"/></div>'
        '<button class="btn secondary" type="submit">Save</button></form></div>'
    )

    ms = W._tenancy.MembershipStore()
    org_rows = ""
    for p in W.list_profiles():
        members = ms.list_for_profile(p.profile_id)
        active_n = sum(1 for m in members if m.status == W._tenancy.STATUS_ACTIVE)
        invited = [m for m in members if m.status == W._tenancy.STATUS_INVITED]
        state = (
            f"bound &middot; {active_n} member" + ("s" if active_n != 1 else "")
            if ms.is_bound(p.profile_id)
            else "open (unbound)"
        )
        inv = (
            '<div style="font-size:11px;color:var(--warn)">invited: '
            + ", ".join(_h(m.email) for m in invited)
            + "</div>"
            if invited
            else ""
        )
        org_rows += (
            "<tr>"
            f'<td style="padding:7px 10px">{_h(p.display_name)} '
            f'<span style="font-size:11px;color:var(--ink-muted)">({_h(p.profile_id)})</span></td>'
            f'<td style="padding:7px 10px">{state}{inv}</td>'
            "</tr>"
        )
    bind_html = (
        '<div class="card" style="padding:20px 24px;margin-bottom:22px">'
        '<h2 style="margin-top:0;font-size:16px">Workspace binding (PC.3)</h2>'
        '<p class="dim" style="font-size:12px;margin:0 0 10px">'
        "Pre-bind each pilot club's contact email as an invited owner — the org "
        "stays open until that email signs up, then becomes members-only with "
        "zero further founder involvement (ADR-0014).</p>"
        '<table style="width:100%;border-collapse:collapse;font-size:12px">'
        f"<tbody>{org_rows or ''}</tbody></table>"
        f'<form method="post" action="{url_for("operator_commercial_bind")}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:12px">'
        '<div><label style="font-size:11px">Profile id</label><br/>'
        '<input name="profile_id" required placeholder="org-slug" style="padding:6px 8px"/></div>'
        '<div><label style="font-size:11px">Owner email</label><br/>'
        '<input name="email" type="email" required style="padding:6px 8px"/></div>'
        '<button class="btn" type="submit">Invite as owner</button></form></div>'
    )

    flash_html = ""
    if notice:
        flash_html += f'<p class="tag good" style="margin-bottom:14px">{_h(notice)}</p>'
    if error:
        flash_html += f'<p class="tag bad" style="margin-bottom:14px">{_h(error)}</p>'
    body = (
        "<h1>Commercial console</h1>"
        '<p class="lede" style="margin-bottom:var(--sp-6)">Phase C sell-side: '
        "revealed-WTP price discovery, the warm-first funnel, the NGB data-API "
        "application, and pilot workspace binding. Operator-only.</p>"
        + flash_html
        + gates_html
        + quotes_html
        + pipeline_html
        + referral_html
        + ngb_html
        + bind_html
    )
    return W._layout("Commercial console", body, active="")


def operator_commercial_quote_add():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.commercial.wtp import QuoteError, QuoteStore

    pence = W._pounds_to_pence(request.form.get("pounds") or "")
    try:
        if pence <= 0:
            raise QuoteError("Enter the annual price in pounds, e.g. 588 or 49.50.")
        q = QuoteStore().create(
            request.form.get("club_name") or "",
            pence,
            contact_email=request.form.get("contact_email") or "",
            notes=request.form.get("notes") or "",
        )
        W._op_flash(notice=f"Quoted {W._pence_str(q.amount_pence)}/yr to {q.club_name}.")
    except QuoteError as exc:
        W._op_flash(error=str(exc))
    return redirect(url_for("operator_commercial"))


def operator_commercial_quote_update():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.commercial.wtp import QuoteError, QuoteStore

    store = QuoteStore()
    quote_id = (request.form.get("quote_id") or "").strip()
    op = (request.form.get("op") or "").strip().lower()
    try:
        if op in ("accepted", "declined"):
            q = store.set_status(quote_id, op)
            W._op_flash(notice=f"{q.club_name}: {q.status}.")
        elif op == "paid_manual":
            pence = W._pounds_to_pence(request.form.get("paid_pounds") or "")
            if pence <= 0:
                raise QuoteError("Enter the amount actually paid (in pounds).")
            q = store.record_manual_payment(quote_id, amount_pence=pence)
            W._op_flash(
                notice=(
                    f"{q.club_name}: payment recorded — {q.status} "
                    f"({W._pence_str(q.paid_amount_pence)} vs quoted {W._pence_str(q.amount_pence)})."
                )
            )
            # PC.9: an attested verified payment settles referrals the
            # same way the webhook does (idempotent per quote).
            try:
                from mediahub.commercial.referrals import on_verified_quote_payment

                on_verified_quote_payment(q)
            except Exception:
                W.log.warning("referral settlement failed", exc_info=True)
        elif op == "checkout":
            q = store.get(quote_id)
            if q is None:
                raise QuoteError("No such quote.")
            if not W._billing.billing_configured():
                raise QuoteError(
                    "Billing is not configured (set STRIPE_SECRET_KEY) — "
                    "record the payment manually instead."
                )
            url = W._billing.create_quote_checkout_session(
                quote_id=q.quote_id,
                club_name=q.club_name,
                amount_pence=q.amount_pence,
                currency=q.currency,
                customer_email=q.contact_email,
                success_url=url_for("signup_page", _external=True),
                cancel_url=url_for("pricing_page", _external=True),
            )
            store.set_checkout_url(q.quote_id, url)
            W._op_flash(notice=f"Checkout link created for {q.club_name} — copy it below.")
        else:
            raise QuoteError("Unknown quote action.")
    except (W._billing.BillingError, QuoteError) as exc:
        W._op_flash(error=str(exc))
    return redirect(url_for("operator_commercial"))


def operator_commercial_lead_add():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.commercial.pipeline import LeadStore, PipelineError

    try:
        lead = LeadStore().create(
            request.form.get("club_name") or "",
            source=request.form.get("source") or "",
            region=request.form.get("region") or "",
            referrer_club=request.form.get("referrer_club") or "",
        )
        W._op_flash(notice=f"Lead added: {lead.club_name} ({lead.source}).")
    except PipelineError as exc:
        W._op_flash(error=str(exc))
    return redirect(url_for("operator_commercial"))


def operator_commercial_lead_update():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.commercial.pipeline import LeadStore, PipelineError

    store = LeadStore()
    lead_id = (request.form.get("lead_id") or "").strip()
    try:
        lead = store.set_status(lead_id, request.form.get("status") or "")
        intros_raw = request.form.get("intros")
        if intros_raw is not None:
            store.set_intros(lead_id, [s for s in intros_raw.split(",")])
        W._op_flash(notice=f"{lead.club_name}: updated.")
    except PipelineError as exc:
        W._op_flash(error=str(exc))
    return redirect(url_for("operator_commercial"))


def operator_commercial_ngb():
    guard = W._require_operator()
    if guard is not None:
        return guard
    from mediahub.commercial import ngb as _ngb

    try:
        state = _ngb.save_state(
            request.form.get("status") or "", notes=request.form.get("notes") or ""
        )
        W._op_flash(notice=f"NGB application: {state['status']}.")
    except ValueError as exc:
        W._op_flash(error=str(exc))
    return redirect(url_for("operator_commercial"))


def operator_commercial_bind():
    guard = W._require_operator()
    if guard is not None:
        return guard
    pid = (request.form.get("profile_id") or "").strip()
    email = (request.form.get("email") or "").strip()
    if not W.load_profile(pid):
        W._op_flash(error=f"No profile with id '{pid}'.")
        return redirect(url_for("operator_commercial"))
    try:
        has_account = W._user_store().get(email) is not None
        m = W._tenancy.MembershipStore().add(
            email,
            pid,
            role=W._tenancy.ROLE_OWNER,
            status=(W._tenancy.STATUS_ACTIVE if has_account else W._tenancy.STATUS_INVITED),
            invited_by=W._auth._dev_operator_email(),
            invited_via_profile_id=pid,
        )
        W._invalidate_memberships_snapshot()
        W._op_flash(
            notice=(
                f"{m.email} bound as owner of {pid}."
                if m.status == W._tenancy.STATUS_ACTIVE
                else (f"{m.email} invited as owner of {pid} — binds when they sign up.")
            )
        )
    except W._tenancy.TenancyError as exc:
        W._op_flash(error=str(exc))
    return redirect(url_for("operator_commercial"))


def billing_page():
    # Auth gate: must be logged in to see/manage billing.
    user = W._auth.current_user(W._user_store())
    if user is None:
        return redirect(url_for("login_page", next=url_for("billing_page")))

    if not W._billing.billing_configured():
        body = (
            '<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
            '<span class="mh-hero-eyebrow">Billing</span>'
            "<h1>Billing</h1>"
            '<p class="lede">Manage your subscription.</p>'
            "</section>"
            '<div class="card" style="padding:24px 28px;max-width:560px">'
            '<p style="margin-top:0">'
            f"{_h(W._billing.NOT_CONFIGURED_MESSAGE.capitalize())}. "
            "You&rsquo;re on the Free plan with full access to the core "
            "features. There&rsquo;s nothing to manage here on this deployment."
            "</p>"
            '<div style="display:flex;gap:10px;flex-wrap:wrap">'
            f'<a class="btn secondary" href="{url_for("home")}">Back to home</a>'
            f'<a class="btn secondary" href="{url_for("pricing_page")}">See plans &amp; pricing &rarr;</a>'
            "</div>"
            "</div>"
        )
        return W._layout("Billing", body, active="signin")

    plan = W._auth.plan_label(user.plan)
    has_customer = bool(user.stripe_customer_id)
    manage_html = ""
    if has_customer:
        manage_html = (
            f'<form method="post" action="{url_for("billing_portal")}" style="margin:0">'
            '<button type="submit" class="btn">Manage subscription &rarr;</button>'
            "</form>"
            '<div class="dim" style="font-size:12px;margin-top:10px">'
            "Opens the Stripe Customer Portal to change card, switch plan, "
            "or cancel.</div>"
            '<div class="dim" style="font-size:12px;margin-top:6px">'
            "<strong>Invoices &amp; receipts:</strong> every payment's invoice "
            "is in the portal too — download the PDF for the club's expense "
            "records.</div>"
            '<div class="dim" style="font-size:12px;margin-top:6px">'
            f'<a href="{url_for("pricing_page")}">See plans &amp; pricing &rarr;</a> '
            "&mdash; compare tiers before switching.</div>"
        )
    elif W._auth.is_premium(user.plan):
        manage_html = (
            '<div class="dim" style="font-size:13px">'
            "Your plan is active. A management link will appear here once "
            "your first payment is processed.</div>"
            '<div class="dim" style="font-size:12px;margin-top:6px">'
            f'<a href="{url_for("pricing_page")}">See plans &amp; pricing &rarr;</a></div>'
        )
    else:
        manage_html = (
            f'<a class="btn" href="{url_for("pricing_page")}">See plans &amp; pricing &rarr;</a>'
            '<div class="dim" style="font-size:12px;margin-top:10px">'
            "Upgrade for unlimited runs and more brand profiles.</div>"
        )

    body = (
        '<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Billing</span>'
        '<h1>Your <em class="editorial">plan</em>.</h1>'
        '<p class="lede">Manage your MediaHub subscription.</p>'
        "</section>"
        '<div class="card" style="padding:24px 28px;max-width:560px">'
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'gap:16px;margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid var(--border)">'
        "<div>"
        '<div style="font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-muted)">Current plan</div>'
        f'<div style="font-size:24px;font-weight:800;margin-top:4px">{_h(plan)}</div>'
        "</div>"
        f'<div class="pill">{_h(user.email)}</div>'
        "</div>"
        f"{manage_html}"
        "</div>"
    )
    return W._layout("Billing", body, active="signin")


def billing_confirm():
    """Pre-contract information page (CCR 2013 / DMCCA) shown BEFORE the
    Stripe checkout: what you're buying, renewal terms, how to cancel,
    and the 14-day cooling-off acknowledgement."""
    user = W._auth.current_user(W._user_store())
    if user is None:
        return redirect(url_for("login_page", next=url_for("pricing_page")))
    if not W._billing.billing_configured():
        return W._billing_unconfigured_response()
    plan = (request.args.get("plan") or "").strip().lower()
    tier = next((t for t in W._billing.TIERS if t.plan == plan), None)
    if tier is None or plan not in (W._auth.PLAN_CLUB, W._auth.PLAN_FEDERATION):
        return redirect(url_for("pricing_page"))
    # Price line: evidence-gated list price when it exists (PC.4), else
    # the honest statement that the exact total shows at checkout before
    # any commitment to pay.
    price_line = (
        "The exact total price and billing interval are shown on the secure "
        "Stripe checkout page before you confirm payment."
    )
    try:
        from mediahub.commercial.wtp import QuoteStore, public_list_price

        lp = public_list_price(QuoteStore().list_all())
        if plan == W._auth.PLAN_CLUB and lp is not None:
            symbol = {"gbp": "£", "usd": "$", "eur": "€"}.get(lp["currency"], "")
            amount = lp["amount_pence"]
            figure = (
                f"{symbol}{amount // 100}" if amount % 100 == 0 else f"{symbol}{amount / 100:.2f}"
            )
            price_line = (
                f"{figure} per year (billed annually). The total is also shown "
                "on the secure Stripe checkout page before you confirm payment."
            )
    except Exception:
        pass
    features = "".join(f"<li>{_h(f)}</li>" for f in tier.features)
    body = (
        '<section class="mh-hero" style="padding-top:var(--sp-7);'
        'padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Subscribe</span>'
        f'<h1>Before you <em class="editorial">subscribe</em>.</h1>'
        f'<p class="lede">The {_h(tier.name)} plan, in plain terms.</p></section>'
        '<div class="card">'
        f"<h2>What you get</h2><p>{_h(tier.blurb)}</p><ul>{features}</ul>"
        f"<p><strong>Price:</strong> {price_line}</p>"
        "<p><strong>Renewal:</strong> your subscription renews automatically at "
        "the interval shown at checkout until you cancel. For annual plans we "
        "send a reminder before renewal.</p>"
        "<p><strong>Cancelling:</strong> as easy as subscribing — open "
        "<em>Billing &rarr; Manage billing</em> any time; cancelling stops future "
        "renewals and you keep access for the period already paid.</p>"
        "<p><strong>Invoices &amp; receipts:</strong> every payment generates an "
        "invoice you can download from <em>Billing &rarr; Manage billing</em> — "
        "made for a volunteer treasurer's expense file.</p>"
        "<p><strong>Your 14-day cancellation right:</strong> you can cancel within "
        "14 days of purchase for a refund. Because the service starts immediately, "
        "if you use it and then cancel within the 14 days we may deduct a "
        "proportionate amount for the service already supplied. Email "
        f"<a href='mailto:{W._legal.CONTACT_EMAIL}'>{W._legal.CONTACT_EMAIL}</a> to "
        "cancel within the cooling-off period.</p>"
        f'<form method="post" action="{url_for("billing_checkout")}">'
        f'<input type="hidden" name="plan" value="{_h(plan)}">'
        '<label style="display:flex;gap:10px;align-items:flex-start;'
        'font-size:13px;color:var(--ink-muted);margin:14px 0">'
        '<input type="checkbox" name="immediate_supply" value="1" required '
        'style="margin-top:3px" />'
        "<span>I expressly request that the service starts immediately, and I "
        "acknowledge that if I cancel within 14 days I may be charged a "
        "proportionate amount for what has already been supplied &mdash; and that "
        "for digital content already downloaded, the cancellation right is "
        "lost once supply has begun with my consent.</span></label>"
        f'<button type="submit" class="btn">Continue to secure checkout &rarr;</button> '
        f'<a class="btn secondary" href="{url_for("pricing_page")}">Cancel</a>'
        "</form>"
        f'<p class="muted" style="margin-top:14px">Full terms: '
        f'<a href="{url_for("terms_page")}">Terms of Service</a>.</p>'
        "</div>"
    )
    return W._layout("Before you subscribe", body, active="signin")


def billing_checkout():
    user = W._auth.current_user(W._user_store())
    if user is None:
        return redirect(url_for("login_page", next=url_for("pricing_page")))
    if not W._billing.billing_configured():
        return W._billing_unconfigured_response()
    plan = (request.form.get("plan") or "").strip().lower()
    if plan not in (W._auth.PLAN_CLUB, W._auth.PLAN_FEDERATION):
        return W._layout(
            "Checkout",
            W._billing_error_body("That plan can&rsquo;t be purchased."),
            active="signin",
        ), 400
    # CCR 2013: no checkout without the recorded immediate-supply /
    # cooling-off acknowledgement from the pre-contract page.
    if (request.form.get("immediate_supply") or "") != "1":
        return redirect(url_for("billing_confirm", plan=plan))
    W._legal.AcceptanceStore().record(
        user.email, W._legal.DOC_COOLING_OFF, W._legal.TERMS_VERSION, org_id=plan
    )
    try:
        checkout_url = W._billing.create_checkout_session(
            plan=plan,
            customer_email=user.email,
            success_url=url_for("billing_page", _external=True),
            cancel_url=url_for("pricing_page", _external=True),
            client_reference_id=user.email,
            customer_id=user.stripe_customer_id or None,
        )
    except W._billing.BillingNotConfigured:
        return W._billing_unconfigured_response()
    except W._billing.BillingError as exc:
        return W._layout(
            "Checkout",
            W._billing_error_body(str(exc)),
            active="signin",
        ), 502
    return redirect(checkout_url, code=303)


def billing_portal():
    user = W._auth.current_user(W._user_store())
    if user is None:
        return redirect(url_for("login_page", next=url_for("billing_page")))
    if not W._billing.billing_configured():
        return W._billing_unconfigured_response()
    if not user.stripe_customer_id:
        return W._layout(
            "Billing",
            W._billing_error_body("No active subscription to manage yet."),
            active="signin",
        ), 400
    try:
        portal_url = W._billing.create_customer_portal_session(
            customer_id=user.stripe_customer_id,
            return_url=url_for("billing_page", _external=True),
        )
    except W._billing.BillingNotConfigured:
        return W._billing_unconfigured_response()
    except W._billing.BillingError as exc:
        return W._layout(
            "Billing",
            W._billing_error_body(str(exc)),
            active="signin",
        ), 502
    return redirect(portal_url, code=303)


def stripe_webhook():
    """Receive Stripe subscription events → drive the user's plan.

    The signature is verified against STRIPE_WEBHOOK_SECRET before the
    payload is trusted (a forged body answers 400). Returns 503 when
    billing isn't configured so Stripe surfaces a clear delivery error
    rather than a silent 200.
    """
    if not W._billing.billing_configured():
        # A machine caller (Stripe) always gets JSON — never the styled HTML
        # card the browser-facing routes now return (D-14).
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "billing_not_configured",
                    "message": W._billing.NOT_CONFIGURED_MESSAGE,
                }
            ),
            503,
        )
    sig = request.headers.get("Stripe-Signature", "")
    payload = request.get_data()  # raw bytes — required for signature check
    try:
        update = W._billing.verify_and_parse_webhook(payload, sig)
    except W._billing.BillingError as exc:
        # Bad/forged signature or malformed payload → 400, do not act.
        return jsonify({"ok": False, "error": "invalid_webhook", "message": str(exc)}), 400
    if update is None:
        # A verified event we simply don't act on.
        return jsonify({"ok": True, "handled": False}), 200

    # PC.4: a checkout that originated from a price-discovery quote
    # records revealed-WTP evidence FIRST — the prospect may well not
    # have an account yet, and the quote ledger must capture the
    # payment either way. record_stripe_payment is idempotent per
    # event and verifies the paid amount against the quoted amount
    # (an unverified figure is stored as a mismatch, never counted).
    if update.quote_id:
        try:
            from mediahub.commercial.wtp import QuoteStore

            paid_quote = QuoteStore().record_stripe_payment(
                update.quote_id,
                amount_total_pence=update.amount_total_pence,
                currency=update.currency,
                event_id=update.event_id,
            )
            # PC.9: a verified payment settles any referral attached to
            # this club — the reward auto-grants (or records honestly
            # as pending) and the funnel ledger advances itself.
            # Idempotent per quote, so webhook retries change nothing.
            if paid_quote is not None:
                try:
                    from mediahub.commercial.referrals import on_verified_quote_payment

                    on_verified_quote_payment(paid_quote)
                except Exception:
                    W.log.warning("referral settlement failed", exc_info=True)
        except Exception:
            W.log.warning("quote payment recording failed", exc_info=True)

    store = W._user_store()
    target = None
    if update.email:
        target = store.get(update.email)
    if target is None and update.customer_id:
        target = store.find_by_customer_id(update.customer_id)
    if target is None:
        # Verified but we can't match it to a known account. Acknowledge
        # so Stripe stops retrying; nothing to update.
        return jsonify({"ok": True, "handled": False, "reason": "no_matching_user"}), 200
    store.set_plan(
        target.email,
        update.plan,
        stripe_customer_id=update.customer_id or target.stripe_customer_id,
    )
    return jsonify({"ok": True, "handled": True, "plan": update.plan}), 200


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule("/audit/<run_id>", endpoint="pb_audit_page", view_func=pb_audit_page)
    app.add_url_rule(
        "/audit/<run_id>/verify/<path:swimmer_key>",
        endpoint="pb_verify_form",
        view_func=pb_verify_form,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/audit/<run_id>/ignore/<path:swimmer_key>",
        endpoint="pb_ignore",
        view_func=pb_ignore,
        methods=["POST"],
    )
    app.add_url_rule(
        "/audit/<run_id>/ground-truth",
        endpoint="pb_ground_truth",
        view_func=pb_ground_truth,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/admin/compliance", endpoint="admin_compliance", view_func=admin_compliance)
    app.add_url_rule(
        "/admin/compliance/complaints/<complaint_id>/ack",
        endpoint="admin_compliance_ack",
        view_func=admin_compliance_ack,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/compliance/incidents",
        endpoint="admin_compliance_incident",
        view_func=admin_compliance_incident,
        methods=["POST"],
    )
    app.add_url_rule("/settings", endpoint="settings_page", view_func=settings_page)
    app.add_url_rule(
        "/settings/interface-language",
        endpoint="set_interface_language",
        view_func=set_interface_language,
        methods=["POST"],
    )
    app.add_url_rule("/settings/<section>", endpoint="settings_section", view_func=settings_section)
    app.add_url_rule(
        "/settings/typography/font/upload",
        endpoint="typography_upload_font",
        view_func=typography_upload_font,
        methods=["POST"],
    )
    app.add_url_rule(
        "/settings/typography/font/<slug>/remove",
        endpoint="typography_remove_font",
        view_func=typography_remove_font,
        methods=["POST"],
    )
    app.add_url_rule(
        "/settings/typography/pair",
        endpoint="typography_pair",
        view_func=typography_pair,
        methods=["POST"],
    )
    app.add_url_rule(
        "/settings/typography/pair/apply",
        endpoint="typography_pair_apply",
        view_func=typography_pair_apply,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/notify-users",
        endpoint="operator_notify_users",
        view_func=operator_notify_users,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/operator/cache/purge",
        endpoint="operator_cache_purge",
        view_func=operator_cache_purge,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/data/purge",
        endpoint="operator_data_purge",
        view_func=operator_data_purge,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/commercial", endpoint="operator_commercial", view_func=operator_commercial
    )
    app.add_url_rule(
        "/operator/commercial/quotes",
        endpoint="operator_commercial_quote_add",
        view_func=operator_commercial_quote_add,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/commercial/quotes/update",
        endpoint="operator_commercial_quote_update",
        view_func=operator_commercial_quote_update,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/commercial/leads",
        endpoint="operator_commercial_lead_add",
        view_func=operator_commercial_lead_add,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/commercial/leads/update",
        endpoint="operator_commercial_lead_update",
        view_func=operator_commercial_lead_update,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/commercial/ngb",
        endpoint="operator_commercial_ngb",
        view_func=operator_commercial_ngb,
        methods=["POST"],
    )
    app.add_url_rule(
        "/operator/commercial/bind",
        endpoint="operator_commercial_bind",
        view_func=operator_commercial_bind,
        methods=["POST"],
    )
    app.add_url_rule("/billing", endpoint="billing_page", view_func=billing_page, methods=["GET"])
    app.add_url_rule(
        "/billing/confirm", endpoint="billing_confirm", view_func=billing_confirm, methods=["GET"]
    )
    app.add_url_rule(
        "/billing/checkout",
        endpoint="billing_checkout",
        view_func=billing_checkout,
        methods=["POST"],
    )
    app.add_url_rule(
        "/billing/portal", endpoint="billing_portal", view_func=billing_portal, methods=["POST"]
    )
    app.add_url_rule(
        "/webhooks/stripe", endpoint="stripe_webhook", view_func=stripe_webhook, methods=["POST"]
    )
