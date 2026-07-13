"""SEC-27 — durable, cross-worker brute-force brakes.

Deep-review finding #27: account lockout, the per-IP auth limiter, and the TOTP
replay guard lived in per-worker in-process dicts. Under gunicorn's two workers
that gave an attacker ~2x the budget, and ``--max-requests`` worker recycling
wiped the counters mid-attack; ``/login/2fa`` also lacked the per-IP brake.

These tests prove the fix (a shared SQLite store, ``web/auth_brakes.py``):

- **Cross-worker** — a genuinely SEPARATE process (a second gunicorn worker,
  simulated with ``subprocess`` sharing the same ``DATA_DIR/data.db``) sees and
  contributes to the SAME counter. Failures split across two workers still add
  up to one lockout — impossible with per-worker dicts.
- **Recycle/restart-durable** — a fresh process (a recycled worker) still sees
  the lockout, so ``--max-requests`` no longer resets it.
- **TOTP replay is cross-worker** — a code accepted on one worker is rejected as
  a replay on the other.
- **/login/2fa has the per-IP brake** it was missing, in its own bucket.
- **Shared-NAT safety** — the per-IP budget is 20 (the old per-worker 10 × the
  two-worker deployment), so a NAT'd club is never locked out sooner than today;
  distinct IPs never share a bucket.

See ``docs/adr/0030-durable-cross-worker-bruteforce-brakes.md``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest


# --------------------------------------------------------------------------
# A second gunicorn worker == a second OS process sharing the same DATA_DIR.
# --------------------------------------------------------------------------


def _worker(data_dir, code: str) -> str:
    """Run ``code`` in a fresh Python process (a second worker) with DATA_DIR
    pointed at the shared store; return its stdout (stripped)."""
    env = dict(os.environ)
    env["DATA_DIR"] = str(data_dir)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"worker failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    return proc.stdout.strip()


# --------------------------------------------------------------------------
# Account lockout: cross-worker + recycle-durable
# --------------------------------------------------------------------------


def test_account_lockout_is_shared_across_two_workers(monkeypatch, tmp_path):
    """3 failures on worker A + 2 failures on worker B == a lockout. Neither
    worker alone reached the limit of 5, so this can only pass if the counter is
    shared — the exact bug the finding describes (per-worker dicts gave 2x)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    # Worker A (this process): 3 failures — NOT yet locked.
    for _ in range(3):
        auth.record_login_failure("target@club.org")
    assert auth.login_locked("target@club.org") is False

    # Worker B (a separate process): 2 more failures, then report lock state.
    out = _worker(
        tmp_path,
        "from mediahub.web import auth\n"
        "for _ in range(2): auth.record_login_failure('target@club.org')\n"
        "print('LOCKED' if auth.login_locked('target@club.org') else 'OPEN')\n",
    )
    assert out.endswith("LOCKED")  # B sees A's 3 + its own 2 == 5

    # And worker A now sees the combined lockout too.
    assert auth.login_locked("target@club.org") is True


def test_lockout_survives_worker_recycle(monkeypatch, tmp_path):
    """--max-requests recycles a worker mid-attack. A brand-new process (the
    recycled worker) must STILL see the lockout the old process recorded."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # Worker A records 5 failures, then exits (== the recycle).
    _worker(
        tmp_path,
        "from mediahub.web import auth\n"
        "for _ in range(5): auth.record_login_failure('victim@club.org')\n",
    )
    # Fresh process (recycled worker) with NO in-memory state still sees it.
    out = _worker(
        tmp_path,
        "from mediahub.web import auth\n"
        "print('LOCKED' if auth.login_locked('victim@club.org') else 'OPEN')\n",
    )
    assert out.endswith("LOCKED")

    # Same-process check via the live import agrees.
    from mediahub.web import auth

    assert auth.login_locked("victim@club.org") is True


def test_clear_login_failures_is_cross_worker(monkeypatch, tmp_path):
    """A successful login on one worker clears the shared failure history, so
    the other worker no longer treats the account as accumulating failures."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    for _ in range(4):
        auth.record_login_failure("user@club.org")
    # Worker B clears (== a success there); worker A must then start from zero.
    _worker(
        tmp_path,
        "from mediahub.web import auth\n"
        "auth.clear_login_failures('user@club.org')\n",
    )
    # One more failure in A: count is 1, not 5 — no lockout.
    assert auth.record_login_failure("user@club.org") is False
    assert auth.login_locked("user@club.org") is False


# --------------------------------------------------------------------------
# TOTP replay guard: cross-worker + recycle-durable
# --------------------------------------------------------------------------


def test_totp_replay_guard_is_cross_worker(monkeypatch, tmp_path):
    """A TOTP code accepted on worker A must be rejected as a replay on worker
    B — the last-accepted counter is shared, not per-worker."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.auth import _totp_code, totp_generate_secret, totp_verify

    secret = totp_generate_secret()
    at = 1_000_000.0  # fixed clock so both workers derive the same counter
    code = _totp_code(secret, int(at // 30))

    # Worker A accepts it once.
    assert totp_verify(secret, code, at=at) is True

    # Worker B (separate process) must reject the SAME code as a replay.
    out = _worker(
        tmp_path,
        "from mediahub.web.auth import totp_verify\n"
        f"ok = totp_verify({secret!r}, {code!r}, at={at!r})\n"
        "print('ACCEPT' if ok else 'REPLAY')\n",
    )
    assert out.endswith("REPLAY")

    # A re-check in this process is also a replay (durable, not a fluke).
    assert totp_verify(secret, code, at=at) is False
    # The next time-step's code is still accepted (guard advances, not freezes).
    nxt = _totp_code(secret, int(at // 30) + 1)
    assert totp_verify(secret, nxt, at=at + 30) is True


# --------------------------------------------------------------------------
# Per-IP limiter: cross-worker, and the shared-NAT budget
# --------------------------------------------------------------------------


def test_per_ip_limiter_is_shared_across_two_workers(monkeypatch, tmp_path):
    """15 attempts on worker A + 6 on worker B == 21 > 20 → limited. Neither
    worker alone exceeds the budget; only a shared counter trips it."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth_brakes

    now = 2_000_000.0
    ip = "203.0.113.9"
    # Worker A: 15 attempts (well under 20).
    for _ in range(15):
        auth_brakes.record_event("ip:login", ip, now=now, window_secs=600)

    # Worker B: 6 more; the 21st crosses 20 in the SHARED counter.
    out = _worker(
        tmp_path,
        "from mediahub.web import auth_brakes\n"
        "c = 0\n"
        f"for _ in range(6): c = auth_brakes.record_event('ip:login', {ip!r}, now={now!r}, window_secs=600)\n"
        "print('LIMIT' if c > 20 else f'OK:{c}')\n",
    )
    assert out.endswith("LIMIT")


def test_per_ip_budget_preserves_two_worker_leniency_for_shared_nat(client_factory, tmp_path):
    """Shared-NAT confirmation: one IP gets 20 attempts before a 429 (the old
    per-worker 10 × two workers), so a club/school behind one address is locked
    out no sooner than today's most-lenient case. Distinct emails per request so
    the per-ACCOUNT lockout never fires — only the per-IP brake is in play."""
    client = client_factory(tmp_path)
    # 20 attempts from one IP: none should be the per-IP 429.
    for i in range(20):
        r = client.post(
            "/login",
            data={"email": f"nat{i}@club.org", "password": "wrong-pass"},
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
        assert r.status_code != 429, f"attempt {i + 1} braked too early (budget regressed)"
    # The 21st from the SAME IP is the first to trip the brake.
    r = client.post(
        "/login",
        data={"email": "nat20@club.org", "password": "wrong-pass"},
        headers={"X-Forwarded-For": "198.51.100.42"},
    )
    assert r.status_code == 429


def test_distinct_nat_ips_do_not_share_a_bucket(client_factory, tmp_path):
    """A user on a DIFFERENT IP is never affected by another IP's spend — the
    brake is per-IP, so one busy address can't lock out an unrelated one."""
    client = client_factory(tmp_path)
    # Exhaust IP #1's whole budget.
    for i in range(21):
        client.post(
            "/login",
            data={"email": f"a{i}@club.org", "password": "wrong-pass"},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
    # A fresh IP still has its full budget — first attempt is not braked.
    r = client.post(
        "/login",
        data={"email": "b@club.org", "password": "wrong-pass"},
        headers={"X-Forwarded-For": "198.51.100.2"},
    )
    assert r.status_code != 429


# --------------------------------------------------------------------------
# /login/2fa gains the per-IP brake (its own bucket)
# --------------------------------------------------------------------------


def _enable_2fa_and_park(client):
    """Sign up, enable TOTP, and land a fresh login on the /login/2fa step."""
    client.post(
        "/signup",
        data={"email": "coach@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    client.get("/account/2fa")
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    from mediahub.web.auth import _totp_code

    client.post(
        "/account/2fa",
        data={"action": "enable", "totp": _totp_code(secret, int(time.time() // 30))},
    )
    client.post("/logout")
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert "/login/2fa" in r.headers["Location"]
    return secret


def test_login_2fa_post_records_into_its_own_ip_bucket(client_factory, tmp_path):
    """Each /login/2fa POST records into the 'login_2fa' per-IP bucket (the brake
    is wired). GET must NOT record — only the code-submission POST does."""
    client = client_factory(tmp_path)
    _enable_2fa_and_park(client)
    from mediahub.web import auth_brakes

    now = time.time()

    def bucket_count():
        return auth_brakes.count_events("ip:login_2fa", "127.0.0.1", now=now, window_secs=600)

    assert bucket_count() == 0
    client.get("/login/2fa")  # rendering the form must not spend budget
    assert bucket_count() == 0
    # 4 wrong POSTs (below the account-lockout limit of 5) each record one hit.
    for _ in range(4):
        client.post("/login/2fa", data={"totp": "000000"})
    assert bucket_count() == 4


def test_login_2fa_per_ip_brake_fires_independent_of_account_lockout(client_factory, tmp_path):
    """When an IP is over its login_2fa budget, the 2FA POST returns the per-IP
    429 (its distinct 'from your network' message), proving the NEW brake fires
    on a path that previously had only the per-account lockout."""
    client = client_factory(tmp_path)
    _enable_2fa_and_park(client)
    from mediahub.web import auth_brakes

    # Put the test client's IP (127.0.0.1) over the 20-budget for login_2fa.
    now = time.time()
    for _ in range(21):
        auth_brakes.record_event("ip:login_2fa", "127.0.0.1", now=now, window_secs=600)

    r = client.post("/login/2fa", data={"totp": "000000"})
    assert r.status_code == 429
    assert "from your network" in r.get_data(as_text=True)


# --------------------------------------------------------------------------
# Store unit tests: sliding window, replay ordering, corrupt-DB fail-open
# --------------------------------------------------------------------------


def test_sliding_window_excludes_expired_events(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth_brakes

    # Two events long ago, one just now; a 600s window sees only the recent one.
    auth_brakes.record_event("fail", "e@x.com", now=1000.0, window_secs=600)
    auth_brakes.record_event("fail", "e@x.com", now=1100.0, window_secs=600)
    now = 5000.0
    assert auth_brakes.count_events("fail", "e@x.com", now=now, window_secs=600) == 0
    auth_brakes.record_event("fail", "e@x.com", now=now, window_secs=600)
    assert auth_brakes.count_events("fail", "e@x.com", now=now, window_secs=600) == 1


def test_totp_replay_ordering(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth_brakes

    s = "SECRETSECRETSECRET"
    assert auth_brakes.totp_replay_ok(s, 100, now=3000.0) is True  # first accept
    assert auth_brakes.totp_replay_ok(s, 100, now=3000.0) is False  # exact replay
    assert auth_brakes.totp_replay_ok(s, 99, now=3000.0) is False  # older rejected
    assert auth_brakes.totp_replay_ok(s, 101, now=3030.0) is True  # newer accepted
    # A different secret has an independent counter.
    assert auth_brakes.totp_replay_ok("OTHER", 1, now=3000.0) is True


def test_secret_plaintext_never_written_to_db(monkeypatch, tmp_path):
    """The raw TOTP secret must never enter data.db (which is snapshotted) — only
    its sha256 hash is stored as the replay key."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth_brakes

    secret = "SUPERSECRETTOTPVALUE"
    auth_brakes.totp_replay_ok(secret, 1, now=100.0)
    blob = (tmp_path / "data.db").read_bytes()
    assert secret.encode() not in blob


def test_counters_fail_open_on_corrupt_db(monkeypatch, tmp_path):
    """A corrupt/unreadable data.db must not 500 the login path: the counters
    fail open (not locked / not limited) and the replay guard accepts the
    already-HMAC-verified code, rather than raising."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "data.db").write_bytes(b"this is not a sqlite database at all")
    from mediahub.web import auth_brakes

    # No exception, and the fail-open verdicts:
    assert auth_brakes.count_events("fail", "e@x.com", now=1.0, window_secs=600) == 0
    assert auth_brakes.record_event("fail", "e@x.com", now=1.0, window_secs=600) == 0
    assert auth_brakes.totp_replay_ok("S", 1, now=1.0) is True


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client_factory(monkeypatch):
    """Build a fresh test client bound to a given DATA_DIR (isolated brake DB)."""

    def _make(data_dir):
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        from mediahub.web.web import create_app

        app = create_app()
        app.config["TESTING"] = True
        if not app.secret_key:
            app.secret_key = "test-secret"
        return app.test_client()

    return _make
