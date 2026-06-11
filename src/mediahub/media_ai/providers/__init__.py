"""Background-removal providers.

MediaHub supports three cutout backends, all running on the deployed server
side of the SaaS \u2014 the customer never installs or runs anything:

  * ``server`` (default) \u2014 in-process rembg model running on the deployment's
    CPU. Free, no per-image API spend, ~300 ms per image. Historically called
    ``local`` because it runs in the same Python process as Flask; the value
    ``local`` is still accepted for backward compatibility but the
    ``server`` label is preferred since "local" implied "on the customer's
    machine", which is never the case for the hosted product.
  * ``replicate`` \u2014 cloud API (Replicate). Requires ``REPLICATE_API_TOKEN``.
  * ``photoroom`` \u2014 cloud API (Photoroom). Requires ``PHOTOROOM_API_KEY``.

Resolution order (first match wins):

1. ``MEDIAHUB_CUTOUT_PROVIDER`` env var, in ``{server, local, rembg, replicate, photoroom}``
   (``local`` and ``rembg`` are accepted aliases for ``server``).
2. Legacy ``MEDIAHUB_BG_PROVIDER`` env var (``rembg`` / ``replicate``).
3. ``data/secrets.json`` ``mediahub_cutout_provider`` field.
4. Default: ``server`` (in-process rembg).

If the chosen cloud provider is missing its API token, the resolver falls
through to the in-process server-side rembg backend so cutouts continue to
work on the deployment even when an operator has selected a cloud provider
without yet wiring up its credentials.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .base import BackgroundRemover

log = logging.getLogger(__name__)

_VALID = {"server", "local", "rembg", "replicate", "photoroom"}


def _resolve_provider_choice() -> str:
    """Return one of {'server', 'replicate', 'photoroom'}. The legacy
    ``local`` / ``rembg`` config values are accepted and normalised to
    ``server`` (the in-process rembg backend running on the deployed
    server)."""
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
        return "server"
    raw = raw.strip().lower()
    if raw in ("local", "rembg"):
        return "server"
    if raw not in _VALID:
        log.warning("Unknown MEDIAHUB_CUTOUT_PROVIDER=%r; defaulting to server", raw)
        return "server"
    return raw


def get_bg_remover() -> Optional[BackgroundRemover]:
    """Return the configured background remover for the deployment.

    When a cloud provider (Photoroom / Replicate) is selected but its
    credential isn't present, falls through to the in-process server-side
    rembg backend so cutouts keep working on the live deployment. Callers
    can rely on a non-None object.
    """
    choice = _resolve_provider_choice()

    if choice == "photoroom":
        from .photoroom_provider import PhotoroomBgRemover

        prov = PhotoroomBgRemover()
        if prov.is_available():
            return prov
        log.info("Photoroom selected but PHOTOROOM_API_KEY missing \u2014 using server-side rembg")

    if choice == "replicate":
        from .replicate_provider import ReplicateBgRemover

        prov = ReplicateBgRemover()
        if prov.is_available():
            return prov
        log.info(
            "Replicate selected but REPLICATE_API_TOKEN missing \u2014 using server-side rembg"
        )

    from .rembg_local import RembgLocalRemover

    return RembgLocalRemover()


__all__ = ["BackgroundRemover", "get_bg_remover"]
