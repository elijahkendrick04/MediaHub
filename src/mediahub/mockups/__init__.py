"""Deterministic product mockups (P6.3, Build 2).

Previews a piece of artwork on a product — a framed poster, a phone post, a
flatlay — using MediaHub's own drawn scenes (no third-party stock photos, no AI,
no provider key). See :mod:`mediahub.mockups.compose`.
"""

from .compose import (
    MOCKUP_TEMPLATES,
    MockupError,
    MockupTemplate,
    compose_mockup,
    list_templates,
)

__all__ = [
    "MOCKUP_TEMPLATES",
    "MockupError",
    "MockupTemplate",
    "compose_mockup",
    "list_templates",
]
