"""Background-removal providers.

V8.1 Issue 7 \u00a74 introduced an explicit provider selector and a Photoroom
provider alongside the pre-existing local rembg + Replicate options.

Resolution order (first match wins):

1. ``MEDIAHUB_CUTOUT_PROVIDER`` env var, in ``{local, replicate, photoroom}``
   (also accepts ``rembg`` as an alias for ``local``).
2. Legacy ``MEDIAHUB_BG_PROVIDER`` env var (``rembg`` / ``replicate``).
3. ``data/secrets.json`` ``mediahub_cutout_provider`` field.
4. Default: ``local``.

If the chosen provider is an API-backed one but the relevant token is not
present, we silently downgrade to ``local`` so the no-API-key path keeps
working. This is required by the spec ("Do not break the no-API-key path").
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .base import BackgroundRemover

log = logging.getLogger(__name__)

_VALID = {"local", "rembg", "replicate", "photoroom"}


def _resolve_provider_choice() -> str:
    """Return one of {'local', 'replicate', 'photoroom'}."""
    raw = os.environ.get("MEDIAHUB_CUTOUT_PROVIDER")
    if not raw:
        raw = os.environ.get("MEDIAHUB_BG_PROVIDER")
    if not raw:
        try:
            from mediahub.web.secrets_store import get_secret
            raw = get_secret("mediahub_cutout_provider")
        except Exception:
            raw = None
    if not raw:
        return "local"
    raw = raw.strip().lower()
    if raw == "rembg":
        return "local"
    if raw not in _VALID:
        log.warning("Unknown MEDIAHUB_CUTOUT_PROVIDER=%r; defaulting to local", raw)
        return "local"
    return raw


def get_bg_remover() -> Optional[BackgroundRemover]:
    """Return the best available background remover for the current config.

    Falls back to the local rembg remover whenever the requested API-backed
    provider has no credentials, so callers can rely on a non-None object.
    """
    choice = _resolve_provider_choice()

    if choice == "photoroom":
        from .photoroom_provider import PhotoroomBgRemover
        prov = PhotoroomBgRemover()
        if prov.is_available():
            return prov
        log.info("Photoroom selected but PHOTOROOM_API_KEY missing \u2014 using local rembg")

    if choice == "replicate":
        from .replicate_provider import ReplicateBgRemover
        prov = ReplicateBgRemover()
        if prov.is_available():
            return prov
        log.info("Replicate selected but REPLICATE_API_TOKEN missing \u2014 using local rembg")

    from .rembg_local import RembgLocalRemover
    return RembgLocalRemover()


__all__ = ["BackgroundRemover", "get_bg_remover"]
