"""mediahub/log_sentinel — production log watchdog with bounded auto-fix.

Polls the deployment's own Render logs through the Render API, runs
deterministic pattern detectors over every new line, notifies the operator
(ntfy / webhook via ``mediahub.notify``), and — only for explicitly opted-in
issues, behind a kill switch, rate caps and cooldowns — applies the playbook's
remediation (v1: a service restart). Every finding, decision and action lands
in an append-only audit ledger under ``DATA_DIR/log_sentinel/``.

Inert without ``RENDER_API_KEY`` + ``RENDER_SERVICE_ID``. See
``docs/LOG_SENTINEL.md`` for setup and the full guardrail model.
"""

from mediahub.log_sentinel.sentinel import Sentinel, start_sentinel, stop_sentinel

__all__ = ["Sentinel", "start_sentinel", "stop_sentinel"]
