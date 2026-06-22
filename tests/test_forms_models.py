"""Forms engine (roadmap 1.16) — build 2: the typed form schema."""

from __future__ import annotations

from mediahub.forms import models as m


def test_field_key_from_label_and_type_fallback():
    f = m.FormField(label="Swimmer's Name", type="bogus")
    assert f.key == "swimmer_s_name"
    assert f.type == "text"  # unknown → text
    assert f.column_type == "text"


def test_column_type_mapping():
    assert m.FormField(label="Email", type="email").column_type == "text"
    assert m.FormField(label="Count", type="number").column_type == "number"
    assert m.FormField(label="When", type="date").column_type == "date"
    assert m.FormField(label="OK?", type="consent").column_type == "bool"
    assert m.FormField(label="Sub?", type="checkbox").column_type == "bool"


def test_effective_max_len():
    assert m.FormField(label="x").effective_max_len == m.DEFAULT_MAX_LEN
    assert m.FormField(label="x", max_len=50).effective_max_len == 50


def test_field_roundtrip():
    f = m.FormField(label="Age", type="select", options=["a", "b"], required=True, help_text="h")
    again = m.FormField.from_dict(f.to_dict())
    assert again.key == f.key and again.options == ["a", "b"] and again.required


def test_formspec_dedupes_keys():
    spec = m.FormSpec(
        title="T",
        fields=[m.FormField(label="Name"), m.FormField(label="Name"), m.FormField(label="Name")],
    )
    keys = [f.key for f in spec.fields]
    assert keys == ["name", "name_2", "name_3"]


def test_formspec_minor_detection_and_lookup():
    spec = m.FormSpec(
        title="Trial",
        fields=[m.FormField(label="Child", minors_sensitive=True), m.FormField(label="Email")],
    )
    assert spec.has_minor_sensitive_field
    assert spec.field_by_key("email").label == "Email"
    assert spec.field_by_key("nope") is None
    # also true via the explicit flag
    assert m.FormSpec(title="x", collects_minor_data=True).has_minor_sensitive_field


def test_formspec_roundtrip_and_new_form():
    spec = m.new_form("RSVP", m.rsvp_fields(), notify=False)
    assert spec.form_id
    again = m.FormSpec.from_dict(spec.to_dict())
    assert again.form_id == spec.form_id
    assert [f.key for f in again.fields] == [f.key for f in spec.fields]
    assert again.notify is False


def test_ready_made_field_sets():
    trial = m.trial_signup_fields()
    assert any(f.type == "consent" and f.required for f in trial)
    assert any(f.minors_sensitive for f in trial)
    assert all(isinstance(f, m.FormField) for f in m.rsvp_fields())
