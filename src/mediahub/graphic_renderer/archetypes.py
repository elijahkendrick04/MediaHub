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
from pathlib import Path

V2_DIR = Path(__file__).parent / "layouts" / "v2"

_TRUE = {"1", "true", "on", "yes"}


def is_enabled() -> bool:
    """True when the Gen Engine v2 flag is set. Off (legacy engine) by default."""
    return os.environ.get("MEDIAHUB_GEN_V2", "").strip().lower() in _TRUE


def list_archetypes() -> list[str]:
    """Sorted archetype names (``<name>`` of every ``layouts/v2/<name>.html``).

    Sorted so the seeded picker is stable across processes/filesystems.
    """
    if not V2_DIR.is_dir():
        return []
    return sorted(p.stem for p in V2_DIR.glob("*.html"))


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
