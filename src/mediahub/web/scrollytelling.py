"""UI 1.7 — Pinned-panel scrollytelling (landing how-it-works section).

A Linear-style *pinned panel*: the four-step workflow narrative scrolls down the
left rail while a sticky visual panel on the right stays pinned and **swaps its
content per step** — the results file you upload → the moments the engine finds
→ the on-brand drafts it writes → your approval before anything posts.

Design rules honoured (see CLAUDE.md):
  * **Pure CSS, scroll-driven, no JS library.** The pin is ``position: sticky``;
    the per-step visual swap is driven entirely by CSS *scroll-driven
    animations* — a named ``view-timeline`` on each narrative step, hoisted with
    ``timeline-scope`` so the sibling panel's visuals can consume it. No
    IntersectionObserver, no scrollytelling library, no inline ``<script>``.
  * **Progressive enhancement.** The base layer is a clean, JS-free,
    scroll-driven-free *static* layout (rail of steps beside a stacked filmstrip
    of all four visuals) that reads top-to-bottom on every browser. The pin +
    swap is layered on top *only* behind
    ``@supports (animation-timeline: view())`` and
    ``@media (prefers-reduced-motion: no-preference)`` at desktop widths — so
    unsupported browsers, mobile, and reduced-motion visitors all get the
    legible static layout and nothing is ever hidden.
  * **Reduced-motion safe.** The enhancement is gated on
    ``prefers-reduced-motion: no-preference``; a reduced-motion visitor never
    enters the scroll-driven path, so the global reduced-motion freeze has
    nothing to fight and every stage is visible at once.
  * **On-brand restraint.** Lane-yellow is the only chrome accent (active step,
    rule ticks, the live "go" pill). Medal-gold appears *only* inside the
    detected-moments mock, where it legitimately marks an athlete achievement —
    never as section chrome.

Pure presentation: the narrative copy is the real, screen-reader-read content;
the right-hand mocks are decorative (``aria-hidden``) duplicates of what the
steps already say in words. There is no user data and no engine logic here, so
nothing to escape and no deterministic-engine surface is touched. The output is
deterministic (no randomness / no I/O), so it is safe to cache and simple to
test.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Step icons — authored on a 24x24 canvas, stroke-only (colour + width from
# CSS). These mirror the four workflow icons the landing page already used.
# --------------------------------------------------------------------------- #
_ICON_INPUT = (
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    '<polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'
)
_ICON_DETECT = (
    '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>' '<path d="M11 8v3M11 14v.01"/>'
)
_ICON_DRAFT = '<path d="M12 19l7-7-3-3-7 7v3z"/><path d="M14 6l3 3"/><path d="M5 21h14"/>'
_ICON_APPROVE = '<polyline points="20 6 9 17 4 12"/>'


def _icon(inner: str) -> str:
    """An inline step icon (24x24, stroke = currentColor)."""
    return (
        '<svg class="mh-scrolly-icon" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{inner}</svg>'
    )


# --------------------------------------------------------------------------- #
# The four pinned visual mocks (decorative duplicates of the step copy).
# Each is the panel content for one workflow stage.
# --------------------------------------------------------------------------- #
_RESULTS_SHEET = (
    "Event 12  Boys 13-14  100 Free\n"
    " 1  Davies, Tom     14  RIV  52.41\n"
    " 2  Okafor, Daniel  13  RIV  54.02\n"
    " 3  Mehta, Arun     14  RIV  54.77\n"
    " 4  Novak, Petr     13  OTT  55.31"
)


def _vis_input() -> str:
    rows = (
        '<div class="mh-scm-head"><span class="mh-scm-dot"></span>'
        "results.hy3 · HY-TEK export</div>"
        f'<pre class="mh-scm-sheet">{_RESULTS_SHEET}</pre>'
        '<div class="mh-scm-row">'
        '<span class="mh-scm-pill">PDF</span>'
        '<span class="mh-scm-pill">CSV</span>'
        '<span class="mh-scm-pill">HY3</span>'
        '<span class="mh-scm-pill mh-scm-pill--ghost">paste · describe</span>'
        "</div>"
    )
    return f'<figure class="mh-scrolly-vis" aria-hidden="true"><div class="mh-scm">{rows}</div></figure>'


def _moment(rank: str, name: str, meet: str, tag: str, tag_kind: str, conf: str) -> str:
    return (
        '<li class="mh-scm-moment">'
        f'<span class="mh-scm-rank">{rank}</span>'
        '<span class="mh-scm-moment-main">'
        f'<span class="mh-scm-moment-name">{name}</span>'
        f'<span class="mh-scm-moment-meet">{meet}</span>'
        "</span>"
        f'<span class="mh-scm-tag mh-scm-tag--{tag_kind}">{tag}</span>'
        f'<span class="mh-scm-conf">{conf}</span>'
        "</li>"
    )


def _vis_detect() -> str:
    moments = (
        _moment("1", "Tom Davies", "100m Free", "PB −0.74s", "pb", "98%")
        + _moment("2", "Maya Cole", "50m Fly", "Gold", "medal", "95%")
        + _moment("3", "Relay squad", "4×100m", "Club record", "record", "92%")
        + _moment("4", "Arun Mehta", "first sub-55", "First time", "first", "88%")
    )
    body = (
        '<div class="mh-scm-head"><span class="mh-scm-dot mh-scm-dot--live"></span>'
        "4 moments detected · ranked</div>"
        f'<ul class="mh-scm-moments">{moments}</ul>'
    )
    return f'<figure class="mh-scrolly-vis" aria-hidden="true"><div class="mh-scm">{body}</div></figure>'


def _vis_draft() -> str:
    body = (
        '<div class="mh-scm-brandbar">'
        '<span class="mh-scm-logo">RSC</span>'
        '<span class="mh-scm-brandname">Riverside SC</span>'
        '<span class="mh-scm-voice">your voice</span>'
        "</div>"
        '<p class="mh-scm-caption">Huge swim from <strong>Tom Davies</strong> at the '
        "Spring Open — a new personal best of <strong>52.41</strong> in the 100m "
        "free, three-quarters of a second off his old mark. Onwards, Riverside! "
        '<span class="mh-scm-hash">#RiversideSC #PB</span></p>'
        '<div class="mh-scm-row">'
        '<span class="mh-scm-pill">Story</span>'
        '<span class="mh-scm-pill">Feed</span>'
        '<span class="mh-scm-pill">Reel</span>'
        "</div>"
    )
    return (
        '<figure class="mh-scrolly-vis" aria-hidden="true">'
        f'<div class="mh-scm mh-scm--draft">{body}</div></figure>'
    )


def _vis_approve() -> str:
    check = (
        '<span class="mh-scm-check"><svg viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/>'
        "</svg></span>"
    )
    body = (
        f"{check}"
        '<div class="mh-scm-approve-title">Approved by you</div>'
        '<p class="mh-scm-approve-sub">Nothing leaves without your sign-off.</p>'
        '<div class="mh-scm-row">'
        '<span class="mh-scm-pill mh-scm-pill--go">Post to Stories</span>'
        '<span class="mh-scm-pill">Download pack</span>'
        '<span class="mh-scm-pill">Copy caption</span>'
        "</div>"
    )
    return (
        '<figure class="mh-scrolly-vis" aria-hidden="true">'
        f'<div class="mh-scm mh-scm--approve">{body}</div></figure>'
    )


# Step copy + its paired visual, drawn once. The narrative text is the real,
# screen-reader-read content; ``visual`` is the decorative pinned-panel mock.
_STEPS = (
    {
        "num": "01",
        "icon": _ICON_INPUT,
        "title": "Add an input",
        "body": (
            "Upload a Hytek results file, paste a sponsor brief, or describe a "
            "moment in your own words. Any sport. Any club."
        ),
        "foot": "~ 30s",
        "visual": _vis_input,
    },
    {
        "num": "02",
        "icon": _ICON_DETECT,
        "title": "We find the moments",
        "body": (
            "The engine spots PBs, medals, first-times, comebacks and standout "
            "swims, then ranks them by content-worthiness — each with a "
            "confidence score you can see."
        ),
        "foot": "~ 45s",
        "visual": _vis_detect,
    },
    {
        "num": "03",
        "icon": _ICON_DRAFT,
        "title": "On-brand drafts appear",
        "body": (
            "Captions are written in your club’s voice, using your tone, "
            "sponsor rules and the example posts you’ve shared — on "
            "every format, in your palette and type."
        ),
        "foot": "~ 60s",
        "visual": _vis_draft,
    },
    {
        "num": "04",
        "icon": _ICON_APPROVE,
        "title": "Approve. Then post.",
        "body": (
            "You review, edit, approve. Nothing goes out without you. Export as "
            "text, copy to Stories, or download a ready-to-post pack."
        ),
        "foot": "Human in the loop",
        "visual": _vis_approve,
    },
)


def _step_html(step: dict) -> str:
    return (
        '<li class="mh-scrolly-step">'
        f'<span class="mh-scrolly-num">{step["num"]}</span>'
        '<h3 class="mh-scrolly-head">'
        f'{_icon(step["icon"])}<span>{step["title"]}</span></h3>'
        f'<p class="mh-scrolly-body">{step["body"]}</p>'
        f'<div class="mh-scrolly-foot">{step["foot"]}</div>'
        "</li>"
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def scrollytelling_grid_html() -> str:
    """The pinned-panel scrollytelling grid (rail of steps + sticky visual panel).

    Returned without the surrounding ``<section>``/eyebrow/heading so the home
    page keeps owning the section chrome (and its established scroll-reveal
    heading); this is the UI 1.7 body. Deterministic — no randomness / no I/O.
    """
    rail = "".join(_step_html(s) for s in _STEPS)
    panel = "".join(s["visual"]() for s in _STEPS)
    return (
        '<div class="mh-scrolly-grid">'
        f'<ol class="mh-scrolly-rail">{rail}</ol>'
        '<div class="mh-scrolly-stage">'
        f'<div class="mh-scrolly-panel">{panel}</div>'
        "</div>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
# CSS — appended to BASE_CSS ahead of the responsive guardrails layer.
# --------------------------------------------------------------------------- #
SCROLLYTELLING_CSS = """
/* ===================================================================== */
/* UI 1.7 — Pinned-panel scrollytelling (landing how-it-works)           */
/* A sticky visual panel that swaps content per workflow step as the      */
/* narrative scrolls past. Base layer = a clean, JS-free, scroll-driven-  */
/* free static layout that reads everywhere; the pin + per-step swap is   */
/* layered on top ONLY behind @supports(animation-timeline) +            */
/* prefers-reduced-motion:no-preference at desktop widths. No JS library, */
/* no IntersectionObserver, no inline script — pure CSS scroll-driven.    */
/* ===================================================================== */
.mh-scrolly-lede {
  max-width: 60ch;
  margin: 0 0 var(--sp-7);
  color: var(--ink-dim);
  font-size: 16px;
  line-height: 1.55;
}
.mh-scrolly-grid { display: grid; gap: var(--sp-6); }
@media (min-width: 900px) {
  .mh-scrolly-grid {
    grid-template-columns: minmax(0, 0.92fr) minmax(0, 1fr);
    gap: var(--sp-8);
    align-items: start;
  }
}

/* --- Left rail: the narrative steps (the real, spoken content) --- */
.mh-scrolly-rail { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-5); }
.mh-scrolly-step {
  position: relative;
  border: 1px solid var(--hairline);
  border-left: 2px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--surface);
  padding: var(--sp-6);
  transition: border-color var(--transition), background var(--transition);
}
.mh-scrolly-num {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.18em;
  color: var(--ink-muted);
  margin-bottom: var(--sp-3);
}
.mh-scrolly-num::before {
  content: '';
  width: 18px; height: 1px;
  background: var(--lane);
  opacity: 0.7;
}
.mh-scrolly-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: 0 0 var(--sp-2);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 22px;
  line-height: 1.1;
  letter-spacing: 0.01em;
  color: var(--ink);
}
.mh-scrolly-icon { width: 26px; height: 26px; color: var(--lane); flex: none; }
.mh-scrolly-body { margin: 0; max-width: 46ch; font-size: 15px; line-height: 1.55; color: var(--ink-dim); }
.mh-scrolly-foot {
  margin-top: var(--sp-4);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--hairline);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

/* --- Right stage: the visual mocks (decorative) --- */
.mh-scrolly-panel { display: grid; gap: var(--sp-5); }
.mh-scrolly-vis {
  margin: 0;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(120% 130% at 50% 0%, rgba(212,255,58,0.05), transparent 62%),
    var(--surface);
  padding: var(--sp-6);
  overflow: hidden;
}

/* Mock chrome shared by the four panel cards */
.mh-scm { display: grid; gap: var(--sp-4); }
.mh-scm-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.mh-scm-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--chrome); flex: none; }
.mh-scm-dot--live { background: var(--lane); box-shadow: 0 0 8px var(--lane-glow); }
.mh-scm-sheet {
  margin: 0;
  padding: var(--sp-4);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-dim);
  white-space: pre;
  overflow-x: auto;
}
.mh-scm-row { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
.mh-scm-pill {
  border: 1px solid var(--hairline);
  border-radius: 999px;
  padding: 4px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-dim);
  background: var(--surface-2);
}
.mh-scm-pill--ghost { border-style: dashed; color: var(--ink-muted); background: transparent; }
.mh-scm-pill--go { border-color: var(--lane); color: var(--lane); }

/* Detected & ranked moments */
.mh-scm-moments { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-3); }
.mh-scm-moment {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}
.mh-scm-rank {
  width: 22px; height: 22px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: var(--surface-3);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 12px;
  color: var(--ink);
}
.mh-scm-moment-main { min-width: 0; display: grid; }
.mh-scm-moment-name {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 14px;
  color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.mh-scm-moment-meet { font-size: 11px; color: var(--ink-muted); }
.mh-scm-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--hairline);
  color: var(--ink-dim);
  white-space: nowrap;
}
.mh-scm-tag--pb { color: var(--lane); border-color: color-mix(in oklab, var(--lane) 40%, transparent); }
.mh-scm-tag--medal { color: var(--medal); border-color: color-mix(in oklab, var(--medal) 45%, transparent); }
.mh-scm-tag--record { color: var(--info); border-color: color-mix(in oklab, var(--info) 45%, transparent); }
.mh-scm-conf {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}

/* Draft caption mock */
.mh-scm-brandbar { display: flex; align-items: center; gap: var(--sp-3); }
.mh-scm-logo {
  width: 32px; height: 32px;
  display: grid; place-items: center;
  border-radius: var(--radius-sm, 8px);
  background: var(--lane);
  color: #0b0d12;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 12px;
  letter-spacing: 0.02em;
}
.mh-scm-brandname { font-family: var(--font-display); font-weight: 700; font-size: 14px; color: var(--ink); }
.mh-scm-voice {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--lane);
}
.mh-scm-caption {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink-dim);
}
.mh-scm-caption strong { color: var(--ink); font-weight: 700; }
.mh-scm-hash { color: var(--ink-muted); }

/* Approval mock */
.mh-scm--approve { justify-items: center; text-align: center; }
.mh-scm-check {
  width: 48px; height: 48px;
  display: grid; place-items: center;
  border-radius: 50%;
  color: var(--lane);
  border: 1.5px solid var(--lane);
  box-shadow: 0 0 14px var(--lane-glow);
}
.mh-scm-check svg { width: 24px; height: 24px; }
.mh-scm-approve-title { font-family: var(--font-display); font-weight: 800; font-size: 18px; color: var(--ink); }
.mh-scm-approve-sub { margin: 0; font-size: 13px; color: var(--ink-muted); }
.mh-scm--approve .mh-scm-row { justify-content: center; }

/* ===================================================================== */
/* Enhancement — pin the panel + swap the visual per step, pure CSS       */
/* scroll-driven. A named view-timeline on each step is hoisted with      */
/* timeline-scope so the sibling panel's visuals can consume it. Gated on */
/* support + motion preference + desktop width; everything below is the   */
/* progressive layer over the static base above.                         */
/* ===================================================================== */
/* True cross-dissolve between the four stage visuals, driven by each step's
   view-timeline (0/100% = the step entering/leaving the viewport, ~50% = the
   step centred). Each visual is fully shown only while its step is centred and
   has faded out before the next step takes over, so no opaque stage ever bleeds
   through another. The FIRST visual is shown from the section's entry and the
   LAST is held through its exit, so the pinned panel is never blank. The
   per-step timeline offset is a viewport-independent ~45%, so the trapezoid
   windows below (visible across ~15%->85%, plateau 35%->65%) overlap just
   enough to dissolve cleanly with no at-rest overlap and no gap. */
@keyframes mh-scrolly-first {
  0%, 65%   { opacity: 1; transform: none; }
  85%, 100% { opacity: 0; transform: translateY(-10px); }
}
@keyframes mh-scrolly-mid {
  0%, 15%   { opacity: 0; transform: translateY(14px); }
  35%, 65%  { opacity: 1; transform: none; }
  85%, 100% { opacity: 0; transform: translateY(-10px); }
}
@keyframes mh-scrolly-last {
  0%, 15%   { opacity: 0; transform: translateY(14px); }
  35%, 100% { opacity: 1; transform: none; }
}
@keyframes mh-scrolly-spotlight {
  0%   { opacity: 0.42; }
  30%  { opacity: 1; }
  70%  { opacity: 1; }
  100% { opacity: 0.42; }
}

@supports (animation-timeline: view()) {
  @media (prefers-reduced-motion: no-preference) and (min-width: 900px) {
    /* Hoist each step's view-timeline so the panel subtree (a sibling, not a
       descendant) can drive its visuals from it. */
    .mh-scrolly-grid {
      timeline-scope: --mhs-1, --mhs-2, --mhs-3, --mhs-4;
      align-items: stretch;            /* stretch the stage so sticky has room */
    }

    /* Steps become tall scroll scenes; each names + consumes its own timeline
       (dim until centred, lane-bright at centre). */
    .mh-scrolly-step {
      min-height: 82vh;
      display: flex;
      flex-direction: column;
      justify-content: center;
      view-timeline-axis: block;
      animation: mh-scrolly-spotlight linear both;
    }
    .mh-scrolly-step:nth-child(1) { view-timeline-name: --mhs-1; animation-timeline: --mhs-1; }
    .mh-scrolly-step:nth-child(2) { view-timeline-name: --mhs-2; animation-timeline: --mhs-2; }
    .mh-scrolly-step:nth-child(3) { view-timeline-name: --mhs-3; animation-timeline: --mhs-3; }
    .mh-scrolly-step:nth-child(4) { view-timeline-name: --mhs-4; animation-timeline: --mhs-4; }

    /* Pin the panel; stack the visuals absolutely; cross-dissolve each as its
       paired step crosses the centre (the shorthand sets linear + fill:both;
       animation-timeline is then bound per child to that step's timeline). */
    .mh-scrolly-panel {
      position: sticky;
      top: 12vh;
      height: 76vh;
      display: block;
    }
    .mh-scrolly-vis {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      justify-content: center;
      opacity: 0;
      animation: mh-scrolly-mid linear both;
    }
    .mh-scrolly-vis:nth-child(1) { animation-name: mh-scrolly-first; animation-timeline: --mhs-1; }
    .mh-scrolly-vis:nth-child(2) { animation-timeline: --mhs-2; }
    .mh-scrolly-vis:nth-child(3) { animation-timeline: --mhs-3; }
    .mh-scrolly-vis:nth-child(4) { animation-name: mh-scrolly-last; animation-timeline: --mhs-4; }
  }
}
"""
