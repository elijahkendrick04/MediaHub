"""
swim_content_pb/fetcher.py
Concurrent HTTP fetcher with budget + circuit breaker.

Uses stdlib only: urllib.request, concurrent.futures.ThreadPoolExecutor.
Each worker uses its own urllib session (stateless, thread-safe).

Circuit breaker: if 5 consecutive HTTP errors, abort remaining fetches
  and mark all unfetched as fetch_skipped_circuit_open.

Budget: total_budget_sec is wall-clock from start of fetch_many; once
  exceeded, in-flight requests are allowed to finish but no new ones
  are submitted.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from datetime import datetime, timezone
from typing import Callable, Optional

from .cache import PBCache
from .parser import parse_pb_html, PB_URL
from .schema import FetchResult, ParsedSnapshot

USER_AGENT = "SwimContentV6/1.0 (contact: admin@swansea-uni-swimming.example)"


class PBFetcher:
    """Concurrent HTTP fetcher with budget, circuit breaker, and cache."""

    def __init__(
        self,
        max_workers: int = 3,
        request_delay_sec: float = 0.5,
        per_request_timeout_sec: float = 12.0,
        total_budget_sec: float = 90.0,
        max_retries: int = 2,
        circuit_breaker_threshold: int = 5,
    ):
        self.max_workers = max_workers
        self.request_delay_sec = request_delay_sec
        self.per_request_timeout_sec = per_request_timeout_sec
        self.total_budget_sec = total_budget_sec
        self.max_retries = max_retries
        self.circuit_breaker_threshold = circuit_breaker_threshold

        # Circuit breaker state (shared across threads — use a lock)
        self._consec_failures = 0
        self._circuit_open = False
        self._lock = threading.Lock()

    def _circuit_trip(self) -> None:
        with self._lock:
            self._circuit_open = True

    def _record_success(self) -> None:
        with self._lock:
            self._consec_failures = 0

    def _record_failure(self) -> bool:
        """Record a failure. Returns True if circuit just tripped."""
        with self._lock:
            self._consec_failures += 1
            if self._consec_failures >= self.circuit_breaker_threshold:
                self._circuit_open = True
                return True
        return False

    def _is_circuit_open(self) -> bool:
        with self._lock:
            return self._circuit_open

    def _fetch_one(self, asa_id: str, cache: PBCache) -> FetchResult:
        """Fetch (or load from cache) the PB page for one swimmer.

        Does NOT check circuit breaker or budget — caller does that.
        """
        # Cache check
        cached = cache.get(asa_id)
        if cached is not None:
            return FetchResult(
                asa_id=asa_id,
                snapshot=cached,
                from_cache=True,
                fetch_ok=True,
                source="cache",
            )

        # Validate ID
        if not asa_id or not asa_id.strip().isdigit():
            snap = ParsedSnapshot(
                asa_id=asa_id,
                swimmer_name=None,
                entries=[],
                source_url="",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                fetch_ok=False,
                error="invalid asa_id",
            )
            return FetchResult(
                asa_id=asa_id,
                snapshot=snap,
                from_cache=False,
                fetch_ok=False,
                error="invalid asa_id",
                source="invalid_id",
            )

        url = PB_URL.format(tiref=asa_id)
        fetched_at = datetime.now(timezone.utc).isoformat()
        last_error: Optional[str] = None
        last_status: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                time.sleep(min(self.request_delay_sec * (2 ** attempt), 5.0))
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-GB,en;q=0.9",
                    },
                )
                with urllib.request.urlopen(req, timeout=self.per_request_timeout_sec) as resp:
                    html = resp.read().decode("utf-8", "replace")

                snapshot = parse_pb_html(html, asa_id, url, fetched_at)
                cache.put(asa_id, snapshot)

                if self.request_delay_sec > 0:
                    time.sleep(self.request_delay_sec)

                self._record_success()
                return FetchResult(
                    asa_id=asa_id,
                    snapshot=snapshot,
                    from_cache=False,
                    fetch_ok=True,
                    source="network",
                )

            except urllib.error.HTTPError as e:
                last_status = e.code
                last_error = f"HTTP {e.code}: {e.reason}"
                # Don't retry 404 — swimmer truly not found
                if e.code == 404:
                    break
            except urllib.error.URLError as e:
                last_error = f"URLError: {e.reason}"
            except Exception as e:
                last_error = repr(e)

        # All attempts failed
        self._record_failure()
        snap = ParsedSnapshot(
            asa_id=asa_id,
            swimmer_name=None,
            entries=[],
            source_url=url,
            fetched_at=fetched_at,
            fetch_ok=False,
            error=last_error,
        )
        return FetchResult(
            asa_id=asa_id,
            snapshot=snap,
            from_cache=False,
            fetch_ok=False,
            error=last_error,
            status_code=last_status,
            source="network",
        )

    def fetch_many(
        self,
        asa_ids: list[str],
        cache: PBCache,
        progress_cb: Optional[Callable] = None,
    ) -> dict[str, FetchResult]:
        """Fetch every asa_id with concurrency, respecting budget and circuit breaker.

        Returns dict keyed by asa_id, including failures.
        Cache is consulted FIRST; only misses go to the network.
        """
        # Reset circuit breaker for each new batch
        with self._lock:
            self._consec_failures = 0
            self._circuit_open = False

        start_wall = time.monotonic()
        results: dict[str, FetchResult] = {}

        # De-duplicate
        unique_ids = list(dict.fromkeys(id_.strip() for id_ in asa_ids if id_ and id_.strip()))
        total = len(unique_ids)

        if not unique_ids:
            return results

        # Submit tasks to a thread pool, checking budget before each submission
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: dict[Future, str] = {}

            for asa_id in unique_ids:
                # Budget check — wall clock from start
                elapsed = time.monotonic() - start_wall
                if elapsed >= self.total_budget_sec:
                    # Budget exceeded — mark remaining as skipped
                    skipped_snap = ParsedSnapshot(
                        asa_id=asa_id,
                        swimmer_name=None,
                        entries=[],
                        source_url="",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        fetch_ok=False,
                        error="fetch_skipped_budget_exceeded",
                    )
                    results[asa_id] = FetchResult(
                        asa_id=asa_id,
                        snapshot=skipped_snap,
                        from_cache=False,
                        fetch_ok=False,
                        error="fetch_skipped_budget_exceeded",
                        source="skipped_budget",
                    )
                    continue

                # Circuit breaker check
                if self._is_circuit_open():
                    skipped_snap = ParsedSnapshot(
                        asa_id=asa_id,
                        swimmer_name=None,
                        entries=[],
                        source_url="",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        fetch_ok=False,
                        error="fetch_skipped_circuit_open",
                    )
                    results[asa_id] = FetchResult(
                        asa_id=asa_id,
                        snapshot=skipped_snap,
                        from_cache=False,
                        fetch_ok=False,
                        error="fetch_skipped_circuit_open",
                        source="skipped_circuit_open",
                    )
                    continue

                # Submit
                fut = executor.submit(self._fetch_one, asa_id, cache)
                futures[fut] = asa_id

            # Collect results
            done_count = 0
            for fut in as_completed(futures):
                asa_id = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:
                    snap = ParsedSnapshot(
                        asa_id=asa_id,
                        swimmer_name=None,
                        entries=[],
                        source_url="",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        fetch_ok=False,
                        error=repr(exc),
                    )
                    result = FetchResult(
                        asa_id=asa_id,
                        snapshot=snap,
                        from_cache=False,
                        fetch_ok=False,
                        error=repr(exc),
                        source="network",
                    )
                results[asa_id] = result
                done_count += 1
                if progress_cb:
                    try:
                        progress_cb(done_count, total, result)
                    except Exception:
                        pass

        return results
