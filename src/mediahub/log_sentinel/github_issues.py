"""mediahub/log_sentinel/github_issues.py — file findings as GitHub issues.

The operator-chosen escalation path for code-level findings (ADR 0017
addendum): each distinct issue id gets ONE open GitHub issue, labelled
``sentinel``, written with the same diagnosis the notification carries. The
roadmap workflow lists open ``sentinel`` issues in ``docs/ROADMAP.md``'s
"Production findings" block, so filed findings are automatically on the
roadmap; closing the issue clears it from the list on the next refresh.

Dedupe contract: the sentinel remembers the issue number per issue id in its
state file and re-files only when that issue is CLOSED (i.e. a fixed problem
that comes back gets a fresh issue; a still-open problem never spams the
tracker). On any API doubt it files nothing and retries next window — a
missing issue is recoverable, a duplicate storm is noise.

Configuration is env-only and **inert when unset**:

    MEDIAHUB_SENTINEL_GITHUB_TOKEN   fine-grained PAT, Issues read/write on the
                                     one repo below. SECRET — env/.env only.
    MEDIAHUB_SENTINEL_GITHUB_REPO    "owner/repo", e.g. elijahkendrick04/MediaHub

The token is sent only in the Authorization header — never logged or persisted.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from mediahub.log_sentinel.detectors import Finding

DEFAULT_API = "https://api.github.com"
DEFAULT_TIMEOUT = 15.0
LABEL = "sentinel"
_LABEL_COLOR = "d93f0b"
_LABEL_DESCRIPTION = "Auto-filed by the production log sentinel (docs/LOG_SENTINEL.md)"


class GithubIssuesUnavailable(RuntimeError):
    """Raised when the GitHub API can't be reached or rejects a request."""


def _token() -> Optional[str]:
    v = os.environ.get("MEDIAHUB_SENTINEL_GITHUB_TOKEN", "").strip()
    return v or None


def repo() -> Optional[str]:
    v = os.environ.get("MEDIAHUB_SENTINEL_GITHUB_REPO", "").strip().strip("/")
    return v if v.count("/") == 1 else None


def is_configured() -> bool:
    return bool(_token() and repo())


def _api() -> str:
    return os.environ.get("MEDIAHUB_SENTINEL_GITHUB_API", DEFAULT_API).strip().rstrip("/")


def _request(method: str, path: str, *, json_body=None):
    token = _token()
    if not token:
        raise GithubIssuesUnavailable("MEDIAHUB_SENTINEL_GITHUB_TOKEN is not configured")
    try:
        import requests  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - requests is a hard dep
        raise GithubIssuesUnavailable(f"requests unavailable: {e}") from e
    try:
        return requests.request(
            method,
            f"{_api()}{path}",
            json=json_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception as e:
        raise GithubIssuesUnavailable(f"GitHub API transport error: {e}") from e


_label_lock = threading.Lock()
_label_ready = False


def ensure_label() -> None:
    """Create the ``sentinel`` label if the repo doesn't have it (once)."""
    global _label_ready
    with _label_lock:
        if _label_ready:
            return
        r = _request("GET", f"/repos/{repo()}/labels/{LABEL}")
        if r.status_code == 404:
            created = _request(
                "POST",
                f"/repos/{repo()}/labels",
                json_body={
                    "name": LABEL,
                    "color": _LABEL_COLOR,
                    "description": _LABEL_DESCRIPTION,
                },
            )
            if created.status_code not in (200, 201, 422):  # 422 = lost a race, label exists
                raise GithubIssuesUnavailable(f"create label: HTTP {created.status_code}")
        elif r.status_code >= 400:
            raise GithubIssuesUnavailable(f"check label: HTTP {r.status_code}")
        _label_ready = True


def issue_state(number: int) -> Optional[str]:
    """'open' / 'closed' for an issue number; 'gone' when it 404s (deleted —
    the caller should file a fresh issue); None only on a transient error (5xx /
    transport), which the caller treats as 'retry next window'.

    Distinguishing 404 from a transient error matters: mapping a permanent 404 to
    None left a deleted escalation issue un-refiled forever."""
    try:
        r = _request("GET", f"/repos/{repo()}/issues/{int(number)}")
        if r.status_code == 404:
            return "gone"
        if r.status_code != 200:
            return None
        return str(r.json().get("state") or "") or None
    except GithubIssuesUnavailable:
        return None


def issue_body(finding: Finding, public_base_url: str = "") -> str:
    lines = [
        f"**Severity:** {finding.severity} · **occurrences in window:** {finding.count}",
        "",
        finding.suggestion,
        "",
    ]
    if finding.evidence:
        lines += ["**Evidence (from production logs):**", "", "```"]
        lines += [e for e in finding.evidence]
        lines += ["```", ""]
    if public_base_url:
        lines += [f"Live sentinel state: {public_base_url}/healthz/sentinel", ""]
    lines += [
        "---",
        "Filed automatically by the log sentinel (`docs/LOG_SENTINEL.md`, dedupe key "
        f"`{finding.issue_id}`). It appears in `docs/ROADMAP.md` → *Production findings* "
        "while open; **close this issue when fixed** and it drops off the roadmap on the "
        "next refresh. A recurrence after closing files a fresh issue.",
    ]
    return "\n".join(lines)


def create_issue(finding: Finding, public_base_url: str = "") -> dict:
    """File the issue; returns ``{"number": int, "url": str}``."""
    ensure_label()
    r = _request(
        "POST",
        f"/repos/{repo()}/issues",
        json_body={
            "title": f"[sentinel] {finding.title}",
            "body": issue_body(finding, public_base_url),
            "labels": [LABEL],
        },
    )
    if r.status_code not in (200, 201):
        raise GithubIssuesUnavailable(f"create issue: HTTP {r.status_code} {str(r.text)[:200]}")
    data = r.json()
    return {"number": int(data.get("number") or 0), "url": str(data.get("html_url") or "")}


__all__ = [
    "GithubIssuesUnavailable",
    "LABEL",
    "is_configured",
    "repo",
    "ensure_label",
    "issue_state",
    "issue_body",
    "create_issue",
]
