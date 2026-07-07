#!/usr/bin/env python3
"""Download the licence-clean default Piper voice for self-hosted, offline TTS.

Roadmap 1.7 made local **Piper** the default voiceover backend (replacing the
online edge-tts). For a deployment to narrate locally out of the box it needs a
voice model present; this fetches one — by default **en_GB-alba-medium**, which
is **CC BY 4.0** (commercial use permitted with attribution), trained on the
Edinburgh ``datashare.ed.ac.uk/handle/10283/3270`` corpus.

It downloads three files into the target voice dir:
  * ``<voice>.onnx``       — the model weights
  * ``<voice>.onnx.json``  — the model config sidecar
  * ``<voice>.MODEL_CARD`` — the upstream licence/attribution card (kept beside
                             the model so the CC BY 4.0 attribution ships with it)

and writes a short ``ATTRIBUTION.txt`` recording the CC BY 4.0 credit.

`mediahub.visual.voiceover` auto-discovers a single ``.onnx`` in the voice dir
(default ``$DATA_DIR/piper_voices``), so once this has run no env configuration
is needed. The model is **not** committed to git (it is ~60 MB) — the deployed
image fetches it at build time (see the Dockerfile), exactly like the rembg
u2net preload.

Usage (from repo root):
    python scripts/fetch_piper_voice.py [TARGET_DIR] [VOICE]

  TARGET_DIR  where to write the voice (default: $MEDIAHUB_PIPER_VOICE_DIR, else
              $DATA_DIR/piper_voices, else ./data/piper_voices)
  VOICE       the piper-voices path key (default: en_GB-alba-medium)

Pick a different voice only after checking its MODEL_CARD licence — some Piper
voices are non-commercial or all-rights-reserved (see DEPENDENCY_LICENSING.md).
"""
from __future__ import annotations

import hashlib
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# rhasspy/piper-voices layout: en/en_GB/alba/medium/en_GB-alba-medium.onnx[.json]
# Pinned to an exact upstream commit (not the moving `main` branch) so the
# bytes the build fetches can never drift under the SHA256 pins below. Bump
# the commit + hashes together when intentionally updating a voice.
_COMMIT = "e21c7de8d4eab79b902f0d61e662b3f21664b8d2"
_BASE = f"https://huggingface.co/rhasspy/piper-voices/resolve/{_COMMIT}"

# voice key -> (lang_dir, speaker, quality, licence note). Only licence-clean,
# commercially-usable voices belong here.
VOICES: dict[str, tuple[str, str, str, str]] = {
    "en_GB-alba-medium": ("en/en_GB", "alba", "medium", "CC BY 4.0"),
}

# Known-good SHA-256 per fetched file (keyed by the on-disk filename). The
# model is executed in the production container, so every downloaded file is
# verified against these and a mismatch hard-fails the build — an integrity
# guard the transport alone can't give us.
SHA256: dict[str, str] = {
    "en_GB-alba-medium.onnx": (
        "401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b"
    ),
    "en_GB-alba-medium.onnx.json": (
        "aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4"
    ),
    "en_GB-alba-medium.MODEL_CARD": (
        "fa166b1779404c470b0b6b4ba0238bc4a35bf89d2cd130c6788f697188b737d6"
    ),
}

DEFAULT_VOICE = "en_GB-alba-medium"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Default *verified* TLS. Transient CDN handshake drops are handled by the
# retry loop in _get, and file integrity by the SHA256 pins — never by
# disabling certificate verification.
_ctx = ssl.create_default_context()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Hard-fail unless ``path``'s SHA-256 matches ``expected``.

    Loud by design: a mismatched voice file must fail the Docker build rather
    than ship unverified model bytes into the production container.
    """
    got = _sha256(path)
    if got != expected:
        raise RuntimeError(
            f"SHA-256 mismatch for {path.name}: expected {expected}, got {got} "
            "— refusing to ship an unverified voice file. If the upstream "
            "voice was intentionally updated, bump _COMMIT and SHA256 together."
        )


def _get(url: str, *, attempts: int = 4, timeout: int = 120) -> bytes:
    """Fetch ``url``, retrying transient network/TLS failures with backoff.

    The voice files sit behind HuggingFace's CDN, which 302-redirects to a
    storage host that intermittently drops the TLS connection mid-handshake
    (``SSL: UNEXPECTED_EOF_WHILE_READING`` — the 2026-06-22 deploy died on
    exactly this, with no retry). A single CDN blip must not fail the whole
    Docker build, so retry a few times with exponential backoff. Once the
    retries are spent we still raise: the fetch staying loud-fail is
    deliberate, since a missing voice would otherwise degrade narration
    silently at runtime.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            # A 4xx is a definite answer (wrong path / gone) — don't burn
            # retries (or build minutes) on it. Only 5xx is worth retrying.
            if exc.code < 500:
                raise
            last = exc
        except OSError as exc:
            # URLError, ssl.SSLError, socket timeouts, connection resets — all
            # transient transport faults that a retry can clear.
            last = exc
        if attempt < attempts:
            backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s, ...
            print(
                f"    fetch attempt {attempt}/{attempts} for {url} failed "
                f"({last}); retrying in {backoff}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
    raise RuntimeError(
        f"failed to fetch {url} after {attempts} attempts: {last}"
    ) from last


def _target_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("MEDIAHUB_PIPER_VOICE_DIR", "").strip()
    if env:
        return Path(env)
    data = os.environ.get("DATA_DIR", "").strip()
    base = Path(data) if data else Path(__file__).resolve().parent.parent / "data"
    return base / "piper_voices"


def main() -> int:
    target = _target_dir(sys.argv[1] if len(sys.argv) > 1 else None)
    voice = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE
    if voice not in VOICES:
        print(
            f"ERROR: voice {voice!r} is not in the licence-cleared list "
            f"{sorted(VOICES)}. Add it (with its MODEL_CARD licence verified) "
            "to VOICES first — never ship an unverified voice licence.",
            file=sys.stderr,
        )
        return 2
    lang_dir, speaker, quality, licence = VOICES[voice]
    target.mkdir(parents=True, exist_ok=True)

    onnx = target / f"{voice}.onnx"
    cfg = target / f"{voice}.onnx.json"
    card = target / f"{voice}.MODEL_CARD"
    base = f"{_BASE}/{lang_dir}/{speaker}/{quality}"

    # Idempotent: skip the big model download only if the present file also
    # passes integrity verification (a stale/corrupt file is re-fetched).
    if onnx.exists() and _sha256(onnx) == SHA256[onnx.name]:
        print(f"  {onnx.name} already present and verified ({onnx.stat().st_size} bytes) — skipping model.")
    else:
        print(f"  downloading {voice}.onnx ...")
        onnx.write_bytes(_get(f"{base}/{voice}.onnx"))
        verify_sha256(onnx, SHA256[onnx.name])
        print(f"    -> {onnx} ({onnx.stat().st_size} bytes, sha256 verified)")
    cfg.write_bytes(_get(f"{base}/{voice}.onnx.json"))
    verify_sha256(cfg, SHA256[cfg.name])
    print(f"    -> {cfg}")
    try:
        card.write_bytes(_get(f"{base}/MODEL_CARD"))
        verify_sha256(card, SHA256[card.name])
        print(f"    -> {card}")
    except Exception as exc:  # the card is attribution-nice-to-have, not fatal
        card.unlink(missing_ok=True)
        print(f"    (MODEL_CARD not fetched: {exc})")

    (target / "ATTRIBUTION.txt").write_text(
        f"Piper voice: {voice} ({licence}).\n"
        f"Source: {base}/{voice}.onnx\n"
        "Trained on the Edinburgh datashare corpus "
        "(https://datashare.ed.ac.uk/handle/10283/3270).\n"
        "Used under CC BY 4.0 — attribution required. See the MODEL_CARD beside "
        "this file and docs/DEPENDENCY_LICENSING.md.\n"
    )
    print(f"\nDone. Piper will auto-discover {onnx.name} in {target}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
