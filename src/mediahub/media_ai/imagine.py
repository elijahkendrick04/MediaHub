"""media_ai.imagine — the P6.3 generative-imagery seam.

One provider-agnostic facade behind which every generative-image capability
sits, mirroring the LLM wrapper's provider doctrine (``media_ai/llm.py``):

* **In-house first.** The default backend is a licence-clean, self-hosted
  diffusion model (``local``, roadmap 1.1 — reached over HTTP at
  ``MEDIAHUB_IMAGINE_LOCAL_ENDPOINT``); cloud generators (Gemini/Imagen) are
  optional on the same seam. Resolution and fall-through live in
  :mod:`mediahub.media_ai.imagine_providers`.
* **Honest errors, never a fake.** No provider → :class:`ProviderNotConfigured`.
  Provider can't do the op → :class:`ImagineUnsupported`. Over budget →
  :class:`QuotaExceeded`. A stubbed or heuristic-substituted image is never
  returned.
* **Provenance always.** Every generated/edited image is stamped: the IPTC
  ``DigitalSourceType`` AI term embedded losslessly in the file
  (:mod:`mediahub.graphic_renderer.metadata_embed`) plus a ``<file>.imagine.json``
  sidecar manifest mirroring the motion-render manifests.
* **Metered per org.** Provider-backed operations check and record against a
  per-org quota (:mod:`mediahub.observability.imagine_usage`). Deterministic
  ``subject_lift`` spends no provider budget, so it is not metered.

The facade returns bytes + a manifest; it does **not** decide where the bytes
live. Persisting a result as a ``MediaAsset`` is the web layer's job (so this
module stays UI-agnostic and fully unit-testable without Flask).

Operations
----------
Provider-backed (metered, may honest-error by capability):
    ``generate`` · ``similar`` · ``edit`` · ``expand`` · ``remove`` ·
    ``upscale`` · ``style_match``
Deterministic (reuses shipped code, not metered):
    ``subject_lift`` — cutout (``media_ai.providers``) + saliency framing
    (``graphic_renderer.saliency``).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Reuse the one canonical "no provider configured" type so callers (web routes,
# the assistant) can catch a single class across the whole AI surface.
from mediahub.ai_core.llm import ProviderNotConfigured
from .imagine_providers import GeneratedImage, ImageInput, get_imagine_provider

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class ImagineError(RuntimeError):
    """A generative-image operation failed (provider error, empty result)."""


class ImagineUnsupported(ImagineError):
    """The active provider does not support the requested operation."""


class QuotaExceeded(ImagineError):
    """The org has reached its generative-imagery quota for the window."""


# ---------------------------------------------------------------------------
# Result + quota types
# ---------------------------------------------------------------------------


@dataclass
class ImagineResult:
    """One produced image plus its provenance manifest (pre-persistence)."""

    data: bytes
    mime: str
    operation: str
    provider: str
    model: str
    manifest: dict = field(default_factory=dict)

    @property
    def ext(self) -> str:
        return "jpg" if "jpeg" in (self.mime or "") or "jpg" in (self.mime or "") else "png"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class QuotaStatus:
    ok: bool
    limit: int  # -1 = unlimited
    used: int
    remaining: int  # -1 = unlimited

    @property
    def unlimited(self) -> bool:
        return self.limit < 0


@dataclass
class SubjectLift:
    """Deterministic Magic-Grab result: a cutout PNG + saliency framing."""

    cutout_path: str
    focus_position: str
    status: str  # "generated" | "cached" | "failed" | "unavailable"


@dataclass
class GrabbedText:
    """Grab-Text result: text lifted out of an image, ready to re-set on-brand."""

    text: str
    blocks: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.text.strip())


# ---------------------------------------------------------------------------
# Availability / capabilities
# ---------------------------------------------------------------------------

# The full P6.3 operation vocabulary the seam advertises (subject_lift and
# grab_text are always available when their backend is — they are not Imagen
# image-generation ops).
ALL_OPERATIONS = (
    "generate",
    "similar",
    "edit",
    "expand",
    "remove",
    "upscale",
    "style_match",
    "subject_lift",
    "grab_text",
)


def is_available() -> bool:
    """True when a provider-backed image operation can run (a provider resolves)."""
    return get_imagine_provider() is not None


def active_provider_name() -> str:
    p = get_imagine_provider()
    return p.name if p is not None else ""


def vision_available() -> bool:
    """True when a vision-capable LLM (for grab_text) is configured."""
    try:
        from mediahub.media_ai import llm

        return bool(llm.is_available())
    except Exception:
        return False


def available_operations() -> set[str]:
    """Operations runnable right now: provider caps + deterministic/vision ones."""
    ops = {"subject_lift"}
    p = get_imagine_provider()
    if p is not None:
        ops |= set(p.capabilities())
    if vision_available():
        ops.add("grab_text")
    return ops


def _require_provider(operation: str):
    p = get_imagine_provider()
    if p is None:
        raise ProviderNotConfigured(
            "No image provider is configured. The default is the in-house local "
            "diffusion backend — set MEDIAHUB_IMAGINE_LOCAL_ENDPOINT to your "
            "self-hosted server, or configure a Gemini key, to use generative "
            "imagery."
        )
    # An explicitly-selected-but-unavailable provider (e.g. the local slot with
    # no endpoint, or gemini without a key) gets the actionable "not configured"
    # error rather than a capability complaint.
    if not p.is_available():
        raise ProviderNotConfigured(
            f"The selected image provider ({p.name!r}) is not available. Set "
            f"MEDIAHUB_IMAGINE_LOCAL_ENDPOINT for the in-house local backend, or "
            f"configure a Gemini key, to generate imagery."
        )
    if not p.supports(operation):
        raise ImagineUnsupported(
            f"The active image provider ({p.name!r}) does not support "
            f"{operation!r}. The in-house local diffusion backend covers the "
            f"full edit family; cloud providers vary."
        )
    return p


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

# Sensible default monthly cap per org — generous for a small club, a guardrail
# against a runaway loop. Operators tune it; PC.4 will fold real tier numbers in.
DEFAULT_MONTHLY_QUOTA = 100


def monthly_quota() -> int:
    """The per-org monthly operation cap. ``-1`` means unlimited."""
    raw = (os.environ.get("MEDIAHUB_IMAGINE_QUOTA_MONTHLY") or "").strip()
    if not raw:
        return DEFAULT_MONTHLY_QUOTA
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MONTHLY_QUOTA


def check_quota(org_id: str) -> QuotaStatus:
    """Where an org stands against its monthly generative-imagery quota."""
    limit = monthly_quota()
    if limit < 0:
        return QuotaStatus(ok=True, limit=-1, used=0, remaining=-1)
    from mediahub.observability import imagine_usage

    used = imagine_usage.count_for_org(org_id, window_hours=imagine_usage.MONTHLY_WINDOW_HOURS)
    remaining = max(0, limit - used)
    return QuotaStatus(ok=(used < limit), limit=limit, used=used, remaining=remaining)


def _enforce_quota(org_id: str, operation: str) -> None:
    status = check_quota(org_id)
    if not status.ok:
        raise QuotaExceeded(
            f"Monthly image quota reached ({status.used}/{status.limit}). "
            f"It resets on a rolling 30-day window."
        )


def _record(
    org_id: Optional[str],
    operation: str,
    provider: str,
    model: str,
    *,
    ok: bool,
    error: Optional[BaseException] = None,
) -> None:
    if not org_id:
        return
    from mediahub.observability import imagine_usage

    imagine_usage.record_use(
        org_id=org_id,
        op=operation,
        ok=ok,
        provider=provider,
        model=model,
        error_kind=type(error).__name__ if error is not None else None,
        error_message=_redact(str(error)) if error is not None else None,
    )


# ---------------------------------------------------------------------------
# Manifest / redaction
# ---------------------------------------------------------------------------


def _redact(text: Optional[str]) -> str:
    """Mask any provider key that may have leaked into prompt/error text."""
    s = text or ""
    for env_name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEDIAHUB_IMAGINE_LOCAL_TOKEN",
    ):
        v = os.environ.get(env_name)
        if v and v in s:
            s = s.replace(v, "***")
    return s


def _manifest(
    *,
    operation: str,
    provider: str,
    model: str,
    data: bytes,
    prompt: str = "",
    style: str = "",
    aspect: str = "",
    allow_people: bool = False,
    source_asset_id: str = "",
    org_id: str = "",
) -> dict:
    wholesale = operation in ("generate", "similar")
    return {
        "operation": operation,
        "provider": provider,
        "model": model,
        "prompt": _redact(prompt),
        "style": style,
        "aspect": aspect,
        "allow_people": bool(allow_people),
        "source_asset_id": source_asset_id,
        "org_id": org_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "digital_source_type": "ai_generated" if wholesale else "ai_composite",
        "software": f"MediaHub ({model})" if model else "MediaHub",
        "generated_by": "media_ai.imagine",
    }


def _result(
    img: GeneratedImage, *, operation: str, provider: str, model: str, **mk
) -> ImagineResult:
    return ImagineResult(
        data=img.data,
        mime=img.mime or "image/png",
        operation=operation,
        provider=provider,
        model=model,
        manifest=_manifest(
            operation=operation, provider=provider, model=model, data=img.data, **mk
        ),
    )


def _model_of(provider) -> str:
    # Providers expose their default model id for provenance; fall back to "".
    try:
        return provider.default_model()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Provider-backed operations
# ---------------------------------------------------------------------------


def generate(
    prompt: str,
    *,
    style: Optional[str] = None,
    aspect: str = "1:1",
    n: int = 1,
    allow_people: bool = False,
    org_id: Optional[str] = None,
) -> list[ImagineResult]:
    """Text → image. Returns one :class:`ImagineResult` per sample (1–4).

    ``allow_people`` defaults to ``False`` per the no-synthetic-people rule.
    Metered against the org's quota when ``org_id`` is given.
    """
    if not (prompt or "").strip():
        raise ImagineError("A non-empty prompt is required to generate an image.")
    provider = _require_provider("generate")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "generate")
    try:
        imgs = provider.generate(prompt, style=style, aspect=aspect, n=n, allow_people=allow_people)
    except Exception as e:
        _record(org_id, "generate", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "generate", provider.name, model, ok=True)
    return [
        _result(
            img,
            operation="generate",
            provider=provider.name,
            model=model,
            prompt=prompt,
            style=(style or ""),
            aspect=aspect,
            allow_people=allow_people,
            org_id=(org_id or ""),
        )
        for img in imgs
    ]


def similar(
    image: ImageInput,
    *,
    prompt: str = "",
    n: int = 1,
    allow_people: bool = False,
    org_id: Optional[str] = None,
    source_asset_id: str = "",
) -> list[ImagineResult]:
    """On-style variations of a reference image."""
    provider = _require_provider("similar")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "similar")
    try:
        imgs = provider.similar(image, prompt=prompt, n=n, allow_people=allow_people)
    except Exception as e:
        _record(org_id, "similar", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "similar", provider.name, model, ok=True)
    return [
        _result(
            img,
            operation="similar",
            provider=provider.name,
            model=model,
            prompt=prompt,
            allow_people=allow_people,
            source_asset_id=source_asset_id,
            org_id=(org_id or ""),
        )
        for img in imgs
    ]


def edit(
    image: ImageInput,
    instruction: str,
    *,
    allow_people: bool = False,
    org_id: Optional[str] = None,
    source_asset_id: str = "",
) -> ImagineResult:
    """Prompt-driven add/replace inside a (masked) region (Magic Edit / Fill)."""
    provider = _require_provider("edit")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "edit")
    try:
        img = provider.edit(image, instruction, allow_people=allow_people)
    except Exception as e:
        _record(org_id, "edit", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "edit", provider.name, model, ok=True)
    return _result(
        img,
        operation="edit",
        provider=provider.name,
        model=model,
        prompt=instruction,
        allow_people=allow_people,
        source_asset_id=source_asset_id,
        org_id=(org_id or ""),
    )


def expand(
    image: ImageInput,
    *,
    aspect: str,
    prompt: str = "",
    org_id: Optional[str] = None,
    source_asset_id: str = "",
) -> ImagineResult:
    """Extend the canvas with generated fill (Magic Expand / outpaint)."""
    provider = _require_provider("expand")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "expand")
    try:
        img = provider.expand(image, aspect=aspect, prompt=prompt)
    except Exception as e:
        _record(org_id, "expand", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "expand", provider.name, model, ok=True)
    return _result(
        img,
        operation="expand",
        provider=provider.name,
        model=model,
        prompt=prompt,
        aspect=aspect,
        source_asset_id=source_asset_id,
        org_id=(org_id or ""),
    )


def remove(
    image: ImageInput,
    *,
    org_id: Optional[str] = None,
    source_asset_id: str = "",
) -> ImagineResult:
    """Erase masked objects and fill the hole (Magic Eraser / inpaint)."""
    provider = _require_provider("remove")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "remove")
    try:
        img = provider.remove(image)
    except Exception as e:
        _record(org_id, "remove", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "remove", provider.name, model, ok=True)
    return _result(
        img,
        operation="remove",
        provider=provider.name,
        model=model,
        source_asset_id=source_asset_id,
        org_id=(org_id or ""),
    )


def upscale(
    image: ImageInput,
    *,
    factor: int = 2,
    org_id: Optional[str] = None,
    source_asset_id: str = "",
) -> ImagineResult:
    """Provider super-resolution / enhance (print-pipeline dependency)."""
    provider = _require_provider("upscale")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "upscale")
    try:
        img = provider.upscale(image, factor=factor)
    except Exception as e:
        _record(org_id, "upscale", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "upscale", provider.name, model, ok=True)
    return _result(
        img,
        operation="upscale",
        provider=provider.name,
        model=model,
        source_asset_id=source_asset_id,
        org_id=(org_id or ""),
    )


def style_match(
    image: ImageInput,
    *,
    style: str,
    palette: Optional[dict] = None,
    org_id: Optional[str] = None,
    source_asset_id: str = "",
) -> ImagineResult:
    """Re-style an image toward a brand look/feel (Style Match)."""
    provider = _require_provider("style_match")
    model = _model_of(provider)
    if org_id:
        _enforce_quota(org_id, "style_match")
    try:
        img = provider.style_match(image, style=style, palette=palette)
    except Exception as e:
        _record(org_id, "style_match", provider.name, model, ok=False, error=e)
        raise
    _record(org_id, "style_match", provider.name, model, ok=True)
    return _result(
        img,
        operation="style_match",
        provider=provider.name,
        model=model,
        style=style,
        source_asset_id=source_asset_id,
        org_id=(org_id or ""),
    )


# ---------------------------------------------------------------------------
# Deterministic operation — subject lift (Magic Grab)
# ---------------------------------------------------------------------------


def subject_lift(
    image_path: str | Path,
    *,
    ratio: str = "4:5",
    out_path: Optional[str | Path] = None,
) -> SubjectLift:
    """Lift the subject from a photo (cutout) and frame it (saliency).

    Deterministic and key-free — reuses the shipped cutout provider
    (``media_ai.providers.get_bg_remover``) and saliency framing
    (``graphic_renderer.saliency.focus_position``). Spends no provider budget,
    so it is not quota-metered.
    """
    src = Path(image_path)
    if not src.exists():
        return SubjectLift(cutout_path="", focus_position="center 28%", status="no_source")

    from mediahub.media_ai.providers import get_bg_remover

    remover = get_bg_remover()
    if remover is None or not remover.is_available():
        return SubjectLift(cutout_path="", focus_position="center 28%", status="unavailable")

    dst = Path(out_path) if out_path is not None else src.with_name(src.stem + "_cutout.png")
    try:
        remover.remove(str(src), str(dst))
    except Exception as e:  # pragma: no cover - provider failure path
        log.debug("imagine.subject_lift: cutout failed: %s", e)
        return SubjectLift(cutout_path="", focus_position="center 28%", status="failed")

    if not dst.exists() or dst.stat().st_size < 1024:
        return SubjectLift(cutout_path="", focus_position="center 28%", status="failed")

    focus = "center 28%"
    try:
        from mediahub.graphic_renderer.saliency import focus_position

        focus = focus_position(dst, ratio)
    except Exception:  # pragma: no cover - saliency is best-effort framing
        pass
    return SubjectLift(cutout_path=str(dst), focus_position=focus, status="generated")


# ---------------------------------------------------------------------------
# Vision operation — grab text (Grab Text)
# ---------------------------------------------------------------------------

# A fixed, literal instruction — we transcribe what is in the image, never
# invent or translate it. The deterministic-engine / honest rules apply: this
# reads pixels, it does not fabricate copy.
_GRAB_TEXT_PROMPT = (
    "Transcribe every piece of visible text in this image exactly as written, "
    "preserving wording, capitalisation and punctuation. Put each distinct text "
    "block (heading, line, label) on its own line, top to bottom. Do not "
    "translate, summarise, correct, or add anything. If there is no legible "
    "text, reply with nothing."
)


def grab_text(
    image_path: str | Path,
    *,
    org_id: Optional[str] = None,
) -> GrabbedText:
    """Lift the text out of an image via vision OCR (Grab Text).

    Uses the configured vision LLM (Gemini/Anthropic) — it transcribes, it does
    not generate imagery — so it is gated on a vision provider, not the image
    provider. Honest-errors (:class:`ProviderNotConfigured`) when no vision LLM
    is configured. Metered against the org quota (a billed vision call).
    """
    src = Path(image_path)
    if not src.exists():
        raise ImagineError("The image to grab text from does not exist.")

    from mediahub.media_ai import llm
    from mediahub.media_ai.llm import ClaudeUnavailableError

    if not llm.is_available():
        raise ProviderNotConfigured(
            "Grab Text needs a vision-capable AI provider (Gemini or Anthropic). "
            "None is configured on this deployment."
        )
    if org_id:
        _enforce_quota(org_id, "grab_text")
    try:
        raw = llm.generate_vision([str(src)], _GRAB_TEXT_PROMPT)
    except ClaudeUnavailableError as e:
        _record(org_id, "grab_text", "vision", "", ok=False, error=e)
        raise ProviderNotConfigured(str(e))
    except Exception as e:
        _record(org_id, "grab_text", "vision", "", ok=False, error=e)
        raise ImagineError(f"Grab Text failed: {e}")
    _record(org_id, "grab_text", "vision", "", ok=True)
    text = (raw or "").strip()
    blocks = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return GrabbedText(text=text, blocks=blocks)


# ---------------------------------------------------------------------------
# Provenance stamping
# ---------------------------------------------------------------------------


def stamp_file(
    path: str | Path,
    result: ImagineResult,
    *,
    source_asset: object = None,
) -> dict:
    """Stamp a saved generated image with provenance, in place.

    Embeds the IPTC ``DigitalSourceType`` AI term (lossless) into the file and
    writes a ``<path>.imagine.json`` sidecar manifest. ``source_asset`` (for an
    edit of a real photo) carries the source's credit chain forward. Returns the
    manifest dict. Best-effort: a metadata-embed failure still writes the
    sidecar and never loses the image.
    """
    p = Path(path)
    from mediahub.graphic_renderer.metadata_embed import (
        ImageMetadata,
        embed_metadata,
        metadata_for_generated,
        metadata_from_asset,
    )

    base: Optional[ImageMetadata] = None
    if source_asset is not None and result.operation not in ("generate", "similar"):
        try:
            base = metadata_from_asset(source_asset)
        except Exception:
            base = None
    try:
        meta = metadata_for_generated(
            result.operation,
            model=result.model,
            description=result.manifest.get("prompt", ""),
            base=base,
        )
        embed_metadata(p, meta)
    except Exception as e:  # pragma: no cover - embed is best-effort
        log.debug("imagine.stamp_file: metadata embed failed: %s", e)

    # Sidecar manifest beside the file (mirrors the motion-render manifests).
    try:
        import json

        sidecar = p.with_suffix(p.suffix + ".imagine.json")
        sidecar.write_text(json.dumps(result.manifest, indent=2, sort_keys=True))
    except Exception as e:  # pragma: no cover - sidecar is best-effort
        log.debug("imagine.stamp_file: sidecar write failed: %s", e)
    return result.manifest


__all__ = [
    "ProviderNotConfigured",
    "ImagineError",
    "ImagineUnsupported",
    "QuotaExceeded",
    "ImagineResult",
    "QuotaStatus",
    "SubjectLift",
    "GrabbedText",
    "ImageInput",
    "ALL_OPERATIONS",
    "is_available",
    "active_provider_name",
    "vision_available",
    "available_operations",
    "grab_text",
    "monthly_quota",
    "check_quota",
    "generate",
    "similar",
    "edit",
    "expand",
    "remove",
    "upscale",
    "style_match",
    "subject_lift",
    "stamp_file",
]
