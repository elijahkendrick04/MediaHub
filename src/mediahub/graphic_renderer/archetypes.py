"""Generation Engine v2 — archetype registry + deterministic picker (Tier A).

The v1 graphic engine repaints a handful of layout families, so a content pack
tends to look "samey". Tier A fixes that *deterministically* (no LLM, ~£0): a
library of structurally-distinct **archetypes** under ``layouts/v2/`` plus a
seeded picker that spreads a pack across them.

This module is the single source of truth for "what are the v2 archetypes" so
the picker (in ``creative_brief.generator``) and the loader (in
``graphic_renderer.render``) can never drift. It is **gated** behind the
``MEDIAHUB_GEN_V2`` env flag and is completely inert when the flag is off — the
legacy engine then renders byte-for-byte as before.

Authoring convention for a ``layouts/v2/<name>.html`` archetype:
  * ``{{BASE_CSS}}`` first inside ``<style>`` (carries the font-faces + reset).
  * brand colours **only** via the CSS custom properties the renderer injects:
    ``--mh-primary``, ``--mh-on-primary``, ``--mh-surface``, ``--mh-on-surface``,
    ``--mh-accent``, ``--mh-secondary``, ``--mh-outline`` — never a hardcoded hex.
  * overflow-prone hero text uses the autofit vars with a sensible default, e.g.
    ``font-size: var(--mh-fit-surname-px, 132px)`` / ``var(--mh-fit-result-px, 96px)``.
  * the athlete photo uses ``object-position: var(--mh-photo-pos, center 28%)``
    so the saliency crop can steer it.
  * text placeholders come from the renderer's substitution dict
    (``{{ATHLETE_SURNAME_DISPLAY}}``, ``{{EVENT_NAME}}``, ``{{RESULT_VALUE}}``,
    ``{{HERO_STAT}}``, ``{{LOGO_BLOCK}}``, ``{{ATHLETE_IMG_BLOCK}}`` …).
  * must read well at both 1080×1350 and 1080×1920.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

V2_DIR = Path(__file__).parent / "layouts" / "v2"

# Explicit kill-switch values. v2 is the DEFAULT engine (the deterministic
# compliance gate guarantees every resolved palette is legible), so enablement is
# opt-OUT: anything that isn't one of these leaves v2 on.
_FALSE = {"0", "false", "off", "no"}

# Conceptual brand colour-role names the design-spec director (Tier B §5.4) may
# assign to the four compositional slots (ground/surface/headline/accent). They
# map onto the renderer's resolved ``--mh-*`` tokens.
TOKEN_ROLES: tuple[str, ...] = (
    "primary",
    "secondary",
    "surface",
    "accent",
    "on_primary",
    "on_surface",
)


def is_enabled() -> bool:
    """True unless v2 is explicitly disabled.

    Gen Engine v2 is the **default** layout engine. Set ``MEDIAHUB_GEN_V2=0``
    (also ``false``/``off``/``no``) to fall back to the legacy engine — the
    deployment-wide kill-switch.
    """
    return os.environ.get("MEDIAHUB_GEN_V2", "").strip().lower() not in _FALSE


@lru_cache(maxsize=1)
def _scan() -> tuple[str, ...]:
    """Scan ``layouts/v2`` once. Archetype files are static at runtime, so the
    directory listing is cached rather than re-globbed on every per-card render.
    """
    if not V2_DIR.is_dir():
        return ()
    return tuple(sorted(p.stem for p in V2_DIR.glob("*.html")))


def list_archetypes() -> list[str]:
    """Sorted archetype names (``<name>`` of every ``layouts/v2/<name>.html``).

    Sorted so the seeded picker is stable across processes/filesystems. Returns a
    fresh list each call (callers may keep/sort it) over the cached scan.
    """
    return list(_scan())


def pick_archetype(seed: int) -> str | None:
    """Deterministically pick one archetype for a card from its variation seed.

    Stable per card (same seed → same archetype) and well-spread across a pack
    (distinct seeds map across the whole library by modulo). Returns ``None``
    when no archetype files exist, so callers keep the legacy family.
    """
    names = list_archetypes()
    if not names:
        return None
    return names[int(seed) % len(names)]


def pick_archetype_avoiding(seed: int, recent: Iterable[str]) -> str | None:
    """Seeded pick that walks past recently-used archetypes.

    The deterministic no-LLM floor for "give me a *fresh* direction": start at
    the card's seeded archetype and step forward until one not in ``recent`` is
    found, so consecutive regenerates (and the 3-variant picker) walk the
    library instead of repeating one composition. Still fully deterministic —
    same seed + same recent list → same pick. When every archetype is in
    ``recent`` (or the library is empty) it degrades to :func:`pick_archetype`.
    """
    names = list_archetypes()
    if not names:
        return None
    avoid = {r for r in recent if r}
    start = int(seed) % len(names)
    for offset in range(len(names)):
        candidate = names[(start + offset) % len(names)]
        if candidate not in avoid:
            return candidate
    return names[start]


# Marker introducing the when-to-pick passage in every <name>.notes.md. The
# authored notes use a few phrasings ("When the director should pick it:",
# "The director should pick this archetype when/for …", "Why the director
# should pick it."); match at the bold marker so the passage that follows —
# the when-clause itself — becomes the catalog line.
_WHEN_TO_PICK_RE = re.compile(
    r"\*\*\s*(?:Why\s+|When\s+)?the\s+director\s+should\s+pick\s+(?:it|this\s+archetype)\b",
    re.IGNORECASE,
)
# Inline markdown the prompt line should not carry.
_MD_NOISE_RE = re.compile(r"[*`]")

_NOTE_MAX_CHARS = 320


@lru_cache(maxsize=None)
def director_note(name: str) -> str:
    """One bounded plain-text line briefing the design-spec director on ``name``.

    Sourced from the archetype's authored ``<name>.notes.md`` (PAR-7), which
    every archetype must ship (test-enforced): the passage after **"When the
    director should pick it"** — falling back to the start of the notes body
    when the marker is absent. Markdown emphasis is stripped and the text is
    clipped at a word boundary so twelve catalog lines stay prompt-sized.
    Returns ``""`` when the notes file is missing/unreadable; the director
    keeps its static fallback line in that case.
    """
    path = V2_DIR / f"{name}.notes.md"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = _WHEN_TO_PICK_RE.search(raw)
    # slice at the marker and shed its trailing punctuation/bold-close, so the
    # line reads as the when-clause itself ("when there is a strong photo …")
    body = raw[m.end() :].lstrip(" .:*\n") if m else raw
    # drop a leading "# name" heading when falling back to the body
    body = re.sub(r"\A#[^\n]*\n", "", body).strip()
    text = " ".join(_MD_NOISE_RE.sub("", body).split())
    if len(text) > _NOTE_MAX_CHARS:
        clipped = text[:_NOTE_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:")
        text = clipped + " …"
    return text


_SUMMARY_MAX_CHARS = 200


@lru_cache(maxsize=None)
def archetype_summary(name: str) -> str:
    """One plain-text line describing WHAT an archetype is — its structural
    signature — for the template/archetype gallery (UI 1.10).

    Sourced from the same authored ``<name>.notes.md`` that feeds
    :func:`director_note`, but from the prose *before* the "When the director
    should pick it" passage (which ``director_note`` already surfaces). A
    leading ``# heading`` and any leading bold section label
    (``**Family / structural signature.**``) are dropped, markdown emphasis is
    stripped, whitespace is collapsed, and the text is clipped to a clean first
    sentence (or a word boundary) so a gallery card stays compact. Returns
    ``""`` when the notes file is missing/unreadable; callers then fall back to
    their own short blurb.
    """
    path = V2_DIR / f"{name}.notes.md"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = _WHEN_TO_PICK_RE.search(raw)
    body = raw[: m.start()] if m else raw
    # drop a leading "# name" heading …
    body = re.sub(r"\A\s*#[^\n]*\n", "", body)
    # … and a leading bold section label, e.g. "**Family / structural signature.**"
    body = re.sub(r"\A\s*\*\*[^*]+\*\*\.?\s*", "", body)
    text = " ".join(_MD_NOISE_RE.sub("", body).split())
    if not text:
        return ""
    if len(text) > _SUMMARY_MAX_CHARS:
        cut = text.rfind(". ", 0, _SUMMARY_MAX_CHARS)
        if cut >= 60:
            text = text[: cut + 1]
        else:
            text = text[:_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    return text
