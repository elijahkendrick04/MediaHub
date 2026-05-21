"""Phase 1.6 Stage I — the 30-seed catalogue.

Imported by ``test_golden_snapshots.py`` and
``scripts/update_theme_snapshots.py``. Adding or removing a seed
here automatically extends / shrinks the snapshot coverage.

Each entry is (seed_hex, label, category). The category is a
short tag — "identity", "common", "hostile", "saturated",
"pastel" — that documents *why* this seed is in the catalogue
(it's not a test discriminant; the snapshot test treats all
seeds equally).

References:
    - docs/THEMING.md §4
"""
from __future__ import annotations

from typing import Final, List, Tuple


SeedEntry = Tuple[str, str, str]   # (hex, label, category)


SEEDS_CATALOGUE: Final[List[SeedEntry]] = [
    # ───────────────────────────────────────────────────────────
    # MediaHub identity anchors (3)
    # ───────────────────────────────────────────────────────────
    ("#D4FF3A", "lane yellow",                "identity"),
    ("#F4D58D", "medal gold",                  "identity"),
    ("#0E2A47", "generic-default navy",        "identity"),

    # ───────────────────────────────────────────────────────────
    # Common club / brand colours (10)
    # ───────────────────────────────────────────────────────────
    ("#A30D2D", "brand red",                   "common"),
    ("#06D6A0", "teal-green",                  "common"),
    ("#FFD700", "gold",                        "common"),
    ("#1E40AF", "corporate deep blue",         "common"),
    ("#16A34A", "emerald",                     "common"),
    ("#DC2626", "corporate red",               "common"),
    ("#800020", "burgundy",                    "common"),
    ("#FF8C00", "orange",                      "common"),
    ("#8B0000", "dark crimson",                "common"),
    ("#4F46E5", "indigo",                      "common"),

    # ───────────────────────────────────────────────────────────
    # Hostile + edge cases (8) — the repair-loop stress test set
    # ───────────────────────────────────────────────────────────
    ("#DFFF00", "fluorescent yellow (hostile)",      "hostile"),
    ("#2A3A1A", "muddy dark green (hostile)",        "hostile"),
    ("#FAFAF7", "near-white (hostile)",              "hostile"),
    ("#0C0C0C", "near-black (hostile)",              "hostile"),
    ("#1B1B1B", "near-black grey",                   "hostile"),
    ("#FF0000", "pure primary red",                  "hostile"),
    ("#00FF00", "pure primary green",                "hostile"),
    ("#0000FF", "pure primary blue",                 "hostile"),

    # ───────────────────────────────────────────────────────────
    # Saturation extremes (5)
    # ───────────────────────────────────────────────────────────
    ("#FF00FF", "magenta",                     "saturated"),
    ("#00FFFF", "cyan",                        "saturated"),
    ("#FFFF00", "pure yellow",                 "saturated"),
    ("#F472B6", "hot pink",                    "saturated"),
    ("#8B5CF6", "violet",                      "saturated"),

    # ───────────────────────────────────────────────────────────
    # Pastels + harmonics (4)
    # ───────────────────────────────────────────────────────────
    ("#84CC2E", "lime green",                  "pastel"),
    ("#E11D48", "rose",                        "pastel"),
    ("#0EA5E9", "sky blue",                    "pastel"),
    ("#7C3AED", "vivid purple",                "pastel"),
]


def snapshot_filename_for(seed_hex: str) -> str:
    """Return the canonical snapshot filename for a seed hex.

    Strips the leading ``#``, lowercases, and appends ``.json`` —
    yielding e.g. ``"a30d2d.json"`` for ``"#A30D2D"``.
    """
    return seed_hex.lstrip("#").lower() + ".json"


def assert_catalogue_invariants() -> None:
    """Programmatic invariants the catalogue must satisfy. Used by
    test_seeds_catalogue.py and the regenerator script."""
    import re

    # Exactly 30 entries per the Stage I brief.
    assert len(SEEDS_CATALOGUE) == 30, (
        f"catalogue has {len(SEEDS_CATALOGUE)} entries, expected 30"
    )

    # Every hex is a valid 6-digit hex with the leading #.
    hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
    for hex_str, label, category in SEEDS_CATALOGUE:
        assert hex_re.fullmatch(hex_str), f"bad hex: {hex_str!r}"
        assert label.strip(), f"empty label for {hex_str}"
        assert category in {
            "identity", "common", "hostile", "saturated", "pastel",
        }, f"bad category {category!r} for {hex_str}"

    # No duplicate hexes.
    seen = set()
    for hex_str, label, category in SEEDS_CATALOGUE:
        normalised = hex_str.upper()
        assert normalised not in seen, f"duplicate hex: {hex_str}"
        seen.add(normalised)

    # Labels are unique (so test failure messages are unambiguous).
    labels = [label for _h, label, _c in SEEDS_CATALOGUE]
    assert len(set(labels)) == len(labels), (
        "duplicate labels in catalogue: "
        + repr([l for l in labels if labels.count(l) > 1])
    )
