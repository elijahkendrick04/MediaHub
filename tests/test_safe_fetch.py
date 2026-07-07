"""Tests for web_research.safe_fetch — the SSRF-hardened fetcher.

Offline: socket.getaddrinfo and the urllib3 connection pools are faked, so no
real DNS or network happens. The security guarantees (internal IPs refused,
redirects re-validated at each hop, the connection pinned to the validated IP,
content sanitised + byte- and char-capped) are the whole point.
"""
from __future__ import annotations

import socket

import pytest
import urllib3

from mediahub.web_research import safe_fetch as sf


def _resolver(mapping):
    def _getaddrinfo(host, *a, **k):
        ips = mapping.get(host)
        if ips is None:
            raise socket.gaierror(f"no such host: {host}")
        if isinstance(ips, str):
            ips = [ips]
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]

    return _getaddrinfo


class _Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def stream(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        pass


class _FakePools:
    """Replaces urllib3.HTTP(S)ConnectionPool; records pinned host + headers."""

    def __init__(self, responses):
        self.responses = responses  # {(ip, path): _Resp}
        self.calls = []  # (scheme, ip, port, server_hostname, path, headers)

    def _factory(self, scheme):
        fake = self

        class _Pool:
            def __init__(self, host, port=None, server_hostname=None, **kw):
                self._ip = host
                self._port = port
                self._sni = server_hostname

            def urlopen(self, method, path, headers=None, **kw):
                fake.calls.append(
                    (scheme, self._ip, self._port, self._sni, path, dict(headers or {}))
                )
                resp = fake.responses.get((self._ip, path))
                if resp is None:
                    raise OSError("connection refused")
                return resp

            def close(self):
                pass

        return _Pool

    def install(self, monkeypatch):
        monkeypatch.setattr(urllib3, "HTTPSConnectionPool", self._factory("https"))
        monkeypatch.setattr(urllib3, "HTTPConnectionPool", self._factory("http"))


def _must_not_connect(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no connection may be made for a blocked host")

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", _boom)
    monkeypatch.setattr(urllib3, "HTTPConnectionPool", _boom)


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1",
     "172.16.0.1", "0.0.0.0", "::1", "fe80::1"],
)
def test_blocks_internal_ips(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"evil.test": ip}))
    _must_not_connect(monkeypatch)
    assert sf.is_url_safe("http://evil.test/path") is False
    assert sf.safe_fetch("http://evil.test/path") is None


def test_blocks_when_any_resolved_ip_is_internal(monkeypatch):
    # Rebinding-style answer: one public IP and one internal IP => refuse all.
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _resolver({"dual.test": ["93.184.216.34", "10.0.0.9"]}),
    )
    _must_not_connect(monkeypatch)
    assert sf.is_url_safe("https://dual.test/x") is False
    assert sf.safe_fetch("https://dual.test/x") is None


def test_connection_is_pinned_to_validated_ip(monkeypatch):
    """DNS-rebinding TOCTOU: the socket must go to the checked IP, with the
    original hostname kept as Host header + TLS SNI."""
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"example.test": "93.184.216.34"}))
    pools = _FakePools(
        {("93.184.216.34", "/x"): _Resp(200, b"<html><body>Hello <b>world</b></body></html>")}
    )
    pools.install(monkeypatch)
    assert sf.safe_fetch("https://example.test/x") == "Hello world"
    (scheme, ip, port, sni, path, headers) = pools.calls[0]
    assert scheme == "https"
    assert ip == "93.184.216.34"  # pinned — not the hostname
    assert port == 443
    assert sni == "example.test"
    assert headers["Host"] == "example.test"


def test_allows_public_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"example.test": "93.184.216.34"}))
    pools = _FakePools(
        {("93.184.216.34", "/x"): _Resp(200, b"<html><body>Hello <b>world</b></body></html>")}
    )
    pools.install(monkeypatch)
    assert sf.is_url_safe("https://example.test/x") is True
    assert sf.safe_fetch("https://example.test/x") == "Hello world"


def test_non_http_scheme_blocked(monkeypatch):
    _must_not_connect(monkeypatch)
    assert sf.is_url_safe("ftp://example.test/x") is False
    assert sf.is_url_safe("file:///etc/passwd") is False
    assert sf.safe_fetch("file:///etc/passwd") is None


def test_strips_scripts_and_caps(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))
    body = (
        "<html><head><style>x{color:red}</style></head><body>"
        "<script>alert(1)</script>KEEP " + "A" * 9000 + "</body></html>"
    ).encode()
    pools = _FakePools({("93.184.216.34", "/x"): _Resp(200, body)})
    pools.install(monkeypatch)
    out = sf.safe_fetch("https://e.test/x", max_chars=50)
    assert "alert" not in out
    assert "KEEP" in out
    assert len(out) <= 50


def test_body_read_is_byte_capped(monkeypatch):
    """A huge 200 response must be read as a bounded stream, not materialised."""
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))

    class _Endless(_Resp):
        def stream(self, chunk_size):
            while True:  # would never terminate without the byte cap
                yield b"B" * chunk_size

    pools = _FakePools({("93.184.216.34", "/x"): _Endless(200)})
    pools.install(monkeypatch)
    out = sf.safe_fetch("https://e.test/x", max_chars=100, max_bytes=200_000)
    assert out is not None
    assert len(out) <= 100


def test_redirect_to_internal_is_blocked(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _resolver({"good.test": "93.184.216.34", "internal.test": "10.0.0.9"}),
    )
    pools = _FakePools(
        {("93.184.216.34", "/x"): _Resp(302, b"", {"Location": "http://internal.test/secret"})}
    )
    pools.install(monkeypatch)
    assert sf.safe_fetch("https://good.test/x") is None
    assert len(pools.calls) == 1  # the 2nd hop's host-check blocked it before fetching


def test_redirect_to_public_is_followed(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _resolver({"a.test": "93.184.216.34", "b.test": "93.184.216.35"}),
    )
    pools = _FakePools(
        {
            ("93.184.216.34", "/x"): _Resp(301, b"", {"Location": "https://b.test/final"}),
            ("93.184.216.35", "/final"): _Resp(200, b"<p>final page</p>"),
        }
    )
    pools.install(monkeypatch)
    assert sf.safe_fetch("https://a.test/x") == "final page"
    # each hop pinned to its own validated IP
    assert [c[1] for c in pools.calls] == ["93.184.216.34", "93.184.216.35"]


def test_non_200_returns_none(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))
    pools = _FakePools({("93.184.216.34", "/x"): _Resp(404, b"nope")})
    pools.install(monkeypatch)
    assert sf.safe_fetch("https://e.test/x") is None


def test_transport_error_returns_none(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))
    pools = _FakePools({})  # no response registered => connection refused
    pools.install(monkeypatch)
    assert sf.safe_fetch("https://e.test/x") is None


def test_unresolvable_host_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({}))
    _must_not_connect(monkeypatch)
    assert sf.safe_fetch("https://nope.test/x") is None
