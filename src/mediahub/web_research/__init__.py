"""
web_research — V7.4

Live web research module that works in the published sandbox.

Primary path: pplx CLI (subprocess) — works in dev/local env
Fallback path: DuckDuckGo HTML scraping — works everywhere

Usage:
    from mediahub.web_research.search import WebResearcher, SearchResult

    researcher = WebResearcher()
    results = researcher.search("Manchester Aquatics Centre swimming", num=5)
    for r in results:
        print(r.title, r.url)
"""
from .search import WebResearcher, SearchResult

__all__ = ["WebResearcher", "SearchResult"]
