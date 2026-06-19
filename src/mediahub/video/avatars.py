"""video/avatars.py — opt-in, disclosed AI avatars behind a provider seam (1.6).

MediaHub's standing rule is **no synthetic AI-generated people unless explicitly
requested** (CLAUDE.md). Canva/Adobe ship talking-avatar generators; rather than
embed D-ID/HeyGen as apps, MediaHub exposes its *own* avatar surface with that
rule enforced in code:

* **Off by default.** ``MEDIAHUB_AVATAR_PROVIDER`` unset ⇒ :func:`is_available`
  is ``False`` and synthesis honest-errors.
* **Explicit opt-in per call.** Even with a provider configured, synthesis
  refuses unless the caller passes ``explicit_opt_in=True`` — env configuration
  alone is never treated as a request to fabricate a person.
* **Mandatory in-frame disclosure.** Every synthesized clip carries an
  ``"AI-generated"`` disclosure (a default is forced when the caller omits one),
  and the provenance is recorded for the 1.23 manifest. There is no path to an
  *undisclosed* synthetic person.
* **Provider behind a flag.** ``did`` / ``heygen`` are optional cloud video-model
  adapters on our seam (the unavoidable model-hosting hop), each honest-erroring
  without its key — not embedded third-party apps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DID = "did"
_HEYGEN = "heygen"
_VALID = frozenset({_DID, _HEYGEN})
_ALIASES = {"did": _DID, "d-id": _DID, "heygen": _HEYGEN}

DEFAULT_DISCLOSURE = "AI-generated"


class AvatarsUnavailable(RuntimeError):
    """Raised when avatar synthesis is not configured/available (honest)."""


class AvatarConsentRequired(RuntimeError):
    """Raised when avatar synthesis is attempted without explicit opt-in.

    The no-synthetic-people rule, enforced in code: a synthetic person is only
    ever made on a deliberate, per-request ``explicit_opt_in=True``.
    """


@dataclass(frozen=True)
class AvatarRequest:
    """A fully-specified, disclosed avatar synthesis request."""

    script: str
    provider: str
    explicit_opt_in: bool
    disclosure: str = DEFAULT_DISCLOSURE
    voice: str = ""
    presenter: str = ""

    def provenance(self) -> dict:
        """The provenance record stamped onto the output (feeds 1.23 manifests)."""
        return {
            "synthetic": True,
            "kind": "ai_avatar",
            "provider": self.provider,
            "disclosure": self.disclosure or DEFAULT_DISCLOSURE,
            "explicit_opt_in": True,
        }


def select_avatar_provider() -> str:
    """Canonical provider name, or ``""`` when the surface is off (the default)."""
    raw = os.environ.get("MEDIAHUB_AVATAR_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _ALIASES.get(raw, raw)
    if canon not in _VALID:
        raise AvatarsUnavailable(
            f"MEDIAHUB_AVATAR_PROVIDER={raw!r} is not recognised. "
            f"Valid: {sorted(_VALID)} (or unset to keep avatars off)."
        )
    return canon


def _provider_available(provider: str) -> bool:
    if provider == _DID:
        return bool(os.environ.get("DID_API_KEY", "").strip())
    if provider == _HEYGEN:
        return bool(os.environ.get("HEYGEN_API_KEY", "").strip())
    return False


def is_available() -> bool:
    """True only when a provider is configured *and* its key is present.

    Note: this is capability, not permission — synthesis still requires an
    explicit per-call opt-in (:func:`build_request`).
    """
    try:
        provider = select_avatar_provider()
    except AvatarsUnavailable:
        return False
    return bool(provider) and _provider_available(provider)


def avatar_status() -> dict:
    """Diagnostics for the health surface; never enables anything by itself."""
    configured = os.environ.get("MEDIAHUB_AVATAR_PROVIDER", "").strip()
    try:
        active = select_avatar_provider()
    except AvatarsUnavailable:
        active = configured.lower()
    return {
        "configured": configured,
        "active": active,
        "available": is_available(),
        "requires_explicit_opt_in": True,
        "disclosure_enforced": True,
    }


def build_request(
    script: str,
    *,
    explicit_opt_in: bool,
    disclosure: str = "",
    voice: str = "",
    presenter: str = "",
) -> AvatarRequest:
    """Validate + assemble a disclosed avatar request (the policy gate).

    Raises :class:`AvatarConsentRequired` unless ``explicit_opt_in`` is ``True``,
    and :class:`AvatarsUnavailable` when no provider/key is configured. The
    disclosure is forced to a non-empty default so an undisclosed synthetic
    person is unrepresentable.
    """
    if not explicit_opt_in:
        raise AvatarConsentRequired(
            "AI avatars are synthetic people and are only generated on an "
            "explicit, per-request opt-in (MediaHub's no-synthetic-people rule)."
        )
    provider = select_avatar_provider()
    if not provider or not _provider_available(provider):
        raise AvatarsUnavailable(
            "AI avatars aren't enabled on this deployment. Configure "
            "MEDIAHUB_AVATAR_PROVIDER (did/heygen) and its API key."
        )
    return AvatarRequest(
        script=(script or "").strip(),
        provider=provider,
        explicit_opt_in=True,
        disclosure=(disclosure or "").strip() or DEFAULT_DISCLOSURE,
        voice=voice,
        presenter=presenter,
    )


def synthesize_avatar(req: AvatarRequest, out_path) -> "tuple":
    """Synthesize a disclosed avatar clip (cloud adapter; honest-error here).

    Returns ``(path, provenance)`` on success. The network integration sits
    behind the provider's key and is not enabled in this build, so this raises
    :class:`AvatarsUnavailable` — never a fabricated, undisclosed person.
    """
    if not req.explicit_opt_in:
        raise AvatarConsentRequired("avatar synthesis requires explicit opt-in")
    raise AvatarsUnavailable(
        f"The {req.provider!r} avatar adapter is configured but its network "
        "integration is not enabled in this build. The disclosure that would be "
        f"burned in: {req.disclosure!r}."
    )


__all__ = [
    "AvatarsUnavailable",
    "AvatarConsentRequired",
    "AvatarRequest",
    "DEFAULT_DISCLOSURE",
    "select_avatar_provider",
    "is_available",
    "avatar_status",
    "build_request",
    "synthesize_avatar",
]
