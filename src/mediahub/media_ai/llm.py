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
        log.debug("gemini http error: %s", e)
        return None
    if r.status_code != 200:
        log.debug("gemini non-200 (%s): %s", r.status_code, r.text[:200])
        return None
    try:
        data = r.json()
    except Exception:
        return None
    # Walk: candidates[0].content.parts[*].text
    candidates = data.get("candidates") or []
    if not candidates:
        log.debug("gemini empty candidates: %s", str(data)[:200])
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

    # Provider order: pplx bridge → Anthropic SDK → Gemini (free tier)
    # → claude CLI (Claude Code dev only) → heuristic.
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
           "active_provider", "call_claude", "ClaudeUnavailableError"]
