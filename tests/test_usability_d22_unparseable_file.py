"""D-22 — an unparseable file must get a "we couldn't read this" diagnosis, not
a self-contradicting "parsed OK — looks like a meet preview" plus a raw parser
exception.

When interpret_document throws (corrupt PDF, weird encoding), the configure gate
used to fall into the same branch as a zero-event file — asserting the file
"parsed OK but doesn't contain any events" and telling the volunteer to wait for
the meet to finish — while printing the raw exception directly beneath. The gate
now branches on parse_error, keeps the raw exception operator-only, and lists the
real supported formats.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="wycombe", display_name="Wycombe SC"))
    client.post("/api/organisation/active", data={"profile_id": "wycombe"})
    return client


def _upload_crashing_file(c, monkeypatch):
    import mediahub.interpreter as interp

    def _boom(*a, **k):
        raise RuntimeError("SECRET_PARSE_CRASH_zzz")

    monkeypatch.setattr(interp, "interpret_document", _boom)
    # >2 KB so it isn't caught by the "too small" branch.
    body = b"%PDF-1.4\n" + b"garbage " * 400
    return c.post(
        "/upload",
        data={"file": (io.BytesIO(body), "results.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_parse_crash_says_couldnt_read_not_meet_preview(gated_client, monkeypatch):
    resp = _upload_crashing_file(gated_client, monkeypatch)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "read that file" in body  # "We couldn't read that file"
    # The misleading "parsed OK / meet preview / wait for the meet" copy is gone.
    assert "parsed OK" not in body
    assert "looks like a meet preview" not in body
    assert "Wait until the meet finishes" not in body


def test_parse_crash_hides_raw_exception_from_customer(gated_client, monkeypatch):
    resp = _upload_crashing_file(gated_client, monkeypatch)
    body = resp.get_data(as_text=True)
    assert "SECRET_PARSE_CRASH_zzz" not in body
    assert "Parser error:" not in body


def test_supported_formats_line_matches_real_allowlist(gated_client, monkeypatch):
    resp = _upload_crashing_file(gated_client, monkeypatch)
    body = resp.get_data(as_text=True)
    # The real allowlist (12 extensions) is reflected, not just 3.
    for ext in (".hy3", ".sdif", ".xlsx"):
        assert ext in body
