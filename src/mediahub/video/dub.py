"""video/dub.py — opt-in, disclosed lip-sync / dubbing behind a provider seam (1.6).

Translate-and-dub with **lip-sync** (HeyGen Translate, sync.so, Rask, ElevenLabs
Dubbing) re-renders the on-screen mouth to match new speech and synthesises a new
(often voice-cloned) audio track. That is **generative synthesis** — it
manufactures pixels and audio of a real person saying words they did not say — so
by MediaHub's rules it is gated exactly like ``avatars`` / ``broll``:

* **Off by default** (``MEDIAHUB_DUB_PROVIDER`` unset ⇒ honest-error).
* **Explicit opt-in per call** — env config alone never authorises re-voicing a
  person.
* **Mandatory disclosure** — every dubbed clip carries an ``"AI-dubbed"``
  disclosure and records provenance (incl. the target language + whether the
  voice was cloned) for the 1.23 manifest. There is no undisclosed path.
* **Providers behind a key**, each honest-erroring without it.

A human approves before export, like everything else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_SYNC = "sync"
_ELEVENLABS = "elevenlabs"
_RASK = "rask"
_HEYGEN = "heygen"
_VALID = frozenset({_SYNC, _ELEVENLABS, _RASK, _HEYGEN})
_ALIASES = {
    "sync": _SYNC,
    "sync.so": _SYNC,
    "syncso": _SYNC,
    "elevenlabs": _ELEVENLABS,
    "11labs": _ELEVENLABS,
    "rask": _RASK,
    "heygen": _HEYGEN,
}
_PROVIDER_KEYS = {
    _SYNC: ("SYNC_API_KEY",),
    _ELEVENLABS: ("ELEVENLABS_API_KEY",),
    _RASK: ("RASK_API_KEY",),
    _HEYGEN: ("HEYGEN_API_KEY",),
}

DEFAULT_DISCLOSURE = "AI-dubbed"


class DubUnavailable(RuntimeError):
    """Raised when dubbing is not configured/available (honest)."""


class DubConsentRequired(RuntimeError):
    """Raised when dubbing is attempted without explicit opt-in."""


@dataclass(frozen=True)
class DubRequest:
    """A fully-specified, disclosed lip-sync/dub request."""

    target_language: str
    provider: str
    explicit_opt_in: bool
    voice_clone: bool = False
    disclosure: str = DEFAULT_DISCLOSURE

    def provenance(self) -> dict:
        return {
            "synthetic": True,
            "kind": "ai_dub",
            "provider": self.provider,
            "target_language": self.target_language,
            "voice_cloned": bool(self.voice_clone),
            "disclosure": self.disclosure or DEFAULT_DISCLOSURE,
            "explicit_opt_in": True,
        }


def select_dub_provider() -> str:
    """Canonical provider name, or ``""`` when the seam is off (the default)."""
    raw = os.environ.get("MEDIAHUB_DUB_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _ALIASES.get(raw, raw)
    if canon not in _VALID:
        raise DubUnavailable(
            f"MEDIAHUB_DUB_PROVIDER={raw!r} is not recognised. "
            f"Valid: {sorted(_VALID)} (or unset to keep dubbing off)."
        )
    return canon


def _provider_available(provider: str) -> bool:
    return any(os.environ.get(k, "").strip() for k in _PROVIDER_KEYS.get(provider, ()))


def is_available() -> bool:
    try:
        provider = select_dub_provider()
    except DubUnavailable:
        return False
    return bool(provider) and _provider_available(provider)


def dub_status() -> dict:
    configured = os.environ.get("MEDIAHUB_DUB_PROVIDER", "").strip()
    try:
        active = select_dub_provider()
    except DubUnavailable:
        active = configured.lower()
    return {
        "configured": configured,
        "active": active,
        "available": is_available(),
        "requires_explicit_opt_in": True,
        "disclosure_enforced": True,
    }


def build_request(
    target_language: str,
    *,
    explicit_opt_in: bool,
    voice_clone: bool = False,
    disclosure: str = "",
) -> DubRequest:
    """Validate + assemble a disclosed dub request (the policy gate)."""
    if not explicit_opt_in:
        raise DubConsentRequired(
            "Lip-sync dubbing re-renders a real person's mouth and re-voices them; "
            "it is only done on an explicit, per-request opt-in."
        )
    if not (target_language or "").strip():
        raise DubUnavailable("a target language is required")
    provider = select_dub_provider()
    if not provider or not _provider_available(provider):
        raise DubUnavailable(
            "Dubbing isn't enabled on this deployment. Configure MEDIAHUB_DUB_PROVIDER "
            "(sync/elevenlabs/rask/heygen) and its API key."
        )
    return DubRequest(
        target_language=target_language.strip(),
        provider=provider,
        explicit_opt_in=True,
        voice_clone=bool(voice_clone),
        disclosure=(disclosure or "").strip() or DEFAULT_DISCLOSURE,
    )


def dub_clip(req: DubRequest, source, out_path) -> "tuple":
    """Dub ``source`` with lip-sync (cloud adapter; honest-error here).

    The network integration sits behind the provider's key and is not enabled in
    this build, so this raises :class:`DubUnavailable` — never a fabricated,
    undisclosed dub.
    """
    if not req.explicit_opt_in:
        raise DubConsentRequired("dubbing requires explicit opt-in")
    raise DubUnavailable(
        f"The {req.provider!r} dub adapter is configured but its network integration "
        f"is not enabled in this build. Disclosure that would be burned: {req.disclosure!r}."
    )


__all__ = [
    "DubUnavailable",
    "DubConsentRequired",
    "DubRequest",
    "DEFAULT_DISCLOSURE",
    "select_dub_provider",
    "is_available",
    "dub_status",
    "build_request",
    "dub_clip",
]
