"""video/eye_contact.py — opt-in eye-contact (gaze) correction seam (1.6).

Eye-contact correction (NVIDIA Broadcast, Descript) **warps the existing eye
pixels** so a speaker reading off-camera appears to look at the lens. Crucially
this is a **pixel edit, not synthesis** — it does NOT fabricate a new person, it
redirects the gaze of the real footage via a learned warp field. So it sits a
notch below the generative seams: provenance records ``synthetic=False``.

It is still gated and opt-in, because silently changing where someone appears to
look is a meaningful alteration of a real recording. Providers reuse already-
declared keys: ``server`` is an in-process model (no key), ``replicate`` is the
cloud adapter on the existing Replicate token. Honest-error without a backend; a
human approves before export.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_SERVER = "server"
_REPLICATE = "replicate"
_VALID = frozenset({_SERVER, _REPLICATE})
_ALIASES = {"server": _SERVER, "local": _SERVER, "nvidia": _SERVER, "replicate": _REPLICATE}

DEFAULT_DISCLOSURE = "eye-contact corrected"


class EyeContactUnavailable(RuntimeError):
    """Raised when gaze correction is not configured/available (honest)."""


class EyeContactConsentRequired(RuntimeError):
    """Raised when gaze correction is attempted without explicit opt-in."""


@dataclass(frozen=True)
class EyeContactRequest:
    """A fully-specified gaze-correction request (a pixel edit, not synthesis)."""

    provider: str
    explicit_opt_in: bool
    disclosure: str = DEFAULT_DISCLOSURE

    def provenance(self) -> dict:
        return {
            # A warp of existing eye pixels — NOT a fabricated person.
            "synthetic": False,
            "kind": "eye_contact_correction",
            "provider": self.provider,
            "disclosure": self.disclosure or DEFAULT_DISCLOSURE,
            "explicit_opt_in": True,
        }


def select_provider() -> str:
    raw = os.environ.get("MEDIAHUB_EYE_CONTACT_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _ALIASES.get(raw, raw)
    if canon not in _VALID:
        raise EyeContactUnavailable(
            f"MEDIAHUB_EYE_CONTACT_PROVIDER={raw!r} is not recognised. "
            f"Valid: {sorted(_VALID)} (or unset to keep gaze correction off)."
        )
    return canon


def _provider_available(provider: str) -> bool:
    if provider == _SERVER:
        import importlib.util

        try:
            return importlib.util.find_spec("eye_contact") is not None
        except Exception:
            return False
    if provider == _REPLICATE:
        return bool(os.environ.get("REPLICATE_API_TOKEN", "").strip())
    return False


def is_available() -> bool:
    try:
        provider = select_provider()
    except EyeContactUnavailable:
        return False
    return bool(provider) and _provider_available(provider)


def status() -> dict:
    configured = os.environ.get("MEDIAHUB_EYE_CONTACT_PROVIDER", "").strip()
    try:
        active = select_provider()
    except EyeContactUnavailable:
        active = configured.lower()
    return {
        "configured": configured,
        "active": active,
        "available": is_available(),
        "requires_explicit_opt_in": True,
        "edits_not_synthesises": True,
    }


def build_request(*, explicit_opt_in: bool, disclosure: str = "") -> EyeContactRequest:
    if not explicit_opt_in:
        raise EyeContactConsentRequired(
            "Gaze correction alters where a real person appears to look; it is only "
            "applied on an explicit, per-request opt-in."
        )
    provider = select_provider()
    if not provider or not _provider_available(provider):
        raise EyeContactUnavailable(
            "Eye-contact correction isn't enabled on this deployment. Configure "
            "MEDIAHUB_EYE_CONTACT_PROVIDER (server/replicate) and its dependency/key."
        )
    return EyeContactRequest(
        provider=provider,
        explicit_opt_in=True,
        disclosure=(disclosure or "").strip() or DEFAULT_DISCLOSURE,
    )


def correct_gaze(req: EyeContactRequest, source, out_path) -> "tuple":
    """Redirect the speaker's gaze to camera (adapter; honest-error here)."""
    if not req.explicit_opt_in:
        raise EyeContactConsentRequired("gaze correction requires explicit opt-in")
    raise EyeContactUnavailable(
        f"The {req.provider!r} eye-contact adapter is configured but its integration "
        "is not enabled in this build."
    )


__all__ = [
    "EyeContactUnavailable",
    "EyeContactConsentRequired",
    "EyeContactRequest",
    "DEFAULT_DISCLOSURE",
    "select_provider",
    "is_available",
    "status",
    "build_request",
    "correct_gaze",
]
