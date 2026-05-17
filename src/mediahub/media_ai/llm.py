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

# In-memory log of the most recent failure per provider. Surfaced by the
# /settings page so users can see WHY the LLM is falling back to heuristic
# instead of being told "key saved" while the provider 401s silently.
# Each entry: {"when": iso, "reason": str, "detail": str (truncated)}
_LAST_PROVIDER_ERROR: dict[str, dict[str, str]] = {}


def _record_provider_error(provider: str, reason: str, detail: str = "") -> None:
    from datetime import datetime, timezone
    _LAST_PROVIDER_ERROR[provider] = {
        "when": datetime.now(timezone.utc).isoformat(),
        "reason": str(reason)[:120],
        "detail": str(detail)[:500],
    }


def last_provider_errors() -> dict[str, dict[str, str]]:
    """Return a copy of the last-error log keyed by provider name."""
    return {k: dict(v) for k, v in _LAST_PROVIDER_ERROR.items()}


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


def _resolve_gemini_key() -> Optional[str]:
    """Return env GEMINI_API_KEY (or GOOGLE_API_KEY), else stored secret, else None.

    Google's free tier (Gemini 1.5/2.0 Flash) gives 15 RPM and 1,500 RPD with no
    credit card — ideal for self-hosted MediaHub deployments. Get a key at
    https://aistudio.google.com/apikey
    """
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env = os.environ.get(env_name)
        if env and env.strip():
            return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret("gemini_api_key")
        return v if v else None
    except Exception:
        return None


def _has_gemini_key() -> bool:
    return bool(_resolve_gemini_key())


# Whether the `claude` CLI (Claude Code) is available AND we're running inside
# an authenticated Claude Code session (signalled by the OAuth FD env var).
# Set MEDIAHUB_DISABLE_CLAUDE_CLI=1 to force-disable (e.g. for tests).
def _has_claude_cli() -> bool:
    if os.environ.get("MEDIAHUB_DISABLE_CLAUDE_CLI", "").lower() in ("1", "true", "yes"):
        return False
    # Need either OAuth context or an API key reachable by `claude`.
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR") and not _has_anthropic_key():
        return False
    # Verify the binary exists. Cache the result on the module.
    global _claude_cli_path
    try:
        return bool(_claude_cli_path)
    except NameError:
        pass
    import shutil
    _claude_cli_path = shutil.which("claude") or ""
    return bool(_claude_cli_path)


def is_available() -> bool:
    """True if a real LLM is reachable. Tests + UI use this for badges."""
    return (_has_pplx_bridge() or _has_anthropic_key()
            or _has_gemini_key() or _has_claude_cli())


def active_provider() -> str:
    """Return a short, user-friendly name of the active LLM provider.

    Priority: pplx-bridge → Anthropic API → Gemini API → Claude CLI → heuristic.
    Anthropic is preferred for users who paid for it; Gemini is the recommended
    free option (free tier from https://aistudio.google.com).
    """
    if _has_pplx_bridge():
        return "pplx-bridge"
    if _has_anthropic_key():
        return "anthropic-api"
    if _has_gemini_key():
        return "gemini-api"
    if _has_claude_cli():
        return "claude-cli"
    return "heuristic"


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


# ---------------------------------------------------------------------------
# Provider 3: Google Gemini (free tier from https://aistudio.google.com)
# ---------------------------------------------------------------------------
# Uses Google's REST API directly so we don't need to add a new Python SDK.
# `requests` is already a project dependency. Free tier is generous:
#   gemini-2.0-flash: 15 RPM, 1,500 RPD, 1M tokens/min, no credit card needed.
_GEMINI_MODEL = os.environ.get("MEDIAHUB_GEMINI_MODEL", "gemini-2.0-flash")
_GEMINI_TIMEOUT = int(os.environ.get("MEDIAHUB_GEMINI_TIMEOUT", "45"))


def _call_gemini(messages: list[dict], system: Optional[str], max_tokens: int) -> Optional[str]:
    """Call Google Gemini generateContent endpoint. Returns text or None.

    See: https://ai.google.dev/api/generate-content
    """
    key = _resolve_gemini_key()
    if not key:
        return None
    try:
        import requests  # already a project dependency
    except Exception as e:
        log.debug("gemini: requests import failed: %s", e)
        return None
    # Convert OpenAI/Anthropic-style messages → Gemini contents.
    contents = []
    for m in (messages or []):
        role = m.get("role")
        text = str(m.get("content", "") or "")
        if not text:
            continue
        # Gemini uses "user" / "model". Map "assistant" → "model".
        g_role = "model" if role == "assistant" else "user"
        contents.append({"role": g_role, "parts": [{"text": text}]})
    if not contents:
        return None
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": int(max_tokens),
            "temperature": 0.7,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent"
    )
    try:
        r = requests.post(
            url,
            params={"key": key},
            json=payload,
            timeout=_GEMINI_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        log.warning("gemini http error: %s", e)
        _record_provider_error("gemini-api", "http_error", str(e))
        return None
    if r.status_code != 200:
        log.warning("gemini non-200 (%s): %s", r.status_code, r.text[:200])
        # Status 400 with "API_KEY_INVALID" is the single most useful signal.
        reason = f"http_{r.status_code}"
        if r.status_code in (401, 403):
            reason = "auth_failed"
        elif r.status_code == 429:
            reason = "rate_limited"
        _record_provider_error("gemini-api", reason, r.text[:500])
        return None
    try:
        data = r.json()
    except Exception as e:
        _record_provider_error("gemini-api", "bad_json", str(e))
        return None
    # Walk: candidates[0].content.parts[*].text
    candidates = data.get("candidates") or []
    if not candidates:
        log.warning("gemini empty candidates: %s", str(data)[:200])
        _record_provider_error("gemini-api", "empty_candidates", str(data)[:500])
        return None
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    return text or None


# ---------------------------------------------------------------------------
# Provider 4: claude CLI (Claude Code, OAuth-authenticated, dev only)
# ---------------------------------------------------------------------------
# Used when no Anthropic API key is configured but the host machine is running
# inside an authenticated `claude` CLI session. Cheap-ish (defaults to Haiku)
# and ALWAYS one-shot (--allowedTools "" disables tool use).
#
# We pass --setting-sources "" and --settings (empty JSON) so user / project
# / local settings (hooks, CLAUDE.md auto-discovery) DO NOT influence the
# sub-process — otherwise we get hook noise mixed into the assistant reply.
_CLAUDE_CLI_MODEL = os.environ.get("MEDIAHUB_CLAUDE_CLI_MODEL", "haiku")
_CLAUDE_CLI_TIMEOUT = int(os.environ.get("MEDIAHUB_CLAUDE_CLI_TIMEOUT", "90"))


def _empty_settings_file() -> str:
    """Write (once) an empty settings JSON file in /tmp and return its path."""
    global _empty_settings_path
    try:
        return _empty_settings_path  # type: ignore[name-defined]
    except NameError:
        pass
    import tempfile
    fd, path = tempfile.mkstemp(prefix="mh-claude-settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("{}")
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
    _empty_settings_path = path  # type: ignore[assignment]
    return path


def _call_claude_cli(messages: list[dict], system: Optional[str], max_tokens: int) -> Optional[str]:
    """Invoke `claude -p` non-interactively and return the assistant text.

    Returns None on any failure so callers fall through to other providers
    or the heuristic.
    """
    if not _has_claude_cli():
        return None
    # Build a single user prompt by concatenating message contents. The CLI
    # doesn't expose a chat-array argument in --print mode.
    user_prompt = "\n\n".join(
        str(m.get("content", "")) for m in (messages or []) if m.get("role") == "user"
    ).strip()
    if not user_prompt:
        return None

    cmd = [
        _claude_cli_path or "claude",
        "-p", user_prompt,
        "--output-format", "json",
        "--model", _CLAUDE_CLI_MODEL,
        # Ignore user/project/local settings (hooks, CLAUDE.md) — we want
        # a pure one-shot LLM call, not an agent acting on this project.
        "--setting-sources", "",
        "--settings", _empty_settings_file(),
        # Disable every tool — one-shot text generation only.
        "--allowedTools", "",
        "--disallowedTools",
        "Bash Edit Write Read Agent NotebookEdit WebFetch WebSearch TodoWrite Skill",
        "--disable-slash-commands",
    ]
    if system:
        cmd += ["--append-system-prompt", system]
    try:
        # Run from /tmp so CLAUDE.md auto-discovery (already disabled) can't
        # accidentally find this project. Belt-and-braces.
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_CLAUDE_CLI_TIMEOUT,
            check=False, cwd="/tmp",
        )
        if r.returncode != 0:
            log.debug("claude CLI non-zero (%s): %s", r.returncode, (r.stderr or "")[:200])
            return None
        out = (r.stdout or "").strip()
        if not out:
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return out  # raw text fallback
        if isinstance(data, dict):
            if data.get("is_error"):
                log.debug("claude CLI is_error: %s", str(data.get("result", ""))[:200])
                return None
            result = data.get("result")
            if isinstance(result, str) and result.strip():
                return result.strip()
        return None
    except subprocess.TimeoutExpired:
        log.debug("claude CLI timed out after %ss", _CLAUDE_CLI_TIMEOUT)
        return None
    except Exception as e:
        log.debug("claude CLI error: %s", e)
        return None


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
            log.warning("anthropic call failed (%s): %s", attempt_model, e)
            _record_provider_error("anthropic-api", f"call_failed_{attempt_model}", str(e))
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

    # Provider order: pplx bridge → Anthropic SDK → Gemini → claude CLI.
    # When none of those reach a real LLM, raise — there is no hardcoded
    # heuristic fallback anywhere in MediaHub by design. Callers should
    # surface the failure to the user with a "configure an AI provider"
    # message instead of pretending fake output is a real answer.
    out = _call_pplx_bridge(msgs, system, max_tokens)
    if out:
        return out
    out = _call_anthropic(msgs, system, max_tokens)
    if out:
        return out
    out = _call_gemini(msgs, system, max_tokens)
    if out:
        return out
    out = _call_claude_cli(msgs, system, max_tokens)
    if out:
        return out
    raise ClaudeUnavailableError(
        "No AI provider could answer this request. Configure a Claude, "
        "OpenAI, or Gemini key on /settings — there is no hardcoded "
        "fallback output in MediaHub by design."
    )


def generate_json(prompt: str, *, system: Optional[str] = None, max_tokens: int = 1024,
                  fallback: Optional[dict] = None) -> dict:
    """Generate a JSON dict.

    Raises ``ClaudeUnavailableError`` when no AI provider can answer —
    callers must catch and surface to the user. The ``fallback`` arg is
    used ONLY when the provider DID answer but produced unparseable
    output (rare); it is no longer used to mask "no provider configured"
    (the user explicitly wants that surfaced honestly).
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

    Provider order: Anthropic (paid, Claude vision) → Gemini (free, Flash
    multimodal) → heuristic. Returns the model's text. Always returns a
    string; never raises.
    """
    # Provider 1: Anthropic
    if _has_anthropic_key():
        out = _call_anthropic_vision(image_paths, prompt, system, max_tokens)
        if out:
            return out
    # Provider 2: Gemini (free)
    if _has_gemini_key():
        out = _call_gemini_vision(image_paths, prompt, system, max_tokens)
        if out:
            return out
    raise ClaudeUnavailableError(
        "No AI provider with vision support could answer this request. "
        "Configure a Claude or Gemini key on /settings — there is no "
        "hardcoded fallback in MediaHub by design."
    )


def _read_image_for_vision(path: str) -> tuple[Optional[str], Optional[str]]:
    """Return (base64_data, mime_type) for an image path, or (None, None)."""
    import base64
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        log.debug("vision image read failed: %s", e)
        return (None, None)
    lower = path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        mt = "image/jpeg"
    elif lower.endswith(".webp"):
        mt = "image/webp"
    elif lower.endswith(".gif"):
        mt = "image/gif"
    else:
        mt = "image/png"
    return (data, mt)


def _call_anthropic_vision(image_paths: list[str], prompt: str,
                           system: Optional[str], max_tokens: int) -> Optional[str]:
    client = _get_anthropic()
    if not client:
        return None
    content_blocks: list[dict] = []
    for p in image_paths[:5]:  # cap to 5
        data, mt = _read_image_for_vision(p)
        if data is None:
            continue
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": data},
        })
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
        return "".join(parts).strip() or None
    except Exception as e:
        log.debug("anthropic vision failed: %s", e)
        return None


def _call_gemini_vision(image_paths: list[str], prompt: str,
                        system: Optional[str], max_tokens: int) -> Optional[str]:
    """Gemini multimodal generateContent — same REST endpoint, inline_data parts."""
    key = _resolve_gemini_key()
    if not key:
        return None
    try:
        import requests
    except Exception:
        return None
    parts: list[dict] = []
    for p in image_paths[:5]:
        data, mt = _read_image_for_vision(p)
        if data is None:
            continue
        parts.append({"inline_data": {"mime_type": mt, "data": data}})
    parts.append({"text": prompt})
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": int(max_tokens), "temperature": 0.7},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent"
    )
    try:
        r = requests.post(url, params={"key": key}, json=payload,
                          timeout=_GEMINI_TIMEOUT,
                          headers={"Content-Type": "application/json"})
    except Exception as e:
        log.debug("gemini vision http error: %s", e)
        return None
    if r.status_code != 200:
        log.debug("gemini vision non-200 (%s): %s", r.status_code, r.text[:200])
        return None
    try:
        data = r.json()
    except Exception:
        return None
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    cparts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in cparts if isinstance(p, dict)).strip()
    return text or None


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


# The heuristic / template fallbacks (_heuristic_response,
# _heuristic_caption, _heuristic_alt) were deleted in the
# Claude-driven-core refactor. By product direction MediaHub has no
# hardcoded substitute output anywhere — every reasoning call goes to a
# configured AI provider, and unavailable providers surface to the user
# as an actionable error ("configure an AI key in /settings") rather
# than silently producing fake captions/alt-text.


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
    # Heuristic JSON sentinel — never a real caption.
    if result.strip() in ("{}", "{}\n", "[]", "{\n}"):
        raise ClaudeUnavailableError("LLM returned heuristic JSON-empty sentinel")
    return result


__all__ = ["generate", "generate_json", "generate_vision", "is_available",
           "active_provider", "call_claude", "ClaudeUnavailableError",
           "last_provider_errors"]
