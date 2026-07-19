"""Planning & campaigns: plan board/calendar, drafts, season, collections, newsletters, sponsors.

Carved out of ``web.create_app`` (deep-review finding #15, final stage).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
any captured ``app`` became ``current_app``. Endpoint names are
PRESERVED via ``add_url_rule`` (ADR-0031).
"""

from __future__ import annotations

from markupsafe import escape as _h
from pathlib import Path
import json
import re
import threading
import time
import uuid
from flask import (
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    send_file,
    url_for,
)

from mediahub.web import web as W


def season_timeline_page():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))

    # Fail-soft, org-scoped DB read (WHERE profile_id = ? is the tenant
    # isolation boundary). A missing / locked data.db must not 500 the
    # page — fall through to a recovery hero instead.
    rows = []
    season_standout_by_id: dict[str, int] = {}
    db_failed = False
    try:
        conn = W._db()
        try:
            rows = conn.execute(
                "SELECT id, created_at, finished_at, status, profile_id, "
                "meet_name, our_swims, n_achievements, n_standout, error, file_name, "
                "content_hash, meet_fingerprint "
                "FROM runs WHERE profile_id = ? "
                "ORDER BY created_at DESC LIMIT 200",
                (prof.profile_id,),
            ).fetchall()
            # Standout-swim counts (column, else recomputed from run JSON)
            # — the timeline's honest per-meet figure.
            season_standout_by_id = W._warm_run_standouts(conn, rows)
        finally:
            conn.close()
    except Exception as e:
        W.log.warning("season: runs DB unreachable: %s", e)
        db_failed = True

    eyebrow = '<span class="mh-hero-eyebrow">Season timeline</span>'

    # ---- Empty / recovery states -----------------------------------
    if not rows:
        if db_failed:
            body = (
                '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
                f"{eyebrow}"
                '<h1>Couldn&rsquo;t load your <em class="editorial">season</em>.</h1>'
                '<p class="lede">The runs database wasn&rsquo;t readable on this '
                "deployment, so the timeline is empty even if meets were processed "
                "earlier. Try refreshing &mdash; if it keeps happening, ask your "
                "operator to check the data volume.</p>"
                '<div class="mh-hero-actions">'
                f'<a class="mh-cta-primary" href="{url_for("season_timeline_page")}">Refresh &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{url_for("home")}">Back to home</a>'
                "</div></section>"
            )
            return W._layout("Season timeline", body, active="season")
        body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
            f"{eyebrow}"
            f'<h1>Your season starts here, <em class="editorial">{_h(prof.display_name)}</em>.</h1>'
            '<p class="lede">Process your first meet and it lands on this timeline '
            "&mdash; every meet a node on the season, with the swims matched and the "
            "standout swims found, and a beam that traces the season as you scroll.</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{url_for("make_page")}">Create your first piece &rarr;</a>'
            f'<a class="mh-cta-secondary" href="{url_for("activity_page")}">Open activity</a>'
            "</div></section>"
        )
        return W._layout("Season timeline", body, active="season")

    # ---- Build the timeline ----------------------------------------
    from datetime import datetime as _dt

    def _parse(iso):
        if not iso:
            return None
        try:
            return _dt.fromisoformat(str(iso).replace("Z", "").replace("T", " ")[:19])
        except Exception:
            return None

    # Inline stat-chip glyphs — a lane/water mark for matched swims and a
    # star for detected moments (echoing the medal motif used elsewhere).
    icon_swims = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/>'
        '<path d="M2 9c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/></svg>'
    )
    icon_moment = (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M12 2.6l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.9 6.6 19.1l1.2-6'
        '-4.5-4.2 6.1-.7z"/></svg>'
    )

    # Re-run badging across the whole season (``rows`` is already the full
    # org set, up to 200, with the hash + fingerprint columns). Computed
    # BEFORE the tallies so re-uploads of the same meet don't inflate the
    # celebratory hero stats: dup_map keys are the re-run ids (the oldest run
    # in each group is the original and is never in the map).
    dup_map = W._duplicate_map(rows)

    # Pass 1 — group runs by calendar month (newest-first order preserved),
    # tally per-month + season totals, note the span, and remember the one
    # standout meet (most moments) so the timeline can celebrate it. Re-runs
    # still RENDER (with their Re-run badge) but are excluded from every
    # count so "Meets", "Swims matched" and "Standout swims" count each
    # real meet once. "Moments" here are STANDOUT SWIMS (deduped), not raw
    # detections — the honest per-meet figure.
    n_meets = 0
    total_swims = 0
    total_moments = 0
    first_dt = None
    last_dt = None
    peak_run_id = None
    peak_moments = 0
    months: list = []
    month_pos: dict = {}
    for r in rows:
        is_rerun = r["id"] in dup_map
        dt = _parse(r["created_at"])
        month_label = dt.strftime("%B %Y") if dt else "Undated"
        swims = int(r["our_swims"] or 0)
        moments = int(season_standout_by_id.get(r["id"], 0) or 0)
        if not is_rerun:
            n_meets += 1
            total_swims += swims
            total_moments += moments
            if dt is not None:
                if first_dt is None or dt < first_dt:
                    first_dt = dt
                if last_dt is None or dt > last_dt:
                    last_dt = dt
            if moments > peak_moments:
                peak_moments = moments
                peak_run_id = r["id"]
        if month_label not in month_pos:
            month_pos[month_label] = len(months)
            months.append({"label": month_label, "rows": [], "swims": 0, "moments": 0})
        bucket = months[month_pos[month_label]]
        bucket["rows"].append((r, dt, swims, moments))
        if not is_rerun:
            bucket["swims"] += swims
            bucket["moments"] += moments

    # Pass 2 — render each month as a labelled section of meet cards.
    items_html = ""
    for bucket in months:
        # Count each real meet once (re-runs still render below with their
        # Re-run badge) so the month label agrees with the deduplicated
        # season hero totals.
        meets_n = sum(1 for r, *_ in bucket["rows"] if r["id"] not in dup_map)
        meta_bits = [f"{meets_n} {'meet' if meets_n == 1 else 'meets'}"]
        if bucket["moments"]:
            meta_bits.append(
                f"{bucket['moments']:,} standout "
                f"{'swim' if bucket['moments'] == 1 else 'swims'}"
            )
        month_meta = " &middot; ".join(_h(b) for b in meta_bits)
        items_html += (
            '<div class="mh-timeline__head">'
            f'<span class="mh-tl-month">{_h(bucket["label"])}</span>'
            f'<span class="mh-tl-month-meta">{month_meta}</span>'
            '<span class="mh-tl-head-rule" aria-hidden="true"></span>'
            "</div>"
        )
        for r, dt, swims, moments in bucket["rows"]:
            if dt:
                day_html = _h(f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}")
                iso_attr = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                full_title = dt.strftime("%A %d %B %Y, %H:%M UTC")
            else:
                day_html, iso_attr, full_title = "&mdash;", "", "Date unknown"

            status = r["status"] or ""
            badge = {"done": "good", "running": "info", "queued": "info", "error": "bad"}.get(
                status, ""
            )
            # Re-clean a stale HY-TEK banner title (pre-QA-002 runs) so the
            # timeline shows the real meet name, not the licensee banner.
            title = W._clean_stored_meet_title(r["meet_name"]) or r["file_name"] or r["id"]
            review_href = url_for("review", run_id=r["id"])
            delete_href = url_for("privacy_delete_run", run_id=r["id"])
            dup_badge = W._dup_badge_html(dup_map.get(r["id"]))
            is_peak = peak_run_id is not None and r["id"] == peak_run_id and peak_moments > 0

            # Stat chips. The "<n> swims matched" / "<n> moments detected"
            # phrasing is kept verbatim (screen readers + tests read it as
            # one string); the chip only lends the figure visual weight.
            chips = (
                '<span class="mh-tl-chip">'
                f"{icon_swims}{swims:,} {'swim' if swims == 1 else 'swims'} matched"
                "</span>"
            )
            if moments:
                chips += (
                    '<span class="mh-tl-chip mh-tl-chip--moments">'
                    f"{icon_moment}{moments:,} standout {'swim' if moments == 1 else 'swims'}"
                    "</span>"
                )

            flag = (
                f'<span class="mh-tl-flag">{icon_moment}Season highlight</span>' if is_peak else ""
            )
            card_cls = "card mh-tl-card" + (" is-peak" if is_peak else "")
            peak_attr = ' data-peak="1"' if is_peak else ""

            item = (
                f'<div class="mh-timeline__item" data-run-row="{_h(r["id"])}"{peak_attr}>'
                f'<article class="{card_cls}">'
                '<div class="mh-tl-top">'
                '<div class="mh-tl-meta">'
                f'<time class="mh-tl-date" datetime="{_h(iso_attr)}" '
                f'title="{_h(full_title)}">{day_html}</time>'
                f"{flag}"
                "</div>"
                f'<span class="tag {badge}">{_h(status)}</span>'
                "</div>"
                f'<h3 class="mh-tl-title"><a href="{review_href}">{_h(title)}</a>{dup_badge}</h3>'
                f'<div class="mh-tl-stats">{chips}</div>'
            )
            if status == "error" and r["error"]:
                err = str(r["error"])
                err = err[:400] + ("…" if len(err) > 400 else "")
                item += (
                    '<details class="mh-tl-err">'
                    "<summary>Why did this run fail?</summary>"
                    f"<pre>{_h(err)}</pre></details>"
                )
            # Per-run delete (in-place via the shared JS; no-JS posts back to
            # this page). Quiet by default — a subtle danger link, not a
            # primary action — since the timeline is a celebratory surface.
            item += (
                '<div class="mh-tl-actions" style="margin-top:var(--sp-3);'
                'display:flex;justify-content:flex-end">'
                f'<form method="post" action="{delete_href}" class="mh-run-delete" '
                f'data-run-id="{_h(r["id"])}" data-no-loader="1" style="display:inline">'
                f'<input type="hidden" name="next" value="{_h(request.path)}">'
                '<button class="btn ghost" type="submit" '
                'style="font-size:11px;padding:4px 10px;color:var(--bad)">'
                "Delete</button>"
                "</form></div>"
            )
            item += "</article></div>"
            items_html += item

    # Season span — oldest → newest meet, for the hero meta line.
    range_str = ""
    if first_dt and last_dt:
        if first_dt.year == last_dt.year and first_dt.month == last_dt.month:
            range_str = first_dt.strftime("%B %Y")
        elif first_dt.year == last_dt.year:
            range_str = f"{first_dt.strftime('%b')} &ndash; {last_dt.strftime('%b %Y')}"
        else:
            range_str = f"{first_dt.strftime('%b %Y')} &ndash; {last_dt.strftime('%b %Y')}"

    # Page-scoped presentation. Kept inline (not in the shared kit CSS) so
    # the feature is self-contained and parallel-safe; design tokens keep it
    # on brand. The rail offset centres the 2px beam on the timeline node
    # dots; the peak meet gets a medal-tinted dot and card treatment.
    season_css = (
        "<style>"
        ".mh-season-tl{max-width:780px}"
        ".mh-season-tl .mh-tracing-beam__rail{left:8px}"
        ".mh-season-tl .mh-timeline__head{display:flex;align-items:baseline;"
        "flex-wrap:wrap;gap:var(--sp-2) var(--sp-3);margin:var(--sp-6) 0 var(--sp-4)}"
        ".mh-season-tl .mh-timeline__head:first-child{margin-top:0}"
        ".mh-season-tl .mh-tl-month{font-family:var(--font-mono);font-size:var(--fs-sm);"
        "font-weight:600;letter-spacing:.14em;text-transform:uppercase;"
        "color:var(--ink-muted);white-space:nowrap}"
        ".mh-season-tl .mh-tl-month-meta{font-family:var(--font-mono);font-size:10.5px;"
        "letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);white-space:nowrap}"
        ".mh-season-tl .mh-tl-head-rule{flex:1 1 auto;min-width:24px;height:1px;"
        "background:linear-gradient(90deg,var(--hairline),transparent)}"
        ".mh-season-tl .mh-tl-card{padding:var(--sp-4) var(--sp-5);"
        "transition:border-color var(--transition),transform var(--transition),"
        "box-shadow var(--transition)}"
        ".mh-season-tl .mh-tl-card:hover{border-color:var(--rule);transform:translateY(-1px)}"
        ".mh-season-tl .mh-tl-top{display:flex;align-items:center;"
        "justify-content:space-between;gap:var(--sp-3);margin-bottom:10px}"
        ".mh-season-tl .mh-tl-meta{display:inline-flex;align-items:center;gap:10px;min-width:0}"
        ".mh-season-tl .mh-tl-date{font-family:var(--font-mono);font-size:var(--fs-sm);"
        "color:var(--ink-muted);letter-spacing:.04em;white-space:nowrap}"
        ".mh-season-tl .mh-tl-title{margin:0 0 12px;font-size:var(--fs-lg);line-height:1.2}"
        ".mh-season-tl .mh-tl-title a{color:var(--ink);text-decoration:none}"
        ".mh-season-tl .mh-tl-title a:hover{color:var(--mh-primary)}"
        ".mh-season-tl .mh-tl-stats{display:flex;flex-wrap:wrap;gap:8px}"
        ".mh-season-tl .mh-tl-chip{display:inline-flex;align-items:center;gap:7px;"
        "padding:5px 11px 5px 9px;border-radius:999px;font-family:var(--font-mono);"
        "font-size:11px;font-weight:500;letter-spacing:.04em;color:var(--ink-dim);"
        "background:rgba(245,242,232,0.04);border:1px solid var(--hairline)}"
        ".mh-season-tl .mh-tl-chip svg{width:14px;height:14px;flex:0 0 auto;opacity:.85}"
        ".mh-season-tl .mh-tl-chip--moments{color:var(--medal);"
        "background:color-mix(in oklab,var(--medal) 10%,transparent);"
        "border-color:color-mix(in oklab,var(--medal) 32%,transparent)}"
        ".mh-season-tl .mh-tl-chip--moments svg{opacity:1}"
        ".mh-season-tl .mh-tl-card.is-peak{"
        "border-color:color-mix(in oklab,var(--medal) 38%,var(--hairline));"
        "background:linear-gradient(180deg,color-mix(in oklab,var(--medal) 7%,transparent),"
        "transparent 60%),var(--surface);"
        "box-shadow:0 0 0 1px color-mix(in oklab,var(--medal) 14%,transparent),"
        "0 18px 40px -28px var(--medal-glow)}"
        ".mh-season-tl .mh-tl-flag{display:inline-flex;align-items:center;gap:6px;"
        "font-family:var(--font-mono);font-size:9.5px;font-weight:600;letter-spacing:.16em;"
        "text-transform:uppercase;color:var(--medal)}"
        ".mh-season-tl .mh-tl-flag svg{width:12px;height:12px}"
        ".mh-season-tl .mh-timeline__item[data-peak]::before{background:var(--medal);"
        "width:11px;height:11px;left:calc(-1 * var(--sp-7) + 4px);"
        "box-shadow:0 0 0 4px color-mix(in oklab,var(--medal) 20%,transparent),"
        "0 0 14px var(--medal-glow)}"
        ".mh-season-tl .mh-tl-err{margin-top:12px}"
        ".mh-season-tl .mh-tl-err summary{cursor:pointer;font-size:var(--fs-sm);"
        "color:var(--bad);font-family:var(--font-mono);letter-spacing:.04em}"
        ".mh-season-tl .mh-tl-err pre{margin:8px 0 0;padding:10px 12px;"
        "background:rgba(0,0,0,0.25);border-radius:6px;font-size:12px;"
        "white-space:pre-wrap;word-break:break-word}"
        "</style>"
    )

    # Season totals — count up on scroll-in via the shared motion system.
    summary_html = (
        '<div class="mh-activity-summary mh-reveal">'
        f'<div class="stat live"><div class="l">Meets</div>'
        f'<div class="v" data-mh-count="{n_meets}">{n_meets:,}</div></div>'
        f'<div class="stat"><div class="l">Swims matched</div>'
        f'<div class="v" data-mh-count="{total_swims}">{total_swims:,}</div></div>'
        f'<div class="stat medal"><div class="l">Standout swims</div>'
        f'<div class="v" data-mh-count="{total_moments}">{total_moments:,}</div></div>'
        "</div>"
    )

    range_html = f'<span>{range_str}</span><span class="sep">&middot;</span>' if range_str else ""
    # Bulk "Clear all runs" — per-tenant; a quiet danger link in the strap.
    _clear_href = url_for("privacy_clear_all_runs")
    clear_all_html = (
        '<span class="sep">&middot;</span><span>'
        f'<form method="post" action="{_clear_href}" class="mh-clear-all-runs" '
        f'data-count="{n_meets}" data-no-loader="1" style="display:inline">'
        f'<input type="hidden" name="next" value="{_h(request.path)}">'
        '<button type="submit" style="background:none;border:0;padding:0;'
        'cursor:pointer;color:var(--bad);font:inherit;text-decoration:underline">'
        "Clear all runs</button></form></span>"
    )
    hero = (
        f'<section class="mh-hero" data-lane="{n_meets}" '
        'style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        f"{eyebrow}"
        f'<h1>{_h(prof.display_name)}&rsquo;s <em class="editorial">season</em></h1>'
        '<p class="lede">Every meet you&rsquo;ve processed, traced in order &mdash; '
        "the swims matched to your club and the moments worth celebrating.</p>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f"{range_html}"
        f"<span>{n_meets:,} {'meet' if n_meets == 1 else 'meets'}</span>"
        '<span class="sep">&middot;</span>'
        # (G-2: the "View as activity log →" link moved into the shared
        # Table · Feed · Season strip below the hero.)
        # C-9 — a discoverable entry into Collections (folders grouping meets),
        # previously reachable only by typing the URL.
        f'<span><a href="{url_for("collections_page")}">Collections &rarr;</a></span>'
        f"{clear_all_html}"
        "</div></section>"
    )

    timeline_html = (
        '<div class="mh-tracing-beam mh-season-tl">'
        '<span class="mh-tracing-beam__rail" aria-hidden="true"></span>'
        '<div class="mh-timeline">'
        f"{items_html}"
        "</div></div>"
    )

    body = (
        season_css
        + hero
        + W._activity_view_toggle("season")
        + summary_html
        + timeline_html
        + W._RUN_DELETE_JS
    )
    return W._layout("Season timeline", body, active="season")


def api_plan_latest():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.planner import load_latest_plan

    plan = load_latest_plan(pid)
    return jsonify({"ok": True, "org_id": pid, "plan": plan})


def api_plan_generate():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    body = request.get_json(silent=True) or {}
    sport = str(body.get("sport") or request.form.get("sport") or "swimming").strip().lower()
    if not W._valid_sport_slug(sport):
        return jsonify({"error": f"No sport profile named {sport!r}."}), 404
    try:
        from mediahub.content_engine.planner import build_content_plan, save_plan

        plan = build_content_plan(sport, pid)
        save_plan(plan)
    except FileNotFoundError:
        return jsonify({"error": f"No sport profile named {sport!r}."}), 404
    except Exception as exc:
        current_app.logger.exception("plan generation failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "org_id": pid, "plan": plan.to_dict()})


def api_plan_inputs():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.inputs import load_planner_inputs, save_planner_inputs

    if request.method == "GET":
        return jsonify({"ok": True, "org_id": pid, "inputs": load_planner_inputs(pid)})
    body = request.get_json(silent=True) or {}
    try:
        saved = save_planner_inputs(pid, body)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "org_id": pid, "inputs": saved})


def api_plan_interpret():
    # Free-text → STRUCTURED direct inputs (the Free-Text feature's NL
    # interpretation + web research, brought to the planner). The AI only
    # PROPOSES inputs the operator reviews + saves; the deterministic
    # ranker is untouched. Honest provider errors, no heuristic fallback.
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Tell the planner what's coming up first."}), 400

    # Resolve the org's sport the same way the page does, so goals can only
    # ever target a post type this sport actually enables.
    from mediahub.club_platform.post_types import post_types_for
    from mediahub.sport_profiles import list_sport_profiles, load_sport_profile

    _avail = {p.sport for p in list_sport_profiles()}
    _prof = W._active_profile()
    sport = W._ORG_TYPE_TO_SPORT.get(getattr(_prof, "org_type", "") or "")
    if sport not in _avail:
        sport = str(body.get("sport") or "swimming").strip().lower()
    if not W._valid_sport_slug(sport):
        return jsonify({"error": f"No sport profile named {sport!r}."}), 404
    try:
        profile = load_sport_profile(sport)
        goal_choices = [(spt.slug, spt.title) for spt in post_types_for(profile)]
    except Exception:
        goal_choices = []

    from mediahub.ai_core import ProviderError, ProviderNotConfigured
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    try:
        parsed = interpret_planner_inputs(text, goal_choices=goal_choices)
    except ProviderNotConfigured as exc:
        return jsonify({"error": str(exc)}), 503
    except ProviderError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        current_app.logger.exception("plan interpret failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "org_id": pid, "parsed": parsed})


def plan_page():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.club_platform.content_types import REGISTRY as _ct_registry
    from mediahub.club_platform.post_types import implemented_content_type
    from mediahub.content_engine.inputs import load_planner_inputs
    from mediahub.content_engine.planner import load_latest_plan
    from mediahub.sport_profiles import list_sport_profiles

    plan = load_latest_plan(pid)
    inputs = load_planner_inputs(pid)
    # Load the sport list defensively. This is the one piece of shared
    # config the index reads that every working /plan/<view> sub-view
    # either guards (calendar/analytics resolve the sport through
    # _org_calendar_sport, which wraps list_sport_profiles in try/except)
    # or never touches (board/grid). An unguarded raise here — a malformed
    # or operator-added profile YAML, a profiles dir pointed elsewhere, an
    # I/O error — would 500 ONLY the index while every sub-view stays up,
    # which is exactly the QA-016 scope. Degrade like the sub-views do.
    try:
        sports = [(p.sport, p.display_name) for p in list_sport_profiles()]
    except Exception:
        current_app.logger.warning("plan page: sport profiles failed to load", exc_info=True)
        sports = []

    # The sport comes from the ORGANISATION, not a per-page dropdown.
    # org_type was chosen at setup; map it onto an available sport
    # profile. Only when the org type doesn't imply a sport (a
    # university society could run anything) do we fall back to a
    # visible selector.
    _prof = W._active_profile()
    _avail = {slug for slug, _ in sports}
    org_sport = W._ORG_TYPE_TO_SPORT.get(getattr(_prof, "org_type", "") or "")
    if org_sport not in _avail:
        org_sport = None
    current_sport = org_sport or (plan or {}).get("sport") or "swimming"

    if org_sport:
        _sport_display = dict(sports).get(org_sport, org_sport.title())
        sport_control_html = (
            f'<input type="hidden" id="mh-plan-sport" value="{_h(org_sport)}"/>'
            f'<span style="font-weight:600">Planning for {_h(_sport_display)}</span>'
            f'<span class="dim" style="font-size:12px">set by your '
            f'<a href="{url_for("organisation_setup")}" style="text-decoration:underline">organisation profile</a></span>'
        )
    else:
        _sport_opts = "".join(
            f'<option value="{_h(slug)}"{" selected" if slug == current_sport else ""}>{_h(name)}</option>'
            for slug, name in sports
        )
        sport_control_html = (
            '<label for="mh-plan-sport" style="font-weight:600">Sport</label>'
            f'<select id="mh-plan-sport" style="min-width:min(160px,100%)">{_sport_opts}</select>'
            '<span class="dim" style="font-size:12px">your organisation type doesn&rsquo;t '
            "pin a sport, so pick one here</span>"
        )

    # F-6: plain-language signal-source chips (the engine's OWN/EXTERNAL/DIRECT
    # taxonomy meant nothing to a volunteer and had no legend on the page).
    src_chip = {
        "own": '<span class="tag" style="background:rgba(34,211,238,.12);color:var(--accent)">From your results</span>',
        "external": '<span class="tag" style="background:rgba(167,139,250,.12);color:var(--medal)">From the calendar</span>',
        "direct": '<span class="tag" style="background:rgba(250,204,21,.12);color:var(--lane)">You told us</span>',
    }

    # Persisted plans are durable state — DATA_DIR is a mounted disk that
    # survives redeploys — so the index can load a plan an *older* planner
    # wrote, whose shape the current engine no longer emits (a None/blank
    # numeric field, a non-list `items`, a stray non-dict entry). The index
    # is the ONLY handler that renders plan items — no /plan/<view> sub-view
    # reads the plan — so any such shape would 500 only the index. Render
    # defensively: coerce the scalars, treat only real lists as lists, and
    # skip anything that isn't a proper item, so one stale field never takes
    # down the landing page. This is the /plan-vs-/plan/<view> diff (QA-016).
    def _as_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _as_list(value: object) -> list:
        return value if isinstance(value, list) else []

    items_html = ""
    if plan:
        for rank, item in enumerate(_as_list(plan.get("items")), start=1):
            if not isinstance(item, dict):
                continue
            slug = item.get("post_type", "")
            ct = implemented_content_type(slug)
            create_link = ""
            if ct is not None:
                meta = _ct_registry.get(ct)
                if meta is not None:
                    try:
                        # J-6: free-text targets carry the idea itself —
                        # the free-text landing prefills its textarea from
                        # ?seed=<title — reason>. Other tools are
                        # form-driven, so their links stay plain.
                        if meta.primary_route_endpoint == "free_text_chat_page":
                            _seed_bits = [str(item.get("title") or slug)]
                            _first_reason = next(
                                (
                                    str(r).strip()
                                    for r in _as_list(item.get("reasons"))
                                    if str(r).strip()
                                ),
                                "",
                            )
                            if _first_reason:
                                _seed_bits.append(_first_reason)
                            _create_url = url_for(
                                meta.primary_route_endpoint,
                                seed=" — ".join(_seed_bits)[:500],
                            )
                        else:
                            _create_url = url_for(meta.primary_route_endpoint)
                        create_link = (
                            f'<a class="btn" style="font-size:12px;padding:4px 12px" '
                            f'href="{_h(_create_url)}">Create →</a>'
                        )
                    except Exception:
                        create_link = ""
            chips = "".join(src_chip.get(s, "") for s in _as_list(item.get("sources_used")))
            if not chips:
                # F-6: a bare "baseline" tag meant nothing — say what it is.
                chips = '<span class="tag">General suggestion</span>'
            reasons = "".join(
                f'<li style="margin:2px 0;color:var(--ink-muted);font-size:12.5px">{_h(r)}</li>'
                for r in _as_list(item.get("reasons"))
            )
            badge = (
                '<span class="tag live">Ready to create</span>'
                if item.get("implemented")
                else '<span class="tag">Planning only</span>'
            )
            items_html += f"""
<details class="card mh-reveal" style="margin-bottom:10px" {"open" if rank <= 3 else ""}>
  <summary style="display:flex;align-items:center;gap:12px;cursor:pointer;list-style:none">
    <span style="font-family:var(--font-display,inherit);font-size:20px;min-width:34px;color:var(--ink-muted)">#{rank}</span>
    <strong style="flex:1">{_h(item.get("title") or slug)}</strong>
    {chips}
    {badge}
    <span style="font-variant-numeric:tabular-nums;font-weight:700;font-size:15px" title="Priority score">{_as_int(item.get("score"))}</span>
    {create_link}
  </summary>
  <div style="padding:10px 4px 2px 46px">
    <p style="margin:0 0 4px 0;font-size:12px;color:var(--ink-muted)">Why this ranks here — every line traces to a signal:</p>
    <ul style="margin:0;padding-left:18px">{reasons}</ul>
  </div>
</details>"""

        counts = plan.get("source_counts") or {}
        notes_html = "".join(
            f'<li style="color:var(--ink-muted);font-size:12.5px">{_h(n)}</li>'
            for n in _as_list(plan.get("notes"))
        )
        plan_meta = f"""
<div class="card" style="margin-bottom:14px">
  <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center">
    <strong>{_h(plan.get("sport_display") or plan.get("sport", ""))} plan</strong>
    <span class="dim" style="font-size:12.5px">generated {_h(str(plan.get("generated_at", ""))[:16].replace("T", " "))} · next {_as_int(plan.get("horizon_days"), 14)} days</span>
    <span style="font-size:12.5px">{_as_int(counts.get("own"))} from your results · {_as_int(counts.get("external"))} from the calendar · {_as_int(counts.get("direct"))} you told us</span>
  </div>
  {f'<ul style="margin:8px 0 0 0;padding-left:18px">{notes_html}</ul>' if notes_html else ""}
</div>"""
        plan_block = plan_meta + items_html
    else:
        plan_block = """
<div class="card" style="text-align:center;padding:42px 24px">
  <h2 style="margin:0 0 8px 0">No plan yet</h2>
  <p class="dim" style="max-width:520px;margin:0 auto 4px auto">Generate your first content plan — MediaHub fuses your processed results,
  discovered context and anything you tell it below into a ranked list of what to post next, with the reasoning shown for every item.</p>
</div>"""

    def _ev_row(e: dict) -> str:
        venue = str(e.get("venue") or "")
        venue_html = (
            f'<span class="dim" style="font-size:11.5px">{_h(venue)}</span>' if venue else ""
        )
        return (
            f'<div class="mh-plan-ev" data-name="{_h(e["name"])}" data-date="{_h(e["date"])}" '
            f'data-venue="{_h(venue)}" style="display:flex;gap:8px;align-items:center;font-size:13px;margin:3px 0">'
            f'<span style="font-variant-numeric:tabular-nums">{_h(e["date"])}</span>'
            f'<span style="flex:1">{_h(e["name"])}{(" — " + venue_html) if venue else ""}</span>'
            f'<button type="button" class="btn" style="font-size:11px;padding:2px 8px" onclick="mhPlanRemoveEvent(this)">remove</button></div>'
        )

    events_rows = "".join(_ev_row(e) for e in inputs.get("upcoming_events") or [])
    blackout_val = _h(", ".join(inputs.get("blackout_dates") or []))

    # Goals are a real planning lever (the ranker rewards a post type the
    # operator says they want to push), but the form never surfaced them —
    # and the old save dropped them on every write. Surface them now, keyed
    # to the post types this sport actually enables.
    from mediahub.club_platform.post_types import post_types_for
    from mediahub.sport_profiles import load_sport_profile

    try:
        _sport_pts = post_types_for(load_sport_profile(current_sport))
    except Exception:
        _sport_pts = []
    _goal_titles = {spt.slug: spt.title for spt in _sport_pts}
    goal_opts = "".join(
        f'<option value="{_h(spt.slug)}">{_h(spt.title)}</option>' for spt in _sport_pts
    )

    def _goal_row(g: dict) -> str:
        slug = str(g.get("post_type") or "")
        title = _goal_titles.get(slug, slug.replace("_", " ").title())
        note = str(g.get("note") or "")
        note_html = (
            f'<span style="flex:1;color:var(--ink-muted)">{_h(note)}</span>'
            if note
            else '<span style="flex:1"></span>'
        )
        return (
            f'<div class="mh-plan-goal" data-slug="{_h(slug)}" data-note="{_h(note)}" '
            f'style="display:flex;gap:8px;align-items:center;font-size:13px;margin:3px 0">'
            f'<span style="flex:0 0 auto;font-weight:600">{_h(title)}</span>{note_html}'
            f'<button type="button" class="btn" style="font-size:11px;padding:2px 8px" onclick="mhPlanRemoveGoal(this)">remove</button></div>'
        )

    goals_rows = "".join(_goal_row(g) for g in inputs.get("goals") or [])

    if goal_opts:
        goals_add_html = (
            '<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">'
            f'<select id="mh-plan-goal-type" aria-label="Post type to push" style="flex:0 0 auto;min-width:180px">{goal_opts}</select>'
            '<input type="text" id="mh-plan-goal-note" aria-label="Why you want to push this type" placeholder="why — e.g. push our new sponsor" style="flex:1;min-width:160px"/>'
            '<button type="button" class="btn" onclick="mhPlanAddGoal()">Add goal</button>'
            "</div>"
        )
    else:
        goals_add_html = (
            '<p class="dim" style="font-size:11.5px;margin:6px 0 0 0">'
            "No post types are enabled for this sport yet.</p>"
        )
    goal_titles_json = json.dumps(_goal_titles)

    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Plan</span>
  <h1>What should we<br><em class="editorial">post next?</em></h1>
  <p class="lede">This page suggests your next posts, in order, and shows its working.
  Hit <strong>Generate plan</strong> and you get a ranked to-post list built from your
  recent results, the calendar, and anything you tell it below. Each item explains
  why it ranks where it does, and the ones marked <strong>Ready to create</strong>
  jump straight into the matching tool. Nothing publishes from here.</p>
  <a class="mh-how-pill" href="{url_for("content_type_intro", ct="plan")}" style="margin-top:var(--sp-3)">How it works</a>
</section>

{W._plan_subnav("plan")}

<div class="mh-next-strip" aria-label="How the plan works" style="margin-bottom:16px">
  <div class="cell"><span class="num">1</span><span class="text"><b>Generate</b><br>One click fuses your results, drafts, the calendar and your direct notes.</span></div>
  <div class="cell"><span class="num">2</span><span class="text"><b>Read the why</b><br>Every item lists the exact signals that put it at that rank.</span></div>
  <div class="cell"><span class="num">3</span><span class="text"><b>Create</b><br>Click <i>Create</i> on an item to open the right tool &mdash; free-text ideas arrive pre-filled.</span></div>
</div>

<div class="card" style="margin-bottom:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;justify-content:center">
  {sport_control_html}
  <button type="button" class="btn primary" id="mh-plan-generate" onclick="mhPlanGenerate(this)"
          data-loader-text="Fusing signals">Generate plan</button>
  <span class="dim" id="mh-plan-status" style="font-size:12.5px"></span>
</div>

{plan_block}

<div class="card" style="margin-top:18px">
  <h2 style="margin-top:0">Tell the planner (direct signals)</h2>
  <p class="dim" style="font-size:12.5px;margin-top:0">Upcoming events boost previews and announcements; blackout dates hold them back; goals nudge a type you want to push. Saved per organisation.</p>

  <div style="border:1px solid var(--lane);border-radius:10px;padding:14px;background:color-mix(in oklab, var(--lane) 4%, transparent);margin:4px 0 18px 0">
    <label for="mh-plan-nl" style="font-weight:600;display:flex;align-items:center;gap:8px">
      <span class="tag live" style="font-size:10px">AI</span>Describe what&rsquo;s coming up
    </label>
    <p class="dim" style="font-size:12px;margin:4px 0 8px 0">Type it in your own words and MediaHub turns it into events, blackout dates and goals below &mdash; checking the web for an event&rsquo;s date when it needs to. You review everything before it saves.</p>
    <textarea id="mh-plan-nl" rows="3" placeholder="e.g. County Champs at Ponds Forge on the 12th, we&rsquo;re shut the bank holiday weekend, and I want to get behind our new sponsor this month."
      style="width:100%;font-size:13px;padding:10px 12px;border:1px solid var(--panel);border-radius:8px;background:var(--bg);color:var(--ink);resize:vertical"></textarea>
    <div style="display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap">
      <button type="button" class="btn primary" id="mh-plan-nl-btn" onclick="mhPlanInterpret(this)" data-loader-text="Reading your note">Interpret &amp; fill in &rarr;</button>
      <span class="dim" id="mh-plan-nl-status" style="font-size:12.5px"></span>
    </div>
    <div id="mh-plan-nl-result" style="margin-top:10px"></div>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px">
    <div>
      <label style="font-weight:600">Upcoming events</label>
      <div id="mh-plan-events">{events_rows}</div>
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
        <input type="date" id="mh-plan-ev-date" aria-label="Event date" style="flex:0 0 auto"/>
        <input type="text" id="mh-plan-ev-name" aria-label="Event name" placeholder="e.g. County Championships" style="flex:1;min-width:140px"/>
        <input type="text" id="mh-plan-ev-venue" aria-label="Event venue (optional)" placeholder="venue (optional)" style="flex:1;min-width:120px"/>
        <button type="button" class="btn" onclick="mhPlanAddEvent()">Add</button>
      </div>
    </div>
    <div>
      <label for="mh-plan-blackouts" style="font-weight:600">Blackout dates</label>
      <input type="text" id="mh-plan-blackouts" value="{blackout_val}" placeholder="YYYY-MM-DD, YYYY-MM-DD"/>
      <p class="dim" style="font-size:11.5px;margin:4px 0 0 0">Comma-separated ISO dates nothing should be scheduled on.</p>
    </div>
  </div>

  <div style="margin-top:18px">
    <label style="font-weight:600">Goals &mdash; a type you want to push</label>
    <p class="dim" style="font-size:11.5px;margin:2px 0 0 0">Each goal gives its post type a ranking nudge, with your note shown as the reason.</p>
    <div id="mh-plan-goals" style="margin-top:6px">{goals_rows}</div>
    {goals_add_html}
  </div>

  <div style="margin-top:16px;display:flex;gap:10px;align-items:center">
    <button type="button" class="btn" onclick="mhPlanSaveInputs(this)">Save inputs</button>
    <span class="dim" id="mh-plan-inputs-status" style="font-size:12.5px"></span>
  </div>
</div>

<script>
var MH_GOAL_TITLES = {goal_titles_json};
function mhPlanEventRow(name, date, venue) {{
  var row = document.createElement('div');
  row.className = 'mh-plan-ev';
  row.dataset.name = name; row.dataset.date = date; row.dataset.venue = venue || '';
  row.style.cssText = 'display:flex;gap:8px;align-items:center;font-size:13px;margin:3px 0';
  var dEl = document.createElement('span'); dEl.style.cssText = 'font-variant-numeric:tabular-nums'; dEl.textContent = date;
  var label = document.createElement('span'); label.style.flex = '1';
  label.textContent = venue ? (name + ' — ' + venue) : name;
  var rm = document.createElement('button'); rm.type = 'button'; rm.className = 'btn';
  rm.style.cssText = 'font-size:11px;padding:2px 8px'; rm.textContent = 'remove';
  rm.setAttribute('onclick', 'mhPlanRemoveEvent(this)');
  row.appendChild(dEl); row.appendChild(label); row.appendChild(rm);
  return row;
}}
function mhPlanCollectEvents() {{
  return Array.from(document.querySelectorAll('#mh-plan-events .mh-plan-ev')).map(function (el) {{
    return {{ name: el.dataset.name, date: el.dataset.date, venue: el.dataset.venue || '' }};
  }});
}}
function mhPlanAddEvent() {{
  var d = document.getElementById('mh-plan-ev-date').value;
  var n = document.getElementById('mh-plan-ev-name').value.trim();
  var v = document.getElementById('mh-plan-ev-venue').value.trim();
  if (!d || !n) return;
  document.getElementById('mh-plan-events').appendChild(mhPlanEventRow(n, d, v));
  document.getElementById('mh-plan-ev-name').value = '';
  document.getElementById('mh-plan-ev-venue').value = '';
}}
function mhPlanRemoveEvent(btn) {{ btn.closest('.mh-plan-ev').remove(); }}
function mhPlanGoalRow(slug, title, note) {{
  var row = document.createElement('div');
  row.className = 'mh-plan-goal';
  row.dataset.slug = slug; row.dataset.note = note || '';
  row.style.cssText = 'display:flex;gap:8px;align-items:center;font-size:13px;margin:3px 0';
  var t = document.createElement('span'); t.style.cssText = 'flex:0 0 auto;font-weight:600'; t.textContent = title || slug;
  var nt = document.createElement('span'); nt.style.cssText = 'flex:1;color:var(--ink-muted)'; nt.textContent = note || '';
  var rm = document.createElement('button'); rm.type = 'button'; rm.className = 'btn';
  rm.style.cssText = 'font-size:11px;padding:2px 8px'; rm.textContent = 'remove';
  rm.setAttribute('onclick', 'mhPlanRemoveGoal(this)');
  row.appendChild(t); row.appendChild(nt); row.appendChild(rm);
  return row;
}}
function mhPlanCollectGoals() {{
  return Array.from(document.querySelectorAll('#mh-plan-goals .mh-plan-goal')).map(function (el) {{
    return {{ post_type: el.dataset.slug, note: el.dataset.note || '' }};
  }});
}}
function mhPlanAddGoal() {{
  var sel = document.getElementById('mh-plan-goal-type');
  if (!sel || !sel.value) return;
  var slug = sel.value;
  if (document.querySelector('#mh-plan-goals .mh-plan-goal[data-slug="' + slug + '"]')) return;
  var note = document.getElementById('mh-plan-goal-note').value.trim();
  var title = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : slug;
  document.getElementById('mh-plan-goals').appendChild(mhPlanGoalRow(slug, title, note));
  document.getElementById('mh-plan-goal-note').value = '';
}}
function mhPlanRemoveGoal(btn) {{ btn.closest('.mh-plan-goal').remove(); }}
function mhPlanSaveInputs(btn) {{
  var status = document.getElementById('mh-plan-inputs-status');
  status.textContent = 'Saving…';
  fetch({json.dumps(url_for("api_plan_inputs"))}, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      upcoming_events: mhPlanCollectEvents(),
      blackout_dates: document.getElementById('mh-plan-blackouts').value.split(',').map(function(s){{return s.trim();}}).filter(Boolean),
      goals: mhPlanCollectGoals()
    }})
  }}).then(function(r){{ return r.json(); }}).then(function(j){{
    status.textContent = j.ok ? 'Saved. Regenerate the plan to apply.' : (j.error || 'Save failed');
  }}).catch(function(){{ status.textContent = 'Save failed'; }});
}}
function mhPlanMergeParsed(p) {{
  var added = 0;
  var have = {{}};
  Array.from(document.querySelectorAll('#mh-plan-events .mh-plan-ev')).forEach(function (el) {{
    have[(el.dataset.date || '') + '|' + (el.dataset.name || '').toLowerCase()] = true;
  }});
  (p.upcoming_events || []).forEach(function (ev) {{
    var key = (ev.date || '') + '|' + (ev.name || '').toLowerCase();
    if (!ev.name || !ev.date || have[key]) return;
    have[key] = true;
    document.getElementById('mh-plan-events').appendChild(mhPlanEventRow(ev.name, ev.date, ev.venue || ''));
    added++;
  }});
  var bf = document.getElementById('mh-plan-blackouts');
  var existing = bf.value.split(',').map(function (s) {{ return s.trim(); }}).filter(Boolean);
  var seen = {{}}; existing.forEach(function (d) {{ seen[d] = true; }});
  (p.blackout_dates || []).forEach(function (d) {{ if (d && !seen[d]) {{ existing.push(d); seen[d] = true; added++; }} }});
  bf.value = existing.join(', ');
  var haveG = {{}};
  Array.from(document.querySelectorAll('#mh-plan-goals .mh-plan-goal')).forEach(function (el) {{ haveG[el.dataset.slug] = true; }});
  (p.goals || []).forEach(function (g) {{
    if (!g.post_type || haveG[g.post_type]) return;
    haveG[g.post_type] = true;
    document.getElementById('mh-plan-goals').appendChild(mhPlanGoalRow(g.post_type, MH_GOAL_TITLES[g.post_type] || g.post_type, g.note || ''));
    added++;
  }});
  return added;
}}
function mhPlanRenderNote(p, added) {{
  var box = document.getElementById('mh-plan-nl-result');
  box.innerHTML = '';
  if (p.summary) {{
    var s = document.createElement('p'); s.className = 'dim'; s.style.cssText = 'font-size:12px;margin:0 0 6px 0';
    s.textContent = p.summary; box.appendChild(s);
  }}
  if (added === 0) {{
    var none = document.createElement('p'); none.className = 'dim'; none.style.cssText = 'font-size:12px;margin:0';
    none.textContent = 'Nothing new to add from that — try naming an event and a date, or what you want to push.';
    box.appendChild(none);
  }}
  var research = p.research || [];
  var hitCount = research.reduce(function (a, r) {{ return a + ((r.hits || []).length); }}, 0);
  if (hitCount) {{
    var det = document.createElement('details'); det.style.cssText = 'margin-top:4px';
    var sum = document.createElement('summary'); sum.style.cssText = 'cursor:pointer;font-size:11.5px;color:var(--ink-muted)';
    sum.textContent = 'Checked the web (' + hitCount + ' source' + (hitCount === 1 ? '' : 's') + ')';
    det.appendChild(sum);
    research.forEach(function (r) {{
      (r.hits || []).forEach(function (h) {{
        if (!h.url || String(h.url).slice(0, 4).toLowerCase() !== 'http') return;
        var a = document.createElement('a'); a.href = h.url; a.target = '_blank'; a.rel = 'noopener';
        a.style.cssText = 'display:block;font-size:11.5px;margin:3px 0;color:var(--accent);text-decoration:none';
        a.textContent = (h.title || h.domain || h.url);
        det.appendChild(a);
      }});
    }});
    box.appendChild(det);
  }}
}}
function mhPlanInterpret(btn) {{
  var status = document.getElementById('mh-plan-nl-status');
  var text = document.getElementById('mh-plan-nl').value.trim();
  if (!text) {{ status.textContent = 'Type a note first.'; return; }}
  // D-27: these AI buttons are type=button outside any form, so the shared
  // form-submit loader never fired — long LLM+web-research calls showed only a
  // tiny status line. Drive the loader from data-loader-text directly.
  btn.disabled = true; status.textContent = 'Reading your note…';
  if (window.MH) MH.showLoader(btn.dataset.loaderText || 'Reading your note', 'Checking dates on the web when it needs to…');
  document.getElementById('mh-plan-nl-result').innerHTML = '';
  fetch({json.dumps(url_for("api_plan_interpret"))}, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ text: text }})
  }}).then(function (r) {{ return r.json().then(function (j) {{ return {{ ok: r.ok, j: j }}; }}); }})
    .then(function (res) {{
      btn.disabled = false;
      if (window.MH) MH.hideLoader();
      var j = res.j || {{}};
      if (!res.ok || !j.ok) {{ status.textContent = j.error || 'Could not interpret that.'; return; }}
      var p = j.parsed || {{}};
      var added = mhPlanMergeParsed(p);
      status.textContent = 'Filled in ' + added + ' item' + (added === 1 ? '' : 's') + ' below — review, then Save inputs.';
      mhPlanRenderNote(p, added);
    }}).catch(function () {{ btn.disabled = false; if (window.MH) MH.hideLoader(); status.textContent = 'Could not interpret that.'; }});
}}
function mhPlanGenerate(btn) {{
  var status = document.getElementById('mh-plan-status');
  btn.disabled = true; status.textContent = 'Saving your inputs…';
  // D-27: visible loading treatment for the long fuse-and-generate call.
  if (window.MH) MH.showLoader(btn.dataset.loaderText || 'Fusing signals', 'Building your ranked plan…');
  // H-7: persist whatever is on the page BEFORE generating. Generate builds
  // the plan from the PERSISTED inputs and the page reloads on success, so an
  // event/goal/blackout the volunteer just typed (or added via "Interpret &
  // fill in", which only creates DOM rows) would otherwise be silently wiped
  // and never reach the plan. Auto-saving first makes the big primary action
  // do what the user expects.
  fetch({json.dumps(url_for("api_plan_inputs"))}, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      upcoming_events: mhPlanCollectEvents(),
      blackout_dates: document.getElementById('mh-plan-blackouts').value.split(',').map(function(s){{return s.trim();}}).filter(Boolean),
      goals: mhPlanCollectGoals()
    }})
  }}).then(function(r){{ return r.json(); }}).catch(function(){{ return {{ok:false}}; }}).then(function(){{
    status.textContent = 'Fusing own + external + direct signals…';
    return fetch({json.dumps(url_for("api_plan_generate"))}, {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ sport: document.getElementById('mh-plan-sport').value }})
    }});
  }}).then(function(r){{ return r.json(); }}).then(function(j){{
    if (j.ok) {{ window.location.reload(); }}
    else {{ btn.disabled = false; if (window.MH) MH.hideLoader(); status.textContent = j.error || 'Plan generation failed'; }}
  }}).catch(function(){{ btn.disabled = false; if (window.MH) MH.hideLoader(); status.textContent = 'Plan generation failed'; }});
}}
</script>
"""
    return W._layout("Content plan", body, active="create")


def api_plan_calendar():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.calendar import build_calendar, grid_bounds

    year, month = W._parse_month_param(request.args.get("m", ""))
    sport = W._org_calendar_sport(W._active_profile())
    start, end = grid_bounds(year, month)
    model = build_calendar(pid, sport, start=start, end=end)
    out = model.to_dict()
    out["year"], out["month"] = year, month
    return jsonify({"ok": True, "org_id": pid, "calendar": out})


def api_plan_calendar_schedule():
    """Set / move / clear the day a draft is planned to post (1.14).

    Planning only — nothing is published. Re-evaluates the soft blackout
    gate and returns a ``warning`` when the chosen day is a blackout; the
    human decides whether to keep it (we never hard-block their own plan).
    """
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    body = request.get_json(silent=True) or {}
    pack_id = str(body.get("pack_id") or "").strip()
    # Empty / null date clears the schedule (back to the side rail).
    new_date = body.get("date")
    new_date = "" if new_date in (None, "") else str(new_date).strip()
    channel = body.get("channel")
    channel = None if channel is None else str(channel).strip()

    from mediahub.club_platform.stub_pack_store import load_pack, set_planned_date

    rec = load_pack(pack_id)
    if rec is None:
        return jsonify({"error": "Draft not found."}), 404
    # Tenant isolation: only the owning org may reschedule its draft.
    if (rec.get("profile_id") or "") != pid:
        return jsonify({"error": "Draft not found."}), 404

    updated = set_planned_date(pack_id, new_date, channel=channel)
    if updated is None:
        return jsonify({"error": "Invalid date (expected YYYY-MM-DD)."}), 400

    warning = ""
    planned = updated.get("planned_date")
    if planned:
        from mediahub.content_engine.inputs import load_planner_inputs

        blackouts = set(load_planner_inputs(pid).get("blackout_dates") or [])
        if planned in blackouts:
            warning = (
                f"Heads up — {planned} is a blackout date you set. "
                "The draft is planned there anyway; move it if that wasn't intended."
            )
    return jsonify(
        {
            "ok": True,
            "pack_id": pack_id,
            "planned_date": planned,
            "planned_channel": updated.get("planned_channel") or "",
            "warning": warning,
        }
    )


def plan_calendar_page():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from datetime import date as _date

    from mediahub.content_engine.calendar import (
        build_calendar,
        grid_bounds,
        month_matrix,
        today_utc,
    )

    prof = W._active_profile()
    sport = W._org_calendar_sport(prof)
    year, month = W._parse_month_param(request.args.get("m", ""))
    start, end = grid_bounds(year, month)
    model = build_calendar(pid, sport, start=start, end=end)
    by_date = model.entries_by_date()
    weeks = month_matrix(year, month)
    today = today_utc()

    month_name = _date(year, month, 1).strftime("%B %Y")
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    prev_url = url_for("plan_calendar_page", m=f"{prev_y:04d}-{prev_m:02d}")
    next_url = url_for("plan_calendar_page", m=f"{next_y:04d}-{next_m:02d}")
    today_url = url_for("plan_calendar_page", m=f"{today.year:04d}-{today.month:02d}")

    # Per-kind chip styling — colour-coded, escaped, deterministic.
    _kind_style = {
        "blackout": ("var(--bad)", "rgba(255,107,107,.12)"),
        "key_date": ("var(--medal)", "rgba(244,213,141,.12)"),
        "event": ("var(--lane)", "color-mix(in oklab, var(--lane) 12%, transparent)"),
        "anniversary": ("var(--ink-dim)", "rgba(182,178,166,.10)"),
        "posted": ("var(--good)", "rgba(94,227,154,.12)"),
    }

    def _entry_chip(e) -> str:
        if e.kind == "planned_draft":
            ch = e.meta.get("channel") or ""
            ch_html = f'<span style="opacity:.7"> · {_h(ch)}</span>' if ch else ""
            # D-26: the flag is always in the markup (hidden off-blackout) so an
            # in-place move onto/off a blackout day can toggle it without a reload.
            warn = (
                '<span class="mh-cal-warnflag" title="On a blackout date you set" '
                'style="color:var(--bad);font-weight:700"'
                f"{'' if e.meta.get('on_blackout') else ' hidden'}> ⚠</span>"
            )
            draft_url = url_for("stub_pack_view", pack_id=e.ref)
            # I-1 parity: HTML5 drag never fires from touch and the chip isn't
            # focusable, so a planned chip also carries a non-drag date field
            # (reschedule) + an unschedule control — the same affordance
            # _rail_card gives unscheduled drafts. mhCalPlanInput / mhCalUnplan →
            # mhCalSchedule + the schedule endpoint already handle move + clear;
            # only this UI was missing on planned chips, so touch/keyboard users
            # could schedule but never reschedule or unschedule.
            # JS2-1: data-prev carries the last date the SERVER confirmed —
            # the change event fires after input.value already mutated, so a
            # failed move must revert to data-prev, never to input.value.
            reschedule = (
                f'<input type="date" class="mh-cal-plan-date" data-pack="{_h(e.ref)}" '
                f'value="{_h(e.date)}" data-prev="{_h(e.date)}" '
                f'aria-label="Move {_h(e.title)} to another day" '
                'onchange="mhCalPlanInput(this)" onclick="event.stopPropagation()" '
                'style="margin-top:5px;width:100%;font-size:11px;padding:2px 5px;'
                "border:1px solid var(--border);border-radius:6px;background:var(--panel);"
                'color:inherit">'
            )
            unplan = (
                f'<button type="button" class="mh-cal-unplan" data-pack="{_h(e.ref)}" '
                f'aria-label="Unschedule {_h(e.title)}" '
                'title="Unschedule — send back to the side rail" '
                'onclick="mhCalUnplan(event, this)" '
                'style="margin-top:3px;font-size:10.5px;background:none;border:none;'
                'color:var(--ink-muted);text-decoration:underline;cursor:pointer;padding:0">'
                "unschedule</button>"
            )
            return (
                f'<div class="mh-cal-draft" draggable="true" data-pack="{_h(e.ref)}" '
                f'data-href="{_h(draft_url)}" '
                f'title="{_h(e.title)} — drag to a day to move, or use the date field to reschedule">'
                f'<span class="mh-cal-draft-dot"></span>'
                f'<span class="mh-cal-draft-t">{_h(e.title)}{ch_html}{warn}</span>'
                f"{reschedule}{unplan}</div>"
            )
        fg, bg = _kind_style.get(e.kind, ("var(--ink-dim)", "rgba(182,178,166,.10)"))
        note = e.meta.get("note") or e.meta.get("venue") or ""
        title_attr = f"{e.title}" + (f" — {note}" if note else "")
        return (
            f'<div class="mh-cal-chip" style="color:{fg};background:{bg}" '
            f'title="{_h(title_attr)}">{_h(e.title)}</div>'
        )

    cells = ""
    for week in weeks:
        for day in week:
            iso = day.isoformat()
            in_month = day.month == month
            is_today = day == today
            chips = "".join(_entry_chip(e) for e in by_date.get(iso, []))
            classes = "mh-cal-cell"
            if not in_month:
                classes += " mh-cal-spill"
            if is_today:
                classes += " mh-cal-today"
            cells += (
                f'<div class="{classes}" data-date="{iso}" '
                f'ondragover="mhCalOver(event)" ondragleave="mhCalLeave(event)" '
                f'ondrop="mhCalDrop(event)">'
                f'<div class="mh-cal-daynum">{day.day}</div>'
                f'<div class="mh-cal-stack">{chips}</div></div>'
            )

    dow_head = "".join(
        f'<div class="mh-cal-dow">{d}</div>'
        for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    )

    # Side rail — unscheduled drafts to drag onto a day.
    def _rail_card(d: dict) -> str:
        # I-1: a non-drag "Plan for…" date field so touch + keyboard users
        # can schedule a draft (HTML5 drag never fires from touch). Drag onto
        # a day stays as the desktop enhancement.
        plan_input = (
            f'<input type="date" class="mh-cal-plan-date" data-pack="{_h(d["pack_id"])}" '
            'data-prev="" '
            f'aria-label="Plan a date to post {_h(d["title"])}" '
            f'onchange="mhCalPlanInput(this)" onclick="event.stopPropagation()" '
            'style="margin-top:6px;width:100%;font-size:11px;padding:3px 6px;'
            "border:1px solid var(--border);border-radius:6px;background:var(--panel);"
            'color:inherit">'
        )
        # D-26: hidden blackout flag + unschedule control ship in the markup, so
        # when this card is scheduled in place (no reload) it gains the same
        # affordances a server-rendered planned chip has.
        warn_flag = (
            '<span class="mh-cal-warnflag" title="On a blackout date you set" '
            'style="color:var(--bad);font-weight:700" hidden> ⚠</span>'
        )
        unplan = (
            f'<button type="button" class="mh-cal-unplan" data-pack="{_h(d["pack_id"])}" '
            f'aria-label="Unschedule {_h(d["title"])}" '
            'title="Unschedule — send back to the side rail" '
            'onclick="mhCalUnplan(event, this)" hidden '
            'style="margin-top:3px;font-size:10.5px;background:none;border:none;'
            'color:var(--ink-muted);text-decoration:underline;cursor:pointer;padding:0">'
            "unschedule</button>"
        )
        return (
            f'<div class="mh-cal-draft mh-cal-rail-card" draggable="true" '
            f'data-pack="{_h(d["pack_id"])}" '
            f'data-href="{_h(url_for("stub_pack_view", pack_id=d["pack_id"]))}" '
            f'title="Drag onto a day — or use the date field — to plan when to post it">'
            f'<span class="mh-cal-draft-dot"></span>'
            f'<span class="mh-cal-draft-t">{_h(d["title"])}'
            f'<span style="opacity:.6"> · {int(d["n_cards"])} card'
            f"{'s' if int(d['n_cards']) != 1 else ''}</span>{warn_flag}</span>"
            f"{plan_input}{unplan}</div>"
        )

    rail = "".join(_rail_card(d) for d in model.unscheduled_drafts)
    if not rail:
        rail = (
            '<p class="dim" id="mh-cal-rail-empty" style="font-size:12px;margin:6px 2px">'
            "No unscheduled drafts. "
            f'<a href="{url_for("make_page")}" style="text-decoration:underline">Make content</a>, '
            "then drag it onto a day to plan when to post.</p>"
        )

    legend = "".join(
        f'<span class="mh-cal-leg"><span class="mh-cal-leg-sw" style="background:{c}"></span>{lbl}</span>'
        for lbl, c in (
            ("Key date", "var(--medal)"),
            ("Event", "var(--lane)"),
            ("Planned draft", "var(--accent)"),
            ("Posted", "var(--good)"),
            ("Blackout", "var(--bad)"),
            ("Anniversary", "var(--ink-dim)"),
        )
    )

    counts = model.counts()
    notes_html = "".join(
        f'<li style="color:var(--ink-muted);font-size:12.5px">{_h(n)}</li>' for n in model.notes
    )

    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-4);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Plan · Calendar</span>
  <h1>Your content<br><em class="editorial">on a calendar.</em></h1>
  <p class="lede">Planned drafts, key dates, your events and what you&rsquo;ve already posted, all in one month view.
  Drag a draft onto a day to plan when to post it &mdash; nothing publishes from here, it&rsquo;s your plan to post by hand.</p>
</section>

{W._plan_subnav("calendar")}

<div class="mh-cal-bar">
  <div class="mh-cal-nav">
    <a class="btn" href="{prev_url}" aria-label="Previous month">&larr;</a>
    <strong class="mh-cal-month">{_h(month_name)}</strong>
    <a class="btn" href="{next_url}" aria-label="Next month">&rarr;</a>
    <a class="btn" href="{today_url}">Today</a>
  </div>
  <div class="mh-cal-legend">{legend}</div>
</div>

<span class="dim" id="mh-cal-status" style="font-size:12.5px;display:block;min-height:18px;margin:2px 2px 8px"></span>

<div id="mh-cal-warn" role="alert" style="display:none;gap:10px;align-items:flex-start;justify-content:space-between;margin:0 0 10px;padding:10px 14px;border:1px solid var(--bad);border-radius:10px;background:color-mix(in oklab, var(--bad) 10%, var(--panel));font-size:13px">
  <span id="mh-cal-warn-text"></span>
  <button type="button" onclick="mhCalWarnBanner('')" aria-label="Dismiss this warning" style="background:none;border:none;color:inherit;cursor:pointer;font-size:16px;line-height:1;padding:0">&times;</button>
</div>

<div class="mh-cal-wrap">
  <div class="mh-cal-grid-wrap">
    <div class="mh-cal-dows">{dow_head}</div>
    <div class="mh-cal-grid">{cells}</div>
    <p class="dim" style="font-size:12px;margin-top:10px">
      Showing {int(counts.get("planned_draft", 0))} planned ·
      {int(counts.get("key_date", 0))} key date{"s" if counts.get("key_date", 0) != 1 else ""} ·
      {int(counts.get("event", 0))} event{"s" if counts.get("event", 0) != 1 else ""} ·
      {int(counts.get("posted", 0))} posted in this month.
    </p>
    {f'<ul style="margin:6px 0 0 0;padding-left:18px">{notes_html}</ul>' if notes_html else ""}
  </div>
  <aside class="mh-cal-rail" ondragover="mhCalOver(event)" ondragleave="mhCalLeave(event)" ondrop="mhCalUnschedule(event)">
    <h2 style="margin:0 0 2px 0;font-size:15px">Unscheduled drafts</h2>
    <p class="dim" style="font-size:11.5px;margin:0 0 8px 0">Drag onto a day to plan it. Drag a planned draft back here to unschedule.</p>
    {rail}
  </aside>
</div>

<script>
var MH_CAL_SCHEDULE_URL = {json.dumps(url_for("api_plan_calendar_schedule"))};
function mhCalOver(e) {{ e.preventDefault(); var c = e.currentTarget; if (c) c.classList.add('mh-cal-drop'); }}
function mhCalLeave(e) {{ var c = e.currentTarget; if (c) c.classList.remove('mh-cal-drop'); }}
function mhCalStatus(msg, warn) {{
  var s = document.getElementById('mh-cal-status');
  if (!s) return; s.textContent = msg || ''; s.style.color = warn ? 'var(--warn)' : 'var(--ink-muted)';
}}
// I-1: non-drag scheduling (touch / keyboard) via the rail card's date field.
function mhCalPlanInput(el) {{
  if (el && el.value) mhCalSchedule(el.getAttribute('data-pack'), el.value);
}}
// I-1 parity: unschedule a planned chip (touch / keyboard) without dragging it
// back to the rail. stopPropagation so the chip's open-draft click never fires.
function mhCalUnplan(e, btn) {{
  if (e) e.stopPropagation();
  if (btn) mhCalSchedule(btn.getAttribute('data-pack'), '');
}}
// D-24 (kept by D-26): the blackout warning is an inline banner that stays
// until the volunteer dismisses it — no reload ever erases it.
function mhCalWarnBanner(msg) {{
  var box = document.getElementById('mh-cal-warn');
  var txt = document.getElementById('mh-cal-warn-text');
  if (!box || !txt) return;
  txt.textContent = msg || '';
  box.style.display = msg ? 'flex' : 'none';
}}
// D-26: keep a moved chip's controls truthful (date field, unschedule,
// blackout flag, rail styling) without re-rendering the page.
function mhCalChipSync(chip, date, warned) {{
  var input = chip.querySelector('.mh-cal-plan-date');
  if (input) input.value = date || '';
  var un = chip.querySelector('.mh-cal-unplan');
  if (un) un.hidden = !date;
  var flag = chip.querySelector('.mh-cal-warnflag');
  if (flag) flag.hidden = !warned;
  chip.classList.toggle('mh-cal-rail-card', !date);
}}
// D-26: a drop / "Plan for…" / unschedule moves the chip in place at once
// (optimistically); a failed POST puts it back and MH.toasts the reason.
function mhCalSchedule(packId, date) {{
  if (!packId) return;
  var chip = document.querySelector('.mh-cal-draft[data-pack="' + packId + '"]');
  var undo = null;
  if (chip) {{
    var parent = chip.parentNode, next = chip.nextSibling;
    var prevInput = chip.querySelector('.mh-cal-plan-date');
    // JS2-1: the change event fires AFTER input.value already holds the new
    // date, so the last server-confirmed date lives in data-prev (stamped
    // server-side, advanced only on a successful POST). Drag drops route
    // through the same bookkeeping so the two paths cannot drift.
    var prevDate = prevInput ? (prevInput.dataset.prev || '') : '';
    var prevFlag = chip.querySelector('.mh-cal-warnflag');
    var prevWarned = !!(prevFlag && !prevFlag.hidden);
    var railEmpty = document.getElementById('mh-cal-rail-empty');
    var target = null;
    if (date) {{
      var cell = document.querySelector('.mh-cal-cell[data-date="' + date + '"]');
      target = cell ? cell.querySelector('.mh-cal-stack') : null;
    }} else {{
      target = document.querySelector('.mh-cal-rail');
    }}
    undo = function () {{
      if (parent) parent.insertBefore(chip, next);
      chip.style.display = '';
      // mhCalChipSync restores input.value from prevDate (= data-prev), so a
      // failed POST never leaves the chip claiming the date that failed.
      mhCalChipSync(chip, prevDate, prevWarned);
      if (railEmpty) railEmpty.style.display = '';
    }};
    if (target) {{ target.appendChild(chip); }} else {{ chip.style.display = 'none'; }}
    mhCalChipSync(chip, date, false);
    if (railEmpty && !date) railEmpty.style.display = 'none';
  }}
  mhCalStatus(date ? 'Scheduling…' : 'Unscheduling…', false);
  fetch(MH_CAL_SCHEDULE_URL, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ pack_id: packId, date: date || '' }})
  }}).then(function (r) {{ return r.json(); }}).then(function (j) {{
    if (!j.ok) {{
      if (undo) undo();
      mhCalStatus(j.error || 'Could not update.', true);
      if (window.MH && MH.toast) MH.toast(j.error || 'Could not update the plan.', 'error');
      return;
    }}
    // JS2-1: the server confirmed the move — data-prev advances to the new
    // date so the NEXT failed move reverts here, not to a stale value.
    if (prevInput) prevInput.dataset.prev = date || '';
    if (chip && date && !document.querySelector('.mh-cal-cell[data-date="' + date + '"]')) {{
      chip.remove(); // planned onto a day outside this month's grid
      mhCalStatus('Planned for ' + date + ' — see that month for the chip.', false);
    }} else {{
      mhCalStatus(date ? ('Planned for ' + date + '.') : 'Unscheduled — back in the side rail.', false);
    }}
    if (j.warning) {{
      mhCalWarnBanner(j.warning);
      var flag = chip ? chip.querySelector('.mh-cal-warnflag') : null;
      if (flag) flag.hidden = false;
    }}
  }}).catch(function () {{
    if (undo) undo();
    mhCalStatus('Could not update.', true);
    if (window.MH && MH.toast) MH.toast('Could not update the plan — check your connection and try again.', 'error');
  }});
}}
document.addEventListener('dragstart', function (e) {{
  var card = e.target.closest ? e.target.closest('.mh-cal-draft') : null;
  if (!card) return;
  e.dataTransfer.setData('text/plain', card.dataset.pack || '');
  e.dataTransfer.effectAllowed = 'move';
}});
function mhCalDrop(e) {{
  e.preventDefault();
  var cell = e.currentTarget; if (cell) cell.classList.remove('mh-cal-drop');
  var packId = e.dataTransfer.getData('text/plain');
  var date = cell ? cell.dataset.date : '';
  if (packId && date) mhCalSchedule(packId, date);
}}
function mhCalUnschedule(e) {{
  e.preventDefault();
  var rail = e.currentTarget; if (rail) rail.classList.remove('mh-cal-drop');
  var packId = e.dataTransfer.getData('text/plain');
  if (packId) mhCalSchedule(packId, '');
}}
// A plain click on a draft chip opens the draft (drag still works).
document.addEventListener('click', function (e) {{
  var card = e.target.closest ? e.target.closest('.mh-cal-draft') : null;
  if (card && card.dataset.href) window.location.href = card.dataset.href;
}});
</script>
"""
    return W._layout("Plan calendar", body, active="create")


def plan_preview_page(pack_id):
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.channel_preview import all_platforms, platform as _platform, preview_card
    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    if rec is None or (rec.get("profile_id") or "") != pid:
        abort(404)

    spec = _platform(request.args.get("platform", "")) or all_platforms()[0]
    fmt_name = request.args.get("format", "") or spec.default_format
    if fmt_name not in spec.format_names():
        fmt_name = spec.default_format

    # Platform tabs (links) + format tabs (links).
    plat_tabs = "".join(
        f'<a class="mh-cp-tab{" active" if p.slug == spec.slug else ""}" '
        f'href="{url_for("plan_preview_page", pack_id=pack_id, platform=p.slug)}">{_h(p.name)}</a>'
        for p in all_platforms()
    )
    fmt_tabs = "".join(
        f'<a class="mh-cp-fmt{" active" if fn == fmt_name else ""}" '
        f'href="{url_for("plan_preview_page", pack_id=pack_id, platform=spec.slug, format=fn)}">{_h(fn)}</a>'
        for fn in spec.format_names()
    )

    cards = rec.get("cards") or []
    frames = ""
    for card in cards:
        pv = preview_card(card, spec.slug, format_name=fmt_name)
        if pv is not None:
            frames += W._channel_frame_html(card, pv)
    if not frames:
        # J-7: don't strand the user on a dead empty state — mirror the
        # ad-variants page and link back to the draft to add/regenerate cards.
        frames = (
            '<p class="dim">This draft has no cards to preview yet. '
            f'<a href="{url_for("stub_pack_view", pack_id=pack_id)}" style="text-decoration:underline">'
            "Add or regenerate cards</a> first.</p>"
        )

    title = _h(rec.get("title") or "Draft")
    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-3);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Plan · Channel preview</span>
  <h1>How it looks <em class="editorial">before you post.</em></h1>
  <p class="lede">&ldquo;{title}&rdquo; the way each platform shows it &mdash; the crop, the
  <strong>safe zone</strong> the app&rsquo;s own buttons cover, and where the caption folds behind
  &ldquo;more&rdquo;. Nothing posts from here; copy it across by hand when you&rsquo;re happy.
  <a href="{url_for("stub_pack_view", pack_id=pack_id)}" style="text-decoration:underline">Back to the draft &rarr;</a></p>
</section>

<div class="mh-cp-bar">
  <div class="mh-cp-tabs">{plat_tabs}</div>
  <div class="mh-cp-fmts">{fmt_tabs}</div>
</div>
<p class="dim" style="font-size:11.5px;margin:0 0 14px">{_h(spec.source)}</p>

<div class="mh-cp-grid">{frames}</div>
<script>
document.addEventListener('click', function (e) {{
  var more = e.target.closest ? e.target.closest('.mh-cp-more') : null;
  if (!more) return;
  var hidden = more.nextElementSibling;
  if (hidden && hidden.classList.contains('mh-cp-hidden')) {{
    hidden.classList.toggle('show');
    more.style.display = hidden.classList.contains('show') ? 'none' : '';
  }}
}});
</script>
"""
    return W._layout("Channel preview", body, active="create")


def plan_grid_page():
    """Instagram-style grid preview of the planned feed — drafts the club has
    scheduled (newest planned first), then unscheduled drafts."""
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.channel_preview import instagram_grid
    from mediahub.club_platform.stub_pack_store import list_packs, load_pack

    # Build feed cells from this org's drafts (planned ones first, by date).
    planned: list[dict] = []
    unplanned: list[dict] = []
    for meta in list_packs(limit=60):
        rec = load_pack(meta.get("pack_id", ""))
        if rec is None or (rec.get("profile_id") or "") != pid:
            continue
        cell = {
            "pack_id": rec.get("pack_id", ""),
            "title": rec.get("title") or "Draft",
            "planned_date": rec.get("planned_date") or "",
            "stub_type": rec.get("stub_type") or "",
        }
        (planned if cell["planned_date"] else unplanned).append(cell)
    planned.sort(key=lambda c: c["planned_date"], reverse=True)
    cells = planned + unplanned

    def _cell_html(c: dict) -> str:
        if c.get("placeholder"):
            return '<div class="mh-grid-cell mh-grid-empty"></div>'
        badge = (
            f'<span class="mh-grid-when">{_h(c["planned_date"])}</span>'
            if c.get("planned_date")
            else '<span class="mh-grid-when mh-grid-unplanned">unscheduled</span>'
        )
        return (
            f'<a class="mh-grid-cell" href="{url_for("plan_preview_page", pack_id=c["pack_id"])}" '
            f'title="{_h(c["title"])}">'
            f'<span class="mh-grid-type">{_h(str(c["stub_type"]).replace("_", " "))}</span>'
            f'<span class="mh-grid-title">{_h(c["title"])}</span>{badge}</a>'
        )

    if cells:
        rows = instagram_grid(cells, columns=3)
        grid_html = (
            '<div class="mh-grid">' + "".join(_cell_html(c) for row in rows for c in row) + "</div>"
        )
    else:
        grid_html = (
            '<div class="card" style="text-align:center;padding:40px 24px">'
            '<h2 style="margin:0 0 6px">No posts to preview yet</h2>'
            f'<p class="dim">Make a draft, then it shows here as a feed tile. '
            f'<a href="{url_for("make_page")}" style="text-decoration:underline">Create &rarr;</a></p></div>'
        )

    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-3);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Plan · Grid preview</span>
  <h1>Your feed, <em class="editorial">as a grid.</em></h1>
  <p class="lede">A quick Instagram-style look at how your planned drafts sit together &mdash;
  scheduled posts first, newest at the top. Tap a tile to preview it per channel.</p>
</section>
{W._plan_subnav("grid")}
{grid_html}
"""
    return W._layout("Grid preview", body, active="create")


def api_plan_board():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.board import board_by_column, load_board

    cols = board_by_column(load_board(pid))
    return jsonify(
        {
            "ok": True,
            "board": {c: [card.to_dict() for card in cards] for c, cards in cols.items()},
        }
    )


def api_plan_board_add():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.board import add_card

    body = request.get_json(silent=True) or {}
    card = add_card(pid, str(body.get("title") or ""), str(body.get("note") or ""))
    if card is None:
        return jsonify({"error": "Give the idea a title (the board may also be full)."}), 400
    return jsonify({"ok": True, "card": card.to_dict()})


def api_plan_board_move():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.board import move_card

    body = request.get_json(silent=True) or {}
    card = move_card(pid, str(body.get("card_id") or ""), str(body.get("column") or ""))
    if card is None:
        return jsonify({"error": "Unknown card or column."}), 400
    return jsonify({"ok": True, "card": card.to_dict()})


def api_plan_board_delete():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.content_engine.board import delete_card

    body = request.get_json(silent=True) or {}
    ok = delete_card(pid, str(body.get("card_id") or ""))
    return jsonify({"ok": bool(ok)})


def api_plan_board_promote():
    """Promote an idea card into a real free-text draft and advance it to
    'drafted'. The draft is seeded from the idea text verbatim (no AI — works
    with no provider) as a starting point the club then edits / regenerates."""
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.club_platform.stub_pack_store import save_pack
    from mediahub.content_engine.board import link_pack, load_board

    body = request.get_json(silent=True) or {}
    card_id = str(body.get("card_id") or "")
    card = next((c for c in load_board(pid) if c.id == card_id), None)
    if card is None:
        return jsonify({"error": "Unknown card."}), 400
    if card.pack_id:
        return jsonify({"ok": True, "pack_id": card.pack_id, "already": True})
    seed = (card.note or card.title).strip()
    pack = save_pack(
        "free_text",
        {"free_text": seed},
        # D-25: prompt-led draft — no fabricated confidence badge.
        [{"platform": "Draft", "caption": seed, "hashtags": [], "confidence": None}],
        profile_id=pid,
    )
    updated = link_pack(pid, card_id, pack["pack_id"], column="drafted")
    return jsonify(
        {
            "ok": True,
            "pack_id": pack["pack_id"],
            "card": updated.to_dict() if updated else None,
        }
    )


def plan_board_page():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.content_engine.board import (
        COLUMN_LABELS,
        COLUMNS,
        board_by_column,
        load_board,
    )

    cols = board_by_column(load_board(pid))

    def _card_html(card) -> str:
        note = f'<p class="mh-bd-note">{_h(card.note)}</p>' if card.note else ""
        if card.pack_id:
            actions = (
                f'<a class="mh-bd-act" href="{url_for("stub_pack_view", pack_id=card.pack_id)}">Open draft &rarr;</a>'
                f'<a class="mh-bd-act" href="{url_for("plan_preview_page", pack_id=card.pack_id)}">Preview</a>'
            )
        elif card.column == "idea":
            actions = (
                f'<button type="button" class="mh-bd-act" onclick="mhBoardPromote(this)" '
                f'data-card="{_h(card.id)}" title="Turn this idea into a free-text draft">Promote to draft</button>'
            )
        else:
            actions = ""
        # I-1: a non-drag "Move to" select so touch + keyboard users can move
        # a card between columns (HTML5 drag never fires from touch). Drag
        # stays as the desktop enhancement.
        move_opts = "".join(
            f'<option value="{_h(c2)}">{_h(COLUMN_LABELS[c2])}</option>'
            for c2 in COLUMNS
            if c2 != card.column
        )
        move_select = (
            f'<select class="mh-bd-move" onchange="mhBoardMove(this)" '
            f'data-card="{_h(card.id)}" aria-label="Move {_h(card.title)} to a column">'
            f'<option value="">Move to&hellip;</option>{move_opts}</select>'
        )
        return (
            f'<div class="mh-bd-card" draggable="true" data-card="{_h(card.id)}">'
            f'<div class="mh-bd-card-head"><strong>{_h(card.title)}</strong>'
            f'<button type="button" class="mh-bd-del" onclick="mhBoardDelete(this)" '
            f'data-card="{_h(card.id)}" title="Delete">&times;</button></div>'
            f"{note}"
            f'<div class="mh-bd-actions">{actions}{move_select}</div></div>'
        )

    columns_html = ""
    for col in COLUMNS:
        cards = cols.get(col, [])
        cards_html = "".join(_card_html(c) for c in cards)
        add_form = (
            '<div class="mh-bd-add">'
            f'<input type="text" class="mh-bd-add-title" aria-label="New idea" placeholder="New idea…" '
            f"onkeydown=\"if(event.key==='Enter')mhBoardAdd(this)\"/>"
            '<button type="button" class="mh-bd-add-btn" onclick="mhBoardAdd(this)">Add</button>'
            '<span class="mh-bd-add-hint">or press Enter to add</span>'
            "</div>"
            if col == "idea"
            else ""
        )
        columns_html += (
            f'<section class="mh-bd-col" data-col="{_h(col)}" '
            f'ondragover="mhBoardOver(event)" ondragleave="mhBoardLeave(event)" ondrop="mhBoardDrop(event)">'
            f'<h2 class="mh-bd-col-h">{_h(COLUMN_LABELS[col])}'
            f'<span class="mh-bd-count">{len(cards)}</span></h2>'
            f"{add_form}"
            f'<div class="mh-bd-cards">{cards_html}</div>'
            "</section>"
        )

    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-3);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Plan · Board</span>
  <h1>The committee <em class="editorial">whiteboard.</em></h1>
  <p class="lede">Throw ideas on the board, drag them as they progress, and turn a good one into a
  draft with one click &mdash; it flows straight into the previews and the calendar. Nothing posts from here.</p>
</section>

{W._plan_subnav("board")}

<span class="dim" id="mh-bd-status" style="font-size:12.5px;display:block;min-height:18px;margin:0 2px 8px"></span>
<div class="mh-bd-board">{columns_html}</div>

<script>
var MH_BD = {{
  add: {json.dumps(url_for("api_plan_board_add"))},
  move: {json.dumps(url_for("api_plan_board_move"))},
  del: {json.dumps(url_for("api_plan_board_delete"))},
  promote: {json.dumps(url_for("api_plan_board_promote"))},
  draft: {json.dumps(url_for("stub_pack_view", pack_id="__PACK__"))},
  preview: {json.dumps(url_for("plan_preview_page", pack_id="__PACK__"))},
  cols: {json.dumps(list(COLUMNS))},
  labels: {json.dumps(COLUMN_LABELS)}
}};
function mhBoardStatus(m, warn) {{
  var s = document.getElementById('mh-bd-status');
  if (s) {{ s.textContent = m || ''; s.style.color = warn ? 'var(--bad)' : 'var(--ink-muted)'; }}
}}
function mhBoardFail(msg) {{
  mhBoardStatus(msg, true);
  if (window.MH && MH.toast) MH.toast(msg, 'error');
}}
// D-26: every board mutation updates the DOM in place — the POST stays, the
// reload goes. `fail` reverts the optimistic change when the server says no.
function mhBoardPost(url, payload, ok, fail) {{
  fetch(url, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}})
    .then(function(r){{return r.json();}}).then(function(j){{
      if (j.ok === false || j.error) {{ if (fail) fail(); mhBoardFail(j.error || 'Could not update.'); return; }}
      if (ok) ok(j);
    }}).catch(function(){{ if (fail) fail(); mhBoardFail('Could not update — check your connection and try again.'); }});
}}
function mhBoardCards(col) {{
  return document.querySelector('.mh-bd-col[data-col="' + col + '"] .mh-bd-cards');
}}
function mhBoardRecount() {{
  document.querySelectorAll('.mh-bd-col').forEach(function (col) {{
    var badge = col.querySelector('.mh-bd-count');
    if (badge) badge.textContent = col.querySelectorAll('.mh-bd-card').length;
  }});
}}
function mhBoardMoveOpts(card, column) {{
  var sel = card.querySelector('.mh-bd-move');
  if (!sel) return;
  sel.innerHTML = '';
  var first = document.createElement('option');
  first.value = ''; first.innerHTML = 'Move to&hellip;';
  sel.appendChild(first);
  MH_BD.cols.forEach(function (c) {{
    if (c === column) return;
    var o = document.createElement('option');
    o.value = c; o.textContent = MH_BD.labels[c] || c;
    sel.appendChild(o);
  }});
  sel.value = '';
}}
// Build a fresh idea card element (textContent for the title/note — never HTML).
function mhBoardCardEl(card) {{
  var el = document.createElement('div');
  el.className = 'mh-bd-card'; el.draggable = true; el.dataset.card = card.id;
  var head = document.createElement('div'); head.className = 'mh-bd-card-head';
  var strong = document.createElement('strong'); strong.textContent = card.title;
  var del = document.createElement('button');
  del.type = 'button'; del.className = 'mh-bd-del'; del.dataset.card = card.id;
  del.title = 'Delete'; del.innerHTML = '&times;';
  del.addEventListener('click', function () {{ mhBoardDelete(del); }});
  head.appendChild(strong); head.appendChild(del);
  el.appendChild(head);
  if (card.note) {{
    var note = document.createElement('p'); note.className = 'mh-bd-note';
    note.textContent = card.note; el.appendChild(note);
  }}
  var actions = document.createElement('div'); actions.className = 'mh-bd-actions';
  var promote = document.createElement('button');
  promote.type = 'button'; promote.className = 'mh-bd-act'; promote.dataset.card = card.id;
  promote.title = 'Turn this idea into a free-text draft';
  promote.textContent = 'Promote to draft';
  promote.addEventListener('click', function () {{ mhBoardPromote(promote); }});
  actions.appendChild(promote);
  var sel = document.createElement('select');
  sel.className = 'mh-bd-move'; sel.dataset.card = card.id;
  sel.setAttribute('aria-label', 'Move ' + card.title + ' to a column');
  sel.addEventListener('change', function () {{ mhBoardMove(sel); }});
  actions.appendChild(sel);
  el.appendChild(actions);
  mhBoardMoveOpts(el, card.column || 'idea');
  return el;
}}
function mhBoardAdd(el) {{
  // H-21: called from the input (Enter) or the Add button — resolve the input
  // either way, and tell the user why nothing happened on an empty title.
  var box = el.closest ? el.closest('.mh-bd-add') : null;
  var inp = box ? box.querySelector('.mh-bd-add-title') : el;
  var t = (inp && inp.value ? inp.value : '').trim();
  if (!t) {{ mhBoardStatus('Type an idea first, then press Add.', true); if (inp) inp.focus(); return; }}
  if (inp) {{ inp.value = ''; inp.focus(); }}
  mhBoardStatus('Adding…');
  mhBoardPost(MH_BD.add, {{title: t}}, function (j) {{
    var cards = mhBoardCards((j.card && j.card.column) || 'idea');
    if (cards && j.card) cards.insertBefore(mhBoardCardEl(j.card), cards.firstChild);
    mhBoardRecount();
    mhBoardStatus('Added to Ideas.');
  }}, function () {{ if (inp) {{ inp.value = t; inp.focus(); }} }});
}}
function mhBoardDelete(btn) {{
  var card = btn.closest ? btn.closest('.mh-bd-card') : null;
  if (!card) return;
  var parent = card.parentNode, next = card.nextSibling;
  card.remove(); mhBoardRecount();
  mhBoardPost(MH_BD.del, {{card_id: btn.dataset.card}}, function () {{
    mhBoardStatus('Deleted.');
  }}, function () {{ if (parent) parent.insertBefore(card, next); mhBoardRecount(); }});
}}
function mhBoardPromote(btn) {{
  btn.disabled = true; mhBoardStatus('Creating a draft from this idea…');
  mhBoardPost(MH_BD.promote, {{card_id: btn.dataset.card}}, function (j) {{
    var card = btn.closest ? btn.closest('.mh-bd-card') : null;
    var column = (j.card && j.card.column) || 'drafted';
    if (card && j.pack_id) {{
      var actions = card.querySelector('.mh-bd-actions');
      var sel = card.querySelector('.mh-bd-move');
      if (actions && !card.querySelector('a.mh-bd-act')) {{
        var open = document.createElement('a');
        open.className = 'mh-bd-act';
        open.href = MH_BD.draft.replace('__PACK__', encodeURIComponent(j.pack_id));
        open.innerHTML = 'Open draft &rarr;';
        var prev = document.createElement('a');
        prev.className = 'mh-bd-act';
        prev.href = MH_BD.preview.replace('__PACK__', encodeURIComponent(j.pack_id));
        prev.textContent = 'Preview';
        actions.insertBefore(prev, sel || null);
        actions.insertBefore(open, prev);
      }}
      btn.remove();
      var target = mhBoardCards(column);
      if (target) target.insertBefore(card, target.firstChild);
      mhBoardMoveOpts(card, column);
      mhBoardRecount();
    }}
    mhBoardStatus('Promoted — the draft is ready to open and edit.');
  }}, function () {{ btn.disabled = false; }});
}}
document.addEventListener('dragstart', function(e) {{
  var card = e.target.closest ? e.target.closest('.mh-bd-card') : null;
  if (!card) return;
  e.dataTransfer.setData('text/plain', card.dataset.card);
  e.dataTransfer.effectAllowed = 'move';
}});
function mhBoardOver(e) {{ e.preventDefault(); var c = e.currentTarget; if (c) c.classList.add('mh-bd-drop'); }}
function mhBoardLeave(e) {{ var c = e.currentTarget; if (c) c.classList.remove('mh-bd-drop'); }}
// D-26: a move (drag-drop or the I-1 select) lifts the card into its new
// column at once; a failed POST puts it back where it was.
function mhBoardMoveTo(cardId, column) {{
  if (!cardId || !column) return;
  var card = document.querySelector('.mh-bd-card[data-card="' + cardId + '"]');
  var target = mhBoardCards(column);
  if (!card || !target) return;
  var parent = card.parentNode, next = card.nextSibling;
  var fromCol = card.closest('.mh-bd-col');
  var fromKey = fromCol ? fromCol.dataset.col : '';
  target.insertBefore(card, target.firstChild);
  mhBoardMoveOpts(card, column);
  mhBoardRecount();
  mhBoardPost(MH_BD.move, {{card_id: cardId, column: column}}, function () {{
    mhBoardStatus('Moved to ' + (MH_BD.labels[column] || column) + '.');
  }}, function () {{
    if (parent) parent.insertBefore(card, next);
    mhBoardMoveOpts(card, fromKey);
    mhBoardRecount();
  }});
}}
function mhBoardDrop(e) {{
  e.preventDefault();
  var col = e.currentTarget; if (col) col.classList.remove('mh-bd-drop');
  var id = e.dataTransfer.getData('text/plain');
  if (id && col) mhBoardMoveTo(id, col.dataset.col);
}}
// I-1: non-drag move (touch / keyboard) via the per-card "Move to" select.
function mhBoardMove(sel) {{
  if (!sel || !sel.value) return;
  mhBoardMoveTo(sel.getAttribute('data-card'), sel.value);
}}
</script>
"""
    return W._layout("Plan board", body, active="create")


def api_plan_analytics_record():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.analytics.store import METRIC_KEYS, engagement_score, record_metric

    body = request.get_json(silent=True) or {}
    metrics = {k: body.get(k, 0) for k in METRIC_KEYS}
    if not any(metrics.values()):
        # Fall back to a nested {"metrics": {...}} object (what the page posts).
        # Guard the type: a truthy non-dict (a number/string/list) made the old
        # ``(... or {}).get`` raise AttributeError and 500 the route.
        nested = body.get("metrics")
        nested = nested if isinstance(nested, dict) else {}
        metrics = {k: nested.get(k, 0) for k in METRIC_KEYS}

    # Honour the "…and at least one metric" the error message promises: a
    # submission with no metric > 0 (the form's all-zero default, or a
    # negative-only value) carries no measurable performance. Reject it here
    # so a data-free row never enters the store, is never counted toward
    # MIN_SAMPLES, and never fabricates a "% below your average" planner signal.
    def _positive(v: object) -> bool:
        try:
            return int(v) > 0
        except (TypeError, ValueError):
            return False

    if not any(_positive(v) for v in metrics.values()):
        return jsonify(
            {"error": "Pick a post type and a valid date (and at least one metric)."}
        ), 400
    rec = record_metric(
        pid,
        str(body.get("post_type") or ""),
        str(body.get("posted_date") or ""),
        metrics,
        posted_hour=body.get("posted_hour"),
        pack_id=str(body.get("pack_id") or ""),
        platform=str(body.get("platform") or ""),
    )
    if rec is None:
        return jsonify(
            {"error": "Pick a post type and a valid date (and at least one metric)."}
        ), 400
    # D-26: the page appends the logged row in place — hand it the same
    # deterministic engagement number the server-rendered rows show.
    return jsonify(
        {"ok": True, "metric": rec.to_dict(), "engagement": engagement_score(rec.metrics)}
    )


def api_plan_analytics_delete():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.analytics.store import delete_metric

    body = request.get_json(silent=True) or {}
    return jsonify({"ok": bool(delete_metric(pid, str(body.get("id") or "")))})


def api_plan_analytics_digest():
    """AI performance digest — phrases the deterministic attribution numbers.
    Honest provider errors; the planner already uses the numbers without it."""
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.analytics.attribution import attribute
    from mediahub.analytics.digest import performance_digest
    from mediahub.analytics.store import load_metrics
    from mediahub.media_ai.llm import ClaudeUnavailableError

    attribution = attribute(load_metrics(pid))
    if attribution.n_posts == 0:
        return jsonify({"error": "Record a few posts first — nothing to summarise yet."}), 400
    try:
        digest = performance_digest(attribution)
    except ClaudeUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        current_app.logger.exception("performance digest failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "digest": digest})


def plan_analytics_page():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.analytics.attribution import MIN_SAMPLES, attribute
    from mediahub.analytics.store import METRIC_KEYS, engagement_score, load_metrics
    from mediahub.club_platform.post_types import post_types_for
    from mediahub.sport_profiles import load_sport_profile

    prof = W._active_profile()
    sport = W._org_calendar_sport(prof)
    metrics = load_metrics(pid)
    attribution = attribute(metrics)

    # Post-type dropdown for the recording form (this sport's enabled types).
    try:
        spts = post_types_for(load_sport_profile(sport))
    except Exception:
        spts = []
    type_titles = {spt.slug: spt.title for spt in spts}
    type_opts = "".join(f'<option value="{_h(spt.slug)}">{_h(spt.title)}</option>' for spt in spts)

    # H-14: the store and API already model platform + pack_id, but the
    # form never offered them. A platform select (blank "not sure"
    # default) and an optional "Which draft?" select of this org's recent
    # drafts close the gap; both prefill from query params so a draft
    # page can link straight here.
    _sel_platform = (request.args.get("platform") or "").strip().lower()
    _sel_pack = (request.args.get("pack_id") or "").strip()
    platform_opts = '<option value="">Not sure / other</option>' + "".join(
        f'<option value="{_h(slug)}"{" selected" if slug == _sel_platform else ""}>'
        f"{_h(label)}</option>"
        for slug, label in W._ORG_PLATFORMS
    )
    from mediahub.club_platform.stub_pack_store import list_packs as _an_list_packs
    from mediahub.club_platform.stub_pack_store import load_pack as _an_load_pack

    _pack_rows: list[tuple[str, str]] = []
    try:
        for _meta in _an_list_packs(limit=40):
            _prec = _an_load_pack(_meta.get("pack_id", ""))
            if _prec is None or (_prec.get("profile_id") or "") != pid:
                continue
            _pack_rows.append((_prec.get("pack_id", ""), _prec.get("title") or "Draft"))
            if len(_pack_rows) >= 15:
                break
        # An older draft arriving via ?pack_id= must still appear selected.
        if _sel_pack and _sel_pack not in {pk for pk, _ in _pack_rows}:
            _prec = _an_load_pack(_sel_pack)
            if _prec is not None and (_prec.get("profile_id") or "") == pid:
                _pack_rows.insert(0, (_sel_pack, _prec.get("title") or "Draft"))
    except Exception:
        _pack_rows = []
    pack_opts = '<option value="">Not linked to a draft</option>' + "".join(
        f'<option value="{_h(pk)}"{" selected" if pk == _sel_pack else ""}>'
        f"{_h(t[:60])}</option>"
        for pk, t in _pack_rows
    )
    _platform_labels = dict(W._ORG_PLATFORMS)

    # The attribution table — what's working, with an index bar.
    if attribution.by_type:
        rows = ""
        for tp in attribution.by_type:
            title = _h(type_titles.get(tp.post_type, tp.post_type.replace("_", " ").title()))
            pct = round((tp.index - 1.0) * 100)
            trusted = tp.n >= MIN_SAMPLES
            cls = "mh-an-up" if pct >= 0 else "mh-an-down"
            bar_w = max(4, min(100, round(tp.index * 50)))
            pct_txt = f"{'+' if pct >= 0 else ''}{pct}%"
            note = (
                ""
                if trusted
                else ' <span class="dim" style="font-size:11px">(needs ≥2 to count)</span>'
            )
            rows += (
                f"<tr><td>{title}{note}</td>"
                f'<td style="text-align:right;font-variant-numeric:tabular-nums">{int(tp.n)}</td>'
                f'<td style="text-align:right;font-variant-numeric:tabular-nums">{tp.avg_engagement:.0f}</td>'
                f'<td><div class="mh-an-bar"><span class="{cls}" style="width:{bar_w}%"></span></div></td>'
                f'<td class="{cls}" style="text-align:right;font-variant-numeric:tabular-nums">{pct_txt}</td></tr>'
            )
        best_bits = []
        if attribution.best_dow_label():
            best_bits.append(f"<strong>{_h(attribution.best_dow_label())}</strong>")
        if attribution.best_hour is not None:
            best_bits.append(f"around <strong>{int(attribution.best_hour):02d}:00</strong>")
        best_line = (
            f'<p class="dim" style="font-size:12.5px">Your posts have done best on '
            + " ".join(best_bits)
            + ".</p>"
            if best_bits
            else ""
        )
        table = (
            '<div class="card"><h2 style="margin-top:0">What’s working</h2>'
            '<p class="dim" style="font-size:12.5px;margin-top:0">Engagement = likes + 2&times;comments + '
            "3&times;shares + 2&times;saves. The planner nudges the types that beat your own average.</p>"
            '<table class="mh-an-table"><thead><tr><th>Post type</th><th>Posts</th>'
            "<th>Avg engagement</th><th>vs your average</th><th></th></tr></thead>"
            f"<tbody>{rows}</tbody></table>{best_line}</div>"
        )
    else:
        table = (
            '<div class="card" style="text-align:center;padding:36px 24px">'
            '<h2 style="margin:0 0 6px">No performance recorded yet</h2>'
            '<p class="dim" style="max-width:520px;margin:0 auto">Post an approved card by hand, '
            "then come back and log how it did. Once you&rsquo;ve a couple in a type, the planner "
            "starts ranking what actually works for your club. Nothing is auto-collected.</p></div>"
        )

    # Recent recorded posts (with delete). Platform shows when recorded.
    recent = ""
    for m in sorted(metrics, key=lambda x: x.recorded_at, reverse=True)[:12]:
        title = _h(type_titles.get(m.post_type, m.post_type.replace("_", " ").title()))
        eng = _h(str(engagement_score(m.metrics)))
        _plat = ""
        if m.platform:
            _plat = f" · {_h(_platform_labels.get(m.platform, m.platform))}"
        recent += (
            f'<div class="mh-an-row" data-id="{_h(m.id)}">'
            f'<span style="flex:1">{title} <span class="dim">· {_h(m.posted_date)}{_plat}</span></span>'
            f'<span class="dim" style="font-variant-numeric:tabular-nums">{eng} eng</span>'
            f'<button type="button" class="btn" style="font-size:11px;padding:2px 8px" '
            f'onclick="mhAnDelete(this)">remove</button></div>'
        )

    metric_inputs = "".join(
        f'<label class="mh-an-mlabel">{_h(k)}<input type="number" min="0" id="mh-an-{_h(k)}" '
        f'value="0" style="width:88px"/></label>'
        for k in METRIC_KEYS
    )

    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-3);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Plan · Performance</span>
  <h1>What actually <em class="editorial">works.</em></h1>
  <p class="lede">Post by hand, then log how it did &mdash; MediaHub learns which post types earn your club
  the most engagement and feeds that straight back into the plan. First-party and honest: nothing is
  auto-collected (that waits on publishing integrations), and the numbers are yours.</p>
</section>

{W._plan_subnav("performance")}

{table}

<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">Log a post&rsquo;s performance</h2>
  <div class="mh-an-form">
    <label class="mh-an-mlabel">Post type<select id="mh-an-type" style="min-width:170px">{type_opts}</select></label>
    <label class="mh-an-mlabel">Platform<select id="mh-an-platform" style="min-width:150px">{platform_opts}</select></label>
    <label class="mh-an-mlabel">Which draft? (optional)<select id="mh-an-pack" style="min-width:180px">{pack_opts}</select></label>
    <label class="mh-an-mlabel">Date posted<input type="date" id="mh-an-date"/></label>
    <label class="mh-an-mlabel">Hour (0&ndash;23, optional)<input type="number" min="0" max="23" id="mh-an-hour" style="width:88px"/></label>
    {metric_inputs}
    <button type="button" class="btn primary" onclick="mhAnRecord(this)">Log it</button>
  </div>
  <span class="dim" id="mh-an-status" style="font-size:12.5px"></span>
  <div id="mh-an-recent" style="margin-top:14px">{recent}</div>
</div>

<div class="card" style="margin-top:16px">
  <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
    <button type="button" class="btn" id="mh-an-digest-btn" onclick="mhAnDigest(this)" data-loader-text="Writing">AI performance digest</button>
    <span class="dim" style="font-size:12px">An optional written summary of the numbers above. Needs an AI provider; the planner uses the numbers either way.</span>
  </div>
  <div id="mh-an-digest" style="margin-top:10px"></div>
</div>

<script>
var MH_AN = {{
  record: {json.dumps(url_for("api_plan_analytics_record"))},
  del: {json.dumps(url_for("api_plan_analytics_delete"))},
  digest: {json.dumps(url_for("api_plan_analytics_digest"))},
  keys: {json.dumps(list(METRIC_KEYS))},
  titles: {json.dumps(type_titles)},
  platforms: {json.dumps(_platform_labels)}
}};
function mhAnStatus(m, warn) {{
  var s = document.getElementById('mh-an-status');
  if (s) {{ s.textContent = m || ''; s.style.color = warn ? 'var(--bad)' : 'var(--ink-muted)'; }}
}}
// D-26: a logged post appears in the recent list at once — same shape as the
// server-rendered rows (textContent only, never HTML from data).
function mhAnAppendRow(m, eng) {{
  var list = document.getElementById('mh-an-recent'); if (!list) return;
  var row = document.createElement('div');
  row.className = 'mh-an-row'; row.dataset.id = m.id || '';
  var title = MH_AN.titles[m.post_type] || String(m.post_type || '').replace(/_/g, ' ');
  var plat = m.platform ? (' · ' + (MH_AN.platforms[m.platform] || m.platform)) : '';
  var left = document.createElement('span'); left.style.flex = '1';
  left.textContent = title + ' ';
  var dim = document.createElement('span'); dim.className = 'dim';
  dim.textContent = '· ' + (m.posted_date || '') + plat;
  left.appendChild(dim);
  var engEl = document.createElement('span'); engEl.className = 'dim';
  engEl.style.fontVariantNumeric = 'tabular-nums';
  engEl.textContent = eng + ' eng';
  var del = document.createElement('button');
  del.type = 'button'; del.className = 'btn';
  del.style.fontSize = '11px'; del.style.padding = '2px 8px';
  del.textContent = 'remove';
  del.addEventListener('click', function () {{ mhAnDelete(del); }});
  row.appendChild(left); row.appendChild(engEl); row.appendChild(del);
  list.insertBefore(row, list.firstChild);
  while (list.children.length > 12) list.removeChild(list.lastChild);
}}
function mhAnRecord(btn) {{
  var metrics = {{}};
  MH_AN.keys.forEach(function(k){{ metrics[k] = parseInt(document.getElementById('mh-an-'+k).value || '0', 10) || 0; }});
  var hour = document.getElementById('mh-an-hour').value;
  var payload = {{
    post_type: document.getElementById('mh-an-type').value,
    posted_date: document.getElementById('mh-an-date').value,
    posted_hour: hour === '' ? null : parseInt(hour, 10),
    platform: document.getElementById('mh-an-platform').value,
    pack_id: document.getElementById('mh-an-pack').value,
    metrics: metrics
  }};
  mhAnStatus('Saving…');
  fetch(MH_AN.record, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}})
    .then(function(r){{return r.json();}}).then(function(j){{
      if (!j.ok) {{
        mhAnStatus(j.error || 'Could not save.', true);
        if (window.MH && MH.toast) MH.toast(j.error || 'Could not save.', 'error');
        return;
      }}
      // D-26: no reload — the row appears in place and the form keeps its post
      // type, platform, draft and date, so logging a run of posts is painless.
      // Only the metric counts reset (they belong to the post just logged).
      mhAnAppendRow(j.metric || {{}}, j.engagement || 0);
      MH_AN.keys.forEach(function(k){{ var el = document.getElementById('mh-an-'+k); if (el) el.value = '0'; }});
      mhAnStatus('Logged — added to your recent posts. The averages above refresh next visit.');
    }}).catch(function(){{
      mhAnStatus('Could not save.', true);
      if (window.MH && MH.toast) MH.toast('Could not save — check your connection and try again.', 'error');
    }});
}}
// D-26: remove deletes the row in place (optimistically); a failed POST puts
// it back and MH.toasts the reason.
function mhAnDelete(btn) {{
  var row = btn.closest('.mh-an-row'); if (!row) return;
  var parent = row.parentNode, next = row.nextSibling;
  row.remove();
  fetch(MH_AN.del, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{id: row.dataset.id}})}})
    .then(function(r){{return r.json();}}).then(function(j){{
      // JS2-2: error bodies like {{"error": "No organisation active."}} carry
      // no ok key — treat them as failures too (match the sibling handlers).
      if (!j || j.ok === false || j.error) {{
        if (parent) parent.insertBefore(row, next);
        mhAnStatus('Could not remove that row.', true);
        if (window.MH && MH.toast) MH.toast('Could not remove that row.', 'error');
        return;
      }}
      mhAnStatus('Removed.');
    }}).catch(function(){{
      if (parent) parent.insertBefore(row, next);
      mhAnStatus('Could not remove that row.', true);
      if (window.MH && MH.toast) MH.toast('Could not remove that row — check your connection and try again.', 'error');
    }});
}}
function mhAnDigest(btn) {{
  var box = document.getElementById('mh-an-digest');
  btn.disabled = true; box.innerHTML = '<span class="dim">Writing…</span>';
  // D-27: visible loading treatment for the AI digest call.
  if (window.MH) MH.showLoader(btn.dataset.loaderText || 'Writing', 'Reading your logged results…');
  fetch(MH_AN.digest, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: '{{}}'}})
    .then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok, j:j}}; }}); }})
    .then(function(res){{
      btn.disabled = false;
      if (window.MH) MH.hideLoader();
      var j = res.j || {{}};
      if (!res.ok || !j.ok) {{ box.innerHTML = '<p class="dim" style="color:var(--warn)">' + (j.error || 'Could not write a digest.') + '</p>'; return; }}
      var d = j.digest || {{}};
      var html = '';
      if (d.summary) html += '<p style="font-weight:600;margin:0 0 6px">' + d.summary.replace(/</g,'&lt;') + '</p>';
      (d.takeaways || []).forEach(function(t){{ html += '<li style="margin:2px 0">' + (t.text||'').replace(/</g,'&lt;') + '</li>'; }});
      box.innerHTML = html ? ('<ul style="margin:0;padding-left:18px">' + html + '</ul>') : '<p class="dim">No takeaways.</p>';
    }}).catch(function(){{ btn.disabled = false; if (window.MH) MH.hideLoader(); box.innerHTML = '<p class="dim" style="color:var(--warn)">Could not write a digest.</p>'; }});
}}
</script>
"""
    return W._layout("Performance", body, active="create")


def plan_ad_variants_page(pack_id):
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.ad_export import all_ad_platforms, ad_platform, build_variant_set
    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    if rec is None or (rec.get("profile_id") or "") != pid:
        abort(404)
    prof = W._active_profile()
    sponsor = W._pack_sponsor(rec, prof)

    spec = ad_platform(request.args.get("platform", "")) or all_ad_platforms()[0]
    vset = build_variant_set(rec.get("cards") or [], sponsor, spec.slug)

    tabs = "".join(
        f'<a class="mh-cp-tab{" active" if p.slug == spec.slug else ""}" '
        f'href="{url_for("plan_ad_variants_page", pack_id=pack_id, platform=p.slug)}">{_h(p.name)}</a>'
        for p in all_ad_platforms()
    )
    sizes_html = "".join(
        f"<li><strong>{_h(s.name)}</strong> &mdash; {int(s.width)}&times;{int(s.height)} "
        f'<span class="dim">({_h(s.aspect_label())})</span></li>'
        for s in spec.sizes
    )
    variants_html = ""
    for v in vset.variants:
        tags = (
            '<p class="dim" style="font-size:11.5px;margin:4px 0 0">'
            + " ".join(f"#{_h(h)}" for h in v.hashtags)
            + "</p>"
            if v.hashtags
            else ""
        )
        variants_html += (
            '<div class="mh-av-variant"><span class="mh-av-label">'
            f'{_h(v.label)}</span><div style="flex:1"><p style="margin:0">{_h(v.caption)}</p>'
            f"{tags}</div></div>"
        )
    if not variants_html:
        variants_html = (
            '<p class="dim">This draft has no copy to turn into ad variants yet. '
            f'<a href="{url_for("stub_pack_view", pack_id=pack_id)}" style="text-decoration:underline">'
            "Add or regenerate cards</a> first.</p>"
        )

    sponsor_line = (
        f"tagged for <strong>{_h(sponsor)}</strong>"
        if sponsor
        else '<span style="color:var(--warn)">no sponsor set on this draft or your profile</span>'
    )
    export_url = url_for("api_plan_ad_variants_export", pack_id=pack_id, platform=spec.slug)

    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-3);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Plan · Sponsor ad set</span>
  <h1>A/B creative, <em class="editorial">ready to run.</em></h1>
  <p class="lede">Turn this sponsor draft&rsquo;s angles into an A/B ad set ({sponsor_line}), sized for the
  platform&rsquo;s ad manager. <strong>MediaHub prepares the creative; it never buys or places ads</strong> &mdash;
  you upload these by hand where a human controls targeting and spend.
  <a href="{url_for("stub_pack_view", pack_id=pack_id)}" style="text-decoration:underline">Back to the draft &rarr;</a></p>
</section>

<div class="mh-cp-bar"><div class="mh-cp-tabs">{tabs}</div>
  <a class="btn" href="{export_url}">Export manifest (.txt)</a></div>
<p class="dim" style="font-size:11.5px;margin:0 0 14px">{_h(spec.source)}</p>

<div class="mh-av-grid">
  <div class="card"><h2 style="margin-top:0">Sizes to prepare</h2>
    <ul class="mh-av-sizes">{sizes_html}</ul></div>
  <div class="card"><h2 style="margin-top:0">Variants ({len(vset.variants)})</h2>
    {variants_html}</div>
</div>
"""
    return W._layout("Sponsor ad set", body, active="create")


def api_plan_ad_variants_export(pack_id):
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "No organisation active."}), 403
    from mediahub.ad_export import build_variant_set, manifest_text
    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    if rec is None or (rec.get("profile_id") or "") != pid:
        abort(404)
    sponsor = W._pack_sponsor(rec, W._active_profile())
    vset = build_variant_set(
        rec.get("cards") or [], sponsor, str(request.args.get("platform") or "meta")
    )
    if vset is None:
        return jsonify({"error": "Unknown ad platform."}), 400
    text = manifest_text(vset)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"ad-set-{vset.platform.slug}-{pack_id}")
    return current_app.response_class(
        text,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{safe}.txt"'},
    )


def stub_sponsor_post():
    return redirect(
        url_for("free_text_chat_page", seed=W._RETIRED_STUB_SEEDS["sponsor_activation"])
    )


def stub_session_update():
    return redirect(url_for("free_text_chat_page", seed=W._RETIRED_STUB_SEEDS["session_update"]))


def stub_packs_list():
    from mediahub.club_platform.stub_pack_store import list_packs

    # Fail-soft: a corrupted pack store would otherwise 500 the
    # Drafts page. Treat the failure as "no packs visible" and tell
    # the user the store wasn't reachable so they don't think their
    # drafts were silently deleted.
    items: list = []
    store_failed = False
    try:
        items = list_packs(limit=100)
        # Tenant isolation (same rule as _can_access_pack): the index must
        # not list other orgs' drafts — a pack's title is the first line
        # of another org's free-text brief. Unstamped legacy packs stay
        # visible, and the active_pid-None sandbox keeps everything
        # visible, exactly like the per-pack routes.
        active_pid = W._active_profile_id()
        if active_pid is not None:
            from mediahub.club_platform.stub_pack_store import load_pack as _load_pack

            items = [
                it
                for it in items
                if W._can_access_pack(_load_pack(it.get("pack_id", "")), active_pid)
            ]
    except Exception as e:
        W.log.warning("drafts: list_packs failed: %s", e)
        store_failed = True
    if not items:
        if store_failed:
            body = (
                '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
                '<span class="mh-hero-eyebrow">Saved drafts</span>'
                '<h1>Couldn&rsquo;t load your <em class="editorial">drafts</em>.</h1>'
                '<p class="lede">'
                "The draft store wasn't readable on this deployment, "
                "so the list is empty even if you saved drafts earlier. "
                "Try refreshing &mdash; if it keeps happening, ask your "
                "operator to check the data volume."
                "</p>"
                '<div class="mh-hero-actions">'
                f'<a class="mh-cta-primary" href="{url_for("stub_packs_list")}">Refresh &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{url_for("make_page")}">Start fresh</a>'
                "</div>"
                "</section>"
            )
            return W._layout("Saved drafts", body, active="create")
        body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7)">'
            '<span class="mh-hero-eyebrow">Saved drafts</span>'
            '<h1>Nothing <em class="editorial">drafted</em> yet.</h1>'
            '<p class="lede">'
            "Content packs you generate are kept here so you can come "
            "back, edit, and approve later. Describe any moment in Free "
            "Text &mdash; a sponsor thank-you, a mid-session update, a "
            "shout-out &mdash; or build an Event Preview."
            "</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{url_for("make_page")}">Start creating &rarr;</a>'
            "</div>"
            "</section>"
        )
        return W._layout("Saved drafts", body, active="create")

    rows_html = ""
    for it in items:
        view_url = url_for("stub_pack_view", pack_id=it["pack_id"])
        delete_url = url_for("stub_pack_delete", pack_id=it["pack_id"])
        label = W._STUB_TYPE_LABEL.get(it["stub_type"], it["stub_type"])
        ts = str(it.get("created_at") or "")[:19].replace("T", " ")
        rows_html += (
            f'<tr><td><a href="{view_url}">{_h(it["title"])}</a></td>'
            f'<td><span class="tag info">{_h(label)}</span></td>'
            f"<td>{it['n_cards']}</td>"
            f'<td class="muted">{_h(ts)}</td>'
            f'<td><form method="post" action="{delete_url}" style="display:inline" '
            f"onsubmit=\"return confirm('Delete this draft?')\">"
            f'<button class="btn secondary" type="submit" style="font-size:11px;padding:4px 10px;color:var(--bad);border-color:rgba(244,63,94,0.3)">Delete</button>'
            f"</form></td></tr>"
        )

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Saved drafts</span>
  <h1>Drafts</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{len(items):02d} pack{"s" if len(items) != 1 else ""} saved</span>
  </div>
</section>
<div class="card">
  <table>
    <thead><tr><th>Title</th><th>Type</th><th>Cards</th><th>Created</th><th></th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<p style="margin-top:var(--sp-4)"><a class="btn secondary" href="{url_for("make_page")}">+ New draft</a></p>
"""
    return W._layout("Saved drafts", body, active="create")


def stub_pack_view(pack_id):
    from mediahub.club_platform.stub_pack_store import load_pack
    from mediahub.club_platform.stubs import render_cards_html

    # ``load_pack`` reads from the saved-drafts store; a corrupt
    # row or missing file should land on the same recovery hero as a
    # genuinely-deleted draft, not a 500.
    try:
        rec = load_pack(pack_id)
    except Exception as e:
        W.log.warning("drafts: load_pack(%s) failed: %s", pack_id, e)
        rec = None
    # Tenant isolation: a foreign org probing for the pack gets the
    # same recovery hero as a real miss, so the existence of another
    # org's draft can't be inferred.
    if not W._can_access_pack(rec, W._active_profile_id()):
        rec = None
    if not rec:
        return W._recovery_page(
            "Draft not found",
            "This draft may have been deleted, or the link could be stale. "
            "Your other drafts are on the Saved drafts page.",
            eyebrow="Saved drafts",
            primary_cta=("All drafts", url_for("stub_packs_list")),
            secondary_cta=("Start a new draft", url_for("make_page")),
        )

    # Athlete-spotlight packs open the mode-aware Content builder, scoped to
    # the single composite post (one caption + one graphic + one reel from
    # the approved moments) with the full live toolbar — instead of the
    # generic saved-draft card layout. Other create-tile types will become
    # additional builder modes; today only spotlight is wired.
    if (rec.get("form_data") or {}).get("source") == "athlete_spotlight":
        _sp_name = (rec.get("form_data") or {}).get("swimmer_name") or "Spotlight"
        return W._layout(
            f"Content builder — {_sp_name}",
            W._render_content_builder(pack_id, rec, mode="spotlight"),
            active="create",
        )

    stub_type = rec.get("stub_type", "other")
    type_label = W._STUB_TYPE_LABEL.get(stub_type, stub_type)
    # We pass back = saved-list so "Start over" goes somewhere sensible.
    back_url = url_for("stub_packs_list")
    # /api/drafts/<pid>/card/<idx>/status → strip "/<idx>/status" so
    # render_cards_html can append the correct per-card suffix itself.
    _full_status_url = url_for("api_stub_pack_card_status", pack_id=pack_id, card_idx=0)
    _status_api_base = _full_status_url.rsplit("/", 2)[0]
    _graphic_api_base = url_for("api_stub_pack_create_graphic", pack_id=pack_id, card_idx=0).rsplit(
        "/", 2
    )[0]
    # Per-card Schedule chip — auto scheduling to social is withdrawn, so
    # this renders a disabled "Coming soon" affordance that keeps the
    # toolbar's shape. Drafts stay fully exportable for manual posting.
    _pack_cards = rec.get("cards") or []
    _pack_fd = rec.get("form_data") or {}
    _sched_run_id = str(_pack_fd.get("run_id") or f"_stub_{pack_id}")
    _extra_actions = [
        W._schedule_button_html(_sched_run_id, f"stub:{pack_id}:{_i}", f"stub-card-{_i}")
        for _i in range(len(_pack_cards))
    ]
    cards_html = render_cards_html(
        {"cards": _pack_cards},
        back_url,
        rec.get("title") or "Draft pack",
        pack_id=pack_id,
        status_api_base=_status_api_base,
        graphic_api_base=_graphic_api_base,
        extra_card_actions=_extra_actions,
    )
    # Replace the renderer's default footer to add export + regenerate.
    export_url = url_for("stub_pack_export", pack_id=pack_id)
    # C-11: sponsor / session drafts predate the retirement of their
    # standalone forms — their "new draft" path is now the free-text
    # landing, seeded with the retired type's ask so the prompt box
    # starts in the right place. Other types keep their live form.
    if stub_type in W._RETIRED_STUB_SEEDS:
        regenerate_url = url_for("free_text_chat_page", seed=W._RETIRED_STUB_SEEDS[stub_type])
    else:
        regenerate_url = url_for(
            {
                # Endpoint names are implementation artifacts (kept across
                # the ADR-0013 slug rename); keys are canonical post-type
                # slugs.
                "free_text": "free_text_chat_page",
                "event_preview": "stub_weekend_preview",
            }.get(stub_type, "free_text_chat_page")
        )
    regen_api = url_for("api_stub_pack_regenerate", pack_id=pack_id)
    footer = (
        f'<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">'
        f'<button type="button" class="btn" '
        f'onclick="mhRegenerateDraft(this, {repr(regen_api)}, {len(_pack_cards)})" '
        f'title="Re-run the content engine — the AI Director plans fresh angles, avoiding what you already have">'
        f"&#x21BA; Regenerate (fresh angles)</button>"
        f'<a class="btn secondary" href="{export_url}">Export as text</a>'
        f'<a class="btn secondary" href="{url_for("plan_preview_page", pack_id=pack_id)}" '
        f'title="See this draft the way each platform shows it — crop, safe zone, caption fold">'
        f"Preview per channel</a>"
        f'<a class="btn secondary" href="{url_for("plan_ad_variants_page", pack_id=pack_id)}" '
        f'title="Turn these angles into a sponsor A/B ad set, sized for ad managers (prepared, never placed)">'
        f"Prepare ad set</a>"
        f'<a class="btn secondary" href="{url_for("plan_analytics_page", pack_id=pack_id)}" '
        f'title="Posted this by hand? Log how it did — what works feeds the plan">'
        f"Log performance</a>"
        f'<a class="btn secondary" href="{regenerate_url}">Start a new draft from the form</a>'
        f'<a class="btn secondary" href="{back_url}">&larr; All drafts</a>'
        f"</div>"
    )
    # Prepend a context band showing the type + timestamp.
    ts = (rec.get("created_at") or "")[:19].replace("T", " ")
    header = (
        f'<p class="dim" style="margin-bottom:14px">'
        f'<span class="tag info">{_h(type_label)}</span> '
        f'<span style="margin-left:8px">Generated {_h(ts)}</span></p>'
    )
    # Show any media-library assets the draft was created with so the
    # user can see which photos are attached without re-opening the
    # source form. Profile-scoped: only assets that still belong to
    # the active org are surfaced; foreign or deleted ids are silently
    # skipped so the panel can't leak photos across orgs.
    attached_html = W._render_pack_attached_media(rec)
    # Replace the renderer's default action row. ``render_cards_html``
    # emits the arrow as the unicode character ``←``, not the
    # ``&larr;`` entity — match on the same form or the replace
    # silently no-ops and the export/regenerate footer never appears.
    _default_row = (
        f'<div style="margin-top:24px;display:flex;gap:10px">'
        f'<a class="btn secondary" href="{_h(back_url)}">← Start over</a>'
        f"</div>"
    )
    _new_cards_html = cards_html.replace(_default_row, footer, 1)
    if _new_cards_html == cards_html:
        # PR-118 regression class: any future markup tweak in
        # render_cards_html silently drops the export/regenerate
        # footer — log loudly instead of failing invisibly.
        W.log.warning(
            "stub pack view %s: default action row not found — render_cards_html "
            "markup drifted; export/regenerate footer was not injected",
            pack_id,
        )
    cards_html = _new_cards_html
    # E-11: "Previous versions" — the captions a Regenerate replaced.
    # replace_cards archives {platform, caption} into card_history; this
    # expander is the page that finally shows it (most recent first).
    history = [
        h
        for h in (rec.get("card_history") or [])
        if isinstance(h, dict) and str(h.get("caption") or "").strip()
    ]
    history_html = ""
    if history:
        rows = ""
        for h_item in reversed(history):
            rows += (
                f'<div style="padding:10px 0;border-top:1px solid var(--border)">'
                f'<div style="font-size:10.5px;text-transform:uppercase;'
                f'letter-spacing:0.14em;color:var(--ink-muted);margin-bottom:4px">'
                f"{_h(h_item.get('platform') or 'Post')}</div>"
                f'<div style="font-size:13px;line-height:1.5;white-space:pre-wrap">'
                f"{_h(h_item.get('caption'))}</div></div>"
            )
        _n_prev = len(history)
        history_html = (
            f'<details class="card" style="margin-top:18px">'
            f'<summary style="cursor:pointer;font-weight:600">Previous versions '
            f"({_n_prev})</summary>"
            f'<p class="dim" style="font-size:12px;margin:8px 0 4px 0">'
            f"Captions replaced by a regenerate — kept here so nothing is lost.</p>"
            f"{rows}</details>"
        )
    # Single-prompt flow lands here with ?autographic=1 — render the first
    # card's graphic on load (with the attached photo as background if one
    # was passed) so "describe it → get a graphic" needs no extra click.
    auto_js = ""
    if request.args.get("autographic") and _pack_cards:
        _g0 = f"{_graphic_api_base}/0/create-graphic"
        _photo = (request.args.get("photo") or "").strip()
        # Escape < in every value embedded in the inline <script>: an
        # attacker-supplied ?photo=</script>... would otherwise break out of
        # the tag (json.dumps does not neutralise </script>, and the CSP
        # allows 'unsafe-inline', so the injected script would execute). The
        # JS engine decodes < back to '<' inside the string literal, so
        # behaviour is unchanged.
        _lt = "\\u003c"
        _arg_card = json.dumps(f"{pack_id}-0").replace("<", _lt)
        _arg_g0 = json.dumps(_g0).replace("<", _lt)
        _arg_photo = json.dumps(_photo).replace("<", _lt)
        auto_js = (
            "<script>document.addEventListener('DOMContentLoaded',function(){"
            "if(window.mhAutoGraphic){window.mhAutoGraphic("
            f"{_arg_card},{_arg_g0},"
            f"{_arg_photo},'feed_portrait');}}}});</script>"
        )
    body = (
        header
        + attached_html
        + cards_html
        + history_html
        + W._VISUAL_PANEL_JS
        + W._DRAFT_REGEN_JS
        + auto_js
    )
    return W._layout(rec.get("title") or "Draft", body, active="create")


def stub_pack_export(pack_id):
    from mediahub.club_platform.stub_pack_store import load_pack, export_pack_text

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        rec = None
    if not rec:
        return ("Pack not found", 404)
    text = export_pack_text(rec)
    return Response(
        text,
        mimetype="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{W._safe_disposition_token(pack_id)}.txt"',
        },
    )


def stub_pack_delete(pack_id):
    # CRITICAL destructive primitive — see /privacy/run/<id>/delete.
    # Resolve the pack first, gate on ownership, then delegate. A
    # foreign session sees the same redirect either way.
    from mediahub.club_platform.stub_pack_store import (
        load_pack,
        delete_pack,
    )

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return redirect(url_for("stub_packs_list"))
    delete_pack(pack_id)
    return redirect(url_for("stub_packs_list"))


def api_stub_pack_card_status(pack_id, card_idx):
    """Approve/reject a single card inside a saved stub pack.

    Powers the inline status pill on Free Text / Event Preview / Sponsor
    Post / Session Update card lists. The pill cycles
    queue → approved → rejected and persists the state in the pack JSON
    so reviewers can come back to it across sessions.
    """
    from mediahub.club_platform.stub_pack_store import (
        load_pack,
        update_card_status,
    )

    # Tenant-isolation guard: only the owning org may mutate card
    # status. Probe the pack first; if it's foreign, return the same
    # generic 400 as a malformed status string so existence isn't
    # confirmable from the response shape.
    existing = load_pack(pack_id)
    if not W._can_access_pack(existing, W._active_profile_id()):
        return jsonify({"ok": False, "error": "invalid_request"}), 400
    # Read the status from a JSON body (the pill posts application/json so
    # the write stays inside the CSRF layer's same-origin JSON exemption);
    # fall back to a form field for any legacy caller.
    _body = request.get_json(silent=True) if request.is_json else None
    status = (
        (_body or {}).get("status") if isinstance(_body, dict) else request.form.get("status")
    ) or ""
    # A JSON body can carry any type ({"status": 123}); a non-string must fall
    # through to the invalid_request 400 below, not AttributeError on .strip().
    if not isinstance(status, str):
        status = ""
    status = status.strip().lower()
    rec = update_card_status(pack_id, card_idx, status)
    if not rec:
        return jsonify({"ok": False, "error": "invalid_request"}), 400
    cards = rec.get("cards") or []
    card = cards[card_idx] if 0 <= card_idx < len(cards) else {}
    return jsonify(
        {
            "ok": True,
            "pack_id": pack_id,
            "card_idx": card_idx,
            "status": card.get("status", status),
        }
    )


def api_stub_pack_caption_save(pack_id, card_idx):
    """Persist a hand-edited caption on one saved-draft card (H-9).

    Plain persistence, no AI: the draft pages reveal a per-card textarea
    and save through the same pack-store mechanism the spotlight tone
    rewrite uses (``update_pack``), so every stub pack type — quick
    free-text included — can edit its captions in place. Tenant-gated
    like the sibling caption endpoints: a foreign org's probe 404s
    indistinguishably from a genuine miss.
    """
    from mediahub.club_platform.stub_pack_store import load_pack, update_pack

    rec = load_pack(pack_id)
    if not rec or not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    cards = rec.get("cards") or []
    if not (0 <= card_idx < len(cards)) or not isinstance(cards[card_idx], dict):
        return jsonify({"error": "card_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    caption = str(payload.get("caption") or "").strip()[:4000]
    if not caption:
        return jsonify({"error": "empty_caption", "message": "Type a caption before saving."}), 400
    new_cards = list(cards)
    new_cards[card_idx] = {**new_cards[card_idx], "caption": caption}
    update_pack(pack_id, cards=new_cards)
    return jsonify({"ok": True, "caption": caption})


def api_stub_pack_create_graphic(pack_id, card_idx):
    """Render a branded text-led graphic for one caption-only stub card.

    Powers the "Create graphic" button on the Free Text / Event Preview /
    Sponsor Post / Session Update draft pages. These flows carry no swim
    achievement, so we shape the caption into a text-led item
    (``_stub_card_to_graphic_item``) and render it through the same
    graphic_renderer the meet-recap cards use, honouring the active
    organisation's brand kit. PNGs land under a synthetic ``_stub_<pack_id>``
    run dir so the existing /api/visual/<id>/png route serves them as-is.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req
    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    # Tenant isolation: only the owning org may render its drafts. Same
    # generic 404 as a real miss so existence isn't confirmable.
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    cards = (rec or {}).get("cards") or []
    if not (0 <= card_idx < len(cards)):
        return jsonify({"error": "card_not_found"}), 404
    card = cards[card_idx]
    stub_type = rec.get("stub_type", "other")
    form_data = rec.get("form_data") or {}
    item = W._stub_card_to_graphic_item(stub_type, card, form_data)

    # Brand kit: the active organisation's palette + logo so the graphic is
    # on-brand. Falls back to a neutral run-scoped kit when no org is
    # pinned (pre-onboarding sandbox / tests).
    run_id = f"_stub_{pack_id}"
    prof = W._active_profile()
    try:
        brand_kit = prof.get_brand_kit() if prof is not None else W._v8_brand_kit_for(run_id)
    except Exception:
        brand_kit = W._v8_brand_kit_for(run_id)
    profile_id = rec.get("profile_id") or run_id

    # Format + photo choice from JSON body / query string. A chosen photo
    # fills the caption graphic's background (the layout stays text-led —
    # the photo sits behind the headline + bullets under a legibility scrim).
    req_fmt = None
    chosen_asset_id = None
    force_no_photo = False
    try:
        if _req.is_json and _req.json:
            req_fmt = _req.json.get("format")
            chosen_asset_id = (_req.json.get("asset_id") or "").strip() or None
            # JSON flag truthiness — bool() of a JSON value is the intended
            # presence test, not a numeric cast. (pre-existing web.py body
            # exposed to semgrep by the #15 carve; behaviour unchanged.)
            # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
            force_no_photo = bool(_req.json.get("no_photo"))
    except Exception:
        pass
    if not req_fmt:
        req_fmt = _req.args.get("format")
    if chosen_asset_id is None:
        chosen_asset_id = (_req.args.get("asset_id") or "").strip() or None
    if not force_no_photo:
        force_no_photo = (_req.args.get("no_photo") or "").lower() in ("1", "true", "yes")
    if force_no_photo:
        chosen_asset_id = None
    formats_kw = [req_fmt] if req_fmt else None

    # The org's library photos, surfaced as a per-graphic picker. A chosen
    # one becomes this caption graphic's background.
    media_assets = []
    try:
        store = W._v8_get_media_store()
        _pid_for_photos = W._active_profile_id() or rec.get("profile_id")
        if _pid_for_photos:
            from mediahub.media_library.photo_edit import asset_dicts_for_render

            assets = store.list(profile_id=_pid_for_photos)
            media_assets = asset_dicts_for_render(assets, store)
    except Exception:
        media_assets = []
    _photo_types = {"athlete_action", "athlete_headshot", "team_photo", "venue_photo", "other"}
    available_photos = []
    for _ad in media_assets:
        _d = _ad if isinstance(_ad, dict) else {}
        if _d.get("id") and _d.get("type") in _photo_types:
            _names = _d.get("linked_athlete_names") or []
            _label = (_names[0] if _names else "") or str(_d.get("type") or "").replace("_", " ")
            available_photos.append(
                {
                    "id": _d["id"],
                    "url": url_for("api_media_library_file", asset_id=_d["id"]),
                    "label": _label,
                }
            )

    # The v2 design-spec director chooses the treatment when a provider is
    # configured; the deterministic archetype rotation is the no-provider
    # floor. The explicit text-led profile pins the v1 path (kill switch /
    # no archetypes) to a safe no-photo treatment with the identity
    # palette role, so white headline text never disappears. A chosen
    # photo rides as the background either way.
    from mediahub.creative_brief.generator import VariationProfile

    variation_profile = VariationProfile(
        layout_family="text_led_recap",
        photo_treatment="no-photo",
        background_style="clean",
        accent_style="minimal",
        composition="center",
    )

    try:
        from mediahub.content_pack_visual.integration import create_visual_for_item

        res = create_visual_for_item(
            item,
            brand_kit,
            profile_id=profile_id,
            run_id=run_id,
            media_assets=media_assets,
            formats=formats_kw,
            variation_profile=variation_profile,
            use_ai_director=True,
            allowed_families=["text_led_recap"],
            forced_bg_asset_id=chosen_asset_id,
        )
    except Exception as e:
        return jsonify(
            {
                "error": "render_failed",
                "user_message": W._friendly_failure_message(
                    e, kind="render", context="draft graphic"
                ),
            }
        ), 500
    return jsonify(
        {
            "ok": True,
            "available_photos": available_photos,
            "chosen_asset_id": chosen_asset_id,
            "no_photo": force_no_photo,
            **res,
        }
    )


def api_stub_pack_caption(pack_id, card_idx):
    """Live composite caption for the Content builder's spotlight mode.

    Recomposes the SAME approved moments in the requested tone and returns
    JSON ``{caption, tone, live, generated_at}`` — the shape the toolbar's
    tone tabs / Regenerate button consume — then persists it onto the pack
    so Copy / Export stay in sync. Spotlight packs only.
    """
    from datetime import datetime, timezone as _tz

    from mediahub.club_platform.stub_pack_store import load_pack, update_pack

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    fd = (rec or {}).get("form_data") or {}
    if fd.get("source") != "athlete_spotlight":
        return jsonify({"error": "unsupported_type"}), 400
    cards = (rec or {}).get("cards") or []
    if not (0 <= card_idx < len(cards)):
        return jsonify({"error": "card_not_found"}), 404

    # Toolbar tone keys → the spotlight compose vocabulary (ai / brand voice
    # = ""). Anything unknown falls back to brand voice.
    _tone_in = (request.args.get("tone") or "ai").strip()
    tone = {"ai": "", "warm-club": "warm-club", "hype": "hype", "data-led": "data-led"}.get(
        _tone_in, ""
    )
    now_iso = datetime.now(_tz.utc).isoformat()

    from mediahub.media_ai.llm import is_available as _llm_available

    if not _llm_available():
        return jsonify(
            {
                "caption": "",
                "tone": _tone_in,
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": (
                    "AI captions are unavailable on this deployment. "
                    "Contact your administrator to enable them."
                ),
            }
        ), 200

    run_id = str(fd.get("run_id") or "")
    swimmer_key = str(fd.get("swimmer_key") or "")
    result, err = W._compose_spotlight_caption(run_id, swimmer_key, tone=tone)
    if err is not None or not result:
        _err_status = err[1] if (isinstance(err, tuple) and len(err) == 2) else None
        if _err_status == 400:
            # _compose_spotlight_caption returns a 400 only for the
            # "no achievements approved yet" case — the reviewer un-approved
            # every moment after building the draft. Name the real cause
            # instead of the generic AI-transient message.
            return jsonify(
                {
                    "caption": "",
                    "tone": _tone_in,
                    "live": True,
                    "generated_at": now_iso,
                    "error": "no_approved",
                    "message": (
                        "No moments are approved for this spotlight. Approve at "
                        "least one on the spotlight page, then regenerate."
                    ),
                }
            ), 200
        # _compose_spotlight_caption returns a rendered HTML error page on
        # provider failure; a fetch caller wants JSON, so translate it.
        return jsonify(
            {
                "caption": "",
                "tone": _tone_in,
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": (
                    "The AI couldn't finish the caption — wait a few seconds and try again."
                ),
            }
        ), 200
    caption = str(result.get("caption") or "").strip()
    new_cards = list(cards)
    new_cards[card_idx] = {**new_cards[card_idx], "caption": caption}
    try:
        update_pack(pack_id, cards=new_cards, form_data_updates={"tone": tone})
    except Exception:
        pass
    return jsonify({"caption": caption, "tone": _tone_in, "live": True, "generated_at": now_iso})


def api_stub_pack_caption_assist(pack_id, card_idx):
    """Inline assist for the composite caption (shorter / punchier / add the
    time / tidy / custom …). Mirrors ``api_caption_assist`` but grounds the
    revision in the spotlight's stored facts (swimmer, meet, the parsed
    result lines) rather than a single swim_id."""
    from datetime import datetime, timezone as _tz

    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    fd = (rec or {}).get("form_data") or {}
    if fd.get("source") != "athlete_spotlight":
        return jsonify({"error": "unsupported_type"}), 400

    payload = request.get_json(silent=True) or {}
    # Server-side length caps: the 140-char maxlength is client-only, so an
    # oversized body would otherwise be embedded verbatim in the provider
    # prompt (token cost, provider 400s). Real captions are ~280 chars.
    current_caption = (payload.get("current_caption") or "").strip()[:4000]
    transform = (payload.get("transform") or "").strip()
    custom = (payload.get("custom") or "").strip()[:500]
    tone = (payload.get("tone") or "warm-club").strip()
    if tone not in ("ai", "warm-club", "hype", "data-led"):
        tone = "warm-club"
    if not current_caption:
        return jsonify(
            {"error": "empty_caption", "message": "Generate a caption first, then assist it."}
        ), 400

    from mediahub.web.caption_assist import assist_caption, resolve_instruction

    if not resolve_instruction(transform, custom):
        return jsonify(
            {"error": "invalid_transform", "message": "Pick a change or type an instruction."}
        ), 400

    swimmer = str(fd.get("swimmer_name") or "")
    meet = str(fd.get("meet_name") or "")
    results_lines = str(fd.get("results_lines") or "")
    # A composite spans several events, so leave event/time blank and hand
    # the joined result lines as the headline context for `add_time`.
    ach_dict = {
        "swimmer_name": swimmer,
        "event": "",
        "time": "",
        "pb": False,
        "club": "",
        "meet": meet,
        "place": "",
        "type": "athlete_spotlight",
        "headline": results_lines.replace("\n", "; "),
    }
    club_brand = {"club_name": "", "meet_name": meet}
    club_profile_obj = None
    voice_profile = None
    try:
        prof = W._active_profile()
        if prof is not None:
            club_profile_obj = prof
            club_brand["club_name"] = getattr(prof, "display_name", "") or ""
            if getattr(prof, "voice_profile", None):
                voice_profile = prof.voice_profile
    except Exception:
        club_profile_obj = None

    now_iso = datetime.now(_tz.utc).isoformat()
    from mediahub.media_ai.llm import is_available as _llm_available
    from mediahub.web.ai_caption import ClaudeUnavailableError as _ClaudeUE

    if not _llm_available():
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": "AI captions are unavailable on this deployment.",
            }
        ), 200
    try:
        revised = assist_caption(
            ach_dict,
            current_caption,
            transform,
            custom=custom,
            club_brand=club_brand,
            club_profile=club_profile_obj,
            tone=tone,
            voice_profile=voice_profile,
        )
    except _ClaudeUE:
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": "AI captions are unavailable on this deployment.",
            }
        ), 200
    except Exception:
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": "The AI is briefly busy — wait a few seconds and try again.",
            }
        ), 200
    revised = (revised or "").strip()
    if not revised:
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": "The AI returned nothing — try again.",
            }
        ), 200
    return jsonify(
        {
            "caption": revised,
            "original": current_caption,
            "tone": tone,
            "transform": transform or "custom",
            "live": True,
            "generated_at": now_iso,
        }
    )


def api_stub_pack_reel_job(pack_id, card_idx):
    """Kick off a background composite reel from the spotlight's approved
    moments; returns ``{job_id, poll_url}``. Mirrors ``api_run_reel_job``
    and reuses ``api_reel_job_status`` for polling + ``-file`` for serving.
    """
    from mediahub.club_platform.stub_pack_store import load_pack

    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    inputs, err = W._assemble_spotlight_reel_inputs(pack_id, rec)
    if err is not None:
        return err

    file_url = url_for(
        "api_stub_pack_reel_file",
        pack_id=pack_id,
        card_idx=card_idx,
        n=inputs["n"],
        format=inputs["format"],
    )
    run_id = inputs["run_id"]
    job_id = uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "reel",
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
            with W._render_slot("reel", f"_stub_{pack_id}", timeout=W._RENDER_TRY_TIMEOUT):
                mp4 = _motion.render_meet_reel(
                    inputs["cards"],
                    inputs["brand_kit"],
                    inputs["out_path"],
                    meet_name=inputs["meet_name"],
                    briefs=inputs["briefs"],
                    format_name=inputs["format"],
                    rhythm=inputs["rhythm"],
                    sponsor=inputs.get("sponsor", ""),
                )
            if not Path(mp4).exists():
                raise RuntimeError("mp4 missing after render")
            job["status"] = "done"
            job["video_url"] = file_url
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_render_complete(
                    job.get("owner_pid") or "", run_id=run_id, label="spotlight reel"
                )
            except Exception:
                pass
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except Exception as e:
            _payload = W._motion_error_payload(e)
            job["status"] = "error"
            job["error"] = str(_payload.get("detail") or e)
            job["user_message"] = str(_payload.get("user_message") or "")
        W._variant_job_save(job)

    threading.Thread(target=_worker, name=f"spreel-{job_id[:8]}", daemon=True).start()
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


def api_stub_pack_reel_file(pack_id, card_idx):
    """Serve an already-rendered composite reel MP4 — never renders."""
    from flask import send_file

    from mediahub.visual import motion as _motion
    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    fd = (rec or {}).get("form_data") or {}
    if fd.get("source") != "athlete_spotlight":
        return jsonify({"error": "unsupported_type"}), 400
    run_id = str(fd.get("run_id") or "")
    swimmer_key = str(fd.get("swimmer_key") or "")
    if not run_id or not swimmer_key:
        return jsonify({"error": "spotlight_context_missing"}), 400
    try:
        n = int(request.args.get("n", "3"))
    except (TypeError, ValueError):
        n = 3
    n = max(1, min(5, n))
    fmt = (request.args.get("format") or _motion.DEFAULT_MOTION_FORMAT).strip().lower()
    if fmt not in _motion.MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    slug = re.sub(r"[^a-z0-9]+", "-", swimmer_key.lower()).strip("-") or "spotlight"
    name = f"spotlight_{slug}_{n}.mp4" if fmt == "story" else f"spotlight_{slug}_{n}_{fmt}.mp4"
    path = W.RUNS_DIR / run_id / "motion" / name
    if not path.exists():
        return jsonify({"error": "reel_not_rendered"}), 404
    return send_file(
        str(path),
        mimetype="video/mp4",
        as_attachment=False,
        download_name=f"spotlight_reel_{slug}.mp4",
    )


def api_stub_pack_reformat(pack_id, card_idx):
    """Re-target the composite graphic to another format/size — the
    meet-recap Reformat, scoped to the spotlight composite's stored design.
    Mirrors ``api_card_reformat`` but resolves the brief from the synthetic
    ``_stub_<pack_id>`` run and authorises via the pack."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import send_file

    from mediahub.club_platform.stub_pack_store import load_pack
    from mediahub.club_platform import format_catalog as _fc
    from mediahub.creative_brief.generator import CreativeBrief
    from mediahub.turn_into import blank_brief_for_format, transform_design

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    run_id = f"_stub_{pack_id}"

    fmt_slug = (request.args.get("format") or "").strip()
    w_raw = request.args.get("w")
    h_raw = request.args.get("h")
    spec = None
    try:
        if w_raw and h_raw:
            spec = _fc.custom_format(
                float(w_raw),
                float(h_raw),
                unit=(request.args.get("unit") or "px"),
                slug=(fmt_slug or "custom"),
            )
        elif fmt_slug:
            spec = _fc.format_for(fmt_slug)
    except (ValueError, TypeError) as e:
        return jsonify({"error": "bad_format", "user_message": str(e)}), 400
    if spec is None:
        return jsonify(
            {"error": "unknown_format", "user_message": "Pick a format from the catalogue."}
        ), 400

    prof = W._active_profile()
    try:
        brand_kit = (
            prof.get_brand_kit()
            if prof is not None
            else (W._v8_brand_kit_for(run_id) if W._v8_ok else None)
        )
    except Exception:
        brand_kit = W._v8_brand_kit_for(run_id) if W._v8_ok else None

    use_ai = (request.args.get("ai") or "").lower() in ("1", "true", "yes")
    blank = (request.args.get("blank") or "").lower() in ("1", "true", "yes")
    card_key = f"{pack_id}-{card_idx}"
    if blank:
        new_brief = blank_brief_for_format(
            spec,
            brand_kit,
            content_item_id=card_key,
            profile_id=(rec.get("profile_id") or run_id),
        )
    else:
        bdict = W._latest_brief_in_run(run_id)
        if not bdict:
            return jsonify(
                {
                    "error": "no_design",
                    "user_message": (
                        "Create the graphic first, then reformat it — or start blank."
                    ),
                }
            ), 409
        src = CreativeBrief.from_dict(bdict)
        if src is None:
            return jsonify({"error": "brief_unreadable"}), 500
        try:
            tr = transform_design(
                source_brief=src,
                target_format=spec,
                brand_kit=brand_kit,
                use_ai_director=use_ai,
            )
        except ValueError as e:
            return jsonify({"error": "transform_failed", "user_message": str(e)}), 400
        new_brief = tr.brief

    import hashlib as _hl

    key = _hl.sha256(
        f"{card_key}|{spec.slug}|{spec.width}x{spec.height}|"
        f"{new_brief.layout_template}|{'blank' if blank else 'tx'}".encode("utf-8")
    ).hexdigest()[:20]
    out_dir = W.RUNS_DIR / run_id / "reformat" / key
    cache_png = out_dir / f"{spec.render_name}.png"
    if cache_png.exists() and not use_ai:
        return send_file(str(cache_png), mimetype="image/png")

    logo_path = None
    bk_logo = getattr(brand_kit, "logo_path", None)
    if bk_logo:
        try:
            if Path(bk_logo).exists():
                logo_path = str(bk_logo)
        except Exception:
            logo_path = None
    try:
        from mediahub.graphic_renderer.render import render_brief

        out_dir.mkdir(parents=True, exist_ok=True)
        # The composite is text-led (no athlete cutout), so no hero photo.
        with W._render_slot("graphic", card_key, timeout=W._RENDER_TRY_TIMEOUT):
            res = render_brief(
                new_brief,
                output_dir=out_dir,
                size=spec.size,
                format_name=spec.render_name,
                athlete_path=None,
                logo_path=logo_path,
                brand_kit=brand_kit,
                image_format="png",
            )
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception as e:
        return jsonify(W._reformat_error_payload(e)), 500
    return send_file(str(res.visual.file_path), mimetype="image/png")


def api_stub_pack_assistant(pack_id, card_idx):
    """One copilot turn editing the composite graphic's design in plain
    words (proposes validated edits; never paints pixels, never publishes).
    Mirrors ``api_card_assistant`` for the spotlight composite — the edited
    brief persists so a subsequent Reformat reflects it."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from mediahub.club_platform.stub_pack_store import load_pack
    from mediahub.creative_brief.generator import CreativeBrief

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify(
            {"error": "empty_message", "user_message": "Type what you'd like to change."}
        ), 400
    session_id = (body.get("session_id") or "").strip()
    run_id = f"_stub_{pack_id}"
    fd = (rec or {}).get("form_data") or {}
    profile_id = rec.get("profile_id") or W._active_profile_id() or run_id

    prof = W._active_profile()
    try:
        brand_kit = (
            prof.get_brand_kit()
            if prof is not None
            else (W._v8_brand_kit_for(run_id) if W._v8_ok else None)
        )
    except Exception:
        brand_kit = W._v8_brand_kit_for(run_id) if W._v8_ok else None

    bdict = W._latest_brief_in_run(run_id)
    if not bdict:
        return jsonify(
            {
                "error": "no_design",
                "user_message": ("Create the graphic first, then ask the copilot to refine it."),
            }
        ), 409
    src = CreativeBrief.from_dict(bdict)
    if src is None:
        return jsonify({"error": "brief_unreadable"}), 500

    from mediahub.assistant import copilot as _acop
    from mediahub.assistant import session as _asess

    card_key = f"{pack_id}-{card_idx}"
    facts = {
        "swimmer_name": fd.get("swimmer_name") or "",
        "meet": fd.get("meet_name") or "",
        "moments": str(fd.get("results_lines") or "").replace("\n", "; "),
    }
    sess = _asess.get_or_create(run_id, card_key, session_id, profile_id=profile_id)
    turn = _acop.run_turn(
        session=sess,
        user_message=message,
        brief=src,
        brand_kit=brand_kit,
        facts=facts,
        profile_id=profile_id,
    )
    if turn.changed:
        try:
            from mediahub.content_pack_visual.integration import briefs_dir_for_run

            bdir = briefs_dir_for_run(run_id)
            (bdir / f"{turn.brief.id}.json").write_text(
                json.dumps(turn.brief.to_dict(), indent=2, default=str), encoding="utf-8"
            )
        except Exception:
            pass
    resp = turn.to_dict()
    resp.update(
        {
            "session_id": sess.session_id,
            "brief_id": turn.brief.id,
            "format": (turn.brief.format_priority or ["story"])[0],
            "reformat_url": url_for("api_stub_pack_reformat", pack_id=pack_id, card_idx=card_idx),
        }
    )
    return jsonify(resp)


def api_stub_pack_assistant_suggestions(pack_id, card_idx):
    """Prompt chips for the composite copilot."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from mediahub.club_platform.stub_pack_store import load_pack

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"error": "pack_not_found"}), 404
    profile_id = rec.get("profile_id") or W._active_profile_id() or f"_stub_{pack_id}"
    from mediahub.assistant.copilot import suggested_prompts

    return jsonify({"suggestions": suggested_prompts(profile_id, "")})


def api_stub_pack_regenerate(pack_id):
    """Regenerate a saved draft's cards through the content engine.

    The pack's current cards (plus any archived history) are fed back to
    the engine as the avoid-set, so the AI Director plans fresh angles and
    the writer produces genuinely different captions every click. The new
    cards replace the pack's cards; prior cards roll into ``card_history``.
    """
    from mediahub.club_platform.stub_pack_store import load_pack, replace_cards
    from mediahub.club_platform import stubs as _stubs_mod
    from mediahub.content_engine import generate_content
    from mediahub.ai_core import ProviderNotConfigured, ProviderError

    rec = load_pack(pack_id)
    if not W._can_access_pack(rec, W._active_profile_id()):
        return jsonify({"ok": False, "error": "pack_not_found"}), 404
    stub_type = rec.get("stub_type", "")
    stub = _stubs_mod.stub_for_type(stub_type)
    if stub is None:
        return jsonify({"ok": False, "error": "unsupported_type"}), 400
    form_data = rec.get("form_data") or {}
    brief = stub.generate_brief(form_data)
    requirements = _stubs_mod.requirements_for(stub_type)
    prior = rec.get("cards") or []
    recent = list(rec.get("card_history") or []) + list(prior)
    n_cards = max(1, min(len(prior) or 3, 6))
    try:
        res = generate_content(
            content_type=stub_type,
            brief=brief,
            requirements=requirements,
            recent_cards=recent,
            n_cards=n_cards,
        )
    except ProviderNotConfigured as e:
        return jsonify({"ok": False, "error": "no_provider", "message": str(e)}), 503
    except ProviderError as e:
        return jsonify({"ok": False, "error": "provider_error", "message": str(e)}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"generate_failed: {e}"}), 500
    new_cards = res.get("cards") or []
    if not new_cards:
        return jsonify({"ok": False, "error": "empty"}), 502
    replace_cards(pack_id, new_cards)
    # The draft view is a GET page that re-renders from the saved pack, so
    # the client just reloads to show the fresh set.
    return jsonify(
        {
            "ok": True,
            "n_cards": len(new_cards),
            "redirect": url_for("stub_pack_view", pack_id=pack_id),
        }
    )


def sponsors_page():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    from mediahub.club_platform.sponsors import active_sponsors, registry_for

    registry = registry_for(prof)
    active_ids = {s["sponsor_id"] for s in active_sponsors(prof)}

    rows = ""
    for s in registry:
        window = ""
        if s["active_from"] or s["active_until"]:
            window = f"{_h(s['active_from'] or '…')} &rarr; {_h(s['active_until'] or '…')}"
        else:
            window = "Always"
        state = (
            '<span style="color:var(--good)">active</span>'
            if s["sponsor_id"] in active_ids
            else '<span class="dim">inactive</span>'
        )
        rows += (
            "<tr>"
            f'<td data-label="Sponsor"><b>{_h(s["name"])}</b></td>'
            f'<td data-label="Tier">{_h(s["tier"])}</td>'
            f'<td data-label="Window">{window}</td>'
            f'<td data-label="State">{state}</td>'
            f'<td><form method="post" action="{url_for("sponsors_delete")}" style="margin:0" '
            "onsubmit=\"return confirm('Remove this sponsor? Their logo and details are "
            "permanently deleted.')\">"
            f'<input type="hidden" name="sponsor_id" value="{_h(s["sponsor_id"])}">'
            '<button type="submit" class="btn secondary" style="font-size:12px;padding:4px 10px">Remove</button>'
            "</form></td></tr>"
        )
    if not rows:
        # D-34: a designed empty state (art + headline + guidance), not a
        # bare grey table line, on the first-run moment.
        rows = (
            '<tr><td colspan="5" style="padding:0">'
            + W._empty_state(
                art="inbox",
                headline="No sponsors yet",
                sub="Add your first sponsor below &mdash; its slot then rotates across your "
                "cards automatically.",
            )
            + "</td></tr>"
        )

    tier_opts = "".join(
        f'<option value="{t}">{t.title()}</option>'
        for t in ("headline", "gold", "silver", "bronze", "partner")
    )
    # Logo picker: any media-library asset can be the sponsor's logo.
    logo_opts = '<option value="">No logo (name only)</option>'
    try:
        if W._v8_ok:
            _mstore = W._v8_get_media_store()
            for _a in _mstore.list(profile_id=prof.profile_id):
                _ad = _a.to_dict() if hasattr(_a, "to_dict") else (_a or {})
                if _ad.get("id"):
                    _lbl = _ad.get("original_filename") or _ad.get("type") or _ad["id"]
                    logo_opts += f'<option value="{_h(_ad["id"])}">{_h(str(_lbl)[:60])}</option>'
    except Exception:
        pass
    month_now = time.strftime("%Y-%m", time.gmtime())
    body = f"""
<h1 style="margin-bottom:4px">Sponsors</h1>
<p class="dim" style="margin-bottom:20px;max-width:640px">Each active sponsor's slot rotates
across your generated cards deterministically &mdash; the same card always carries the same
sponsor, on stills and motion alike. The monthly exposure report shows each sponsor exactly
where they appeared, ready to forward.</p>

<div class="card" style="margin-bottom:20px">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Sponsor registry</h3>
  <table class="mh-table-stack" style="width:100%;border-collapse:collapse;font-size:14px">
    <thead><tr style="text-align:left;color:var(--ink-dim);font-size:12px;text-transform:uppercase">
      <th style="padding:6px 8px">Sponsor</th><th>Tier</th><th>Active window</th><th>State</th><th></th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
  <div class="card">
    <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Add a sponsor</h3>
    <form method="post" action="{url_for("sponsors_add")}" style="display:flex;flex-direction:column;gap:10px">
      <label style="font-size:13px">Name<br>
        <input name="name" required maxlength="120" style="width:100%"></label>
      <label style="font-size:13px">Tier<br>
        <select name="tier" style="width:100%">{tier_opts}</select></label>
      <div style="display:flex;gap:10px">
        <label style="font-size:13px;flex:1">Active from<br>
          <input name="active_from" type="date" style="width:100%"></label>
        <label style="font-size:13px;flex:1">Active until<br>
          <input name="active_until" type="date" style="width:100%"></label>
      </div>
      <label style="font-size:13px">Logo (from your media library)<br>
        <select name="logo_asset_id" style="width:100%">{logo_opts}</select></label>
      <label style="font-size:13px">Website (optional)<br>
        <input name="website" maxlength="300" style="width:100%" placeholder="https://"></label>
      <button type="submit" class="btn" style="align-self:flex-start">Add sponsor</button>
    </form>
  </div>
  <div class="card">
    <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Exposure report</h3>
    <p class="dim" style="font-size:13px">Per-sponsor counts of cards carrying their slot,
    how many were approved and posted, and the runs they came from.</p>
    <form method="get" action="{url_for("sponsors_report")}" style="display:flex;gap:10px;align-items:flex-end">
      <label style="font-size:13px">Month<br>
        <input name="month" type="month" value="{month_now}" style="width:100%"></label>
      <button type="submit" class="btn">View report</button>
    </form>
  </div>
</div>
"""
    return W._layout("Sponsors", body, active="home")


def sponsors_add():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    from mediahub.club_platform.sponsors import normalise_sponsor

    entry = normalise_sponsor(
        {
            "name": request.form.get("name", ""),
            "tier": request.form.get("tier", ""),
            "active_from": request.form.get("active_from", ""),
            "active_until": request.form.get("active_until", ""),
            "website": request.form.get("website", ""),
            "logo_asset_id": request.form.get("logo_asset_id", ""),
        }
    )
    if entry is not None:
        registry = [s for s in (prof.sponsors or [])]
        # Replace an entry with the same id (same name) instead of duplicating.
        _had_existing = any(
            isinstance(s, dict) and s.get("sponsor_id") == entry["sponsor_id"] for s in registry
        )
        registry = [
            s
            for s in registry
            if not (isinstance(s, dict) and s.get("sponsor_id") == entry["sponsor_id"])
        ]
        registry.append(entry)
        prof.sponsors = registry
        W.save_profile(prof)
        # E-14: the replace semantics stay, but the user is told — a
        # same-named add used to overwrite the existing entry silently.
        if _had_existing:
            W._flash_toast(
                f"Updated existing sponsor {entry['name']} — "
                "its previous details were replaced.",
                "info",
            )
    return redirect(url_for("sponsors_page"))


def sponsors_delete():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    sid = (request.form.get("sponsor_id") or "").strip()
    if sid:
        prof.sponsors = [
            s
            for s in (prof.sponsors or [])
            if not (isinstance(s, dict) and s.get("sponsor_id") == sid)
        ]
        W.save_profile(prof)
    return redirect(url_for("sponsors_page"))


def sponsors_report():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    from mediahub.club_platform.sponsors import exposure_report

    month = (request.args.get("month") or "").strip()[:7]
    if not re.match(r"^\d{4}-\d{2}$", month):
        month = time.strftime("%Y-%m", time.gmtime())
    report = exposure_report(prof.profile_id, month)

    sections = ""
    for s in report["sponsors"]:
        runs_list = ", ".join(_h(r) for r in s["runs"]) or "&mdash;"
        sections += f"""
<div class="card" style="margin-bottom:16px">
  <h3 style="margin-top:0">{_h(s["sponsor_name"])}</h3>
  <div style="display:flex;gap:28px;flex-wrap:wrap;font-size:14px">
    <div><div style="font-size:26px;font-weight:800">{s["cards"]}</div><div class="dim">cards carried the slot</div></div>
    <div><div style="font-size:26px;font-weight:800">{s["approved"]}</div><div class="dim">approved</div></div>
    <div><div style="font-size:26px;font-weight:800">{s["posted"]}</div><div class="dim">posted</div></div>
  </div>
  <p class="dim" style="font-size:12px;margin-bottom:0">Runs: {runs_list}</p>
</div>"""
    if not sections:
        sections = (
            '<div class="card empty"><p>No sponsor exposure recorded for this month. '
            "Exposure is counted when a card carrying a sponsor slot is generated.</p></div>"
        )

    body = f"""
<p class="dim"><a href="{url_for("sponsors_page")}">&larr; Back to sponsors</a></p>
<h1 style="margin-bottom:4px">Sponsor exposure &mdash; {_h(month)}</h1>
<p class="dim" style="margin-bottom:20px">{_h(prof.display_name)} &middot; generated by MediaHub.
Counts come from the exposure ledger (which cards carried which sponsor's slot), the approval
workflow, and the publish log &mdash; deterministic and auditable.</p>
{sections}
"""
    resp = make_response(W._layout(f"Sponsor exposure — {month}", body, active="home"))
    if (request.args.get("download") or "").lower() in ("1", "true", "yes"):
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="sponsor-exposure-{prof.profile_id}-{month}.html"'
        )
    return resp


def api_collections():
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "no_org"}), 403
    from mediahub.collab import collections as _col

    if request.method == "GET":
        return jsonify({"ok": True, "collections": _col.list_collections(pid)})
    if not W._perms.can_edit(W._active_role(pid)):
        return jsonify({"error": "forbidden", "reason": "Your role can't edit collections."}), 403
    payload = request.get_json(silent=True) or {}
    try:
        col = _col.create_collection(pid, payload.get("name", ""))
    except _col.CollectionError as e:
        return jsonify({"error": "bad_request", "detail": str(e)}), 400
    return jsonify({"ok": True, "collection": col}), 201


def api_collection_detail(collection_id: str):
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"error": "no_org"}), 403
    from mediahub.collab import collections as _col

    if request.method == "GET":
        items = _col.list_items(pid, collection_id)
        if items is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify({"ok": True, "items": items})

    if not W._perms.can_edit(W._active_role(pid)):
        return jsonify({"error": "forbidden", "reason": "Your role can't edit collections."}), 403
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip().lower()
    try:
        if action == "rename":
            ok = _col.rename_collection(pid, collection_id, payload.get("name", ""))
        elif action == "delete":
            ok = _col.delete_collection(pid, collection_id)
        elif action == "add_item":
            ok = _col.add_item(
                pid, collection_id, payload.get("item_type", ""), payload.get("item_id", "")
            )
        elif action == "remove_item":
            ok = _col.remove_item(
                pid, collection_id, payload.get("item_type", ""), payload.get("item_id", "")
            )
        else:
            return jsonify({"error": "unknown_action"}), 400
    except _col.CollectionError as e:
        return jsonify({"error": "bad_request", "detail": str(e)}), 400
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True})


def collections_page():
    """Manage org collections (folders over runs & packs)."""
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.collab import collections as _col

    cols = _col.list_collections(pid)
    can_edit = W._perms.can_edit(W._active_role(pid))
    rows = ""
    for c in cols:
        # C-9 — the name links into the collection so it's no longer a
        # look-don't-touch row; the detail page lists contents and fills it.
        _detail = url_for("collection_detail_page", collection_id=c["id"])
        rows += (
            '<div class="card" style="padding:12px 16px;margin-bottom:10px;display:flex;'
            'justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">'
            f'<div><a href="{_detail}" style="text-decoration:none"><strong>{_h(c["name"])}</strong></a>'
            f'<span style="color:var(--ink-muted);font-size:12px;margin-left:8px">'
            f"{c['count']} item{'s' if c['count'] != 1 else ''}</span></div>"
            '<div style="display:flex;gap:8px">'
            f'<a class="btn secondary" style="font-size:12px;padding:4px 10px" href="{_detail}">Open</a>'
            + (
                f'<button class="btn secondary" style="font-size:12px;padding:4px 10px" '
                f"onclick=\"mhDeleteCollection('{c['id']}')\">Delete</button>"
                if can_edit
                else ""
            )
            + "</div></div>"
        )
    # D-34: a designed empty state instead of a bare grey line.
    rows = rows or W._empty_state(
        art="inbox",
        headline="No collections yet",
        sub="Group related meets and packs &mdash; a season, a championship, a sponsor "
        "campaign &mdash; into one place.",
    )
    create_html = ""
    if can_edit:
        create_html = (
            '<div class="card" style="padding:14px 16px;margin-bottom:16px">'
            '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
            '<input id="mh-col-name" type="text" placeholder="New collection name" '
            'style="flex:1;min-width:200px;padding:8px 10px;border:1px solid var(--border);'
            'border-radius:6px;background:rgba(255,255,255,0.04);color:inherit"/>'
            '<button class="btn" onclick="mhCreateCollection()">Create</button></div></div>'
        )
    body = (
        "<h1>Collections</h1>"
        '<p class="lede" style="margin-bottom:var(--sp-6)">Group your meets and packs '
        "into folders — a season, a championship, a sponsor campaign.</p>"
        + create_html
        + f'<div id="mh-col-list">{rows}</div>'
        + "<script>\n"
        "function mhCreateCollection(){var n=document.getElementById('mh-col-name');"
        "if(!n||!n.value.trim())return;"
        "fetch('" + url_for("api_collections") + "',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n.value.trim()})})"
        ".then(function(r){return r.json();}).then(function(j){if(j.ok)location.reload();"
        "else if(window.MH&&MH.toast)MH.toast(j.reason||j.detail||'Could not create','error',3000);})"
        ".catch(function(){if(window.MH&&MH.toast)"
        "MH.toast('Network error — the collection was not created.','error',3000);});}\n"
        "function mhDeleteCollection(id){"
        "var go=function(){fetch('"
        + url_for("api_collections")
        + "/'+encodeURIComponent(id),{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete'})})"
        ".then(function(r){return r.json();}).then(function(j){if(j.ok)location.reload();"
        "else if(window.MH&&MH.toast)MH.toast(j.reason||j.detail||'Could not delete','error',3000);})"
        ".catch(function(){if(window.MH&&MH.toast)"
        "MH.toast('Network error — the collection was not deleted.','error',3000);});};"
        "if(window.MH&&MH.confirm){MH.confirm({title:'Delete this collection?',"
        "body:'The folder is removed. The meets and packs inside it are kept.',"
        "confirmText:'Delete',onConfirm:go});}"
        "else if(confirm('Delete this collection? The meets themselves are kept.')){go();}}\n"
        "</script>"
    )
    return W._layout("Collections", body, active="settings")


def collection_detail_page(collection_id: str):
    """C-9 — a collection's contents, with a picker to actually fill it.

    Previously collections could be created but never filled (no
    'add to collection' action anywhere), so every one stayed at 0 items.
    This lists the collection's meets (resolved to names, linking into
    review) and offers a meet picker to add/remove — the fillable path the
    feature was missing."""
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    from mediahub.collab import collections as _col

    items = _col.list_items(pid, collection_id)
    if items is None:  # not this org's collection (or gone)
        return W._recovery_page(
            "Collection not found",
            "It may have been deleted, or it belongs to another organisation.",
            primary_cta=("All collections", url_for("collections_page")),
        )
    name = next(
        (c["name"] for c in _col.list_collections(pid) if c["id"] == collection_id),
        "Collection",
    )
    can_edit = W._perms.can_edit(W._active_role(pid))
    # Resolve run items to a meet name + review link via the org-scoped runs
    # table (WHERE profile_id = pid is the tenant boundary, so a run id from
    # another org — or a deleted run — resolves to nothing and shows as its
    # raw id, still removable, never linked/leaked).
    run_names: dict = {}
    run_ids = [it["item_id"] for it in items if it["item_type"] == "run"]
    if run_ids:
        try:
            conn = W._db()
            qmarks = ",".join("?" for _ in run_ids)
            for r in conn.execute(
                f"SELECT id, meet_name FROM runs WHERE profile_id = ? AND id IN ({qmarks})",
                (pid, *run_ids),
            ).fetchall():
                run_names[r["id"]] = r["meet_name"] or r["id"]
            conn.close()
        except Exception:
            run_names = {}
    rows = ""
    for it in items:
        iid = it["item_id"]
        label, link = iid, None
        if it["item_type"] == "run" and iid in run_names:
            label = run_names[iid]
            link = url_for("review", run_id=iid)
        label_html = f'<a href="{link}">{_h(label)}</a>' if link else f"<span>{_h(label)}</span>"
        remove_btn = (
            f'<button class="btn secondary" style="font-size:12px;padding:4px 10px" '
            f"onclick=\"mhColRemove('{_h(it['item_type'])}','{_h(iid)}')\">Remove</button>"
            if can_edit
            else ""
        )
        rows += (
            '<div class="card" style="padding:10px 14px;margin-bottom:8px;display:flex;'
            'justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">'
            f'<div><span class="tag" style="font-size:10px;margin-right:8px">'
            f"{_h(it['item_type'])}</span>{label_html}</div>{remove_btn}</div>"
        )
    rows = rows or (
        '<p class="dim" style="margin:var(--sp-4) 0">Nothing in this collection yet — '
        "add a meet below.</p>"
    )
    # Meet picker: this org's processed meets, minus ones already in.
    present = {it["item_id"] for it in items if it["item_type"] == "run"}
    picker = ""
    if can_edit:
        opts = ""
        try:
            conn = W._db()
            runs = conn.execute(
                "SELECT id, meet_name FROM runs WHERE profile_id = ? AND status = 'done' "
                "ORDER BY created_at DESC LIMIT 100",
                (pid,),
            ).fetchall()
            conn.close()
            for r in runs:
                if r["id"] in present:
                    continue
                opts += f'<option value="{_h(r["id"])}">{_h(r["meet_name"] or r["id"])}</option>'
        except Exception:
            opts = ""
        opts = opts or '<option value="">No processed meets to add</option>'
        picker = (
            '<div class="card" style="padding:12px 16px;margin:var(--sp-4) 0;display:flex;'
            'gap:8px;flex-wrap:wrap;align-items:center">'
            '<label for="mh-col-add" style="margin:0">Add a meet</label>'
            '<select id="mh-col-add" style="flex:1;min-width:200px;padding:8px 10px;'
            "border:1px solid var(--border);border-radius:6px;background:rgba(255,255,255,0.04);"
            f'color:inherit">{opts}</select>'
            '<button class="btn" onclick="mhColAdd()">Add</button></div>'
        )
    detail_url = url_for("api_collection_detail", collection_id=collection_id)
    body = (
        f'<div class="strap" style="margin-bottom:var(--sp-2)">'
        f'<a href="{url_for("collections_page")}" style="color:var(--ink-muted);'
        'text-decoration:none">&larr; All collections</a></div>'
        f"<h1>{_h(name)}</h1>" + picker + f'<div id="mh-col-items">{rows}</div>' + "<script>\n"
        f"var COL_URL='{detail_url}';\n"
        "function mhColAdd(){var s=document.getElementById('mh-col-add');"
        "if(!s||!s.value)return;"
        "fetch(COL_URL,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({action:'add_item',item_type:'run',item_id:s.value})})"
        ".then(function(r){return r.json();}).then(function(j){if(j.ok)location.reload();"
        "else if(window.MH&&MH.toast)MH.toast(j.detail||j.error||'Could not add','error',3000);})"
        ".catch(function(){if(window.MH&&MH.toast)MH.toast('Network error','error',3000);});}\n"
        "function mhColRemove(t,id){"
        "fetch(COL_URL,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({action:'remove_item',item_type:t,item_id:id})})"
        ".then(function(r){return r.json();}).then(function(){location.reload();})"
        ".catch(function(){if(window.MH&&MH.toast)MH.toast('Network error','error',3000);});}\n"
        "</script>"
    )
    return W._layout(name + " — collection", body, active="settings")


def newsletters_home():
    if not W._email_design_ok:
        return W._recovery_page(
            "Newsletters unavailable",
            "The newsletter composer isn't enabled on this deployment.",
            primary_cta=("Back to home", url_for("home")),
        )
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Newsletters", W._PW_NO_ORG, active="create")
    from mediahub.email_design import store as _ns

    items = _ns.list_newsletters(pid)
    range_opts = "".join(
        f'<option value="{_h(k)}">{_h(label)}</option>' for k, label in W._NL_RANGES
    )

    saved = ""
    if items:
        rows = []
        for it in items:
            badge = it["newsletter_format"].replace("_", " ").title()
            live = ' &middot; <span class="tag live">Published</span>' if it["published"] else ""
            rows.append(
                '<a class="card" style="display:block;text-decoration:none" '
                f'href="{url_for("newsletter_view", newsletter_id=it["newsletter_id"])}">'
                f"<strong>{_h(it['title'])}</strong>"
                f'<div class="dim" style="font-size:12px;margin-top:4px">{_h(badge)}{live}</div></a>'
            )
        saved = (
            '<h2 style="margin-top:28px">Your newsletters</h2>'
            '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr));'
            f'gap:12px">{"".join(rows)}</div>'
        )

    def _tile(fmt, name, desc, extra=""):
        return (
            '<div class="card"><h3 style="margin-top:0">' + name + "</h3>"
            '<p class="dim" style="font-size:13px">'
            + desc
            + "</p>"
            + extra
            + '<label class="mh-ai-opt" style="display:flex;align-items:center;gap:6px;'
            'font-size:12px;margin-top:8px;color:var(--ink-muted)">'
            '<input type="checkbox" class="mh-ai-toggle" checked> Write the intro with AI</label>'
            '<button class="btn" style="margin-top:8px" onclick="genNl(this,\'' + fmt + "')\">"
            "Generate</button></div>"
        )

    # H-12: the meet digest names which meet it covers. Same recent-meets
    # query the Documents "Meet programme" tile uses; the default option
    # keeps the pick-the-latest-in-range behaviour for one-click use.
    digest_run_opts = '<option value="">Latest meet in range</option>' + "".join(
        f'<option value="{_h(rid)}">{_h(name)} ({n} cards)</option>'
        for rid, name, n in W._doc_recent_runs(pid)
    )
    digest_meet_select = (
        '<label class="dim" for="nl-digest-run" style="font-size:12px;display:block;'
        'margin-top:8px">Meet</label>'
        f'<select id="nl-digest-run" class="input">{digest_run_opts}</select>'
    )

    body = (
        '<section class="mh-hero"><h1>Newsletters</h1>'
        '<p class="muted">Turn your approved content into a branded, send-anywhere '
        "newsletter — results, spotlights, fixtures and your sponsor, with an AI intro "
        "in your club voice. Download the email HTML for your list tool, or publish a "
        "hosted web version.</p></section>"
        '<div class="card" style="margin-bottom:14px"><label class="dim" style="font-size:13px">'
        "Period to cover</label><br>"
        f'<select id="nl-range" class="input" style="max-width:260px">{range_opts}</select></div>'
        '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px">'
        + _tile(
            "monthly_roundup",
            "Monthly roundup",
            "A month of approved content: numbers, highlights, fixtures and your sponsor.",
        )
        + _tile(
            "meet_digest",
            "Meet digest",
            "One meet: the standout swims, athletes to watch and what's next.",
            extra=digest_meet_select,
        )
        + _tile(
            "season_highlights",
            "Season highlights",
            "A season window: the headline numbers and the swims you'll remember.",
        )
        + _tile("blank", "Blank", "An empty newsletter you fill in yourself.")
        + "</div>"
        + saved
        + W._NEWSLETTERS_HOME_JS.replace("__GEN_URL__", url_for("api_newsletters_generate"))
    )
    return W._layout("Newsletters", body, active="create")


def api_newsletters_generate():
    if not W._email_design_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    body = request.get_json(silent=True) or {}
    fmt = (body.get("format") or "monthly_roundup").strip()
    if fmt not in ("monthly_roundup", "meet_digest", "season_highlights", "blank"):
        return jsonify({"ok": False, "error": "bad_format"}), 400
    preset = (body.get("range") or "this_month").strip()
    with_ai = bool(body.get("with_ai", True))
    # H-12: the meet digest can pin exactly one meet. Only the digest
    # takes a run_id; ownership is tenant-gated the same way as every
    # other per-run endpoint (a foreign run answers like a missing one).
    run_id = (body.get("run_id") or "").strip()
    if run_id and fmt != "meet_digest":
        run_id = ""
    if run_id and not W._can_access_run(run_id, W._load_run(run_id), pid):
        return jsonify({"ok": False, "error": "run_not_found"}), 404
    if with_ai:  # AI drafting is metered spend — permission + quota first
        denied = W._editorial_ai_gate(pid)
        if denied is not None:
            return denied
    start, end = W._nl_range(preset, body)
    prof = W.load_profile(pid)
    tone = (getattr(prof, "tone", "") or "warm-club") if prof else "warm-club"
    from mediahub.email_design import store as _ns
    from mediahub.email_design.draft import generate_newsletter

    try:
        spec = generate_newsletter(
            pid,
            start=start,
            end=end,
            newsletter_format=fmt,
            tone=tone,
            with_ai=with_ai,
            profile=prof,
            runs_dir=W.RUNS_DIR,
            run_id=run_id or None,
        )
    except Exception as e:  # honest AI-unavailable signal — offer a data-only build
        from mediahub.media_ai.llm import ClaudeUnavailableError

        if isinstance(e, ClaudeUnavailableError):
            return jsonify({"ok": False, "error": "no_ai", "message": str(e)}), 200
        W.log.warning("newsletter generation failed", exc_info=True)
        return jsonify({"ok": False, "error": "generate_failed"}), 500
    if with_ai:
        W._editorial_ai_record(pid, detail=f"newsletter={fmt}")
    _ns.save_newsletter(pid, spec)
    return jsonify(
        {
            "ok": True,
            "newsletter_id": spec.newsletter_id,
            "url": url_for("newsletter_view", newsletter_id=spec.newsletter_id),
        }
    )


def newsletter_view(newsletter_id: str):
    if not W._email_design_ok:
        return W._recovery_page(
            "Newsletters unavailable",
            "Not enabled here.",
            primary_cta=("Home", url_for("home")),
        )
    pid, spec = W._nl_load_owned(newsletter_id)
    if spec is None:
        return W._recovery_page(
            "Newsletter not found",
            "It may have been deleted, or belongs to another organisation.",
            primary_cta=("All newsletters", url_for("newsletters_home")),
        )
    from mediahub.email_design import store as _ns

    rec = _ns.newsletter_record(pid, newsletter_id) or {}
    html_url = url_for("api_newsletter_html", newsletter_id=newsletter_id)
    text_url = url_for("api_newsletter_text", newsletter_id=newsletter_id)

    # publish status block
    if rec.get("published") and rec.get("public_token"):
        hosted = url_for("newsletter_public", token=rec["public_token"], _external=True)
        publish_html = (
            '<div class="card" style="margin-bottom:14px">'
            "<strong>Hosted web version is live.</strong> "
            f'<a href="{_h(hosted)}" target="_blank">{_h(hosted)}</a>'
            '<div style="margin-top:8px">'
            '<button class="btn secondary" onclick="nlPublish(false)">Unpublish</button> '
            '<button class="btn secondary" onclick="nlPublish(true)">Re-publish latest</button>'
            "</div></div>"
        )
    else:
        publish_html = (
            '<div class="card" style="margin-bottom:14px">'
            "<strong>Publish a hosted web version</strong>"
            '<p class="dim" style="font-size:13px;margin:4px 0 8px">A shareable '
            "browser-readable page. The downloaded email embeds its card images inline, "
            "but publishing also gives hosted image links that every email client renders "
            "reliably.</p>"
            '<button class="btn" onclick="nlPublish(true)">Publish</button></div>'
        )

    spec_json = _h(json.dumps(spec.to_dict(), indent=2))
    # H-5: a structured content editor so editing wording/links no longer
    # means hand-writing raw spec JSON; the JSON textarea stays as the
    # "advanced" hatch for images and anything the fields don't cover.
    from mediahub.web import spec_editor as _se

    nl_structured = (
        '<div class="card" style="margin-bottom:14px"><h3 style="margin-top:0">Edit content</h3>'
        '<p class="dim" style="font-size:13px">Change your wording and links here — no JSON needed. '
        "Photos stay in the advanced editor below.</p>"
        f'<form method="post" action="{url_for("api_newsletter_content_edit", newsletter_id=newsletter_id)}">'
        f"{_se.render_structured(spec.to_dict(), 'newsletter')}"
        '<div style="margin-top:10px"><button class="btn" type="submit">Save changes</button></div>'
        "</form></div>"
    )
    period = _h(spec.subtitle or spec.newsletter_format.replace("_", " ").title())
    body = (
        f'<section class="mh-hero"><h1>{_h(spec.title)}</h1>'
        f'<p class="muted">{period}</p></section>'
        + publish_html
        + '<div style="margin-bottom:14px">'
        f'<a class="btn" href="{html_url}?dl=1">Download email HTML</a> '
        '<button class="btn secondary" onclick="nlCopyHtml()">Copy HTML</button> '
        f'<a class="btn secondary" href="{text_url}?dl=1">Download plain text</a> '
        '<button class="btn secondary" disabled title="Direct send is coming soon — '
        'for now, download or copy the HTML into your own mailing-list tool." '
        'style="opacity:.55;cursor:not-allowed">Send (coming soon)</button>'
        '<span id="nl-msg" class="dim" style="margin-left:10px"></span>'
        "</div>"
        '<p class="dim" style="font-size:12px;margin:0 0 8px">Preview (renders like an '
        "email client). Card images show here and on the hosted version.</p>"
        f'<iframe src="{html_url}?preview=1" '
        'style="width:100%;height:72vh;border:1px solid var(--panel);border-radius:8px;'
        'background:var(--panel)"></iframe>'
        + nl_structured
        + '<details style="margin-top:18px"><summary class="dim">Advanced — raw spec (JSON)</summary>'
        f'<textarea id="nl-spec" class="input" style="width:100%;height:300px;font-family:monospace;font-size:12px">{spec_json}</textarea>'
        '<button class="btn" style="margin-top:8px" onclick="nlSave()">Save changes</button> '
        '<button class="btn secondary" style="margin-top:8px" onclick="nlDelete()">Delete newsletter</button>'
        "</details>"
        + W._NEWSLETTER_VIEW_JS.replace("__HTML_URL__", html_url)
        .replace("__SAVE_URL__", url_for("api_newsletter_save", newsletter_id=newsletter_id))
        .replace("__DEL_URL__", url_for("api_newsletter_delete", newsletter_id=newsletter_id))
        .replace("__PUB_URL__", url_for("api_newsletter_publish", newsletter_id=newsletter_id))
        .replace("__UNPUB_URL__", url_for("api_newsletter_unpublish", newsletter_id=newsletter_id))
        .replace("__HOME_URL__", url_for("newsletters_home"))
    )
    return W._layout(spec.title, body, active="create")


def api_newsletter_html(newsletter_id: str):
    if not W._email_design_ok:
        return jsonify({"error": "unavailable"}), 503
    pid, spec = W._nl_load_owned(newsletter_id)
    if spec is None:
        return jsonify({"error": "not_found"}), 404
    from mediahub.email_design import store as _ns

    preview = request.args.get("preview") == "1"
    is_dl = request.args.get("dl") == "1"
    token = ""
    embed = False
    if not preview:
        rec = _ns.newsletter_record(pid, newsletter_id) or {}
        if rec.get("published"):
            token = rec.get("public_token", "")
        elif is_dl:
            # D-18 — a downloaded draft used to omit every card image. Embed
            # them inline so the file is self-contained; publishing still
            # gives hosted URLs that every email client renders.
            embed = True
    html = W._nl_render_html(
        pid, newsletter_id, spec, preview=preview, published_token=token, embed=embed
    )
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    if request.args.get("dl") == "1":
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{W._safe_filename(spec.title, "html")}"'
        )
    return resp


def api_newsletter_text(newsletter_id: str):
    if not W._email_design_ok:
        return jsonify({"error": "unavailable"}), 503
    pid, spec = W._nl_load_owned(newsletter_id)
    if spec is None:
        return jsonify({"error": "not_found"}), 404
    from mediahub.email_design.render import render_plaintext

    text_out = render_plaintext(spec, profile=W.load_profile(pid))
    resp = make_response(text_out)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    if request.args.get("dl") == "1":
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{W._safe_filename(spec.title, "txt")}"'
        )
    return resp


def api_newsletter_save(newsletter_id: str):
    if not W._email_design_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid, spec = W._nl_load_owned(newsletter_id)
    if spec is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    body = request.get_json(silent=True) or {}
    raw = body.get("spec")
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "bad_spec"}), 400
    from mediahub.email_design import store as _ns
    from mediahub.email_design.models import NewsletterSpec

    raw["newsletter_id"] = newsletter_id  # never let an edit reassign identity
    _ns.save_newsletter(pid, NewsletterSpec.from_dict(raw))
    return jsonify({"ok": True})


def api_newsletter_content_edit(newsletter_id: str):
    """H-5: apply the structured content editor's form onto the newsletter.

    Reads request.form (a plain server-rendered POST) rather than JSON, so it
    is distinct from api_newsletter_save's JSON hatch. Load → to_dict → apply
    whitelisted (block_id, prop) edits by id → from_dict → save; identity id
    and every non-whitelisted field survive untouched.
    """
    if not W._email_design_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid, spec = W._nl_load_owned(newsletter_id)
    if spec is None:
        abort(404)
    from mediahub.email_design import store as _ns
    from mediahub.email_design.models import NewsletterSpec
    from mediahub.web import spec_editor as _se

    data = spec.to_dict()
    _se.apply_structured(data, request.form, "newsletter")
    data["newsletter_id"] = newsletter_id
    _ns.save_newsletter(pid, NewsletterSpec.from_dict(data))
    return redirect(url_for("newsletter_view", newsletter_id=newsletter_id))


def api_newsletter_delete(newsletter_id: str):
    if not W._email_design_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    from mediahub.email_design import store as _ns

    return jsonify({"ok": _ns.delete_newsletter(pid, newsletter_id)})


def api_newsletter_publish(newsletter_id: str):
    if not W._email_design_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    from mediahub.email_design import store as _ns

    token = _ns.publish_newsletter(pid, newsletter_id)
    if not token:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "url": url_for("newsletter_public", token=token, _external=True)})


def api_newsletter_unpublish(newsletter_id: str):
    if not W._email_design_ok:
        return jsonify({"ok": False, "error": "unavailable"}), 503
    pid = W._active_profile_id()
    if not pid:
        return jsonify({"ok": False, "error": "not_signed_in"}), 403
    from mediahub.email_design import store as _ns

    return jsonify({"ok": _ns.unpublish_newsletter(pid, newsletter_id)})


def newsletter_preview_card(newsletter_id: str, run_id: str, card_id: str):
    """Authenticated card image for the editor preview (owner-only, IDOR-guarded)."""
    if not W._email_design_ok:
        abort(404)
    pid, spec = W._nl_load_owned(newsletter_id)
    if spec is None:
        abort(404)
    if (run_id, card_id) not in W._nl_card_refs(spec):
        abort(404)  # draft-scoped: only cards the spec references
    run_data = W._load_run(run_id)
    if run_data is None or not W._can_access_run(run_id, run_data, pid):
        abort(404)
    path = W._nl_card_image_path(pid, run_id, card_id)
    if not path:
        abort(404)
    resp = make_response(send_file(path, mimetype="image/png"))
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def newsletter_public(token: str):
    """The hosted web version — the published snapshot, served to anyone with
    the unguessable link (the human-approval publish gate decides who that is)."""
    if not W._email_design_ok:
        abort(404)
    from mediahub.email_design import store as _ns

    ref = _ns.resolve_token(token)
    if not ref:
        abort(404)
    pid, newsletter_id = ref
    spec = _ns.load_published(pid, newsletter_id)
    if spec is None:
        abort(404)
    html = W._nl_render_html(pid, newsletter_id, spec, published_token=token)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def newsletter_public_card(token: str, run_id: str, card_id: str):
    """Card image for a published newsletter (token-scoped, IDOR-guarded)."""
    if not W._email_design_ok:
        abort(404)
    from mediahub.email_design import store as _ns

    ref = _ns.resolve_token(token)
    if not ref:
        abort(404)
    pid, newsletter_id = ref
    spec = _ns.load_published(pid, newsletter_id)
    if spec is None:
        abort(404)
    if (run_id, card_id) not in W._nl_card_refs(spec):
        abort(404)  # snapshot-scoped: the token only unlocks referenced cards
    run_data = W._load_run(run_id)
    if run_data is None or not W._can_access_run(run_id, run_data, pid):
        abort(404)
    path = W._nl_card_image_path(pid, run_id, card_id)
    if not path:
        abort(404)
    resp = make_response(send_file(path, mimetype="image/png"))
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule("/season", endpoint="season_timeline_page", view_func=season_timeline_page)
    app.add_url_rule(
        "/api/plan/latest", endpoint="api_plan_latest", view_func=api_plan_latest, methods=["GET"]
    )
    app.add_url_rule(
        "/api/plan/generate",
        endpoint="api_plan_generate",
        view_func=api_plan_generate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/plan/inputs",
        endpoint="api_plan_inputs",
        view_func=api_plan_inputs,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/plan/interpret",
        endpoint="api_plan_interpret",
        view_func=api_plan_interpret,
        methods=["POST"],
    )
    app.add_url_rule("/plan", endpoint="plan_page", view_func=plan_page)
    app.add_url_rule(
        "/api/plan/calendar",
        endpoint="api_plan_calendar",
        view_func=api_plan_calendar,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/plan/calendar/schedule",
        endpoint="api_plan_calendar_schedule",
        view_func=api_plan_calendar_schedule,
        methods=["POST"],
    )
    app.add_url_rule("/plan/calendar", endpoint="plan_calendar_page", view_func=plan_calendar_page)
    app.add_url_rule(
        "/plan/preview/<pack_id>", endpoint="plan_preview_page", view_func=plan_preview_page
    )
    app.add_url_rule("/plan/grid", endpoint="plan_grid_page", view_func=plan_grid_page)
    app.add_url_rule(
        "/api/plan/board", endpoint="api_plan_board", view_func=api_plan_board, methods=["GET"]
    )
    app.add_url_rule(
        "/api/plan/board/add",
        endpoint="api_plan_board_add",
        view_func=api_plan_board_add,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/plan/board/move",
        endpoint="api_plan_board_move",
        view_func=api_plan_board_move,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/plan/board/delete",
        endpoint="api_plan_board_delete",
        view_func=api_plan_board_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/plan/board/promote",
        endpoint="api_plan_board_promote",
        view_func=api_plan_board_promote,
        methods=["POST"],
    )
    app.add_url_rule("/plan/board", endpoint="plan_board_page", view_func=plan_board_page)
    app.add_url_rule(
        "/api/plan/analytics/record",
        endpoint="api_plan_analytics_record",
        view_func=api_plan_analytics_record,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/plan/analytics/delete",
        endpoint="api_plan_analytics_delete",
        view_func=api_plan_analytics_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/plan/analytics/digest",
        endpoint="api_plan_analytics_digest",
        view_func=api_plan_analytics_digest,
        methods=["POST"],
    )
    app.add_url_rule(
        "/plan/analytics", endpoint="plan_analytics_page", view_func=plan_analytics_page
    )
    app.add_url_rule(
        "/plan/ad-variants/<pack_id>",
        endpoint="plan_ad_variants_page",
        view_func=plan_ad_variants_page,
    )
    app.add_url_rule(
        "/api/plan/ad-variants/<pack_id>/export",
        endpoint="api_plan_ad_variants_export",
        view_func=api_plan_ad_variants_export,
    )
    app.add_url_rule("/sponsor-post", endpoint="stub_sponsor_post", view_func=stub_sponsor_post)
    app.add_url_rule(
        "/session-update", endpoint="stub_session_update", view_func=stub_session_update
    )
    app.add_url_rule("/drafts", endpoint="stub_packs_list", view_func=stub_packs_list)
    app.add_url_rule("/drafts/<pack_id>", endpoint="stub_pack_view", view_func=stub_pack_view)
    app.add_url_rule(
        "/drafts/<pack_id>/export.txt", endpoint="stub_pack_export", view_func=stub_pack_export
    )
    app.add_url_rule(
        "/drafts/<pack_id>/delete",
        endpoint="stub_pack_delete",
        view_func=stub_pack_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/status",
        endpoint="api_stub_pack_card_status",
        view_func=api_stub_pack_card_status,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/caption/save",
        endpoint="api_stub_pack_caption_save",
        view_func=api_stub_pack_caption_save,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/create-graphic",
        endpoint="api_stub_pack_create_graphic",
        view_func=api_stub_pack_create_graphic,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/caption",
        endpoint="api_stub_pack_caption",
        view_func=api_stub_pack_caption,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/caption/assist",
        endpoint="api_stub_pack_caption_assist",
        view_func=api_stub_pack_caption_assist,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/reel-job",
        endpoint="api_stub_pack_reel_job",
        view_func=api_stub_pack_reel_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/reel-file",
        endpoint="api_stub_pack_reel_file",
        view_func=api_stub_pack_reel_file,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/reformat",
        endpoint="api_stub_pack_reformat",
        view_func=api_stub_pack_reformat,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/assistant",
        endpoint="api_stub_pack_assistant",
        view_func=api_stub_pack_assistant,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/card/<int:card_idx>/assistant/suggestions",
        endpoint="api_stub_pack_assistant_suggestions",
        view_func=api_stub_pack_assistant_suggestions,
    )
    app.add_url_rule(
        "/api/drafts/<pack_id>/regenerate",
        endpoint="api_stub_pack_regenerate",
        view_func=api_stub_pack_regenerate,
        methods=["POST"],
    )
    app.add_url_rule("/sponsors", endpoint="sponsors_page", view_func=sponsors_page)
    app.add_url_rule(
        "/sponsors/add", endpoint="sponsors_add", view_func=sponsors_add, methods=["POST"]
    )
    app.add_url_rule(
        "/sponsors/delete", endpoint="sponsors_delete", view_func=sponsors_delete, methods=["POST"]
    )
    app.add_url_rule("/sponsors/report", endpoint="sponsors_report", view_func=sponsors_report)
    app.add_url_rule(
        "/api/collections",
        endpoint="api_collections",
        view_func=api_collections,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/collections/<collection_id>",
        endpoint="api_collection_detail",
        view_func=api_collection_detail,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/collections", endpoint="collections_page", view_func=collections_page)
    app.add_url_rule(
        "/collections/<collection_id>",
        endpoint="collection_detail_page",
        view_func=collection_detail_page,
    )
    app.add_url_rule("/newsletters", endpoint="newsletters_home", view_func=newsletters_home)
    app.add_url_rule(
        "/api/newsletters/generate",
        endpoint="api_newsletters_generate",
        view_func=api_newsletters_generate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/newsletters/<newsletter_id>", endpoint="newsletter_view", view_func=newsletter_view
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/html",
        endpoint="api_newsletter_html",
        view_func=api_newsletter_html,
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/text",
        endpoint="api_newsletter_text",
        view_func=api_newsletter_text,
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/save",
        endpoint="api_newsletter_save",
        view_func=api_newsletter_save,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/content-edit",
        endpoint="api_newsletter_content_edit",
        view_func=api_newsletter_content_edit,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/delete",
        endpoint="api_newsletter_delete",
        view_func=api_newsletter_delete,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/publish",
        endpoint="api_newsletter_publish",
        view_func=api_newsletter_publish,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/newsletters/<newsletter_id>/unpublish",
        endpoint="api_newsletter_unpublish",
        view_func=api_newsletter_unpublish,
        methods=["POST"],
    )
    app.add_url_rule(
        "/newsletters/<newsletter_id>/card/<run_id>/<card_id>.png",
        endpoint="newsletter_preview_card",
        view_func=newsletter_preview_card,
    )
    app.add_url_rule(
        "/newsletter/<token>", endpoint="newsletter_public", view_func=newsletter_public
    )
    app.add_url_rule(
        "/newsletter/<token>/card/<run_id>/<card_id>.png",
        endpoint="newsletter_public_card",
        view_func=newsletter_public_card,
    )
