"""Server-side photo adjustment stack — deterministic PIL recipes, pre-inline.

Roadmap **G1.25**. Before a real athlete / action / venue / background photo is
base64-inlined into a card's HTML, this module can bake a small, ordered stack
of pixel adjustments into the image bytes: **sharpen, contrast, saturation,
brightness, levels, auto-contrast**. The browser-side ``_photo_treatment_css``
applies CSS *filters* at screenshot time; this is the server-side *pixel*
analogue — real adjustments, controllable to the unit, that travel with the
image into the data URI and look identical on every surface that re-uses it.

Like :mod:`graphic_renderer.saliency`, it is **deliberately not AI-driven**.
This is image-processing maths, so it lives on the deterministic side of the
engine boundary (the same rule that keeps the ranker and colour-science
reproducible): the *same image + same recipe → byte-identical output*, every
run, no LLM and no network.

Design rules
------------
* **Alpha is sacred.** A cutout's transparency mask marks exactly where the
  subject is — saliency and compositing depend on it. Every adjustment runs on
  the *visible RGB only*; the original alpha channel is re-attached untouched,
  so the mask never shifts and no edge halo is introduced.
* **Off by default, byte-identical.** With no recipe requested
  (:func:`recipe_for` returns ``None``) the renderer keeps its existing
  un-adjusted inline, so today's renders are unchanged. A recipe is opt-in via
  the ``MEDIAHUB_PHOTO_ADJUST`` env default or an explicit preset token.
* **Bounded + clamped.** Every parameter is clamped to a sane range, so a
  fat-fingered value can dull or punch a photo but never corrupt it.
* **Hashable + explainable.** A :class:`PhotoRecipe` carries a stable
  :meth:`~PhotoRecipe.signature` (a cache-key seed that feeds G1.24's
  render-stage caching) and a :meth:`~PhotoRecipe.describe` (plain-English
  steps for the why-this-design sidecar).

Public API
----------
* Primitives — ``sharpen / contrast / saturation / brightness / levels /
  auto_contrast`` each take and return a ``PIL.Image`` (alpha-preserving).
* :class:`PhotoRecipe` / :class:`AdjustStep` — an ordered, validated,
  serialisable recipe; :data:`PRESETS` are the curated named bundles.
* :func:`adjust_image` / :func:`adjust_bytes` / :func:`adjust_to_data_uri` —
  apply a recipe to an image / encoded bytes / and straight to an inline-ready
  ``data:`` URI.
* :func:`recipe_for` — resolve the recipe a render should use (or ``None``).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

__all__ = [
    "AdjustStep",
    "PhotoRecipe",
    "PRESETS",
    "PRESET_NAMES",
    "sharpen",
    "contrast",
    "saturation",
    "brightness",
    "levels",
    "auto_contrast",
    "adjust_image",
    "adjust_bytes",
    "adjust_to_data_uri",
    "recipe_for",
    "get_preset",
    "is_enabled",
    "ENV_VAR",
]

# Operator-level global default: set ``MEDIAHUB_PHOTO_ADJUST=<preset>`` to apply
# one recipe to every photo render. Unset (the default) ⇒ no adjustment.
ENV_VAR = "MEDIAHUB_PHOTO_ADJUST"

ImageLike = Union[str, Path, bytes, Image.Image]


# --------------------------------------------------------------------------- #
# Clamps — every adjustment parameter has a bounded, sane range.
# --------------------------------------------------------------------------- #

# (low, high) bounds, deliberately conservative: enough range for a real look,
# never enough to corrupt the photo. 1.0 is the identity for the enhance factors.
_BOUNDS: Dict[str, Tuple[float, float]] = {
    "contrast": (0.2, 3.0),
    "saturation": (0.0, 3.0),
    "brightness": (0.2, 3.0),
    "sharpen_amount": (0.0, 4.0),
    "sharpen_radius": (0.1, 8.0),
    "sharpen_threshold": (0.0, 255.0),
    "levels_point": (0.0, 255.0),
    "gamma": (0.2, 5.0),
    "cutoff": (0.0, 49.0),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    if v != v:  # NaN
        return lo
    return lo if v < lo else hi if v > hi else v


# --------------------------------------------------------------------------- #
# Alpha-preserving split / merge
# --------------------------------------------------------------------------- #


def _split_alpha(img: Image.Image) -> Tuple[Image.Image, Optional[Image.Image]]:
    """Return ``(rgb, alpha_or_None)`` — adjustments run on ``rgb`` alone.

    Converting RGBA→RGB *drops* the alpha band without compositing, so the
    original colour under transparent pixels is preserved exactly; the alpha is
    handed back separately so :func:`_merge_alpha` can re-attach it untouched.
    """
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        rgba = img.convert("RGBA")
        return rgba.convert("RGB"), rgba.getchannel("A")
    if img.mode == "RGB":
        return img, None
    return img.convert("RGB"), None


def _merge_alpha(rgb: Image.Image, alpha: Optional[Image.Image]) -> Image.Image:
    if alpha is None:
        return rgb
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


# --------------------------------------------------------------------------- #
# Primitives — each takes & returns a PIL.Image, alpha-preserving, deterministic
# --------------------------------------------------------------------------- #


def sharpen(
    img: Image.Image,
    amount: float = 1.0,
    radius: float = 2.0,
    threshold: int = 3,
) -> Image.Image:
    """Unsharp-mask sharpen on the visible RGB.

    ``amount`` is an intuitive 0–4 strength (1.0 ≈ a confident clarity bump);
    it maps to PIL's 0–~480 ``percent``. ``radius`` is the blur radius and
    ``threshold`` suppresses sharpening of low-contrast (noise) areas.
    """
    amt = _clamp(amount, *_BOUNDS["sharpen_amount"])
    if amt <= 0:
        return img
    rad = _clamp(radius, *_BOUNDS["sharpen_radius"])
    thr = int(_clamp(threshold, *_BOUNDS["sharpen_threshold"]))
    percent = int(round(amt * 120))  # 1.0 → 120%, the UnsharpMask default-ish
    rgb, alpha = _split_alpha(img)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=rad, percent=percent, threshold=thr))
    return _merge_alpha(rgb, alpha)


def contrast(img: Image.Image, factor: float = 1.0) -> Image.Image:
    """Scale contrast about mid-grey. 1.0 = identity, >1 punchier, <1 flatter."""
    f = _clamp(factor, *_BOUNDS["contrast"])
    if f == 1.0:
        return img
    rgb, alpha = _split_alpha(img)
    rgb = ImageEnhance.Contrast(rgb).enhance(f)
    return _merge_alpha(rgb, alpha)


def saturation(img: Image.Image, factor: float = 1.0) -> Image.Image:
    """Scale colour saturation. 1.0 = identity, 0.0 = greyscale, >1 = vivid."""
    f = _clamp(factor, *_BOUNDS["saturation"])
    if f == 1.0:
        return img
    rgb, alpha = _split_alpha(img)
    rgb = ImageEnhance.Color(rgb).enhance(f)
    return _merge_alpha(rgb, alpha)


def brightness(img: Image.Image, factor: float = 1.0) -> Image.Image:
    """Scale overall brightness. 1.0 = identity, >1 lighter, <1 darker."""
    f = _clamp(factor, *_BOUNDS["brightness"])
    if f == 1.0:
        return img
    rgb, alpha = _split_alpha(img)
    rgb = ImageEnhance.Brightness(rgb).enhance(f)
    return _merge_alpha(rgb, alpha)


def levels(
    img: Image.Image,
    black: int = 0,
    white: int = 255,
    gamma: float = 1.0,
) -> Image.Image:
    """Photoshop-style input levels: remap ``[black, white]`` to ``[0, 255]``
    with a mid-tone ``gamma``.

    ``black``/``white`` are the input black/white points (0–255); ``gamma`` > 1
    lifts mid-tones, < 1 deepens them. A degenerate ``white <= black`` is
    treated as a no-op rather than a divide-by-zero.
    """
    b = _clamp(black, *_BOUNDS["levels_point"])
    w = _clamp(white, *_BOUNDS["levels_point"])
    g = _clamp(gamma, *_BOUNDS["gamma"])
    if w <= b:
        return img
    if b == 0.0 and w == 255.0 and g == 1.0:
        return img
    span = w - b
    inv_gamma = 1.0 / g
    lut: List[int] = []
    for v in range(256):
        norm = (v - b) / span
        norm = 0.0 if norm < 0.0 else 1.0 if norm > 1.0 else norm
        out = (norm**inv_gamma) * 255.0
        lut.append(int(round(0.0 if out < 0.0 else 255.0 if out > 255.0 else out)))
    rgb, alpha = _split_alpha(img)
    rgb = rgb.point(lut * len(rgb.getbands()))
    return _merge_alpha(rgb, alpha)


def auto_contrast(img: Image.Image, cutoff: float = 0.0) -> Image.Image:
    """Deterministic per-channel histogram stretch (``ImageOps.autocontrast``).

    ``cutoff`` is the percentage of the lightest/darkest pixels to ignore when
    finding the histogram extremes — a small cutoff (≈0.5) avoids letting a
    single specular highlight or shadow speck pin the stretch.
    """
    c = _clamp(cutoff, *_BOUNDS["cutoff"])
    rgb, alpha = _split_alpha(img)
    rgb = ImageOps.autocontrast(rgb, cutoff=c)
    return _merge_alpha(rgb, alpha)


# Dispatch table: op name → callable(rgb_or_img, **params). The apply loop in
# :func:`adjust_image` splits alpha once and feeds the RGB working image here,
# so each op operates band-correctly without re-splitting per step.
_OPS: Dict[str, Callable[..., Image.Image]] = {
    "sharpen": sharpen,
    "contrast": contrast,
    "saturation": saturation,
    "brightness": brightness,
    "levels": levels,
    "auto_contrast": auto_contrast,
}


# --------------------------------------------------------------------------- #
# Recipe model
# --------------------------------------------------------------------------- #


def _coerce_params(op: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + clamp the params for ``op`` into a canonical, JSON-safe dict.

    Unknown keys are dropped and missing keys keep the primitive's identity
    default, so a recipe never carries junk that could shift the signature.
    """
    p = dict(params or {})
    if op == "sharpen":
        return {
            "amount": round(_clamp(p.get("amount", 1.0), *_BOUNDS["sharpen_amount"]), 4),
            "radius": round(_clamp(p.get("radius", 2.0), *_BOUNDS["sharpen_radius"]), 4),
            "threshold": int(_clamp(p.get("threshold", 3), *_BOUNDS["sharpen_threshold"])),
        }
    if op in ("contrast", "saturation", "brightness"):
        bound = _BOUNDS["saturation"] if op == "saturation" else _BOUNDS[op]
        return {"factor": round(_clamp(p.get("factor", 1.0), *bound), 4)}
    if op == "levels":
        return {
            "black": int(_clamp(p.get("black", 0), *_BOUNDS["levels_point"])),
            "white": int(_clamp(p.get("white", 255), *_BOUNDS["levels_point"])),
            "gamma": round(_clamp(p.get("gamma", 1.0), *_BOUNDS["gamma"]), 4),
        }
    if op == "auto_contrast":
        return {"cutoff": round(_clamp(p.get("cutoff", 0.0), *_BOUNDS["cutoff"]), 4)}
    return {}


@dataclass
class AdjustStep:
    """One validated adjustment in a recipe: an op name + clamped params."""

    op: str
    params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.op = str(self.op)
        self.params = _coerce_params(self.op, self.params)

    @property
    def valid(self) -> bool:
        return self.op in _OPS

    def apply(self, img: Image.Image) -> Image.Image:
        fn = _OPS.get(self.op)
        if fn is None:
            return img
        return fn(img, **self.params)

    def to_dict(self) -> Dict[str, Any]:
        return {"op": self.op, "params": dict(self.params)}

    def describe(self) -> str:
        p = self.params
        if self.op == "sharpen":
            return f"sharpen ×{p['amount']:g} (r={p['radius']:g}, t={p['threshold']})"
        if self.op == "contrast":
            return f"contrast ×{p['factor']:g}"
        if self.op == "saturation":
            return f"saturation ×{p['factor']:g}"
        if self.op == "brightness":
            return f"brightness ×{p['factor']:g}"
        if self.op == "levels":
            return f"levels [{p['black']}–{p['white']}] γ{p['gamma']:g}"
        if self.op == "auto_contrast":
            return f"auto-contrast (cut {p['cutoff']:g}%)"
        return self.op


@dataclass
class PhotoRecipe:
    """An ordered, validated, serialisable stack of photo adjustments.

    Construct from presets (:data:`PRESETS`), from a list of ``(op, params)``
    via :meth:`build`, or rehydrate persisted state via :meth:`from_dict`.
    Invalid steps are dropped on construction, so a recipe is always runnable.
    """

    name: str = ""
    steps: Tuple[AdjustStep, ...] = ()

    def __post_init__(self) -> None:
        self.steps = tuple(s for s in self.steps if isinstance(s, AdjustStep) and s.valid)

    # --- construction --------------------------------------------------- #

    @classmethod
    def build(
        cls,
        name: str,
        spec: List[Union[Tuple[str, Dict[str, Any]], Tuple[str], str]],
    ) -> "PhotoRecipe":
        steps: List[AdjustStep] = []
        for item in spec:
            if isinstance(item, str):
                op, params = item, {}
            elif len(item) == 1:
                op, params = item[0], {}
            else:
                op, params = item[0], item[1]
            steps.append(AdjustStep(op, params))
        return cls(name=name, steps=tuple(steps))

    @classmethod
    def from_dict(cls, data: Any) -> Optional["PhotoRecipe"]:
        """Rebuild a recipe from :meth:`to_dict`. Tolerant: bad shapes → None."""
        if not isinstance(data, dict):
            return None
        try:
            steps = tuple(
                AdjustStep(s.get("op", ""), s.get("params", {}))
                for s in data.get("steps", [])
                if isinstance(s, dict)
            )
            return cls(name=str(data.get("name", "")), steps=steps)
        except Exception:
            return None

    # --- properties ----------------------------------------------------- #

    def is_noop(self) -> bool:
        """True when applying this recipe leaves any image unchanged."""
        return len(self.steps) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "steps": [s.to_dict() for s in self.steps]}

    def describe(self) -> List[str]:
        """Plain-English step list for the why-this-design explainability sidecar."""
        return [s.describe() for s in self.steps]

    def signature(self) -> str:
        """Stable 12-hex digest of the *effect* (steps only, not the name).

        Two recipes with identical steps share a signature even if named
        differently — exactly what a render-stage cache key (G1.24) wants.
        """
        payload = json.dumps([s.to_dict() for s in self.steps], sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def __hash__(self) -> int:  # usable as a dict/cache key
        return hash(self.signature())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PhotoRecipe):
            return NotImplemented
        return [s.to_dict() for s in self.steps] == [s.to_dict() for s in other.steps]


# --------------------------------------------------------------------------- #
# Curated presets — deliberately restrained; a tasteful nudge, never a filter
# that screams "edited". Names are the opt-in tokens for ``recipe_for``.
# --------------------------------------------------------------------------- #

PRESETS: Dict[str, PhotoRecipe] = {
    # Identity — explicit "do nothing" so a caller can name it without branching.
    "none": PhotoRecipe.build("none", []),
    # Crisp clarity for action shots: tidy the histogram, then a gentle sharpen.
    "natural": PhotoRecipe.build(
        "natural",
        [("auto_contrast", {"cutoff": 0.5}), ("sharpen", {"amount": 0.5})],
    ),
    # Confident clarity bump without changing the colour mood.
    "crisp": PhotoRecipe.build(
        "crisp",
        [("sharpen", {"amount": 0.9}), ("contrast", {"factor": 1.05})],
    ),
    # Bold social pop — the default "make it look good on the feed" recipe.
    "punchy": PhotoRecipe.build(
        "punchy",
        [
            ("contrast", {"factor": 1.12}),
            ("saturation", {"factor": 1.15}),
            ("sharpen", {"amount": 0.8}),
        ],
    ),
    # Colour-forward, for bright kit / pool-deck colour.
    "vivid": PhotoRecipe.build(
        "vivid",
        [("saturation", {"factor": 1.28}), ("contrast", {"factor": 1.08})],
    ),
    # Refined magazine look: deep blacks, slightly held-back colour.
    "editorial": PhotoRecipe.build(
        "editorial",
        [
            ("contrast", {"factor": 1.06}),
            ("saturation", {"factor": 0.92}),
            ("levels", {"black": 6, "white": 250, "gamma": 0.98}),
        ],
    ),
    # Gentle, airy — for portraits / softer moods.
    "soft": PhotoRecipe.build(
        "soft",
        [
            ("contrast", {"factor": 0.94}),
            ("brightness", {"factor": 1.04}),
            ("saturation", {"factor": 0.96}),
        ],
    ),
}

# Public, stable order for any "pick a look" UI.
PRESET_NAMES: Tuple[str, ...] = (
    "natural",
    "crisp",
    "punchy",
    "vivid",
    "editorial",
    "soft",
)


def get_preset(name: str) -> Optional[PhotoRecipe]:
    """Return the named preset recipe, or ``None`` if unknown."""
    if not name:
        return None
    return PRESETS.get(str(name).strip().lower())


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #


def _as_recipe(recipe: Union[PhotoRecipe, str, None]) -> Optional[PhotoRecipe]:
    """Normalise a recipe argument to a ``PhotoRecipe`` or ``None``."""
    if recipe is None:
        return None
    if isinstance(recipe, PhotoRecipe):
        return recipe
    if isinstance(recipe, str):
        return get_preset(recipe)
    return None


def adjust_image(img: Image.Image, recipe: Union[PhotoRecipe, str, None]) -> Image.Image:
    """Apply ``recipe`` to a PIL image. Alpha-preserving and deterministic.

    The alpha channel is split off once and re-attached after every step, so a
    cutout's mask is byte-identical to the input. A ``None``/no-op recipe
    returns the image unchanged.
    """
    r = _as_recipe(recipe)
    if r is None or r.is_noop():
        return img
    rgb, alpha = _split_alpha(img)
    for step in r.steps:
        # Each op is alpha-aware too, but we feed it the already-split RGB so the
        # split happens once per recipe rather than once per step.
        rgb = step.apply(rgb)
    return _merge_alpha(rgb, alpha)


def _encode(img: Image.Image, src_format: str) -> Tuple[bytes, str]:
    """Encode an adjusted image to bytes + MIME.

    Anything carrying alpha must be PNG (JPEG can't hold it); a photo that came
    in as JPEG stays JPEG (smaller, and re-PNG-ing a photo bloats the data URI);
    everything else is PNG.
    """
    buf = io.BytesIO()
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if not has_alpha and src_format in ("JPEG", "JPG", "MPO"):
        img.convert("RGB").save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    img.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def adjust_bytes(
    data: bytes,
    recipe: Union[PhotoRecipe, str, None],
) -> bytes:
    """Decode ``data``, apply ``recipe``, re-encode. Returns the new bytes.

    A ``None``/no-op recipe returns ``data`` untouched (byte-identical).
    """
    r = _as_recipe(recipe)
    if r is None or r.is_noop():
        return data
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        src_format = (im.format or "").upper()
        out = adjust_image(im, r)
    encoded, _mime = _encode(out, src_format)
    return encoded


def adjust_to_data_uri(
    source: ImageLike,
    recipe: Union[PhotoRecipe, str, None],
) -> str:
    """Apply ``recipe`` and return an inline-ready ``data:`` URI.

    ``source`` may be a path, raw bytes, or an open PIL image. With a
    ``None``/no-op recipe the *original* bytes are passed through unchanged
    (so the result is byte-identical to a plain inline of the source).
    """
    r = _as_recipe(recipe)

    # Resolve the source to (raw_bytes, original_format_hint).
    raw: Optional[bytes] = None
    pil: Optional[Image.Image] = None
    src_suffix = ""
    if isinstance(source, Image.Image):
        pil = source
    elif isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        p = Path(source)
        raw = p.read_bytes()
        src_suffix = p.suffix.lower().lstrip(".")

    # No-op: pass the original through, mirroring render._img_to_data_uri.
    if r is None or r.is_noop():
        if raw is not None:
            mime = _MIME_BY_SUFFIX.get(src_suffix, "application/octet-stream")
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        # An in-memory image with no recipe: encode losslessly as PNG.
        buf = io.BytesIO()
        (pil or Image.new("RGB", (1, 1))).save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    if pil is not None:
        out = adjust_image(pil, r)
        encoded, mime = _encode(out, (pil.format or "").upper())
    else:
        with Image.open(io.BytesIO(raw or b"")) as im:  # type: ignore[arg-type]
            im.load()
            src_format = (im.format or "").upper()
            out = adjust_image(im, r)
        encoded, mime = _encode(out, src_format)
    return f"data:{mime};base64,{base64.b64encode(encoded).decode('ascii')}"


_MIME_BY_SUFFIX = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


# --------------------------------------------------------------------------- #
# Resolution — which recipe (if any) a render should use
# --------------------------------------------------------------------------- #


def is_enabled() -> bool:
    """True iff an operator default recipe is configured via the env var."""
    return get_preset(os.environ.get(ENV_VAR, "")) is not None


def recipe_for(
    *,
    explicit: str = "",
    treatment: str = "",
    env: bool = True,
) -> Optional[PhotoRecipe]:
    """Resolve the photo-adjust recipe a render should apply, or ``None``.

    Resolution order (first hit wins), all opt-in so the default is *no
    adjustment* and renders stay byte-identical:

    1. ``explicit`` — a recipe name a caller/brief asked for directly.
    2. ``treatment`` — the brief's ``photo_treatment`` *only if* it names a
       preset. The existing CSS treatments (``cutout`` / ``vignette`` /
       ``duotone`` / ``halftone`` / ``frame`` / ``no-photo``) are **not**
       presets, so legacy briefs resolve to ``None`` and are unchanged.
    3. ``MEDIAHUB_PHOTO_ADJUST`` — the operator-level global default.

    The ``none`` preset resolves to a real (no-op) recipe so a caller can force
    "explicitly off" past a global env default.
    """
    for token in (explicit, treatment):
        r = get_preset(token)
        if r is not None:
            return r
    if env:
        return get_preset(os.environ.get(ENV_VAR, ""))
    return None
