"""ad_export — sponsor A/B ad-variant sets, prepared not placed (roadmap 1.14).

The paid-distribution counterpart to ``channel_preview``. A sponsor-activation
draft already holds several copy angles (the cards the content engine generated);
this turns them into an **A/B creative set** — each angle a labelled variant,
tagged with the sponsor, laid out against an ad platform's required sizes
(``specs``) — and exports a manifest a club hands to whoever runs the campaign.

MediaHub **prepares, never spends**: no ad-account API, no spend automation, no
auto-publish (standing rule). Pure, deterministic, offline — mechanical sizing +
the club's own copy.
"""

from .specs import AD_PLATFORMS, AdPlatform, AdSize, ad_platform, all_ad_platforms
from .variants import AdVariant, AdVariantSet, build_variant_set, manifest_text

__all__ = [
    "AD_PLATFORMS",
    "AdPlatform",
    "AdSize",
    "AdVariant",
    "AdVariantSet",
    "ad_platform",
    "all_ad_platforms",
    "build_variant_set",
    "manifest_text",
]
