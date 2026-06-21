"""First-party sample output graphics for the landing "What the engine does" showcase.

These are deterministic, self-contained **inline SVG** renditions of the
formats MediaHub actually produces — a story card, a meet reel, a feed
graphic, the detected-&-ranked intelligence read-out, the brand-kit
application, and the moment taxonomy. They are *template fake-real* samples:
the data is a fixed demo meet (Riverside SC), but the composition, type
registers, brand-role discipline and honest data weight mirror the real
Playwright/Chromium still renderer (``graphic_renderer/render.py``) and the
Remotion reel — so a first-time visitor sees genuine output, not prose
describing it.

Why inline SVG (not the heavy PNG/MP4 renderer, and not an ``<img>`` chip):

* **Inline** SVG lives in the page DOM, so it inherits the live brand tokens
  (``--lane``, ``--medal``, ``--ink``, …) and the self-hosted brand fonts
  (``--font-display`` Big Shoulders, ``--font-mono`` JetBrains Mono). An
  ``<img>``-loaded SVG (the small ``/static/samples`` chips) cannot — which is
  why those fall back to web-safe fonts. These showcase cards are far more
  faithful as a result, and re-skin automatically if the palette changes.
* **No external fetch** — pure vector, no remote ``<image>``, webfont
  ``@import`` or CDN; honours the same no-external-fetch rule the fonts do.
* **Cheap** — a few KB each, crisp at any size, no Chromium on the request
  path (the real renderer's heavy artefacts don't belong as marketing chrome).

Craft rules applied (see ``.claude/skills/graphic-craft``): three depth layers
(tinted ground + scoreboard substrate → facts → accents), two focal points,
edge-anchored hero text, medal-gold reserved exclusively for athlete
achievements, lane-yellow for chrome, and any size-encoding element kept
truthfully proportional (the ranked-moment score bars) or visibly symbolic
(the podium). Everything here is static — no user input — so nothing needs
escaping.

Guarded by ``tests/test_engine_showcase.py``.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Shared, document-safe style block.
# Only ``mhg-*`` prefixed *class* selectors are used (never a bare element
# selector), so an inline SVG <style> — which is document-global — can never
# restyle anything else on the page. Each rule pulls a live brand token with a
# self-host fallback, so a card is on-brand inline and still legible if ever
# viewed standalone.
# --------------------------------------------------------------------------- #
_STYLE = (
    "<style>"
    ".mhg-d{font-family:var(--font-display,'Impact','Oswald',sans-serif);font-weight:800}"
    ".mhg-m{font-family:var(--font-mono,ui-monospace,'SF Mono',Menlo,monospace);font-weight:600}"
    ".mhg-b{font-family:var(--font-body,-apple-system,'Segoe UI',sans-serif);font-weight:600}"
    ".mhg-i{fill:var(--ink,#F5F2E8)}"
    ".mhg-dim{fill:var(--ink-dim,#B6B2A6)}"
    ".mhg-ft{fill:var(--ink-faint,#62604F)}"
    ".mhg-l{fill:var(--lane,#D4FF3A)}"
    ".mhg-md{fill:var(--medal,#F4D58D)}"
    ".mhg-mi{fill:var(--medal-ink,#2B1F00)}"
    ".mhg-li{fill:var(--lane-ink,#0A0B11)}"
    ".mhg-nf{fill:var(--info,#4DA3FF)}"
    "</style>"
)


def _open(w: int, h: int, title: str, cls: str = "") -> str:
    """Open a viewBox-sized, accessible, fit-to-container inline SVG."""
    klass = f' class="{cls}"' if cls else ""
    return (
        f'<svg{klass} viewBox="0 0 {w} {h}" role="img" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg" aria-label="{title}">'
        f"<title>{title}</title>{_STYLE}"
    )


def _grid(w: int, h: int, step: int = 40, op: float = 0.05) -> str:
    """Faint scoreboard-grid substrate — the depth layer under the facts."""
    lines = []
    x = step
    while x < w:
        lines.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}"/>')
        x += step
    y = step
    while y < h:
        lines.append(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}"/>')
        y += step
    return (
        f'<g class="mhg-i" stroke="currentColor" fill="none" '
        f'stroke-width="1" style="opacity:{op}">' + "".join(lines) + "</g>"
    )


def _corner_marks(w: int, h: int, m: int = 14, length: int = 9) -> str:
    """Registration corner ticks — a produced, art-directed detail."""
    return (
        f'<g class="mhg-ft" stroke="currentColor" stroke-width="1.4" '
        f'fill="none" style="opacity:0.5">'
        f'<path d="M{m} {m+length} V{m} H{m+length}"/>'
        f'<path d="M{w-m-length} {m} H{w-m} V{m+length}"/>'
        f'<path d="M{m} {h-m-length} V{h-m} H{m+length}"/>'
        f'<path d="M{w-m-length} {h-m} H{w-m} V{h-m-length}"/>'
        "</g>"
    )


# --------------------------------------------------------------------------- #
# 1. Story card — 9:16, the `big_number_dominant` archetype.
#    Hero numeral carries the card; PB delta on a medal chip (the only gold);
#    name edge-anchored; ghost achievement word + grid for depth.
# --------------------------------------------------------------------------- #
def story_card_svg() -> str:
    w, h = 360, 640
    return (
        _open(w, h, "Story card — Tom Davies personal best, 100m freestyle 52.41")
        + f'<rect width="{w}" height="{h}" fill="var(--bg,#0A0B11)"/>'
        + _grid(w, h)
        # lane-glow ground lift (radial, no banding)
        + '<defs><radialGradient id="mhg-storyglow" cx="0.5" cy="0.30" r="0.62">'
        '<stop offset="0" stop-color="var(--lane,#D4FF3A)" stop-opacity="0.16"/>'
        '<stop offset="1" stop-color="var(--lane,#D4FF3A)" stop-opacity="0"/>'
        "</radialGradient></defs>"
        + f'<rect width="{w}" height="{h}" fill="url(#mhg-storyglow)"/>'
        # brand top rule
        + f'<rect width="{w}" height="6" class="mhg-l" fill="currentColor"/>'
        # ghost achievement word (background accent)
        + '<text x="-6" y="430" class="mhg-d mhg-i" style="opacity:0.05" '
        'font-size="320" letter-spacing="-12">PB</text>'
        # eyebrow
        + '<rect x="28" y="48" width="10" height="10" class="mhg-l" fill="currentColor"/>'
        + '<text x="46" y="57" class="mhg-m mhg-l" font-size="13" '
        'letter-spacing="2">NEW PB &#183; 100M FREESTYLE</text>'
        # athlete name (display, edge-anchored, two lines)
         + '<text x="26" y="150" class="mhg-d mhg-i" font-size="74" '
        'letter-spacing="-2">TOM</text>'
        + '<text x="26" y="222" class="mhg-d mhg-i" font-size="74" '
        'letter-spacing="-2">DAVIES</text>'
        + '<rect x="28" y="244" width="56" height="4" class="mhg-l" fill="currentColor"/>'
        # hero time — the dominant numeral (fitted to the 360-wide canvas)
        + '<text x="26" y="416" class="mhg-m mhg-i" font-size="102" '
        'font-weight="700" letter-spacing="-3">52.41</text>'
        + '<text x="30" y="452" class="mhg-m mhg-dim" font-size="15" '
        'letter-spacing="3">FINAL &#183; LONG COURSE</text>'
        # PB delta — the achievement, on the medal chip (only gold on the card)
         + '<rect x="28" y="486" width="150" height="46" rx="8" '
        'fill="var(--medal,#F4D58D)"/>'
        + '<path d="M44 502 l8 13 8 -13 z" class="mhg-mi" fill="currentColor"/>'
        + '<text x="68" y="516" class="mhg-d mhg-mi" font-size="26">&#8722;0.74s</text>'
        + '<text x="68" y="527" class="mhg-m mhg-mi" font-size="9" '
        'style="opacity:0.8" letter-spacing="1.5">PERSONAL BEST</text>'
        + '<text x="192" y="503" class="mhg-m mhg-dim" font-size="12">PREV</text>'
        + '<text x="192" y="521" class="mhg-m mhg-i" font-size="20" '
        'font-weight="700">53.15</text>'
        # footer lockup — wordmark + lane + grounded confidence
         + f'<line x1="28" y1="576" x2="{w-28}" y2="576" class="mhg-i" '
        'stroke="currentColor" stroke-width="1" style="opacity:0.14"/>'
        + '<rect x="28" y="592" width="26" height="26" rx="5" '
        'fill="var(--lane,#D4FF3A)"/>'
        + '<text x="41" y="610" text-anchor="middle" class="mhg-d mhg-li" '
        'font-size="14">R</text>' + '<text x="64" y="604" class="mhg-m mhg-i" font-size="13" '
        'letter-spacing="1">RIVERSIDE SC</text>'
        + '<text x="64" y="617" class="mhg-m mhg-ft" font-size="10" '
        'letter-spacing="1.5">SOURCE-GROUNDED &#183; 0.96</text>'
        + f'<text x="{w-26}" y="614" text-anchor="end" class="mhg-d mhg-l" '
        'font-size="40" style="opacity:0.9">04</text>' + _corner_marks(w, h) + "</svg>"
    )


# --------------------------------------------------------------------------- #
# 2. Meet reel — 9:16 poster frame for the `reel_cover` → beats → outro cut.
#    Reads as video: play affordance + a cover/beats/outro timeline + timecode.
# --------------------------------------------------------------------------- #
def reel_poster_svg() -> str:
    w, h = 360, 640
    # progress timeline: cover + 5 card beats + outro; 3 beats "played"
    beats = ""
    seg_w, gap, x0, y = 40, 8, 28, 560
    played = 3
    for i in range(7):
        x = x0 + i * (seg_w + gap)
        lit = i <= played
        cls = "mhg-l" if lit else "mhg-dim"
        op = "" if lit else ' style="opacity:0.3"'
        beats += (
            f'<rect x="{x}" y="{y}" width="{seg_w}" height="6" rx="3" '
            f'class="{cls}" fill="currentColor"{op}/>'
        )
    return (
        _open(w, h, "Meet reel — meet-day highlights, 15-second branded cut")
        + '<defs><linearGradient id="mhg-reelbg" x1="0" y1="0" x2="0.7" y2="1">'
        '<stop offset="0" stop-color="var(--surface,#14171F)"/>'
        '<stop offset="1" stop-color="var(--bg-deep,#06070C)"/>'
        "</linearGradient>"
        '<radialGradient id="mhg-reelglow" cx="0.5" cy="0.40" r="0.5">'
        '<stop offset="0" stop-color="var(--lane,#D4FF3A)" stop-opacity="0.22"/>'
        '<stop offset="1" stop-color="var(--lane,#D4FF3A)" stop-opacity="0"/>'
        "</radialGradient></defs>"
        + f'<rect width="{w}" height="{h}" fill="url(#mhg-reelbg)"/>'
        + f'<rect width="{w}" height="{h}" fill="url(#mhg-reelglow)"/>'
        + _grid(w, h, step=48, op=0.04)
        # format chips
        + '<rect x="28" y="40" width="62" height="26" rx="13" fill="none" '
        'stroke="var(--lane,#D4FF3A)" stroke-width="1.5" style="opacity:0.8"/>'
        + '<text x="59" y="57" text-anchor="middle" class="mhg-m mhg-l" '
        'font-size="13" letter-spacing="2">REEL</text>'
        + f'<text x="{w-28}" y="58" text-anchor="end" class="mhg-m mhg-i" '
        'font-size="15" style="font-variant-numeric:tabular-nums">0:15</text>'
        # play affordance — the video signifier
         + '<circle cx="180" cy="262" r="62" class="mhg-l" fill="currentColor" '
        'style="opacity:0.12"/>'
        + '<circle class="mhg-reel-pulse" cx="180" cy="262" r="48" fill="none" '
        'stroke="var(--lane,#D4FF3A)" stroke-width="2" style="opacity:0.45"/>'
        + '<circle cx="180" cy="262" r="42" class="mhg-l" fill="currentColor"/>'
        + '<path d="M168 240 L168 284 L206 262 Z" class="mhg-li" fill="currentColor"/>'
        # headline + sub
        + '<text x="28" y="438" class="mhg-d mhg-i" font-size="56" '
        'letter-spacing="-2">MEET-DAY</text>'
        + '<text x="28" y="494" class="mhg-d mhg-i" font-size="56" '
        'letter-spacing="-2">HIGHLIGHTS</text>'
        + '<text x="30" y="524" class="mhg-m mhg-dim" font-size="14" '
        'letter-spacing="2">5 SWIMMERS &#183; 3 PBS &#183; 1 RELAY</text>'
        # timeline (cover / beats / outro)
         + beats + '<text x="28" y="600" class="mhg-m mhg-ft" font-size="10" '
        'letter-spacing="2">COVER &#183; RANKED BEATS &#183; CLUB OUTRO</text>'
        # outro wordmark
         + '<rect x="28" y="610" width="22" height="22" rx="5" '
        'fill="var(--lane,#D4FF3A)"/>'
        + '<text x="39" y="626" text-anchor="middle" class="mhg-d mhg-li" '
        'font-size="12">R</text>' + '<text x="58" y="626" class="mhg-m mhg-i" font-size="12" '
        'letter-spacing="1">RIVERSIDE SC</text>' + "</svg>"
    )


# --------------------------------------------------------------------------- #
# 3. Feed graphic — 4:5, top-three finals podium.
#    Medal tints encode rank (gold/silver/bronze = achievement), the podium is
#    a recognised symbol; real names + times sit under each step.
# --------------------------------------------------------------------------- #
def feed_graphic_svg() -> str:
    w, h = 360, 450
    base = 350  # podium baseline y
    # (x, bar-height, rank, fill, name, time)
    steps = [
        (40, 96, "2", "#E6E8ED", "A. NOLAN", "53.18"),  # silver
        (140, 150, "1", "var(--medal,#F4D58D)", "T. DAVIES", "52.41"),  # gold
        (240, 64, "3", "var(--medal-deep,#C9A04B)", "R. KHAN", "54.02"),  # bronze
    ]
    bars = ""
    bw = 80
    for x, bh, rank, fill, name, t in steps:
        top = base - bh
        rank_ink = "mhg-li" if rank == "1" else "mhg-mi"
        bars += (
            f'<rect x="{x}" y="{top}" width="{bw}" height="{bh}" rx="3" fill="{fill}"/>'
            f'<text x="{x + bw // 2}" y="{top + 34}" text-anchor="middle" '
            f'class="mhg-d {rank_ink}" font-size="30">{rank}</text>'
            f'<text x="{x + bw // 2}" y="{base + 22}" text-anchor="middle" '
            f'class="mhg-d mhg-i" font-size="15">{name}</text>'
            f'<text x="{x + bw // 2}" y="{base + 40}" text-anchor="middle" '
            f'class="mhg-m mhg-dim" font-size="13" '
            f'style="font-variant-numeric:tabular-nums">{t}</text>'
        )
    return (
        _open(w, h, "Feed graphic — top three, county finals 100m freestyle")
        + f'<rect width="{w}" height="{h}" fill="var(--bg,#0A0B11)"/>'
        + _grid(w, h)
        + f'<rect width="{w}" height="6" class="mhg-l" fill="currentColor"/>'
        # eyebrow + title
        + '<text x="28" y="50" class="mhg-m mhg-l" font-size="13" '
        'letter-spacing="2">COUNTY FINALS &#183; 100M FREE</text>'
        + '<text x="26" y="104" class="mhg-d mhg-i" font-size="58" '
        'letter-spacing="-2">TOP THREE</text>'
        + '<text x="28" y="134" class="mhg-m mhg-dim" font-size="14" '
        'letter-spacing="2">FRIDAY FINALS &#183; SENIOR</text>'
        + bars
        # baseline + footer
        + f'<line x1="28" y1="{base}" x2="{w-28}" y2="{base}" class="mhg-i" '
        'stroke="currentColor" stroke-width="2" style="opacity:0.20"/>'
        + '<rect x="28" y="416" width="22" height="22" rx="5" '
        'fill="var(--lane,#D4FF3A)"/>'
        + '<text x="39" y="432" text-anchor="middle" class="mhg-d mhg-li" '
        'font-size="12">R</text>' + '<text x="58" y="432" class="mhg-m mhg-i" font-size="12" '
        'letter-spacing="1">RIVERSIDE SC</text>'
        + f'<text x="{w-28}" y="432" text-anchor="end" class="mhg-m mhg-ft" '
        'font-size="11" letter-spacing="1.5">FEED &#183; 1080&#215;1350</text>' + "</svg>"
    )


# --------------------------------------------------------------------------- #
# 4. Detected & ranked — landscape intelligence read-out (the moat).
#    A "12 moments" stat + three ranked rows whose score bars are *truthfully*
#    proportional to the content-worthiness score shown beside them.
# --------------------------------------------------------------------------- #
def detected_ranked_svg() -> str:
    w, h = 380, 230
    # (rank, badge, badge-fill, badge-ink, who, event, score 0..1)
    rows = [
        ("1", "PB", "var(--medal,#F4D58D)", "mhg-mi", "Tom Davies", "100m Free", 0.96),
        ("2", "1ST", "var(--medal,#F4D58D)", "mhg-mi", "W. 4×100 Relay", "Final", 0.91),
        ("3", "NEW", "var(--info,#4DA3FF)", "mhg-li", "Aoife Nolan", "first sub-1:00", 0.88),
    ]
    bar_x, bar_w = 250, 96
    row_h, y0 = 40, 96
    body = ""
    for i, (rank, badge, bf, bink, who, ev, score) in enumerate(rows):
        y = y0 + i * row_h
        fill_w = round(bar_w * score)
        body += (
            f'<text x="28" y="{y+16}" class="mhg-d mhg-ft" font-size="22">{rank}</text>'
            f'<rect x="46" y="{y}" width="40" height="22" rx="5" fill="{bf}"/>'
            f'<text x="66" y="{y+15}" text-anchor="middle" class="mhg-d {bink}" '
            f'font-size="12">{badge}</text>'
            f'<text x="96" y="{y+10}" class="mhg-b mhg-i" font-size="14">{who}</text>'
            f'<text x="96" y="{y+24}" class="mhg-m mhg-dim" font-size="10" '
            f'letter-spacing="0.5">{ev}</text>'
            # score bar — proportional to the real content-worthiness score
            f'<rect x="{bar_x}" y="{y+6}" width="{bar_w}" height="6" rx="3" '
            f'class="mhg-i" fill="currentColor" style="opacity:0.12"/>'
            f'<rect x="{bar_x}" y="{y+6}" width="{fill_w}" height="6" rx="3" '
            f'class="mhg-l" fill="currentColor"/>'
            f'<text x="{bar_x+bar_w+8}" y="{y+13}" class="mhg-m mhg-i" '
            f'font-size="12" style="font-variant-numeric:tabular-nums">{score:.2f}</text>'
        )
    return (
        _open(w, h, "Detected and ranked — 12 moments scored by content-worthiness")
        + f'<rect width="{w}" height="{h}" fill="var(--surface,#14171F)"/>'
        + _grid(w, h, step=38, op=0.04)
        # header
        + '<rect x="28" y="26" width="9" height="9" class="mhg-l" fill="currentColor"/>'
        + '<text x="44" y="35" class="mhg-m mhg-l" font-size="12" '
        'letter-spacing="2">DETECTED &amp; RANKED</text>'
        + f'<text x="{w-28}" y="35" text-anchor="end" class="mhg-m mhg-ft" '
        'font-size="10" letter-spacing="1.5">CONTENT-WORTHINESS</text>'
        # big stat
         + '<text x="26" y="86" class="mhg-d mhg-i" font-size="68" '
        'letter-spacing="-3">12</text>'
        + '<text x="120" y="66" class="mhg-d mhg-i" font-size="20">MOMENTS</text>'
        + '<text x="120" y="84" class="mhg-m mhg-dim" font-size="10" '
        'letter-spacing="1">FROM 42 SWIMS READ</text>'
        # divider above rows
         + f'<line x1="28" y1="84" x2="{w-28}" y2="84" class="mhg-i" '
        'stroke="currentColor" stroke-width="1" style="opacity:0.12"/>'
        + body
        + '<text x="28" y="218" class="mhg-m mhg-ft" font-size="9" '
        'letter-spacing="1.5">5 PBS &#183; 3 MEDALS &#183; 1 CLUB RECORD &#183; EXPLAINABLE</text>'
        + "</svg>"
    )


# --------------------------------------------------------------------------- #
# 5. Brand kit applied — square specimen: monogram, palette, type, lock state.
# --------------------------------------------------------------------------- #
def brand_kit_svg() -> str:
    w, h = 240, 240
    # palette swatches (role, hex label)
    sw = [
        ("var(--lane,#D4FF3A)", "LANE"),
        ("var(--medal,#F4D58D)", "MEDAL"),
        ("var(--info,#4DA3FF)", "INFO"),
        ("var(--ink,#F5F2E8)", "INK"),
    ]
    swatches = ""
    sx, sgap, swid = 28, 12, 39
    for i, (fill, lab) in enumerate(sw):
        x = sx + i * (swid + sgap)
        swatches += (
            f'<rect x="{x}" y="120" width="{swid}" height="34" rx="5" fill="{fill}"/>'
            f'<text x="{x}" y="168" class="mhg-m mhg-ft" font-size="8" '
            f'letter-spacing="1">{lab}</text>'
        )
    return (
        _open(w, h, "Your brand applied — palette, logo, fonts locked onto every card")
        + f'<rect width="{w}" height="{h}" fill="var(--bg,#0A0B11)"/>'
        + _grid(w, h, step=32, op=0.05)
        + '<text x="28" y="38" class="mhg-m mhg-l" font-size="11" '
        'letter-spacing="2">YOUR BRAND</text>'
        # monogram chip
         + '<rect x="28" y="52" width="52" height="52" rx="11" '
        'fill="var(--lane,#D4FF3A)"/>'
        + '<text x="54" y="92" text-anchor="middle" class="mhg-d mhg-li" '
        'font-size="34">RSC</text>'
        + '<text x="92" y="76" class="mhg-d mhg-i" font-size="20">RIVERSIDE</text>'
        + '<text x="92" y="96" class="mhg-m mhg-dim" font-size="11" '
        'letter-spacing="2">SWIM CLUB</text>'
        + swatches
        # type specimen
        + '<text x="28" y="210" class="mhg-d mhg-i" font-size="46">Aa</text>'
        + '<text x="92" y="196" class="mhg-m mhg-dim" font-size="11">'
        "Display &#183; Mono</text>" + '<text x="92" y="212" class="mhg-m mhg-i" font-size="16" '
        'style="font-variant-numeric:tabular-nums">00:52.41</text>'
        # lock state
         + '<rect x="148" y="50" width="64" height="22" rx="11" fill="none" '
        'stroke="var(--lane,#D4FF3A)" stroke-width="1.3" style="opacity:0.7"/>'
        + '<text x="180" y="65" text-anchor="middle" class="mhg-m mhg-l" '
        'font-size="9" letter-spacing="1.5">LOCKED</text>'
        + _corner_marks(w, h, m=12, length=8)
        + "</svg>"
    )


# --------------------------------------------------------------------------- #
# 6. Moments we detect — the taxonomy as a scannable, weighted legend.
# --------------------------------------------------------------------------- #
def moments_svg() -> str:
    w, h = 240, 240
    # (dot-class, label, count)  — medal dot = achievement, lane dot = signal
    items = [
        ("mhg-md", "Personal bests", "5"),
        ("mhg-md", "Medal finishes", "3"),
        ("mhg-l", "Club records", "1"),
        ("mhg-l", "First-time swims", "2"),
        ("mhg-l", "Qualifying times", "4"),
        ("mhg-ft", "Comeback swims", "1"),
    ]
    rows = ""
    y0, rh = 70, 26
    for i, (dot, label, count) in enumerate(items):
        y = y0 + i * rh
        op = "opacity:0.6;" if dot == "mhg-ft" else ""
        muted = f' style="{op}"' if op else ""
        rows += (
            f'<circle cx="34" cy="{y-4}" r="4" class="{dot}" fill="currentColor"{muted}/>'
            f'<text x="48" y="{y}" class="mhg-b mhg-i" font-size="13"{muted}>{label}</text>'
            f'<text x="{w-28}" y="{y}" text-anchor="end" class="mhg-m mhg-dim" '
            f'font-size="13" style="{op}font-variant-numeric:tabular-nums">&#215;{count}</text>'
        )
    return (
        _open(w, h, "Moments we detect — personal bests, medals, records, debuts")
        + f'<rect width="{w}" height="{h}" fill="var(--surface,#14171F)"/>'
        + _grid(w, h, step=32, op=0.04)
        + '<rect x="28" y="30" width="9" height="9" class="mhg-l" fill="currentColor"/>'
        + '<text x="44" y="39" class="mhg-m mhg-l" font-size="12" '
        'letter-spacing="2">WE DETECT</text>'
        + f'<line x1="28" y1="52" x2="{w-28}" y2="52" class="mhg-i" '
        'stroke="currentColor" stroke-width="1" style="opacity:0.12"/>'
        + rows
        + '<text x="28" y="224" class="mhg-m mhg-ft" font-size="9" '
        'letter-spacing="1">RANKED BY CONTENT-WORTHINESS</text>' + "</svg>"
    )


# Order mirrors the showcase grid (story is the 2x2 feature).
SAMPLES = {
    "story": story_card_svg,
    "reel": reel_poster_svg,
    "feed": feed_graphic_svg,
    "ranked": detected_ranked_svg,
    "brand": brand_kit_svg,
    "moments": moments_svg,
}
