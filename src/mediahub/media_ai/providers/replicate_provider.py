"""Replicate-API background remover.

Uses 851-labs/background-remover by default — a high-quality production
model that handles edge-cases (translucent fabric, fly-away hair) better
than the server-side rembg `u2net`. Optional upgrade when a token is
present; falls through to the server-side rembg backend on any failure
so cutouts keep working on the deployment.

Credential resolution order:
  1. ``REPLICATE_API_TOKEN`` env var
  2. ``replicate_api_token`` in ``data/secrets.json`` (set via /settings)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

from .base import BackgroundRemover

log = logging.getLogger(__name__)

# Default model required by V8.1 Issue 7 §4. Override only via env for QA.
DEFAULT_MODEL = "851-labs/background-remover"


def _resolve_replicate_token() -> Optional[str]:
    """Env wins, then secrets store. Returns None if neither set."""
    env = os.environ.get("REPLICATE_API_TOKEN")
    if env and env.strip():
        return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret

        v = get_secret("replicate_api_token")
        return v if v else None
    except Exception:
        return None


class ReplicateBgRemover(BackgroundRemover):
    name = "replicate"

    def __init__(self, token: Optional[str] = None, model: Optional[str] = None):
        self.model = model or os.environ.get("MEDIAHUB_REPLICATE_BG_MODEL", DEFAULT_MODEL)
        # Lazily resolve so changes to the secrets store after process
        # startup are picked up on the next call.
        self._explicit_token = token

    @property
    def token(self) -> str:
        if self._explicit_token:
            return self._explicit_token
        return _resolve_replicate_token() or ""

    def is_available(self) -> bool:
        return bool(self.token)

    def cutout(self, image_bytes: bytes) -> bytes:
        """In-memory cutout. Returns transparent PNG bytes.

        Mirrors the public-API surface used by ``photoroom_provider`` so
        callers can swap providers via env var without code changes.
        """
        token = self.token
        if not token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")
        try:
            import replicate  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"replicate SDK not installed: {e}")
        import io

        client = replicate.Client(api_token=token)
        # Replicate accepts a file-like object via the `image` input on
        # 851-labs/background-remover. Wrap our bytes in BytesIO.
        output = client.run(self.model, input={"image": io.BytesIO(image_bytes)})
        url = output if isinstance(output, str) else (output[0] if output else None)
        if not url:
            raise RuntimeError("Replicate returned no image URL")
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.content

    def remove(self, src_path: str, dst_path: str) -> str:
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        if not self.token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")
        try:
            with open(src_path, "rb") as f:
                src_bytes = f.read()
            out_bytes = self.cutout(src_bytes)
            with open(dst_path, "wb") as f:
                f.write(out_bytes)
            return dst_path
        except Exception as e:
            log.warning("Replicate bg-removal failed: %s — falling back to local rembg", e)
            from .rembg_local import RembgLocalRemover

            return RembgLocalRemover().remove(src_path, dst_path)
