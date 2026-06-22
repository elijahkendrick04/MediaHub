"""sites.theme — brand role vars → a microsite's responsive CSS tokens & sheet.

Microsites paint with the **same** ``--mh-*`` brand roles the cards, charts and
documents use (``charts.palette.role_vars_from_palette``), so a club's site, its
cards and its reels are unmistakably one brand. Fonts are the self-hosted woff2
the rest of the engine serves (CLAUDE.md rule — never the Google Fonts CDN); only
the ``@font-face`` blocks are reused (via :mod:`documents.theme`).

Unlike a document (a fixed print sheet), a site is **responsive** and screen-first:
a mobile-first, fluid base sheet that reads on a phone (where most clubs' followers
land from a bio link) and scales up. Dark-first by default per the UI rules, with a
light variant for bright-brand clubs.

Everything here is deterministic: same role vars + theme → byte-identical CSS.
"""

from __future__ import annotations

from typing import Optional

# Reuse the document engine's brand resolver + self-hosted font faces so colour
# and type resolve identically across both engines.
from mediahub.documents.theme import _mix, _to_rgb, font_face_css, resolve_role_vars

__all__ = ["resolve_role_vars", "site_tokens", "site_style", "font_face_css"]


def _role(role_vars: dict[str, str], name: str, default: str) -> str:
    return role_vars.get(name) or default


def _luminance(hex_colour: str) -> float:
    r, g, b = _to_rgb(hex_colour)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _is_light(hex_colour: str) -> bool:
    return _luminance(hex_colour) > 0.6


def _contrast_ok(a: str, b: str) -> bool:
    return abs(_luminance(a) - _luminance(b)) > 0.4


def site_tokens(role_vars: dict[str, str], *, theme: str = "dark") -> dict[str, str]:
    """Map brand ``--mh-*`` roles to the ``--site-*`` tokens the sheet consumes."""
    primary = _role(role_vars, "--mh-primary", "#0A2540")
    secondary = _role(role_vars, "--mh-secondary", "#1B3D5C")
    surface = _role(role_vars, "--mh-surface", "#051433")
    accent = _role(role_vars, "--mh-accent", "#FFB81C")
    on_primary = _role(role_vars, "--mh-on-primary", "#FFFFFF")
    on_accent = primary if _contrast_ok(primary, accent) else "#10151C"

    if theme == "light":
        page = "#FFFFFF"
        ink = "#14181F"
        panel = _mix(primary, page, 0.94)
        return {
            "--site-bg": page,
            "--site-ink": ink,
            "--site-muted": "#5A6472",
            "--site-panel": panel,
            "--site-line": "#E3E7ED",
            "--site-brand": primary,
            "--site-brand-ink": on_primary,
            "--site-secondary": secondary,
            "--site-accent": accent,
            "--site-on-accent": "#10151C" if _is_light(accent) else "#FFFFFF",
            "--site-hero-ink": on_primary,
        }

    # Dark-first (default) — the deep brand surface, light ink, accent highlights.
    page = surface
    ink = _role(role_vars, "--mh-on-surface", "#FFFFFF")
    return {
        "--site-bg": page,
        "--site-ink": ink,
        "--site-muted": _mix(ink, page, 0.42),
        "--site-panel": _mix(page, ink, 0.08),
        "--site-line": _mix(page, ink, 0.20),
        "--site-brand": primary,
        "--site-brand-ink": on_primary,
        "--site-secondary": secondary,
        "--site-accent": accent,
        "--site-on-accent": on_accent,
        "--site-hero-ink": on_primary,
    }


# Mobile-first, dependency-free responsive base sheet. No external assets: fonts
# are the self-hosted @font-face blocks, colours are the --site-* tokens above.
_BASE_CSS = r"""
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;
  font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  color:var(--site-ink);
  background:var(--site-bg);
  line-height:1.6;
  font-size:17px;
  -webkit-font-smoothing:antialiased;
}
img{max-width:100%;height:auto;display:block}
a{color:var(--site-accent)}
h1,h2,h3{font-family:'Space Grotesk','Inter',sans-serif;line-height:1.12;margin:0 0 .5rem;font-weight:700}
h1{font-size:clamp(1.9rem,6vw,3rem);letter-spacing:-.01em}
h2{font-size:clamp(1.5rem,4vw,2rem)}
h3{font-size:1.2rem;color:var(--site-accent)}
p{margin:0 0 1rem}
.site-wrap{max-width:960px;margin:0 auto;padding:0 20px}
.site-wrap.narrow{max-width:560px}
/* top nav */
.site-nav{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--site-bg) 88%,transparent);
  backdrop-filter:saturate(140%) blur(8px);border-bottom:1px solid var(--site-line)}
.site-nav .row{display:flex;align-items:center;gap:18px;padding:12px 20px;max-width:1100px;margin:0 auto}
.site-nav .brand{display:flex;align-items:center;gap:10px;font-family:'Space Grotesk',sans-serif;
  font-weight:700;color:var(--site-ink);text-decoration:none;font-size:1.05rem}
.site-nav .brand img{height:30px;width:auto}
.site-nav .links{display:flex;gap:16px;margin-left:auto;flex-wrap:wrap}
.site-nav .links a{color:var(--site-muted);text-decoration:none;font-weight:600;font-size:.95rem}
.site-nav .links a:hover,.site-nav .links a[aria-current=page]{color:var(--site-ink)}
/* sections */
.site-section{padding:48px 0}
.site-section.bg-surface{background:var(--site-panel)}
.site-section.bg-primary{background:var(--site-brand);color:var(--site-brand-ink)}
.site-section.bg-accent{background:var(--site-accent);color:var(--site-on-accent)}
.site-section.bg-primary h1,.site-section.bg-primary h2,.site-section.bg-primary h3,.site-section.bg-primary a{color:var(--site-brand-ink)}
.site-section.bg-accent h1,.site-section.bg-accent h2,.site-section.bg-accent h3{color:var(--site-on-accent)}
.layout-centered .site-wrap{max-width:560px;text-align:center}
.layout-grid .blocks{display:grid;gap:18px}
/* hero */
.site-hero{position:relative;padding:84px 0;text-align:left;overflow:hidden;
  background:linear-gradient(135deg,var(--site-brand),var(--site-secondary));color:var(--site-hero-ink)}
.site-hero.has-media{background:#0b0b0b}
.site-hero .bgimg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.42}
.site-hero .inner{position:relative;max-width:760px}
.site-hero h1{color:var(--site-hero-ink)}
.site-hero .kicker{text-transform:uppercase;letter-spacing:.16em;font-size:.8rem;font-weight:700;
  color:var(--site-accent);margin-bottom:.7rem}
.site-hero .subhead{font-size:1.15rem;opacity:.92;margin:.6rem 0 0;max-width:48ch}
/* buttons */
.site-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:13px 22px;border-radius:12px;font-weight:700;text-decoration:none;cursor:pointer;
  border:1px solid transparent;font-size:1rem;transition:transform .08s ease}
.site-btn:active{transform:translateY(1px)}
.site-btn.primary{background:var(--site-accent);color:var(--site-on-accent)}
.site-btn.secondary{background:transparent;color:var(--site-ink);border-color:var(--site-line)}
.site-hero .site-btn{margin-top:1.4rem}
/* link-in-bio stack */
.bio-stack{display:flex;flex-direction:column;gap:14px;margin:18px 0}
.bio-link{display:block;width:100%;text-align:center;padding:16px 18px;border-radius:14px;
  background:var(--site-panel);border:1px solid var(--site-line);color:var(--site-ink);
  text-decoration:none;font-weight:700}
.bio-link:hover{border-color:var(--site-accent)}
.bio-link .note{display:block;font-weight:500;font-size:.85rem;color:var(--site-muted);margin-top:3px}
.bio-link.primary{background:var(--site-accent);color:var(--site-on-accent);border-color:transparent}
.bio-link.primary .note{color:inherit;opacity:.85}
/* social row */
.social-row{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin:14px 0}
.social-row a{color:var(--site-muted);text-decoration:none;font-weight:600}
.social-row a:hover{color:var(--site-ink)}
/* card grid (approved-card embeds) */
.card-grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.card-grid.cols-2{grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.card-grid figure{margin:0}
.card-grid img{border-radius:12px;width:100%}
.card-grid figcaption{color:var(--site-muted);font-size:.85rem;margin-top:.4rem}
/* sponsor strip */
.sponsor-strip{text-align:center}
.sponsor-strip .title{text-transform:uppercase;letter-spacing:.12em;font-size:.78rem;
  color:var(--site-muted);font-weight:700;margin-bottom:14px}
.sponsor-strip .logos{display:flex;gap:26px;flex-wrap:wrap;align-items:center;justify-content:center}
.sponsor-strip .logos img{height:44px;width:auto;opacity:.92}
/* cta band */
.cta-band{display:flex;gap:18px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.cta-band .t{font-size:1.25rem;font-weight:700;margin:0}
/* event details */
.event-card{display:grid;gap:10px;background:var(--site-panel);border:1px solid var(--site-line);
  border-radius:14px;padding:20px}
.event-card .row{display:flex;gap:10px}
.event-card .k{min-width:84px;color:var(--site-muted);font-weight:700;font-size:.85rem;
  text-transform:uppercase;letter-spacing:.05em}
.event-card .map-link{color:var(--site-accent);font-weight:600;text-decoration:none}
/* qr */
.qr-block{display:inline-block;text-align:center}
.qr-block svg,.qr-block img{width:200px;height:200px;background:#fff;border-radius:12px;padding:10px}
.qr-block .cap{display:block;color:var(--site-muted);font-size:.85rem;margin-top:.5rem}
/* generic blocks reused from documents (table/list/kpi/quote) re-skinned */
.doc-table{width:100%;border-collapse:collapse;margin:.4em 0 1em;font-size:.95em}
.doc-table th{background:var(--site-brand);color:var(--site-brand-ink);text-align:left;padding:9px 12px}
.doc-table td{padding:8px 12px;border-bottom:1px solid var(--site-line)}
.doc-kpis{display:flex;gap:14px;flex-wrap:wrap;margin:.5em 0 1em}
.doc-kpi{flex:1 1 0;min-width:130px;background:var(--site-panel);border:1px solid var(--site-line);
  border-radius:12px;padding:16px 18px}
.doc-kpi .v{font-family:'Space Grotesk',sans-serif;font-size:2rem;font-weight:700;color:var(--site-accent);line-height:1}
.doc-kpi .l{display:block;margin-top:.35em;font-size:.8rem;color:var(--site-muted);font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.doc-kpi .s{display:block;margin-top:.1em;font-size:.78rem;color:var(--site-muted)}
.doc-list{padding-left:1.3em}.doc-list li{margin:.25em 0}
.doc-quote{margin:.6em 0;padding:.6em 1.1em;border-left:4px solid var(--site-accent);
  background:var(--site-panel);font-style:italic;border-radius:0 8px 8px 0}
.doc-quote .who{display:block;margin-top:.4em;font-style:normal;font-size:.82em;color:var(--site-muted);font-weight:600}
.doc-divider{border:0;border-top:1px solid var(--site-line);margin:1.4em 0}
.doc-spacer-sm{height:12px}.doc-spacer-md{height:28px}.doc-spacer-lg{height:52px}
.doc-figure{margin:.5em 0 1em}.doc-figure img{border-radius:10px}
.doc-figure figcaption{color:var(--site-muted);font-size:.85em;margin-top:.4em}
.doc-cols{display:grid;gap:22px;grid-template-columns:1fr}
/* footer */
.site-foot{border-top:1px solid var(--site-line);margin-top:8px;padding:28px 0;color:var(--site-muted);font-size:.85rem}
.site-foot .made{opacity:.7}
@media (min-width:760px){
  .site-section{padding:64px 0}
  .doc-cols{grid-template-columns:1fr 1fr}
}
"""


def site_style(role_vars: dict[str, str], *, theme: str = "dark") -> str:
    """The complete inner CSS for a microsite: fonts + tokens + responsive base."""
    tokens = site_tokens(role_vars, theme=theme)
    root = ":root{" + "".join(f"{k}:{v};" for k, v in tokens.items()) + "}"
    return "\n".join([font_face_css(), root, _BASE_CSS])


def role_vars_for(brand_kit=None, palette: Optional[dict] = None) -> dict[str, str]:
    """Convenience alias mirroring documents.theme.resolve_role_vars."""
    return resolve_role_vars(brand_kit, palette)
