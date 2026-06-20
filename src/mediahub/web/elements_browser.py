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
) -> str:
    """The Elements browser page body (HTML + scoped CSS + JS)."""
    in_card = bool(add_url and list_url)
    boot = {
        "searchUrl": search_url,
        "addUrl": add_url,
        "listUrl": list_url,
        "suggestUrl": suggest_url,
        "semantic": bool(semantic),
        "inCard": in_card,
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
    toastEl.textContent = msg; toastEl.classList.add('show');
    setTimeout(function(){{ toastEl.classList.remove('show'); }}, 1600);
  }}

  function card(el) {{
    var d = document.createElement('div'); d.className = 'eb-card';
    var add = BOOT.inCard
      ? '<button type="button" class="eb-add" data-id="' + el.id + '">Add to card</button>'
      : '';
    d.innerHTML =
      '<div class="eb-thumb">' + (el.svg || '') + '</div>' +
      '<div class="eb-meta"><div class="eb-name">' + (el.name || '') + '</div>' +
      '<div class="eb-kind">' + (el.kind || '') + '</div>' + add + '</div>';
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
      .then(function(d){{ toast(d.ok ? 'Added — re-render the card to see it' : (d.error || 'Could not add')); b.disabled = false; }})
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


def render_stock_body(*, search_url: str, import_url: str, sources: dict) -> str:
    """The licence-clean stock browser body (search → add to library)."""
    boot = {"searchUrl": search_url, "importUrl": import_url}
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
    .sb-thumb {{ aspect-ratio:4/3; background:var(--bg,#0b0e14) center/cover no-repeat; }}
    .sb-thumb video {{ width:100%; height:100%; object-fit:cover; }}
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

  function card(r) {{
    var d = document.createElement('div'); d.className='sb-card';
    var thumb = r.kind === 'video'
      ? '<div class="sb-thumb"><video src="' + esc(r.direct_url) + '" muted preload="metadata"></video></div>'
      : '<div class="sb-thumb" style="background-image:url(\\'' + esc(r.thumb_url || r.direct_url) + '\\')"></div>';
    var attr = (r.licence && r.licence.attribution) ? ('© ' + esc(r.licence.attribution)) : '';
    var lic = (r.licence && r.licence.name) ? esc(r.licence.name) : '';
    d.innerHTML = thumb + '<div class="sb-meta"><div class="sb-lic">' + lic + '</div>' +
      '<div class="sb-attr">' + attr + '</div>' +
      '<button type="button" class="sb-add">Add to library</button></div>';
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


__all__ = ["render_browser_body", "render_stock_body"]
