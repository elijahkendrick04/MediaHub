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


__all__ = ["render_browser_body"]
