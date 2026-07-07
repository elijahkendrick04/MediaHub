"""sprint_hooks/icon_overlay.py — G1.22 icon / badge overlay system.

Deterministic medal / club-record / PB-ribbon / nationality-flag SVG badges
stamped into the top-right corner of a finished card. The badges are derived
purely from the brief's *achievement semantics* — no AI, no randomness — so the
overlay is content-driven: a card with no badge-worthy signal is returned
byte-identical (the contract every sprint hook honours).

What a card can earn (priority order, capped at three so the corner never
clutters):

    record  →  a heraldic shield        (club / county / national record)
    medal   →  a metallic medal disc     (gold / silver / bronze finish)
    flag    →  a nation colour-chip       (when the brief carries a nationality)
    ribbon  →  a PB rosette               (NEW PB / LIKELY PB)

Tints: medals use fixed metallic tiers (for a medal the colour *is* the
information, mirroring ``render._MEDAL_ACCENTS``); the record shield and PB
rosette take the club's own primary so they read on-brand; the flag uses the
nation's colours plus an always-visible ISO/NOC code chip. The SVG assets live
in ``graphic_renderer/icons/`` as token-templates this module fills in.

Operators can force the overlay off for a card with ``icon_overlay = "off"`` on
the brief (or in ``text_layers``); the default is content-driven ``"auto"``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import RenderHookCtx

# Late in the hook order so the badges sit visually above earlier background /
# style hooks. (Z-index, set below, is what actually decides paint order.)
ORDER = 70

_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"

# Paint above card content but below the demo watermark (z-index 9999) so a
# watermark always stamps over everything, exactly as render.py intends.
_OVERLAY_Z = 80

# Fixed metallic medal tints (light face, deep ring). The colour carries the
# tier, so these are deliberately brand-independent — a gold badge must read
# gold. Kept in step with render._MEDAL_ACCENTS.
_MEDAL_TINTS: dict[str, tuple[str, str]] = {
    "gold": ("#FFE07A", "#9A6E0E"),
    "silver": ("#F2F2F2", "#6E6E6E"),
    "bronze": ("#F0BC8A", "#7A4314"),
}
_MEDAL_LABEL = {"gold": "Gold medal", "silver": "Silver medal", "bronze": "Bronze medal"}

# Families that already paint a prominent medal in the composition itself —
# suppress the *medal* badge there to avoid doubling (record / flag / PB ribbon
# still apply).
_MEDAL_BAKED_FAMILIES = {"medal_card", "centered_medal_spotlight"}

# Nation → three colour bands (top→bottom) for the flag chip. Real flags vary in
# geometry, so we evoke the nation's colours and ALWAYS show the code chip rather
# than claim exact vexillology. Keyed by upper-case ISO alpha-2 / alpha-3 / NOC.
_NATIONS: dict[str, tuple[str, str, str]] = {
    "GBR": ("#012169", "#FFFFFF", "#C8102E"),
    "GB": ("#012169", "#FFFFFF", "#C8102E"),
    "ENG": ("#FFFFFF", "#CE1124", "#FFFFFF"),
    "SCO": ("#005EB8", "#FFFFFF", "#005EB8"),
    "WAL": ("#FFFFFF", "#00AD36", "#C8102E"),
    "IRL": ("#169B62", "#FFFFFF", "#FF883E"),
    "IE": ("#169B62", "#FFFFFF", "#FF883E"),
    "USA": ("#B31942", "#FFFFFF", "#0A3161"),
    "US": ("#B31942", "#FFFFFF", "#0A3161"),
    "AUS": ("#00247D", "#FFFFFF", "#E4002B"),
    "AU": ("#00247D", "#FFFFFF", "#E4002B"),
    "CAN": ("#D80621", "#FFFFFF", "#D80621"),
    "CA": ("#D80621", "#FFFFFF", "#D80621"),
    "NZL": ("#00247D", "#FFFFFF", "#CC142B"),
    "NZ": ("#00247D", "#FFFFFF", "#CC142B"),
    "RSA": ("#007749", "#FFB81C", "#000000"),
    "ZAF": ("#007749", "#FFB81C", "#000000"),
    "FRA": ("#0055A4", "#FFFFFF", "#EF4135"),
    "FR": ("#0055A4", "#FFFFFF", "#EF4135"),
    "GER": ("#000000", "#DD0000", "#FFCE00"),
    "DEU": ("#000000", "#DD0000", "#FFCE00"),
    "DE": ("#000000", "#DD0000", "#FFCE00"),
    "ITA": ("#008C45", "#F4F5F0", "#CD212A"),
    "IT": ("#008C45", "#F4F5F0", "#CD212A"),
    "ESP": ("#AA151B", "#F1BF00", "#AA151B"),
    "ES": ("#AA151B", "#F1BF00", "#AA151B"),
    "NED": ("#AE1C28", "#FFFFFF", "#21468B"),
    "NLD": ("#AE1C28", "#FFFFFF", "#21468B"),
    "NL": ("#AE1C28", "#FFFFFF", "#21468B"),
    "JPN": ("#FFFFFF", "#BC002D", "#FFFFFF"),
    "JP": ("#FFFFFF", "#BC002D", "#FFFFFF"),
    "CHN": ("#DE2910", "#DE2910", "#FFDE00"),
    "CN": ("#DE2910", "#DE2910", "#FFDE00"),
    "BRA": ("#009C3B", "#FFDF00", "#009C3B"),
    "BR": ("#009C3B", "#FFDF00", "#009C3B"),
    "SWE": ("#006AA7", "#FECC00", "#006AA7"),
    "SE": ("#006AA7", "#FECC00", "#006AA7"),
    "NOR": ("#BA0C2F", "#FFFFFF", "#00205B"),
    "NO": ("#BA0C2F", "#FFFFFF", "#00205B"),
    "DEN": ("#C8102E", "#FFFFFF", "#C8102E"),
    "DNK": ("#C8102E", "#FFFFFF", "#C8102E"),
    "DK": ("#C8102E", "#FFFFFF", "#C8102E"),
    "HUN": ("#CD2A3E", "#FFFFFF", "#436F4D"),
    "HU": ("#CD2A3E", "#FFFFFF", "#436F4D"),
    "POL": ("#FFFFFF", "#FFFFFF", "#DC143C"),
    "PL": ("#FFFFFF", "#FFFFFF", "#DC143C"),
}
# Neutral cloth for a nation we don't have colours for — still honest (the code
# chip names it), never a guessed flag.
_NATION_FALLBACK = ("#5B6472", "#3A4150", "#262B35")

# A few full names → code, for briefs that carry a country name rather than a code.
_NAME_TO_CODE = {
    "great britain": "GBR",
    "united kingdom": "GBR",
    "england": "ENG",
    "scotland": "SCO",
    "wales": "WAL",
    "ireland": "IRL",
    "united states": "USA",
    "united states of america": "USA",
    "america": "USA",
    "australia": "AUS",
    "canada": "CAN",
    "new zealand": "NZL",
    "south africa": "RSA",
    "france": "FRA",
    "germany": "GER",
    "italy": "ITA",
    "spain": "ESP",
    "netherlands": "NED",
    "japan": "JPN",
    "china": "CHN",
    "brazil": "BRA",
    "sweden": "SWE",
    "norway": "NOR",
    "denmark": "DEN",
    "hungary": "HUN",
    "poland": "POL",
}


# ---------------------------------------------------------------------------
# tiny deterministic colour helpers (no colour-science gate — badges are
# decorative and carry their own white iconography + drop-shadow for legibility)
# ---------------------------------------------------------------------------
def _hex(value: object) -> str | None:
    """Normalise ``#rgb`` / ``#rrggbb`` (with or without ``#``) → ``#rrggbb``."""
    if not isinstance(value, str):
        return None
    s = value.strip().lstrip("#")
    if len(s) == 3 and all(c in "0123456789abcdefABCDEF" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
        return "#" + s.lower()
    return None


def _rgb(hexs: str) -> tuple[int, int, int]:
    h = hexs.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luma(hexs: str) -> float:
    """Rough relative luminance 0..1 (sRGB-weighted, no gamma — good enough for
    a light/dark decision)."""
    r, g, b = _rgb(hexs)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _darken(hexs: str, factor: float) -> str:
    r, g, b = _rgb(hexs)
    f = max(0.0, min(1.0, factor))
    return "#{:02x}{:02x}{:02x}".format(int(r * f), int(g * f), int(b * f))


def _brand_base(brief) -> tuple[str, str]:
    """(face, deep) for the on-brand emblems (record shield, PB rosette).

    The club's primary, unless it is so light the badge would vanish — then fall
    back to a dark secondary or a safe ink so the emblem is always visible.
    """
    pal = getattr(brief, "palette", None) or {}
    base = _hex(pal.get("primary")) or "#1B2330"
    if _luma(base) > 0.72:
        sec = _hex(pal.get("secondary"))
        base = sec if (sec and _luma(sec) < 0.72) else "#1B2330"
    return base, _darken(base, 0.55)


# ---------------------------------------------------------------------------
# semantic detection — all read existing brief fields; none reach the network
# ---------------------------------------------------------------------------
def _norm(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _haystack(brief) -> str:
    layers = getattr(brief, "text_layers", None) or {}
    parts = [
        _norm(getattr(brief, "confidence_label", "")),
        _norm(layers.get("achievement_label")),
        _norm(getattr(brief, "inspiration_pattern_id", "")),
        _norm(layers.get("post_angle")),
        _norm(getattr(brief, "primary_hook", "")),
    ]
    return " ".join(p for p in parts if p).lower()


def _factual_haystack(brief) -> str:
    """Achievement-fact fields ONLY — a medal / record badge is a factual claim,
    so free-form hook copy (``primary_hook`` / ``post_angle``) is excluded: "a
    golden night for the squad" must never mint a gold-medal badge. The
    deterministic ``inspiration_pattern_id`` counts as factual; its underscores
    read as word separators so ``medal_and_pb_combo`` matches ``\\bmedal\\b``.
    """
    layers = getattr(brief, "text_layers", None) or {}
    parts = [
        _norm(getattr(brief, "confidence_label", "")),
        _norm(layers.get("achievement_label")),
        _norm(getattr(brief, "inspiration_pattern_id", "")).replace("_", " "),
    ]
    return " ".join(p for p in parts if p).lower()


def _word(term: str, hay: str) -> bool:
    """Whole-word match, so "golden" never reads as "gold"."""
    return re.search(rf"\b{term}\b", hay) is not None


def _place_int(value: object) -> int | None:
    """Leading integer of a place string (``"1st"`` → 1, ``"=2nd"`` → 2)."""
    m = re.match(r"\D*(\d+)", _norm(value))
    return int(m.group(1)) if m else None


def _medal_tier(brief) -> str | None:
    hay = _factual_haystack(brief)
    layers = getattr(brief, "text_layers", None) or {}
    place = _place_int(layers.get("place"))
    medal_ctx = _word("medal", hay)  # only let a 1/2/3 placing imply a medal in a medal context
    if _word("gold", hay) or (medal_ctx and place == 1):
        return "gold"
    if _word("silver", hay) or (medal_ctx and place == 2):
        return "silver"
    if _word("bronze", hay) or (medal_ctx and place == 3):
        return "bronze"
    return None


def _record_kind(brief) -> str | None:
    hay = _factual_haystack(brief)
    if not _word("record", hay):
        return None
    if _word("national", hay):
        return "NATIONAL"
    if _word("county", hay) or _word("regional", hay):
        return "COUNTY"
    if _word("club", hay):
        return "CLUB"
    return "RECORD"


def _is_pb(brief) -> bool:
    hay = _haystack(brief)
    return bool(re.search(r"\bpb\b", hay)) or "personal best" in hay


def _nation_code(brief) -> str | None:
    layers = getattr(brief, "text_layers", None) or {}
    cand = ""
    for key in ("nationality", "nation", "noc", "country_code", "country"):
        cand = _norm(layers.get(key))
        if cand:
            break
    if not cand:
        cand = _norm(getattr(brief, "nationality", "")) or _norm(getattr(brief, "country", ""))
    if not cand:
        return None
    letters = re.sub(r"[^A-Za-z]", "", cand).upper()
    if len(letters) in (2, 3):
        return letters
    return _NAME_TO_CODE.get(cand.lower())  # a full country name, else None


def _enabled(brief) -> bool:
    """Operator kill-switch. Default (absent / ``auto`` / ``on``) is enabled."""
    layers = getattr(brief, "text_layers", None) or {}
    flag = _norm(getattr(brief, "icon_overlay", "")) or _norm(layers.get("icon_overlay"))
    return flag.lower() not in {"off", "none", "0", "false", "no"}


# ---------------------------------------------------------------------------
# asset filling + badge assembly
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _asset(name: str) -> str:
    return (_ICONS_DIR / name).read_text(encoding="utf-8")


def _fill(name: str, uid: str, **tokens: str) -> str:
    svg = _asset(name).replace("__UID__", uid)
    for key, val in tokens.items():
        svg = svg.replace(f"__{key}__", val)
    # A bare viewBox SVG won't size to its container — make it fill the badge
    # box (default preserveAspectRatio="xMidYMid meet" keeps it centred).
    return svg.replace("<svg ", '<svg style="width:100%;height:100%;display:block" ', 1)


def _medal_svg(tier: str, uid: str) -> str:
    light, deep = _MEDAL_TINTS[tier]
    return _fill("medal.svg", uid, TINT=light, TINT_DEEP=deep, LABEL=_MEDAL_LABEL[tier])


def _record_svg(kind: str, base: str, deep: str, uid: str) -> str:
    return _fill(
        "record.svg", uid, TINT=base, TINT_DEEP=deep, TEXT=kind, LABEL=f"{kind.title()} record"
    )


def _ribbon_svg(base: str, deep: str, uid: str) -> str:
    return _fill("ribbon.svg", uid, TINT=base, TINT_DEEP=deep, TEXT="PB", LABEL="Personal best")


def _flag_svg(code: str, uid: str) -> str:
    b1, b2, b3 = _NATIONS.get(code, _NATION_FALLBACK)
    return _fill(
        "flag.svg", uid, BAND1=b1, BAND2=b2, BAND3=b3, CODE=code, LABEL=f"{code} nationality"
    )


def _plan_badges(brief, family: str) -> list[tuple[str, str]]:
    """Deterministic (kind, svg) list, priority order, capped at three."""
    badges: list[tuple[str, str]] = []
    base, deep = _brand_base(brief)

    record = _record_kind(brief)
    if record:
        badges.append(("record", _record_svg(record, base, deep, "rec")))

    if family not in _MEDAL_BAKED_FAMILIES:
        tier = _medal_tier(brief)
        if tier:
            badges.append((f"medal-{tier}", _medal_svg(tier, "med")))

    code = _nation_code(brief)
    if code:
        badges.append(("flag", _flag_svg(code, "flag")))

    # A record already implies a best, so don't double up with a PB ribbon.
    if not record and _is_pb(brief):
        badges.append(("ribbon", _ribbon_svg(base, deep, "pb")))

    return badges[:3]


def apply(html: str, ctx: RenderHookCtx) -> str:
    brief = ctx.brief
    if brief is None or ctx.width <= 0 or ctx.height <= 0:
        return html
    if not _enabled(brief):
        return html

    badges = _plan_badges(brief, ctx.family or "")
    if not badges:
        return html  # opt out: nothing badge-worthy on this card → byte-identical

    short = min(ctx.width, ctx.height)
    box = max(40, round(short * 0.135))  # uniform square badge box
    margin = max(12, round(short * 0.05))
    gap = max(6, round(short * 0.022))

    kinds = ",".join(k for k, _ in badges)
    cells: list[str] = []
    top = margin
    for _kind, svg in badges:
        cells.append(
            f'<div style="position:absolute;top:{top}px;right:{margin}px;'
            f"width:{box}px;height:{box}px;"
            f'filter:drop-shadow(0 2px 6px rgba(0,0,0,0.45))">{svg}</div>'
        )
        top += box + gap

    overlay = (
        f'<div class="mh-icon-overlay" data-badges="{kinds}" '
        f'style="position:fixed;inset:0;z-index:{_OVERLAY_Z};pointer-events:none">'
        + "".join(cells)
        + "</div>"
    )
    if "</body>" in html:
        return html.replace("</body>", overlay + "</body>", 1)
    return html + overlay


__all__ = ["apply", "ORDER"]
