"""Phase 1.6 Stage I — shared snapshot helpers.

Used by both ``test_golden_snapshots.py`` (read + compare) and
``scripts/update_theme_snapshots.py`` (regenerate + write).

Two responsibilities:
  1. ``build_snapshot(theme_json)`` — take a full DerivedTheme.to_json()
     and reduce it to the compact ~1KB shape stored on disk.
  2. ``load_snapshot(seed_hex)`` — read the JSON for a seed.

The snapshot shape is documented in
``docs/stage_i_test_coverage_plan.md`` §4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .seeds_catalogue import snapshot_filename_for


SNAPSHOTS_DIR: Path = Path(__file__).resolve().parent / "snapshots"


def build_snapshot(theme_json: dict, *, label: str = "") -> dict:
    """Reduce a full DerivedTheme.to_json() dict to the compact
    snapshot shape.

    Captures the headline values per docs/stage_i §4:
      - seed (hex + hct + source)
      - schema_version + was_repaired
      - harmonic_fit
      - palette anchor hues (one per ramp)
      - 4 key role tokens per scheme (light/dark × primary,
        on_primary, surface, on_surface)
      - quality summary counts
    """
    palettes = theme_json.get("palettes") or {}
    roles_light = (theme_json.get("roles") or {}).get("light") or {}
    roles_dark = (theme_json.get("roles") or {}).get("dark") or {}
    quality = theme_json.get("quality") or {}
    harmonic = theme_json.get("harmonic_fit") or {}

    def _hue(ramp_name: str):
        ramp = palettes.get(ramp_name) or {}
        h = ramp.get("hue")
        return round(float(h), 1) if isinstance(h, (int, float)) else None

    def _tone(ramp_name: str, tone_key: str):
        """MD3 tone stops are 0..100; tone 40 is the canonical
        light-scheme primary."""
        ramp = palettes.get(ramp_name) or {}
        tones = ramp.get("tones") or {}
        return tones.get(tone_key)

    snap = {
        "seed_hex": theme_json.get("seed_hex", ""),
        "label": label,
        "seed_hct": _round_list(theme_json.get("seed_hct", []), 1),
        "seed_source": theme_json.get("seed_source", ""),
        "schema_version": theme_json.get("schema_version", ""),
        "was_repaired": bool(theme_json.get("was_repaired", False)),
        "harmonic_fit": {
            "template": harmonic.get("template"),
            "rotation": _round(harmonic.get("rotation"), 1),
            "energy": _round(harmonic.get("energy"), 2),
            "hue_count": harmonic.get("hue_count"),
        } if harmonic else None,
        "palette_anchors": {
            # Tone 40 is the canonical light-scheme primary tone for
            # each MD3 ramp. The dark-scheme tone (80) lives in
            # roles_dark.primary already.
            "primary_tone40":       _tone("primary", "40"),
            "primary_hue":          _hue("primary"),
            "secondary_hue":        _hue("secondary"),
            "tertiary_hue":         _hue("tertiary"),
            "neutral_hue":          _hue("neutral"),
            "error_hue":            _hue("error"),
            "success_hue":          _hue("success"),
            "warning_hue":          _hue("warning"),
            "info_hue":             _hue("info"),
        },
        "roles_light": {
            "primary":     roles_light.get("primary"),
            "on_primary":  roles_light.get("on_primary"),
            "surface":     roles_light.get("surface"),
            "on_surface":  roles_light.get("on_surface"),
        },
        "roles_dark": {
            "primary":     roles_dark.get("primary"),
            "on_primary":  roles_dark.get("on_primary"),
            "surface":     roles_dark.get("surface"),
            "on_surface":  roles_dark.get("on_surface"),
        },
        "quality_summary": {
            "passed":                    quality.get("passed"),
            "n_contrast_failures":       quality.get("n_contrast_failures"),
            "n_adjacency_failures":      quality.get("n_adjacency_failures"),
            "n_status_distance_failures":quality.get("n_status_distance_failures"),
            "n_cvd_failures":            quality.get("n_cvd_failures"),
        },
    }
    return snap


def load_snapshot(seed_hex: str) -> Optional[dict]:
    """Read a seed's snapshot JSON or return None if missing."""
    path = SNAPSHOTS_DIR / snapshot_filename_for(seed_hex)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_snapshot(seed_hex: str, snapshot: dict) -> Path:
    """Write a snapshot atomically (tmp + rename)."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / snapshot_filename_for(seed_hex)
    # JSON dumped sorted for stable PR diffs.
    text = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def diff_snapshots(expected: dict, actual: dict, *, path: str = "") -> list[str]:
    """Walk two snapshot dicts and return a list of human-readable
    diffs (`<path>: snapshot=<x>, actual=<y>`).

    Used by the test failure message to point at the exact key
    that changed."""
    diffs: list[str] = []
    keys = set(expected) | set(actual)
    for k in sorted(keys):
        sub_path = f"{path}.{k}" if path else k
        e = expected.get(k)
        a = actual.get(k)
        if isinstance(e, dict) and isinstance(a, dict):
            diffs.extend(diff_snapshots(e, a, path=sub_path))
        elif e != a:
            diffs.append(f"  {sub_path}: snapshot={e!r}, actual={a!r}")
    return diffs


def _round(value, ndigits: int):
    if isinstance(value, (int, float)):
        return round(float(value), ndigits)
    return value


def _round_list(values, ndigits: int):
    out = []
    for v in values or []:
        out.append(_round(v, ndigits))
    return out
