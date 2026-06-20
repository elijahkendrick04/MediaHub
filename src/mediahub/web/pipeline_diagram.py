"""U.8 — Animated how-it-works pipeline diagram (landing page).

A self-contained SVG + CSS-keyframes diagram for the home page that shows the
product thesis as a glowing circuit: MediaHub **reads** the sources a club
already has (club site / socials / brand kit) → the **engine** detects, ranks,
brands and generates → MediaHub **writes** posting-ready content (captions /
graphics / reels). Light pulses travel the connecting traces left-to-right
(top-to-bottom on mobile): cool/raw on the way in, lane-yellow/branded on the
way out.

Design rules honoured (see CLAUDE.md):
  * Reuses the blueprint grid motif — an in-SVG ``<pattern>`` lattice, the same
    faint scoreboard substrate used behind the hero.
  * On-brand restraint — lane-yellow is the only chrome accent (engine + the
    "branded out" pulses); medal-gold is *never* used here (reserved for athlete
    achievements). Reads stay neutral ink; writes are lit by the engine.
  * Pure SVG geometry + CSS ``@keyframes`` — no SMIL, no JS, no external deps.
  * Reduced-motion safe — the travelling pulses default to ``opacity:0`` and
    their keyframes *end* at ``opacity:0``, so when the global
    ``prefers-reduced-motion`` rule freezes animations at their final frame the
    diagram settles to clean static wires + chips + a steady engine glow.
  * Mobile-aware — a horizontal layout for >=720px and a stacked vertical layout
    for narrow screens (toggled purely by CSS) so node labels stay legible.

Pure presentation: there is no user data and no engine logic here, so nothing
to escape and no deterministic-engine surface is touched.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Icon glyphs — authored on a 24x24 canvas, stroke-only (colour + stroke-width
# come from CSS). Inner markup only; positioned + scaled by ``_icon``.
# --------------------------------------------------------------------------- #
_ICON_GLOBE = (
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><ellipse cx="12" cy="12" rx="4.2" ry="9"/>'
)
_ICON_SHARE = (
    '<circle cx="6" cy="12" r="2.3"/><circle cx="17.5" cy="6" r="2.3"/>'
    '<circle cx="17.5" cy="18" r="2.3"/><path d="M8 11l7-3.6M8 13l7 3.6"/>'
)
_ICON_SWATCH = (
    '<path d="M12 3a9 9 0 1 0 0 18 2.2 2.2 0 0 0 1.8-3.4 1.9 1.9 0 0 1 '
    '1.6-2.9H18a3 3 0 0 0 3-3.1A8.6 8.6 0 0 0 12 3z"/>'
    '<circle cx="7.6" cy="11.2" r="1.1"/><circle cx="11" cy="7.4" r="1.1"/>'
    '<circle cx="15.6" cy="8.7" r="1.1"/>'
)
_ICON_TEXT = '<path d="M5 7h14M5 11h14M5 15h10M5 19h6"/>'
_ICON_IMAGE = (
    '<rect x="3" y="4.5" width="18" height="15" rx="2"/>'
    '<circle cx="8.5" cy="10" r="1.9"/><path d="M21 16l-5-5-8 8"/>'
)
_ICON_REEL = '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M10.5 9l4.5 3-4.5 3z"/>'
_ICON_SPARK = (
    '<circle cx="12" cy="12" r="3.4"/>'
    '<path d="M12 3.2v3M12 17.8v3M3.2 12h3M17.8 12h3'
    'M6.1 6.1l2.1 2.1M15.8 15.8l2.1 2.1M17.9 6.1l-2.1 2.1M8.2 15.8l-2.1 2.1"/>'
)

# Node content (label, icon) — defined once, drawn in both orientations.
_READS = [
    ("Club site", _ICON_GLOBE),
    ("Socials", _ICON_SHARE),
    ("Brand kit", _ICON_SWATCH),
]
_WRITES = [
    ("Captions", _ICON_TEXT),
    ("Graphics", _ICON_IMAGE),
    ("Reels", _ICON_REEL),
]
_ENGINE_TITLE = "THE ENGINE"
_ENGINE_SUB = "detect · rank · brand · generate"

# Plain-language alternative announced to assistive tech (both SVGs are
# aria-hidden decorative duplicates of this single description).
_A11Y_SUMMARY = (
    "How MediaHub works: it reads the sources you already have — your club "
    "site, social profiles and brand kit. The engine detects the moments that "
    "matter, ranks them, applies your branding and generates the content. It "
    "writes posting-ready captions, graphics and reels for your approval."
)


# --------------------------------------------------------------------------- #
# Low-level SVG part builders
# --------------------------------------------------------------------------- #
def _icon(inner: str, cx: float, cy: float, size: float, cls: str) -> str:
    """Place a 24x24 icon centred at (cx, cy), scaled to ``size``."""
    s = size / 24.0
    tx = cx - 12 * s
    ty = cy - 12 * s
    return f'<g class="{cls}" transform="translate({tx:.2f} {ty:.2f}) scale({s:.4f})">{inner}</g>'


def _wire(d: str) -> str:
    """A static faint base trace (always visible — carries the diagram under
    reduced motion)."""
    return f'<path class="mh-pl-wire" d="{d}"/>'


def _pulse(d: str, direction: str, delay: float, dur: float = 3.0) -> str:
    """A travelling light pulse along ``d``. ``direction`` is ``in`` (cool/raw,
    reads→engine) or ``out`` (lane/branded, engine→writes)."""
    return (
        f'<path class="mh-pl-pulse mh-pl-pulse--{direction}" d="{d}" '
        f'pathLength="100" style="animation-delay:{delay:.2f}s;'
        f'animation-duration:{dur:.2f}s"/>'
    )


def _dot(x: float, y: float, kind: str, delay: float) -> str:
    """A glowing connection node where a trace meets a chip or the engine."""
    return (
        f'<circle class="mh-pl-dot mh-pl-dot--{kind}" cx="{x:.1f}" cy="{y:.1f}" '
        f'r="3" style="animation-delay:{delay:.2f}s"/>'
    )


def _engine(cx: float, cy: float, w: float, h: float) -> str:
    x0 = cx - w / 2
    y0 = cy - h / 2
    # Icon / title / sub are a single optically-centred stack: the spark caps
    # the wordmark with a tight gap, the title sits as the heaviest element and
    # the sub trails one line below — the whole cluster balanced around ``cy``.
    return (
        '<g class="mh-pl-engine">'
        f'<rect class="mh-pl-engine-bg" x="{x0:.1f}" y="{y0:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" rx="16"/>'
        + _icon(_ICON_SPARK, cx, cy - 23, 26, "mh-pl-ico mh-pl-ico--engine")
        + f'<text class="mh-pl-engine-title" x="{cx:.1f}" y="{cy + 15:.1f}" '
        f'text-anchor="middle">{_ENGINE_TITLE}</text>'
        + f'<text class="mh-pl-engine-sub" x="{cx:.1f}" y="{cy + 34:.1f}" '
        f'text-anchor="middle">{_ENGINE_SUB}</text>' + "</g>"
    )


def _head(text: str, x: float, y: float) -> str:
    return (
        f'<text class="mh-pl-col-head" x="{x:.1f}" y="{y:.1f}" text-anchor="middle">{text}</text>'
    )


# --------------------------------------------------------------------------- #
# Horizontal layout (>=720px) — reads | engine | writes, in three columns.
# --------------------------------------------------------------------------- #
def _svg_horizontal() -> str:
    W, H = 1040, 430
    chip_w, chip_h = 196, 66
    rows = [96, 230, 364]  # y-centres for the three read/write rows
    ports = [190, 230, 270]  # engine entry/exit y-positions
    read_x0, read_edge = 28, 28 + chip_w  # 28 .. 224
    write_x0 = 812
    write_edge = write_x0  # 812
    eng_cx, eng_cy, eng_w, eng_h = 520, 230, 244, 136
    eng_left, eng_right = eng_cx - eng_w / 2, eng_cx + eng_w / 2  # 398 .. 642

    wires, pulses, dots, chips = [], [], [], []

    # Read column → engine
    for i, ((label, icon), ry) in enumerate(zip(_READS, rows)):
        py = ports[i]
        d = f"M {read_edge} {ry} C {read_edge + 80} {ry}, {eng_left - 80} {py}, {eng_left} {py}"
        wires.append(_wire(d))
        pulses.append(_pulse(d, "in", delay=i * 0.5))
        dots.append(_dot(read_edge, ry, "read", delay=i * 0.5))
        dots.append(_dot(eng_left, py, "engine", delay=i * 0.5 + 0.4))
        chips.append(_chip_h(read_x0, ry, chip_w, chip_h, icon, label, "read"))

    # Engine → write column
    for i, ((label, icon), wy) in enumerate(zip(_WRITES, rows)):
        py = ports[i]
        d = f"M {eng_right} {py} C {eng_right + 80} {py}, {write_edge - 80} {wy}, {write_edge} {wy}"
        wires.append(_wire(d))
        pulses.append(_pulse(d, "out", delay=i * 0.5 + 1.4))
        dots.append(_dot(eng_right, py, "engine", delay=i * 0.5 + 1.0))
        dots.append(_dot(write_edge, wy, "write", delay=i * 0.5 + 1.8))
        chips.append(_chip_h(write_x0, wy, chip_w, chip_h, icon, label, "write"))

    heads = [
        _head("What it reads", read_x0 + chip_w / 2, 40),
        _head("What it writes", write_x0 + chip_w / 2, 40),
    ]
    body = (
        f'<rect class="mh-pl-grid-fill" x="0" y="0" width="{W}" height="{H}" fill="url(#mh-pl-grid-h)"/>'
        + '<g class="mh-pl-wires">'
        + "".join(wires)
        + "</g>"
        + '<g class="mh-pl-pulses">'
        + "".join(pulses)
        + "</g>"
        + '<g class="mh-pl-dots">'
        + "".join(dots)
        + "</g>"
        + '<g class="mh-pl-heads">'
        + "".join(heads)
        + "</g>"
        + '<g class="mh-pl-nodes">'
        + "".join(chips)
        + _engine(eng_cx, eng_cy, eng_w, eng_h)
        + "</g>"
    )
    return _svg_shell("h", W, H, body)


def _chip_h(x0: float, yc: float, w: float, h: float, icon: str, label: str, kind: str) -> str:
    y0 = yc - h / 2
    return (
        f'<g class="mh-pl-chip mh-pl-chip--{kind}">'
        f'<rect class="mh-pl-chip-bg" x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12"/>'
        + _icon(icon, x0 + 32, yc, 26, f"mh-pl-ico mh-pl-ico--{kind}")
        + f'<text class="mh-pl-chip-label" x="{x0 + 56:.1f}" y="{yc:.1f}" '
        f'dominant-baseline="central">{label}</text>' + "</g>"
    )


# --------------------------------------------------------------------------- #
# Vertical layout (<720px) — reads row / engine / writes row, stacked.
# --------------------------------------------------------------------------- #
def _svg_vertical() -> str:
    W, H = 460, 760
    chip_w, chip_h = 132, 84
    cols = [80, 230, 380]  # x-centres for the three read/write nodes
    ports = [190, 230, 270]  # engine entry/exit x-positions
    read_yc, write_yc = 78, 700
    read_edge = read_yc + chip_h / 2  # 120 (bottom of read chips)
    write_edge = write_yc - chip_h / 2  # 658 (top of write chips)
    eng_cx, eng_cy, eng_w, eng_h = 230, 400, 244, 136
    eng_top, eng_bot = eng_cy - eng_h / 2, eng_cy + eng_h / 2  # 332 .. 468

    wires, pulses, dots, chips = [], [], [], []

    for i, ((label, icon), cx) in enumerate(zip(_READS, cols)):
        px = ports[i]
        d = f"M {cx} {read_edge} C {cx} {read_edge + 110}, {px} {eng_top - 95}, {px} {eng_top}"
        wires.append(_wire(d))
        pulses.append(_pulse(d, "in", delay=i * 0.5))
        dots.append(_dot(cx, read_edge, "read", delay=i * 0.5))
        dots.append(_dot(px, eng_top, "engine", delay=i * 0.5 + 0.4))
        chips.append(_chip_v(cx, read_yc, chip_w, chip_h, icon, label, "read"))

    for i, ((label, icon), cx) in enumerate(zip(_WRITES, cols)):
        px = ports[i]
        d = f"M {px} {eng_bot} C {px} {eng_bot + 100}, {cx} {write_edge - 100}, {cx} {write_edge}"
        wires.append(_wire(d))
        pulses.append(_pulse(d, "out", delay=i * 0.5 + 1.4))
        dots.append(_dot(px, eng_bot, "engine", delay=i * 0.5 + 1.0))
        dots.append(_dot(cx, write_edge, "write", delay=i * 0.5 + 1.8))
        chips.append(_chip_v(cx, write_yc, chip_w, chip_h, icon, label, "write"))

    heads = [
        _head("What it reads", W / 2, 22),
        _head("What it writes", W / 2, 752),
    ]
    body = (
        f'<rect class="mh-pl-grid-fill" x="0" y="0" width="{W}" height="{H}" fill="url(#mh-pl-grid-v)"/>'
        + '<g class="mh-pl-wires">'
        + "".join(wires)
        + "</g>"
        + '<g class="mh-pl-pulses">'
        + "".join(pulses)
        + "</g>"
        + '<g class="mh-pl-dots">'
        + "".join(dots)
        + "</g>"
        + '<g class="mh-pl-heads">'
        + "".join(heads)
        + "</g>"
        + '<g class="mh-pl-nodes">'
        + "".join(chips)
        + _engine(eng_cx, eng_cy, eng_w, eng_h)
        + "</g>"
    )
    return _svg_shell("v", W, H, body)


def _chip_v(cx: float, yc: float, w: float, h: float, icon: str, label: str, kind: str) -> str:
    x0 = cx - w / 2
    y0 = yc - h / 2
    return (
        f'<g class="mh-pl-chip mh-pl-chip--{kind}">'
        f'<rect class="mh-pl-chip-bg" x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12"/>'
        + _icon(icon, cx, y0 + 28, 24, f"mh-pl-ico mh-pl-ico--{kind}")
        + f'<text class="mh-pl-chip-label mh-pl-chip-label--v" x="{cx:.1f}" y="{y0 + 64:.1f}" '
        f'text-anchor="middle">{label}</text>' + "</g>"
    )


def _svg_shell(suffix: str, w: int, h: int, body: str) -> str:
    """Wrap diagram ``body`` in an aria-hidden, responsive SVG with its own
    blueprint-grid ``<pattern>`` (ids are suffixed so the two SVGs never clash)."""
    return (
        f'<svg class="mh-pl-svg mh-pl-svg--{suffix}" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<defs><pattern id="mh-pl-grid-{suffix}" width="40" height="40" '
        f'patternUnits="userSpaceOnUse">'
        f'<path class="mh-pl-grid" d="M40 0H0V40"/></pattern></defs>'
        f"{body}</svg>"
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def pipeline_diagram_section_html() -> str:
    """The full landing-page section markup for the U.8 pipeline diagram.

    Deterministic (no randomness / no I/O) so it is safe to cache and simple to
    test. Carries ``mh-reveal`` so it joins the existing scroll-reveal system.
    """
    return (
        '<section class="mh-section mh-reveal mh-pl-section" id="mh-ch-how" aria-labelledby="mh-pl-title">'
        '<div class="mh-section-eyebrow-strip"><span class="label">How it works</span></div>'
        '<h2 class="mh-section-title" id="mh-pl-title">'
        'Reads what your club already has. <em class="editorial">Writes</em> what you need.</h2>'
        '<p class="mh-pl-lede">MediaHub reads the sources you already have: your '
        "club site, social profiles and brand kit. It works out what matters, ranks "
        "it, then writes captions, builds graphics and renders reels. In your "
        "colours, in your voice. Nothing leaves without your approval.</p>"
        '<div class="mh-pl-stage">'
        f'<p class="mh-visually-hidden">{_A11Y_SUMMARY}</p>'
        f"{_svg_horizontal()}{_svg_vertical()}"
        "</div>"
        "</section>"
    )


# --------------------------------------------------------------------------- #
# CSS — appended to BASE_CSS ahead of the responsive guardrails layer.
# --------------------------------------------------------------------------- #
PIPELINE_DIAGRAM_CSS = """
/* ===================================================================== */
/* U.8 — Animated how-it-works pipeline diagram                          */
/* Glowing nodes + connecting traces: reads (club site / socials / brand */
/* kit) -> MediaHub engine -> writes (captions / graphics / reels).      */
/* SVG geometry + CSS keyframes; reuses the blueprint grid motif via an  */
/* in-SVG <pattern>. The static wires + chips read fine with motion      */
/* frozen, so prefers-reduced-motion (gated at the foot of this file)     */
/* settles clean.                                                         */
/* ===================================================================== */
.mh-pl-lede {
  max-width: 66ch;
  margin: 0 0 var(--sp-6);
  color: var(--ink-dim);
  font-size: 16px;
  line-height: 1.55;
}
.mh-pl-stage {
  position: relative;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(120% 130% at 50% 0%, color-mix(in oklab, var(--lane) 5%, transparent), transparent 62%),
    var(--surface);
  padding: var(--sp-6);
  overflow: hidden;
}
/* When SIGNED OUT, this is the unbranded marketing home: it runs the generic-
   default navy kit, which would drag the diagram's lit traces to a near-
   invisible navy. There the engine stays MediaHub's own signature lane-yellow,
   pinned and scoped to the stage. When SIGNED IN, the diagram is the club's
   surface, so it drops the pin and follows the active brand (--lane ←
   --mh-primary) like every other accent on the site. */
html:not(.mh-signed-in) .mh-pl-stage {
  --lane: #D4FF3A;
  --lane-glow: rgba(212,255,58,0.35);
}
.mh-pl-svg { display: block; width: 100%; height: auto; }
.mh-pl-svg--v { display: none; }
@media (max-width: 720px) {
  .mh-pl-svg--h { display: none; }
  .mh-pl-svg--v { display: block; }
  .mh-pl-stage { padding: var(--sp-4); }
}

/* Blueprint grid lattice (the reused motif) */
.mh-pl-grid { stroke: rgba(245,242,232,0.05); stroke-width: 1; fill: none; }

/* Static base traces — always visible */
.mh-pl-wire { fill: none; stroke: var(--chrome); stroke-width: 1.6; }

/* Node chips */
.mh-pl-chip-bg { fill: var(--surface-2); stroke: var(--chrome); stroke-width: 1; }
/* Writes are the branded output, so their chips pick up a faint lane edge and
   bed-glow — neutral sources in, club-coloured content out. */
.mh-pl-chip--write .mh-pl-chip-bg {
  stroke: color-mix(in oklab, var(--lane) 34%, var(--chrome));
  fill: color-mix(in oklab, var(--lane) 5%, var(--surface-2));
}
.mh-pl-chip-label {
  fill: var(--ink);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 21px;
  letter-spacing: 0.01em;
  text-transform: uppercase;
}
.mh-pl-chip-label--v { font-size: 18px; }

/* Icons — crisp at any scale; reads matte, writes/engine lit lane-yellow */
.mh-pl-ico { fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.mh-pl-ico > * { vector-effect: non-scaling-stroke; }
.mh-pl-ico--read { stroke: var(--ink-dim); }
.mh-pl-ico--write { stroke: var(--lane); filter: drop-shadow(0 0 4px var(--lane-glow)); }
.mh-pl-ico--engine { stroke: var(--lane); filter: drop-shadow(0 0 5px var(--lane-glow)); }

/* Engine node — the lane-accented hub, breathing glow */
.mh-pl-engine-bg {
  fill: var(--surface-3);
  stroke: var(--lane);
  stroke-width: 1.75;
  filter: drop-shadow(0 0 10px var(--lane-glow));
  animation: mh-pl-breathe 3.4s ease-in-out infinite;
}
.mh-pl-engine-title {
  fill: var(--ink);
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 23px;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.mh-pl-engine-sub {
  fill: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.02em;
}
.mh-pl-col-head {
  fill: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}

/* Glowing connection nodes — steady soft glow at rest, gentle pulse in motion */
.mh-pl-dot { fill: var(--lane); filter: drop-shadow(0 0 4px var(--lane-glow));
  animation: mh-pl-dot-pulse 2.6s ease-in-out infinite; }
.mh-pl-dot--read { fill: var(--ink); filter: drop-shadow(0 0 4px rgba(245,242,232,0.35)); }

/* Travelling pulses — INVISIBLE at rest (opacity:0) and the keyframes END at
   opacity:0, so the reduced-motion freeze (foot of this file) leaves the
   diagram as clean static wires. pathLength="100" makes the dash maths
   path-length independent. */
.mh-pl-pulse {
  fill: none;
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-dasharray: 7 93;
  opacity: 0;
  animation: mh-pl-flow 3s linear infinite;
}
.mh-pl-pulse--in { stroke: var(--ink); }
.mh-pl-pulse--out { stroke: var(--lane); filter: drop-shadow(0 0 5px var(--lane-glow)); }

@keyframes mh-pl-flow {
  0%   { stroke-dashoffset: 0;    opacity: 0; }
  12%  { opacity: 1; }
  85%  { opacity: 1; }
  100% { stroke-dashoffset: -100; opacity: 0; }
}
@keyframes mh-pl-dot-pulse {
  0%, 100% { opacity: 0.5; }
  50%      { opacity: 1; }
}
@keyframes mh-pl-breathe {
  0%, 100% { filter: drop-shadow(0 0 10px var(--lane-glow)); }
  50%      { filter: drop-shadow(0 0 18px var(--lane-glow)); }
}

/* Honour the reduced-motion cohort. The travelling pulses rest at opacity:0
   and the dots/engine settle to their base glow, so freezing every animation
   leaves clean static wires + a steady engine — the "settled" state the
   diagram was designed around. This rule lives with the animations it gates,
   so it also covers the Create "how it works" intro slides, which reuse these
   .mh-pl-* classes. (It was previously assumed to be handled by a global
   freeze that did not exist, so the diagram animated regardless of the
   preference.) */
@media (prefers-reduced-motion: reduce) {
  .mh-pl-pulse,
  .mh-pl-dot,
  .mh-pl-engine-bg { animation: none; }
}
"""
