#!/usr/bin/env python3
"""Synthesise MediaHub's bundled, licence-clean audio pool (roadmap 1.8).

Every asset here is generated from scratch with FFmpeg's signal generators
(sines, shaped noise) — no sample is taken from anyone else — so the whole pool
is genuinely first-party and dedicated to the public domain (**CC0-1.0**). That
is what lets ``audio/library.py`` ship sound a club can use anywhere without a
rights worry.

Run from the repo root to (re)generate ``src/mediahub/audio/assets/`` and its
``manifest.json``:

    python scripts/make_audio_assets.py

It is deterministic: fixed frequencies and fixed noise seeds mean the same bytes
every time, so the committed assets are reproducible. Idempotent: it clears and
rewrites the generated files.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "audio" / "assets"

_CC0 = {
    "name": "CC0 1.0",
    "spdx": "CC0-1.0",
    "url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "attribution": "",
    "source": "MediaHub first-party (synthesised, scripts/make_audio_assets.py)",
    "commercial_ok": True,
}
_ALL_PLATFORMS = ["instagram", "tiktok", "youtube", "facebook", "linkedin", "x"]

# Each spec: id, dir, name, kind, lavfi source, filter chain, duration, mood,
# energy, bpm, tags, title. The lavfi 'src' is the input after `-f lavfi -i`.
_SPECS: list[dict] = [
    # ---- Sound effects -----------------------------------------------------
    {
        "id": "sfx_whistle", "dir": "sfx", "name": "whistle", "kind": "sfx",
        "src": "sine=frequency=3000:duration=0.4",
        "af": "vibrato=f=22:d=0.8,afade=t=in:st=0:d=0.02,afade=t=out:st=0.34:d=0.06,volume=0.85",
        "dur": 0.4, "mood": ["sharp", "attention"], "energy": 4, "bpm": None,
        "tags": ["whistle", "referee", "start", "sport"], "title": "Referee Whistle",
    },
    {
        "id": "sfx_airhorn", "dir": "sfx", "name": "airhorn", "kind": "sfx",
        "src": "aevalsrc=0.3*sin(2*PI*230*t)+0.2*sin(2*PI*460*t)+0.15*sin(2*PI*690*t):d=0.7",
        "af": "tremolo=f=8:d=0.4,afade=t=in:st=0:d=0.02,afade=t=out:st=0.55:d=0.15",
        "dur": 0.7, "mood": ["celebratory", "loud"], "energy": 5, "bpm": None,
        "tags": ["airhorn", "celebration", "win"], "title": "Air Horn",
    },
    {
        "id": "sfx_splash", "dir": "sfx", "name": "splash", "kind": "sfx",
        "src": "anoisesrc=color=white:seed=11:duration=0.6",
        "af": "highpass=f=600,afade=t=in:st=0:d=0.005,afade=t=out:st=0.12:d=0.45,volume=1.2",
        "dur": 0.6, "mood": ["splashy", "playful"], "energy": 3, "bpm": None,
        "tags": ["splash", "water", "pool", "swim"], "title": "Water Splash",
    },
    {
        "id": "sfx_swoosh", "dir": "sfx", "name": "swoosh", "kind": "sfx",
        "src": "anoisesrc=color=white:seed=22:duration=0.5",
        "af": "bandpass=f=1200:width_type=h:w=1500,afade=t=in:st=0:d=0.2,afade=t=out:st=0.25:d=0.25",
        "dur": 0.5, "mood": ["transition", "smooth"], "energy": 2, "bpm": None,
        "tags": ["swoosh", "transition", "whoosh"], "title": "Swoosh",
    },
    {
        "id": "sfx_chime", "dir": "sfx", "name": "chime", "kind": "sfx",
        "src": "aevalsrc=0.4*sin(2*PI*880*t)+0.25*sin(2*PI*1760*t)+0.12*sin(2*PI*2640*t):d=0.9",
        "af": "volume=exp(-4*t):eval=frame,afade=t=in:st=0:d=0.005",
        "dur": 0.9, "mood": ["bright", "positive"], "energy": 2, "bpm": None,
        "tags": ["chime", "bell", "ping", "notify"], "title": "Bright Chime",
    },
    {
        "id": "sfx_crowd", "dir": "sfx", "name": "crowd", "kind": "sfx",
        "src": "anoisesrc=color=pink:seed=7:duration=1.6",
        "af": "highpass=f=200,lowpass=f=3000,afade=t=in:st=0:d=0.4,afade=t=out:st=1.2:d=0.4,volume=0.9",
        "dur": 1.6, "mood": ["energetic", "crowd"], "energy": 4, "bpm": None,
        "tags": ["crowd", "cheer", "applause", "ambience"], "title": "Crowd Wash",
    },
    # ---- Branded idents (short stings) -------------------------------------
    {
        "id": "ident_bright", "dir": "sfx", "name": "ident_bright", "kind": "ident",
        "src": "aevalsrc=0.22*sin(2*PI*523.25*t)+0.22*sin(2*PI*659.25*t)+0.22*sin(2*PI*783.99*t):d=1.0",
        "af": "afade=t=in:st=0:d=0.08,afade=t=out:st=0.7:d=0.3",
        "dur": 1.0, "mood": ["bright", "uplifting"], "energy": 4, "bpm": None,
        "tags": ["ident", "sting", "logo", "intro"], "title": "Bright Ident",
    },
    {
        "id": "ident_warm", "dir": "sfx", "name": "ident_warm", "kind": "ident",
        "src": "aevalsrc=0.22*sin(2*PI*392.00*t)+0.22*sin(2*PI*493.88*t)+0.22*sin(2*PI*587.33*t):d=1.0",
        "af": "afade=t=in:st=0:d=0.2,afade=t=out:st=0.6:d=0.4",
        "dur": 1.0, "mood": ["warm", "resolved"], "energy": 2, "bpm": None,
        "tags": ["ident", "sting", "logo", "outro"], "title": "Warm Ident",
    },
    # ---- Simple ambient music beds (loopable) -----------------------------
    {
        "id": "bed_uplift", "dir": "music", "name": "bed_uplift", "kind": "music",
        "src": "aevalsrc=0.18*sin(2*PI*261.63*t)+0.18*sin(2*PI*329.63*t)+0.18*sin(2*PI*392.00*t):d=8",
        "af": "tremolo=f=0.5:d=0.3,afade=t=in:st=0:d=0.5,afade=t=out:st=7.4:d=0.6",
        "dur": 8.0, "mood": ["uplifting", "warm", "hopeful"], "energy": 3, "bpm": None,
        "tags": ["bed", "pad", "uplifting", "highlights"], "title": "Uplift Pad",
    },
    {
        "id": "bed_drive", "dir": "music", "name": "bed_drive", "kind": "music",
        "src": "aevalsrc=0.16*sin(2*PI*293.66*t)+0.16*sin(2*PI*440.00*t)+0.16*sin(2*PI*587.33*t):d=8",
        "af": "tremolo=f=2:d=0.6,afade=t=in:st=0:d=0.4,afade=t=out:st=7.4:d=0.6",
        "dur": 8.0, "mood": ["energetic", "driving", "triumphant"], "energy": 4, "bpm": 120,
        "tags": ["bed", "pad", "energetic", "drive"], "title": "Drive Pad",
    },
    {
        "id": "bed_calm", "dir": "music", "name": "bed_calm", "kind": "music",
        "src": "aevalsrc=0.18*sin(2*PI*130.81*t)+0.18*sin(2*PI*164.81*t)+0.18*sin(2*PI*196.00*t):d=8",
        "af": "tremolo=f=0.25:d=0.2,afade=t=in:st=0:d=0.8,afade=t=out:st=7.0:d=1.0",
        "dur": 8.0, "mood": ["calm", "reflective", "gentle"], "energy": 1, "bpm": None,
        "tags": ["bed", "pad", "calm", "reflective"], "title": "Calm Pad",
    },
]


def _ffmpeg() -> str:
    import os

    explicit = os.environ.get("MEDIAHUB_FFMPEG", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    sys.exit("No FFmpeg binary found (set MEDIAHUB_FFMPEG, install ffmpeg, or pip install imageio-ffmpeg).")


def _pick_format(exe: str) -> tuple[str, list[str]]:
    """Choose the best available compressed format from this FFmpeg build."""
    try:
        enc = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except Exception:
        enc = ""
    for name, suffix, args in (
        ("libvorbis", ".ogg", ["-c:a", "libvorbis", "-q:a", "4"]),
        ("libopus", ".opus", ["-c:a", "libopus", "-b:a", "96k"]),
        ("libmp3lame", ".mp3", ["-c:a", "libmp3lame", "-b:a", "160k"]),
    ):
        if name in enc:
            return suffix, args
    # Last resort: uncompressed WAV (always available).
    return ".wav", ["-c:a", "pcm_s16le"]


def main() -> None:
    exe = _ffmpeg()
    suffix, codec = _pick_format(exe)
    print(f"FFmpeg: {exe}\nFormat: {suffix} ({' '.join(codec)})")

    # Clean previously generated audio (keep the dir structure).
    for sub in ("sfx", "music"):
        d = ASSETS / sub
        if d.is_dir():
            for f in d.iterdir():
                if f.suffix.lower() in {".ogg", ".opus", ".mp3", ".wav", ".flac"}:
                    f.unlink()
        d.mkdir(parents=True, exist_ok=True)

    tracks: list[dict] = []
    for spec in _SPECS:
        rel = f"{spec['dir']}/{spec['name']}{suffix}"
        out = ASSETS / rel
        cmd = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", spec["src"],
            "-af", spec["af"],
            "-ac", "1", "-ar", "44100",
            *codec, str(out),
        ]
        subprocess.run(cmd, check=True)
        size = out.stat().st_size
        print(f"  {rel:28s} {size:>7d} bytes")
        tracks.append({
            "id": spec["id"],
            "file": rel,
            "title": spec["title"],
            "kind": spec["kind"],
            "mood": spec["mood"],
            "energy": spec["energy"],
            "bpm": spec["bpm"],
            "duration_sec": spec["dur"],
            "tags": spec["tags"],
            "licence": _CC0,
            "platforms": _ALL_PLATFORMS,
        })

    manifest = {
        "version": 1,
        "generator": "scripts/make_audio_assets.py",
        "note": "First-party, synthesised, CC0-1.0. Regenerate with the generator script.",
        "tracks": tracks,
    }
    (ASSETS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {ASSETS / 'manifest.json'} ({len(tracks)} tracks).")


if __name__ == "__main__":
    main()
