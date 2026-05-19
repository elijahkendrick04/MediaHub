"""link_learners/block_detector.py — B8. Block detector learner.

Given a fetched response (status + headers + body excerpt), classify
it into one of:

    real_content       — readable body with meaningful text
    soft_blocked_spa   — HTML present but body is essentially empty
                          (JS-only SPA — typical Instagram unauth response)
    hard_blocked       — Cloudflare / captcha / "access denied" page
    auth_walled        — 401 / 403 / "please sign in"
    rate_limited       — 429 / "too many requests"
    not_found          — 404 / "this page does not exist"
    unknown            — body received but classifier can't decide

The handler uses this to decide whether to (a) trust the result and
hand it to the content extractor, (b) try an alternative endpoint, or
(c) ask the strategy proposer for a new approach.

LLM-driven so the classifier improves as Claude itself sharpens. When
the cloud LLM is unreachable, a deterministic structural classifier
runs against the response (response code + body shape) so the scraper
can still make a binary "loaded vs blocked" call — this is a
mechanical detector, not an AI stand-in. AI-driven surfaces elsewhere
in the codebase surface ``ClaudeUnavailableError`` when the LLM is
missing rather than inventing output.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


VALID_STATUSES: tuple[str, ...] = (
    "real_content",
    "soft_blocked_spa",
    "hard_blocked",
    "auth_walled",
    "rate_limited",
    "not_found",
    "unknown",
)


_HARD_BLOCK_PATTERNS = (
    r"\baccess denied\b", r"\bblocked\b", r"\bforbidden\b",
    r"\bcloudflare\b", r"\bcaptcha\b", r"\bare you a robot\b",
    r"\bsecurity check\b", r"\bdetected unusual traffic\b",
    r"\bplease enable cookies\b",
)

_AUTH_PATTERNS = (
    r"\bsign in\b", r"\blog in\b", r"\blogin to\b", r"\bsign up\b",
    r"\bregister to view\b", r"\bauthorisation required\b",
    r"\bauthorization required\b",
)

_NOT_FOUND_PATTERNS = (
    r"\b404\b", r"\bnot found\b", r"\bpage does not exist\b",
    r"\bsorry, this page isn't available\b",
)


def _heuristic(status_code: int, body: str) -> str:
    body = (body or "").strip()
    if status_code == 0:
        return "unknown"
    if status_code in (401, 403):
        return "auth_walled"
    if status_code == 404:
        return "not_found"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "unknown"
    if status_code != 200:
        return "unknown"
    # status == 200, but is the body real?
    if not body:
        return "soft_blocked_spa"

    # Strip tags for a rough visible-text estimate.
    visible = re.sub(r"<script[^>]*>.*?</script>", " ", body,
                      flags=re.IGNORECASE | re.DOTALL)
    visible = re.sub(r"<style[^>]*>.*?</style>", " ", visible,
                      flags=re.IGNORECASE | re.DOTALL)
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = re.sub(r"\s+", " ", visible).strip()

    low = visible.lower()
    if any(re.search(p, low) for p in _HARD_BLOCK_PATTERNS):
        return "hard_blocked"
    if any(re.search(p, low) for p in _AUTH_PATTERNS) and len(visible) < 1_500:
        return "auth_walled"
    if any(re.search(p, low) for p in _NOT_FOUND_PATTERNS) and len(visible) < 1_500:
        return "not_found"

    # The classic JS-SPA tell — body is almost entirely a noscript
    # placeholder, often under 800 visible chars after tag strip.
    if len(visible) < 350:
        return "soft_blocked_spa"

    return "real_content"


_LLM_SYSTEM = (
    "You classify web responses for a brand-intelligence system. You "
    "are given the HTTP status, key response headers, and a body "
    "excerpt. You return ONE of these labels in JSON: "
    "real_content, soft_blocked_spa, hard_blocked, auth_walled, "
    "rate_limited, not_found, unknown. Be conservative — only label "
    "something 'real_content' if you can clearly see human-readable "
    "text describing the organisation, not just navigation, "
    "boilerplate, or markup. Soft_blocked_spa means the page rendered "
    "an HTML shell but the body has no actual content."
)


def _build_prompt(url: str, status_code: int, headers: dict, body: str) -> str:
    body_excerpt = (body or "")[:6_000]
    hdr_lines = [f"  {k}: {v}" for k, v in (headers or {}).items()
                  if k.lower() in (
                      "content-type", "server", "x-frame-options",
                      "content-security-policy", "set-cookie",
                      "location", "retry-after",
                  )]
    parts = [
        f"URL: {url}",
        f"HTTP status: {status_code}",
        "Key headers:",
        *(hdr_lines or ["  (none captured)"]),
        "Body excerpt:",
        body_excerpt or "(empty body)",
        "",
        "Return JSON: { \"label\": <one of: real_content, "
        "soft_blocked_spa, hard_blocked, auth_walled, rate_limited, "
        "not_found, unknown>, \"reason\": <short string> }",
    ]
    return "\n".join(parts)


def classify(
    url: str,
    *,
    status_code: int = 0,
    headers: Optional[dict] = None,
    body: str = "",
    use_llm: bool = True,
) -> dict:
    """Classify a single fetch outcome.

    Returns ``{"label": <str>, "reason": <str>, "source": "llm"|"heuristic"}``.
    Never raises.
    """
    heuristic_label = _heuristic(status_code, body)
    # For unambiguous cases we don't even need to spend an LLM call.
    if not use_llm or heuristic_label in ("not_found", "auth_walled", "rate_limited"):
        return {
            "label": heuristic_label,
            "reason": f"HTTP {status_code} signal" if status_code else "no status",
            "source": "heuristic",
        }
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return {"label": heuristic_label, "reason": "no LLM", "source": "heuristic"}
    if not is_available():
        return {"label": heuristic_label, "reason": "no LLM", "source": "heuristic"}
    prompt = _build_prompt(url, status_code, headers or {}, body)
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=200, fallback={})
    except Exception as e:
        log.debug("block-detector LLM call failed: %s", e)
        return {"label": heuristic_label, "reason": "llm error", "source": "heuristic"}
    if not isinstance(raw, dict):
        return {"label": heuristic_label, "reason": "llm bad shape", "source": "heuristic"}
    label = raw.get("label")
    if not isinstance(label, str) or label not in VALID_STATUSES:
        return {"label": heuristic_label, "reason": "llm bad label", "source": "heuristic"}
    reason = raw.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return {"label": label, "reason": reason.strip()[:240], "source": "llm"}


__all__ = ["classify", "VALID_STATUSES"]
