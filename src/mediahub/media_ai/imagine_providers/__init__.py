"""Image-AI providers for the P6.3 ``imagine`` seam.

MediaHub's in-house-first rule makes a licence-clean, self-hosted diffusion model
the **default** backend (``local``, roadmap 1.1 — reached over HTTP at
``MEDIAHUB_IMAGINE_LOCAL_ENDPOINT``); cloud generators are optional on the same
seam. With no local endpoint configured the slot is unavailable, so an operator
with a Gemini key falls through to the cloud provider.

Resolution order (first usable wins):

1. ``MEDIAHUB_IMAGINE_PROVIDER`` env var, in ``{local, gemini}``. An explicit
   choice is honoured even if it is not available — the caller gets an honest
   "not configured" error rather than a silent switch to a billed cloud call
   they did not ask for.
2. Unset → prefer ``local`` (the intended default) when it is available, else
   fall through to ``gemini`` when a Gemini key is present.
3. Nothing usable → the facade raises ``ProviderNotConfigured``.

This mirrors the cutout-provider resolver (``media_ai/providers/__init__.py``)
and the LLM wrapper's Gemini-first doctrine.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .base import GeneratedImage, ImageInput, ImagineProvider

log = logging.getLogger(__name__)

_VALID = {"local", "gemini"}


def _provider_choice() -> Optional[str]:
    raw = (os.environ.get("MEDIAHUB_IMAGINE_PROVIDER") or "").strip().lower()
    if not raw:
        return None
    if raw not in _VALID:
        log.warning("Unknown MEDIAHUB_IMAGINE_PROVIDER=%r; ignoring", raw)
        return None
    return raw


def _local() -> ImagineProvider:
    from .local_imagine import LocalImagineProvider

    return LocalImagineProvider()


def _gemini() -> ImagineProvider:
    from .gemini_imagine import GeminiImagineProvider

    return GeminiImagineProvider()


def get_imagine_provider() -> Optional[ImagineProvider]:
    """Return the active image-AI provider, or ``None`` if none is configured.

    An explicit ``MEDIAHUB_IMAGINE_PROVIDER`` is always honoured (returned even
    when not available, so its operations honest-error rather than silently
    falling to a different backend). With no explicit choice, prefer the local
    default when available, else a key-configured Gemini, else ``None``.
    """
    choice = _provider_choice()
    if choice == "local":
        return _local()
    if choice == "gemini":
        return _gemini()

    # No explicit choice — in-house first, then cloud fall-through.
    local = _local()
    if local.is_available():
        return local
    gemini = _gemini()
    if gemini.is_available():
        return gemini
    return None


__all__ = [
    "ImagineProvider",
    "ImageInput",
    "GeneratedImage",
    "get_imagine_provider",
]
