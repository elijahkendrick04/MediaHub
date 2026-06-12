"""A4 print exports — PB certificates + noticeboard posters (roadmap W.12).

Renders print-ready PDFs via the same headless-Chromium (Playwright) path the
still-graphic renderer uses, but through ``page.pdf`` instead of a screenshot.

Design notes
------------
- **Print is light.** The dark-first product palette applies to the web UI,
  not to paper: certificates and posters use a warm paper background with
  dark ink so they stay credible on a mono laser printer — colour carries
  brand, never information.
- Layouts live beside the social-card layouts (``layouts/print_*.html``) and
  use the same ``{{PLACEHOLDER}}`` string substitution (intentionally not
  Jinja, matching ``render.py``).
- Typography is the repo's SELF-HOSTED font stack from ``_shared.css``: the
  relative ``url(fonts/...)`` declarations are rewritten to absolute
  ``file://`` URLs exactly like ``render.py`` does, and the page is navigated
  as a real ``file://`` document so Chromium is allowed to fetch them. No
  Google Fonts CDN, ever.
- Brand colours come from the caller-supplied ``brand`` mapping (BrandKit
  shaped — ``primary``/``primary_colour`` etc.) so print matches the cards.
- Every piece of interpolated text is HTML-escaped; the layouts never trust
  caller-supplied strings.

Public API
----------
- ``render_html_to_pdf(html, output_path, *, page_format="A4",
  landscape=False)`` → write a PDF, return its path.
- ``build_certificate_html(...)`` → filled ``print_certificate_a4.html``.
- ``build_poster_html(...)`` → filled ``print_poster_a4.html``.
- ``export_certificate_pdf(...)`` / ``export_poster_pdf(...)`` → build the
  HTML and render the PDF in one call.
"""

from __future__ import annotations

import re
from pathlib import Path

from mediahub.graphic_renderer.render import LAYOUTS_DIR, darken, html_escape as _esc

_SHARED_CSS_PATH = LAYOUTS_DIR / "_shared.css"
_CERTIFICATE_LAYOUT = LAYOUTS_DIR / "print_certificate_a4.html"
_POSTER_LAYOUT = LAYOUTS_DIR / "print_poster_a4.html"

# Fixed ink/paper tones shared by both print layouts (light, mono-safe).
_PAPER = "#FDFBF6"
_INK = "#1C1B18"


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
) -> Path:
    """Headless-Chromium print-to-PDF; returns the written path.

    Same sync-playwright pattern as ``render.render_html_to_png``: the HTML is
    written beside the output and navigated as a real ``file://`` document
    (``set_content`` would leave the page on about:blank, where Chromium
    refuses to fetch the self-hosted file:// fonts), and the render waits for
    ``document.fonts.ready`` before printing. ``print_background=True`` keeps
    the brand bands and paper tone on the page.
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
            page.pdf(
                path=str(output_path),
                format=page_format,
                landscape=landscape,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
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
