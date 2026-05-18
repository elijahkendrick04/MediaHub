"""brand/social_dna.py — public capture entry point for the first-run org setup.

Historically this module contained per-platform fetchers + a single
"interpret-it-all-at-once" LLM call. That hardcoded extractor was the
exact thing the user asked to replace: "none of this should be
hardcoded — the AI should be taught how to read and interact with
these links (and never forget how to)".

The new pipeline lives in:

    mediahub.brand.link_handlers   — six per-platform orchestrators
    mediahub.brand.link_learners   — five LLM-driven capabilities
    mediahub.brand.playbooks       — persistent learned strategies

This module is now thin: it kept its public `capture_from_socials()`
entry point (so /organisation/setup/capture and existing callers
don't need to change) and the on-disk cache. Internally it delegates
to ``link_handlers.process_links`` and maps the result back to the
legacy ClubProfile-friendly dict shape.

Public surface (unchanged):
    capture_from_socials(social_links, website_url, *, force=False) -> dict
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.brand import link_handlers

log = logging.getLogger(__name__)


# Platforms we recognise on the signup form. Each name maps to a handler
# module in ``link_handlers``. Unknown platforms fall through to a
# generic web fetch via the website handler.
SUPPORTED_PLATFORMS: tuple[str, ...] = (
    "instagram",
    "facebook",
    "twitter",
    "tiktok",
    "linkedin",
)


# ---------------------------------------------------------------------------
# On-disk cache (kept for parity with the pre-refactor behaviour — the
# capture step can be expensive when the LLM is involved, so a stable
# cache key avoids re-running on every form submit).
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    base = os.environ.get("DATA_DIR")
    if base:
        d = Path(base) / "social_dna_cache"
    else:
        d = Path(__file__).resolve().parents[1] / "data" / "social_dna_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(website_url: str, social_links: dict[str, str]) -> str:
    parts = [(website_url or "").strip().lower()]
    for k in sorted(social_links or {}):
        v = (social_links.get(k) or "").strip().lower()
        if v:
            parts.append(f"{k}|{v}")
    blob = "::".join(parts) or "empty"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _cache_path(website_url: str, social_links: dict[str, str]) -> Path:
    return _cache_dir() / f"{_cache_key(website_url, social_links)}.json"


def _load_cache(website_url: str, social_links: dict[str, str]) -> Optional[dict]:
    p = _cache_path(website_url, social_links)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(website_url: str, social_links: dict[str, str], payload: dict) -> None:
    try:
        p = _cache_path(website_url, social_links)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("social-dna cache write failed: %s", e)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Output shape — preserved so downstream consumers (ClubProfile field
# assignment in web.py, brand.context._dna_prose, brand.derived, etc.)
# don't need to change.
# ---------------------------------------------------------------------------

def _empty_result(primary_url: str, status: str) -> dict:
    return {
        "brand_voice_summary": "",
        "brand_keywords": [],
        "brand_palette_extracted": {},
        "brand_logo_url": "",
        "brand_typography_hint": "",
        "brand_phrases_to_avoid": [],
        "brand_phrases_to_use": [],
        "brand_source_url": primary_url,
        "brand_captured_at": _now_iso(),
        "brand_capture_status": status,
        "voice_profile": {},
        "social_links_status": {},
        "captions_captured": 0,
        "link_capture_state": {},
    }


def _palette_from_extractor(merged_dna: dict) -> dict:
    """Map content_extractor's ``palette_mentions`` list to the
    primary/secondary/accent slot dict ClubProfile expects.
    """
    pal: dict[str, str] = {}
    mentions = merged_dna.get("palette_mentions") or []
    slots = ["primary", "secondary", "accent"]
    for i, c in enumerate(mentions[:3]):
        pal[slots[i]] = c
    return pal


def _map_handlers_output(
    handler_out: dict,
    *,
    primary_url: str,
) -> dict:
    """Translate ``link_handlers.process_links()`` output back into the
    ClubProfile-friendly dict shape the capture route writes from.
    """
    out = _empty_result(primary_url, "no_sources")
    dna = handler_out.get("merged_dna") or {}
    state = handler_out.get("state") or {}
    if not handler_out.get("any_real") and not dna:
        # Nothing readable at all.
        out["brand_capture_status"] = "fetch_failed_all"
        out["social_links_status"] = {
            k: v.get("status", "unknown") for k, v in state.items()
        }
        out["link_capture_state"] = state
        return out

    out["brand_voice_summary"] = (dna.get("voice_summary") or "")[:800]
    out["brand_keywords"] = list(dna.get("keywords") or [])[:12]
    out["brand_phrases_to_use"] = list(dna.get("phrases_to_use") or [])[:6]
    out["brand_phrases_to_avoid"] = list(dna.get("phrases_to_avoid") or [])[:5]
    out["brand_typography_hint"] = dna.get("typography_hint") or ""
    pal = _palette_from_extractor(dna)
    if pal:
        out["brand_palette_extracted"] = pal
    out["social_links_status"] = {
        k: v.get("status", "unknown") for k, v in state.items()
    }
    out["link_capture_state"] = state
    out["captions_captured"] = sum(
        1 for s in state.values() if s.get("voice_digest")
    )
    out["brand_capture_status"] = "ok" if handler_out.get("any_real") else "ok_heuristic"
    return out


# ---------------------------------------------------------------------------
# Public API — unchanged signature, AI-driven internals
# ---------------------------------------------------------------------------

def capture_from_socials(
    social_links: Optional[dict[str, str]] = None,
    website_url: str = "",
    *,
    force: bool = False,
) -> dict:
    """Build a unified brand+voice profile from a website + social links.

    Returns a dict matching the legacy schema documented at the top of
    this module. Always returns; never raises.

    Internals now delegate every per-platform fetch + extraction to the
    AI-driven ``link_handlers`` + ``link_learners`` pipeline. No
    hardcoded "if instagram do X" logic remains here.
    """
    social_links = {
        k.lower(): (v or "").strip()
        for k, v in (social_links or {}).items()
        if v
    }
    website_url = (website_url or "").strip()
    if website_url and not re.match(r"^https?://", website_url, re.I):
        website_url = "https://" + website_url
    for k in list(social_links):
        u = social_links[k]
        if u and not re.match(r"^https?://", u, re.I):
            social_links[k] = "https://" + u

    primary = website_url or next(iter(social_links.values()), "")
    if not primary:
        return _empty_result("", "no_sources")

    if not force:
        cached = _load_cache(website_url, social_links)
        if (
            cached
            and isinstance(cached, dict)
            and cached.get("brand_capture_status") in ("ok", "ok_heuristic")
        ):
            return cached

    try:
        handler_out = link_handlers.process_links(
            website_url=website_url,
            social_links=social_links,
        )
    except Exception as e:
        log.debug("link_handlers pipeline failed: %s", e)
        out = _empty_result(primary, f"error: {e}")
        return out

    out = _map_handlers_output(handler_out, primary_url=primary)
    out["brand_source_url"] = primary
    out["brand_captured_at"] = _now_iso()

    if out["brand_capture_status"] in ("ok", "ok_heuristic"):
        _save_cache(website_url, social_links, out)
    return out


__all__ = ["capture_from_socials", "SUPPORTED_PLATFORMS"]
