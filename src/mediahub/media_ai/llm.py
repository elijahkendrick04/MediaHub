"""media_ai/llm.py — Claude Sonnet wrapper with multi-tier fallback.

Resolution order:
  1. Computer LLM bridge (pplx-tool / llm_bridge) if PPLX_TOOL_BRIDGE_* env set
  2. Anthropic SDK if ANTHROPIC_API_KEY env set
  3. Heuristic fallback (deterministic, never crashes)

All public functions are tolerant: they always return a usable string/dict
even when no LLM is reachable. Tests rely on the fallback path.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("MEDIAHUB_LLM_MODEL", "claude-sonnet-4-5-20250929")
ALT_MODEL = "claude-3-5-sonnet-20241022"


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _has_pplx_bridge() -> bool:
    return bool(os.environ.get("PPLX_TOOL_BRIDGE_LOCAL_URL")
                and os.environ.get("PPLX_TOOL_BRIDGE_TOKEN"))


def _resolve_anthropic_key() -> Optional[str]:
    """Return env ANTHROPIC_API_KEY, else key from data/secrets.json, else None."""
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env and env.strip():
        return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret("anthropic_api_key")
        return v if v else None
    except Exception:
        return None


def _has_anthropic_key() -> bool:
    return bool(_resolve_anthropic_key())


def is_available() -> bool:
    """True if a real LLM is reachable. Tests + UI use this for badges."""
    return _has_pplx_bridge() or _has_anthropic_key()


# ---------------------------------------------------------------------------
# Provider 1: pplx-tool bridge (Computer's LLM)
# ---------------------------------------------------------------------------

def _call_pplx_bridge(messages: list[dict], system: Optional[str], max_tokens: int) -> Optional[str]:
    """Try the Computer pplx-tool bridge. Returns None on failure."""
    if not _has_pplx_bridge():
        return None
    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if system:
        payload["system"] = system
    try:
        r = subprocess.run(
            ["pplx-tool", "anthropic_message", json.dumps(payload)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            log.debug("pplx bridge non-zero: %s", r.stderr[:200])
            return None
        out = json.loads(r.stdout or "{}")
        # Try common shapes
        if isinstance(out, dict):
            if "content" in out and isinstance(out["content"], list):
                # Anthropic-style content blocks
                texts = [b.get("text", "") for b in out["content"] if isinstance(b, dict)]
                return "".join(texts).strip() or None
            if "text" in out:
                return str(out["text"]).strip()
            if "message" in out and isinstance(out["message"], dict):
                return str(out["message"].get("content", "")).strip() or None
        return None
    except Exception as e:
        log.debug("pplx bridge error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Provider 2: Anthropic SDK
# ---------------------------------------------------------------------------

_anthropic_client = None


_anthropic_client_key = None  # cache key the client was built for, so rotation works


def _get_anthropic():
    """Return an anthropic.Anthropic client built with the currently-resolved key.

    Rebuilds when the key changes (e.g. user pasted a new key in /settings).
    """
    global _anthropic_client, _anthropic_client_key
    key = _resolve_anthropic_key()
    if not key:
        return None
    if _anthropic_client and _anthropic_client_key == key:
        return _anthropic_client
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=key)
        _anthropic_client_key = key
    except Exception as e:
        log.debug("anthropic import/init failed: %s", e)
        _anthropic_client = False
        _anthropic_client_key = None
    return _anthropic_client if _anthropic_client else None


def _call_anthropic(messages: list[dict], system: Optional[str], max_tokens: int,
                    model: Optional[str] = None) -> Optional[str]:
    if not _has_anthropic_key():
        return None
    client = _get_anthropic()
    if not client:
        return None
    use_model = model or DEFAULT_MODEL
    for attempt_model in (use_model, ALT_MODEL):
        try:
            kwargs = {
                "model": attempt_model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if system:
                kwargs["system"] = system
            resp = client.messages.create(**kwargs)
            parts = [b.text for b in resp.content if hasattr(b, "text")]
            return "".join(parts).strip() or None
        except Exception as e:
            log.debug("anthropic call failed (%s): %s", attempt_model, e)
            continue
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(prompt: str, *, system: Optional[str] = None, max_tokens: int = 1024,
             messages: Optional[list[dict]] = None) -> str:
    """Generate plain text. Always returns a string.

    Args:
        prompt: user message text. Ignored if messages= is given.
        system: optional system prompt.
        max_tokens: token cap.
        messages: full message list (overrides prompt).
    """
    msgs = messages if messages else [{"role": "user", "content": prompt}]

    # Try bridges
    out = _call_pplx_bridge(msgs, system, max_tokens)
    if out:
        return out
    out = _call_anthropic(msgs, system, max_tokens)
    if out:
        return out

    # Heuristic fallback
    return _heuristic_response(prompt, system)


def generate_json(prompt: str, *, system: Optional[str] = None, max_tokens: int = 1024,
                  fallback: Optional[dict] = None) -> dict:
    """Generate JSON. Strips fences, falls back gracefully.

    On failure or unparseable output: returns `fallback` if given, else {}.
    """
    sys_with_json = (system or "") + (
        "\n\nReturn ONLY a JSON object. No prose, no fences."
    )
    raw = generate(prompt, system=sys_with_json.strip(), max_tokens=max_tokens)
    parsed = _extract_json(raw)
    if parsed is not None:
        return parsed
    return fallback if fallback is not None else {}


def generate_vision(image_paths: list[str], prompt: str, *, system: Optional[str] = None,
                    max_tokens: int = 1024) -> str:
    """Vision generation — analyses one or more local images.

    Returns the model's text. Falls back to heuristic when no API.
    """
    if not _has_anthropic_key():
        return _heuristic_response(prompt, system)
    client = _get_anthropic()
    if not client:
        return _heuristic_response(prompt, system)
    import base64
    content_blocks: list[dict] = []
    for p in image_paths[:5]:  # cap to 5
        try:
            with open(p, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            mt = "image/png"
            if p.lower().endswith((".jpg", ".jpeg")):
                mt = "image/jpeg"
            elif p.lower().endswith(".webp"):
                mt = "image/webp"
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": data},
            })
        except Exception as e:
            log.debug("vision image read failed: %s", e)
    content_blocks.append({"type": "text", "text": prompt})
    try:
        kwargs = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": content_blocks}],
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        parts = [b.text for b in resp.content if hasattr(b, "text")]
        return "".join(parts).strip() or _heuristic_response(prompt, system)
    except Exception as e:
        log.debug("vision call failed: %s", e)
        return _heuristic_response(prompt, system)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    s = text.strip()
    # Strip markdown fences
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    # Find first {
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(s[start:end + 1])
    except Exception:
        return None


def _heuristic_response(prompt: str, system: Optional[str]) -> str:
    """Deterministic fallback when no LLM is reachable.

    Tries to detect intent from system+prompt and emit something usable.
    Tests for absence/presence of specific words depend on this output
    so keep it stable.
    """
    full = ((system or "") + "\n" + (prompt or "")).lower()

    # JSON structured (description parsing or brief) — check first; takes priority
    if "json" in full or "return only" in full:
        return "{}"
    # Alt text
    if "alt text" in full or "alt-text" in full or "accessibility" in full:
        return _heuristic_alt(prompt)
    # Caption generation
    if "caption" in full or "instagram" in full or "social" in full or "post" in full:
        return _heuristic_caption(prompt)
    return "Generated content unavailable — using deterministic fallback."


def _heuristic_caption(prompt: str) -> str:
    """Simple template caption from the prompt fields if recognisable."""
    name_match = re.search(r"(?:swimmer|athlete)[:=]\s*([^\n,]+)", prompt, re.I)
    event_match = re.search(r"event[:=]\s*([^\n,]+)", prompt, re.I)
    result_match = re.search(r"(?:result|time)[:=]\s*([^\n,]+)", prompt, re.I)
    name = name_match.group(1).strip() if name_match else "the swimmer"
    event = event_match.group(1).strip() if event_match else "the event"
    result = result_match.group(1).strip() if result_match else ""
    if result:
        return f"Massive swim from {name} — {result} in the {event}. One for the grid."
    return f"Strong swim from {name} in the {event}. Proud of the work."


def _heuristic_alt(prompt: str) -> str:
    return ("Branded social graphic celebrating a swimming achievement, "
            "featuring an athlete photo with bold typography and club colours.")


# ---------------------------------------------------------------------------
# V8 compatibility alias: call_claude() wraps generate() for ai_caption.py
# ---------------------------------------------------------------------------

class ClaudeUnavailableError(RuntimeError):
    """Raised when the LLM cannot be reached (no key, no bridge, etc.)."""


def call_claude(
    system: str,
    user: str,
    model: Optional[str] = None,
    max_tokens: int = 512,
) -> str:
    """
    V8 Live Caption API: call Claude Sonnet and return its text.

    Uses the existing multi-tier generate() internals.
    Raises ClaudeUnavailableError if no LLM provider is available.
    """
    if not is_available():
        raise ClaudeUnavailableError("No LLM provider available (no API key or bridge)")
    result = generate(user, system=system, max_tokens=max_tokens)
    if not result or result.startswith("Generated content unavailable"):
        raise ClaudeUnavailableError("LLM returned empty or heuristic fallback")
    return result


__all__ = ["generate", "generate_json", "generate_vision", "is_available",
           "call_claude", "ClaudeUnavailableError"]
