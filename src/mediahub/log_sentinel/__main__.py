"""CLI for the log sentinel: ``python -m mediahub.log_sentinel <command>``.

Commands:
    check    validate config end-to-end (API key, service reachable, one log page,
             notify channels) without acting on anything.
    once     run a single poll→detect→notify→act cycle and print its summary.
    run      run the loop in the foreground (Ctrl-C to stop).
    status   print the last status snapshot and recent audit entries.
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def _cmd_check() -> int:
    from mediahub.log_sentinel import render_api
    from mediahub.notify.channels import all_channels

    report: dict = {"configured": render_api.is_configured()}
    if not report["configured"]:
        report["detail"] = "set RENDER_API_KEY and RENDER_SERVICE_ID"
        print(json.dumps(report, indent=2))
        return 1
    try:
        details = render_api.service_details()
        report["service"] = {
            "id": details.get("id"),
            "name": details.get("name"),
            "ownerId": details.get("ownerId"),
        }
        lines, _ = render_api.fetch_log_lines(time.time() - 300)
        report["log_fetch"] = {"ok": True, "lines_last_5min": len(lines)}
    except render_api.RenderApiUnavailable as e:
        report["error"] = str(e)
        print(json.dumps(report, indent=2))
        return 1
    report["notify_channels"] = [ch.name for ch in all_channels() if ch.configured()]
    if not report["notify_channels"]:
        report["notify_warning"] = (
            "no notify channel configured (MEDIAHUB_NTFY_TOPIC / MEDIAHUB_NOTIFY_WEBHOOK) "
            "— findings will only reach the audit ledger"
        )
    print(json.dumps(report, indent=2))
    return 0


def _cmd_once() -> int:
    from mediahub.log_sentinel import Sentinel

    summary = Sentinel().run_once()
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("configured") else 1


def _cmd_run() -> int:
    from mediahub.log_sentinel import Sentinel

    print("log sentinel running in foreground (Ctrl-C to stop)…", file=sys.stderr)
    try:
        Sentinel().run_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_status() -> int:
    from mediahub.log_sentinel import state as st

    print(json.dumps({"status": st.read_status(), "audit_tail": st.read_audit_tail(15)}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mediahub.log_sentinel", description=__doc__)
    parser.add_argument("command", choices=["check", "once", "run", "status"])
    args = parser.parse_args(argv)
    return {"check": _cmd_check, "once": _cmd_once, "run": _cmd_run, "status": _cmd_status}[
        args.command
    ]()


if __name__ == "__main__":
    raise SystemExit(main())
