"""Regression tests for deep-review batch 14a (infra hardening, non-SSRF).

#119 backup.create_backup writes to a .part file, verifies the ZIP, and only
     then renames into the canonical name — no truncated archive under the real
     name, no leftover .part.
#121 web.request_ip.client_ip trusts the LAST X-Forwarded-For hop (the proxy's
     appended real client), not remote_addr / the first hop.
#123 A token minted with no scopes is fail-closed (validate_scopes -> []), not
     silently granted the read-only default.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


# ── #119 durable, verified backup ───────────────────────────────────────────


def test_backup_is_verified_and_atomically_named(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "users.jsonl").write_text('{"email":"a@b.c"}\n', encoding="utf-8")
    from mediahub.backup import create_backup

    out_dir = tmp_path / "backups"
    report = create_backup(dest_dir=out_dir)
    archive = Path(report["archive"])

    assert archive.exists() and archive.name.endswith(".zip")
    assert not list(out_dir.glob("*.part")), "a .part temp was left behind"
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None  # CRCs all check out
        assert "backup_manifest.json" in zf.namelist()


# ── #121 proxy-aware client IP ──────────────────────────────────────────────


class _Req:
    def __init__(self, xff=None, remote=None):
        self.headers = {"X-Forwarded-For": xff} if xff else {}
        self.remote_addr = remote


def test_client_ip_uses_last_forwarded_hop(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_TRUSTED_PROXY_HOPS", raising=False)  # default: 1 hop
    from mediahub.web.request_ip import client_ip

    # One trusted proxy appends the real client as the LAST hop; earlier hops are
    # attacker-supplied and must NOT be trusted (else a rotated header = fresh bucket).
    assert client_ip(_Req("1.1.1.1, 2.2.2.2", "10.0.0.9")) == "2.2.2.2"
    assert client_ip(_Req(None, "10.0.0.9")) == "10.0.0.9"  # no XFF → socket
    assert client_ip(_Req(None, None)) == "unknown"


def test_client_ip_no_proxy_uses_socket(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TRUSTED_PROXY_HOPS", "0")
    from mediahub.web.request_ip import client_ip

    # 0 hops: ignore the forwarded header entirely, trust only the socket address.
    assert client_ip(_Req("9.9.9.9", "10.0.0.9")) == "10.0.0.9"


# ── #123 fail-closed token scopes ───────────────────────────────────────────


def test_no_scope_token_is_fail_closed():
    from mediahub.api_public.scopes import DEFAULT_SCOPES, validate_scopes

    assert validate_scopes(None) == []
    assert validate_scopes([]) == []
    assert DEFAULT_SCOPES, "the read-only bundle still exists for the UI to suggest"
