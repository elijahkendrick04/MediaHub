"""Guard against HTML entities in _layout() page titles.

The layout template renders the title via ``{{ title }}`` which Jinja
auto-escapes. So a title built with a literal HTML entity
(``_layout(f"Content Pack &mdash; {x}")``) is double-escaped — the
browser tab shows a literal ``&amp;mdash;`` instead of an em-dash.

This test fails if any ``_layout(...)`` call passes a title string
containing a named HTML entity, forcing the use of the literal
character (—, ·, …) instead.
"""
from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parent.parent / "src" / "mediahub" / "web" / "web.py"

# _layout("<title>...") or _layout(f"<title>...") where the title literal
# (first arg, up to the closing quote) contains a named entity.
_LAYOUT_TITLE_RE = re.compile(
    r"""_layout\(\s*f?(['"])(?P<title>(?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)
_ENTITY_RE = re.compile(r"&(?:mdash|ndash|hellip|middot|amp|rsquo|lsquo|nbsp|times);")


def test_no_html_entities_in_layout_titles():
    src = _WEB.read_text(encoding="utf-8")
    offenders = []
    for m in _LAYOUT_TITLE_RE.finditer(src):
        title = m.group("title")
        if _ENTITY_RE.search(title):
            line = src.count("\n", 0, m.start()) + 1
            offenders.append(f"web.py:{line}: title={title!r}")
    assert not offenders, (
        "HTML entities in _layout() titles get double-escaped by Jinja "
        "(browser tab shows literal &amp;mdash;). Use the literal char "
        "(—, ·, …) instead:\n  " + "\n  ".join(offenders)
    )
