"""
recap_progress.py — map a meet-recap run's raw progress log to a customer-facing
percentage + plain-English phase label.

The pipeline (``pipeline.pipeline_v4``) emits terse, engineer-facing ``step()``
lines — "Looking up personal bests 3/10: NAME", "PB lookup error for NAME: …".
Operators (the signed-in developer) see those verbatim on the progress page; a
customer should instead see a clean progress bar and a human sentence about what
the engine is doing — never the raw steps or internal error text.

This module is the single, deterministic mapping from ``(progress_log, status)``
to ``(percent, phase)``. It is pure (no I/O, no request/session context) so it
can be unit-tested in isolation and reused by every poll on
``/api/runs/<id>/status``.

The percentage is monotonic (the log only ever grows) and capped below 100 until
the run actually finishes, so the customer's bar never rushes to "done" and then
sits there.
"""

from __future__ import annotations

import re
from typing import Iterable, Tuple

# Ordered phases: (key, friendly label, percent reached when the phase begins).
# A run advances monotonically through these; the bar shows the begin-percent of
# the furthest phase reached, with the personal-best phase interpolated across
# its band by the swimmer count parsed from its step lines.
_PHASES = [
    ("start", "Getting started", 4),
    ("read", "Reading your results file", 10),
    ("match", "Matching your swimmers", 28),
    ("pbs", "Researching personal bests", 32),  # band 32 → _PB_END
    ("recognise", "Finding the standout moments", 70),
    ("design", "Designing your content", 90),
]

_PB_BEGIN = 32
_PB_END = 66
_RUNNING_CAP = 96  # never show 100% until status == "done"

_PHASE_ORDER = {key: i for i, (key, _label, _pct) in enumerate(_PHASES)}
_PHASE_PCT = {key: pct for key, _label, pct in _PHASES}
_PHASE_LABEL = {key: label for key, label, _pct in _PHASES}

# Substring (lowercased) → phase key, ordered HIGHEST phase first so a line that
# could read as two phases (e.g. "V3 stubs synthesised from 4 V5 achievements")
# maps to the furthest one it implies. Matched against each real pipeline_v4
# step string; the furthest phase reached across all lines sets the bar.
_MARKERS = [
    # design (latest)
    ("v3 stubs", "design"),
    ("child-policy", "design"),
    ("child policy", "design"),
    ("designing", "design"),
    ("caption", "design"),
    ("content pack", "design"),
    ("rendering", "design"),
    # recognise
    ("pb audit", "recognise"),
    ("recognis", "recognise"),  # "recognising", "recognition"
    ("achievement", "recognise"),
    ("meet identity", "recognise"),
    # personal bests
    ("personal best", "pbs"),
    ("pb lookup", "pbs"),
    ("pb discovery", "pbs"),
    # match
    ("filtered to", "match"),
    # read (earliest)
    ("interpreting", "read"),
    ("bridging", "read"),
    ("interpreter parsed", "read"),
    ("inferred missing", "read"),
    ("parsing", "read"),
]

# Fraction parsers for the personal-best phase, in priority order.
_PB_FRACTION_RES = [
    re.compile(r"(\d+)\s*/\s*(\d+)\s+done", re.I),  # "(3/10 done)"
    re.compile(r"personal bests\s+(\d+)\s*/\s*(\d+)", re.I),  # "personal bests 3/10:"
]


def _pb_fraction(line: str) -> float | None:
    for rx in _PB_FRACTION_RES:
        m = rx.search(line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                return max(0.0, min(1.0, done / total))
    return None


def _phase_for_line(low: str) -> str | None:
    for needle, key in _MARKERS:
        if needle in low:
            return key
    return None


def recap_progress(progress_log: Iterable[str] | None, status: str | None) -> Tuple[int, str]:
    """Return ``(percent, phase)`` for a customer-facing progress view.

    ``percent`` is monotonic and capped below 100 until ``status == 'done'``.
    ``phase`` is a friendly description of the current stage. Neither value ever
    contains raw step text or internal error detail.
    """
    status_l = (status or "").lower()
    if status_l == "done":
        return 100, "Ready"

    log = [str(x) for x in (progress_log or [])]

    furthest_key = "start"
    furthest_i = 0
    pb_fraction = 0.0
    for line in log:
        key = _phase_for_line(line.lower())
        if key is None:
            continue
        i = _PHASE_ORDER[key]
        if i > furthest_i:
            furthest_i, furthest_key = i, key
        if key == "pbs":
            fr = _pb_fraction(line)
            if fr is not None and fr > pb_fraction:
                pb_fraction = fr

    if furthest_key == "pbs":
        pct = int(round(_PB_BEGIN + pb_fraction * (_PB_END - _PB_BEGIN)))
    else:
        pct = _PHASE_PCT[furthest_key]

    pct = max(4, min(_RUNNING_CAP, pct))
    return pct, _PHASE_LABEL[furthest_key]
