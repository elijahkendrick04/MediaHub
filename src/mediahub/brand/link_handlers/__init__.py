"""link_handlers/ — six per-platform link orchestrators (B1-B6).

Each handler is a thin orchestrator: it knows which platform it
represents and what brand-intelligence intent to pass to the learners,
but it does NOT hardcode any extraction logic. Every semantic decision —
which endpoint to hit, whether the response is blocked, what to pull out
of the body — is delegated to ``link_learners``.

The shared orchestration lives in :func:`process_link` here so all six
handlers behave consistently. Per-platform files (website.py,
instagram.py, …) only override:

  - ``platform``       — short key matching ClubProfile.social_links
  - ``intent``         — free-form prose describing what the AI should
                          look for on this platform
  - ``normalise_url``  — optional, handles "@user" or bare-handle inputs

Drift detection is built into the orchestration: every call loads the
playbook for the domain, re-validates it if stale, and persists the
outcome. The audit log records every regeneration so the operator can
explain why a playbook changed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from mediahub.brand import playbooks
from mediahub.brand.link_learners import (
    block_detector,
    content_extractor,
    endpoint_discoverer,
    strategy as strategy_learner,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared HTTP fetcher — reuses the existing helper from social_dna so
# we don't duplicate the UA / timeout / size-cap config.
# ---------------------------------------------------------------------------


def _fetch_with_strategy(url: str, strat: dict) -> tuple[Optional[str], int, dict]:
    """Issue one fetch with the given strategy.

    Returns ``(body_text_or_None, status_code, response_headers)``.
    Status 0 == connection failure. Response headers are best-effort.
    """
    try:
        import requests
    except Exception:
        return None, 0, {}
    headers = strat.get("headers") if isinstance(strat.get("headers"), dict) else {}
    try:
        r = requests.get(
            url,
            headers=headers or {},
            timeout=15,
            allow_redirects=True,
        )
    except Exception as e:
        log.debug("strategy fetch failed for %s: %s", url, e)
        return None, 0, {}
    body = r.text or ""
    if len(body) > 2_000_000:
        body = body[:2_000_000]
    resp_headers = {k: v for k, v in r.headers.items()}
    return body, r.status_code, resp_headers


# ---------------------------------------------------------------------------
# URL-template expansion — handlers can declare {handle} / {slug}
# placeholders so the strategy generalises across orgs in the same
# domain.
# ---------------------------------------------------------------------------


def _expand(template: str, *, handle: str = "", slug: str = "", fallback_url: str = "") -> str:
    if not template:
        return fallback_url
    try:
        return template.format(handle=handle, slug=slug)
    except Exception:
        return template


def _handle_from_url(url: str) -> str:
    """Best-effort handle extraction. For instagram.com/foo → "foo",
    twitter.com/foo → "foo", linkedin.com/company/foo → "foo".

    Returns empty string if no handle can be derived; the orchestration
    falls back to using the raw URL in that case.
    """
    if not url:
        return ""
    from urllib.parse import urlparse

    try:
        path = urlparse(url if "://" in url else "https://" + url).path
    except Exception:
        return ""
    path = path.strip("/")
    if not path:
        return ""
    parts = path.split("/")
    # LinkedIn /company/<slug>, /school/<slug>, /in/<handle>
    if parts[0] in ("company", "school", "in") and len(parts) >= 2:
        return parts[1].lstrip("@")
    return parts[0].lstrip("@")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def process_link(
    platform: str,
    url: str,
    *,
    intent: str,
    normalise_url: Optional[Callable[[str], str]] = None,
) -> dict:
    """Run one URL through the full handler pipeline.

    Returns:
        {
          "platform":     str,
          "url":          str,    # post-normalisation
          "status":       str,    # block_detector label
          "playbook_age": int,    # days since last_validated_at (-1 if never)
          "regenerated":  bool,   # True if we re-asked the strategy proposer
          "dna":          dict,   # content_extractor output
        }
    Never raises.
    """
    base = {
        "platform": platform,
        "url": url or "",
        "status": "unknown",
        "playbook_age": -1,
        "regenerated": False,
        "dna": {},
    }
    if not url:
        base["status"] = "unknown"
        return base

    if normalise_url:
        try:
            url = normalise_url(url)
        except Exception:
            pass
    base["url"] = url

    domain = playbooks.domain_for(url)
    if not domain:
        base["status"] = "unknown"
        return base

    pb = playbooks.load(domain) or playbooks.empty_playbook(domain)
    handle = _handle_from_url(url)

    # ---- Stage 1: choose a strategy ----
    stale = playbooks.is_stale(pb)
    broken = playbooks.needs_regeneration(pb)
    if stale or broken or not pb.get("strategy"):
        playbooks.record_audit(
            {
                "domain": domain,
                "action": "regenerate",
                "reason": "stale" if stale else ("broken" if broken else "missing"),
                "platform": platform,
            }
        )
        # Use a single sample fetch with the default strategy to give
        # the strategy proposer something to read.
        default_strat = strategy_learner.default_strategy(url)
        body, code, hdrs = _fetch_with_strategy(url, default_strat)
        sample = {
            "status_code": code,
            "response_headers": hdrs,
            "body_excerpt": (body or "")[:8_000],
        }
        pb["strategy"] = strategy_learner.propose_strategy(
            url,
            platform_intent=intent,
            sample=sample,
        )
        base["regenerated"] = True
    else:
        playbooks.record_audit(
            {
                "domain": domain,
                "action": "replay",
                "platform": platform,
            }
        )

    # Compute current age (days since last_validated_at)
    last = pb.get("last_validated_at")
    if last:
        try:
            dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            base["playbook_age"] = (datetime.now(timezone.utc) - dt).days
        except Exception:
            pass

    strat = pb.get("strategy") or strategy_learner.default_strategy(url)
    primary_url = _expand(strat.get("url_template") or url, handle=handle, fallback_url=url)

    # ---- Stage 2: execute the strategy ----
    body, code, hdrs = _fetch_with_strategy(primary_url, strat)
    classification = block_detector.classify(
        primary_url,
        status_code=code,
        headers=hdrs,
        body=body or "",
    )
    label = classification["label"]
    base["status"] = label
    playbooks.record_attempt(pb, status=label, notes=primary_url, persist=False)

    # ---- Stage 3: if blocked, try alternatives ----
    if label != "real_content":
        alts = []
        # Replay the strategy's own alt_endpoints first
        for alt_tmpl in strat.get("alt_endpoints") or []:
            alt_url = _expand(alt_tmpl, handle=handle, fallback_url=alt_tmpl)
            if alt_url not in alts:
                alts.append(alt_url)
        # Then ask the discoverer for more if the strategy ones are exhausted
        if not alts:
            alts = endpoint_discoverer.propose_alternatives(
                primary_url,
                platform_intent=intent,
                last_status=label,
                last_strategy=strat,
            )
        for alt_url in alts:
            body, code, hdrs = _fetch_with_strategy(alt_url, strat)
            c2 = block_detector.classify(
                alt_url,
                status_code=code,
                headers=hdrs,
                body=body or "",
            )
            playbooks.record_attempt(pb, status=c2["label"], notes=alt_url, persist=False)
            if c2["label"] == "real_content":
                base["status"] = "real_content"
                # Remember the working alternative so the next run
                # tries it first.
                primary_url = alt_url
                strat.setdefault("alt_endpoints", [])
                if alt_url not in strat["alt_endpoints"]:
                    strat["alt_endpoints"].insert(0, alt_url)
                break

    # ---- Stage 4: extract brand DNA ----
    # ONLY extract for real_content. Earlier this branch also ran for
    # auth_walled / soft_blocked_spa / not_found / unknown bodies on
    # the theory that "some text is better than none" — but the bodies
    # in those states are login walls, scraping-gateway error JSON, or
    # captcha pages. Stuffing those into voice_summary poisoned every
    # downstream caption prompt for orgs whose website failed to load.
    if base["status"] == "real_content" and body:
        base["dna"] = content_extractor.extract_brand_dna(
            body,
            url=primary_url,
            platform_intent=intent,
        )
        # Colour-USAGE evidence (frequency-ranked), incl. linked CSS.
        # The brand-palette decision is made by the cloud LLM from this
        # evidence; we only gather it here. Best-effort: a CSS-fetch
        # failure just yields HTML-only counts and never blocks the
        # crawl. Only meaningful for full web pages (HTML + stylesheets),
        # so we gate on the body looking like markup.
        if "<" in body and platform in ("website", "site", "home"):
            try:
                from mediahub.brand.dna_capture import colour_usage_evidence

                usage = colour_usage_evidence(body, primary_url)
                if usage:
                    base["dna"]["colour_usage"] = [[h, c] for h, c in usage]
            except Exception as e:
                log.debug("colour-usage evidence failed for %s: %s", primary_url, e)

    # ---- Stage 5: persist ----
    try:
        playbooks.save(pb)
    except Exception as e:
        log.debug("playbook persist failed for %s: %s", domain, e)

    return base


# ---------------------------------------------------------------------------
# Convenience: dispatch by platform name
# ---------------------------------------------------------------------------

# Lazy imports — each platform module only loads the moment it's used.
# This also lets the per-platform tests stub a handler without dragging
# in the other five.


def get_handler(platform: str):
    p = (platform or "").lower().strip()
    if p in ("website", "site", "home"):
        from . import website as mod
    elif p == "instagram":
        from . import instagram as mod
    elif p == "facebook":
        from . import facebook as mod
    elif p in ("twitter", "x"):
        from . import twitter as mod
    elif p == "tiktok":
        from . import tiktok as mod
    elif p == "linkedin":
        from . import linkedin as mod
    else:
        return None
    return mod


def process_links(
    *,
    website_url: str = "",
    social_links: Optional[dict[str, str]] = None,
) -> dict:
    """High-level entry: run the website + any social links and return
    per-link state plus a merged brand-DNA snapshot.

    The merged DNA picks the richest signal from any single source
    (highest count of keywords + phrases) so the caller can write
    straight into ClubProfile.brand_* fields. Per-link detail goes into
    ``state`` for ClubProfile.link_capture_state.
    """
    social_links = social_links or {}
    result = {
        "state": {},  # platform → {url, status, dna_present, …}
        "merged_dna": {},  # picked-best fields for ClubProfile.brand_*
        "any_real": False,
    }

    per_link: list[dict] = []
    if website_url:
        mod = get_handler("website")
        if mod is not None:
            per_link.append(mod.process(website_url))
    for platform, url in social_links.items():
        if not url:
            continue
        mod = get_handler(platform)
        if mod is None:
            continue
        per_link.append(mod.process(url))

    for entry in per_link:
        dna = entry.get("dna") or {}
        result["state"][entry["platform"]] = {
            "url": entry["url"],
            "status": entry["status"],
            "playbook_age": entry["playbook_age"],
            "regenerated": entry["regenerated"],
            "voice_digest": dna.get("voice_summary", "")[:240],
            # Per-link palette_mentions surface here so the unified
            # palette resolver (brand.palette) can weight every source
            # independently. The merged_dna below only keeps the
            # richest single source, which would otherwise drop colours
            # mentioned only on, say, the Instagram bio.
            "palette_mentions": list(dna.get("palette_mentions") or []),
            # Frequency-ranked colour-USAGE evidence for the AI palette
            # resolver: [[hex, count], ...]. Only the website handler
            # populates it (that's where the real CSS lives).
            "colour_usage": list(dna.get("colour_usage") or []),
        }
        if entry["status"] == "real_content":
            result["any_real"] = True

    # Merge: pick the richest DNA across all real_content entries.
    best: dict = {}
    best_score = -1
    for entry in per_link:
        if entry["status"] != "real_content":
            continue
        dna = entry.get("dna") or {}
        score = (
            (1 if dna.get("voice_summary") else 0) * 3
            + len(dna.get("keywords") or [])
            + len(dna.get("phrases_to_use") or [])
            + len(dna.get("hashtag_patterns") or [])
        )
        if score > best_score:
            best_score = score
            best = dna
    result["merged_dna"] = best
    return result


__all__ = ["process_link", "process_links", "get_handler"]
