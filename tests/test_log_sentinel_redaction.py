"""Regression tests for deep-review batch 3 (log_sentinel hardening).

  #92  evidence is redacted (keys / auth / emails) before it leaves the process
  #93  append_audit is best-effort — a failed write (ENOSPC) does not raise, so
       the disk-full notification still gets sent

The secret-SHAPED fixtures below are assembled from fragments so no literal
key string ever appears in source — these are synthetic values, never real
credentials (which are env-only, per CLAUDE.md), and building them from parts
keeps the gitleaks secret-scanner strict over this file.
"""

from __future__ import annotations

from mediahub.log_sentinel import state as st
from mediahub.log_sentinel.detectors import detect, redact_evidence
from mediahub.log_sentinel.render_api import LogLine

# Fake, non-literal secret shapes (fragments joined at runtime).
_FAKE_GOOGLE = "AIza" + "Sy" + ("FAKEfake" * 4) + "abc"  # Gemini-key shape
_FAKE_ANTHROPIC = "sk-ant-" + "api03-" + ("FAKEfake" * 3) + "_x"  # Anthropic-key shape
_FAKE_GENERIC = "super" + "secret" + "value"
_FAKE_TOKEN = "abc" + "TOKEN" + "123"
_FAKE_EMAIL = "parent" + "@" + "example.com"


def test_redact_evidence_masks_secrets_and_pii():
    cases = {
        f"GET /v1/x?key={_FAKE_GOOGLE} HTTP/1.1": _FAKE_GOOGLE,
        f"Authorization: Bearer {_FAKE_ANTHROPIC}": _FAKE_ANTHROPIC,
        f"api_key={_FAKE_GENERIC}&next=1": _FAKE_GENERIC,
        f"token: {_FAKE_TOKEN}": _FAKE_TOKEN,
        f"export requested by {_FAKE_EMAIL}": _FAKE_EMAIL,
    }
    for raw, leaked in cases.items():
        out = redact_evidence(raw)
        assert leaked not in out, f"secret/PII survived redaction: {out!r}"
    # The masked forms are present so the line is still diagnostically useful.
    assert redact_evidence(f"api_key={_FAKE_GENERIC}&next=1") == "api_key=***&next=1"
    assert "<email redacted>" in redact_evidence(f"mail to {_FAKE_EMAIL} now")


def test_detect_evidence_is_redacted():
    line = LogLine(
        epoch=0.0,
        timestamp="2026-07-12T00:00:00Z",
        message=f"Traceback (most recent call last): GET /api?key={_FAKE_GOOGLE} died",
    )
    findings = detect([line])
    assert findings, "traceback detector should have fired"
    joined = " ".join(findings[0].evidence)
    assert _FAKE_GOOGLE not in joined, f"key leaked into evidence: {joined!r}"
    assert "key=***" in joined


def test_append_audit_survives_write_failure(tmp_path):
    # Point data_dir at a *file*, so state_dir() can't mkdir the log_sentinel
    # subdir — the same OSError shape as a full disk. append_audit must swallow
    # it rather than abort the sentinel cycle before it can notify.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    st.append_audit({"kind": "finding", "issue_id": "disk_full"}, data_dir=str(blocker))
    # no exception == pass
