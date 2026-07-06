"""s.164A DPA 2018 complaints intake + incident register.

The statutory duty (in force 19 June 2026): facilitate data-protection
complaints via an electronic form and acknowledge within 30 days. These
tests pin the public form, the 30-day acknowledgement metadata, the
operator-only admin surface, and XSS-escaping of complainant content.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _submit(client, **overrides):
    data = {
        "name": "Pat Parent",
        "contact": "pat@example.org",
        "relationship": "parent/guardian",
        "club": "Testville SC",
        "details": "My daughter's results were posted without my consent.",
    }
    data.update(overrides)
    return client.post("/complaints", data=data)


def test_public_form_renders_without_login(client):
    r = client.get("/complaints")
    assert r.status_code == 200
    assert b"complaint" in r.data.lower()
    assert b'action="/complaints"' in r.data


def test_submit_creates_record_with_30_day_ack_deadline(client, tmp_path):
    r = _submit(client)
    assert r.status_code == 200
    assert b"reference" in r.data.lower()

    ledger = tmp_path / "compliance" / "complaints.jsonl"
    rec = json.loads(ledger.read_text().splitlines()[0])
    assert rec["status"] == "received"
    received = datetime.fromisoformat(rec["received_at"])
    due = datetime.fromisoformat(rec["ack_due_at"])
    assert due - received == timedelta(days=30)
    # reference shown to the complainant matches the stored id
    assert rec["id"].encode() in r.data


def test_submit_requires_details_and_contact(client):
    assert _submit(client, details="").status_code == 400
    assert _submit(client, contact="").status_code == 400


def test_submission_throttled_per_address(client):
    for _ in range(5):
        assert _submit(client).status_code == 200
    assert _submit(client).status_code == 429


def test_throttle_keyed_on_trusted_hop_not_spoofable_first_hop(client):
    """The throttle keys on the trusted (rightmost) X-Forwarded-For hop, so
    rotating the client-supplied first hop can't mint fresh buckets: after 5
    posts every further rotated post 429s, regardless of the spoofed hop."""
    # Simulate Render's edge appending the real client as the constant LAST hop;
    # the attacker only controls (and rotates) the leading spoofed hop.
    codes = []
    for i in range(7):
        r = client.post(
            "/complaints",
            data={
                "name": "Pat",
                "contact": "pat@example.org",
                "relationship": "parent/guardian",
                "club": "SC",
                "details": "spoof rotation attempt",
            },
            headers={"X-Forwarded-For": f"10.0.0.{i}, 9.9.9.9"},
        )
        codes.append(r.status_code)
    # First 5 succeed; the rotated 6th/7th still hit the same trusted bucket.
    assert codes[:5] == [200, 200, 200, 200, 200]
    assert codes[5] == 429 and codes[6] == 429


def test_admin_page_hidden_without_operator_session(client):
    assert client.get("/admin/compliance").status_code == 404
    assert client.post("/admin/compliance/complaints/abc123/ack").status_code == 404
    assert client.post("/admin/compliance/incidents", data={"title": "x"}).status_code == 404


@pytest.fixture
def operator_client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    c = application.test_client()
    with c.session_transaction() as sess:
        sess["dev_operator"] = True
    return c


def test_operator_sees_and_acknowledges_complaint(operator_client, tmp_path):
    _submit(operator_client)
    ledger = tmp_path / "compliance" / "complaints.jsonl"
    ref = json.loads(ledger.read_text().splitlines()[0])["id"]

    page = operator_client.get("/admin/compliance")
    assert page.status_code == 200
    assert ref.encode() in page.data

    r = operator_client.post(
        f"/admin/compliance/complaints/{ref}/ack", data={"via": "email sent"}
    )
    assert r.status_code == 302

    from mediahub.compliance.complaints import ComplaintsStore

    c = ComplaintsStore().get(ref)
    assert c.status == "acknowledged"
    assert c.acknowledged_at
    assert c.acknowledged_via == "email sent"


def test_complaint_content_is_escaped_in_admin_page(operator_client):
    _submit(operator_client, details='<script>alert("xss")</script>', name="<b>Bold</b>")
    page = operator_client.get("/admin/compliance")
    assert b"<script>alert(" not in page.data
    assert b"&lt;script&gt;" in page.data


def test_overdue_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # never write into the source tree
    from mediahub.compliance.complaints import Complaint, ComplaintsStore

    store = ComplaintsStore()
    c = store.submit(name="A", contact="a@b.c", details="late one")
    # backdate the ack deadline to yesterday by appending a superseding record
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rec = c.to_record()
    rec["ack_due_at"] = past
    store._ledger.append(rec)
    assert any(o.id == c.id for o in store.overdue())
    store.acknowledge(c.id, via="phone")
    assert not any(o.id == c.id for o in store.overdue())


def test_incident_register_roundtrip(operator_client, tmp_path):
    r = operator_client.post(
        "/admin/compliance/incidents",
        data={"title": "Test breach", "severity": "high", "personal_data": "1"},
    )
    assert r.status_code == 302
    from mediahub.compliance.incidents import IncidentRegister

    incidents = IncidentRegister().all()
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.title == "Test breach"
    assert inc.severity == "high"
    assert inc.personal_data_involved is True
    assert inc.detected_at  # 72h clock evidence

    IncidentRegister().update(inc.id, status="closed", remedial_action="fixed")
    assert IncidentRegister().get(inc.id).status == "closed"


def test_complaint_ids_not_guessable_sequential(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # never write into the source tree
    from mediahub.compliance.complaints import ComplaintsStore

    store = ComplaintsStore()
    a = store.submit(name="A", contact="a@b.c", details="one")
    b = store.submit(name="B", contact="b@b.c", details="two")
    assert a.id != b.id
    assert len(a.id) == 12  # 6 random bytes hex — not enumerable
