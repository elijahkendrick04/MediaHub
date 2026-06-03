"""Regression — HTML entities must not appear in JS ``textContent`` strings.

``element.textContent = 'Rendering reel&hellip;'`` displays the literal
string "&hellip;" — textContent does not parse HTML. Live sightings
(2026-06-04): the reel button showed "Rendering reel&hellip;" while
rendering, and the caption timestamp showed "regenerated just now &middot;
23:46:41". Use real Unicode characters (… ·) in textContent assignments;
entities remain fine inside innerHTML.
"""

from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"


def test_no_html_entities_in_textcontent_assignments():
    src = _WEB.read_text(encoding="utf-8")
    offenders: list[str] = []
    for line_no, line in enumerate(src.splitlines(), 1):
        if "textContent" not in line:
            continue
        # Only flag assignment-ish lines that carry an entity literal.
        if re.search(r"textContent\s*[+]?=", line) and re.search(
            r"&(?:[a-zA-Z]{2,8}|#x?[0-9a-fA-F]{2,6});", line
        ):
            offenders.append(f"web.py:{line_no}: {line.strip()[:120]}")
    assert not offenders, (
        "HTML entities in textContent render literally — use Unicode "
        "characters instead:\n" + "\n".join(offenders)
    )
