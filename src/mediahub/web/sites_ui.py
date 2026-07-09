"""web.sites_ui — operator HTML for the club-microsite surface (roadmap 1.16).

Pure rendering helpers kept out of the monolith for testability (mirrors
:mod:`web.data_hub_ui`). Everything is server-rendered and escaped
(``markupsafe.escape``); the route layer wraps these with ``_layout`` and supplies
the live data. State-changing actions are plain ``POST`` forms (the app
auto-injects the CSRF token); the device-preview switch is pure CSS (no JS), and
the only iframe points at the same-origin draft-preview route.
"""

from __future__ import annotations

from flask import url_for
from markupsafe import escape as _h

from mediahub.sites.models import SITE_ARCHETYPES, SiteSpec
from mediahub.web import spec_editor as _se

_ARCHETYPE_LABELS = {
    "club_home": "Club home",
    "link_in_bio": "Link in bio",
    "meet_microsite": "Meet microsite",
    "event_page": "Event page",
    "blank": "Blank",
}


def _archetype_label(key: str) -> str:
    return _ARCHETYPE_LABELS.get(key, key.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def render_index(sites: list[dict], forms: list[dict], runs: list[tuple]) -> str:
    arch_opts = "".join(
        f'<option value="{_h(a)}">{_h(_archetype_label(a))}</option>'
        for a in SITE_ARCHETYPES
        if a != "blank"
    )
    run_opts = '<option value="">Just my club details</option>' + "".join(
        f'<option value="{_h(rid)}">{_h(meet)}</option>' for rid, meet, _n in runs
    )
    create = (
        '<div class="card"><h3 style="margin-top:0">New site</h3>'
        '<p class="dim" style="font-size:13px">Pick a kind of page; MediaHub fills it from your '
        "club details and approved content. You can edit everything after.</p>"
        f'<form method="post" action="{url_for("api_sites_generate")}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
        f'<select name="archetype" style="padding:7px">{arch_opts}</select>'
        f'<select name="run_id" style="padding:7px">{run_opts}</select>'
        '<label style="font-size:13px;display:flex;gap:6px;align-items:center">'
        '<input type="checkbox" name="with_ai" value="1"> Write copy with AI</label>'
        '<button class="btn" type="submit">Create site</button></form></div>'
    )

    if sites:
        rows = []
        for s in sites:
            status = (
                '<span class="tag live">Published</span>'
                if s.get("published")
                else '<span class="tag">Draft</span>'
            )
            pub = ""
            if s.get("published") and s.get("public_token"):
                pub_url = url_for("site_public_home", token=s["public_token"], _external=True)
                pub = f' &middot; <a href="{_h(pub_url)}" rel="noopener" target="_blank">View live</a>'
            edit = url_for("site_editor", site_id=s["site_id"])
            rows.append(
                '<div class="card" style="display:flex;justify-content:space-between;'
                'align-items:center;gap:12px;flex-wrap:wrap">'
                f'<div><a href="{_h(edit)}"><strong>{_h(s["title"])}</strong></a> '
                f'<span class="dim" style="font-size:12px">· {_h(_archetype_label(s.get("archetype", "")))} '
                f"· {s.get('n_pages', 0)} page(s)</span><br>{status}{pub}</div>"
                f'<a class="btn secondary" href="{_h(edit)}">Open editor</a></div>'
            )
        sites_html = "".join(rows)
    else:
        sites_html = '<div class="card"><p class="dim">No sites yet — create one above.</p></div>'

    forms_html = _render_forms_card(forms)
    return (
        '<h1 style="margin:.2em 0">Sites</h1>'
        '<p class="dim">Club home pages, link-in-bio pages, meet microsites and event pages — '
        "generated from your data, published when you approve them.</p>"
        f"{create}{sites_html}{forms_html}"
    )


def _render_forms_card(forms: list[dict]) -> str:
    create = (
        f'<form method="post" action="{url_for("api_forms_create")}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px">'
        '<input name="title" placeholder="Form name" required style="padding:7px">'
        '<select name="template" style="padding:7px">'
        '<option value="trial_signup">Trial sign-up</option>'
        '<option value="rsvp">Event RSVP</option>'
        '<option value="blank">Blank</option></select>'
        '<button class="btn secondary" type="submit">Create form</button></form>'
    )
    if forms:
        items = []
        for f in forms:
            embed = f"<code>{_h(f['form_id'])}</code>"
            responses = ""
            if f.get("table_id"):
                responses = (
                    f' &middot; <a href="{url_for("data_hub_table", table_id=f["table_id"])}">'
                    "View responses</a>"
                )
            minor = (
                ' <span class="tag" title="Collects a minor\'s data">minors</span>'
                if f.get("collects_minor_data")
                else ""
            )
            del_url = url_for("api_form_delete", form_id=f["form_id"])
            items.append(
                '<li style="margin:6px 0">'
                f"<strong>{_h(f['title'])}</strong>{minor} "
                f'<span class="dim" style="font-size:12px">embed id: {embed} · '
                f"{f.get('n_fields', 0)} field(s){responses}</span> "
                f'<form method="post" action="{_h(del_url)}" style="display:inline" '
                "onsubmit=\"return confirm('Delete this form? Responses stay in the data hub.')\">"
                '<button class="btn-link" type="submit" style="color:var(--mh-error,#e66)">delete</button>'
                "</form></li>"
            )
        forms_list = f'<ul style="list-style:none;padding:0">{"".join(items)}</ul>'
    else:
        forms_list = '<p class="dim">No forms yet. Create one, then add a <em>form</em> block to a page using its embed id.</p>'
    return (
        '<div class="card" style="margin-top:16px"><h3 style="margin-top:0">Forms</h3>'
        '<p class="dim" style="font-size:13px">Trial sign-ups, RSVPs and more. Responses land as '
        "rows in your data hub. Add a form to a page with a <code>form_embed</code> block "
        "carrying its embed id.</p>"
        f"{forms_list}{create}</div>"
    )


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------


def render_editor(
    rec: dict,
    spec: SiteSpec,
    *,
    forms: list[dict],
    insights: dict,
    flash: str = "",
    flash_is_error: bool = False,
    spec_override=None,
) -> str:
    site_id = rec["site_id"]
    published = bool(rec.get("published"))
    preview_url = url_for("site_preview_home", site_id=site_id)

    status = (
        '<span class="tag live">Published</span>' if published else '<span class="tag">Draft</span>'
    )
    public_block = ""
    if published and rec.get("public_token"):
        pub_url = url_for("site_public_home", token=rec["public_token"], _external=True)
        public_block = (
            f'<p style="margin:.4em 0">Live at <a href="{_h(pub_url)}" rel="noopener" '
            f'target="_blank">{_h(pub_url)}</a></p>'
            '<div style="display:flex;gap:8px;flex-wrap:wrap">'
            f'<a class="btn secondary" href="{url_for("api_site_qr", site_id=site_id, fmt="png")}">QR (PNG)</a>'
            f'<a class="btn secondary" href="{url_for("api_site_qr", site_id=site_id, fmt="svg")}">QR (SVG)</a>'
            f'<a class="btn secondary" href="{url_for("api_site_qr", site_id=site_id, fmt="pdf")}">QR (PDF)</a>'
            "</div>"
        )

    publish_btn = (
        f'<form method="post" action="{url_for("api_site_unpublish", site_id=site_id)}" style="display:inline">'
        '<button class="btn secondary" type="submit">Unpublish</button></form>'
        if published
        else f'<form method="post" action="{url_for("api_site_publish", site_id=site_id)}" style="display:inline">'
        '<button class="btn" type="submit">Publish</button></form>'
    )

    # H-6: an error flash (e.g. invalid JSON) must NOT wear the success colour.
    _flash_border = "var(--mh-bad,#c33)" if flash_is_error else "var(--mh-success,#3a7)"
    flash_html = (
        f'<div class="card" style="border-color:{_flash_border}"><p>{_h(flash)}</p></div>'
        if flash
        else ""
    )

    # device preview — pure-CSS width toggle around a same-origin iframe
    preview = f"""
<div class="card"><h3 style="margin-top:0">Preview</h3>
<div class="dev-prev">
  <input type="radio" name="dev" id="dev-d" checked><label for="dev-d">Desktop</label>
  <input type="radio" name="dev" id="dev-t"><label for="dev-t">Tablet</label>
  <input type="radio" name="dev" id="dev-m"><label for="dev-m">Mobile</label>
  <div class="dev-stage"><iframe class="dev-frame" src="{_h(preview_url)}" title="Site preview"></iframe></div>
</div>
<style>
.dev-prev label{{display:inline-block;padding:5px 12px;border:1px solid var(--line,#2a3550);border-radius:8px;
  margin:0 4px 10px 0;cursor:pointer;font-size:13px}}
.dev-prev input[type=radio]{{position:absolute;opacity:0;pointer-events:none}}
.dev-prev input:checked+label{{border-color:var(--accent,#7cf);color:var(--accent,#7cf)}}
.dev-stage{{background:#0c1018;border:1px solid var(--line,#2a3550);border-radius:10px;padding:14px;overflow:auto;display:flex;justify-content:center}}
.dev-frame{{width:100%;height:640px;border:0;background:#fff;border-radius:8px;transition:width .2s ease}}
#dev-t:checked~.dev-stage .dev-frame{{width:820px}}
#dev-m:checked~.dev-stage .dev-frame{{width:390px}}
</style></div>"""

    # H-5: a structured content editor (per-section title / intro / link fields)
    # so editing wording no longer means hand-writing raw spec JSON. Advanced
    # blocks (images, cards, charts) stay in the raw hatch below, which is kept
    # verbatim as the "Advanced" escape hatch.
    structured_body = _se.render_structured(spec.to_dict(), "site")
    structured = f"""
<div class="card"><h3 style="margin-top:0">Edit content</h3>
<p class="dim" style="font-size:13px">Change your wording and links here — no JSON needed. Photos, card
grids and charts stay in the advanced editor below. Publishing freezes a snapshot of the current draft.</p>
<form method="post" action="{url_for("api_site_content_edit", site_id=site_id)}">
{structured_body}
<div style="margin-top:10px"><button class="btn" type="submit">Save changes</button></div>
</form></div>"""

    # H-6: on a failed save the caller passes the user's SUBMITTED text so a
    # single JSON typo never wipes their edits; otherwise pretty-print the
    # stored spec as before.
    spec_json = _h(spec_override) if spec_override is not None else _h(_pretty(spec))
    editor = f"""
<div class="card"><h3 style="margin-top:0">Advanced — raw spec (JSON)</h3>
<p class="dim" style="font-size:13px">The site is plain data (pages → sections → blocks). This is the full
editor for anything the structured fields above don't cover; edit and save, and the preview refreshes.</p>
<form method="post" action="{url_for("api_site_save", site_id=site_id)}" onsubmit="return mhSiteSpecValid(this)">
<textarea name="spec" spellcheck="false" style="width:100%;min-height:420px;font-family:ui-monospace,monospace;
  font-size:12px;padding:12px;border-radius:8px;border:1px solid var(--line,#2a3550);
  background:#0c1018;color:#cfe">{spec_json}</textarea>
<div id="mh-site-spec-err" style="display:none;margin-top:8px;padding:8px 10px;border-radius:6px;
  border:1px solid var(--mh-bad,#c33);color:var(--mh-bad,#c33);font-size:12px"></div>
<div style="margin-top:10px"><button class="btn" type="submit">Save changes</button></div>
</form>
<script>
function mhSiteSpecValid(f) {{
  var box = document.getElementById('mh-site-spec-err');
  try {{ JSON.parse(f.spec.value); if (box) box.style.display = 'none'; return true; }}
  catch (e) {{
    if (box) {{
      box.textContent = 'Not valid JSON (' + e.message + '). Fix it and save again — your text is kept.';
      box.style.display = 'block';
    }}
    return false;
  }}
}}
</script></div>"""

    insights_html = _render_insights(insights)
    forms_html = _render_forms_card(forms)

    # D-8: a per-page "members-only" toggle so protection is a real editor
    # control, not a raw-JSON flag — and honest warnings when a password and
    # protected pages are out of step (either one alone protects nothing).
    has_pw = bool(rec.get("has_password"))
    any_protected = any(p.protected for p in spec.pages)
    prot_rows = ""
    for pg in spec.pages:
        label = pg.title or (pg.slug or "Home")
        checked = " checked" if pg.protected else ""
        prot_rows += (
            '<label style="display:flex;gap:8px;align-items:center;font-size:13px;margin:2px 0">'
            f'<input type="checkbox" name="protected" value="{_h(pg.slug)}"{checked}> '
            f"{_h(label)}</label>"
        )
    if has_pw and not any_protected:
        prot_warn = (
            '<p style="color:var(--mh-error,#e66);font-size:12px;margin:8px 0 0">A password is '
            "set, but no page is members-only yet — the site is still fully public. Tick a page "
            "above to protect it.</p>"
        )
    elif any_protected and not has_pw:
        prot_warn = (
            '<p style="color:var(--mh-error,#e66);font-size:12px;margin:8px 0 0">Some pages are '
            "members-only, but no password is set — set one above to actually lock them.</p>"
        )
    else:
        prot_warn = ""
    protection = (
        f'<form method="post" action="{url_for("api_site_page_protection", site_id=site_id)}" '
        'style="margin:12px 0 0">'
        '<div class="dim" style="font-size:12px;margin-bottom:4px">Members-only pages '
        "(shown only after the password):</div>"
        + (prot_rows or '<span class="dim" style="font-size:12px">No pages yet.</span>')
        + '<div style="margin-top:8px"><button class="btn secondary" type="submit">'
        "Update members-only pages</button></div>" + prot_warn + "</form>"
    )

    danger = (
        '<div class="card" style="border-color:var(--mh-error,#e66)">'
        '<h3 style="margin-top:0">Access &amp; danger zone</h3>'
        f'<form method="post" action="{url_for("api_site_password", site_id=site_id)}" '
        'style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">'
        '<input name="password" type="text" placeholder="Set a page password (blank to clear)" style="padding:7px">'
        f'<button class="btn secondary" type="submit">{"Update" if has_pw else "Set"} password</button>'
        + ('  <span class="dim" style="font-size:12px">A password is set.</span>' if has_pw else "")
        + "</form>"
        + protection
        + '<hr style="border:none;border-top:1px solid var(--line,#2a3550);margin:14px 0">'
        + f'<form method="post" action="{url_for("api_site_delete", site_id=site_id)}" '
        "onsubmit=\"return confirm('Delete this site permanently?')\">"
        '<button class="btn secondary" type="submit" style="color:var(--mh-error,#e66)">Delete site</button>'
        "</form></div>"
    )

    header = (
        f'<p style="margin:0"><a href="{url_for("sites_home")}">&larr; All sites</a></p>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">'
        f'<h1 style="margin:.2em 0">{_h(spec.title)} {status}</h1>'
        f'<div style="display:flex;gap:8px">{publish_btn}</div></div>'
        f"{public_block}"
    )

    return (
        flash_html
        + header
        + '<div class="mh-sites-grid" style="display:grid;gap:16px;grid-template-columns:1fr">'
        + preview
        + structured
        + editor
        + forms_html
        + insights_html
        + danger
        + "</div>"
    )


def _render_insights(insights: dict) -> str:
    total = int((insights or {}).get("total", 0))
    by_page = (insights or {}).get("by_page", {}) or {}
    rows = "".join(
        f"<li>{_h(slug or 'home')}: <strong>{int(n)}</strong></li>"
        for slug, n in sorted(by_page.items(), key=lambda kv: -kv[1])
    )
    body = (
        f'<p style="font-size:1.4em;margin:.2em 0"><strong>{total}</strong> total views</p>'
        + (f'<ul style="columns:2;font-size:13px">{rows}</ul>' if rows else "")
        if total
        else '<p class="dim">No views yet. Views are counted privately — no cookies, no tracking.</p>'
    )
    return f'<div class="card"><h3 style="margin-top:0">Insights</h3>{body}</div>'


def _pretty(spec: SiteSpec) -> str:
    import json

    return json.dumps(spec.to_dict(), indent=2, ensure_ascii=False)


__all__ = ["render_index", "render_editor"]
