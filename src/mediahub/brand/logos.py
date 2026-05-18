"""brand/logos.py — D1. Multi-logo storage + AI description.

The signup form lets the user drop any number of logo files (PNG, JPG,
SVG, WEBP, PDF, EPS, AI). This module owns:

  - on-disk storage layout under {DATA_DIR}/club_logos/<profile_id>/
  - a metadata record per logo that lives on ClubProfile.brand_logos
  - an optional AI vision pass that produces a short description +
    dominant colour palette so downstream image/motion generators can
    pick the right logo variant (mono vs full-colour, wordmark vs icon)
    without forcing the user to label each file manually

Each logo's metadata dict:

    {
      "logo_id":           "<uuid hex 12>",
      "original_filename": "navy-on-white.svg",
      "stored_path":       "club_logos/your-club/<uuid>.svg",  # relative to DATA_DIR
      "mime":              "image/svg+xml",
      "byte_size":         1234,
      "uploaded_at":       "2026-05-18T12:00:00+00:00",
      "label":             "navy on white",                   # user-editable
      "ai_description":    "Wordmark on transparent background. Suits dark UIs.",
      "ai_dominant_colours": ["#0a2540", "#f5f2e8"],
    }

No automatic logo *generation* happens here — the user uploads the
files they already have. Generation belongs to the motion / graphic
renderers downstream.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Accepted file extensions. The UI accept= attribute also lists MIME
# types — the server still validates the extension because some
# browsers (notably Safari) send empty MIME for SVG/PDF/EPS uploads.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    "png", "jpg", "jpeg", "webp", "svg", "pdf", "eps", "ai", "tiff", "tif", "gif",
})

# Per-file size cap. Logos are typically small; cap stops zip-bomb /
# disk-fill attacks while leaving headroom for high-res print files.
MAX_LOGO_BYTES = 20 * 1024 * 1024  # 20 MB

# Reasonable cap on how many logos a single org keeps on file. The
# user said "as many logos as they like" — but every logo costs disk
# and renders. 25 is plenty for a single club with multiple variants.
MAX_LOGOS_PER_PROFILE = 25


def _data_dir() -> Path:
    base = os.environ.get("DATA_DIR")
    if base:
        return Path(base)
    return Path(__file__).resolve().parents[1] / "data"


def logos_dir(profile_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "_", (profile_id or "").lower().strip())
    if not safe:
        raise ValueError("profile_id required to resolve logos dir")
    d = _data_dir() / "club_logos" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ext(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower().strip()


def _mime_for(ext: str) -> str:
    if ext == "svg":
        return "image/svg+xml"
    if ext in ("eps", "ai"):
        return "application/postscript"
    if ext == "pdf":
        return "application/pdf"
    guess, _ = mimetypes.guess_type("x." + ext)
    return guess or "application/octet-stream"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# AI vision pass — optional, gracefully no-ops without a vision model
# ---------------------------------------------------------------------------

def describe_logo_with_ai(file_bytes: bytes, mime: str) -> dict:
    """Ask the vision LLM to describe a logo. Returns ``{"description":
    str, "dominant_colours": list[str]}`` or empty dict on failure.

    The result feeds two consumers:
      1. brand.context._logos_prose — the AI sees which logo variants
         exist when picking imagery for a generated post.
      2. The signup-page thumbnail grid — short auto-label so the user
         doesn't have to type one for every variant.

    Never raises.
    """
    if not file_bytes:
        return {}
    try:
        from mediahub.media_ai import llm as _llm
    except Exception:
        return {}
    if not getattr(_llm, "is_available", lambda: False)():
        return {}
    # We don't unconditionally invoke vision — many deployments don't
    # have a vision-capable model. Look for a vision helper first; the
    # llm wrapper exposes one if available.
    describe = getattr(_llm, "describe_image", None)
    if not callable(describe):
        return {}
    try:
        result = describe(
            file_bytes,
            mime=mime,
            instruction=(
                "Describe this logo in one short sentence (<=140 chars), "
                "focusing on what makes it visually distinctive (icon "
                "vs wordmark, mono vs full-colour, light vs dark, what's "
                "suited to dark backgrounds vs light). Then list the 2-4 "
                "dominant hex colours. Return JSON with keys "
                "'description' and 'dominant_colours' (array of #rrggbb)."
            ),
        )
    except Exception as e:
        log.debug("logo describe_image failed: %s", e)
        return {}
    if not isinstance(result, dict):
        return {}
    out: dict = {}
    desc = result.get("description")
    if isinstance(desc, str) and desc.strip():
        out["description"] = desc.strip()[:240]
    colours = result.get("dominant_colours")
    if isinstance(colours, list):
        valid: list[str] = []
        for c in colours:
            if not isinstance(c, str):
                continue
            cl = c.strip().lower()
            if not cl.startswith("#"):
                cl = "#" + cl
            if len(cl) == 4:
                cl = "#" + "".join(ch * 2 for ch in cl[1:])
            if re.match(r"^#[0-9a-f]{6}$", cl):
                valid.append(cl)
        if valid:
            out["dominant_colours"] = valid[:4]
    return out


# ---------------------------------------------------------------------------
# Storage operations
# ---------------------------------------------------------------------------

def store_logo(
    *,
    profile_id: str,
    filename: str,
    file_bytes: bytes,
    label: str = "",
    existing_logos: Optional[list[dict]] = None,
) -> dict:
    """Persist one logo to disk and return its metadata dict.

    Raises ``ValueError`` for size / extension / capacity issues so the
    web layer can surface a friendly status to the user.
    """
    if not profile_id:
        raise ValueError("profile_id required")
    if not filename:
        raise ValueError("filename required")
    if not file_bytes:
        raise ValueError("empty file")
    if len(file_bytes) > MAX_LOGO_BYTES:
        raise ValueError(f"file exceeds {MAX_LOGO_BYTES // (1024 * 1024)} MB limit")

    ext = _ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"unsupported format '.{ext}' — accepted: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )
    if existing_logos and len(existing_logos) >= MAX_LOGOS_PER_PROFILE:
        raise ValueError(
            f"this profile already has {MAX_LOGOS_PER_PROFILE} logos — "
            "delete one before uploading another."
        )

    logo_id = uuid.uuid4().hex[:12]
    target = logos_dir(profile_id) / f"{logo_id}.{ext}"
    target.write_bytes(file_bytes)
    mime = _mime_for(ext)

    # Best-effort AI description — non-blocking on failure.
    ai = describe_logo_with_ai(file_bytes, mime)

    meta = {
        "logo_id": logo_id,
        "original_filename": filename[:240],
        "stored_path": str(target.relative_to(_data_dir())),
        "mime": mime,
        "byte_size": len(file_bytes),
        "uploaded_at": _now_iso(),
        "label": (label or "").strip()[:80],
        "ai_description": ai.get("description", ""),
        "ai_dominant_colours": ai.get("dominant_colours", []),
    }
    return meta


def delete_logo(profile_id: str, logo_id: str) -> bool:
    """Remove a logo's file from disk. Returns True if the file was
    deleted; False if it didn't exist. Never raises.
    """
    if not profile_id or not logo_id:
        return False
    try:
        d = logos_dir(profile_id)
    except Exception:
        return False
    # Try each accepted extension
    for ext in ALLOWED_EXTENSIONS:
        p = d / f"{logo_id}.{ext}"
        if p.exists():
            try:
                p.unlink()
                return True
            except Exception as e:
                log.debug("logo unlink failed for %s: %s", p, e)
                return False
    return False


def resolve_logo_path(profile_id: str, logo_id: str) -> Optional[Path]:
    """Resolve the on-disk path for a logo id. Used by the file-serving
    route. Returns None if the logo doesn't exist for that profile —
    crucial to avoid IDOR (a request for /logo/other-profile/X must
    not return the file).
    """
    if not profile_id or not logo_id:
        return None
    # Guard against traversal: logo_id must be a plain alphanumeric
    # token, not "../" or similar.
    if not re.match(r"^[a-zA-Z0-9_-]+$", logo_id):
        return None
    try:
        d = logos_dir(profile_id)
    except Exception:
        return None
    for ext in ALLOWED_EXTENSIONS:
        p = d / f"{logo_id}.{ext}"
        if p.exists():
            return p
    return None


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_LOGO_BYTES",
    "MAX_LOGOS_PER_PROFILE",
    "logos_dir",
    "store_logo",
    "delete_logo",
    "resolve_logo_path",
    "describe_logo_with_ai",
]
