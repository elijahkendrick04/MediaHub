"""documents.theme — brand role vars → a document's CSS tokens, fonts & base sheet.

Documents paint with the **same** ``--mh-*`` brand roles the cards and charts use
(``charts.palette.role_vars_from_palette`` → ``graphic_renderer.render._mh_role_vars``),
so a programme, a report and a card from one club are unmistakably the same brand.
Fonts are the self-hosted woff2 the rest of the engine serves (CLAUDE.md rule —
never the Google Fonts CDN); only the ``@font-face`` blocks are pulled in (file://
rewritten for Chromium's print path), not the card layout CSS.

Two presentations from one palette:
  - ``document`` (programme / report / proposal) — an editorial **print** look:
    near-black ink on white paper, brand colour as header bands, rules and KPI
    accents. Reads well printed and is toner-kind.
  - ``deck`` (AGM) — the **brand-dark** card look: the deep brand surface, light
    ink, accent highlights — so a presented deck matches the social cards.

Everything here is deterministic: same role vars + kind → byte-identical CSS.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from .models import PAGE_GEOMETRIES, PageGeometry

# ---------------------------------------------------------------------------
# Brand role vars (delegated to the single source of truth)
# ---------------------------------------------------------------------------


def resolve_role_vars(brand_kit=None, palette: Optional[dict] = None) -> dict[str, str]:
    """The resolved ``--mh-*`` role set for a brand kit / bare palette.

    Thin wrapper over ``charts.palette.role_vars_from_palette`` so documents and
    charts resolve colour identically. Always returns a usable set (the wrapper
    falls back to a neutral brand if the renderer is unavailable)."""
    from mediahub.charts.palette import role_vars_from_palette

    return role_vars_from_palette(palette, brand_kit)


def _role(role_vars: dict[str, str], name: str, default: str) -> str:
    return role_vars.get(name) or default


def _to_rgb(hex_or_rgba: str) -> tuple[int, int, int]:
    s = (hex_or_rgba or "").strip()
    if s.startswith("#"):
        s = s[1:]
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) >= 6:
            try:
                return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            except ValueError:
                pass
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            return int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
        except (ValueError, IndexError):
            pass
    return (10, 37, 64)  # safe brand-navy default


def _mix(a: str, b: str, t: float) -> str:
    """Blend hex ``a`` toward ``b`` by ``t`` (0..1). Deterministic, dependency-free."""
    ar, ag, ab = _to_rgb(a)
    br, bg, bb = _to_rgb(b)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return f"#{r:02X}{g:02X}{bl:02X}"


# ---------------------------------------------------------------------------
# Document colour tokens (the --doc-* layer the base sheet consumes)
# ---------------------------------------------------------------------------


def doc_tokens(role_vars: dict[str, str], *, kind: str = "document") -> dict[str, str]:
    """Map brand ``--mh-*`` roles to the ``--doc-*`` tokens the sheet uses."""
    primary = _role(role_vars, "--mh-primary", "#0A2540")
    secondary = _role(role_vars, "--mh-secondary", "#1B3D5C")
    surface = _role(role_vars, "--mh-surface", "#051433")
    accent = _role(role_vars, "--mh-accent", "#FFB81C")
    on_primary = _role(role_vars, "--mh-on-primary", "#FFFFFF")
    on_surface = _role(role_vars, "--mh-on-surface", "#FFFFFF")

    if kind == "deck":
        page = surface
        ink = on_surface
        return {
            "--doc-page": page,
            "--doc-ink": ink,
            "--doc-muted": _mix(ink, page, 0.42),
            "--doc-rule": _mix(ink, page, 0.78),
            "--doc-brand": primary,
            "--doc-secondary": secondary,
            "--doc-accent": accent,
            "--doc-band": primary,
            "--doc-band-ink": on_primary,
            "--doc-soft": _mix(page, ink, 0.10),
            "--doc-on-accent": _mix(primary, "#000000", 0.0)
            if _contrast_ok(primary, accent)
            else "#10151C",
        }

    # Paper document — editorial print look.
    ink = "#14181F"
    page = "#FFFFFF"
    return {
        "--doc-page": page,
        "--doc-ink": ink,
        "--doc-muted": "#5A6472",
        "--doc-rule": "#E3E7ED",
        "--doc-brand": primary,
        "--doc-secondary": secondary,
        "--doc-accent": accent,
        "--doc-band": primary,
        "--doc-band-ink": on_primary,
        "--doc-soft": _mix(primary, page, 0.93),  # faint brand tint for tiles/headers
        "--doc-on-accent": "#10151C" if _is_light(accent) else "#FFFFFF",
    }


def _luminance(hex_colour: str) -> float:
    r, g, b = _to_rgb(hex_colour)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _is_light(hex_colour: str) -> bool:
    return _luminance(hex_colour) > 0.6


def _contrast_ok(a: str, b: str) -> bool:
    return abs(_luminance(a) - _luminance(b)) > 0.4


# ---------------------------------------------------------------------------
# Self-hosted fonts (CLAUDE.md rule — never the Google Fonts CDN)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def font_face_css() -> str:
    """The ``@font-face`` blocks from the renderer's shared CSS, file:// rewritten.

    Only the font faces are pulled in (not card layout rules), so a document gets
    the self-hosted typefaces with no Google Fonts ``<link>``/``@import``."""
    try:
        from mediahub.graphic_renderer.render import LAYOUTS_DIR

        shared = (LAYOUTS_DIR / "_shared.css").read_text(encoding="utf-8")
        rewritten = shared.replace(
            "url(fonts/", f"url({(LAYOUTS_DIR / 'fonts').as_uri()}/"
        )
        faces = re.findall(r"@font-face\s*\{[^}]*\}", rewritten, flags=re.DOTALL)
        return "\n".join(faces)
    except Exception:
        return ""  # fonts fall back to system stack; never a CDN link


# ---------------------------------------------------------------------------
# Base stylesheet
# ---------------------------------------------------------------------------

_BASE_CSS = r"""
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  color:var(--doc-ink);
  background:var(--doc-page);
  -webkit-print-color-adjust:exact;
  print-color-adjust:exact;
  font-size:11pt;
  line-height:1.5;
}
.doc-sheet{
  background:var(--doc-page);
  color:var(--doc-ink);
  position:relative;
  overflow:hidden;
}
.doc-pad{padding:var(--doc-margin)}
h1,h2,h3{font-family:'Space Grotesk','Inter',sans-serif;line-height:1.12;margin:0 0 .35em;color:var(--doc-ink);font-weight:700}
.doc-h1{font-size:1.9em;letter-spacing:-.01em}
.doc-h2{font-size:1.4em;border-bottom:2px solid var(--doc-accent);padding-bottom:.18em;margin-top:1.1em}
.doc-h3{font-size:1.12em;color:var(--doc-brand)}
.doc-text{margin:0 0 .7em;white-space:pre-wrap}
.doc-text.center{text-align:center}
.doc-text.right{text-align:right}
.doc-text.justify{text-align:justify}
.doc-list{margin:.2em 0 .9em;padding-left:1.3em}
.doc-list li{margin:.22em 0}
.doc-quote{margin:.6em 0;padding:.5em 1em;border-left:4px solid var(--doc-accent);
  background:var(--doc-soft);font-size:1.05em;font-style:italic;border-radius:0 6px 6px 0}
.doc-quote .who{display:block;margin-top:.4em;font-style:normal;font-size:.8em;color:var(--doc-muted);font-weight:600}
.doc-divider{border:0;border-top:1px solid var(--doc-rule);margin:1em 0}
.doc-spacer-sm{height:8px}.doc-spacer-md{height:18px}.doc-spacer-lg{height:36px}
table.doc-table{width:100%;border-collapse:collapse;margin:.4em 0 1em;font-size:.92em}
table.doc-table caption{caption-side:bottom;text-align:left;color:var(--doc-muted);font-size:.82em;margin-top:.35em}
table.doc-table th{background:var(--doc-band);color:var(--doc-band-ink);text-align:left;
  padding:7px 10px;font-weight:600;font-size:.92em}
table.doc-table td{padding:6px 10px;border-bottom:1px solid var(--doc-rule)}
table.doc-table tr:nth-child(even) td{background:var(--doc-soft)}
.doc-figure{margin:.5em 0 1em;text-align:center}
.doc-figure img{max-width:100%;border-radius:8px}
.doc-figure.cover img{width:100%;object-fit:cover}
.doc-figure figcaption{color:var(--doc-muted);font-size:.82em;margin-top:.4em;text-align:center}
.doc-chart{margin:.5em 0 1em}
.doc-chart svg{display:block;max-width:100%;height:auto;margin:0 auto}
.doc-kpis{display:flex;gap:14px;flex-wrap:wrap;margin:.5em 0 1em}
.doc-kpi{flex:1 1 0;min-width:120px;background:var(--doc-soft);border:1px solid var(--doc-rule);
  border-radius:10px;padding:14px 16px}
.doc-kpi .v{font-family:'Space Grotesk',sans-serif;font-size:1.9em;font-weight:700;color:var(--doc-brand);line-height:1}
.doc-kpi .l{display:block;margin-top:.35em;font-size:.82em;color:var(--doc-muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.doc-kpi .s{display:block;margin-top:.1em;font-size:.78em;color:var(--doc-muted)}
.doc-cols{display:flex;gap:24px}
.doc-cols>.doc-col{flex:1 1 0;min-width:0}
/* running header / footer band on paper documents */
.doc-runhead{display:flex;justify-content:space-between;align-items:center;
  font-size:.74em;color:var(--doc-muted);border-bottom:1px solid var(--doc-rule);
  padding-bottom:6px;margin-bottom:14px}
.doc-runhead .brand{font-weight:700;color:var(--doc-brand);text-transform:uppercase;letter-spacing:.06em}
.doc-foot{position:absolute;left:var(--doc-margin);right:var(--doc-margin);bottom:8mm;
  display:flex;justify-content:space-between;font-size:.7em;color:var(--doc-muted);
  border-top:1px solid var(--doc-rule);padding-top:5px}
.doc-sources{font-size:.7em;color:var(--doc-muted);margin-top:1.2em;border-top:1px dashed var(--doc-rule);padding-top:6px}
/* cover / section / centered treatments */
.layout-cover,.layout-section_break,.layout-centered,.layout-closing{
  display:flex;flex-direction:column;justify-content:center;height:100%}
.layout-cover .doc-h1{font-size:2.6em}
.layout-cover .cover-kicker{font-size:.9em;text-transform:uppercase;letter-spacing:.14em;color:var(--doc-accent);font-weight:700;margin-bottom:.6em}
.layout-section_break{align-items:flex-start}
.layout-centered{align-items:center;text-align:center}
.layout-closing{align-items:center;text-align:center}
"""

_DECK_CSS = r"""
.doc-sheet{display:flex;flex-direction:column}
.doc-pad{flex:1;display:flex;flex-direction:column;min-height:0}
body{font-size:20px;line-height:1.4}
.doc-h1{font-size:2.4em}
.doc-h2{font-size:1.7em;border-bottom-width:3px}
.doc-h3{font-size:1.3em}
table.doc-table{font-size:1em}
.doc-kpi .v{font-size:2.4em}
.bg-primary{background:var(--doc-brand);color:var(--doc-band-ink)}
.bg-accent{background:var(--doc-accent);color:var(--doc-on-accent)}
.bg-primary .doc-h1,.bg-primary .doc-h2,.bg-primary .doc-h3,.bg-primary .doc-text{color:var(--doc-band-ink)}
.bg-accent .doc-h1,.bg-accent .doc-h2,.bg-accent .doc-h3,.bg-accent .doc-text{color:var(--doc-on-accent)}
.slide-num{position:absolute;right:24px;bottom:16px;font-size:.7em;color:var(--doc-muted);font-weight:600}
"""


def page_css(geom: PageGeometry, *, kind: str = "document") -> str:
    """The ``@page`` + sheet-box rules for the document kind.

    *deck* — one fixed slide box per section, one slide per sheet (margin 0; the
    pad lives inside the slide). *document* — ``@page`` margins applied to every
    printed sheet; content flows and paginates, sections may force a page break."""
    if kind == "deck":
        return (
            f"@page{{size:{geom.width} {geom.height};margin:0}}"
            f":root{{--doc-margin:{geom.margin}}}"
            f".doc-sheet{{width:{geom.width};height:{geom.height};break-after:page}}"
            ".doc-sheet:last-child{break-after:auto}"
        )
    return (
        f"@page{{size:{geom.width} {geom.height};margin:{geom.margin}}}"
        ":root{--doc-margin:0}"
        ".doc-section.brk{break-before:page}"
    )


def document_style(role_vars: dict[str, str], *, kind: str, geom: PageGeometry) -> str:
    """The complete inner CSS for a document/deck: tokens + fonts + base + page."""
    tokens = doc_tokens(role_vars, kind=kind)
    root = ":root{" + "".join(f"{k}:{v};" for k, v in tokens.items()) + "}"
    parts = [font_face_css(), root, page_css(geom, kind=kind), _BASE_CSS]
    if kind == "deck":
        parts.append(_DECK_CSS)
    return "\n".join(parts)


__all__ = [
    "resolve_role_vars",
    "doc_tokens",
    "font_face_css",
    "page_css",
    "document_style",
]
