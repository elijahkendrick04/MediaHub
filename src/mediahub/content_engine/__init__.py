"""content_engine — MediaHub's strategy brain + content generation engine.

Two layers:

* **The cross-source planner (P1.3)** — ``build_content_plan`` fuses the
  three signal sources (own / external / direct, ``signals.py``) into a
  ranked, explainable content plan keyed by a sport profile. Deterministic
  scoring (the swim newsworthiness ranker's pattern, generalised); every
  item carries reasons grounded in the signals that produced them. Operator
  inputs (upcoming events, structured goals, blackout dates) live in
  ``inputs.py``; ``nl_inputs.py`` lets the operator *describe* those in plain
  language (with optional web research) and turns the note into the same
  structured inputs for review — the AI proposes, the deterministic planner
  still ranks.
* **Generation** — every content type produces its draft cards through
  ``generate_content``: an AI Director plans the set (platform mix, angle,
  hook) while avoiding anything the user has already seen, then the writer
  turns that plan into platform-ready caption cards. This is the one engine
  the caption stubs and the meet-recap content tools route through.

The planner recommends; humans approve; generation drafts. A human always
approves before any content leaves the system.
"""

from .calendar import (
    CalendarEntry,
    CalendarModel,
    build_calendar,
    month_matrix,
)
from .director import plan_content_directions
from .engine import generate_caption, generate_content, load_brand_context
from .inputs import load_planner_inputs, save_planner_inputs
from .key_dates import KeyDate, key_dates_in_range, load_key_date_pack
from .nl_inputs import interpret_planner_inputs
from .planner import (
    ContentPlan,
    PlanItem,
    build_content_plan,
    load_latest_plan,
    save_plan,
)
from .signals import Signal, gather_all_signals

__all__ = [
    "CalendarEntry",
    "CalendarModel",
    "ContentPlan",
    "KeyDate",
    "PlanItem",
    "Signal",
    "build_calendar",
    "build_content_plan",
    "gather_all_signals",
    "generate_caption",
    "generate_content",
    "interpret_planner_inputs",
    "key_dates_in_range",
    "load_brand_context",
    "load_key_date_pack",
    "load_latest_plan",
    "load_planner_inputs",
    "month_matrix",
    "plan_content_directions",
    "save_plan",
    "save_planner_inputs",
]
