"""sites.widgets — the vetted interactive-widget catalogue (roadmap 1.16).

The Canva-Code analogue, done safely: a **fixed catalogue of audited primitives**,
each rendered as a self-contained component (deterministic HTML + a small,
nonce-stamped inline script — no external resources, no ``eval``, no arbitrary
hosted code). The AI may *compose* a widget only by **choosing a type from this
catalogue and filling its config** (:func:`compose_widget`); it can never emit code.
Every value is ``markupsafe``-escaped.

Catalogue:
  - ``countdown``   — counts down to a meet/event datetime (client-side ticker)
  - ``medal_tally`` — a data-grounded gold/silver/bronze tally (pure HTML)
  - ``lane_lookup`` — a searchable lane-draw / heat-sheet table (client filter)
  - ``poll``        — a one-tap poll/Q&A with live result bars (votes via the web layer)
"""

from __future__ import annotations

import re
from typing import Any, Optional

from markupsafe import escape as _h

WIDGET_TYPES = ("countdown", "medal_tally", "lane_lookup", "poll")

_ID_RE = re.compile(r"[^A-Za-z0-9_]+")


def _dom_id(props: dict) -> str:
    """A safe DOM id (alnum/underscore only) — used in HTML ids + JS selectors."""
    wid = str(props.get("widget_id") or props.get("widget_type") or "w")
    return "mhw_" + (_ID_RE.sub("_", wid).strip("_") or "w")


def _script(nonce: str, body: str) -> str:
    nonce_attr = f' nonce="{_h(nonce)}"' if nonce else ""
    return f"<script{nonce_attr}>{body}</script>"


# ---------------------------------------------------------------------------
# countdown
# ---------------------------------------------------------------------------


def _render_countdown(props: dict, dom_id: str, nonce: str) -> str:
    cfg = props.get("config") or {}
    target = str(cfg.get("target", "")).strip()
    label = str(cfg.get("label", "")).strip()
    head = f'<div class="mhw-label">{_h(label)}</div>' if label else ""
    units = "".join(
        f'<div class="mhw-unit"><span class="mhw-n" data-{k}>--</span>'
        f'<span class="mhw-u">{name}</span></div>'
        for k, name in (("d", "days"), ("h", "hrs"), ("m", "min"), ("s", "sec"))
    )
    js = (
        f"(function(){{var e=document.getElementById('{dom_id}');if(!e)return;"
        "var t=Date.parse(e.getAttribute('data-target'));if(isNaN(t)){e.classList.add('mhw-cd-na');return;}"
        "function p(n){return('0'+n).slice(-2);}function u(){var d=t-Date.now();if(d<0)d=0;"
        "var s=Math.floor(d/1000);e.querySelector('[data-d]').textContent=Math.floor(s/86400);"
        "e.querySelector('[data-h]').textContent=p(Math.floor(s%86400/3600));"
        "e.querySelector('[data-m]').textContent=p(Math.floor(s%3600/60));"
        "e.querySelector('[data-s]').textContent=p(s%60);}u();setInterval(u,1000);})();"
    )
    return (
        f'<div class="mhw mhw-countdown" id="{dom_id}" data-target="{_h(target)}">'
        f'{head}<div class="mhw-units">{units}</div></div>{_script(nonce, js)}'
    )


# ---------------------------------------------------------------------------
# medal_tally (data-grounded; no JS)
# ---------------------------------------------------------------------------


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _render_medal_tally(props: dict, dom_id: str) -> str:
    cfg = props.get("config") or {}
    g, s, b = _int(cfg.get("gold")), _int(cfg.get("silver")), _int(cfg.get("bronze"))
    label = str(cfg.get("label", "Medal tally")).strip()
    tiles = "".join(
        f'<div class="mhw-medal mhw-{cls}"><span class="mhw-n">{n}</span>'
        f'<span class="mhw-u">{name}</span></div>'
        for cls, name, n in (("gold", "Gold", g), ("silver", "Silver", s), ("bronze", "Bronze", b))
    )
    total = g + s + b
    foot = f'<div class="mhw-total">{total} total</div>' if total else ""
    head = f'<div class="mhw-label">{_h(label)}</div>' if label else ""
    return f'<div class="mhw mhw-tally" id="{dom_id}">{head}<div class="mhw-medals">{tiles}</div>{foot}</div>'


# ---------------------------------------------------------------------------
# lane_lookup (client-side filter)
# ---------------------------------------------------------------------------


def _render_lane_lookup(props: dict, dom_id: str, nonce: str) -> str:
    cfg = props.get("config") or {}
    entries = cfg.get("entries") or []
    label = str(cfg.get("label", "Find your lane")).strip()
    rows = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_h(e.get('name', ''))}</td>"
            f"<td>{_h(e.get('event', ''))}</td>"
            f"<td>{_h(e.get('heat', ''))}</td>"
            f"<td>{_h(e.get('lane', ''))}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    js = (
        f"(function(){{var w=document.getElementById('{dom_id}');if(!w)return;"
        "var i=w.querySelector('[data-q]');var rs=w.querySelectorAll('tbody tr');"
        "i.addEventListener('input',function(){var q=i.value.toLowerCase();rs.forEach(function(r){"
        "r.style.display=r.textContent.toLowerCase().indexOf(q)>=0?'':'none';});});})();"
    )
    return (
        f'<div class="mhw mhw-lanes" id="{dom_id}">'
        f'<label class="mhw-label" for="{dom_id}_q">{_h(label)}</label>'
        f'<input id="{dom_id}_q" data-q type="search" placeholder="Search name or event…"/>'
        '<table class="mhw-lane-table"><thead><tr><th>Swimmer</th><th>Event</th>'
        f"<th>Heat</th><th>Lane</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"</div>{_script(nonce, js)}"
    )


# ---------------------------------------------------------------------------
# poll (votes recorded via the web layer)
# ---------------------------------------------------------------------------


def _render_poll(
    props: dict, dom_id: str, nonce: str, *, vote_url: str = "", counts: Optional[dict] = None
) -> str:
    cfg = props.get("config") or {}
    question = str(cfg.get("question", "")).strip()
    options = [str(o) for o in (cfg.get("options") or []) if str(o).strip()]
    if not options:
        return ""
    counts = counts or {}
    total = sum(int(counts.get(o, 0)) for o in options)
    head = f'<div class="mhw-label">{_h(question)}</div>' if question else ""

    rows = []
    for o in options:
        c = int(counts.get(o, 0))
        pct = round(c * 100 / total) if total else 0
        if vote_url:
            control = f'<button class="mhw-poll-opt" data-opt="{_h(o)}">{_h(o)}</button>'
        else:
            control = f'<div class="mhw-poll-opt">{_h(o)}</div>'
        rows.append(
            f'<div class="mhw-poll-row">{control}'
            f'<div class="mhw-bar-track"><div class="mhw-bar" data-bar="{_h(o)}" style="width:{pct}%"></div></div>'
            f'<span class="mhw-pct" data-pct="{_h(o)}">{pct}% ({c})</span></div>'
        )

    js = ""
    if vote_url:
        js = _script(
            nonce,
            f"(function(){{var w=document.getElementById('{dom_id}');if(!w)return;"
            "var u=w.getAttribute('data-vote');function paint(c){var t=0;Object.keys(c).forEach("
            "function(k){t+=c[k];});w.querySelectorAll('[data-bar]').forEach(function(bar){"
            "var o=bar.getAttribute('data-bar');var v=c[o]||0;var p=t?Math.round(v*100/t):0;"
            "bar.style.width=p+'%';var l=w.querySelector('[data-pct=\"'+o+'\"]');"
            "if(l)l.textContent=p+'% ('+v+')';});}"
            "w.querySelectorAll('button[data-opt]').forEach(function(b){b.addEventListener('click',"
            "function(){if(w.getAttribute('data-voted'))return;"
            "fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify({option:b.getAttribute('data-opt')})}).then(function(r){return r.json();})"
            ".then(function(j){if(j&&j.ok){w.setAttribute('data-voted','1');paint(j.counts||{});}});});});})();",
        )
    vote_attr = f' data-vote="{_h(vote_url)}"' if vote_url else ""
    return f'<div class="mhw mhw-poll" id="{dom_id}"{vote_attr}>{head}{"".join(rows)}</div>{js}'


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def render_widget(
    props: dict,
    *,
    nonce: str = "",
    role_vars: Optional[dict[str, str]] = None,
    vote_url: str = "",
    counts: Optional[dict] = None,
) -> str:
    """Render one widget block. Unknown types render as nothing (forward-compatible)."""
    wtype = str((props or {}).get("widget_type", "")).strip()
    dom_id = _dom_id(props or {})
    if wtype == "countdown":
        return _render_countdown(props, dom_id, nonce)
    if wtype == "medal_tally":
        return _render_medal_tally(props, dom_id)
    if wtype == "lane_lookup":
        return _render_lane_lookup(props, dom_id, nonce)
    if wtype == "poll":
        return _render_poll(props, dom_id, nonce, vote_url=vote_url, counts=counts)
    return ""


def widget_styles() -> str:
    """The widget CSS (folded into the site stylesheet by the theme)."""
    return _WIDGET_CSS


_WIDGET_CSS = r"""
.mhw{margin:.5rem 0 1rem}
.mhw-label{font-weight:700;margin-bottom:10px}
.mhw-units,.mhw-medals{display:flex;gap:14px;flex-wrap:wrap}
.mhw-unit,.mhw-medal{background:var(--site-panel);border:1px solid var(--site-line);border-radius:12px;
  padding:14px 18px;text-align:center;min-width:78px}
.mhw-n{display:block;font-family:'Space Grotesk',sans-serif;font-size:2rem;font-weight:700;color:var(--site-accent);line-height:1}
.mhw-u{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--site-muted);margin-top:6px}
.mhw-medal.mhw-gold .mhw-n{color:#f4c542}.mhw-medal.mhw-silver .mhw-n{color:#c9ced6}.mhw-medal.mhw-bronze .mhw-n{color:#cd8246}
.mhw-total{margin-top:10px;color:var(--site-muted);font-size:.85rem}
.mhw-cd-na .mhw-units{opacity:.4}
.mhw-lanes input[data-q]{width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--site-line);
  background:var(--site-bg);color:var(--site-ink);margin-bottom:12px;font:inherit}
.mhw-lane-table{width:100%;border-collapse:collapse;font-size:.95rem}
.mhw-lane-table th{text-align:left;background:var(--site-brand);color:var(--site-brand-ink);padding:8px 10px}
.mhw-lane-table td{padding:7px 10px;border-bottom:1px solid var(--site-line)}
.mhw-poll-row{display:grid;grid-template-columns:minmax(120px,1fr) 2fr auto;gap:12px;align-items:center;margin:8px 0}
.mhw-poll-opt{background:var(--site-panel);border:1px solid var(--site-line);color:var(--site-ink);
  border-radius:10px;padding:10px 14px;text-align:left;cursor:pointer;font:inherit}
button.mhw-poll-opt:hover{border-color:var(--site-accent)}
.mhw-bar-track{background:var(--site-panel);border-radius:8px;height:14px;overflow:hidden}
.mhw-bar{height:100%;background:var(--site-accent);transition:width .4s ease}
.mhw-pct{color:var(--site-muted);font-size:.85rem;white-space:nowrap}
"""


# ---------------------------------------------------------------------------
# AI composer — constrained to the catalogue (never emits code)
# ---------------------------------------------------------------------------


def compose_widget(prompt: str, *, allowed_types: tuple[str, ...] = WIDGET_TYPES) -> dict:
    """Ask the LLM to pick a catalogue widget + fill its config from a plain-English
    request. Returns a validated ``{"widget_type", "config"}`` dict. Honest-errors
    with ``ClaudeUnavailableError`` when no provider is set. The AI can only choose a
    type from ``allowed_types`` and supply config — it never produces code."""
    from mediahub.media_ai.llm import ClaudeUnavailableError, generate_json, is_available

    if not is_available():
        raise ClaudeUnavailableError("No cloud LLM provider is reachable; cannot compose a widget.")
    system = (
        "You configure a sports-club web widget by choosing ONE type from a fixed "
        "catalogue and filling its settings. You never write code. Allowed types: "
        f"{', '.join(allowed_types)}. countdown:{{target:ISO-date,label}}. "
        "medal_tally:{gold,silver,bronze}. lane_lookup:{entries:[{name,event,heat,lane}]}. "
        'poll:{question,options:[...]}. Return JSON {"widget_type":..., "config":{...}}.'
    )
    try:
        raw = generate_json(prompt, system=system, max_tokens=500, fallback={})
    except ClaudeUnavailableError:
        raise
    except Exception as e:
        raise ClaudeUnavailableError(f"Widget composition failed: {e}") from e

    wtype = str((raw or {}).get("widget_type", "")).strip()
    if wtype not in allowed_types:
        raise ValueError(f"AI chose an unknown widget type {wtype!r}; refusing.")
    config = raw.get("config")
    return {"widget_type": wtype, "config": config if isinstance(config, dict) else {}}


__all__ = ["WIDGET_TYPES", "render_widget", "widget_styles", "compose_widget"]
