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

import os
import ssl
import sys
import urllib.request
from pathlib import Path

# rhasspy/piper-voices layout: en/en_GB/alba/medium/en_GB-alba-medium.onnx[.json]
_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# voice key -> (lang_dir, speaker, quality, licence note). Only licence-clean,
# commercially-usable voices belong here.
VOICES: dict[str, tuple[str, str, str, str]] = {
    "en_GB-alba-medium": ("en/en_GB", "alba", "medium", "CC BY 4.0"),
}

DEFAULT_VOICE = "en_GB-alba-medium"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120, context=_ctx) as r:
        return r.read()


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

    # Idempotent: skip the big model download if it is already present.
    if onnx.exists() and onnx.stat().st_size > 0:
        print(f"  {onnx.name} already present ({onnx.stat().st_size} bytes) — skipping model.")
    else:
        print(f"  downloading {voice}.onnx ...")
        onnx.write_bytes(_get(f"{base}/{voice}.onnx"))
        print(f"    -> {onnx} ({onnx.stat().st_size} bytes)")
    cfg.write_bytes(_get(f"{base}/{voice}.onnx.json"))
    print(f"    -> {cfg}")
    try:
        card.write_bytes(_get(f"{base}/MODEL_CARD"))
        print(f"    -> {card}")
    except Exception as exc:  # the card is attribution-nice-to-have, not fatal
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
