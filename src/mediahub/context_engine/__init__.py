"""
context_engine — V7.5 Context Engine public API.

Provides live research capabilities: meet identity discovery,
domain trust scoring, ontology growth, and a persistent cache layer.

No hardcoded references to any specific data sources — the engine
discovers and learns from live web research.
"""

from .identity import discover_meet_identity, MeetIdentity
from .trust import score_domain, rank_candidates
from .ontology import note_new_term, load_ontology
from .cache import DiscoveryCache
from .research import ResearchClient

__all__ = [
    "discover_meet_identity",
    "MeetIdentity",
    "score_domain",
    "rank_candidates",
    "note_new_term",
    "load_ontology",
    "DiscoveryCache",
    "ResearchClient",
]
