"""Local rembg-based background remover. Free, decent quality.

Lazy-imports rembg so the module loads even if rembg/onnxruntime are absent.
First run downloads the u2net model (~170MB) into ~/.u2net/.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import BackgroundRemover

log = logging.getLogger(__name__)


class RembgLocalRemover(BackgroundRemover):
    name = "rembg_local"

    def __init__(self, model: str = "u2net"):
        self.model = model
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
