"""Local diffusion image provider — the in-house-first default backend (1.1).

MediaHub's in-house-first rule (roadmap rule 11) makes a licence-clean,
self-hosted diffusion model (e.g. **FLUX.1-schnell, Apache-2.0**) the default
backend for the whole imagery suite: generate / similar / edit / fill / expand /
remove / style-match run with **no cloud key**, with cloud generators
(Gemini/Imagen) optional on the same seam.

**How "self-hosted" works here.** The diffusion model is heavy and GPU-bound, so
— exactly like the Remotion/Playwright renderers — it runs as the operator's own
process and MediaHub talks to it over HTTP. The operator stands up an inference
server (FLUX.1-schnell behind a small adapter) on their own infrastructure and
points MediaHub at it with ``MEDIAHUB_IMAGINE_LOCAL_ENDPOINT``. Nothing leaves
the operator's network, no third party is billed, and MediaHub ships **no model
weights and no new heavy dependency** — only this HTTP client. (The same shape
the local-LLM path uses: a keyless self-hosted endpoint, roadmap 1.26.)

**The contract** (MediaHub-native JSON over HTTP; tolerant on the way back):

* one ``POST {endpoint}/<op>`` per operation, JSON body, e.g. ::

      POST {endpoint}/generate
      {"prompt": "...", "style": "editorial", "aspect": "9:16",
       "n": 1, "allow_people": false, "model": "flux.1-schnell"}

  Edit-family ops carry the source ``image`` (base64) and, where relevant, a
  ``mask`` (base64 PNG whose painted region marks where to act).
* the response may be **raw image bytes** (``Content-Type: image/*``) or JSON
  carrying base64 images under ``images`` / ``data`` (OpenAI-images-compatible) /
  ``image``. Base64 may be a bare string or a ``data:`` URI. This tolerance lets
  a range of self-hosted servers slot in behind a thin adapter.

**Honest, never fake.** No endpoint → the slot is unavailable and the facade
honest-errors (:class:`ProviderNotConfigured`). A configured-but-failing endpoint
→ :class:`ImagineError` with a redacted reason — never a stubbed or substituted
image. Capabilities are declared (not silently assumed): the default advertises
the realistic FLUX inpaint vocabulary and the operator can narrow or widen it.

Configuration (env):

* ``MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`` — base URL of the inference server
  (presence ⇒ available). Required.
* ``MEDIAHUB_IMAGINE_LOCAL_TOKEN`` — optional bearer token for the endpoint.
* ``MEDIAHUB_IMAGINE_LOCAL_MODEL`` — model id recorded in provenance
  (default ``flux.1-schnell``).
* ``MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES`` — comma list overriding the advertised
  ops, or ``all``. Default ``generate,similar,edit,expand,remove,style_match``
  (``upscale`` is opt-in — it needs a dedicated upscaler model).
* ``MEDIAHUB_IMAGINE_LOCAL_TIMEOUT`` — per-request timeout seconds (default 180).
* ``MEDIAHUB_IMAGINE_LOCAL_STEPS`` — optional inference steps passed through
  (FLUX.1-schnell is happy at ~4); unset ⇒ the server decides.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from .base import GeneratedImage, ImageInput, ImagineProvider
from .styles import compose_prompt

log = logging.getLogger(__name__)

# The realistic capability set of a FLUX.1-schnell inpaint-capable server. The
# headline "generate / edit / fill / expand / remove" are all here; ``upscale``
# is opt-in because it needs a separate upscaler model (Real-ESRGAN etc.).
_DEFAULT_CAPS = ("generate", "similar", "edit", "expand", "remove", "style_match")
_ALL_CAPS = ("generate", "similar", "edit", "expand", "remove", "upscale", "style_match")


def _endpoint() -> str:
    return (os.environ.get("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT") or "").strip().rstrip("/")


def _token() -> str:
    return (os.environ.get("MEDIAHUB_IMAGINE_LOCAL_TOKEN") or "").strip()


def _default_model() -> str:
    return (os.environ.get("MEDIAHUB_IMAGINE_LOCAL_MODEL") or "").strip() or "flux.1-schnell"


def _timeout() -> int:
    raw = (os.environ.get("MEDIAHUB_IMAGINE_LOCAL_TIMEOUT") or "").strip()
    try:
        return int(raw) if raw else 180
    except ValueError:
        return 180


def _steps() -> Optional[int]:
    raw = (os.environ.get("MEDIAHUB_IMAGINE_LOCAL_STEPS") or "").strip()
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def _configured_caps() -> set[str]:
    raw = (os.environ.get("MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES") or "").strip().lower()
    if not raw:
        return set(_DEFAULT_CAPS)
    if raw == "all":
        return set(_ALL_CAPS)
    valid = set(_ALL_CAPS)
    chosen = {p.strip() for p in raw.split(",") if p.strip()}
    unknown = chosen - valid
    if unknown:
        log.warning("Ignoring unknown MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES: %s", sorted(unknown))
    return chosen & valid


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode_image_field(value: object) -> Optional[bytes]:
    """Decode one base64 image value (bare string or ``data:`` URI)."""
    if not isinstance(value, str) or not value:
        return None
    s = value
    if s.startswith("data:"):
        comma = s.find(",")
        if comma != -1:
            s = s[comma + 1 :]
    try:
        return base64.b64decode(s)
    except Exception:
        return None


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class LocalImagineProvider(ImagineProvider):
    """Self-hosted diffusion backend, reached over HTTP (the in-house default)."""

    name = "local"

    # -- availability / capability ------------------------------------------

    def is_available(self) -> bool:
        return bool(_endpoint())

    def default_model(self) -> str:
        return _default_model()

    def capabilities(self) -> set[str]:
        # Advertise nothing until an endpoint exists, so the facade never routes
        # to an empty slot; once configured, the declared (configurable) set.
        if not self.is_available():
            return set()
        return _configured_caps()

    # -- HTTP plumbing ------------------------------------------------------

    def _not_configured(self):
        from mediahub.media_ai.imagine import ProviderNotConfigured

        return ProviderNotConfigured(
            "The local image backend has no endpoint. Set "
            "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT to your self-hosted diffusion "
            "server, or configure a Gemini key to use cloud imagery."
        )

    def _require(self, operation: str):
        if not self.is_available():
            raise self._not_configured()
        if operation not in self.capabilities():
            raise self._unsupported(operation)

    def _request(self, op: str, body: dict) -> list[GeneratedImage]:
        """POST one operation to the endpoint and return the produced images."""
        from mediahub.media_ai.imagine import ImagineError

        endpoint = _endpoint()
        if not endpoint:
            raise self._not_configured()
        try:
            import requests  # type: ignore
        except Exception as e:  # pragma: no cover - requests is a hard dep
            raise ImagineError(f"The local image backend needs the 'requests' library: {e}")

        headers = {"Content-Type": "application/json", "Accept": "image/*, application/json"}
        token = _token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {k: v for k, v in body.items() if v is not None}
        body.setdefault("model", _default_model())
        url = f"{endpoint}/{op}"
        try:
            r = requests.post(url, json=body, headers=headers, timeout=_timeout())
        except Exception as e:  # network / timeout
            raise ImagineError(f"The local image backend ({op}) could not be reached: {_red(e)}")
        if r.status_code < 200 or r.status_code >= 300:
            raise ImagineError(
                f"The local image backend ({op}) returned HTTP {r.status_code}: "
                f"{_red((r.text or '')[:300])}"
            )
        images = _images_from_response(r)
        if not images:
            raise ImagineError(
                f"The local image backend ({op}) returned no image. Check the "
                f"server logs at {endpoint}."
            )
        return images

    # -- operations ---------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        style: Optional[str] = None,
        aspect: str = "1:1",
        n: int = 1,
        allow_people: bool = False,
        refs: Optional[list[ImageInput]] = None,
    ) -> list[GeneratedImage]:
        self._require("generate")
        body = {
            "prompt": compose_prompt(prompt, style),
            "style": (style or "").strip() or None,
            "aspect": aspect,
            "n": max(1, min(int(n), 4)),
            "allow_people": bool(allow_people),
            "steps": _steps(),
        }
        if refs:
            body["refs"] = [_b64(r.data) for r in refs if getattr(r, "data", None)]
        return self._request("generate", body)

    def similar(
        self,
        image: ImageInput,
        *,
        prompt: str = "",
        n: int = 1,
        allow_people: bool = False,
    ) -> list[GeneratedImage]:
        # Unlike the cloud backend, a local diffusion server conditions on the
        # reference pixels (img2img), so a bare reference is valid — no prompt
        # required.
        self._require("similar")
        body = {
            "image": _b64(image.data),
            "prompt": (prompt or "").strip() or None,
            "n": max(1, min(int(n), 4)),
            "allow_people": bool(allow_people),
            "steps": _steps(),
        }
        return self._request("similar", body)

    def edit(
        self,
        image: ImageInput,
        instruction: str,
        *,
        allow_people: bool = False,
    ) -> GeneratedImage:
        self._require("edit")
        body = {
            "image": _b64(image.data),
            "mask": _b64(image.mask) if image.mask else None,
            "prompt": (instruction or "").strip(),
            "allow_people": bool(allow_people),
            "steps": _steps(),
        }
        return self._request("edit", body)[0]

    def expand(
        self,
        image: ImageInput,
        *,
        aspect: str,
        prompt: str = "",
    ) -> GeneratedImage:
        self._require("expand")
        body = {
            "image": _b64(image.data),
            "aspect": aspect,
            "prompt": (prompt or "").strip() or None,
            "steps": _steps(),
        }
        return self._request("expand", body)[0]

    def remove(self, image: ImageInput) -> GeneratedImage:
        self._require("remove")
        body = {
            "image": _b64(image.data),
            "mask": _b64(image.mask) if image.mask else None,
            "steps": _steps(),
        }
        return self._request("remove", body)[0]

    def upscale(self, image: ImageInput, *, factor: int = 2) -> GeneratedImage:
        self._require("upscale")
        body = {"image": _b64(image.data), "factor": max(1, int(factor))}
        return self._request("upscale", body)[0]

    def style_match(
        self,
        image: ImageInput,
        *,
        style: str,
        palette: Optional[dict] = None,
    ) -> GeneratedImage:
        self._require("style_match")
        body = {
            "image": _b64(image.data),
            "style": (style or "").strip(),
            "prompt": compose_prompt("", style),
            "palette": palette or None,
            "steps": _steps(),
        }
        return self._request("style_match", body)[0]


def _images_from_response(r) -> list[GeneratedImage]:
    """Pull produced images out of a tolerant set of response shapes."""
    ctype = (r.headers.get("Content-Type") or "").lower()
    if ctype.startswith("image/"):
        data = r.content or b""
        return (
            [GeneratedImage(data=data, mime=ctype.split(";")[0].strip() or _sniff_mime(data))]
            if data
            else []
        )

    try:
        body = r.json()
    except Exception:
        return []
    if not isinstance(body, dict):
        return []

    # Ordered list of the keys a server might carry images under.
    items: list = []
    for key in ("images", "data"):
        val = body.get(key)
        if isinstance(val, list):
            items = val
            break
    if not items:
        for key in ("image", "b64", "b64_json"):
            if body.get(key):
                items = [body[key]]
                break

    default_mime = body.get("mime") if isinstance(body.get("mime"), str) else None
    out: list[GeneratedImage] = []
    for item in items:
        data: Optional[bytes] = None
        mime = default_mime
        seed = None
        if isinstance(item, str):
            data = _decode_image_field(item)
        elif isinstance(item, dict):
            for f in ("b64", "b64_json", "data", "image"):
                if item.get(f):
                    data = _decode_image_field(item[f])
                    if data is not None:
                        break
            if isinstance(item.get("mime"), str):
                mime = item["mime"]
            if isinstance(item.get("seed"), int):
                seed = item["seed"]
        if data:
            out.append(GeneratedImage(data=data, mime=mime or _sniff_mime(data), seed=seed))
    return out


def _red(value: object) -> str:
    """Redact the endpoint bearer token from an error/exception string."""
    s = str(value)
    tok = _token()
    if tok and tok in s:
        s = s.replace(tok, "***")
    return s


__all__ = ["LocalImagineProvider"]
