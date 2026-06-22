"""Print exports — PB certificates + noticeboard posters, with a full
print-production pipeline (roadmap W.12 + G1.17).

Renders print-ready PDFs via the same headless-Chromium (Playwright) path the
still-graphic renderer uses, but through ``page.pdf`` instead of a screenshot.

W.12 shipped the trim-only A4 certificate and poster. **G1.17 expands this into
a real print-production pipeline**: bleed, crop/trim marks, a registration +
CMYK colour bar, and CMYK-aware export. The trim artwork is unchanged — the
expansion wraps *any* ``.sheet`` layout in a bleed-expanded media box with
printer's marks, so a club can hand the PDF straight to a print shop.

Design notes
------------
- **Print is light.** The dark-first product palette applies to the web UI,
  not to paper: certificates and posters use a warm paper background with
  dark ink so they stay credible on a mono laser printer — colour carries
  brand, never information.
- Layouts live beside the social-card layouts (``layouts/print_*.html`` and
  the new ``layouts/_print.css`` page furniture) and use the same
  ``{{PLACEHOLDER}}`` string substitution (intentionally not Jinja, matching
  ``render.py``).
- Typography is the repo's SELF-HOSTED font stack from ``_shared.css``: the
  relative ``url(fonts/...)`` declarations are rewritten to absolute
  ``file://`` URLs exactly like ``render.py`` does, and the page is navigated
  as a real ``file://`` document so Chromium is allowed to fetch them. No
  Google Fonts CDN, ever.
- Brand colours come from the caller-supplied ``brand`` mapping (BrandKit
  shaped — ``primary``/``primary_colour`` etc.) so print matches the cards.
- Every piece of interpolated text is HTML-escaped; the layouts never trust
  caller-supplied strings.
- **CMYK is honest.** The on-page colour bar + ``cmyk_separations`` report use
  a deterministic, *uncalibrated* device RGB↔CMYK transform (no ICC profile),
  clearly labelled as such — a print shop's RIP does the real, profiled
  conversion. ``cmyk_convert_pdf`` performs a true DeviceCMYK conversion via
  Ghostscript *when it is installed*, and raises ``CmykUnavailable`` otherwise
  rather than faking it (the RGB print-ready PDF with marks + bleed is always
  produced regardless).

Public API
----------
W.12 (trim-only):
- ``render_html_to_pdf(html, output_path, *, page_format="A4", landscape=False,
  width=None, height=None)`` → write a PDF, return its path.
- ``build_certificate_html(...)`` / ``build_poster_html(...)``.
- ``export_certificate_pdf(...)`` / ``export_poster_pdf(...)``.

G1.17 (print production):
- ``PrintGeometry`` / ``geometry_for(...)`` → trim/bleed/mark/media maths.
- ``rgb_to_cmyk`` / ``cmyk_to_rgb`` / ``format_cmyk`` / ``cmyk_separations`` →
  deterministic colour science + a brand separations report.
- ``print_furniture_svg(geom, ...)`` → crop marks + registration + colour bar.
- ``to_print_production(trim_html, geom, ...)`` → wrap any ``.sheet`` layout.
- ``build_certificate_print_html(...)`` / ``build_poster_print_html(...)``.
- ``export_certificate_print_pdf(...)`` / ``export_poster_print_pdf(...)``.
- ``cmyk_convert_pdf(...)`` (Ghostscript, honest ``CmykUnavailable``).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mediahub.graphic_renderer.render import LAYOUTS_DIR, darken, html_escape as _esc

_SHARED_CSS_PATH = LAYOUTS_DIR / "_shared.css"
_PRINT_CSS_PATH = LAYOUTS_DIR / "_print.css"
_CERTIFICATE_LAYOUT = LAYOUTS_DIR / "print_certificate_a4.html"
_POSTER_LAYOUT = LAYOUTS_DIR / "print_poster_a4.html"

# Fixed ink/paper tones shared by both print layouts (light, mono-safe).
_PAPER = "#FDFBF6"
_INK = "#1C1B18"

# The W.12 layouts size their ``.sheet`` a hair under A4 height so Chromium
# never spills a second page in the trim-only path; the print-production path
# treats that exact box as the trim and expands the media box around it.
_SHEET_TRIM_W_MM = 210.0
_SHEET_TRIM_H_MM = 296.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fonts_css() -> str:
    """The self-hosted @font-face block, with font URLs rewritten to file://.

    Same rewrite as ``render.py``: the page is rendered from a throwaway
    directory, so the relative ``url(fonts/...)`` in ``_shared.css`` would not
    resolve — absolute ``file://`` URLs under the layouts dir always do.
    """
    css = _SHARED_CSS_PATH.read_text(encoding="utf-8")
    return css.replace("url(fonts/", f"url({(LAYOUTS_DIR / 'fonts').as_uri()}/")


def _brand_hex(brand: dict, *keys: str, default: str) -> str:
    for k in keys:
        v = (brand or {}).get(k)
        if isinstance(v, str) and v.strip().startswith("#"):
            return v.strip()
    return default


def _palette_replacements(brand: dict) -> dict[str, str]:
    """BrandKit-shaped dict → the colour placeholders both layouts use."""
    primary = _brand_hex(brand, "primary", "primary_colour", default="#0A2540")
    secondary = _brand_hex(brand, "secondary", "secondary_colour", default=darken(primary, 0.35))
    accent = _brand_hex(brand, "accent", "accent_colour", default=secondary)
    return {
        "PRIMARY": primary,
        "PRIMARY_DEEP": darken(primary, 0.30),
        "SECONDARY": secondary,
        "ACCENT": accent,
        "PAPER": _PAPER,
        "INK": _INK,
    }


def _apply(template: str, replacements: dict[str, str]) -> str:
    """``{{KEY}}`` substitution (mirrors render.py), strict about coverage.

    Coverage is checked against the TEMPLATE (every placeholder it declares
    must have a replacement) rather than by re-scanning the output, so
    caller text that happens to contain ``{{`` can never trip the check —
    it just passes through escaped, like any other literal text.
    """
    missing = sorted(set(_find_placeholders(template)) - set(replacements))
    if missing:
        raise ValueError(f"print layout has unfilled placeholders: {missing}")
    out = template
    for k, v in replacements.items():
        out = out.replace("{{" + k + "}}", "" if v is None else str(v))
    return out


def _find_placeholders(html: str) -> list[str]:
    return re.findall(r"\{\{([A-Z0-9_]+)\}\}", html)


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


def build_certificate_html(
    *,
    swimmer_name: str,
    event_label: str,
    time_str: str,
    achievement_headline: str,
    meet_name: str,
    meet_date: str,
    club_name: str,
    brand: dict,
    detail_line: str = "",
) -> str:
    """Fill ``layouts/print_certificate_a4.html`` — the framed PB certificate.

    The certificate is the artifact families print and frame: verified time,
    swimmer name large, club branding in the header band, and an honest
    provenance footer. All text arguments are HTML-escaped here.
    """
    template = _CERTIFICATE_LAYOUT.read_text(encoding="utf-8")
    repl = _palette_replacements(brand)
    repl.update(
        {
            "FONTS_CSS": _fonts_css(),
            "CLUB_NAME": _esc(club_name),
            "ACHIEVEMENT_HEADLINE": _esc(achievement_headline or "Personal Best Certificate"),
            "SWIMMER_NAME": _esc(swimmer_name),
            "EVENT_LABEL": _esc(event_label),
            "TIME_STR": _esc(time_str),
            "MEET_NAME": _esc(meet_name),
            "MEET_DATE": _esc(meet_date),
            "DETAIL_LINE": _esc(detail_line),
        }
    )
    return _apply(template, repl)


def build_poster_html(
    *,
    title: str,
    meet_name: str,
    stat_lines: list[tuple[str, str]],
    highlight_rows: list[dict],
    club_name: str,
    brand: dict,
) -> str:
    """Fill ``layouts/print_poster_a4.html`` — the weekend-in-numbers poster.

    ``stat_lines`` are ``(label, value)`` pairs ("PBs", "14") rendered as big
    stat chips; ``highlight_rows`` are ``{swimmer, event, time, note}`` dicts
    rendered as the highlights table. Zero rows renders a friendly empty
    state instead of a bare table. All text is HTML-escaped here.
    """
    template = _POSTER_LAYOUT.read_text(encoding="utf-8")

    chips = "".join(
        '<div class="stat-chip">'
        f'<div class="num">{_esc(value)}</div>'
        f'<div class="lab">{_esc(label)}</div>'
        "</div>"
        for label, value in (stat_lines or [])
    )

    rows = [r or {} for r in (highlight_rows or [])]
    if rows:
        body = "".join(
            "<tr>"
            f'<td class="sw">{_esc(r.get("swimmer", ""))}</td>'
            f'<td class="ev">{_esc(r.get("event", ""))}</td>'
            f'<td class="tm">{_esc(r.get("time", ""))}</td>'
            f'<td class="nt">{_esc(r.get("note", ""))}</td>'
            "</tr>"
            for r in rows
        )
        highlights_block = (
            '<table class="highlights">'
            "<thead><tr>"
            "<th>Swimmer</th><th>Event</th><th>Time</th><th>Highlight</th>"
            f"</tr></thead><tbody>{body}</tbody></table>"
        )
    else:
        highlights_block = (
            '<div class="no-highlights">'
            "A full weekend of racing — see the results sheet for every swim."
            "</div>"
        )

    repl = _palette_replacements(brand)
    repl.update(
        {
            "FONTS_CSS": _fonts_css(),
            "TITLE": _esc(title),
            "MEET_NAME": _esc(meet_name),
            "CLUB_NAME": _esc(club_name),
            "STAT_CHIPS": chips,
            "HIGHLIGHTS_BLOCK": highlights_block,
        }
    )
    return _apply(template, repl)


# ---------------------------------------------------------------------------
# Playwright PDF runner
# ---------------------------------------------------------------------------


def render_html_to_pdf(
    html: str,
    output_path: Path,
    *,
    page_format: str = "A4",
    landscape: bool = False,
    width: str | None = None,
    height: str | None = None,
    prefer_css_page_size: bool = False,
    tagged: bool = False,
) -> Path:
    """Headless-Chromium print-to-PDF; returns the written path.

    Same sync-playwright pattern as ``render.render_html_to_png``: the HTML is
    written beside the output and navigated as a real ``file://`` document
    (``set_content`` would leave the page on about:blank, where Chromium
    refuses to fetch the self-hosted file:// fonts), and the render waits for
    ``document.fonts.ready`` before printing. ``print_background=True`` keeps
    the brand bands and paper tone on the page.

    ``width``/``height`` (CSS lengths, e.g. ``"224mm"``) pin the PDF media box
    to an exact size and take precedence over ``page_format``. The G1.17
    print-production path uses them to emit the bleed-expanded media box
    (trim + bleed + crop-mark margin); when omitted the behaviour is the
    historic ``format="A4"`` page (back-compatible for the W.12 callers).

    ``prefer_css_page_size=True`` lets a document's own ``@page { size: ... }``
    rule drive the sheet geometry (and per-page breaks) — the multi-page
    document engine (roadmap 1.15) uses it so A4 reports and 16:9 decks
    paginate from CSS. It is ignored when ``width``/``height`` pin an explicit
    media box; default ``False`` keeps every existing caller byte-identical.

    ``tagged=True`` emits an accessible (tagged) PDF — the document's ``<h1..3>``
    headings and image ``alt`` text become screen-reader structure (roadmap 1.15);
    default ``False`` keeps existing callers byte-identical.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # pragma: no cover - environment-dependent
        raise RuntimeError(f"Playwright not installed: {e}")

    page_path = output_path.with_suffix(output_path.suffix + ".render.html")
    page_path.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--font-render-hinting=none"])
            page = browser.new_page()
            page.goto(page_path.as_uri(), wait_until="networkidle", timeout=30_000)
            try:
                page.evaluate(
                    "() => (document.fonts && document.fonts.ready) "
                    "? document.fonts.ready.then(() => true) : true"
                )
            except Exception:
                try:
                    page.wait_for_timeout(400)
                except Exception:
                    pass
            pdf_kwargs: dict = {
                "path": str(output_path),
                "print_background": True,
                "margin": {"top": "0", "right": "0", "bottom": "0", "left": "0"},
            }
            if tagged:
                # Accessible (tagged) PDF — carries the document's headings + image
                # alt text as structure for screen readers (roadmap 1.15 a11y).
                pdf_kwargs["tagged"] = True
            if width and height:
                # Explicit media box (bleed-expanded print page) — pin the
                # exact size deterministically, ignoring any @page rule.
                pdf_kwargs.update(width=width, height=height)
            else:
                pdf_kwargs.update(format=page_format, landscape=landscape)
                if prefer_css_page_size:
                    # Let the document's own @page size win over the format —
                    # multi-page docs/decks paginate from their CSS geometry.
                    pdf_kwargs["prefer_css_page_size"] = True
            page.pdf(**pdf_kwargs)
            browser.close()
    finally:
        try:
            page_path.unlink()
        except OSError:
            pass
    return output_path


# ---------------------------------------------------------------------------
# Convenience wrappers — build HTML → render PDF
# ---------------------------------------------------------------------------


def export_certificate_pdf(
    output_path: Path,
    *,
    swimmer_name: str,
    event_label: str,
    time_str: str,
    achievement_headline: str,
    meet_name: str,
    meet_date: str,
    club_name: str,
    brand: dict,
    detail_line: str = "",
) -> Path:
    """Build the certificate HTML and print it to ``output_path`` (A4 portrait)."""
    html = build_certificate_html(
        swimmer_name=swimmer_name,
        event_label=event_label,
        time_str=time_str,
        achievement_headline=achievement_headline,
        meet_name=meet_name,
        meet_date=meet_date,
        club_name=club_name,
        brand=brand,
        detail_line=detail_line,
    )
    return render_html_to_pdf(html, Path(output_path))


def export_poster_pdf(
    output_path: Path,
    *,
    title: str,
    meet_name: str,
    stat_lines: list[tuple[str, str]],
    highlight_rows: list[dict],
    club_name: str,
    brand: dict,
) -> Path:
    """Build the noticeboard poster HTML and print it to ``output_path`` (A4 portrait)."""
    html = build_poster_html(
        title=title,
        meet_name=meet_name,
        stat_lines=stat_lines,
        highlight_rows=highlight_rows,
        club_name=club_name,
        brand=brand,
    )
    return render_html_to_pdf(html, Path(output_path))


# ===========================================================================
# G1.17 — Print-production pipeline (trim/bleed/crop marks + CMYK-aware export)
# ===========================================================================
#
# The W.12 builders above emit *trim-only* artwork. Everything below expands
# that into print-shop-ready output: a bleed-extended media box, corner
# crop/trim marks, a registration + CMYK colour bar, and an optional true
# DeviceCMYK conversion. The trim artwork is never modified — the expansion
# wraps it, so it works for any current or future ``.sheet`` layout.


# ---------------------------------------------------------------------------
# Print geometry
# ---------------------------------------------------------------------------

# Named trim sizes in millimetres (portrait orientation; landscape swaps).
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A6": (105.0, 148.0),
    "A5": (148.0, 210.0),
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "Tabloid": (279.4, 431.8),
    "6x4": (152.4, 101.6),  # the classic photo print (already landscape)
    "5x7": (177.8, 127.0),
}

# Sensible print defaults (mm). 3 mm bleed is the UK/EU litho standard; a
# 4 mm crop mark sits clear of the bleed in the unprinted slug margin.
_DEFAULT_BLEED_MM = 3.0
_DEFAULT_MARK_LEN_MM = 4.0
_DEFAULT_MARK_WEIGHT_MM = 0.25  # ~0.7 pt hairline


@dataclass(frozen=True)
class PrintGeometry:
    """Trim/bleed/mark geometry for one print page, all dimensions in mm.

    The media box is the trim box grown on every side by ``margin_mm`` =
    ``bleed_mm + mark_len_mm``. Inside that margin: the inner ``bleed_mm`` band
    is filled by the bled background (so a slightly-off guillotine cut never
    shows a white sliver), and the outer ``mark_len_mm`` band is the unprinted
    slug where the crop marks and colour bar live.
    """

    trim_w_mm: float
    trim_h_mm: float
    bleed_mm: float = _DEFAULT_BLEED_MM
    mark_len_mm: float = _DEFAULT_MARK_LEN_MM
    mark_weight_mm: float = _DEFAULT_MARK_WEIGHT_MM

    def __post_init__(self) -> None:
        for name in ("trim_w_mm", "trim_h_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("bleed_mm", "mark_len_mm", "mark_weight_mm"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def margin_mm(self) -> float:
        """Total media margin on each side: bleed band + crop-mark slug."""
        return self.bleed_mm + self.mark_len_mm

    @property
    def media_w_mm(self) -> float:
        return self.trim_w_mm + 2 * self.margin_mm

    @property
    def media_h_mm(self) -> float:
        return self.trim_h_mm + 2 * self.margin_mm

    @property
    def trim_left_mm(self) -> float:
        return self.margin_mm

    @property
    def trim_top_mm(self) -> float:
        return self.margin_mm

    @property
    def bleed_rect_left_mm(self) -> float:
        return self.margin_mm - self.bleed_mm  # == mark_len_mm

    @property
    def bleed_rect_w_mm(self) -> float:
        return self.trim_w_mm + 2 * self.bleed_mm

    @property
    def bleed_rect_h_mm(self) -> float:
        return self.trim_h_mm + 2 * self.bleed_mm


def geometry_for(
    paper: str = "A4",
    *,
    landscape: bool = False,
    bleed_mm: float = _DEFAULT_BLEED_MM,
    mark_len_mm: float = _DEFAULT_MARK_LEN_MM,
    mark_weight_mm: float = _DEFAULT_MARK_WEIGHT_MM,
) -> PrintGeometry:
    """Geometry for a named paper size (case-insensitive); ``landscape`` swaps."""
    key = next((k for k in PAPER_SIZES_MM if k.lower() == str(paper).lower()), None)
    if key is None:
        raise ValueError(f"unknown paper size {paper!r}; known: {sorted(PAPER_SIZES_MM)}")
    w, h = PAPER_SIZES_MM[key]
    if landscape:
        w, h = h, w
    return PrintGeometry(
        trim_w_mm=w,
        trim_h_mm=h,
        bleed_mm=bleed_mm,
        mark_len_mm=mark_len_mm,
        mark_weight_mm=mark_weight_mm,
    )


def _sheet_geometry(
    *,
    bleed_mm: float = _DEFAULT_BLEED_MM,
    mark_len_mm: float = _DEFAULT_MARK_LEN_MM,
    mark_weight_mm: float = _DEFAULT_MARK_WEIGHT_MM,
) -> PrintGeometry:
    """Geometry matching the W.12 ``.sheet`` trim box (210 x 296 mm)."""
    return PrintGeometry(
        trim_w_mm=_SHEET_TRIM_W_MM,
        trim_h_mm=_SHEET_TRIM_H_MM,
        bleed_mm=bleed_mm,
        mark_len_mm=mark_len_mm,
        mark_weight_mm=mark_weight_mm,
    )


# ---------------------------------------------------------------------------
# CMYK colour science (deterministic, uncalibrated device transform)
# ---------------------------------------------------------------------------
#
# A naive, device-independent RGB<->CMYK transform. It is exact on the
# round-trip for in-gamut colours and is honest about being uncalibrated: it
# carries no ICC profile, so it is a *preview* of the separations, not a
# press-accurate proof. The print shop's RIP (or ``cmyk_convert_pdf`` via
# Ghostscript) does the real, profiled conversion.


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    """Parse ``#RGB`` / ``#RRGGBB`` (with or without ``#``) to a 0..255 tuple."""
    s = str(hex_colour or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        raise ValueError(f"not a hex colour: {hex_colour!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_cmyk(hex_colour: str) -> tuple[float, float, float, float]:
    """``#RRGGBB`` → ``(c, m, y, k)`` each in 0..1 (uncalibrated)."""
    r, g, b = _hex_to_rgb(hex_colour)
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    k = 1.0 - max(r_, g_, b_)
    if k >= 1.0:  # pure black — avoid divide-by-zero
        return (0.0, 0.0, 0.0, 1.0)
    inv = 1.0 - k
    c = (1.0 - r_ - k) / inv
    m = (1.0 - g_ - k) / inv
    y = (1.0 - b_ - k) / inv
    return (c, m, y, k)


def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> tuple[int, int, int]:
    """``(c, m, y, k)`` each 0..1 → ``(r, g, b)`` 0..255 (clamped)."""

    def _clamp01(v: float) -> float:
        return 0.0 if v < 0 else 1.0 if v > 1 else v

    c, m, y, k = (_clamp01(v) for v in (c, m, y, k))
    r = round(255.0 * (1.0 - c) * (1.0 - k))
    g = round(255.0 * (1.0 - m) * (1.0 - k))
    b = round(255.0 * (1.0 - y) * (1.0 - k))
    return (int(r), int(g), int(b))


def cmyk_to_hex(c: float, m: float, y: float, k: float) -> str:
    r, g, b = cmyk_to_rgb(c, m, y, k)
    return f"#{r:02X}{g:02X}{b:02X}"


def format_cmyk(c: float, m: float, y: float, k: float) -> str:
    """Compact print-ready label, e.g. ``"C0 M100 Y100 K0"`` (rounded %)."""
    return " ".join(f"{ch}{round(v * 100)}" for ch, v in zip("CMYK", (c, m, y, k)))


def cmyk_percent(hex_colour: str) -> tuple[int, int, int, int]:
    """``#RRGGBB`` → integer CMYK percentages ``(C, M, Y, K)`` in 0..100."""
    return tuple(round(v * 100) for v in rgb_to_cmyk(hex_colour))  # type: ignore[return-value]


# Roles probed from a BrandKit-shaped mapping, in resolution order.
_BRAND_ROLE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("primary", ("primary", "primary_colour")),
    ("secondary", ("secondary", "secondary_colour")),
    ("accent", ("accent", "accent_colour")),
)


def cmyk_separations(brand: dict | None) -> list[dict]:
    """Brand colours → a CMYK separations report (one row per resolved role).

    Each row is ``{role, hex, cmyk, label}`` where ``cmyk`` is a ``(C,M,Y,K)``
    integer-percent tuple and ``label`` is the print-ready ``"C0 M0 Y0 K100"``
    string. The fixed ink/paper tones are always appended so the report fully
    describes every colour that can appear on paper. Roles with no valid hex
    are skipped; the list is de-duplicated by hex while preserving order.
    """
    rows: list[dict] = []
    seen: set[str] = set()

    def _add(role: str, hex_value: str | None) -> None:
        if not isinstance(hex_value, str):
            return
        try:
            r, g, b = _hex_to_rgb(hex_value)
        except ValueError:
            return
        norm = f"#{r:02X}{g:02X}{b:02X}"
        if norm in seen:
            return
        seen.add(norm)
        c = rgb_to_cmyk(norm)
        rows.append(
            {
                "role": role,
                "hex": norm,
                "cmyk": cmyk_percent(norm),
                "label": format_cmyk(*c),
            }
        )

    b = brand or {}
    for role, keys in _BRAND_ROLE_KEYS:
        val = next((b[k] for k in keys if isinstance(b.get(k), str)), None)
        _add(role, val)
    _add("ink", _INK)
    _add("paper", _PAPER)
    return rows


# ---------------------------------------------------------------------------
# Print furniture — crop marks, registration targets, CMYK colour bar (SVG)
# ---------------------------------------------------------------------------


def _f(value: float) -> str:
    """Format a mm coordinate compactly (trim trailing zeros)."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _crop_mark_lines(geom: PrintGeometry) -> list[tuple[float, float, float, float]]:
    """The eight crop-mark line segments (x1,y1,x2,y2) in media-box mm.

    Two perpendicular marks per trim corner. Each sits in the unprinted slug,
    aligned to a trim edge, running from the media edge inward only as far as
    the bleed boundary so it never inks onto the bled artwork.
    """
    mw, mh = geom.media_w_mm, geom.media_h_mm
    tl, tt = geom.trim_left_mm, geom.trim_top_mm  # trim left / top
    tr, tb = mw - geom.margin_mm, mh - geom.margin_mm  # trim right / bottom
    # The marks stop at the bleed boundary (one bleed inside the trim line).
    in_top, in_bottom = tt - geom.bleed_mm, tb + geom.bleed_mm
    in_left, in_right = tl - geom.bleed_mm, tr + geom.bleed_mm
    return [
        (tl, 0.0, tl, in_top),  # top-left  — vertical
        (0.0, tt, in_left, tt),  # top-left  — horizontal
        (tr, 0.0, tr, in_top),  # top-right — vertical
        (mw, tt, in_right, tt),  # top-right — horizontal
        (tl, mh, tl, in_bottom),  # bottom-left  — vertical
        (0.0, tb, in_left, tb),  # bottom-left  — horizontal
        (tr, mh, tr, in_bottom),  # bottom-right — vertical
        (mw, tb, in_right, tb),  # bottom-right — horizontal
    ]


def _registration_target(cx: float, cy: float, r: float, weight: float) -> str:
    """A printer's registration target (crosshair + ring) centred at cx,cy."""
    return (
        f'<g stroke="#000000" stroke-width="{_f(weight)}" fill="none">'
        f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}"/>'
        f'<line x1="{_f(cx - r * 1.7)}" y1="{_f(cy)}" x2="{_f(cx + r * 1.7)}" y2="{_f(cy)}"/>'
        f'<line x1="{_f(cx)}" y1="{_f(cy - r * 1.7)}" x2="{_f(cx)}" y2="{_f(cy + r * 1.7)}"/>'
        "</g>"
    )


def _colour_bar(geom: PrintGeometry, brand: dict | None) -> str:
    """A registration + CMYK colour bar across the bottom slug margin.

    Process patches (C, M, Y, K via the in-house transform) then the brand
    separations, each a swatch — standard print furniture a press operator
    eyeballs for ink density. Drawn centred between the bottom corner marks.
    """
    mw, mh = geom.media_w_mm, geom.media_h_mm
    band_h = geom.mark_len_mm  # the slug height
    if band_h < 2.0 or geom.margin_mm <= 0:
        return ""  # no room for furniture
    sw = min(band_h * 0.9, 4.0)  # square-ish swatch side
    gap = sw * 0.28
    y = mh - geom.mark_len_mm + (band_h - sw) / 2.0

    process = [
        ("C", cmyk_to_hex(1, 0, 0, 0)),
        ("M", cmyk_to_hex(0, 1, 0, 0)),
        ("Y", cmyk_to_hex(0, 0, 1, 0)),
        ("K", cmyk_to_hex(0, 0, 0, 1)),
    ]
    brand_rows = cmyk_separations(brand)[:4]
    swatches = [hx for _, hx in process] + [r["hex"] for r in brand_rows]
    total_w = len(swatches) * sw + (len(swatches) - 1) * gap
    # Keep the bar clear of the corner crop marks.
    avail = mw - 2 * (geom.margin_mm + 2.0)
    if total_w > avail or total_w <= 0:
        return ""
    x0 = (mw - total_w) / 2.0

    parts = [
        f'<rect x="{_f(x0 - gap)}" y="{_f(y - gap)}" '
        f'width="{_f(total_w + 2 * gap)}" height="{_f(sw + 2 * gap)}" '
        f'fill="#FFFFFF" stroke="#000000" stroke-width="{_f(geom.mark_weight_mm)}"/>'
    ]
    x = x0
    for hx in swatches:
        parts.append(
            f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(sw)}" height="{_f(sw)}" '
            f'fill="{hx}" stroke="#000000" stroke-width="{_f(geom.mark_weight_mm * 0.6)}"/>'
        )
        x += sw + gap
    return "".join(parts)


def print_furniture_svg(
    geom: PrintGeometry,
    *,
    brand: dict | None = None,
    crop_marks: bool = True,
    registration: bool = True,
    colour_bar: bool = True,
    info: bool = True,
    info_label: str = "",
) -> str:
    """A media-box-sized SVG overlay carrying every printer's mark.

    Pure vector, deterministic, ``pointer-events:none`` — it overlays the page
    without touching the artwork. mm are used as SVG user units.
    """
    mw, mh = geom.media_w_mm, geom.media_h_mm
    body: list[str] = []

    if crop_marks:
        lines = "".join(
            f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"/>'
            for (x1, y1, x2, y2) in _crop_mark_lines(geom)
        )
        body.append(
            f'<g stroke="#000000" stroke-width="{_f(geom.mark_weight_mm)}" '
            f'stroke-linecap="butt">{lines}</g>'
        )

    if registration and geom.mark_len_mm >= 2.0:
        r = min(geom.mark_len_mm * 0.32, 1.6)
        cy_top = geom.mark_len_mm / 2.0
        cy_bottom = mh - geom.mark_len_mm / 2.0
        body.append(_registration_target(mw / 2.0, cy_top, r, geom.mark_weight_mm))
        body.append(_registration_target(mw / 2.0, cy_bottom, r, geom.mark_weight_mm))

    if colour_bar:
        body.append(_colour_bar(geom, brand))

    if info:
        label = info_label or (
            f"TRIM {_f(geom.trim_w_mm)}×{_f(geom.trim_h_mm)}mm · "
            f"BLEED {_f(geom.bleed_mm)}mm · CMYK (uncalibrated) · MediaHub"
        )
        fs = max(min(geom.mark_len_mm * 0.55, 2.4), 1.6)
        body.append(
            f'<text x="{_f(mw / 2.0)}" y="{_f(geom.mark_len_mm / 2.0 + fs * 0.95)}" '
            f'font-family="monospace" font-size="{_f(fs)}" fill="#000000" '
            f'text-anchor="middle" opacity="0.78">{_esc(label)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_f(mw)} {_f(mh)}" '
        f'width="{_f(mw)}mm" height="{_f(mh)}mm" '
        f'shape-rendering="crispEdges">{"".join(body)}</svg>'
    )


# ---------------------------------------------------------------------------
# Bleed wrapper — turn any trim ``.sheet`` layout into a print-production page
# ---------------------------------------------------------------------------


def _print_css(geom: PrintGeometry, *, bleed_bg: str, sheet_selector: str) -> str:
    """Fill ``layouts/_print.css`` with this page's geometry + bleed colour."""
    template = _PRINT_CSS_PATH.read_text(encoding="utf-8")
    repl = {
        "MEDIA_W": _f(geom.media_w_mm),
        "MEDIA_H": _f(geom.media_h_mm),
        "BLEED_RECT_LEFT": _f(geom.bleed_rect_left_mm),
        "BLEED_RECT_TOP": _f(geom.bleed_rect_left_mm),
        "BLEED_RECT_W": _f(geom.bleed_rect_w_mm),
        "BLEED_RECT_H": _f(geom.bleed_rect_h_mm),
        "BLEED_BG": bleed_bg,
        "SHEET_SELECTOR": sheet_selector,
        "SHEET_LEFT": _f(geom.trim_left_mm),
        "SHEET_TOP": _f(geom.trim_top_mm),
    }
    missing = sorted(set(_find_placeholders(template)) - set(repl))
    if missing:
        raise ValueError(f"_print.css has unfilled placeholders: {missing}")
    out = template
    for k, v in repl.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def to_print_production(
    trim_html: str,
    geom: PrintGeometry,
    *,
    bleed_bg: str = _PAPER,
    sheet_selector: str = ".sheet",
    brand: dict | None = None,
    crop_marks: bool = True,
    registration: bool = True,
    colour_bar: bool = True,
    info: bool = True,
    info_label: str = "",
) -> str:
    """Wrap a trim-sized layout doc into a bleed + crop-marks print page.

    ``trim_html`` is a self-contained document whose artwork root matches
    ``sheet_selector`` (the W.12 layouts use ``.sheet``). The wrapper injects a
    ``<style>`` (from ``_print.css``) right before ``</head>`` that pins the
    media box, repositions the sheet into the trim area, and paints the bleed,
    plus an SVG marks overlay right before ``</body>``. The artwork itself is
    untouched, so this composes with *any* ``.sheet`` layout. Idempotent: a doc
    already wrapped (carrying the marks sentinel) is returned unchanged.
    """
    if "mh-print-marks" in trim_html:
        return trim_html

    style = (
        "<style>\n"
        + _print_css(geom, bleed_bg=bleed_bg, sheet_selector=sheet_selector)
        + "\n</style>"
    )
    svg = print_furniture_svg(
        geom,
        brand=brand,
        crop_marks=crop_marks,
        registration=registration,
        colour_bar=colour_bar,
        info=info,
        info_label=info_label,
    )
    marks = f'<div class="mh-print-marks" aria-hidden="true">{svg}</div>'

    out = trim_html
    if "</head>" in out:
        out = out.replace("</head>", style + "\n</head>", 1)
    else:  # pragma: no cover - the layouts always have a <head>
        out = style + out
    if "</body>" in out:
        out = out.replace("</body>", marks + "\n</body>", 1)
    else:  # pragma: no cover
        out = out + marks
    return out


# ---------------------------------------------------------------------------
# Print-production builders + exporters (certificate / poster)
# ---------------------------------------------------------------------------


def _poster_bleed_bg(brand: dict) -> str:
    """Layered bleed background for the poster: branded top strip, ink bottom
    strip, paper sides/base — so the masthead and footer bands bleed cleanly.
    """
    primary = _brand_hex(brand, "primary", "primary_colour", default="#0A2540")
    strip = f"{_DEFAULT_BLEED_MM + 1.5:.1f}mm"  # a touch past the bleed line
    return (
        f"linear-gradient({primary}, {primary}) top / 100% {strip} no-repeat, "
        f"linear-gradient({_INK}, {_INK}) bottom / 100% {strip} no-repeat, "
        f"{_PAPER}"
    )


def build_certificate_print_html(
    *,
    bleed_mm: float = _DEFAULT_BLEED_MM,
    crop_marks: bool = True,
    colour_bar: bool = True,
    **certificate_kwargs,
) -> str:
    """Print-production certificate: the W.12 certificate + bleed + crop marks.

    Accepts every ``build_certificate_html`` keyword; the certificate is paper
    to the edge, so the bleed background is simply the paper tone.
    """
    trim_html = build_certificate_html(**certificate_kwargs)
    geom = _sheet_geometry(bleed_mm=bleed_mm)
    return to_print_production(
        trim_html,
        geom,
        bleed_bg=_PAPER,
        brand=certificate_kwargs.get("brand") or {},
        crop_marks=crop_marks,
        colour_bar=colour_bar,
        info_label=f"PB CERTIFICATE · TRIM A4 · BLEED {_f(bleed_mm)}mm · MediaHub",
    )


def build_poster_print_html(
    *,
    bleed_mm: float = _DEFAULT_BLEED_MM,
    crop_marks: bool = True,
    colour_bar: bool = True,
    **poster_kwargs,
) -> str:
    """Print-production poster: the W.12 poster + bleed + crop marks.

    The poster has edge-to-edge masthead and footer bands, so the bleed
    background is a layered strip (brand top / ink bottom / paper sides).
    """
    brand = poster_kwargs.get("brand") or {}
    trim_html = build_poster_html(**poster_kwargs)
    geom = _sheet_geometry(bleed_mm=bleed_mm)
    return to_print_production(
        trim_html,
        geom,
        bleed_bg=_poster_bleed_bg(brand),
        brand=brand,
        crop_marks=crop_marks,
        colour_bar=colour_bar,
        info_label=f"CLUB POSTER · TRIM A4 · BLEED {_f(bleed_mm)}mm · MediaHub",
    )


def _render_print_pdf(html: str, output_path: Path, geom: PrintGeometry) -> Path:
    """Render a print-production doc at its exact bleed-expanded media box."""
    return render_html_to_pdf(
        html,
        Path(output_path),
        width=f"{_f(geom.media_w_mm)}mm",
        height=f"{_f(geom.media_h_mm)}mm",
    )


def export_certificate_print_pdf(
    output_path: Path,
    *,
    bleed_mm: float = _DEFAULT_BLEED_MM,
    crop_marks: bool = True,
    colour_bar: bool = True,
    cmyk: bool = False,
    **certificate_kwargs,
) -> Path:
    """Build + render a print-production certificate PDF (bleed + crop marks).

    With ``cmyk=True`` the RGB PDF is additionally converted to DeviceCMYK via
    Ghostscript (raises :class:`CmykUnavailable` if Ghostscript is absent).
    """
    html = build_certificate_print_html(
        bleed_mm=bleed_mm, crop_marks=crop_marks, colour_bar=colour_bar, **certificate_kwargs
    )
    geom = _sheet_geometry(bleed_mm=bleed_mm)
    out = _render_print_pdf(html, Path(output_path), geom)
    return cmyk_convert_pdf(out) if cmyk else out


def export_poster_print_pdf(
    output_path: Path,
    *,
    bleed_mm: float = _DEFAULT_BLEED_MM,
    crop_marks: bool = True,
    colour_bar: bool = True,
    cmyk: bool = False,
    **poster_kwargs,
) -> Path:
    """Build + render a print-production poster PDF (bleed + crop marks)."""
    html = build_poster_print_html(
        bleed_mm=bleed_mm, crop_marks=crop_marks, colour_bar=colour_bar, **poster_kwargs
    )
    geom = _sheet_geometry(bleed_mm=bleed_mm)
    out = _render_print_pdf(html, Path(output_path), geom)
    return cmyk_convert_pdf(out) if cmyk else out


# ---------------------------------------------------------------------------
# True DeviceCMYK conversion (Ghostscript when present; honest error otherwise)
# ---------------------------------------------------------------------------


class CmykUnavailable(RuntimeError):
    """Raised when DeviceCMYK conversion is requested but Ghostscript is absent.

    Honest by design (no fake CMYK): the caller still has the RGB
    print-production PDF — bleed + crop marks intact — which most digital print
    shops accept and convert with their own profiled RIP.
    """


def ghostscript_available() -> bool:
    """True if a Ghostscript binary (``gs``/``gswin*c``) is on PATH."""
    return _gs_binary() is not None


def _gs_binary() -> str | None:
    for name in ("gs", "gswin64c", "gswin32c"):
        path = shutil.which(name)
        if path:
            return path
    return None


def cmyk_convert_pdf(src_path: Path, dst_path: Path | None = None) -> Path:
    """Convert an RGB PDF to a DeviceCMYK PDF in place (or to ``dst_path``).

    Uses Ghostscript's ``pdfwrite`` with a CMYK process model. Raises
    :class:`CmykUnavailable` when Ghostscript is not installed — never a fake
    conversion. Returns the path to the CMYK PDF.
    """
    src_path = Path(src_path)
    if not src_path.exists():
        raise FileNotFoundError(src_path)
    gs = _gs_binary()
    if gs is None:
        raise CmykUnavailable(
            "DeviceCMYK conversion needs Ghostscript (gs), which is not installed. "
            "The RGB print PDF (bleed + crop marks) is still print-ready."
        )
    final = Path(dst_path) if dst_path else src_path
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(final.suffix + ".cmyk.tmp.pdf")
    cmd = [
        gs,
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dNOCACHE",
        "-sDEVICE=pdfwrite",
        "-dProcessColorModel=/DeviceCMYK",
        "-sColorConversionStrategy=CMYK",
        "-dOverrideICC=true",
        "-dPDFSETTINGS=/printer",
        f"-sOutputFile={tmp}",
        str(src_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:  # pragma: no cover
        try:
            tmp.unlink()
        except OSError:
            pass
        raise CmykUnavailable(f"Ghostscript CMYK conversion failed: {e}") from e
    tmp.replace(final)
    return final
