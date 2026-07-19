"""The run-review core: review page, run APIs, uploads, activity, spotlights, wraps.

Carved out of ``web.create_app`` (deep-review finding #15, final stage).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
any captured ``app`` became ``current_app``. Endpoint names are
PRESERVED via ``add_url_rule`` (ADR-0031).
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from markupsafe import escape as _h
import json
import os
import re
import uuid
from flask import (
    abort,
    jsonify,
    redirect,
    request,
    send_file,
    url_for,
)

from mediahub.web import web as W


def activity_page():
    prof = W._active_profile()
    # The gate ensures we only land here with a ready profile; the
    # extra guard keeps the page honest if invoked under TESTING mode.
    if prof is None:
        return redirect(url_for("organisation_setup"))

    # Phase 5 — optional ?status= filter. Whitelist the values to
    # avoid arbitrary SQL.
    status_q = (request.args.get("status") or "").strip()
    if status_q not in ("done", "running", "queued", "error"):
        status_q = ""

    # DB-read is fail-soft: a corrupted/missing data.db or a partial
    # schema would otherwise 500 the entire Activity page. Treat the
    # failure as "no runs visible" and surface a recovery hero so the
    # user knows the page loaded but the store wasn't reachable.
    rows = []
    unfiltered_counts: dict[str, int] = {}
    total_unfiltered = 0
    ach_unfiltered = 0
    ach_by_id: dict[str, int] = {}
    standout_unfiltered = 0
    standout_by_id: dict[str, int] = {}
    db_failed = False
    try:
        conn = W._db()
        try:
            if status_q:
                rows = conn.execute(
                    "SELECT id, created_at, finished_at, status, profile_id, "
                    "meet_name, our_swims, n_cards, n_queue, n_achievements, n_standout, "
                    "error, file_name, content_hash, meet_fingerprint "
                    "FROM runs WHERE profile_id = ? AND status = ? "
                    "ORDER BY created_at DESC LIMIT 100",
                    (prof.profile_id, status_q),
                ).fetchall()
                # Also pull totals for the stat strip + chip counts so the
                # filtered view still shows the full picture at the top.
                counts_row = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM runs WHERE profile_id = ? "
                    "GROUP BY status",
                    (prof.profile_id,),
                ).fetchall()
                unfiltered_counts = {r["status"]: r["n"] for r in counts_row}
                total_unfiltered = sum(unfiltered_counts.values())
            else:
                rows = conn.execute(
                    "SELECT id, created_at, finished_at, status, profile_id, "
                    "meet_name, our_swims, n_cards, n_queue, n_achievements, n_standout, "
                    "error, file_name, content_hash, meet_fingerprint "
                    "FROM runs WHERE profile_id = ? "
                    "ORDER BY created_at DESC LIMIT 100",
                    (prof.profile_id,),
                ).fetchall()
                for r in rows:
                    unfiltered_counts[r["status"]] = unfiltered_counts.get(r["status"], 0) + 1
                total_unfiltered = len(rows)

            # Council STEP 3 — surface the REAL engine output (V5
            # recognition achievements), not the legacy n_cards which the
            # recognition-first pipeline leaves at 0 and a user reads as
            # "nothing was produced". Read each run's count from the column,
            # or its run JSON for rows written before the column existed.
            #
            # Audit-round hardening: the DISPLAY never depends on a DB
            # write. The shared helper computes counts in memory (column or
            # JSON) and best-effort warms the column — a locked / read-only
            # DB is a silent no-op, never a 500 and never an undercount.
            ach_by_id = W._warm_run_achievements(conn, rows)
            ach_unfiltered = sum(ach_by_id.values())
            standout_by_id = W._warm_run_standouts(conn, rows)
            standout_unfiltered = sum(standout_by_id.values())
        finally:
            conn.close()
    except Exception as e:
        W.log.warning("activity: runs DB unreachable: %s", e)
        db_failed = True

    if not rows:
        if db_failed:
            # DB on disk but unreadable — surface honestly so the user
            # doesn't think their runs vanished. Same shape as the
            # quiet-weekend hero so the chrome stays familiar.
            empty_body = (
                '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
                '<span class="mh-hero-eyebrow">Activity</span>'
                '<h1>Couldn&rsquo;t load your <em class="editorial">runs</em>.</h1>'
                '<p class="lede">'
                "The runs database wasn't readable on this deployment, "
                "so the run list is empty even if work was done earlier. "
                "Try refreshing &mdash; if it keeps happening, ask your "
                "operator to check the data volume."
                "</p>"
                '<div class="mh-hero-actions">'
                f'<a class="mh-cta-primary" href="{url_for("activity_page")}">Refresh &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{url_for("home")}">Back to home</a>'
                "</div>"
                "</section>"
            )
            return W._layout("Activity", empty_body, active="activity")
        empty_body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
            '<span class="mh-hero-eyebrow">Activity</span>'
            f'<h1>Quiet weekend, <em class="editorial">{_h(prof.display_name)}</em>.</h1>'
            '<p class="lede">'
            "No results yet for this organisation. Upload a results file, paste "
            "a sponsor brief, or describe a moment in your own words &mdash; "
            "every run lands here with the meet name, status, queue, and a "
            "one-click link back into the review."
            "</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{url_for("make_page")}">Create your first piece &rarr;</a>'
            "</div>"
            "</section>"
        )
        return W._layout("Activity", empty_body, active="activity")

    # Phase 5 — group rows by date bucket so the table reads as a
    # newsroom log instead of an undifferentiated 100-row dump.
    from datetime import datetime as _dt

    def _bucket(iso_str: str) -> str:
        if not iso_str:
            return "earlier"
        try:
            t = _dt.fromisoformat(iso_str.replace("Z", "").replace("T", " ")[:19])
        except Exception:
            return "earlier"
        now = _dt.now()
        delta = now - t
        if delta.total_seconds() < 0:
            return "today"
        days = delta.days
        if days == 0:
            return "today"
        if days == 1:
            return "yesterday"
        if days < 7:
            return "this_week"
        if days < 30:
            return "this_month"
        return "earlier"

    bucket_labels = {
        "today": "Today",
        "yesterday": "Yesterday",
        "this_week": "Earlier this week",
        "this_month": "Earlier this month",
        "earlier": "Earlier",
    }
    bucket_order = ["today", "yesterday", "this_week", "this_month", "earlier"]
    grouped: dict[str, list] = {b: [] for b in bucket_order}
    # Flat status counts for the top stats / failure callout.
    n_done = 0
    n_running = 0
    n_errored = 0
    for r in rows:
        if r["status"] == "done":
            n_done += 1
        if r["status"] == "running":
            n_running += 1
        if r["status"] == "error":
            n_errored += 1
        grouped[_bucket((r["created_at"] or "")[:19])].append(r)

    # Re-run badging is org-wide (not limited to the filtered/visible rows),
    # so a re-run still links back to its original even when a status filter
    # hides it.
    dup_map = W._org_duplicate_map(prof.profile_id)
    rows_html = ""
    for bucket in bucket_order:
        bucket_rows = grouped[bucket]
        if not bucket_rows:
            continue
        rows_html += (
            '<tr class="mh-date-group-row">'
            f'<td colspan="7"><span class="label">{bucket_labels[bucket]} '
            f'<span style="color:var(--ink-faint)">&middot; {len(bucket_rows):02d}</span></span></td>'
            "</tr>"
        )
        for r in bucket_rows:
            badge = {"done": "good", "running": "info", "queued": "info", "error": "bad"}.get(
                r["status"], ""
            )
            review_href = url_for("review", run_id=r["id"])
            delete_href = url_for("privacy_delete_run", run_id=r["id"])
            started = (r["created_at"] or "")[:19]
            started_iso = started.replace(" ", "T") + "Z" if started else ""
            search_haystack = (r["meet_name"] or r["file_name"] or r["id"] or "").lower()
            dup_badge = W._dup_badge_html(dup_map.get(r["id"]))
            # C-10: processed meets get an explicit route into the athlete
            # spotlight — otherwise its only entries are the Review view
            # switch or a hand-typed URL. ?older=1 keeps the spotlight's
            # meet picker consistent even for meets past its 31-day window.
            spotlight_link = ""
            if r["status"] == "done" and W._club_platform_ok:
                _sp_href = url_for("spotlight_landing", run_id=r["id"], older=1)
                spotlight_link = (
                    f'<a href="{_sp_href}" style="font-size:11px;'
                    "color:var(--ink-muted);white-space:nowrap;"
                    'margin-right:10px">Spotlight a swimmer &rarr;</a>'
                )
            rows_html += (
                f'<tr data-run-row="{_h(r["id"])}" data-status="{_h(r["status"])}" data-q="{_h(search_haystack)}">'
                f'<td data-label="Input"><a href="{review_href}">{_h(r["meet_name"] or r["file_name"] or r["id"])}</a>{dup_badge}</td>'
                f'<td data-label="Status"><span class="tag {badge}">{_h(r["status"])}</span></td>'
                f'<td data-label="Matched">{_h(r["our_swims"] or 0)}</td>'
                f'<td data-label="Achievements">{_h(ach_by_id.get(r["id"], 0))}</td>'
                f'<td data-label="Started"><time class="mh-rel" datetime="{_h(started_iso)}">{_h(started)}</time></td>'
                f"<td>{spotlight_link}"
                f'<form method="post" action="{delete_href}" '
                f'class="mh-run-delete" data-run-id="{_h(r["id"])}" '
                f'style="display:inline" data-no-loader="1">'
                f'<input type="hidden" name="next" value="{_h(request.path)}">'
                f'<button class="btn danger" type="submit" '
                f'style="font-size:11px;padding:4px 10px">Delete</button>'
                f"</form></td></tr>"
            )
            if r["status"] == "error" and r["error"]:
                err_text = str(r["error"])
                truncated = err_text[:600] + ("…" if len(err_text) > 600 else "")
                rows_html += (
                    f'<tr class="run-error-row" data-run-err="{_h(r["id"])}">'
                    '<td colspan="7" style="padding:6px 14px 14px 14px;'
                    'background:rgba(255,93,108,0.06);border-left:3px solid var(--mh-prim-error-500)">'
                    "<details>"
                    '<summary style="cursor:pointer;font-size:13px;font-weight:600;'
                    'color:var(--mh-prim-error-300)">Why did this run fail?</summary>'
                    '<pre style="margin:8px 0 0;padding:10px 12px;'
                    "background:rgba(0,0,0,0.25);border-radius:6px;"
                    'font-size:12px;white-space:pre-wrap;word-break:break-word">'
                    f"{_h(truncated)}</pre>"
                    "</details>"
                    "</td></tr>"
                )

    # Phase 1.5 — surface the number of failed runs at the top of the
    # page so an operator triaging issues sees the scope before reading
    # individual rows.
    failure_callout = ""
    if n_errored:
        label = "1 run failed" if n_errored == 1 else f"{n_errored} runs failed"
        failure_callout = (
            '<div class="card" style="padding:12px 18px;margin-bottom:20px;'
            'background:rgba(255,93,108,0.06);border-left:3px solid var(--mh-prim-error-500)">'
            f"<b>{_h(label)}</b> in the last 100 runs. "
            "Expand <i>Why did this run fail?</i> on each row below to "
            "see the pipeline error.</div>"
        )

    # Top stat strip — always shows the UNFILTERED picture so it's a
    # stable org-level summary regardless of the active ?status= chip.
    # Values count up on scroll-in via the Phase 10 motion system.
    # The headline is STANDOUT SWIMS (distinct swims worth shouting about),
    # not raw detections — one race can emit several achievements and most
    # swims are simply completed races, so the old "Achievements detected"
    # figure read absurdly high. The raw detection total stays available on
    # each run's review page and trace JSON.
    summary_html = (
        '<div class="mh-activity-summary mh-reveal">'
        f'<div class="stat live"><div class="l">Total runs</div><div class="v" data-mh-count="{total_unfiltered}">{total_unfiltered:,}</div></div>'
        f'<div class="stat medal"><div class="l">Standout swims</div><div class="v" data-mh-count="{standout_unfiltered}">{standout_unfiltered:,}</div></div>'
        f'<div class="stat good"><div class="l">Completed</div><div class="v" data-mh-count="{unfiltered_counts.get("done", 0)}">{unfiltered_counts.get("done", 0):,}</div></div>'
    )
    if unfiltered_counts.get("error", 0):
        summary_html += f'<div class="stat bad"><div class="l">Failed</div><div class="v" data-mh-count="{unfiltered_counts.get("error", 0)}">{unfiltered_counts.get("error", 0):,}</div></div>'
    summary_html += "</div>"

    # UI 1.17 — content-cadence heatmap. A GitHub-style year grid of this
    # org's generate/post consistency, rendered server-side as inline SVG
    # from run history + the posting log. Fail-soft: any trouble drops the
    # panel rather than breaking the rest of the page.
    cadence_html = ""
    try:
        end_day = datetime.now(timezone.utc).date()
        _gen, _post = W._cadence_activity_counts(prof.profile_id, end_day)
        if _gen or _post:
            cadence_html = W._cadence_panel_html(_gen, _post, end=end_day)
    except Exception as e:  # pragma: no cover - defensive
        W.log.warning("activity: cadence heatmap failed: %s", e)
        cadence_html = ""

    # Toolbar — search input + status segment filter.
    # Filter buttons use ?status= for server-side filtering plus the
    # client-side text search filters in-place. Counts are unfiltered
    # so the chips always show the full picture.
    seg_buttons = ""
    seg_specs = [
        ("", "All", total_unfiltered),
        ("done", "Completed", unfiltered_counts.get("done", 0)),
        (
            "running",
            "Running",
            unfiltered_counts.get("running", 0) + unfiltered_counts.get("queued", 0),
        ),
        ("error", "Failed", unfiltered_counts.get("error", 0)),
    ]
    for val, label, count in seg_specs:
        is_active = status_q == val
        active_cls = " is-active" if is_active else ""
        url_arg = f"?status={val}" if val else ""
        seg_buttons += (
            f'<a role="tab" aria-selected="{"true" if is_active else "false"}"'
            f' class="{active_cls.strip()}" href="{url_for("activity_page")}{url_arg}">'
            f'{label}<span class="count">{count}</span></a>'
        )
    # Bulk "Clear all runs" — permanently delete every run for THIS org
    # (per-tenant; never touches another org's runs). Right-aligned in the
    # toolbar, shown only when there's something to clear.
    clear_all_html = ""
    if total_unfiltered:
        _clear_href = url_for("privacy_clear_all_runs")
        clear_all_html = (
            f'<form method="post" action="{_clear_href}" class="mh-clear-all-runs" '
            f'data-count="{total_unfiltered}" data-no-loader="1" '
            'style="display:inline-flex;margin-left:auto">'
            f'<input type="hidden" name="next" value="{_h(request.path)}">'
            '<button class="btn danger" type="submit" '
            'style="font-size:12px;padding:6px 12px" '
            'title="Permanently delete every run for this organisation">'
            "Clear all runs</button></form>"
        )
    toolbar_html = (
        '<div class="mh-toolbar">'
        f'<div class="grow mh-search mh-vanish" {W._VANISH_PH_ATTR_SEARCH}>'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
        '<input id="mh-activity-search" type="search" placeholder=" " autocomplete="off" aria-label="Search runs by meet name, file or run id" />'
        f'<span class="mh-vanish__ph" aria-hidden="true">{_h(W._VANISH_PH_SEARCH[0])}</span>'
        "</div>"
        '<nav class="mh-segmented" role="tablist" aria-label="Filter by run status">'
        f"{seg_buttons}"
        "</nav>"
        f"{clear_all_html}"
        "</div>"
        '<div id="mh-activity-empty" class="mh-empty-inline" style="display:none">'
        "<b>Nothing matches.</b><br>Try clearing the search box or picking a different status."
        "</div>"
    )

    # Inline JS — client-side filter on the table rows.
    filter_js = """
<script>
(function(){
  var search = document.getElementById('mh-activity-search');
  var tbody  = document.querySelector('table.mh-table-stack tbody');
  var empty  = document.getElementById('mh-activity-empty');
  if (!search || !tbody) return;
  function apply() {
    var q = (search.value || '').toLowerCase().trim();
    var rows = tbody.querySelectorAll('tr[data-q]');
    var visible = 0;
    rows.forEach(function(r){
      var hay = r.getAttribute('data-q') || '';
      var ok = !q || hay.indexOf(q) !== -1;
      r.style.display = ok ? '' : 'none';
      // Hide the matching error-detail row (immediately following).
      var next = r.nextElementSibling;
      if (next && next.classList.contains('run-error-row')) {
        next.style.display = ok ? '' : 'none';
      }
      if (ok) visible++;
    });
    // Hide group-header rows whose group has no visible siblings.
    tbody.querySelectorAll('tr.mh-date-group-row').forEach(function(g){
      var sib = g.nextElementSibling, any = false;
      while (sib && !sib.classList.contains('mh-date-group-row')) {
        if (sib.style.display !== 'none' && sib.hasAttribute('data-q')) {
          any = true; break;
        }
        sib = sib.nextElementSibling;
      }
      g.style.display = any ? '' : 'none';
    });
    if (empty) empty.style.display = visible === 0 ? '' : 'none';
  }
  search.addEventListener('input', apply);
})();
</script>"""

    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Activity</span>'
        "<h1>Recent runs</h1>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f'<span>{_h(prof.display_name)}</span><span class="sep">·</span>'
        f"<span>{len(rows):02d} {'run' if len(rows) == 1 else 'runs'}</span>"
        "</div>"
        "</section>"
        f"{W._activity_view_toggle('table')}"
        f"{summary_html}"
        f"{cadence_html}"
        f"{failure_callout}"
        f"{toolbar_html}"
        '<div class="card"><table class="mh-table-stack">'
        "<thead><tr><th>Input</th><th>Status</th>"
        "<th>Matched</th><th>Achievements</th>"
        "<th>Started</th><th></th></tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table></div>"
        f"{filter_js}"
        f"{W._RUN_DELETE_JS}"
    )
    return W._layout("Activity", body, active="activity")


def activity_feed_page():
    from mediahub.web import activity_feed as _af

    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))

    # ?kind= filter — whitelist to the three lanes (empty = all).
    kind_q = (request.args.get("kind") or "").strip().lower()
    if kind_q not in _af.KINDS:
        kind_q = ""

    # --- Gather the three EXISTING records (no new data source) ---------
    # 1. Runs for this org (newest first), fail-soft on a bad DB.
    rows: list = []
    ach_by_id_feed: dict[str, int] = {}
    standout_by_id_feed: dict[str, int] = {}
    db_failed = False
    try:
        conn = W._db()
        try:
            rows = conn.execute(
                "SELECT id, created_at, finished_at, status, profile_id, "
                "meet_name, our_swims, n_cards, n_queue, n_achievements, n_standout, "
                "error, file_name "
                "FROM runs WHERE profile_id = ? "
                "ORDER BY created_at DESC LIMIT 100",
                (prof.profile_id,),
            ).fetchall()
            # Backfill n_achievements + n_standout via the shared helpers
            # (column or JSON), which also warm the columns so feed-only
            # users don't re-read the JSON on every visit — same logic the
            # runs-table view uses.
            ach_by_id_feed = W._warm_run_achievements(conn, rows)
            standout_by_id_feed = W._warm_run_standouts(conn, rows)
        finally:
            conn.close()
    except Exception as e:
        W.log.warning("activity feed: runs DB unreachable: %s", e)
        db_failed = True

    # Normalise rows to plain dicts so the (lazily backfilled) counts
    # ride along and the builder stays storage-agnostic.
    run_dicts: list[dict] = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        if d["id"] in ach_by_id_feed:
            d["n_achievements"] = ach_by_id_feed[d["id"]]
        if d["id"] in standout_by_id_feed:
            d["n_standout"] = standout_by_id_feed[d["id"]]
        run_dicts.append(d)

    # 2. Workflow states (approvals + posted) for the most recent runs only
    #    — bound the sidecar reads so the page stays cheap.
    workflow_by_run: dict[str, dict] = {}
    ws = None
    try:
        ws = W._get_wf_store()
    except Exception as e:
        # Defensive: the approvals/posted lanes go quiet rather than 500,
        # but log it so a sidecar-dir permission issue isn't invisible.
        W.log.warning("activity feed: workflow store unavailable: %s", e)
        ws = None
    if ws is not None:
        for d in run_dicts[:40]:
            try:
                states = ws.load(d["id"]) or {}
            except Exception:
                states = {}
            if states:
                workflow_by_run[d["id"]] = states

    # --- Build the merged feed (all lanes) for accurate chip counts -----
    all_events = _af.build_activity_feed(
        runs=run_dicts,
        workflow_by_run=workflow_by_run,
        limit=200,
    )
    counts = _af.feed_counts(all_events)
    events = [e for e in all_events if (not kind_q or e.kind == kind_q)][:120]

    # --- Empty state ----------------------------------------------------
    if not all_events:
        if db_failed:
            empty_body = (
                '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
                '<span class="mh-hero-eyebrow">Activity feed</span>'
                '<h1>Couldn&rsquo;t load your <em class="editorial">activity</em>.</h1>'
                '<p class="lede">The runs database wasn\'t readable on this '
                "deployment, so the feed is empty even if work was done "
                "earlier. Try refreshing &mdash; if it persists, ask your "
                "operator to check the data volume.</p>"
                '<div class="mh-hero-actions">'
                f'<a class="mh-cta-primary" href="{url_for("activity_feed_page")}">Refresh &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{url_for("activity_page")}">Results table</a>'
                "</div></section>"
            )
            return W._layout("Activity feed", empty_body, active="activity")
        empty_body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
            '<span class="mh-hero-eyebrow">Activity feed</span>'
            f'<h1>Nothing here yet, <em class="editorial">{_h(prof.display_name)}</em>.</h1>'
            '<p class="lede">Runs, review decisions, and publishes will stream '
            "in here as cards &mdash; newest first, each one expandable for the "
            "detail behind it. Create your first piece to get started.</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{url_for("make_page")}">Create your first piece &rarr;</a>'
            f'<a class="mh-cta-secondary" href="{url_for("activity_page")}">Results table</a>'
            "</div></section>"
        )
        return W._layout("Activity feed", empty_body, active="activity")

    # --- Filter chips (server-side ?kind=) ------------------------------
    chip_specs = [
        ("", "All", counts["all"]),
        (_af.KIND_RUN, "Runs", counts[_af.KIND_RUN]),
        (_af.KIND_APPROVAL, "Approvals", counts[_af.KIND_APPROVAL]),
        (_af.KIND_EXPORT, "Exports", counts[_af.KIND_EXPORT]),
    ]
    chips = ""
    for val, label, count in chip_specs:
        is_active = kind_q == val
        url_arg = f"?kind={val}" if val else ""
        chips += (
            f'<a role="tab" aria-selected="{"true" if is_active else "false"}"'
            f' class="{"is-active" if is_active else ""}"'
            f' href="{url_for("activity_feed_page")}{url_arg}">'
            f'{label}<span class="count">{count}</span></a>'
        )
    toolbar_html = (
        '<div class="mh-toolbar">'
        '<div class="grow mh-search">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
        '<input id="mh-feed-search" type="search" placeholder="Search the activity feed…" autocomplete="off" aria-label="Search the activity feed" />'
        "</div>"
        '<nav class="mh-segmented" role="tablist" aria-label="Filter activity by type">'
        f"{chips}"
        "</nav>"
        "</div>"
        '<div id="mh-feed-empty" class="mh-empty-inline" style="display:none">'
        "<b>Nothing matches.</b><br>Try clearing the search box or picking a "
        "different type.</div>"
    )

    # Client-side text filter over the rendered cards (progressive
    # enhancement — the server already applied the ?kind= filter).
    filter_js = """
<script>
(function(){
  var search = document.getElementById('mh-feed-search');
  var feed = document.querySelector('.mh-feed');
  var empty = document.getElementById('mh-feed-empty');
  if (!search || !feed) return;
  function apply(){
    var q = (search.value || '').toLowerCase().trim();
    var items = feed.querySelectorAll('.mh-feed-item');
    var visible = 0;
    items.forEach(function(it){
      var hay = it.getAttribute('data-q') || '';
      var ok = !q || hay.indexOf(q) !== -1;
      it.style.display = ok ? '' : 'none';
      if (ok) visible++;
    });
    feed.querySelectorAll('.mh-feed-group-label').forEach(function(g){
      var sib = g.nextElementSibling, any = false;
      while (sib && !sib.classList.contains('mh-feed-group-label')) {
        if (sib.classList.contains('mh-feed-item') && sib.style.display !== 'none') { any = true; break; }
        sib = sib.nextElementSibling;
      }
      g.style.display = any ? '' : 'none';
    });
    if (empty) empty.style.display = visible === 0 ? '' : 'none';
  }
  search.addEventListener('input', apply);
})();
</script>"""

    # All events exist, but the active ?kind= chip filtered them all out:
    # show an honest in-place notice rather than a blank column.
    if events:
        feed_html = W._render_activity_feed(events)
    else:
        feed_html = (
            '<div class="mh-empty-inline" style="display:block">'
            f"<b>No {_h(kind_q)} activity yet.</b><br>"
            "Switch to <i>All</i> above to see everything that's happened."
            "</div>"
        )
    showing = "" if not kind_q else f" &middot; {_h(kind_q)}"
    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Activity feed</span>'
        "<h1>What&rsquo;s happened</h1>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f'<span>{_h(prof.display_name)}</span><span class="sep">·</span>'
        f"<span>{counts['all']:02d} {'event' if counts['all'] == 1 else 'events'}{showing}</span>"
        "</div>"
        "</section>"
        f"{W._activity_view_toggle('feed')}"
        f"{toolbar_html}"
        f"{feed_html}"
        f"{filter_js}"
    )
    return W._layout("Activity feed", body, active="activity")


def upload():
    # V8.2 issue 3: every upload now goes through /upload/configure.
    # The upload form has only the file input + submit. Branding is
    # collected on the configure step, after we've parsed the file.
    #
    # H-18: rejections never dead-end on a bare error card — they fall
    # through to the full upload page (form, dropzone, recent meets)
    # with the error rendered inline above the dropzone, so the
    # volunteer can fix the problem and try again in place.
    # upload_error values are fixed server-controlled literals (never
    # user input — no filename/extension echo), rendered un-escaped.
    upload_error = ""
    if request.method == "POST":
        f = request.files.get("file")
        # Extension allowlist (THREAT_MODEL §1): results files only. The
        # file is stored as opaque bytes under a random run id and parsed
        # by deterministic parsers — but rejecting junk up front shrinks
        # the parser attack surface and gives an honest error.
        _ALLOWED_UPLOAD_EXTS = {
            ".hy3",
            ".hyv",
            ".sd3",
            ".sdif",
            ".cl2",
            ".zip",
            ".pdf",
            ".htm",
            ".html",
            ".csv",
            ".txt",
            ".xlsx",
        }
        data = b""
        ext = os.path.splitext(f.filename)[1].lower() if f and f.filename else ""
        if not f or not f.filename:
            upload_error = "Please choose a results file first."
        elif ext not in _ALLOWED_UPLOAD_EXTS:
            upload_error = (
                "That file type isn't supported. Upload meet results as "
                "HY3, SDIF/SD3/CL2, ZIP, PDF, HTML, CSV, TXT or Excel (.xlsx)."
            )
        else:
            data = f.read()
            if not data:
                upload_error = "That file is empty. Export the results file again and re-upload it."
    if request.method == "POST" and not upload_error:
        temp_run_id = uuid.uuid4().hex[:12]
        tmp_dir = W.RUNS_DIR / temp_run_id
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
            meta["meet_date"] = (interpreted.dates[0] if interpreted.dates else "") or ""
            meta["n_events"] = len(interpreted.events)
            meta["file_byte_size"] = len(data)
        except Exception as exc:
            meta["clubs"] = []
            meta["parse_error"] = str(exc)
            meta["file_byte_size"] = len(data)
        (tmp_dir / "upload_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return redirect(url_for("upload_configure", run_id=temp_run_id))

    # Recent files for this profile — lets the user re-run an already-
    # uploaded meet without re-uploading. Pulls the last 5 runs we
    # still have on disk (RUNS_DIR/<id>/input.bin must exist).
    recent_html = ""
    try:
        prof_for_recent = W._active_profile()
        if prof_for_recent is not None:
            conn = W._db()
            rows = conn.execute(
                # D-6: include failed runs too — their file is still on disk,
                # so the volunteer can re-run from it instead of re-uploading.
                "SELECT id, meet_name, file_name, created_at, our_swims, status "
                "FROM runs WHERE profile_id = ? AND status IN ('done', 'error') "
                "ORDER BY created_at DESC LIMIT 5",
                (prof_for_recent.profile_id,),
            ).fetchall()
            conn.close()
            # Filter to runs whose input.bin still exists on disk.
            recent_rows = []
            for r in rows:
                if (W.RUNS_DIR / r["id"] / "input.bin").exists():
                    recent_rows.append(r)
            if recent_rows:
                items_html = ""
                for r in recent_rows[:3]:
                    name = r["meet_name"] or r["file_name"] or r["id"]
                    when = (r["created_at"] or "")[:19]
                    when_iso = when.replace(" ", "T") + "Z" if when else ""
                    configure_href = url_for("upload_configure", run_id=r["id"])
                    n_swims = r["our_swims"] or 0
                    failed = r["status"] == "error"
                    # A failed run has no swim count worth showing — flag that
                    # it didn't finish and invite a retry from the saved file.
                    meta_line = (
                        '<span class="tag bad" style="font-size:10px">Didn\'t finish</span>'
                        if failed
                        else f"{n_swims} swim{'' if n_swims == 1 else 's'}"
                    )
                    items_html += (
                        "<li>"
                        '<span class="ico">'
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'
                        "</span>"
                        f'<div class="body"><span class="name">{_h(name)}</span>'
                        f'<span class="meta">{meta_line} · '
                        f'<time class="mh-rel" datetime="{_h(when_iso)}">{_h(when)}</time></span>'
                        "</div>"
                        f'<a class="go" href="{configure_href}">'
                        f"{'Try again' if failed else 'Re-configure'} &rarr;</a>"
                        "</li>"
                    )
                recent_html = (
                    '<div class="card mh-recent-card">'
                    '<h3 style="margin-top:0;font-family:var(--font-mono);'
                    "font-size:var(--fs-10);letter-spacing:0.18em;"
                    "text-transform:uppercase;color:var(--ink-muted);"
                    'margin-bottom:var(--sp-3)">Re-run a recent meet</h3>'
                    f'<ul class="mh-recent-list">{items_html}</ul>'
                    "</div>"
                )
    except Exception:
        recent_html = ""

    # Results-from-a-link: second input mode (Step 7). Gated by the
    # kill-switch; the card is interpolated into the body as a value, so its
    # braces are literal (no f-string escaping needed).
    results_url_card = ""
    if W._results_url_enabled():
        _post_url = url_for("upload_from_url")
        _status_base = url_for("upload_from_url_status", job_id="JOBID")
        results_url_card = (
            (
                """
<style>
  .mh-rf-card .mh-rf-inputrow{display:flex;gap:var(--sp-3);flex-wrap:wrap;align-items:stretch}
  #mh-url-input{flex:1;min-width:min(260px,100%);padding:12px 14px;border-radius:10px;border:1px solid var(--border);background:rgba(255,255,255,0.04);color:inherit;font-family:inherit;font-size:15px;box-sizing:border-box;transition:border-color 160ms ease, box-shadow 160ms ease}
  #mh-url-input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in oklab, var(--accent) 18%, transparent)}
  #mh-url-fetch{transition:transform 140ms cubic-bezier(0.23,1,0.32,1)}
  #mh-url-fetch:active{transform:scale(0.97)}
  .mh-rf-panel{margin-top:var(--sp-4);padding:var(--sp-4) var(--sp-4) calc(var(--sp-4) - 2px);border:1px solid var(--border);border-radius:14px;background:color-mix(in oklab, var(--lane) 5%, transparent);animation:mh-rf-in 360ms cubic-bezier(0.23,1,0.32,1) both}
  @keyframes mh-rf-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
  .mh-rf-steps{display:flex;list-style:none;margin:0 0 var(--sp-4);padding:0}
  .mh-rf-steps li{flex:1;display:flex;flex-direction:column;align-items:center;gap:7px;position:relative;font-family:var(--font-mono);font-size:10px;letter-spacing:0.1em;text-transform:uppercase;text-align:center;color:var(--ink-muted);opacity:0.5;transition:opacity 220ms ease,color 220ms ease}
  .mh-rf-steps li .dot{width:11px;height:11px;border-radius:999px;border:2px solid color-mix(in oklab, var(--ink-muted) 45%, transparent);background:transparent;position:relative;z-index:1;transition:background 240ms cubic-bezier(0.23,1,0.32,1),border-color 240ms ease,box-shadow 240ms ease}
  .mh-rf-steps li:not(:last-child)::after{content:'';position:absolute;top:5px;left:50%;width:100%;height:2px;background:color-mix(in oklab, var(--ink-muted) 20%, transparent);z-index:0;transition:background 240ms ease}
  .mh-rf-steps li.is-active{opacity:1;color:var(--ink)}
  .mh-rf-steps li.is-active .dot{border-color:var(--accent);box-shadow:0 0 0 4px color-mix(in oklab, var(--accent) 20%, transparent)}
  .mh-rf-steps li.is-done{opacity:1}
  .mh-rf-steps li.is-done .dot{background:var(--accent);border-color:var(--accent)}
  .mh-rf-steps li.is-done::after{background:var(--accent)}
  .mh-rf-meter{display:flex;align-items:center;gap:var(--sp-4)}
  .mh-rf-pct{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:30px;font-weight:600;line-height:1;color:var(--ink);min-width:3.4ch;text-align:right}
  .mh-rf-pct i{font-size:15px;color:var(--ink-muted);font-style:normal;margin-left:2px}
  .mh-rf-track{position:relative;flex:1;height:10px;border-radius:999px;background:rgba(255,255,255,0.07);overflow:hidden}
  .mh-rf-fill{position:absolute;top:0;bottom:0;left:0;width:0%;border-radius:999px;background:linear-gradient(90deg, color-mix(in oklab, var(--accent) 72%, #000), var(--accent));transition:width 560ms cubic-bezier(0.23,1,0.32,1)}
  .mh-rf-track.is-active::after{content:'';position:absolute;top:0;bottom:0;left:0;right:0;background:linear-gradient(90deg, transparent, rgba(255,255,255,0.20), transparent);transform:translateX(-100%);animation:mh-rf-shimmer 1.4s linear infinite}
  @keyframes mh-rf-shimmer{to{transform:translateX(100%)}}
  .mh-rf-stats{display:flex;flex-wrap:wrap;gap:8px;margin-top:var(--sp-4)}
  .mh-rf-chip{font-family:var(--font-mono);font-size:12px;color:var(--ink-muted);padding:5px 11px;border-radius:999px;border:1px solid var(--border);background:rgba(255,255,255,0.03)}
  .mh-rf-chip b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
  .mh-rf-status{margin-top:var(--sp-3);font-family:var(--font-mono);font-size:12px;color:var(--ink-muted);min-height:1.2em}
  @media (prefers-reduced-motion: reduce){
    .mh-rf-panel{animation:none}
    .mh-rf-fill{transition:width 200ms ease}
    .mh-rf-track.is-active::after{display:none}
  }
</style>
<div class="card mh-rf-card" style="margin-top:var(--sp-4)">
  <h3 style="margin-top:0;font-family:var(--font-mono);font-size:var(--fs-10);letter-spacing:0.18em;text-transform:uppercase;color:var(--ink-muted);margin-bottom:var(--sp-3)">Or paste a results link</h3>
  <p class="lede" style="font-size:var(--fs-14);margin-bottom:var(--sp-4)">Works with results sites for any sport &mdash; including modern app-style sites. We&rsquo;ll read every result on the site, fast.</p>
  <div class="mh-rf-inputrow">
    <input id="mh-url-input" type="url" inputmode="url" autocomplete="off" placeholder="https://results.example.org/championships/2026/" aria-label="Results page URL" />
    <button id="mh-url-fetch" class="btn" type="button">Fetch results &rarr;</button>
  </div>
  <div id="mh-url-panel" class="mh-rf-panel" hidden>
    <ol id="mh-url-steps" class="mh-rf-steps">
      <li data-phase="fetching"><span class="dot"></span>Reading site</li>
      <li data-phase="reading"><span class="dot"></span>Extracting</li>
      <li data-phase="packaging"><span class="dot"></span>Packaging</li>
      <li data-phase="done"><span class="dot"></span>Ready</li>
    </ol>
    <div class="mh-rf-meter">
      <div class="mh-rf-pct"><span id="mh-url-pct">0</span><i>%</i></div>
      <div id="mh-url-progress" class="mh-rf-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Fetch progress">
        <div id="mh-url-progress-fill" class="mh-rf-fill"></div>
      </div>
    </div>
    <div class="mh-rf-stats">
      <span class="mh-rf-chip"><b id="mh-url-stat-pages">0</b> pages read</span>
      <span class="mh-rf-chip"><b id="mh-url-stat-kept">0</b> with results</span>
      <span class="mh-rf-chip"><b id="mh-url-stat-size">0 KB</b> mirrored</span>
    </div>
    <div id="mh-url-status" class="mh-rf-status" role="status" aria-live="polite"></div>
  </div>
  <div id="mh-url-error" class="mh-field-error" role="alert" hidden style="margin-top:var(--sp-3)"></div>
</div>
<script>
(function(){
  var btn = document.getElementById('mh-url-fetch');
  var input = document.getElementById('mh-url-input');
  var panel = document.getElementById('mh-url-panel');
  var statusEl = document.getElementById('mh-url-status');
  var errEl = document.getElementById('mh-url-error');
  var track = document.getElementById('mh-url-progress');
  var fill = document.getElementById('mh-url-progress-fill');
  var pctNum = document.getElementById('mh-url-pct');
  var steps = panel ? panel.querySelectorAll('#mh-url-steps li') : [];
  var statPages = document.getElementById('mh-url-stat-pages');
  var statKept = document.getElementById('mh-url-stat-kept');
  var statSize = document.getElementById('mh-url-stat-size');
  if (!btn || !input) return;
  var PHASES = ['fetching','reading','packaging','done'];
  var lastPct = 0;
  // Cursor-anchored readout for the (long) site-fetch ingest: created when the
  // fetch starts, fed the real percent each poll, removed on done/error.
  var cursor = null;
  function setText(el, msg){ if (el){ el.textContent = msg; } }
  function setPct(p){
    if (typeof p !== 'number' || isNaN(p)) return;
    // Monotonic: never let the bar jump backwards on a stale poll.
    if (p < lastPct) p = lastPct;
    lastPct = p;
    var r = Math.round(p);
    if (track) track.setAttribute('aria-valuenow', String(r));
    if (fill) fill.style.width = p + '%';
    if (pctNum) pctNum.textContent = String(r);
    if (cursor) cursor.set(p);
  }
  function setPhase(ph, allDone){
    var idx = (ph === 'queued') ? 0 : PHASES.indexOf(ph);
    if (!allDone && idx < 0) return;
    for (var i = 0; i < steps.length; i++){
      var active = !allDone && i === idx;
      var done = allDone ? true : (i < idx);
      steps[i].classList.toggle('is-active', active);
      steps[i].classList.toggle('is-done', done && !active);
    }
  }
  function fmtSize(kb){ kb = kb || 0; return kb >= 1024 ? (kb / 1024).toFixed(1) + ' MB' : kb + ' KB'; }
  function setStats(s){
    if (!s) return;
    if (statPages) statPages.textContent = s.discovered ? (s.pages + ' / ~' + s.discovered) : (s.pages || 0);
    if (statKept) statKept.textContent = s.kept || 0;
    if (statSize) statSize.textContent = fmtSize(s.kb);
  }
  function resetStats(){ if (statPages) statPages.textContent = '0'; if (statKept) statKept.textContent = '0'; if (statSize) statSize.textContent = '0 KB'; }
  function stopActive(){ if (track) track.classList.remove('is-active'); }
  function go(){
    var url = (input.value || '').trim();
    if (errEl) errEl.hidden = true;
    if (!/^https?:\\/\\//i.test(url)) { if (errEl){ errEl.textContent = 'Enter a full URL starting with http:// or https://'; errEl.hidden = false; } return; }
    btn.disabled = true; input.disabled = true;
    if (panel) panel.hidden = false;
    if (track) track.classList.add('is-active');
    resetStats(); setPhase('fetching', false); setText(statusEl, 'Starting\\u2026');
    cursor = (window.MH && MH.cursorReadout) ? MH.cursorReadout({ label: 'Fetching results', percent: 3 }) : null;
    lastPct = 0; setPct(3);
    var fd = new FormData(); fd.append('url', url);
    fetch('__POST_URL__', { method: 'POST', headers: { 'X-CSRF-Token': '__CSRF__', 'Accept': 'application/json' }, body: fd })
      .then(function(r){ return r.text().then(function(t){ var j=null; try { j=JSON.parse(t); } catch(e){} return { ok: r.ok, status: r.status, j: j }; }); })
      .then(function(res){
        if (!res.j) { throw new Error('The server returned an unexpected response (' + res.status + '). You may need to sign in again, or the deployment is briefly restarting \\u2014 reload the page and try again.'); }
        if (!res.ok || res.j.error) { throw new Error(res.j.error || res.j.message || 'Could not start the fetch.'); }
        poll(res.j.job_id);
      })
      .catch(function(e){ if (cursor) cursor.done(); fail(e.message); });
  }
  function fail(msg){
    btn.disabled = false; input.disabled = false;
    stopActive(); if (panel) panel.hidden = true; cursor = null;
    if (errEl){ errEl.textContent = msg; errEl.hidden = false; }
  }
  function poll(jobId){
    var statusUrl = '__STATUS_BASE__'.replace('JOBID', jobId);
    var unknownStreak = 0, errStreak = 0;
    var lostMsg = 'We can\\u2019t find this fetch any more \\u2014 please try the link again.';
    var tick = function(){
      fetch(statusUrl, { headers: { 'Accept': 'application/json' } }).then(function(r){ return r.json(); }).then(function(j){
        errStreak = 0;
        // 'unknown' = the job left memory/disk (worker restart / prune). It is
        // terminal, but tolerate a couple during a worker swap before failing so
        // a transient 404 doesn't kill a live fetch.
        if (j.status === 'unknown') {
          if (++unknownStreak >= 3) { if (cursor) cursor.done(); fail(lostMsg); return; }
          setTimeout(tick, 1500); return;
        }
        unknownStreak = 0;
        if (typeof j.percent === 'number') setPct(j.percent);
        setStats(j.stats);
        if (j.status === 'done' && j.redirect) { setPct(100); setPhase(null, true); stopActive(); setText(statusEl, 'Done \\u2014 opening configure\\u2026'); if (cursor) cursor.done(); window.location.href = j.redirect; return; }
        if (j.status === 'error') { if (cursor) cursor.done(); fail(j.error || 'The fetch failed.'); return; }
        if (j.phase) setPhase(j.phase, false);
        setText(statusEl, j.progress || 'Reading the site\\u2026');
        if (cursor) cursor.status(j.progress || 'Reading the site\\u2026');
        setTimeout(tick, 1500);
      }).catch(function(){
        // Cap consecutive network failures so a gone job can't poll forever.
        if (++errStreak >= 8) { if (cursor) cursor.done(); fail(lostMsg); return; }
        setTimeout(tick, 2500);
      });
    };
    tick();
  }
  btn.addEventListener('click', go);
  input.addEventListener('keydown', function(e){ if (e.key === 'Enter') { e.preventDefault(); go(); } });
})();
</script>
"""
            )
            .replace("__POST_URL__", _post_url)
            .replace("__STATUS_BASE__", _status_base)
            .replace("__CSRF__", W._csrf_token())
        )

    # H-18: a rejected POST re-renders this same page with the error
    # inline — same region and look the client-side showError() uses.
    _upload_err_hidden = "" if upload_error else " hidden"
    _upload_dz_invalid = ' style="border-color:var(--bad)"' if upload_error else ""

    body = f"""
<div class="mh-fx mh-aurora" style="overflow:hidden;border-radius:var(--radius-lg);margin-bottom:var(--sp-4)">
<section class="mh-hero" data-lane="01" style="padding-top:var(--sp-8);padding-bottom:var(--sp-6)">
  <span class="mh-hero-eyebrow">Upload meet file</span>
  <h1>Drop the results.<br><em class="editorial">We'll do the rest.</em></h1>
  <p class="lede">Upload your meet results file — Hytek&nbsp;<code>.hy3</code>&hairsp;/&hairsp;<code>.hyv</code>&hairsp;/&hairsp;<code>.zip</code>, SDIF&hairsp;/&hairsp;SD3&hairsp;/&hairsp;CL2, PDF, CSV, TXT, Excel&nbsp;<code>.xlsx</code> or HTML. You'll pick your club, upload your logo, and add photos on the next step.</p>
  <a class="mh-how-pill" href="{url_for("content_type_intro", ct="meet_recap")}" style="margin-top:var(--sp-3)">How it works</a>
</section>
</div>

<nav class="mh-stepper" aria-label="Upload progress">
  <span class="mh-stepper-item is-active"><span class="num">1</span>Upload</span>
  <span class="mh-stepper-arrow"></span>
  <span class="mh-stepper-item"><span class="num">2</span>Configure</span>
  <span class="mh-stepper-arrow"></span>
  <span class="mh-stepper-item"><span class="num">3</span>Run</span>
  <span class="mh-stepper-arrow"></span>
  <span class="mh-stepper-item"><span class="num">4</span>Review</span>
</nav>

{W._llm_unavailable_banner()}
{recent_html}
<div class="card">
  <form id="mh-upload-form" method="post" enctype="multipart/form-data" data-loader-text="Reading your meet file">
    <label class="req" for="upload-file">Meet results file</label>
    <div id="mh-upload-error" class="mh-field-error" role="alert"{_upload_err_hidden} style="margin-bottom:var(--sp-3)">{upload_error}</div>
    <label class="mh-dropzone" for="upload-file"{_upload_dz_invalid}>
      <svg class="mh-dropzone-icon" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M24 32V12"/>
        <polyline points="16 19 24 11 32 19"/>
        <path d="M8 32v6a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4v-6"/>
      </svg>
      <div class="mh-dropzone-headline">Drop your results file</div>
      <div class="mh-dropzone-sub">or click to browse</div>
      <input id="upload-file" type="file" name="file" accept=".hy3,.hyv,.sd3,.sdif,.cl2,.zip,.pdf,.htm,.html,.csv,.txt,.xlsx" required />
      <div class="mh-dropzone-fineprint">HY3 · SDIF/SD3/CL2 · ZIP · PDF · CSV · TXT · HTML · Excel (.xlsx)</div>
      <div class="mh-dropzone-preview" aria-live="polite"></div>
    </label>
    <div id="mh-parse-preview" class="mh-parse-preview" role="status" aria-live="polite">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
      <div class="label"><b>—</b><span></span></div>
    </div>
    <div style="margin-top:var(--sp-5);display:flex;gap:var(--sp-3);flex-wrap:wrap">
      <button id="mh-upload-submit" class="btn mh-cta-motion" type="submit">
        <span class="mh-btn-label">Continue &rarr;</span>
        <span class="mh-btn-spin" aria-hidden="true"></span>
        <span class="mh-btn-check" aria-hidden="true">&#x2713;</span>
      </button>
      <a class="btn ghost" href="{url_for("home")}">Cancel</a>
    </div>
  </form>
</div>
{results_url_card}
{W._sample_pack_cta()}
<div class="mh-next-strip" aria-label="What happens next">
  <div class="cell"><span class="num">2</span><span class="text"><b>Configure</b><br>Pick your club from the parsed list, upload your logo, choose tone, and drop in photos.</span></div>
  <div class="cell"><span class="num">3</span><span class="text"><b>Pipeline runs</b><br>The engine spots PBs, medals, first-times and comebacks. About 30 to 60 seconds.</span></div>
  <div class="cell"><span class="num">4</span><span class="text"><b>Review &amp; approve</b><br>Approve and edit the cards you want to post. Nothing leaves the deployment without you.</span></div>
</div>

<script>
(function(){{
  var form = document.getElementById('mh-upload-form');
  if (!form) return;
  var input = form.querySelector('input[type=file]');
  var btn = document.getElementById('mh-upload-submit');
  var preview = document.getElementById('mh-parse-preview');
  var errEl = document.getElementById('mh-upload-error');
  var dropzone = form.querySelector('.mh-dropzone');
  if (!input || !btn) return;
  function hasFile() {{ return !!(input.files && input.files.length && input.files[0]); }}
  function clearError() {{
    if (errEl) {{ errEl.hidden = true; errEl.textContent = ''; }}
    if (dropzone) {{
      dropzone.classList.remove('is-invalid');
      dropzone.style.borderColor = '';
    }}
  }}
  function showError(msg) {{
    if (errEl) {{ errEl.textContent = msg; errEl.hidden = false; }}
    if (dropzone) {{
      dropzone.classList.add('is-invalid');
      dropzone.style.borderColor = 'var(--bad)';
    }}
    try {{ input.focus(); }} catch (e) {{}}
  }}
  function fmtBytes(n) {{
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }}
  // Mirrors the server's upload extension allowlist exactly — a file the
  // preview calls good is a file the server will accept, and vice versa.
  function inferFormat(name) {{
    var n = (name || '').toLowerCase();
    if (n.endsWith('.hy3'))  return {{kind: 'good', label: 'Hytek Meet Manager (.hy3)',  note: 'looks good'}};
    if (n.endsWith('.hyv'))  return {{kind: 'good', label: 'Hytek Meet Manager (.hyv)',  note: 'looks good'}};
    if (n.endsWith('.zip'))  return {{kind: 'good', label: 'Hytek .zip export',          note: 'we\\u2019ll unpack and read it'}};
    if (n.endsWith('.sd3'))  return {{kind: 'good', label: 'SDIF results file (.sd3)',   note: 'looks good'}};
    if (n.endsWith('.sdif')) return {{kind: 'good', label: 'SDIF results file (.sdif)',  note: 'looks good'}};
    if (n.endsWith('.cl2'))  return {{kind: 'good', label: 'CL2 results file',           note: 'looks good'}};
    if (n.endsWith('.pdf'))  return {{kind: 'good', label: 'PDF results file',           note: 'we\\u2019ll run the OCR / table extractor'}};
    if (n.endsWith('.csv'))  return {{kind: 'good', label: 'CSV results file',           note: 'we\\u2019ll read every row'}};
    if (n.endsWith('.htm') || n.endsWith('.html')) return {{kind: 'good', label: 'HTML results page', note: 'we\\u2019ll extract the result tables'}};
    if (n.endsWith('.txt'))  return {{kind: 'good', label: 'Text results file',          note: 'we\\u2019ll try every adapter'}};
    if (n.endsWith('.xlsx')) return {{kind: 'good', label: 'Excel workbook (.xlsx)',     note: 'we\\u2019ll read every sheet'}};
    if (n.endsWith('.xls'))  return {{kind: 'bad',  label: 'Old Excel format (.xls)',    note: 'save it as .xlsx and upload that instead'}};
    var dot = n.lastIndexOf('.');
    var ext = dot > 0 ? n.slice(dot) : '';
    return {{kind: 'bad',
             label: ext ? 'MediaHub can\\u2019t read ' + ext + ' files' : 'MediaHub can\\u2019t read this file',
             note: 'upload HY3, SDIF/SD3/CL2, ZIP, PDF, HTML, CSV, TXT or Excel (.xlsx)'}};
  }}
  function refresh() {{
    var f = input.files && input.files[0];
    var has = !!f;
    if (!has) {{ if (preview) preview.removeAttribute('data-shown'); btn.disabled = false; return; }}
    var info = inferFormat(f.name);
    // Honest blocker: the drag-and-drop path bypasses the picker's accept
    // filter, so an unsupported file is stopped here instead of 400ing
    // after the upload.
    if (info.kind === 'bad') {{
      btn.disabled = true;
      showError(info.label + ' \\u2014 ' + info.note + '.');
    }} else {{
      btn.disabled = false;
      clearError();
    }}
    if (!preview) return;
    preview.className = 'mh-parse-preview' + (info.kind === 'warn' ? ' warn' : (info.kind === 'bad' ? ' bad' : ''));
    var labelEl = preview.querySelector('.label');
    labelEl.querySelector('b').textContent = info.label + ' \\u00b7 ' + fmtBytes(f.size);
    labelEl.querySelector('span').textContent = info.note;
  }}
  input.addEventListener('change', refresh);
  form.addEventListener('submit', function(e) {{
    if (!hasFile()) {{
      e.preventDefault();
      showError('Please choose a results file first.');
      return;
    }}
    // Stateful CTA: spin while the file uploads + the parser runs, so the
    // single primary action shows it's working before the page turns over.
    if (window.MH && MH.btnState) MH.btnState(btn, 'loading');
  }});
  refresh();
}})();
</script>
"""
    page = W._layout("Upload", body, active="create")
    return (page, 400) if upload_error else page


def upload_from_url():
    """Kick off a background results-from-a-link fetch. Returns a job id the
    upload page polls; on success the job stages a ZIP and the page redirects
    to the EXISTING configure step."""
    if not W._results_url_enabled():
        return jsonify({"error": "Results-from-a-link is disabled on this deployment."}), 404
    from urllib.parse import urlparse

    url = (request.values.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return (
            jsonify({"error": "Enter a full results-page URL starting with http:// or https://"}),
            400,
        )
    # Early SSRF reject (every fetch inside the crawl is re-validated too).
    # FAIL-CLOSED: if the guard itself can't run, the URL doesn't either.
    try:
        from mediahub.web_research.safe_fetch import is_url_safe

        url_ok = is_url_safe(url)
    except Exception:
        W.log.warning("SSRF guard unavailable — refusing user-supplied URL", exc_info=True)
        url_ok = False
    if not url_ok:
        return (
            jsonify({"error": "That address can't be reached (private/invalid host)."}),
            400,
        )
    # Per-identity rate limit (a real headless-browser crawl is a real cost).
    if not W._url_fetch_rate_ok(W._url_fetch_rate_key()):
        return (
            jsonify({"error": "Too many fetches just now — wait a minute and try again."}),
            429,
        )
    prof = W._active_profile()
    profile_id = prof.profile_id if prof is not None else None
    job_id = W._start_url_fetch_job(url, profile_id)
    return jsonify({"job_id": job_id})


def run_refetch(run_id):
    """Re-fetch a results-from-a-link run's source as a brand-new run.

    Reuses the Step-7 background job and the SAME status endpoint the upload
    page polls, so a fresh run is staged for /upload/configure. Never mutates
    the existing run — re-fetch is always additive."""
    if not W._results_url_enabled():
        return jsonify({"error": "Results-from-a-link is disabled on this deployment."}), 404
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id or ""):
        return jsonify({"error": "Bad run id"}), 400
    # Tenant gate — don't let a run id from another org be re-fetched.
    if not W._can_access_run(run_id, W._load_run(run_id), W._active_profile_id()):
        return jsonify({"error": "Run not found"}), 404
    source_url = W._run_source_url(run_id)
    if not source_url:
        return jsonify({"error": "This run wasn't fetched from a link."}), 400
    if not W._url_fetch_rate_ok(W._url_fetch_rate_key()):
        return (
            jsonify({"error": "Too many fetches just now — wait a minute and try again."}),
            429,
        )
    prof = W._active_profile()
    profile_id = prof.profile_id if prof is not None else None
    job_id = W._start_url_fetch_job(source_url, profile_id)
    return jsonify({"job_id": job_id})


def upload_configure():
    run_id = request.values.get("run_id", "").strip()
    if not run_id:
        return W._recovery_page(
            "Configure step opened without a run",
            "The configure step is the second half of the upload flow — you reach it by uploading a file first. Open the upload page and pick a meet results file to start.",
            eyebrow="Upload",
            primary_cta=("Start an upload", url_for("upload")),
            secondary_cta=("All input types", url_for("make_page")),
        )
    # `run_id` is read from request.values (form + query), so a
    # client can submit arbitrary bytes — including `..` segments.
    # Reject anything that isn't shaped like a generated run token
    # (12-char hex from uuid4().hex[:12], or the longer ids
    # _start_run produces). This blocks path traversal where the
    # file-system join would otherwise let the configure step read
    # `upload_meta.json` from outside RUNS_DIR.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        return W._recovery_page(
            "Upload session expired",
            "The staged upload only lives for a few minutes before it's swept. Start a new upload — the file picker is one click away.",
            eyebrow="Upload",
            primary_cta=("Start a new upload", url_for("upload")),
            secondary_cta=("Recent runs", url_for("activity_page")),
        )
    tmp_dir = W.RUNS_DIR / run_id
    meta_path = tmp_dir / "upload_meta.json"
    input_path = tmp_dir / "input.bin"
    if not input_path.exists():
        return W._recovery_page(
            "Upload session expired",
            "The staged upload only lives for a few minutes before it's swept. Start a new upload — the file picker is one click away.",
            eyebrow="Upload",
            primary_cta=("Start a new upload", url_for("upload")),
            secondary_cta=("Recent runs", url_for("activity_page")),
        )
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            meta = {}
    else:
        # Re-configuring an already-processed (or failed) run from the
        # "Re-run a recent meet" card: the staged upload_meta.json only ever
        # exists for a brand-new upload, but the run's saved input.bin +
        # resume.json survive on disk, so rebuild the configure metadata here
        # (a fresh light club-parse) instead of 404ing. Without this the card's
        # "Try again"/"Re-configure" links always hit "Upload session expired".
        meta = W._rebuild_staged_meta(tmp_dir, input_path)

    if request.method == "POST":
        club_filter = (request.form.get("club_filter") or "").strip() or None
        if not club_filter:
            # Designed error state (U.2), not a dead-end card: the staged
            # upload is still on disk, so offer a clear way back to re-pick
            # rather than stranding the volunteer on a one-line error.
            return W._layout(
                "Configure",
                W._empty_state(
                    "alert",
                    "Pick a club to feature",
                    "Choose which club&rsquo;s swimmers this content pack is about, "
                    "then start the run &mdash; we never guess the club for you.",
                    actions=(
                        f'<a class="btn" href="{url_for("upload_configure", run_id=run_id)}">'
                        "Back to configure &rarr;</a>"
                    ),
                    kind="error",
                ),
                active="create",
            ), 400

        # Phase 1.5 logo consolidation: logos now live on the active
        # organisation profile, not on individual runs. The configure
        # form no longer accepts a club_logo file; the per-run brand
        # kit pulls the logo from the active ClubProfile's
        # brand_logo_url and the colour pickers default to the
        # profile's saved colours (still per-run-overridable).
        active_prof_for_run = W._active_profile()
        logo_bytes = None
        logo_filename = None
        primary_form = (request.form.get("primary_colour") or "").strip() or None
        secondary_form = (request.form.get("secondary_colour") or "").strip() or None
        accent_form = (request.form.get("accent_colour") or "").strip() or None
        use_logo_colours = False
        display_name_form = (request.form.get("display_name") or club_filter or "").strip()
        # H-13: which of the org's saved brand kits these results run
        # under. Validated against the org's kit list — an unknown or
        # foreign id degrades to "" (= the org's default kit), so a
        # tampered form can never pin a kit the org doesn't own.
        brand_kit_choice = (request.form.get("brand_kit_id") or "").strip()
        if brand_kit_choice:
            try:
                from mediahub.brand import kits as _bkits

                if active_prof_for_run is None or (
                    _bkits.get_kit(active_prof_for_run, brand_kit_choice) is None
                ):
                    brand_kit_choice = ""
            except Exception:
                brand_kit_choice = ""
        # We always have branding now (the profile guarantees it), so
        # the old "branding required" gate is removed. If somehow
        # neither the profile nor the form supplies colours, the
        # downstream renderer falls back to deterministic defaults.

        data = input_path.read_bytes()
        # Pin the run to the active organisation so it appears on
        # /activity for the right tenant. Falls back to the upload
        # meta only if it carries a profile_id (older flows); modern
        # flows always come through the org-gated Create tab,
        # so the session pin is the authoritative source. A meta id
        # naming a bound workspace this session may not enter is
        # ignored (PC.3) — never stamp a run into a foreign tenant.
        meta_pid = (meta.get("profile_id") or "").strip()
        if meta_pid and not W._session_can_use_profile(meta_pid):
            meta_pid = ""
        profile_id = meta_pid or W._active_profile_id() or None
        use_cache = bool(meta.get("use_cache", True))
        fetch_pbs = bool(meta.get("fetch_pbs", True))
        filename = meta.get("filename") or "upload.bin"

        # Kick off the real run; reuse the temp run_id.
        new_run_id = W._start_run(
            data,
            filename,
            profile_id,
            use_cache,
            fetch_pbs,
            club_filter=club_filter,
            source_url=meta.get("source_url"),
        )

        # Persist the brand kit (colours) for the new run id. The
        # logo is no longer per-run — it comes from the active
        # profile's brand_logo_url at render time (see
        # content_pack_visual/integration.py fallback). If the
        # profile has a logo, we fetch it once and seed the run's
        # brand kit with it so downstream layout code that expects
        # a local path doesn't trip.
        try:
            from .brand_kit_upload import process_upload as _bk_process

            profile_logo_bytes = None
            profile_logo_name = None
            if active_prof_for_run is not None:
                # Logos the user uploaded at /organisation/setup ALWAYS
                # beat the one auto-discovered from the club website.
                # An uploaded file is an explicit brand decision; the
                # scraped brand_logo_url is only a best guess (and has
                # picked up university-site logos before).
                try:
                    from mediahub.brand.logos import (
                        resolve_logo_path as _resolve_logo_path,
                    )

                    for _lg in getattr(active_prof_for_run, "brand_logos", None) or []:
                        if not str(_lg.get("mime", "")).startswith("image/"):
                            continue
                        _lp = _resolve_logo_path(
                            active_prof_for_run.profile_id,
                            _lg.get("logo_id", ""),
                        )
                        if not _lp:
                            continue
                        _lb = _lp.read_bytes()
                        if _lb and len(_lb) < 5_000_000:
                            profile_logo_bytes = _lb
                            profile_logo_name = _lp.name
                            break
                except Exception:
                    profile_logo_bytes = None
                # Fall back to the website-discovered logo URL only when
                # nothing was uploaded.
                url = (getattr(active_prof_for_run, "brand_logo_url", "") or "").strip()
                if (
                    profile_logo_bytes is None
                    and url
                    and (url.startswith("http://") or url.startswith("https://"))
                ):
                    try:
                        import requests as _rq

                        r = _rq.get(url, timeout=10)
                        if r.ok and len(r.content) < 5_000_000:
                            profile_logo_bytes = r.content
                            # Derive a sensible filename from the URL
                            # path so the on-disk save uses the right
                            # extension. Default to .png if unknown.
                            from urllib.parse import urlparse

                            path = urlparse(url).path or ""
                            tail = path.rsplit("/", 1)[-1] or "logo.png"
                            if "." not in tail:
                                tail += ".png"
                            profile_logo_name = tail
                    except Exception:
                        profile_logo_bytes = None
            _bk_process(
                new_run_id,
                logo_bytes=profile_logo_bytes,
                logo_filename=profile_logo_name,
                primary_form=primary_form,
                secondary_form=secondary_form,
                accent_form=accent_form,
                use_logo_colours=False,
                display_name=display_name_form,
                brand_kit_id=brand_kit_choice,
            )
        except Exception:
            pass

        # Photos are no longer collected at the configure step — each
        # card's graphic has its own "Add photo of <athlete>" control
        # (api_card_photo_upload) that stores the photo in the org's
        # media library linked to the athlete, so it can be suggested
        # again at the next meet.
        return redirect(url_for("run_status", run_id=new_run_id))

    # Pre-select the club whose name best fuzzy-matches the active org, so
    # the common case is a single click. The user still confirms (and can
    # change it); an unconfident match pre-selects nothing.
    _ap = W._active_profile()
    _preselect = W._best_club_match(meta.get("clubs") or [], _ap.display_name if _ap else "")
    # Re-run guard (warn, never block): has this org already processed this
    # exact file, or this same meet via any tool? Compare the staged file's
    # content hash and the meet identity against finished runs.
    duplicate = None
    try:
        _pid = W._active_profile_id()
        _chash = W._content_hash(input_path.read_bytes())
        _fp = W._meet_fingerprint(_pid, meta.get("meet_name"), meta.get("meet_date"))
        duplicate = W._find_duplicate_run(_pid, _chash, _fp, exclude_run_id=run_id)
    except Exception:  # noqa: BLE001
        duplicate = None
    return W._render_configure(run_id, meta, selected_club=_preselect, duplicate=duplicate)


@W.require_run
def rerun_run(run_id):
    """D-6: re-launch a run from its server-persisted input file instead of
    forcing a full re-upload. The launch bytes are kept beside every run
    (``input.bin`` + ``resume.json``), so a poolside volunteer who no longer
    has the original file can retry in one click. Starts a fresh run so the
    failed run's record is preserved for diagnosis."""
    loaded = W._load_run_input(run_id)
    if not loaded:
        # The saved file isn't on disk (an old run, or a best-effort write
        # that failed) — be honest and send them to re-upload.
        if W._req_wants_json(request):
            return jsonify({"error": "no_saved_input"}), 409
        W._flash_toast(
            "We couldn't find the saved file for that run — please upload it again.",
            "error",
        )
        return redirect(url_for("upload"))
    data, meta = loaded
    new_run_id = W._start_run(
        file_bytes=data,
        file_name=meta.get("file_name") or "upload.bin",
        profile_id=meta.get("profile_id") or W._active_profile_id(),
        use_pb_cache=bool(meta.get("use_pb_cache", True)),
        fetch_pbs=bool(meta.get("fetch_pbs", True)),
        club_filter=meta.get("club_filter"),
    )
    target = url_for("run_status", run_id=new_run_id)
    if W._req_wants_json(request):
        return jsonify({"ok": True, "run_id": new_run_id, "redirect": target})
    return redirect(target)


@W.require_run(
    deny=lambda: (
        W._recovery_page(
            "Run not found",
            "This run isn't on disk or in memory. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            eyebrow="Run status",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Upload a new file", url_for("upload")),
        )
    )
)
# A run reported 'running'/'queued' but whose heartbeat has gone stale
# is dead (its worker was recycled or it wedged past every per-call
# timeout). Surface it as a terminal error so the poller stops instead
# of spinning forever.
def run_status(run_id):
    _status_url = url_for("api_status", run_id=run_id)
    _review_url = url_for("review", run_id=run_id)
    # Tenant gate: prevent the progress page from acting as an
    # existence oracle for runs owned by a different org.
    # If the run already finished (e.g. user refreshes /runs/<id>
    # post-completion, or bookmarks the URL), skip the holding pen
    # and send them straight to the review queue. Same for error.
    try:
        _cur = W._active_runs.copy_value(run_id)
        _row_status = None
        _row_error = None
        if _cur and isinstance(_cur, dict):
            _row_status = _cur.get("status")
            _row_error = _cur.get("error")
        if _row_status is None:
            _c = W._db()
            _r = _c.execute("SELECT status, error FROM runs WHERE id = ?", (run_id,)).fetchone()
            _c.close()
            if _r:
                _row_status = _r["status"]
                _row_error = _r["error"]
        if _row_status == "done":
            return redirect(_review_url)
        if _row_status == "error":
            # Server-side render a real error page rather than waiting for
            # the JS poller — gives the user immediate context and a clear
            # recovery path. D-6: the uploaded file is persisted server-side,
            # so lead with a one-click "Run this file again" instead of
            # forcing a re-upload; the raw exception is operator-only.
            _err_msg = _row_error or "Pipeline failed without leaving an error message."
            _is_dev_err = W._auth.is_dev_operator()
            _can_rerun = W._resume_input_exists(run_id)
            _rerun_action = (
                f'<form method="post" action="{url_for("rerun_run", run_id=run_id)}" style="display:inline">'
                '<button type="submit" class="mh-cta-primary">Run this file again &rarr;</button>'
                "</form>"
                if _can_rerun
                else f'<a class="mh-cta-primary" href="{url_for("upload")}">Try another file &rarr;</a>'
            )
            _upload_cta = (
                f'<a class="mh-cta-secondary" href="{url_for("upload")}">Upload a different file</a>'
                if _can_rerun
                else ""
            )
            _err_detail = (
                '<div class="card" style="border-left:2px solid var(--bad)">'
                '<div class="strap" style="color:var(--bad);margin-bottom:var(--sp-3)">Error detail</div>'
                f'<pre style="font-family:var(--font-mono);font-size:12px;white-space:pre-wrap;margin:0;color:var(--ink)">{_h(_err_msg)}</pre>'
                "</div>"
                if _is_dev_err
                else ""
            )
            _err_body = (
                '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7);margin-bottom:var(--sp-5)">'
                '<span class="mh-hero-eyebrow">Pipeline failed</span>'
                "<h1>Run didn't finish.</h1>"
                '<p class="lede">'
                "The pipeline hit a snag before producing any cards &mdash; often a results file the parser couldn't read. Your file is saved, so you can run it again, or try a different one."
                "</p>"
                '<div class="mh-hero-actions">'
                f"{_rerun_action}"
                f"{_upload_cta}"
                f'<a class="mh-cta-secondary" href="{url_for("activity_page")}">All recent runs</a>'
                "</div>"
                "</section>"
                f"{_err_detail}"
            )
            return W._layout("Run failed", _err_body, active="create")
        # Round-6 fix: when neither the in-memory cache nor the DB has
        # the run id, we used to fall through to the "Processing run"
        # hero with an indefinite poller — users bookmarking a stale
        # URL would stare at an infinite spinner. Now we send them to
        # the recovery page instead.
        if _row_status is None:
            return W._recovery_page(
                "Run not found",
                "This run isn't on disk or in memory. It may have been deleted from /privacy, or the URL might be from a different deployment.",
                eyebrow="Run status",
                primary_cta=("Open activity", url_for("activity_page")),
                secondary_cta=("Upload a new file", url_for("upload")),
            )
    except Exception:
        pass
    # Operators (the signed-in developer) get the raw, engineer-facing step
    # log + technical detail; a customer sees only a clean percentage bar and
    # a plain-English phase describing what the engine is doing — never the
    # raw steps or internal error text.
    _is_dev = W._auth.is_dev_operator()
    # D-6: the launch file is persisted, so on failure we can offer a
    # one-click re-run from it rather than a forced re-upload.
    _can_rerun = W._resume_input_exists(run_id)
    _rerun_form = (
        f'<form id="rerun-form" method="post" action="{url_for("rerun_run", run_id=run_id)}" style="display:none">'
        '<button type="submit" class="btn">Run this file again &rarr;</button>'
        "</form>"
        if _can_rerun
        else ""
    )
    _dev_stepcount = (
        '<span class="sep">·</span><span id="mh-step-count">0 steps</span>' if _is_dev else ""
    )
    _dev_steploader = (
        '<div class="mh-steploader" id="mh-steps" style="margin-top:var(--sp-4)"></div>'
        if _is_dev
        else ""
    )
    _dev_techlog = (
        '<details style="margin-top:var(--sp-5)">'
        '<summary style="cursor:pointer;color:var(--ink-dim);font-size:13px;user-select:none">Show technical log</summary>'
        '<div class="progress-log" id="log" style="margin-top:var(--sp-3)">Starting&hellip;</div>'
        "</details>"
        if _is_dev
        else ""
    )
    body = f"""
<section class="mh-hero" data-lane="--" style="padding-top:var(--sp-9);padding-bottom:var(--sp-7);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Pipeline running</span>
  <h1>Processing run</h1>
  <p class="lede">We're reading your results, finding the standout moments and drafting your content. Usually 20&ndash;60 seconds. This page opens your review queue the moment it's ready.</p>
</section>

<div class="card">
  <div class="strap live" role="status" aria-live="polite" style="margin-bottom:var(--sp-3)"><span id="mh-current-stage">Starting&hellip;</span>{_dev_stepcount}</div>
  <div class="mh-progress-bar indeterminate"><span></span></div>
  <div id="mh-percent" aria-live="polite" style="margin-top:var(--sp-2);font-size:13px;color:var(--ink-dim);font-variant-numeric:tabular-nums">0%</div>
  {_dev_steploader}
  {_dev_techlog}

  <p class="dim" style="margin-top:var(--sp-3);font-size:12.5px">You can leave this page &mdash; the run keeps going on our server and the finished content pack appears on your Home.</p>
  <div style="margin-top:var(--sp-4);display:flex;gap:var(--sp-3);flex-wrap:wrap">
    <a id="review-link" class="btn" style="display:none" href="{_review_url}">Open review queue &rarr;</a>
    {_rerun_form}
    <a id="retry-link"  class="btn secondary" style="display:none" href="{url_for("upload")}">Try another file</a>
    <a id="home-link"   class="btn secondary" href="{url_for("home")}">Leave &mdash; it finishes on Home</a>
  </div>
</div>

<script>
(function() {{
  var STATUS_URL = {json.dumps(_status_url)};
  var REVIEW_URL = {json.dumps(_review_url)};
  var IS_DEV = {("true" if _is_dev else "false")};
  // Poll cadence. Bounded backoff + a hard cap so a stuck/missing run can't
  // spin the spinner forever (the unbounded earlier version also helped trip
  // gunicorn's --max-requests recycle, which killed in-flight runs).
  var BASE_MS = 1500, SLOW_MS = 8000, MAX_BACKOFF_MS = 6000;
  var SOFT_CAP_MS = 90000;     // reassure the user it's still working
  var HARD_CAP_MS = 480000;    // 8 min: slow down, keep going (big meets)
  var FAIL_GIVEUP = 8;         // consecutive transport failures before we quit
  var startedAt = Date.now(), fails = 0, stopped = false;
  // QA-005: status polls round-robin across the 2 gunicorn workers. The worker
  // that isn't running the pipeline has no in-memory log and falls back to the
  // throttled DB progress_log, which lags — so a single poll's percent / step
  // count can read LOWER than an earlier one and the bar appears to jump
  // backwards. The client is the one consistent observer across polls, so hold
  // a high-water mark for both: reported progress never decreases.
  var maxPct = 0, maxSteps = 0, bestLog = [];
  var stage = document.getElementById('mh-current-stage');
  var stepEl = document.getElementById('mh-step-count');
  var logEl = document.getElementById('log');
  var pctEl = document.getElementById('mh-percent');
  var bar = document.querySelector('.mh-progress-bar');
  var lede = document.querySelector('.lede');
  var reviewLink = document.getElementById('review-link');
  var retryLink = document.getElementById('retry-link');
  // D-6: a one-click re-run from the saved file (present only when the launch
  // input is still on disk) — the primary recovery, shown ahead of re-upload.
  var rerunForm = document.getElementById('rerun-form');
  function showRerun() {{ if (rerunForm) rerunForm.style.display = 'inline-block'; }}

  function setStage(txt) {{ if (stage) stage.textContent = txt; }}
  // Drive the determinate progress bar + numeric readout from a 0–100 percent.
  function setBar(pct, colour) {{
    if (!bar) return;
    bar.classList.remove('indeterminate');
    var v = Math.max(0, Math.min(100, (typeof pct === 'number' ? pct : 0)));
    var s = bar.firstElementChild;
    if (s) {{ if (colour) s.style.background = colour; s.style.width = Math.max(2, v) + '%'; }}
    if (pctEl) pctEl.textContent = Math.round(v) + '%';
  }}
  function showStuck(msg) {{
    stopped = true;
    setStage('Stopped');
    setBar(100, 'var(--bad)');
    if (reviewLink) reviewLink.style.display = 'inline-flex';
    if (retryLink) retryLink.style.display = 'inline-flex';
    showRerun();
    if (lede) lede.textContent = msg;
    if (window.MH) MH.toast(msg, 'error', 9000);
  }}
  async function poll() {{
    if (stopped) return;
    var waited = Date.now() - startedAt, r, j;
    try {{
      r = await fetch(STATUS_URL, {{cache:'no-store'}});
      if (!r.ok && r.status !== 404) throw new Error('http ' + r.status);
      j = await r.json();
    }} catch (e) {{
      fails++;
      if (fails >= FAIL_GIVEUP && waited > HARD_CAP_MS) {{
        showStuck("We lost contact with the server while processing. Open the review queue to check whether it finished, or try uploading again.");
        return;
      }}
      setTimeout(poll, Math.min(MAX_BACKOFF_MS, BASE_MS * Math.pow(1.6, Math.min(fails, 5))));
      return;
    }}
    fails = 0;
    var status = (j && j.status) || 'unknown';
    var log = (j && j.log) || [];
    var pct = (j && typeof j.percent === 'number') ? j.percent : null;
    var phase = (j && j.phase) || null;

    // Clamp to the high-water mark so a lagging cross-worker poll can't rewind
    // the bar or the step count (QA-005). Keep the longest log seen so the step
    // count + raw log stay monotonic too.
    if (log.length >= maxSteps) {{ maxSteps = log.length; bestLog = log; }}
    log = bestLog;
    if (pct != null) {{ if (pct < maxPct) {{ pct = maxPct; }} maxPct = pct; }}

    // Developer-only raw detail: the verbatim step log, the live step list and
    // the technical-log panel. These elements aren't rendered for customers, so
    // the engineer-facing lines and internal error text stay operator-only.
    if (IS_DEV) {{
      if (logEl && log.length) {{ logEl.textContent = log.join('\\n'); logEl.scrollTop = logEl.scrollHeight; }}
      if (stepEl) stepEl.textContent = log.length + ' step' + (log.length === 1 ? '' : 's');
      if (window.MH && MH.renderLogSteps) MH.renderLogSteps('mh-steps', log, status);
    }}

    if (status === 'done') {{
      stopped = true;
      // Lead with the honest standout-swim count (distinct swims worth a
      // post); fall back to the raw detection count only for old payloads.
      var nStand = (j && j.n_standout != null) ? j.n_standout : null;
      var nAch = (j && j.n_achievements != null) ? j.n_achievements : null;
      var achLabel;
      if (nStand !== null && nStand > 0) {{
        achLabel = nStand + ' standout swim' + (nStand === 1 ? '' : 's') + ' found — ready to review';
      }} else if (nStand === null && nAch !== null && nAch > 0) {{
        achLabel = nAch + ' moment' + (nAch === 1 ? '' : 's') + ' found — ready to review';
      }} else {{
        achLabel = 'All done — ready to review';
      }}
      setStage(achLabel);
      if (lede) lede.textContent = achLabel + '. Opening your content…';
      setBar(100, null);
      if (reviewLink) reviewLink.style.display = 'inline-flex';
      if (window.MH) MH.toast(achLabel, 'success', 2500);
      setTimeout(function() {{ location.replace(REVIEW_URL); }}, 900);
      return;
    }}
    if (status === 'error') {{
      stopped = true;
      setBar(100, 'var(--bad)');
      if (retryLink) retryLink.style.display = 'inline-flex';
      showRerun();
      if (IS_DEV) {{
        setStage('Run failed');
        var emsg = (j && j.error) || 'unknown';
        if (logEl) logEl.textContent += '\\n\\nERROR: ' + emsg;
        if (lede) lede.textContent = 'The pipeline stopped before it could finish. ' + emsg;
        if (window.MH) MH.toast('Run failed: ' + emsg, 'error', 9000);
      }} else {{
        setStage('Something went wrong');
        if (lede) lede.textContent = rerunForm
          ? "We hit a snag finishing your recap. Your file is saved — run it again below; nothing you did was lost."
          : "We hit a snag finishing your recap. Please try uploading your file again — nothing you did was lost.";
        if (window.MH) MH.toast('Your recap could not be completed', 'error', 7000);
      }}
      return;
    }}
    if (status === 'unknown') {{
      showStuck(IS_DEV
        ? "This run isn't in memory or on disk any more (cleared, deleted, or a different deployment)."
        : "We can't find this run any more — it may have been cleared. Please upload your file again.");
      return;
    }}
    // queued / running — drive the determinate bar from the server's percent,
    // falling back to the indeterminate sweep until the first percent arrives.
    if (pct != null) {{ setBar(pct, null); }} else if (bar) {{ bar.classList.add('indeterminate'); }}
    setStage(phase || (IS_DEV ? (log[log.length - 1] || 'Starting…') : 'Working…'));
    if (waited > SOFT_CAP_MS && lede) {{
      lede.textContent = "Still working — large meets and personal-best lookups can take a little longer. This page updates automatically and opens your content the moment it's ready.";
    }}
    setTimeout(poll, waited > HARD_CAP_MS ? SLOW_MS : BASE_MS);
  }}
  poll();
}})();
</script>
"""
    return W._layout("Run progress", body, active="create")


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
def review(run_id, run_data):
    data = run_data
    meet = data.get("meet") or {}
    cards = data.get("cards") or []
    trust = data.get("trust") or {}
    warnings = data.get("parse_warnings") or []
    sc = data.get("self_check") or {}
    ds = data.get("detector_summary") or {}
    dispatch_log = data.get("dispatch_log") or {}
    rr = data.get("recognition_report") or {}
    recognition_error = data.get("recognition_error") or ""

    # G-10 — the bulk-bar review verbs come from the UI catalogue so
    # Welsh mode shows Welsh verbs (English for everything else).
    from mediahub.localize.ui_catalogue import t as _rv_t

    _rv_loc = W._ui_locale()

    # --- Hard pipeline failure (U.2 error state).
    # A run that failed terminally persists a top-level ``error`` and
    # usually has no meet/cards/recognition_report. Rendering the normal
    # review page for it showed a misleading "(unknown meet)" header and a
    # "No standout swims" empty state — implying the swimmers simply had no
    # good results, hiding that the file never processed. Surface the honest
    # reason instead (never a silent guess), with the parse notes that often
    # explain why and a clear path to re-run or delete.
    _run_err = (data.get("error") or "").strip()
    if _run_err:
        _file_disp = _h(
            data.get("file_name")
            or (data.get("dispatch_log") or {}).get("chosen_filename")
            or "your file"
        )
        # The persisted run.error is a raw str(e) that can carry absolute
        # server paths and exception internals. Only the signed-in operator
        # sees it verbatim; a customer gets an honest generic reason (the
        # "Common causes" note below stays for everyone). Mirrors the
        # is_dev gate run_status() already applies to the same detail.
        if W._auth.is_dev_operator():
            _err_detail_html = (
                '<p style="font-family:var(--font-mono);font-size:13px;color:var(--ink);'
                "background:var(--bad-bg);padding:12px 14px;border-radius:var(--radius-sm);"
                'white-space:pre-wrap;word-break:break-word">' + _h(_run_err) + "</p>"
            )
        else:
            _err_detail_html = (
                '<p style="font-size:13px;color:var(--ink);margin-top:0">The file couldn&rsquo;t '
                "be read into cards. This is almost always the results file itself &mdash; the "
                "common causes are below.</p>"
            )
        _err_body = f"""
<section class="mh-hero" data-lane="failed" style="padding-top:var(--sp-9);padding-bottom:var(--sp-8)">
  <span class="mh-hero-eyebrow">Processing failed</span>
  <h1>We couldn&rsquo;t finish processing this run</h1>
  <p class="lede">The pipeline started on <strong>{_file_disp}</strong> but stopped
    before it could produce any cards. Nothing was guessed &mdash; here&rsquo;s
    exactly what went wrong.</p>
  <div class="mh-hero-actions">
    <a class="mh-cta-primary" href="{url_for("upload")}">Try another file &rarr;</a>
    <a class="mh-cta-secondary" href="{url_for("activity_page")}">Back to runs</a>
  </div>
</section>
<div class="card" style="border-color:rgba(255,107,107,0.35);border-left:3px solid var(--bad)">
  <h2 style="margin-top:0">What went wrong</h2>
  {_err_detail_html}
  <p class="dim" style="font-size:13px;margin-bottom:0">Common causes: the file wasn&rsquo;t a
    readable results export, it was an entry list or heat sheet with no times, or no club was
    matched. Re-upload and check the file and the club you selected.</p>
</div>
{W._parse_notes_card(warnings)}
<div class="card" style="border-color:rgba(255,107,107,0.25);margin-top:var(--sp-6)">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap">
    <div>
      <h2 style="margin:0 0 2px 0;font-size:15px">Delete these results</h2>
      <p class="muted" style="margin:0;font-size:12px">Removes the failed run. Source files stay
        on disk and can be re-processed.</p>
    </div>
    <form method="post" action="{url_for("privacy_delete_run", run_id=run_id)}"
          onsubmit="return confirm('Delete these results permanently?')">
      <button class="btn danger" type="submit">Delete run</button>
    </form>
  </div>
</div>
"""
        return W._layout(f"Run failed — {meet.get('name') or run_id}", _err_body, active="home")

    # --- Header
    _gt_url = url_for("ground_truth", run_id=run_id)
    _export_url = url_for("api_export", run_id=run_id)
    _rec_json_url = url_for("api_recognition", run_id=run_id)
    _delete_url = url_for("privacy_delete_run", run_id=run_id)
    _status_url = url_for("api_status", run_id=run_id)
    _pack_url = url_for("content_pack", run_id=run_id)
    # Reel + Turn-Into generation now live on the Content builder (they are
    # content creation, which happens after approval). Review = triage only.

    # --- Results-from-a-link provenance (Step 8): a Source chip, an AI-read
    # marker for results read from the page by Tier C, and a one-click
    # re-fetch that stages a fresh run. Only appears for URL-sourced runs;
    # file uploads have no source_url sidecar so this stays empty.
    _provenance_card = ""
    _src_url = W._run_source_url(run_id)
    if _src_url:
        from urllib.parse import urlparse as _urlparse  # noqa: PLC0415

        _src_host = _urlparse(_src_url).hostname or _src_url
        _ai_note = ""
        _ai_sources = W._run_ai_read_sources(run_id)
        if _ai_sources:
            _n_tables = sum(int(s.get("tables") or 0) for s in _ai_sources)
            _confs = [float(s.get("confidence") or 0.0) for s in _ai_sources]
            _avg = (sum(_confs) / len(_confs)) if _confs else 0.0
            _ai_note = (
                '<div class="kv" style="margin-top:10px">'
                '<span class="k">AI-read</span><span>'
                '<span class="tag warn">AI-read from page</span> '
                f"{_n_tables} table{'' if _n_tables == 1 else 's'} on this run "
                f"{'was' if _n_tables == 1 else 'were'} read from the page by AI vision "
                f"(avg confidence {_avg:.0%}) and re-checked by the deterministic "
                "interpreter like any other input.</span></div>"
            )
        _refetch_block = ""
        if W._results_url_enabled():
            _refetch_js = (
                """
<script>
(function(){
  var b=document.getElementById('mh-refetch-btn');
  var s=document.getElementById('mh-refetch-status');
  if(!b) return;
  function show(m){ s.hidden=false; s.textContent=m; }
  function poll(jobId){
    var u='__STATUS_BASE__'.replace('JOBID',jobId);
    (function tick(){
      fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.json();}).then(function(j){
        if(j.status==='done'&&j.redirect){ show('Done - opening configure…'); window.location.href=j.redirect; return; }
        if(j.status==='error'){ b.disabled=false; show(j.error||'The re-fetch failed.'); return; }
        show(j.progress||'Reading the site…'); setTimeout(tick,1500);
      }).catch(function(){ setTimeout(tick,2500); });
    })();
  }
  b.addEventListener('click',function(){
    b.disabled=true; show('Starting…');
    fetch('__REFETCH_URL__',{method:'POST',headers:{'X-CSRF-Token':'__CSRF__','Accept':'application/json'}})
      .then(function(r){return r.text().then(function(t){var j=null;try{j=JSON.parse(t);}catch(e){}return {ok:r.ok,status:r.status,j:j};});})
      .then(function(res){ if(!res.j){throw new Error('The server returned an unexpected response ('+res.status+'). You may need to sign in again, or the deployment is briefly restarting - reload and try again.');} if(!res.ok||res.j.error){throw new Error(res.j.error||res.j.message||'Could not start the re-fetch.');} poll(res.j.job_id); })
      .catch(function(e){ b.disabled=false; show(e.message); });
  });
})();
</script>
""".replace("__REFETCH_URL__", url_for("run_refetch", run_id=run_id))
                .replace("__STATUS_BASE__", url_for("upload_from_url_status", job_id="JOBID"))
                .replace("__CSRF__", W._csrf_token())
            )
            _refetch_block = (
                '<div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
                '<button id="mh-refetch-btn" type="button" class="btn secondary">Re-fetch latest results &rarr;</button>'
                '<span id="mh-refetch-status" role="status" aria-live="polite" hidden '
                'class="muted" style="font-family:var(--font-mono);font-size:12px"></span>'
                "</div>"
                '<p class="muted" style="font-size:12px;margin-top:8px">'
                "Re-fetching reads the site again and stages a <b>new</b> run &mdash; "
                "this one is left untouched.</p>" + _refetch_js
            )
        _provenance_card = (
            '<div class="card">'
            '<div class="kv"><span class="k">Source</span><span>'
            f'<a href="{_h(_src_url)}" target="_blank" rel="noopener">{_h(str(_src_host))}</a>'
            "</span></div>" + _ai_note + _refetch_block + "</div>"
        )

    # --- V7: Workflow state
    _wf_summary = {}
    _wf_states = {}
    ws = W._get_wf_store()
    if ws is not None:
        _wf_summary = ws.summary(run_id)
        _wf_states = ws.load(run_id)

    # UI 1.18 — brand-locked swatches for the inspector palette, resolved
    # once per page from this run's brand kit (the same resolver the
    # create-graphic route uses). Best-effort: any failure yields an empty
    # palette section rather than breaking the review page.
    _review_swatches: list[dict] = []
    try:
        _insp_profile_id = data.get("profile_id") or data.get("club_filter") or ("_run_" + run_id)
        _insp_profile_id = re.sub(r"[^a-z0-9_-]", "-", str(_insp_profile_id).lower()).strip(
            "-"
        ) or ("_run_" + run_id)
        _review_swatches = W._brand_swatches(
            W._resolve_run_brand_kit(_insp_profile_id, run_id, data)
        )
    except Exception:
        _review_swatches = []

    # Workflow filter from query param. Triage states only — a malformed
    # or retired (`posted`) ``?wf=`` value falls back to "show all".
    # G-1: `rejected` is a first-class filter — bulk Reject puts cards in
    # that state, so the reviewer must be able to see (and re-queue) them.
    _wf_filter = (request.args.get("wf", "") or "").strip().lower()
    if _wf_filter not in ("", "queue", "approved", "rejected"):
        _wf_filter = ""

    # Post-promotion confirmation (?promoted=1 set by the redirect from
    # api_promote_swim). A fixed template — no user text rides in the URL.
    _promoted_flash = ""
    if (request.args.get("promoted") or "") == "1":
        _promoted_flash = (
            '<div class="tag good" style="display:block;padding:10px 12px;'
            'font-size:12px;margin:0 0 12px">Highlight created — the new card '
            "is in the review queue above. Approve it to send it to the "
            "Content builder.</div>"
        )

    # --- Recognition summary band
    n_elite = rr.get("n_elite", 0)
    n_strong = rr.get("n_strong", 0)
    n_story = rr.get("n_story", 0)
    n_total = rr.get("n_achievements", 0)
    n_analysed = rr.get("n_swims_analysed", data.get("our_swim_count", 0))
    n_cards = len(cards)
    # The headline figure is STANDOUT SWIMS — distinct swims whose best
    # band is elite/strong (plus human-promoted highlights), deduped
    # across the several achievements one race can emit. The raw
    # detection total stays in the trace JSON / machine-readable view;
    # showing it as the headline read absurdly high ("400 achievements"
    # when most swims were simply completed races).
    n_standout = W._n_standout_from_report(rr)

    # Recognition stats — semantic .stat variants tell the story:
    # medal = standout swims (the headline), live = strong (the working
    # set), plain = story / context counts.
    rec_stats_html = "".join(
        [
            f'<div class="stat medal"><div class="l">Standout swims</div><div class="v" data-mh-count="{n_standout}">{n_standout}</div></div>',
            f'<div class="stat"><div class="l">Elite</div><div class="v" data-mh-count="{n_elite}">{n_elite}</div></div>',
            f'<div class="stat live"><div class="l">Strong</div><div class="v" data-mh-count="{n_strong}">{n_strong}</div></div>',
            f'<div class="stat"><div class="l">Story</div><div class="v" data-mh-count="{n_story}">{n_story}</div></div>',
            f'<div class="stat"><div class="l">Swims analysed</div><div class="v" data-mh-count="{n_analysed}">{n_analysed}</div></div>',
            f'<div class="stat"><div class="l">Cards</div><div class="v" data-mh-count="{n_cards}">{n_cards}</div></div>',
        ]
    )

    # --- UI 1.30 "Weekend at a glance" digest (deterministic; no new LLM
    # call — surfaces the recognition report the pipeline already produced).
    # Fail-soft: a summary panel must never 500 the review page, so any
    # surprise in the run shape collapses to no panel rather than an error.
    try:
        weekend_glance_html = W._render_weekend_glance_html(W._build_weekend_glance(data))
    except Exception:
        # The builder is written to be total, but a summary panel must never
        # be the thing that 500s the review page — degrade to no panel.
        W.log.exception("weekend-glance: render failed for run %s", run_id)
        weekend_glance_html = ""

    # --- Meet context card
    mctx = rr.get("meet_context") or {}
    ctx_sources = mctx.get("research_sources") or []
    ctx_sources_html = ""
    if ctx_sources:
        ctx_sources_html = '<ul style="margin-top:6px;">'
        for s in ctx_sources[:5]:
            u = _h(s.get("url", ""))
            n = _h(s.get("name", s.get("url", "")))
            ctx_sources_html += f'<li><a href="{u}" target="_blank" rel="noopener">{n}</a></li>'
        ctx_sources_html += "</ul>"
    elif not mctx.get("research_available"):
        ctx_sources_html = '<p class="muted" style="font-size:12px">No external sources retrieved for this meet. Context derived from results file only.</p>'

    def ctx_badge(val):
        if val:
            return '<span class="tag good">yes</span>'
        return '<span class="tag">no</span>'

    meet_ctx_html = f"""
<div class="card">
  <h2>Meet context</h2>
  <div class="kv">
    <span class="k">Meet level</span><span><span class="tag info">{_h(mctx.get("meet_level", "open"))}</span></span>
    <span class="k">Governing body</span><span>{_h(mctx.get("governing_body") or "—")}</span>
    <span class="k">Has finals</span><span>{ctx_badge(mctx.get("has_finals"))}</span>
    <span class="k">Has age groups</span><span>{ctx_badge(mctx.get("has_age_groups"))}</span>
    <span class="k">Age groups</span><span class="muted">{_h(", ".join(mctx.get("age_groups") or []) or "—")}</span>
    <span class="k">Research</span><span>{'<span class="tag good">available</span>' if mctx.get("research_available") else '<span class="tag warn">unavailable</span>'}</span>
  </div>
  {('<div style="margin-top:10px"><span class="k">Sources</span>' + ctx_sources_html + "</div>") if ctx_sources_html else ""}
</div>"""

    # The ranked achievements drive the review list, built below as
    # ``ach_rows_html_wf`` (with its own empty/error states). An older
    # ``top_achs`` / ``ach_rows_html`` render of the same cards was orphaned
    # when the workflow list took over this surface — it built a string the
    # page never inserted — so it's removed here (dead-code sweep), leaving
    # one source of truth for the card render.
    ranked_achs = rr.get("ranked_achievements") or []
    # F11: a run-wide, index-aligned unique id per ranked achievement, so
    # two rows that share a swim_id get distinct per-(run_id, card_id)
    # workflow state instead of colliding. Computed once over the FULL list
    # (before any pagination/filter slice) so the ~n suffixes are stable.
    # Non-duplicate runs key exactly as before (first occurrence == bare
    # swim_id), so persisted workflow state still resolves.
    _card_ids = W._unique_card_ids(ranked_achs)

    # --- UI 1.6 · Animated results/data charts from this run's real data.
    # Two first-party build-on-scroll figures (web/charts.py): a quality-band
    # bar chart (how many Elite / Strong / Story moments the deterministic
    # detectors found) and a content-worthiness area curve (the ranker's
    # priority score across the top ranked achievements, strongest first).
    # Presentation-only over already-computed engine output — no new
    # judgement, no AI, nothing invented. Each chart renders only when it has
    # real data to draw; with neither, the whole card is omitted.
    _band_bars = []
    if n_elite:
        _band_bars.append({"label": "Elite", "value": n_elite, "tone": "gold"})
    if n_strong:
        _band_bars.append({"label": "Strong", "value": n_strong, "tone": "lane"})
    if n_story:
        _band_bars.append({"label": "Story", "value": n_story, "tone": "info"})
    _band_chart_html = ""
    if _band_bars:
        _band_chart_html = W._chart_card(
            "Detected &amp; ranked",
            "Moments by quality band",
            W._charts.bar_chart(
                _band_bars,
                caption="What the detectors found in this meet",
                chart_id=f"run-bands-{run_id}",
            ),
        )
    # Content-worthiness curve — the ranker's priority for each of the top
    # ranked achievements, strongest first (x = rank, implicit; left = best).
    _worth_pts = [
        {"label": "", "value": float(ra.get("priority", 0.0) or 0.0)} for ra in ranked_achs[:12]
    ]
    _worth_chart_html = ""
    if len(_worth_pts) >= 2:
        _worth_chart_html = W._chart_card(
            "Ranked by the engine",
            "Content-worthiness by rank",
            W._charts.area_chart(
                _worth_pts,
                caption="Ranker priority · strongest first",
                chart_id=f"run-worth-{run_id}",
            ),
        )
    if _band_chart_html or _worth_chart_html:
        meet_charts_html = (
            '<div class="card">'
            '<h2 style="margin-bottom:var(--sp-2)">Meet at a glance</h2>'
            '<p class="muted" style="margin-bottom:var(--sp-4);font-size:13px">'
            "Counts and rankings drawn straight from this run — no estimates.</p>"
            '<div class="mh-charts-grid">' + _band_chart_html + _worth_chart_html + "</div></div>"
        )
    else:
        meet_charts_html = ""

    # --- All swims — ranked (supersedes the old capped "Not generated"
    # panel). Every analysed swim gets a row: the deterministic tier
    # module (recognition.swim_tiers) joins the ranked achievements back
    # to their underlying swims, so standouts pin to the top, notable
    # swims follow by score, close calls are flagged in plain English,
    # and ordinary completed swims read honestly as just that. Any swim
    # the automation didn't flag carries a "Create highlight" form — the
    # human promotion path into the review queue + Content builder.
    swim_traces_raw = rr.get("swim_traces") or []
    no_ach_traces = [t for t in swim_traces_raw if t.get("achievement_count", 0) == 0]
    _n_close_calls = sum(
        1 for t in no_ach_traces if W._near_miss_is_close_call(t.get("near_miss_category"))
    )
    try:
        _swim_rows = W._swim_tiers.swim_rows_for_report(rr)
    except Exception:
        W.log.exception("all-swims: tier rows failed for run %s", run_id)
        _swim_rows = []

    # Within the close-call tier (every score is 0), lead with the most
    # reviewable near-misses (almost-a-PB before ambiguous-swimmer before
    # weak-field) — the same severity order the old panel used.
    def _nm_pos(r_):
        cat = (r_.get("near_miss_category") or "lower_priority").strip().lower()
        try:
            return W._NEAR_MISS_ORDER.index(cat)
        except ValueError:
            return len(W._NEAR_MISS_ORDER)

    _swim_rows = (
        [
            r_
            for r_ in _swim_rows
            if r_["tier"] in (W._swim_tiers.TIER_STANDOUT, W._swim_tiers.TIER_NOTABLE)
        ]
        + sorted(
            (r_ for r_ in _swim_rows if r_["tier"] == W._swim_tiers.TIER_CLOSE_CALL),
            key=_nm_pos,
        )
        + [r_ for r_ in _swim_rows if r_["tier"] == W._swim_tiers.TIER_ORDINARY]
    )
    _n_swim_standout = sum(1 for r_ in _swim_rows if r_["tier"] == W._swim_tiers.TIER_STANDOUT)
    # Swims the engine never analysed (DQ / no final time) — counted from
    # the run's own figures so the panel is honest about its coverage.
    _n_unanalysed = max(0, int(data.get("our_swim_count") or 0) - len(swim_traces_raw))
    _TIER_TAG_CLS = {
        W._swim_tiers.TIER_STANDOUT: "good",
        W._swim_tiers.TIER_NOTABLE: "info",
        W._swim_tiers.TIER_CLOSE_CALL: "warn",
        W._swim_tiers.TIER_ORDINARY: "",
    }
    _promote_url = url_for("api_promote_swim", run_id=run_id)
    all_swims_rows = ""
    for _sr in _swim_rows:
        _tier = _sr["tier"]
        _tag_cls = _TIER_TAG_CLS.get(_tier, "")
        _ranked_here = _sr["ranked"]
        if _ranked_here:
            # What the engine (or a human promotion) found for this swim,
            # verbatim from the ranked achievements — no new copy.
            _kinds = " · ".join(
                W._humanise((ra.get("achievement") or {}).get("type", ""))
                for ra in _ranked_here[:3]
            )
            _best_headline = str(
                ((_ranked_here[0].get("achievement") or {}).get("headline") or "")
            ).strip()
            _why_cell = (
                f'<span class="tag {_tag_cls}" style="font-size:10px">{_h(_sr["tier_label"])}</span> '
                f'<span class="tag" style="font-size:10px">{_h(_kinds)}</span>'
                + (
                    f'<div style="font-size:12px;color:var(--ink-dim);margin-top:3px">{_h(_best_headline[:140])}</div>'
                    if _best_headline
                    else ""
                )
                + '<div class="muted" style="font-size:11px;margin-top:3px">Card in the review list above.</div>'
            )
            _score_cell = W._worthiness_meter(_sr["score"])
        else:
            _cat = (_sr.get("near_miss_category") or "lower_priority").strip().lower()
            _nm_label, _nm_blurb = W._near_miss_label(_cat)
            _raw = (_sr.get("summary") or "").strip()
            _raw_line = (
                f'<div class="muted" style="font-size:11px;margin-top:3px" '
                f'title="{_h(_raw)}">{_h(_raw[:120])}</div>'
                if _raw
                else ""
            )
            _why_cell = (
                f'<span class="tag {_tag_cls}" style="font-size:10px">'
                f"{_h(_nm_label if _sr['close_call'] else _sr['tier_label'])}</span>"
                f'<div style="font-size:12px;color:var(--ink-dim);margin-top:3px">{_h(_nm_blurb if _sr["close_call"] else "Completed race — nothing the detectors rank, and that is fine.")}</div>'
                f"{_raw_line}"
            )
            _score_cell = '<span class="muted" style="font-size:11px">—</span>'
        _action_cell = ""
        if _sr["promotable"]:
            # No-JS friendly inline promotion form. The headline is
            # optional — left blank, a deterministic fact-only template
            # over the swim's own row is used. Never auto-approved: the
            # new card lands in the review queue like any other.
            _action_cell = f"""<details class="mh-promote">
  <summary class="btn secondary" style="font-size:11px;padding:4px 10px;display:inline-flex;cursor:pointer" title="Create a custom highlight card for this swim — it joins the review queue, then the Content builder once you approve it.">&#x2606; Create highlight</summary>
  <form method="post" action="{_promote_url}" style="margin-top:8px;display:flex;flex-direction:column;gap:6px;max-width:340px">
    <input type="hidden" name="swim_id" value="{_h(_sr["swim_id"])}">
    <input class="input" type="text" name="headline" maxlength="140" placeholder="Headline (optional — facts are used if blank)" style="font-size:12px">
    <input class="input" type="text" name="note" maxlength="200" placeholder="Why does this swim matter? (optional)" style="font-size:12px">
    <button class="btn" type="submit" style="font-size:12px;align-self:flex-start">Create highlight card</button>
  </form>
</details>"""
        all_swims_rows += (
            f'<tr data-swimmer="{_h(_sr["swimmer_name"])}" data-event="{_h(_sr["event"])}" '
            f'data-tier="{_h(_tier)}" data-score="{_sr["score"]:.4f}">'
            f"<td>{_h(_sr['swimmer_name'])}</td>"
            f"<td>{_h(_sr['event'])}</td>"
            f'<td style="font-family:monospace">{_h(_sr["time_str"])}</td>'
            f"<td>{_score_cell}</td>"
            f"<td>{_why_cell}</td>"
            f"<td>{_action_cell}</td>"
            f"</tr>"
        )
    if _n_unanalysed:
        all_swims_rows += (
            '<tr><td colspan="6" class="muted" '
            'style="font-size:12px;text-align:center;padding:12px">'
            f"{_n_unanalysed} swim{'' if _n_unanalysed == 1 else 's'} "
            "not analysed (DQ or no final time) &mdash; see Browse all results."
            "</td></tr>"
        )

    # --- Legacy V4 cards (collapsed)
    # ``card_id`` is canonically present on every card / trust entry,
    # but an old or hand-edited run JSON might omit it. Use .get()
    # so a malformed card doesn't 500 the entire Review page.
    tcards = {t.get("card_id", ""): t for t in trust.get("cards", []) if t.get("card_id")}
    v4_rows = []
    for c in cards:
        t = tcards.get(c.get("card_id", ""), {})
        conf = t.get("confidence", "medium")
        safe = t.get("safe_to_post", "review")
        badge = {"high": "good", "medium": "warn", "low": "bad"}.get(conf, "")
        safe_badge = {"post": "good", "review": "warn", "hold": "bad"}.get(safe, "")
        sources_str = ", ".join(s.get("name", "") for s in (t.get("sources") or [])[:3])
        v4_rows.append(
            f'<tr><td><span class="tag info">{_h(W._humanise(c.get("card_type", "")))}</span><br>'
            f"<strong>{_h((c.get('headline') or '')[:80])}</strong>"
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
            f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px">{_h(W._humanise(c.get("card_type", "")))}</div>'
            f'<strong style="font-size:13px">{_h(c.get("headline", ""))}</strong>'
            f'<div class="dim" style="margin-top:4px;font-size:12px">{_h(c.get("subhead", ""))}</div>'
            f'<div class="grid-3" style="margin-top:10px;gap:10px">'
            f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Clean</div><div style="font-size:12px">{_h(cap.get("clean") or "—")}</div></div>'
            f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Team</div><div style="font-size:12px">{_h(cap.get("team") or "—")}</div></div>'
            f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Hype</div><div style="font-size:12px">{_h(cap.get("hype") or "—")}</div></div>'
            f"</div></div>"
        )

    # Parse notes — the flag-for-review surface (U.2). Humanised codes,
    # error-severity flags led out, "+N more" when truncated. See helper.
    warn_html = W._parse_notes_card(warnings)

    # --- V6 PB Audit panel
    pb_audit_data = data.get("pb_audit") or {}
    pb_audit_html = ""
    if pb_audit_data:
        _audit_url = url_for("pb_audit_page", run_id=run_id)
        _n_swimmers = pb_audit_data.get("swimmers_total", 0)
        _n_verified = pb_audit_data.get("swimmers_matched_verified", 0)
        _n_needs = pb_audit_data.get("swimmers_needs_verification", 0)
        _n_fetch_fail = pb_audit_data.get("swimmers_fetch_failed", 0)
        _n_no_history = pb_audit_data.get("swimmers_no_history", 0)
        _n_decisions = pb_audit_data.get("pb_decisions_count", 0)
        _n_confirmed = pb_audit_data.get("pb_confirmed_count", 0)
        _n_official = pb_audit_data.get("pb_confirmed_official_count", 0)
        _n_matched = pb_audit_data.get("pb_matched_count", 0)
        _n_likely = pb_audit_data.get("pb_likely_count", 0)
        _n_not_pb = pb_audit_data.get("pb_not_pb_count", 0)
        _n_unverified = pb_audit_data.get("pb_unverified_count", 0)
        _n_suppressed = pb_audit_data.get("pb_suppressed_count", 0)
        _fetch_secs = pb_audit_data.get("fetch_total_seconds", 0)
        _cache_hits = pb_audit_data.get("cache_hits", 0)
        _cache_misses = pb_audit_data.get("cache_misses", 0)
        _budget_exceeded = pb_audit_data.get("fetch_budget_exceeded", False)

        # Needs-verification swimmers list
        _needs_verif_html = ""
        _needs_verif_swimmers = [
            sa
            for sa in (pb_audit_data.get("per_swimmer") or [])
            if (sa.get("identity") or {}).get("method") == "needs_verification"
        ]
        if _needs_verif_swimmers:
            rows = ""
            for sa in _needs_verif_swimmers[:10]:
                _sw_key = _h(sa.get("asa_id") or f"name:{sa.get('hy3_name', '')}")
                _hy3 = _h(sa.get("hy3_name", ""))
                _sr = _h(sa.get("sr_name") or "—")
                _asa = _h(sa.get("asa_id") or "?")
                _verify_url = url_for("pb_verify_form", run_id=run_id, swimmer_key=_sw_key)
                rows += (
                    f'<div style="padding:8px 0;border-bottom:1px solid var(--border)">'
                    f'<a class="btn secondary" style="font-size:11px;padding:4px 8px;margin-right:8px" href="{_verify_url}">Verify</a>'
                    f'<strong>{_hy3}</strong> <span class="muted">(id {_asa})</span>'
                    f'<div class="muted" style="font-size:12px;margin-top:2px">SR returned: "{_sr}" &rarr; canonical mismatch</div>'
                    f"</div>"
                )
            _needs_verif_html = (
                f'<div class="divider"></div>'
                f'<div><strong style="color:var(--warn)">&#x26A0; {_n_needs} swimmer{"s" if _n_needs != 1 else ""} need verification:</strong>'
                f"{rows}</div>"
            )

        _budget_note = ' <span class="tag warn">budget exceeded</span>' if _budget_exceeded else ""
        # When EVERY lookup failed (none completed, none found history), the
        # cause is almost always that the deployment can't reach a web-search
        # backend to find ranking history — make that actionable instead of
        # leaving the operator staring at "Lookups failed: N".
        _pb_lookup_diag = ""
        if _n_swimmers > 0 and _n_fetch_fail >= _n_swimmers and _n_no_history == 0:
            _pb_lookup_diag = (
                '<div class="divider"></div>'
                '<p class="dim" style="color:var(--warn);font-size:13px;line-height:1.5">'
                "&#x26A0; <strong>Every PB lookup failed.</strong> The engine couldn&rsquo;t "
                "reach a web-search backend to find swimmers&rsquo; ranking history, so no PB "
                "could be confirmed (they show as &ldquo;possible &mdash; unconfirmed&rdquo;). "
                "On a hosted server the default DuckDuckGo path is usually blocked from the "
                "server&rsquo;s IP &mdash; set <code>MEDIAHUB_SEARCH_ENDPOINT</code> to a "
                "reachable SearXNG instance to enable PB confirmation.</p>"
            )
        pb_audit_html = f"""
<div class="card">
  <h2>PB Audit</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Swimmers</div><div class="v">{_n_swimmers}</div></div>
    <div class="stat live"><div class="l">Verified</div><div class="v">{_n_verified}</div></div>
    <div class="stat warn"><div class="l">Needs verification</div><div class="v">{_n_needs}</div></div>
    <div class="stat" title="The lookup itself failed (search or page fetch) &mdash; distinct from swimmers who simply have no online history"><div class="l">Lookups failed</div><div class="v">{_n_fetch_fail}</div></div>
    <div class="stat" title="Lookup completed but found no verifiable online history for these swimmers"><div class="l">No online history</div><div class="v">{_n_no_history}</div></div>
    <div class="stat"><div class="l">PB decisions</div><div class="v">{_n_decisions}</div></div>
    <div class="stat good"><div class="l">Confirmed PBs</div><div class="v">{_n_confirmed}</div></div>
    <div class="stat live" title="Time + date match SR all-time PB &mdash; strongest possible confirmation"><div class="l">Official PBs</div><div class="v">{_n_official}</div></div>
    <div class="stat"><div class="l">Likely PBs</div><div class="v">{_n_likely}</div></div>
    <div class="stat"><div class="l">Not PB</div><div class="v">{_n_not_pb}</div></div>
    <div class="stat"><div class="l">Unverified</div><div class="v">{_n_unverified}</div></div>
    <div class="stat"><div class="l">Suppressed</div><div class="v">{_n_suppressed}</div></div>
    <div class="stat"><div class="l">Fetch time</div><div class="v">{_fetch_secs:.1f}s{_budget_note}</div></div>
    <div class="stat"><div class="l">Cache hits/misses</div><div class="v">{_cache_hits}/{_cache_misses}</div></div>
  </div>
  {_pb_lookup_diag}
  {_needs_verif_html}
  <div class="divider"></div>
  <a class="btn secondary" href="{_audit_url}">Show all per-swimmer audits &#x25BE;</a>
</div>"""
    elif data.get("pb_fetch_ok") and data.get("pb_fetch_ok") > 0 and not data.get("pb_audit"):
        # Run did some PB fetching but produced no audit (legacy mode path).
        # Offer a direct re-run link so the volunteer can act on the warning.
        _has_input = (W.RUNS_DIR / run_id / "input.bin").exists()
        _rerun_url = url_for("upload_configure", run_id=run_id) if _has_input else url_for("upload")
        _rerun_label = "Re-run this meet" if _has_input else "Re-upload with PB fetching"
        pb_audit_html = (
            '<div class="card">'
            '<p class="muted" style="margin-bottom:var(--sp-3)">'
            "PB data was fetched but the full per-swimmer audit wasn&#x2019;t saved. "
            "Re-running the meet will generate the complete PB audit."
            "</p>"
            f'<a class="btn secondary" href="{_rerun_url}">{_rerun_label} &rarr;</a>'
            "</div>"
        )

    # Sources panel
    all_sources = rr.get("all_sources") or []
    sources_rows = ""
    for s in all_sources[:20]:
        u = _h(s.get("url", ""))
        n = _h(s.get("name", s.get("url", "")))
        uf = _h(s.get("used_for", ""))
        fa = _h((s.get("fetched_at") or "")[:16])
        sources_rows += f'<tr><td><a href="{u}" target="_blank" rel="noopener">{n}</a></td><td class="muted" style="font-size:12px">{uf}</td><td class="muted" style="font-size:12px">{fa}</td></tr>'

    if not sources_rows:
        sources_rows = '<tr><td colspan="3" class="muted">No external sources used (research unavailable or not yet run).</td></tr>'

    # Build filter dropdowns from unique values
    swimmers_set = sorted(
        set(
            ra.get("achievement", {}).get("swimmer_name", "")
            for ra in ranked_achs
            if ra.get("achievement")
        )
    )
    events_set = sorted(
        set(
            ra.get("achievement", {}).get("event", "")
            for ra in ranked_achs
            if ra.get("achievement")
        )
    )
    types_set = sorted(
        set(
            ra.get("achievement", {}).get("type", "") for ra in ranked_achs if ra.get("achievement")
        )
    )
    bands_set = ["elite", "strong", "story", "nice", "not_worthy"]
    post_types_set = sorted(set(ra.get("suggested_post_type", "") for ra in ranked_achs))

    # UI2.2: per-swimmer aggregate for the athlete-avatar tooltip — how many
    # ranked moments this swimmer earned in *this* meet and their best band.
    # Every figure is read straight from the recognition report (grounded,
    # never fabricated); hovering any of a swimmer's rows surfaces their haul.
    _BAND_RANK = {"elite": 4, "strong": 3, "story": 2, "nice": 1, "not_worthy": 0}
    _sw_agg: dict[str, dict] = {}
    for _ra in ranked_achs:
        _aa = _ra.get("achievement", {}) or {}
        _key = _aa.get("swimmer_name", "") or _aa.get("swimmer_id", "")
        if not _key:
            continue
        _band = _ra.get("quality_band") or "nice"
        _rec = _sw_agg.setdefault(_key, {"count": 0, "band": "nice"})
        _rec["count"] += 1
        if _BAND_RANK.get(_band, 0) > _BAND_RANK.get(_rec["band"], 0):
            _rec["band"] = _band
    _run_club = (data.get("profile_display") or data.get("club_filter") or "").strip()

    def _athlete_stat(swimmer_name: str) -> str:
        agg = _sw_agg.get(swimmer_name) or {}
        n = agg.get("count", 0)
        if not n:
            return ""
        s = f"{n} moment{'s' if n != 1 else ''}"
        best = agg.get("band") or ""
        if best:
            s += f" · best {best}"
        return s

    # F-2: map the engine's raw enums to display labels in the filters —
    # every other part of the page is humanised, so "not_worthy" /
    # "medal_gold" / "main_feed" with underscores read as a leak. The
    # <option value> keeps the raw enum (the JS filter matches on it); only
    # the visible label is humanised.
    _BAND_SHORT = {
        "elite": "Elite",
        "strong": "Strong",
        "story": "Story",
        "nice": "Nice",
        "not_worthy": "Below the bar",
    }
    _ACH_TYPE_LABELS = {
        "medal_gold": "Gold medal",
        "medal_silver": "Silver medal",
        "medal_bronze": "Bronze medal",
        "top_of_field_top_3": "Top-3 finish",
        "pb_confirmed": "Personal best",
        "pb_probable": "Likely personal best",
        "first_time": "First-time swim",
        "season_best": "Season best",
    }
    _POST_TYPE_LABELS = {
        "main_feed": "Feed post",
        "feed": "Feed post",
        "story": "Story",
        "stories": "Story",
        "reel": "Reel",
        "spotlight": "Athlete spotlight",
        "meet_recap": "Meet recap",
    }

    def _humanise_enum(v: str) -> str:
        return (v or "").replace("_", " ").replace("-", " ").strip().title() or (v or "")

    def opts(items, label, labels=None):
        o = f'<option value="">All {label}</option>'
        for item in items:
            disp = (labels or {}).get(item) or _humanise_enum(item)
            o += f'<option value="{_h(item)}">{_h(disp)}</option>'
        return o

    # --- V7: build workflow summary card (triage counts)
    _wf_n_approved = _wf_summary.get("approved", 0)
    _wf_n_rejected = _wf_summary.get("rejected", 0)
    _wf_n_total = _wf_summary.get("total", 0)

    # UI2.4 — the filter tab badges + the stat block count from the ACTUAL
    # rendered cards (each defaults to "queue" with no sidecar state), so
    # they match the DOM and the live JS recount on first paint. The bare
    # sidecar summary is empty until the first action, which would otherwise
    # read "Queue 0" beside a full queue. (The progress strip below keeps its
    # own store-summary "decided / ranked-total" maths — a separate concept
    # with its own regression guard.)
    _wf_card_counts: dict[str, int] = {}
    # J-3: the FULL queued-id list, embedded in the page for "Approve all
    # in queue" — with server-side pagination the DOM only holds one page
    # of rows, so the bulk approve must not scrape it.
    _queued_card_ids: list[str] = []
    _seen_queue_base: set[str] = set()
    for _idx, _ra in enumerate(ranked_achs):
        _cid = _card_ids[_idx]
        _cst = _wf_states.get(_cid)
        _cst_val = _cst.status.value if _cst else "queue"
        _wf_card_counts[_cst_val] = _wf_card_counts.get(_cst_val, 0) + 1
        if _cst_val == "queue" and _cid:
            # F11: "Approve all in queue" posts each id to the BULK route,
            # whose consent / brand-lock / task gates resolve the card via
            # find_card_in_run — which only knows the base swim_id. Emit the
            # base id (deduped) so a consent-blocked duplicate twin can never
            # slip past those gates in bulk; the twin's own ~n state stays
            # individually approvable on its row (that path is base-gated
            # here in web.py). For a non-duplicate run this is the bare
            # swim_id, so the list is unchanged.
            _qbase = W._base_card_id(str(_cid))
            if _qbase not in _seen_queue_base:
                _seen_queue_base.add(_qbase)
                _queued_card_ids.append(_qbase)
    _n_queue_cards = _wf_card_counts.get("queue", 0)
    _n_approved_cards = _wf_card_counts.get("approved", 0)
    _n_rejected_cards = _wf_card_counts.get("rejected", 0)

    # Only show workflow card if there's any state or any achievements
    if _wf_summary or ranked_achs:
        _review_base = url_for("review", run_id=run_id)
        _wf_filter_buttons = ""
        _wf_counts = {
            "": len(ranked_achs) or _wf_n_total,
            "queue": _n_queue_cards,
            "approved": _n_approved_cards,
            "rejected": _n_rejected_cards,
        }
        # UI2.4 — the filter is a client-side tab control (kit `.mh-tabs`
        # sliding indicator): switching shows/hides cards in place with no
        # full reload. Each tab keeps its `?wf=` href so a no-JS page (or a
        # deep-link) still filters server-side via `#ach-list[data-wf-filter]`.
        # The count spans always render (even at 0) with stable ids so the
        # live recount can update them as cards are approved/re-queued.
        _wf_tab_count_id = {
            "": "mh-wf-tabcount-all",
            "queue": "mh-wf-tabcount-queue",
            "approved": "mh-wf-tabcount-approved",
            "rejected": "mh-wf-tabcount-rejected",
        }
        for _wf_opt in [
            ("", "All"),
            ("queue", "Queue"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ]:
            _wf_is_on = _wf_filter == _wf_opt[0]
            _wf_opt_url = _review_base + (f"?wf={_wf_opt[0]}" if _wf_opt[0] else "")
            _wf_btn_cls = " is-active" if _wf_is_on else ""
            _wf_count_for_opt = _wf_counts.get(_wf_opt[0], 0)
            _wf_filter_buttons += (
                f'<a role="tab" class="{_wf_btn_cls.strip()}" href="{_wf_opt_url}" '
                f'data-wf-filter-to="{_wf_opt[0]}" '
                f'aria-selected="{"true" if _wf_is_on else "false"}">'
                f"{_wf_opt[1]}"
                f'<span class="count" id="{_wf_tab_count_id[_wf_opt[0]]}">{_wf_count_for_opt}</span>'
                f"</a>"
            )
        # Progress maths — how much of the queue has the user actioned?
        # Denominator is the ranked total (not the store total, which only
        # counts touched cards); regression-guarded in test_review_body_content.
        _wf_decided = (_wf_n_approved or 0) + (_wf_n_rejected or 0)
        _wf_grand_total = len(ranked_achs) or _wf_n_total or 0
        _wf_pct = int(round(100 * _wf_decided / _wf_grand_total)) if _wf_grand_total else 0
        # Only show bulk-approve when cards remain unreviewed; hide at 100%.
        _bulk_approve_btn = (
            '<button type="button" class="btn secondary" id="mh-bulk-approve"'
            ' title="Approve every card currently shown in the queue">'
            "Approve all in queue</button>"
            if _wf_pct < 100
            else ""
        )

        workflow_summary_card = f"""
<div class="card" style="border-left:3px solid var(--accent);display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
  <div style="flex:1;min-width:min(240px,100%)">
    <h2 style="margin-bottom:6px">Review &amp; approve all achievements</h2>
    <p class="dim" style="margin:0;font-size:13px;max-width:560px">
      Approve the achievements you want to post — anything you skip simply
      stays in the queue. Approved cards flow into the
      <strong>Content builder</strong>, where you pick a caption, create graphics
      and video, then schedule or download. Nothing is created until
      you&rsquo;ve approved it. Want one swimmer&rsquo;s story instead? Switch to
      <strong>Athlete spotlight</strong> above.
    </p>
  </div>
</div>
<div class="mh-progress-strip" role="group" aria-label="Review progress" id="mh-review-progress" data-wf-total="{_wf_grand_total}" data-wf-base-queue="{_n_queue_cards}" data-wf-base-approved="{_n_approved_cards}" data-wf-base-rejected="{_n_rejected_cards}">
  <span class="mh-progress-strip-label">Reviewed</span>
  <span class="mh-progress-strip-value" id="mh-wf-value">{_wf_decided}<span class="total">/ {_wf_grand_total}</span></span>
  <span class="mh-progress-strip-bar"><span id="mh-wf-bar" style="width:{_wf_pct}%"></span></span>
  <span id="mh-wf-pct" class="mh-progress-strip-label">{_wf_pct}%</span>
</div>
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
    <div>
      <h2 style="margin-bottom:var(--sp-3)">Workflow</h2>
      <div class="stat-block">
        <div class="stat"><div class="l">Queue</div><div class="v" id="mh-wf-n-queue">{_n_queue_cards}</div></div>
        <div class="stat good"><div class="l">Approved</div><div class="v" id="mh-wf-n-approved">{_n_approved_cards}</div></div>
        <div class="stat bad"><div class="l">Rejected</div><div class="v" id="mh-wf-n-rejected">{_n_rejected_cards}</div></div>
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      {_bulk_approve_btn}
      <a class="btn" href="{_pack_url}" style="align-self:flex-end">Open content builder &rarr;</a>
      <!-- The finished output in one click: every generated graphic + caption
           for this run, zipped. If nothing's been built yet it lands on a
           friendly "open the content builder" page, not an empty file. -->
      <a class="btn secondary" href="{url_for("content_pack_zip", run_id=run_id)}" style="align-self:flex-end">Download content pack (.zip)</a>
    </div>
  </div>
  <div style="margin-top:14px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
    <span class="muted" style="font-size:12px;font-family:var(--font-mono);letter-spacing:0.14em;text-transform:uppercase">Filter</span>
    <nav class="mh-tabs" role="tablist" aria-label="Filter cards by workflow status">
      {_wf_filter_buttons}
      <span class="mh-tabs__ind" aria-hidden="true"></span>
    </nav>
    <span class="mh-kbd-hint" aria-hidden="true">
      <kbd>J</kbd><kbd>K</kbd> move · <kbd>A</kbd> approve · <kbd>?</kbd> help
    </span>
  </div>
</div>"""
    else:
        workflow_summary_card = ""

    # --- The review list: one card per ranked achievement, with the
    # workflow status pill and the U.3 confidence / worthiness / "why this
    # card" / factor-breakdown surfaces. This is the only card render that
    # reaches the page (`#ach-list`).
    # UI 1.25 — tally every card's emoji reactions in one indexed query so
    # the per-card strips render server-side without a round-trip each.
    _react_counts = W._reaction_counts_for_run(run_id)

    # J-3: server-side pagination, 25 rank-ordered cards per page. A
    # 249-card meet used to render every row into one ~70,000px page and
    # the thumbnail loader (2 concurrent, 6 retries) permanently gave up
    # on deep rows with "Renderer busy". Tab counts, the stat block and
    # the progress strip above are all computed from the FULL run state;
    # only the rendered rows are sliced. Runs of 25 cards or fewer render
    # exactly as before (single page, no pager).
    _REVIEW_PAGE_SIZE = 25
    # SRV-1: pages are sliced from the cards MATCHING the active workflow
    # filter (tab badges stay full-run counts). Slicing the unfiltered
    # list meant a filtered multi-page run rendered mostly-empty pages
    # whose matching cards lived elsewhere. Each entry keeps its full-list
    # index so the lazy why-card URLs stay stable under filtering.
    _indexed_achs = list(enumerate(ranked_achs))
    if _wf_filter:

        def _row_wf_status(_i: int) -> str:
            # Key on the same run-wide deduped id the row + counts use, so
            # filtering agrees with the tab badges for duplicate swim_ids.
            _cst = _wf_states.get(_card_ids[_i])
            return _cst.status.value if _cst else "queue"

        _indexed_achs = [(_i, _ra) for _i, _ra in _indexed_achs if _row_wf_status(_i) == _wf_filter]
    try:
        _pg = int(request.args.get("page", "1") or "1")
    except (TypeError, ValueError):
        _pg = 1
    _n_pages = max(1, -(-len(_indexed_achs) // _REVIEW_PAGE_SIZE))
    _pg = min(max(1, _pg), _n_pages)
    _pg_start = (_pg - 1) * _REVIEW_PAGE_SIZE

    def _review_page_url(p: int) -> str:
        _q: dict = {}
        if _wf_filter:
            _q["wf"] = _wf_filter
        if p > 1:
            _q["page"] = p
        return url_for("review", run_id=run_id, **_q)

    _pager_html = ""
    if _n_pages > 1:
        _pg_btn_css = "font-size:12px;padding:6px 14px"
        _prev_html = (
            f'<a class="btn secondary" href="{_review_page_url(_pg - 1)}" '
            f'rel="prev" style="{_pg_btn_css}">&larr; Prev</a>'
            if _pg > 1
            else f'<span class="btn secondary" aria-disabled="true" '
            f'style="{_pg_btn_css};opacity:0.4;pointer-events:none">&larr; Prev</span>'
        )
        _next_html = (
            f'<a class="btn secondary" href="{_review_page_url(_pg + 1)}" '
            f'rel="next" style="{_pg_btn_css}">Next &rarr;</a>'
            if _pg < _n_pages
            else f'<span class="btn secondary" aria-disabled="true" '
            f'style="{_pg_btn_css};opacity:0.4;pointer-events:none">Next &rarr;</span>'
        )
        _pg_lo = _pg_start + 1
        _pg_hi = min(_pg_start + _REVIEW_PAGE_SIZE, len(_indexed_achs))
        # Say what the count counts when a filter narrows the pages.
        _pg_noun = {
            "queue": " in the queue",
            "approved": " approved",
            "rejected": " rejected",
        }.get(_wf_filter, "")
        _pager_html = (
            '<nav class="mh-review-pager" aria-label="Review pages" '
            'style="display:flex;align-items:center;justify-content:center;'
            'gap:14px;flex-wrap:wrap;margin:14px 0">'
            f"{_prev_html}"
            f'<span class="muted" style="font-size:12px;font-family:var(--font-mono)">'
            f"Page {_pg} of {_n_pages} &middot; cards {_pg_lo}&ndash;{_pg_hi} "
            f"of {len(_indexed_achs)}{_pg_noun}</span>"
            f"{_next_html}"
            "</nav>"
        )

    ach_rows_html_wf = ""
    for _why_idx, ra in _indexed_achs[_pg_start : _pg_start + _REVIEW_PAGE_SIZE]:
        a = ra.get("achievement", {})
        band = ra.get("quality_band", "nice")
        prio = ra.get("priority", 0.0)
        rank = ra.get("rank", 0)
        conf_label = a.get("confidence_label", "medium")
        swimmer = _h(a.get("swimmer_name", ""))
        event = _h(a.get("event", ""))
        headline = _h(a.get("headline", ""))
        atype = _h(W._humanise(a.get("type", "")))
        post_type = _h(ra.get("suggested_post_type", ""))
        _trace_url = url_for("api_swim_trace", run_id=run_id, swim_id=a.get("swim_id", "x"))

        # V7: workflow state for this card.
        # F11: ``card_id_raw`` is this row's UNIQUE identity (the ~n-deduped
        # id) — it keys the workflow state (approve/reject/caption-edit via
        # the in-app /api/workflow route, which base-gates consent),
        # reactions, the row's DOM id and the inspector's data-card-id, so a
        # duplicate swim_id's twin decides independently. ``_render_card_id``
        # is the bare swim_id, used for (a) the render/preview routes
        # (graphic/caption/thumb, resolved against the shared recognition
        # report) so the twin still resolves, and (b) the bulk-select
        # checkbox, whose ids flow to the BULK approve route whose consent
        # gate resolves on the base swim_id — emitting a ~n id there would
        # let a consent-blocked twin slip past. For a non-duplicate row the
        # two ids are identical, so every URL + attribute is byte-identical
        # to before.
        card_id_raw = _card_ids[_why_idx]
        _render_card_id = a.get("swim_id", "")
        wf_state = _wf_states.get(card_id_raw)
        wf_status = wf_state.status.value if wf_state else "queue"

        # UI2.4 — every card is rendered into the DOM regardless of the
        # active filter; the Queue/Approved tabs hide/show them client-side
        # (CSS on `#ach-list[data-wf-filter]`) so switching needs no reload
        # and a card leaving the queue on approval drops out of the Queue
        # view live. The no-JS / deep-link path still filters server-side via
        # the same `data-wf-filter` attribute set from `?wf=` below.

        # Evidence list
        ev_html = ""
        for ev in (a.get("evidence") or [])[:3]:
            ev_url = ev.get("source_url") or ""
            ev_src = _h(ev.get("source_name", ""))
            ev_stmt = _h(ev.get("statement", ""))
            if ev_url:
                ev_html += f'<li><a href="{_h(ev_url)}" target="_blank" rel="noopener">{ev_src}</a>: {ev_stmt}</li>'
            else:
                ev_html += f"<li><strong>{ev_src}</strong>: {ev_stmt}</li>"

        # Caption tone, graphics, motion + scheduling all move to the
        # Content builder (post-approval). Review stays pure triage:
        # Approve / Reject only. `card_uuid` is still needed below for
        # the "Why this card?" anchor + filter data attributes.
        card_uuid = W._dom_card_uuid(card_id_raw)

        # V9: "Why this card?" &mdash; plain-English, source-grounded reasoning.
        # Lazy: a 150+ card meet would otherwise fire 300+ blocking LLM
        # calls during this render. Each card's reasoning streams in via
        # api_why_card once it scrolls into view.
        why_html = W._render_why_this_card(
            ra, card_uuid=f"wf-{card_uuid}", run_id=run_id, ach_index=_why_idx, lazy=True
        )

        # UI 1.18 — per-card "Inspect" affordance. Opens the shared
        # inspector drawer (one instance, injected once below) wired to the
        # existing create-graphic + live-caption + workflow routes for THIS
        # card via the data-* attributes. Lightweight: no markup is rendered
        # per card beyond the button itself.
        _insp_graphic_url = url_for("api_create_graphic", run_id=run_id, card_id=_render_card_id)
        _insp_caption_url = url_for("api_live_caption", run_id=run_id, swim_id=_render_card_id)
        # M29 (UX-1) — see before approve: a lazy, cached thumbnail of the
        # card's actual graphic. The <img> stays empty until it scrolls
        # into view (IntersectionObserver script below), then loads from
        # the thumb route — an existing render is served as-is; a first
        # render happens once and is cached per card.
        _thumb_url = url_for("api_card_thumb", run_id=run_id, card_id=_render_card_id)
        # UI2.2: athlete avatar + hover tooltip (name · club · meet haul).
        # Decorative here — the row already shows the name/event/band as
        # text — so the chip stays aria-hidden and out of the tab order.
        _sw_key = a.get("swimmer_name", "") or a.get("swimmer_id", "")
        _row_avatar = W._athlete_avatar(
            a.get("swimmer_name", ""),
            club=_run_club,
            stat=_athlete_stat(_sw_key),
            focusable=False,
            size=30,
        )

        # H-10: a saved caption is part of what the approver signs off, so
        # it shows on the row (truncated, escaped) — not only inside the
        # edit drawer. The container always ships (hidden when empty) so
        # the drawer's save can fill it live without a reload.
        _row_caption = ""
        if wf_state is not None:
            _row_caption = str(
                (getattr(wf_state, "edited_captions", None) or {}).get("warm-club_headline") or ""
            ).strip()
        _row_caption_disp = (_row_caption[:140] + "…") if len(_row_caption) > 140 else _row_caption
        _row_caption_html = (
            f'<div class="mh-row-caption" data-mh-row-caption="{_h(card_id_raw)}"'
            f"{'' if _row_caption else ' hidden'}"
            ' style="margin-top:4px;font-size:12px;color:var(--ink-dim)">'
            '<span style="font-family:var(--font-mono);font-size:10px;'
            'letter-spacing:0.14em;text-transform:uppercase;color:var(--ink-muted)">'
            "Caption</span> "
            f"<em data-mh-row-caption-text>{_h(_row_caption_disp)}</em></div>"
        )

        # E-13: translations saved on the card (via /translate or a
        # bilingual caption bundle) are part of what the approver signs
        # off — every saved slot (caption, alt text, headline, subhead)
        # renders on the row BEFORE approval, labelled, each with its own
        # dir attribute. Empty string for the common untranslated card.
        _row_translations_html = ""
        if wf_state is not None and getattr(wf_state, "translations", None):
            _row_translations_html = W._render_stored_translations({"workflow": wf_state.to_dict()})

        ach_rows_html_wf += f"""
<div class="ach-row" data-type="{a.get("type", "")}" data-conf="{conf_label}" data-swimmer="{_h(a.get("swimmer_name", ""))}" data-event="{_h(a.get("event", ""))}" data-band="{band}" data-post="{ra.get("suggested_post_type", "")}" data-status="{wf_status}" data-status-initial="{wf_status}">
  <div style="display:flex;align-items:flex-start;gap:14px;padding:14px 0;border-bottom:1px solid var(--border)">
    <label class="mh-row-check-wrap" title="Select card"><input type="checkbox" class="mh-row-check" name="card_ids" value="{_h(_render_card_id)}" aria-label="Select this card"></label>
    <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px;padding-top:2px">#{rank}</div>
    <div class="mh-thumb-wrap" style="flex:0 0 76px">
      <img class="mh-card-thumb" data-thumb-src="{_h(_thumb_url)}" alt=""
           style="width:76px;aspect-ratio:4/5;object-fit:cover;border-radius:8px;border:1px solid var(--border);background:color-mix(in oklab, var(--panel) 85%, transparent);display:block;opacity:0;transition:opacity 240ms ease"/>
    </div>
    <div style="flex:1">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        {W._band_chip(band)}
        <span class="tag info" style="font-size:10px">{atype}</span>
        {W._confidence_chip(conf_label, numeric=a.get("confidence"))}
        <span class="tag" style="font-size:10px">{post_type}</span>
        {W._worthiness_meter(prio)}
      </div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:2px">
        {_row_avatar}
        <div style="font-size:13px;font-weight:600">{swimmer} &middot; {event}</div>
      </div>
      <div style="font-size:13px;color:var(--ink-dim)">{headline}</div>
      {_row_caption_html}
      {_row_translations_html}
      {why_html}
      <!-- B-4: the slim triage row — Approve + Edit card (+ Re-queue /
           Download once decided). Captions, graphics, motion + scheduling
           all happen later in the Content builder (approved cards only). -->
      <div class="wf-actions" style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        {W._render_wf_actions(run_id, card_id_raw, wf_status)}
        <button type="button" class="btn secondary mh-inspect-btn" style="font-size:11px;padding:4px 10px"
                data-mh-inspect data-run-id="{_h(run_id)}" data-card-id="{_h(card_id_raw)}"
                data-card-uuid="{_h(card_uuid)}" data-graphic-url="{_h(_insp_graphic_url)}"
                data-caption-url="{_h(_insp_caption_url)}" data-thumb-url="{_h(_thumb_url)}" data-card-title="{swimmer} &middot; {event}"{W._inspector_state_attrs(wf_state)}
                aria-haspopup="dialog" aria-controls="mh-inspector"
                title="Edit this card before approval — caption, palette, elements, crop">
          &#9998; Edit card
        </button>
      </div>
      <details style="margin-top:10px">
        <summary style="cursor:pointer;font-size:12px;color:var(--ink-dim);user-select:none">How the ranking added up &amp; evidence</summary>
        <div style="margin-top:8px;font-size:12px">
          <div style="margin-bottom:6px"><strong>How the ranking added up:</strong></div>
          {W._render_factor_breakdown(ra.get("factors"))}
          <div style="margin:12px 0 4px"><strong>Evidence:</strong></div>
          <ul style="margin:0;padding-left:18px">{ev_html or '<li class="muted">No evidence items</li>'}</ul>
          <div style="margin-top:8px"><a href="{_trace_url}" target="_blank" rel="noopener" style="font-size:12px">View full trace JSON &rarr;</a></div>
          <!-- B-4: the quick reactions live with the evidence, not in the
               decision row — they annotate a card, they don't decide it. -->
          <div style="margin-top:10px;display:flex;align-items:center;gap:10px">
            <span class="muted" style="font-size:11px">Reactions</span>
            {W._render_reactions(run_id, card_id_raw, _react_counts)}
          </div>
        </div>
      </details>
    </div>
  </div>
</div>"""

    if not ach_rows_html_wf:
        # UI2.4 — a per-filter empty view (e.g. "nothing approved yet") is no
        # longer a server concern: every card renders and the tabs hide/show
        # them client-side, so emptiness here means there are genuinely no
        # ranked cards. The client-side tab sync shows the per-tab hint.
        if recognition_error:
            ach_rows_html_wf = W._empty_state(
                "alert",
                "Recognition hit a snag",
                f"The engine returned an error while ranking this run: "
                f'<code style="font-size:12px">{_h(recognition_error)}</code>. '
                "Re-uploading the file usually clears a transient parse error.",
                actions=f'<a class="btn" href="{url_for("upload")}">Try another file &rarr;</a>',
                kind="error",
            )
        elif not rr:
            ach_rows_html_wf = W._empty_state(
                "inbox",
                "No report <em>yet</em>",
                "We don&rsquo;t have a recognition report for this run. "
                "Re-upload the results file and the engine will rank the moments.",
                actions=f'<a class="btn" href="{url_for("upload")}">Upload results &rarr;</a>',
            )
        else:
            # Distinguish "engine ranked your swims and none stood out" from
            # "we never matched any of your swims in the first place". The
            # second case (file had swims but 0 matched this run's club) is
            # the common silent dead-end: the engine read the meet but the
            # club name didn't match, so recognition had nothing to rank.
            # Saying "no standout swims" there is misleading — name the real
            # reason and give a re-run path.
            _parsed_n = data.get("parsed_swim_count") or 0
            _our_n = data.get("our_swim_count") or 0
            _run_filter = (data.get("club_filter") or "").strip()
            _no_filter = any(
                isinstance(w, dict) and w.get("code") == "no_club_filter"
                for w in (data.get("parse_warnings") or [])
            )
            if _parsed_n and _our_n == 0:
                if _no_filter or not _run_filter:
                    _why = (
                        f"We read <strong>{_parsed_n}</strong> swims from the file, but no club "
                        "was selected — so none were matched to your swimmers and there was "
                        "nothing to rank. Re-run this file and pick your club."
                    )
                else:
                    _why = (
                        f"We read <strong>{_parsed_n}</strong> swims from the file, but "
                        f"<strong>0</strong> matched &ldquo;{_h(_run_filter)}&rdquo;. The club "
                        "name in the results may be written differently &mdash; re-run and "
                        "check the club name matches the file."
                    )
                ach_rows_html_wf = W._empty_state(
                    "search",
                    "No swims matched your club",
                    _why,
                    actions=f'<a class="btn" href="{url_for("upload")}">Re-run with your club &rarr;</a>',
                )
            else:
                ach_rows_html_wf = W._empty_state(
                    "trophy",
                    "No standout swims",
                    "The engine read the file but didn&rsquo;t find PBs, medals, or "
                    "first-times worth a card. That can happen for heats-only sheets "
                    "or entry lists.",
                    actions=f'<a class="btn secondary" href="{url_for("activity_page")}">Back to runs</a>',
                )

    # Single global AI-availability banner — replaces the 177 per-card
    # "AI UNAVAILABLE" alerts the previous implementation emitted. Now the
    # one shared honest-error helper (U.2), so the copy can't drift again.
    _ai_banner_html = W._ai_unavailable_banner()

    # J-3: the full queued-id list for "Approve all in queue" — the DOM
    # only holds the current page's rows. \\u003c-escaped so an id can
    # never close the <script type="application/json"> tag it rides in.
    _queued_ids_all_json = json.dumps(_queued_card_ids).replace("<", "\\u003c")

    # U.4 — sample-run banner. A sample pack carries the user's brand but
    # fictional swimmers, so say so plainly (never let a demo masquerade as
    # the club's own data) and point at the real upload when they're ready.
    _sample_banner_html = ""
    if W._run_is_sample(run_id):
        _sample_banner_html = (
            '<div class="card" style="border:1px solid var(--accent);'
            "background:var(--surface);display:flex;gap:16px;align-items:center;"
            'flex-wrap:wrap;justify-content:space-between;margin-bottom:var(--sp-5)">'
            '<div style="flex:1;min-width:min(240px,100%)">'
            '<div style="font-family:var(--font-mono);font-size:10.5px;'
            "letter-spacing:0.18em;text-transform:uppercase;color:var(--accent);"
            'margin-bottom:6px">Sample meet</div>'
            '<p style="margin:0;font-size:14px;line-height:1.55;color:var(--ink)">'
            "This is a demo meet so you can see the whole engine work — the "
            "cards, captions and ranking are styled in <strong>your</strong> "
            "brand, but the swimmers and clubs are fictional. When you've got "
            "a real results file, upload it and your first true pack lands here."
            "</p></div>"
            f'<a class="btn" href="{url_for("upload")}">Upload real results &rarr;</a>'
            "</div>"
        )

    body = f"""
<style>
.ach-row {{ transition: background 100ms; position: relative; padding-left: 12px; }}
.ach-row:hover {{ background: rgba(245,242,232,0.018); }}
.ach-row::before {{ content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 2px; background: transparent; border-radius: 0; }}
.ach-row[data-type="pb"]::before,
.ach-row[data-type="personal_best"]::before {{ background: var(--lane); box-shadow: 0 0 8px var(--lane-glow); }}
.ach-row[data-type="medal"]::before,
.ach-row[data-type="gold_medal"]::before,
.ach-row[data-type="podium"]::before {{ background: var(--medal); box-shadow: 0 0 8px var(--medal-glow); }}
.ach-row[data-type="first_time"]::before,
.ach-row[data-type="ft"]::before {{ background: var(--info); }}
.filters-bar {{ display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;padding:14px 16px;background:var(--panel2);border:1px solid var(--border);border-radius:var(--radius-sm);position:sticky;top:56px;z-index:50; }}
.filters-bar select {{ width:auto;min-width:120px;font-size:13px;padding:6px 10px; }}
.ach-row.hidden {{ display:none; }}
/* UI2.4 — client-side workflow tabs. The active tab sets data-wf-filter on
   #ach-list; these rules hide the cards that don't match, so Queue/Approved
   switch with no reload. Set server-side from ?wf= too, so the no-JS / deep-
   link path filters identically. Composes with .ach-row.hidden (the dropdown
   filters above): a row hidden by either axis stays hidden. */
#ach-list[data-wf-filter="queue"] .ach-row:not([data-status="queue"]) {{ display:none; }}
#ach-list[data-wf-filter="approved"] .ach-row:not([data-status="approved"]) {{ display:none; }}
#ach-list[data-wf-filter="rejected"] .ach-row:not([data-status="rejected"]) {{ display:none; }}
#mh-wf-empty {{ margin-top: var(--sp-2); }}
/* Council UI verdict (2026-05-31) — the review list collapses each card's
   reasoning by default for scroll relief (a 249-card meet was a ~70,000px
   wall). These rules keep the reasoning one click away with a clear "show
   reasoning" affordance; the "Expand all reasoning" control lives in the
   already-sticky .filters-bar above the list (a second sticky bar collided
   with it — caught in the Council audit round). */
details.why-card > summary .why-peek {{
  color: var(--ink-dim); font-weight: 600;
  text-decoration: underline;
  text-decoration-color: color-mix(in oklab, var(--lane) 50%, transparent);
  text-underline-offset: 3px;
  display: inline-flex; align-items: center; gap: 4px;
}}
details.why-card > summary .why-peek .why-chev {{ font-size: 9px; text-decoration: none; }}
details.why-card[open] > summary .why-peek {{ display: none; }}
@keyframes spin {{ from {{ transform:rotate(0deg) }} to {{ transform:rotate(360deg) }} }}
/* U.4 — mobile-aware review. Desktop keeps its compact, dense triage row;
   on a phone the Approve / Re-queue controls grow into full-width, 46px
   tap targets and the status label takes its own line, so a volunteer can
   work the queue from the pool deck without pinch-zooming. The inline
   button sizing on _render_wf_actions is overridden with !important here. */
@media (max-width: 700px) {{
  /* I-5: non-sticky on small screens — the 9-control bar otherwise pins over a
     third of the viewport above the queue while scrolling. */
  .filters-bar {{ position: static; top: auto; padding: 10px 12px; gap: 8px; }}
  .filters-bar select {{ flex: 1 1 calc(50% - 8px); min-width: 0; }}
  .ach-row > div {{ gap: 10px !important; }}
  .wf-actions {{ width: 100%; }}
  .wf-actions .strap {{ flex: 1 0 100%; }}
  .wf-actions .btn {{
    flex: 1 1 auto;
    min-height: 46px !important;
    padding: 12px 14px !important;
    font-size: 14px !important;
  }}
}}
/* B-4 — slim rows: the per-row checkboxes are opt-in. The bulk bar always
   shows its Select toggle; the select-all box, the count and the bulk
   actions only appear once select mode is on (the toggle stamps
   .mh-select-on onto #ach-list — revealing the row checkboxes — and onto
   the bar itself). Every rule keys on html.mh-js so a no-JS page keeps
   the always-visible checkboxes and bar. */
html.mh-js #ach-list:not(.mh-select-on) .mh-row-check-wrap {{ display: none; }}
html.mh-js #mh-rv-bulkbar.is-empty {{ display: flex; }}
html.mh-js #mh-rv-bulkbar:not(.mh-select-on) .mh-bulkbar-all,
html.mh-js #mh-rv-bulkbar:not(.mh-select-on) .mh-bulkbar-count,
html.mh-js #mh-rv-bulkbar:not(.mh-select-on) .mh-bulkbar-actions {{ display: none; }}
html:not(.mh-js) #mh-rv-select-toggle {{ display: none; }}
</style>

{_ai_banner_html}

<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7);margin-bottom:var(--sp-6)">
  <span class="mh-hero-eyebrow">Review queue</span>
  <h1>{_h(meet.get("name", "(unknown meet)"))}</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{_h(data.get("profile_display", "—"))}</span><span class="sep">·</span>
    <span>{_h(meet.get("start_date", "?"))} – {_h(meet.get("end_date", "?"))}</span><span class="sep">·</span>
    <span>{_h(meet.get("course", "?"))}</span><span class="sep">·</span>
    <span>{_h(meet.get("venue") or "venue unknown")}</span><span class="sep">·</span>
    <span style="color:var(--ink-faint)">{_h(dispatch_log.get("chosen_filename") or data.get("file_name", ""))}</span>
  </div>
</section>

{W._render_meet_recap_tabs(run_id, "review")}

{_sample_banner_html}

{_provenance_card}

{workflow_summary_card}

{warn_html}

{W._render_explainability_key()}

{weekend_glance_html}

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:8px">
    <h2 style="margin:0">Top achievements</h2>
    <span class="muted" style="font-size:12px">Approve cards here &mdash; build graphics, video &amp; the reel in the content builder.</span>
  </div>
  <div class="filters-bar">
    <select id="f-type" onchange="applyFilters()">{opts(types_set, "types", _ACH_TYPE_LABELS)}</select>
    <select id="f-conf" onchange="applyFilters()"><option value="">All confidence</option><option>high</option><option>medium</option><option>low</option></select>
    <select id="f-swimmer" onchange="applyFilters()">{opts(swimmers_set, "swimmers")}</select>
    <select id="f-event" onchange="applyFilters()">{opts(events_set, "events")}</select>
    <select id="f-band" onchange="applyFilters()">{opts(bands_set, "bands", _BAND_SHORT)}</select>
    <select id="f-post" onchange="applyFilters()">{opts(post_types_set, "post types", _POST_TYPE_LABELS)}</select>
    <button class="btn secondary" style="font-size:13px;padding:6px 12px" onclick="clearFilters()">Clear</button>
    <span id="f-count" class="muted" style="font-size:12px;align-self:center"></span>
    <button type="button" class="btn secondary" id="mh-expand-all-why" aria-pressed="false"
            style="margin-left:auto;font-size:12px;padding:6px 12px"
            title="Show or hide every card's reasoning at once">Expand all reasoning</button>
  </div>
  {_pager_html}
  <form id="mh-review-bulk" method="post">
    <div class="mh-bulkbar is-empty" id="mh-rv-bulkbar" role="group" aria-label="Bulk card actions"
         data-mh-bulkbar="review" data-form="mh-review-bulk" data-count="mh-rv-count"
         data-select-all="mh-rv-all" data-check="mh-row-check" data-row=".ach-row">
      <button type="button" class="btn secondary" id="mh-rv-select-toggle" aria-pressed="false"
              title="Pick several cards, then approve, reject, re-queue or download them together">Select</button>
      <label class="mh-bulkbar-all"><input type="checkbox" id="mh-rv-all" class="mh-check-all" aria-label="Select all shown cards"> Select all shown</label>
      <span class="mh-bulkbar-count" id="mh-rv-count">0 selected</span>
      <div class="mh-bulkbar-actions">
        <button type="submit" class="btn" data-mh-bulk="approve" name="op" value="approved"
                formaction="{url_for("api_cards_bulk_status", run_id=run_id)}">{_h(_rv_t("action.approve", _rv_loc))}</button>
        <button type="submit" class="btn secondary" data-mh-bulk="reject" name="op" value="rejected"
                formaction="{url_for("api_cards_bulk_status", run_id=run_id)}"
                data-confirm="Reject {{n}} selected card(s)? They move out of the queue; you can re-queue them later.">{_h(_rv_t("action.reject", _rv_loc))}</button>
        <button type="submit" class="btn secondary" data-mh-bulk="requeue" name="op" value="queue"
                formaction="{url_for("api_cards_bulk_status", run_id=run_id)}"
                title="Send the selected cards back to the queue — undoes an approval or rejection">{_h(_rv_t("action.requeue", _rv_loc))}</button>
        <button type="submit" class="btn secondary" data-mh-bulk="download"
                formaction="{url_for("api_cards_bulk_download", run_id=run_id)}"
                title="Download the selected cards' captions + visuals as a ZIP, ready to post">Download content (.zip)</button>
        <button type="submit" class="btn ghost" data-mh-bulk="export"
                style="font-size:12px;padding:6px 12px"
                formaction="{url_for("api_cards_bulk_export", run_id=run_id)}"
                title="Developer export: the selected cards' data (rank, scores, status) as JSON">{_h(_rv_t("action.export", _rv_loc))} data (JSON)</button>
      </div>
    </div>
    <div id="ach-list" data-wf-filter="{_h(_wf_filter)}">{ach_rows_html_wf}</div>
    <div id="mh-wf-empty" class="mh-empty-inline" hidden>
      <b id="mh-wf-empty-title">Nothing here yet</b><br>
      <span id="mh-wf-empty-body">Switch the filter to see the rest of the queue.</span>
    </div>
  </form>
  {_pager_html}
</div>
<script type="application/json" id="mh-queued-ids">{_queued_ids_all_json}</script>

<style>{W._BULK_ACTIONS_CSS}</style>
<script>{W._BULK_ACTIONS_JS}</script>

{W._render_near_miss_hint(len(no_ach_traces), _n_close_calls)}

<!-- Run detail & diagnostics: the recognition read, meet context, PB audit and
     raw tables a volunteer rarely needs are demoted below the decision surface,
     so the page leads with the task (review & approve) rather than the data. -->
<div style="margin:var(--sp-8) 0 var(--sp-3) 0;display:flex;align-items:center;gap:14px">
  <span style="font-family:var(--font-mono);font-size:10.5px;letter-spacing:0.18em;text-transform:uppercase;color:var(--ink-muted);white-space:nowrap">Run detail &amp; diagnostics</span>
  <span style="flex:1;height:1px;background:var(--hairline)"></span>
</div>

{meet_charts_html}

<div class="card">
  <h2>Recognition summary</h2>
  <div class="stat-block">{rec_stats_html}</div>
  <div style="margin-top:var(--sp-5);display:flex;gap:var(--sp-3);flex-wrap:wrap">
    <a class="btn secondary" href="{url_for("run_results_table", run_id=run_id)}">Browse all results &rarr;</a>
    <a class="btn secondary" href="{_export_url}">Download data (JSON)</a>
  </div>
  <details style="margin-top:var(--sp-4)">
    <summary style="font-family:var(--font-mono);font-size:10.5px;letter-spacing:0.18em;text-transform:uppercase;color:var(--ink-muted);cursor:pointer">Developer tools</summary>
    <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-top:var(--sp-3)">
      <a class="btn secondary" href="{_rec_json_url}" target="_blank" rel="noopener" style="font-size:12px">Download recognition JSON</a>
      <a class="btn secondary" href="{_gt_url}" style="font-size:12px">Run ground-truth check</a>
    </div>
    <!-- UI2.8 — Codeblock raw parsed-data view. The machine-readable JSON the
         recognition engine produced, shown inline through the first-party
         server-side highlighter (no CDN), syntax-coloured and copyable, so a
         volunteer never has to leave the page or read an unstyled browser tab
         to see exactly what the engine decided. Whitelisted fields only; the
         block is server-rendered so it works with JavaScript disabled (only the
         copy button is a progressive enhancement). -->
    <div class="mh-machine-readable" id="mh-machine-readable" style="margin-top:var(--sp-4)">
      <p class="muted" style="font-size:12px;margin:0 0 8px">The machine-readable data the recognition engine produced for this run &mdash; meet context, the parsed and club-matched swim counts and the ranked achievements, in the same JSON shape the export and the downstream content steps consume. Read-only; copy it straight from here.</p>
      {W._code_hl.code_block(W._machine_readable_run(data, run_id), "json", label="Recognition data")}
    </div>
  </details>
</div>

{meet_ctx_html}

{pb_audit_html}

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Legacy content cards <span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(cards)} cards</span></summary>
    <div style="margin-top:14px">
      <div class="mh-table-scroll"><table>
        <thead><tr><th>Card</th><th>Confidence</th><th>Safe to post</th><th>Bucket</th><th>Why</th></tr></thead>
        <tbody>{"".join(v4_rows) or '<tr><td colspan="5" class="muted">No cards generated.</td></tr>'}</tbody>
      </table></div>
      <div style="margin-top:14px">{captions_html or '<p class="muted">No captions.</p>'}</div>
    </div>
  </details>
</div>

<div class="card" id="mh-all-swims">
  <details{" open" if (_n_close_calls or _promoted_flash) else ""}>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">All swims &mdash; ranked <span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(_swim_rows)} analysed, {_n_swim_standout} standout{f", {_n_close_calls} close {'call' if _n_close_calls == 1 else 'calls'}" if _n_close_calls else ""}</span></summary>
    <div style="margin-top:8px">
      {_promoted_flash}
      <p class="muted" style="font-size:12px;margin:0 0 12px">Every analysed swim, ranked by the engine's own scores &mdash; standouts pinned first, close calls flagged in plain English, and ordinary completed swims read honestly as just that. Nothing was silently dropped. If the automation missed a swim that matters to your club, <b>Create highlight</b> turns it into a card in the review queue &mdash; you approve it like any other before it reaches the Content builder.</p>
      <div class="mh-table-scroll"><table>
        <thead><tr><th>Swimmer</th><th>Event</th><th>Time</th><th>Score</th><th>What we saw</th><th></th></tr></thead>
        <tbody>{all_swims_rows or '<tr><td colspan="6" class="muted">No trace data available for this run — re-run the file to get the per-swim breakdown.</td></tr>'}</tbody>
      </table></div>
    </div>
  </details>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Sources used <span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(all_sources)} source(s)</span></summary>
    <div style="margin-top:14px">
      <div class="mh-table-scroll"><table>
        <thead><tr><th>Source</th><th>Used for</th><th>Fetched</th></tr></thead>
        <tbody>{sources_rows}</tbody>
      </table></div>
    </div>
  </details>
</div>

<div class="card" style="border-color:rgba(255,107,107,0.25);margin-top:var(--sp-6)">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap">
    <div>
      <h2 style="margin:0 0 2px 0;font-size:15px">Delete these results</h2>
      <p class="muted" style="margin:0;font-size:12px">Removes the generated cards and review state for this run. Source files stay on disk and can be re-processed.</p>
    </div>
    <form method="post" action="{_delete_url}" onsubmit="return confirm('Delete these results permanently? Source files stay on disk; generated cards and the review state are removed.')">
      <button class="btn danger" type="submit">Delete run</button>
    </form>
  </div>
</div>

<script>
function mhActiveWfFilter() {{
  var list = document.getElementById('ach-list');
  return (list && list.getAttribute('data-wf-filter')) || '';
}}
function applyFilters() {{
  var fType = document.getElementById('f-type').value;
  var fConf = document.getElementById('f-conf').value;
  var fSwimmer = document.getElementById('f-swimmer').value;
  var fEvent = document.getElementById('f-event').value;
  var fBand = document.getElementById('f-band').value;
  var fPost = document.getElementById('f-post').value;
  var wf = mhActiveWfFilter();
  var rows = document.querySelectorAll('#ach-list .ach-row');
  var shown = 0, inTab = 0;
  rows.forEach(function(row) {{
    // UI2.4 — the workflow tab axis is applied by CSS (#ach-list[data-wf-filter]);
    // fold it into the count only, so "N of M shown" tracks the active tab.
    var wfOk = !wf || row.dataset.status === wf;
    if (wfOk) inTab++;
    var match = true;
    if (fType && row.dataset.type !== fType) match = false;
    if (fConf && row.dataset.conf !== fConf) match = false;
    if (fSwimmer && row.dataset.swimmer !== fSwimmer) match = false;
    if (fEvent && row.dataset.event !== fEvent) match = false;
    if (fBand && row.dataset.band !== fBand) match = false;
    if (fPost && row.dataset.post !== fPost) match = false;
    // .hidden carries only the dropdown axis so it composes with the CSS tab
    // hide — a row hidden by either axis stays hidden.
    row.classList.toggle('hidden', !match);
    if (match && wfOk) shown++;
  }});
  var countEl = document.getElementById('f-count');
  if (countEl) {{
    // JS-1: on a paginated run these numbers are page-scoped while the tab
    // badges are run-wide — say so, so "3 of 3 shown" can't read as the meet.
    var pageScoped = !!document.querySelector('.mh-review-pager');
    countEl.textContent = shown + ' of ' + inTab + ' shown' + (pageScoped ? ' on this page' : '');
  }}
}}
function clearFilters() {{
  ['f-type','f-conf','f-swimmer','f-event','f-band','f-post'].forEach(function(id) {{
    var el = document.getElementById(id);
    if (el) el.value = '';
  }});
  applyFilters();
}}
applyFilters();

// UI2.4 — client-side workflow filter tabs. The kit (.mh-tabs) already slides
// the indicator + toggles the active tab on click; this turns that tab into an
// in-place filter: it sets #ach-list[data-wf-filter] (CSS hides the cards that
// don't match), keeps the URL's ?wf= in sync without a reload, and refreshes
// the per-tab empty hint + the "N of M shown" count. Each tab keeps its href so
// a no-JS page still filters via a normal navigation.
(function() {{
  var nav = document.querySelector('.mh-tabs[role="tablist"]');
  var list = document.getElementById('ach-list');
  if (!nav || !list) return;

  window.mhWfTabsSync = function() {{
    var wf = list.getAttribute('data-wf-filter') || '';
    var rows = document.querySelectorAll('#ach-list .ach-row');
    var inTab = 0;
    rows.forEach(function(r) {{ if (!wf || r.dataset.status === wf) inTab++; }});
    var empty = document.getElementById('mh-wf-empty');
    if (empty) {{
      var show = rows.length > 0 && inTab === 0;
      empty.hidden = !show;
      if (show) {{
        var t = document.getElementById('mh-wf-empty-title');
        var b = document.getElementById('mh-wf-empty-body');
        // JS-1: the DOM only holds this page's rows (J-3 pagination) while
        // the tab badges are painted from run-wide counts (baseline + live
        // delta). When the run still has cards in this tab, the truth is
        // "not on this page" — "Queue clear" is reserved for a run-wide 0.
        var badge = document.getElementById('mh-wf-tabcount-' + (wf || 'all'));
        var runWide = badge ? (parseInt(badge.textContent, 10) || 0) : 0;
        if (runWide > 0) {{
          var noun = wf === 'approved' ? 'approved' : (wf === 'rejected' ? 'rejected' : 'queued');
          if (t) t.textContent = 'None on this page';
          if (b) b.textContent = 'The ' + noun + ' cards for this meet live on other pages \\u2014 use the pager above.';
        }} else if (wf === 'approved') {{
          if (t) t.textContent = 'Nothing approved yet';
          if (b) b.textContent = 'Approve cards from the Queue and they move here.';
        }} else if (wf === 'rejected') {{
          if (t) t.textContent = 'No rejected cards';
          if (b) b.textContent = 'Cards you reject move here \\u2014 you can re-queue them any time.';
        }} else if (wf === 'queue') {{
          if (t) t.textContent = 'Queue clear';
          if (b) b.textContent = 'Every card has been reviewed \\u2014 nice work.';
        }} else {{
          if (t) t.textContent = 'Nothing here yet';
          if (b) b.textContent = 'Switch the filter to see the rest of the queue.';
        }}
      }}
    }}
    if (window.applyFilters) window.applyFilters();
  }};

  nav.addEventListener('click', function(ev) {{
    var tab = ev.target.closest('[data-wf-filter-to]');
    if (!tab || !nav.contains(tab)) return;
    ev.preventDefault();
    var val = tab.getAttribute('data-wf-filter-to') || '';
    // SRV-1: on a paginated run the pages are sliced server-side from the
    // cards matching the active filter, so switching tabs needs the server
    // to re-filter and re-paginate (page resets to 1). Single-page runs
    // keep the instant client-side toggle — the kit just moves the
    // indicator.
    if (document.querySelector('.mh-review-pager')) {{
      location.assign(location.pathname + (val ? ('?wf=' + encodeURIComponent(val)) : ''));
      return;
    }}
    list.setAttribute('data-wf-filter', val);
    try {{
      // JS-1: keep ?page=N (J-3 pagination) when rewriting ?wf= — dropping
      // it made a mid-run reload silently jump back to page 1.
      var qs = new URLSearchParams(location.search);
      if (val) qs.set('wf', val); else qs.delete('wf');
      var q = qs.toString();
      history.replaceState(null, '', location.pathname + (q ? ('?' + q) : ''));
    }} catch (e) {{}}
    window.mhWfTabsSync();
  }});

  window.mhWfTabsSync();           // initial sync (covers a ?wf= deep-link)
}})();

// V9: Copy "Why this card?" reasoning to clipboard (for sponsor reports etc.)
function copyWhyCard(btn, taId) {{
  var ta = document.getElementById(taId);
  if (!ta) {{ return; }}
  var text = ta.value || '';
  var orig = btn.textContent;
  var done = function(ok) {{
    btn.textContent = ok ? 'Copied!' : 'Copy failed';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function() {{ done(true); }}).catch(function() {{ fallback(); }});
  }} else {{
    fallback();
  }}
  function fallback() {{
    var t = document.createElement('textarea');
    t.value = text; t.style.position = 'fixed'; t.style.left = '-9999px';
    document.body.appendChild(t); t.focus(); t.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }}
    catch (e) {{ done(false); }}
    document.body.removeChild(t);
  }}
}}

// Lazy "Why this card?" loader. Each card's reasoning is LLM-backed; a big
// meet has 150+ cards, so fetching them all up front (or server-side during
// the page render) is what made /review take minutes. We fetch each card's
// reasoning only when it scrolls near the viewport, a few at a time.
(function() {{
  var inflight = 0, MAXQ = 3, queue = [];
  function pump() {{
    while (inflight < MAXQ && queue.length) {{ loadWhy(queue.shift()); }}
  }}
  function loadWhy(el) {{
    if (!el || el.dataset.whyLoaded) {{ return; }}
    el.dataset.whyLoaded = '1';
    var url = el.getAttribute('data-why-url');
    if (!url) {{ return; }}
    var cuid = el.getAttribute('data-why-cuid') || '';
    var full = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'cuid=' + encodeURIComponent(cuid);
    inflight++;
    fetch(full, {{cache:'no-store'}})
      .then(function(r) {{ if (!r.ok) {{ throw new Error('http ' + r.status); }} return r.text(); }})
      .then(function(html) {{ el.innerHTML = html; }})
      .catch(function() {{
        el.dataset.whyLoaded = '';
        el.innerHTML = '<div class="muted" style="margin-top:8px;font-size:12px;color:var(--ink-muted)">'
          + 'Could not load the reasoning. <a href="#" onclick="return mhRetryWhy(this)">Retry</a></div>';
      }})
      .then(function() {{ inflight--; pump(); }});
  }}
  window.mhRetryWhy = function(a) {{
    var body = a.closest ? a.closest('.why-body') : null;
    if (body) {{ body.dataset.whyLoaded = ''; queue.push(body); pump(); }}
    return false;
  }};
  function loadBody(b) {{
    if (!b || b.dataset.whyLoaded) {{ return; }}
    queue.push(b); pump();
  }}
  function markSeen(d) {{
    var row = d.closest ? d.closest('.ach-row') : null;
    if (row) row.setAttribute('data-why-seen', '1');
  }}
  function init() {{
    var bodies = Array.prototype.slice.call(document.querySelectorAll('.why-body[data-why-url]'));
    if (!bodies.length) {{ return; }}
    // The review list collapses each card's reasoning by default (Council UI
    // verdict): a collapsed <details> hides its .why-body (display:none), so
    // the IntersectionObserver never fires for it. Load on expand instead, and
    // remember the reviewer has now actually seen that card's reasoning.
    Array.prototype.slice.call(document.querySelectorAll('details.why-card')).forEach(function(d){{
      d.addEventListener('toggle', function(){{
        if (d.open) {{ loadBody(d.querySelector('.why-body[data-why-url]')); markSeen(d); }}
      }});
      if (d.open) {{ loadBody(d.querySelector('.why-body[data-why-url]')); markSeen(d); }}
    }});
    if ('IntersectionObserver' in window) {{
      var obs = new IntersectionObserver(function(entries) {{
        entries.forEach(function(e) {{
          if (e.isIntersecting) {{ obs.unobserve(e.target); queue.push(e.target); pump(); }}
        }});
      }}, {{rootMargin: '600px 0px'}});
      // Only observe bodies already visible (inside an open card); collapsed
      // ones are handled by the toggle listener above.
      bodies.forEach(function(b) {{ if (b.offsetParent !== null) obs.observe(b); }});
    }} else {{
      bodies.forEach(function(b) {{ queue.push(b); }});
      pump();
    }}
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', init);
  }} else {{ init(); }}
}})();

</script>

<!-- M29 (UX-1) — lazy card thumbnails: each review row shows the card's real
     graphic. Loading waits for scroll-into-view, runs at most two renders at
     a time (the server render gate is small), retries politely on the 429
     "renderer busy" answer, and degrades to an honest placeholder. -->
<script>
(function() {{
  var imgs = Array.prototype.slice.call(document.querySelectorAll('img.mh-card-thumb[data-thumb-src]'));
  if (!imgs.length) {{ return; }}
  var queue = [], inflight = 0, MAXC = 2;
  function placeholder(img, msg) {{
    var d = document.createElement('div');
    d.className = 'mh-card-thumb-empty';
    d.style.cssText = 'width:76px;aspect-ratio:4/5;display:flex;align-items:center;justify-content:center;text-align:center;font-size:10px;line-height:1.35;color:var(--ink-muted);border:1px dashed var(--border);border-radius:8px;padding:4px';
    d.textContent = msg;
    img.replaceWith(d);
  }}
  function settle() {{ inflight--; pump(); }}
  function attempt(img) {{
    fetch(img.getAttribute('data-thumb-src'), {{cache: 'no-store'}})
      .then(function(r) {{
        if (r.status === 429) {{
          var t = (parseInt(img.dataset.tries || '0', 10)) + 1;
          img.dataset.tries = t;
          if (t <= 6) {{ setTimeout(function() {{ inflight++; attempt(img); }}, 5000); return null; }}
          placeholder(img, 'Renderer busy — refresh to retry');
          return null;
        }}
        if (!r.ok) {{ placeholder(img, 'Preview appears after the first render'); return null; }}
        return r.blob();
      }})
      .then(function(b) {{
        if (b) {{
          img.onload = function() {{ img.style.opacity = '1'; }};
          img.src = URL.createObjectURL(b);
        }}
      }})
      .catch(function() {{ placeholder(img, 'Preview unavailable'); }})
      .then(settle, settle);
  }}
  function pump() {{
    while (inflight < MAXC && queue.length) {{
      inflight++;
      attempt(queue.shift());
    }}
  }}
  if ('IntersectionObserver' in window) {{
    var obs = new IntersectionObserver(function(entries) {{
      entries.forEach(function(e) {{
        if (e.isIntersecting) {{ obs.unobserve(e.target); queue.push(e.target); pump(); }}
      }});
    }}, {{rootMargin: '250px 0px'}});
    imgs.forEach(function(im) {{ obs.observe(im); }});
  }} else {{
    imgs.forEach(function(im) {{ queue.push(im); }});
    pump();
  }}
}})();
</script>

<!-- Phase 6 — bulk approve + expand-all reasoning. (Keyboard navigation and the
     '?' help overlay are now provided globally by the UI 1.28 shortcuts engine
     in _layout, which detects this review surface via its .ach-row cards — so
     the review page no longer ships its own '?' handler or modal.) -->
<script>
(function(){{
  // ----- Bulk approve -----
  // D-2: every queued card approves in ONE request — per-card gate results,
  // held-vote handling and a single summary toast — never 150+ fetches.
  // J-3: the review list is paginated server-side, so the DOM only holds the
  // current page's rows. The FULL queued-id list is embedded by the server
  // (#mh-queued-ids), so the approve-all button operates on the whole queue,
  // not just the visible page.
  var bulkBtn = document.getElementById('mh-bulk-approve');
  if (bulkBtn) {{
    bulkBtn.addEventListener('click', function(){{
      var ids = [];
      try {{
        var idsEl = document.getElementById('mh-queued-ids');
        if (idsEl) ids = JSON.parse(idsEl.textContent || '[]') || [];
      }} catch (e) {{ ids = []; }}
      var pageQueued = Array.prototype.slice.call(
        document.querySelectorAll('.ach-row[data-status="queue"]')
      );
      if (!ids.length) {{
        // Defensive fallback (embedded list absent): approve what this page
        // can see rather than doing nothing.
        ids = pageQueued.map(function(row){{
          var c = row.querySelector('.mh-row-check');
          return c ? c.value : '';
        }}).filter(Boolean);
      }}
      // JS-2: the embedded list is a render-time snapshot — reconcile it with
      // decisions made on this page since (per-card straps, bulk bar). Each
      // row's live data-status is the source of truth, so approve-then-requeue
      // is handled too; off-page ids can't change without a reload, so the
      // snapshot stays truthful for them.
      var decidedNow = {{}};
      Array.prototype.slice.call(document.querySelectorAll('.ach-row[data-status]')).forEach(function(row){{
        var chk = row.querySelector('.mh-row-check');
        if (chk && chk.value && row.dataset.status !== 'queue') decidedNow[chk.value] = 1;
      }});
      ids = ids.filter(function(id){{ return !decidedNow[id]; }});
      if (!ids.length) {{
        if (window.MH) MH.toast('No cards in the queue to approve.', 'info');
        return;
      }}
      var unseen = pageQueued.filter(function(el){{ return !el.getAttribute('data-why-seen'); }}).length;
      var offPage = ids.length - pageQueued.length;
      var msg = 'Approve all ' + ids.length + ' queued card' + (ids.length === 1 ? '' : 's') + '?';
      if (offPage > 0) {{
        msg += '  (' + offPage + ' of them ' + (offPage === 1 ? 'is' : 'are') + ' on other pages.)';
      }}
      if (unseen > 0) {{
        msg += '  (' + unseen + " on this page not yet opened — you haven't read their reasoning; approving accepts them as-is.)";
      }}
      if (!window.confirm(msg)) return;
      bulkBtn.disabled = true;
      fetch((window._API_BASE || '') + '{url_for("api_cards_bulk_status", run_id=run_id)}', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json', 'Accept': 'application/json'}},
        body: JSON.stringify({{ids: ids, status: 'approved'}})
      }}).then(function(r){{ return r.json().then(function(j){{ return {{ok: r.ok, body: j}}; }}); }})
        .then(function(o){{
          if (!o.ok || !o.body || o.body.ok === false) {{
            bulkBtn.disabled = false;
            var m = (o.body && (o.body.reason || o.body.error || o.body.message)) || 'failed';
            if (window.MH) MH.toast('Bulk approve failed: ' + m, 'error', 4000);
            return;
          }}
          var results = o.body.results || [];
          var okN = results.filter(function(r){{ return r.ok && (r.status || 'approved') === 'approved'; }}).length;
          var held = results.filter(function(r){{ return r.ok && r.status && r.status !== 'approved'; }}).length;
          var blocked = o.body.n_blocked || 0;
          var m2 = 'Approved ' + okN + ' card' + (okN === 1 ? '' : 's') + '.';
          if (held) m2 += ' ' + held + ' held for another approver.';
          if (blocked) {{
            var gateNames = {{consent_blocked: 'consent', brand_locked: 'brand lock', tasks_open: 'open task'}};
            var byGate = {{}};
            results.forEach(function(r){{
              if (!r.ok && gateNames[r.error]) {{
                var g = gateNames[r.error];
                byGate[g] = (byGate[g] || 0) + 1;
              }}
            }});
            var parts = Object.keys(byGate).map(function(g){{ return byGate[g] + ' ' + g; }});
            m2 += ' ' + blocked + ' blocked' + (parts.length ? ' (' + parts.join(', ') + ').' : ' by review gates.');
          }}
          if (window.MH) MH.toast(m2, okN ? 'success' : 'info', 3500);
          // The whole queue (other pages included) changed server-side —
          // re-render so rows, tabs and counts reflect the new state. Leave
          // the toast readable a beat longer when something was held/blocked.
          setTimeout(function(){{ window.location.reload(); }}, (held || blocked) ? 2600 : 1200);
        }})
        .catch(function(err){{
          bulkBtn.disabled = false;
          if (window.MH) MH.toast('Bulk approve failed: ' + ((err && err.message) || err), 'error', 4000);
        }});
    }});
  }}

  // ----- Expand / collapse all reasoning -----
  // Reviewers who want the old "everything visible" experience get it in one
  // click; opening a card fires its toggle handler, which lazy-loads the
  // reasoning and marks it seen.
  var expandBtn = document.getElementById('mh-expand-all-why');
  if (expandBtn) {{
    expandBtn.addEventListener('click', function(){{
      var next = expandBtn.getAttribute('aria-pressed') !== 'true';
      Array.prototype.slice.call(document.querySelectorAll('details.why-card'))
        .forEach(function(d){{ d.open = next; }});
      expandBtn.setAttribute('aria-pressed', next ? 'true' : 'false');
      expandBtn.textContent = next ? 'Collapse all reasoning' : 'Expand all reasoning';
    }});
  }}

  // ----- B-4: select mode -----
  // The per-row checkboxes are hidden until the volunteer asks for them; the
  // Select toggle stamps .mh-select-on onto #ach-list (revealing the boxes)
  // and onto the bulk bar (revealing select-all, the count and the actions).
  // Leaving select mode clears the selection — nothing stays checked
  // invisibly — via a bubbled change event so the shared bulk-bar JS
  // refreshes its count, is-empty state and row highlights.
  var selToggle = document.getElementById('mh-rv-select-toggle');
  if (selToggle) {{
    selToggle.addEventListener('click', function(){{
      var list = document.getElementById('ach-list');
      var bar = document.getElementById('mh-rv-bulkbar');
      var on = selToggle.getAttribute('aria-pressed') !== 'true';
      if (list) list.classList.toggle('mh-select-on', on);
      if (bar) bar.classList.toggle('mh-select-on', on);
      selToggle.setAttribute('aria-pressed', on ? 'true' : 'false');
      selToggle.textContent = on ? 'Done' : 'Select';
      if (!on) {{
        var all = document.getElementById('mh-rv-all');
        if (all) {{ all.checked = false; all.indeterminate = false; }}
        var lastChecked = null;
        Array.prototype.forEach.call(
          document.querySelectorAll('#mh-review-bulk .mh-row-check'),
          function(c){{ if (c.checked) {{ c.checked = false; lastChecked = c; }} }}
        );
        if (lastChecked) lastChecked.dispatchEvent(new Event('change', {{bubbles: true}}));
      }}
    }});
  }}
}})();
</script>

<!-- UI 1.18 — Inspector / properties panel (one shared drawer for the page) -->
{W._render_inspector_panel(_review_swatches)}
{W._inspector_js()}
"""
    # Operator-only processing log. A developer reviewing a finished run can
    # see exactly what happened — PB-lookup errors, club-discovery store
    # warnings, and every other step — persisted from the run, so genuine
    # failures never silently vanish once the live progress screen redirects
    # here. Gated behind the developer session: customers never see the raw
    # engineer-facing steps or internal error text.
    if W._auth.is_dev_operator():
        _plog = data.get("progress_log") or []
        if _plog:
            _problem_lines = [
                ln for ln in _plog if any(k in ln.lower() for k in ("error", "warning", "failed"))
            ]
            _problems_html = ""
            if _problem_lines:
                _problems_html = (
                    '<div class="strap" style="color:var(--bad);margin-bottom:var(--sp-2)">'
                    f"{len(_problem_lines)} issue(s) flagged during processing</div>"
                    + "".join(
                        '<div style="font-family:var(--font-mono);font-size:12px;'
                        'color:var(--bad);white-space:pre-wrap;word-break:break-word">'
                        f"{_h(ln)}</div>"
                        for ln in _problem_lines
                    )
                )
            body += f"""
<div class="card" style="margin-top:var(--sp-6);border-left:2px solid var(--accent)">
  <div class="strap" style="margin-bottom:var(--sp-3)">Processing log &middot; operator only</div>
  {_problems_html}
  <details style="margin-top:var(--sp-3)">
    <summary style="cursor:pointer;color:var(--ink-dim);font-size:13px;user-select:none">Full processing log ({len(_plog)} steps)</summary>
    <div class="progress-log" style="margin-top:var(--sp-3)">{_h(chr(10).join(_plog))}</div>
  </details>
</div>
"""
    # U.13: floating mobile action dock for the review/approve flow — only
    # when there's actually a pack to review (cards present or workflow
    # state on file). Its "Approve" pill advances through the queue; when
    # empty it links to the content builder. `queue` is the initial count
    # (mirrors the page's Queue stat); the dock script keeps it live.
    _review_dock = (
        {"builder": _pack_url, "queue": _n_queue_cards} if (_wf_summary or ranked_achs) else None
    )
    # F-2: the browser tab read the engine's "Recognition"; title it by the
    # meet the volunteer is reviewing instead.
    _meet_name = (meet.get("name") or "").strip() if isinstance(meet, dict) else ""
    _review_title = f"Review — {_meet_name}" if _meet_name else "Review"
    return W._layout(_review_title, body, active="home", dock=_review_dock)


@W.require_run(
    deny=lambda: (
        W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            eyebrow="Results table",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    ),
    require_exists=True,
)
def run_results_table(run_id, run_data):
    """UI 1.12 — Wope-style sortable/filterable parsed-results table.

    A flat, scannable grid of every individual swim in the run, each with a
    per-athlete progress sparkline and a PB/improvement delta badge. Sort
    and filter are server-side (this route re-renders from query params); the
    sparklines are drawn client-side on ``<canvas>`` from an embedded series
    payload, so the page stays fully usable without JavaScript.
    """
    data = run_data
    meet = data.get("meet") or {}
    _review_url = url_for("review", run_id=run_id)

    # Cross-meet history per athlete — read-only registry lookups (resolve by
    # name, then that athlete's full swim log). Best-effort: a missing/empty
    # registry just means no prior history yet (the current swim still shows
    # as the latest point and the badge reads "first on record").
    pid = W._active_profile_id() or (data.get("profile_id") or "")
    history: dict[str, list[dict]] = {}
    if pid:
        try:
            from mediahub.athletes import resolve_and_swims_bulk as _ath_bulk

            swimmers = meet.get("swimmers") or {}
            # Distinct swimmer_key → display name, then ONE bulk lookup
            # (single connection, IN-queries) instead of resolve + swims per
            # swimmer (two connection opens each).
            sk_name: dict[str, str] = {}
            for res in meet.get("results") or []:
                sk = res.get("swimmer_key") or ""
                if not sk or sk in sk_name:
                    continue
                sw = swimmers.get(sk) or {}
                sk_name[sk] = (
                    f"{(sw.get('first_name') or '').strip()} "
                    f"{(sw.get('last_name') or '').strip()}"
                ).strip()
            names = [n for n in sk_name.values() if n]
            swims_by_name = _ath_bulk(pid, names) if names else {}
            history = {
                sk: (swims_by_name.get(name, []) if name else []) for sk, name in sk_name.items()
            }
        except Exception:
            history = {}

    rows = W._rt.build_rows(meet, history, run_id)

    # Empty run (no individual results at all) — honest empty state.
    if not rows:
        empty_body = (
            '<section class="mh-hero" data-lane="--" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
            '<span class="mh-hero-eyebrow">Results table</span>'
            "<h1>No parsed results on this run</h1>"
            '<p class="lede">This run has no individual swim results to tabulate &mdash; '
            "it may have parsed only relays, or failed before extracting results.</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{_review_url}">Back to review &rarr;</a>'
            f'<a class="mh-cta-secondary" href="{url_for("upload")}">Upload another file</a>'
            "</div></section>"
        )
        return W._layout("Results table", empty_body, active="create")

    # ---- server-side sort + filter from query params ----
    sort, order = W._rt.normalise_sort(request.args.get("sort"), request.args.get("order"))
    f_event = (request.args.get("event") or "").strip()
    f_q = (request.args.get("q") or "").strip()
    f_pb = (request.args.get("pb") or "") in ("1", "on", "true")
    filtered = W._rt.filter_rows(rows, event=f_event, query=f_q, pb_only=f_pb)
    visible = W._rt.sort_rows(filtered, sort, order)

    # ---- summary stats (over ALL rows, not the filtered view) ----
    n_swims = len(rows)
    n_athletes = len({r.swimmer_key for r in rows if r.swimmer_key})
    n_pb = sum(1 for r in rows if r.delta.kind == "pb")
    n_impr = sum(1 for r in rows if r.delta.kind == "improvement")

    # ---- sortable column headers (server-side; toggle asc/desc) ----
    def _sort_href(col: str) -> str:
        new_order = "desc" if (sort == col and order == "asc") else "asc"
        return url_for(
            "run_results_table",
            run_id=run_id,
            sort=col,
            order=new_order,
            event=f_event or None,
            q=f_q or None,
            pb="1" if f_pb else None,
        )

    def _th(col: str, label: str) -> str:
        arrow = ""
        aria = ""
        if sort == col:
            arrow = (
                ' <span aria-hidden="true">▲</span>'
                if order == "asc"
                else ' <span aria-hidden="true">▼</span>'
            )
            aria = ' aria-sort="ascending"' if order == "asc" else ' aria-sort="descending"'
        return (
            f'<th{aria}><a href="{_sort_href(col)}" '
            'style="color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:4px">'
            f"{label}{arrow}</a></th>"
        )

    # ---- rows + sparkline payload ----
    _DELTA_TAG = {
        "pb": "medal",
        "improvement": "good",
        "matched": "info",
        "first": "",
        "slower": "bad",
        "none": "",
    }
    spark_payload: dict[str, dict] = {}
    body_rows = ""
    for i, r in enumerate(visible):
        if r.delta.kind == "none" or not r.delta.label:
            delta_html = '<span class="muted" style="font-size:12px">—</span>'
        else:
            cls = _DELTA_TAG.get(r.delta.kind, "")
            delta_html = (
                f'<span class="tag {cls}" title="{_h(r.delta.title)}">{_h(r.delta.label)}</span>'
            )

        if len(r.series_cs) >= 2:
            sid = f"s{i}"
            _series = W._rt.sparkline_series(r)
            # The drawing JS only reads t/cur/kind; 'd' carries swim_date
            # strings from the uploaded file and is never used. Drop it so
            # untrusted file content can't ride into the embedded <script>.
            _series.pop("d", None)
            spark_payload[sid] = _series
            _trend = (
                f" ({r.delta.label})" if r.delta.kind in ("pb", "improvement", "matched") else ""
            )
            aria = _h(f"Progress over {len(r.series_cs)} swims, latest {r.time_str}{_trend}")
            spark_html = (
                f'<canvas class="mh-spark" data-spark="{sid}" role="img" '
                f'aria-label="{aria}" width="104" height="28" '
                'style="width:104px;height:28px;display:block"></canvas>'
            )
        elif len(r.series_cs) == 1:
            spark_html = '<span class="muted" style="font-size:11px" title="No earlier swim on record yet">1 swim</span>'
        else:
            spark_html = '<span class="muted" style="font-size:12px">—</span>'

        gender_html = (
            f' <span class="muted" style="font-size:11px">{_h(r.gender)}</span>' if r.gender else ""
        )
        if r.is_dq:
            time_cell = f'<span class="tag bad" title="{_h(r.status.upper())}">{_h(r.status.upper() or "DQ")}</span>'
        else:
            time_cell = _h(r.time_str)
        body_rows += (
            "<tr>"
            f'<td class="mono" style="color:var(--ink-dim)">{r.place if r.place is not None else "—"}</td>'
            f"<td><strong>{_h(r.swimmer_name)}</strong></td>"
            f"<td>{_h(r.event_label)}{gender_html}</td>"
            f'<td class="muted">{_h(r.age_band or "—")}</td>'
            f'<td class="mono" style="white-space:nowrap">{time_cell}</td>'
            f"<td>{delta_html}</td>"
            f"<td>{spark_html}</td>"
            "</tr>"
        )

    # ---- event filter dropdown ----
    ev_opts = '<option value="">All events</option>'
    for ek, elabel in W._rt.event_options(rows):
        sel = " selected" if ek == f_event else ""
        ev_opts += f'<option value="{_h(ek)}"{sel}>{_h(elabel)}</option>'

    # Truthiness of already-parsed filter values, not a user-input cast.
    # (pre-existing web.py body exposed to semgrep by the #15 carve.)
    # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
    any_filter = bool(f_event or f_q or f_pb)
    clear_link = (
        f'<a class="btn ghost" style="font-size:13px" '
        f'href="{url_for("run_results_table", run_id=run_id, sort=sort, order=order)}">Clear filters</a>'
        if any_filter
        else ""
    )
    count_line = f"Showing <strong>{len(visible)}</strong> of {n_swims} swims" + (
        " (filtered)" if any_filter else ""
    )
    no_match_row = (
        '<tr><td colspan="7" class="muted" style="text-align:center;padding:24px">'
        "No swims match these filters.</td></tr>"
    )
    # Belt-and-braces: json.dumps does NOT escape '</script>', so escape the
    # closing-tag sequence before embedding the payload inside <script>.
    spark_json = json.dumps(spark_payload).replace("</", "<\\/")

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Results table</span>
  <h1>{_h(meet.get("name") or "(unknown meet)")}</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{_h(meet.get("start_date") or "?")} – {_h(meet.get("end_date") or "?")}</span><span class="sep">·</span>
    <span>{_h(meet.get("course") or "?")}</span><span class="sep">·</span>
    <span>{_h(meet.get("venue") or "venue unknown")}</span>
  </div>
  <div class="mh-hero-actions" style="margin-top:var(--sp-4)">
    <a class="mh-cta-secondary" href="{_review_url}">&larr; Back to review</a>
  </div>
</section>

<div class="stat-block" style="margin-bottom:var(--sp-5)">
  <div class="stat"><div class="l">Swims</div><div class="v" data-mh-count="{n_swims}">{n_swims}</div></div>
  <div class="stat"><div class="l">Athletes</div><div class="v" data-mh-count="{n_athletes}">{n_athletes}</div></div>
  <div class="stat"><div class="l">Personal bests</div><div class="v" data-mh-count="{n_pb}" style="color:var(--medal)">{n_pb}</div></div>
  <div class="stat"><div class="l">Improvements</div><div class="v" data-mh-count="{n_impr}" style="color:var(--good)">{n_impr}</div></div>
</div>

<div class="card">
  <form method="get" class="filters-bar" data-no-loader="1" style="margin-bottom:0">
    <input type="hidden" name="sort" value="{_h(sort)}">
    <input type="hidden" name="order" value="{_h(order)}">
    <input type="search" name="q" value="{_h(f_q)}" placeholder="Search swimmer…"
           style="min-width:180px" aria-label="Search swimmer name">
    <select name="event" aria-label="Filter by event">{ev_opts}</select>
    <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--ink-dim)">
      <input type="checkbox" name="pb" value="1"{" checked" if f_pb else ""} style="width:auto">
      PBs &amp; improvements only
    </label>
    <button class="btn secondary" type="submit" style="font-size:13px">Apply</button>
    {clear_link}
    <span class="muted" style="font-size:12px;align-self:center;margin-left:auto">{count_line}</span>
  </form>
</div>

<div class="card" style="margin-top:var(--sp-4)">
  <table class="mh-table">
    <thead><tr>
      {_th("place", "#")}
      {_th("name", "Swimmer")}
      {_th("event", "Event")}
      {_th("age", "Age")}
      {_th("time", "Time")}
      {_th("delta", "Δ vs PB")}
      <th>Progress</th>
    </tr></thead>
    <tbody>{body_rows or no_match_row}</tbody>
  </table>
  <p class="muted" style="font-size:11px;margin:12px 2px 0">
    Sparkline shows this athlete's time for the event over time &mdash; higher is faster.
    Delta badges compare each swim to the athlete's prior best <em>on record</em>.
  </p>
</div>

<script>
(function(){{
  var DATA = {spark_json};
  function cssColor(name, fb){{
    try {{
      var el=document.createElement('span');
      el.style.cssText='color:var('+name+');position:absolute;visibility:hidden';
      document.body.appendChild(el);
      var c=getComputedStyle(el).color; document.body.removeChild(el);
      return c||fb;
    }} catch(e){{ return fb; }}
  }}
  var ACCENT=cssColor('--lane','#D4FF3A'), MEDAL=cssColor('--medal','#F4D58D');
  function draw(cv){{
    var s=DATA[cv.getAttribute('data-spark')];
    if(!s||!s.t||s.t.length<2) return;
    var dpr=window.devicePixelRatio||1;
    var w=cv.clientWidth||104, h=cv.clientHeight||28, pad=3;
    cv.width=Math.round(w*dpr); cv.height=Math.round(h*dpr);
    var ctx=cv.getContext('2d'); if(!ctx) return;
    ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,w,h);
    var t=s.t, n=t.length, mn=Math.min.apply(null,t), mx=Math.max.apply(null,t), span=(mx-mn)||1;
    function X(i){{ return pad + (w-2*pad)*(n===1?0.5:i/(n-1)); }}
    function Y(v){{ return pad + (h-2*pad)*((v-mn)/span); }}
    ctx.lineWidth=1.5; ctx.lineJoin='round'; ctx.lineCap='round'; ctx.strokeStyle=ACCENT;
    ctx.beginPath();
    for(var i=0;i<n;i++){{ var px=X(i), py=Y(t[i]); i?ctx.lineTo(px,py):ctx.moveTo(px,py); }}
    ctx.stroke();
    var ci=(s.cur>=0&&s.cur<n)?s.cur:n-1;
    ctx.fillStyle=(s.kind==='pb'||s.kind==='matched')?MEDAL:ACCENT;
    ctx.beginPath(); ctx.arc(X(ci),Y(t[ci]),2.4,0,6.2832); ctx.fill();
  }}
  function drawAll(){{ var c=document.querySelectorAll('canvas.mh-spark'); for(var i=0;i<c.length;i++) draw(c[i]); }}
  drawAll();
  var rt; window.addEventListener('resize', function(){{ clearTimeout(rt); rt=setTimeout(drawAll,150); }});
}})();
</script>
"""
    return W._layout(f"Results — {meet.get('name') or run_id}", body, active="create")


def spotlight_build(run_id, swimmer_key):
    """Take the achievements the user has *approved* on the spotlight
    page and turn them into a single composite post draft saved as a
    stub pack. Lets the user pick which moments go into the post by
    approving them first. Accepts an optional ``tone`` field (warm-club /
    hype / data-led) — empty means the organisation's brand voice."""
    try:
        from mediahub.club_platform.stub_pack_store import (
            list_packs,
            load_pack,
            save_pack,
            update_pack,
        )
    except ImportError:
        return W._recovery_page(
            "Spotlight unavailable",
            "The club_platform module isn't loaded on this deployment, so "
            "spotlight posts can't be built. Other parts of MediaHub still "
            "work; ask your operator to enable the club_platform extra.",
            eyebrow="Athlete spotlight",
            primary_cta=("Back to Create", url_for("make_page")),
            secondary_cta=("System status", url_for("status_page")),
            code=501,
        )
    tone = (request.form.get("tone") or "").strip()
    if tone not in ("", "warm-club", "hype", "data-led"):
        tone = ""
    result, err = W._compose_spotlight_caption(run_id, swimmer_key, tone=tone)
    if err is not None:
        return err

    card = {
        "platform": "Instagram",
        "caption": result["caption"],
        "hashtags": ["#spotlight", "#swimming"],
        # D-25: prompt-led drafts carry no real model confidence — leave it
        # unset so the honest "% conf" badge doesn't render a fabricated one.
        "confidence": None,
        "notes": (
            f"Composed from {result['n_approved']} approved achievement(s) "
            f"for {result['swimmer_name']}."
        ),
        "status": "queue",
    }
    _active_pid = W._active_profile_id()
    _form_data = {
        "free_text": f"Spotlight — {result['swimmer_name']}",
        "source": "athlete_spotlight",
        "swimmer_name": result["swimmer_name"],
        "meet_name": result["meet_name"],
        "run_id": run_id,
        "swimmer_key": swimmer_key,
        "n_approved": result["n_approved"],
        "n_pbs": result["n_pbs"],
        "n_medals": result["n_medals"],
        "tone": tone,
        "results_lines": result["results_lines"],
    }

    # Idempotency: re-building the same swimmer's spotlight refreshes the
    # existing draft in place rather than minting a duplicate — a double-
    # click or a deliberate rebuild would otherwise litter /drafts with
    # clones keyed on the same (run_id, swimmer_key). Preserve the existing
    # card's approval status (and update_pack leaves any planned_date
    # untouched) so a rebuild never silently un-approves or unschedules a
    # draft the reviewer already actioned.
    existing = None
    for _meta in list_packs(limit=200):
        rec = load_pack(_meta["pack_id"])
        if not rec or not W._can_access_pack(rec, _active_pid):
            continue
        _fd = rec.get("form_data") or {}
        if (
            _fd.get("source") == "athlete_spotlight"
            and str(_fd.get("run_id") or "") == str(run_id)
            and str(_fd.get("swimmer_key") or "") == str(swimmer_key)
        ):
            existing = rec
            break

    if existing is not None:
        _prev_card = (existing.get("cards") or [{}])[0]
        card["status"] = _prev_card.get("status") or "queue"
        update_pack(existing["pack_id"], cards=[card], form_data_updates=_form_data)
        return redirect(url_for("stub_pack_view", pack_id=existing["pack_id"]))

    saved = save_pack(
        "free_text",  # reuses the stub-pack list; tagged in form_data
        _form_data,
        [card],
        profile_id=_active_pid,
    )
    return redirect(url_for("stub_pack_view", pack_id=saved["pack_id"]))


def spotlight_landing():
    try:
        from mediahub.club_platform.athlete_spotlight import list_swimmers_in_run
    except ImportError:
        return W._recovery_page(
            "Spotlight unavailable",
            "The club_platform module isn't loaded on this deployment, so "
            "spotlights can't be browsed. Other parts of MediaHub still "
            "work; ask your operator to enable the club_platform extra.",
            eyebrow="Athlete spotlight",
            primary_cta=("Back to Create", url_for("make_page")),
            secondary_cta=("System status", url_for("status_page")),
            code=501,
        )

    # List recent runs that have a recognition report. DB-read is
    # fail-soft so a corrupted data.db or missing schema doesn't 500
    # the spotlight landing page — the user gets a recovery hero
    # instead of a stack trace.
    #
    # TENANT ISOLATION: scope the picker to the active organisation's
    # runs (plus legacy untagged runs, which stay readable per the
    # _can_access_run philosophy). Without this filter the dropdown
    # leaked every tenant's meet names + run ids, and a tampered
    # ?run_id= surfaced another club's full swimmer roster (PII).
    _active_pid = W._active_profile_id()
    recent_runs: list = []
    db_failed = False
    # Spotlight is a *fresh-moments* surface: by default it only offers
    # meets from the last 31 days of runs. C-10: ?older=1 lifts that cutoff
    # so an older meet stays reachable (the hint below links the toggle).
    # created_at is a tz-aware isoformat() string, so the cutoff is computed
    # the same way and compared lexically (ISO-8601 sorts lexically for a
    # fixed shape) — never SQLite datetime(), whose space/no-offset format
    # wouldn't compare cleanly against the stored "T…+00:00".
    from datetime import timedelta as _td

    show_older = request.args.get("older") == "1"
    _spot_cutoff = (datetime.now(timezone.utc) - _td(days=31)).isoformat()
    _where = ["status='done'"]
    _params: list = []
    if not show_older:
        _where.append("created_at >= ?")
        _params.append(_spot_cutoff)
    if _active_pid:
        # TENANT ISOLATION (see comment above); without an active org
        # (pre-onboarding sandbox / tests) there's nothing to isolate
        # against, so list everything in-window.
        _where.append("(profile_id = ? OR profile_id IS NULL OR profile_id = '')")
        _params.append(_active_pid)
    # The recent view keeps its tight shortlist; the older view lists up
    # to 100 (matching Activity) so lifting the cutoff actually surfaces
    # older meets for busy clubs.
    _spot_limit = 100 if show_older else 20
    try:
        conn = W._db()
        try:
            recent_runs = conn.execute(
                "SELECT id, meet_name, file_name, created_at FROM runs "
                "WHERE " + " AND ".join(_where) + " "
                f"ORDER BY created_at DESC LIMIT {_spot_limit}",
                tuple(_params),
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        W.log.warning("spotlight: runs DB unreachable: %s", e)
        db_failed = True

    # Self-heal stale rows: a run whose JSON is gone was deleted (or
    # half-deleted by an older version) — it must not appear in the
    # picker, and the orphaned DB row gets pruned so it stays gone.
    _stale_ids = [
        r["id"]
        for r in recent_runs
        if not (W.RUNS_DIR / f"{r['id']}.json").exists()
        and not (W.RUNS_DIR / str(r["id"]) / "run.json").exists()
    ]
    if _stale_ids:
        try:
            conn = W._db()
            conn.executemany("DELETE FROM runs WHERE id = ?", [(i,) for i in _stale_ids])
            conn.commit()
            conn.close()
        except Exception as e:  # noqa: BLE001
            W.log.warning("spotlight: stale-run prune failed: %s", e)
        _stale_set = set(_stale_ids)
        recent_runs = [r for r in recent_runs if r["id"] not in _stale_set]

    run_id_param = request.args.get("run_id", "")
    # Path-traversal guard: unlike the <run_id> route converter (which
    # rejects slashes), this query param reaches the shared _load_run
    # helper — which builds RUNS_DIR / f"{run_id}.json" — completely
    # unfiltered. A tampered ?run_id=../../<dir>/victim would otherwise
    # escape DATA_DIR and reflect an arbitrary JSON file's swimmer roster
    # (PII) onto the page. Real run ids are uuid hex, so any separator or
    # ".." means the value is hostile: treat it as "no meet selected".
    if run_id_param and ("/" in run_id_param or "\\" in run_id_param or ".." in run_id_param):
        run_id_param = ""

    # Empty state when no meets have been processed yet
    if not recent_runs:
        if db_failed:
            empty_body = (
                '<section class="mh-hero" data-lane="01" style="padding-top:var(--sp-9);padding-bottom:var(--sp-8)">'
                '<span class="mh-hero-eyebrow">Athlete spotlight</span>'
                '<h1>Couldn&rsquo;t load your <em class="editorial">meets</em>.</h1>'
                '<p class="lede">'
                "The runs database wasn't readable on this deployment, "
                "so the meet picker is empty. Try refreshing &mdash; if it "
                "keeps happening, ask your operator to check the data volume."
                "</p>"
                '<div class="mh-hero-actions">'
                f'<a class="mh-cta-primary" href="{url_for("spotlight_landing")}">Refresh &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{url_for("home")}">Back to home</a>'
                "</div>"
                "</section>"
            )
            return W._layout("Athlete Spotlight", empty_body, active="create")
        # C-10: with the 31-day window on, a club whose meets are all
        # older would otherwise hit this hero with no way to reach them.
        _older_cta = (
            ""
            if show_older
            else f'<a class="mh-cta-secondary" href="{url_for("spotlight_landing", older=1)}">Show older meets</a>'
        )
        empty_body = (
            '<section class="mh-hero" data-lane="01" style="padding-top:var(--sp-9);padding-bottom:var(--sp-8)">'
            '<span class="mh-hero-eyebrow">Athlete spotlight</span>'
            '<h1>One swimmer.<br><em class="editorial">One story.</em></h1>'
            '<p class="lede">'
            "Upload a meet first, and every swimmer in your club becomes "
            "a single-athlete content pack — every achievement, ranked."
            "</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{url_for("upload")}">Upload a meet &rarr;</a>'
            f'<a class="mh-cta-secondary" href="{url_for("make_page")}">All input types</a>'
            f"{_older_cta}"
            "</div>"
            "</section>"
        )
        return W._layout("Athlete Spotlight", empty_body, active="create")

    runs_opts = '<option value="">Select a meet&hellip;</option>'
    for r in recent_runs:
        sel = "selected" if r["id"] == run_id_param else ""
        label = _h(r["meet_name"] or r["file_name"] or r["id"])
        runs_opts += f'<option value="{_h(r["id"])}" {sel}>{label}</option>'

    swimmers_html = ""
    # When scoped to an accessible run, the meet-recap view switch lets the
    # user toggle back to Review & approve for the same meet (set below).
    _recap_tabs = ""
    if run_id_param:
        run_data = W._load_run(run_id_param)
        # Tenant isolation: a tampered ?run_id= pointing at another
        # org's run must not surface that org's swimmer roster (PII).
        # Mirror the guard used by /review, /pack, /audit.
        if run_data and not W._can_access_run(run_id_param, run_data, _active_pid):
            run_data = None
        if run_data:
            _recap_tabs = W._render_meet_recap_tabs(run_id_param, "spotlight")
            # A malformed run_data (missing recognition_report keys,
            # weird achievement shapes) would otherwise bubble out of
            # list_swimmers_in_run and 500 the page.
            try:
                swimmers = list_swimmers_in_run(run_data)
            except Exception as e:
                W.log.warning(
                    "spotlight: list_swimmers_in_run failed for %s: %s",
                    run_id_param,
                    e,
                )
                swimmers = []
            if swimmers:
                _review_url = url_for("review", run_id=run_id_param)
                # UI2.2: the run's club for the athlete-avatar tooltips.
                _sp_club = (
                    run_data.get("profile_display") or run_data.get("club_filter") or ""
                ).strip()
                # Bound the render: a big multi-club invitational can list
                # hundreds of swimmers (~1.6KB of card markup each -> an
                # 800KB+ page), so cap the grid to the most content-worthy
                # names (list_swimmers_in_run already sorts by achievement
                # count) and point to the full meet review for the rest.
                # Realistic single-club rosters sit well under the cap and
                # are never truncated.
                _ROSTER_CAP = 120
                _total_sw = len(swimmers)
                _shown_sw = swimmers[:_ROSTER_CAP]
                swimmers_html = f'<div style="margin-top:20px"><h2>Swimmers in this meet <span class="muted" style="font-weight:400;font-size:13px">({_total_sw})</span></h2>'
                swimmers_html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:12px">'
                for sw in _shown_sw:
                    sp_url = url_for(
                        "spotlight_view", run_id=run_id_param, swimmer_key=sw["swimmer_key"]
                    )
                    _n_ach = sw["n_achievements"]
                    _ach_label = f"{_n_ach} achievement{'s' if _n_ach != 1 else ''}"
                    # Decorative chip (it lives inside the card link, so it
                    # stays aria-hidden / out of the tab order); the link's
                    # own text carries the same name + count for AT.
                    _sw_avatar = W._athlete_avatar(
                        sw["swimmer_name"],
                        club=_sp_club,
                        stat=_ach_label,
                        focusable=False,
                        size=38,
                    )
                    swimmers_html += f"""
<a href="{sp_url}" style="display:flex;align-items:center;gap:12px;padding:14px;background:var(--panel2);border:1px solid var(--border);border-radius:var(--radius-sm);text-decoration:none;transition:border-color 150ms">
  {_sw_avatar}
  <div style="display:flex;flex-direction:column;gap:4px;min-width:0">
    <div style="font-size:14px;font-weight:600;color:var(--ink)">{_h(sw["swimmer_name"])}</div>
    <div style="font-size:12px;color:var(--ink-dim)">{_ach_label}</div>
  </div>
</a>"""
                swimmers_html += "</div>"
                if _total_sw > len(_shown_sw):
                    swimmers_html += (
                        '<p class="muted" style="margin-top:12px;font-size:13px">'
                        f"Showing the {len(_shown_sw)} swimmers with the most "
                        f'achievements. <a href="{_review_url}" style="color:var(--ink)">'
                        "Open the full meet review</a> to reach the other "
                        f"{_total_sw - len(_shown_sw)}.</p>"
                    )
                swimmers_html += "</div>"
            else:
                swimmers_html = '<div class="card"><p class="muted">No achievements found for this run. The recognition report may not be available.</p></div>'
        elif run_id_param:
            # A meet was selected but couldn't be opened — a run the active
            # org can't access, or a corrupt/unreadable data file. Surface an
            # honest message instead of a silent dead-end (the dropdown
            # selected, no roster, no explanation).
            swimmers_html = (
                '<div class="card"><p class="muted">We couldn&rsquo;t open that '
                "meet. It may have been processed on an older version, be "
                "owned by another organisation, or its data file may be "
                "unreadable. Pick another meet above.</p></div>"
            )

    change_js = url_for("spotlight_landing")
    # C-10: the window hint states the cutoff and links the toggle, so the
    # 31-day filter is a choice rather than a silent limit. The toggle
    # keeps the current meet selection; the hidden input keeps the mode
    # across the picker's own GET submit.
    _toggle_args = {"run_id": run_id_param} if run_id_param else {}
    if show_older:
        window_hint = (
            "Showing all processed meets. "
            f'<a href="{url_for("spotlight_landing", **_toggle_args)}">Show the last 31 days only</a>. '
            "A meet deleted in Settings disappears from here too."
        )
        older_field = '<input type="hidden" name="older" value="1">'
    else:
        window_hint = (
            "Showing meets from the last 31 days. "
            f'<a href="{url_for("spotlight_landing", older=1, **_toggle_args)}">Show older meets</a>. '
            "A meet deleted in Settings disappears from here too."
        )
        older_field = ""
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Athlete spotlight</span>
  <h1>One swimmer. <em class="editorial">One story.</em></h1>
  <p class="lede">Pick a processed meet, then pick a swimmer. We pull every achievement they earned into a single-athlete content pack ranked by impact.</p>
</section>

{_recap_tabs}

<div class="card">
  <h2>Choose a meet</h2>
  <p class="muted" style="margin-top:0;font-size:13px">{window_hint}</p>
  <form method="get" action="{url_for("spotlight_landing")}">
    {older_field}
    <label for="sp-meet-select" class="mh-sr-only">Choose a processed meet</label>
    <select id="sp-meet-select" name="run_id" aria-label="Choose a processed meet" onchange="this.form.submit()" style="max-width:480px">
      {runs_opts}
    </select>
    <noscript><button class="btn" type="submit" style="margin-top:var(--sp-3)">Load swimmers &rarr;</button></noscript>
  </form>
  {swimmers_html}
</div>
"""
    return W._layout("Athlete Spotlight", body, active="create")


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
def spotlight_view(run_id, swimmer_key, run_data):
    try:
        from mediahub.club_platform.athlete_spotlight import build_spotlight_pack
    except ImportError:
        return W._recovery_page(
            "Spotlight unavailable",
            "The club_platform module isn't loaded on this deployment, so "
            "this spotlight can't be opened. Other parts of MediaHub still "
            "work; ask your operator to enable the club_platform extra.",
            eyebrow="Athlete spotlight",
            primary_cta=("Back to Create", url_for("make_page")),
            secondary_cta=("System status", url_for("status_page")),
            code=501,
        )

    # run_data is loaded once and tenant-gated by @require_run (finding
    # #18); require_exists routes a missing/foreign run to the "Run not
    # found" recovery deny above before the body runs.

    # A malformed run_data shape would otherwise bubble out of
    # build_spotlight_pack and 500 the page; treat it as "no pack"
    # so the recovery hero below renders.
    try:
        pack = build_spotlight_pack(run_data, swimmer_key)
    except Exception as e:
        W.log.warning(
            "spotlight_view: build_spotlight_pack failed for %s/%s: %s",
            run_id,
            swimmer_key,
            e,
        )
        pack = None
    if not pack:
        return W._recovery_page(
            "Swimmer not found",
            f'No achievements were recorded for "{swimmer_key}" in this meet. Pick another swimmer, or open the meet review to see who\'s in the recognition report.',
            eyebrow="Athlete spotlight",
            primary_cta=(
                "Choose another swimmer",
                url_for("spotlight_landing") + f"?run_id={run_id}",
            ),
            secondary_cta=("Open review", url_for("review", run_id=run_id)),
        )

    _back_url = url_for("spotlight_landing") + f"?run_id={run_id}"
    _review_url = url_for("review", run_id=run_id)
    _pack_url = url_for("content_pack", run_id=run_id)

    # Load workflow state for this run so spotlight cards reflect current status.
    wf_states = {}
    try:
        ws = W._get_wf_store()
        if ws:
            wf_states = ws.load(run_id)
    except Exception:
        wf_states = {}
    # UI 1.25 — one indexed query for every card's reaction tally.
    _react_counts = W._reaction_counts_for_run(run_id)

    # F11: a unique per-row id so a duplicate swim_id (or two aggregate rows
    # sharing an sp:type:event key) get independent workflow state instead
    # of colliding. Keyed by object identity because the same ``ra`` dicts
    # flow through the approved/other splits below; the first occurrence
    # keeps its bare id (back-compat), later duplicates get a ~n suffix.
    _sp_card_ids = {
        id(ra): uid
        for ra, uid in zip(
            pack["ranked_achievements"],
            W._unique_card_ids(pack["ranked_achievements"], base_fn=W._card_base_id_for),
        )
    }

    def _sp_card_id(ra: dict) -> str:
        return _sp_card_ids.get(id(ra)) or W._card_base_id_for(ra.get("achievement") or {})

    # Render achievements with the same approve strip the meet recap
    # uses (_render_wf_actions): outline "Approve" until approved,
    # filled "Approved ✓" after, Re-queue to undo. Approved rows are
    # grouped at the top, mirroring the content builder.
    def _sp_row_html(ra: dict) -> str:
        a = ra.get("achievement", {})
        band = ra.get("quality_band", "nice")
        prio = ra.get("priority", 0.0)
        rank = ra.get("rank", 0)
        band_cls = {
            "elite": "warn",
            "strong": "info",
            "story": "",
            "nice": "",
            "not_worthy": "bad",
        }.get(band, "")
        headline = _h(a.get("headline", ""))
        angle = _h(W._humanise(a.get("angle_hint", "") or ""))
        event = _h(a.get("event", ""))
        atype = _h(W._humanise(a.get("type", "")))
        # Row identity (workflow state / reactions / DOM) on the unique
        # ~n-deduped id; the graphic button below keeps the bare swim_id so
        # it still resolves in the recognition report.
        card_id_raw = _sp_card_id(ra)
        card_id_safe = _h(card_id_raw)

        wf = wf_states.get(card_id_raw)
        wf_status = wf.status.value if wf else "queue"

        cap_text = headline
        if angle:
            # Real newlines (not the literal backslash-n a normal f-string's
            # "\\n" would emit) so the hidden span's textContent — which
            # copySpotlightCaption copies verbatim to the clipboard — carries
            # actual line breaks between the headline and the angle.
            cap_text = f"{headline}\n\n{angle}"

        # "Create graphic" — only for achievements with a real swim_id,
        # which api_create_graphic can resolve in the run's recognition
        # report. Aggregate rows (synthetic "sp:..." ids) have no single
        # swim to render, so they keep caption-only.
        _sp_swim_id = a.get("swim_id")
        sp_graphic_btn = ""
        sp_visual_panel = ""
        if _sp_swim_id:
            _sp_g_url = url_for("api_create_graphic", run_id=run_id, card_id=_sp_swim_id)
            # JS-context safety: the card id derives from swim_id, which
            # carries the swimmer key (e.g. a surname like O'Brien) verbatim,
            # so it can contain an apostrophe or other JS-breaking chars.
            # _h() (HTML-escape) is the WRONG escaping here — the browser
            # decodes &#39; back to ' before the JS string is compiled, so an
            # apostrophe would break out of the literal (a broken control,
            # and a stored-XSS vector from a crafted results file). Encode
            # for the JS context first (json.dumps) then the HTML-attribute
            # context (_h), the standard two-layer safe pattern.
            _g_url_js = _h(json.dumps(str(_sp_g_url)))
            _card_id_js = _h(json.dumps(card_id_raw))
            sp_graphic_btn = (
                f'<button class="btn secondary" style="font-size:11px;padding:4px 10px" '
                f'onclick="mhCreateGraphic(this, {_g_url_js}, {_card_id_js})">'
                f"&#x2726; Create graphic</button>"
            )
            sp_visual_panel = (
                f'<div class="visual-panel" data-card="{card_id_safe}" '
                f'style="display:none;margin-top:10px;padding:12px;'
                f"background:color-mix(in oklab, var(--lane) 4%, transparent);border:1px solid var(--border);"
                f'border-radius:8px"></div>'
            )

        return f"""
<div class="sp-row ach-row" data-card="{card_id_safe}" data-status="{_h(wf_status)}" style="padding:14px 0;border-bottom:1px solid var(--border);display:flex;gap:14px;align-items:flex-start">
  <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px">#{rank}</div>
  <div style="flex:1">
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap">
      <span class="tag {band_cls}" style="font-size:10px">{band.upper()}</span>
      <span class="tag info" style="font-size:10px">{atype}</span>
      <span class="muted" style="font-size:11px">{prio:.2f}</span>
    </div>
    <div style="font-size:14px;font-weight:600;color:var(--ink)">{event}</div>
    <div style="font-size:13px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">
      {W._render_wf_actions(run_id, card_id_raw, wf_status)}
      <button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="copySpotlightCaption(this)">Copy caption</button>
      {sp_graphic_btn}
      <span style="flex:1;min-width:8px"></span>
      {W._render_reactions(run_id, card_id_raw, _react_counts)}
      <span class="sp-cap-src" style="display:none">{cap_text}</span>
    </div>
    {sp_visual_panel}
  </div>
</div>"""

    def _sp_status(ra: dict) -> str:
        wf = wf_states.get(_sp_card_id(ra))
        return wf.status.value if wf else "queue"

    _approved_ras = [
        ra for ra in pack["ranked_achievements"] if _sp_status(ra) in ("approved", "posted")
    ]
    _other_ras = [
        ra for ra in pack["ranked_achievements"] if _sp_status(ra) not in ("approved", "posted")
    ]
    approved_rows = "".join(_sp_row_html(ra) for ra in _approved_ras)
    other_rows = "".join(_sp_row_html(ra) for ra in _other_ras)
    approved_section = (
        f'<div class="card"><h2>Going into the post '
        f'<span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(_approved_ras)} approved</span></h2>'
        f"{approved_rows}</div>"
        if _approved_ras
        else ""
    )

    from mediahub.brand.tone import TONE_META as _SP_TONE_META

    _sp_tone_opts = '<option value="">Brand voice (default)</option>' + "".join(
        f'<option value="{_h(t.value)}">{_h(m["label"])}</option>' for t, m in _SP_TONE_META.items()
    )

    # H-23: with nothing approved, "Build spotlight post" 400s on a full page
    # and loses the tone selection. Disable the button and surface the
    # already-present helper line as the reason; the server check stays as a
    # fallback for the (rare) approve-elsewhere race.
    _sp_has_approved = bool(_approved_ras)
    _sp_build_attr = "" if _sp_has_approved else " disabled"
    _sp_build_title = (
        "Build the post from the approved achievements"
        if _sp_has_approved
        else "Approve at least one achievement below to build the post"
    )

    # UI2.2: the hero athlete avatar + tooltip. Standalone, so it's
    # keyboard-reachable (focusable) and exposes the same grounded summary
    # to assistive tech via aria-label. Club + haul come from the run and
    # the spotlight pack's band counts — all real figures, never invented.
    _hero_club = (run_data.get("profile_display") or run_data.get("club_filter") or "").strip()
    _hero_n = pack["n_achievements"]
    _hero_stat = f"{_hero_n} moment{'s' if _hero_n != 1 else ''}"
    if pack["n_elite"]:
        _hero_stat = f"{pack['n_elite']} elite · {_hero_stat}"
    elif pack["n_strong"]:
        _hero_stat = f"{pack['n_strong']} strong · {_hero_stat}"
    _hero_avatar = W._athlete_avatar(
        pack["swimmer_name"],
        club=_hero_club,
        stat=_hero_stat,
        focusable=True,
        size=52,
    )

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Athlete spotlight</span>
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
    {_hero_avatar}
    <h1 style="margin:0">{_h(pack["swimmer_name"])}</h1>
  </div>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{_h(pack["meet_name"])}</span><span class="sep">/</span>
    <a href="{_back_url}" style="color:var(--ink-muted);text-decoration:none">&larr; Swimmer list</a><span class="sep">/</span>
    <a href="{_review_url}" style="color:var(--ink-muted);text-decoration:none">Full meet review</a>
  </div>
</section>

<div class="card">
  <div class="stat-block">
    <div class="stat medal"><div class="l">Elite</div><div class="v">{pack["n_elite"]}</div></div>
    <div class="stat live"><div class="l">Strong</div><div class="v">{pack["n_strong"]}</div></div>
    <div class="stat"><div class="l" style="color:var(--lane)">Story</div><div class="v" style="color:var(--lane)">{pack["n_story"]}</div></div>
    <div class="stat"><div class="l">Total</div><div class="v">{pack["n_achievements"]}</div></div>
  </div>
  <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
    <form method="post" action="{url_for("spotlight_build", run_id=run_id, swimmer_key=swimmer_key)}" style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap"
          data-loader-text="Composing the spotlight post">
      <label for="sp-tone-select" class="mh-sr-only">Caption tone for the spotlight post</label>
      <select id="sp-tone-select" name="tone" aria-label="Caption tone for the spotlight post" style="font-size:12px;max-width:220px" title="Caption tone for the spotlight post">{_sp_tone_opts}</select>
      <button type="submit" class="btn"{_sp_build_attr} title="{_h(_sp_build_title)}" style="font-size:13px">Build spotlight post from approved cards &rarr;</button>
    </form>
    <a class="btn secondary" href="{_pack_url}" style="font-size:13px">Open content builder &rarr;</a>
    <span class="muted" style="font-size:12px">Approve the achievements below to choose which go into the post.</span>
  </div>
</div>

{approved_section}

<div class="card">
  <h2>{"More achievements" if _approved_ras else "Achievements"}</h2>
  {other_rows or '<p class="muted">Everything is approved. Build the post above.</p>' if _approved_ras else (other_rows or '<p class="muted">No achievements.</p>')}
</div>

<script>
function copySpotlightCaption(btn) {{
  // Locate the caption span relative to the clicked button (both live in the
  // same .sp-row) rather than by an id built from user data — the card id can
  // carry an apostrophe (e.g. a surname like O'Brien) which would break an
  // interpolated selector.
  var row = btn.closest('.sp-row');
  var span = row ? row.querySelector('.sp-cap-src') : null;
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
    body += W._VISUAL_PANEL_JS
    return W._layout(f"Spotlight: {pack['swimmer_name']}", body, active="create")


def add_input_page():
    # The "Add Input" tab was merged into "Create". The route stays
    # as a redirect alias so old bookmarks and external links still
    # resolve to the unified chooser on /make.
    return redirect(url_for("make_page"), code=301)


@W.require_run(
    deny=lambda: (
        W._layout("Not found", '<div class="empty">Repurpose pack not found.</div>'),
        404,
    )
)
def turn_into_pack_view(run_id, pack_id):
    """Render a saved Turn-Into pack with the 8 artefacts."""
    # Turn-Into packs are namespaced under <run_id>/<pack_id> on
    # disk, so the run's owner check is the right gate.
    from mediahub.turn_into import load_pack

    pack = load_pack(run_id, pack_id, base_dir=W.DATA_DIR / "turn_into_packs")
    if pack is None:
        return W._layout("Not found", '<div class="empty">Repurpose pack not found.</div>'), 404

    _review_url = url_for("review", run_id=run_id)
    _api_url = url_for("api_turn_into", run_id=run_id)
    _edit_api = url_for("api_turn_into_edit_caption", run_id=run_id, pack_id=pack_id)
    meet_name = _h(pack.get("meet_name", ""))
    gen_at = _h(pack.get("generated_at", ""))

    artefacts = pack.get("artefacts") or []
    skipped = pack.get("skipped") or []

    # --- Skipped notice band
    skipped_html = ""
    if skipped:
        items = "".join(
            f"<li><strong>{_h(s.get('type', ''))}</strong>: {_h(s.get('reason', ''))}</li>"
            for s in skipped
        )
        skipped_html = (
            '<div class="card" style="border-color:var(--warn);background:rgba(245,158,11,0.04)">'
            '<h2 style="margin-top:0">Skipped pieces</h2>'
            f'<ul style="margin:0">{items}</ul>'
            "</div>"
        )

    # Human-friendly labels for internal artefact-type slugs so the
    # tag chips don't expose snake_case engineering enums.
    _ARTEFACT_LABEL = {
        "meet_recap": "Meet recap",
        "swimmer_spotlight": "Swimmer spotlight",
        "athlete_spotlight": "Athlete spotlight",
        "event_preview": "Event preview",
        "sponsor_activation": "Sponsor post",
        # Legacy artefact slugs (pre-ADR-0013) still present in stored
        # media descriptions / operating profiles.
        "weekend_preview": "Event preview",
        "sponsor_post": "Sponsor post",
        "session_update": "Session update",
        "x_thread": "X / Twitter thread",
        "twitter_thread": "Twitter thread",
        "linkedin_post": "LinkedIn post",
        "free_text": "Free text brief",
        "parent_newsletter": "Parent newsletter",
        "club_report": "Club website report",
        "coach_dm": "Coach DM",
        "dm_pack": "DM pack",
    }

    # --- Artefact cards
    cards_html = ""
    for art_idx, art in enumerate(artefacts):
        atype = art.get("type", "")
        atype_label = _ARTEFACT_LABEL.get(atype, atype.replace("_", " ").capitalize() or "Piece")
        title = _h(art.get("title", atype_label))
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
                "background:rgba(245,158,11,0.12);border:1px solid var(--warn);"
                f'border-radius:8px;font-weight:600;color:var(--warn)">{_h(draft)}</div>'
            )

        # Fallback badge — honest marker that this artefact shipped the
        # deterministic template copy (a provider error prevented an
        # AI-written version). Rendered only when the pack carries the
        # per-artefact `source` field (old packs omit it → no badge).
        fallback_html = ""
        if art.get("source") == "fallback":
            fallback_html = (
                '<div style="margin-bottom:12px;padding:10px 14px;'
                "background:rgba(245,158,11,0.12);border:1px solid var(--warn);"
                'border-radius:8px;font-weight:600;color:var(--warn)">'
                "&#9888; Template copy &mdash; the AI writer was unavailable, so this "
                "piece fell back to a deterministic draft. Review before posting."
                "</div>"
            )

        # Caption editor blocks &mdash; one per key. J-4: every block gets
        # a Copy button (copyText) so a finished piece is one click from
        # the clipboard instead of a select-all-and-copy dead end.
        caption_blocks = ""
        for cap_key, cap_val in captions.items():
            if cap_key == "x_thread" and isinstance(cap_val, list):
                # Special-case: numbered thread of posts.
                sub = ""
                for ti, post in enumerate(cap_val):
                    post_chars = len(post or "")
                    cls = "good" if post_chars <= 280 else "bad"
                    _ta_id = f"ti-cap-{art_idx}-t{ti}"
                    sub += (
                        f'<div style="margin-bottom:10px">'
                        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
                        f'<span class="muted" style="font-size:11px">Post {ti + 1}</span>'
                        f'<span style="display:inline-flex;gap:6px;align-items:center">'
                        f'<button class="btn secondary" style="font-size:10px;padding:2px 8px" '
                        f"onclick=\"copyText(this,'{_ta_id}')\">Copy</button>"
                        f'<span class="tag {cls}" style="font-size:10px">{post_chars}/280</span>'
                        f"</span>"
                        f"</div>"
                        f'<textarea class="ti-cap" id="{_ta_id}" data-artefact="{art_idx}" '
                        f'data-thread="{ti}" '
                        f'style="width:100%;min-height:60px;font-size:13px;'
                        f"padding:8px;border:1px solid var(--border);border-radius:6px;"
                        f'background:var(--bg);color:var(--ink);font-family:inherit">'
                        f"{_h(post)}</textarea>"
                        f"</div>"
                    )
                caption_blocks += (
                    '<div style="margin-bottom:14px">'
                    f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;'
                    f'color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:8px">X thread '
                    f"({len(cap_val)} posts, &le;280 chars each)</div>"
                    f"{sub}"
                    "</div>"
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
            _key_slug = re.sub(r"[^A-Za-z0-9_-]", "-", cap_key)
            _ta_id = f"ti-cap-{art_idx}-{_key_slug}"
            caption_blocks += (
                '<div style="margin-bottom:14px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
                f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;'
                f'color:var(--ink-muted);letter-spacing:0.5px">'
                f"{_h(key_label)}{cap_limit_html}</div>"
                f'<button class="btn secondary" style="font-size:10px;padding:2px 8px" '
                f"onclick=\"copyText(this,'{_ta_id}')\">Copy</button>"
                f"</div>"
                f'<textarea class="ti-cap" id="{_ta_id}" data-artefact="{art_idx}" '
                f'data-key="{_h(cap_key)}" '
                f'style="width:100%;min-height:80px;font-size:13px;'
                f"padding:10px;border:1px solid var(--border);border-radius:6px;"
                f'background:var(--bg);color:var(--ink);font-family:inherit">'
                f"{_h(cap_val)}</textarea>"
                "</div>"
            )

        # Optional sub-cards strip (e.g. spotlight series)
        sub_cards_html = ""
        if cards and atype in ("swimmer_spotlight",):
            rows = ""
            for c in cards:
                rows += (
                    '<div style="padding:10px;background:rgba(255,255,255,0.03);'
                    'border:1px solid var(--border);border-radius:8px;margin-bottom:8px">'
                    f'<div style="font-size:13px;font-weight:700">{_h(c.get("swimmer", ""))} '
                    f"&middot; {_h(c.get('event', ''))}</div>"
                    f'<div style="font-size:12px;color:var(--ink-dim);margin-top:4px">{_h(c.get("headline", ""))}</div>'
                    "</div>"
                )
            sub_cards_html = f'<div style="margin-bottom:12px">{rows}</div>'

        # Newsletter HTML preview + download (J-4: the piece's HTML was
        # view-only — a hidden textarea carries the exact source so
        # "Download HTML" hands over a ready-to-send file).
        html_preview_html = ""
        html_download_btn = ""
        if html_block:
            # Display rendered HTML in a sandboxed-ish preview area.
            # The templates module HTML-escapes the body, so it's safe here.
            html_preview_html = (
                f'<textarea id="ti-html-{art_idx}" style="display:none">{_h(html_block)}</textarea>'
                '<details style="margin-top:8px">'
                '<summary style="cursor:pointer;font-size:12px;color:var(--accent)">View HTML preview</summary>'
                f'<div style="margin-top:10px;padding:14px;border:1px dashed var(--border);'
                f'border-radius:8px;background:rgba(255,255,255,0.02)">{html_block}</div>'
                "</details>"
            )
            html_download_btn = (
                f'<button class="btn secondary" style="font-size:12px;padding:6px 14px" '
                f'onclick="tiDownloadHtml({art_idx})" '
                f'title="Download this piece as a ready-to-send .html file">Download HTML</button>'
            )

        notes_html = ""
        if notes_list:
            lis = "".join(f"<li>{_h(n)}</li>" for n in notes_list)
            notes_html = (
                '<details style="margin-top:8px">'
                '<summary style="cursor:pointer;font-size:12px;color:var(--ink-muted)">Why this piece?</summary>'
                f'<ul style="margin:8px 0 0 0;font-size:12px;color:var(--ink-dim)">{lis}</ul>'
                "</details>"
            )

        cards_html += f"""
<div class="card ti-artefact" data-type="{_h(atype)}" data-artefact-index="{art_idx}" style="margin-bottom:18px">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">
    <h2 style="margin:0">{title}</h2>
    <span class="tag info">{_h(atype_label)}</span>
  </div>
  {draft_html}
  {fallback_html}
  {sub_cards_html}
  {caption_blocks}
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class="btn" style="font-size:12px;padding:6px 14px"
            onclick="tiSaveArtefact({art_idx})">Save edits</button>
    {html_download_btn}
    <span class="ti-status" data-artefact="{art_idx}" style="font-size:11px;color:var(--ink-muted)"></span>
  </div>
  {html_preview_html}
  {notes_html}
</div>"""

    if not cards_html:
        cards_html = '<div class="empty">No pieces generated.</div>'

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Repurpose pack</span>
  <h1><span class="mh-shiny-text">{meet_name}</span></h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{len(artefacts):02d} {"piece" if len(artefacts) == 1 else "pieces"}</span><span class="sep">·</span>
    <span>generated {gen_at}</span><span class="sep">/</span>
    <a href="{_review_url}" style="color:var(--ink-muted);text-decoration:none">← Back to review</a>
  </div>
</section>

<div style="margin-bottom:var(--sp-5);display:flex;gap:var(--sp-3);flex-wrap:wrap;align-items:center">
  <button class="btn secondary" onclick="tiRegenerate(this)">&#x21BA; Regenerate pack</button>
  <span id="ti-regen-status" role="status" aria-live="polite" style="font-size:12px;color:var(--ink-muted)"></span>
</div>

{skipped_html}
{cards_html}

<script>
const TI_EDIT_API = {json.dumps(_edit_api)};
const TI_REGEN_API = {json.dumps(_api_url)};
const TI_REVIEW_URL = {json.dumps(_review_url)};

// J-4: one-click copy for each piece's caption (same behaviour as the
// grouped page's copy buttons).
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

// J-4: download a piece's HTML (the newsletter) as a ready-to-send file.
// The hidden textarea carries the exact source the engine produced.
function tiDownloadHtml(idx) {{
  var ta = document.getElementById('ti-html-' + idx);
  if (!ta) return;
  var blob = new Blob([ta.value], {{ type: 'text/html' }});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'repurpose-pack-newsletter.html';
  document.body.appendChild(a);
  a.click();
  setTimeout(function() {{ URL.revokeObjectURL(a.href); a.remove(); }}, 400);
}}

function tiSaveArtefact(idx) {{
  const root = document.querySelector('.ti-artefact[data-artefact-index="' + idx + '"]');
  if (!root) return;
  const status = root.querySelector('.ti-status');
  status.textContent = 'Saving\u2026';
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

// J-4: styled confirm (MH.confirm), a busy state on the button, and an
// inline styled status/error line — no native confirm()/alert() dead ends.
function tiRegenerate(btn) {{
  var run = function() {{
    var status = document.getElementById('ti-regen-status');
    var say = function(m, bad) {{
      if (!status) return;
      status.textContent = m || '';
      status.style.color = bad ? 'var(--bad)' : 'var(--ink-muted)';
    }};
    var origLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Regenerating\u2026';
    say('Drafting a fresh pack with live AI \u2014 usually under a minute.');
    fetch(TI_REGEN_API, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{}}),
    }}).then(r => r.json()).then(function(j) {{
      if (j && j.pack_url) {{
        say('Done \u2014 opening the new pack\u2026');
        window.location.href = j.pack_url;
        return;
      }}
      btn.disabled = false; btn.textContent = origLabel;
      say('Regenerate failed: ' + ((j && (j.user_message || j.message || j.error)) || 'unknown error'), true);
    }}).catch(function() {{
      btn.disabled = false; btn.textContent = origLabel;
      say('Regenerate failed: network error \u2014 try again.', true);
    }});
  }};
  if (window.MH && MH.confirm) {{
    MH.confirm({{title: 'Regenerate this pack?', body: 'A fresh Repurpose pack is drafted with live AI. The current pack is preserved.', confirmText: 'Regenerate', danger: false, onConfirm: run}});
  }} else {{ run(); }}
}}
</script>
"""
    return W._layout(f"Repurpose pack — {meet_name}", body, active="home")


def annotate_page(asset_id: str):
    """Standalone telestration canvas for one asset."""
    if not W._v8_ok:
        return W._recovery_page(
            "Annotate unavailable",
            "The media library isn't enabled on this deployment.",
            eyebrow="Annotate",
            primary_cta=("Back to Create", url_for("make_page")),
            code=503,
        )
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return W._recovery_page(
            "Photo not found",
            "That photo isn't in your library.",
            eyebrow="Annotate",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=404,
        )
    if not W._session_can_access_profile(a.profile_id):
        return W._recovery_page(
            "Not your photo",
            "This photo belongs to a different organisation.",
            eyebrow="Annotate",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=403,
        )
    from mediahub.web import elements_browser as _eb

    body = _eb.render_annotate_body(
        asset_url=url_for("api_media_library_file", asset_id=a.id),
        save_url=url_for("api_annotate_asset", asset_id=a.id),
        back_url=url_for("media_library_page"),
        existing=getattr(a, "annotation", None) or {},
    )
    return W._layout("Annotate", body, active="media")


def sponsor_variant_view(run_id: str, card_id: str):
    """Server-rendered sponsor variant page for one card."""
    run_data, target = W._load_run_for_card(run_id, card_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        run_data = None
        target = None
    if run_data is None:
        return W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    if target is None:
        return W._recovery_page(
            "Card not found",
            "That card isn't part of this run any more. The pack may have been regenerated since the link was shared, or the card was deleted from the review queue.",
            primary_cta=(
                "Open the content pack",
                url_for("content_pack_grouped", run_id=run_id),
            ),
            secondary_cta=("Back to the review queue", url_for("review", run_id=run_id)),
        )

    # Profile resolution: run's profile_id → session-pinned active.
    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or ""
    profile = W.load_profile(profile_id) if profile_id else None
    if profile is None:
        profile = W._active_profile()
    # PC.8: the registry's deterministic rotation decides which sponsor
    # this card carries; the legacy single sponsor_name field remains
    # the fallback when no registry is configured.
    _rotated = None
    if profile is not None:
        try:
            from mediahub.club_platform.sponsors import sponsor_for_card as _sponsor_for_card

            _rotated = _sponsor_for_card(profile, run_id, card_id)
        except Exception:
            _rotated = None
    sponsor_name = (_rotated or {}).get("name", "").strip()
    if not sponsor_name:
        body = (
            f'<p class="dim"><a href="{url_for("content_pack_grouped", run_id=run_id)}">'
            f"&larr; Back to recommendations</a></p>"
            "<h1>Sponsor variant unavailable</h1>"
            '<div class="card empty">'
            "<p>No sponsor is configured for this organisation.</p>"
            f'<p><a class="btn" href="{url_for("organisation_page")}">'
            "Add a sponsor name on the Organisation page &rarr;</a></p>"
            "</div>"
        )
        return W._layout("Sponsor variant", body, active="home")

    ach = target.get("achievement") or {}

    # ---- D-32: the render + caption used to run synchronously inside
    # this GET (30–90s cold, LLM call included) before any HTML returned.
    # The page shell now returns immediately: a cached variant renders
    # straight away; otherwise a branded progress panel mounts and the
    # background job (api_sponsor_variant_job → api_reel_job_status poll)
    # does the work. "Refresh to regenerate" became a Regenerate button
    # that starts a fresh job.
    cached = W._sponsor_variant_cached(run_id, card_id, sponsor_name)
    if cached is not None:
        img_url = url_for(
            "api_visual_png",
            vid=cached["visual_id"],
            format_name=cached.get("format_name") or "feed_portrait",
        )
        visual_block = (
            f'<img src="{_h(img_url)}" alt="Sponsor-branded variant" '
            f'style="max-width:100%;border-radius:10px;border:1px solid var(--border)"/>'
        )
        _cap_text = str(cached.get("caption") or "")
        if _cap_text:
            caption_block = (
                f'<textarea readonly style="width:100%;min-height:140px;font-size:14px;'
                f"padding:12px;border:1px solid var(--border);border-radius:8px;"
                f'background:var(--bg);color:var(--ink);font-family:inherit">'
                f"{_h(_cap_text)}</textarea>"
                f'<button class="btn" style="margin-top:8px;font-size:12px;padding:6px 14px" '
                f'onclick="navigator.clipboard.writeText(this.previousElementSibling.value);'
                f"this.textContent='Copied ✓'\">Copy caption</button>"
            )
        else:
            caption_block = (
                '<div class="empty" style="text-align:left;padding:14px">'
                f"{_h(str(cached.get('caption_message') or 'No caption was generated — use Regenerate to try again.'))}"
                "</div>"
            )
    else:
        # No-JS fallback copy; the script below replaces both panels the
        # moment the job starts.
        visual_block = (
            '<p class="muted" style="padding:14px;font-size:13px">'
            "Preparing the sponsor graphic&hellip;</p>"
        )
        caption_block = (
            '<p class="muted" style="padding:14px;font-size:13px">'
            "The caption is written alongside the graphic&hellip;</p>"
        )

    _pack_url = url_for("content_pack_grouped", run_id=run_id)
    _job_url = url_for("api_sponsor_variant_job", run_id=run_id, card_id=card_id)
    swimmer = _h(ach.get("swimmer_name") or "")
    event = _h(ach.get("event") or "")
    body = f"""
<p class="dim"><a href="{_pack_url}">&larr; Back to recommendations</a></p>
<h1 style="margin-bottom:4px">Sponsor variant &mdash; {swimmer}{(" · " + event) if event else ""}</h1>
<div style="display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:24px">
  <p class="dim" style="margin:0">Sponsor-branded result card + sponsor-acknowledging caption for <b>{_h(sponsor_name)}</b>.</p>
  <button id="sv-regen" class="btn secondary" type="button">Regenerate</button>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start">
  <div class="card">
    <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Sponsor-branded visual</h3>
    <div id="sv-visual">{visual_block}</div>
  </div>
  <div class="card">
    <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Sponsor-acknowledging caption</h3>
    <div id="sv-caption">{caption_block}</div>
  </div>
</div>
"""
    # Plain string (not an f-string) so the JS braces stay single; the two
    # dynamic values ride in via json.dumps.
    body += (
        "<script>\n(function(){\n"
        "  var jobUrl = " + json.dumps(_job_url) + ";\n"
        "  var autostart = " + ("false" if cached is not None else "true") + ";\n"
        """  var visual = document.getElementById('sv-visual');
  var caption = document.getElementById('sv-caption');
  var btn = document.getElementById('sv-regen');
  function emptyBox(text) {
    var d = document.createElement('div');
    d.className = 'empty';
    d.style.cssText = 'text-align:left;padding:14px;font-size:13px';
    d.textContent = text;
    return d;
  }
  function fillVisual(j) {
    visual.innerHTML = '';
    if (j.image_url) {
      var img = document.createElement('img');
      img.src = j.image_url;
      img.alt = 'Sponsor-branded variant';
      img.style.cssText = 'max-width:100%;border-radius:10px;border:1px solid var(--border)';
      visual.appendChild(img);
    } else {
      visual.appendChild(emptyBox(j.image_message || 'The graphic couldn\\u2019t be rendered \\u2014 try again.'));
    }
  }
  function fillCaption(j) {
    caption.innerHTML = '';
    if (j.caption) {
      var ta = document.createElement('textarea');
      ta.readOnly = true;
      ta.style.cssText = 'width:100%;min-height:140px;font-size:14px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--ink);font-family:inherit';
      ta.value = j.caption;
      var copy = document.createElement('button');
      copy.className = 'btn';
      copy.style.cssText = 'margin-top:8px;font-size:12px;padding:6px 14px';
      copy.textContent = 'Copy caption';
      copy.addEventListener('click', function(){ navigator.clipboard.writeText(ta.value); copy.textContent = 'Copied \\u2713'; });
      caption.appendChild(ta);
      caption.appendChild(copy);
    } else {
      caption.appendChild(emptyBox(j.caption_message || 'The caption couldn\\u2019t be generated \\u2014 try again.'));
    }
  }
  function restoreBtn() { if (btn) { btn.disabled = false; btn.textContent = 'Regenerate'; } }
  function fail(msg) {
    fillVisual({image_message: msg});
    fillCaption({caption_message: msg});
    restoreBtn();
  }
  function svStart() {
    if (btn) { btn.disabled = true; btn.textContent = 'Generating\\u2026'; }
    caption.innerHTML = '';
    caption.appendChild(emptyBox('The caption is written alongside the graphic\\u2026'));
    visual.innerHTML = '';
    var mount = document.createElement('div');
    visual.appendChild(mount);
    var prog = (window.MH && MH.renderProgress)
      ? MH.renderProgress(mount, {label: 'Rendering the sponsor graphic', sub: 'Usually 30\\u201390 seconds the first time', expectedMs: 45000, accent: 'lane'})
      : {stop: function(){}, complete: function(cb){ cb(); }};
    fetch(jobUrl, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
      .then(function(r){ return r.json().then(function(j){ return {status: r.status, body: j}; }); })
      .then(function(res){
        if (res.status !== 202 || !res.body || !res.body.poll_url) {
          prog.stop();
          fail((res.body && (res.body.user_message || res.body.error)) || 'The sponsor variant couldn\\u2019t be started \\u2014 try again.');
          return;
        }
        var tries = 0;
        var poll = function(){
          tries++;
          if (tries > 100) { prog.stop(); fail('This is taking longer than expected \\u2014 reload the page to check again.'); return; }
          fetch(res.body.poll_url)
            .then(function(r){ return r.json(); })
            .then(function(j){
              if (j.status === 'done') {
                prog.complete(function(){
                  restoreBtn();
                  fillVisual(j);
                  fillCaption(j);
                });
                return;
              }
              if (j.status === 'error') {
                prog.stop();
                fail(j.user_message || 'The sponsor variant couldn\\u2019t be generated \\u2014 try again.');
                return;
              }
              setTimeout(poll, 3000);
            })
            .catch(function(){ setTimeout(poll, 3000); });
        };
        setTimeout(poll, 3000);
      })
      .catch(function(){ prog.stop(); fail('Network error \\u2014 check your connection and try again.'); });
  }
  if (btn) btn.addEventListener('click', svStart);
  if (autostart) {
    if (document.readyState !== 'loading') svStart();
    else document.addEventListener('DOMContentLoaded', svStart);
  }
})();
</script>"""
    )
    return W._layout(f"Sponsor variant — {swimmer}", body, active="home")


def run_charts_page(run_id: str):
    """The Charts & insights surface: a gallery of brand-styled stat graphics
    from this meet, with AI-picked highlights and grounded takeaways."""
    if not W._charts_ok:
        return W._recovery_page(
            "Charts unavailable",
            "The charts engine isn't enabled on this deployment.",
            primary_cta=("Back to home", url_for("home")),
        )
    ctx, cands, err = W._charts_candidates_for(run_id)
    if err is not None:
        # err is (json_response, status); show a friendly recovery page instead.
        return W._recovery_page(
            "Run not found",
            "This run isn't on disk, or it belongs to another organisation.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    meet_name = (
        (ctx["run_data"].get("meet") or {}).get("name")
        or ctx["run_data"].get("meet_name")
        or "Meet"
    )
    _pack_url = url_for("content_pack", run_id=run_id)

    if not cands:
        body = (
            f'<section class="mh-hero" style="padding:var(--sp-7) 0"><h1>Charts &amp; insights</h1>'
            f'<p class="muted">{_h(meet_name)}</p>'
            '<div class="card" style="margin-top:16px"><p>No charts yet — this run has no detected '
            "PBs, medals or splits to plot. Process a meet with standout results to see stat graphics here.</p>"
            f'<p><a class="btn secondary" href="{_h(_pack_url)}">&larr; Back to content builder</a></p></div></section>'
        )
        return W._layout("Charts & insights", body, active="home")

    # Server-rendered gallery — each card embeds its deterministic SVG by URL.
    # Pure f-strings only: a raw-HTML literal + a markupsafe Markup (what _h
    # returns) would escape the *HTML*, so we interpolate values, never concat.
    tiles = []
    for c in cands:
        svg_url = url_for("api_run_chart_svg", run_id=run_id, chart_id=c.chart_id)
        cap_url = url_for("api_run_chart_caption", run_id=run_id, chart_id=c.chart_id)
        # Ready-to-post PNGs (Instagram/Facebook don't accept SVG) + the vector.
        png_sq = svg_url + "?fmt=png&format=square&download=1"
        png_pt = svg_url + "?fmt=png&format=portrait&download=1"
        png_st = svg_url + "?fmt=png&format=story&download=1"
        svg_dl = svg_url + "?download=1"
        tiles.append(
            f'<div class="card mh-chartpack-tile" data-chart-id="{_h(c.chart_id)}" '
            'style="padding:14px;display:flex;flex-direction:column;gap:10px">'
            '<div style="aspect-ratio:1/1;background:var(--panel);border-radius:10px;overflow:hidden">'
            f'<img loading="lazy" src="{_h(svg_url)}" alt="{_h(c.title)}" '
            'style="width:100%;height:100%;object-fit:contain"></div>'
            f'<div><div style="font-weight:700">{_h(c.title)}</div>'
            f'<div class="muted" style="font-size:12px;margin-top:2px">{_h(c.summary)}</div></div>'
            '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:auto">'
            f'<span class="tag">{_h(c.headline_stat)}</span>'
            f'<button class="btn secondary mh-cap-btn" data-cap-url="{_h(cap_url)}" '
            'style="font-size:12px;padding:5px 12px">✍ Caption</button>'
            '<span style="margin-left:auto;display:inline-flex;gap:6px;flex-wrap:wrap">'
            # D-33 — label by intent (was bare geometric glyphs), and fetch the
            # PNG via JS so a raster failure shows inline with an SVG fallback
            # instead of navigating onto a raw JSON error blob.
            f'<button type="button" class="btn mh-chart-dl" style="font-size:12px;padding:5px 12px" '
            f'data-dl-url="{_h(png_pt)}" data-dl-name="{_h(c.chart_id)}-post.png" '
            f'data-svg-fallback="{_h(svg_dl)}" title="1080×1350 — Instagram / Facebook post">Post 4:5</button>'
            f'<button type="button" class="btn secondary mh-chart-dl" style="font-size:12px;padding:5px 10px" '
            f'data-dl-url="{_h(png_sq)}" data-dl-name="{_h(c.chart_id)}-square.png" '
            f'data-svg-fallback="{_h(svg_dl)}" title="1080×1080 — square post">Square 1:1</button>'
            f'<button type="button" class="btn secondary mh-chart-dl" style="font-size:12px;padding:5px 10px" '
            f'data-dl-url="{_h(png_st)}" data-dl-name="{_h(c.chart_id)}-story.png" '
            f'data-svg-fallback="{_h(svg_dl)}" title="1080×1920 — story / reel">Story 9:16</button>'
            f'<a class="btn ghost" style="font-size:12px;padding:5px 10px" href="{_h(svg_dl)}" '
            'download title="Vector SVG — scales losslessly, for designers">Vector</a>'
            "</span></div>"
            '<div class="mh-chart-export-msg" style="display:none;font-size:12.5px;line-height:1.5;'
            'color:var(--warn);background:var(--panel);border-radius:8px;padding:10px"></div>'
            '<div class="mh-cap-out" style="display:none;font-size:13px;line-height:1.5;'
            'background:var(--panel);border-radius:8px;padding:10px"></div></div>'
        )
    gallery = (
        '<div class="mh-chartpack-grid" style="display:grid;'
        "grid-template-columns:repeat(auto-fill,minmax(280px,1fr));"
        f'gap:16px;margin-top:16px">{"".join(tiles)}</div>'
    )

    rec_url = url_for("api_run_charts_recommend", run_id=run_id)
    ins_url = url_for("api_run_charts_insights", run_id=run_id)
    head = (
        '<section class="mh-hero" style="padding:var(--sp-7) 0 var(--sp-4)">'
        "<h1>Charts &amp; insights</h1>"
        f'<p class="muted">{_h(meet_name)} &middot; {len(cands)} chart{"" if len(cands) == 1 else "s"} '
        "from your own results, in your brand colours.</p>"
        f'<p style="margin-top:8px"><a class="muted" href="{_h(_pack_url)}" '
        'style="text-decoration:none">&larr; Back to content builder</a></p></section>'
    )
    ai_panel = (
        '<div class="card no-print" style="display:flex;flex-direction:column;gap:12px">'
        '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">'
        '<div><div style="font-weight:700">AI highlights</div>'
        '<div class="muted" style="font-size:12px;margin-top:2px">Which chart leads the story, and the '
        "takeaways — grounded in the numbers above, never invented.</div></div>"
        '<div style="display:flex;gap:6px;flex-wrap:wrap">'
        '<button id="mh-rec-btn" class="btn" style="font-size:12px;padding:6px 14px">Recommend a chart</button>'
        '<button id="mh-ins-btn" class="btn secondary" style="font-size:12px;padding:6px 14px">Write takeaways</button>'
        "</div></div>"
        '<div id="mh-ai-out" style="display:none"></div></div>'
    )
    js = W._CHARTS_PAGE_JS.replace("__REC_URL__", rec_url).replace("__INS_URL__", ins_url)
    body = head + ai_panel + gallery + js
    return W._layout("Charts & insights", body, active="home")


def season_wraps_page():
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Season wraps", W._PW_NO_ORG, active="create")
    from mediahub.season_wrap import list_drafts

    msg = (request.args.get("msg") or "").strip()
    msg_html = f'<p class="tag good" style="margin-bottom:14px">{_h(msg)}</p>' if msg else ""
    drafts = list_drafts(pid)
    rows = (
        "".join(
            "<tr>"
            f"<td><strong>{_h(d.get('title', d.get('id', '')))}</strong></td>"
            f"<td>{_h((d.get('window') or {}).get('start', ''))} &rarr; {_h((d.get('window') or {}).get('end', ''))}</td>"
            f"<td>{(d.get('stats') or {}).get('n_runs', 0)} meets</td>"
            f"<td><a class='btn secondary' style='font-size:12px;padding:4px 10px' "
            f'href="{url_for("season_wrap_view", draft_id=d.get("id", ""))}">Open</a></td>'
            "</tr>"
            for d in drafts
        )
        or '<tr><td colspan="4" class="muted">No wrap drafts yet — generate one below.</td></tr>'
    )
    try:
        from mediahub.workflow.schedule import list_tasks as _lt

        monthly_on = any(
            t.task_type == "season_wrap_draft" and (t.params or {}).get("profile_id") == pid
            for t in _lt()
        )
    except Exception:
        monthly_on = False
    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Club data &middot; Wraps</span>
  <h1>Season <em class="editorial">wraps</em></h1>
  <p class="lede">Your stored history, turned into &ldquo;month in numbers&rdquo; and
  season-recap packs — PBs, medals, records, debuts, the busiest swimmer.
  Drafted for approval, never auto-posted.</p>
</section>
{msg_html}
<div class="card" style="margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
  <form method="POST" action="{url_for("season_wraps_action")}">
    <input type="hidden" name="action" value="month"/>
    <button type="submit" class="btn">Draft last month&rsquo;s wrap</button>
  </form>
  <form method="POST" action="{url_for("season_wraps_action")}">
    <input type="hidden" name="action" value="season"/>
    <button type="submit" class="btn secondary">Draft this season&rsquo;s wrap (since 1 Sept)</button>
  </form>
  <form method="POST" action="{url_for("season_wraps_action")}">
    <input type="hidden" name="action" value="{"monthly_off" if monthly_on else "monthly_on"}"/>
    <button type="submit" class="btn secondary">{"Disable monthly auto-draft" if monthly_on else "Enable monthly auto-draft"}</button>
  </form>
</div>
<div class="card">
  <h2 style="margin-top:0">Drafts</h2>
  <table class="mh-table" style="width:100%">
    <thead><tr><th>Wrap</th><th>Window</th><th>Coverage</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
"""
    return W._layout("Season wraps", body, active="create")


def season_wraps_action():
    pid = W._phase_w_org()
    if not pid:
        abort(403)
    from mediahub.season_wrap import (
        build_monthly_draft,
        build_season_draft,
        save_draft,
    )

    action = (request.form.get("action") or "").strip()
    now = datetime.now(timezone.utc)
    msg = ""
    if action == "month":
        # Drafting reads every stored run; a single malformed one must not
        # 500 with a stack trace — fail with an honest message instead.
        try:
            year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
            draft = build_monthly_draft(pid, W.RUNS_DIR, year=year, month=month)
            save_draft(pid, draft)
            msg = f"Drafted: {draft.get('title', '')}"
        except Exception:
            W.log.warning("season wrap month draft failed", exc_info=True)
            msg = "Could not draft this wrap - please check your stored runs."
    elif action == "season":
        try:
            season_start = f"{now.year}-09-01" if now.month >= 9 else f"{now.year - 1}-09-01"
            draft = build_season_draft(
                pid, W.RUNS_DIR, season_start=season_start, season_end=now.date().isoformat()
            )
            save_draft(pid, draft)
            msg = f"Drafted: {draft.get('title', '')}"
        except Exception:
            W.log.warning("season wrap season draft failed", exc_info=True)
            msg = "Could not draft this wrap - please check your stored runs."
    elif action == "monthly_on":
        try:
            from mediahub.workflow.schedule import create_task as _ct
            from mediahub.workflow.schedule import list_tasks as _lt

            if not any(
                t.task_type == "season_wrap_draft" and (t.params or {}).get("profile_id") == pid
                for t in _lt()
            ):
                _ct(
                    name=f"Monthly wrap draft — {pid}",
                    task_type="season_wrap_draft",
                    schedule_kind="monthly",
                    schedule_expr="1 06:30",
                    params={"profile_id": pid, "runs_dir": str(W.RUNS_DIR)},
                )
            msg = "Monthly auto-draft enabled — a wrap drafts itself on the 1st."
        except Exception as e:
            msg = f"Could not enable: {e}"
    elif action == "monthly_off":
        try:
            from mediahub.workflow.schedule import delete_task as _dt
            from mediahub.workflow.schedule import list_tasks as _lt

            for t in _lt():
                if t.task_type == "season_wrap_draft" and (t.params or {}).get("profile_id") == pid:
                    _dt(t.id)
            msg = "Monthly auto-draft disabled."
        except Exception as e:
            msg = f"Could not disable: {e}"
    return redirect(url_for("season_wraps_page", msg=msg))


def season_wrap_view(draft_id: str):
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Season wrap", W._PW_NO_ORG, active="create")
    from mediahub.season_wrap import load_draft

    draft = load_draft(pid, draft_id)
    if not draft:
        abort(404)
    chips = "".join(
        f'<div style="border:1px solid var(--border);border-radius:10px;padding:14px 18px;text-align:center">'
        f'<div style="font-size:28px;font-weight:800">{_h(str(v))}</div>'
        f'<div class="muted" style="font-size:12px">{_h(str(k))}</div></div>'
        for k, v in (draft.get("stat_chips") or [])
    )
    highlights = (
        "".join(
            "<tr>"
            f"<td>{_h(h.get('swimmer', ''))}</td><td>{_h(h.get('event', ''))}</td>"
            f"<td>{_h(h.get('headline', ''))}</td>"
            "</tr>"
            for h in (draft.get("highlights") or [])
        )
        or '<tr><td colspan="3" class="muted">No highlights in this window.</td></tr>'
    )
    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Season wrap</span>
  <h1>{_h(draft.get("title", "Wrap"))}</h1>
  <p class="lede">Deterministic numbers from your stored run history. Print the
  noticeboard poster, or use the highlights to build posts.</p>
</section>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:16px">{chips}</div>
<div class="card" style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap">
  <a class="btn" href="{url_for("season_wrap_poster", draft_id=draft_id)}">Print A4 noticeboard poster (PDF)</a>
  <a class="btn secondary" href="{url_for("season_wrap_poster", draft_id=draft_id, print=1)}" title="A4 + 3mm bleed and crop marks, ready for a professional print shop">Print-shop version (bleed + crop marks)</a>
</div>
<div class="card">
  <h2 style="margin-top:0">Highlights</h2>
  <table class="mh-table" style="width:100%">
    <thead><tr><th>Swimmer</th><th>Event</th><th>What happened</th></tr></thead>
    <tbody>{highlights}</tbody>
  </table>
</div>
"""
    return W._layout(draft.get("title", "Season wrap"), body, active="create")


def season_wrap_poster(draft_id: str):
    pid = W._phase_w_org()
    if not pid:
        abort(403)
    from mediahub.graphic_renderer.print_export import (
        build_poster_html,
        export_poster_print_pdf,
        render_html_to_pdf,
    )
    from mediahub.season_wrap import load_draft

    draft = load_draft(pid, draft_id)
    if not draft:
        abort(404)
    prof = W.load_profile(pid)

    def _safe_hex(value, default: str) -> str:
        # Defence in depth: brand colours are substituted raw into the
        # poster's <style> block by the shared print renderer, so a non-hex
        # stored value could break out of the CSS and inject markup into the
        # server-side PDF render. Only let a strict hex literal through.
        v = str(value or "").strip()
        return v if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", v) else default

    brand = {
        "primary": _safe_hex(getattr(prof, "brand_primary", "") if prof else "", "#0A2540"),
        "secondary": _safe_hex(getattr(prof, "brand_secondary", "") if prof else "", "#000000"),
    }
    highlight_rows = [
        {
            "swimmer": h.get("swimmer", ""),
            "event": h.get("event", ""),
            "time": h.get("time", ""),
            "note": h.get("headline", ""),
        }
        for h in (draft.get("highlights") or [])[:10]
    ]
    poster_kwargs = dict(
        title=draft.get("title", "Club wrap"),
        meet_name=", ".join((draft.get("stats") or {}).get("meet_names", [])[:3]),
        stat_lines=[(str(k), str(v)) for k, v in (draft.get("stat_chips") or [])],
        highlight_rows=highlight_rows,
        club_name=(prof.display_name if prof else pid),
        brand=brand,
    )
    # G1.17: ?print=1 emits a print-shop-ready poster (bleed + crop marks).
    print_mode = (request.args.get("print") or "").strip().lower() in W._TRUTHY
    out = W.DATA_DIR / "print_exports" / f"wrap-{pid}-{draft_id}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    if print_mode:
        bleed_mm = W._clamp_float(request.args.get("bleed"), default=3.0, lo=0.0, hi=10.0)
        crop_marks = (request.args.get("marks") or "1").strip().lower() in W._TRUTHY
        export_poster_print_pdf(out, bleed_mm=bleed_mm, crop_marks=crop_marks, **poster_kwargs)
    else:
        render_html_to_pdf(build_poster_html(**poster_kwargs), out)
    return send_file(
        out,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{draft_id}-poster{'-print' if print_mode else ''}.pdf",
    )


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule("/activity", endpoint="activity_page", view_func=activity_page)
    app.add_url_rule("/activity/feed", endpoint="activity_feed_page", view_func=activity_feed_page)
    app.add_url_rule("/upload", endpoint="upload", view_func=upload, methods=["GET", "POST"])
    app.add_url_rule(
        "/upload/from-url", endpoint="upload_from_url", view_func=upload_from_url, methods=["POST"]
    )
    app.add_url_rule(
        "/runs/<run_id>/refetch", endpoint="run_refetch", view_func=run_refetch, methods=["POST"]
    )
    app.add_url_rule(
        "/upload/configure",
        endpoint="upload_configure",
        view_func=upload_configure,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/runs/<run_id>/rerun", endpoint="rerun_run", view_func=rerun_run, methods=["POST"]
    )
    app.add_url_rule("/runs/<run_id>", endpoint="run_status", view_func=run_status)
    app.add_url_rule("/review/<run_id>", endpoint="review", view_func=review)
    app.add_url_rule(
        "/runs/<run_id>/results", endpoint="run_results_table", view_func=run_results_table
    )
    app.add_url_rule(
        "/spotlight/<run_id>/<path:swimmer_key>/build",
        endpoint="spotlight_build",
        view_func=spotlight_build,
        methods=["POST"],
    )
    app.add_url_rule("/spotlight", endpoint="spotlight_landing", view_func=spotlight_landing)
    app.add_url_rule(
        "/spotlight/<run_id>/<path:swimmer_key>",
        endpoint="spotlight_view",
        view_func=spotlight_view,
    )
    app.add_url_rule("/add-input", endpoint="add_input_page", view_func=add_input_page)
    app.add_url_rule(
        "/runs/<run_id>/pack/<pack_id>",
        endpoint="turn_into_pack_view",
        view_func=turn_into_pack_view,
    )
    app.add_url_rule("/annotate/<asset_id>", endpoint="annotate_page", view_func=annotate_page)
    app.add_url_rule(
        "/runs/<run_id>/card/<card_id>/sponsor-variant",
        endpoint="sponsor_variant_view",
        view_func=sponsor_variant_view,
    )
    app.add_url_rule(
        "/runs/<run_id>/charts",
        endpoint="run_charts_page",
        view_func=run_charts_page,
        methods=["GET"],
    )
    app.add_url_rule("/wraps", endpoint="season_wraps_page", view_func=season_wraps_page)
    app.add_url_rule(
        "/wraps/action",
        endpoint="season_wraps_action",
        view_func=season_wraps_action,
        methods=["POST"],
    )
    app.add_url_rule("/wraps/<draft_id>", endpoint="season_wrap_view", view_func=season_wrap_view)
    app.add_url_rule(
        "/wraps/<draft_id>/poster.pdf", endpoint="season_wrap_poster", view_func=season_wrap_poster
    )
