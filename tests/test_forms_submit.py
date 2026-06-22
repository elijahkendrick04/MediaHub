"""Forms engine (roadmap 1.16) — build 2: validation, spam & data-hub rows."""

from __future__ import annotations

import pytest

from mediahub.data_hub import store as dh_store
from mediahub.forms import submit
from mediahub.forms.models import FormField, FormSpec


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _form(**kw):
    fields = kw.pop(
        "fields",
        [
            FormField(label="Name", required=True),
            FormField(label="Email", type="email", required=True),
            FormField(label="Count", type="number"),
            FormField(label="Size", type="select", options=["S", "M", "L"]),
            FormField(label="I agree", type="consent", required=True),
        ],
    )
    return FormSpec(title="Trial", fields=fields, **kw)


def test_validate_required_and_shapes():
    form = _form()
    _clean, errors = submit.validate(
        form, {"name": "", "email": "nope", "count": "abc", "size": "XL", "i_agree": False}
    )
    assert "name" in errors  # required
    assert "email" in errors  # bad email
    assert "count" in errors  # not a number
    assert "size" in errors  # not an option
    assert "i_agree" in errors  # required consent unticked


def test_validate_accepts_good_data():
    form = _form()
    clean, errors = submit.validate(
        form,
        {"name": "Sam", "email": "sam@club.example", "count": "3", "size": "M", "i_agree": True},
    )
    assert errors == {}
    assert clean["name"] == "Sam"
    assert clean["count"] == 3  # coerced to int
    assert clean["i_agree"] is True


def test_max_len_enforced():
    form = FormSpec(title="t", fields=[FormField(label="Note", type="textarea", max_len=5)])
    _clean, errors = submit.validate(form, {"note": "way too long"})
    assert "note" in errors


def test_honeypot_detection():
    assert submit.is_spam({"_hp": "i am a bot"})
    assert not submit.is_spam({"_hp": ""})
    assert not submit.is_spam({})


def test_record_submission_writes_a_typed_row():
    form = _form()
    data = {"name": "Sam", "email": "sam@club.example", "count": "2", "size": "S", "i_agree": True}
    result = submit.record_submission("club-a", form, data, source="form:test")
    assert result["ok"] is True
    table_id = result["table_id"]
    assert table_id
    # the form now carries the table id (caller persists it)
    assert result["form"].table_id == table_id

    table = dh_store.get_org_table("club-a", table_id)
    assert table is not None
    assert len(table.rows) == 1
    row = table.rows[0]
    assert row["name"].display == "Sam"
    assert row["email"].display == "sam@club.example"
    assert row["i_agree"].display == "Yes"
    assert row["submitted_at"].value  # timestamped


def test_record_submission_reuses_table_on_second_submit():
    form = _form()
    r1 = submit.record_submission(
        "club-a", form, {"name": "A", "email": "a@x.com", "i_agree": True}
    )
    form2 = r1["form"]  # now has table_id
    r2 = submit.record_submission(
        "club-a", form2, {"name": "B", "email": "b@x.com", "i_agree": True}
    )
    assert r1["table_id"] == r2["table_id"]
    table = dh_store.get_org_table("club-a", r2["table_id"])
    assert len(table.rows) == 2


def test_record_submission_rejects_invalid():
    form = _form()
    result = submit.record_submission("club-a", form, {"name": "", "i_agree": False})
    assert result["ok"] is False
    assert result["error"] == "validation"
    assert "name" in result["errors"]


def test_honeypot_submission_is_accepted_and_discarded():
    form = _form()
    result = submit.record_submission(
        "club-a",
        form,
        {"name": "Bot", "email": "b@x.com", "i_agree": True, "_hp": "spam"},
    )
    assert result["ok"] is True and result.get("discarded") is True
    assert result["row_id"] == ""  # nothing written


def test_minor_data_flags_table_and_cell():
    form = FormSpec(
        title="Trial",
        fields=[
            FormField(label="Child name", minors_sensitive=True),
            FormField(label="Email", type="email"),
        ],
    )
    result = submit.record_submission("club-a", form, {"child_name": "Kid", "email": "p@x.com"})
    assert result["ok"]
    table = dh_store.get_org_table("club-a", result["table_id"])
    assert table.rows[0]["child_name"].note  # safeguarding note present
    # the response table itself records that it holds minors' data
    summary = next(
        t for t in dh_store.list_org_tables("club-a") if t["table_id"] == result["table_id"]
    )
    assert "minors" in summary["description"].lower()
