"""Tests for web_research.safe_fetch — the SSRF-hardened fetcher.

Offline: socket.getaddrinfo and requests.get are faked, so no real DNS or
network happens. The security guarantees (internal IPs refused, redirects
re-validated at each hop, content sanitised + capped) are the whole point.
"""
from __future__ import annotations

import socket

import pytest
import requests

from mediahub.web_research import safe_fetch as sf


def _resolver(mapping):
    def _getaddrinfo(host, *a, **k):
        ip = mapping.get(host)
        if ip is None:
            raise socket.gaierror(f"no such host: {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]

    return _getaddrinfo


class _Resp:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _must_not_fetch(*a, **k):
    raise AssertionError("requests.get must not be called for a blocked host")


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1",
     "172.16.0.1", "0.0.0.0", "::1", "fe80::1"],
)
def test_blocks_internal_ips(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"evil.test": ip}))
    monkeypatch.setattr(requests, "get", _must_not_fetch)
    assert sf.is_url_safe("http://evil.test/path") is False
    assert sf.safe_fetch("http://evil.test/path") is None


def test_allows_public_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"example.test": "93.184.216.34"}))
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _Resp(200, "<html><body>Hello <b>world</b></body></html>")
    )
    assert sf.is_url_safe("https://example.test/x") is True
    assert sf.safe_fetch("https://example.test/x") == "Hello world"


def test_non_http_scheme_blocked(monkeypatch):
    monkeypatch.setattr(requests, "get", _must_not_fetch)
    assert sf.is_url_safe("ftp://example.test/x") is False
    assert sf.is_url_safe("file:///etc/passwd") is False
    assert sf.safe_fetch("file:///etc/passwd") is None


def test_strips_scripts_and_caps(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))
    body = (
        "<html><head><style>x{color:red}</style></head><body>"
        "<script>alert(1)</script>KEEP " + "A" * 9000 + "</body></html>"
    )
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, body))
    out = sf.safe_fetch("https://e.test/x", max_chars=50)
    assert "alert" not in out
    assert "KEEP" in out
    assert len(out) <= 50


def test_redirect_to_internal_is_blocked(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _resolver({"good.test": "93.184.216.34", "internal.test": "10.0.0.9"}),
    )
    calls = []

    def fake_get(url, **k):
        calls.append(url)
        if "good.test" in url:
            return _Resp(302, "", {"Location": "http://internal.test/secret"})
        raise AssertionError("must not fetch the internal redirect target")

    monkeypatch.setattr(requests, "get", fake_get)
    assert sf.safe_fetch("https://good.test/x") is None
    assert len(calls) == 1  # the 2nd hop's host-check blocked it before fetching


def test_redirect_to_public_is_followed(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _resolver({"a.test": "93.184.216.34", "b.test": "93.184.216.35"}),
    )

    def fake_get(url, **k):
        if "a.test" in url:
            return _Resp(301, "", {"Location": "https://b.test/final"})
        return _Resp(200, "<p>final page</p>")

    monkeypatch.setattr(requests, "get", fake_get)
    assert sf.safe_fetch("https://a.test/x") == "final page"


def test_non_200_returns_none(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(404, "nope"))
    assert sf.safe_fetch("https://e.test/x") is None


def test_transport_error_returns_none(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"e.test": "93.184.216.34"}))

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(requests, "get", boom)
    assert sf.safe_fetch("https://e.test/x") is None


def test_unresolvable_host_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({}))
    monkeypatch.setattr(requests, "get", _must_not_fetch)
    assert sf.safe_fetch("https://nope.test/x") is None
