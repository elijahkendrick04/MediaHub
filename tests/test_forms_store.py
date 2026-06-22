"""Forms engine (roadmap 1.16) — build 2: per-club form persistence."""

from __future__ import annotations

import pytest

from mediahub.forms import store
from mediahub.forms.models import FormField, FormSpec


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _form():
    return FormSpec(title="Trial sign-up", fields=[FormField(label="Name", required=True)])


def test_save_load_list_delete():
    spec = _form()
    store.save_form("club-a", spec)
    loaded = store.load_form("club-a", spec.form_id)
    assert loaded is not None and loaded.title == "Trial sign-up"
    summaries = store.list_forms("club-a")
    assert len(summaries) == 1 and summaries[0]["n_fields"] == 1
    assert store.delete_form("club-a", spec.form_id)
    assert store.load_form("club-a", spec.form_id) is None


def test_org_isolation():
    spec = _form()
    store.save_form("club-a", spec)
    assert store.list_forms("club-b") == []
    assert store.load_form("club-b", spec.form_id) is None
