"""Finals-round detection from SportSystems event headers.

British finals are encoded in the event header: "EVENT 132 B FINAL OF EVENT 101
…" is the B-final, "EVENT 131 FINAL OF EVENT 101 …" the A/main final; heats
carry no FINAL token. The round is surfaced on each result (extra.final_label /
final_rank) so a B-final result can't be read as the A-final win, and so the
A-final (rank 1) can be prioritised above the B-final (rank 2) for posting.
"""

from __future__ import annotations

import pytest

from mediahub.pipeline.interpreter_bridge import _detect_final_round


@pytest.mark.parametrize(
    "header,label,rank",
    [
        ("EVENT 131 FINAL OF EVENT 101 Women's Junior 50m Breaststroke", "A Final", 1),
        ("EVENT 132 B FINAL OF EVENT 101 Women's 50m Breaststroke", "B Final", 2),
        ("EVENT 141 B FINAL OF EVENT 105 Women's MC 100m Freestyle", "B Final", 2),
        ("EVENT 152 FINAL OF EVENT 102 Men's 400m Freestyle", "A Final", 1),
        # Heats / preliminary "Full Results" — no explicit final round.
        ("EVENT 101 Women's 50m Breaststroke", "", 0),
        ("EVENT 102 Men's 400m Freestyle", "", 0),
        ("", "", 0),
    ],
)
def test_detect_final_round(header: str, label: str, rank: int) -> None:
    assert _detect_final_round(header) == (label, rank)


def test_a_final_outranks_b_final() -> None:
    _, a = _detect_final_round("EVENT 131 FINAL OF EVENT 101 Women's 50m Breaststroke")
    _, b = _detect_final_round("EVENT 132 B FINAL OF EVENT 101 Women's 50m Breaststroke")
    assert a < b  # lower rank number = higher posting priority
