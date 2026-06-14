"""UI 1.13 — Annotated UI callouts ("anatomy of a card").

A self-contained SVG diagram for the landing page that takes ONE finished
MediaHub content card and labels every part of it — a detected moment, a
verified time, the club's branding, a caption in the club's voice, and a
confidence score — with numbered hotspot pins joined to side callouts by
SVG connector lines. It answers the question a first-time visitor (or a
committee member on the onboarding tour) actually has: *what is all of this,
and where did each piece come from?*

The eight annotated parts trace the intelligence-layer story MediaHub sells —
ingest → detect → rank → brand → generate → approve:

  1. logo + palette   — read from the club's own site, locked onto every card
  2. moment pill      — the achievement the engine detected and ranked
  3. name + event     — normalised from the raw results file
  4. confidence score — how sure the engine is before a human ever sees it
  5. format badge     — story 1080x1920, rendered server-side
  6. headline time    — read straight from the results sheet
  7. PB delta         — verified against the swimmer's season history
  8. caption          — written in the club's voice, never auto-posted

Design rules honoured (see CLAUDE.md):
  * Pure SVG geometry + a little CSS — no JS, no charting/annotation library,
    no external deps, no Google-Fonts CDN.
  * Two orientations toggled purely by CSS: a horizontal "card in the middle,
    callouts fanning out either side" layout for >=760px, and a stacked
    "card on top, numbered legend below" layout for narrow screens (the
    crossing connector lines do not fit a phone, so the numbered pins map to
    a legible HTML legend instead — the standard accessible degradation).
  * On-brand restraint — lane-yellow is the system/brand accent (pins,
    connector lines, logo, confidence); medal-gold marks the *athlete
    achievement* it legitimately depicts (the moment pill + the verified PB
    delta), which is exactly what medal-gold is reserved for.
  * Static by default with one reduced-motion-safe pin shimmer (it oscillates
    opacity around a visible value, so the global prefers-reduced-motion
    freeze settles on a clean, fully-visible diagram).

Pure presentation: the card depicts an illustrative club (Riverside SC,
Tom Davies) — there is no real user data and no engine logic here, so nothing
to escape and no deterministic-engine surface is touched.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# The illustrative card's content — an honest example of a real story card.
# --------------------------------------------------------------------------- #
_LOGO = "RS"
_CLUB = "Riverside SC"
_SWIMMER = "Tom Davies"
_EVENT = "100m Freestyle"
_TIME = "52.41"
_DELTA = "−0.74s"          # U+2212 MINUS SIGN — typographic, not a hyphen
_MOMENT = "Personal best"
_CONF = 92
_CAPTION = (
    "Tom knocks three-quarters of a",
    "second off his 100m free PB.",
)
# The illustrative club palette (lane-yellow, medal-gold, pool-teal, chalk).
_SWATCHES = ("a", "b", "c", "d")

# Each annotated part: (number, fx, fy, side, title, description).
# fx/fy are fractions of the card box, so the pins, the card content and the
# connector endpoints all track one source of truth if the box is resized.
_ANATOMY = [
    (1, 0.150, 0.088, "L", "Your logo and palette, locked on",
     "Read from your own club site, then pinned to every card."),
    (2, 0.120, 0.205, "L", "A moment, detected and ranked",
     "The engine found this swim and scored it worth posting."),
    (3, 0.300, 0.340, "L", "Names and events, normalised",
     "Cleaned and matched from your raw results file."),
    (4, 0.280, 0.720, "L", "A confidence score on every card",
     "How sure the engine is, before a human ever sees it."),
    (5, 0.810, 0.085, "R", "Story format",
     "1080×1920, rendered on our server — ready to post."),
    (6, 0.430, 0.545, "R", "The headline time",
     "Read straight from the results sheet, never guessed."),
    (7, 0.755, 0.545, "R", "A verified personal best",
     "Checked against this swimmer’s own season history."),
    (8, 0.545, 0.850, "R", "A caption in your voice",
     "Written on-brand. Nothing posts without your approval."),
]

# Plain-language alternative announced to assistive tech (both SVGs are
# aria-hidden decorative duplicates of this single description).
_A11Y_SUMMARY = (
    "Anatomy of a MediaHub content card, using an example story card for "
    "Riverside SC: a personal best for Tom Davies in the 100m freestyle, "
    "52.41. Eight numbered callouts label its parts — the club logo and "
    "palette read from your own site; the moment the engine detected and "
    "ranked; the swimmer name and event normalised from your results file; a "
    "confidence score carried on every card; the story format rendered on our "
    "server; the headline time read straight from the sheet; the personal "
    "best verified against the swimmer’s season history; and a caption "
    "written in your club voice that never posts without your approval."
)


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _abs(box, fx: float, fy: float):
    x0, y0, w, h = box
    return x0 + fx * w, y0 + fy * h


def _pin(n: int, x: float, y: float) -> str:
    """A numbered hotspot pin sitting on the card."""
    return (
        f'<g class="mh-an-pin">'
        f'<circle class="mh-an-pin-halo" cx="{x:.1f}" cy="{y:.1f}" r="15.5" '
        f'style="animation-delay:{(n - 1) * 0.18:.2f}s"/>'
        f'<circle class="mh-an-pin-dot" cx="{x:.1f}" cy="{y:.1f}" r="12"/>'
        f'<text class="mh-an-pin-num" x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
        f'dominant-baseline="central">{n}</text>'
        f"</g>"
    )


def _connector(side: str, lx: float, ly: float, px: float, py: float) -> str:
    """A curved connector line from a side callout anchor to a card pin."""
    k = 58.0
    if side == "L":
        d = f"M {lx:.1f} {ly:.1f} C {lx + k:.1f} {ly:.1f}, {px - k:.1f} {py:.1f}, {px:.1f} {py:.1f}"
    else:
        d = f"M {lx:.1f} {ly:.1f} C {lx - k:.1f} {ly:.1f}, {px + k:.1f} {py:.1f}, {px:.1f} {py:.1f}"
    return f'<path class="mh-an-line" d="{d}"/>'


def _callout(side: str, lx: float, ly: float, n: int, title: str, desc: str) -> str:
    """A side callout: a numbered tag at the line anchor, then a title + a one
    line description, right-aligned on the left side and left-aligned on the
    right so both columns read inward toward the card."""
    if side == "L":
        tag_x = lx
        text_x = lx - 26
        anchor = "end"
    else:
        tag_x = lx
        text_x = lx + 26
        anchor = "start"
    return (
        '<g class="mh-an-callout">'
        f'<circle class="mh-an-tag-dot" cx="{tag_x:.1f}" cy="{ly:.1f}" r="12"/>'
        f'<text class="mh-an-tag-num" x="{tag_x:.1f}" y="{ly:.1f}" text-anchor="middle" '
        f'dominant-baseline="central">{n}</text>'
        f'<text class="mh-an-title" x="{text_x:.1f}" y="{ly - 5:.1f}" '
        f'text-anchor="{anchor}">{title}</text>'
        f'<text class="mh-an-desc" x="{text_x:.1f}" y="{ly + 15:.1f}" '
        f'text-anchor="{anchor}">{desc}</text>'
        "</g>"
    )


# --------------------------------------------------------------------------- #
# The card illustration (drawn once, placed by both orientations)
# --------------------------------------------------------------------------- #
def _card(box) -> str:
    """Draw the illustrative story card (no pins) inside ``box``."""
    x0, y0, w, h = box
    P = lambda fx, fy: _abs(box, fx, fy)  # noqa: E731 — terse local geometry

    # Card shell.
    parts = [
        f'<rect class="mh-an-card-bg" x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" '
        f'height="{h:.1f}" rx="22"/>',
        f'<rect class="mh-an-card-edge" x="{x0 + 0.5:.1f}" y="{y0 + 0.5:.1f}" '
        f'width="{w - 1:.1f}" height="{h - 1:.1f}" rx="21.5"/>',
    ]

    # Logo chip (top-left).
    lc_x, lc_y = P(0.150, 0.088)
    parts.append(
        f'<rect class="mh-an-logo-bg" x="{lc_x - 22:.1f}" y="{lc_y - 22:.1f}" '
        f'width="44" height="44" rx="11"/>'
        f'<text class="mh-an-logo-tx" x="{lc_x:.1f}" y="{lc_y:.1f}" '
        f'text-anchor="middle" dominant-baseline="central">{_LOGO}</text>'
    )
    # Club name beside the logo.
    parts.append(
        f'<text class="mh-an-club" x="{lc_x + 32:.1f}" y="{lc_y:.1f}" '
        f'dominant-baseline="central">{_CLUB}</text>'
    )
    # Format badge (top-right).
    fb_x, fb_y = P(0.815, 0.085)
    parts.append(
        f'<rect class="mh-an-format-bg" x="{fb_x - 34:.1f}" y="{fb_y - 13:.1f}" '
        f'width="68" height="26" rx="13"/>'
        f'<text class="mh-an-format-tx" x="{fb_x:.1f}" y="{fb_y:.1f}" '
        f'text-anchor="middle" dominant-baseline="central">STORY</text>'
    )

    # Moment pill.
    mp_x, mp_y = P(0.080, 0.205)
    parts.append(
        f'<rect class="mh-an-pill-bg" x="{mp_x:.1f}" y="{mp_y - 14:.1f}" '
        f'width="148" height="28" rx="14"/>'
        f'<text class="mh-an-pill-tx" x="{mp_x + 16:.1f}" y="{mp_y:.1f}" '
        f'dominant-baseline="central">{_MOMENT.upper()}</text>'
    )

    # Swimmer name + event.
    nm_x, nm_y = P(0.080, 0.335)
    parts.append(
        f'<text class="mh-an-name" x="{nm_x:.1f}" y="{nm_y:.1f}">{_SWIMMER}</text>'
    )
    ev_x, ev_y = P(0.080, 0.405)
    parts.append(
        f'<text class="mh-an-event" x="{ev_x:.1f}" y="{ev_y:.1f}">{_EVENT}</text>'
    )

    # Headline time (the hero) + PB delta badge.
    tm_x, tm_y = P(0.080, 0.575)
    parts.append(
        f'<text class="mh-an-time" x="{tm_x:.1f}" y="{tm_y:.1f}">{_TIME}</text>'
    )
    dl_x, dl_y = P(0.620, 0.520)
    parts.append(
        f'<rect class="mh-an-delta-bg" x="{dl_x:.1f}" y="{dl_y - 22:.1f}" '
        f'width="92" height="44" rx="11"/>'
        f'<text class="mh-an-delta-tx" x="{dl_x + 46:.1f}" y="{dl_y - 4:.1f}" '
        f'text-anchor="middle">{_DELTA}</text>'
        f'<text class="mh-an-delta-sub" x="{dl_x + 46:.1f}" y="{dl_y + 12:.1f}" '
        f'text-anchor="middle">SEASON BEST</text>'
    )

    # Confidence chip + mini bar.
    cf_x, cf_y = P(0.080, 0.705)
    parts.append(
        f'<text class="mh-an-conf-tx" x="{cf_x:.1f}" y="{cf_y:.1f}">'
        f'CONFIDENCE {_CONF}%</text>'
    )
    bar_x, bar_y, bar_w = cf_x, cf_y + 12, w * 0.40
    parts.append(
        f'<rect class="mh-an-conf-track" x="{bar_x:.1f}" y="{bar_y:.1f}" '
        f'width="{bar_w:.1f}" height="6" rx="3"/>'
        f'<rect class="mh-an-conf-fill" x="{bar_x:.1f}" y="{bar_y:.1f}" '
        f'width="{bar_w * _CONF / 100:.1f}" height="6" rx="3"/>'
    )

    # Caption (two lines near the foot).
    cap_x, cap_y = P(0.080, 0.840)
    parts.append(
        f'<text class="mh-an-cap" x="{cap_x:.1f}" y="{cap_y:.1f}">{_CAPTION[0]}</text>'
        f'<text class="mh-an-cap" x="{cap_x:.1f}" y="{cap_y + 20:.1f}">{_CAPTION[1]}</text>'
    )

    # Brand palette strip (foot).
    sw_x, sw_y = P(0.080, 0.945)
    for i, kind in enumerate(_SWATCHES):
        parts.append(
            f'<rect class="mh-an-sw mh-an-sw--{kind}" x="{sw_x + i * 24:.1f}" '
            f'y="{sw_y - 9:.1f}" width="18" height="18" rx="5"/>'
        )

    return '<g class="mh-an-card">' + "".join(parts) + "</g>"


def _grid(suffix: str, w: int, h: int) -> str:
    return (
        f'<defs><pattern id="mh-an-grid-{suffix}" width="40" height="40" '
        f'patternUnits="userSpaceOnUse">'
        f'<path class="mh-an-grid" d="M40 0H0V40"/></pattern></defs>'
        f'<rect class="mh-an-grid-fill" x="0" y="0" width="{w}" height="{h}" '
        f'fill="url(#mh-an-grid-{suffix})"/>'
    )


def _svg_shell(suffix: str, w: int, h: int, body: str) -> str:
    return (
        f'<svg class="mh-an-svg mh-an-svg--{suffix}" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f"{_grid(suffix, w, h)}{body}</svg>"
    )


# --------------------------------------------------------------------------- #
# Horizontal layout (>=760px) — card centred, callouts fanning out both sides.
# --------------------------------------------------------------------------- #
def _svg_horizontal() -> str:
    W, H = 1120, 650
    box = (410, 90, 300, 470)  # x0, y0, w, h

    # Evenly distribute the four left and four right callouts down the card.
    col_ys = [140.0 + i * (380.0 / 3.0) for i in range(4)]
    left_x, right_x = 372.0, 748.0

    lines, callouts, pins = [], [], []
    li = ri = 0
    for n, fx, fy, side, title, desc in _ANATOMY:
        px, py = _abs(box, fx, fy)
        pins.append(_pin(n, px, py))
        if side == "L":
            ly = col_ys[li]
            li += 1
            lx = left_x
        else:
            ly = col_ys[ri]
            ri += 1
            lx = right_x
        lines.append(_connector(side, lx, ly, px, py))
        callouts.append(_callout(side, lx, ly, n, title, desc))

    body = (
        _card(box)
        + '<g class="mh-an-lines">' + "".join(lines) + "</g>"
        + '<g class="mh-an-pins">' + "".join(pins) + "</g>"
        + '<g class="mh-an-callouts">' + "".join(callouts) + "</g>"
    )
    return _svg_shell("h", W, H, body)


# --------------------------------------------------------------------------- #
# Vertical layout (<760px) — card on top with pins; the numbered legend (an
# accessible HTML list) carries the labels below it.
# --------------------------------------------------------------------------- #
def _svg_vertical() -> str:
    W, H = 380, 560
    box = (40, 40, 300, 470)
    pins = [_pin(n, *_abs(box, fx, fy)) for n, fx, fy, *_ in _ANATOMY]
    body = _card(box) + '<g class="mh-an-pins">' + "".join(pins) + "</g>"
    return _svg_shell("v", W, H, body)


def _legend_html() -> str:
    items = "".join(
        f'<li class="mh-an-leg-item">'
        f'<span class="mh-an-leg-num">{n}</span>'
        f'<span class="mh-an-leg-text">'
        f'<b class="mh-an-leg-title">{title}</b>'
        f'<span class="mh-an-leg-desc">{desc}</span>'
        f"</span></li>"
        for n, _fx, _fy, _side, title, desc in _ANATOMY
    )
    return f'<ol class="mh-an-legend" aria-hidden="true">{items}</ol>'


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def anatomy_callout_section_html() -> str:
    """The full landing-page section markup for the UI 1.13 anatomy diagram.

    Deterministic (no randomness / no I/O) so it is safe to cache and simple to
    test. Carries ``mh-reveal`` so it joins the existing scroll-reveal system.
    """
    return (
        '<section class="mh-section mh-reveal mh-an-section" aria-labelledby="mh-an-title">'
        '<div class="mh-section-eyebrow-strip"><span class="label">Anatomy of a card</span></div>'
        '<h2 class="mh-section-title" id="mh-an-title">'
        'Every part, <em class="editorial">accounted for</em>.</h2>'
        '<p class="mh-an-lede">One generated card carries a lot: a detected '
        "moment, a time read straight from the sheet, your branding, a caption "
        "in your voice — and a confidence score for all of it. Here is "
        "where each piece comes from.</p>"
        '<div class="mh-an-stage">'
        f'<p class="mh-visually-hidden">{_A11Y_SUMMARY}</p>'
        f"{_svg_horizontal()}{_svg_vertical()}"
        f"{_legend_html()}"
        "</div>"
        "</section>"
    )


# --------------------------------------------------------------------------- #
# CSS — appended to BASE_CSS ahead of the responsive guardrails layer.
# --------------------------------------------------------------------------- #
ANATOMY_CALLOUT_CSS = """
/* ===================================================================== */
/* UI 1.13 — Annotated UI callouts ("anatomy of a card")                 */
/* One example story card, with eight numbered hotspot pins joined to    */
/* side callouts by SVG connector lines. Lane-yellow is the system       */
/* accent (pins, lines, logo, confidence); medal-gold marks the athlete  */
/* achievement it depicts (moment pill + verified PB delta). Static save  */
/* for one reduced-motion-safe pin shimmer that settles fully visible.   */
/* ===================================================================== */
.mh-an-lede {
  max-width: 64ch;
  margin: 0 0 var(--sp-6);
  color: var(--ink-dim);
  font-size: 16px;
  line-height: 1.55;
}
.mh-an-stage {
  position: relative;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(120% 130% at 50% 0%, rgba(212,255,58,0.05), transparent 62%),
    var(--surface);
  padding: var(--sp-6);
  overflow: hidden;
}
.mh-an-svg { display: block; width: 100%; height: auto; }
.mh-an-svg--v { display: none; }
.mh-an-legend { display: none; }

@media (max-width: 760px) {
  .mh-an-svg--h { display: none; }
  .mh-an-svg--v { display: block; max-width: 360px; margin: 0 auto; }
  .mh-an-stage { padding: var(--sp-5) var(--sp-4); }
  .mh-an-legend { display: grid; }
}

/* Blueprint grid substrate (the reused motif) */
.mh-an-grid { stroke: rgba(245,242,232,0.05); stroke-width: 1; fill: none; }

/* ---- The example card -------------------------------------------------- */
.mh-an-card-bg {
  fill: var(--surface-2);
  filter: drop-shadow(0 18px 40px rgba(0,0,0,0.45));
}
.mh-an-card-edge { fill: none; stroke: var(--chrome); stroke-width: 1; }
.mh-an-logo-bg { fill: var(--lane); }
.mh-an-logo-tx {
  fill: #0c0d09;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 19px;
  letter-spacing: 0.01em;
}
.mh-an-club {
  fill: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
.mh-an-format-bg { fill: none; stroke: var(--chrome); stroke-width: 1; }
.mh-an-format-tx {
  fill: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
}
.mh-an-pill-bg {
  fill: rgba(244,213,141,0.12);
  stroke: var(--medal);
  stroke-width: 1;
}
.mh-an-pill-tx {
  fill: var(--medal);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.10em;
}
.mh-an-name {
  fill: var(--ink);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 30px;
  letter-spacing: 0.005em;
}
.mh-an-event {
  fill: var(--ink-dim);
  font-family: var(--font-mono);
  font-size: 15px;
  letter-spacing: 0.04em;
}
.mh-an-time {
  fill: var(--ink);
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 78px;
  letter-spacing: -0.02em;
}
.mh-an-delta-bg {
  fill: rgba(244,213,141,0.14);
  stroke: var(--medal);
  stroke-width: 1;
}
.mh-an-delta-tx {
  fill: var(--medal);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 19px;
}
.mh-an-delta-sub {
  fill: var(--medal);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  opacity: 0.85;
}
.mh-an-conf-tx {
  fill: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.10em;
}
.mh-an-conf-track { fill: var(--chrome); }
.mh-an-conf-fill { fill: var(--lane); }
.mh-an-cap {
  fill: var(--ink-dim);
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 14px;
}
.mh-an-sw--a { fill: var(--lane); }
.mh-an-sw--b { fill: var(--medal); }
.mh-an-sw--c { fill: #3aa6a0; }
.mh-an-sw--d { fill: #f5f2e8; }

/* ---- Connector lines + hotspot pins ----------------------------------- */
.mh-an-line {
  fill: none;
  stroke: var(--lane);
  stroke-width: 1.4;
  stroke-opacity: 0.55;
  stroke-dasharray: 4 4;
}
.mh-an-pin-halo {
  fill: var(--lane);
  opacity: 0.22;
  animation: mh-an-shimmer 3.2s ease-in-out infinite;
}
.mh-an-pin-dot {
  fill: var(--lane);
  stroke: #0c0d09;
  stroke-width: 1.5;
}
.mh-an-pin-num {
  fill: #0c0d09;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 15px;
}

/* ---- Side callouts ----------------------------------------------------- */
.mh-an-tag-dot {
  fill: none;
  stroke: var(--lane);
  stroke-width: 1.5;
}
.mh-an-tag-num {
  fill: var(--lane);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 14px;
}
.mh-an-title {
  fill: var(--ink);
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 18px;
}
.mh-an-desc {
  fill: var(--ink-muted);
  font-family: var(--font-body, var(--font-mono));
  font-size: 13px;
}

/* ---- Mobile legend ----------------------------------------------------- */
.mh-an-legend {
  list-style: none;
  margin: var(--sp-5) 0 0;
  padding: 0;
  gap: var(--sp-3);
}
.mh-an-leg-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.mh-an-leg-num {
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--lane);
  color: #0c0d09;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.mh-an-leg-text { display: block; }
.mh-an-leg-title {
  display: block;
  color: var(--ink);
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 15px;
  line-height: 1.3;
}
.mh-an-leg-desc {
  display: block;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.45;
  margin-top: 2px;
}

@keyframes mh-an-shimmer {
  0%, 100% { opacity: 0.18; }
  50%      { opacity: 0.40; }
}
"""
