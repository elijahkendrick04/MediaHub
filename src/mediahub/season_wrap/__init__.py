"""mediahub.season_wrap — season wraps and monthly recap packs (W.8).

In plain words: this package looks back over everything a club already
did — every saved meet in a month or a season — and adds it up into one
shareable story: how many PBs, how many medals, who raced the most, who
improved the most. It then shapes that into a draft pack a human reviews
and approves; nothing is posted from here, and no AI is involved — it is
deterministic counting over stored results.

Pieces:

* ``aggregate``  — :func:`aggregate_window` + :class:`WrapStats`, the maths.
* ``drafts``     — monthly / season draft builders + DATA_DIR persistence.
* ``task``       — the monthly scheduler handler and its register function.
"""

from mediahub.season_wrap.aggregate import WrapStats, aggregate_window
from mediahub.season_wrap.drafts import (
    build_monthly_draft,
    build_season_draft,
    list_drafts,
    load_draft,
    save_draft,
)
from mediahub.season_wrap.task import (
    TASK_TYPE,
    monthly_wrap_task_handler,
    register_season_wrap_task,
)

__all__ = [
    "WrapStats",
    "aggregate_window",
    "build_monthly_draft",
    "build_season_draft",
    "save_draft",
    "list_drafts",
    "load_draft",
    "TASK_TYPE",
    "monthly_wrap_task_handler",
    "register_season_wrap_task",
]
