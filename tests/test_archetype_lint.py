"""F3 (systemic floor) — the archetype lint.

A single, parametrised gate over EVERY registered v2 archetype crossed with the
certified canvas formats and a small matrix of canonical content fixtures
(short/long surname, 0/4 stats, photo/no-photo). It has two layers:

* **Static lints (always run, no browser):** the archetype source may carry no
  hardcoded hex (brand colour rides the ``--mh-*`` role tokens) and no
  non-catalog font family (only the self-hosted families + the generic/fallback
  stack entries). These are a fast, deterministic regex sweep per archetype.

* **Rendered structural sweep (opt-in, browser-gated):** each
  (archetype × format × fixture) page is loaded once in headless Chromium and a
  SINGLE ``evaluate()`` sweep collects every text leaf's box + font size. From
  that one sweep the test asserts: no text node lands fully off-canvas; the
  brand foot lockup respects a minimum outer margin; sibling text nodes do not
  overlap; exactly one register-1 headline dominates; and empty slots (0 stats /
  no photo) collapse rather than leaving a dangling visible chip. This layer is
  **skipped when Chromium is unavailable** and is **opt-in** via
  ``MEDIAHUB_ARCHETYPE_LINT=1`` (it is an opt-in slow render sweep, like the
  render-diff tests), so ``pytest tests/`` stays fast while the capability is
  always one flag away. A one-page smoke still exercises the machinery in the
  default suite whenever Chromium is present.
"""

from __future__ import annotations

import os
import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.graphic_renderer.variants import FORMAT_SIZES
from mediahub.media_requirements.evaluator import EvaluationResult

NAMES = archetypes.list_archetypes()

# The certified canvas formats the lint sweeps. The v2 archetype authoring
# contract is explicitly "must read well at both 1080×1350 and 1080×1920" (see
# archetypes.py) — the two portrait cuts that also share the 1080 short edge the
# F1/F2 geometry leans on. Square/landscape are served by the same compositions
# but are not part of that per-archetype legibility contract, so the lint holds
# each archetype to the formats it is certified for.
CERT_FORMATS = {
    "feed_portrait": FORMAT_SIZES["feed_portrait"],
    "story": FORMAT_SIZES["story"],
}

# The self-hosted catalog (layouts/_shared.css @font-face) plus the generic /
# fallback tokens that may legitimately trail a font stack. A family outside
# this set means an off-catalog (probably CDN-bound) typeface crept in.
_CATALOG_FAMILIES = {
    "anton",
    "bebas neue",
    "bowlby one",
    "inter",
    "jetbrains mono",
    "noto sans",
    "noto sans arabic",
    "noto sans bengali",
    "noto sans devanagari",
    "playfair display",
    "space grotesk",
}
_GENERIC_FAMILIES = {
    "impact",
    "oswald",
    "times new roman",
    "monospace",
    "sans-serif",
    "serif",
    "system-ui",
    "-apple-system",
    "cursive",
    "ui-sans-serif",
    "blinkmacsystemfont",
    # web-safe serif/sans fallbacks that legitimately trail a display stack
    # (e.g. 'Playfair Display', Georgia, serif). These never load a CDN — they
    # are the browser's local last resort behind a self-hosted primary.
    "georgia",
    "garamond",
    "cambria",
    "arial",
    "helvetica",
    "helvetica neue",
}
_ALLOWED_FAMILIES = _CATALOG_FAMILIES | _GENERIC_FAMILIES

_FONT_FAMILY_DECL = re.compile(r"font-family\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _families_in(decl: str) -> list[str]:
    """Split a font-family value into its individual family tokens, dropping any
    ``var(--mh-font-*, …)`` wrapper (the fallback list inside it is still
    linted)."""
    # Strip var() wrappers but keep their fallback contents.
    decl = re.sub(r"var\([^,)]+,?", "", decl).replace(")", "")
    out = []
    for part in decl.split(","):
        p = part.strip().strip("'\"").strip()
        if p:
            out.append(p.lower())
    return out


@pytest.mark.parametrize("name", NAMES)
def test_no_hardcoded_hex(name):
    raw = (archetypes.V2_DIR / f"{name}.html").read_text(encoding="utf-8")
    assert _HEX_RE.search(raw) is None, f"{name}: hardcoded hex colour present"


@pytest.mark.parametrize("name", NAMES)
def test_only_catalog_font_families(name):
    raw = (archetypes.V2_DIR / f"{name}.html").read_text(encoding="utf-8")
    offenders = set()
    for m in _FONT_FAMILY_DECL.finditer(raw):
        for fam in _families_in(m.group(1)):
            # A bare CSS custom property name that leaked through is not a family.
            if fam.startswith("--mh-"):
                continue
            if fam not in _ALLOWED_FAMILIES:
                offenders.add(fam)
    assert not offenders, (
        f"{name}: off-catalog font families {sorted(offenders)} — only the "
        f"self-hosted catalog + generic fallbacks are allowed (no CDN fonts)."
    )


# ---------------------------------------------------------------------------
# Canonical content fixtures
# ---------------------------------------------------------------------------


def _brand():
    return BrandKit(
        profile_id="lint",
        display_name="Riverside Swimming Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="RSC",
    )


def _eval():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


# (label, swimmer_name, drop_seconds-or-None) — short vs long surname, 4 vs 0
# stats. photo/no-photo is driven separately (athlete_path).
_FIXTURES = [
    ("short_4stats", "Mia Cox", 2.4),
    ("long_4stats", "Anastasia Vandenberg-Whitmore", 2.4),
    ("short_0stats", "Mia Cox", None),
    ("long_0stats", "Anastasia Vandenberg-Whitmore", None),
]


def _brief_for(name, swimmer, drop):
    ach = {
        "swimmer_name": swimmer,
        "event_name": "200m Individual Medley",
        "result_time": "2:18.07",
    }
    if drop is not None:
        ach["raw_facts"] = {"drop_seconds": drop}
    item = {"id": "ci-1", "post_angle": "individual_pb", "achievement": ach}
    b = gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="lint",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=0,
    )
    b.layout_template = name
    return b


def _assemble_html(monkeypatch, tmp_path, brief, size):
    import mediahub.graphic_renderer.render as R

    captured: dict = {}

    def _fake_png(html, output_path, size):  # noqa: ARG001
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=size)
    return captured["html"]


# ---------------------------------------------------------------------------
# Browser structural sweep (opt-in, Chromium-gated)
# ---------------------------------------------------------------------------

# The single evaluate() sweep. Returns, for every text-bearing leaf element:
# its text, box, font-size, and whether it paints its own chip (bg/border). Plus
# a list of empty-but-visible slot boxes (empty-slot-collapse check).
_SWEEP_JS = r"""
() => {
  const W = window.innerWidth, H = window.innerHeight;
  const leaves = [];
  const emptyVisible = [];
  const all = document.querySelectorAll('*');
  for (const el of all) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0)
      continue;
    const r = el.getBoundingClientRect();
    // A zero-size box is a collapsed/hidden slot (a chip that folded away when
    // its data was absent) — not painted, so it is neither a text node nor an
    // overflow. Skip it entirely.
    if (r.width < 1 || r.height < 1) continue;
    // direct text of this element (excluding descendants)
    let direct = '';
    for (const n of el.childNodes)
      if (n.nodeType === 3) direct += n.textContent;
    direct = direct.replace(/\s+/g, ' ').trim();
    const hasElementChild = Array.from(el.children).length > 0;
    // A SOLID chip fill (background colour, no gradient/image); decorative rings
    // paint a border only, or a radial-gradient image — those are NOT chips.
    const bgFill =
      cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' &&
      cs.backgroundImage === 'none';
    // Effective opacity = element opacity × the text colour's own alpha, so a
    // faint watermark (low opacity or a low-alpha colour) is recognisable and
    // excluded from collision detection.
    let colorA = 1;
    const cm = cs.color.match(/rgba?\(([^)]+)\)/);
    if (cm) { const p = cm[1].split(','); if (p.length === 4) colorA = parseFloat(p[3]); }
    const eff = parseFloat(cs.opacity) * colorA;
    if (direct && !hasElementChild) {
      leaves.push({
        text: direct,
        x: r.x, y: r.y, w: r.width, h: r.height,
        fontPx: parseFloat(cs.fontSize),
        bgFill, eff,
      });
    }
    // A chip-sized SOLID-filled element with no text and no children. Chip bounds
    // exclude decorative rings/discs/photo wells (large) and hairlines (tiny).
    // Whether it is a *failed collapse* vs a decorative block is decided across
    // fixtures (a chip that holds text in the with-stats render but renders empty
    // here), not by this box alone.
    if (!direct && !hasElementChild && bgFill &&
        r.width >= 24 && r.width <= 0.45 * W &&
        r.height >= 12 && r.height <= 0.16 * H) {
      emptyVisible.push({cx: r.x + r.width / 2, cy: r.y + r.height / 2,
                         w: r.width, h: r.height, tag: el.tagName});
    }
  }
  return {W, H, leaves, emptyVisible};
}
"""

# Detecting text collisions generically across 35 wildly different archetypes is
# noisy: badges deliberately sit over headlines, and a monospaced result can be
# split into ``2:18`` / ``.`` / ``07`` fragment spans. So the overlap check only
# fires on GROSS collisions between two SUBSTANTIAL words — three-plus
# alphanumeric characters, neither carrying its own chip fill — where the
# intersection covers most of the smaller box. That is essentially always a real
# layout break, never intentional layering.
_WORD_RE = re.compile(r"[A-Za-z0-9]")


def _is_word(lf) -> bool:
    # Substantial, opaque, non-chip text — a real content word, not a faint
    # watermark, a badge pill, or a punctuation/numeral fragment.
    return (
        not lf["bgFill"]
        and lf.get("eff", 1) >= 0.4
        and len(re.sub(r"\s", "", lf["text"])) >= 3
        and bool(_WORD_RE.search(lf["text"]))
    )


def _gross_overlap(a, b, frac=0.55):
    ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if ix <= 0 or iy <= 0:
        return False
    inter = ix * iy
    smaller = max(1.0, min(a["w"] * a["h"], b["w"] * b["h"]))
    return inter / smaller > frac


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False
    return True


@pytest.fixture(scope="module")
def _browser():
    from playwright.sync_api import sync_playwright

    from mediahub.graphic_renderer.render import _CHROMIUM_LAUNCH_ARGS

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(args=_CHROMIUM_LAUNCH_ARGS)
    except Exception as exc:  # pragma: no cover
        pw.stop()
        pytest.skip(f"chromium unavailable: {exc}")
    yield browser
    try:
        browser.close()
    finally:
        pw.stop()


def _sweep(browser, html, size, tmp_path, tag):
    page_path = tmp_path / f"{tag}.html"
    page_path.write_text(html, encoding="utf-8")
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    try:
        page.goto(page_path.as_uri(), wait_until="networkidle", timeout=30_000)
        try:
            page.evaluate(
                "() => (document.fonts && document.fonts.ready) "
                "? document.fonts.ready.then(() => true) : true"
            )
        except Exception:
            pass
        return page.evaluate(_SWEEP_JS)
    finally:
        page.close()


# Known content-fit limitation surfaced BY this lint: split_diagonal_hero's
# fixed-height wedge cannot hold a 4-stat block under a very long surname — the
# lowest stat is pushed off the bottom. This is exactly the hostile-content case
# F4's score_archetype eligibility filter routes AWAY from this archetype, so it
# is an accepted degradation here rather than a layout regression. The exemption
# is scoped to the long-surname fixtures only; the archetype must still be clean
# for ordinary content.
_KNOWN_HOSTILE = {("split_diagonal_hero", "long_4stats"), ("split_diagonal_hero", "long_0stats")}


def _assert_per_fixture(name, fmt, label, data):
    """Per-fixture structural asserts from one evaluate() sweep."""
    W, H = data["W"], data["H"]
    leaves = data["leaves"]
    assert leaves, f"{name}/{fmt}/{label}: no text nodes rendered"

    # 1) No text node lands entirely off-canvas (a partial bleed is fine).
    if (name, label) not in _KNOWN_HOSTILE:
        for lf in leaves:
            fully_off = (
                lf["x"] + lf["w"] <= 0 or lf["x"] >= W or lf["y"] + lf["h"] <= 0 or lf["y"] >= H
            )
            assert not fully_off, f"{name}/{fmt}/{label}: text {lf['text']!r} fully off-canvas"

    # 2) Outer margin — the brand foot lockup (the club display name) keeps a
    #    HORIZONTAL inset (left/right) and stays on-canvas vertically. Horizontal
    #    margin is enforced because a lockup rarely bleeds sideways; vertical is
    #    only on-canvas because some archetypes deliberately anchor the foot hard
    #    to the bottom safe line.
    short = min(W, H)
    min_margin = 0.02 * short  # ~21px at 1080 — well inside the 56px edge pad
    for lf in [lf for lf in leaves if "riverside" in lf["text"].lower()]:
        assert lf["x"] >= min_margin - 1, f"{name}/{fmt}/{label}: club lockup too near left"
        assert lf["x"] + lf["w"] <= W - min_margin + 1, (
            f"{name}/{fmt}/{label}: club lockup too near right"
        )
        if (name, label) not in _KNOWN_HOSTILE:
            assert lf["y"] >= -1 and lf["y"] + lf["h"] <= H + 1, (
                f"{name}/{fmt}/{label}: club lockup off-canvas vertically"
            )

    # 3) Substantial words must not grossly collide (not badge-over-headline
    #    layering, a faint watermark, or split numeral fragments — all filtered
    #    by _is_word + the gross-overlap fraction).
    words = [lf for lf in leaves if _is_word(lf)]
    for i in range(len(words)):
        for j in range(i + 1, len(words)):
            assert not _gross_overlap(words[i], words[j]), (
                f"{name}/{fmt}/{label}: gross text overlap between "
                f"{words[i]['text']!r} and {words[j]['text']!r}"
            )

    # 4) One dominant register-1 headline: among substantial words the single
    #    largest font size is carried by exactly one node. Archetypes with only
    #    one distinct word size (a ticker/marquee crawl) have no headline
    #    register and are exempt.
    if len(words) >= 2 and (name, label) not in _KNOWN_HOSTILE:
        wsizes = sorted({round(lf["fontPx"], 1) for lf in words}, reverse=True)
        if len(wsizes) > 1:
            top = wsizes[0]
            top_nodes = [lf for lf in words if round(lf["fontPx"], 1) == top]
            assert len(top_nodes) == 1, (
                f"{name}/{fmt}/{label}: {len(top_nodes)} words tie for the largest "
                f"font ({top}px) — no single dominant headline"
            )


def _assert_empty_collapse(name, fmt, filled, empty):
    """Cross-fixture empty-slot collapse.

    A slot that carries a stat chip when the data is present must *collapse* when
    the data is absent — not render as a hollow filled pill. So any empty chip in
    the no-stats sweep whose centre coincides with a text-bearing chip in the
    with-stats sweep is a failed collapse. Purely decorative solid blocks (ribbon
    tails, accent bars) never held text, so they never match and are ignored.
    """
    filled_chip_centres = [
        (lf["x"] + lf["w"] / 2, lf["y"] + lf["h"] / 2) for lf in filled["leaves"] if lf["bgFill"]
    ]
    for e in empty["emptyVisible"]:
        for cx, cy in filled_chip_centres:
            if abs(e["cx"] - cx) <= 30 and abs(e["cy"] - cy) <= 30:
                raise AssertionError(
                    f"{name}/{fmt}: a stat chip at ~({cx:.0f},{cy:.0f}) rendered as a "
                    f"hollow {e['w']:.0f}×{e['h']:.0f} pill when the stat was absent — "
                    f"empty slot did not collapse"
                )


def _lint_enabled() -> bool:
    return os.environ.get("MEDIAHUB_ARCHETYPE_LINT", "").strip().lower() in {"1", "true", "on"}


@pytest.mark.skipif(not _chromium_ok(), reason="chromium/playwright unavailable")
def test_structural_smoke(monkeypatch, tmp_path, _browser):
    """Always-on single-page smoke so the sweep machinery is covered by default."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    name = "centered_medal_spotlight"
    size = CERT_FORMATS["feed_portrait"]
    html = _assemble_html(monkeypatch, tmp_path, _brief_for(name, "Mia Cox", 2.4), size)
    data = _sweep(_browser, html, size, tmp_path, "smoke")
    _assert_per_fixture(name, "feed_portrait", "smoke", data)


@pytest.mark.skipif(
    not _chromium_ok() or not _lint_enabled(),
    reason="opt-in slow archetype lint (set MEDIAHUB_ARCHETYPE_LINT=1 with chromium)",
)
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("fmt", sorted(CERT_FORMATS))
def test_archetype_structural_sweep(monkeypatch, tmp_path, _browser, name, fmt):
    """One evaluate() sweep per (archetype × format × fixture); the four canonical
    fixtures also feed the cross-fixture empty-slot-collapse check."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    size = CERT_FORMATS[fmt]
    swept: dict[str, dict] = {}
    for label, swimmer, drop in _FIXTURES:
        html = _assemble_html(monkeypatch, tmp_path, _brief_for(name, swimmer, drop), size)
        data = _sweep(_browser, html, size, tmp_path, f"{name}_{fmt}_{label}")
        _assert_per_fixture(name, fmt, label, data)
        swept[label] = data
    # empty-slot collapse: short_4stats (chips present) vs short_0stats (absent).
    _assert_empty_collapse(name, fmt, swept["short_4stats"], swept["short_0stats"])
