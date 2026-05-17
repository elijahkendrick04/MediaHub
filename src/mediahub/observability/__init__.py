"""mediahub.observability — uptime + LLM usage stores.

The two submodules underpin Phase 1.5's reliability surface:

* ``uptime`` — every /healthz and /health hit is a heartbeat row in
  SQLite. The public ``/status`` page reads this to show a real,
  honest uptime number without depending on a third-party monitor.
* ``llm_usage`` — every Gemini / Anthropic call records one row with
  the provider, success flag, and a coarse token estimate. The
  operator-facing ``/healthz/usage`` dashboard reads this to show
  today's call count and a cost estimate against published pricing.

Both stores are bounded (retention sweep at 100k → 90k for uptime,
30k → 27k for llm_usage), share the same ``DATA_DIR/data.db`` as the
rest of the app, and degrade safely if the DB is unreachable.
"""

from . import uptime, llm_usage  # noqa: F401

__all__ = ["uptime", "llm_usage"]
