# ad_export

Sponsor **A/B ad-variant sets**, prepared — never placed (roadmap **1.14**).

A sponsor-activation draft already holds several copy angles (the cards the
content engine generated). This turns them into an **A/B creative set** for a
paid campaign: each angle becomes a labelled variant (A, B, C…), tagged with the
sponsor, laid out against an ad platform's required sizes, and bundled into an
export manifest the club hands to whoever runs the ads.

> **MediaHub prepares, never spends.** There is no ad-account API, no spend
> automation, and no auto-publish here (standing rule). The output is creative +
> a plain-text manifest for *manual* upload, where a human controls targeting and
> spend. The downstream performance can be logged back through the 1.14 analytics
> loop.

## Files

- `specs.py` — the ad-platform creative **sizes** as data: `AdPlatform` /
  `AdSize` and the `AD_PLATFORMS` registry (Meta, Google Display, LinkedIn,
  TikTok). `ad_platform(slug)` looks one up (alias-tolerant). Each platform
  carries a `source`; sizes are sourced, common-denominator creatives for
  preparation, not a parity guarantee.
- `variants.py` — `build_variant_set(cards, sponsor, platform)` →
  `AdVariantSet` (one labelled variant per non-empty card, capped at
  `MAX_VARIANTS`), and `manifest_text(set)` for the export.

Pure, deterministic, offline — mechanical sizing plus the club's own copy.
Surface: **draft → Prepare ad set** (`/plan/ad-variants/<pack>`) and the export
at `/api/plan/ad-variants/<pack>/export`. Tests: `tests/test_ad_export.py`.
