"""Create & share surfaces: make, packs, export/print/share, walls, data hub, studio pages.

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
import json
import os
import re
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
    session,
    url_for,
)

from mediahub.web import web as W


def mobile_parity_tool():
    # Operator-only: the audit crawls every in-app page in a hidden frame,
    # so it stays behind the developer-operator gate like the other
    # internal diagnostics.
    if not W._auth.is_dev_operator():
        abort(404)
    from mediahub.web.mobile_parity import build_mobile_parity_body

    # Auto-discover the auditable surface from the live URL map: GET pages
    # with no path parameters, minus machinery (api / webhooks / static /
    # downloads / auth round-trips / the tool itself). This keeps the audit
    # honest as routes come and go — nothing to hand-maintain.
    _SKIP_PREFIX = (
        "/api",
        "/webhooks",
        "/static",
        "/healthz",
        "/sw.js",
        "/robots",
        "/.well-known",
        "/tools/mobile-parity",
        "/logout",
        "/sign-out",
        "/auth",
        "/oauth",
        "/r/",
        "/embed/",
    )
    _SKIP_SUBSTR = (
        "download",
        "export",
        "raw",
        "render",
        "motion",
        "reel",
        "poster",
        "preview_image",
        "thumbnail",
        "favicon",
        "manifest",
        "feed.xml",
        # Mutation-ish GET endpoints the audit must not trigger by loading.
        "confirm",
        "claim",
        "delete",
        "checkout",
        "portal",
    )
    seen: set[str] = set()
    targets: list[dict] = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.arguments:
            continue
        methods = rule.methods or set()
        if "GET" not in methods:
            continue
        path = str(rule.rule)
        if any(path.startswith(p) for p in _SKIP_PREFIX):
            continue
        if any(s in rule.endpoint.lower() or s in path.lower() for s in _SKIP_SUBSTR):
            continue
        # /health is the deep dependency probe — it returns JSON, not an
        # HTML page, so it has no place in a UI parity sweep. (The client
        # audit also skips non-HTML responses defensively.)
        if path == "/health":
            continue
        if path in seen:
            continue
        seen.add(path)
        label = rule.endpoint.replace("_page", "").replace("_", " ").strip().title() or path
        targets.append({"label": label, "url": path, "group": ""})
    targets.sort(key=lambda t: (t["url"] != "/", t["label"]))

    body = build_mobile_parity_body(targets)
    return W._layout("Mobile parity audit", body, active="settings")


def research_page():
    # F-4 — a customer-facing "what can I upload?" page, not the old
    # parser/adapter research notes. Plain language for a club volunteer
    # deciding whether their meet file will work; the engine-internal
    # can_parse()/adapter detail lives on /developer/api instead.
    html = """
<h2>Files you can upload today</h2>
<ul>
  <li><strong>Hytek results (.hy3)</strong> &mdash; the file Meet Manager exports after
      a gala. This is the richest input: individual swims, splits and heats all come
      through.</li>
  <li><strong>SDIF timing exports (.sd3 / .cl2)</strong> &mdash; the sibling of the
      Hytek file, used by USA Swimming meets.</li>
  <li><strong>PDF result sheets</strong> &mdash; the printed-style results many meets
      publish. We read the tables and flag anything that looks unclear for your review.</li>
  <li><strong>Spreadsheets (.csv / .xls / .xlsx)</strong> &mdash; results exported from
      Meet Mobile, SwimTopia or a hand-kept sheet.</li>
  <li><strong>A results link</strong> &mdash; paste the web address of a public results
      page and we'll read it for you.</li>
</ul>
<h3>Coming soon</h3>
<ul>
  <li>Direct import from more meet-management and timing platforms.</li>
</ul>
<p class="muted">Not sure your file will work? Upload it anyway &mdash; MediaHub tells you
   straight away what it found and asks you to confirm anything it wasn't sure about.
   Nothing is published without your approval.</p>
"""
    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Getting started</span>'
        '<h1>What files can I <em class="editorial">upload</em>?</h1>'
        '<p class="lede">The result formats MediaHub reads today, and what\'s coming next — in plain English, no timing-software jargon required.</p>'
        "</section>"
        f'<div class="card">{html}</div>'
        '<div class="card"><p>Ready when you are — '
        f'<a class="btn" href="{url_for("upload")}">Upload your results</a></p></div>'
    )
    return W._layout("What files can I upload?", body, active="research")


def motion_vocabulary_gallery():
    """A reference gallery of the brand motion vocabulary (roadmap 1.5).

    An operator/dev surface that renders every preset through its *compiled
    CSS* — the same tokenised vocabulary the reels compile to Remotion and
    the ffmpeg engine compiles to filter recipes — grouped by family. The
    reduce-motion variants are honoured by the stylesheet, so toggling the
    OS "reduce motion" setting visibly calms the whole page.
    """
    from mediahub.motion import compile_css as _mcss
    from mediahub.motion import vocabulary as _mv

    css_url = url_for("static", filename="theme/motion-vocabulary.css")
    sections = []
    for family in _mv.FAMILIES:
        presets = _mv.by_family(family)
        cells = []
        for p in presets:
            cls = _mcss.class_name(p)
            cells.append(
                f'<figure class="mv-cell"><div class="mv-stage">'
                f'<div class="mv-chip {cls}"></div></div>'
                f"<figcaption><b>{_h(p.name)}</b>"
                f'<span class="mv-meta">{_h(p.energy)} · {_h(p.direction)}'
                f"{' · photo' if p.photo else ''}{' · loop' if p.loop else ''}</span>"
                f'<span class="mv-desc">{_h(p.description)}</span></figcaption></figure>'
            )
        sections.append(
            f"<section><h2>{_h(family)} "
            f'<span class="mv-count">{len(presets)}</span></h2>'
            f'<div class="mv-grid">{"".join(cells)}</div></section>'
        )
    body = "".join(sections)
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Motion vocabulary — MediaHub</title>"
        f'<link rel="stylesheet" href="{url_for("static", filename="theme/fonts.css", v=W._static_ver("theme/fonts.css"))}">'
        f'<link rel="stylesheet" href="{css_url}">'
        "<style>"
        ":root{--bg:#0A0B11;--panel:#14161F;--ink:#EaEcF2;--muted:#8A90A2;--accent:#C9A227;}"
        "*{box-sizing:border-box}"
        "body{margin:0;background:var(--bg);color:var(--ink);"
        "font-family:'Hanken Grotesk',system-ui,sans-serif;padding:28px 22px 60px}"
        "header{max-width:1100px;margin:0 auto 8px}"
        "h1{font-size:22px;margin:0 0 4px}"
        ".lede{color:var(--muted);max-width:640px;margin:0 0 4px;font-size:14px;line-height:1.5}"
        "section{max-width:1100px;margin:26px auto 0}"
        "h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;"
        "color:var(--accent);border-bottom:1px solid #222533;padding-bottom:6px}"
        ".mv-count{color:var(--muted);font-weight:400;margin-left:6px}"
        ".mv-grid{display:grid;gap:14px;"
        "grid-template-columns:repeat(auto-fill,minmax(150px,1fr));margin-top:14px}"
        ".mv-cell{margin:0;background:var(--panel);border:1px solid #222533;"
        "border-radius:10px;padding:12px;cursor:pointer}"
        ".mv-stage{height:64px;display:flex;align-items:center;justify-content:center;"
        "overflow:hidden;margin-bottom:10px}"
        ".mv-chip{width:46px;height:46px;border-radius:9px;"
        "background:linear-gradient(135deg,var(--accent),#7a6418)}"
        "figcaption b{font-size:13px}"
        ".mv-meta{display:block;color:var(--muted);font-size:11px;margin-top:2px}"
        ".mv-desc{display:block;color:#aeb4c4;font-size:11px;margin-top:5px;line-height:1.4}"
        "</style></head><body>"
        "<header><h1>Motion vocabulary</h1>"
        '<p class="lede">Every brand motion preset (roadmap 1.5), rendered '
        "from its compiled CSS. One source of truth in <code>motion/</code>; "
        "the reels compile the same tokens to Remotion and the ffmpeg engine "
        "to filter recipes. Click a tile to replay; turn on your device's "
        "<em>reduce motion</em> setting to see the calmer variants.</p></header>"
        f"{body}"
        "<script>document.addEventListener('click',function(e){"
        "var c=e.target.closest('.mv-cell');if(!c)return;"
        "var chip=c.querySelector('.mv-chip');if(!chip)return;"
        "var cls=chip.className;chip.className='mv-chip';"
        "void chip.offsetWidth;chip.className=cls;});</script>"
        "</body></html>"
    )
    return current_app.response_class(html, mimetype="text/html")


def template_gallery():
    # Browse-only gallery of the content archetypes the design director
    # draws from, shown *before* creating a pack. Renders existing data
    # only (the live archetype catalog + each archetype's authored notes)
    # with deterministic schematic previews + category filters — no new
    # API, no external service, and no way to force an archetype (the
    # engine still picks per moment). All logic lives in the Flask-free
    # ``template_gallery`` helper so it unit-tests without a request.
    from mediahub.web import template_gallery as _gallery

    active = _gallery.valid_category(request.args.get("category"))
    body = _gallery.render_gallery_body(
        gallery_url=url_for("template_gallery"),
        make_url=url_for("make_page"),
        active_category=active,
        studio_url=url_for("template_preview_gallery"),
    )
    return W._layout("Templates", body, active="templates")


def template_preview_gallery():
    from mediahub.web import template_preview_gallery as _studio

    state = _studio.normalise_state(request.args)

    def _thumb_url(archetype, pack_id, hero=False):
        url = url_for("template_preview_thumb", archetype=archetype, pack_id=pack_id)
        return url + "?hero=1" if hero else url

    body = _studio.render_studio_body(
        studio_url=url_for("template_preview_gallery"),
        gallery_url=url_for("template_gallery"),
        make_url=url_for("make_page"),
        thumb_url=_thumb_url,
        state=state,
    )
    return W._layout("Template previews", body, active="templates")


def template_preview_thumb(archetype: str, pack_id: str):
    from flask import Response, send_file

    from mediahub.web import template_preview_gallery as _studio

    # Coerce to known catalog members — junk can never render an unknown
    # layout, 500, or escape the cache dir (no path traversal).
    archetype = _studio.valid_archetype(archetype)
    pack_id = _studio.valid_pack(pack_id)
    size = (560, 700) if request.args.get("hero") == "1" else (384, 480)

    def _schematic_response():
        resp = Response(_studio.standalone_schematic_svg(archetype), mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp

    brand_kit, brand_sig = W._preview_brand_kit()
    w, h = size
    cache_path = (
        W.DATA_DIR / "template_previews" / brand_sig / f"{archetype}__{pack_id}__{w}x{h}.png"
    )
    if cache_path.exists() and cache_path.stat().st_size > 100:
        resp = send_file(str(cache_path), mimetype="image/png")
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    try:
        png_path = W._render_template_preview(archetype, pack_id, brand_kit, size, cache_path)
    except W._RenderBusy:
        return _schematic_response()
    except Exception:
        W.log.warning("template preview render failed for %s/%s", archetype, pack_id, exc_info=True)
        return _schematic_response()
    if not png_path or not Path(png_path).exists():
        return _schematic_response()
    resp = send_file(str(png_path), mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def design_studio():
    # The interactive design editor: tweak text layers, palette, archetype
    # and style pack and watch the card re-render live on the *real* engine
    # (creative_brief → graphic_renderer.render_brief), distinct from the
    # browse-only /templates gallery. All page logic lives in the Flask-free
    # ``design_editor`` helper so it unit-tests without a request; the route
    # only resolves url_for() links + the active org's palette and wraps the
    # body with _layout.
    from mediahub.web import design_editor as _studio

    # Seed the colour controls from the signed-in org's brand kit when
    # available; the helper re-validates every value, so a missing/odd
    # colour falls back to the neutral default.
    seed_palette = None
    try:
        _prof = W._active_profile()
        if _prof is not None:
            _bk = _prof.get_brand_kit()
            seed_palette = {
                "primary": getattr(_bk, "primary_colour", "") or "",
                "secondary": getattr(_bk, "secondary_colour", "") or "",
                "accent": getattr(_bk, "accent_colour", "") or "",
            }
    except Exception:
        seed_palette = None

    body = _studio.render_editor_body(
        render_url=url_for("api_studio_render"),
        gallery_url=url_for("template_gallery"),
        make_url=url_for("make_page"),
        palette=seed_palette,
    )
    # The studio is a sub-surface of Create (reached from the Create tile), so
    # it highlights the Create nav item — active="studio" matched no nav key and
    # left the top bar with nothing lit, orphaning the page in the IA.
    return W._layout("Studio", body, active="create")


def make_page():
    # The Create tab is the single chooser for starting work. Tiles
    # come from the ContentType REGISTRY — the canonical catalogue
    # of every content type the platform produces. /add-input is
    # preserved as a redirect alias so external links still resolve.
    try:
        from mediahub.club_platform.content_types import REGISTRY
    except ImportError:
        REGISTRY = {}

    # Presentation-only metadata (output formats + rough effort) lives in
    # mediahub.web.content_intro.PRESENTATION_FORMATS so the Create tiles and
    # each heading's "how it works" first slide read from one source. UI
    # sugar only — it does NOT live on the registry dataclass, so it can
    # never affect the engine. Unknown types fall back to a generic chip.

    # Session Update and Sponsor Post are no longer their own tiles —
    # Free Text now interprets any such prompt (and adds photos) into a
    # graphic, so a single "describe it" path covers them.
    #
    # Athlete Spotlight is no longer a standalone tile either: it lives
    # inside the meet-recap flow, reached from the Review ⇄ Athlete spotlight
    # view switch on a processed meet (it always needed a processed meet
    # anyway). The content type + its routes stay for the toggle, deep links
    # and back-compat; it's just not surfaced as a separate Create card.
    _hidden_cts = {"session_update", "sponsor_activation", "athlete_spotlight"}

    # B-1: once this organisation has met a heading's intro slide, its tile
    # links straight into the flow (nav → upload drops from 7 clicks to 4);
    # first-timers still get the explainer. Per-profile, persisted.
    _seen_intros = W._intro_seen_slugs(W._active_profile_id())

    # C-19 parity: the Create tiles are bunched into headed segments
    # (mirroring the Settings clusters) so related surfaces sit together
    # instead of one flat wall of cards. Each tile is filed into a group
    # bucket here and rendered under its heading below.
    tile_groups: dict[str, str] = {}
    # Which segment each REGISTRY content type belongs to; unknown types
    # default to the results-driven lane so a future content type still
    # lands somewhere sensible.
    _CT_GROUP = {"free_text": "studios"}
    # First implemented tile gets the "Start here" lane-yellow ribbon so
    # users have a clear primary path instead of six equal-weight options.
    primary_marked = False
    for ct, meta in REGISTRY.items():
        if getattr(meta.type, "value", str(ct)) in _hidden_cts:
            continue
        ct_val = getattr(meta.type, "value", str(ct))
        # Defensive: a stale endpoint name in the content-type registry must
        # NEVER 500 the whole /make page. We resolve the primary route only
        # to decide Ready-vs-disabled; the tile itself links to the per-type
        # "how it works" first slide (content_type_intro), whose Start button
        # carries on to the real route.
        try:
            url_for(meta.primary_route_endpoint)
            href_ok = True
        except Exception:
            W.log.warning(
                "make_page: content type %r references unknown endpoint %r — "
                "rendering as disabled tile",
                ct,
                meta.primary_route_endpoint,
            )
            href_ok = False
        if meta.is_implemented and href_ok:
            badge = '<span class="tag live">Ready</span>'
            # B-1: the intro is first-visit-only per organisation — once
            # seen, the tile opens the real flow directly. The "How it
            # works" pill (added on the tile below) keeps the explainer
            # reachable forever.
            if ct_val in _seen_intros:
                action = f'href="{url_for(meta.primary_route_endpoint)}"'
            else:
                action = f'href="{url_for("content_type_intro", ct=ct_val)}"'
            disabled_cls = ""
            if not primary_marked:
                disabled_cls = " mh-template-primary"
                primary_marked = True
        else:
            badge = '<span class="tag">Coming soon</span>'
            action = 'href="#" onclick="return false"'
            disabled_cls = " is-disabled"

        # Build the output-format chip row + effort estimate.
        formats, effort = W._ct_presentation_for(ct_val)
        fmt_chips = "".join(f'<span class="mh-template-fmt">{_h(fmt)}</span>' for fmt in formats)
        effort_html = f'<span class="mh-template-effort">{_h(effort)}</span>' if effort else ""
        # Pointer-following glow-border (::after — free on .mh-template and
        # .mh-template-primary) only on live tiles; never on a "Coming soon"
        # tile, where a glow would falsely imply it's clickable.
        glow_cls = " mh-glow-border" if (meta.is_implemented and href_ok) else ""

        # U.14 cursor-following preview — implemented tiles spawn a floating
        # "output frame" poster (orientation + canonical dimensions + format
        # chips) the static tile can't show. Honest: only real tile data,
        # clearly a stylised frame (same family as the home samples), no
        # fabricated content. Coming-soon tiles get no preview.
        _is_live = bool(meta.is_implemented and href_ok)
        hp_cls = " mh-hp" if _is_live else ""
        hp_tpl = ""
        if _is_live:
            _f_low = [f.lower() for f in formats]
            if "reel" in _f_low:
                _hp_eyebrow, _hp_dims = "Motion reel", "1080×1920"
            elif "story" in _f_low:
                _hp_eyebrow, _hp_dims = "Story card", "1080×1920"
            elif "graphic" in _f_low:
                _hp_eyebrow, _hp_dims = "Feed graphic", "1080×1350"
            else:
                _hp_eyebrow, _hp_dims = "Caption", "Ready to post"
            _hp_fmt_chips = "".join(
                f'<span class="mh-hp-poster-fmt">{_h(f)}</span>' for f in formats
            )
            hp_tpl = (
                '<template class="mh-hp-tpl"><div class="mh-hp-poster">'
                '<div class="mh-hp-poster-top">'
                f'<span class="mh-hp-poster-eyebrow">{_h(_hp_eyebrow)}</span>'
                f'<span class="mh-hp-poster-mark">{meta.icon_svg}</span>'
                "</div>"
                f'<div class="mh-hp-poster-title">{_h(meta.title)}</div>'
                f'<div class="mh-hp-poster-dims">{_h(_hp_dims)}</div>'
                f'<div class="mh-hp-poster-formats">{_hp_fmt_chips}</div>'
                "</div></template>"
            )

        # B-1: a tile is itself an <a>, so its always-available "How it
        # works" link is a positioned sibling in a relative wrapper (a
        # nested anchor would be invalid HTML). Live tiles only — a
        # coming-soon tile has no intro to reach.
        how_html = ""
        if _is_live:
            how_html = (
                f'<a class="mh-how-pill" href="{url_for("content_type_intro", ct=ct_val)}" '
                f'aria-label="How {_h(meta.title)} works">How it works</a>'
            )
        # Search scent: Free text now absorbs the folded content types
        # (sponsor thank-you, session update, shout-out — see _hidden_cts), but
        # its description never named them, so anyone scanning Create for those
        # words found nothing. A "Covers:" chip row restores that scent.
        covers_html = ""
        if ct_val == "free_text":
            covers_html = (
                '<p class="dim" style="font-size:11px;margin:2px 0 6px 0">'
                "Also covers: Sponsor thank-you &middot; Session update &middot; Shout-out"
                "</p>"
            )
        _ct_grp = _CT_GROUP.get(ct_val, "results")
        tile_groups[_ct_grp] = tile_groups.get(_ct_grp, "") + (
            '<div class="mh-template-cell">'
            f'<a {action} class="mh-template{glow_cls}{disabled_cls}{hp_cls}">'
            f'<div class="mh-template-icon">{meta.icon_svg}</div>'
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
            f'<h3 style="margin:0">{_h(meta.title)}</h3>'
            f"{badge}"
            "</div>"
            f"<p>{_h(meta.description)}</p>"
            f"{covers_html}"
            f'<div class="mh-template-formats">{fmt_chips}{effort_html}</div>'
            '<span class="mh-template-cta">Start</span>'
            f"{hp_tpl}"
            "</a>"
            f"{how_html}"
            "</div>"
        )

    # Design studio — a full, first-class Create tile, not the old slim
    # gallery-link strip. The live design editor (tweak text / palette /
    # archetype / style pack and watch the card re-render on the real
    # engine) is a function MediaHub offers in its own right, equal-billing
    # with the content types, so it earns a tile. Live/Ready, sitting after
    # the content types and ahead of the disabled coming-soon tiles.
    _studio_svg = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
        '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>'
        '<line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>'
        '<line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/>'
        '<line x1="17" y1="16" x2="23" y2="16"/></svg>'
    )
    tile_groups["studios"] = tile_groups.get("studios", "") + (
        f'<a href="{_h(url_for("design_studio"))}" class="mh-template mh-glow-border">'
        f'<div class="mh-template-icon">{_studio_svg}</div>'
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
        '<h3 style="margin:0">Design studio</h3>'
        '<span class="tag live">Ready</span>'
        "</div>"
        "<p>Tweak the text, palette, archetype and style pack and watch the "
        "card re-render live on the real engine &mdash; your starting point "
        "for a custom look.</p>"
        '<div class="mh-template-formats">'
        '<span class="mh-template-fmt">Live editor</span>'
        '<span class="mh-template-fmt">Graphic</span>'
        "</div>"
        '<span class="mh-template-cta">Open studio</span>'
        "</a>"
    )

    # Video studio — the footage→reel path, relocated here from the top bar
    # so every "what can I make?" surface lives on Create (it sits beside the
    # design studio tile above). A first-class Create tile: upload or record a
    # clip and Clip-Maker finds the moment, crops it upright, captions the
    # spoken words and brands it, with human approval before export. Gated on
    # the V8 media engine (_v8_ok) — the same flag that used to gate the
    # top-bar link — so it only shows where the studio actually works.
    if W._v8_ok:
        _video_svg = (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
            '<polygon points="23 7 16 12 23 17 23 7"/>'
            '<rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>'
        )
        tile_groups["studios"] = tile_groups.get("studios", "") + (
            f'<a href="{_h(url_for("video_studio_page"))}" class="mh-template mh-glow-border">'
            f'<div class="mh-template-icon">{_video_svg}</div>'
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
            '<h3 style="margin:0">Video studio</h3>'
            '<span class="tag live">Ready</span>'
            "</div>"
            "<p>Turn race footage into a branded reel &mdash; upload or record a "
            "clip and MediaHub finds the moment, crops it upright, captions the "
            "spoken words and brands it. You approve before anything is exported.</p>"
            '<div class="mh-template-formats">'
            '<span class="mh-template-fmt">Footage &rarr; reel</span>'
            '<span class="mh-template-fmt">Story</span>'
            '<span class="mh-template-fmt">Captions</span>'
            "</div>"
            '<span class="mh-template-cta">Open video studio</span>'
            "</a>"
        )

    # Documents — the 1.15 document engine (programmes / reports / proposals
    # / AGM decks + the PDF tools). A first-class Create tile beside the
    # studios; gated on _documents_ok so it only shows where it works.
    if W._documents_ok:
        _doc_svg = (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
            '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
            '<polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/>'
            '<line x1="8" y1="17" x2="16" y2="17"/><line x1="8" y1="9" x2="10" y2="9"/></svg>'
        )
        tile_groups["publish"] = tile_groups.get("publish", "") + (
            f'<a href="{_h(url_for("documents_home"))}" class="mh-template mh-glow-border">'
            f'<div class="mh-template-icon">{_doc_svg}</div>'
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
            '<h3 style="margin:0">Documents</h3>'
            '<span class="tag live">Ready</span>'
            "</div>"
            "<p>Build a meet programme, season report, sponsor proposal or AGM "
            "deck from your real results &mdash; then export to PDF, PowerPoint or "
            "Word, or present the deck with speaker notes.</p>"
            '<div class="mh-template-formats">'
            '<span class="mh-template-fmt">PDF</span>'
            '<span class="mh-template-fmt">PPTX / DOCX</span>'
            '<span class="mh-template-fmt">Present</span>'
            "</div>"
            '<span class="mh-template-cta">Open documents</span>'
            "</a>"
        )

    # Newsletters — the 1.17 email & newsletter composer. Email-safe branded
    # HTML auto-assembled from the period's approved content; export-first
    # (download / copy / hosted view). Gated on _email_design_ok.
    if W._email_design_ok:
        _nl_svg = (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
            '<rect x="3" y="5" width="18" height="14" rx="2"/>'
            '<path d="m3 7 9 6 9-6"/></svg>'
        )
        tile_groups["publish"] = tile_groups.get("publish", "") + (
            f'<a href="{_h(url_for("newsletters_home"))}" class="mh-template mh-glow-border">'
            f'<div class="mh-template-icon">{_nl_svg}</div>'
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
            '<h3 style="margin:0">Newsletters</h3>'
            '<span class="tag live">Ready</span>'
            "</div>"
            "<p>Turn a month (or a meet) of approved content into a branded, "
            "email-safe newsletter &mdash; results, spotlights, fixtures and your "
            "sponsor, with an AI intro in your club voice &mdash; then download the "
            "HTML for your list tool or publish a web version.</p>"
            '<div class="mh-template-formats">'
            '<span class="mh-template-fmt">Email HTML</span>'
            '<span class="mh-template-fmt">Copy / download</span>'
            '<span class="mh-template-fmt">Hosted view</span>'
            "</div>"
            '<span class="mh-template-cta">Open newsletters</span>'
            "</a>"
        )

    # C-8 — the public achievements wall is a flagship shareable output (free
    # public celebration page + embed + RSS/JSON), but its only link lived in
    # Organisation-settings prose. It gets a first-class Create tile alongside
    # Sites/Newsletters (independent of the email-design flag).
    _wall_svg = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
        '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
    )
    tile_groups["publish"] = tile_groups.get("publish", "") + (
        f'<a href="{_h(url_for("public_wall_settings"))}" class="mh-template mh-glow-border">'
        f'<div class="mh-template-icon">{_wall_svg}</div>'
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
        '<h3 style="margin:0">Public wall</h3>'
        '<span class="tag live">Ready</span>'
        "</div>"
        "<p>A free public celebration page of your approved cards &mdash; share the "
        "link, embed it on your club website, or offer an RSS/JSON feed. One "
        "shared URL you can publish and unpublish.</p>"
        '<div class="mh-template-formats">'
        '<span class="mh-template-fmt">Public page</span>'
        '<span class="mh-template-fmt">Website embed</span>'
        '<span class="mh-template-fmt">RSS / JSON</span>'
        "</div>"
        '<span class="mh-template-cta">Open public wall</span>'
        "</a>"
    )

    # Print & merch — a full press-ready pipeline (posters, flyers, banners,
    # certificates, merch mock-ups) that previously had NO Create tile and
    # was reachable only from a Help-page footer link. It belongs in the "what
    # can I make?" catalogue. Falls back to nothing if the route is absent.
    try:
        _print_url = url_for("print_center_page")
    except Exception:
        _print_url = ""
    if _print_url:
        _print_svg = (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
            '<polyline points="6 9 6 2 18 2 18 9"/>'
            '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
            '<rect x="6" y="14" width="12" height="8"/></svg>'
        )
        tile_groups["publish"] = tile_groups.get("publish", "") + (
            f'<a href="{_h(_print_url)}" class="mh-template mh-glow-border">'
            f'<div class="mh-template-icon">{_print_svg}</div>'
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
            '<h3 style="margin:0">Print &amp; merch</h3>'
            '<span class="tag good">Ready</span>'
            "</div>"
            "<p>Turn approved cards into press-ready posters, flyers, banners, "
            "certificates and merch mock-ups &mdash; MediaHub proofs the artwork "
            "and hands you print-ready files.</p>"
            '<div class="mh-template-formats">'
            '<span class="mh-template-fmt">Posters</span>'
            '<span class="mh-template-fmt">Certificates</span>'
            '<span class="mh-template-fmt">Merch</span>'
            "</div>"
            '<span class="mh-template-cta">Open Print &amp; merch</span>'
            "</a>"
        )

    # Live meet + Season wraps — fully-built surfaces presented as Create
    # tiles so the whole "what can I make?" catalogue lives in one place.
    # These used to render as disabled "Coming soon" tiles even though both
    # pages ship and work (C-5 / C-6): the UI contradicted reality and the
    # pages were reachable only by typing the URL. They now link straight
    # through, falling back to an honest disabled tile only if the route is
    # genuinely absent on a deployment.
    _live_svg = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
        '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49"/>'
        '<path d="M7.76 16.24a6 6 0 0 1 0-8.49"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>'
        '<path d="M4.93 19.07a10 10 0 0 1 0-14.14"/></svg>'
    )
    _wraps_svg = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
        '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/>'
        '<line x1="12" y1="22" x2="12" y2="7"/>'
        '<path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/>'
        '<path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></svg>'
    )
    for _cs_title, _cs_desc, _cs_icon, _cs_endpoint, _cs_cta in (
        (
            "Live meet",
            "Point MediaHub at the host club's live-results page during a gala; "
            "new results queue cards for approval as they land.",
            _live_svg,
            "live_meet_page",
            "Open Live meet",
        ),
        (
            "Season wraps",
            "Month-in-numbers and season recap packs built from your stored "
            "history — PBs, medals, records, debuts, busiest swimmer.",
            _wraps_svg,
            "season_wraps_page",
            "Open Season wraps",
        ),
    ):
        try:
            _cs_url = url_for(_cs_endpoint)
        except Exception:
            _cs_url = ""
        if _cs_url:
            tile_groups["results"] = tile_groups.get("results", "") + (
                f'<a href="{_cs_url}" class="mh-template">'
                f'<div class="mh-template-icon">{_cs_icon}</div>'
                '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
                f'<h3 style="margin:0">{_h(_cs_title)}</h3>'
                '<span class="tag good">Ready</span>'
                "</div>"
                f"<p>{_h(_cs_desc)}</p>"
                f'<span class="mh-template-cta">{_h(_cs_cta)}</span>'
                "</a>"
            )
        else:
            tile_groups["results"] = tile_groups.get("results", "") + (
                '<a href="#" onclick="return false" class="mh-template is-disabled" aria-disabled="true">'
                f'<div class="mh-template-icon">{_cs_icon}</div>'
                '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
                f'<h3 style="margin:0">{_h(_cs_title)}</h3>'
                '<span class="tag">Coming soon</span>'
                "</div>"
                f"<p>{_h(_cs_desc)}</p>"
                '<span class="mh-template-cta">Soon</span>'
                "</a>"
            )

    # Drafts — everything you generate (free text, spotlights, previews,
    # event packs) lands here. Promoted from the old top-right strip to a
    # first-class Create tile in its own segment, so returning users have
    # an obvious way back into saved work.
    _drafts_svg = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
        '<path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
        '<polyline points="13 2 13 9 20 9"/><line x1="9" y1="13" x2="15" y2="13"/>'
        '<line x1="9" y1="17" x2="13" y2="17"/></svg>'
    )
    try:
        _drafts_tile_url = url_for("stub_packs_list")
    except Exception:
        _drafts_tile_url = ""
    if _drafts_tile_url:
        tile_groups["drafts"] = tile_groups.get("drafts", "") + (
            f'<a href="{_h(_drafts_tile_url)}" class="mh-template mh-glow-border">'
            f'<div class="mh-template-icon">{_drafts_svg}</div>'
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:var(--sp-1)">'
            '<h3 style="margin:0">Drafts</h3>'
            '<span class="tag live">Ready</span>'
            "</div>"
            "<p>Every piece you generate &mdash; free text, spotlights, previews "
            "and event packs &mdash; is saved here so you can come back, edit, "
            "approve and export it later.</p>"
            '<div class="mh-template-formats">'
            '<span class="mh-template-fmt">Saved packs</span>'
            '<span class="mh-template-fmt">Edit &amp; approve</span>'
            "</div>"
            '<span class="mh-template-cta">Open drafts</span>'
            "</a>"
        )

    # Render the tiles as headed segments (C-19 parity with Settings): each
    # non-empty group becomes a labelled cluster of related tiles, in this
    # order. Reuses the Settings cluster + reveal classes so the two
    # surfaces read as one system.
    _MAKE_SEGMENTS = (
        ("results", "From your results"),
        ("studios", "Studios & free-form"),
        ("publish", "Documents & publishing"),
        ("drafts", "Your drafts"),
    )
    if any(tile_groups.get(k) for k, _ in _MAKE_SEGMENTS):
        tiles_section = ""
        for _seg_key, _seg_head in _MAKE_SEGMENTS:
            _seg_tiles = tile_groups.get(_seg_key, "")
            if not _seg_tiles:
                continue
            tiles_section += (
                f'<section class="mh-settings-cluster" aria-labelledby="mh-make-{_seg_key}">'
                f'<h2 class="mh-settings-cluster-head" id="mh-make-{_seg_key}">{_h(_seg_head)}</h2>'
                f'<div class="mh-template-grid">{_seg_tiles}</div>'
                "</section>"
            )
    else:
        tiles_section = (
            '<div class="card empty">'
            '<p class="muted">No content types are registered on this deployment. '
            "Check the deployment configuration.</p>"
            "</div>"
        )

    # The active organisation's profile drives the first-run nudge below.
    # (A "Brand in use" strip used to sit here; it was removed — the brand
    # is reviewed from Settings → Organisation & brand instead.)
    active_prof = W._active_profile()

    # U.4 — first-run nudge. A brand-new org (no completed runs yet) gets
    # the one-click sample path up top so the very first thing it can do is
    # see the whole engine run, rather than having to source a results file
    # before anything appears. Once the org has real runs the nudge retires.
    first_run_cta = ""
    if active_prof is not None:
        _has_done_run = False
        try:
            conn = W._db()
            row = conn.execute(
                "SELECT 1 FROM runs WHERE profile_id = ? AND status = 'done' LIMIT 1",
                (active_prof.profile_id,),
            ).fetchone()
            conn.close()
            _has_done_run = row is not None
        except Exception:
            _has_done_run = False
        if not _has_done_run:
            first_run_cta = W._sample_pack_cta(
                heading="New here? See it work in one click.",
                sub=(
                    "Generate a sample content pack from a demo meet and watch "
                    "detection, ranking, captions and branded cards happen end "
                    "to end — in your colours and voice. No file needed; it "
                    "lands in your review queue, and you can delete it after."
                ),
                button_label="Generate a sample pack →",
            )

    # Plan moved here from the top bar — it answers this page's own hero
    # question ("what should we make?"), so it sits at the TOP of Create as
    # the predominant, strategic entry point into the ranked, explainable
    # content plan. Like every tile it opens its own how-it-works first slide
    # (/make/plan); that slide's "Open Plan" CTA continues into the planner.
    _plan_tile_icon = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
        '<path d="M9 11l3 3L22 4"/>'
        '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'
        "</svg>"
    )
    # C-20: exactly ONE "start here" on this page — the first implemented
    # tile's START HERE ribbon (Meet Recap, the audience's actual first
    # step). The Plan hero is the strategic aid, not the starting point,
    # so its label stays a plain "Plan".
    # B-1: Plan stops double-paying the interstitial — once its intro has
    # been seen, the tile opens the planner directly; the "How it works"
    # pill keeps the slide reachable.
    _plan_intro_url = url_for("content_type_intro", ct="plan")
    try:
        _plan_direct_url = url_for("plan_page")
    except Exception:
        _plan_direct_url = _plan_intro_url
    _plan_href = _plan_direct_url if "plan" in _seen_intros else _plan_intro_url
    plan_entry_html = (
        '<div class="mh-plan-tile-wrap">'
        f'<a href="{_h(_plan_href)}" class="mh-plan-tile">'
        f'<span class="mh-plan-tile-icon">{_plan_tile_icon}</span>'
        '<span class="mh-plan-tile-body">'
        '<span class="mh-plan-tile-eyebrow">Plan</span>'
        '<span class="mh-plan-tile-title">Not sure what to post? '
        '<em class="editorial">Plan it.</em></span>'
        '<span class="mh-plan-tile-desc">MediaHub ranks what to post next from your '
        "results, the calendar and what you tell it &mdash; with the reasoning shown for "
        "every item. Describe what&rsquo;s coming up in your own words and it fills in the "
        "calendar for you, then jump straight into making the top idea.</span>"
        "</span>"
        '<span class="mh-plan-tile-cta">Open Plan &rarr;</span>'
        "</a>"
        f'<a class="mh-how-pill" href="{_h(_plan_intro_url)}" '
        'aria-label="How Plan works">How it works</a>'
        "</div>"
    )

    # C-3: everything you make (free text, spotlights, previews, event
    # packs) lands in Drafts. It now has a first-class tile in its own
    # "Your drafts" segment below (built above), so the old top-right
    # "Your saved drafts →" strip was retired to avoid two links to the
    # same place on one page. (The template gallery is deliberately reached
    # from Settings — not from here, so Create stays focused; see
    # test_make_page_no_longer_links_to_gallery.)
    body = (
        '<section class="mh-hero" data-lane="03" style="padding-top:var(--sp-9);padding-bottom:var(--sp-7);margin-bottom:var(--sp-6)">'
        '<span class="mh-hero-eyebrow">Create</span>'
        '<h1>What do you want<br>to <em class="editorial">make</em>?</h1>'
        '<p class="lede">Upload a file, paste a brief, or describe a moment in your own words. Pick a starting point and the engine takes it from there.</p>'
        "</section>"
        f"{W._free_tier_banner_html()}"
        f"{plan_entry_html}"
        f"{first_run_cta}"
        f"{tiles_section}"
    )
    return W._layout("Create", body, active="create")


def content_type_intro(ct):
    # Every implemented Create tile links here first. The slide explains, in
    # the landing page's visual language, what this heading takes in and
    # produces; its "Start" CTA carries on to the real route. Registry-driven
    # (mediahub.web.content_intro), so a heading added to the REGISTRY gets a
    # first slide automatically — no per-heading wiring here.
    try:
        from mediahub.club_platform.content_types import REGISTRY
        from mediahub.club_platform.post_types import canonical_slug, implemented_content_type
    except ImportError:
        return redirect(url_for("make_page"))

    # Plan is the predominant non-content-type entry. It gets the same
    # how-it-works first slide, but its "Open Plan" CTA opens the planner.
    if canonical_slug(ct) == "plan":
        # B-1: viewing the intro retires it — the Create tile links
        # straight to the planner from now on (per organisation).
        W._intro_mark_seen(W._active_profile_id(), "plan")
        try:
            plan_start = url_for("plan_page")
        except Exception:
            plan_start = url_for("make_page")
        body = W._render_plan_intro(start_url=plan_start, back_url=url_for("make_page"))
        return W._layout("Plan", body, active="create")

    ctype = implemented_content_type(ct)
    if ctype is None or ctype not in REGISTRY:
        # Unknown / planning-only slug — send them back to the chooser.
        return redirect(url_for("make_page"))
    meta = REGISTRY[ctype]

    # B-1: viewing the intro retires it — this organisation's Create tile
    # for the heading links straight into the flow from now on (the slide
    # stays reachable via the "How it works" pills). Keyed on the
    # canonical value so legacy slug aliases mark the same heading.
    W._intro_mark_seen(W._active_profile_id(), ctype.value)

    formats, effort = W._ct_presentation_for(ctype.value)
    # Start → the real flow. Degrade gracefully (a missing endpoint sends the
    # user back to Create rather than 500ing the intro).
    try:
        start_url = url_for(meta.primary_route_endpoint)
    except Exception:
        W.log.warning(
            "content_type_intro: %r references unknown endpoint %r",
            ctype.value,
            meta.primary_route_endpoint,
        )
        start_url = url_for("make_page")

    body = W._render_content_intro(
        meta,
        formats=formats,
        effort=effort,
        start_url=start_url,
        back_url=url_for("make_page"),
    )
    return W._layout(meta.title, body, active="create")


def stub_free_text_quick():
    # One-shot single-textarea form (legacy). Kept under /quick because
    # the primary /free-text experience is now the iterative chat.
    return W._render_stub(
        "FreeTextStub", "stub_free_text_quick", "Free Text (quick)", intro_ct="free_text"
    )


def free_text_chat_page():
    from mediahub.free_text_chat.session import list_sessions

    # Fail-soft: a corrupted chat store would otherwise 500 the
    # Free-text landing page. Treat the failure as "no sessions
    # visible" so the user can still start a new chat.
    sessions: list = []
    store_failed = False
    try:
        # Tenant isolation: a chat title is the first line of another org's
        # free-text brief (often an athlete name), so the landing list must
        # be scoped to the active organisation — mirrors the /drafts index
        # and _can_access_pack. Unstamped legacy chats stay visible, and the
        # no-org sandbox (active pid None) keeps everything visible.
        sessions = list_sessions(limit=20, profile_id=W._active_profile_id())
    except Exception as e:
        W.log.warning("free-text: list_sessions failed: %s", e)
        store_failed = True
    rows_html = ""
    for it in sessions:
        view_url = url_for("free_text_chat_view", chat_id=it["chat_id"])
        ts = str(it.get("updated_at") or "")[:19].replace("T", " ")
        badge = (
            '<span class="tag good" style="font-size:10px">brief accepted</span>'
            if it.get("accepted")
            else '<span class="tag" style="font-size:10px">draft</span>'
        )
        rows_html += (
            f'<tr><td><a href="{view_url}">{_h(it.get("title") or "Untitled chat")}</a></td>'
            f"<td>{badge}</td>"
            f"<td>{it.get('n_messages', 0)}</td>"
            f'<td class="muted">{_h(ts)}</td></tr>'
        )
    new_url = url_for("free_text_chat_new")
    quick_url = url_for("free_text_quick_build")
    quick_err = session.pop("free_text_quick_error", "")
    # H-8: restore the prompt the user typed if the last build failed.
    quick_prompt = session.pop("free_text_quick_prompt", "")
    # J-6: a planner "Create →" link can carry the ranked idea — prefill
    # the textarea from ?seed=… (capped; a restored failed prompt wins).
    if not quick_prompt:
        quick_prompt = (request.args.get("seed") or "").strip()[:500]
    quick_err_html = (
        '<div class="mh-flash error" role="alert" style="margin:0 0 14px;padding:12px 16px;'
        "border:1px solid rgba(255,107,107,0.30);border-left:3px solid var(--bad);"
        f'background:var(--bad-bg);color:var(--ink);font-size:13px">{_h(quick_err)}</div>'
        if quick_err
        else ""
    )
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Free text</span>
  <h1>Describe it.<br><em class="editorial">Get a graphic.</em></h1>
  <p class="lede">
  Type what you want &mdash; a shout-out, a sponsor thank-you, a session
  update, a milestone, anything &mdash; and MediaHub interprets the prompt and
  builds a branded graphic from it. Add your own photos and it places them in.
  No forms, no templates: the prompt carries the context.
  </p>
  <a class="mh-how-pill" href="{
            url_for("content_type_intro", ct="free_text")
        }" style="margin-top:var(--sp-3)">How it works</a>
</section>

{W._llm_unavailable_banner()}
{quick_err_html}

<div class="card" style="padding:20px 22px;margin-bottom:18px">
  <form method="post" action="{
            quick_url
        }" enctype="multipart/form-data" data-loader-text="Building your graphic">
    <label for="ft-prompt" style="font-weight:600;display:block;margin-bottom:6px">What do you want to make?</label>
    <textarea id="ft-prompt" name="prompt" rows="4" required {W._CYCLE_PH_ATTR_MOMENT}
      placeholder="e.g. A bold thank-you post for our sponsor Riverside Physio after a great gala weekend — upbeat, club colours."
      style="width:100%;font-size:14px;padding:10px 12px;border:1px solid var(--panel);border-radius:8px;background:var(--bg);color:var(--ink);resize:vertical">{
            _h(quick_prompt)
        }</textarea>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px">
      <label class="btn secondary" style="font-size:13px;cursor:pointer;margin:0" tabindex="0" role="button"
        onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();this.querySelector('input[type=file]').click();}}">
        &#x1F4CE; Add photos
        <input type="file" name="photos" accept="image/*" multiple style="display:none"
          onchange="var n=this.files.length;var s=document.getElementById('ft-photo-count');if(s)s.textContent=n?(n+' photo'+(n===1?'':'s')+' attached'):'';">
      </label>
      <span id="ft-photo-count" class="dim" style="font-size:12px"></span>
      <button type="submit" class="mh-cta-primary" style="border:0;margin-left:auto">Generate graphic &rarr;</button>
    </div>
    <p class="dim" style="font-size:12px;margin:10px 0 0 0">You'll land on a draft with the graphic rendered &mdash; edit the
    caption, swap the photo, change format, approve, or export from there.</p>
  </form>
</div>

<div class="card" style="padding:16px 20px;margin-bottom:18px">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
    <div>
      <div style="font-weight:600">Want to refine it together first?</div>
      <p class="dim" style="font-size:13px;margin:4px 0 0 0">Chat it through &mdash; the assistant researches names, venues and PBs and proposes a brief you approve before generating.</p>
    </div>
    <form method="post" action="{new_url}" style="margin:0">
      <button type="submit" class="btn secondary" style="border:0;white-space:nowrap">Start a chat &rarr;</button>
    </form>
  </div>
</div>

<div class="card">
  <h2>Past chats</h2>
  {
            (
                "<table><thead><tr><th>Title</th><th>State</th><th>Messages</th>"
                "<th>Updated</th></tr></thead><tbody>" + rows_html + "</tbody></table>"
            )
            if rows_html
            else (
                '<p class="muted">Couldn&rsquo;t load past chats &mdash; the chat store wasn&rsquo;t '
                "readable. You can still start a new chat above; if this persists, ask "
                "your operator to check the data volume.</p>"
                if store_failed
                else '<p class="muted">No chats yet.</p>'
            )
        }
</div>
"""
    return W._layout("Free text — chat", body, active="create")


def free_text_quick_build():
    """Single prompt → branded graphic.

    The user describes what they want (optionally attaching photos); we
    interpret it into a brief with one LLM call, save it as a draft pack,
    and land on the draft with the graphic auto-rendering. This is the
    ChatGPT-style "describe it and get a graphic" path that supersedes the
    bespoke Session Update / Sponsor Post forms — the prompt itself carries
    the context, whatever it is.
    """
    from mediahub.free_text_chat.agent import build_brief_from_prompt
    from mediahub.ai_core import ProviderNotConfigured, ProviderError
    from mediahub.club_platform.stub_pack_store import save_pack

    prompt = (request.form.get("prompt") or "").strip()
    if not prompt:
        return redirect(url_for("free_text_chat_page"))
    if len(prompt) > W._FREE_TEXT_MAX_PROMPT_CHARS:
        session["free_text_quick_error"] = (
            f"That prompt is very long ({len(prompt):,} characters). "
            f"Please keep it under {W._FREE_TEXT_MAX_PROMPT_CHARS:,} characters."
        )
        return redirect(url_for("free_text_chat_page"))
    active_pid = W._active_profile_id() or ""

    # Uploaded photos → media library so they're available to the graphic
    # picker; the first becomes the auto-rendered background.
    uploaded_ids: list[str] = []
    for f in request.files.getlist("photos"):
        if not f or not f.filename:
            continue
        try:
            a = W._quick_save_library_photo(f, active_pid)
            if a is not None:
                uploaded_ids.append(a.id)
        except Exception:
            current_app.logger.exception("free-text quick-build photo upload failed")
    picked_ids = [i for i in request.form.getlist("library_asset_id") if i]

    club_brand = W._active_club_brand_for_llm()
    try:
        brief = build_brief_from_prompt(prompt, club_brand=club_brand)
    except (ProviderNotConfigured, ProviderError) as e:
        # Honest error — no fake graphic. Bounce back with the reason AND the
        # prompt the user typed (H-8) so a poolside volunteer doesn't have to
        # retype a multi-sentence brief to retry.
        session["free_text_quick_error"] = str(e)
        session["free_text_quick_prompt"] = prompt
        return redirect(url_for("free_text_chat_page"))

    caption = "\n\n".join(
        [p for p in [brief.get("headline", ""), brief.get("body", "")] if p]
    ).strip()
    card = {
        "platform": brief.get("platform") or "Instagram",
        "caption": caption,
        "hashtags": brief.get("hashtags") or [],
        # D-25: prompt-led draft — no fabricated confidence badge.
        "confidence": None,
        "notes": brief.get("visual_concept", "") or "",
        "status": "queue",
    }
    form_data = {
        "free_text": prompt,
        "source": "quick",
        "title": brief.get("title") or "",
        "wants_reel": "1" if brief.get("wants_reel") else "",
    }
    if active_pid:
        form_data["profile_id"] = active_pid

    chosen = ""
    all_ids = uploaded_ids + picked_ids
    if all_ids and W._v8_get_media_store is not None and active_pid:
        try:
            store = W._v8_get_media_store()
            resolved = [
                a
                for a in (store.get(aid) for aid in all_ids)
                if a is not None and a.profile_id == active_pid
            ]
            if resolved:
                form_data["library_asset_ids"] = ",".join(a.id for a in resolved)
                form_data["library_asset_paths"] = ",".join(a.path for a in resolved)
                form_data["attached_photo_path"] = resolved[0].path
                form_data["attached_photo_filename"] = resolved[0].filename
                chosen = resolved[0].id
        except Exception:
            current_app.logger.exception("free-text quick-build photo resolve failed")

    saved = save_pack("free_text", form_data, [card], profile_id=active_pid or None)
    target = url_for("stub_pack_view", pack_id=saved["pack_id"]) + "?autographic=1"
    if chosen:
        target += "&photo=" + chosen
    return redirect(target)


def free_text_chat_new():
    """Create a fresh chat session and redirect into it.

    POST creates immediately. GET — used to also create-and-redirect,
    but that polluted the chat list with "Untitled" drafts every time
    a user followed a back-button or shared link. Now GET renders the
    Free-text landing page (which has the prominent "Start a new chat"
    POST form) so the DB row is only written after the user actually
    means to create one.
    """
    if request.method == "GET":
        return redirect(url_for("free_text_chat_page"))
    from mediahub.free_text_chat.session import create_session

    # Stamp the creating organisation so the chat is tenant-scoped from
    # birth (mirrors runs/packs). Without this every web chat is ownerless
    # and readable by any org via /free-text/chat/<id>.
    s = create_session(profile_id=W._active_profile_id() or "")
    return redirect(url_for("free_text_chat_view", chat_id=s.chat_id))


def free_text_chat_view(chat_id):
    s = W._load_accessible_chat(chat_id)
    if not s:
        return W._recovery_page(
            "Chat not found",
            "This chat may have expired or been deleted. Start a new one — your previous chats list is on the Free text page.",
            primary_cta=("Start a new chat", url_for("free_text_chat_new")),
            secondary_cta=("Free-text home", url_for("free_text_chat_page")),
        )
    # Pre-render messages for the initial paint; JS keeps it live.
    # User vs assistant bubbles are distinguished by a lane-yellow side
    # rail (user) vs a paper-cream side rail (assistant) — same chrome
    # discipline as everywhere else in the system.
    msgs_html = ""
    for m in s.messages:
        if m.get("role") == "system_note":
            continue  # internal — not shown to user
        role = m.get("role", "")
        text = _h(m.get("content", "") or "")
        is_user = role == "user"
        who = "You" if is_user else "Assistant"
        rail = "var(--lane)" if is_user else "var(--ink-faint)"
        msgs_html += (
            f'<div class="chat-msg" data-role="{_h(role)}" '
            f'style="margin-bottom:var(--sp-3);padding:var(--sp-3) var(--sp-4) var(--sp-3) var(--sp-5);'
            f"background:var(--surface);border:1px solid var(--hairline);"
            f'border-left:2px solid {rail};border-radius:var(--radius)">'
            f'<div style="font-family:var(--font-mono);font-size:10px;text-transform:uppercase;'
            f'color:{"var(--lane)" if is_user else "var(--ink-muted)"};letter-spacing:0.18em;margin-bottom:6px">{who}</div>'
            f'<div style="font-family:var(--font-body);font-size:14px;color:var(--ink);'
            f'white-space:pre-wrap;line-height:1.5">{text}</div></div>'
        )

    def _format_brief_html(brief: dict) -> str:
        """Render a brief as a structured field list rather than a raw
        JSON dump. Round-7 cleanup: the audit flagged the previous
        `<pre>{json.dumps(brief)}</pre>` rendering as engineering
        leak — users were staring at curly braces and indentation
        instead of the actual content they were approving."""
        if not isinstance(brief, dict):
            return f"<p>{_h(str(brief))}</p>"
        rows = []

        # Field-name humanisation: snake_case -> Title Case sentence,
        # so the LLM's structured output reads as English.
        def _label(key: str) -> str:
            return key.replace("_", " ").strip().capitalize()

        for k, v in brief.items():
            if k.startswith("_"):
                continue
            label = _h(_label(k))
            if isinstance(v, (list, tuple)):
                if not v:
                    body = '<span class="muted">—</span>'
                else:
                    items = "".join(f"<li>{_h(str(x))}</li>" for x in v)
                    body = f'<ul style="margin:4px 0 0 var(--sp-5);padding:0">{items}</ul>'
            elif isinstance(v, dict):
                sub_items = "".join(
                    f"<li><strong>{_h(_label(sk))}:</strong> {_h(str(sv))}</li>"
                    for sk, sv in v.items()
                    if not sk.startswith("_")
                )
                body = f'<ul style="margin:4px 0 0 var(--sp-5);padding:0">{sub_items}</ul>'
            elif v is None or v == "":
                body = '<span class="muted">—</span>'
            else:
                body = _h(str(v))
            rows.append(
                f'<div style="display:grid;grid-template-columns:140px 1fr;gap:var(--sp-3);padding:var(--sp-2) 0;border-bottom:1px solid var(--hairline)">'
                f'<div class="strap" style="color:var(--ink-muted);padding:0">{label}</div>'
                f'<div style="font-size:14px;color:var(--ink);line-height:1.5">{body}</div>'
                "</div>"
            )
        return "".join(rows) if rows else '<p class="muted">Empty brief.</p>'

    # Pending brief card (if any)
    brief_html = ""
    if s.pending_brief and not s.accepted_brief:
        brief_html = f"""
<div id="pending-brief" class="card" style="margin-top:var(--sp-4);border-left:2px solid var(--good);background:var(--good-bg)">
  <div class="strap" style="color:var(--good);margin-bottom:var(--sp-3)">Proposed brief</div>
  {_format_brief_html(s.pending_brief)}
  <div style="margin-top:var(--sp-4);display:flex;gap:var(--sp-3)">
    <form method="post" action="{url_for("free_text_chat_accept", chat_id=chat_id)}" style="display:inline">
      <button type="submit" class="btn">Accept &amp; generate</button>
    </form>
    <form method="post" action="{url_for("free_text_chat_decline", chat_id=chat_id)}" style="display:inline">
      <button type="submit" class="btn secondary">Decline — keep refining</button>
    </form>
  </div>
</div>
"""
    accepted_html = ""
    if s.accepted_brief:
        generate_url = url_for("free_text_chat_generate", chat_id=chat_id)
        # Offer the active org's library as a final step before generating
        # content. Picks ride through on the generate POST and land on the
        # saved pack so the chat flow has the same media-attachment story
        # as the legacy /free-text/quick form.
        chat_picker_html = W._render_library_picker_for_active_profile()
        accepted_html = f"""
<div class="card" style="margin-top:var(--sp-4);border-left:2px solid var(--lane);background:color-mix(in oklab, var(--lane) 4%, transparent)">
  <div class="strap live" style="margin-bottom:var(--sp-3)">Accepted brief</div>
  {_format_brief_html(s.accepted_brief)}
  <form method="post" action="{generate_url}" style="margin-top:var(--sp-3)">
    {chat_picker_html}
    <button type="submit" class="btn">Generate content from this brief →</button>
  </form>
</div>
"""
    send_url = url_for("free_text_chat_send", chat_id=chat_id)
    title = _h(s.title or "New chat")
    msg_count = sum(1 for m in s.messages if m.get("role") not in ("system_note",))
    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Free text — chat</span>
  <h1>{title}</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{msg_count:02d} {"message" if msg_count == 1 else "messages"}</span><span class="sep">/</span>
    <a href="{url_for("free_text_chat_page")}" style="color:var(--ink-muted);text-decoration:none">← All chats</a>
  </div>
</section>

{W._llm_unavailable_banner()}

<div id="chat-log">
  {msgs_html or '<p class="muted">Start by telling the assistant what you want to post. It will ask questions, research the web, and propose a brief.</p>'}
</div>

{brief_html}
{accepted_html}

<form id="chat-form" method="post" action="{send_url}" style="margin-top:var(--sp-5)" data-loader-text="Thinking…">
  <label class="req" for="chat-reply">Your reply</label>
  <textarea id="chat-reply" name="message" placeholder="Tell the assistant what you want to post about…"
            {W._CYCLE_PH_ATTR_MOMENT} style="min-height:110px" required></textarea>
  <div style="margin-top:var(--sp-3);display:flex;gap:var(--sp-3);align-items:center;flex-wrap:wrap">
    <button type="submit" class="btn">Send reply &rarr;</button>
    <span class="strap" style="color:var(--ink-muted)">AI assistant · web research</span>
  </div>
</form>
"""
    return W._layout(s.title or "Chat", body, active="create")


def free_text_chat_send(chat_id):
    from mediahub.free_text_chat.session import save_session
    from mediahub.free_text_chat.agent import next_assistant_turn

    s = W._load_accessible_chat(chat_id)
    if not s:
        return W._recovery_page(
            "Chat not found",
            "This chat may have expired or been deleted. Start a new one — your previous chats list is on the Free text page.",
            primary_cta=("Start a new chat", url_for("free_text_chat_new")),
            secondary_cta=("Free-text home", url_for("free_text_chat_page")),
        )
    msg = (request.form.get("message") or "").strip()
    if len(msg) > W._FREE_TEXT_MAX_PROMPT_CHARS:
        s.add_assistant_message(
            f"That reply is very long ({len(msg):,} characters). Please shorten "
            f"it to under {W._FREE_TEXT_MAX_PROMPT_CHARS:,} characters and send again.",
            meta={"error": True},
        )
        save_session(s)
        return redirect(url_for("free_text_chat_view", chat_id=chat_id))
    if msg:
        s.add_user_message(msg)
        save_session(s)
        try:
            next_assistant_turn(s, club_brand=W._active_club_brand_for_llm())
        except Exception as e:
            s.add_assistant_message(
                W._friendly_failure_message(e, kind="ai", context="free-text chat"),
                meta={"error": True},
            )
            save_session(s)
    return redirect(url_for("free_text_chat_view", chat_id=chat_id))


def free_text_chat_accept(chat_id):
    # B-6: "Accept & generate" now actually generates. It used to only mark
    # the brief accepted and reload, leaving the user to hunt for a second
    # "Generate content from this brief" button and a third "Create graphic"
    # click. Accepting the brief and building the draft is a single POST that
    # ends on the rendered graphic (?autographic=1), like the quick path.
    from mediahub.free_text_chat.session import save_session

    s = W._load_accessible_chat(chat_id)
    if not s:
        return redirect(url_for("free_text_chat_page"))
    if s.pending_brief:
        s.accepted_brief = s.pending_brief
        s.pending_brief = None
        s.messages.append(
            {
                "role": "system_note",
                "content": "[user accepted the brief]",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        save_session(s)
        # Build the draft exactly once, on the accepting POST. A stale or
        # double-submitted re-POST (pending_brief already cleared) falls
        # through to the chat view rather than minting another draft —
        # deliberate regeneration is the explicit "Generate content from
        # this brief" action (free_text_chat_generate).
        pack_url = W._chat_brief_to_pack(s, chat_id, request.form.getlist("library_asset_id"))
        if pack_url:
            return redirect(pack_url)
    return redirect(url_for("free_text_chat_view", chat_id=chat_id))


def free_text_chat_decline(chat_id):
    from mediahub.free_text_chat.session import save_session
    from mediahub.free_text_chat.agent import next_assistant_turn

    s = W._load_accessible_chat(chat_id)
    if not s:
        return redirect(url_for("free_text_chat_page"))
    if s.pending_brief:
        s.pending_brief = None
        s.add_user_message(
            "I'm not happy with that brief yet. Ask me what's missing or "
            "propose a revised version."
        )
        save_session(s)
        try:
            next_assistant_turn(s, club_brand=W._active_club_brand_for_llm())
        except Exception as e:
            s.add_assistant_message(
                W._friendly_failure_message(e, kind="ai", context="free-text chat"),
                meta={"error": True},
            )
            save_session(s)
    return redirect(url_for("free_text_chat_view", chat_id=chat_id))


def free_text_chat_generate(chat_id):
    """Turn an accepted brief into a saved stub-pack so the existing
    approval pills + export flow apply."""
    s = W._load_accessible_chat(chat_id)
    if not s or not s.accepted_brief:
        return redirect(url_for("free_text_chat_view", chat_id=chat_id))
    # B-6: land on the draft with the graphic already rendering, like the
    # quick path (?autographic=1) — the chat path used to drop the user on a
    # blank draft needing a third "Create graphic" click.
    pack_url = W._chat_brief_to_pack(s, chat_id, request.form.getlist("library_asset_id"))
    return redirect(pack_url or url_for("free_text_chat_view", chat_id=chat_id))


def brand_home_page():
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("sign_in_page"))
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    # A bound non-owner (Viewer/Reviewer/Editor) can view the brand home but
    # not mutate kits — mirror the api_brand_kit_* POST gate so they see a
    # read-only page rather than admin controls that dead-end in a 404.
    return W._render_brand_home(prof, can_admin=W._brand_can_admin(pid))


def content_pack(run_id):
    """Content builder — the post-approval step.

    Shows only APPROVED cards. This is where the user picks a caption
    tone, creates graphics + motion, then schedules or downloads.
    Approval / rejection happens first on the Review page; nothing is
    created here until a card has been approved. The grouped 8-bucket
    recommendation explorer still lives at /pack/<run_id>/grouped.
    """
    # Tenant gate BEFORE the in_progress short-circuit (mirrors
    # api_cards / api_export): a foreign org or anonymous prober must get
    # run_not_found whether or not the run is still processing, so the
    # "Still processing" page can't be used as an existence / timing
    # oracle. _can_access_run resolves ownership from the runs DB row, so
    # it works mid-pipeline before the run JSON is written.
    run_data = W._load_run(run_id)
    _has_access = W._can_access_run(run_id, run_data, W._active_profile_id())
    if not _has_access:
        run_data = None
    if _has_access and W._run_state(run_id) == "in_progress":
        return W._layout(
            "Still processing", W._in_progress_page(run_id, "content_pack"), active="home"
        )
    if not run_data:
        return W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    # A terminally-failed run has nothing to build from; the honest "what
    # went wrong" surface lives on /review (U.2), so send the user there
    # rather than showing an empty "Nothing approved yet" builder.
    if (run_data.get("error") or "").strip():
        return redirect(url_for("review", run_id=run_id))

    profile_id = run_data.get("profile_id", "")
    try:
        from mediahub.workflow.pack import build_content_pack as _bcp

        approved = _bcp(run_id, profile_id, W.RUNS_DIR)
    except Exception:
        approved = []

    _review_url = url_for("review", run_id=run_id)
    _grouped_url = url_for("content_pack_grouped", run_id=run_id)
    meet_name = _h(run_data.get("meet", {}).get("name", "") or run_data.get("profile_display", ""))

    # Empty state — nothing approved yet. Send the user back to triage.
    if not approved:
        body = (
            '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-7);margin-bottom:var(--sp-5)">'
            '<span class="mh-hero-eyebrow">Content builder</span>'
            '<h1>Nothing <em class="editorial">approved</em> yet.</h1>'
            '<p class="lede">'
            f"The content builder holds the cards you approve in <strong>{meet_name}</strong>. "
            "Approve a few in the review queue and they land here &mdash; ready to caption, turn into "
            "graphics and video, then schedule or download."
            "</p>"
            '<div class="mh-hero-actions">'
            f'<a class="mh-cta-primary" href="{_review_url}">Go to review &amp; approve &rarr;</a>'
            f'<a class="mh-cta-secondary" href="{url_for("activity_page")}">All runs</a>'
            "</div>"
            "</section>"
        )
        return W._layout("Content builder", body, active="home")

    # M30 — what's already rendered for this run (persisted visuals dir).
    # Drives the pre-filled visual panels, the rendered-count annotation on
    # the export buttons, the pack-preview wall, and the batch job's
    # "only the missing ones" default.
    _rendered = W._rendered_visuals_for_run(run_id)
    _approved_ids: list[str] = []
    for card in approved:
        _ach = card.get("achievement") or {}
        _cid = str(card.get("_card_id") or _ach.get("swim_id") or "")
        if _cid:
            _approved_ids.append(_cid)
    _rendered_ids = [cid for cid in _approved_ids if cid in _rendered]
    rendered_n = len(_rendered_ids)

    # Per-card builder rows: header + the live creative toolbar (caption
    # tones, create graphic, motion) + a download for manual posting.
    cards_html = ""
    for card in approved:
        ach = card.get("achievement") or {}
        swimmer = _h(ach.get("swimmer_name", ""))
        event = _h(ach.get("event", ""))
        headline = _h(ach.get("headline", ""))
        card_id_raw = card.get("_card_id") or ach.get("swim_id", "")
        card_uuid = W._dom_card_uuid(card_id_raw)
        _dl_url = url_for("api_card_download", run_id=run_id, card_id=card_id_raw)
        # B-2 — ONE primary export per card. The ZIP link only goes live
        # once this card has a rendered graphic; before that it is
        # honestly disabled instead of shipping a caption-only ZIP.
        _dl_ready = str(card_id_raw) in _rendered
        _dl_style = "font-size:11px;padding:4px 10px" + (
            "" if _dl_ready else ";pointer-events:none;opacity:0.45"
        )
        # JS2-3 — the gate marker + the ready tooltip ride on the anchor
        # so mhExportGatesEnable can lift this card's gate in place after
        # an in-page render (no reload).
        _dl_ready_title = "The graphic plus the caption text in one .zip, ready to post manually"
        _dl_gate = (
            ""
            if _dl_ready
            else (
                ' aria-disabled="true" onclick="return false" '
                'data-mh-export-gate="card" '
                f'data-mh-title-ready="{_h(_dl_ready_title)}"'
            )
        )
        _dl_title = (
            _dl_ready_title
            if _dl_ready
            else "No graphic yet — use Create graphic first, then download the post"
        )
        # M30/M32 — persisted renders show on page load, no re-render.
        _initial_visual = W._prefilled_visual_panel_html(
            run_id, card_id_raw, _rendered.get(str(card_id_raw))
        )
        _initial_motion = W._rendered_motion_strip_html(run_id, card_id_raw)
        cards_html += f"""
<div class="card" id="pc-{_h(card_id_raw)}" style="margin-bottom:14px;page-break-inside:avoid">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
    <div style="flex:1">
      <div style="font-size:13px;font-weight:700">{swimmer}{(" · " + event) if event else ""}</div>
      <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
      <span class="tag good">approved</span>
    </div>
  </div>
  {
                W._render_card_creative_toolbar(
                    run_id,
                    card_id_raw,
                    initial_visual_html=_initial_visual,
                    initial_motion_html=_initial_motion,
                )
            }
  {W._render_stored_translations(card)}
  <div class="no-print" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <a class="btn" style="{_dl_style}" href="{_h(_dl_url)}"{_dl_gate}
       title="{_dl_title}">Download post (graphic + caption)</a>
    <span class="muted" style="font-size:11px">Pick a tone, then create a graphic or motion and download.</span>
  </div>
</div>"""

    _wf_api_base = url_for("api_workflow_set", run_id=run_id, card_id="CARD_ID").replace(
        "CARD_ID", ""
    )
    _reel_url = url_for("api_run_reel", run_id=run_id)
    _charts_url = url_for("run_charts_page", run_id=run_id) if W._charts_ok else ""
    _newsletter_html_url = url_for("api_run_newsletter", run_id=run_id)
    _newsletter_text_url = _newsletter_html_url + "?format=text"
    _newsletter_zip_url = _newsletter_html_url + "?format=zip"
    _zip_url = url_for("content_pack_zip", run_id=run_id)
    _export_zip_url = url_for("pack_export_zip", run_id=run_id)
    _bulk_export_url = url_for("export_run_tool_page", run_id=run_id)
    _print_tool_url = url_for("print_run_tool_page", run_id=run_id)
    _certs_url = url_for("pack_certificates_zip", run_id=run_id)
    _certs_print_url = url_for("pack_certificates_zip", run_id=run_id, print=1)
    # D-12: the anchors keep their direct hrefs as the no-JS fallback;
    # with JS the click kicks the background job and polls for progress.
    _certs_job_url = url_for("api_run_certificates_job", run_id=run_id)
    _certs_print_job_url = url_for("api_run_certificates_job", run_id=run_id, print=1)
    _turn_into_html = W._render_turn_into_card(run_id)

    # W.14: what this club's own approval history says it prefers —
    # deterministic, explainable, straight from the telemetry store.
    _prefs_html = ""
    try:
        from mediahub.observability.approval_telemetry import preference_summary

        _prefs_pid = profile_id or W._run_owner_profile_id(run_id) or ""
        if _prefs_pid:
            _prefs = preference_summary(_prefs_pid)
            if _prefs["reasons"]:
                _reasons_li = "".join(
                    f'<li style="margin:2px 0">{_h(r)}</li>' for r in _prefs["reasons"][:4]
                )
                _prefs_html = (
                    '<div class="card no-print" style="margin-bottom:14px;'
                    'border-left:3px solid var(--accent)">'
                    '<div style="font-size:13px;font-weight:700">What this club prefers</div>'
                    '<div style="font-size:12px;color:var(--ink-dim);margin:2px 0 6px">'
                    f"Learned from {_prefs['total_events']} of your own approve/reject "
                    "decisions — no guesswork, no AI ranking.</div>"
                    f'<ul style="margin:0;padding-left:18px;font-size:13px">{_reasons_li}</ul>'
                    "</div>"
                )
    except Exception:
        _prefs_html = ""

    # Single global AI-availability banner (shared helper — U.2). The
    # content builder promises a narrower slice of AI than /review, so it
    # passes the shorter body copy.
    _ai_banner_html = W._ai_unavailable_banner(W._AI_UNAVAILABLE_DETAIL_PACK)

    # ---- M31 (UX-3): the reel composer -----------------------------
    # A rank-ordered checkbox list of approved cards (top 3 pre-checked,
    # max 5), a live duration readout mirroring reel_duration_for's
    # maths, rhythm presets mapping onto the R1.12 request shape, an
    # audio-mix select when voiceover is enabled, and the existing
    # format chips. Untouched defaults send NO extra params, so the
    # default top-3 reel stays byte-identical.
    _default_reel_ids = _approved_ids[:3]
    _composer_rows = ""
    for _idx, card in enumerate(approved[:10]):
        _ach = card.get("achievement") or {}
        _cid = str(card.get("_card_id") or _ach.get("swim_id") or "")
        if not _cid:
            continue
        _label = " · ".join(
            b
            for b in (
                str(_ach.get("swimmer_name") or "").strip(),
                str(_ach.get("event") or "").strip(),
            )
            if b
        )
        _thumb = url_for("api_card_thumb", run_id=run_id, card_id=_cid)
        _checked = "checked" if _cid in _default_reel_ids else ""
        _composer_rows += (
            '<label style="display:flex;align-items:center;gap:10px;padding:6px 8px;'
            "border:1px solid var(--border);border-radius:8px;cursor:pointer;"
            'background:color-mix(in oklab, var(--panel) 60%, transparent)">'
            f'<input type="checkbox" class="mh-reel-pick" value="{_h(_cid)}" {_checked} '
            'onchange="mhReelComposerSync()">'
            f'<span style="color:var(--ink-muted);font-size:11px;min-width:22px">#{_idx + 1}</span>'
            f'<img src="{_h(_thumb)}" alt="" loading="lazy" '
            'style="width:34px;aspect-ratio:4/5;object-fit:cover;border-radius:4px;'
            'border:1px solid var(--border);background:var(--panel)" onerror="this.style.visibility=\'hidden\'">'
            f'<span style="font-size:12px;color:var(--ink)">{_h(_label) or _h(_cid)}</span>'
            "</label>"
        )
    _mix_select = ""
    _dub_select = ""
    if W._voiceover_enabled():
        _mix_select = (
            '<label style="display:inline-flex;align-items:center;gap:6px;font-size:12px;'
            'color:var(--ink-dim)">Audio mix '
            '<select id="mh-reel-mix" onchange="mhReelComposerSync()" '
            'style="font-size:12px;padding:4px 8px;min-height:0">'
            '<option value="">Default</option>'
            '<option value="voice_lead">Voice-led</option>'
            '<option value="balanced">Balanced</option>'
            '<option value="music_forward">Music-forward</option>'
            "</select></label>"
        )
        # C-17 — the 1.24 AI-dub language was URL-only (?lang=), invisible
        # from the composer. Offer the caption-language registry's
        # dubbable languages (same registry as the Settings picker;
        # English IS the original narration, so it isn't a dub target).
        # Gated with the mix select: a dub re-voices the narration, which
        # only exists when voiceover is enabled.
        try:
            from mediahub.visual import dub as _dub_mod
            from mediahub.web.languages import single_language_options as _lang_opts

            _dub_opts = "".join(
                f'<option value="{_h(code)}">{_h(label)}</option>'
                for code, label in _lang_opts()
                if code != "en" and _dub_mod.is_dubbable(code)
            )
        except Exception:
            _dub_opts = ""
        if _dub_opts:
            _dub_select = (
                '<label style="display:inline-flex;align-items:center;gap:6px;font-size:12px;'
                'color:var(--ink-dim)">Narration language '
                '<select id="mh-reel-dub" onchange="mhReelComposerSync()" '
                'title="Re-voice the reel&#39;s fact-only narration in another language (clearly labelled as AI-dubbed)" '
                'style="font-size:12px;padding:4px 8px;min-height:0">'
                '<option value="">No narration dub</option>' + _dub_opts + "</select></label>"
            )
    _reel_composer_html = f"""
<div class="card no-print" id="mh-reel-composer" data-default-cards="{_h(",".join(_default_reel_ids))}" style="margin-bottom:14px">
  <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap">
    <div>
      <div style="font-size:13px;font-weight:700">Meet reel</div>
      <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">Tick up to 5 moments &mdash; the top 3 are picked for you. Rank order decides the running order.</div>
    </div>
    <div id="mh-reel-duration" style="font-size:13px;font-weight:700;color:var(--medal)"></div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:6px;margin:10px 0">{_composer_rows}</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
    <label style="display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-dim)">Rhythm
      <select id="mh-reel-rhythm" onchange="mhReelComposerSync()" style="font-size:12px;padding:4px 8px;min-height:0">
        <option value="steady">Steady &mdash; even beats</option>
        <option value="punchy">Punchy &mdash; lead moment holds longer</option>
        <option value="showcase">Showcase &mdash; longer cover &amp; outro</option>
      </select>
    </label>
    {_mix_select}
    {_dub_select}
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button class="btn mh-reel-go" style="font-size:12px;padding:6px 14px;background:var(--medal);color:var(--medal-ink);border:none"
            onclick="generateReel(this, {repr(_reel_url)})">&#x25B6; Generate reel</button>
    <button class="btn secondary mh-reel-go" style="font-size:12px;padding:6px 14px"
            onclick="generateReelBatch(this, {repr(_reel_url)})">All 4 formats</button>
  </div>
  {f'<div class="dim" style="font-size:11px;margin-top:8px">Working from race footage? <a href="{url_for("video_studio_page")}">Try the Video Studio &rarr;</a></div>' if W._v8_ok else ""}
</div>"""

    # ---- M30: Create-all-graphics + rendered-count + pack wall ------
    _render_all_url = url_for("api_run_render_all_job", run_id=run_id)
    _missing_n = len(approved) - rendered_n
    _create_all_html = f"""
<div class="card no-print" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
  <div>
    <div style="font-size:13px;font-weight:700">Build the whole pack</div>
    <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">
      <span id="mh-renderall-count">{rendered_n} of {len(approved)}</span> approved cards have graphics.
      One click renders the rest in the background &mdash; every card, every format.</div>
    <div id="mh-renderall-status" class="dim" role="status" aria-live="polite" style="font-size:12px;margin-top:4px;min-height:1.2em"></div>
  </div>
  <button class="btn" id="mh-renderall-go" data-render-all-url="{_h(_render_all_url)}"
          style="font-size:12px;padding:6px 14px;background:var(--lane);color:var(--lane-ink);border:none">
    &#x2726; Create all graphics</button>
</div>"""

    _wall_tiles = ""
    for _cid in _approved_ids:
        _info = _rendered.get(_cid)
        if not _info:
            continue
        _fmt = next(
            (f for f in W._THUMB_FORMAT_PREFERENCE if f in (_info.get("png_paths") or {})),
            None,
        )
        if _fmt is None:
            continue
        _vid = (_info.get("format_ids") or {}).get(_fmt) or _info.get("visual_id") or ""
        if not _vid:
            continue
        _png_url = url_for("api_visual_png", vid=_vid, format_name="feed_portrait")
        _wall_tiles += (
            f'<img src="{_h(_png_url)}" alt="" loading="lazy" '
            'style="width:100%;aspect-ratio:4/5;object-fit:cover;display:block;'
            'background:var(--panel)"/>'
        )
    _wall_html = ""
    if _wall_tiles:
        _wall_html = f"""
<div class="card no-print" style="margin-bottom:14px">
  <div style="font-size:13px;font-weight:700">Pack preview</div>
  <div style="font-size:12px;color:var(--ink-dim);margin:2px 0 10px">How this pack reads as a feed grid &mdash; if two cards look like twins here, regenerate one before exporting.</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px;max-width:420px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--border)">{_wall_tiles}</div>
</div>"""

    # ---- M33: photo coverage — which swimmers still lack a photo ----
    _coverage_html = ""
    try:
        _cov_profile_id = profile_id or run_data.get("club_filter") or "_run_" + run_id
        _cov_profile_id = re.sub(r"[^a-z0-9_-]", "-", _cov_profile_id.lower()).strip("-") or (
            "_run_" + run_id
        )
        _lib_names: list[str] = []
        if W._v8_ok and W._v8_get_media_store is not None:
            _photo_types = {"athlete_action", "athlete_headshot", "team_photo", "other"}
            for _a in W._v8_get_media_store().list(profile_id=_cov_profile_id):
                if _a.type in _photo_types:
                    _lib_names.extend(str(n).strip().lower() for n in _a.linked_athlete_names if n)
        _lib_name_set = set(_lib_names)

        def _has_photo(name_lc: str) -> bool:
            return any(name_lc == ln or name_lc in ln or ln in name_lc for ln in _lib_name_set)

        _cov_athletes: list[tuple[str, str]] = []  # (athlete, first card id)
        _cov_seen: set[str] = set()
        for card in approved:
            _ach = card.get("achievement") or {}
            _nm = str(_ach.get("swimmer_name") or "").strip()
            _cid = str(card.get("_card_id") or _ach.get("swim_id") or "")
            if _nm and _cid and _nm.lower() not in _cov_seen:
                _cov_seen.add(_nm.lower())
                _cov_athletes.append((_nm, _cid))
        if _cov_athletes:
            _with_photo = [nm for nm, _ in _cov_athletes if _has_photo(nm.lower())]
            _missing = [(nm, cid) for nm, cid in _cov_athletes if not _has_photo(nm.lower())]
            _missing_btns = ""
            for _nm, _cid in _missing[:12]:
                _first = _h(_nm.split(" ")[0])
                _cuid = W._dom_card_uuid(_cid)
                _photo_url = url_for("api_card_photo_upload", run_id=run_id, card_id=_cid)
                _create_url = url_for("api_create_graphic", run_id=run_id, card_id=_cid)
                _oc = _h(
                    "mhCardPhotoUpload(this, "
                    + json.dumps(_photo_url)
                    + ", "
                    + json.dumps(_create_url)
                    + ", "
                    + json.dumps(_cuid)
                    + ", 'feed_portrait')"
                )
                _missing_btns += (
                    f'<button type="button" class="btn secondary" onclick="{_oc}" '
                    'style="font-size:11px;padding:4px 10px;border-style:dashed" '
                    f'title="Upload a photo of {_h(_nm)} — it links to them in your library and renders their card">'
                    f"+ Add photo of {_first}</button>"
                )
            if _missing:
                _cov_body = (
                    f"<strong>{len(_with_photo)} of {len(_cov_athletes)}</strong> swimmers in "
                    "this pack have a photo in your library. Add the missing ones and their "
                    "cards switch from text-led to photo-led automatically."
                )
            else:
                _cov_body = (
                    f"<strong>All {len(_cov_athletes)}</strong> swimmers in this pack have a "
                    "photo in your library — every card can render photo-led."
                )
            _coverage_html = f"""
<div class="card no-print" style="margin-bottom:14px;border-left:3px solid var(--lane)">
  <div style="font-size:13px;font-weight:700">Photo coverage</div>
  <div style="font-size:12px;color:var(--ink-dim);margin:4px 0 8px">{_cov_body}</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">{_missing_btns}</div>
</div>"""
    except Exception:
        _coverage_html = ""

    # M32 — restore the reel on revisit whenever its file exists (the old
    # behaviour only restored when review comments happened to exist).
    _reel_prerendered = (W.RUNS_DIR / run_id / "motion" / "reel_3.mp4").exists()

    # M30 — honest export gating copy: the ZIPs bundle only what exists.
    if not approved:
        _export_note = ""
    elif rendered_n == 0:
        _export_note = (
            "Nothing rendered yet — the ZIPs would be empty. "
            "Use “Create all graphics” above first."
        )
    elif _missing_n > 0:
        _export_note = (
            f"{rendered_n} of {len(approved)} approved cards have graphics — "
            f"the ZIPs include only those {rendered_n}. "
            "Use “Create all graphics” to build the rest first."
        )
    else:
        _export_note = f"All {len(approved)} approved cards are rendered and ready to export."
    # JS2-3 — data-mh-export-gate marks exactly what the gate stamped so
    # mhExportGatesEnable can lift it client-side after the first in-page
    # render (no reload). The marker value names the gate variant.
    _export_disabled_attr = (
        ' aria-disabled="true" onclick="return false" '
        'style="pointer-events:none;opacity:0.45" data-mh-export-gate="attr" '
        'title="No graphics rendered yet — use Create all graphics first"'
        if rendered_n == 0
        else ""
    )
    # B-2 — every pack-level export sits under the same render gate. Two
    # variants for controls where the standard attr would double up an
    # attribute: the certificate anchors carry their own onclick
    # (mhCertificatesJob refuses aria-disabled anchors), and the
    # browser-print button takes a real ``disabled``.
    _export_disabled_plain = (
        ' aria-disabled="true" style="pointer-events:none;opacity:0.45" '
        'data-mh-export-gate="plain" '
        'title="No graphics rendered yet — use Create all graphics first"'
        if rendered_n == 0
        else ""
    )
    _export_disabled_btn = (
        ' disabled style="opacity:0.45" data-mh-export-gate="btn" '
        'title="No graphics rendered yet — use Create all graphics first"'
        if rendered_n == 0
        else ""
    )

    # JS2-5 — exactly one title attribute per gated control in either
    # state: when the render gate is on, the gate string above supplies
    # the title and the control's own tooltip rides along in
    # data-mh-title-ready (restored by mhExportGatesEnable); once
    # rendered, the control's own title renders directly.
    def _export_title_attr(ready_title: str) -> str:
        if rendered_n == 0:
            return f' data-mh-title-ready="{_h(ready_title)}"'
        return f' title="{_h(ready_title)}"'

    # B-2 — the single pack-level export disclosure's label carries the
    # live approved count.
    _export_summary_label = (
        f"Export pack ({len(approved)} approved "
        f"card{'s' if len(approved) != 1 else ''})&hellip;"
    )

    # J-9 — one "Share publicly" chooser: the two token-URL surfaces where
    # approved cards can go live, each with a one-line explanation. Links
    # only — nothing here publishes anything; each destination has its own
    # explicit Publish step. Kept as its own card, outside the export row.
    _share_newsletter_row = (
        (
            '<div style="font-size:13px;margin-top:6px">'
            f'<a href="{_h(url_for("newsletters_home"))}">Newsletter</a>'
            " &mdash; a digest you publish or email.</div>"
        )
        if W._email_design_ok
        else ""
    )
    _share_publicly_html = (
        '<div class="card no-print" id="mh-share-publicly" style="margin-top:14px">'
        '<div style="font-size:13px;font-weight:700">Share publicly</div>'
        '<div style="font-size:12px;color:var(--ink-dim);margin:2px 0 8px">'
        "Where approved cards can go beyond downloads. Nothing goes public until "
        "you press Publish there.</div>"
        '<div style="font-size:13px">'
        f'<a href="{_h(url_for("public_wall_settings"))}">Public wall</a>'
        " &mdash; a live page of your approved cards.</div>"
        f"{_share_newsletter_row}"
        "</div>"
    )
    # J-9 — the one-off meet email above vs the recurring composer: one
    # clarifying line so the two newsletter systems stop reading as one.
    _nl_composer_hint = (
        (
            '<div style="font-size:12px;color:var(--ink-dim);margin-top:4px">'
            "Building a recurring email? Use "
            f'<a href="{_h(url_for("newsletters_home"))}">Newsletters</a>.</div>'
        )
        if W._email_design_ok
        else ""
    )

    body = f"""
<style>
@media print {{
  .no-print {{ display: none !important; }}
  body {{ background: white; color: black; }}
  .card {{ border: 1px solid #ccc; box-shadow: none; }}
}}
</style>
{_ai_banner_html}
<section class="mh-hero no-print" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Content builder</span>
  <h1><span class="mh-shiny-text">{meet_name}</span></h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{len(approved):02d} approved {
            "card" if len(approved) == 1 else "cards"
        }</span><span class="sep">·</span>
    <a href="{
            _review_url
        }" style="color:var(--ink-muted);text-decoration:none">← Back to review</a><span class="sep">/</span>
    <a href="{
            _grouped_url
        }" style="color:var(--ink-muted);text-decoration:none">All recommendations</a>
  </div>
</section>

{_create_all_html}
{_coverage_html}
{_reel_composer_html}
<div id="reel-panel" class="no-print" style="display:none;margin-bottom:14px;padding:14px;background:rgba(244,213,141,0.04);border:1px solid var(--border);border-radius:8px"></div>
{_wall_html}
{
            (
                '<div class="card no-print" style="margin-bottom:14px;display:flex;justify-content:space-between;'
                'align-items:center;flex-wrap:wrap;gap:10px">'
                '<div><div style="font-size:13px;font-weight:700">Charts &amp; insights</div>'
                '<div style="font-size:12px;color:var(--ink-dim);margin-top:2px">Brand-styled stat graphics from this '
                "meet's results — PBs, medals, drops, splits — with AI-picked highlights and grounded takeaways.</div></div>"
                f'<a class="btn secondary" style="font-size:12px;padding:6px 12px" href="{_h(_charts_url)}">Open charts &amp; insights &rarr;</a>'
                "</div>"
            )
            if _charts_url
            else ""
        }

{_prefs_html}

<div class="no-print">{_turn_into_html}</div>

<h2 style="margin:18px 0 12px">Approved cards <span class="muted" style="font-weight:400;font-size:13px">&mdash; {
            len(approved)
        }</span></h2>
{cards_html}

<details class="card no-print" id="mh-export-pack" style="margin-top:16px">
  <summary style="cursor:pointer;font-size:13px;font-weight:700">{_export_summary_label}
    <span class="muted" style="font-weight:400;font-size:12px;margin-left:6px">ZIPs, bulk convert, print, certificates &amp; newsletter</span>
  </summary>
  <div id="mh-export-note"{
            ' data-mh-export-note-gated="1"' if rendered_n == 0 else ""
        } style="font-size:12px;color:var(--ink-dim);margin:10px 0 12px">{_export_note}</div>

  <div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">Social posting</div>
  <p id="mh-export-howto" class="muted" style="font-size:12px;margin:0 0 10px;max-width:640px">
    Each ZIP holds a ready-to-post caption (.txt) alongside the branded image(s) &mdash;
    no editing needed. Download it, pick the size for your platform (square or
    portrait for Instagram or Facebook, story/9:16 for Instagram Stories,
    portrait or square for Twitter / X), then upload that image and paste in
    the matching caption yourself &mdash; MediaHub never posts on your behalf.
  </p>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">
    <a class="btn" href="{_export_zip_url}"{_export_disabled_attr}{
            _export_title_attr(
                "Every rendered card at every size (square, portrait, story), grouped per card and ready to post"
            )
        }>Every format, organised for posting (.zip)</a>
    <a class="btn secondary" href="{_zip_url}"{_export_disabled_attr}{
            _export_title_attr(
                "One folder with just the rendered images — no captions, no grouping"
            )
        }>Just the images (.zip)</a>
    <a class="btn secondary" href="{_bulk_export_url}"{_export_disabled_attr}{
            _export_title_attr(
                "Convert this pack to JPG / WebP / AVIF / PNG with quality options, bundled into one ZIP"
            )
        }>Bulk export &amp; convert&hellip;</a>
  </div>

  <div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">Print &amp; certificates</div>
  <div style="font-size:12px;color:var(--ink-dim);margin-bottom:6px">A branded A4 certificate for every approved achievement &mdash; the thing families frame. Photo/name consent is honoured automatically.</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
    <a class="btn secondary" href="{_print_tool_url}"{_export_disabled_attr}{
            _export_title_attr(
                "Proof and export a print-ready PDF (posters, flyers, banners, merch) "
                "from this meet's cards — pre-flight checked before you send it to a printer"
            )
        }>Print &amp; merch&hellip;</a>
    <a class="btn secondary mh-certs-go" href="{_h(_certs_url)}" data-certs-job="{
            _h(_certs_job_url)
        }" onclick="return mhCertificatesJob(this)"{
            _export_disabled_plain
        }>Download certificates (.zip of PDFs)</a>
    <a class="btn secondary mh-certs-go" href="{_h(_certs_print_url)}" data-certs-job="{
            _h(_certs_print_job_url)
        }" onclick="return mhCertificatesJob(this)"{_export_disabled_plain}{
            _export_title_attr("A4 + 3mm bleed and crop marks, ready for a professional print shop")
        }>Print-shop pack (bleed + crop marks)</a>
    <button class="btn secondary" onclick="window.print()"{_export_disabled_btn}{
            _export_title_attr(
                "Use the browser print dialog on this page as it stands — "
                "for a press-ready file use Print & merch instead"
            )
        }>Print this page</button>
  </div>
  <div id="mh-certs-status" class="dim" role="status" aria-live="polite" style="font-size:12px;margin:4px 0 14px;min-height:1.2em"></div>

  <div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">Parent newsletter</div>
  <div style="font-size:12px;color:var(--ink-dim);margin-bottom:6px">Branded HTML email + plaintext fallback, ready to paste into Mailchimp / ConvertKit / your email client.</div>
  {_nl_composer_hint}
  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <a class="btn secondary" href="{_h(_newsletter_html_url)}" target="_blank" rel="noopener"{
            _export_disabled_attr
        }>Preview HTML &rarr;</a>
    <a class="btn secondary" href="{_h(_newsletter_html_url)}?download=1"{
            _export_disabled_attr
        }>Download .html</a>
    <a class="btn secondary" href="{_h(_newsletter_text_url)}&download=1"{
            _export_disabled_attr
        }>Download .txt</a>
    <a class="btn secondary" href="{_h(_newsletter_zip_url)}"{
            _export_disabled_attr
        }>Download .zip</a>
  </div>
</details>

{_share_publicly_html}

<style>{W._CARD_TOOLBAR_CSS}</style>
{W._CARD_TOOLBAR_JS}
{W._PACK_EXPORT_GATE_JS}
<script>var WF_API_BASE = {json.dumps(_wf_api_base)};</script>
{W._card_creative_js()}
<script>
// UI 1.8 / M32 - on load, surface the cached reel whenever its rendered file
// still exists on this run (not only when review comments happen to exist),
// so a returning user finds their MP4 instead of a blank builder.
(function(){{
  var reelUrl = {json.dumps(_reel_url)};
  var prerendered = {json.dumps(_reel_prerendered)};
  var panel = document.getElementById('reel-panel');
  if (!panel || typeof mhReelComments !== 'function') return;
  // JS-3: the finished-file restore is shared — mhResumeReelJob falls back
  // to it when its recalled job record turns out stale/unreachable, so a
  // dead record can no longer suppress the finished reel.
  var mhRestoreFinishedReel = function() {{
    var fileUrl = reelUrl + '-file?n=3&format=story';
    if (prerendered) {{
      panel.style.display = '';
      mhRenderReel(panel, reelUrl, 'story', fileUrl);
      return;
    }}
    fetch(reelUrl + '/comments?target=reel', {{headers:{{'Accept':'application/json'}}}})
      .then(function(r){{ return r.json(); }})
      .then(function(j){{
        var n = (j && j.comments && j.comments.length) || 0;
        if (!n) return;
        panel.style.display = '';
        fetch(fileUrl, {{method:'HEAD'}})
          .then(function(hr){{ if (hr.ok) mhRenderReel(panel, reelUrl, 'story', fileUrl); else mhRenderReelCommentsOnly(panel, reelUrl, n); }})
          .catch(function(){{ mhRenderReelCommentsOnly(panel, reelUrl, n); }});
      }})
      .catch(function(){{}});
  }};
  // D-13: a reel render still in flight from before navigation wins over
  // the finished-file restore — re-attach to it and keep polling.
  if (typeof mhResumeReelJob === 'function' && mhResumeReelJob(reelUrl, mhRestoreFinishedReel)) return;
  mhRestoreFinishedReel();
}})();

// M31 - initialise the reel composer readout (duration + max-5 rule).
if (typeof mhReelComposerSync === 'function') mhReelComposerSync();

// D-12 - the certificates ZIP renders one Chromium PDF per approved card,
// far too slow to hold the click's request open. Kick the background job,
// report per-certificate progress, then trigger the finished ZIP download
// from the same gated file route. Returning false keeps the anchor's href
// as the no-JS fallback.
function mhCertificatesJob(a) {{
  var status = document.getElementById('mh-certs-status');
  var say = function(m) {{ if (status) status.textContent = m; }};
  if (a.getAttribute('aria-disabled') === 'true') return false;
  var siblings = document.querySelectorAll('a.mh-certs-go');
  var setBusy = function(busy) {{
    Array.prototype.forEach.call(siblings, function(el) {{
      if (busy) {{ el.setAttribute('aria-disabled', 'true'); el.style.opacity = '0.55'; }}
      else {{ el.removeAttribute('aria-disabled'); el.style.opacity = ''; }}
    }});
  }};
  setBusy(true);
  var finish = function(msg) {{ setBusy(false); say(msg || ''); }};
  say('Starting…');
  fetch(a.dataset.certsJob, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:'{{}}'}})
    .then(function(r){{ return r.json().then(function(j){{ return {{status: r.status, j: j}}; }}); }})
    .then(function(res){{
      var j = res.j || {{}};
      if (res.status !== 202 || !j.poll_url) {{
        finish(j.user_message || j.error || 'Could not start the certificates export.');
        return;
      }}
      var tries = 0;
      var poll = function() {{
        tries++;
        if (tries > 200) {{ finish('Timed out waiting for the certificates — try again.'); return; }}
        fetch(j.poll_url).then(function(r){{ return r.json(); }}).then(function(s){{
          if (s.status === 'done' && s.download_url) {{
            finish('Done — your download is starting.');
            window.location.href = s.download_url;
            return;
          }}
          if (s.status === 'error') {{
            finish(s.user_message || s.error || 'Certificates export failed.');
            return;
          }}
          var n = Math.min((s.done || 0) + 1, s.total || 1);
          say('Rendering certificate ' + n + ' of ' + (s.total || '?') + (s.current ? (' — ' + s.current) : '') + '…');
          setTimeout(poll, 2000);
        }}).catch(function(){{ setTimeout(poll, 4000); }});
      }};
      setTimeout(poll, 1000);
    }})
    .catch(function(){{ finish('Network error — try again.'); }});
  return false;
}}

// M30 - "Create all graphics": one background job over the approved cards
// still missing a graphic, with honest per-card progress, then a reload so
// the server-rendered panels + pack wall show everything.
(function(){{
  var go = document.getElementById('mh-renderall-go');
  if (!go) return;
  var status = document.getElementById('mh-renderall-status');
  var say = function(m) {{ if (status) status.textContent = m; }};
  go.addEventListener('click', function(){{
    go.disabled = true;
    say('Starting…');
    fetch(go.dataset.renderAllUrl, {{method:'POST', headers:{{'Accept':'application/json', 'Content-Type':'application/json'}}, body:'{{}}'}})
      .then(function(r){{ return r.json().then(function(j){{ return {{status: r.status, j: j}}; }}); }})
      .then(function(res){{
        var j = res.j || {{}};
        if (res.status === 200 && j.status === 'done') {{ say(j.message || 'Everything is already rendered.'); go.disabled = false; return; }}
        if (res.status !== 202 || !j.poll_url) {{
          go.disabled = false;
          say(j.user_message || j.error || 'Could not start the batch render.');
          return;
        }}
        var poll = function(){{
          fetch(j.poll_url).then(function(r){{ return r.json(); }}).then(function(s){{
            if (s.status === 'done') {{ say('Done — reloading…'); location.reload(); return; }}
            if (s.status === 'error') {{
              go.disabled = false;
              say(s.user_message || s.error || 'Batch render failed.');
              return;
            }}
            say((s.done || 0) + ' of ' + (s.total || 0) + ' rendered' + (s.current ? (' — designing ' + s.current) : '') + '…');
            setTimeout(poll, 3000);
          }}).catch(function(){{ setTimeout(poll, 5000); }});
        }};
        setTimeout(poll, 2000);
      }})
      .catch(function(){{ go.disabled = false; say('Network error — try again.'); }});
  }});
}})();
</script>
"""
    return W._layout(f"Content builder — {meet_name}", body, active="home")


def web_research_console():
    """Render the interactive web-research console (off by default)."""
    if not W._research_console_enabled():
        off = (
            '<section class="panel" style="max-width:720px;margin:32px auto">'
            '<h1 style="margin-top:0">Web research</h1>'
            "<p>The web-research console is turned off on this deployment. "
            "An operator can enable it by setting "
            "<code>MEDIAHUB_RESEARCH_UI=1</code>.</p></section>"
        )
        return W._layout("Web research", off, active="research"), 404
    body = W._WEB_RESEARCH_CONSOLE_BODY.replace(
        "__SUBMIT_URL__", url_for("api_web_research_submit")
    ).replace("__CYCLE_PH__", W._CYCLE_PH_ATTR_RESEARCH)
    return W._layout("Web research", body, active="research")


def club_qa_console():
    """Render the "Ask the data" console — Q&A over the org's own runs."""
    body = W._CLUB_QA_CONSOLE_BODY.replace("__SUBMIT_URL__", url_for("api_club_qa_submit")).replace(
        "__CYCLE_PH__", W._CYCLE_PH_ATTR_ASKDATA
    )
    return W._layout("Ask the data", body, active="settings")


def content_pack_grouped(run_id):
    """Read-only "explore all recommendations" view &mdash; 8 buckets.

    B-3: single-purpose pages. Triage (approve / re-queue) lives on
    /review, creation + export on the content builder (/pack); this
    page keeps no approval strap or export row of its own &mdash; each
    card deep-links to its spot in the builder instead.
    """
    # Tenant gate BEFORE the in_progress short-circuit (mirrors
    # api_cards / api_export): a foreign org or anonymous prober must get
    # run_not_found whether or not the run is still processing, so the
    # "Still processing" page can't be used as an existence / timing
    # oracle. _can_access_run resolves ownership from the runs DB row, so
    # it works mid-pipeline before the run JSON is written.
    run_data = W._load_run(run_id)
    _has_access = W._can_access_run(run_id, run_data, W._active_profile_id())
    if not _has_access:
        run_data = None
    if _has_access and W._run_state(run_id) == "in_progress":
        return W._layout(
            "Still processing", W._in_progress_page(run_id, "content_pack_grouped"), active="home"
        )
    if not run_data:
        return W._recovery_page(
            "Run not found",
            "This run isn't on disk. It may have been deleted from /privacy, or the URL might be from a different deployment.",
            primary_cta=("Open activity", url_for("activity_page")),
            secondary_cta=("Back to home", url_for("home")),
        )
    # Failed run → the honest error surface on /review (U.2), not an empty
    # grouped builder.
    if (run_data.get("error") or "").strip():
        return redirect(url_for("review", run_id=run_id))

    profile_id = run_data.get("profile_id", "")
    meet_name = _h(run_data.get("meet", {}).get("name", "") or run_data.get("profile_display", ""))
    _review_url = url_for("review", run_id=run_id)
    _pack_url = url_for("content_pack", run_id=run_id)

    if not W._v73_ok or W._build_grouped_pack is None:
        return redirect(_pack_url)

    # UI 1.25 — per-card reaction tallies for this run, in one query.
    _react_counts = W._reaction_counts_for_run(run_id)

    try:
        grouped = W._build_grouped_pack(run_data, profile_id)
    except Exception as e:
        grouped = {}
        import traceback

        traceback.print_exc()

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
            angle = _h(W._humanise(item.get("post_angle") or ""))
            s2p = item.get("safe_to_post") or {}
            s2p_level = (
                s2p.get("level", "needs_review") if isinstance(s2p, dict) else "needs_review"
            )
            s2p_reason = _h(s2p.get("reason", "") if isinstance(s2p, dict) else "")
            s2p_cls = {"safe": "good", "needs_review": "warn", "do_not_post": "bad"}.get(
                s2p_level, ""
            )
            cap_only = _h(item.get("caption_only") or ach.get("headline") or "")
            cap_hash = _h(item.get("caption_with_hashtags") or "")
            cap_full = _h(item.get("caption_full_brief") or "")
            card_id_raw = ach.get("swim_id") or item.get("card_id") or ""
            card_id = _h(card_id_raw)
            card_uuid = W._dom_card_uuid(card_id_raw)
            band = _h(item.get("quality_band") or "")
            prio = item.get("priority", 0)
            n_ach = item.get("n_achievements", 0)
            # B-3 — this page is a read-only explorer: approval lives on
            # /review and creation on the content builder, so instead of
            # its own approve strap each card deep-links to its builder
            # spot (the builder's per-card anchor is `pc-<card id>`).
            builder_link = ""
            if card_id_raw:
                from urllib.parse import quote as _quote  # noqa: PLC0415

                builder_link = (
                    f'<a class="btn secondary" style="font-size:12px;padding:4px 10px" '
                    f'href="{_h(_pack_url)}#pc-{_h(_quote(str(card_id_raw), safe=""))}" '
                    f'title="Open this card in the content builder — approved cards are '
                    f'captioned, rendered and downloaded there.">'
                    f"Open in content builder &rarr;</a>"
                )
            schedule_btn = W._schedule_button_html(run_id, card_id_raw, f"g-{card_uuid}")
            # Per-card motion render — D-12: the same background job +
            # poll + progress UI the Content builder uses (the shared
            # _MOTION_CLIENT_JS block), instead of a plain link that
            # held a 30-90s synchronous render open in a new tab with
            # zero feedback.
            motion_btn = ""
            motion_panel = ""
            if card_id_raw:
                _motion_url = url_for(
                    "api_card_motion",
                    run_id=run_id,
                    card_id=str(card_id_raw),
                )
                motion_btn = (
                    f'<button class="btn secondary" style="font-size:12px;padding:4px 10px" '
                    f"onclick=\"generateMotion(this, {repr(_motion_url)}, '{card_uuid}')\" "
                    f'title="Render a 6-second branded story-format MP4 for this card. '
                    f'The first render can take up to 90 seconds; repeats are instant.">'
                    f"&#x25B6; Motion video</button>"
                )
                motion_panel = (
                    f'<div class="motion-panel" data-card="{card_uuid}" '
                    f'data-motion-url="{_h(_motion_url)}" '
                    f'style="display:none;margin-top:10px;padding:12px;'
                    f"background:rgba(244,213,141,0.04);border:1px solid var(--border);"
                    f'border-radius:8px"></div>'
                )
            # Per-card sponsor variant — Phase 1.2 deliverable.
            # Sponsor-branded result-card graphic + sponsor-
            # acknowledging caption rendered in a single page.
            sponsor_btn = ""
            if card_id_raw:
                _sponsor_url = url_for(
                    "sponsor_variant_view",
                    run_id=run_id,
                    card_id=str(card_id_raw),
                )
                sponsor_btn = (
                    f'<a class="btn secondary" style="font-size:12px;padding:4px 10px" '
                    f'href="{_h(_sponsor_url)}" target="_blank" rel="noopener" '
                    f'title="Render a sponsor-branded variant: sponsor-tile graphic + '
                    f'sponsor-acknowledging caption for this card.">'
                    f"&#x2605; Sponsor variant</a>"
                )
            _ra_for_why = {
                "achievement": ach if isinstance(ach, dict) else (item.get("achievement") or {}),
                "factors": item.get("factors")
                or (ach.get("factors") if isinstance(ach, dict) else None)
                or [],
                "rank": item.get("rank"),
            }
            _why_uuid = (str(card_id) or section_id).replace(":", "_").replace(",", "_").replace(
                "/", "_"
            ) or f"gp-{section_id}"
            why_html = W._render_why_this_card(
                _ra_for_why, card_uuid=f"gp-{_why_uuid}", run_id=run_id
            )
            # Phase 1.4 — sortable confidence/priority. Stamp the band
            # + priority on the card div so a JS sort handler in the
            # section header can reorder without re-rendering.
            _band_rank = {"elite": 4, "great": 3, "good": 2, "standard": 1}.get(
                (item.get("quality_band") or "").lower(),
                0,
            )
            try:
                _prio_num = float(item.get("priority", 0) or 0)
            except (TypeError, ValueError):
                _prio_num = 0.0
            rows += f"""
<div class="card mh-pack-card" id="g-{card_uuid}"
     data-quality-band="{_h(item.get("quality_band") or "")}"
     data-band-rank="{_band_rank}"
     data-priority="{_prio_num:.4f}"
     style="margin-bottom:12px">
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
  {why_html}
  <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    {builder_link}
    {W._render_reactions(run_id, str(card_id_raw), _react_counts) if card_id_raw else ""}
    <span style="flex:1"></span>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-1')">Copy caption</button>
    <textarea id="cap-{card_id}-1" style="display:none">{cap_only}</textarea>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-2')">Copy + hashtags</button>
    <textarea id="cap-{card_id}-2" style="display:none">{cap_hash}</textarea>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-3')">Copy full brief</button>
    <textarea id="cap-{card_id}-3" style="display:none">{cap_full}</textarea>
    {motion_btn}
    {sponsor_btn}
    {schedule_btn}
  </div>
  {motion_panel}
</div>"""
        if not rows:
            rows = f'<p class="muted">{_h(empty_msg)}</p>'
        # Phase 1.4 — sort controls. Only render when there's
        # more than one card to sort.
        sort_controls = ""
        if isinstance(items_list, list) and len([x for x in items_list if x]) > 1:
            sort_controls = (
                f'<span style="font-size:11px;display:flex;gap:4px;align-items:center;'
                f'margin-right:8px">'
                f'<span class="muted">Sort:</span>'
                f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" '
                f'onclick="event.preventDefault();event.stopPropagation();'
                f"mhSortPackSection(this, 'band-rank', 'desc')\">Confidence</button>"
                f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" '
                f'onclick="event.preventDefault();event.stopPropagation();'
                f"mhSortPackSection(this, 'priority', 'desc')\">Priority</button>"
                f"</span>"
            )
        return f"""
<details open data-mh-pack-section="{section_id}">
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>{icon} {_h(title)}</span>
    <span style="display:flex;align-items:center">{sort_controls}<span class="tag" style="font-size:12px">{n}</span></span>
  </summary>
  <div class="mh-pack-rows">{rows}</div>
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
        hl_html = "".join(f"<li>{_h(h)}</li>" for h in highlights)
        cap_txt = _h(win.get("caption_text", ""))
        win_html = f"""
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none">Weekend in numbers</summary>
  <div class="card">
    <div class="stat-block">{stats_html}</div>
    {f'<ul style="margin-top:10px">' + hl_html + "</ul>" if hl_html else ""}
    <div style="margin-top:10px;display:flex;gap:8px">
      <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'win-cap')">Copy caption</button>
      <textarea id="win-cap" style="display:none">{cap_txt}</textarea>
    </div>
  </div>
</details>"""

    # Build a thumbnail strip of generated visuals if any exist for this run
    visuals_strip = ""
    try:
        vdir = W.RUNS_DIR / run_id / "visuals"
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
                fmt_label = {
                    "feed_square": "Square",
                    "feed_portrait": "Portrait",
                    "story": "Story",
                    "reel_cover": "Reel cover",
                }.get(fmt, fmt)
                tiles.append(f"""
<div class="card" style="padding:10px;display:flex;flex-direction:column;gap:8px;width:200px;flex:0 0 200px">
  <img src="{url_for("api_visual_png", vid=vid, format_name=fmt)}" alt="" style="width:100%;border-radius:6px;display:block" loading="lazy">
  <div style="font-size:11px;color:var(--ink-dim)">{_h(fmt_label)}</div>
  <div style="font-size:12px;line-height:1.3">{_h(cap)}</div>
  <a class="btn secondary" style="font-size:12px;padding:4px 10px" target="_blank" rel="noopener" href="{url_for("api_visual_png", vid=vid, format_name=fmt)}">Download PNG</a>
</div>""")
            if tiles:
                _zip_url = url_for("content_pack_zip", run_id=run_id)
                visuals_strip = f"""
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>&#x1F3A8; Generated visuals <span class="tag" style="font-size:11px">{len(tiles)}</span></span>
    <a class="btn" style="font-size:12px;padding:6px 14px" href="{_zip_url}">Download all as ZIP</a>
  </summary>
  <div style="display:flex;gap:12px;overflow-x:auto;padding:8px 0 12px">{"".join(tiles)}</div>
</details>"""
    except Exception:
        visuals_strip = ""

    # Single global AI-availability banner (shared helper — U.2).
    _ai_banner_html = W._ai_unavailable_banner()

    body = f"""
{_ai_banner_html}

<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">All recommendations</span>
  <h1><span class="mh-shiny-text">{meet_name}</span></h1>
  <p class="lede" style="max-width:60ch">Every ranked recommendation for this meet, in one read-only view.
  Approve cards on the <a href="{_review_url}">review page</a>; captions, graphics, video and downloads
  live in the <a href="{_pack_url}">content builder</a>.</p>
  <div class="strap" style="margin-top:var(--sp-3)">
    <a href="{_review_url}" style="color:var(--ink-muted);text-decoration:none">← Back to review</a><span class="sep">/</span>
    <a href="{_pack_url}" style="color:var(--ink-muted);text-decoration:none">Content builder &rarr;</a>
  </div>
</section>

<div class="card" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
  <div>
    <div style="font-size:13px;font-weight:700">Meet reel</div>
    <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">Pick up to 5 moments, set the rhythm, and render a branded MP4 reel &mdash; the reel composer works from this meet&#39;s approved cards on the Content builder.</div>
  </div>
  <a class="btn" style="font-size:12px;padding:6px 14px;background:var(--medal);color:var(--medal-ink);border:none"
     href="{_pack_url}#mh-reel-composer">&#x25B6; Open the reel composer</a>
</div>

{visuals_strip}

{_section_html("Main feed posts", grouped.get("main_feed", []), icon="&#x1F4CC;")}
{_section_html("Stories", grouped.get("stories", []), icon="&#x1F4D6;")}
{_section_html("Athlete spotlights", grouped.get("athlete_spotlights", []), icon="&#x1F31F;", empty_msg="No swimmers with 3+ achievements.")}
{win_html}
{_section_html("Internal notes / nice mentions", grouped.get("internal_notes", []), icon="&#x1F4DD;")}
{_section_html("Needs review", grouped.get("needs_review", []), icon="&#x26A0;")}
{_section_html("Not recommended", grouped.get("rejected", []), icon="&#x2715;")}

{W._MOTION_CLIENT_JS}
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
// V9: Copy "Why this card?" reasoning.
function copyWhyCard(btn, taId) {{ copyText(btn, taId); }}
// Escape a JS expression for an HTML onclick attribute (this page's script
// block doesn't share the card-toolbar _attrEsc helper).
function _attrEsc(jsExpr) {{
  return '"' + jsExpr.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"';
}}
// Phase 1.4 — sort the cards within one pack section by a data
// attribute on each .mh-pack-card. Toggles between desc / asc on
// repeat clicks of the same key. The DOM is reordered in place,
// avoiding any server round-trip.
window.mhSortPackSection = function(btn, key, defaultDir) {{
  var section = btn.closest('[data-mh-pack-section]');
  if (!section) return;
  var container = section.querySelector('.mh-pack-rows');
  if (!container) return;
  var cards = Array.prototype.slice.call(container.querySelectorAll('.mh-pack-card'));
  if (cards.length < 2) return;
  var prevKey = section.dataset.mhSortKey || '';
  var prevDir = section.dataset.mhSortDir || '';
  var dir = (prevKey === key && prevDir === defaultDir) ? (defaultDir === 'desc' ? 'asc' : 'desc') : defaultDir;
  var attr = 'data-' + key;
  cards.sort(function(a, b) {{
    var av = parseFloat(a.getAttribute(attr)) || 0;
    var bv = parseFloat(b.getAttribute(attr)) || 0;
    return dir === 'desc' ? (bv - av) : (av - bv);
  }});
  cards.forEach(function(c) {{ container.appendChild(c); }});
  section.dataset.mhSortKey = key;
  section.dataset.mhSortDir = dir;
  // Visual marker on the active sort button.
  var allBtns = section.querySelectorAll('button[onclick*="mhSortPackSection"]');
  Array.prototype.forEach.call(allBtns, function(b) {{
    b.style.background = (b === btn) ? 'color-mix(in oklab, var(--lane) 18%, transparent)' : '';
    b.style.color = (b === btn) ? 'var(--accent)' : '';
  }});
}};
</script>
"""
    return W._layout(f"All recommendations — {meet_name}", body, active="home")


def media_library_page():
    """Browse and upload reusable media assets."""
    if not W._v8_ok:
        # The V8 media engine is required for everything below — surface
        # a recovery hero instead of a bare ``<div class="empty">`` so
        # the user has somewhere to go.
        return W._recovery_page(
            "Media library unavailable",
            "The V8 media engine isn't enabled on this deployment, so the "
            "library can't be browsed or uploaded to. Other parts of MediaHub "
            "still work; ask your operator to enable the V8 engine if you need "
            "a per-org photo library.",
            eyebrow="Media library",
            primary_cta=("Back to Create", url_for("make_page")),
            secondary_cta=("System status", url_for("status_page")),
            code=503,
        )
    from flask import request as _req

    requested_pid = _req.args.get("profile_id")
    active_pid = W._active_profile_id()
    # Strict isolation: even if the caller asks for another profile by
    # query string, only show the active organisation (or a run-scoped
    # synthetic profile, which has its own per-run privacy semantics).
    if requested_pid and requested_pid != active_pid and not requested_pid.startswith("_run_"):
        return redirect(url_for("media_library_page"))
    profile_id = requested_pid or active_pid
    if not profile_id:
        _profs = W.list_profiles()
        if not _profs:
            _org_url = url_for("organisation_setup")
            _create_url = url_for("make_page")
            empty_body = (
                '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-9);padding-bottom:var(--sp-8)">'
                '<span class="mh-hero-eyebrow">Media library</span>'
                '<h1>No organisation,<br><em class="editorial">no library.</em></h1>'
                '<p class="lede">'
                "The media library is scoped per organisation. Set up your "
                "organisation first &mdash; or jump into Create and one "
                "gets created automatically."
                "</p>"
                '<div class="mh-hero-actions">'
                f'<a class="mh-cta-primary" href="{_org_url}">Set up organisation &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{_create_url}">Or start creating</a>'
                "</div>"
                "</section>"
            )
            return W._layout("Media library", empty_body, active="media")
        profile_id = _profs[0].profile_id
    # Fail-soft on the media store, but tell two different stories apart.
    # A store that simply isn't there yet — a fresh org, or a data volume
    # with nothing uploaded — is an EMPTY library, not a fault: the asset
    # DB is created lazily on first write, so "no file on disk" just means
    # "no photos uploaded here yet" and must render the clean empty state.
    # Only a store whose DB file IS on disk but won't read (corrupt /
    # unreadable) earns the "check the data volume" recovery message.
    assets: list = []
    store_failed = False
    store = None
    try:
        store = W._v8_get_media_store()
        assets = store.list(profile_id=profile_id)
    except Exception as e:
        db_path = None
        try:
            from mediahub.media_library.store import _default_db_path as _ml_default_db

            db_path = Path(getattr(store, "db_path", None) or _ml_default_db())
        except Exception:
            db_path = None
        if db_path is not None and db_path.exists():
            # The DB file is on disk but the read failed → genuinely
            # corrupt or unreadable. Surface the recovery message.
            W.log.warning(
                "media-library: store.list(%s) failed on an existing store: %s",
                profile_id,
                e,
            )
            store_failed = True
        else:
            # No DB file yet → nothing has been uploaded on this
            # deployment. Render the clean empty state, not an error.
            W.log.info(
                "media-library: no store yet for %s; empty state (%s)",
                profile_id,
                e,
            )
    rows_html = ""

    def _media_approval_badge(status: str) -> str:
        """D-29 — a visible Draft/Ready badge per photo (JS updates it in
        place after a bulk mark), so a volunteer can see which photos are
        approved for cards and which still need it."""
        ready = str(status or "").strip() == "approved"
        cls = "tag good" if ready else "tag"
        label = "Ready" if ready else "Draft"
        title = (
            "Ready to use on cards (the photo picker prefers these)"
            if ready
            else "Not yet marked ready for cards"
        )
        return (
            f'<span class="{cls}" data-mh-approval title="{title}" '
            f'style="font-size:10px">{label}</span>'
        )

    gallery_items = ""  # UI 1.27 — drag-scroll filmstrip cards
    untagged_n = 0  # M34 — photos with no athlete link, tags, or vision record
    _skip_tag_types = {"footage", "logo", "sponsor_logo", "brand_pattern"}
    for a in assets[:200]:
        ad = a.to_dict() if hasattr(a, "to_dict") else a
        athlete_names = ", ".join(ad.get("linked_athlete_names") or [])
        _parsed = ad.get("description_parsed") or {}
        _has_vision = bool(isinstance(_parsed, dict) and _parsed.get("vision"))
        _is_untagged = (
            ad.get("type") not in _skip_tag_types
            and not (ad.get("linked_athlete_names") or [])
            and not (ad.get("tags") or [])
            and not _has_vision
        )
        if _is_untagged:
            untagged_n += 1
        # M34 — honest tagging state per row: an "auto" marker on AI-linked
        # athletes (reviewable metadata), an "untagged" badge when nothing
        # has tagged the photo yet.
        _tag_badges = ""
        if _has_vision and athlete_names:
            _tag_badges += (
                ' <span class="tag" style="font-size:9px;cursor:pointer" '
                'data-mh-meta-open role="button" tabindex="0" '
                'title="AI-tagged from the photo — click to review and edit">&#10024; auto</span>'
            )
        if _is_untagged:
            _tag_badges += (
                ' <span class="tag warn" style="font-size:10px" '
                'title="No athlete or scene tags yet — add a description with '
                "the swimmer's name, or run AI tagging below\">untagged</span>"
            )
        _file_url = url_for("api_media_library_file", asset_id=ad.get("id", ""))
        _delete_url = url_for("api_media_library_delete", asset_id=ad.get("id", ""))
        _cutout_url = url_for("media_library_cutout_page", asset_id=ad.get("id", ""))
        _studio_url = url_for("image_studio_page", asset_id=ad.get("id", ""))
        _edit_url = url_for("photo_editor_page", asset_id=ad.get("id", ""))
        _qa_url = url_for("api_media_library_quick_action", asset_id=ad.get("id", ""))
        # H-4 — the editable metadata carried on the row so the in-place
        # editor can prefill without a round-trip.
        _meta_desc = ad.get("description_raw", "") or ""
        _meta_tags = ", ".join(ad.get("tags") or [])
        _meta_venue = ad.get("linked_venue") or ""
        _meta_event = ad.get("linked_event") or ""
        # U.14 cursor-following preview: the row shows a 60px chip, so the
        # floating frame carries the full photo at a useful size plus a
        # caption (type + athlete/venue). Escaped — parsed metadata is
        # never trusted into markup. <template> keeps the image inert
        # until the first hover, so listing 200 assets costs no extra
        # network up front.
        _hp_type = (str(ad.get("type", "") or "photo")).replace("_", " ")
        _hp_subject = athlete_names or (ad.get("linked_venue") or ad.get("linked_event") or "")
        _hp_subject_html = f"<span>{_h(_hp_subject)}</span>" if _hp_subject else ""
        _hp_tpl = (
            '<template class="mh-hp-tpl">'
            f'<img class="mh-hp-img" src="{_file_url}" alt="" />'
            f'<span class="mh-hp-cap"><b>{_h(_hp_type)}</b>{_hp_subject_html}</span>'
            "</template>"
        )
        # UI 1.27 — one filmstrip card per asset for the drag-scroll
        # gallery above the table. Same escaped, parsed-metadata caption
        # as the row; the photo loads lazily so a 200-asset strip costs
        # nothing up front beyond what's on screen.
        gallery_items += (
            '<figure class="mh-ds-card">'
            '<div class="mh-ds-card-media">'
            f'<img src="{_file_url}" loading="lazy" decoding="async" alt="" />'
            "</div>"
            '<figcaption class="mh-ds-card-cap">'
            f'<span class="eyebrow">{_h(_hp_type)}</span>'
            + (f'<span class="sub">{_h(_hp_subject)}</span>' if _hp_subject else "")
            + "</figcaption>"
            "</figure>"
        )
        # HTML-escape every parsed-metadata cell: descriptions/links are
        # user-supplied + AI-parsed, so an unescaped name/venue was a
        # stored-XSS vector. (Same _h() rule the rest of the app follows.)
        rows_html += f"""
<tr class="mh-hp mh-asset-row" data-asset-id="{_h(ad.get("id", ""))}"
    data-desc="{_h(_meta_desc)}" data-athletes="{_h(athlete_names)}"
    data-venue="{_h(_meta_venue)}" data-event="{_h(_meta_event)}" data-tags="{_h(_meta_tags)}">
  <td class="mh-bulk-cell"><input type="checkbox" class="mh-row-check" name="asset_ids" value="{
                _h(ad.get("id", ""))
            }" aria-label="Select photo"></td>
  <td data-label="Preview"><span class=\"mh-lens\" style=\"display:inline-block;border-radius:4px;overflow:hidden;line-height:0\"><img src=\"{
                _file_url
            }\" style=\"max-height:60px;border-radius:4px;display:block\" /></span>{_hp_tpl}</td>
  <td data-label="Type">{_h(ad.get("type", ""))}</td>
  <td data-label="Athlete">{_h(athlete_names)}{_tag_badges}</td>
  <td data-label="Venue / Event">{_h(ad.get("linked_venue") or ad.get("linked_event") or "")}</td>
  <td data-label="Permission">{
                W._media_permission_select(ad.get("id", ""), ad.get("permission_status", ""))
                if ad.get("type") not in _skip_tag_types
                else _h(
                    W._MEDIA_PERMISSION_LABELS.get(
                        ad.get("permission_status", ""), ad.get("permission_status", "")
                    )
                )
            }</td>
  <td data-label="Status">{_media_approval_badge(ad.get("approval_status", ""))}</td>
  <td data-label="ID"><code>{_h(ad.get("id", "")[:12])}</code></td>
  <td style="white-space:nowrap">
    <a class="btn ghost" href="{
                _edit_url
            }" style="font-size:11px;padding:3px 9px;margin-right:6px" title="Filters, adjustments, crop, shapes, blur brush — non-destructive edits">&#9998; Edit</a>
    <a class="btn ghost" href="{
                _studio_url
            }" style="font-size:11px;padding:3px 9px;margin-right:6px" title="Edit this photo with AI — fill, erase, expand, upscale, restyle">&#x2726; Studio</a>
    <a class="btn ghost" href="{
                _cutout_url
            }" style="font-size:11px;padding:3px 9px;margin-right:6px" title="See exactly what background removal knocks out">Cut-out</a>
    <button class="btn ghost" type="button" data-mh-meta-open style="font-size:11px;padding:3px 9px;margin-right:6px" title="Edit the description, swimmer, venue and tags">&#x270E; Info</button>
    <button class="btn ghost mh-ml-qa" type="button" data-qa-url="{_qa_url}"
            aria-haspopup="menu" aria-expanded="false"
            style="font-size:11px;padding:3px 9px;margin-right:6px"
            title="One-click convert — pick a format from the export engine and download the result">&#x21C4; Convert</button>
    <button class="btn danger" type="submit" formaction="{_delete_url}" formnovalidate
            style="font-size:11px;padding:3px 9px"
            onclick="return confirm('Delete this photo from the library? Graphics already rendered keep their copy; the photo just stops being available for new ones.')">Delete</button>
  </td>
</tr>"""
    # P6.3 — "Generate an image" panel. Shown when the imagine seam is
    # importable; the Generate control is disabled (with an honest note)
    # until a provider is actually configured.
    imagine_panel = ""
    if W._imagine_ok:
        _img_avail = W._imagine.is_available()
        _gen_url = url_for("api_imagine_generate")
        from mediahub.media_ai.imagine_providers.gemini_imagine import STYLE_PRESETS

        _style_opts = "".join(
            '<option value="%s">%s</option>' % (_h(s), _h(s.replace("_", " ").title()))
            for s in sorted(STYLE_PRESETS)
        )
        _dis = "" if _img_avail else "disabled"
        _note = (
            ""
            if _img_avail
            # F-3: no env-var names in customer copy — the fix is an
            # operator action, so point the customer at their operator.
            else (
                '<p class="dim" style="margin-bottom:var(--sp-4)">Image generation '
                "isn&rsquo;t switched on for this workspace yet &mdash; ask your "
                "operator to enable it.</p>"
            )
        )
        _imagine_js = (
            "(function(){var go=document.getElementById('mh-imagine-go');if(!go)return;"
            "go.addEventListener('click',function(){"
            "var p=(document.getElementById('mh-imagine-prompt').value||'').trim();"
            "var s=document.getElementById('mh-imagine-status');"
            "if(!p){s.textContent='Enter a prompt first.';return;}"
            "go.disabled=true;s.textContent='Generating\\u2026';"
            "fetch(go.dataset.genUrl,{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify({prompt:p,style:document.getElementById('mh-imagine-style').value,"
            "aspect:document.getElementById('mh-imagine-aspect').value})})"
            ".then(function(r){return r.json().then(function(j){return{ok:r.ok,j:j};});})"
            ".then(function(res){if(res.ok&&res.j.ok){s.textContent='Done \\u2014 added to library.';"
            "location.reload();}else{s.textContent=(res.j&&(res.j.user_message||res.j.error))||"
            "'Generation failed.';go.disabled=false;}})"
            ".catch(function(){s.textContent='Network error.';go.disabled=false;});});})();"
        )
        _gen_hist_url = url_for("media_library_generated_page")
        imagine_panel = (
            '<div class="card" id="mh-imagine">'
            '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:var(--sp-3);flex-wrap:wrap">'
            '<h2 style="margin:0">Generate an image <span class="dim" style="font-weight:400">&middot; AI</span></h2>'
            f'<a href="{_gen_hist_url}">View generated &rarr;</a>'
            "</div>"
            '<p class="dim" style="margin:var(--sp-3) 0 var(--sp-5)">Create a brand-fitting backdrop '
            "or scene from a text prompt. Every image is provenance-stamped as AI-generated "
            "and saved to this library. People are off by default.</p>"
            + _note
            + '<label for="mh-imagine-prompt">Prompt</label>'
            '<input id="mh-imagine-prompt" type="text" '
            'placeholder="e.g. abstract navy and gold poolside backdrop, dynamic light" '
            + _dis
            + ">"
            '<label for="mh-imagine-style">Style</label>'
            '<select id="mh-imagine-style" ' + _dis + ">" + _style_opts + "</select>"
            '<label for="mh-imagine-aspect">Aspect</label>'
            '<select id="mh-imagine-aspect" ' + _dis + ">"
            '<option value="1:1">Square (1:1)</option>'
            '<option value="3:4">Portrait (3:4)</option>'
            '<option value="9:16">Story (9:16)</option>'
            '<option value="16:9">Landscape (16:9)</option>'
            "</select>"
            '<div style="margin-top:var(--sp-4)">'
            '<button type="button" class="btn" id="mh-imagine-go" data-gen-url="'
            + _gen_url
            + '" '
            + _dis
            + ">Generate image &rarr;</button>"
            '<span id="mh-imagine-status" class="dim" style="margin-left:var(--sp-3)"></span>'
            "</div></div><script>" + _imagine_js + "</script>"
        )

    # A success banner after a share-target drop (roadmap 1.22) or a
    # camera/quick upload that round-tripped through ?shared=N&skipped=M.
    try:
        _shared_n = int(_req.args.get("shared") or 0)
    except (TypeError, ValueError):
        _shared_n = 0
    try:
        _skipped_n = int(_req.args.get("skipped") or 0)
    except (TypeError, ValueError):
        _skipped_n = 0
    shared_banner = ""
    if _shared_n > 0 or _skipped_n > 0:
        if _shared_n > 0:
            _sb_msg = (
                f"<strong>{_shared_n} photo{'s' if _shared_n != 1 else ''} added</strong> "
                "to your library."
            )
        else:
            _sb_msg = "<strong>No photos added.</strong>"
        if _skipped_n > 0:
            _sb_msg += (
                f" {_skipped_n} item{'s' if _skipped_n != 1 else ''} skipped "
                "(not a supported image)."
            )
        shared_banner = (
            '<div class="mh-flash" role="status" style="'
            "margin:0 0 var(--sp-5);padding:14px 18px;"
            "border:1px solid color-mix(in oklab, var(--lane) 30%, transparent);"
            "border-left:3px solid var(--accent);"
            "background:color-mix(in oklab, var(--lane) 6%, transparent);color:var(--ink);"
            'border-radius:var(--radius-sm);font-size:13px;line-height:1.5">'
            f"{_sb_msg}</div>"
        )

    # M34 — bulk vision tagging for the photos nothing has tagged yet.
    # Honest availability: with no provider the button is disabled with
    # plain copy (photos stay usable; the manual description flow works).
    describe_panel = ""
    if untagged_n > 0:
        _vision_ok = W._vision_tagging_available()
        _describe_url = url_for("api_media_library_describe_job")
        _btn_disabled = "" if _vision_ok else "disabled"
        _note = (
            "AI looks at each photo and fills in the swimmer (from your roster), "
            "the shot type and scene tags &mdash; you can review or edit "
            "everything afterwards. The automatic photo picker stays "
            "deterministic; this only writes the metadata it reads from."
            if _vision_ok
            else "AI tagging needs a Gemini or Anthropic API key, which isn&rsquo;t "
            "configured on this deployment. Your photos stay fully usable &mdash; "
            "add the swimmer&rsquo;s name in each photo&rsquo;s description instead."
        )
        describe_panel = f"""
<div class="card" id="mh-describe-panel">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:var(--sp-4);flex-wrap:wrap">
    <div>
      <h2 style="margin:0 0 4px">Auto-tag your photos <span class="dim" style="font-weight:400">&middot; AI</span></h2>
      <p class="dim" style="margin:0;max-width:560px">{_note}</p>
    </div>
    <div style="text-align:right">
      <button type="button" class="btn" id="mh-describe-go" data-describe-url="{_h(_describe_url)}" {_btn_disabled}>
        &#10024; Describe {untagged_n} untagged photo{"s" if untagged_n != 1 else ""}</button>
      <div id="mh-describe-status" class="dim" role="status" aria-live="polite" style="margin-top:var(--sp-2);font-size:12px;min-height:1.2em"></div>
    </div>
  </div>
</div>
<script>
(function() {{
  var go = document.getElementById('mh-describe-go');
  if (!go || go.disabled) return;
  var status = document.getElementById('mh-describe-status');
  go.addEventListener('click', function() {{
    go.disabled = true;
    status.textContent = 'Starting…';
    fetch(go.dataset.describeUrl, {{method: 'POST', headers: {{'Accept': 'application/json', 'Content-Type': 'application/json'}}, body: '{{}}'}})
      .then(function(r) {{ return r.json().then(function(j) {{ return {{status: r.status, j: j}}; }}); }})
      .then(function(res) {{
        var j = res.j || {{}};
        if (res.status === 200 && j.status === 'done') {{ status.textContent = j.message || 'Nothing to tag.'; return; }}
        if (res.status !== 202 || !j.poll_url) {{
          go.disabled = false;
          status.textContent = j.user_message || j.error || 'Could not start tagging.';
          return;
        }}
        var poll = function() {{
          fetch(j.poll_url).then(function(r) {{ return r.json(); }}).then(function(s) {{
            if (s.status === 'done') {{ status.textContent = 'Done — reloading…'; location.reload(); return; }}
            if (s.status === 'error') {{
              go.disabled = false;
              status.textContent = s.user_message || s.error || 'Tagging failed.';
              return;
            }}
            status.textContent = 'Tagging ' + (s.done || 0) + ' of ' + (s.total || 0) + (s.current ? (' — ' + s.current) : '') + '…';
            setTimeout(poll, 2500);
          }}).catch(function() {{ setTimeout(poll, 4000); }});
        }};
        setTimeout(poll, 1500);
      }})
      .catch(function() {{ go.disabled = false; status.textContent = 'Network error — try again.'; }});
  }});
}})();
</script>
"""

    body = f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Media library</span>
  <h1>Library</h1>
  <div class="strap" style="margin-top:var(--sp-3)">
    <span>{_h(profile_id)}</span><span class="sep">·</span>
    <span><span data-mh-asset-count>{len(assets):03d}</span> {
            "asset" if len(assets) == 1 else "assets"
        }</span>
  </div>
</section>
{shared_banner}
<div class="card">
  <h2>Upload photos</h2>
  <p class="dim" style="margin-bottom:var(--sp-5)">Reusable photos for branded content cards. Pick several at once &mdash; each upload is parsed for athlete, venue, and event metadata so the engine can pull the right shot into the right moment. On a phone you can take a photo or share one straight from your camera roll into the library.
    No photos of your own yet? <a href="{
            url_for("stock_page")
        }">Find stock photos &rarr;</a> &mdash; licence-clean, saved straight into this library.</p>
  <form id="ml-upload-form" data-mh-capture-form method="POST" action="{
            url_for("api_media_library_upload")
        }" enctype="multipart/form-data" data-loader-text="Uploading photos">
    <label class="req" for="ml-file">Files</label>
    <input id="ml-file" type="file" name="file" accept="image/*" multiple required>
    <input id="ml-capture" type="file" accept="image/*" capture="environment" hidden>
    <label for="ml-desc">Description <span class="dim" style="font-weight:400">(applies to every photo in this batch)</span></label>
    <input id="ml-desc" type="text" name="description" placeholder="e.g. Eira Hughes at Welsh National Open">
    <label for="ml-type">Type</label>
    <select id="ml-type" name="asset_type">
      <option value="athlete_action">Athlete / action photo</option>
      <option value="athlete_headshot">Headshot</option>
      <option value="team_photo">Team</option>
      <option value="venue_photo">Venue</option>
      <option value="logo">Logo</option>
      <option value="other">Other</option>
    </select>
    <input type="hidden" name="profile_id" value="{profile_id}">
    <div style="margin-top:var(--sp-4);display:flex;gap:var(--sp-3);flex-wrap:wrap">
      <button type="submit" class="btn">Upload photo &rarr;</button>
      <button type="button" id="ml-capture-btn" class="btn secondary" hidden>Take photo</button>
    </div>
    <div id="ml-capture-status" class="dim" role="status" aria-live="polite" style="margin-top:var(--sp-3);min-height:1.2em"></div>
  </form>
</div>
{describe_panel}
{imagine_panel}
{
            (
                '<div class="card">'
                '<div class="strap" style="margin-bottom:var(--sp-3)">Browse &middot; drag to scroll</div>'
                '<div class="mh-ds-gallery-wrap">'
                '<div class="mh-drag-scroll" tabindex="0" role="group" '
                'aria-label="Media library photos — drag or scroll to browse">'
                + gallery_items
                + "</div>"
                + W._drag_hint("Drag to explore")
                + "</div></div>"
            )
            if gallery_items
            else ""
        }
<div class="card" data-formats-url="{url_for("api_export_formats")}">
  <div class="strap" style="margin-bottom:var(--sp-3)"><span data-mh-asset-count>{
            len(assets):03d}</span> {"asset" if len(assets) == 1 else "assets"} in library</div>
  <form id="mh-ml-bulk" method="post">
    <div class="mh-bulkbar is-empty" id="mh-ml-bulkbar" role="group" aria-label="Bulk photo actions"
         data-mh-bulkbar="media" data-form="mh-ml-bulk" data-count="mh-ml-count"
         data-select-all="mh-ml-all" data-check="mh-row-check" data-row=".mh-asset-row">
      <span class="mh-bulkbar-count" id="mh-ml-count">0 selected</span>
      <div class="mh-bulkbar-actions">
        <button type="submit" class="btn secondary" data-mh-bulk="approve"
                formaction="{url_for("api_media_library_bulk_approve")}"
                title="Mark these photos ready — the card photo picker prefers them"
                data-confirm="Mark {{n}} selected photo(s) ready for cards?">Mark ready for cards</button>
        <button type="submit" class="btn secondary" data-mh-bulk="unapprove"
                formaction="{url_for("api_media_library_bulk_unapprove")}"
                title="Move these photos back to Draft"
                data-confirm="Move {{n}} selected photo(s) back to Draft?">Unapprove</button>
        <span style="display:inline-flex;gap:6px;align-items:center">
          <select id="mh-ml-collage-layout" name="layout" aria-label="Collage layout"
                  style="font-size:12px;padding:5px 8px;min-height:0">
            <option value="grid_2x2">Grid 2&times;2</option>
            <option value="duo_v">Duo &mdash; side by side</option>
            <option value="duo_h">Duo &mdash; stacked</option>
            <option value="trio_strip">Trio strip</option>
            <option value="trio_feature">Trio feature</option>
            <option value="grid_3x3">Grid 3&times;3</option>
          </select>
          <button type="submit" class="btn secondary" data-mh-bulk="collage"
                  formaction="{url_for("api_media_library_collage")}"
                  title="Pick 2&ndash;9 photos, then compose them into one draft graphic">Make collage</button>
        </span>
        <button type="submit" class="btn secondary" data-mh-bulk="export"
                formaction="{url_for("api_media_library_bulk_export")}">Export ZIP</button>
        <button type="submit" class="btn danger" data-mh-bulk="delete"
                formaction="{url_for("api_media_library_bulk_delete")}"
                data-confirm="Delete {{n}} selected photo(s)? Graphics already rendered keep their copy.">Delete</button>
      </div>
    </div>
    <table class="mh-table-stack" style="width:100%">
      <thead><tr><th class="mh-bulk-cell"><input type="checkbox" id="mh-ml-all" class="mh-check-all" aria-label="Select all photos" title="Select all"></th><th>Preview</th><th>Type</th><th>Athlete</th><th>Venue / Event</th><th>Permission</th><th>Status</th><th>ID</th><th></th></tr></thead>
      <tbody>{
            rows_html
            or (
                '<tr><td colspan="9" style="text-align:center;padding:var(--sp-7);color:var(--ink-muted)">'
                "Couldn&rsquo;t load library assets &mdash; the store wasn&rsquo;t readable. "
                "Uploads above still work; if this persists, ask your operator to check the data volume."
                "</td></tr>"
                if store_failed
                else (
                    '<tr><td colspan="9" style="padding:var(--sp-7)">'
                    '<div style="max-width:520px;margin:0 auto;text-align:left">'
                    '<div style="font-size:14px;font-weight:700;margin-bottom:6px;color:var(--ink)">'
                    "Get your club&rsquo;s photos onto cards in three steps</div>"
                    '<ol style="margin:0;padding-left:20px;font-size:13px;color:var(--ink-dim);line-height:1.7">'
                    "<li><strong>Upload 10+ action and podium shots</strong> from your meets &mdash; you can pick them all in one go.</li>"
                    "<li><strong>Put the swimmer&rsquo;s name in the description</strong> &mdash; or let AI auto-tagging do it for you.</li>"
                    "<li><strong>Best shots are picked automatically</strong> for each card; you can override the photo on any card.</li>"
                    "</ol></div></td></tr>"
                )
            )
        }</tbody>
    </table>
  </form>
</div>

<style>{W._BULK_ACTIONS_CSS}</style>
<script>{W._BULK_ACTIONS_JS}</script>
<script>{W._ML_QUICK_ACTION_JS}</script>
{W._ML_META_EDIT_MODAL}
<style>.mh-safeguard-flag{{outline:2px solid var(--warn);outline-offset:-2px}}</style>
<script>{
            W._ML_META_EDIT_JS.replace(
                "__META_TMPL__",
                url_for("api_media_library_meta", asset_id="__AID__"),
            ).replace("__CSRF__", _h(W._csrf_token()))
        }</script>
<script>{
            W._ML_PERMISSION_JS.replace(
                "__PERM_TMPL__",
                url_for("api_media_library_permission", asset_id="__AID__"),
            ).replace("__CSRF__", _h(W._csrf_token()))
        }</script>
<script src="{
            url_for(
                "static", filename="js/mobile-capture.js", v=W._static_ver("js/mobile-capture.js")
            )
        }"></script>
"""
    return W._layout("Media library", body, active="media")


def media_library_generated_page():
    """Generation history + provenance viewer for this org's AI imagery."""
    if not W._v8_ok:
        return redirect(url_for("media_library_page"))
    pid = W._active_profile_id()
    if not pid:
        return redirect(url_for("media_library_page"))
    try:
        store = W._v8_get_media_store()
        assets = store.list(profile_id=pid, asset_type="ai_generated")
    except Exception:
        assets = []
    _ds_label = {
        "ai_generated": "AI-generated",
        "ai_composite": "AI-edited",
    }
    cards = ""
    for a in assets[:200]:
        ad = a.to_dict() if hasattr(a, "to_dict") else a
        man = (ad.get("description_parsed") or {}).get("imagine") or {}
        file_url = url_for("api_media_library_file", asset_id=ad.get("id", ""))
        op = str(man.get("operation") or "generate")
        model = str(man.get("model") or "")
        prompt = str(man.get("prompt") or ad.get("description_raw") or "")
        dst = _ds_label.get(str(man.get("digital_source_type") or ""), "AI")
        created = str(man.get("created_at") or ad.get("uploaded_at") or "")[:19].replace("T", " ")
        cards += (
            '<figure class="mh-gen-card">'
            f'<a href="{file_url}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="{file_url}" alt="">'
            "</a>"
            "<figcaption>"
            f'<span class="mh-gen-badge">{_h(dst)}</span>'
            f'<span class="mh-gen-op">{_h(op)}</span>'
            f'<p class="mh-gen-prompt">{_h(prompt[:180])}</p>'
            f'<p class="dim mh-gen-meta">{_h(model)}{" · " if model and created else ""}{_h(created)}</p>'
            '<div class="mh-gen-actions">'
            f'<a class="btn secondary" href="{url_for("image_studio_page", asset_id=ad.get("id", ""))}">&#x2726; Edit</a>'
            f'<a class="btn secondary" href="{file_url}" download>Download</a>'
            f'<button type="button" class="btn secondary" data-mh-mockup-open data-asset-id="{_h(ad.get("id", ""))}">Mockups &amp; sticker</button>'
            "</div>"
            "</figcaption></figure>"
        )
    empty = (
        '<div class="card"><p class="dim" style="text-align:center;padding:var(--sp-7)">'
        "No AI-generated images yet. Use &ldquo;Generate an image&rdquo; on the "
        f'<a href="{url_for("media_library_page")}">media library</a> to make one — '
        "every image you create lands here with its provenance.</p></div>"
    )
    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Media library</span>'
        "<h1>Generated images</h1>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f'<span>{_h(pid)}</span><span class="sep">·</span>'
        f"<span>{len(assets)} AI image{'' if len(assets) == 1 else 's'}</span>"
        f'<span class="sep">·</span><a href="{url_for("media_library_page")}">&larr; Library</a>'
        "</div>"
        '<p class="lede" style="margin-top:var(--sp-3)">Every AI-made image, with the '
        "operation, model and prompt that produced it. Each file also carries an embedded "
        "C2PA-class &ldquo;AI&rdquo; provenance tag wherever it travels.</p>"
        "</section>"
        + (f'<div class="mh-gen-grid">{cards}</div>' if cards else empty)
        + f"<style>{W._GENERATED_GALLERY_CSS}</style>"
        + W._ML_MOCKUP_MODAL
        + "<script>"
        + (
            W._ML_MOCKUP_PICKER_JS.replace("__TEMPLATES_URL__", url_for("api_mockup_templates"))
            .replace(
                "__MOCKUP_TMPL__",
                url_for("api_media_library_mockup", asset_id="__AID__", template="__T__"),
            )
            .replace(
                "__STICKER_TMPL__",
                url_for("api_make_sticker", asset_id="__AID__"),
            )
            .replace("__CSRF__", _h(W._csrf_token()))
        )
        + "</script>"
    )
    return W._layout("Generated images", body, active="media")


def media_library_cutout_page(asset_id: str):
    """Before/after cut-out preview (UI2.1).

    Drag the `.mh-compare` slider to see *exactly* what background removal
    knocked out: the original photo on the left, the cut-out (subject on a
    transparency checkerboard) on the right. Fails honestly — if no real
    remover is available it shows the original with a plain explanation,
    never a fake cut-out.
    """
    if not W._v8_ok:
        return W._recovery_page(
            "Media library unavailable",
            "The V8 media engine isn't enabled on this deployment, so cut-out "
            "previews can't be generated. Ask your operator to enable it.",
            eyebrow="Cut-out preview",
            primary_cta=("Back to Create", url_for("make_page")),
            code=503,
        )
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return W._recovery_page(
            "Photo not found",
            "That photo isn't in your library &mdash; it may have been deleted, "
            "or the link might be out of date.",
            eyebrow="Cut-out preview",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=404,
        )
    if not W._session_can_access_profile(a.profile_id):
        return W._recovery_page(
            "Not your photo",
            "This photo belongs to a different organisation, so it isn't "
            "available from your current session.",
            eyebrow="Cut-out preview",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=403,
        )

    ad = a.to_dict() if hasattr(a, "to_dict") else dict(a)
    subject = (
        ", ".join(ad.get("linked_athlete_names") or [])
        or ad.get("linked_venue")
        or ad.get("linked_event")
        or ad.get("filename")
        or "this photo"
    )
    orig_url = url_for("api_media_library_file", asset_id=a.id)
    cutout_url = url_for("api_media_library_cutout", asset_id=a.id)
    back_url = url_for("media_library_page")

    # Pixel-perfect alignment: size the slider to the photo's own aspect
    # ratio so the before/after halves line up. Falls back to a portrait
    # default when the file can't be measured (e.g. a placeholder blob).
    aspect = "4 / 5"
    try:
        from PIL import Image

        with Image.open(a.path) as _im:
            _iw, _ih = _im.size
        if _iw > 0 and _ih > 0:
            aspect = f"{_iw} / {_ih}"
    except Exception:
        pass

    path, status = W._v8_ensure_cutout(a)

    hero = (
        '<section class="mh-hero" data-lane="" '
        'style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Cut-out preview</span>'
        f"<h1>{_h(subject)}</h1>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f'<span>{_h(ad.get("type", "photo"))}</span><span class="sep">·</span>'
        "<span>before &rarr; after background removal</span>"
        "</div>"
        "</section>"
    )

    if path is not None:
        provider = W._cutout_provider_label()
        compare = (
            '<div class="card">'
            '<p class="dim" style="margin-bottom:var(--sp-4)">'
            "Drag the handle to wipe between the original photo (left) and the "
            "cut-out (right). The checkerboard is transparency &mdash; that&rsquo;s "
            "exactly what was removed."
            "</p>"
            '<figure class="mh-compare" data-mh-pos="50" '
            'aria-label="Before and after background removal" '
            f'style="aspect-ratio:{aspect};max-width:560px;width:100%;margin:0 auto">'
            f'<img src="{orig_url}" alt="Original photo of {_h(subject)}, background intact" />'
            '<div class="mh-compare__after mh-compare__after--checker">'
            f'<img src="{cutout_url}" alt="{_h(subject)} with the background removed" />'
            "</div>"
            '<div class="mh-compare__handle"></div>'
            "</figure>"
            '<p class="dim" style="margin-top:var(--sp-4);font-size:13px">'
            f"Cut out by {_h(provider)} on MediaHub&rsquo;s servers &mdash; the same "
            "background removal composited into your branded graphics."
            "</p>"
            "</div>"
        )
        body = hero + compare
    else:
        # Honest fallback — no fabricated cut-out (CLAUDE.md honest-error rule).
        if status == "unavailable":
            detail = (
                "Background removal isn&rsquo;t available on this deployment, so "
                "there&rsquo;s no cut-out to compare yet. Your operator can enable it "
                "(the on-server rembg model, or a Photoroom / Replicate key). The "
                "original photo is shown below."
            )
        elif status == "no_source":
            detail = (
                "The original file for this photo is missing, so there&rsquo;s "
                "nothing to preview. Try re-uploading it to the library."
            )
        else:  # failed
            detail = (
                "We couldn&rsquo;t produce a cut-out for this photo. The original is "
                "shown below &mdash; a clearer subject-on-background shot usually cuts "
                "out cleanly."
            )
        note = (
            '<div class="card">'
            '<div role="status" class="mh-ai-unavailable" '
            'style="margin-bottom:var(--sp-4);padding:14px 18px;'
            "background:var(--warn-bg);border:1px solid rgba(255,180,84,0.30);"
            "border-left:3px solid var(--warn);border-radius:var(--radius-sm);"
            "font-family:var(--font-body);font-size:13px;color:var(--ink);"
            'display:flex;align-items:flex-start;gap:var(--sp-3);flex-wrap:wrap">'
            f"{W._AI_UNAVAILABLE_ICON}"
            '<span class="strap" style="color:var(--warn)">No cut-out to show</span>'
            f'<span style="color:var(--ink-dim)">{detail}</span>'
            "</div>"
        )
        if status != "no_source":
            note += (
                f'<img src="{orig_url}" alt="Original photo of {_h(subject)}" '
                f'style="max-width:560px;width:100%;border-radius:var(--radius-md);display:block" />'
            )
        note += "</div>"
        body = hero + note

    body += (
        '<div style="margin-top:var(--sp-5);display:flex;gap:var(--sp-3);flex-wrap:wrap">'
        f'<a class="btn ghost" href="{back_url}">&larr; Back to library</a>'
        f'<a class="btn secondary" href="{url_for("image_studio_page", asset_id=a.id)}">'
        "&#x2726; Open in image studio</a>"
        # C-14 — a cut-out is the ideal sticker/mockup source, so offer the
        # picker here (the make-sticker API's other UI home).
        f'<button type="button" class="btn secondary" data-mh-mockup-open data-asset-id="{_h(a.id)}">Mockups &amp; sticker</button>'
        "</div>"
        + W._ML_MOCKUP_MODAL
        + "<script>"
        + (
            W._ML_MOCKUP_PICKER_JS.replace("__TEMPLATES_URL__", url_for("api_mockup_templates"))
            .replace(
                "__MOCKUP_TMPL__",
                url_for("api_media_library_mockup", asset_id="__AID__", template="__T__"),
            )
            .replace("__STICKER_TMPL__", url_for("api_make_sticker", asset_id="__AID__"))
            .replace("__CSRF__", _h(W._csrf_token()))
        )
        + "</script>"
    )
    return W._layout("Cut-out preview", body, active="media")


def image_studio_page(asset_id: str):
    """Roadmap 1.2 — the generative-imagery studio for one library asset.

    The mask-brush / expand surface in front of the shipped ``imagine`` edit
    family (edit/fill/remove/expand/upscale/style_match/similar) plus the
    deterministic subject-lift and vision grab-text. All page logic lives in
    the Flask-free ``image_studio`` helper so it unit-tests without a request;
    this route only enforces tenancy, measures the asset, resolves the
    ``url_for(...)`` endpoints, and wraps the body with ``_layout``. The
    provider-backed ops still honest-error (and the panels stay hidden) when
    no image backend is configured — capabilities are probed at runtime.
    """
    if not (W._v8_ok and W._imagine_ok):
        return W._recovery_page(
            "Image studio unavailable",
            "The generative-imagery engine isn't enabled on this deployment, so "
            "the image studio can't open. Other parts of MediaHub still work.",
            eyebrow="Image studio",
            primary_cta=("Back to Create", url_for("make_page")),
            secondary_cta=("Media library", url_for("media_library_page")),
            code=503,
        )
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return W._recovery_page(
            "Photo not found",
            "That photo isn't in your library &mdash; it may have been deleted, "
            "or the link might be out of date.",
            eyebrow="Image studio",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=404,
        )
    if not W._session_can_access_profile(a.profile_id):
        return W._recovery_page(
            "Not your photo",
            "This photo belongs to a different organisation, so it isn't "
            "available from your current session.",
            eyebrow="Image studio",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=403,
        )

    ad = a.to_dict() if hasattr(a, "to_dict") else dict(a)
    label = (
        ", ".join(ad.get("linked_athlete_names") or [])
        or ad.get("linked_venue")
        or ad.get("linked_event")
        or ad.get("filename")
        or "this photo"
    )
    width = int(ad.get("width") or 0)
    height = int(ad.get("height") or 0)
    if not (width and height):
        try:
            from PIL import Image as _Image

            with _Image.open(a.path) as _im:
                width, height = int(_im.width), int(_im.height)
        except Exception:
            width = height = 0

    from mediahub.web import image_studio as _studio

    body = _studio.render_studio_body(
        asset_id=a.id,
        asset_label=label,
        asset_type=str(ad.get("type") or "photo"),
        asset_url=url_for("api_media_library_file", asset_id=a.id),
        info_url=url_for("api_imagine_info"),
        op_url_base=url_for("api_imagine_asset_op", asset_id=a.id, op=_studio.OP_SENTINEL),
        grab_text_url=url_for("api_imagine_grab_text", asset_id=a.id),
        subject_lift_url=url_for("api_imagine_subject_lift", asset_id=a.id),
        cutout_url=url_for("api_media_library_cutout", asset_id=a.id),
        studio_url_base=url_for("image_studio_page", asset_id=_studio.ASSET_SENTINEL),
        file_url_base=url_for("api_media_library_file", asset_id=_studio.ASSET_SENTINEL),
        back_url=url_for("media_library_page"),
        gen_history_url=url_for("media_library_generated_page"),
        width=width,
        height=height,
    )
    return W._layout("Image studio", body, active="media")


def photo_editor_page(asset_id: str):
    """The standalone photo-editor page for one library asset."""
    if not W._v8_ok:
        return W._recovery_page(
            "Photo editor unavailable",
            "The media library isn't enabled on this deployment, so the photo "
            "editor can't open.",
            eyebrow="Photo editor",
            primary_cta=("Back to Create", url_for("make_page")),
            code=503,
        )
    store = W._v8_get_media_store()
    a = store.get(asset_id)
    if not a:
        return W._recovery_page(
            "Photo not found",
            "That photo isn't in your library &mdash; it may have been deleted.",
            eyebrow="Photo editor",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=404,
        )
    if not W._session_can_access_profile(a.profile_id):
        return W._recovery_page(
            "Not your photo",
            "This photo belongs to a different organisation.",
            eyebrow="Photo editor",
            primary_cta=("Back to library", url_for("media_library_page")),
            code=403,
        )

    ad = a.to_dict() if hasattr(a, "to_dict") else dict(a)
    label = (
        ", ".join(ad.get("linked_athlete_names") or [])
        or ad.get("linked_venue")
        or ad.get("linked_event")
        or ad.get("filename")
        or "this photo"
    )
    width = int(ad.get("width") or 0)
    height = int(ad.get("height") or 0)
    if not (width and height):
        try:
            from PIL import Image as _Image

            with _Image.open(a.path) as _im:
                width, height = int(_im.width), int(_im.height)
        except Exception:
            width = height = 0

    from mediahub.media_library import photo_edit as _pe
    from mediahub.web import photo_editor as _editor

    bk = W._v8_brand_kit_for(a.profile_id) if a.profile_id else None
    brand_shadow = (getattr(bk, "primary_colour", None) or "#0b1020") if bk else "#0b1020"

    body = _editor.render_editor_body(
        asset_id=a.id,
        asset_label=label,
        asset_type=str(ad.get("type") or "photo"),
        asset_url=url_for("api_media_library_file", asset_id=a.id),
        edited_url=url_for("api_media_library_edited", asset_id=a.id),
        apply_url=url_for("api_photo_edit_apply", asset_id=a.id),
        preview_url=url_for("api_photo_edit_preview", asset_id=a.id),
        enhance_url=url_for("api_photo_edit_enhance", asset_id=a.id),
        reset_url=url_for("api_photo_edit_reset", asset_id=a.id),
        profile_pic_url=url_for("api_photo_profile_picture", asset_id=a.id),
        back_url=url_for("media_library_page"),
        studio_url=url_for("image_studio_page", asset_id=a.id) if W._imagine_ok else "",
        cutout_url=url_for("media_library_cutout_page", asset_id=a.id),
        annotate_url=url_for("annotate_page", asset_id=a.id),
        width=width,
        height=height,
        brand_shadow=brand_shadow,
        brand_highlight="#f5f7ff",
        has_edit=_pe.has_edit(a),
        recipe=_pe.recipe_for_asset(a).to_dict(),
    )
    return W._layout("Photo editor", body, active="media")


def elements_page():
    """Standalone Elements browser. ?run_id=&card_id= enables add-to-card."""
    from flask import request as _req
    from mediahub.elements import catalog as _el_catalog
    from mediahub.elements import gradients as _el_grad
    from mediahub.elements import search as _el_search
    from mediahub.web import elements_browser as _eb

    profile_id = W._active_profile_id()
    role_vars = W._elements_role_vars(profile_id)
    seed = [
        W._element_to_payload(el, role_vars, profile_id)
        for el in _el_catalog.load_catalog(profile_id)
    ]
    grad = [
        {"name": p.name, "css": _el_grad.gradient_css(p, role_vars)}
        for p in _el_grad.list_presets()
    ]

    run_id = (_req.args.get("run_id") or "").strip()
    card_id = (_req.args.get("card_id") or "").strip()
    add_url = list_url = suggest_url = ""
    card_label = card_url = ""
    if run_id and card_id:
        run_data = W._load_run(run_id)
        if run_data and W._can_access_run(run_id, run_data, profile_id):
            add_url = url_for("api_card_elements", run_id=run_id, card_id=card_id)
            list_url = add_url
            suggest_url = url_for("api_element_suggestions", run_id=run_id, card_id=card_id)
            card_label = card_id
            # C-12: the add-to-card toast links straight back to the
            # card's review page so "Added" isn't a dead end.
            card_url = url_for("review", run_id=run_id)

    body = _eb.render_browser_body(
        elements=seed,
        kinds=_el_catalog.list_kinds(profile_id),
        gradients=grad,
        semantic=_el_search.is_semantic_available(),
        search_url=url_for("api_elements"),
        add_url=add_url,
        list_url=list_url,
        suggest_url=suggest_url,
        card_label=card_label,
        stock_url=url_for("stock_page"),
        # C-12: browse-only visits get an explainer + a route into the
        # card flow (Activity lists the processed meets).
        activity_url=url_for("activity_page"),
        card_url=card_url,
    )
    return W._layout("Elements", body, active="elements")


def stock_page():
    """Standalone licence-clean stock browser (search → add to library)."""
    from mediahub.elements import stock as _stock
    from mediahub.web import elements_browser as _eb

    body = _eb.render_stock_body(
        search_url=url_for("api_stock_search"),
        import_url=url_for("api_import_stock"),
        proxy_url=url_for("api_stock_thumb"),
        sources=_stock.available_sources(),
    )
    return W._layout("Stock", body, active="media")


def public_wall_settings():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    from mediahub.web import public_wall as _pw

    enabled = bool(prof.public_wall_enabled and prof.public_wall_token)
    consent_hidden: list[dict] = []
    cards = _pw.wall_cards(prof, consent_hidden=consent_hidden) if enabled else []
    excluded = set(prof.public_wall_excluded_cards or [])

    if enabled:
        wall_url = url_for("public_wall_page", token=prof.public_wall_token, _external=True)
        embed_url = url_for("public_wall_embed", token=prof.public_wall_token, _external=True)
        rss_url = url_for("public_wall_rss", token=prof.public_wall_token, _external=True)
        json_url = url_for("public_wall_json", token=prof.public_wall_token, _external=True)
        snippet = _h(
            f'<iframe src="{embed_url}" style="width:100%;height:640px;border:0" '
            f'title="{prof.display_name} — latest achievements"></iframe>'
        )
        card_rows = ""
        for c in cards[:30]:
            key = _pw.card_key(c["run_id"], c["card_id"])
            card_rows += (
                "<tr>"
                f"<td>{_h(c['title'])}</td><td class='dim'>{_h(c['meet_name'])}</td>"
                f'<td><form method="post" action="{url_for("public_wall_update")}" style="margin:0">'
                f'<input type="hidden" name="action" value="exclude">'
                f'<input type="hidden" name="card_key" value="{_h(key)}">'
                '<button type="submit" class="btn secondary" style="font-size:12px;padding:3px 10px">Hide</button>'
                "</form></td></tr>"
            )
        # F-12: resolve the excluded keys to card titles + meet names so the
        # "Hidden cards" list matches the visible table, instead of opaque
        # run_id::card_id strings that make "Show again" a guessing game.
        _excluded_labels = _pw.card_labels(prof, excluded)
        excluded_rows = ""
        for key in sorted(excluded):
            _lbl = _excluded_labels.get(key)
            if _lbl:
                _name_cell = (
                    f"<td>{_h(_lbl['title'])}</td><td class='dim'>{_h(_lbl['meet_name'])}</td>"
                )
            else:
                # The run no longer exists — fall back to the raw key.
                _name_cell = f"<td colspan='2'><code>{_h(key)}</code></td>"
            excluded_rows += (
                f"<tr>{_name_cell}"
                f'<td><form method="post" action="{url_for("public_wall_update")}" style="margin:0">'
                f'<input type="hidden" name="action" value="include">'
                f'<input type="hidden" name="card_key" value="{_h(key)}">'
                '<button type="submit" class="btn secondary" style="font-size:12px;padding:3px 10px">Show again</button>'
                "</form></td></tr>"
            )
        consent_hidden_rows = ""
        for h_item in consent_hidden:
            from mediahub.safeguarding.consent import LEVEL_LABELS as _cl

            label = _cl.get(h_item["level"], h_item["level"])
            consent_hidden_rows += (
                f"<tr><td>{_h(h_item['athlete'])}</td>"
                f"<td class='dim'>{_h(label)}</td>"
                f"<td class='dim'>{_h(h_item['reason'])}</td></tr>"
            )
        consent_hidden_block = ""
        if consent_hidden_rows:
            consent_hidden_block = f"""
<div class="card" style="margin-bottom:20px;border-left:3px solid var(--warn)">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Held off the wall by consent ({len(consent_hidden)})</h3>
  <p class="dim" style="font-size:13px">These approved cards never appear on the public wall,
  the embed or the feeds because the athlete's recorded consent does not allow it. Update the
  consent registry to change this — the wall follows it automatically.</p>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
  <thead><tr style="text-align:left"><th>Athlete</th><th>Consent</th><th>Why hidden</th></tr></thead>
  <tbody>{consent_hidden_rows}</tbody></table>
</div>"""
        initials_checked = "checked" if prof.public_wall_initials_only else ""
        status_block = f"""
<div class="card" style="margin-bottom:20px">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Your public wall is live</h3>
  <p style="font-size:14px">Public page: <a href="{_h(wall_url)}" target="_blank" rel="noopener">{_h(wall_url)}</a></p>
  <p style="font-size:13px" class="dim">RSS: <code>{_h(rss_url)}</code> &middot; JSON: <code>{_h(json_url)}</code></p>
  <p style="font-size:13px;margin-bottom:6px">Embed on your club website:</p>
  <pre style="white-space:pre-wrap;font-size:12px;background:var(--bg);padding:10px;border-radius:8px;border:1px solid var(--border)">{snippet}</pre>
  <form method="post" action="{url_for("public_wall_update")}" style="display:flex;gap:14px;align-items:center;margin-top:10px">
    <input type="hidden" name="action" value="settings">
    <label style="font-size:13px"><input type="checkbox" name="initials_only" {initials_checked}>
      Initials-only names for everyone (per-athlete consent from your registry is always
      enforced on top &mdash; this blanket setting can only tighten it further)</label>
    <button type="submit" class="btn secondary" style="font-size:12px">Save</button>
  </form>
  <form method="post" action="{url_for("public_wall_update")}" style="margin-top:14px"
        onsubmit="return mhWallOffConfirm(this)">
    <input type="hidden" name="action" value="disable">
    <button type="submit" class="btn secondary">Unpublish &amp; revoke link</button>
  </form>
</div>
<div class="card" style="margin-bottom:20px">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Cards on the wall ({len(cards)})</h3>
  <table style="width:100%;border-collapse:collapse;font-size:13px"><tbody>
  {card_rows or '<tr><td class="dim" style="padding:12px">No approved, rendered cards yet — approve cards in the review queue and generate their graphics.</td></tr>'}
  </tbody></table>
</div>
{consent_hidden_block}
<div class="card">
  <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Hidden cards</h3>
  <table style="width:100%;border-collapse:collapse;font-size:13px"><tbody>
  {excluded_rows or '<tr><td class="dim" style="padding:12px">None hidden.</td></tr>'}
  </tbody></table>
</div>"""
        # E-12: switching off clears the token, so every shared URL,
        # embed, feed and QR code dies permanently (re-enabling mints a
        # NEW link). That deserves an explicit confirm — styled
        # MH.confirm where loaded, native confirm fallback. Plain string
        # (not an f-string) so the JS braces stay single.
        status_block += """
<script>
function mhWallOffConfirm(f) {
  if (f.dataset.mhConfirmed === '1') { f.dataset.mhConfirmed = ''; return true; }
  var body = 'Your public link, website embed, feeds and any QR codes will stop working. Switching back on creates a DIFFERENT link.';
  if (window.MH && MH.confirm) {
    MH.confirm({
      title: 'Switch off the public wall?',
      body: body,
      confirmText: 'Switch off & revoke',
      onConfirm: function() {
        f.dataset.mhConfirmed = '1';
        if (f.requestSubmit) f.requestSubmit(); else f.submit();
      }
    });
    return false;
  }
  return confirm('Switch off the public wall? ' + body);
}
</script>"""
    else:
        status_block = f"""
<div class="card empty">
  <p><b>Your public wall is not published.</b> Publishing it creates an unguessable public link
  showing only your <i>approved</i> cards — a celebration page you can share or embed in
  the club website. Names display as initials by default. Unpublishing later revokes
  the link immediately.</p>
  <form method="post" action="{url_for("public_wall_update")}">
    <input type="hidden" name="action" value="enable">
    <button type="submit" class="btn">Publish wall</button>
  </form>
</div>"""

    body = f"""
<h1 style="margin-bottom:4px">Public achievements wall</h1>
<p class="dim" style="margin-bottom:20px;max-width:640px">A free public celebration page
of your approved cards, plus a website embed and RSS/JSON feed. Only cards you approved
ever appear; queued, edited and rejected cards never do.</p>
{status_block}
"""
    return W._layout("Public wall", body, active="home")


def public_wall_update():
    prof = W._active_profile()
    if prof is None:
        return redirect(url_for("organisation_setup"))
    from mediahub.web import public_wall as _pw

    action = (request.form.get("action") or "").strip()
    if action == "enable":
        prof.public_wall_enabled = True
        if not prof.public_wall_token:
            prof.public_wall_token = _pw.generate_token()
    elif action == "disable":
        # Revocation is structural: the token is cleared, so the old
        # URL resolves to nothing (404), not to an "off" page.
        prof.public_wall_enabled = False
        prof.public_wall_token = ""
    elif action == "settings":
        # HTML checkbox truthiness — "on" or absent, never a NaN literal.
        # (pre-existing web.py body exposed to semgrep by the #15 carve.)
        # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
        prof.public_wall_initials_only = bool(request.form.get("initials_only"))
    elif action in ("exclude", "include"):
        key = (request.form.get("card_key") or "").strip()
        current = set(prof.public_wall_excluded_cards or [])
        if action == "exclude" and key:
            current.add(key)
        elif action == "include":
            current.discard(key)
        prof.public_wall_excluded_cards = sorted(current)
    else:
        return redirect(url_for("public_wall_settings"))
    W.save_profile(prof)
    return redirect(url_for("public_wall_settings"))


def public_wall_page(token: str):
    from mediahub.web import public_wall as _pw

    prof = W._resolve_wall_or_404(token)
    resp = make_response(W._wall_page_html(prof, _pw.wall_cards(prof), token, embed=False))
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def public_wall_embed(token: str):
    from mediahub.web import public_wall as _pw

    prof = W._resolve_wall_or_404(token)
    resp = make_response(W._wall_page_html(prof, _pw.wall_cards(prof), token, embed=True))
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def public_wall_json(token: str):
    from mediahub.web import public_wall as _pw

    prof = W._resolve_wall_or_404(token)
    cards = _pw.wall_cards(prof)
    items = [
        {
            "title": c["title"],
            "meet": c["meet_name"],
            "image": url_for(
                "public_wall_card_png",
                token=token,
                run_id=c["run_id"],
                card_id=c["card_id"],
                _external=True,
            ),
            "alt": c["alt_text"],
        }
        for c in cards
    ]
    resp = jsonify({"club": prof.display_name, "items": items, "powered_by": "MediaHub"})
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def public_wall_rss(token: str):
    from xml.sax.saxutils import escape as _xml_escape

    from mediahub.web import public_wall as _pw

    prof = W._resolve_wall_or_404(token)
    cards = _pw.wall_cards(prof)
    wall_url = url_for("public_wall_page", token=token, _external=True)
    items_xml = ""
    for c in cards:
        img = url_for(
            "public_wall_card_png",
            token=token,
            run_id=c["run_id"],
            card_id=c["card_id"],
            _external=True,
        )
        title = _xml_escape(c["title"] + (f" — {c['meet_name']}" if c["meet_name"] else ""))
        items_xml += (
            "<item>"
            f"<title>{title}</title>"
            f"<link>{_xml_escape(wall_url)}</link>"
            f'<guid isPermaLink="false">{_xml_escape(img)}</guid>'
            f'<enclosure url="{_xml_escape(img)}" type="image/png"/>'
            f"<description>{_xml_escape(c['alt_text'])}</description>"
            "</item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{_xml_escape(prof.display_name)} — achievements</title>"
        f"<link>{_xml_escape(wall_url)}</link>"
        "<description>Approved achievement cards, powered by MediaHub</description>"
        f"{items_xml}"
        "</channel></rss>"
    )
    resp = make_response(rss)
    resp.headers["Content-Type"] = "application/rss+xml; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def public_wall_card_png(token: str, run_id: str, card_id: str):
    from flask import send_file

    from mediahub.web import public_wall as _pw

    prof = W._resolve_wall_or_404(token)
    path = _pw.wall_image_path(prof, run_id, card_id)
    if not path:
        abort(404)
    resp = make_response(send_file(path, mimetype="image/png"))
    # Match the page/feed TTL (max-age=300) and require revalidation. On a
    # children's-data surface where consent can be withdrawn or a card hidden
    # at any moment, a 1-hour public cache could keep serving a withdrawn
    # child's card image long after it should be gone.
    resp.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
    return resp


# PC.7 — instant try-before-signup demo.
# A stranger drops a results file (or one click on the bundled sample
# meet) and gets a watermarked ≤3-card preview with captions and the
# "why this card" explainer — no account. Per-IP + global daily caps,
# demo runs live only under the sandboxed unbound demo org, PB
# web-verification is skipped for anonymous runs, and a daily sweep
# deletes old demo runs. The signup CTA carries the run so a
# converting club keeps its preview.
# The bundled sample is SYNTHETIC (scripts/make_demo_sample.py): every
# swimmer, club and meet is fictional. The public demo must never ship
# real children's data — Children's-Code pass, PC.12
# (docs/compliance/CHILDRENS_CODE_PASS.md).
def try_demo():
    from mediahub.web import demo_try as _demo

    if not _demo.demo_enabled():
        abort(404)
    if request.method == "GET":
        return W._try_form_page()

    # ---- POST: take the file (or the bundled sample) ----
    if (request.form.get("sample") or "") == "1":
        if not W._DEMO_SAMPLE_PATH.exists():
            return W._try_form_page("The sample meet isn't available on this deployment.")
        file_bytes = W._DEMO_SAMPLE_PATH.read_bytes()
        file_name = W._DEMO_SAMPLE_PATH.name
    else:
        f = request.files.get("file")
        if f is None or not (f.filename or "").strip():
            return W._try_form_page("Choose a results file first.")
        file_name = os.path.basename(f.filename or "results.bin")
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in _demo.ALLOWED_EXTENSIONS:
            return W._try_form_page(
                "That file type isn't supported. Use a Hy-Tek PDF, HY3, ZIP, or spreadsheet."
            )
        file_bytes = f.read(_demo.MAX_UPLOAD_BYTES + 1)
        if len(file_bytes) > _demo.MAX_UPLOAD_BYTES:
            return W._try_form_page("That file is too large for the demo (15 MB max).")
        if not file_bytes:
            return W._try_form_page("That file is empty.")

    # ---- caps: one claim per uploaded file ----
    allowed, reason = _demo.claim_demo_slot(W._client_ip())
    if not allowed:
        return W._try_form_page(reason)

    # ---- light parse for the club picker (same as the real upload) ----
    clubs: list[str] = []
    meet_name = ""
    try:
        from mediahub.interpreter import interpret_document

        interpreted = interpret_document(file_bytes, hint=None)
        seen: set[str] = set()
        for ev in interpreted.events:
            for sw in ev.swims:
                c = (sw.club or "").strip()
                if c and c.lower() not in seen:
                    seen.add(c.lower())
                    clubs.append(c)
        clubs.sort(key=str.lower)
        meet_name = interpreted.meet_name or ""
    except Exception as exc:
        # D-23: keep the raw parser exception operator-only. The anonymous
        # demo is the top of the acquisition funnel — a first-time visitor
        # must never see a Python traceback or "Parser said: <exception>".
        W.log.warning("try-demo parse failed: %s", exc, exc_info=True)
    if not clubs:
        inner = f"""
<h1>We couldn't read that file</h1>
<div class="card" style="max-width:560px">
  <p>It doesn't look like a meet results file we can parse (Hy-Tek PDF, HY3, or a ZIP of
  one). Entry lists and heat sheets won't work — it needs finished results.</p>
  <p class="dim" style="font-size:13px">Double-check it's a finished-results export and
  try again — or use the sample meet to see how it works.</p>
  <a class="btn" href="{url_for("try_demo")}">&larr; Try another file</a>
</div>"""
        return W._try_page(inner)

    # ---- stage the file + show the one-question club picker ----
    temp_id = uuid.uuid4().hex[:12]
    tmp_dir = W.RUNS_DIR / temp_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "input.bin").write_bytes(file_bytes)
    (tmp_dir / "demo_meta.json").write_text(
        json.dumps({"filename": file_name, "clubs": clubs, "meet_name": meet_name}),
        encoding="utf-8",
    )
    pending = session.get("demo_pending")
    pending = list(pending) if isinstance(pending, list) else []
    session["demo_pending"] = (pending + [temp_id])[-5:]

    opts = "".join(f'<option value="{_h(c)}">{_h(c)}</option>' for c in clubs[:400])
    meet_line = f'<p class="dim">Meet: <b>{_h(meet_name)}</b></p>' if meet_name else ""
    inner = f"""
<h1>One question: which club is yours?</h1>
{meet_line}
<div class="card" style="max-width:560px">
  <form method="post" action="{url_for("try_demo_start")}" style="display:flex;flex-direction:column;gap:14px">
    <input type="hidden" name="temp_id" value="{_h(temp_id)}">
    <label style="font-size:14px">Your club in this meet<br>
      <select name="club" required style="width:100%">{opts}</select></label>
    <button type="submit" class="btn">Generate my preview &rarr;</button>
  </form>
</div>"""
    return W._try_page(inner)


def try_demo_start():
    from mediahub.web import demo_try as _demo

    if not _demo.demo_enabled():
        abort(404)
    temp_id = (request.form.get("temp_id") or "").strip()
    pending = session.get("demo_pending")
    pending = list(pending) if isinstance(pending, list) else []
    if not re.fullmatch(r"[a-f0-9]{12}", temp_id) or temp_id not in pending:
        abort(404)
    tmp_dir = W.RUNS_DIR / temp_id
    try:
        meta = json.loads((tmp_dir / "demo_meta.json").read_text(encoding="utf-8"))
        file_bytes = (tmp_dir / "input.bin").read_bytes()
    except Exception:
        abort(404)
    club = (request.form.get("club") or "").strip()
    if club not in (meta.get("clubs") or []):
        abort(400)

    _demo.ensure_demo_profile()
    # Demo restriction: PB web-verification is OFF for anonymous runs
    # (fetch_pbs=False) — no third-party calls on unauthenticated traffic.
    run_id = W._start_run(
        file_bytes,
        meta.get("filename") or "demo-results.bin",
        _demo.DEMO_PROFILE_ID,
        True,  # use_pb_cache
        False,  # fetch_pbs — never web-verify for anonymous demo runs
        club_filter=club,
    )
    session["demo_pending"] = [t for t in pending if t != temp_id]
    session["demo_runs"] = (W._demo_session_runs() + [run_id])[-5:]
    try:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass
    return redirect(url_for("try_demo_run", run_id=run_id))


def try_demo_run(run_id: str):
    state = W._demo_run_or_404(run_id)
    if state["status"] in ("queued", "running"):
        # D-23: an animated indeterminate bar instead of a blank wait, so a
        # first-time visitor sees the demo is working rather than a stalled
        # page that silently reloads.
        inner = """
<h1>Reading your results&hellip;</h1>
<div class="card" style="max-width:560px">
  <p>MediaHub is parsing the file, detecting achievements, and ranking what's worth
  posting. This usually takes under a minute.</p>
  <div style="height:6px;border-radius:999px;background:var(--hairline);overflow:hidden;margin:14px 0 4px">
    <div style="height:100%;width:40%;border-radius:999px;background:var(--lane);
                animation:mhTryBar 1.4s ease-in-out infinite"></div>
  </div>
  <p class="dim" style="font-size:13px">This page updates itself &mdash; no need to refresh.</p>
</div>
<style>@keyframes mhTryBar{0%{margin-left:-40%}100%{margin-left:100%}}</style>
<script>setTimeout(function () { location.reload(); }, 3000);</script>"""
        return W._try_page(inner, title="Working…")
    if state["status"] != "done":
        # D-23: log the raw pipeline error operator-only; the anonymous
        # visitor sees plain-language copy, never a traceback.
        W.log.warning("try-demo run %s failed: %s", run_id, (state.get("error") or "")[:500])
        inner = f"""
<h1>That run didn't finish</h1>
<div class="card" style="max-width:560px">
  <p>Something went wrong while we were processing that file. It might be a partial or
  unusual export &mdash; try another results file, or use the sample meet.</p>
  <a class="btn" href="{url_for("try_demo")}">&larr; Try another file</a>
</div>"""
        return W._try_page(inner, title="Demo run failed")

    cards = W._demo_top_cards(run_id)
    if not cards:
        inner = f"""
<h1>No achievements detected for that club</h1>
<div class="card" style="max-width:560px">
  <p>The file parsed, but the recognition engine found nothing card-worthy for the club
  you picked — that can happen with small entries or DNF-heavy meets.</p>
  <a class="btn" href="{url_for("try_demo")}">&larr; Try another file or club</a>
</div>"""
        return W._try_page(inner, title="Nothing to show")

    # Captions via the existing brand-template path (deterministic), and
    # the same "why this card" explainer the product shows. Both honest:
    # the explainer says so when no AI provider is configured.
    from mediahub.web import demo_try as _demo

    demo_prof = _demo.ensure_demo_profile()
    kit = demo_prof.get_brand_kit()
    tone = demo_prof.get_tone()
    sections = ""
    for c in cards:
        ach = c["achievement"]
        caption = ""
        try:
            from mediahub.brand.apply import apply_brand

            branded = apply_brand(dict(c["ra"]), kit, tone, "meet_recap", {})
            active = branded.get("active_caption") or {}
            caption = " ".join(
                str(v).strip() for v in active.values() if isinstance(v, str) and v.strip()
            )
        except Exception:
            caption = ""
        explanation = {}
        try:
            explanation = W._build_card_explanation(c["ra"]) or {}
        except Exception:
            explanation = {}
        # U.7 — the same source-grounded "focus the facts" highlight the
        # logged-in review uses, on the public preview: the athlete, event,
        # time and PB/medal markers light up in both the caption and the
        # reasoning so the demo reads as the intelligence layer it is.
        _demo_facts = W._card_facts(ach)
        why_bits = ""
        if explanation.get("headline"):
            why_bits += (
                f"<p style='margin:6px 0'><b>"
                f"{W._focus_facts_html(explanation['headline'], phrases=_demo_facts)}</b></p>"
            )
        for b in (explanation.get("bullets") or [])[:3]:
            why_bits += (
                f'<p class="dim" style="font-size:13px;margin:2px 0">&bull; '
                f"{W._focus_facts_html(b, phrases=_demo_facts)}</p>"
            )
        if explanation.get("ai_error"):
            why_bits += (
                f'<p class="dim" style="font-size:12px">AI explainer unavailable: '
                f"{_h(explanation['ai_error'])}</p>"
            )
        img_url = url_for("try_demo_card_png", run_id=run_id, card_id=c["card_id"])
        caption_html = (
            f'<p style="font-size:14px;white-space:pre-wrap">'
            f"{W._focus_facts_html(caption, phrases=_demo_facts)}</p>"
            if caption
            else ""
        )
        title = " — ".join(
            b
            for b in (
                str(ach.get("swimmer_name") or "").strip(),
                str(ach.get("event") or "").strip(),
                str(ach.get("time") or "").strip(),
            )
            if b
        )
        sections += f"""
<div class="card" style="margin-bottom:20px">
  <h3 style="margin-top:0">{_h(title) or "Achievement"}</h3>
  <div style="display:grid;grid-template-columns:minmax(220px,360px) 1fr;gap:20px;align-items:start">
    <img src="{_h(img_url)}" alt="Watermarked preview card" loading="lazy"
         style="width:100%;border-radius:10px;border:1px solid var(--border)"/>
    <div>
      <h4 style="margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Why this card</h4>
      {why_bits or '<p class="dim" style="font-size:13px">Ranked by the deterministic recognition engine.</p>'}
      {caption_html}
    </div>
  </div>
</div>"""

    # G-15: a signed-in visitor already has an account, so show one CTA —
    # claim this preview into their workspace — not the signup button plus a
    # near-identical claim button. Anonymous visitors see only the signup CTA.
    if W._active_profile() is not None:
        cta_html = f"""
  <form method="post" action="{url_for("try_demo_claim", run_id=run_id)}" style="margin:0">
    <button type="submit" class="btn">Keep this preview in my workspace &rarr;</button>
  </form>"""
    else:
        cta_html = (
            f'<a class="btn" href="{url_for("signup_page")}">Sign up — keep your preview &rarr;</a>'
        )
    inner = f"""
<h1 style="margin-bottom:4px">Your top {len(cards)} card{"s" if len(cards) != 1 else ""}</h1>
<p class="dim" style="margin-bottom:20px;max-width:640px">Watermarked preview — the real
product renders these in your club's colours with your logo, generates captions in your
voice, and queues them for one-click approval.</p>
{sections}
<div class="card" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
  {cta_html}
  <span class="dim" style="font-size:12px">Demo runs are deleted within 24 hours.</span>
</div>"""
    return W._try_page(inner, title="Your preview")


def try_demo_card_png(run_id: str, card_id: str):
    from flask import send_file

    from mediahub.web import demo_try as _demo

    state = W._demo_run_or_404(run_id)
    if state["status"] != "done":
        abort(404)
    cards = {c["card_id"]: c for c in W._demo_top_cards(run_id)}
    card = cards.get(str(card_id))
    if card is None:
        abort(404)

    # Cached?
    manifest_path = W.RUNS_DIR / run_id / "demo_cards.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    cached = manifest.get(str(card_id))
    if cached and Path(cached).exists():
        return send_file(cached, mimetype="image/png")

    if not W._v8_ok or W._v8_create_visual_for_item is None:
        abort(503)
    run_data = W._load_run(run_id) or {}
    ach = card["achievement"]
    item = {
        "id": card["card_id"],
        "swim_id": card["card_id"],
        "achievement": ach,
        "post_angle": ach.get("post_angle"),
        "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
        "safe_to_post": W._safe_to_post_or_cautious(card["ra"].get("safe_to_post")),
    }
    demo_prof = _demo.ensure_demo_profile()
    brand_kit = demo_prof.get_brand_kit()
    try:
        with W._render_slot("graphic", card["card_id"], timeout=W._RENDER_TRY_TIMEOUT):
            res = W._v8_create_visual_for_item(
                item,
                brand_kit,
                profile_id=_demo.DEMO_PROFILE_ID,
                run_id=run_id,
                formats=["feed_portrait"],
                watermark_text=_demo.WATERMARK_TEXT,
            )
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception:
        abort(503)
    visuals = res.get("visuals") or []
    path = visuals[0].get("file_path") if visuals else None
    if not path or not Path(path).exists():
        abort(503)
    manifest[str(card_id)] = str(path)
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    except OSError:
        pass
    return send_file(path, mimetype="image/png")


def try_demo_claim(run_id: str):
    """A converting club keeps its preview: re-stamp the demo run to the
    signed-in session's own org. The run leaves the demo sandbox (and
    the sweep's reach) and shows up in the org's Activity."""
    W._demo_run_or_404(run_id)
    prof = W._active_profile()
    if prof is None:
        # Not signed in yet — send them to signup; the demo run stays in
        # their session so they can claim after creating the org.
        return redirect(url_for("signup_page"))
    run_data = W._load_run(run_id)
    if not isinstance(run_data, dict):
        abort(404)
    original_pid = run_data.get("profile_id") or ""
    run_data["profile_id"] = prof.profile_id
    try:
        (W.RUNS_DIR / f"{run_id}.json").write_text(
            json.dumps(run_data, indent=2, default=str), encoding="utf-8"
        )
    except OSError:
        abort(500)
    # The DB row is what the demo sweep and the org's activity list read,
    # so this UPDATE is required: leaving JSON and DB disagreeing about
    # ownership would let sweep_demo_runs delete the claimed run within
    # 24h while it never shows in the org's Activity. On failure, roll
    # the JSON back and tell the user honestly instead of half-claiming.
    try:
        conn = W._db()
        try:
            conn.execute("UPDATE runs SET profile_id = ? WHERE id = ?", (prof.profile_id, run_id))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        W.log.warning("try-demo claim %s: DB update failed, rolling back JSON: %s", run_id, e)
        run_data["profile_id"] = original_pid
        try:
            (W.RUNS_DIR / f"{run_id}.json").write_text(
                json.dumps(run_data, indent=2, default=str), encoding="utf-8"
            )
        except OSError:
            W.log.error(
                "try-demo claim %s: rollback write failed — run JSON and DB "
                "disagree about ownership",
                run_id,
            )
        return W._recovery_page(
            "Claim didn't complete",
            "Saving the claim hit a temporary database error, so the preview "
            "is still in the demo sandbox. Try again in a moment.",
            primary_cta=("Back to your preview", url_for("try_demo_run", run_id=run_id)),
            code=500,
        )
    session["demo_runs"] = [r for r in W._demo_session_runs() if r != run_id]
    return redirect(url_for("review", run_id=run_id))


def print_center_page():
    """A plain-English reference of the print/merch products + capabilities."""
    from mediahub.graphic_renderer.print_export import ghostscript_available
    from mediahub.print_ready import fulfilment as _ff
    from mediahub.print_ready import pdfx as _pdfx
    from mediahub.print_ready import products as _pp

    sections = []
    for grp in _pp.grouped():
        chips = "".join(
            f'<span class="mh-chip" title="{_h(p["description"])}">{_h(p["title"])}</span>'
            for p in grp["products"]
        )
        sections.append(
            f'<section class="panel" style="margin-bottom:var(--sp-4)">'
            f'<h2 style="text-transform:capitalize">{_h(grp["label"])}</h2>'
            f'<div class="mh-chip-row">{chips}</div></section>'
        )
    # J-8: the catalogue was a dead end — product chips and engine status
    # with no path to any meet's actual print tool. List the active org's
    # recent processed meets, each opening its own print tool.
    _meet_rows = []
    _pid = W._active_profile_id()
    if _pid:
        try:
            conn = W._db()
            _meet_rows = conn.execute(
                "SELECT id, meet_name, created_at FROM runs "
                "WHERE profile_id = ? AND status = 'done' "
                "ORDER BY created_at DESC LIMIT 8",
                (_pid,),
            ).fetchall()
            conn.close()
        except Exception:  # noqa: BLE001
            _meet_rows = []
    if _meet_rows:
        _meet_items = "".join(
            f'<li style="margin-bottom:6px">'
            f'<a href="{url_for("print_run_tool_page", run_id=r["id"])}">'
            f"{_h((r['meet_name'] or 'Meet').strip() or 'Meet')}</a>"
            f'<span class="muted" style="margin-left:8px;font-size:12px">'
            f"processed {_h((r['created_at'] or '')[:10])}</span></li>"
            for r in _meet_rows
        )
        _meets_inner = (
            '<p class="muted" style="margin-top:0">Each meet opens its own print '
            "tool: pick a card and a product, proof it, then export the "
            "print-ready file.</p>"
            f'<ul style="margin:0;padding-left:20px">{_meet_items}</ul>'
        )
    else:
        _meets_inner = W._empty_state(
            "inbox",
            "No results to print from yet",
            "Process a results file first &mdash; every meet you process "
            "appears here, ready to turn into posters, certificates and merch.",
            actions=f'<a class="btn" href="{url_for("home")}">Upload results</a>',
        )
    _meets_html = (
        '<section class="panel" style="margin-bottom:var(--sp-4)">'
        "<h2>Print from a meet</h2>"
        f"{_meets_inner}</section>"
    )
    ff = _ff.status()
    # Name the piece that's actually missing: PDF/X-3 needs Ghostscript AND
    # an ICC profile, so "needs an ICC profile" when Ghostscript itself is
    # absent pointed the operator at the wrong fix.
    if _pdfx.pdfx_available():
        _pdfx_state = "ready"
    elif not ghostscript_available():
        _pdfx_state = "needs Ghostscript"
    else:
        _pdfx_state = "needs an ICC profile"
    caps = (
        f'<p class="muted">CMYK conversion (Ghostscript): '
        f"<strong>{'ready' if ghostscript_available() else 'not installed'}</strong> · "
        f"PDF/X-3: <strong>{_pdfx_state}"
        f"</strong> · Fulfilment: <strong>{_h(ff['message'])}</strong></p>"
    )
    body = (
        '<section class="mh-hero" data-lane="" '
        'style="padding-top:var(--sp-8);padding-bottom:var(--sp-6)">'
        '<span class="mh-hero-eyebrow">Print &amp; merch</span>'
        '<h1>Print-ready, <em class="editorial">no surprises</em>.</h1>'
        '<p class="lede">Turn any approved design into a file a high-street or online '
        "printer will accept — posters, flyers, certificates, banners, and fundraising "
        "merch. MediaHub checks resolution, bleed, text size, contrast and ink before you "
        "ever send it, and explains anything to fix. Pick a meet below to proof and "
        "export its cards.</p>"
        f"{caps}</section>" + _meets_html + "".join(sections)
    )
    return W._layout("Print & merch", body)


def print_run_tool_page(run_id: str):
    """The per-meet print tool: pick a card + product, proof, export, preview."""
    run_data = W._run_data_any(run_id)
    if run_data is None or not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return W._layout(
            "Print", '<div class="empty">That meet isn\'t available to print.</div>'
        ), 404
    from mediahub.print_ready import products as _pp

    rr = run_data.get("recognition_report") or {}
    card_opts = []
    for ra in (rr.get("ranked_achievements") or [])[:60]:
        ach = ra.get("achievement") or {}
        cid = ach.get("swim_id") or ra.get("id")
        if not cid:
            continue
        label = ach.get("swimmer_name") or ach.get("headline") or cid
        card_opts.append(f'<option value="{_h(str(cid))}">{_h(str(label))}</option>')
    cards_html = "".join(card_opts) or '<option value="">(no cards yet)</option>'
    prod_html = "".join(
        f'<optgroup label="{_h(g["label"])}">'
        + "".join(
            "".join(
                f'<option value="{_h(p["slug"])}::{_h(pl["slug"])}">'
                f"{_h(p['title'])}"
                + (f" — {_h(pl['label'])}" if p["double_sided"] else "")
                + "</option>"
                for pl in p["placements"]
            )
            for p in g["products"]
        )
        + "</optgroup>"
        for g in _pp.grouped()
    )
    meet = (run_data or {}).get("meet") or {}
    title = _h(meet.get("name") or run_id)
    pf_url = url_for("api_card_preflight", run_id=run_id, card_id="__CARD__")
    print_url = url_for("api_card_print", run_id=run_id, card_id="__CARD__")
    mock_url = url_for("api_card_merch_mockup", run_id=run_id, card_id="__CARD__")
    body = (
        f'<section class="panel" data-print-tool data-preflight-url="{_h(pf_url)}" '
        f'data-print-url="{_h(print_url)}" data-mockup-url="{_h(mock_url)}">'
        f'<h1 style="margin-top:0">Print &amp; merch — {title}</h1>'
        '<p class="muted">Pick a card and a product, run the pre-flight check, then '
        "download a print-ready PDF or preview the merch. A blocking issue is explained "
        "and held back until you fix it (or choose to export anyway).</p>"
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin:var(--sp-3) 0">'
        f'<label class="mh-field">Card <select id="pr-card">{cards_html}</select></label>'
        f'<label class="mh-field">Product <select id="pr-product">{prod_html}</select></label>'
        '<label class="mh-field">Colour <select id="pr-colour">'
        '<option value="rgb">RGB (print-ready)</option>'
        '<option value="cmyk">CMYK (Ghostscript)</option>'
        '<option value="pdfx">PDF/X-3</option></select></label>'
        "</div>"
        '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
        '<button class="btn" id="pr-preflight">Run pre-flight</button>'
        '<button class="btn primary" id="pr-download">Download print-ready PDF</button>'
        '<button class="btn secondary" id="pr-mockup">Preview mockup</button>'
        '<label class="mh-check" title="Warnings never hold an export back — only a blocking pre-flight error does. Tick to export anyway.">'
        '<input type="checkbox" id="pr-force"> '
        "export despite blocking errors</label>"
        "</div>"
        '<div id="pr-report" style="margin-top:var(--sp-4)" role="status" '
        'aria-live="polite"></div>'
        '<div id="pr-preview" style="margin-top:var(--sp-3)"></div>'
        "</section>"
        '<script src="'
        + url_for("static", filename="js/print_center.js", v=W._static_ver("js/print_center.js"))
        + '"></script>'
    )
    return W._layout("Print & merch", body)


def export_center_page():
    """A plain-English reference of every format MediaHub can export."""
    from mediahub import export_engine as ee

    order = ["image", "video", "audio", "document", "data", "pack"]
    sections = []
    for cat in order:
        fmts = ee.formats_for_category(cat)
        if not fmts:
            continue
        chips = "".join(
            f'<span class="mh-chip" title="{_h(f.mime)}">{_h(f.label)}</span>' for f in fmts
        )
        sections.append(
            f'<section class="panel" style="margin-bottom:var(--sp-4)">'
            f'<h2 style="text-transform:capitalize">{_h(cat)}</h2>'
            f'<div class="mh-chip-row">{chips}</div></section>'
        )
    st = ee.engine_status()
    engines = (
        f'<p class="muted">Video engine (FFmpeg): '
        f"<strong>{'ready' if st['ffmpeg'] else 'not installed'}</strong> · "
        f"WebP: <strong>{'yes' if st['webp_encode'] else 'no'}</strong> · "
        f"AVIF: <strong>{'yes' if st['avif_encode'] else 'no'}</strong></p>"
    )
    # J-5: this hub used to send users to a "meet's review page" to bulk-export
    # — but the bulk-export tool lives at /export/<run_id>. List the profile's
    # recent results linking straight there, and fix the misdirecting copy.
    prof = W._active_profile()
    recent_html = ""
    if prof is not None:
        rrows = []
        try:
            conn = W._db()
            try:
                rrows = conn.execute(
                    "SELECT id, meet_name FROM runs "
                    "WHERE profile_id = ? AND status = 'done' "
                    "ORDER BY created_at DESC LIMIT 8",
                    (prof.profile_id,),
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            rrows = []
        if rrows:
            items = "".join(
                f'<li style="margin:6px 0"><a href="{url_for("export_run_tool_page", run_id=r["id"])}">'
                f"{_h(r['meet_name'] or 'Untitled results')} &rarr;</a></li>"
                for r in rrows
            )
            recent_html = (
                '<section class="panel" style="margin-bottom:var(--sp-4)">'
                "<h2>Bulk-export your recent results</h2>"
                '<p class="muted">Open the export tool for a set of results — pick formats, '
                "run it, and download or share the whole pack.</p>"
                f'<ul style="list-style:none;padding:0;margin:0">{items}</ul></section>'
            )
    if not recent_html:
        recent_html = (
            '<section class="panel" style="margin-bottom:var(--sp-4)">'
            "<h2>Bulk-export a content pack</h2>"
            '<p class="muted">Once you\'ve processed a set of results, its Content builder '
            'has an "Export ZIP" that bulk-exports the whole pack in these formats. '
            f'<a href="{url_for("home")}">Start with your results &rarr;</a></p></section>'
        )
    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-8);padding-bottom:var(--sp-6)">'
        '<span class="mh-hero-eyebrow">Export &amp; convert</span>'
        '<h1>Export <em class="editorial">anything</em>, your way.</h1>'
        '<p class="lede">Every card, reel, document and photo can leave MediaHub in the '
        "format you need — with quality, size and transparency options.</p>"
        f"{engines}</section>" + recent_html + "".join(sections)
    )
    return W._layout("Export & convert", body)


@W.require_run(
    deny=lambda: (
        W._layout(
            "Export",
            '<div class="empty">That meet isn\'t available to export.</div>',
        ),
        404,
    )
)
def export_run_tool_page(run_id: str, run_data):
    """The bulk-export tool for one run: pick formats, run it, download/share."""
    from mediahub import export_engine as ee

    meet = (run_data or {}).get("meet") or {}
    title = _h(meet.get("name") or run_id)
    img_fmts = [
        f for f in ee.formats_for_category("image") if f.key in ("png", "jpg", "webp", "avif")
    ]
    # F-11 — one-line plain-English guidance per format so a volunteer isn't
    # picking blind between raw codec names.
    _fmt_hint = {
        "jpg": "smallest, works everywhere — best for photos",
        "png": "sharpest text &amp; logos; larger files",
        "webp": "small and sharp; most apps now accept it",
        "avif": "smallest of all, but some apps can't open it yet",
    }
    boxes = "".join(
        f'<label class="mh-check" style="display:block;margin-bottom:8px">'
        f'<input type="checkbox" name="fmt" value="{f.key}"'
        f"{' checked' if f.key == 'jpg' else ''}> <strong>{_h(f.label)}</strong>"
        f'<span class="muted" style="font-size:12px"> — {_fmt_hint.get(f.key, "")}</span>'
        f"</label>"
        for f in img_fmts
    )
    kick_url = url_for("api_run_bulk_export", run_id=run_id)
    share_url = url_for("api_run_export_share", run_id=run_id)
    body = (
        f'<section class="panel" data-bulk-export data-kick-url="{_h(kick_url)}" '
        f'data-share-url="{_h(share_url)}">'
        f'<h1 style="margin-top:0">Bulk export — {title}</h1>'
        '<p class="muted">Convert every rendered card in this pack to the formats you '
        "tick, bundled into one ZIP with a manifest. A format a card can't become is "
        "listed honestly in the manifest — the rest still export.</p>"
        f'<div style="margin:var(--sp-3) 0">{boxes}</div>'
        '<label class="mh-field" for="bx-quality">Quality '
        '<input type="range" id="bx-quality" min="10" max="100" value="90" '
        'style="vertical-align:middle"> '
        '<output id="bx-quality-out" for="bx-quality" '
        'style="font-variant-numeric:tabular-nums;font-weight:600">90</output></label>'
        '<p class="muted" style="font-size:12px;margin:4px 0 0">Higher = sharper, '
        "but larger files. 90 suits most posts.</p>"
        '<div style="margin-top:var(--sp-3)">'
        '<button class="btn primary" id="bx-start">Start export</button> '
        '<span id="bx-status" class="muted" role="status" aria-live="polite"></span>'
        "</div>"
        '<div id="bx-result" style="margin-top:var(--sp-3)"></div>'
        "</section>"
        '<script src="'
        + url_for("static", filename="js/bulk_export.js", v=W._static_ver("js/bulk_export.js"))
        + '"></script>'
    )
    return W._layout("Bulk export", body)


def share_review_page(token: str):
    """Public, no-account review page for a scoped share link."""
    from mediahub.collab import share_tokens as _shares
    from mediahub.collab import threads as _threads

    share = _shares.resolve(token)
    if share is None:
        return W._layout(
            "Link unavailable",
            "<h1>This review link is no longer available</h1>"
            '<p class="lede">It may have expired or been turned off by the club. '
            "Ask them for a fresh link.</p>",
            active="",
        ), 404
    run_data = W._load_run(share.run_id) or {}
    meet = _h((run_data.get("meet") or {}).get("name") or run_data.get("meet_name") or "Meet")
    cards = W._share_visible_cards(share)
    can_comment = share.perm == _shares.PERM_COMMENT

    blocks = ""
    for c in cards:
        cid = c["card_id"]
        img = url_for("share_card_png", token=token, card_id=cid)
        # External-safe entries only. Internal committee comments and tasks
        # carry the member's account email (api_collab_comments always sets
        # author_email) and must never render to an unauthenticated link
        # holder; share-posted comments (share_add_comment) never set an
        # email, so they are the ones an external reviewer sees.
        comments = [
            cm
            for cm in _threads.list_for_card(share.run_id, cid, include_resolved=True)
            if cm.kind == "comment" and not (cm.author_email or "").strip()
        ]
        cm_html = ""
        for cm in comments:
            who = _h(cm.author_name or "Reviewer")
            cm_html += (
                '<div style="padding:6px 0;border-top:1px solid var(--border);font-size:13px">'
                f"<strong>{who}</strong>: {_h(cm.body)}</div>"
            )
        form_html = ""
        if can_comment:
            form_html = (
                f'<form method="post" action="{url_for("share_add_comment", token=token)}" '
                'style="margin-top:8px;display:flex;flex-direction:column;gap:6px">'
                f'<input type="hidden" name="card_id" value="{_h(cid)}"/>'
                '<input type="text" name="name" placeholder="Your name (optional)" '
                'style="padding:6px 8px;border:1px solid var(--border);border-radius:6px;'
                'background:rgba(255,255,255,0.04);color:inherit"/>'
                '<textarea name="body" required rows="2" placeholder="Add a comment — '
                'e.g. confirm the name is spelled right" '
                'style="padding:6px 8px;border:1px solid var(--border);border-radius:6px;'
                'background:rgba(255,255,255,0.04);color:inherit"></textarea>'
                '<button type="submit" class="btn" style="align-self:flex-start">'
                "Send comment</button></form>"
            )
        blocks += (
            '<div class="card" style="margin-bottom:18px;padding:16px">'
            f'<img src="{img}" alt="{_h(c["headline"] or "Card")}" '
            'style="max-width:100%;border-radius:8px;display:block;margin-bottom:10px"/>'
            + (
                f'<div style="font-weight:700;margin-bottom:4px">{_h(c["headline"])}</div>'
                if c["headline"]
                else ""
            )
            + (
                f'<div style="font-size:13px;color:var(--ink-muted)">{_h(c["event"])}</div>'
                if c["event"]
                else ""
            )
            + (f'<div style="margin-top:10px">{cm_html}</div>' if cm_html else "")
            + form_html
            + "</div>"
        )
    if not blocks:
        blocks = '<p class="lede">There are no cards to review on this link yet.</p>'
    intro = (
        f"<h1>{meet} — for review</h1>"
        '<p class="lede">A club has shared this content for your review'
        + (" — you can leave a comment below." if can_comment else " (view only).")
        + "</p>"
    )
    return W._layout(f"{meet} — review", intro + blocks, active="")


def share_card_png(token: str, card_id: str):
    from flask import send_file

    from mediahub.collab import share_tokens as _shares
    from mediahub.web import public_wall as _pw

    share = _shares.resolve(token)
    if share is None:
        abort(404)
    # A card-scoped share only serves its own card.
    if share.card_id and str(card_id) != str(share.card_id):
        abort(404)
    run_data = W._load_run(share.run_id) or {}
    owner = W._run_owner_id(share.run_id, run_data) or run_data.get("profile_id", "")
    path = _pw.rendered_card_png(owner, share.run_id, card_id)
    if not path:
        abort(404)
    resp = make_response(send_file(path, mimetype="image/png"))
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def share_add_comment(token: str):
    from mediahub.collab import share_tokens as _shares
    from mediahub.collab import threads as _threads

    share = _shares.resolve(token)
    if share is None or share.perm != _shares.PERM_COMMENT:
        abort(404)
    if W._auth_rate_limited("share_comment"):
        return W._layout(
            "Slow down",
            "<h1>Too many comments</h1><p>Please wait a moment and try again.</p>",
            active="",
        ), 429
    card_id = (request.form.get("card_id") or share.card_id or "").strip()
    body = (request.form.get("body") or "").strip()
    name = (request.form.get("name") or "").strip()[:120]
    # Only allow commenting on a card the share actually exposes.
    visible = {c["card_id"] for c in W._share_visible_cards(share)}
    if card_id not in visible:
        abort(404)
    try:
        _threads.add_comment(
            share.run_id,
            card_id,
            body,
            author_name=name or "External reviewer",
            kind="comment",
        )
    except _threads.ThreadError:
        return redirect(url_for("share_review_page", token=token))
    # Tell the club an external comment arrived (org-wide inbox).
    try:
        from mediahub.notify import inbox as _inbox

        owner = W._run_owner_id(share.run_id, run_data=W._load_run(share.run_id)) or ""
        if owner:
            _inbox.record(
                owner,
                _inbox.KIND_INFO,
                "New review comment",
                f"{name or 'An external reviewer'} commented on a shared card.",
                run_id=share.run_id,
                click_url=url_for("review", run_id=share.run_id),
            )
    except Exception:
        pass
    return redirect(url_for("share_review_page", token=token))


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
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    # M30 — honest, current copy: graphics are built on the Content
    # builder (post-approval), not the old recognition page.
    _no_visuals_html = (
        '<div class="empty">No graphics have been generated for this run yet. '
        f'Open the <a href="{url_for("content_pack", run_id=run_id)}">Content builder</a> '
        "and use &ldquo;Create graphic&rdquo; on a card &mdash; or &ldquo;Create all "
        "graphics&rdquo; to build the whole pack.</div>"
    )
    if not W._can_access_run(run_id, W._load_run(run_id), W._active_profile_id()):
        return W._layout("No visuals", _no_visuals_html), 404
    from flask import send_file
    import io, zipfile

    vdir = W.RUNS_DIR / run_id / "visuals"
    if not vdir.is_dir():
        return W._layout("No visuals", _no_visuals_html), 404

    buf = io.BytesIO()
    approval = []
    # E-2: a human who rejected a card must never see it ship in this ZIP.
    _rejected = W._rejected_card_ids(run_id)
    # W.11: the approver-edited alt text (saved in review) outranks
    # whatever the visual sidecar recorded at generation time.
    _wf_alt_edits: dict[str, str] = {}
    try:
        _ws_zip = W._get_wf_store()
        if _ws_zip is not None:
            for _cid, _st in (_ws_zip.load(run_id) or {}).items():
                _alt = ((_st.edited_captions or {}) if _st else {}).get("alt_text", "")
                if _alt:
                    _wf_alt_edits[_cid] = _alt
    except Exception:
        _wf_alt_edits = {}
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
            # E-2: skip cards a human rejected (match on the workflow
            # card id, falling back to the visual id / dir name).
            if str(visual.get("content_item_id") or vid) in _rejected:
                continue
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
            alt = (
                _wf_alt_edits.get(visual.get("content_item_id") or "")
                or visual.get("alt_text")
                or ""
            )
            z.writestr(
                f"{run_id}/captions/{vid}.txt",
                f"CAPTION:\n{cap}\n\nALT TEXT:\n{alt}\n",
            )
            approval.append(
                {
                    "id": vid,
                    "format": fmt,
                    "status": visual.get("status", "draft"),
                    "caption": cap,
                    "alt_text": alt,
                    "source_asset_ids": visual.get("source_asset_ids", []),
                    "created_at": visual.get("created_at"),
                }
            )
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


def pack_export_zip(run_id: str):
    """G1.15 — batch ZIP of a pack's EVERY rendered format + a metadata.json manifest.

    Distinct from ``content_pack_zip`` (which groups PNGs by destination
    bucket + an approval-summary.json): this export groups by card with
    every size together (square / portrait / story), writes a real
    ``metadata.json`` manifest (layout, palette, dimensions, per-format
    sha256, confidence, design reasoning, and honest format-coverage), and
    a plain-English README. Built by ``graphic_renderer.pack_export``.

    Packaging only — it bundles what the generation pipeline already
    rendered; it never re-renders (no Chromium in the request path).
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    # M30 — honest, current copy (see content_pack_zip's twin note).
    _no_visuals_html = (
        '<div class="empty">No graphics have been generated for this run yet. '
        f'Open the <a href="{url_for("content_pack", run_id=run_id)}">Content builder</a> '
        "and use &ldquo;Create graphic&rdquo; on a card &mdash; or &ldquo;Create all "
        "graphics&rdquo; to build the whole pack.</div>"
    )
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return W._layout("No visuals", _no_visuals_html), 404

    profile_id = run_data.get("profile_id") if run_data else None
    profile_id = profile_id or W._active_profile_id() or ""
    zip_bytes = W._build_run_pack_zip(run_id, run_data or {}, profile_id)
    if zip_bytes is None:
        return W._layout("No visuals", _no_visuals_html), 404

    from flask import send_file
    import io as _io

    return send_file(
        _io.BytesIO(zip_bytes),
        as_attachment=True,
        download_name=f"content-pack-{run_id}-all-formats.zip",
        mimetype="application/zip",
    )


def club_data_page():
    # The Club-data top-nav tab was retired: club records + "Ask the data"
    # live under Settings → Club data, athletes & consent under Settings →
    # Privacy, and live meet / season wraps moved to Create (coming soon).
    # This route stays only as a redirect so old links/bookmarks resolve.
    return redirect(url_for("settings_section", section="clubdata"))


def data_hub_page():
    if not W._data_hub_ok:
        return W._dh_unavailable_page()
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Data hub", W._PW_NO_ORG, active="settings")
    from mediahub.bulk import store as _bulk_store
    from mediahub.data_hub import store as _dh_store
    from mediahub.data_hub import tables as _dh_tables
    from mediahub.web import data_hub_ui as _ui

    canonical = _dh_tables.list_canonical_tables(pid, runs_dir=W.RUNS_DIR)
    org_tables = _dh_store.list_org_tables(pid)
    meets = _dh_tables.meets_table(pid, runs_dir=W.RUNS_DIR)
    runs = [
        {"run_id": meets.cell(i, "run_id").display, "meet": meets.cell(i, "meet").display}
        for i in range(meets.row_count)
    ]
    jobs = _bulk_store.list_jobs(pid)
    msg = ""
    if request.args.get("msg"):
        # D-20: link straight to the run's review queue where the cards landed.
        _review_run = (request.args.get("review_run") or "").strip()
        _review_link = (
            f'<p style="margin:6px 0 0"><a class="btn" href="{url_for("review", run_id=_review_run)}">'
            "Review these cards &rarr;</a></p>"
            if _review_run
            else ""
        )
        msg = (
            '<div class="card" style="border-color:var(--mh-success)">'
            f"<p>{_h(request.args.get('msg'))}</p>{_review_link}</div>"
        )
    if request.args.get("err"):
        msg = f'<div class="card" style="border-color:var(--mh-error)"><p>{_h(request.args.get("err"))}</p></div>'
    body = msg + _ui.render_index(
        canonical=canonical,
        org_tables=org_tables,
        runs=runs,
        jobs=jobs,
        connectors=[],
    )
    return W._layout("Data hub", body, active="settings")


def data_hub_table(table_id):
    if not W._data_hub_ok:
        return W._dh_unavailable_page()
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Data hub", W._PW_NO_ORG, active="settings")
    from mediahub.web import data_hub_ui as _ui

    table = W._dh_resolve(pid, table_id)
    if table is None:
        return W._layout(
            "Data hub",
            '<div class="card"><h2>Table not found</h2>'
            f'<p class="dim"><a href="{url_for("data_hub_page")}">Back to the data hub</a></p></div>',
            active="settings",
        ), 404
    sort = (request.args.get("sort") or "").strip()
    direction = "desc" if request.args.get("dir") == "desc" else "asc"
    query = (request.args.get("q") or "").strip()
    grid = _ui.render_grid(table, sort=sort, direction=direction, query=query)
    toolbar = _ui.render_toolbar(table, query=query)

    extras = ""
    if table.editable:  # org tables: add-calculated-column + delete
        extras = W._dh_org_table_controls(table)
    back = f'<p style="margin:12px 0"><a class="btn secondary" href="{url_for("data_hub_page")}">&larr; Data hub</a></p>'
    body = f'{back}<h1 style="margin:.2em 0">{_h(table.title)}</h1>{toolbar}{grid}{extras}'
    return W._layout(f"Data hub — {table.title}", body, active="settings")


def data_hub_export(table_id):
    if not W._data_hub_ok:
        return jsonify({"error": "Data hub unavailable."}), 404
    pid = W._phase_w_org()
    if not pid:
        return jsonify({"error": "Not signed in."}), 403
    table = W._dh_resolve(pid, table_id)
    if table is None:
        return jsonify({"error": "Table not found."}), 404
    fmt = (request.args.get("fmt") or "csv").lower()
    from mediahub.data_hub.portability import export_csv, export_xlsx

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", table.title or "table").strip("_") or "table"
    if fmt == "xlsx":
        try:
            payload = export_xlsx(table)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 503
        return Response(
            payload,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
        )
    return Response(
        export_csv(table),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )


def club_records_page():
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Club records", W._PW_NO_ORG, active="settings")
    from mediahub.club_records import list_records

    msg = (request.args.get("msg") or "").strip()
    msg_html = f'<p class="tag good" style="margin-bottom:14px">{_h(msg)}</p>' if msg else ""
    # D-19: list exactly which rows the last records import couldn't read.
    msg_html += W._import_skipped_html(session.pop("records_import_skipped", None))
    records = list_records(pid)
    rows = "".join(
        "<tr>"
        f"<td>{r.distance}m {_h(r.stroke)}</td><td>{_h(r.course)}</td>"
        f"<td>{_h(r.gender)}</td><td>{_h(r.age_group)}</td>"
        f"<td><strong>{_h(r.time_str)}</strong></td><td>{_h(r.holder)}</td>"
        f"<td>{_h(r.set_date or '')}</td>"
        f'<td><form method="POST" action="{url_for("club_records_action")}">'
        f'<input type="hidden" name="action" value="delete"/>'
        f'<input type="hidden" name="distance" value="{r.distance}"/>'
        f'<input type="hidden" name="stroke" value="{_h(r.stroke)}"/>'
        f'<input type="hidden" name="course" value="{_h(r.course)}"/>'
        f'<input type="hidden" name="gender" value="{_h(r.gender)}"/>'
        f'<input type="hidden" name="age_group" value="{_h(r.age_group)}"/>'
        f'<button type="submit" class="btn secondary" style="font-size:11px;padding:3px 8px">Remove</button>'
        f"</form></td></tr>"
        for r in records
    ) or (
        '<tr><td colspan="8" class="muted">No records yet — import the club '
        "records sheet below. That one import is what turns record swims into "
        "NEW CLUB RECORD cards.</td></tr>"
    )
    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Club data &middot; Records</span>
  <h1>Club <em class="editorial">records</em></h1>
  <p class="lede">The highest-emotion post a club makes. When a swim beats a mark
  here, a NEW CLUB RECORD card outranks everything — and this table only changes
  when you approve that card.</p>
</section>
{msg_html}
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-top:0">Current records ({len(records)})</h2>
  <table class="mh-table" style="width:100%">
    <thead><tr><th>Event</th><th>Course</th><th>Sex</th><th>Age group</th><th>Time</th><th>Holder</th><th>Set</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<div class="card">
  <h2 style="margin-top:0">Import the records sheet (.csv)</h2>
  <p class="dim" style="font-size:13px">One row per record:
  <code>event, course, sex, age group, time, holder[, date]</code><br/>
  e.g. <code>100 Freestyle, LC, F, open, 1:02.10, Erin Jones, 2019-05-01</code>
  &mdash; age group is <code>open</code> or a band like <code>13-14</code>.
  Unreadable rows are reported back, never guessed.</p>
  <form method="POST" action="{url_for("club_records_action")}">
    <input type="hidden" name="action" value="import"/>
    <textarea name="csv_text" rows="8" style="width:100%;max-width:640px"
      placeholder="100 Freestyle, LC, F, open, 1:02.10, Erin Jones, 2019-05-01"></textarea>
    <div style="margin-top:8px"><button type="submit" class="btn">Import records</button></div>
  </form>
</div>
"""
    return W._layout("Club records", body, active="settings")


def club_records_action():
    pid = W._phase_w_org()
    if not pid:
        abort(403)
    from mediahub.club_records import delete_record, import_csv

    action = (request.form.get("action") or "").strip()
    msg = ""
    if action == "import":
        result = import_csv(pid, request.form.get("csv_text") or "")
        msg = f"Imported {result['imported']} records."
        if result["skipped"]:
            msg += f" Skipped {len(result['skipped'])} unreadable rows."
            # D-19: stash the failed rows so the page lists which to fix.
            session["records_import_skipped"] = result["skipped"]
    elif action == "delete":
        try:
            ok = delete_record(
                pid,
                distance=int(request.form.get("distance") or 0),
                stroke=request.form.get("stroke") or "",
                course=request.form.get("course") or "",
                gender=request.form.get("gender") or "",
                age_group=request.form.get("age_group") or "open",
            )
            msg = "Record removed." if ok else "Record not found."
        except (TypeError, ValueError):
            msg = "Record not found."
    return redirect(url_for("club_records_page", msg=msg))


def live_meet_page():
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Live meet", W._PW_NO_ORG, active="create")
    from mediahub.results_fetch.live_watch import list_watches

    # Success feedback rides ?msg=, failures ride ?err= so the banner can
    # style them honestly (green success vs amber warning) instead of
    # painting every message — including "could not start the watch" — green.
    msg = (request.args.get("msg") or "").strip()
    err = (request.args.get("err") or "").strip()
    if err:
        msg_html = f'<p class="tag warn" style="margin-bottom:14px">{_h(err)}</p>'
    elif msg:
        msg_html = f'<p class="tag good" style="margin-bottom:14px">{_h(msg)}</p>'
    else:
        msg_html = ""
    watches = list_watches(pid)

    def _review_cell(w) -> str:
        # A run only exists on disk once a poll has actually carded new
        # swims. Until then the review link would dead-end on "Run not
        # found", so show an honest "No cards yet" placeholder instead.
        if w.new_swims_total > 0:
            return (
                "<a class='btn secondary' style='font-size:12px;padding:4px 10px' "
                f'href="{url_for("review", run_id=w.run_id or w.id)}">Review cards</a>'
            )
        return "<span class='muted' style='font-size:12px'>No cards yet</span>"

    rows = (
        "".join(
            "<tr>"
            f"<td>{_h(w.label or w.url)}<br/><span class='muted' style='font-size:11px'>{_h(w.url)}</span></td>"
            f"<td><span class='tag {'good' if w.status == 'active' else 'warn'}'>{_h(w.status)}</span></td>"
            f"<td>every {w.interval_minutes} min</td>"
            f"<td>{w.polls} polls &middot; {w.new_swims_total} new swims</td>"
            f"<td>{_h((w.last_error or '')[:80])}</td>"
            f"<td>{_review_cell(w)}</td>"
            f'<td><form method="POST" action="{url_for("live_meet_action")}">'
            f'<input type="hidden" name="action" value="stop"/>'
            f'<input type="hidden" name="watch_id" value="{_h(w.id)}"/>'
            f'<button type="submit" class="btn secondary" style="font-size:12px;padding:4px 10px"'
            f"{' disabled' if w.status != 'active' else ''}>Stop</button></form></td>"
            "</tr>"
            for w in watches
        )
        or '<tr><td colspan="7" class="muted">No live watches yet.</td></tr>'
    )
    body = f"""
<section class="mh-hero" style="padding-top:var(--sp-7);padding-bottom:var(--sp-4)">
  <span class="mh-hero-eyebrow">Club data &middot; Live meet</span>
  <h1>Live <em class="editorial">meet</em> mode</h1>
  <p class="lede">Paste the host club&rsquo;s live-results page. MediaHub checks it
  politely during the gala; each new result runs through recognition and queues a
  card for approval — you get a push, nothing posts itself, and the watch stops
  on its own.</p>
</section>
{msg_html}
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-top:0">Watch a results page</h2>
  <p class="dim" style="font-size:13px">Use the meet results page on the host
  club&rsquo;s own website or results.swimming.org. Meet Mobile and rankings sites
  are not supported — they don&rsquo;t allow it.</p>
  <form method="POST" action="{url_for("live_meet_action")}" style="display:grid;gap:8px;max-width:640px">
    <input type="hidden" name="action" value="create"/>
    <label for="lm-url">Live results page URL</label>
    <input id="lm-url" type="url" name="url" required placeholder="https://hostclub.org.uk/gala/live-results.htm"/>
    <label for="lm-label">Name (so you recognise it)</label>
    <input id="lm-label" type="text" name="label" placeholder="Swansea Spring Open — Sunday"/>
    <div style="display:flex;gap:14px;flex-wrap:wrap">
      <div><label for="lm-interval">Check every</label>
        <select id="lm-interval" name="interval_minutes"><option value="3">3 min</option><option value="5" selected>5 min</option><option value="10">10 min</option></select></div>
      <div><label for="lm-hours">Stop after</label>
        <select id="lm-hours" name="hours"><option value="6">6 hours</option><option value="12" selected>12 hours</option><option value="24">24 hours</option></select></div>
    </div>
    <div><button type="submit" class="btn">Start watching</button></div>
  </form>
</div>
<div class="card">
  <h2 style="margin-top:0">Watches</h2>
  <table class="mh-table" style="width:100%">
    <thead><tr><th>Meet</th><th>Status</th><th>Interval</th><th>Activity</th><th>Last issue</th><th><span class="mh-sr-only">Review</span></th><th><span class="mh-sr-only">Actions</span></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
"""
    return W._layout("Live meet", body, active="create")


def live_meet_action():
    pid = W._phase_w_org()
    if not pid:
        abort(403)
    from datetime import timedelta as _td

    from mediahub.results_fetch.live_watch import create_watch, list_watches, stop_watch

    action = (request.form.get("action") or "").strip()
    msg = ""
    err = ""
    if action == "create":
        try:
            hours = max(1, min(48, int(request.form.get("hours") or 12)))
        except (TypeError, ValueError):
            hours = 12
        # interval_minutes comes from a <select> (3/5/10), but a hand-crafted
        # POST can send anything. Parse defensively so a bad value is a clean
        # default rather than a leaked ValueError; create_watch clamps range.
        try:
            interval = int(request.form.get("interval_minutes") or 5)
        except (TypeError, ValueError):
            interval = 5
        url = (request.form.get("url") or "").strip()
        # Politeness: at most one active watch per (org, url). A repeat
        # submission reuses the existing watch instead of doubling the poll
        # rate against the host club's site.
        existing = next(
            (w for w in list_watches(pid) if w.status == "active" and w.url == url),
            None,
        )
        if existing is not None:
            msg = f"Already watching that page ({existing.interval_minutes}-min checks)."
        else:
            rid = uuid.uuid4().hex[:12]
            try:
                watch = create_watch(
                    pid,
                    url,
                    interval_minutes=interval,
                    expires_at=datetime.now(timezone.utc) + _td(hours=hours),
                    label=(request.form.get("label") or "").strip(),
                    run_id=rid,
                    review_url=url_for("review", run_id=rid, _external=True),
                )
            except ValueError as e:
                err = f"Could not start the watch: {e}"
            except Exception:
                W.log.warning("live watch create failed", exc_info=True)
                err = "Could not start the watch: something went wrong. Please try again."
            else:
                if W._ensure_live_watch_schedule():
                    msg = f"Watching. Cards will queue under Review as results land ({watch.interval_minutes}-min checks)."
                else:
                    err = (
                        "Watch saved, but polling could not be scheduled. Please try again shortly."
                    )
    elif action == "stop":
        try:
            ok = stop_watch(pid, (request.form.get("watch_id") or "").strip())
        except Exception:
            W.log.warning("live watch stop failed", exc_info=True)
            err = "Could not stop the watch: something went wrong. Please try again."
        else:
            msg = "Watch stopped." if ok else ""
            if not ok:
                err = "Watch not found."
    if err:
        return redirect(url_for("live_meet_page", err=err))
    return redirect(url_for("live_meet_page", msg=msg))


@W.require_run(deny=lambda: (abort(404)))
def pack_certificates_zip(run_id: str):
    import io as _io

    # D-12: serve a ZIP a finished background job already built
    # (?file=<job_id>) — this route stays the one gated file server.
    _file_job = (request.args.get("file") or "").strip()
    if _file_job:
        job = W._variant_job_load(_file_job)
        if (
            job is None
            or job.get("kind") != "certificates"
            or job.get("run_id") != run_id
            or job.get("status") != "done"
        ):
            abort(404)
        zip_path = Path(str(job.get("zip_path") or ""))
        if not zip_path.is_file():
            abort(404)
        return send_file(
            str(zip_path),
            mimetype="application/zip",
            as_attachment=True,
            download_name=str(job.get("download_name") or f"certificates-{run_id}.zip"),
        )

    data, pid, prof, approved = W._certificates_approved_for(run_id)
    if data is None:
        abort(404)
    if not approved:
        return (
            W._layout(
                "Certificates",
                '<div class="card"><h2>No approved cards yet</h2>'
                '<p class="dim">Certificates are printed from approved achievements '
                "only — approve some cards first, then come back.</p></div>",
            ),
            200,
        )
    # G1.17: print-production mode (?print=1) adds bleed + crop marks; an
    # optional ?cmyk=1 converts to DeviceCMYK via Ghostscript when present.
    print_mode = (request.args.get("print") or "").strip().lower() in W._TRUTHY
    bleed_mm = W._clamp_float(request.args.get("bleed"), default=3.0, lo=0.0, hi=10.0)
    crop_marks = (request.args.get("marks") or "1").strip().lower() in W._TRUTHY
    colour_bar = (
        request.args.get("colorbar") or request.args.get("colourbar") or "1"
    ).strip().lower() in W._TRUTHY
    want_cmyk = (request.args.get("cmyk") or "").strip().lower() in W._TRUTHY
    buf = _io.BytesIO()
    W._write_certificates_zip(
        buf,
        run_id,
        data,
        pid,
        prof,
        approved,
        print_mode=print_mode,
        bleed_mm=bleed_mm,
        crop_marks=crop_marks,
        colour_bar=colour_bar,
        want_cmyk=want_cmyk,
    )
    buf.seek(0)
    kind = "print" if print_mode else "certificates"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{kind}-{run_id}.zip",
    )


@W.require_run(deny=lambda: (abort(404)))
def pack_print_separations(run_id: str):
    """G1.17: the CMYK separations report for a run's brand colours.

    Machine-readable breakdown a club can hand to a print shop: each brand
    role's hex + uncalibrated CMYK percentages, the default print geometry,
    and whether the server can do a true DeviceCMYK conversion.
    """
    from mediahub.graphic_renderer.print_export import (
        cmyk_separations,
        geometry_for,
        ghostscript_available,
    )

    pid = W._run_owner_profile_id(run_id) or ""
    prof = W.load_profile(pid) if pid else None
    brand = {
        "primary": getattr(prof, "brand_primary", "#0A2540") if prof else "#0A2540",
        "secondary": getattr(prof, "brand_secondary", "#000000") if prof else "#000000",
    }
    geom = geometry_for("A4")
    return jsonify(
        {
            "run_id": run_id,
            "colour_mode": "CMYK (uncalibrated device preview)",
            "ghostscript_available": ghostscript_available(),
            "geometry": {
                "paper": "A4",
                "trim_mm": [geom.trim_w_mm, geom.trim_h_mm],
                "bleed_mm": geom.bleed_mm,
                "crop_mark_mm": geom.mark_len_mm,
                "media_mm": [geom.media_w_mm, geom.media_h_mm],
            },
            "separations": cmyk_separations(brand),
        }
    )


def documents_home():
    if not W._documents_ok:
        return W._recovery_page(
            "Documents unavailable",
            "The document engine isn't enabled on this deployment.",
            primary_cta=("Back to home", url_for("home")),
        )
    pid = W._phase_w_org()
    if not pid:
        return W._layout("Documents", W._PW_NO_ORG, active="create")
    from mediahub.documents import store as _docstore

    docs = _docstore.list_documents(pid)
    runs = W._doc_recent_runs(pid)

    run_opts = (
        "".join(
            f'<option value="{_h(rid)}">{_h(name)} ({n} cards)</option>' for rid, name, n in runs
        )
        or '<option value="">No processed meets yet</option>'
    )

    saved = ""
    if docs:
        rows = []
        for d in docs:
            badge = "Deck" if d["kind"] == "deck" else d["doc_format"].replace("_", " ").title()
            rows.append(
                '<a class="card" style="display:block;text-decoration:none" '
                f'href="{url_for("document_view", doc_id=d["doc_id"])}">'
                f"<strong>{_h(d['title'])}</strong>"
                f'<div class="dim" style="font-size:12px;margin-top:4px">{_h(badge)}</div></a>'
            )
        saved = (
            '<h2 style="margin-top:28px">Your documents</h2>'
            '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr));'
            f'gap:12px">{"".join(rows)}</div>'
        )

    body = (
        '<section class="mh-hero"><h1>Documents</h1>'
        '<p class="muted">Build a meet programme, season report, sponsor proposal or '
        "AGM deck from your real results — then export, present or download it.</p></section>"
        '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px">'
        # meet programme (meet scope)
        '<div class="card"><h3 style="margin-top:0">Meet programme</h3>'
        '<p class="dim" style="font-size:13px">A gala-night programme/recap from one meet.</p>'
        f'<select id="prog-run" class="input">{run_opts}</select>'
        + W._EDITORIAL_AI_CHECKBOX
        + '<button class="btn" style="margin-top:8px" '
        "onclick=\"genDoc(this,'meet_programme','meet',document.getElementById('prog-run').value)\">"
        "Generate</button></div>"
        # season report (season scope)
        '<div class="card"><h3 style="margin-top:0">Season report</h3>'
        '<p class="dim" style="font-size:13px">The committee report from your whole season.</p>'
        + W._EDITORIAL_AI_CHECKBOX
        + "<button class=\"btn\" onclick=\"genDoc(this,'season_report','season')\">Generate</button></div>"
        # sponsor proposal
        '<div class="card"><h3 style="margin-top:0">Sponsor proposal</h3>'
        '<p class="dim" style="font-size:13px">A sponsorship pitch with your reach and packages.</p>'
        + W._EDITORIAL_AI_CHECKBOX
        + "<button class=\"btn\" onclick=\"genDoc(this,'sponsor_proposal','season')\">Generate</button></div>"
        # AGM deck
        '<div class="card"><h3 style="margin-top:0">AGM deck</h3>'
        '<p class="dim" style="font-size:13px">The year in review, ready to present.</p>'
        + W._EDITORIAL_AI_CHECKBOX
        + "<button class=\"btn\" onclick=\"genDoc(this,'agm_deck','season')\">Generate</button></div>"
        "</div>"
        # tools row
        '<h2 style="margin-top:28px">PDF tools</h2>'
        '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px">'
        '<div class="card"><h3 style="margin-top:0">Import to edit</h3>'
        '<p class="dim" style="font-size:13px">Open a PDF, Word or PowerPoint file as an editable document (bounded fidelity).</p>'
        '<input type="file" id="imp-file" accept=".pdf,.docx,.pptx" class="input" '
        'aria-label="Choose a PDF, Word or PowerPoint file to import">'
        '<button class="btn secondary" style="margin-top:8px" onclick="importDoc()">Import</button></div>'
        '<div class="card"><h3 style="margin-top:0">Merge PDFs</h3>'
        '<p class="dim" style="font-size:13px">Combine several PDFs into one, in order.</p>'
        '<input type="file" id="merge-files" accept="application/pdf" multiple class="input" '
        'aria-label="Choose PDF files to merge">'
        '<button class="btn secondary" style="margin-top:8px" onclick="mergePdfs()">Merge &amp; download</button></div>'
        '<div class="card"><h3 style="margin-top:0">Images → PDF</h3>'
        '<p class="dim" style="font-size:13px">Turn photos/screenshots into a single PDF.</p>'
        '<input type="file" id="img-files" accept="image/*" multiple class="input" '
        'aria-label="Choose images to combine into a PDF">'
        '<button class="btn secondary" style="margin-top:8px" onclick="imagesToPdf()">Build &amp; download</button></div>'
        "</div>"
        + saved
        + W._DOCUMENTS_HOME_JS.replace("__GEN_URL__", url_for("api_documents_generate"))
        .replace("__IMPORT_URL__", url_for("api_documents_import"))
        .replace("__MERGE_URL__", url_for("api_documents_tool_merge"))
        .replace("__IMG_URL__", url_for("api_documents_tool_images_to_pdf"))
        .replace("__CSRF__", W._csrf_token())
    )
    return W._layout("Documents", body, active="create")


def document_view(doc_id: str):
    if not W._documents_ok:
        return W._recovery_page(
            "Documents unavailable", "Not enabled here.", primary_cta=("Home", url_for("home"))
        )
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return W._recovery_page(
            "Document not found",
            "It may have been deleted, or belongs to another organisation.",
            primary_cta=("All documents", url_for("documents_home")),
        )
    is_deck = spec.is_deck
    present_btns = ""
    if is_deck:
        present_btns = (
            f'<a class="btn" href="{url_for("document_present", doc_id=doc_id)}">Present</a> '
            f'<a class="btn secondary" href="{url_for("api_document_video", doc_id=doc_id)}">Download video (MP4)</a> '
        )
    spec_json = _h(json.dumps(spec.to_dict(), indent=2))
    # H-5: structured content editor above the raw-JSON hatch.
    from mediahub.web import spec_editor as _se

    doc_structured = (
        '<div class="card" style="margin-bottom:14px"><h3 style="margin-top:0">Edit content</h3>'
        '<p class="dim" style="font-size:13px">Change your wording here — no JSON needed. Tables, charts '
        "and images stay in the advanced editor below.</p>"
        f'<form method="post" action="{url_for("api_document_content_edit", doc_id=doc_id)}">'
        f"{_se.render_structured(spec.to_dict(), 'document')}"
        '<div style="margin-top:10px"><button class="btn" type="submit">Save changes</button></div>'
        "</form></div>"
    )
    body = (
        f'<section class="mh-hero"><h1>{_h(spec.title)}</h1>'
        f'<p class="muted">{_h(spec.subtitle or spec.doc_format.replace("_", " ").title())}</p></section>'
        '<div style="margin-bottom:14px">'
        + present_btns
        + f'<a class="btn secondary" href="{url_for("api_document_pdf", doc_id=doc_id)}?dl=1">Download PDF</a> '
        f'<a class="btn secondary" href="{url_for("api_document_pptx", doc_id=doc_id)}">PowerPoint (.pptx)</a> '
        f'<a class="btn secondary" href="{url_for("api_document_docx", doc_id=doc_id)}">Word (.docx)</a>'
        "</div>"
        f'<iframe src="{url_for("api_document_pdf", doc_id=doc_id)}" '
        'title="Document preview" '
        'style="width:100%;height:70vh;border:1px solid var(--panel);border-radius:8px;background:var(--panel)"></iframe>'
        + doc_structured
        + '<details style="margin-top:18px"><summary class="dim">Advanced — raw spec (JSON)</summary>'
        f'<textarea id="spec-json" class="input" style="width:100%;height:300px;font-family:monospace;font-size:12px">{spec_json}</textarea>'
        '<button class="btn" style="margin-top:8px" onclick="saveSpec()">Save changes</button> '
        '<button class="btn secondary" style="margin-top:8px" onclick="delDoc()">Delete document</button>'
        '<span id="save-msg" class="dim" style="margin-left:10px"></span></details>'
        + W._DOCUMENT_VIEW_JS.replace("__SAVE_URL__", url_for("api_document_save", doc_id=doc_id))
        .replace("__DEL_URL__", url_for("api_document_delete", doc_id=doc_id))
        .replace("__HOME_URL__", url_for("documents_home"))
    )
    return W._layout(spec.title, body, active="create")


def document_present(doc_id: str):
    if not W._documents_ok:
        return W._recovery_page(
            "Documents unavailable", "Not enabled here.", primary_cta=("Home", url_for("home"))
        )
    pid, spec = W._doc_load_owned(doc_id)
    if spec is None:
        return W._recovery_page(
            "Document not found",
            "It may have been deleted.",
            primary_cta=("All documents", url_for("documents_home")),
        )
    if not spec.is_deck:
        return W._recovery_page(
            "Not a deck",
            "Only AGM decks can be presented. Generate an AGM deck to present.",
            primary_cta=("All documents", url_for("documents_home")),
        )
    from mediahub.documents import presenter as _pres
    from mediahub.documents.deck import deck_view, spec_version

    # G-12: resume an existing live session for this deck+owner on reload
    # rather than reminting a session (and a new pairing code) every load —
    # a fresh code would desync the already-paired phone and audience view.
    _ver = spec_version(spec)
    session = _pres.get_live_for(doc_id, pid)
    if session is None:
        session = _pres.create_session(doc_id, len(spec.sections), owner=pid, spec_version=_ver)
    else:
        # Reflect any edit to the deck since the session started (bumps the
        # version only when the content actually changed, so an unchanged
        # reload doesn't needlessly reload the audience).
        resumed = _pres.update_spec(
            session.session_id, total_slides=len(spec.sections), spec_version=_ver
        )
        if resumed is not None:
            session = resumed
    view = deck_view(spec)
    # Script-safe JSON: neutralise </script> by escaping '<' (embedded as a JS
    # literal, not HTML), so speaker notes can carry any text.
    notes = json.dumps([s["notes"] for s in view["slides"]]).replace("<", "\\u003c")
    titles = json.dumps([s["title"] for s in view["slides"]]).replace("<", "\\u003c")
    body = (
        W._DOC_PRESENT_CONSOLE.replace("__TOTAL__", str(len(spec.sections)))
        .replace(
            "__SLIDE_URL__",
            url_for("api_present_slide", session_id=session.session_id, i=0).rsplit("/0", 1)[0],
        )
        .replace("__STATE_URL__", url_for("api_present_state", session_id=session.session_id))
        .replace("__ACTION_URL__", url_for("api_present_action", session_id=session.session_id))
        .replace("__AUDIENCE_URL__", url_for("present_audience", session_id=session.session_id))
        .replace("__DOC_URL__", url_for("document_view", doc_id=doc_id))
        .replace("__NOTES__", notes)
        .replace("__TITLES__", titles)
    )
    return W._layout("Presenting — " + spec.title, body, active="create")


def present_audience(session_id: str):
    if not W._documents_ok:
        return W._recovery_page(
            "Unavailable", "Not enabled here.", primary_cta=("Home", url_for("home"))
        )
    from mediahub.documents import presenter as _pres

    session = _pres.get_session(session_id)
    if session is None or session.ended:
        return W._recovery_page(
            "Presentation ended",
            "This presentation has finished or expired.",
            primary_cta=("Home", url_for("home")),
        )
    body = (
        W._DOC_PRESENT_AUDIENCE.replace("__TOTAL__", str(session.total_slides))
        .replace(
            "__SLIDE_URL__",
            url_for("api_present_slide", session_id=session_id, i=0).rsplit("/0", 1)[0],
        )
        .replace("__STATE_URL__", url_for("api_present_state", session_id=session_id))
    )
    return Response(body, mimetype="text/html")


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule(
        "/tools/mobile-parity", endpoint="mobile_parity_tool", view_func=mobile_parity_tool
    )
    app.add_url_rule("/research", endpoint="research_page", view_func=research_page)
    app.add_url_rule(
        "/motion/vocabulary",
        endpoint="motion_vocabulary_gallery",
        view_func=motion_vocabulary_gallery,
    )
    app.add_url_rule("/templates", endpoint="template_gallery", view_func=template_gallery)
    app.add_url_rule(
        "/templates/preview",
        endpoint="template_preview_gallery",
        view_func=template_preview_gallery,
    )
    app.add_url_rule(
        "/templates/preview/thumb/<archetype>/<pack_id>",
        endpoint="template_preview_thumb",
        view_func=template_preview_thumb,
    )
    app.add_url_rule("/studio", endpoint="design_studio", view_func=design_studio)
    app.add_url_rule("/make", endpoint="make_page", view_func=make_page)
    app.add_url_rule("/make/<ct>", endpoint="content_type_intro", view_func=content_type_intro)
    app.add_url_rule(
        "/free-text/quick",
        endpoint="stub_free_text_quick",
        view_func=stub_free_text_quick,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/free-text", endpoint="free_text_chat_page", view_func=free_text_chat_page, methods=["GET"]
    )
    app.add_url_rule(
        "/free-text/quick-build",
        endpoint="free_text_quick_build",
        view_func=free_text_quick_build,
        methods=["POST"],
    )
    app.add_url_rule(
        "/free-text/chat/new",
        endpoint="free_text_chat_new",
        view_func=free_text_chat_new,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/free-text/chat/<chat_id>",
        endpoint="free_text_chat_view",
        view_func=free_text_chat_view,
        methods=["GET"],
    )
    app.add_url_rule(
        "/free-text/chat/<chat_id>/send",
        endpoint="free_text_chat_send",
        view_func=free_text_chat_send,
        methods=["POST"],
    )
    app.add_url_rule(
        "/free-text/chat/<chat_id>/accept",
        endpoint="free_text_chat_accept",
        view_func=free_text_chat_accept,
        methods=["POST"],
    )
    app.add_url_rule(
        "/free-text/chat/<chat_id>/decline",
        endpoint="free_text_chat_decline",
        view_func=free_text_chat_decline,
        methods=["POST"],
    )
    app.add_url_rule(
        "/free-text/chat/<chat_id>/generate",
        endpoint="free_text_chat_generate",
        view_func=free_text_chat_generate,
        methods=["POST"],
    )
    app.add_url_rule("/brand", endpoint="brand_home_page", view_func=brand_home_page)
    app.add_url_rule("/pack/<run_id>", endpoint="content_pack", view_func=content_pack)
    app.add_url_rule(
        "/web-research", endpoint="web_research_console", view_func=web_research_console
    )
    app.add_url_rule("/club-qa", endpoint="club_qa_console", view_func=club_qa_console)
    app.add_url_rule(
        "/pack/<run_id>/grouped", endpoint="content_pack_grouped", view_func=content_pack_grouped
    )
    app.add_url_rule("/media-library", endpoint="media_library_page", view_func=media_library_page)
    app.add_url_rule(
        "/media-library/generated",
        endpoint="media_library_generated_page",
        view_func=media_library_generated_page,
    )
    app.add_url_rule(
        "/media-library/<asset_id>/cutout",
        endpoint="media_library_cutout_page",
        view_func=media_library_cutout_page,
    )
    app.add_url_rule(
        "/media-library/<asset_id>/studio",
        endpoint="image_studio_page",
        view_func=image_studio_page,
    )
    app.add_url_rule(
        "/media-library/<asset_id>/edit", endpoint="photo_editor_page", view_func=photo_editor_page
    )
    app.add_url_rule("/elements", endpoint="elements_page", view_func=elements_page)
    app.add_url_rule("/stock", endpoint="stock_page", view_func=stock_page)
    app.add_url_rule(
        "/public-wall", endpoint="public_wall_settings", view_func=public_wall_settings
    )
    app.add_url_rule(
        "/public-wall/update",
        endpoint="public_wall_update",
        view_func=public_wall_update,
        methods=["POST"],
    )
    app.add_url_rule("/wall/<token>", endpoint="public_wall_page", view_func=public_wall_page)
    app.add_url_rule(
        "/wall/<token>/embed", endpoint="public_wall_embed", view_func=public_wall_embed
    )
    app.add_url_rule(
        "/wall/<token>/feed.json", endpoint="public_wall_json", view_func=public_wall_json
    )
    app.add_url_rule(
        "/wall/<token>/feed.rss", endpoint="public_wall_rss", view_func=public_wall_rss
    )
    app.add_url_rule(
        "/wall/<token>/card/<run_id>/<card_id>.png",
        endpoint="public_wall_card_png",
        view_func=public_wall_card_png,
    )
    app.add_url_rule("/try", endpoint="try_demo", view_func=try_demo, methods=["GET", "POST"])
    app.add_url_rule(
        "/try/start", endpoint="try_demo_start", view_func=try_demo_start, methods=["POST"]
    )
    app.add_url_rule("/try/<run_id>", endpoint="try_demo_run", view_func=try_demo_run)
    app.add_url_rule(
        "/try/<run_id>/card/<card_id>.png",
        endpoint="try_demo_card_png",
        view_func=try_demo_card_png,
    )
    app.add_url_rule(
        "/try/<run_id>/claim", endpoint="try_demo_claim", view_func=try_demo_claim, methods=["POST"]
    )
    app.add_url_rule("/print", endpoint="print_center_page", view_func=print_center_page)
    app.add_url_rule(
        "/print/<run_id>", endpoint="print_run_tool_page", view_func=print_run_tool_page
    )
    app.add_url_rule("/export", endpoint="export_center_page", view_func=export_center_page)
    app.add_url_rule(
        "/export/<run_id>", endpoint="export_run_tool_page", view_func=export_run_tool_page
    )
    app.add_url_rule("/share/<token>", endpoint="share_review_page", view_func=share_review_page)
    app.add_url_rule(
        "/share/<token>/card/<card_id>.png", endpoint="share_card_png", view_func=share_card_png
    )
    app.add_url_rule(
        "/share/<token>/comment",
        endpoint="share_add_comment",
        view_func=share_add_comment,
        methods=["POST"],
    )
    app.add_url_rule("/pack/<run_id>/zip", endpoint="content_pack_zip", view_func=content_pack_zip)
    app.add_url_rule(
        "/pack/<run_id>/export.zip", endpoint="pack_export_zip", view_func=pack_export_zip
    )
    app.add_url_rule("/club-data", endpoint="club_data_page", view_func=club_data_page)
    app.add_url_rule("/data-hub", endpoint="data_hub_page", view_func=data_hub_page)
    app.add_url_rule(
        "/data-hub/table/<table_id>", endpoint="data_hub_table", view_func=data_hub_table
    )
    app.add_url_rule(
        "/data-hub/export/<table_id>", endpoint="data_hub_export", view_func=data_hub_export
    )
    app.add_url_rule("/records", endpoint="club_records_page", view_func=club_records_page)
    app.add_url_rule(
        "/records/action",
        endpoint="club_records_action",
        view_func=club_records_action,
        methods=["POST"],
    )
    app.add_url_rule("/live", endpoint="live_meet_page", view_func=live_meet_page)
    app.add_url_rule(
        "/live/action", endpoint="live_meet_action", view_func=live_meet_action, methods=["POST"]
    )
    app.add_url_rule(
        "/pack/<run_id>/certificates.zip",
        endpoint="pack_certificates_zip",
        view_func=pack_certificates_zip,
    )
    app.add_url_rule(
        "/pack/<run_id>/print/separations.json",
        endpoint="pack_print_separations",
        view_func=pack_print_separations,
    )
    app.add_url_rule("/documents", endpoint="documents_home", view_func=documents_home)
    app.add_url_rule("/documents/<doc_id>", endpoint="document_view", view_func=document_view)
    app.add_url_rule(
        "/documents/<doc_id>/present", endpoint="document_present", view_func=document_present
    )
    app.add_url_rule(
        "/present/<session_id>", endpoint="present_audience", view_func=present_audience
    )
