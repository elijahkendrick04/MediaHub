"""email_design.render — a :class:`NewsletterSpec` → email-safe HTML (+ plaintext).

Email clients are a hostile rendering target: Outlook routes HTML through Word,
Gmail strips ``<style>`` and ``class`` from the body in some contexts, Apple Mail
auto-darkens, and external images are blocked by default. So this renderer obeys
the email-HTML contract end to end:

* **table-based layout** — every structural box is a ``<table role="presentation">``,
  never a flex/grid ``<div>``;
* **inlined CSS** — every visual style is an inline ``style=""`` on the element
  (the ``<head> <style>`` block is *progressive enhancement only*: dark-mode and
  mobile overrides that clients which support them honour, and the rest safely
  ignore);
* **dark-mode aware** — ``color-scheme`` meta + a ``prefers-color-scheme: dark``
  block reskins the neutral chrome (never the brand colours);
* **bulletproof buttons** — a ``bgcolor`` table cell + padded anchor so the CTA is
  a real, clickable, filled button in Outlook too;
* **image fallbacks** — every ``<img>`` carries ``alt``, explicit ``width`` and
  ``border:0;display:block``; a missing image degrades to its caption text.

The render is **pure and deterministic**: the same spec + same palette produces
byte-identical HTML (no timestamps, no randomness), which is what lets the
output be snapshot-tested across client quirks.
"""

from __future__ import annotations

from typing import Any

from markupsafe import escape as _escape

from .models import EmailBlock, NewsletterSpec, Section
from .theme import EMAIL_FONT_STACK, email_palette, mix_hex

_FONT = EMAIL_FONT_STACK


def _esc(s: Any) -> str:
    return str(_escape("" if s is None else str(s)))


def _esc_attr(s: Any) -> str:
    """Escape for an attribute value (e.g. an href). markupsafe escapes quotes."""
    return str(_escape("" if s is None else str(s)))


_ALLOWED_SCHEMES = ("http://", "https://", "mailto:")


def _safe_href(value: Any) -> str:
    """URL-scheme whitelist for rendered hrefs (stored-XSS defence).

    Attribute escaping alone keeps a ``javascript:`` URL intact — it executes
    on click in the same-origin preview and on the public page. So, mirroring
    the align/size enum whitelisting in :mod:`.models`, only ``http``/``https``
    /``mailto`` URLs plus site-relative paths (``/…``) and fragments (``#…``)
    survive; anything else renders as ``""`` (the block degrades to plain text
    or an unlinked element).
    """
    s = str(value or "").strip()
    if not s:
        return ""
    # control chars can smuggle a scheme past a prefix check ("java\tscript:")
    compact = "".join(ch for ch in s if ord(ch) > 32).lower()
    if compact.startswith(("/", "#")) or compact.startswith(_ALLOWED_SCHEMES):
        return s
    return ""


def _safe_src(value: Any) -> str:
    """Like :func:`_safe_href` for image ``src``, additionally allowing inline
    ``data:image/`` URIs (defence-in-depth for the ``<img>`` sink)."""
    s = str(value or "").strip()
    compact = "".join(ch for ch in s if ord(ch) > 32).lower()
    if compact.startswith("data:image/"):
        return s
    return _safe_href(s)


def _safe_int(value: Any, default: int) -> int:
    """Coerce a saved prop to int; malformed values degrade to ``default``
    instead of 500ing the html/text export (forward-compatible no-op stance)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _band_colors(pal: dict, background: str) -> dict:
    """Resolve the foreground colour set for one section band.

    Loose flowing content (headings, text, lists, quotes, fixtures, buttons) is
    painted directly on the band, so an **accent** (brand-coloured) band must
    invert its content to the on-brand ink and flip the button to a light fill —
    otherwise brand-on-brand content is invisible. Self-contained components (a
    ``card``, a ``sponsor`` box) keep their own surface and read from ``pal``.
    """
    if background == "accent":
        on = pal["on_brand"]
        return {
            "ink": on,
            "muted": mix_hex(on, pal["brand"], 0.30),  # dimmed on-brand
            "accent": on,
            "link": on,
            "stat": on,
            "btn_fill": pal["panel"],
            "btn_text": pal["brand"],
            "rule": mix_hex(on, pal["brand"], 0.62),
        }
    # plain / surface bands read from the base palette
    return {
        "ink": pal["ink"],
        "muted": pal["muted"],
        "accent": pal["accent"],
        "link": pal["brand"],
        "stat": pal["brand"],
        "btn_fill": pal["brand"],
        "btn_text": pal["on_brand"],
        "rule": pal["border"],
    }


# ---------------------------------------------------------------------------
# Block renderers — each returns a self-contained HTML fragment that flows
# vertically inside a section's <td>.
# ---------------------------------------------------------------------------


def _b_heading(p: dict, pal: dict, band: dict) -> str:
    level = min(3, max(1, _safe_int(p.get("level"), 2)))
    size = {1: 24, 2: 19, 3: 16}.get(level, 19)
    return (
        f'<h{level} class="mh-ink" style="margin:0 0 12px 0;font-family:{_FONT};'
        f'font-size:{size}px;line-height:1.3;font-weight:700;color:{band["ink"]}">'
        f'{_esc(p.get("text", ""))}</h{level}>'
    )


def _b_text(p: dict, pal: dict, band: dict) -> str:
    align = p.get("align") if p.get("align") in ("left", "center", "right") else "left"
    body = _esc(p.get("text", "")).replace("\n", "<br>")
    if not body:
        return ""
    return (
        f'<p class="mh-ink" style="margin:0 0 16px 0;font-family:{_FONT};font-size:15px;'
        f'line-height:1.6;color:{band["ink"]};text-align:{align}">{body}</p>'
    )


def _b_list(p: dict, pal: dict, band: dict) -> str:
    items = [i for i in (p.get("items") or []) if str(i).strip()]
    if not items:
        return ""
    tag = "ol" if p.get("ordered") else "ul"
    lis = "".join(f'<li style="margin:0 0 6px 0">{_esc(i)}</li>' for i in items)
    return (
        f'<{tag} class="mh-ink" style="margin:0 0 16px 0;padding:0 0 0 22px;'
        f'font-family:{_FONT};font-size:15px;line-height:1.6;color:{band["ink"]}">{lis}</{tag}>'
    )


def _b_button(p: dict, pal: dict, band: dict) -> str:
    label = p.get("label") or ""
    href = _safe_href(p.get("href"))
    if not label:
        return ""
    align = p.get("align") if p.get("align") in ("left", "center", "right") else "left"
    href_attr = _esc_attr(href) if href else "#"
    # Bulletproof button: bgcolor cell (Outlook fills it) + padded anchor (modern
    # clients get the click target). mso-padding-alt nudges Outlook's padding. On
    # an accent band the fill flips to a light surface so the CTA never vanishes.
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'align="{align}" style="margin:4px 0 18px 0">'
        f'<tr><td align="center" bgcolor="{band["btn_fill"]}" '
        f'style="border-radius:8px;mso-padding-alt:12px 24px">'
        f'<a href="{href_attr}" target="_blank" '
        f'style="display:inline-block;padding:12px 24px;font-family:{_FONT};'
        f'font-size:15px;font-weight:600;line-height:1;color:{band["btn_text"]};'
        f'text-decoration:none;border-radius:8px">{_esc(label)}</a>'
        f"</td></tr></table>"
    )


def _img_tag(src: str, alt: str, pal: dict, *, width: int = 0, radius: int = 0) -> str:
    w = f' width="{int(width)}"' if width else ' width="100%"'
    rad = f"border-radius:{int(radius)}px;" if radius else ""
    return (
        f'<img src="{_esc_attr(_safe_src(src))}" alt="{_esc_attr(alt)}"{w} '
        f'style="display:block;border:0;outline:none;text-decoration:none;'
        f"max-width:100%;height:auto;{rad}"
        f'background:{pal["surface"]}"/>'
    )


def _b_image(p: dict, pal: dict, band: dict) -> str:
    src = _safe_src(p.get("src"))
    alt = p.get("alt") or ""
    caption = p.get("caption") or ""
    href = _safe_href(p.get("href"))
    width = _safe_int(p.get("width"), 0)
    if not src:
        # Degrade to alt/caption text rather than emit a broken image.
        fallback = caption or alt
        return _b_text({"text": fallback}, pal, band) if fallback else ""
    img = _img_tag(src, alt, pal, width=width, radius=8)
    if href:
        img = f'<a href="{_esc_attr(href)}" target="_blank" style="text-decoration:none">{img}</a>'
    cap = ""
    if caption:
        cap = (
            f'<div class="mh-muted" style="margin:6px 0 0 0;font-family:{_FONT};'
            f'font-size:12px;line-height:1.4;color:{band["muted"]}">{_esc(caption)}</div>'
        )
    return f'<div style="margin:0 0 18px 0">{img}{cap}</div>'


def _b_card(p: dict, pal: dict, band: dict) -> str:
    title = p.get("title") or ""
    body = p.get("body") or ""
    src = _safe_src(p.get("src"))
    alt = p.get("alt") or ""
    href = _safe_href(p.get("href"))
    cta = p.get("cta") or ""
    img_html = ""
    if src:
        img_html = f'<tr><td style="padding:0">{_img_tag(src, alt, pal, radius=0)}</td></tr>'
    title_html = ""
    if title:
        title_html = (
            f'<div class="mh-ink" style="font-family:{_FONT};font-size:17px;'
            f'font-weight:700;line-height:1.3;color:{pal["ink"]};margin:0 0 6px 0">'
            f"{_esc(title)}</div>"
        )
    body_html = ""
    if body:
        body_html = (
            f'<div class="mh-ink" style="font-family:{_FONT};font-size:14px;'
            f'line-height:1.55;color:{pal["ink"]}">{_esc(body).replace(chr(10), "<br>")}</div>'
        )
    cta_html = ""
    if cta and href:
        cta_html = (
            f'<div style="margin:10px 0 0 0"><a href="{_esc_attr(href)}" target="_blank" '
            f'style="font-family:{_FONT};font-size:14px;font-weight:600;'
            f'color:{pal["brand"]};text-decoration:none">{_esc(cta)} &rarr;</a></div>'
        )
    inner = (
        f'<tr><td class="mh-pad" style="padding:16px 18px">'
        f"{title_html}{body_html}{cta_html}</td></tr>"
    )
    return (
        f'<table role="presentation" class="mh-card" cellspacing="0" cellpadding="0" '
        f'border="0" width="100%" style="margin:0 0 18px 0;background:{pal["panel"]};'
        f'border:1px solid {pal["border"]};border-radius:10px;overflow:hidden">'
        f"{img_html}{inner}</table>"
    )


def _b_stat_row(p: dict, pal: dict, band: dict) -> str:
    stats = [
        s for s in (p.get("stats") or []) if isinstance(s, dict) and str(s.get("value", "")).strip()
    ]
    if not stats:
        return ""
    cells = ""
    for s in stats:
        cells += (
            f'<td align="center" valign="top" class="mh-pad" '
            f'style="padding:6px 8px">'
            f'<div class="mh-ink" style="font-family:{_FONT};font-size:24px;'
            f'font-weight:800;line-height:1.1;color:{band["stat"]}">'
            f'{_esc(s.get("value", ""))}</div>'
            f'<div class="mh-muted" style="font-family:{_FONT};font-size:12px;'
            f'line-height:1.3;color:{band["muted"]};text-transform:uppercase;'
            f'letter-spacing:0.04em;margin-top:4px">{_esc(s.get("label", ""))}</div>'
            f"</td>"
        )
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'width="100%" style="margin:0 0 18px 0"><tr>{cells}</tr></table>'
    )


def _b_quote(p: dict, pal: dict, band: dict) -> str:
    body = _esc(p.get("text", ""))
    if not body:
        return ""
    attribution = p.get("attribution") or ""
    attr_html = ""
    if attribution:
        attr_html = (
            f'<div class="mh-muted" style="margin:8px 0 0 0;font-family:{_FONT};'
            f'font-size:13px;color:{band["muted"]}">&mdash; {_esc(attribution)}</div>'
        )
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'width="100%" style="margin:0 0 18px 0"><tr>'
        f'<td style="padding:4px 0 4px 16px;border-left:3px solid {band["accent"]}">'
        f'<div class="mh-ink" style="font-family:{_FONT};font-size:16px;'
        f'line-height:1.5;font-style:italic;color:{band["ink"]}">{body}</div>'
        f"{attr_html}</td></tr></table>"
    )


def _b_fixtures(p: dict, pal: dict, band: dict) -> str:
    items = [
        it
        for it in (p.get("items") or [])
        if isinstance(it, dict) and (it.get("name") or it.get("date"))
    ]
    if not items:
        return ""
    title = p.get("title") or ""
    title_html = ""
    if title:
        title_html = (
            f'<div class="mh-ink" style="font-family:{_FONT};font-size:15px;'
            f'font-weight:700;color:{band["ink"]};margin:0 0 10px 0">{_esc(title)}</div>'
        )
    rows = ""
    for it in items:
        date = it.get("date") or ""
        name = it.get("name") or ""
        venue = it.get("venue") or ""
        meta_bits = " &middot; ".join(b for b in (venue,) if b)
        meta_html = (
            f'<div class="mh-muted" style="font-family:{_FONT};font-size:12px;'
            f'color:{band["muted"]};margin-top:2px">{_esc(meta_bits)}</div>'
            if meta_bits
            else ""
        )
        rows += (
            f'<tr><td valign="top" width="84" '
            f'style="padding:8px 12px 8px 0;font-family:{_FONT};font-size:13px;'
            f'font-weight:700;color:{band["accent"]};white-space:nowrap">{_esc(date)}</td>'
            f'<td valign="top" style="padding:8px 0;border-top:1px solid {band["rule"]}">'
            f'<div class="mh-ink" style="font-family:{_FONT};font-size:14px;'
            f'font-weight:600;color:{band["ink"]}">{_esc(name)}</div>{meta_html}</td></tr>'
        )
    return (
        f"{title_html}"
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'width="100%" style="margin:0 0 18px 0">{rows}</table>'
    )


def _b_sponsor(p: dict, pal: dict, band: dict) -> str:
    name = p.get("name") or ""
    if not name and not p.get("logo_src"):
        return ""
    label = p.get("label") or "In partnership with"
    logo_src = _safe_src(p.get("logo_src"))
    href = _safe_href(p.get("href"))
    logo_html = ""
    if logo_src:
        logo_html = _img_tag(logo_src, name or "Sponsor", pal, width=160)
        logo_html = f'<div style="margin:8px auto 0 auto;max-width:160px">{logo_html}</div>'
    else:
        logo_html = (
            f'<div class="mh-ink" style="font-family:{_FONT};font-size:18px;'
            f'font-weight:700;color:{pal["ink"]};margin-top:4px">{_esc(name)}</div>'
        )
    if href:
        logo_html = (
            f'<a href="{_esc_attr(href)}" target="_blank" style="text-decoration:none">'
            f"{logo_html}</a>"
        )
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'width="100%" style="margin:0 0 8px 0"><tr><td align="center" '
        f'class="mh-pad" style="padding:18px;background:{pal["surface"]};border-radius:10px">'
        f'<div class="mh-muted" style="font-family:{_FONT};font-size:11px;'
        f'text-transform:uppercase;letter-spacing:0.1em;color:{pal["muted"]}">'
        f"{_esc(label)}</div>{logo_html}</td></tr></table>"
    )


def _b_divider(p: dict, pal: dict, band: dict) -> str:
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'width="100%" style="margin:8px 0 18px 0"><tr><td '
        f'style="border-top:1px solid {band["rule"]};font-size:0;line-height:0">&nbsp;</td>'
        f"</tr></table>"
    )


def _b_spacer(p: dict, pal: dict, band: dict) -> str:
    h = {"sm": 8, "md": 18, "lg": 32}.get(p.get("size"), 18)
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'width="100%"><tr><td height="{h}" style="height:{h}px;font-size:0;'
        f'line-height:0">&nbsp;</td></tr></table>'
    )


_RENDERERS = {
    "heading": _b_heading,
    "text": _b_text,
    "list": _b_list,
    "button": _b_button,
    "image": _b_image,
    "card": _b_card,
    "stat_row": _b_stat_row,
    "quote": _b_quote,
    "fixtures": _b_fixtures,
    "sponsor": _b_sponsor,
    "divider": _b_divider,
    "spacer": _b_spacer,
}


def _render_block(block: EmailBlock, pal: dict, band: dict) -> str:
    fn = _RENDERERS.get(block.kind)
    if fn is None:
        return ""  # unknown kind → forward-compatible no-op
    return fn(block.props or {}, pal, band)


def _render_section(section: Section, pal: dict) -> str:
    band = _band_colors(pal, section.background)
    inner = "".join(_render_block(b, pal, band) for b in section.blocks)
    if not inner.strip():
        return ""
    if section.background == "accent":
        bg = pal["brand"]
        cls = "mh-accentband"
    elif section.background == "surface":
        bg = pal["surface"]
        cls = "mh-surfaceband"
    else:
        bg = pal["panel"]
        cls = "mh-panel"
    return (
        f'<tr><td class="{cls} mh-pad" style="padding:24px 32px;background:{bg}">'
        f"{inner}</td></tr>"
    )


# ---------------------------------------------------------------------------
# Masthead + footer chrome
# ---------------------------------------------------------------------------


def _masthead(spec: NewsletterSpec, pal: dict, *, logo_url: str, org_name: str) -> str:
    logo_html = ""
    if logo_url:
        logo_html = (
            f'<img src="{_esc_attr(logo_url)}" alt="{_esc_attr(org_name)}" '
            f'width="52" height="52" style="display:block;border:0;border-radius:8px;'
            f'margin:0 auto 12px auto"/>'
        )
    kicker = spec.kicker or (org_name and f"{org_name} newsletter") or "Club update"
    kicker_html = (
        f'<div style="font-family:{_FONT};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:0.12em;opacity:0.85">{_esc(kicker)}</div>'
    )
    title_html = (
        f'<div style="font-family:{_FONT};font-size:23px;font-weight:800;'
        f'margin-top:6px;line-height:1.25">{_esc(spec.title)}</div>'
    )
    subtitle_html = ""
    if spec.subtitle:
        subtitle_html = (
            f'<div style="font-family:{_FONT};font-size:13px;margin-top:6px;'
            f'opacity:0.85">{_esc(spec.subtitle)}</div>'
        )
    return (
        f'<tr><td class="mh-pad" style="padding:30px 32px 20px 32px;'
        f'background:{pal["brand"]};text-align:center;color:{pal["on_brand"]}">'
        f"{logo_html}{kicker_html}{title_html}{subtitle_html}</td></tr>"
        # brand-accent strip — confirms the club's second colour carried through.
        f'<tr><td style="padding:0;background:{pal["accent"]};height:4px;'
        f'line-height:4px;font-size:0">&nbsp;</td></tr>'
    )


def _footer(spec: NewsletterSpec, pal: dict, *, org_name: str) -> str:
    sent_line = f"Sent on behalf of {_esc(org_name)}. " if org_name else ""
    # Unsubscribe placeholder — the club's list tool injects the real link on send;
    # export-first, so we surface an honest placeholder rather than a dead link.
    unsub = (
        '<span style="text-decoration:underline">Unsubscribe</span> via your club’s '
        "mailing list."
    )
    return (
        f'<tr><td class="mh-pad" style="padding:22px 32px 30px 32px;'
        f'border-top:1px solid {pal["border"]};text-align:center">'
        f'<p class="mh-muted" style="margin:0;font-family:{_FONT};font-size:12px;'
        f'line-height:1.5;color:{pal["muted"]}">{sent_line}Made with MediaHub.</p>'
        f'<p class="mh-muted" style="margin:8px 0 0 0;font-family:{_FONT};font-size:11px;'
        f'line-height:1.5;color:{pal["muted"]}">{unsub}</p>'
        f"</td></tr>"
    )


def _head_style(pal: dict) -> str:
    """The progressive-enhancement <style>: dark-mode + mobile. Clients that
    honour it reskin the neutral chrome; the rest fall back to the inline
    light styles. Brand colours are never flipped."""
    return (
        "<style>\n"
        ":root{color-scheme:light dark;supported-color-schemes:light dark;}\n"
        "@media (prefers-color-scheme: dark){\n"
        ".mh-body{background:#0b0b0f !important;}\n"
        ".mh-panel{background:#15161c !important;}\n"
        ".mh-surfaceband{background:#1b1d25 !important;}\n"
        ".mh-card{background:#1b1d25 !important;border-color:#2a2d38 !important;}\n"
        ".mh-ink{color:#e8eaf0 !important;}\n"
        ".mh-muted{color:#9aa3b2 !important;}\n"
        "}\n"
        "@media only screen and (max-width:600px){\n"
        ".mh-container{width:100% !important;}\n"
        ".mh-pad{padding-left:20px !important;padding-right:20px !important;}\n"
        "}\n"
        "</style>"
    )


def _preheader(text: str) -> str:
    if not text:
        return ""
    # Hidden in the body, shown by inboxes beside the subject. The trailing
    # zero-width chars push the real content out of the preview tail.
    pad = "&#847;&zwnj;&nbsp;" * 12
    return (
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
        'font-size:1px;line-height:1px;color:#f3f4f6;opacity:0">'
        f"{_esc(text)}{pad}</div>"
    )


def render_email_html(spec: NewsletterSpec, *, profile: Any = None, brand_kit: Any = None) -> str:
    """Render ``spec`` to a complete, standalone, email-safe HTML document.

    ``profile`` / ``brand_kit`` supply the brand chrome (logo, palette). The
    output is deterministic: same spec + same brand → byte-identical HTML.
    """
    pal = email_palette(profile, brand_kit)
    width = spec.email_format.width
    org_name = (
        spec.meta.get("club_name")
        or _attr(profile, "display_name")
        or _attr(profile, "short_name")
        or ""
    )
    logo_url = _attr(profile, "brand_logo_url") or ""

    masthead = _masthead(spec, pal, logo_url=logo_url, org_name=org_name)
    body = "".join(_render_section(s, pal) for s in spec.sections)
    footer = _footer(spec, pal, org_name=org_name)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">\n'
        '<meta name="color-scheme" content="light dark">\n'
        '<meta name="supported-color-schemes" content="light dark">\n'
        f"<title>{_esc(spec.title)}</title>\n"
        f"{_head_style(pal)}\n"
        "</head>\n"
        f'<body class="mh-body" style="margin:0;padding:0;background:{pal["bg"]};'
        f'font-family:{_FONT};color:{pal["ink"]}">\n'
        f"{_preheader(spec.preheader)}\n"
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" class="mh-body" style="background:{pal["bg"]}">\n'
        '<tr><td align="center" style="padding:24px 12px">\n'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{width}" class="mh-container" style="width:{width}px;max-width:{width}px;'
        f'background:{pal["panel"]};border-radius:12px;overflow:hidden;'
        f'box-shadow:0 1px 3px rgba(0,0,0,0.08)">\n'
        f"{masthead}{body}{footer}"
        "</table>\n"
        "</td></tr>\n"
        "</table>\n"
        "</body>\n"
        "</html>\n"
    )


def _attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# ---------------------------------------------------------------------------
# Plaintext — the text/plain alternative every good email carries.
# ---------------------------------------------------------------------------


def _plain_block(block: EmailBlock) -> str:
    k = block.kind
    p = block.props or {}
    if k == "heading":
        t = (p.get("text") or "").strip()
        return f"{t}\n{'-' * len(t)}" if t else ""
    if k == "text":
        return (p.get("text") or "").strip()
    if k == "list":
        items = [str(i).strip() for i in (p.get("items") or []) if str(i).strip()]
        return "\n".join(f"  - {i}" for i in items)
    if k == "button":
        label = (p.get("label") or "").strip()
        href = (p.get("href") or "").strip()
        if label and href:
            return f"{label}: {href}"
        return label or href
    if k == "image":
        cap = (p.get("caption") or p.get("alt") or "").strip()
        return f"[{cap}]" if cap else ""
    if k == "card":
        title = (p.get("title") or "").strip()
        body = (p.get("body") or "").strip()
        href = (p.get("href") or "").strip()
        parts = [pt for pt in (title, body) if pt]
        if href:
            parts.append(href)
        return "\n".join(parts)
    if k == "stat_row":
        bits = [
            f"{s.get('value', '')} {s.get('label', '')}".strip()
            for s in (p.get("stats") or [])
            if isinstance(s, dict) and str(s.get("value", "")).strip()
        ]
        return "  |  ".join(bits)
    if k == "quote":
        t = (p.get("text") or "").strip()
        attr = (p.get("attribution") or "").strip()
        return f'"{t}"' + (f" — {attr}" if attr else "") if t else ""
    if k == "fixtures":
        title = (p.get("title") or "").strip()
        lines = [title] if title else []
        for it in p.get("items") or []:
            if not isinstance(it, dict):
                continue
            date = (it.get("date") or "").strip()
            name = (it.get("name") or "").strip()
            venue = (it.get("venue") or "").strip()
            bits = [b for b in (date, name, venue) if b]
            if bits:
                lines.append("  " + " — ".join(bits))
        return "\n".join(lines)
    if k == "sponsor":
        name = (p.get("name") or "").strip()
        label = (p.get("label") or "In partnership with").strip()
        return f"{label}: {name}" if name else ""
    if k == "divider":
        return "---"
    if k == "spacer":
        return ""
    return ""


def render_plaintext(spec: NewsletterSpec, *, profile: Any = None) -> str:
    """A clean, readable ``text/plain`` rendering of the newsletter."""
    org_name = spec.meta.get("club_name") or _attr(profile, "display_name") or ""
    lines: list[str] = []
    if spec.kicker:
        lines.append(spec.kicker.upper())
    lines.append(spec.title)
    if spec.subtitle:
        lines.append(spec.subtitle)
    lines.append("")
    for section in spec.sections:
        for block in section.blocks:
            chunk = _plain_block(block).strip("\n")
            if chunk:
                lines.append(chunk)
                lines.append("")
    if org_name:
        lines.append(f"Sent on behalf of {org_name}. Made with MediaHub.")
    text_out = "\n".join(lines)
    # collapse 3+ blank lines to a single blank line for tidiness
    while "\n\n\n" in text_out:
        text_out = text_out.replace("\n\n\n", "\n\n")
    return text_out.strip() + "\n"


__all__ = ["render_email_html", "render_plaintext"]
