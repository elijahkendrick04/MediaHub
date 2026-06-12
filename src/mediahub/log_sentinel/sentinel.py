"""mediahub/log_sentinel/sentinel.py — the poll → detect → notify → act loop.

One cycle (:meth:`Sentinel.run_once`):

1. Pull new log lines from the Render API since the persisted cursor.
2. Run the deterministic detectors over the batch.
3. For every finding: write it to the audit ledger, notify the operator (per-issue
   cooldown so a noisy issue is one ping per window, not a flood), and evaluate
   the playbook gates. Only a fully-gated issue is auto-fixed, and the state/audit
   write happens BEFORE the action so a sentinel-triggered restart can never
   re-fire on the same evidence after boot.

Runs either in-process (``start_sentinel()`` — one daemon thread, leader-elected
across gunicorn workers via a heartbeat lockfile) or standalone
(``python -m mediahub.log_sentinel run``). Inert without RENDER_API_KEY +
RENDER_SERVICE_ID: it idles and says so in status, costing nothing.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import threading
import time
from typing import Optional

from mediahub.log_sentinel import detectors, playbook, render_api, state as st
from mediahub.log_sentinel.detectors import Finding

log = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

DEFAULT_INTERVAL = 60.0
FIRST_LOOKBACK = 900.0  # first ever poll looks 15 min back

# ntfy priority per severity (notify/channels.py passes it straight through).
_PRIORITY = {"info": "default", "warning": "high", "critical": "urgent"}


def _interval() -> float:
    raw = os.environ.get("MEDIAHUB_SENTINEL_INTERVAL", "").strip()
    try:
        return max(15.0, float(raw)) if raw else DEFAULT_INTERVAL
    except ValueError:
        return DEFAULT_INTERVAL


def _enabled() -> bool:
    return os.environ.get("MEDIAHUB_SENTINEL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _public_base_url() -> str:
    return os.environ.get("MEDIAHUB_PUBLIC_BASE_URL", "").strip().rstrip("/")


def _ai_triage(finding: Finding) -> Optional[str]:
    """Optional one-paragraph traceback summary via the configured provider.

    Advisory text for the notification only — it never influences detection or
    gating. Honest absence: returns None when no provider is configured."""
    if finding.issue_id != "unhandled_traceback":
        return None
    try:
        from mediahub.ai_core import llm  # noqa: PLC0415

        return llm.ask(
            "You are helping a sports-club SaaS operator read a production log "
            "excerpt. In at most 3 plain sentences: what failed, the most likely "
            "cause, and where to look first. No speculation beyond the lines given.",
            "\n".join(finding.evidence)[:4000],
            max_tokens=250,
        ).strip()
    except Exception as e:
        log.debug("AI triage unavailable: %s", e)
        return None


class Sentinel:
    """One sentinel instance; ``data_dir`` overrides DATA_DIR (tests)."""

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir

    # -- notification ---------------------------------------------------------

    def _notify(self, finding: Finding, extra: str = "") -> bool:
        try:
            from mediahub.notify.channels import Notification, all_channels  # noqa: PLC0415
        except Exception:
            return False
        body_parts = [
            f"{finding.count}× in the last poll window.",
            "",
            finding.suggestion,
        ]
        if extra:
            body_parts += ["", extra]
        if finding.evidence:
            body_parts += ["", "Evidence:"] + [f"• {e[:300]}" for e in finding.evidence[:3]]
        n = Notification(
            title=f"MediaHub sentinel: {finding.title}",
            message="\n".join(body_parts)[:3500],
            priority=_PRIORITY.get(finding.severity, "default"),
            tags=("rotating_light",) if finding.severity == "critical" else ("mag",),
            click_url=(f"{_public_base_url()}/healthz" if _public_base_url() else None),
        )
        sent = False
        for ch in all_channels():
            if ch.configured():
                sent = ch.send(n) or sent
        return sent

    # -- one finding ----------------------------------------------------------

    def _handle(self, finding: Finding, state: dict) -> Optional[str]:
        """Audit + notify + gate-check one finding.

        Returns the action name to execute after state is persisted (actions are
        deferred to the end of the cycle), or None."""
        now = time.time()
        mem = st.issue_memory(state, finding.issue_id)
        st.append_audit(
            {
                "kind": "finding",
                "issue_id": finding.issue_id,
                "severity": finding.severity,
                "count": finding.count,
                "evidence": list(finding.evidence),
            },
            self._data_dir,
        )

        last_notified = float(mem.get("last_notified") or 0.0)
        if (now - last_notified) >= playbook.notify_cooldown():
            triage = _ai_triage(finding)
            sent = self._notify(finding, extra=f"AI triage: {triage}" if triage else "")
            st.remember_issue(state, finding.issue_id, last_notified=now)
            st.append_audit(
                {
                    "kind": "notify",
                    "issue_id": finding.issue_id,
                    "sent": sent,
                    "detail": "delivered" if sent else "no notify channel configured",
                },
                self._data_dir,
            )

        allowed, reason = playbook.action_decision(
            finding.issue_id,
            last_acted_epoch=float(mem.get("last_acted") or 0.0),
            actions_today=st.actions_today(state),
        )
        remediation = playbook.PLAYBOOK.get(finding.issue_id)
        if remediation is not None:
            st.append_audit(
                {
                    "kind": "action_decision",
                    "issue_id": finding.issue_id,
                    "allowed": allowed,
                    "reason": reason,
                },
                self._data_dir,
            )
        if not allowed:
            st.remember_issue(state, finding.issue_id, last_seen=now)
            return None
        # Claim the action in persisted state BEFORE executing it: a restart
        # kills this very process, and the reborn sentinel must see the caps.
        st.remember_issue(state, finding.issue_id, last_seen=now, last_acted=now)
        st.record_action(state)
        return remediation.action if remediation else None

    # -- actions ----------------------------------------------------------------

    def _execute(self, action: str, issue_id: str) -> None:
        st.append_audit(
            {"kind": "action_attempt", "issue_id": issue_id, "action": action},
            self._data_dir,
        )
        ok, detail = False, f"unknown action {action!r}"
        if action == "restart_service":
            try:
                render_api.restart_service()
                ok, detail = True, "Render service restart requested"
            except render_api.RenderApiUnavailable as e:
                ok, detail = False, str(e)
        st.append_audit(
            {
                "kind": "action_result",
                "issue_id": issue_id,
                "action": action,
                "ok": ok,
                "detail": detail,
            },
            self._data_dir,
        )
        log.warning(
            "sentinel action %s for %s: %s (%s)", action, issue_id, "ok" if ok else "FAILED", detail
        )
        self._notify(
            Finding(
                issue_id=issue_id,
                severity="info" if ok else "warning",
                title=f"auto-fix {'applied' if ok else 'FAILED'} for {issue_id}",
                suggestion=detail,
                count=1,
            )
        )

    # -- one full cycle ---------------------------------------------------------

    def run_once(self) -> dict:
        if not render_api.is_configured():
            summary = {
                "configured": False,
                "detail": "RENDER_API_KEY / RENDER_SERVICE_ID not set — sentinel idle",
            }
            st.write_status(summary, self._data_dir)
            return summary

        state = st.load_state(self._data_dir)
        cursor = float(state.get("cursor_epoch") or 0.0) or (time.time() - FIRST_LOOKBACK)
        try:
            lines, newest = render_api.fetch_log_lines(cursor)
        except render_api.RenderApiUnavailable as e:
            log.warning("sentinel poll failed: %s", e)
            summary = {"configured": True, "last_poll_ok": False, "detail": str(e)[:300]}
            st.write_status(summary, self._data_dir)
            return summary

        findings = detectors.detect(lines)
        pending: list[tuple[str, str]] = []
        for finding in findings:
            action = self._handle(finding, state)
            if action:
                pending.append((action, finding.issue_id))

        state["cursor_epoch"] = newest
        st.save_state(state, self._data_dir)
        summary = {
            "configured": True,
            "last_poll_ok": True,
            "cursor_epoch": newest,
            "lines_scanned": len(lines),
            "findings": [f.issue_id for f in findings],
            "actions_today": st.actions_today(state),
            "kill_switch": playbook.kill_switch_on(),
            "leader": WORKER_ID,
        }
        st.write_status(summary, self._data_dir)
        # Actions LAST: state + status are already on disk if a restart lands.
        for action, issue_id in pending:
            self._execute(action, issue_id)
        return summary

    # -- forever ------------------------------------------------------------------

    def run_forever(self, interval: Optional[float] = None, stop: Optional[threading.Event] = None):
        tick = interval or _interval()
        stop = stop or threading.Event()
        atexit.register(st.release_leader, WORKER_ID, self._data_dir)
        while not stop.is_set():
            try:
                if st.acquire_leader(WORKER_ID, ttl=tick * 3, data_dir=self._data_dir):
                    self.run_once()
            except Exception as e:  # the loop must never die
                log.warning("sentinel tick error: %s", e)
            stop.wait(tick)


_started = False
_start_lock = threading.Lock()
_stop = threading.Event()


def start_sentinel(data_dir: Optional[str] = None) -> bool:
    """Start the in-process sentinel thread once (idempotent).

    No-ops (returning False) when disabled via MEDIAHUB_SENTINEL=0, when the
    Render API isn't configured, or during pytest."""
    global _started
    if not _enabled() or _started:
        return False
    import sys  # noqa: PLC0415

    if "pytest" in sys.modules:
        return False
    if not render_api.is_configured():
        log.info("log sentinel idle: RENDER_API_KEY / RENDER_SERVICE_ID not set")
        try:
            st.write_status(
                {"configured": False, "detail": "RENDER_API_KEY / RENDER_SERVICE_ID not set"},
                data_dir,
            )
        except Exception:
            pass
        return False
    with _start_lock:
        if _started:
            return False
        threading.Thread(
            target=Sentinel(data_dir).run_forever,
            kwargs={"stop": _stop},
            daemon=True,
            name="log-sentinel",
        ).start()
        _started = True
        log.info("log sentinel started (interval %ss)", int(_interval()))
        return True


def stop_sentinel() -> None:
    """Signal the loop to stop (tests)."""
    _stop.set()


__all__ = ["Sentinel", "start_sentinel", "stop_sentinel", "WORKER_ID"]
