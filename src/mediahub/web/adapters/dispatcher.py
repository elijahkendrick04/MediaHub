"""
Adapter dispatcher.

Given a raw uploaded file (path or bytes), pick the best adapter
according to each adapter's can_parse() confidence and run it. Handles
.zip auto-pick: searches inside the zip for a file each adapter scores
highly.

Returns (Meet, dispatch_log) where dispatch_log captures which files
were considered and which adapter won, for audit.
"""

from __future__ import annotations
import io
import os
import zipfile
from dataclasses import dataclass, field
from typing import Optional

from ..canonical import Meet
from .hy3 import HY3Adapter

# V7.4: SPORTSYSTEMS PDF adapter
try:
    from engine_v4.adapters.sportsystems_pdf import (
        SportSystemsPDFAdapter as _SportSystemsPDFAdapter,
    )

    _pdf_adapter_available = True
except ImportError:
    _pdf_adapter_available = False
    _SportSystemsPDFAdapter = None


# Adapter registry. Order matters only for ties.
ADAPTERS = [
    HY3Adapter(),
]
if _pdf_adapter_available and _SportSystemsPDFAdapter is not None:
    ADAPTERS.append(_SportSystemsPDFAdapter())


@dataclass
class DispatchLog:
    chosen_adapter: Optional[str] = None
    chosen_filename: Optional[str] = None
    chosen_score: float = 0.0
    candidates: list[dict] = field(default_factory=list)  # [{adapter, filename, score}]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chosen_adapter": self.chosen_adapter,
            "chosen_filename": self.chosen_filename,
            "chosen_score": self.chosen_score,
            "candidates": list(self.candidates),
            "notes": list(self.notes),
        }


def _score_all(file_bytes: bytes, filename: str) -> list[tuple[float, object, str]]:
    out = []
    for ad in ADAPTERS:
        try:
            score = ad.can_parse(file_bytes, filename)
        except Exception:
            score = 0.0
        out.append((score, ad, filename))
    return out


def dispatch(file_bytes: bytes, filename: str) -> tuple[Meet, DispatchLog]:
    log = DispatchLog()

    # Zip handling: examine each entry, pick the single best (adapter, entry).
    is_zip = filename.lower().endswith(".zip") or file_bytes[:2] == b"PK"
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                best = (0.0, None, None, None)  # score, adapter, inner_name, inner_bytes
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    try:
                        inner = zf.read(name)
                    except Exception:
                        continue
                    inner_base = os.path.basename(name)
                    for score, ad, _ in _score_all(inner, inner_base):
                        log.candidates.append(
                            {
                                "adapter": ad.format_id,
                                "filename": inner_base,
                                "score": round(score, 3),
                            }
                        )
                        if score > best[0]:
                            best = (score, ad, inner_base, inner)
                if best[1] is None:
                    meet = Meet(source_format="unknown", source_filename=filename)
                    meet.add_warning(
                        "no_adapter",
                        "No adapter could parse any file inside the zip. "
                        "Supported formats: .hy3 (Hytek Meet Manager), .pdf (SPORTSYSTEMS).",
                        severity="error",
                    )
                    log.notes.append("Zip contained no parseable files.")
                    return meet, log

                log.chosen_adapter = best[1].format_id
                log.chosen_filename = best[2]
                log.chosen_score = round(best[0], 3)
                log.notes.append(
                    f"Picked '{best[2]}' inside zip via {best[1].format_id} (score {best[0]:.2f})."
                )
                meet = best[1].parse(best[3], best[2])
                meet.source_filename = f"{filename} :: {best[2]}"
                return meet, log
        except zipfile.BadZipFile:
            log.notes.append("File looked like a zip but could not be opened.")
            # Fall through to direct dispatch

    # Direct dispatch (non-zip or zip-open failure).
    scored = _score_all(file_bytes, filename)
    for score, ad, fn in scored:
        log.candidates.append(
            {
                "adapter": ad.format_id,
                "filename": fn,
                "score": round(score, 3),
            }
        )
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_adapter, best_fn = scored[0]
    if best_score <= 0.0:
        meet = Meet(source_format="unknown", source_filename=filename)
        meet.add_warning(
            "no_adapter",
            f"No adapter recognised '{filename}'. Supported formats: .hy3 "
            "(Hytek Meet Manager), .pdf (SPORTSYSTEMS). For other formats, please contact us.",
            severity="error",
        )
        return meet, log

    log.chosen_adapter = best_adapter.format_id
    log.chosen_filename = filename
    log.chosen_score = round(best_score, 3)
    return best_adapter.parse(file_bytes, filename), log
