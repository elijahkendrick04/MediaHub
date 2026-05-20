#!/usr/bin/env python3
"""Measure MediaHub HTTP route latencies via curl.

Usage:
    # 1. Start the server:
    DATA_DIR=/tmp/perf_data PORT=5050 gunicorn mediahub.web:app \
        --bind 127.0.0.1:5050 --workers 1 --threads 4 --daemon

    # 2. Warm and prime the session cookie:
    rm -f /tmp/cookies.txt
    for i in 1 2 3; do
      curl -s -c /tmp/cookies.txt -b /tmp/cookies.txt -o /dev/null \
        http://localhost:5050/
    done

    # 3. Bench:
    python scripts/perf/bench_routes.py --n 5

Each route is hit ``--n`` times with curl ``--write-out`` for accurate
wall-clock timing (Flask's test_client over-counts the WSGI overhead).
p50 / p95 / max are reported alongside HTTP status and response size so
non-200s and tiny redirect bodies are obvious in the table.
"""
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path

DEFAULT_HOST = "http://localhost:5050"
DEFAULT_RUN_ID = "test_run"
DEFAULT_COOKIES = "/tmp/cookies.txt"


def time_one(url: str, cookies: str, method: str = "GET") -> tuple[int, float, int]:
    """Return (status, total_seconds, bytes_received) for one curl request."""
    cmd = [
        "curl", "-s",
        "-X", method,
        "-b", cookies,
        "-c", cookies,
        "-o", "/dev/null",
        "-w", "%{http_code} %{time_total} %{size_download}",
        url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    parts = out.stdout.strip().split()
    if len(parts) != 3:
        return -1, 0.0, 0
    return int(parts[0]), float(parts[1]), int(parts[2])


def pXX(samples: list[float], pct: float) -> float:
    if not samples:
        return float("nan")
    s = sorted(samples)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def bench(routes: list[dict], host: str, cookies: str, n: int = 5) -> list[dict]:
    rows = []
    for r in routes:
        url = host + r["path"]
        samples_ms, statuses, sizes = [], [], []
        for _ in range(n):
            status, t, sz = time_one(url, cookies, method=r.get("method", "GET"))
            samples_ms.append(t * 1000)
            statuses.append(status)
            sizes.append(sz)
        rows.append({
            "label": r["label"],
            "path": r["path"],
            "method": r.get("method", "GET"),
            "n": n,
            "statuses": statuses,
            "samples_ms": samples_ms,
            "p50_ms": pXX(samples_ms, 50),
            "p95_ms": pXX(samples_ms, 95),
            "min_ms": min(samples_ms),
            "max_ms": max(samples_ms),
            "size_bytes": max(sizes),
        })
    return rows


def fmt_table(rows: list[dict]) -> str:
    w_label = max(34, max(len(r["label"]) for r in rows))
    w_path = max(34, max(len(r["path"]) for r in rows))
    header = f"{'label':<{w_label}}  {'path':<{w_path}}  {'status':>6}  {'p50_ms':>8}  {'p95_ms':>8}  {'max_ms':>8}  {'bytes':>8}"
    out = [header, "-" * len(header)]
    for r in rows:
        st = r["statuses"]
        status_str = str(st[0]) if all(s == st[0] for s in st) else ",".join(str(s) for s in st)
        out.append(
            f"{r['label']:<{w_label}}  {r['path']:<{w_path}}  {status_str:>6}  "
            f"{r['p50_ms']:>8.1f}  {r['p95_ms']:>8.1f}  {r['max_ms']:>8.1f}  {r['size_bytes']:>8}"
        )
    return "\n".join(out)


def default_routes(run_id: str) -> list[dict]:
    return [
        # Static / no-run pages
        {"label": "home",                "path": "/"},
        {"label": "activity",            "path": "/activity"},
        {"label": "upload (GET)",        "path": "/upload"},
        {"label": "research",            "path": "/research"},
        {"label": "privacy",             "path": "/privacy"},
        {"label": "settings",            "path": "/settings"},
        {"label": "status",              "path": "/status"},
        {"label": "make",                "path": "/make"},
        {"label": "spotlight (index)",   "path": "/spotlight"},
        {"label": "weekend-preview",     "path": "/weekend-preview"},
        {"label": "sponsor-post",        "path": "/sponsor-post"},
        {"label": "session-update",      "path": "/session-update"},
        {"label": "free-text/quick",     "path": "/free-text/quick"},
        {"label": "free-text",           "path": "/free-text"},
        {"label": "drafts",              "path": "/drafts"},
        {"label": "add-input",           "path": "/add-input"},
        {"label": "organisation",        "path": "/organisation"},
        {"label": "organisation/setup",  "path": "/organisation/setup"},
        {"label": "media-library",       "path": "/media-library"},
        {"label": "sign-in",             "path": "/sign-in"},
        # Health probes
        {"label": "healthz",             "path": "/healthz"},
        {"label": "healthz/memory",      "path": "/healthz/memory"},
        {"label": "healthz/deps",        "path": "/healthz/deps"},
        {"label": "healthz/usage",       "path": "/healthz/usage"},
        {"label": "health",              "path": "/health"},
        # API (no run-id)
        {"label": "api/status",                "path": "/api/status"},
        {"label": "api/settings/llm-status",   "path": "/api/settings/llm-status"},
        {"label": "api/media-library/list",    "path": "/api/media-library/list.json"},
        # Run-scoped pages
        {"label": "pack",                 "path": f"/pack/{run_id}"},
        {"label": "pack/grouped",         "path": f"/pack/{run_id}/grouped"},
        {"label": "runs/<id>",            "path": f"/runs/{run_id}"},
        {"label": "review",               "path": f"/review/{run_id}"},
        {"label": "audit",                "path": f"/audit/{run_id}"},
        {"label": "recognition",          "path": f"/recognition/{run_id}"},
        # Run-scoped API
        {"label": "api/runs/<id>/status",        "path": f"/api/runs/{run_id}/status"},
        {"label": "api/runs/<id>/cards",         "path": f"/api/runs/{run_id}/cards"},
        {"label": "api/runs/<id>/trust",         "path": f"/api/runs/{run_id}/trust"},
        {"label": "api/runs/<id>/recognition",   "path": f"/api/runs/{run_id}/recognition"},
        {"label": "api/runs/<id>/export",        "path": f"/api/runs/{run_id}/export"},
        {"label": "api/runs/<id>/newsletter",    "path": f"/api/runs/{run_id}/newsletter"},
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--cookies", default=DEFAULT_COOKIES)
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--json", default="bench_results.json")
    ap.add_argument("--routes-file", default=None,
                    help="Optional JSON list of {label, path, method}")
    args = ap.parse_args()

    routes = (json.loads(Path(args.routes_file).read_text())
              if args.routes_file else default_routes(args.run_id))
    rows = bench(routes, args.host, args.cookies, n=args.n)
    print(fmt_table(rows))
    Path(args.json).write_text(json.dumps(rows, indent=2))
    print(f"\nRaw results: {args.json}")


if __name__ == "__main__":
    main()
