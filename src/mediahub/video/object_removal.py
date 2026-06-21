"""video/object_removal.py — opt-in, disclosed object removal / inpainting (1.6).

"Brush out the lamppost / the photobomber" — video inpainting (Runway Aleph,
ProPainter, Resolve Object Removal) removes a masked region and **fills the hole
with newly-synthesised pixels**. That is **generative synthesis**, so it is gated
like ``broll`` / ``avatars``: off by default, explicit per-call opt-in, a forced
``"AI-edited"`` disclosure + provenance, and honest-error without a backend.

Providers reuse keys MediaHub already declares (no new sub-processor surface):
``server`` is in-process ProPainter (flow-guided, mostly copies real pixels from
other frames — the conservative fill), ``replicate`` / ``runway`` are cloud
adapters on the matting/b-roll keys. A human approves before export.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_SERVER = "server"
_REPLICATE = "replicate"
_RUNWAY = "runway"
_VALID = frozenset({_SERVER, _REPLICATE, _RUNWAY})
_ALIASES = {
    "server": _SERVER,
    "propainter": _SERVER,
    "local": _SERVER,
    "replicate": _REPLICATE,
    "runway": _RUNWAY,
    "aleph": _RUNWAY,
}

DEFAULT_DISCLOSURE = "AI-edited"


class ObjectRemovalUnavailable(RuntimeError):
    """Raised when object removal is not configured/available (honest)."""


class ObjectRemovalConsentRequired(RuntimeError):
    """Raised when object removal is attempted without explicit opt-in."""


@dataclass(frozen=True)
class ObjectRemovalRequest:
    """A fully-specified, disclosed object-removal request."""

    provider: str
    explicit_opt_in: bool
    disclosure: str = DEFAULT_DISCLOSURE

    def provenance(self) -> dict:
        return {
            "synthetic": True,
            "kind": "ai_object_removal",
            "provider": self.provider,
            "disclosure": self.disclosure or DEFAULT_DISCLOSURE,
            "explicit_opt_in": True,
        }


def select_provider() -> str:
    raw = os.environ.get("MEDIAHUB_OBJECT_REMOVAL_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _ALIASES.get(raw, raw)
    if canon not in _VALID:
        raise ObjectRemovalUnavailable(
            f"MEDIAHUB_OBJECT_REMOVAL_PROVIDER={raw!r} is not recognised. "
            f"Valid: {sorted(_VALID)} (or unset to keep object removal off)."
        )
    return canon


def _provider_available(provider: str) -> bool:
    if provider == _SERVER:
        import importlib.util

        try:
            return importlib.util.find_spec("propainter") is not None
        except Exception:
            return False
    if provider == _REPLICATE:
        return bool(os.environ.get("REPLICATE_API_TOKEN", "").strip())
    if provider == _RUNWAY:
        return bool(os.environ.get("RUNWAY_API_KEY", "").strip())
    return False


def is_available() -> bool:
    try:
        provider = select_provider()
    except ObjectRemovalUnavailable:
        return False
    return bool(provider) and _provider_available(provider)


def status() -> dict:
    configured = os.environ.get("MEDIAHUB_OBJECT_REMOVAL_PROVIDER", "").strip()
    try:
        active = select_provider()
    except ObjectRemovalUnavailable:
        active = configured.lower()
    return {
        "configured": configured,
        "active": active,
        "available": is_available(),
        "requires_explicit_opt_in": True,
        "disclosure_enforced": True,
    }


def build_request(*, explicit_opt_in: bool, disclosure: str = "") -> ObjectRemovalRequest:
    if not explicit_opt_in:
        raise ObjectRemovalConsentRequired(
            "Object removal synthesises pixels to fill the erased region; it is only "
            "done on an explicit, per-request opt-in."
        )
    provider = select_provider()
    if not provider or not _provider_available(provider):
        raise ObjectRemovalUnavailable(
            "Object removal isn't enabled on this deployment. Configure "
            "MEDIAHUB_OBJECT_REMOVAL_PROVIDER (server/replicate/runway) and its dependency/key."
        )
    return ObjectRemovalRequest(
        provider=provider,
        explicit_opt_in=True,
        disclosure=(disclosure or "").strip() or DEFAULT_DISCLOSURE,
    )


def remove_object(req: ObjectRemovalRequest, source, mask, out_path) -> "tuple":
    """Inpaint ``source`` over ``mask`` (cloud/server adapter; honest-error here)."""
    if not req.explicit_opt_in:
        raise ObjectRemovalConsentRequired("object removal requires explicit opt-in")
    raise ObjectRemovalUnavailable(
        f"The {req.provider!r} object-removal adapter is configured but its integration "
        f"is not enabled in this build. Disclosure that would be burned: {req.disclosure!r}."
    )


__all__ = [
    "ObjectRemovalUnavailable",
    "ObjectRemovalConsentRequired",
    "ObjectRemovalRequest",
    "DEFAULT_DISCLOSURE",
    "select_provider",
    "is_available",
    "status",
    "build_request",
    "remove_object",
]
