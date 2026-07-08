"""tests/test_plan_generate_saves_inputs.py — "Generate plan" persists the
on-page inputs before generating (audit finding H-7).

mhPlanGenerate posted only {sport} and reloaded on success, and Generate builds
the plan from the PERSISTED inputs — so any event/goal/blackout the volunteer
just typed (or added via "Interpret & fill in", which only creates DOM rows)
was silently wiped and never reached the plan. The fix auto-saves the current
inputs first.

Client JS with no unit harness, so this guards the source: mhPlanGenerate must
POST to the plan-inputs endpoint before it POSTs to the plan-generate endpoint.
"""
from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"


def _generate_fn_body(src: str) -> str:
    start = src.index("function mhPlanGenerate(")
    end = src.index("\nfunction ", start + 1) if "\nfunction " in src[start + 1:] else src.index("</script>", start)
    return src[start:end]


def test_generate_saves_inputs_before_generating():
    src = _WEB.read_text(encoding="utf-8")
    body = _generate_fn_body(src)
    # Both endpoints are referenced inside the function...
    assert "api_plan_inputs" in body, "generate must save inputs first (H-7)"
    assert "api_plan_generate" in body
    # ...and the save comes BEFORE the generate call.
    assert body.index("api_plan_inputs") < body.index("api_plan_generate"), (
        "inputs must be saved before generation, or typed rows are lost"
    )
    # It collects the live events + goals for that save.
    assert "mhPlanCollectEvents()" in body
    assert "mhPlanCollectGoals()" in body
