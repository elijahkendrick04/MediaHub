"""
Loader for sport-profile YAML files.

Sport profiles are **shipped, read-only configuration** — the same category as
``data/ontology/*.json`` and ``data/voices/seed/*.json``, not per-run runtime
state. They therefore resolve relative to the repo's ``data/`` directory (with an
env override for tests/ops), rather than through ``DATA_DIR`` which is reserved
for mutable runtime storage. This mirrors ``voice.learned.store``'s handling of
the read-only seed-voice directory.

YAML (not JSON) is used for these files on purpose: profiles are authored and
reviewed by humans — including non-coders — so comments and readability matter.

Consumed by the running product: the web routes (sport selection),
``content_engine/planner.py``, ``club_platform/post_types.py`` and
``format_catalog.py`` all load profiles through this module.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

from .schema import SportProfile

# Sport slugs are simple identifiers ("swimming", "water_polo"). The slug is
# interpolated into a filesystem path and can arrive from request JSON, so
# anything else (path separators, dots, ..) is rejected before touching disk.
_SPORT_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

# Repo layout: this file is src/mediahub/sport_profiles/loader.py, so the repo
# root is parents[3] and the shipped profiles live at data/sport_profiles/.
_REPO_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "sport_profiles"


def _profiles_dir(base_dir: Optional[os.PathLike | str] = None) -> Path:
    """Resolve the directory holding the profile YAML files.

    Precedence: explicit ``base_dir`` arg > ``MEDIAHUB_SPORT_PROFILES_DIR`` env
    var > the shipped ``data/sport_profiles/`` directory.
    """
    if base_dir is not None:
        return Path(base_dir)
    env = os.environ.get("MEDIAHUB_SPORT_PROFILES_DIR")
    if env:
        return Path(env)
    return _REPO_DATA_DIR


def load_sport_profile(sport: str, base_dir: Optional[os.PathLike | str] = None) -> SportProfile:
    """Load and parse the profile for ``sport`` (e.g. ``"swimming"``).

    Raises ``FileNotFoundError`` if no ``<sport>.yaml`` exists — an honest error,
    never a fabricated default profile — and ``ValueError`` for a malformed slug
    (the value can come from request JSON and is used in a filesystem path, so
    traversal-shaped input never reaches the disk).
    """
    if not _SPORT_SLUG_RE.match(sport or ""):
        raise ValueError(f"invalid sport slug: {sport!r}")
    path = _profiles_dir(base_dir) / f"{sport}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no sport profile for {sport!r} at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SportProfile.from_dict(data)


def list_sport_profiles(
    base_dir: Optional[os.PathLike | str] = None,
) -> list[SportProfile]:
    """Load every ``*.yaml`` profile in the directory, sorted by sport slug."""
    directory = _profiles_dir(base_dir)
    if not directory.exists():
        return []
    profiles: list[SportProfile] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles.append(SportProfile.from_dict(data))
    return profiles


__all__ = ["load_sport_profile", "list_sport_profiles"]
