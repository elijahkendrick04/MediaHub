"""web.elements_browser — the Elements browse + search surface (roadmap 1.10, build 2).

Renders the standalone Elements gallery: a recoloured, on-brand grid of the
curated library with AI/keyword search, kind filters, and brand-palette gradient
presets. When opened in a card's context (``run_id`` + ``card_id``) each element
gains an "Add to card" action that appends a placement to the card's brief.

Pure presentation — all data comes from the ``/api/elements*`` routes in
``web.py``. Kept out of the monolith (like ``web.photo_editor``) so the page is
readable on its own.
"""

from __future__ import annotations

import json
from html import escape as _h


def _script_json(obj: object) -> str:
    """JSON safe to embed inside a ``<script>`` (no ``</script>`` break-out)."""
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_browser_body(
    *,
    elements: list[dict],
    kinds: list[str],
    gradients: list[dict],
    semantic: bool,
    search_url: str,
    add_url: str = "",
    list_url: str = "",
    suggest_url: str = "",
    card_label: str = "",
    stock_url: str = "",
    activity_url: str = "",
    card_url: str = "",
) -> str:
    """The Elements browser page body (HTML + scoped CSS + JS).

    ``activity_url`` (C-12): where to send a browse-only visitor so they can
    open a meet's cards and actually place elements. ``card_url`` (C-12): the
    review page of the card being edited, linked from the add-to-card toast.
    """
    in_card = bool(add_url and list_url)
    boot = {
        "searchUrl": search_url,
        "addUrl": add_url,
        "listUrl": list_url,
        "suggestUrl": suggest_url,
        "semantic": bool(semantic),
        "inCard": in_card,
        "cardUrl": card_url,
    }

    kind_chips = "".join(
        f'<button type="button" class="eb-chip" data-kind="{_h(k)}">{_h(k.title())}</button>'
        for k in kinds
    )

    search_ph = (
        "Search elements — try “relay”, “a fast feel”, “celebration”…"
        if semantic
        else "Search elements by name or tag…"
    )
    ai_badge = (
        '<span class="eb-ai on" title="Semantic search is on">AI search</span>'
        if semantic
        else '<span class="eb-ai off" title="No embedding provider configured — keyword search">Keyword</span>'
    )

    context_line = ""
    if in_card:
        context_line = (
            f'<div class="eb-context">Adding to <strong>{_h(card_label or "this card")}</strong>'
            ' · <button type="button" id="eb-suggest" class="eb-link">Suggest for this card</button>'
            ' · <button type="button" id="eb-clear" class="eb-link danger">Clear elements</button></div>'
        )
    elif activity_url:
        # C-12: opened from a plain link (no run/card context) the page used
        # to be silently look-don't-touch. Say what elements are FOR and route
        # the visitor into the card flow where "Add to card" actually works.
        context_line = (
            '<div class="eb-explain">'
            "<strong>Elements are stickers and badges you add to a card.</strong> "
            "Browse them here any time — to place one, open a processed meet and "
            "pick a card; the card&rsquo;s builder brings you back with "
            "&ldquo;Add to card&rdquo; switched on. "
            f'<a href="{_h(activity_url)}">Open a meet&rsquo;s builder &rarr;</a>'
            "</div>"
        )

    grad_html = "".join(
        f'<div class="eb-grad" title="{_h(g.get("name", ""))}" '
        f'style="background:{_h(g.get("css", ""))}"><span>{_h(g.get("name", ""))}</span></div>'
        for g in gradients
    )

    return f"""
<div class="eb-wrap">
  <style>
    .eb-wrap {{ max-width: 1100px; margin: 0 auto; padding: 8px 0 64px; }}
    .eb-head {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:6px; }}
    .eb-head h1 {{ font-size:22px; margin:0; letter-spacing:-0.01em; }}
    .eb-ai {{ font-size:11px; font-weight:700; padding:3px 8px; border-radius:999px; letter-spacing:.04em; }}
    .eb-ai.on {{ background:var(--accent,#FFB81C); color:#10131a; }}
    .eb-ai.off {{ background:var(--panel,#1a1f29); color:var(--ink-dim,#9aa3b2); border:1px solid var(--line,#2a3140); }}
    .eb-sub {{ color:var(--ink-muted,#9aa3b2); font-size:13px; margin:0 0 16px; }}
    .eb-search {{ width:100%; padding:13px 16px; font-size:15px; border-radius:12px;
      border:1px solid var(--line,#2a3140); background:var(--panel,#141821); color:var(--ink,#e8ecf3);
      outline:none; }}
    .eb-search:focus {{ border-color:var(--accent,#FFB81C); }}
    .eb-filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:14px 0; }}
    .eb-chip {{ padding:6px 13px; border-radius:999px; font-size:13px; cursor:pointer;
      border:1px solid var(--line,#2a3140); background:transparent; color:var(--ink-dim,#9aa3b2); }}
    .eb-chip.active {{ background:var(--accent,#FFB81C); color:#10131a; border-color:var(--accent,#FFB81C); font-weight:700; }}
    .eb-context {{ font-size:13px; color:var(--ink-muted,#9aa3b2); margin:6px 0 14px; }}
    .eb-explain {{ font-size:13px; line-height:1.55; color:var(--ink-muted,#9aa3b2);
      border:1px dashed var(--line,#2a3140); border-radius:12px; padding:12px 14px; margin:6px 0 16px; }}
    .eb-explain strong {{ color:var(--ink,#e8ecf3); }}
    .eb-explain a {{ color:var(--accent,#FFB81C); }}
    .eb-link {{ background:none; border:none; color:var(--accent,#FFB81C); cursor:pointer; font-size:13px; padding:0; }}
    .eb-link.danger {{ color:#f0808a; }}
    .eb-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; }}
    .eb-card {{ border:1px solid var(--line,#2a3140); border-radius:14px; overflow:hidden;
      background:var(--panel,#141821); display:flex; flex-direction:column; transition:border-color .12s; }}
    .eb-card:hover {{ border-color:var(--accent,#FFB81C); }}
    .eb-thumb {{ aspect-ratio:1/1; display:flex; align-items:center; justify-content:center;
      padding:22px; background:var(--bg,#0b0e14); }}
    .eb-thumb svg {{ max-width:100%; max-height:100%; }}
    .eb-meta {{ padding:9px 12px; border-top:1px solid var(--line,#2a3140); }}
    .eb-name {{ font-size:13px; font-weight:600; color:var(--ink,#e8ecf3); }}
    .eb-kind {{ font-size:11px; color:var(--ink-dim,#7e8696); text-transform:uppercase; letter-spacing:.05em; }}
    .eb-add {{ width:100%; margin-top:8px; padding:7px; border-radius:8px; cursor:pointer;
      border:none; background:var(--accent,#FFB81C); color:#10131a; font-weight:700; font-size:12px; }}
    .eb-add:disabled {{ opacity:.5; cursor:default; }}
    .eb-grads {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; margin-top:10px; }}
    .eb-grad {{ aspect-ratio:16/9; border-radius:12px; border:1px solid var(--line,#2a3140);
      display:flex; align-items:flex-end; padding:8px; }}
    .eb-grad span {{ font-size:11px; font-weight:700; color:#fff; text-shadow:0 1px 3px rgba(0,0,0,.6); }}
    .eb-section-title {{ font-size:15px; font-weight:700; margin:34px 0 4px; }}
    .eb-empty {{ color:var(--ink-dim,#7e8696); padding:40px; text-align:center; }}
    .eb-toast {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
      background:var(--accent,#FFB81C); color:#10131a; padding:10px 18px; border-radius:10px;
      font-weight:700; font-size:13px; opacity:0; transition:opacity .2s; pointer-events:none; z-index:50; }}
    .eb-toast.show {{ opacity:1; }}
    /* C-12: a toast carrying a "back to the card" link must be clickable. */
    .eb-toast.linky {{ pointer-events:auto; }}
    .eb-toast a {{ color:inherit; text-decoration:underline; }}
  </style>

  <div class="eb-head">
    <h1>Elements</h1>
    {ai_badge}
    {f'<a class="eb-link" href="{_h(stock_url)}" style="margin-left:auto">Browse stock photos &rarr;</a>' if stock_url else ""}
  </div>
  <p class="eb-sub">A curated, on-brand set of sport-editorial stickers, chips, dividers and frames —
    every one painted in your club colours automatically.</p>

  {context_line}

  <input type="search" id="eb-search" class="eb-search" placeholder="{_h(search_ph)}" autocomplete="off">
  <div class="eb-filters" id="eb-filters">
    <button type="button" class="eb-chip active" data-kind="">All</button>
    {kind_chips}
  </div>

  <div class="eb-grid" id="eb-grid"></div>

  <div class="eb-section-title">Brand gradients</div>
  <p class="eb-sub">Colour fades built from your palette — never an off-brand hue.</p>
  <div class="eb-grads">{grad_html}</div>

  <div class="eb-toast" id="eb-toast"></div>
</div>

<script>
(function() {{
  var BOOT = {_script_json(boot)};
  var SEED = {_script_json(elements)};
  var grid = document.getElementById('eb-grid');
  var searchEl = document.getElementById('eb-search');
  var filters = document.getElementById('eb-filters');
  var toastEl = document.getElementById('eb-toast');
  var activeKind = '';
  var timer = null;

  function toast(msg) {{
    toastEl.textContent = msg; toastEl.classList.remove('linky'); toastEl.classList.add('show');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(function(){{ toastEl.classList.remove('show'); }}, 1600);
  }}

  // C-12: success toasts that should route the user somewhere carry a real
  // link (DOM-built — never innerHTML with data) and stay up long enough to
  // click.
  function toastLink(msg, href, label) {{
    if (!href) {{ toast(msg); return; }}
    toastEl.textContent = '';
    toastEl.appendChild(document.createTextNode(msg + ' '));
    var a = document.createElement('a');
    a.href = href; a.textContent = label;
    toastEl.appendChild(a);
    toastEl.classList.add('show', 'linky');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(function(){{ toastEl.classList.remove('show', 'linky'); }}, 6000);
  }}

  function card(el) {{
    // Build with DOM APIs, not innerHTML string concat: el.name / el.kind / el.id
    // come from the (org-custom) catalog and must never be parsed as HTML. Only
    // el.svg is injected as markup, and it is sanitised server-side
    // (elements.recolour._sanitise_svg) before it reaches here.
    var d = document.createElement('div'); d.className = 'eb-card';
    var thumb = document.createElement('div'); thumb.className = 'eb-thumb';
    thumb.innerHTML = el.svg || '';
    var meta = document.createElement('div'); meta.className = 'eb-meta';
    var nm = document.createElement('div'); nm.className = 'eb-name'; nm.textContent = el.name || '';
    var kd = document.createElement('div'); kd.className = 'eb-kind'; kd.textContent = el.kind || '';
    meta.appendChild(nm); meta.appendChild(kd);
    if (BOOT.inCard) {{
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'eb-add';
      btn.setAttribute('data-id', el.id || ''); btn.textContent = 'Add to card';
      meta.appendChild(btn);
    }}
    d.appendChild(thumb); d.appendChild(meta);
    return d;
  }}

  function render(items) {{
    grid.innerHTML = '';
    if (!items || !items.length) {{
      grid.innerHTML = '<div class="eb-empty">No elements match — try a different word.</div>';
      return;
    }}
    items.forEach(function(el) {{ grid.appendChild(card(el)); }});
  }}

  function fetchElements() {{
    var q = searchEl.value.trim();
    var u = BOOT.searchUrl + '?q=' + encodeURIComponent(q) + '&kind=' + encodeURIComponent(activeKind);
    fetch(u, {{headers: {{'Accept': 'application/json'}}}})
      .then(function(r){{ return r.json(); }})
      .then(function(d){{ render(d.elements || []); }})
      .catch(function(){{ /* keep last results on error */ }});
  }}

  filters.addEventListener('click', function(ev) {{
    var b = ev.target.closest('.eb-chip'); if (!b) return;
    activeKind = b.getAttribute('data-kind') || '';
    Array.prototype.forEach.call(filters.querySelectorAll('.eb-chip'), function(c){{ c.classList.remove('active'); }});
    b.classList.add('active');
    fetchElements();
  }});

  searchEl.addEventListener('input', function() {{
    clearTimeout(timer); timer = setTimeout(fetchElements, 220);
  }});

  grid.addEventListener('click', function(ev) {{
    var b = ev.target.closest('.eb-add'); if (!b || !BOOT.inCard) return;
    b.disabled = true;
    fetch(BOOT.addUrl, {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{element_id: b.getAttribute('data-id')}})
    }}).then(function(r){{ return r.json(); }})
      .then(function(d){{
        if (d.ok) {{
          toastLink('Added — re-render the card to see it.', BOOT.cardUrl, 'Back to the card →');
        }} else {{
          toast(d.error || 'Could not add');
        }}
        b.disabled = false;
      }})
      .catch(function(){{ toast('Could not add'); b.disabled = false; }});
  }});

  var suggestBtn = document.getElementById('eb-suggest');
  if (suggestBtn && BOOT.suggestUrl) {{
    suggestBtn.addEventListener('click', function() {{
      fetch(BOOT.suggestUrl, {{headers:{{'Accept':'application/json'}}}})
        .then(function(r){{ return r.json(); }})
        .then(function(d){{ render(d.elements || []); toast('Suggested for this card'); }})
        .catch(function(){{ toast('Could not load suggestions'); }});
    }});
  }}

  var clearBtn = document.getElementById('eb-clear');
  if (clearBtn && BOOT.addUrl) {{
    clearBtn.addEventListener('click', function() {{
      fetch(BOOT.addUrl, {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{clear: true}})
      }}).then(function(r){{ return r.json(); }})
        .then(function(d){{ toast(d.ok ? 'Cleared elements from card' : 'Could not clear'); }})
        .catch(function(){{ toast('Could not clear'); }});
    }});
  }}

  render(SEED);
}})();
</script>
"""


def render_stock_body(
    *, search_url: str, import_url: str, sources: dict, proxy_url: str = ""
) -> str:
    """The licence-clean stock browser body (search → add to library).

    ``proxy_url`` is the first-party thumbnail proxy (``/api/stock/thumb``).
    Stock thumbnails are cross-origin and the app CSP pins ``img-src 'self'``,
    so each tile loads through the proxy (same origin) rather than the raw CDN
    URL — otherwise the browser blocks the load and the tile renders blank.
    """
    boot = {"searchUrl": search_url, "importUrl": import_url, "proxyUrl": proxy_url}
    paid_on = [s for s in ("pexels", "pixabay") if sources.get(s)]
    paid_note = (
        f" · paid sources on: {', '.join(paid_on)}"
        if paid_on
        else " · free sources only (Openverse, Wikimedia)"
    )
    return f"""
<div class="sb-wrap">
  <style>
    .sb-wrap {{ max-width:1100px; margin:0 auto; padding:8px 0 64px; }}
    .sb-wrap h1 {{ font-size:22px; margin:0 0 4px; }}
    .sb-sub {{ color:var(--ink-muted,#9aa3b2); font-size:13px; margin:0 0 16px; }}
    .sb-row {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
    .sb-search {{ flex:1; min-width:240px; padding:13px 16px; font-size:15px; border-radius:12px;
      border:1px solid var(--line,#2a3140); background:var(--panel,#141821); color:var(--ink,#e8ecf3); outline:none; }}
    .sb-search:focus {{ border-color:var(--accent,#FFB81C); }}
    .sb-kind {{ padding:11px 14px; border-radius:12px; border:1px solid var(--line,#2a3140);
      background:var(--panel,#141821); color:var(--ink,#e8ecf3); }}
    .sb-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:14px; margin-top:18px; }}
    .sb-card {{ border:1px solid var(--line,#2a3140); border-radius:14px; overflow:hidden; background:var(--panel,#141821); }}
    .sb-thumb {{ position:relative; aspect-ratio:4/3; background:var(--bg,#0b0e14);
      display:flex; align-items:center; justify-content:center; overflow:hidden; }}
    .sb-thumb img {{ width:100%; height:100%; object-fit:cover; display:block; }}
    .sb-noimg {{ font-size:11px; color:var(--ink-dim,#7e8696); letter-spacing:.04em; }}
    .sb-play {{ position:absolute; inset:0; margin:auto; width:40px; height:40px; pointer-events:none;
      display:flex; align-items:center; justify-content:center; padding-left:3px;
      background:rgba(0,0,0,.5); color:#fff; border-radius:999px; font-size:15px; }}
    .sb-meta {{ padding:10px 12px; }}
    .sb-attr {{ font-size:11px; color:var(--ink-dim,#7e8696); margin:2px 0 8px; }}
    .sb-lic {{ font-size:11px; color:var(--accent,#FFB81C); font-weight:700; }}
    .sb-add {{ width:100%; padding:8px; border-radius:8px; border:none; cursor:pointer;
      background:var(--accent,#FFB81C); color:#10131a; font-weight:700; font-size:12px; }}
    .sb-add:disabled {{ opacity:.5; cursor:default; }}
    .sb-empty {{ color:var(--ink-dim,#7e8696); padding:40px; text-align:center; }}
    .sb-toast {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
      background:var(--accent,#FFB81C); color:#10131a; padding:10px 18px; border-radius:10px;
      font-weight:700; font-size:13px; opacity:0; transition:opacity .2s; pointer-events:none; z-index:50; }}
    .sb-toast.show {{ opacity:1; }}
  </style>
  <h1>Stock library</h1>
  <p class="sb-sub">Licence-clean photos &amp; video from open collections — every result keeps its
    licence &amp; attribution, and only commercially-usable assets are shown.{_h(paid_note)}</p>
  <div class="sb-row">
    <input type="search" id="sb-search" class="sb-search" placeholder="Search stock — “swimming pool”, “starting blocks”, “crowd”…" autocomplete="off">
    <select id="sb-kind" class="sb-kind"><option value="photo">Photos</option><option value="video">Video</option></select>
  </div>
  <div class="sb-grid" id="sb-grid"><div class="sb-empty">Search to find licence-clean stock to add to your library.</div></div>
  <div class="sb-toast" id="sb-toast"></div>
</div>
<script>
(function() {{
  var BOOT = {_script_json(boot)};
  var grid = document.getElementById('sb-grid');
  var searchEl = document.getElementById('sb-search');
  var kindEl = document.getElementById('sb-kind');
  var toastEl = document.getElementById('sb-toast');
  var timer = null;

  function toast(m) {{ toastEl.textContent=m; toastEl.classList.add('show'); setTimeout(function(){{toastEl.classList.remove('show');}},1800); }}

  function esc(s) {{ var d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }}

  // Thumbnails are cross-origin (Wikimedia/Openverse/…); the app CSP pins
  // img-src 'self', so route every tile through our first-party proxy. The
  // proxy URL is a fixed prefix + encodeURIComponent(...), so it's safe to drop
  // straight into the src attribute (no quotes/brackets survive the encode).
  function proxied(u) {{ return u ? (BOOT.proxyUrl + '?u=' + encodeURIComponent(u)) : ''; }}

  function card(r) {{
    var d = document.createElement('div'); d.className='sb-card';
    var isVideo = r.kind === 'video';
    // For video we show the poster frame (Wikimedia renders one as thumb_url)
    // with a play badge — never the heavy clip — so it stays light and clears
    // the media-src CSP. The full clip is fetched server-side only on import.
    var posterSrc = proxied(r.thumb_url || (isVideo ? '' : r.direct_url));
    var thumbInner = posterSrc
      ? '<img class="sb-img" src="' + posterSrc + '" alt="" loading="lazy">'
      : '<div class="sb-noimg">' + (isVideo ? 'Video' : 'No preview') + '</div>';
    var thumb = '<div class="sb-thumb">' + thumbInner + (isVideo ? '<span class="sb-play">&#9654;</span>' : '') + '</div>';
    var attr = (r.licence && r.licence.attribution) ? ('© ' + esc(r.licence.attribution)) : '';
    var lic = (r.licence && r.licence.name) ? esc(r.licence.name) : '';
    d.innerHTML = thumb + '<div class="sb-meta"><div class="sb-lic">' + lic + '</div>' +
      '<div class="sb-attr">' + attr + '</div>' +
      '<button type="button" class="sb-add">Add to library</button></div>';
    // The proxy serves cache-only (a miss 404s while it warms in the background).
    // The warmer fills the cache at a deliberately polite rate (to stay under the
    // source's limit), so retry over a generous window with the &_r= cache-buster
    // until the tile lands; only then fall back to a placeholder. (dead CDN links
    // / refused hosts also end up here.)
    var imgEl = d.querySelector('.sb-img');
    if (imgEl && posterSrc) {{
      var tries = 0;
      imgEl.addEventListener('error', function() {{
        tries++;
        if (tries <= 9) {{
          setTimeout(function(){{ imgEl.src = posterSrc + '&_r=' + tries; }}, Math.min(3500, 900 * tries));
        }} else {{
          var box = imgEl.parentNode; if (box) box.innerHTML = '<div class="sb-noimg">No preview</div>';
        }}
      }});
    }}
    d.querySelector('.sb-add').addEventListener('click', function(ev) {{
      var b = ev.target; b.disabled = true;
      fetch(BOOT.importUrl, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{
        direct_url: r.direct_url, title: r.title, source_url: r.source_url, source_site: r.source_site,
        licence: (r.licence||{{}}).name, licence_url: (r.licence||{{}}).url,
        attribution: (r.licence||{{}}).attribution, kind: r.kind, permission_status: r.permission_status
      }})}}).then(function(x){{return x.json();}}).then(function(j){{
        toast(j.ok ? 'Added to your library' : (j.user_message || j.error || 'Could not add'));
        b.disabled = !j.ok; b.textContent = j.ok ? 'Added ✓' : 'Add to library';
      }}).catch(function(){{ toast('Could not add'); b.disabled=false; }});
    }});
    return d;
  }}

  function run() {{
    var q = searchEl.value.trim();
    if (!q) {{ grid.innerHTML = '<div class="sb-empty">Search to find licence-clean stock to add to your library.</div>'; return; }}
    grid.innerHTML = '<div class="sb-empty">Searching…</div>';
    fetch(BOOT.searchUrl + '?q=' + encodeURIComponent(q) + '&kind=' + encodeURIComponent(kindEl.value), {{headers:{{'Accept':'application/json'}}}})
      .then(function(r){{return r.json();}})
      .then(function(d){{
        grid.innerHTML = '';
        var rs = d.results || [];
        if (!rs.length) {{ grid.innerHTML = '<div class="sb-empty">No licence-clean results — try different words.</div>'; return; }}
        rs.forEach(function(r){{ grid.appendChild(card(r)); }});
      }}).catch(function(){{ grid.innerHTML = '<div class="sb-empty">Search failed — try again.</div>'; }});
  }}

  searchEl.addEventListener('input', function(){{ clearTimeout(timer); timer=setTimeout(run, 400); }});
  kindEl.addEventListener('change', run);
}})();
</script>
"""


def render_annotate_body(*, asset_url: str, save_url: str, back_url: str, existing: dict) -> str:
    """The telestration canvas page body (pointer-capture draw → save spec layer)."""
    boot = {"assetUrl": asset_url, "saveUrl": save_url, "existing": existing or {}}
    return f"""
<div class="an-wrap">
  <style>
    .an-wrap {{ max-width:1000px; margin:0 auto; padding:8px 0 64px; }}
    .an-wrap h1 {{ font-size:21px; margin:0 0 2px; }}
    .an-sub {{ color:var(--ink-muted,#9aa3b2); font-size:13px; margin:0 0 14px; }}
    .an-bar {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }}
    .an-tool, .an-col {{ width:36px; height:36px; border-radius:9px; cursor:pointer; border:1px solid var(--line,#2a3140);
      background:var(--panel,#141821); color:var(--ink,#e8ecf3); display:flex; align-items:center; justify-content:center; font-size:13px; }}
    .an-tool.active {{ background:var(--accent,#FFB81C); color:#10131a; border-color:var(--accent,#FFB81C); font-weight:700; }}
    .an-col {{ padding:0; }}
    .an-col.active {{ outline:2px solid var(--ink,#e8ecf3); outline-offset:1px; }}
    .an-sep {{ width:1px; height:26px; background:var(--line,#2a3140); margin:0 4px; }}
    .an-stage {{ position:relative; display:inline-block; max-width:100%; border:1px solid var(--line,#2a3140); border-radius:12px; overflow:hidden; }}
    .an-stage img {{ display:block; max-width:100%; height:auto; }}
    .an-stage canvas {{ position:absolute; inset:0; width:100%; height:100%; touch-action:none; cursor:crosshair; }}
    .an-btn {{ padding:8px 16px; border-radius:9px; border:none; cursor:pointer; font-weight:700; font-size:13px; }}
    .an-btn.primary {{ background:var(--accent,#FFB81C); color:#10131a; }}
    .an-btn.ghost {{ background:transparent; color:var(--ink-dim,#9aa3b2); border:1px solid var(--line,#2a3140); }}
    .an-range {{ width:90px; }}
    .an-toast {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:var(--accent,#FFB81C);
      color:#10131a; padding:10px 18px; border-radius:10px; font-weight:700; font-size:13px; opacity:0; transition:opacity .2s; z-index:50; }}
    .an-toast.show {{ opacity:1; }}
  </style>
  <h1>Annotate</h1>
  <p class="an-sub">Telestration for coaching — draw over the photo. Pick a tool, draw, save.
    The original photo is never changed (the marks are a separate layer).
    <a href="{_h(back_url)}">&larr; Library</a></p>

  <div class="an-bar" id="an-bar">
    <button type="button" class="an-tool active" data-kind="free" title="Pen">&#9998;</button>
    <button type="button" class="an-tool" data-kind="line" title="Line">&#9135;</button>
    <button type="button" class="an-tool" data-kind="arrow" title="Arrow">&#8594;</button>
    <button type="button" class="an-tool" data-kind="rect" title="Rectangle">&#9633;</button>
    <button type="button" class="an-tool" data-kind="ellipse" title="Ellipse">&#9711;</button>
    <button type="button" class="an-tool" data-kind="auto" title="Shape assist (auto-snap)">&#10022;</button>
    <span class="an-sep"></span>
    <button type="button" class="an-col active" data-colour="--mh-accent" style="background:var(--accent,#FFB81C)" title="Brand accent"></button>
    <button type="button" class="an-col" data-colour="#FF3B30" style="background:#FF3B30" title="Red"></button>
    <button type="button" class="an-col" data-colour="#FFD60A" style="background:#FFD60A" title="Yellow"></button>
    <button type="button" class="an-col" data-colour="#FFFFFF" style="background:#FFFFFF" title="White"></button>
    <button type="button" class="an-col" data-colour="#0A0A0A" style="background:#0A0A0A" title="Black"></button>
    <span class="an-sep"></span>
    <input type="range" class="an-range" id="an-width" min="2" max="18" value="6" title="Line width">
    <select class="an-tool" id="an-sym" style="width:auto;padding:0 8px" title="Symmetry">
      <option value="none">No mirror</option>
      <option value="vertical">Mirror ↔</option>
      <option value="horizontal">Mirror ↕</option>
      <option value="quad">Mirror ✛</option>
    </select>
  </div>

  <div class="an-stage" id="an-stage">
    <img id="an-img" src="{_h(asset_url)}" alt="" crossorigin="anonymous">
    <canvas id="an-canvas"></canvas>
  </div>
  <div style="margin-top:14px;display:flex;gap:10px">
    <button type="button" class="an-btn primary" id="an-save">Save annotation</button>
    <button type="button" class="an-btn ghost" id="an-undo">Undo</button>
    <button type="button" class="an-btn ghost" id="an-clear">Clear</button>
  </div>
  <div class="an-toast" id="an-toast"></div>
</div>

<script>
(function() {{
  var BOOT = {_script_json(boot)};
  var img = document.getElementById('an-img');
  var canvas = document.getElementById('an-canvas');
  var ctx = canvas.getContext('2d');
  var toastEl = document.getElementById('an-toast');
  var kind = 'free', colour = '--mh-accent', width = 6, drawing = false;
  var strokes = (BOOT.existing.strokes || []).slice();
  var sym = BOOT.existing.symmetry || 'none';
  var cur = null;

  function toast(m){{ toastEl.textContent=m; toastEl.classList.add('show'); setTimeout(function(){{toastEl.classList.remove('show');}},1700); }}
  function brandAccent(){{ return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#FFB81C'; }}
  function rgb(c){{ return c === '--mh-accent' ? brandAccent() : c; }}

  function fit(){{
    canvas.width = img.clientWidth; canvas.height = img.clientHeight; redraw();
  }}
  function pt(ev){{
    var r = canvas.getBoundingClientRect();
    return [Math.min(1,Math.max(0,(ev.clientX-r.left)/r.width)), Math.min(1,Math.max(0,(ev.clientY-r.top)/r.height))];
  }}

  function drawStroke(s){{
    var W=canvas.width, H=canvas.height, p=s.points.map(function(q){{return [q[0]*W,q[1]*H];}});
    var lw = (s.width||6); if (lw < 1) lw = lw * Math.min(W,H);  // stored widths are short-edge fractions
    ctx.strokeStyle = rgb(s.colour); ctx.fillStyle = rgb(s.colour);
    ctx.lineWidth = lw; ctx.lineCap='round'; ctx.lineJoin='round';
    if (!p.length) return;
    if (s.kind==='rect' && p.length>=2) {{ ctx.strokeRect(Math.min(p[0][0],p[p.length-1][0]),Math.min(p[0][1],p[p.length-1][1]),Math.abs(p[p.length-1][0]-p[0][0]),Math.abs(p[p.length-1][1]-p[0][1])); return; }}
    if (s.kind==='ellipse' && p.length>=2) {{ var a=p[0],b=p[p.length-1]; ctx.beginPath(); ctx.ellipse((a[0]+b[0])/2,(a[1]+b[1])/2,Math.abs(b[0]-a[0])/2,Math.abs(b[1]-a[1])/2,0,0,7); ctx.stroke(); return; }}
    var pts = (s.kind==='line'||s.kind==='arrow') && p.length>=2 ? [p[0],p[p.length-1]] : p;
    ctx.beginPath(); ctx.moveTo(pts[0][0],pts[0][1]); for(var i=1;i<pts.length;i++) ctx.lineTo(pts[i][0],pts[i][1]); ctx.stroke();
    if (s.kind==='arrow' && pts.length>=2) {{
      var a=pts[pts.length-2], b=pts[pts.length-1], ang=Math.atan2(b[1]-a[1],b[0]-a[0]), sz=Math.max(8,lw*2.5);
      ctx.beginPath(); ctx.moveTo(b[0],b[1]); ctx.lineTo(b[0]+sz*Math.cos(ang+2.6),b[1]+sz*Math.sin(ang+2.6));
      ctx.lineTo(b[0]+sz*Math.cos(ang-2.6),b[1]+sz*Math.sin(ang-2.6)); ctx.closePath(); ctx.fill();
    }}
  }}
  function mirror(s){{
    var out=[];
    function mk(fn){{ return {{points:s.points.map(fn),kind:s.kind,colour:s.colour,width:s.width}}; }}
    if(sym==='vertical'||sym==='quad') out.push(mk(function(q){{return [1-q[0],q[1]];}}));
    if(sym==='horizontal'||sym==='quad') out.push(mk(function(q){{return [q[0],1-q[1]];}}));
    if(sym==='quad') out.push(mk(function(q){{return [1-q[0],1-q[1]];}}));
    return out;
  }}
  function redraw(){{
    ctx.clearRect(0,0,canvas.width,canvas.height);
    var all = strokes.concat(cur?[cur]:[]);
    all.forEach(function(s){{ drawStroke(s); mirror(s).forEach(drawStroke); }});
  }}

  canvas.addEventListener('pointerdown', function(ev){{ canvas.setPointerCapture(ev.pointerId); drawing=true; cur={{points:[pt(ev)],kind:kind,colour:colour,width:width}}; redraw(); }});
  canvas.addEventListener('pointermove', function(ev){{ if(!drawing) return; cur.points.push(pt(ev)); redraw(); }});
  function end(){{ if(!drawing) return; drawing=false; if(cur && cur.points.length){{ strokes.push(cur); }} cur=null; redraw(); }}
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);

  document.getElementById('an-bar').addEventListener('click', function(ev){{
    var t=ev.target.closest('.an-tool'); if(t && t.dataset.kind){{ kind=t.dataset.kind; document.querySelectorAll('.an-tool[data-kind]').forEach(function(x){{x.classList.remove('active');}}); t.classList.add('active'); return; }}
    var c=ev.target.closest('.an-col'); if(c){{ colour=c.dataset.colour; document.querySelectorAll('.an-col').forEach(function(x){{x.classList.remove('active');}}); c.classList.add('active'); }}
  }});
  document.getElementById('an-width').addEventListener('input', function(e){{ width=parseInt(e.target.value,10)||6; }});
  document.getElementById('an-sym').addEventListener('change', function(e){{ sym=e.target.value; redraw(); }});
  document.getElementById('an-undo').addEventListener('click', function(){{ strokes.pop(); redraw(); }});
  document.getElementById('an-clear').addEventListener('click', function(){{ strokes=[]; redraw(); }});
  document.getElementById('an-save').addEventListener('click', function(){{
    var shortEdge = Math.min(canvas.width,canvas.height) || 1;
    var payload = {{symmetry:sym, strokes:strokes.map(function(s){{ var w=(s.width||6); return {{points:s.points,kind:s.kind,colour:s.colour,width:(w<1?w:w/shortEdge)}}; }})}};
    fetch(BOOT.saveUrl, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}})
      .then(function(r){{return r.json();}}).then(function(j){{ toast(j.ok?'Saved':'Save failed'); }}).catch(function(){{ toast('Save failed'); }});
  }});

  if (img.complete) fit(); else img.addEventListener('load', fit);
  window.addEventListener('resize', fit);
}})();
</script>
"""


__all__ = ["render_browser_body", "render_stock_body", "render_annotate_body"]
