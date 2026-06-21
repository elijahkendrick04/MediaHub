"""video/broll.py — opt-in, disclosed generative b-roll behind a provider seam (1.6).

Modern editors (Descript, Opus Clip, InVideo, Captions) offer **generative
b-roll**: a text-to-video model invents a brand-new clip to cut away to. That is
**generative synthesis** — it manufactures pixels that were never filmed — so by
MediaHub's rules it is *not* shipped as a default capability. It lives behind a
provider seam with the same guard rails as ``avatars`` and ``matting``:

* **Off by default.** ``MEDIAHUB_BROLL_PROVIDER`` unset ⇒ :func:`is_available`
  is ``False`` and synthesis honest-errors.
* **Explicit opt-in per call.** Even with a provider configured, synthesis
  refuses unless the caller passes ``explicit_opt_in=True`` — env configuration
  alone is never a request to fabricate footage.
* **Mandatory disclosure.** Every generated clip carries an ``"AI-generated"``
  disclosure (forced when omitted) and records its provenance for the 1.23
  manifest. There is no path to *undisclosed* synthetic footage.
* **Providers behind a key.** ``veo`` / ``runway`` / ``pika`` / ``luma`` /
  ``kling`` are optional cloud video-model adapters on our seam (the unavoidable
  model-hosting hop), each honest-erroring without its key — not embedded apps.

A human still approves before export, like everything else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_VEO = "veo"
_RUNWAY = "runway"
_PIKA = "pika"
_LUMA = "luma"
_KLING = "kling"
_VALID = frozenset({_VEO, _RUNWAY, _PIKA, _LUMA, _KLING})
_ALIASES = {
    "veo": _VEO,
    "google": _VEO,
    "gemini": _VEO,
    "runway": _RUNWAY,
    "runwayml": _RUNWAY,
    "pika": _PIKA,
    "luma": _LUMA,
    "dream-machine": _LUMA,
    "kling": _KLING,
    "kuaishou": _KLING,
}

# Provider → the env key that unlocks it.
_PROVIDER_KEYS = {
    _VEO: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    _RUNWAY: ("RUNWAY_API_KEY", "RUNWAYML_API_SECRET"),
    _PIKA: ("PIKA_API_KEY",),
    _LUMA: ("LUMA_API_KEY", "LUMAAI_API_KEY"),
    _KLING: ("KLING_API_KEY", "KLING_ACCESS_KEY"),
}

DEFAULT_DISCLOSURE = "AI-generated"
MAX_BROLL_SECONDS = 10  # the generative models cap short; keep b-roll a cutaway


class BrollUnavailable(RuntimeError):
    """Raised when generative b-roll is not configured/available (honest)."""


class BrollConsentRequired(RuntimeError):
    """Raised when b-roll synthesis is attempted without explicit opt-in.

    The no-fabricated-footage default, enforced in code: a synthetic clip is only
    ever made on a deliberate, per-request ``explicit_opt_in=True``.
    """


@dataclass(frozen=True)
class BrollRequest:
    """A fully-specified, disclosed generative-b-roll request."""

    prompt: str
    provider: str
    explicit_opt_in: bool
    seconds: float = 5.0
    aspect: str = "9:16"
    disclosure: str = DEFAULT_DISCLOSURE

    def provenance(self) -> dict:
        """The provenance record stamped onto the output (feeds 1.23 manifests)."""
        return {
            "synthetic": True,
            "kind": "ai_broll",
            "provider": self.provider,
            "prompt": self.prompt,
            "disclosure": self.disclosure or DEFAULT_DISCLOSURE,
            "explicit_opt_in": True,
        }


def select_broll_provider() -> str:
    """Canonical provider name, or ``""`` when the seam is off (the default)."""
    raw = os.environ.get("MEDIAHUB_BROLL_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _ALIASES.get(raw, raw)
    if canon not in _VALID:
        raise BrollUnavailable(
            f"MEDIAHUB_BROLL_PROVIDER={raw!r} is not recognised. "
            f"Valid: {sorted(_VALID)} (or unset to keep generative b-roll off)."
        )
    return canon


def _provider_available(provider: str) -> bool:
    keys = _PROVIDER_KEYS.get(provider, ())
    return any(os.environ.get(k, "").strip() for k in keys)


def is_available() -> bool:
    """True only when a provider is configured *and* its key is present.

    Capability, not permission — synthesis still requires an explicit per-call
    opt-in (:func:`build_request`).
    """
    try:
        provider = select_broll_provider()
    except BrollUnavailable:
        return False
    return bool(provider) and _provider_available(provider)


def broll_status() -> dict:
    """Diagnostics for the health surface; never enables anything by itself."""
    configured = os.environ.get("MEDIAHUB_BROLL_PROVIDER", "").strip()
    try:
        active = select_broll_provider()
    except BrollUnavailable:
        active = configured.lower()
    return {
        "configured": configured,
        "active": active,
        "available": is_available(),
        "requires_explicit_opt_in": True,
        "disclosure_enforced": True,
        "max_seconds": MAX_BROLL_SECONDS,
    }


def build_request(
    prompt: str,
    *,
    explicit_opt_in: bool,
    seconds: float = 5.0,
    aspect: str = "9:16",
    disclosure: str = "",
) -> BrollRequest:
    """Validate + assemble a disclosed b-roll request (the policy gate).

    Raises :class:`BrollConsentRequired` unless ``explicit_opt_in`` is ``True``,
    and :class:`BrollUnavailable` when no provider/key is configured. The
    disclosure is forced to a non-empty default so undisclosed synthetic footage
    is unrepresentable.
    """
    if not explicit_opt_in:
        raise BrollConsentRequired(
            "Generative b-roll synthesises footage that was never filmed and is "
            "only created on an explicit, per-request opt-in (MediaHub's "
            "no-fabricated-footage rule)."
        )
    if not (prompt or "").strip():
        raise BrollUnavailable("a b-roll prompt is required")
    provider = select_broll_provider()
    if not provider or not _provider_available(provider):
        raise BrollUnavailable(
            "Generative b-roll isn't enabled on this deployment. Configure "
            "MEDIAHUB_BROLL_PROVIDER (veo/runway/pika/luma/kling) and its API key."
        )
    return BrollRequest(
        prompt=prompt.strip(),
        provider=provider,
        explicit_opt_in=True,
        seconds=max(1.0, min(float(MAX_BROLL_SECONDS), float(seconds))),
        aspect=(aspect or "9:16").strip(),
        disclosure=(disclosure or "").strip() or DEFAULT_DISCLOSURE,
    )


def generate_broll(req: BrollRequest, out_path) -> "tuple":
    """Synthesize a disclosed b-roll clip (cloud adapter; honest-error here).

    Returns ``(path, provenance)`` on success. The network integration sits
    behind the provider's key and is not enabled in this build, so this raises
    :class:`BrollUnavailable` — never a fabricated, undisclosed clip.
    """
    if not req.explicit_opt_in:
        raise BrollConsentRequired("b-roll synthesis requires explicit opt-in")
    raise BrollUnavailable(
        f"The {req.provider!r} b-roll adapter is configured but its network "
        "integration is not enabled in this build. The disclosure that would be "
        f"burned in: {req.disclosure!r}."
    )


__all__ = [
    "BrollUnavailable",
    "BrollConsentRequired",
    "BrollRequest",
    "DEFAULT_DISCLOSURE",
    "MAX_BROLL_SECONDS",
    "select_broll_provider",
    "is_available",
    "broll_status",
    "build_request",
    "generate_broll",
]
