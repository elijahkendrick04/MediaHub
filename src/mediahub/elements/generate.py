"""elements.generate — the AI element-generation seam (roadmap 1.10, build 4).

Canva/Express have an "AI-Powered Elements" tab: generate a photo / shape / icon /
3D object from a prompt. In MediaHub that capability rides on **1.2 (generative
imagery edit-family)**, which is not yet shipped — its default backend is the
licence-clean local diffusion model (1.1). Rather than fake it with clip-art or a
stub, this module is an **honest seam**: it surfaces a clear, typed error until
1.2 lands, exactly as the AI honest-error rule requires (a made-up element is
worse than a clear "not yet").

When 1.2 ships, these functions call through to ``media_ai`` image generation with
a vector-style preset and trace the result to an SVG element — no caller change
needed; only this seam fills in.
"""

from __future__ import annotations

from dataclasses import dataclass


class GenerativeElementsUnavailable(RuntimeError):
    """Raised when AI element generation is requested but 1.2 hasn't shipped.

    Carries a human-facing message so the web layer can surface an honest error
    instead of fabricating an element.
    """


_NOT_YET = (
    "AI element generation needs the generative-imagery engine (roadmap 1.2), "
    "which isn't enabled yet. Browse the curated element library or import "
    "licence-clean stock in the meantime."
)


@dataclass(frozen=True)
class GenerationStatus:
    available: bool
    reason: str
    depends_on: str = "1.2"

    def to_dict(self) -> dict:
        return {"available": self.available, "reason": self.reason, "depends_on": self.depends_on}


def status() -> GenerationStatus:
    """Whether AI element generation is available (it isn't until 1.2 ships)."""
    return GenerationStatus(available=False, reason=_NOT_YET)


def generate_shape(prompt: str, *, style: str = "vector") -> dict:
    """Generate a unique shape from a prompt → traced SVG. Honest-errors until 1.2."""
    raise GenerativeElementsUnavailable(_NOT_YET)


def generate_element(prompt: str, *, kind: str = "shape") -> dict:
    """Generate an element (photo/icon/shape/3D) from a prompt. Honest-errors until 1.2."""
    raise GenerativeElementsUnavailable(_NOT_YET)


def generate_3d_element(prompt: str) -> dict:
    """Generate a 3D-render element (crest/trophy) via 1.2, cached as an image. Honest-errors until 1.2."""
    raise GenerativeElementsUnavailable(_NOT_YET)


__all__ = [
    "GenerativeElementsUnavailable",
    "GenerationStatus",
    "status",
    "generate_shape",
    "generate_element",
    "generate_3d_element",
]
