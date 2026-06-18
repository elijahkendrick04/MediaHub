"""Image-AI provider interface (P6.3).

Every generative-image capability sits behind one provider contract, mirroring
the cutout-provider seam (``media_ai/providers/base.py``) and the LLM wrapper's
provider doctrine: a swappable backend that declares which operations it can do,
returns raw image bytes, and raises an honest error when it cannot — never a
fabricated or silently-substituted result.

A provider does **not** decide policy (quotas, provenance, where the bytes are
stored). It only turns an operation request into pixels. Orchestration —
quota checks, provenance stamping, media-library persistence — lives in
:mod:`mediahub.media_ai.imagine`.

Operations (the full P6.3 vocabulary):

  * ``generate``     — text → image (Magic Media / Dream Lab / Firefly).
  * ``similar``      — on-style variations of a reference image.
  * ``edit``         — prompt-driven add/replace inside a (masked) region.
  * ``expand``       — extend the canvas with generated fill (outpaint).
  * ``remove``       — erase masked objects, filling the hole (inpaint).
  * ``upscale``      — provider super-resolution / enhance.
  * ``style_match``  — re-style an image toward brand look/feel.

``subject_lift`` (Magic Grab) is deterministic — cutout + saliency, handled in
the facade, not here — so it is deliberately absent from this list.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Optional

# The full operation vocabulary the seam exposes. Providers advertise the
# subset they actually support via ``capabilities()``; the facade honest-errors
# (``ImagineUnsupported``) for anything a provider does not claim.
OPERATIONS = (
    "generate",
    "similar",
    "edit",
    "expand",
    "remove",
    "upscale",
    "style_match",
)


@dataclass
class ImageInput:
    """An input image for an editing operation.

    Carries the raw bytes plus the MIME type. ``mask`` (when present) is a PNG
    whose alpha/white region marks where an ``edit`` / ``remove`` should act.
    """

    data: bytes
    mime: str = "image/png"
    mask: Optional[bytes] = None


@dataclass
class GeneratedImage:
    """One image produced by a provider, before orchestration stamps it."""

    data: bytes
    mime: str = "image/png"
    seed: Optional[int] = None
    # Provider-native extras a later op may use (e.g. layer URLs). Never trusted
    # blindly by the facade — purely informational.
    extra: dict = field(default_factory=dict)


class ImagineProvider(ABC):
    """Base class for an image-AI backend.

    Concrete providers override only the operations they support and list them
    in :meth:`capabilities`. The default operation methods raise
    :class:`mediahub.media_ai.imagine.ImagineUnsupported` so an unimplemented op
    is an honest error, not a stub image.
    """

    name: str = "base"

    def is_available(self) -> bool:
        """True when this provider can plausibly run (key/endpoint present)."""
        return False

    def capabilities(self) -> set[str]:
        """The subset of :data:`OPERATIONS` this provider implements."""
        return set()

    def supports(self, operation: str) -> bool:
        return operation in self.capabilities()

    # -- operations (override the supported ones) ---------------------------
    # Signatures take orchestration-neutral primitives; the facade adapts
    # media-library assets / briefs into these before calling.

    def generate(
        self,
        prompt: str,
        *,
        style: Optional[str] = None,
        aspect: str = "1:1",
        n: int = 1,
        allow_people: bool = False,
        refs: Optional[list[ImageInput]] = None,
    ) -> list[GeneratedImage]:
        raise self._unsupported("generate")

    def similar(
        self,
        image: ImageInput,
        *,
        prompt: str = "",
        n: int = 1,
        allow_people: bool = False,
    ) -> list[GeneratedImage]:
        raise self._unsupported("similar")

    def edit(
        self,
        image: ImageInput,
        instruction: str,
        *,
        allow_people: bool = False,
    ) -> GeneratedImage:
        raise self._unsupported("edit")

    def expand(
        self,
        image: ImageInput,
        *,
        aspect: str,
        prompt: str = "",
    ) -> GeneratedImage:
        raise self._unsupported("expand")

    def remove(self, image: ImageInput) -> GeneratedImage:
        raise self._unsupported("remove")

    def upscale(self, image: ImageInput, *, factor: int = 2) -> GeneratedImage:
        raise self._unsupported("upscale")

    def style_match(
        self,
        image: ImageInput,
        *,
        style: str,
        palette: Optional[dict] = None,
    ) -> GeneratedImage:
        raise self._unsupported("style_match")

    def _unsupported(self, operation: str):
        # Imported lazily to avoid a circular import (imagine imports providers).
        from mediahub.media_ai.imagine import ImagineUnsupported

        return ImagineUnsupported(
            f"The configured image provider ({self.name!r}) does not support "
            f"the {operation!r} operation. Configure a provider that does "
            f"(e.g. the local diffusion backend, P5.6)."
        )


__all__ = [
    "OPERATIONS",
    "ImageInput",
    "GeneratedImage",
    "ImagineProvider",
]
