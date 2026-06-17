"""Create → heading "how it works" first slide.

Every tile under the Create tab links here first (``/make/<type>``). Before the
real flow starts, the user gets a per-heading intro slide built in the same
visual language as the landing page's pipeline diagram (``pipeline_diagram.py``):
a glowing **you give → the engine → you get** circuit, then a few numbered
steps and a single "Start" CTA into the real route.

Why it lives here and how it stays automatic
---------------------------------------------
The slide is driven entirely by the :class:`~mediahub.club_platform.content_types.ContentTypeMeta`
registry. A heading's bespoke copy comes from its optional
:class:`~mediahub.club_platform.content_types.HowItWorks`; when a new content
type omits it, :func:`_resolved_hiw` derives a sensible default from the
existing title/description. So the moment a developer adds a heading to the
REGISTRY it gets a working first slide — no per-heading wiring, no new route.

Pure presentation: there is no user data here (every label is registry-authored),
and no engine / AI / deterministic surface is touched. The diagram is
self-contained SVG geometry that *reuses the landing diagram's ``.mh-pl-*`` CSS
classes* for a pixel-consistent look, with its own variable-count layout maths
so any number of inputs/outputs (1–4+) lays out cleanly. SVG + CSS keyframes
only — no SMIL, no JS — and the travelling pulses inherit the landing diagram's
reduced-motion-safe rules.
"""

from __future__ import annotations

from mediahub.club_platform.content_types import ContentTypeMeta, HowItWorks

# --------------------------------------------------------------------------- #
# Presentation metadata (output formats + rough effort), keyed by ContentType
# value. Shared with the Create page so the two surfaces never drift. UI sugar
# only — it does NOT live on the registry dataclass, so editing it can never
# affect the engine. Unknown types fall back to a generic chip.
# --------------------------------------------------------------------------- #
PRESENTATION_FORMATS: dict[str, tuple[list[str], str]] = {
    "meet_recap": (["Caption", "Graphic", "Reel"], "~ 60s"),
    "athlete_spotlight": (["Caption", "Graphic", "Story"], "~ 45s"),
    "event_preview": (["Caption", "Graphic"], "~ 40s"),
    "sponsor_activation": (["Caption", "Graphic"], "~ 30s"),
    "session_update": (["Caption", "Graphic"], "~ 20s"),
    "free_text": (["Caption", "Graphic"], "~ 15s"),
}


def presentation_for(ct_value: str) -> tuple[list[str], str]:
    """(formats, effort) for a content-type value, with a safe generic default."""
    return PRESENTATION_FORMATS.get(ct_value, (["Caption", "Graphic"], ""))


# --------------------------------------------------------------------------- #
# Icon glyphs — authored on a 24x24 canvas, stroke-only (colour + stroke-width
# come from the reused .mh-pl-ico CSS). Inner markup only; scaled by ``_icon``.
# --------------------------------------------------------------------------- #
_ICON_SPARK = (
    '<circle cx="12" cy="12" r="3.4"/>'
    '<path d="M12 3.2v3M12 17.8v3M3.2 12h3M17.8 12h3'
    'M6.1 6.1l2.1 2.1M15.8 15.8l2.1 2.1M17.9 6.1l-2.1 2.1M8.2 15.8l-2.1 2.1"/>'
)
_GLYPHS: dict[str, str] = {
    # "what you give" inputs
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "pb": '<path d="M3 17l5-5 4 4 8-8"/><path d="M16 8h5v5"/>',
    "brand": (
        '<path d="M12 3a9 9 0 1 0 0 18 2.2 2.2 0 0 0 1.8-3.4 1.9 1.9 0 0 1 '
        '1.6-2.9H18a3 3 0 0 0 3-3.1A8.6 8.6 0 0 0 12 3z"/>'
        '<circle cx="7.6" cy="11.2" r="1.1"/><circle cx="11" cy="7.4" r="1.1"/>'
        '<circle cx="15.6" cy="8.7" r="1.1"/>'
    ),
    "meet": (
        '<rect x="6" y="4" width="12" height="17" rx="2"/>'
        '<path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/>'
        '<path d="M9 10h6M9 14h6"/>'
    ),
    "swimmer": '<circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>',
    "event": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "photo": (
        '<rect x="3" y="4.5" width="18" height="15" rx="2"/>'
        '<circle cx="8.5" cy="10" r="1.9"/><path d="M21 16l-5-5-8 8"/>'
    ),
    "sponsor": (
        '<polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 '
        '12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>'
    ),
    "trophy": (
        '<path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0z"/>'
        '<path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 0-3 3"/>'
    ),
    "words": (
        '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
        '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'
    ),
    "note": '<path d="M5 7h14M5 11h14M5 15h10M5 19h6"/>',
    # "what you get" outputs
    "caption": '<path d="M5 7h14M5 11h14M5 15h10M5 19h6"/>',
    "graphic": (
        '<rect x="3" y="4.5" width="18" height="15" rx="2"/>'
        '<circle cx="8.5" cy="10" r="1.9"/><path d="M21 16l-5-5-8 8"/>'
    ),
    "reel": '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M10.5 9l4.5 3-4.5 3z"/>',
    "story": '<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 6.5h2"/>',
}
_GLYPH_FALLBACK = _GLYPHS["note"]

# Output format label (lower-cased) → (display label, glyph key, canonical dims).
# Dims are honest, fact-based — the same canonical sizes the renderer emits.
_OUTPUT_META: dict[str, tuple[str, str, str]] = {
    "caption": ("Caption", "caption", "Ready to post"),
    "graphic": ("Graphic", "graphic", "1080×1350"),
    "reel": ("Reel", "reel", "1080×1920"),
    "story": ("Story", "story", "1080×1920"),
}


def _glyph(key: str) -> str:
    return _GLYPHS.get(key, _GLYPH_FALLBACK)


def _x(s: object) -> str:
    """Minimal XML/HTML text-node escape (labels are registry-authored, but we
    escape defensively so the hand-built SVG/markup is always well-formed)."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
# Leaf SVG builders — emit the landing diagram's .mh-pl-* classes so the intro
# circuit is visually identical to the home page, with its own geometry below.
# --------------------------------------------------------------------------- #
def _icon(inner: str, cx: float, cy: float, size: float, cls: str) -> str:
    s = size / 24.0
    return (
        f'<g class="{cls}" transform="translate({cx - 12 * s:.2f} '
        f'{cy - 12 * s:.2f}) scale({s:.4f})">{inner}</g>'
    )


def _wire(d: str) -> str:
    return f'<path class="mh-pl-wire" d="{d}"/>'


def _pulse(d: str, direction: str, delay: float, dur: float = 3.0) -> str:
    return (
        f'<path class="mh-pl-pulse mh-pl-pulse--{direction}" d="{d}" '
        f'pathLength="100" style="animation-delay:{delay:.2f}s;'
        f'animation-duration:{dur:.2f}s"/>'
    )


def _dot(x: float, y: float, kind: str, delay: float) -> str:
    return (
        f'<circle class="mh-pl-dot mh-pl-dot--{kind}" cx="{x:.1f}" cy="{y:.1f}" '
        f'r="3" style="animation-delay:{delay:.2f}s"/>'
    )


def _head(text: str, x: float, y: float) -> str:
    return (
        f'<text class="mh-pl-col-head" x="{x:.1f}" y="{y:.1f}" '
        f'text-anchor="middle">{_x(text)}</text>'
    )


# The canonical full-pipeline phrase — the fallback when a tile hasn't authored
# its own engine process line (the per-tile guard test requires surfaced tiles
# to author one, so each graphic's centre is specific to that tile's function).
_CANONICAL_ENGINE_PROCESS = "detect · rank · brand · generate"


def _engine(cx: float, cy: float, w: float, h: float, process: str) -> str:
    x0, y0 = cx - w / 2, cy - h / 2
    # Icon / title / sub are one optically-centred stack (matches the tidied
    # home-page engine block, PR #782): spark caps the wordmark with a tight
    # gap, the title is the heaviest element, the sub trails one line below.
    return (
        '<g class="mh-pl-engine">'
        f'<rect class="mh-pl-engine-bg" x="{x0:.1f}" y="{y0:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" rx="16"/>'
        + _icon(_ICON_SPARK, cx, cy - 23, 26, "mh-pl-ico mh-pl-ico--engine")
        + f'<text class="mh-pl-engine-title" x="{cx:.1f}" y="{cy + 15:.1f}" '
        'text-anchor="middle">THE ENGINE</text>'
        + f'<text class="mh-pl-engine-sub" x="{cx:.1f}" y="{cy + 34:.1f}" '
        f'text-anchor="middle">{_x(process)}</text>' + "</g>"
    )


def _chip_h(x0: float, yc: float, w: float, h: float, icon: str, label: str, kind: str) -> str:
    y0 = yc - h / 2
    return (
        f'<g class="mh-pl-chip mh-pl-chip--{kind}">'
        f'<rect class="mh-pl-chip-bg" x="{x0:.1f}" y="{y0:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" rx="12"/>'
        + _icon(icon, x0 + 32, yc, 26, f"mh-pl-ico mh-pl-ico--{kind}")
        + f'<text class="mh-pl-chip-label" x="{x0 + 56:.1f}" y="{yc:.1f}" '
        f'dominant-baseline="central">{_x(label)}</text>' + "</g>"
    )


def _chip_v(cx: float, yc: float, w: float, h: float, icon: str, label: str, kind: str) -> str:
    x0, y0 = cx - w / 2, yc - h / 2
    return (
        f'<g class="mh-pl-chip mh-pl-chip--{kind}">'
        f'<rect class="mh-pl-chip-bg" x="{x0:.1f}" y="{y0:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" rx="12"/>'
        + _icon(icon, cx, y0 + 28, 24, f"mh-pl-ico mh-pl-ico--{kind}")
        + f'<text class="mh-pl-chip-label mh-pl-chip-label--v" x="{cx:.1f}" '
        f'y="{y0 + 64:.1f}" text-anchor="middle">{_x(label)}</text>' + "</g>"
    )


def _svg_shell(orient: str, w: int, h: int, body: str) -> str:
    """Wrap diagram ``body`` in an aria-hidden, responsive SVG. The ``h``/``v``
    class suffix reuses the landing diagram's responsive show/hide CSS; the
    in-SVG ``<pattern>`` id is namespaced (``mh-ci-grid-*``) so it can never
    collide with the home page's grid."""
    return (
        f'<svg class="mh-pl-svg mh-pl-svg--{orient}" viewBox="0 0 {w} {h}" '
        'preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<defs><pattern id="mh-ci-grid-{orient}" width="40" height="40" '
        'patternUnits="userSpaceOnUse">'
        '<path class="mh-pl-grid" d="M40 0H0V40"/></pattern></defs>'
        f"{body}</svg>"
    )


def _spread(n: int, center: float, spacing: float) -> list[float]:
    """``n`` positions evenly spaced and centred on ``center``."""
    if n <= 0:
        return []
    return [center + (i - (n - 1) / 2.0) * spacing for i in range(n)]


# --------------------------------------------------------------------------- #
# Diagram geometry — variable input/output counts (the home page is fixed at 3).
# --------------------------------------------------------------------------- #
def _svg_horizontal(
    inputs: list[tuple[str, str]], outputs: list[tuple[str, str]], process: str
) -> str:
    W = 1040
    chip_w, chip_h = 196, 66
    read_x0, read_edge = 28, 224
    write_x0 = write_edge = 812
    eng_cx, eng_w = 520, 244  # widened (PR #782) so the process line breathes
    n_in, n_out = len(inputs), len(outputs)
    n_max = max(n_in, n_out, 1)
    if n_max <= 3:
        H, eng_cy, row_sp = 430, 230, 134
    elif n_max == 4:
        H, eng_cy, row_sp = 556, 290, 122
    else:
        row_sp = 108
        eng_cy = 70 + chip_h / 2 + (n_max - 1) * row_sp / 2.0
        H = int(round(2 * eng_cy))
    # Ports fan ±40 into the engine (matches the home-page diagram), and the box
    # is trimmed to 136 for ≤3 nodes (PR #782), growing only when more ports
    # need the room. Wire control points eased 96→80 for cleaner S-curves.
    port_sp = min(row_sp, 40)
    cp = 80
    eng_h = max(136, int((n_max - 1) * port_sp + 44))
    eng_left, eng_right = eng_cx - eng_w / 2, eng_cx + eng_w / 2

    wires: list[str] = []
    pulses: list[str] = []
    dots: list[str] = []
    chips: list[str] = []

    for i, ((label, icon), ry, py) in enumerate(
        zip(inputs, _spread(n_in, eng_cy, row_sp), _spread(n_in, eng_cy, port_sp))
    ):
        d = (
            f"M {read_edge} {ry:.1f} C {read_edge + cp} {ry:.1f}, "
            f"{eng_left - cp:.1f} {py:.1f}, {eng_left:.1f} {py:.1f}"
        )
        wires.append(_wire(d))
        pulses.append(_pulse(d, "in", delay=i * 0.5))
        dots.append(_dot(read_edge, ry, "read", delay=i * 0.5))
        dots.append(_dot(eng_left, py, "engine", delay=i * 0.5 + 0.4))
        chips.append(_chip_h(read_x0, ry, chip_w, chip_h, icon, label, "read"))

    for i, ((label, icon), wy, py) in enumerate(
        zip(outputs, _spread(n_out, eng_cy, row_sp), _spread(n_out, eng_cy, port_sp))
    ):
        d = (
            f"M {eng_right:.1f} {py:.1f} C {eng_right + cp:.1f} {py:.1f}, "
            f"{write_edge - cp} {wy:.1f}, {write_edge} {wy:.1f}"
        )
        wires.append(_wire(d))
        pulses.append(_pulse(d, "out", delay=i * 0.5 + 1.4))
        dots.append(_dot(eng_right, py, "engine", delay=i * 0.5 + 1.0))
        dots.append(_dot(write_edge, wy, "write", delay=i * 0.5 + 1.8))
        chips.append(_chip_h(write_x0, wy, chip_w, chip_h, icon, label, "write"))

    heads = [
        _head("What you give", read_x0 + chip_w / 2, 40),
        _head("What you get", write_x0 + chip_w / 2, 40),
    ]
    body = (
        f'<rect class="mh-pl-grid-fill" x="0" y="0" width="{W}" height="{H}" '
        'fill="url(#mh-ci-grid-h)"/>'
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
        + _engine(eng_cx, eng_cy, eng_w, eng_h, process)
        + "</g>"
    )
    return _svg_shell("h", W, H, body)


def _svg_vertical(
    inputs: list[tuple[str, str]], outputs: list[tuple[str, str]], process: str
) -> str:
    W, H = 460, 760
    chip_w, chip_h = 132, 84
    n_in, n_out = len(inputs), len(outputs)
    n_max = max(n_in, n_out, 1)
    col_sp = 150 if n_max <= 3 else (104 if n_max == 4 else 86)
    port_sp = min(col_sp, 40)
    read_yc, write_yc = 78, 700
    read_edge = read_yc + chip_h / 2
    write_edge = write_yc - chip_h / 2
    # Wider + trimmed engine box to match the tidied home-page diagram (PR #782).
    eng_cx, eng_cy, eng_w, eng_h = 230, 400, 244, 136
    eng_top, eng_bot = eng_cy - eng_h / 2, eng_cy + eng_h / 2

    wires: list[str] = []
    pulses: list[str] = []
    dots: list[str] = []
    chips: list[str] = []

    for i, ((label, icon), cx, px) in enumerate(
        zip(inputs, _spread(n_in, eng_cx, col_sp), _spread(n_in, eng_cx, port_sp))
    ):
        d = (
            f"M {cx:.1f} {read_edge} C {cx:.1f} {read_edge + 110}, "
            f"{px:.1f} {eng_top - 95}, {px:.1f} {eng_top}"
        )
        wires.append(_wire(d))
        pulses.append(_pulse(d, "in", delay=i * 0.5))
        dots.append(_dot(cx, read_edge, "read", delay=i * 0.5))
        dots.append(_dot(px, eng_top, "engine", delay=i * 0.5 + 0.4))
        chips.append(_chip_v(cx, read_yc, chip_w, chip_h, icon, label, "read"))

    for i, ((label, icon), cx, px) in enumerate(
        zip(outputs, _spread(n_out, eng_cx, col_sp), _spread(n_out, eng_cx, port_sp))
    ):
        d = (
            f"M {px:.1f} {eng_bot} C {px:.1f} {eng_bot + 100}, "
            f"{cx:.1f} {write_edge - 100}, {cx:.1f} {write_edge}"
        )
        wires.append(_wire(d))
        pulses.append(_pulse(d, "out", delay=i * 0.5 + 1.4))
        dots.append(_dot(px, eng_bot, "engine", delay=i * 0.5 + 1.0))
        dots.append(_dot(cx, write_edge, "write", delay=i * 0.5 + 1.8))
        chips.append(_chip_v(cx, write_yc, chip_w, chip_h, icon, label, "write"))

    heads = [_head("What you give", W / 2, 22), _head("What you get", W / 2, 752)]
    body = (
        f'<rect class="mh-pl-grid-fill" x="0" y="0" width="{W}" height="{H}" '
        'fill="url(#mh-ci-grid-v)"/>'
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
        + _engine(eng_cx, eng_cy, eng_w, eng_h, process)
        + "</g>"
    )
    return _svg_shell("v", W, H, body)


# --------------------------------------------------------------------------- #
# Default derivation + public renderer
# --------------------------------------------------------------------------- #
def _resolved_hiw(meta: ContentTypeMeta) -> HowItWorks:
    """The heading's authored :class:`HowItWorks`, or a graceful default derived
    from its title/description so a brand-new heading still gets a coherent
    first slide with zero authoring."""
    if meta.how_it_works is not None:
        return meta.how_it_works
    return HowItWorks(
        tagline=meta.description,
        inputs=(("Your brief", "note"),),
        steps=(
            f"Give MediaHub what it needs to make a {meta.title.lower()}.",
            "The engine works out what matters, ranks it, applies your brand "
            "and writes the content.",
            "Review, edit, approve and export — nothing posts without you.",
        ),
    )


def _outputs_for(formats: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Map presentation format names to (label, glyph) chips for the diagram and
    (label, dims) pairs for the honest meta strip."""
    chips: list[tuple[str, str]] = []
    dims: list[tuple[str, str]] = []
    for fmt in formats or ["Caption"]:
        label, glyph_key, dim = _OUTPUT_META.get(fmt.lower(), (fmt, "note", ""))
        chips.append((label, _glyph(glyph_key)))
        dims.append((label, dim))
    return chips, dims


def _intro_slide(
    *,
    title: str,
    tagline: str,
    inputs: list[tuple[str, str]],
    outputs: list[tuple[str, str]],
    process: str,
    steps: tuple[str, ...],
    meta_chips_html: str,
    a11y: str,
    start_url: str,
    start_label: str,
    back_url: str,
) -> str:
    """The shared "how it works" first-slide markup: hero header → give/engine/get
    circuit → numbered steps → action row. ``inputs``/``outputs`` are
    ``(label, glyph_markup)`` pairs; ``process`` is the engine node's per-tile
    process line. Deterministic (no randomness / no I/O)."""
    steps_html = "".join(
        f'<li class="mh-ci-step"><span class="mh-ci-step-num">{i}</span>'
        f'<span class="mh-ci-step-body">{_x(step)}</span></li>'
        for i, step in enumerate(steps, 1)
    )
    return (
        '<section class="mh-hero mh-ci-head" data-lane="03" '
        'style="padding-top:var(--sp-8);padding-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">How it works</span>'
        f"<h1>{_x(title)}</h1>"
        f'<p class="lede">{_x(tagline)}</p>'
        "</section>"
        '<div class="mh-pl-stage mh-ci-stage">'
        f'<p class="mh-visually-hidden">{_x(a11y)}</p>'
        f"{_svg_horizontal(inputs, outputs, process)}{_svg_vertical(inputs, outputs, process)}"
        "</div>"
        f'<ol class="mh-ci-steps">{steps_html}</ol>'
        '<div class="mh-ci-actions">'
        f'<a class="btn mh-ci-start" href="{start_url}">{_x(start_label)} &rarr;</a>'
        f'<a class="btn secondary" href="{back_url}">&larr; Back to Create</a>'
        f'<span class="mh-ci-meta">{meta_chips_html}</span>'
        "</div>"
    )


def render_content_intro(
    meta: ContentTypeMeta,
    *,
    formats: list[str],
    effort: str,
    start_url: str,
    back_url: str,
) -> str:
    """Full ``<body>`` markup for a content-type tile's "how it works" first
    slide. Pass the result straight to ``_layout``."""
    hiw = _resolved_hiw(meta)
    inputs = [(label, _glyph(key)) for label, key in hiw.inputs]
    out_chips, out_dims = _outputs_for(formats)
    process = hiw.engine_process or _CANONICAL_ENGINE_PROCESS

    in_labels = ", ".join(label for label, _ in hiw.inputs)
    out_labels = ", ".join(label for label, _ in out_dims)
    a11y = (
        f"How {meta.title} works. You give: {in_labels}. The MediaHub engine "
        f"({process.replace('·', 'then')}) turns that into your content. You get: "
        f"{out_labels} — to review and approve. Nothing leaves without your approval."
    )

    meta_chips = "".join(
        f'<span class="mh-ci-chip">{_x(label)}'
        + (f' <span class="mh-ci-chip-dim">{_x(dim)}</span>' if dim else "")
        + "</span>"
        for label, dim in out_dims
    )
    if effort:
        meta_chips += f'<span class="mh-ci-chip mh-ci-chip--time">{_x(effort)}</span>'

    return _intro_slide(
        title=meta.title,
        tagline=hiw.tagline,
        inputs=inputs,
        outputs=out_chips,
        process=process,
        steps=hiw.steps,
        meta_chips_html=meta_chips,
        a11y=a11y,
        start_url=start_url,
        start_label=f"Start {meta.title}",
        back_url=back_url,
    )


# --------------------------------------------------------------------------- #
# Plan — the strategic "what should we make?" entry. It is NOT a content-type
# tile (its output is a ranked, explainable plan, not a media format), so it
# carries its own intro spec here rather than in the ContentType REGISTRY, and
# its "Start" opens the planner (/plan) instead of a generator.
# --------------------------------------------------------------------------- #
_PLAN_INPUTS: tuple[tuple[str, str], ...] = (
    ("What's coming up", "words"),
    ("Your goals", "trophy"),
    ("Club history", "meet"),
)
_PLAN_OUTPUTS: tuple[tuple[str, str], ...] = (
    ("Ranked ideas", "pb"),
    ("The reasoning", "note"),
    ("Top pick to make", "graphic"),
)
_PLAN_STEPS: tuple[str, ...] = (
    "Describe what's coming up in your own words and set your goals.",
    "The engine ranks what to post next from your results, the calendar and your "
    "goals — with the reasoning shown for every idea.",
    "Jump straight into making the top idea, or work down the ranked list.",
)
_PLAN_TAGLINE = "Not sure what to post? Get a ranked, explainable plan of what to make next."
# Plan recommends rather than generates — its engine line is its own.
_PLAN_ENGINE_PROCESS = "ingest · detect · rank · recommend"


def render_plan_intro(*, start_url: str, back_url: str) -> str:
    """Full ``<body>`` markup for the Plan "how it works" first slide. Same visual
    language as the tiles; its Start opens the planner."""
    inputs = [(label, _glyph(key)) for label, key in _PLAN_INPUTS]
    outputs = [(label, _glyph(key)) for label, key in _PLAN_OUTPUTS]
    a11y = (
        "How Plan works. You give: what's coming up, your goals and your club "
        "history. The MediaHub engine ranks what to post next, with the reasoning "
        "shown for every idea. You get a ranked, explainable content plan — and can "
        "jump straight into making the top pick. Nothing posts without your approval."
    )
    meta_chips = (
        '<span class="mh-ci-chip">Ranked plan</span>'
        '<span class="mh-ci-chip">Reasoning shown</span>'
        '<span class="mh-ci-chip mh-ci-chip--time">~ 30s</span>'
    )
    return _intro_slide(
        title="Plan",
        tagline=_PLAN_TAGLINE,
        inputs=inputs,
        outputs=outputs,
        process=_PLAN_ENGINE_PROCESS,
        steps=_PLAN_STEPS,
        meta_chips_html=meta_chips,
        a11y=a11y,
        start_url=start_url,
        start_label="Open Plan",
        back_url=back_url,
    )


# --------------------------------------------------------------------------- #
# CSS — appended to BASE_CSS right after the pipeline-diagram layer (and before
# the responsive guardrails), so it reuses every .mh-pl-* token the diagram set.
# --------------------------------------------------------------------------- #
CONTENT_INTRO_CSS = """
/* ===================================================================== */
/* Create -> heading "how it works" first slide (/make/<type>)           */
/* The circuit diagram reuses the landing diagram's .mh-pl-* classes; the */
/* rules below only style the steps strip, the action row and the meta   */
/* chips that sit beneath it.                                             */
/* ===================================================================== */
.mh-ci-head { margin-bottom: var(--sp-5); }
/* The how-it-works diagram is the *club's* surface, so its lit traces take the
   active profile's brand colour — overriding the home-page diagram's pinned
   lane-yellow (PR #782, scoped to .mh-pl-stage for the unbranded marketing
   home). It uses the SAME token the rest of the site themes from — --lane ←
   --mh-primary, set per-profile by the <style id="mh-theme-seed"> injection — so
   when a club changes its colours the engine recolours automatically, exactly
   like every other accent on the site. No bespoke per-request colour: one
   mechanism, no drift. (.mh-ci-stage is the same element as .mh-pl-stage and
   comes later in the cascade, so this wins.) */
.mh-ci-stage {
  margin-bottom: var(--sp-6);
  --lane: var(--mh-primary);
  --lane-glow: color-mix(in oklab, var(--mh-primary) 42%, transparent);
}
/* The engine box glow is a hard-yellow drop-shadow in the landing-diagram CSS
   (PR #782 bakes the literal for the unbranded home). On the club's surface,
   recolour it to the brand via --lane-glow — otherwise a non-yellow club gets a
   brand-coloured stroke ringed by a stale yellow halo. Scoped + higher
   specificity than .mh-pl-engine-bg, so the home page is untouched. */
.mh-ci-stage .mh-pl-engine-bg {
  filter: drop-shadow(0 0 10px var(--lane-glow));
  animation: mh-ci-breathe 3.4s ease-in-out infinite;
}
@keyframes mh-ci-breathe {
  0%, 100% { filter: drop-shadow(0 0 10px var(--lane-glow)); }
  50%      { filter: drop-shadow(0 0 20px var(--lane-glow)); }
}

.mh-ci-steps {
  list-style: none;
  margin: 0 0 var(--sp-6);
  padding: 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-4);
}
.mh-ci-step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: var(--sp-4);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: var(--surface);
}
.mh-ci-step-num {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  color: var(--bg);
  background: var(--lane);
}
.mh-ci-step-body { color: var(--ink-dim); font-size: 14px; line-height: 1.5; }

.mh-ci-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  margin-bottom: var(--sp-6);
}
.mh-ci-start { font-size: 15px; }
.mh-ci-meta { display: inline-flex; flex-wrap: wrap; gap: 8px; margin-left: auto; }
.mh-ci-chip {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.03em;
  color: var(--ink);
  padding: 4px 9px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: var(--surface);
}
.mh-ci-chip-dim { color: var(--ink-muted); }
.mh-ci-chip--time { color: var(--ink-dim); }

@media (max-width: 720px) {
  .mh-ci-steps { grid-template-columns: 1fr; }
  .mh-ci-meta { margin-left: 0; width: 100%; }
}

/* The predominant "Plan" entry tile at the top of the Create page. Sits above
   the content-type grid and is lane-accented + lifted so it reads as the
   strategic starting point ("what should we make?"). Links to Plan's own
   how-it-works first slide. */
.mh-plan-tile {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: var(--sp-5);
  padding: 22px 24px;
  border: 1px solid var(--lane);
  border-radius: 14px;
  background:
    radial-gradient(130% 170% at 0% 0%, color-mix(in oklab, var(--lane) 10%, transparent), transparent 60%),
    var(--surface);
  box-shadow: 0 0 0 1px color-mix(in oklab, var(--lane) 8%, transparent), 0 10px 30px rgba(0,0,0,0.25);
  text-decoration: none;
  color: var(--ink);
  transition: transform .15s ease, box-shadow .15s ease;
}
.mh-plan-tile:hover {
  transform: translateY(-2px);
  box-shadow: 0 0 0 1px color-mix(in oklab, var(--lane) 20%, transparent), 0 16px 40px rgba(0,0,0,0.34);
}
.mh-plan-tile-icon {
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: color-mix(in oklab, var(--lane) 10%, transparent);
  color: var(--lane);
  border: 1px solid color-mix(in oklab, var(--lane) 30%, transparent);
}
.mh-plan-tile-body {
  flex: 1;
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.mh-plan-tile-eyebrow {
  font-family: var(--font-mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--lane);
}
.mh-plan-tile-title {
  font-size: 20px;
  font-weight: 800;
  margin: 0;
  line-height: 1.15;
}
.mh-plan-tile-title .editorial { color: var(--lane); }
.mh-plan-tile-desc {
  margin: 0;
  font-size: 13px;
  color: var(--ink-dim);
  max-width: 64ch;
  line-height: 1.5;
}
.mh-plan-tile-cta {
  flex: 0 0 auto;
  font-weight: 700;
  border: 1px solid var(--lane);
  border-radius: 999px;
  padding: 10px 18px;
  font-size: 13px;
  color: var(--lane);
  white-space: nowrap;
}
@media (max-width: 720px) {
  .mh-plan-tile { padding: 18px; }
  .mh-plan-tile-cta { width: 100%; text-align: center; }
}
"""
