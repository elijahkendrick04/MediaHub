"""Photoroom-API background remover.

Photoroom's `/v1/segment` endpoint accepts a multipart upload and returns a
PNG with transparent background. Pricing is per-call; we only enable this
provider when a key is configured.

Credential resolution order:
  1. ``PHOTOROOM_API_KEY`` env var
  2. ``photoroom_api_key`` in ``data/secrets.json`` (set via /settings)

Docs: https://www.photoroom.com/api/docs/reference/remove-background
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

from .base import BackgroundRemover

log = logging.getLogger(__name__)

# Public Photoroom API endpoint (sandbox + production share this hostname;
# the API key determines billing). Override via env for staging.
DEFAULT_ENDPOINT = "https://sdk.photoroom.com/v1/segment"


def _resolve_photoroom_key() -> Optional[str]:
    """Env wins, then secrets store. Returns None if neither set."""
    env = os.environ.get("PHOTOROOM_API_KEY")
    if env and env.strip():
        return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret("photoroom_api_key")
        return v if v else None
    except Exception:
        return None


class PhotoroomBgRemover(BackgroundRemover):
    """Photoroom cutout provider."""

    name = "photoroom"

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None):
        self._explicit_key = api_key
        self.endpoint = endpoint or os.environ.get(
            "PHOTOROOM_ENDPOINT", DEFAULT_ENDPOINT
        )

    @property
    def api_key(self) -> str:
        if self._explicit_key:
            return self._explicit_key
        return _resolve_photoroom_key() or ""

    def is_available(self) -> bool:
        return bool(self.api_key)

    def cutout(self, image_bytes: bytes) -> bytes:
        """Send raw image bytes to Photoroom; return transparent PNG bytes.

        Raises RuntimeError on missing key or non-2xx response.
        """
        key = self.api_key
        if not key:
            raise RuntimeError("PHOTOROOM_API_KEY not set")

        # Photoroom expects a multipart/form-data POST with the image under
        # the field name `image_file`. The `x-api-key` header carries the
        # credential. We force PNG output via the `format` field so the
        # transparency channel survives.
        headers = {
            "x-api-key": key,
            "Accept": "image/png, application/json",
        }
        files = {"image_file": ("input.png", image_bytes, "application/octet-stream")}
        # `crop=false` preserves the original image dimensions; without
        # it Photoroom auto-crops to the subject's bounding box and the
        # athlete then sizes/positions wrong in layouts that assume the
        # input dimensions are preserved.
        data = {"format": "png", "bg_color": "transparent", "crop": "false"}
        r = requests.post(
            self.endpoint, headers=headers, files=files, data=data, timeout=60,
        )
        if r.status_code >= 400:
            # Photoroom returns JSON on error; surface it for debuggability.
            try:
                body = r.json()
            except Exception:
                body = r.text[:300]
            raise RuntimeError(f"Photoroom error {r.status_code}: {body}")
        ct = r.headers.get("content-type", "")
        if "image" not in ct:
            raise RuntimeError(
                f"Photoroom returned non-image content-type {ct!r}: {r.text[:200]}"
            )
        return r.content

    def remove(self, src_path: str, dst_path: str) -> str:
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        if not self.api_key:
            raise RuntimeError("PHOTOROOM_API_KEY not set")
        try:
            with open(src_path, "rb") as f:
                src_bytes = f.read()
            out = self.cutout(src_bytes)
            with open(dst_path, "wb") as f:
                f.write(out)
            return dst_path
        except Exception as e:
            log.warning(
                "Photoroom bg-removal failed: %s — falling back to local rembg", e,
            )
            from .rembg_local import RembgLocalRemover
            return RembgLocalRemover().remove(src_path, dst_path)


__all__ = ["PhotoroomBgRemover"]
