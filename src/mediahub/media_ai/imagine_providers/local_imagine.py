"""Local diffusion image provider — the *intended default* backend (P5.6).

MediaHub's in-house-first rule (roadmap rule 11) makes a licence-clean,
self-hosted diffusion model (e.g. FLUX.1-schnell, Apache-2.0) the default
backend for the whole P6.3 imagery suite: generate / edit / fill / expand /
remove run with **no cloud key**, with cloud generators optional on the same
seam.

That backend is **P5.6**, a Phase-3 work package that has not yet landed. Until
it does, this provider is a registered-but-empty slot: it is the default in the
resolution order, but :meth:`is_available` returns ``False`` and every
operation honest-errors with ``ProviderNotConfigured`` — exactly the pattern the
Piper TTS slot uses (``MEDIAHUB_TTS_PROVIDER=piper`` honest-errors until P5.2).

This keeps the seam honest:

* an operator who *wants* the local path and sets ``MEDIAHUB_IMAGINE_PROVIDER=
  local`` gets a clear "not yet available" error rather than a silent fall to a
  billed cloud call;
* an operator who configures nothing, but has a Gemini key, falls through to the
  cloud provider (see :func:`mediahub.media_ai.imagine_providers.get_imagine_provider`).
"""

from __future__ import annotations

import os

from .base import ImagineProvider


def _local_backend_configured() -> bool:
    """True once a real local diffusion runtime is wired up.

    P5.6 will flip this on (e.g. by detecting a model weights path or a running
    inference endpoint). Today there is no local backend, so it is always
    ``False`` and the slot honest-errors.
    """
    # An operator-facing override exists so P5.6 can light the slot up without a
    # code change once the runtime is present, but it is opt-in and undocumented
    # as a product path until the backend actually ships.
    return os.environ.get("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "").strip() != ""


class LocalImagineProvider(ImagineProvider):
    """The self-hosted diffusion slot. Empty until P5.6 fills it."""

    name = "local"

    def is_available(self) -> bool:
        return _local_backend_configured()

    def capabilities(self) -> set[str]:
        # The eventual backend supports the full vocabulary; advertise nothing
        # until it is actually present so the facade never routes to a stub.
        if not self.is_available():
            return set()
        # P5.6 will return the real capability set here.
        return set()

    def _not_configured(self):
        from mediahub.media_ai.imagine import ProviderNotConfigured

        return ProviderNotConfigured(
            "The local image backend is not yet available (P5.6). Set "
            "MEDIAHUB_IMAGINE_PROVIDER to a configured cloud provider, or "
            "configure a Gemini key, to generate imagery today."
        )

    # Every operation honest-errors until the backend lands. We override the
    # facade-facing methods so the error is "not configured" (actionable) rather
    # than the base class's "unsupported".

    def generate(self, *args, **kwargs):  # noqa: D401 - see base
        raise self._not_configured()

    def similar(self, *args, **kwargs):
        raise self._not_configured()

    def edit(self, *args, **kwargs):
        raise self._not_configured()

    def expand(self, *args, **kwargs):
        raise self._not_configured()

    def remove(self, *args, **kwargs):
        raise self._not_configured()

    def upscale(self, *args, **kwargs):
        raise self._not_configured()

    def style_match(self, *args, **kwargs):
        raise self._not_configured()


__all__ = ["LocalImagineProvider"]
