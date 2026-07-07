"""Server-side rembg-based background remover. Free, decent quality.

Runs in the same Python process as Flask on the deployed server — not on
the customer's machine. "Local" here means "in-process with the web app",
which the cloud-hosted SaaS treats as the default cutout backend because
it has no per-image API spend. Customers never run this themselves; the
processing always happens on the deployment side of the network.

Lazy-imports rembg so the module loads even if rembg/onnxruntime are absent.
First run downloads the model (~170MB) into ~/.u2net/.

The default matting model is ``u2net_human_seg`` (PHOTOS-7): MediaHub's
cutouts are overwhelmingly people — swimmers on a pool deck — and the
human-segmentation variant mattes them markedly better than generic u2net.
Override per deployment with ``MEDIAHUB_CUTOUT_MODEL``. The renderer folds the
model name into its cutout cache filenames, so switching models never serves
a stale matte from the previous model.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import BackgroundRemover

log = logging.getLogger(__name__)

# Operator override for the rembg matting model; unset → human segmentation.
MODEL_ENV_VAR = "MEDIAHUB_CUTOUT_MODEL"
DEFAULT_MODEL = "u2net_human_seg"


def default_model() -> str:
    """The rembg model this deployment mattes with (env-overridable)."""
    return os.environ.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL


class RembgLocalRemover(BackgroundRemover):
    name = "rembg_local"

    def __init__(self, model: str | None = None):
        self.model = model or default_model()
        self._session = None

    def _get_session(self):
        if self._session is None:
            try:
                from rembg import new_session

                self._session = new_session(self.model)
            except Exception as e:
                log.warning("rembg session init failed: %s", e)
                self._session = False
        return self._session if self._session else None

    def remove(self, src_path: str, dst_path: str) -> str:
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            from rembg import remove

            with open(src_path, "rb") as f:
                src = f.read()
            session = self._get_session()
            kwargs = {}
            if session:
                kwargs["session"] = session
            out = remove(src, **kwargs)
            with open(dst_path, "wb") as f:
                f.write(out)
            return dst_path
        except Exception as e:
            log.warning("rembg failed (%s) — falling back to passthrough alpha", e)
            return self._passthrough(src_path, dst_path)

    def _passthrough(self, src_path: str, dst_path: str) -> str:
        """Fallback: just copy the image with alpha channel intact."""
        from PIL import Image

        img = Image.open(src_path).convert("RGBA")
        img.save(dst_path, "PNG")
        return dst_path

    def is_available(self) -> bool:
        try:
            import rembg  # noqa: F401

            return True
        except Exception:
            return False
