"""Public site, PWA chrome & compliance pages: landing, about/help/pricing, health probes, legal.

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
from pathlib import Path
from typing import Optional
import json
import os
import re
from flask import (
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    session,
    url_for,
)

from mediahub.web import web as W


def home():
    """Rebuilt home page (Phase 1.5 polish).

    Two-button hero — "Sign up" (primary) + "Log in" (secondary, the
    ACCOUNT log-in) — plus the established four-step explainer. When an
    org is already pinned, the hero swaps in a "Continue as <name>" CTA
    pointing at Create, with the log-in / create paths still accessible
    below so the user can switch tenants without rummaging through nav.
    """
    prof = W._active_profile()
    existing = W.list_profiles()
    n_orgs = len(existing)

    # Compute small deployment-wide tallies for the hero meta line so the
    # page doesn't feel hollow once the user has activity. The third figure
    # is the honest headline — the sum of STANDOUT SWIMS (n_standout:
    # distinct swims whose best band is elite/strong, deduped across the
    # several achievements one race can emit) — NOT raw n_achievements,
    # which counts every derivative detection and reads absurdly high, and
    # NOT the legacy n_cards column, which the V5 recognition-first
    # pipeline leaves at ~0 and would read as a falsehood ("0 cards
    # generated"). COALESCE keeps NULL rows (pre-column runs that were
    # never relisted) as 0: an honest lower bound, never a fabrication.
    # Honesty (H-3): a signed-in club must see ITS OWN season, not the
    # deployment-wide totals. When a workspace is pinned the tallies are
    # scoped to that profile_id; the signed-out landing keeps the global
    # figures (a genuine "this many clubs use it" proof, not a per-org claim).
    n_runs = 0
    n_moments = 0
    n_awaiting = 0
    _tally_pid = prof.profile_id if (prof and prof.is_ready()) else None
    try:
        conn = W._db()
        try:
            if _tally_pid:
                n_runs = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM runs WHERE profile_id = ?", (_tally_pid,)
                    ).fetchone()[0]
                )
                n_moments = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(n_standout), 0) FROM runs WHERE profile_id = ?",
                        (_tally_pid,),
                    ).fetchone()[0]
                    or 0
                )
                n_awaiting = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(n_queue), 0) FROM runs "
                        "WHERE profile_id = ? AND status = 'done'",
                        (_tally_pid,),
                    ).fetchone()[0]
                    or 0
                )
            else:
                n_runs = int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
                n_moments = int(
                    conn.execute("SELECT COALESCE(SUM(n_standout), 0) FROM runs").fetchone()[0] or 0
                )
        finally:
            conn.close()
    except Exception:
        pass

    # --- Hero ----------------------------------------------------------
    # Lane-number watermark sits behind the headline. The org name stays
    # in default ink (no .grad span) so the only lane-yellow on the page
    # is the live dot + the CTA. Editorial italic does the emphasis work.
    # U.9 — only the signed-out hero cycles its content-type accent word;
    # the returning-user "Ready to file." greeting stays static, so the
    # cycling script ships only when the rotator is actually on the page.
    word_cycle_js = ""
    if prof and prof.is_ready():
        # Returning user with a pinned org.
        hero_h1 = f'{_h(prof.display_name)}.<br><em class="editorial">Ready</em> to file.'
        hero_lede = (
            "Your brand voice, palette, and logo are loaded. Drop a results "
            "file and the on-brand captions, graphics and reels draft "
            "themselves — you approve, nothing posts without you."
        )
        # The top return task is "upload the weekend's results", so that is
        # the ONE primary action and it deep-links straight to /upload (no
        # content-type chooser detour). "Create other content" reaches the
        # rest; "Edit profile" stays the canonical link to brand/setup (it
        # must point at /organisation/setup, not the legacy /organisation
        # editor — g3 brand-canonical guard).
        # "Switch organisation" is a developer-operator-only affordance
        # (ADR-0029): members and anonymous pilot sessions never switch —
        # their club IS their session. The /sign-in picker itself stays as
        # the org-ready gate destination and the first org pick.
        _switch_cta = (
            f'<a class="mh-cta-secondary" href="{url_for("sign_in_page")}">'
            "Switch organisation</a>"
            if W._auth.is_dev_operator()
            else ""
        )
        hero_actions = (
            f'<a class="mh-cta-primary" href="{url_for("upload")}">'
            "Upload results &rarr;</a>"
            f'<a class="mh-cta-secondary" href="{url_for("make_page")}">'
            "Create other content</a>"
            + _switch_cta
            + f'<a class="mh-cta-secondary" href="{url_for("organisation_setup")}">'
            "Edit profile</a>"
        )
        eyebrow = "Pinned organisation"
        lane_no = "04"
    else:
        # Fresh visit (or signed-out). Display-caps + italic emphasis.
        # U.9 — the content-type noun is now the gold serif-italic accent
        # and crossfades through stories / reels / graphics / captions.
        hero_h1 = "Results in.<br>On-brand " + W._hero_word_cycle_html() + " out."
        word_cycle_js = W._HERO_WORD_CYCLE_JS
        # Lede leads with the ONE concrete thing MediaHub does, in plain
        # words, so a visitor who has never heard of it understands the
        # mechanic in a single read: upload a results file → the engine
        # finds the moments → it drafts branded content → you approve.
        # (The old lede opened on brand-reading — the setup step — which
        # buried the actual value under the secondary detail.)
        hero_lede = (
            "Upload your meet results — HY3, PDF or a spreadsheet. MediaHub "
            "finds every personal best, medal and club record, writes the "
            "caption, and builds branded story cards, feed graphics and "
            "reels — ready to post in your club's colours and voice. You "
            "approve each one; nothing posts without you."
        )
        # Sign up is the unambiguous entry point for a first-time visitor.
        # The secondary CTA is the ACCOUNT log-in for returning users
        # (A-5): authentication is an account action, and organisation
        # selection happens afterwards — so it points at /login, not the
        # org picker, and the words never collide with the org vocabulary.
        hero_actions = (
            f'<a class="mh-cta-primary" href="{url_for("signup_page")}">'
            "Sign up &rarr;</a>"
            f'<a class="mh-cta-secondary" href="{url_for("login_page")}">'
            "Log in</a>"
        )
        eyebrow = "Turn meet results into ready-to-post content"
        lane_no = "01"

    # Meta line under the CTAs — bracketed mono strap, scoreboard voice.
    # U.12: the live tallies are odometer numerals — zero-padded digit
    # reels that roll upward on page load + scroll-into-view via the shared
    # reveal/counter system (data-mh-count + data-mh-odometer). Progressive
    # enhancement: the padded value is the element's text, so it reads
    # correctly with JS off; role="img" + aria-label hand assistive tech the
    # clean (unpadded, comma-grouped) value on both the JS and no-JS paths.
    def _odometer(value: int, pad: int) -> str:
        return (
            f'<b class="mh-odo" role="img" aria-label="{value:,}" '
            f'data-mh-count="{value}" data-mh-odometer data-mh-count-pad="{pad}">'
            f"{value:0{pad}d}</b>"
        )

    meta_parts = []
    # Signed-in with a review queue waiting: lead the strap with the ONE
    # actionable number, accented, so a returning club sees its outstanding
    # work first (and the resume strip below links straight into it).
    if _tally_pid and n_awaiting:
        meta_parts.append(
            f'<span class="mh-hero-meta-live">{_odometer(n_awaiting, 2)} '
            f"{'card' if n_awaiting == 1 else 'cards'} awaiting your review</span>"
        )
    # The signed-out landing leads with the deployment-wide org count as
    # social proof; a signed-in club doesn't need "N clubs use this" pitched
    # back — its strap is its own season (runs/moments) plus the queue above.
    if n_orgs and not _tally_pid:
        meta_parts.append(
            f"<span>{_odometer(n_orgs, 2)} {'organisation' if n_orgs == 1 else 'organisations'}</span>"
        )
    if n_runs:
        meta_parts.append(
            f"<span>{_odometer(n_runs, 3)} {'result' if n_runs == 1 else 'results'} processed</span>"
        )
    if n_moments:
        meta_parts.append(
            f"<span>{_odometer(n_moments, 3)} standout "
            f"{'swim' if n_moments == 1 else 'swims'} found</span>"
        )
    if prof and prof.brand_capture_status in ("ok", "ok_heuristic"):
        meta_parts.append("<span>Brand voice <b>captured</b></span>")
    meta_html = ""
    if meta_parts:
        sep = '<span class="dot">/</span>'
        meta_html = '<div class="mh-hero-meta">' + sep.join(meta_parts) + "</div>"

    # Demo line for first-time visitors — small tertiary CTA below the
    # primary buttons. Links to /upload which the org gate will steer
    # them through cleanly if they don't have an org yet.
    demo_line_html = ""
    if not (prof and prof.is_ready()):
        demo_line_html = (
            '<p class="mh-demo-line">Just looking? '
            '<a href="#mh-see-it-work">See it in action</a>, '
            '<a href="' + url_for("about_page") + '">take the full tour</a> '
            'or <a href="' + url_for("sign_in_page") + '">browse pinned organisations</a>.'
            "</p>"
        )

    # Three-step "how it works" strip, sits under the lede so the core
    # mechanic (generate → review → approve) is glanceable ABOVE THE FOLD —
    # the one screen every visitor sees — instead of only in the scroll-down
    # explainer. Labels match the live product demo's step indicator below
    # (mh-demo-steps in _hero_product_demo) so a visitor reads one consistent
    # vocabulary for the same 3 stages. Fresh / signed-out visitors only; a
    # pinned org already knows the flow and gets the lean "Ready to file" hero.
    steps_html = ""
    if not (prof and prof.is_ready()):
        _steps = (
            ("01", "Generate"),
            ("02", "Review"),
            ("03", "Approve"),
        )
        steps_html = (
            '<ol class="mh-hero-steps" '
            'aria-label="How MediaHub works, in three steps">'
            + "".join(
                f'<li><span class="i" aria-hidden="true">{i}</span>'
                f'<span class="t">{t}</span></li>'
                for i, t in _steps
            )
            + "</ol>"
        )

    # U.10 — framed, looping product demo in its own "See it work" section.
    # It is now the FIRST section after the hero (ahead of the read ->
    # engine -> write diagram), so the concrete product proof lands before
    # the conceptual explainer. Fresh / signed-out visitors only; a pinned
    # org gets the utilitarian "Ready to file" hero with no marketing demo.
    demo_html = "" if (prof and prof.is_ready()) else W._hero_product_demo()
    demo_section_html = ""
    if demo_html:
        demo_section_html = (
            '<section class="mh-section mh-reveal" id="mh-see-it-work">'
            '<div class="mh-section-eyebrow-strip mh-reveal">'
            '<span class="label">See it work</span></div>'
            + W._reveal_lines(["One result in.", 'A post you <em class="editorial">approve</em>.'])
            + demo_html
            + "</section>"
        )

    hero_html = (
        f'<section class="mh-hero" id="mh-ch-overview" data-lane="{lane_no}">'
        f'<span class="mh-hero-eyebrow">{_h(eyebrow)}</span>'
        f"<h1>{hero_h1}</h1>"
        f'<p class="lede">{_h(hero_lede)}</p>'
        f"{steps_html}"
        f'<div class="mh-hero-actions">{hero_actions}</div>'
        f"{demo_line_html}"
        f"{meta_html}"
        "</section>"
        f"{word_cycle_js}"
    )

    # The product-story explainer sections (input→output headline, the
    # "what the engine does" bento, the "made for" audience cards, the
    # human-in-the-loop promise and the FAQ) are built by the module-level
    # `_home_*` helpers above. The signed-OUT landing page assembles them
    # below; the signed-IN home omits them (they live on the Help page).

    # --- Final CTA strip before the footer. Two variants based on
    # whether the user has a pinned org. Picks up the masthead lane-
    # stripe accent so the page resolves with the same chrome.
    if prof and prof.is_ready():
        final_cta_html = (
            '<section class="mh-final-cta mh-reveal" id="mh-ch-start">'
            "<div>"
            + W._reveal_lines(
                ["Next weekend's meet,", "<em>ready</em> in a sitting."],
                cls="mh-final-cta-headline",
            )
            + '<p class="mh-final-cta-sub mh-reveal">Drop the results file. We\'ll '
            "rank the moments and write the captions; you spend the "
            "evening approving instead of opening Photoshop.</p>"
            "</div>"
            '<div class="mh-final-cta-actions">'
            f'<a class="btn large" href="{url_for("make_page")}">Start a content pack &rarr;</a>'
            f'<a class="btn secondary" href="{url_for("activity_page")}">All recent runs</a>'
            "</div>"
            "</section>"
        )
    else:
        final_cta_html = (
            '<section class="mh-final-cta mh-reveal" id="mh-ch-start">'
            "<div>"
            + W._reveal_lines(
                ["A minute to set up.", "<em>Then</em> every week is easier."],
                cls="mh-final-cta-headline",
            )
            + '<p class="mh-final-cta-sub mh-reveal">Tell us your club\'s name and '
            "website. We'll read your brand, palette and voice, and have "
            "on-brand drafts ready the next time you upload a results file.</p>"
            "</div>"
            '<div class="mh-final-cta-actions">'
            f'<a class="btn large" href="{url_for("organisation_setup")}">Create your organisation &rarr;</a>'
            f'<a class="btn secondary" href="{url_for("login_page")}">Log in</a>'
            "</div>"
            "</section>"
        )

    # ================================================================ #
    # Signed-in home — a content-creation workspace, not a sales page.
    #
    # A returning club doesn't need "what the engine does" pitched back at
    # it every visit; it needs to get to work. So the pinned-org home is a
    # lean dashboard: the "Ready to file" hero, a quick-action grid to the
    # surfaces they actually use (their runs live on the org-scoped
    # /activity page, reached from the "All activity" tile), then the
    # create-focused final CTA. The product-story explainer (how it works /
    # what it does / promise / FAQ) moved to the in-app Help page, reached
    # from the account menu. Signed-OUT visitors still get the full landing.
    # ================================================================ #
    if prof and prof.is_ready():
        return W._layout(
            "Home",
            '<div class="mh-fx mh-spotlight">'
            + hero_html
            + "</div>"
            + W._home_resume_strip_html(prof.profile_id)
            + W._home_signed_in_quick_actions_html(n_awaiting)
            + final_cta_html,
            active="home",
        )

    # --- Signed-out landing page — brief, but really clear. ------------
    # The home page states plainly what MediaHub is and shows it working;
    # the depth (the animated step-by-step walkthrough and the full explainer
    # sections) lives on /about, one obvious click away. Keeping the landing
    # short means a cold visitor gets the value in one screen and one scroll,
    # not a marketing scroll marathon. No scroll-spy rail here — the page is
    # deliberately too short to need one (it lives on /about instead).
    about_teaser_html = (
        '<section class="mh-section mh-reveal" '
        'style="text-align:center;padding-top:var(--sp-4)">'
        + W._reveal_lines(["See exactly how", 'it <em class="editorial">works</em>.'])
        + '<p class="mh-pipeline-sub" style="margin:0 auto var(--sp-5);max-width:52ch">'
        "A step-by-step, animated walkthrough of the whole flow &mdash; from a "
        "results file to an approved post &mdash; plus who it&rsquo;s for and "
        "our human-in-the-loop promise.</p>"
        f'<a class="btn large" href="{url_for("about_page")}">Take the tour &rarr;</a>'
        "</section>"
    )
    return W._layout(
        "Home",
        '<div class="mh-fx mh-spotlight">'
        + hero_html
        + "</div>"
        # Concrete product proof FIRST: the framed generate → review →
        # approve demo shows the actual thing (a results file becoming a
        # branded card + caption you approve) right after the hero.
        + demo_section_html
        # One crisp "what it is" statement — a results sheet in, four
        # posting-ready formats out — then a single clear path to the full
        # animated walkthrough and the deeper story on /about.
        + W._home_io_headline_html()
        + about_teaser_html
        + final_cta_html,
        active="home",
    )


def help_page():
    intro = (
        "Everything MediaHub does from a single upload — what goes in, what "
        "comes out, and the questions clubs ask first. It's all one click "
        "from Create whenever you need it."
    )
    header_html = (
        '<section class="mh-hero" data-lane="">'
        '<span class="mh-hero-eyebrow">Help &amp; how it works</span>'
        '<h1>How MediaHub <em class="editorial">works</em>.</h1>'
        f'<p class="lede">{_h(intro)}</p>'
        '<div class="mh-hero-actions">'
        f'<a class="mh-cta-primary" href="{url_for("make_page")}">'
        "Create new content &rarr;</a>"
        f'<a class="mh-cta-secondary" href="{url_for("status_page")}">'
        "System status</a>"
        "</div>"
        "</section>"
    )

    # The looping "see it work" product demo, wrapped exactly as the landing
    # page wraps it (its non-chapter id keeps it out of any scroll-spy rail).
    demo_section_html = (
        '<section class="mh-section mh-reveal" id="mh-see-it-work">'
        '<div class="mh-section-eyebrow-strip mh-reveal">'
        '<span class="label">See it work</span></div>'
        + W._reveal_lines(["One result in.", 'A post you <em class="editorial">approve</em>.'])
        + W._hero_product_demo()
        + "</section>"
    )

    # Closing "still stuck?" strip — points at the operator-facing surfaces
    # that answer the rest (live status, the privacy data inventory, roadmap).
    closing_html = (
        '<section class="mh-section">'
        '<div class="mh-section-eyebrow-strip mh-reveal">'
        '<span class="label">Still stuck?</span></div>'
        + W._reveal_lines(["Can't find the", '<em class="editorial">answer</em>?'])
        + '<p class="mh-reveal" style="color:var(--ink-dim);max-width:62ch">'
        "Check the live system status, audit exactly what's stored about your "
        "club on the privacy page, or see which result files you can upload."
        "</p>"
        '<div class="mh-hero-actions" style="margin-top:var(--sp-4)">'
        f'<a class="btn" href="{url_for("status_page")}">System status</a>'
        f'<a class="btn secondary" href="{url_for("privacy_page")}">'
        "Privacy &amp; data</a>"
        f'<a class="btn secondary" href="{url_for("research_page")}">Supported files</a>'
        f'<a class="btn secondary" href="{url_for("export_center_page")}">'
        "Export &amp; convert</a>"
        f'<a class="btn secondary" href="{url_for("print_center_page")}">'
        "Print &amp; merch</a>"
        "</div>"
        "</section>"
    )

    # Jump-chip row so the useful answers are one click away instead of a
    # scroll past the whole explainer. Reuses the shared .mh-legal-toc chrome;
    # every target is a real in-page anchor id (or a real page) so it works
    # with JS off. The FAQ (a keyboard-operable <details> accordion) is
    # rendered FIRST below — it's scannable in one screen — then the full
    # "how it works" explainer follows for anyone who wants the deep read.
    help_jump_html = (
        '<nav class="mh-legal-toc card" aria-label="Jump to" '
        'style="margin-top:var(--sp-4)">'
        '<span class="mh-legal-toc-eyebrow">Jump to</span>'
        '<div class="mh-legal-toc-links">'
        '<a href="#mh-faq-h">Common questions</a>'
        '<a href="#mh-pipeline-h">How the pipeline works</a>'
        '<a href="#mh-ch-engine">What it makes</a>'
        f'<a href="{url_for("research_page")}">Supported files</a>'
        f'<a href="{url_for("privacy_page")}">Privacy &amp; data</a>'
        "</div></nav>"
    )
    return W._layout(
        "Help",
        '<div class="mh-fx mh-spotlight">'
        + header_html
        + "</div>"
        + help_jump_html
        + W._home_faq_html()
        + W._pipeline_diagram_section_html()
        + demo_section_html
        + W._home_io_headline_html()
        + W._home_engine_bento_html()
        + W._home_audience_html()
        + W._home_promise_html()
        + closing_html,
        active="help",
    )


def recognition_page(run_id):
    """Standalone recognition page (redirect to review for now)."""
    return redirect(url_for("review", run_id=run_id))


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
def ground_truth(run_id, run_data):
    data = run_data
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
                cs.distance = cl.get("distance")
                cs.stroke = cl.get("stroke")
                claims.append(cs)
            s.claims = claims
            cards.append(s)
        rep = evaluate(text, cards)
        data["ground_truth_report"] = rep.to_dict()
        (W.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(data, indent=2, default=str))

        rows = ""
        for m in rep.matches:
            badge = "good" if m.get("matched_card") else "bad"
            rows += (
                f"<tr><td>{_h(m.get('moment', ''))}</td>"
                f'<td><span class="tag {badge}">'
                f"{'matched' if m.get('matched_card') else 'missed'}</span></td>"
                f"<td>{_h(m.get('matched_headline') or '—')}</td>"
                f"<td>{_h(m.get('score', ''))}</td></tr>"
            )
        rep_html = f"""
<div class="card">
  <h2>Result</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Precision</div><div class="v">{rep.precision * 100:.0f}%</div></div>
    <div class="stat"><div class="l">Recall</div><div class="v">{rep.recall * 100:.0f}%</div></div>
    <div class="stat"><div class="l">F1</div><div class="v">{rep.f1 * 100:.0f}%</div></div>
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
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Ground-truth check</span>
  <h1>How <em class="editorial">well</em> did we recall?</h1>
  <p class="lede">Paste 5&ndash;15 expected highlights from this meet. We score how many MediaHub surfaced as content cards. One per line.</p>
</section>

<div class="card">
  <form method="post" data-loader-text="Scoring recall">
    <label class="req" for="gt-moments">Expected moments (one per line)</label>
    <textarea id="gt-moments" name="moments" required placeholder="Eva Davies 100m butterfly PB
Mathew Bradley 200m IM gold
Relay team broke club record"></textarea>
    <div style="margin-top:var(--sp-4)"><button class="btn" type="submit">Score recall &rarr;</button></div>
  </form>
</div>
{rep_html}
"""
    return W._layout("Ground truth", body, active="home")


def api_docs_page():
    """Public Developer/API reference.

    Documents the real HTTP + JSON endpoints the app exposes, each with a
    tabbed cURL / Python / JavaScript code-example switcher. Highlighting is
    rendered server-side by ``code_highlight.py`` (no Prism, no CDN); the
    language tabs are pure CSS and the copy button is JS-enhanced (UI 1.11).
    """
    return W._layout("Developer API", W._render_api_docs_body(), active="")


def privacy_page():
    return W._privacy_page_render()


def terms_page():
    body = W._legal.terms_html(
        privacy_url=url_for("privacy_page"),
        cookies_url=url_for("cookies_page"),
        dpa_url=url_for("dpa_page"),
    )
    return W._layout("Terms of Service", body, active="")


def cookies_page():
    body = W._legal.cookies_html(privacy_url=url_for("privacy_page"))
    return W._layout("Cookie Policy", body, active="")


def dpa_page():
    body = W._legal.dpa_html(privacy_url=url_for("privacy_page"))
    return W._layout("Data Processing Agreement", body, active="")


def privacy_delete_run(run_id):
    # Defence in depth: run ids generated by _start_run / upload are
    # 12-hex-char tokens. Flask's default string converter already
    # blocks slashes, but tightening here rejects future shapes that
    # might somehow slip through (e.g. URL-decoded `..` chains).
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        return W._layout(
            "Delete blocked",
            '<div class="card"><p class="tag bad">That run id has an unexpected '
            "shape and was not deleted.</p></div>",
            active="privacy",
        ), 400
    # Multi-tenant guard: a run can only be deleted by the
    # organisation that owns it. Legacy untagged runs (empty
    # profile_id) are treated as belonging to whichever org is
    # active so the user can still clean them up. A request that
    # targets another tenant's run is refused with a 404 — we don't
    # confirm-or-deny the existence to a cross-tenant attacker.
    owner = W._run_owner_profile_id(run_id)
    active = W._active_profile_id() or ""
    if owner is None:
        return W._layout(
            "Run not found",
            '<div class="card"><p class="tag bad">No such run.</p></div>',
            active="privacy",
        ), 404
    if owner and active and owner != active:
        W.log.warning(
            "privacy_delete_run: cross-tenant attempt active=%r owner=%r run=%r",
            active,
            owner,
            run_id,
        )
        return W._layout(
            "Run not found",
            '<div class="card"><p class="tag bad">No such run.</p></div>',
            active="privacy",
        ), 404
    W._delete_run(run_id)
    # Stay where the delete was triggered. The settings activity table
    # posts via fetch() and just drops the row in place (the "delete there
    # and then, stay on the page" ask); a plain form post returns to the
    # page named in ``next`` (same-site validated), falling back to the
    # settings page rather than bouncing the user home.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "deleted": run_id})
    # Plain form post (e.g. the review-page danger zone) redirects away with
    # no other signal — a one-shot toast confirms the delete landed (U.2).
    W._flash_toast("Run deleted.")
    nxt = W._safe_next(request.form.get("next") or request.args.get("next"))
    return redirect(nxt or url_for("settings_page"))


def privacy_clear_all_runs():
    # Per-tenant bulk erase: permanently delete EVERY finished run owned by
    # the active organisation, via the same cascade as the single-run delete
    # (run JSON + sidecars + DB rows + re-derivable caches). The
    # ``WHERE profile_id`` gate is the tenant-isolation boundary — this never
    # touches another org's runs (mirrors privacy_delete_run).
    #
    # Only terminal runs (done/error) are cleared: deleting a run still in
    # flight would race the worker, whose _persist_run could resurrect the
    # DB row after we removed it. In-flight runs finish, then become
    # deletable like any other.
    active = W._active_profile_id() or ""
    if not active:
        # No active org → nothing safe to scope a wipe to (a blank
        # profile_id would match legacy untagged rows of unknown ownership).
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "no active organisation"}), 400
        W._flash_toast("No active organisation to clear.", "error")
        nxt = W._safe_next(request.form.get("next") or request.args.get("next"))
        return redirect(nxt or url_for("activity_page"))
    try:
        conn = W._db()
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM runs WHERE profile_id = ? AND status IN ('done','error')",
                (active,),
            ).fetchall()
        ]
        conn.close()
    except Exception:  # noqa: BLE001
        ids = []
    deleted = 0
    for rid in ids:
        try:
            W._delete_run(rid)
            deleted += 1
        except Exception:  # noqa: BLE001
            W.log.warning("clear-all: failed to delete run %s", rid, exc_info=True)
    W.log.info("clear-all: org=%r removed %d runs", active, deleted)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "deleted": deleted})
    W._flash_toast(f"Deleted {deleted} run{'s' if deleted != 1 else ''}.")
    nxt = W._safe_next(request.form.get("next") or request.args.get("next"))
    return redirect(nxt or url_for("activity_page"))


def privacy_cache_clear():
    for d in [W.DATA_DIR / ".cache" / "pb_lookup", W.DATA_DIR / ".cache" / "swimmingresults"]:
        if d.exists():
            for f in d.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass
    # Return to wherever the clear was triggered (Settings → Privacy or the
    # standalone /privacy page), not unconditionally to /privacy.
    nxt = W._safe_next(request.form.get("next"))
    return redirect(nxt or url_for("privacy_page"))


def complaints_form():
    return W._layout("Complaints", W._complaints_form_body(), active="privacy")


def complaints_submit():
    from mediahub.compliance.complaints import ComplaintsStore

    # Same trusted-proxy derivation as the auth limiter — the first XFF
    # hop is client-supplied, so keying on it would defeat the throttle.
    remote = W._client_ip()
    if W._complaints_throttled(remote):
        return W._layout(
            "Complaints",
            W._complaints_form_body(
                "Too many submissions from this address — please try again later."
            ),
            active="privacy",
        ), 429
    details = (request.form.get("details") or "").strip()
    contact = (request.form.get("contact") or "").strip()
    if not details or not contact:
        return W._layout(
            "Complaints",
            W._complaints_form_body("Please tell us what happened and how to reach you."),
            active="privacy",
        ), 400
    complaint = ComplaintsStore().submit(
        name=request.form.get("name") or "",
        contact=contact,
        details=details,
        relationship=request.form.get("relationship") or "",
        club=request.form.get("club") or "",
    )
    W.log.info("complaint received id=%s", complaint.id)  # no contact details in logs
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Privacy &amp; data</span>
  <h1>Complaint <em class="editorial">received.</em></h1>
  <p class="lede">Thank you. Your reference is <strong>{_h(complaint.id)}</strong> — keep it. We will acknowledge your complaint within 30 days (by {_h(complaint.ack_due_at[:10])}) using the contact details you gave.</p>
</section>
<div class="card"><p class="muted">You can also raise this with the Information Commissioner's Office at any time: ico.org.uk/make-a-complaint.</p></div>
"""
    return W._layout("Complaint received", body, active="privacy")


def legal_subprocessors():
    # One canonical register (legal.SUBPROCESSORS) renders the DPA §6
    # table AND this public page, and the PC.11 guard test pins it to
    # the env-flag surface — the two surfaces cannot drift apart.
    rows = W._legal.subprocessor_public_rows_html()
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Privacy &amp; data</span>
  <h1>Who we <em class="editorial">work with.</em></h1>
  <p class="lede">Every third party that can touch personal data processed by this service, what they do, where they do it, and the legal safeguard for the transfer. Social platforms (Instagram, Facebook, TikTok) are not processors — once a club approves a post, the platform handles it under its own terms.</p>
</section>
<div class="card">
  <table>
    <thead><tr><th>Provider</th><th>What they do</th><th>Where</th><th>Transfer safeguard</th><th>When engaged</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="muted">Clubs are notified before a new sub-processor is added and may object (see the Data Processing Agreement). The swimmingresults.org rankings site is a public data <em>source</em>, not a processor — nothing is sent to it beyond the lookup itself.</p>
</div>
"""
    return W._layout("Sub-processors", body, active="privacy")


def privacy_athlete_erase():
    """Erase one named athlete across everything the active org holds."""
    active = W._active_profile_id() or ""
    if not active:
        return redirect(url_for("privacy_page"))
    name = (request.form.get("athlete_name") or "").strip()
    club = (request.form.get("athlete_club") or "").strip()
    if not name:
        # H-17: re-render with an inline error instead of a silent
        # redirect that discarded what the user typed.
        return W._privacy_page_render(
            erase_error=(
                "Enter the athlete's full name — nothing was erased. "
                "The name must match how it appears in the results."
            ),
            erase_values={"athlete_name": name, "athlete_club": club},
            status=400,
        )
    # ONE erasure engine: compliance.dsr delegates to the privacy
    # cascade and adds the media-library / profile-text / suppression
    # extras, so this quick action and the Art 12A DSR workflow
    # (/organisation/athlete-rights) do the same work.
    from mediahub.compliance.dsr import erase_athlete as _dsr_erase

    recorded_by = ""
    try:
        recorded_by = W._auth.current_user_email() or ""
    except Exception:
        pass
    report = _dsr_erase(
        active, name, recorded_by=recorded_by, include_ownerless=W._ownerless_run_readable()
    )
    cascade = report.get("cascade") or {}
    body = (
        '<section class="mh-hero" style="padding-top:var(--sp-7);'
        'padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Privacy &amp; data</span>'
        '<h1>Athlete <em class="editorial">erased.</em></h1></section>'
        '<div class="card"><h2>What was removed</h2>'
        + W._erasure_removed_html(report, cascade)
        + "<p class='muted'>Remaining mentions inside multi-athlete captions "
        "were redacted. Content already published to social "
        "platforms must be deleted there too &mdash; use the correction tools "
        "on the Privacy page.</p>"
        f'<p><a class="btn secondary" href="{url_for("privacy_page")}">'
        "&larr; Back to privacy</a></p></div>"
    )
    return W._layout("Athlete erased", body, active="privacy")


def privacy_correction_open():
    """Open a correction/takedown for a published-but-wrong card.

    Does everything MediaHub controls: records the request and pulls the
    card off the public wall. The response is honest about the manual
    remainder (deleting the post on the platform itself)."""
    active = W._active_profile_id() or ""
    if not active:
        return redirect(url_for("privacy_page"))
    run_id = (request.form.get("run_id") or "").strip()
    card_id = (request.form.get("card_id") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    _ids_ok = bool(
        re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id)
        and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", card_id)
    )
    if not (_ids_ok and reason):
        # H-17: re-render with an inline error next to the form and the
        # typed values preserved, instead of a silent redirect that
        # discarded them.
        if not _ids_ok:
            _msg = (
                "That meet or card id doesn't look right — copy both from "
                "the meet's page and try again. Nothing was recorded."
            )
        else:
            _msg = (
                "Say what's wrong with the card — the reason is recorded "
                "with the correction. Nothing was recorded yet."
            )
        return W._privacy_page_render(
            correction_error=_msg,
            correction_values={
                "run_id": run_id,
                "card_id": card_id,
                "reason": reason,
            },
            status=400,
        )
    from mediahub.privacy import TAKEDOWN_CHECKLIST, open_correction

    cid = open_correction(profile_id=active, run_id=run_id, card_id=card_id, reason=reason)
    # Pull the card off the public wall immediately.
    try:
        from mediahub.web.public_wall import card_key

        prof = W.load_profile(active)
        if prof is not None:
            current = set(prof.public_wall_excluded_cards or [])
            key = card_key(run_id, card_id)
            if key not in current:
                current.add(key)
                prof.public_wall_excluded_cards = sorted(current)
                W.save_profile(prof)
    except Exception:
        W.log.warning("correction: wall exclusion failed", exc_info=True)
    checklist = "".join(f"<li>{_h(item)}</li>" for item in TAKEDOWN_CHECKLIST)
    body = (
        '<section class="mh-hero" style="padding-top:var(--sp-7);'
        'padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Privacy &amp; data</span>'
        '<h1>Correction <em class="editorial">opened.</em></h1></section>'
        '<div class="card">'
        f"<p>Correction #{cid} recorded for card <code>{_h(card_id)}</code> "
        f"in run <code>{_h(run_id)}</code>. The card has been removed from the "
        "public wall.</p>"
        "<h2>Still to do (outside MediaHub)</h2>"
        f"<ul>{checklist}</ul>"
        f'<p><a class="btn secondary" href="{url_for("privacy_page")}">'
        "&larr; Back to privacy</a></p></div>"
    )
    return W._layout("Correction opened", body, active="privacy")


def privacy_correction_resolve(correction_id: int):
    active = W._active_profile_id() or ""
    if active:
        from mediahub.privacy import resolve_correction

        resolve_correction(
            profile_id=active,
            correction_id=correction_id,
            resolution=(request.form.get("resolution") or "").strip(),
        )
    return redirect(url_for("privacy_page"))


def health():
    import time as _time

    started = _time.monotonic()
    payload = W._health_payload()
    # Surface the deep health result into the heartbeat log so /status
    # can count real failures, not just "did the request answer".
    first_error: Optional[str] = None
    if not payload["ok"]:
        for name, check in (payload.get("checks") or {}).items():
            if not check.get("ok"):
                first_error = f"{name}: {check.get('error', 'failed')}"
                break
    W._record_heartbeat_safe("health", payload["ok"], started, error=first_error)
    status_code = 200 if payload["ok"] else 503
    resp = jsonify(payload)
    resp.status_code = status_code
    return resp


def favicon():
    # Browsers auto-request /favicon.ico on every first page load.
    # Without a handler that produced a 404 on every cold visit
    # (and a generic browser-tab icon). Serve the MediaHub podium
    # mark as SVG; modern browsers render SVG favicons and the
    # .ico alias keeps legacy auto-requests quiet.
    return current_app.response_class(
        W._FAVICON_SVG,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def app_icon(size):
    # Only the two manifest sizes are rendered; anything else snaps to 192.
    if size not in (192, 512):
        size = 192
    return current_app.response_class(
        W._app_icon_png(size),
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def web_manifest():
    """PWA manifest — lets MediaHub be installed to a phone home screen so a
    volunteer can approve content on the go (start_url/scope resolve through
    any deployed prefix)."""
    manifest = {
        "name": "MediaHub",
        "short_name": "MediaHub",
        "description": "Turn meet results into ready-to-post content.",
        "start_url": url_for("home"),
        "scope": url_for("home"),
        "display": "standalone",
        "orientation": "portrait-primary",
        "theme_color": "#0A0B11",
        "background_color": "#0A0B11",
        "icons": [
            {
                "src": url_for("favicon"),
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            },
            # Raster home-screen icons (roadmap 1.22) — a real maskable PNG
            # installs cleanly where an SVG icon doesn't.
            {
                "src": url_for("app_icon", size=192),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": url_for("app_icon", size=512),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        # Web Share Target (roadmap 1.22) — registers MediaHub in the phone's
        # OS share sheet so a poolside volunteer can share a camera-roll photo
        # straight into the org's media library. The browser POSTs a multipart
        # navigation to /share-target with the image(s) under the "photos"
        # field declared here.
        "share_target": {
            "action": url_for("share_target_receiver"),
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {
                "title": "title",
                "text": "text",
                "url": "url",
                "files": [
                    {"name": "photos", "accept": ["image/*"]},
                ],
            },
        },
    }
    return current_app.response_class(json.dumps(manifest), mimetype="application/manifest+json")


# Installable-PWA service worker. Network-first so the app is always fresh
# online; falls back to cache (then a tiny offline page) only when the
# network is unavailable — so a stale cache can never be served to an online
# user. Only same-origin /static/ assets are opportunistically cached.
#
# Offline-tolerant approval queue (roadmap 1.22): POSTs to /api/workflow/
# (approve / reject / caption-edit — the actions a volunteer takes on the
# bus) are intercepted. Online they pass straight through; offline they are
# persisted to IndexedDB and a Background Sync is registered, then replayed
# when the connection returns. The workflow API is idempotent (re-approving
# is a no-op), so a replay never double-applies. It is NOT, however, always
# a success: a consent/brand/task gate can refuse an approval (403) and the
# group-approver rule can hold it as a vote (200 status:'queue'). D-4:
# drainQueue inspects each replay's body and reports those outcomes to the
# client instead of silently dropping them and claiming "All changes synced".
def service_worker():
    """Serve the service worker from the app root so it can control the whole
    scope (via Service-Worker-Allowed)."""
    resp = current_app.response_class(W._SERVICE_WORKER_JS, mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = url_for("home")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def static_fonts_css():
    return current_app.send_static_file("theme/fonts.css")


def static_motion_vocabulary_css():
    # The compiled brand motion vocabulary (roadmap 1.5): a @keyframes block
    # per preset, generated from src/mediahub/motion/ by
    # scripts/regen_motion_tokens.py. Reduce-motion variants are folded in via
    # @media (prefers-reduced-motion: reduce).
    return current_app.send_static_file("theme/motion-vocabulary.css")


def healthz():
    # Cheap liveness probe (no disk/db work). We still record a
    # heartbeat row so external monitors and Render's own platform
    # probe contribute to /status's uptime number.
    import time as _time

    started = _time.monotonic()
    payload = {"ok": True, "version": W.APP_VERSION, "ts": datetime.now(timezone.utc).isoformat()}
    W._record_heartbeat_safe("healthz", True, started)
    return jsonify(payload)


def healthz_ping():
    payload = {"pong": True}
    return jsonify(payload)


def healthz_memory():
    """Report process memory usage + in-memory state size.

    Added Phase 1.5 as a diagnostic for the "gunicorn restarts
    every 6 minutes" pattern. If `rss_mb` climbs steadily across
    repeated polls, the process is leaking and Render's 2 GB
    Standard ceiling (shared across two gunicorn workers) will
    eventually OOM-kill it. If `rss_mb` is stable and restarts
    still happen, the cause is somewhere else (auto-redeploy,
    platform action, etc.) and the user can stop blaming the app.
    """
    import resource

    # Peak (high-water) RSS from ru_maxrss. On Linux it's in KB; on macOS
    # it's bytes. Render is always Linux so KB is correct.
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    # CURRENT RSS is what actually spots a leak — ru_maxrss is a lifetime
    # high-water mark that never falls, so freed memory would be invisible
    # and a one-off spike would read as a permanent leak. Read VmRSS (and
    # VmHWM, the peak, from the SAME snapshot so peak >= current holds) from
    # /proc/self/status (Linux/Render); fall back to ru_maxrss where /proc
    # is absent (e.g. a macOS dev box).
    rss_mb = peak_mb
    try:
        with open("/proc/self/status", encoding="utf-8") as _st:
            for _line in _st:
                if _line.startswith("VmRSS:"):
                    rss_mb = int(_line.split()[1]) / 1024.0  # KB → MB
                elif _line.startswith("VmHWM:"):
                    peak_mb = int(_line.split()[1]) / 1024.0  # KB → MB
    except OSError:
        pass
    with W._active_lock:
        active_n = len(W._active_runs)
        active_running = sum(1 for v in W._active_runs.values() if v.get("status") == "running")
        ti_n = len(W._turn_into_jobs)
    payload = {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}
    # RSS, the OOM-ceiling ratio and the in-memory concurrency limits map the
    # deployment's resource envelope — useful to the operator diagnosing a
    # restart loop, but reconnaissance for anyone else. Uptime monitors only
    # need the liveness boolean; the internals are signed-in-operator only,
    # mirroring /healthz/deps and /healthz/sentinel. (The `_active_runs`
    # walk above still runs for every caller, so its crash-safety is
    # exercised regardless of who is looking.)
    if W._auth.is_dev_operator():
        payload.update(
            {
                "rss_mb": round(rss_mb, 1),
                "rss_peak_mb": round(peak_mb, 1),
                "rss_pct_of_2048": round((rss_mb / 2048.0) * 100.0, 1),
                "active_runs": active_n,
                "active_runs_running": active_running,
                "active_runs_limit": W._ACTIVE_RUNS_LIMIT,
                "turn_into_jobs": ti_n,
                "turn_into_jobs_limit": W._TURN_INTO_LIMIT,
            }
        )
    return jsonify(payload)


def healthz_deps():
    """Report whether image / motion rendering dependencies are available.

    Exposed at /healthz/deps (and read by /api/settings/llm-status
    for the captions-tab status dot) so operators can tell at a
    glance whether "Create graphic" and "Generate motion" buttons will
    succeed in the current deployment. Silent failures of these in
    production were the root of "images and videos aren't generating".
    """
    import shutil
    import subprocess

    deps: dict[str, dict] = {}
    # Playwright + chromium browser.
    #
    # We deliberately avoid sync_playwright() here: just to read
    # p.chromium.executable_path it spawns the Playwright Node
    # driver subprocess and tears it down via the asyncio loop,
    # which is ~350ms of pure overhead on every probe. Operators
    # poll this endpoint, so that adds up. Probe the installed
    # browser by checking the cache directory directly instead.
    try:
        import playwright  # noqa: F401

        browser_path = ""
        chromium_ok = False
        pw_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
            Path.home() / ".cache" / "ms-playwright"
        )
        try:
            root = Path(pw_root)
            # Each Playwright version installs Chromium into
            # ``chromium-<build>/chrome-linux/chrome`` (or chrome.exe
            # on Windows). Take the newest matching build so a
            # stale older install doesn't shadow the current one.
            candidates = sorted(root.glob("chromium*/chrome-linux/chrome"))
            if not candidates:
                candidates = sorted(root.glob("chromium*/chrome-*/chrome*"))
            if candidates:
                browser_path = str(candidates[-1])
                chromium_ok = Path(browser_path).exists()
        except Exception:
            pass
        deps["playwright"] = {
            "available": True,
            "chromium": chromium_ok,
            "executable": browser_path,
        }
    except Exception as e:
        deps["playwright"] = {"available": False, "error": str(e)[:200]}
    # Node binary
    node_path = shutil.which("node")
    if node_path:
        try:
            v = subprocess.run([node_path, "--version"], capture_output=True, text=True, timeout=5)
            deps["node"] = {
                "available": True,
                "path": node_path,
                "version": (v.stdout or "").strip(),
            }
        except Exception as e:
            deps["node"] = {"available": True, "path": node_path, "error": str(e)[:200]}
    else:
        deps["node"] = {"available": False}
    # Remotion node_modules
    remotion_dir = Path(__file__).resolve().parents[1] / "remotion"
    node_modules = remotion_dir / "node_modules" / "remotion"
    deps["remotion"] = {
        "available": node_modules.exists(),
        "dir": str(remotion_dir),
    }
    # Reel-engine selection seam (P0.1).
    try:
        from mediahub.visual.reel_engine import reel_engine_status

        deps["reel_engine"] = reel_engine_status()
    except Exception as _re_err:
        deps["reel_engine"] = {"error": str(_re_err)[:200]}
    # TTS provider slot (P0.4) — informational; voiceover is opt-in.
    try:
        from mediahub.visual.voiceover import tts_provider_status

        deps["tts_provider"] = tts_provider_status()
    except Exception as _tts_err:
        deps["tts_provider"] = {"error": str(_tts_err)[:200]}
    # ASR provider slot (P0.4 / roadmap 1.4) — informational; server
    # transcription is opt-in (the live copilot voice path is the browser's
    # on-device speech capture).
    try:
        from mediahub.visual.transcribe import asr_provider_status

        deps["asr_provider"] = asr_provider_status()
    except Exception as _asr_err:
        deps["asr_provider"] = {"error": str(_asr_err)[:200]}
    # Video suite (roadmap 1.6) — footage render engine + the flagged
    # matting/avatar provider slots (both off by default, honest about it).
    try:
        from mediahub.video.render import available as _video_render_available

        deps["video_engine"] = {"available": bool(_video_render_available())}
        from mediahub.video.matting import matting_status

        deps["video_matting"] = matting_status()
        from mediahub.video.avatars import avatar_status

        deps["video_avatars"] = avatar_status()
    except Exception as _vid_err:
        deps["video_engine"] = {"error": str(_vid_err)[:200]}
    # Motion is healthy when the *active* reel engine can render:
    # remotion needs node + node_modules; the ffmpeg fallback (P0.1)
    # makes both optional.
    _motion_ok = deps["node"].get("available") and deps["remotion"].get("available")
    _re_status = deps.get("reel_engine") or {}
    if _re_status.get("active") == "ffmpeg":
        _motion_ok = bool(_re_status.get("ffmpeg_available"))
    ok = deps["playwright"].get("chromium") and _motion_ok
    payload = {"ok": bool(ok), "deps": deps}
    # Absolute filesystem paths (the Chromium executable, the node binary and
    # the Remotion install dir) disclose the deployment's internal layout, so
    # they are operator-only. This endpoint stays public for uptime monitors —
    # they still get every availability boolean and version they need — but an
    # anonymous caller no longer learns where anything lives on disk. Mirrors
    # /healthz/sentinel, which likewise hands its raw audit tail to the
    # signed-in operator alone.
    if not W._auth.is_dev_operator():
        for _dep_key, _path_field in (
            ("playwright", "executable"),
            ("node", "path"),
            ("remotion", "dir"),
        ):
            section = deps.get(_dep_key)
            if isinstance(section, dict):
                section.pop(_path_field, None)
    return jsonify(payload)


def status_page():
    # Public view: just "Website operational" / "Website down". The detailed
    # uptime/incident/version breakdown is operator-only (also reachable at
    # Settings → Developer for a signed-in operator).
    if not W._auth.is_dev_operator():
        body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-6);margin-bottom:var(--sp-4)">'
            '<span class="mh-hero-eyebrow">Status</span>'
            '<h1>Service <em class="editorial">status</em></h1></section>'
            + W._render_settings_status_public_section()
        )
        resp = make_response(W._layout("Status", body, active="status"))
        resp.headers["Refresh"] = "60"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    from mediahub.observability import uptime as _uptime

    # Pull three windows so the page reads "24h / 7d / 30d uptime"
    # straight off the database, with no aggregation in the view. The
    # uptime store is exception-safe by contract, but defend the operator
    # page the same way _render_settings_status_section already does — an
    # unexpected observability error degrades to the honest public view,
    # never an unhandled 500.
    try:
        s24 = _uptime.uptime_stats(window_hours=24)
        s7d = _uptime.uptime_stats(window_hours=24 * 7)
        s30 = _uptime.uptime_stats(window_hours=24 * 30)
        latest = _uptime.latest_heartbeat()
        gaps = _uptime.recent_gaps(window_hours=24 * 30, limit=5)
    except Exception:
        body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-6);margin-bottom:var(--sp-4)">'
            '<span class="mh-hero-eyebrow">Status</span>'
            '<h1>Service <em class="editorial">status</em></h1></section>'
            + W._render_settings_status_public_section()
        )
        resp = make_response(W._layout("Status", body, active="status"))
        resp.headers["Refresh"] = "60"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # Current pill — green if last heartbeat < 5 min ago AND ok.
    pill_class = "muted"
    pill_label = "no data yet"
    pill_color = "#7a7a7a"
    if latest is not None:
        try:
            ts_raw = latest["ts"]
            if ts_raw.endswith("Z"):
                ts_raw = ts_raw[:-1] + "+00:00"
            from datetime import datetime as _dt

            last_ts = _dt.fromisoformat(ts_raw)
            age_s = (datetime.now(timezone.utc) - last_ts).total_seconds()
        except (ValueError, TypeError):
            age_s = 99999
        if not latest.get("ok"):
            pill_label = "degraded"
            pill_color = "#ffaa3a"
        elif age_s <= 300:
            pill_label = "operational"
            pill_color = "#2cc97f"
        elif age_s <= 1800:
            pill_label = "stale (no heartbeat in 5–30 min)"
            pill_color = "#ffaa3a"
        else:
            pill_label = "unknown (last heartbeat > 30 min ago)"
            pill_color = "#ff5d6c"

    # Most recent gap → "Last incident" callout.
    last_incident_html = (
        '<p class="dim" style="margin:0">No incidents recorded in the last 30 days.</p>'
    )
    if gaps:
        top = gaps[0]
        duration = W._humanize_duration(top["duration_seconds"])
        when = W._humanize_when(top["to_ts"])
        last_incident_html = (
            f'<p style="margin:0"><b>Last incident:</b> {_h(when)} '
            f"(silent for {_h(duration)})</p>"
            f'<p class="dim" style="margin:4px 0 0;font-size:12px">'
            f"Detected from a gap in heartbeats between "
            f"{_h(top['from_ts'][:19])} and {_h(top['to_ts'][:19])} UTC.</p>"
        )

    # Build a compact incident table so operators can see the
    # five longest gaps without a separate /status/incidents page.
    if gaps:
        gap_rows = ""
        for g in gaps:
            gap_rows += (
                f'<tr><td class="muted" style="font-size:12px">'
                f"{_h(g['to_ts'][:19])} UTC</td>"
                f"<td>{_h(W._humanize_duration(g['duration_seconds']))}</td>"
                f'<td class="muted" style="font-size:12px">'
                f"gap started {_h(g['from_ts'][:19])} UTC</td></tr>"
            )
        incidents_html = (
            '<h2 style="margin-top:28px;margin-bottom:6px;font-size:18px">'
            "Recent incidents</h2>"
            '<p class="dim" style="margin-bottom:14px;font-size:13px">'
            "Gaps longer than 5 minutes between heartbeats. The 5-minute "
            "grace window matches the platform ping cadence.</p>"
            '<div class="card"><table>'
            "<thead><tr><th>Resolved</th><th>Duration</th><th>Window</th></tr></thead>"
            f"<tbody>{gap_rows}</tbody></table></div>"
        )
    else:
        incidents_html = ""

    # Pull APP_VERSION from the closure scope.
    version_label = W.APP_VERSION

    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">System status</span>'
        '<h1>Live <em class="editorial">health</em>.</h1>'
        '<p class="lede">Operational health of this MediaHub deployment. Auto-refreshes every 60 seconds.</p>'
        "</section>"
        '<div class="card" style="display:flex;align-items:center;gap:14px;'
        'padding:18px 22px;margin-bottom:20px">'
        f'<span style="display:inline-block;width:14px;height:14px;'
        f'border-radius:50%;background:{pill_color};flex:0 0 auto"></span>'
        f'<div style="flex:1"><div style="font-size:18px;font-weight:600">'
        f"Backend &mdash; {_h(pill_label)}</div>"
        f'<div class="dim" style="font-size:13px;margin-top:2px">'
        f"Version <code>{_h(version_label)}</code>"
        + (
            f" &middot; last heartbeat {_h(W._humanize_when(latest['ts']))} "
            f"({_h((latest.get('source') or '').lower())})"
            if latest
            else ""
        )
        + "</div></div></div>"
        '<div class="card" style="padding:18px 22px;margin-bottom:20px">'
        '<table style="width:100%"><thead>'
        "<tr><th>Window</th><th>Uptime</th><th>Heartbeats</th>"
        "<th>Downtime</th></tr></thead><tbody>"
        f"<tr><td><b>24 hours</b></td>"
        f"<td>{W._format_uptime_pct(s24)}</td>"
        f"<td>{_h(s24.get('samples', 0))}</td>"
        f"<td>{_h(W._humanize_duration(s24.get('downtime_seconds', 0))) if s24.get('has_data') else '&mdash;'}</td></tr>"
        f"<tr><td><b>7 days</b></td>"
        f"<td>{W._format_uptime_pct(s7d)}</td>"
        f"<td>{_h(s7d.get('samples', 0))}</td>"
        f"<td>{_h(W._humanize_duration(s7d.get('downtime_seconds', 0))) if s7d.get('has_data') else '&mdash;'}</td></tr>"
        f"<tr><td><b>30 days</b></td>"
        f"<td>{W._format_uptime_pct(s30)}</td>"
        f"<td>{_h(s30.get('samples', 0))}</td>"
        f"<td>{_h(W._humanize_duration(s30.get('downtime_seconds', 0))) if s30.get('has_data') else '&mdash;'}</td></tr>"
        "</tbody></table>"
        f"{W._uptime_tracking_note(s24, s7d, s30)}</div>"
        f'<div class="card" style="padding:14px 22px;margin-bottom:20px">'
        f"{last_incident_html}</div>"
        f"{incidents_html}"
        '<p class="dim" style="margin-top:30px;font-size:12px">'
        "Uptime is derived from heartbeat density: each platform ping or "
        "health check inserts one row, and gaps over 5 minutes are counted "
        "as downtime. Raw data at "
        f'<a href="{url_for("api_status_json")}">/api/status</a>.</p>'
    )
    html = W._layout("Status", body, active="status")
    resp = make_response(html)
    # Auto-refresh: the page is intentionally a low-traffic informational
    # surface; refreshing every 60s keeps the number live without
    # JavaScript polling.
    resp.headers["Refresh"] = "60"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def healthz_breaker():
    """Expose the Gemini circuit-breaker state for one worker.

    Added 2026-05-19 after the user-facing symptom "regenerate
    keeps returning ai_directed=false even though Gemini usage
    shows mostly-OK calls" turned out to be (most likely) a
    tripped per-worker breaker on the worker handling this
    request. Gunicorn workers have independent in-process breaker
    state, so the operator may need to refresh this endpoint a
    few times to land on each worker. Anything in the snapshot
    with ``open: true`` means that worker is currently skipping
    Gemini for the listed cooldown period.

    The breaker counters and — especially — ``providers_configured``
    (which of the GEMINI/ANTHROPIC keys are set on this deployment) are
    operator diagnostics, not public information. Anonymous callers get
    the liveness boolean alone, mirroring /healthz/deps and
    /healthz/sentinel; the full snapshot is signed-in-operator only.
    """
    if not W._auth.is_dev_operator():
        return jsonify({"ok": True})
    try:
        # Breaker state lives in the shared Gemini transport (one copy
        # for both LLM wrappers — finding #43).
        from mediahub.ai_core.gemini_transport import (
            breaker_snapshot as gemini_breaker_snapshot,
        )

        snap = gemini_breaker_snapshot()
    except Exception as e:
        return jsonify({"error": f"breaker_unavailable: {e}"}), 500
    try:
        from mediahub.ai_core.llm import _key_for as _key

        providers_configured = {
            "gemini": bool(_key("gemini")),
            "claude": bool(_key("claude")),
        }
    except Exception:
        providers_configured = {}
    payload = {
        "ok": True,
        "gemini_breaker": snap,
        "providers_configured": providers_configured,
        "fallback_available": providers_configured.get("claude", False),
        "note": (
            "Per-worker state. If your deployment runs multiple "
            "gunicorn workers, refresh this endpoint to sample each "
            "worker. A high 'consecutive_failures' on a worker with "
            "'open': false means a few errors but no trip yet."
        ),
    }
    return jsonify(payload)


def healthz_search():
    """Report which web-search backend is live (SearXNG vs DuckDuckGo).

    Lets the operator confirm whether the in-container SearXNG actually
    started — if it's unreachable, MediaHub silently falls back to
    DuckDuckGo, and this endpoint says so.

    Which backend is live (and any endpoint detail in the probe) is a
    deployment internal, so it is signed-in-operator only. Anonymous
    monitors get the liveness boolean alone, mirroring /healthz/deps and
    /healthz/sentinel.
    """
    if not W._auth.is_dev_operator():
        return jsonify({"ok": True})
    try:
        from mediahub.web_research import searxng_client

        return jsonify({"ok": True, **searxng_client.health()})
    except Exception as e:
        return jsonify({"ok": False, "error": f"search_health_unavailable: {e}"}), 500


def healthz_sentinel():
    """Log-sentinel monitoring probe: last poll, findings, recent actions.

    Read-only snapshot of DATA_DIR/log_sentinel/status.json plus the audit
    tail, so the operator can see what the watchdog saw and did
    (docs/LOG_SENTINEL.md). Reports configured=False honestly when the
    Render API env vars aren't set.
    """
    try:
        from mediahub.log_sentinel import state as _sentinel_state

        payload = {
            "ok": True,
            "status": _sentinel_state.read_status(),
        }
        # The audit tail carries raw production log excerpts (tracebacks,
        # request paths/IPs) in its 'evidence' fields — operator-only.
        # Anonymous monitors get the status booleans/timestamps only, like
        # the sibling /healthz/* probes.
        if W._auth.is_dev_operator():
            payload["audit_tail"] = _sentinel_state.read_audit_tail(10)
        return jsonify(payload)
    except Exception as e:
        return jsonify({"ok": False, "error": f"sentinel_health_unavailable: {e}"}), 500


def healthz_governance():
    """Operator-only: per-org AI feature usage across the deployment (1.23)."""
    if not W._auth.is_dev_operator():
        return redirect(url_for("settings_page"))
    from mediahub.observability import feature_quota as _fq
    from mediahub.governance import features as _gf

    per_org = _fq.usage_all_orgs(limit=100)
    # Fold in generative-imagery usage (it keeps its own dedicated ledger).
    # Union, not intersect: an org whose ONLY AI usage is imagery has no
    # feature_uses rows, so it is absent from usage_all_orgs — it must still
    # appear here (imagery is the one feature with a real per-call cost).
    if W._imagine_ok:
        try:
            from mediahub.observability import imagine_usage as _iu

            by_org = {row["org_id"]: row for row in per_org}
            for org_id, n in _iu.counts_all_orgs().items():
                row = by_org.get(org_id)
                if row is None:
                    row = {"org_id": org_id, "total": 0, "by_feature": {}}
                    per_org.append(row)
                row["by_feature"]["imagine"] = n
                row["total"] += n
        except Exception:
            pass
    per_org.sort(key=lambda r: r["total"], reverse=True)

    feat_keys = _gf.feature_keys()
    head = "".join(f'<th style="text-align:right">{_h(_gf.label_for(k))}</th>' for k in feat_keys)
    rows = ""
    for r in per_org:
        cells = "".join(
            f'<td style="text-align:right">{int(r["by_feature"].get(k, 0))}</td>' for k in feat_keys
        )
        rows += (
            f"<tr><td>{_h(r['org_id'])}</td>{cells}"
            f'<td style="text-align:right"><strong>{int(r["total"])}</strong></td></tr>'
        )
    if not rows:
        rows = (
            f'<tr><td colspan="{len(feat_keys) + 2}" class="dim">'
            "No AI usage recorded in the last 30 days.</td></tr>"
        )
    body = (
        '<div class="card"><h1 style="margin-top:0">AI governance &mdash; usage</h1>'
        '<p class="dim">Per-org AI feature use over a rolling 30-day window '
        "(successful calls only). Operator-only.</p>"
        '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
        f'<thead><tr><th style="text-align:left">Org</th>{head}'
        '<th style="text-align:right">Total</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div></div>"
    )
    return W._layout("AI governance · usage", body, active="")


# Operator-facing LLM usage dashboard. Lives under /healthz/* (same
# trust boundary as /healthz/deps — an operations endpoint, not a
# user-facing surface) so it's reachable without going through the
# org-setup gate. Single-instance operators see their own usage;
# there is no tenant aggregation because each MediaHub deployment
# belongs to one operator.
#
# Surfaces:
#   1. Today's LLM call count, broken down by provider.
#   2. Rough USD cost estimate from public list pricing.
#   3. Gemini free-tier headroom (1,500 req/day ceiling).
#   4. Most recent LLM error message (so the operator can diagnose
#      a quietly-failing provider without grepping logs).
#   5. 7-day posting-log roll-up.
def healthz_usage():
    """Operator-only: LLM call counts, token totals, cost estimates,
    free-tier headroom and the last raw provider error. Same gate as its
    sibling /healthz/governance — the org-gate exemption above only lets it
    past the org-setup wall, it is NOT an authentication."""
    if not W._auth.is_dev_operator():
        return redirect(url_for("settings_page"))
    from mediahub.observability import llm_usage as _u

    today = _u.usage_for_window(window_hours=24)
    seven_d = _u.usage_for_window(window_hours=24 * 7)
    thirty_d = _u.daily_usage(days=30)
    last_err = _u.last_error()

    # Per-provider rows for the "Today" card.
    if today["by_provider"]:
        prov_rows = ""
        for b in today["by_provider"]:
            cost_disp = f"${b['est_cost_usd']:.4f}"
            if b["provider"] == "gemini" and b["est_cost_usd"] == 0:
                cost_disp = "$0.00 (free tier)"
            prov_rows += (
                f"<tr><td><b>{_h(b['provider'])}</b></td>"
                f"<td>{_h(b['calls'])}</td>"
                f"<td>{_h(b['ok'])}</td>"
                f"<td>{_h(b['failed'])}</td>"
                f"<td>{_h(b.get('tokens_in', 0))}</td>"
                f"<td>{_h(b.get('tokens_out', 0))}</td>"
                f"<td>{_h(cost_disp)}</td></tr>"
            )
        providers_html = (
            '<div class="card"><table style="width:100%">'
            "<thead><tr><th>Provider</th><th>Calls</th><th>OK</th>"
            "<th>Failed</th><th>Tokens in</th><th>Tokens out</th>"
            "<th>Est. cost</th></tr></thead>"
            f"<tbody>{prov_rows}</tbody></table></div>"
        )
    else:
        providers_html = '<div class="card empty">No LLM calls in the last 24 hours.</div>'

    # Gemini free-tier headroom callout.
    if today["gemini_free_tier_headroom"] is not None:
        from mediahub.observability.llm_usage import GEMINI_FREE_TIER_DAILY_REQ

        headroom = today["gemini_free_tier_headroom"]
        used = GEMINI_FREE_TIER_DAILY_REQ - headroom
        pct = (used / GEMINI_FREE_TIER_DAILY_REQ) * 100.0 if GEMINI_FREE_TIER_DAILY_REQ else 0
        bar_color = "#2cc97f"
        if pct > 80:
            bar_color = "#ffaa3a"
        if pct >= 100:
            bar_color = "#ff5d6c"
        headroom_html = (
            '<div class="card" style="padding:16px 22px;margin-bottom:18px">'
            '<div style="display:flex;justify-content:space-between;'
            'align-items:baseline;margin-bottom:6px">'
            f"<div><b>Gemini free-tier today</b> &mdash; "
            f"{_h(used)} / {GEMINI_FREE_TIER_DAILY_REQ} calls</div>"
            f'<div class="dim" style="font-size:12px">{_h(headroom)} remaining</div>'
            "</div>"
            '<div style="height:10px;background:rgba(255,255,255,0.08);'
            'border-radius:6px;overflow:hidden">'
            f'<div style="height:100%;width:{min(pct, 100):.1f}%;'
            f'background:{bar_color}"></div></div>'
            "</div>"
        )
    else:
        headroom_html = ""

    # Most recent LLM error (if any) — surfaced front and centre.
    if last_err:
        err_html = (
            '<div class="card" style="padding:16px 22px;margin-bottom:18px;'
            'border-left:3px solid var(--mh-prim-error-500)">'
            f'<div style="font-weight:600;margin-bottom:4px">'
            f"Last LLM error &mdash; {_h(last_err.get('provider', 'unknown'))}</div>"
            f'<div class="dim" style="font-size:12px;margin-bottom:6px">'
            f"{_h((last_err.get('ts') or '')[:19])} UTC"
            + (f" &middot; {_h(last_err.get('error_kind'))}" if last_err.get("error_kind") else "")
            + "</div>"
            f'<code style="font-size:12px">'
            f"{_h((last_err.get('error_message') or '')[:300])}</code>"
            "</div>"
        )
    else:
        err_html = ""

    # 30-day daily breakdown.
    if thirty_d:
        day_rows = ""
        for d in reversed(thirty_d):
            cost = f"${d['est_cost_usd']:.4f}" if d["est_cost_usd"] else "$0.00"
            day_rows += (
                f'<tr><td class="muted" style="font-size:12px">{_h(d["date"])}</td>'
                f"<td>{_h(d['calls'])}</td>"
                f"<td>{_h(d['ok'])}</td>"
                f"<td>{_h(d['failed'])}</td>"
                f"<td>{_h(cost)}</td></tr>"
            )
        thirty_html = (
            '<h2 style="margin-top:30px;margin-bottom:6px;font-size:18px">'
            "Last 30 days</h2>"
            '<p class="dim" style="margin-bottom:14px;font-size:13px">'
            "Per-day LLM call counts. Estimated cost uses public list "
            "pricing &mdash; not a billing source of truth.</p>"
            '<div class="card"><table style="width:100%">'
            "<thead><tr><th>Date (UTC)</th><th>Calls</th><th>OK</th>"
            "<th>Failed</th><th>Est. cost</th></tr></thead>"
            f"<tbody>{day_rows}</tbody></table></div>"
        )
    else:
        thirty_html = ""

    # 7-day totals headline.
    seven_total = seven_d["total_calls"]
    seven_cost = seven_d["est_cost_usd_total"]
    body = (
        '<h1 style="margin-bottom:6px">Usage</h1>'
        '<p class="dim" style="margin-bottom:24px">Operator dashboard. '
        "LLM call counts, free-tier headroom, and recent provider errors "
        "for this MediaHub deployment.</p>"
        f"{err_html}"
        f"{headroom_html}"
        '<h2 style="margin-top:28px;margin-bottom:6px;font-size:18px">'
        "Today (last 24h)</h2>"
        '<p class="dim" style="margin-bottom:14px;font-size:13px">'
        f"{_h(today['total_calls'])} calls &middot; "
        f"<b>${today['est_cost_usd_total']:.4f}</b> estimated cost &middot; "
        f"{_h(today['failed_count'])} failed"
        "</p>"
        f"{providers_html}"
        '<h2 style="margin-top:28px;margin-bottom:6px;font-size:18px">'
        "Last 7 days</h2>"
        '<p class="dim" style="margin-bottom:14px;font-size:13px">'
        f"{_h(seven_total)} calls &middot; "
        f"<b>${seven_cost:.4f}</b> estimated cost.</p>"
        f"{thirty_html}"
        '<p class="dim" style="margin-top:30px;font-size:12px">'
        "Estimated cost is derived from published list pricing for each "
        "provider and is not a substitute for a real billing source. "
        "Gemini free tier (1,500 req/day on gemini-2.5-flash) is treated "
        "as $0; Anthropic input/output tokens use Sonnet midpoint rates.</p>"
    )
    return W._layout("Usage", body, active="usage")


def stub_weekend_preview():
    return W._render_stub(
        "WeekendPreviewStub",
        "stub_weekend_preview",
        "Event Preview",
        intro_ct="event_preview",
    )


def legal_accept_page():
    email = W._auth.current_user_email()
    if not email:
        return redirect(url_for("login_page"))
    nxt = W._safe_next(request.args.get("next"))
    action = url_for("legal_accept_post", next=nxt) if nxt else url_for("legal_accept_post")
    prior = W._legal.AcceptanceStore().latest(email, W._legal.DOC_TERMS)
    prior_line = (
        f"You last accepted version {_h(prior.version)} on {_h(prior.accepted_at)}."
        if prior
        else "Your account predates recorded acceptance, so we're asking once now."
    )
    body = (
        '<section class="mh-hero" style="padding-top:var(--sp-7);'
        'padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Legal</span>'
        '<h1>Updated <em class="editorial">terms</em>.</h1>'
        f'<p class="lede">The Terms of Service changed (version {W._legal.TERMS_VERSION}). '
        "Please review and accept to continue.</p></section>"
        '<div class="card">'
        f"<p>{prior_line}</p>"
        f'<p>Read the <a href="{url_for("terms_page")}" target="_blank" '
        'style="color:var(--accent)">current Terms of Service</a> and the '
        f'<a href="{url_for("privacy_page")}" target="_blank" '
        'style="color:var(--accent)">Privacy Notice</a>.</p>'
        f'<form method="post" action="{action}">'
        '<label style="display:flex;gap:10px;align-items:flex-start;'
        'font-size:13px;color:var(--ink-muted)">'
        '<input type="checkbox" name="accept_terms" value="1" required '
        'style="margin-top:3px" />'
        f"<span>I accept the Terms of Service (version {W._legal.TERMS_VERSION}).</span>"
        "</label>"
        '<button type="submit" class="btn" style="margin-top:16px">Accept and continue</button>'
        "</form>"
        f'<p class="muted" style="margin-top:14px">Don\'t agree? You can '
        f'<a href="{url_for("privacy_page")}">export your data</a> and '
        f'<a href="{url_for("logout")}">sign out</a>.</p>'
        "</div>"
    )
    return W._layout("Accept updated terms", body, active="")


def legal_accept_post():
    email = W._auth.current_user_email()
    if not email:
        return redirect(url_for("login_page"))
    if (request.form.get("accept_terms") or "") != "1":
        return redirect(url_for("legal_accept_page"))
    W._legal.AcceptanceStore().record(email, W._legal.DOC_TERMS, W._legal.TERMS_VERSION)
    session["terms_ok_version"] = W._legal.TERMS_VERSION
    nxt = W._safe_next(request.args.get("next") or request.form.get("next"))
    return redirect(nxt or url_for("make_page"))


def developer_login():
    if W._auth.is_dev_operator():
        return redirect(url_for("make_page"))
    return W._developer_login_page()


def developer_login_post():
    if W._auth_rate_limited("developer"):
        return W._auth_rate_limit_response()
    if W._auth.verify_dev_credentials(
        request.form.get("dev_user"), request.form.get("dev_password")
    ):
        # Session rotation on privilege change (the same order as
        # login_post): read next from the request FIRST, drop everything
        # the pre-auth session held, then grant the operator identity —
        # the highest-privilege grant must not inherit pre-auth state.
        nxt = W._safe_next(request.args.get("next") or request.form.get("next"))
        session.clear()
        W._auth.login_dev_operator()
        return redirect(nxt or url_for("make_page"))
    return W._developer_login_page(error="Invalid username or password."), 401


def about_page():
    """The detailed, animated product walkthrough — "who we are and what we
    do", in depth.

    Public marketing page (exempt from the org-ready gate, like /pricing and
    the legal pages). The signed-out home is deliberately brief; this is
    where the depth lives — an animated step-by-step walk through the whole
    flow, then the shared product-story sections (input→output, the engine
    bento, who it's for, the human-in-the-loop promise, the pipeline diagram
    and the FAQ). Linked from the top bar's "About" item for signed-out
    visitors; the URL always resolves so a signed-in user can read it too.
    """
    hero_html = (
        '<section class="mh-hero" id="mh-ch-overview" data-lane="00">'
        '<span class="mh-hero-eyebrow">About MediaHub</span>'
        '<h1>The intelligence layer between<br>'
        '<em class="editorial">results</em> and ready-to-post.</h1>'
        '<p class="lede">MediaHub turns the structured data a club already '
        "produces &mdash; meet results, PDFs, spreadsheets &mdash; into "
        "on-brand content that&rsquo;s ready to post. It detects the moments "
        "that matter, ranks them by how content-worthy they are, dresses them "
        "in your colours and voice, and stops at a review queue you control. "
        "Nothing is invented, and nothing posts without you.</p>"
        '<div class="mh-hero-actions">'
        f'<a class="mh-cta-primary" href="{url_for("signup_page")}">Get started &rarr;</a>'
        f'<a class="mh-cta-secondary" href="{url_for("pricing_page")}">See pricing</a>'
        "</div>"
        "</section>"
    )
    # The looping generate → review → approve product demo, wrapped exactly
    # as the landing page wraps it (its non-chapter id keeps it out of the
    # scroll-spy rail).
    demo_section_html = (
        '<section class="mh-section mh-reveal" id="mh-see-it-work">'
        '<div class="mh-section-eyebrow-strip mh-reveal">'
        '<span class="label">See it work</span></div>'
        + W._reveal_lines(["One result in.", 'A post you <em class="editorial">approve</em>.'])
        + W._hero_product_demo()
        + "</section>"
    )
    final_cta_html = (
        '<section class="mh-final-cta mh-reveal" id="mh-ch-start">'
        "<div>"
        + W._reveal_lines(
            ["A minute to set up.", "<em>Then</em> every week is easier."],
            cls="mh-final-cta-headline",
        )
        + '<p class="mh-final-cta-sub mh-reveal">Tell us your club\'s name and '
        "website. We'll read your brand, palette and voice, and have on-brand "
        "drafts ready the next time you upload a results file.</p>"
        "</div>"
        '<div class="mh-final-cta-actions">'
        f'<a class="btn large" href="{url_for("signup_page")}">Create your organisation &rarr;</a>'
        f'<a class="btn secondary" href="{url_for("pricing_page")}">See plans &amp; pricing</a>'
        "</div>"
        "</section>"
    )
    # Rich scroll-spy rail: the animated walkthrough is the first chapter
    # after the overview, then the supporting explainer sections (each owns
    # its section id — mh-ch-how / -engine / -audience / -promise / -start).
    about_chapters = [
        ("mh-ch-overview", "Overview"),
        ("mh-ch-flow", "Step by step"),
        ("mh-ch-how", "How it works"),
        ("mh-ch-engine", "What it does"),
        ("mh-ch-audience", "Who it's for"),
        ("mh-ch-promise", "Our promise"),
        ("mh-ch-start", "Get started"),
    ]
    body = (
        W._ABOUT_CSS
        + '<div class="mh-about">'
        + '<div class="mh-fx mh-spotlight">'
        + hero_html
        + "</div>"
        + demo_section_html
        + W._home_io_headline_html()
        + W._about_walkthrough_html()
        + W._pipeline_diagram_section_html()
        + W._home_engine_bento_html()
        + W._home_audience_html()
        + W._home_promise_html()
        + W._home_faq_html()
        + final_cta_html
        + "</div>"
    )
    return W._layout("About", body, active="about", chapters=about_chapters)


def pricing_page():
    from mediahub.commercial.wtp import QuoteStore, public_list_price

    configured = W._billing.billing_configured()
    plan_now = W._auth.current_plan(W._user_store())
    signed_in = bool(W._auth.current_user_email())
    # PC.4 evidence gate (ADR-0011): a committed list price exists only
    # once ≥5 distinct clubs have paid annual at a tested price, and it is
    # the highest tested price that cleared — read from the quote ledger.
    try:
        list_price = public_list_price(QuoteStore().list_all())
    except Exception:
        list_price = None

    _CUR_SYMBOL = {"gbp": "&pound;", "usd": "$", "eur": "&euro;"}

    def _figure(symbol: str, pence: int) -> str:
        # Whole pounds when even, else two decimals. The pence is always
        # ledger-derived — never a hardcoded amount (ADR-0011 / PC.4).
        if pence % 100 == 0:
            return f"{symbol}{pence // 100}"
        return f"{symbol}{pence / 100:.2f}"

    def _price_block(plan: str) -> str:
        """Annual + monthly price panes for a tier.

        Honest billing-period toggle (UI 1.20): MediaHub sells annual
        prepay only (ADR-0011; wtp.Quote.billing_interval == "year"), so the
        "Monthly" view shows the *same committed annual price expressed per
        month* (annual ÷ 12), explicitly "billed annually" — never a
        fabricated monthly SKU or a made-up discount. While the PC.4 gate is
        unmet there is no committed figure, so both views read "Pricing TBC"
        and no "/year" or "/mo" suffix is emitted at all.
        """
        if plan == W._auth.PLAN_FREE:
            return '<div class="mh-price-fig">Free</div>'
        if plan == W._auth.PLAN_CLUB and list_price is not None:
            symbol = _CUR_SYMBOL.get(list_price["currency"], "")
            annual_pence = int(list_price["amount_pence"])
            monthly_pence = round(annual_pence / 12)
            annual = (
                '<span data-pane="annual">'
                f'<span class="mh-price-fig">{_figure(symbol, annual_pence)}'
                '<span class="mh-price-per">/year</span></span>'
                '<span class="mh-price-note">Billed annually</span></span>'
            )
            monthly = (
                '<span data-pane="monthly">'
                f'<span class="mh-price-fig">{_figure(symbol, monthly_pence)}'
                '<span class="mh-price-per">/mo</span></span>'
                '<span class="mh-price-note">billed annually</span></span>'
            )
            return annual + monthly
        # Federation (no committed list price) or Club before the gate: the
        # honest state is "Pricing TBC" — never a guessed number.
        purchasable = W._billing.plan_purchasable(plan)
        title = (
            "The exact price is shown at checkout"
            if purchasable
            else "Set STRIPE_PRICE_"
            + ("CLUB" if plan == W._auth.PLAN_CLUB else "FEDERATION")
            + " to enable"
        )
        return f'<div class="mh-price-tbc" title="{title}">Pricing TBC</div>'

    def _feature_li(row, plan: str) -> str:
        val = row.value_for(plan)
        if val is False:
            return (
                '<li class="mh-feat mh-feat-no">'
                '<span class="mh-feat-mark" aria-hidden="true">&times;</span>'
                f'<span class="mh-feat-label">{_h(row.label)}</span>'
                '<span class="mh-sr">— not included</span></li>'
            )
        value_html = f'<span class="mh-feat-val">{_h(val)}</span>' if isinstance(val, str) else ""
        return (
            '<li class="mh-feat mh-feat-yes">'
            '<span class="mh-feat-mark" aria-hidden="true">&check;</span>'
            f'<span class="mh-feat-label">{_h(row.label)}</span>'
            f'{value_html}<span class="mh-sr">— included</span></li>'
        )

    cards = ""
    for tier in W._billing.TIERS:
        is_current = tier.plan == plan_now and signed_in
        recommended = tier.plan == W._auth.PLAN_CLUB
        features = "".join(_feature_li(row, tier.plan) for row in W._billing.feature_rows())
        price_html = _price_block(tier.plan)

        # CTA — purchase/upgrade logic (unchanged from the prior page).
        if is_current:
            cta = (
                '<div class="btn secondary mh-cta" '
                'style="pointer-events:none;opacity:0.75">Current plan</div>'
            )
        elif tier.plan == W._auth.PLAN_FREE:
            cta = (
                f'<a class="btn secondary mh-cta" href="{url_for("signup_page")}">'
                "Get started free</a>"
                if not signed_in
                else '<div class="dim mh-cta-note">Included</div>'
            )
        else:
            if not W._billing.plan_purchasable(tier.plan):
                # J-15: a tier that can't be bought here (billing not
                # configured, or no price wired for it) gets a live route
                # to a human — never a dead "Not yet available" pill that
                # leaves a treasurer with nothing to click.
                cta = (
                    '<a class="btn secondary mh-cta" '
                    f'href="mailto:{W._legal.CONTACT_EMAIL}'
                    '?subject=MediaHub%20club%20pricing">'
                    "Talk to us about pricing</a>"
                )
            elif not signed_in:
                cta = (
                    f'<a class="btn mh-cta" '
                    f'href="{url_for("login_page", next=url_for("pricing_page"))}">'
                    "Log in to upgrade</a>"
                )
            else:
                # CCR 2013: route through the pre-contract information
                # page (/billing/confirm) before any payment step.
                cta = (
                    f'<a class="btn mh-cta" '
                    f'href="{url_for("billing_confirm", plan=tier.plan)}">'
                    f"Upgrade to {_h(tier.name)}</a>"
                )

        badge = '<div class="mh-tier-badge">Recommended</div>' if recommended else ""
        cls = "mh-tier" + (" is-recommended" if recommended else "")
        cards += (
            f'<div class="{cls}">{badge}'
            '<div class="mh-tier-head">'
            f'<div class="mh-tier-name">{_h(tier.name)}</div>'
            f'<div class="mh-tier-price">{price_html}</div>'
            f'<div class="mh-tier-blurb">{_h(tier.blurb)}</div>'
            "</div>"
            f'<ul class="mh-feat-list">{features}</ul>'
            f'<div class="mh-tier-cta">{cta}</div>'
            "</div>"
        )

    # Feature comparison table — same single-source matrix as the cards.
    def _cell(val) -> str:
        if val is True:
            return (
                '<span class="mh-cell-yes" aria-hidden="true">&check;</span>'
                '<span class="mh-sr">Included</span>'
            )
        if val is False:
            return (
                '<span class="mh-cell-no" aria-hidden="true">&times;</span>'
                '<span class="mh-sr">Not included</span>'
            )
        return f'<span class="mh-cell-val">{_h(val)}</span>'

    head_cells = ""
    for t in W._billing.TIERS:
        rec = " is-rec" if t.plan == W._auth.PLAN_CLUB else ""
        tag = '<span class="mh-th-rec">Recommended</span>' if t.plan == W._auth.PLAN_CLUB else ""
        head_cells += f'<th scope="col" class="mh-th-plan{rec}">{_h(t.name)}{tag}</th>'
    ncols = 1 + len(W._billing.TIERS)
    rows_html = ""
    for group in W._billing.FEATURE_MATRIX:
        rows_html += (
            f'<tr class="mh-compare-group"><th colspan="{ncols}" scope="colgroup">'
            f"{_h(group.title)}</th></tr>"
        )
        for row in group.rows:
            cells = ""
            for t in W._billing.TIERS:
                rec = " is-rec" if t.plan == W._auth.PLAN_CLUB else ""
                cells += f'<td class="{rec.strip()}">{_cell(row.value_for(t.plan))}</td>'
            rows_html += f'<tr><th scope="row">{_h(row.label)}</th>{cells}</tr>'
    compare_table = (
        '<div class="mh-compare-wrap"><table class="mh-compare">'
        f'<thead><tr><th scope="col"><span class="mh-sr">Feature</span></th>{head_cells}</tr></thead>'
        f"<tbody>{rows_html}</tbody></table></div>"
    )

    # Honest banner about where pricing stands (ADR-0011 / PC.4).
    if configured:
        note = "Paid plans are billed through Stripe. The exact price is shown during checkout."
    else:
        note = (
            "Billing is not configured on this deployment, so paid plans "
            "can&rsquo;t be purchased here &mdash; the Free tier is fully usable."
        )
    note_html = f'<p class="dim mh-price-note-banner">{note}</p>'

    # The Annually/Monthly segmented control only exists when a committed
    # list price is live (PC.4): with no price, no tier emits the
    # annual/monthly panes — every paid tier reads "Pricing TBC" — so the
    # toggle would render and visibly do nothing. The container keeps its
    # harmless data-period attribute either way.
    if list_price is not None:
        toggle = (
            '<div class="mh-billing-toggle">'
            '<div class="mh-segmented" role="group" aria-label="Billing period">'
            '<button type="button" class="is-active" data-period="annual" '
            'aria-pressed="true">Annually</button>'
            '<button type="button" data-period="monthly" '
            'aria-pressed="false">Monthly</button>'
            "</div></div>"
        )
        period_js = W._PRICING_JS
    else:
        toggle = ""
        period_js = ""

    body = (
        W._PRICING_CSS
        + '<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-6)">'
        '<span class="mh-hero-eyebrow">Pricing</span>'
        '<h1>Simple <em class="editorial">plans</em> for every club.</h1>'
        '<p class="lede">Start free. Upgrade when your club is posting in earnest. '
        "Simple annual pricing.</p>"
        "</section>"
        '<div id="mh-pricing" class="mh-pricing" data-period="annual">'
        f"{toggle}"
        f'<div class="mh-tier-grid">{cards}</div>'
        f"{note_html}"
        '<h2 class="mh-compare-title">Compare every plan</h2>'
        f"{compare_table}"
        "</div>" + period_js
    )
    return W._layout("Pricing", body, active="pricing")


def oembed():
    """oEmbed (read-only) for a club's public achievements wall (roadmap 1.21).

    Pass ``?url=<wall url>`` (a ``/wall/<token>`` page) and get oEmbed JSON
    whose ``html`` is the wall's embed iframe — so a CMS (WordPress, etc.) can
    auto-embed approved content. The unguessable wall token is the capability
    (the "signed" embed); an unknown or disabled wall returns 404. Only
    APPROVED cards are ever shown (enforced by the wall itself)."""
    raw = (request.args.get("url") or "").strip()
    fmt = (request.args.get("format") or "json").lower()
    if fmt != "json":
        # We offer JSON oEmbed only; XML is not implemented.
        return jsonify({"error": "unsupported_format", "message": "format must be json"}), 501
    m = re.search(r"/wall/([A-Za-z0-9_\-]+)", raw)
    if not m:
        abort(404)
    token = m.group(1)
    prof = W._resolve_wall_or_404(token)  # 404 if invalid / wall disabled

    def _clamp(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    width = _clamp("maxwidth", 600, 200, 1200)
    height = _clamp("maxheight", 800, 200, 2000)
    embed_url = url_for("public_wall_embed", token=token, _external=True)
    html = (
        f'<iframe src="{_h(embed_url)}" width="{width}" height="{height}" '
        'style="border:0;max-width:100%" loading="lazy" '
        'title="MediaHub achievements wall"></iframe>'
    )
    return jsonify(
        {
            "version": "1.0",
            "type": "rich",
            "provider_name": "MediaHub",
            "provider_url": request.host_url.rstrip("/"),
            "title": f"{prof.display_name} — achievements",
            "html": html,
            "width": width,
            "height": height,
            "cache_age": 300,
        }
    )


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule("/", endpoint="home", view_func=home)
    app.add_url_rule("/help", endpoint="help_page", view_func=help_page)
    app.add_url_rule(
        "/recognition/<run_id>", endpoint="recognition_page", view_func=recognition_page
    )
    app.add_url_rule(
        "/ground-truth/<run_id>",
        endpoint="ground_truth",
        view_func=ground_truth,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/developer/api", endpoint="api_docs_page", view_func=api_docs_page)
    app.add_url_rule("/privacy", endpoint="privacy_page", view_func=privacy_page)
    app.add_url_rule("/terms", endpoint="terms_page", view_func=terms_page)
    app.add_url_rule("/cookies", endpoint="cookies_page", view_func=cookies_page)
    app.add_url_rule("/dpa", endpoint="dpa_page", view_func=dpa_page)
    app.add_url_rule(
        "/privacy/run/<run_id>/delete",
        endpoint="privacy_delete_run",
        view_func=privacy_delete_run,
        methods=["POST"],
    )
    app.add_url_rule(
        "/privacy/runs/clear-all",
        endpoint="privacy_clear_all_runs",
        view_func=privacy_clear_all_runs,
        methods=["POST"],
    )
    app.add_url_rule(
        "/privacy/cache/clear",
        endpoint="privacy_cache_clear",
        view_func=privacy_cache_clear,
        methods=["POST"],
    )
    app.add_url_rule("/complaints", endpoint="complaints_form", view_func=complaints_form)
    app.add_url_rule(
        "/complaints", endpoint="complaints_submit", view_func=complaints_submit, methods=["POST"]
    )
    app.add_url_rule(
        "/legal/subprocessors", endpoint="legal_subprocessors", view_func=legal_subprocessors
    )
    app.add_url_rule(
        "/privacy/athlete/erase",
        endpoint="privacy_athlete_erase",
        view_func=privacy_athlete_erase,
        methods=["POST"],
    )
    app.add_url_rule(
        "/privacy/correction",
        endpoint="privacy_correction_open",
        view_func=privacy_correction_open,
        methods=["POST"],
    )
    app.add_url_rule(
        "/privacy/correction/<int:correction_id>/resolve",
        endpoint="privacy_correction_resolve",
        view_func=privacy_correction_resolve,
        methods=["POST"],
    )
    app.add_url_rule("/health", endpoint="health", view_func=health)
    app.add_url_rule("/favicon.svg", endpoint="favicon", view_func=favicon)
    app.add_url_rule("/favicon.ico", endpoint="favicon", view_func=favicon)
    app.add_url_rule("/icon-<int:size>.png", endpoint="app_icon", view_func=app_icon)
    app.add_url_rule("/manifest.webmanifest", endpoint="web_manifest", view_func=web_manifest)
    app.add_url_rule("/sw.js", endpoint="service_worker", view_func=service_worker)
    app.add_url_rule(
        "/static/theme/fonts.css", endpoint="static_fonts_css", view_func=static_fonts_css
    )
    app.add_url_rule(
        "/static/theme/motion-vocabulary.css",
        endpoint="static_motion_vocabulary_css",
        view_func=static_motion_vocabulary_css,
    )
    app.add_url_rule("/healthz", endpoint="healthz", view_func=healthz)
    app.add_url_rule("/healthz/ping", endpoint="healthz_ping", view_func=healthz_ping)
    app.add_url_rule("/healthz/memory", endpoint="healthz_memory", view_func=healthz_memory)
    app.add_url_rule("/healthz/deps", endpoint="healthz_deps", view_func=healthz_deps)
    app.add_url_rule("/status", endpoint="status_page", view_func=status_page)
    app.add_url_rule("/healthz/breaker", endpoint="healthz_breaker", view_func=healthz_breaker)
    app.add_url_rule("/healthz/search", endpoint="healthz_search", view_func=healthz_search)
    app.add_url_rule("/healthz/sentinel", endpoint="healthz_sentinel", view_func=healthz_sentinel)
    app.add_url_rule(
        "/healthz/governance", endpoint="healthz_governance", view_func=healthz_governance
    )
    app.add_url_rule("/healthz/usage", endpoint="healthz_usage", view_func=healthz_usage)
    app.add_url_rule(
        "/weekend-preview",
        endpoint="stub_weekend_preview",
        view_func=stub_weekend_preview,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/legal/accept", endpoint="legal_accept_page", view_func=legal_accept_page, methods=["GET"]
    )
    app.add_url_rule(
        "/legal/accept", endpoint="legal_accept_post", view_func=legal_accept_post, methods=["POST"]
    )
    app.add_url_rule(
        "/developer", endpoint="developer_login", view_func=developer_login, methods=["GET"]
    )
    app.add_url_rule(
        "/developer",
        endpoint="developer_login_post",
        view_func=developer_login_post,
        methods=["POST"],
    )
    app.add_url_rule("/about", endpoint="about_page", view_func=about_page, methods=["GET"])
    app.add_url_rule("/pricing", endpoint="pricing_page", view_func=pricing_page, methods=["GET"])
    app.add_url_rule("/oembed", endpoint="oembed", view_func=oembed)
