"""brand/newsletter_renderer.py — wrap a Turn-Into newsletter artefact
into email-ready HTML, plaintext, or a downloadable ZIP.

The Turn-Into `build_parent_newsletter` builder already produces a
plaintext block and a small `<section>` HTML snippet. That's enough
to display on the pack page but it isn't usable as an actual email
because email clients aggressively strip `<head>` and most external
stylesheets — so anything sender-safe needs inline styles, a full
HTML doctype, and a fixed-width table-based layout for older clients.

This module owns the rendering. It is consumed by the
`/api/runs/<run_id>/newsletter` endpoint, which lets the user
download either format directly or grab a ZIP with both.

Brand alignment: the rendered email picks up the org's
`brand_primary`, logo URL and display name from the profile
(`brand_context_for_llm` already exposes these to the upstream
caption generator, so the artefact text is already on-brand; this
renderer only handles the visual chrome).
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from html import escape
from typing import Optional


# ---------------------------------------------------------------------------
# Profile / artefact field access (tolerant of dataclasses + dicts)
# ---------------------------------------------------------------------------


def _get(obj, name: str, default=""):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Plaintext
# ---------------------------------------------------------------------------


def render_plaintext(artefact: dict) -> str:
    """Return the plaintext body of the newsletter artefact, cleaned
    up for a copy-paste-into-mailchimp / email-client workflow."""
    captions = (artefact or {}).get("captions") or {}
    body = captions.get("plain_text") or captions.get("default") or ""
    body = (body or "").strip()
    # Collapse runs of >2 newlines so the plaintext stays compact.
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body


# ---------------------------------------------------------------------------
# Email-ready HTML
# ---------------------------------------------------------------------------

_BASE_FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "Roboto, Oxygen, Ubuntu, Helvetica, Arial, sans-serif"
)


def _safe_hex(value: Optional[str], fallback: str) -> str:
    """Accept a hex colour or return fallback. Strips quoting noise."""
    if not value or not isinstance(value, str):
        return fallback
    v = value.strip().lower()
    if not v.startswith("#"):
        v = "#" + v
    if re.match(r"^#[0-9a-f]{6}$", v):
        return v
    if re.match(r"^#[0-9a-f]{3}$", v):
        return "#" + "".join(c * 2 for c in v[1:])
    return fallback


def _resolve_email_primary(profile) -> str:
    """Resolve the header band's primary colour.

    Mirrors ``_resolve_email_secondary`` so the email honours the
    club's CONFIRMED brand colour over the MD3 theme-store derivation.
    The theme store tone-shifts the seed for accessibility (a navy
    ``#003C71`` becomes a washed-out ``#426089``), so a confirmed brand
    primary must win — otherwise the header renders off-brand.

    Order of preference:
      1. ``brand_palette_manual["primary"]``    — explicit user override
      2. ``brand_palette_extracted["primary"]`` — AI's confirmed pick
      3. theme-store light-scheme primary       — derived fallback
      4. legacy ``brand_primary`` field
      5. Stage A default navy

    The theme-store value is third (not first), matching the secondary
    resolver: a club that confirmed a specific primary should see that
    exact colour, not its tonal-spot derivative.
    """
    manual = _get(profile, "brand_palette_manual") or {}
    extracted = _get(profile, "brand_palette_extracted") or {}
    for src in (manual, extracted):
        if isinstance(src, dict):
            v = src.get("primary")
            if isinstance(v, str) and v.startswith("#"):
                return _safe_hex(v, "#0A2540")
    pid = _get(profile, "profile_id")
    if pid:
        try:
            from mediahub.theming.theme_store import read_theme, palette_for_email

            theme_json = read_theme(pid)
            if theme_json:
                p = palette_for_email(theme_json)
                hex_value = p.get("primary")
                if isinstance(hex_value, str) and hex_value.startswith("#"):
                    return _safe_hex(hex_value, "#0A2540")
        except Exception:
            pass
    return _safe_hex(_get(profile, "brand_primary"), "#0A2540")


def _resolve_email_secondary(profile) -> str:
    """Resolve the secondary colour the email accent line + footer
    sub-rule should use. Honours the user's confirmed secondary so a
    navy + gold club shows the gold strip instead of MediaHub default.

    Order of preference:
      1. ``brand_palette_manual["secondary"]`` — explicit override
      2. ``brand_palette_extracted["secondary"]`` — AI's confirmed pick
      3. theme-store secondary_container (HCT-derived from primary)
      4. legacy ``brand_secondary`` field
      5. neutral slate

    The theme-store value is third (not first) because HCT derives the
    secondary container from the primary's hue — so a navy + gold club
    that confirmed "secondary = gold" would otherwise see a muted navy
    band as the "secondary", erasing the second brand colour.
    """
    manual = _get(profile, "brand_palette_manual") or {}
    extracted = _get(profile, "brand_palette_extracted") or {}
    for src in (manual, extracted):
        if isinstance(src, dict):
            v = src.get("secondary")
            if isinstance(v, str) and v.startswith("#"):
                return _safe_hex(v, "#475569")
    pid = _get(profile, "profile_id")
    if pid:
        try:
            from mediahub.theming.theme_store import read_theme, palette_for_email

            theme_json = read_theme(pid)
            if theme_json:
                p = palette_for_email(theme_json)
                hex_value = p.get("secondary")
                if isinstance(hex_value, str) and hex_value.startswith("#"):
                    return _safe_hex(hex_value, "#475569")
        except Exception:
            pass
    return _safe_hex(_get(profile, "brand_secondary"), "#475569")


def _para_html(text: str) -> str:
    """Convert plaintext (double-newline-separated paragraphs) into
    a series of <p> tags with inline styles. Single newlines become
    <br> for readability in email clients."""
    paragraphs = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    out_parts: list[str] = []
    for p in paragraphs:
        # Treat single newlines inside a paragraph as soft line breaks.
        esc = escape(p).replace("\n", "<br>")
        out_parts.append(
            '<p style="margin:0 0 16px 0;font-family:'
            + _BASE_FONT
            + ';font-size:15px;line-height:1.6;color:#1f2937">'
            + esc
            + "</p>"
        )
    return "\n".join(out_parts)


def render_email_html(
    artefact: dict,
    *,
    profile=None,
    meet_summary: Optional[dict] = None,
) -> str:
    """Return a full standalone HTML email body for the newsletter
    artefact. Uses inline styles + table-based layout so it renders
    consistently in Gmail / Outlook / Apple Mail / etc.

    Args:
        artefact: a Turn-Into ``parent_newsletter`` artefact dict.
        profile: a ClubProfile (or dict) — used for branding chrome
            (display_name, brand_primary, brand_logo_url).
        meet_summary: optional {name, start_date, venue}.
    """
    plain = render_plaintext(artefact)
    body_html = _para_html(plain)

    org_name = _get(profile, "display_name") or _get(profile, "short_name") or ""
    # Phase 1.6 Stage G — prefer theme-store light primary over legacy field.
    brand_primary = _resolve_email_primary(profile)
    brand_secondary = _resolve_email_secondary(profile)
    logo_url = _get(profile, "brand_logo_url") or ""

    meet_summary = meet_summary or {}
    meet_name = (meet_summary.get("name") or artefact.get("title") or "Meet update").strip()
    meet_date = (meet_summary.get("start_date") or "").strip()
    venue = (meet_summary.get("venue") or "").strip()
    title_line = escape(meet_name)
    sub_bits = [s for s in (meet_date, venue) if s]
    subtitle = escape(" · ".join(sub_bits)) if sub_bits else ""

    logo_html = ""
    if logo_url:
        logo_html = (
            '<img src="' + escape(logo_url) + '" alt="" '
            'width="48" height="48" '
            'style="display:block;border:0;border-radius:8px;'
            'margin:0 auto 12px auto"/>'
        )

    footer_org = escape(org_name) if org_name else ""
    footer_html = (
        '<p style="margin:24px 0 0 0;font-family:'
        + _BASE_FONT
        + ';font-size:12px;color:#6b7280;text-align:center;line-height:1.5">'
        + (("Sent on behalf of " + footer_org + ". ") if footer_org else "")
        + "Generated by MediaHub."
        + "</p>"
    )

    # Table-based outer scaffold — required for legacy Outlook.
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{title_line}</title>\n"
        "</head>\n"
        '<body style="margin:0;padding:0;background:#f3f4f6;'
        "font-family:" + _BASE_FONT + ';color:#1f2937">\n'
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'width="100%" style="background:#f3f4f6">\n'
        '<tr><td align="center" style="padding:24px 16px">\n'
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'width="600" style="max-width:600px;background:#ffffff;'
        "border-radius:12px;overflow:hidden;"
        'box-shadow:0 1px 3px rgba(0,0,0,0.08)">\n'
        # Header band
        '<tr><td style="padding:28px 32px 18px 32px;background:'
        + brand_primary
        + ';text-align:center;color:#ffffff">\n'
        + logo_html
        + '<div style="font-family:'
        + _BASE_FONT
        + ";font-size:11px;"
        'text-transform:uppercase;letter-spacing:0.12em;opacity:0.85">'
        + (escape(org_name) if org_name else "Club update")
        + "</div>\n"
        + '<div style="font-family:'
        + _BASE_FONT
        + ";font-size:22px;"
        'font-weight:700;margin-top:6px">'
        + title_line
        + "</div>\n"
        + (
            (
                '<div style="font-family:' + _BASE_FONT + ";font-size:13px;"
                'margin-top:6px;opacity:0.85">' + subtitle + "</div>\n"
            )
            if subtitle
            else ""
        )
        + "</td></tr>\n"
        # Brand-secondary accent band. Without this the user's
        # confirmed secondary never appeared in the rendered email —
        # the header used the primary, the body used neutral ink, the
        # footer used grey. A 4px strip is non-invasive but visually
        # confirms the second brand colour carried through.
        '<tr><td style="padding:0;background:'
        + brand_secondary
        + ';height:4px;line-height:4px;font-size:0">&nbsp;</td></tr>\n'
        # Body
        '<tr><td style="padding:28px 32px 8px 32px">\n' + body_html + "</td></tr>\n"
        # Footer
        '<tr><td style="padding:0 32px 28px 32px;'
        "border-top:1px solid " + brand_secondary + '">\n' + footer_html + "</td></tr>\n"
        "</table>\n"
        "</td></tr>\n"
        "</table>\n"
        "</body>\n"
        "</html>\n"
    )


# ---------------------------------------------------------------------------
# ZIP — both formats together
# ---------------------------------------------------------------------------


def render_zip(
    artefact: dict,
    *,
    profile=None,
    meet_summary: Optional[dict] = None,
    base_name: str = "newsletter",
) -> bytes:
    """Return a ZIP containing both the HTML email and the plaintext
    body. Suitable for download via Content-Disposition."""
    html_body = render_email_html(
        artefact,
        profile=profile,
        meet_summary=meet_summary,
    )
    text_body = render_plaintext(artefact)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base_name}.html", html_body)
        zf.writestr(f"{base_name}.txt", text_body)
        zf.writestr(
            "README.txt",
            "MediaHub newsletter export.\n\n"
            f"Generated: {_now_iso()}\n\n"
            "- newsletter.html — full HTML email body. Open in a "
            "browser to preview, or paste the markup into Mailchimp / "
            "ConvertKit / your email tool of choice.\n"
            "- newsletter.txt — plaintext fallback.\n",
        )
    return buf.getvalue()


def safe_filename_for(meet_name: str) -> str:
    """Produce a filesystem-safe slug from a meet name."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", (meet_name or "newsletter")).strip("-").lower()
    return s[:60] or "newsletter"


__all__ = [
    "render_plaintext",
    "render_email_html",
    "render_zip",
    "safe_filename_for",
]
