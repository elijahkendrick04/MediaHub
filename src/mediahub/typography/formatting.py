"""Deterministic rich-text formatting model (roadmap 1.9).

The "formatting depth" half of the typography system: the character- and
paragraph-level controls Canva/Adobe expose (colour, alignment, weight/style,
underline, strikethrough, decimal sizes, line height, letter spacing, lists with
markers, links) plus the editor utilities (uppercase transform, find & replace,
copy-style, auto-link, an honest spellcheck seam) — all as **pure, deterministic
functions** with **XSS-safe** HTML output.

No AI here: formatting is mechanical. The one rule that matters is safety — every
piece of user text is HTML-escaped, and every value that lands in a ``style=``
attribute is validated against a closed vocabulary or a strict hex/number check,
so an arbitrary caption can never inject CSS or markup (CLAUDE.md security focus:
"XSS in generated captions"). Colours resolve to the card's ``--mh-*`` role
tokens or a validated hex; anything else is dropped, never echoed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
ALIGNMENTS: tuple[str, ...] = ("left", "center", "right", "justify")
ORDERED_MARKERS: tuple[str, ...] = ("decimal", "lower-alpha", "upper-alpha", "lower-roman")
UNORDERED_MARKERS: tuple[str, ...] = ("disc", "circle", "square", "dash")
STYLES: tuple[str, ...] = ("normal", "italic")

# Role colour names → the card's CSS custom properties (never an invented hex).
ROLE_COLOURS: dict[str, str] = {
    "ink": "var(--mh-on-primary)",
    "ground": "var(--mh-primary)",
    "surface": "var(--mh-surface)",
    "surface-ink": "var(--mh-on-surface)",
    "accent": "var(--mh-accent)",
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# Conservative URL matcher for auto-linking in doc/web/email outputs.
_URL_RE = re.compile(r"(https?://[^\s<>\"']+)")

# Decimal sizes are supported (Canva/Adobe allow e.g. 17.5px) but clamped.
_MIN_SIZE_PX = 4.0
_MAX_SIZE_PX = 800.0
_MIN_WEIGHT = 100
_MAX_WEIGHT = 900


def escape(text: object) -> str:
    """HTML-escape any value (the single escaping gate for this module)."""
    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _safe_colour(value: Optional[str]) -> Optional[str]:
    """Resolve a role name or validated hex to a CSS colour, else ``None``."""
    if not value:
        return None
    v = str(value).strip()
    if v in ROLE_COLOURS:
        return ROLE_COLOURS[v]
    if _HEX_RE.match(v):
        return v
    return None


# --------------------------------------------------------------------------- #
# Character / paragraph format
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TextFormat:
    """One run's formatting. Every field is validated before it reaches CSS."""

    colour: Optional[str] = None  # role name or #hex
    align: Optional[str] = None  # ALIGNMENTS
    weight: Optional[int] = None  # 100..900
    style: str = "normal"  # normal | italic
    underline: bool = False
    strikethrough: bool = False
    uppercase: bool = False
    size_px: Optional[float] = None  # decimals allowed, clamped
    line_height: Optional[float] = None  # unitless multiplier
    letter_spacing_em: Optional[float] = None
    gradient: Optional[tuple[str, str]] = None  # (colour, colour) → background-clip:text

    def css(self) -> str:
        """Deterministic, XSS-safe inline CSS declarations for this format."""
        decls: list[str] = []
        col = _safe_colour(self.colour)
        if self.gradient:
            a = _safe_colour(self.gradient[0])
            b = _safe_colour(self.gradient[1])
            if a and b:
                decls.append(f"background:linear-gradient(92deg,{a},{b})")
                decls.append("-webkit-background-clip:text")
                decls.append("background-clip:text")
                decls.append("color:transparent")
                decls.append("-webkit-text-fill-color:transparent")
        elif col:
            decls.append(f"color:{col}")
        if self.align in ALIGNMENTS:
            decls.append(f"text-align:{self.align}")
        if isinstance(self.weight, int):
            decls.append(f"font-weight:{max(_MIN_WEIGHT, min(_MAX_WEIGHT, self.weight))}")
        if self.style == "italic":
            decls.append("font-style:italic")
        deco = []
        if self.underline:
            deco.append("underline")
        if self.strikethrough:
            deco.append("line-through")
        if deco:
            decls.append("text-decoration:" + " ".join(deco))
        if self.uppercase:
            decls.append("text-transform:uppercase")
        if self.size_px is not None:
            sz = max(_MIN_SIZE_PX, min(_MAX_SIZE_PX, float(self.size_px)))
            decls.append(f"font-size:{sz:g}px")
        if self.line_height is not None:
            lh = max(0.5, min(4.0, float(self.line_height)))
            decls.append(f"line-height:{lh:g}")
        if self.letter_spacing_em is not None:
            ls = max(-0.2, min(1.0, float(self.letter_spacing_em)))
            decls.append(f"letter-spacing:{ls:g}em")
        return ";".join(decls)


def copy_style(src: TextFormat) -> TextFormat:
    """The paintbrush: a copy of ``src``'s formatting to apply elsewhere."""
    return TextFormat(**{f.name: getattr(src, f.name) for f in src.__dataclass_fields__.values()})


# --------------------------------------------------------------------------- #
# Run / paragraph / list emission (XSS-safe)
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    """A span of text with one format (and an optional link)."""

    text: str
    fmt: TextFormat = field(default_factory=TextFormat)
    href: Optional[str] = None

    def html(self) -> str:
        inner = escape(self.text)
        if self.href and (self.href.startswith("https://") or self.href.startswith("http://")):
            inner = (
                f'<a href="{escape(self.href)}" rel="noopener noreferrer nofollow" '
                f'target="_blank">{inner}</a>'
            )
        css = self.fmt.css()
        if not css:
            return inner if self.fmt == TextFormat() else f"<span>{inner}</span>"
        return f'<span style="{css}">{inner}</span>'


def render_runs(runs: list[Run]) -> str:
    """Concatenate runs into one XSS-safe HTML string."""
    return "".join(r.html() for r in runs)


def render_list(items: list[str], *, ordered: bool = False, marker: Optional[str] = None) -> str:
    """An ``<ol>``/``<ul>`` with a validated marker; items are escaped.

    The ``dash`` unordered marker has no native CSS keyword, so it renders via a
    ``::marker``-free list with an explicit "– " prefix.
    """
    valid = ORDERED_MARKERS if ordered else UNORDERED_MARKERS
    mk = marker if marker in valid else valid[0]
    tag = "ol" if ordered else "ul"
    if not ordered and mk == "dash":
        lis = "".join(f'<li>&#8211; {escape(it)}</li>' for it in items)
        return f'<ul style="list-style:none;padding-left:1em">{lis}</ul>'
    lis = "".join(f"<li>{escape(it)}</li>" for it in items)
    return f'<{tag} style="list-style-type:{mk}">{lis}</{tag}>'


def auto_link(text: str) -> str:
    """Escape ``text`` and wrap bare http(s) URLs in safe ``<a>`` tags.

    For document/web/email outputs; plain image renderers ignore the anchors and
    show the visible URL text. Order-safe: we escape first, then linkify the
    (already-escaped) URL substrings, so no markup can be injected.
    """
    out = escape(text)
    return _URL_RE.sub(
        lambda m: f'<a href="{m.group(1)}" rel="noopener noreferrer nofollow" '
        f'target="_blank">{m.group(1)}</a>',
        out,
    )


# --------------------------------------------------------------------------- #
# Editor utilities
# --------------------------------------------------------------------------- #
def to_uppercase(text: str) -> str:
    """Locale-naïve uppercase transform (the editor's UPPERCASE button)."""
    return (text or "").upper()


def find_replace(
    text: str,
    find: str,
    replace: str,
    *,
    case_sensitive: bool = True,
    whole_word: bool = False,
) -> tuple[str, int]:
    """Deterministic find & replace. Returns ``(new_text, count)``.

    ``find`` is treated as a literal (never a regex from the user), so a caption
    full of regex metacharacters replaces safely.
    """
    if not find:
        return text, 0
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.escape(find)
    if whole_word:
        pattern = rf"\b{pattern}\b"
    new, n = re.subn(pattern, lambda _m: replace, text, flags=flags)
    return new, n


@dataclass(frozen=True)
class Misspelling:
    word: str
    start: int
    end: int


def spellcheck(text: str, *, dictionary: Optional[set[str]] = None) -> tuple[bool, list[Misspelling]]:
    """Honest spellcheck seam. Returns ``(available, misspellings)``.

    Deterministic and dependency-light: when a ``dictionary`` (a set of
    lowercase known words) is supplied, every alphabetic token not in it is
    flagged; otherwise — the common case, where live checking is the browser's
    job — it returns ``(False, [])`` rather than pretending to check. No fake
    results, mirroring the rest of MediaHub's honest-error discipline.
    """
    if not dictionary:
        return False, []
    out: list[Misspelling] = []
    for m in re.finditer(r"[A-Za-z']+", text or ""):
        w = m.group(0)
        if w.lower() not in dictionary:
            out.append(Misspelling(word=w, start=m.start(), end=m.end()))
    return True, out


__all__ = [
    "ALIGNMENTS",
    "ORDERED_MARKERS",
    "UNORDERED_MARKERS",
    "ROLE_COLOURS",
    "TextFormat",
    "Run",
    "Misspelling",
    "escape",
    "copy_style",
    "render_runs",
    "render_list",
    "auto_link",
    "to_uppercase",
    "find_replace",
    "spellcheck",
]
