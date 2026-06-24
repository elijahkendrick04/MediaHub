"""governance/features.py — the registry of metered/governed AI features (1.23).

A single, deterministic source of truth for *which* AI surfaces governance knows
about: their stable key (stored in the usage ledger and quota config), a human
label, and a one-line description for the dashboard and settings UI. Quota
limits (:mod:`mediahub.governance.quota`) and role permissions
(:mod:`mediahub.governance.permissions`) both key off these constants, so adding
a feature is a one-line edit here rather than a string scattered across modules.

Pure data — no I/O, no Flask — so it is trivially testable and importable
anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---- canonical feature keys ----------------------------------------------
# Stored verbatim in feature_uses.feature and in MEDIAHUB_QUOTA_<FEATURE>_<PLAN>
# env names (upper-cased). Keep them short, lowercase, and stable.

FEATURE_CAPTION = "caption"
FEATURE_IMAGINE = "imagine"
FEATURE_BRAND = "brand_interpret"
FEATURE_PALETTE = "palette"
FEATURE_DESCRIBE = "describe"
FEATURE_DNA = "brand_dna"
FEATURE_RESEARCH = "research"
FEATURE_TRANSLATE = "translate"


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    description: str
    # Whether this feature meters through the shared feature_quota ledger.
    # Generative imagery (FEATURE_IMAGINE) keeps its own dedicated imagine_uses
    # ledger and enforcement, so it is governed for *permissions* but its counts
    # come from imagine_usage, not feature_quota.
    metered_here: bool = True


_FEATURES: dict[str, FeatureSpec] = {
    FEATURE_CAPTION: FeatureSpec(
        FEATURE_CAPTION,
        "AI captions",
        "Generate and rewrite post captions, alt-text and platform variants.",
    ),
    FEATURE_IMAGINE: FeatureSpec(
        FEATURE_IMAGINE,
        "Generative imagery",
        "Generate, edit, expand, remove, upscale and style-match images.",
        metered_here=False,
    ),
    FEATURE_BRAND: FeatureSpec(
        FEATURE_BRAND,
        "Brand interpretation",
        "Interpret brand guidelines and derive the club's operating profile.",
    ),
    FEATURE_PALETTE: FeatureSpec(
        FEATURE_PALETTE,
        "Palette resolution",
        "Resolve the brand colour palette from logos, guidelines and the site.",
    ),
    FEATURE_DESCRIBE: FeatureSpec(
        FEATURE_DESCRIBE,
        "Media tagging",
        "Tag photos from a free-text description (athletes, venue, event).",
    ),
    FEATURE_DNA: FeatureSpec(
        FEATURE_DNA,
        "Brand DNA capture",
        "Capture a brand profile from the club's website.",
    ),
    FEATURE_RESEARCH: FeatureSpec(
        FEATURE_RESEARCH,
        "Web research",
        "Search the web and run bounded deep-research lookups.",
    ),
    FEATURE_TRANSLATE: FeatureSpec(
        FEATURE_TRANSLATE,
        "AI translation",
        "Translate captions, cards and reel narration into other languages (1.24).",
    ),
}


def all_features() -> list[FeatureSpec]:
    """Every registered feature, in declaration order (stable for the UI)."""
    return list(_FEATURES.values())


def feature_keys() -> list[str]:
    """Just the keys, in declaration order."""
    return list(_FEATURES.keys())


def is_feature(key: object) -> bool:
    """True when ``key`` is a registered feature key."""
    return normalise(key) in _FEATURES


def normalise(key: object) -> str:
    """Lowercase/strip a feature key for storage and lookup."""
    return str(key or "").strip().lower()


def spec_for(key: object) -> FeatureSpec | None:
    """The :class:`FeatureSpec` for ``key``, or None if unknown."""
    return _FEATURES.get(normalise(key))


def label_for(key: object) -> str:
    """Human label for a feature, falling back to the raw key."""
    spec = spec_for(key)
    return spec.label if spec else (normalise(key) or "unknown")


__all__ = [
    "FEATURE_CAPTION",
    "FEATURE_IMAGINE",
    "FEATURE_BRAND",
    "FEATURE_PALETTE",
    "FEATURE_DESCRIBE",
    "FEATURE_DNA",
    "FEATURE_RESEARCH",
    "FEATURE_TRANSLATE",
    "FeatureSpec",
    "all_features",
    "feature_keys",
    "is_feature",
    "normalise",
    "spec_for",
    "label_for",
]
