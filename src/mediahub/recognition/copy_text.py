"""
recognition/copy_text.py — Plain-text copy builder for cards.

build_caption_text(card, mode) returns plain text suitable for clipboard.
Zero HTML tags or inline style fragments.
"""
from __future__ import annotations

import re


def _strip_html(text: str) -> str:
    """Remove any HTML tags that might have snuck in."""
    clean = re.sub(r"<[^>]+>", "", text or "")
    # Also decode common HTML entities
    clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    clean = clean.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    return clean.strip()


def build_caption_text(card: dict, mode: str = "caption_only") -> str:
    """
    Returns plain text suitable for clipboard.

    mode:
      - "caption_only"    headline + body, no hashtags, no formatting
      - "with_hashtags"   caption + hashtags (from voice profile or card)
      - "full_brief"      caption + hashtags + sources + safe-to-post note + suggested post type

    Guarantees: zero HTML tags, zero inline style fragments.
    """
    # Support both V4 card format (captions.clean/hype/team) and
    # V5 recognition format (active_caption with headline/body/cta)
    cap = card.get("active_caption") or {}
    if not cap:
        # Try V4 format: prefer 'clean' caption
        captions = card.get("captions") or {}
        headline = _strip_html(card.get("headline", ""))
        body = _strip_html(captions.get("clean") or captions.get("team") or captions.get("hype") or "")
        cta = ""
    else:
        headline = _strip_html(cap.get("headline", ""))
        body = _strip_html(cap.get("body", ""))
        cta = _strip_html(cap.get("cta", ""))

    # Fallback: use card-level headline if not in caption
    if not headline:
        headline = _strip_html(card.get("headline", ""))

    parts: list[str] = []

    if headline:
        parts.append(headline)
    if body:
        if parts:
            parts.append("")
        parts.append(body)
    if cta:
        parts.append(cta)

    if mode in ("with_hashtags", "full_brief"):
        hashtags = card.get("hashtags") or []
        if hashtags:
            parts.append("")
            parts.append(" ".join(_strip_html(h) for h in hashtags))

    if mode == "full_brief":
        parts.append("")
        parts.append("---")
        post_type = _strip_html(card.get("suggested_post_type") or card.get("post_type") or "main_feed")
        parts.append(f"Suggested format: {post_type}")

        confidence = card.get("confidence") or card.get("priority", "")
        if confidence:
            if isinstance(confidence, float):
                parts.append(f"Confidence: {confidence:.0%}")
            else:
                parts.append(f"Confidence: {_strip_html(str(confidence))}")

        s2p = card.get("safe_to_post") or {}
        if isinstance(s2p, dict) and s2p.get("level"):
            parts.append(f"Safe to post: {s2p['level']} — {_strip_html(s2p.get('reason', ''))}")

        post_angle = card.get("post_angle", "")
        if post_angle:
            parts.append(f"Post angle: {_strip_html(post_angle)}")

        # Evidence / sources
        evidence = card.get("evidence") or []
        if evidence:
            parts.append("Sources:")
            for e in evidence[:3]:
                url = e.get("source_url") or e.get("url") or ""
                name = e.get("source_name") or e.get("name") or ""
                stmt = e.get("statement") or ""
                line = f"  - {_strip_html(name)}"
                if url:
                    line += f" ({_strip_html(url)})"
                if stmt:
                    line += f": {_strip_html(stmt)}"
                parts.append(line)

    result = "\n".join(parts)
    # Final safety: ensure no HTML remains
    if "<" in result and ">" in result:
        result = _strip_html(result)
    return result


__all__ = ["build_caption_text"]
