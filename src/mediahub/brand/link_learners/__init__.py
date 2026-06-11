"""link_learners/ — five cross-cutting LLM capabilities used by link_handlers/.

The user's directive: "The AI should be taught how to read and interact
with these links (and never forget how to)." None of the per-platform
extraction logic is hardcoded. Instead, the handlers delegate every
semantic decision to one of these learners:

  - strategy.propose_strategy(url, sample_fetch)
      → "given what you just saw, here's the next scrape strategy"
  - block_detector.classify(response_meta, body_excerpt)
      → "is this a real page, soft-blocked SPA, auth wall, rate limit,
         or 404?"
  - endpoint_discoverer.propose_alternatives(url, prev_strategy, last_status)
      → "the primary endpoint is blocked, here are public alternatives"
  - content_extractor.extract_brand_dna(raw_text, platform_intent)
      → "given raw scraped text, extract voice, keywords, phrases,
         palette, hashtags relevant to ``platform_intent``"

The fifth "learner" is the persistent memory at brand.playbooks —
loaded as a sibling module so all the AI-driven decisions can be
recorded, replayed, and audited.
"""

from __future__ import annotations

from . import block_detector, content_extractor, endpoint_discoverer, strategy

__all__ = ["strategy", "block_detector", "endpoint_discoverer", "content_extractor"]
