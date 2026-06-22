"""Email & newsletter composer (roadmap 1.17) — build 1: persistence & publish."""

from __future__ import annotations

import pytest

from mediahub.email_design import models as m
from mediahub.email_design import store


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _spec(title="June Roundup", body="v1"):
    return m.NewsletterSpec(
        title=title, sections=[m.Section(blocks=[m.text(body)])]
    )


def test_save_load_list_delete():
    spec = _spec()
    store.save_newsletter("club-a", spec)
    loaded = store.load_newsletter("club-a", spec.newsletter_id)
    assert loaded is not None and loaded.title == "June Roundup"
    summaries = store.list_newsletters("club-a")
    assert len(summaries) == 1 and summaries[0]["published"] is False
    assert summaries[0]["n_sections"] == 1
    assert store.delete_newsletter("club-a", spec.newsletter_id)
    assert store.load_newsletter("club-a", spec.newsletter_id) is None


def test_org_isolation():
    spec = _spec()
    store.save_newsletter("club-a", spec)
    assert store.list_newsletters("club-b") == []
    assert store.load_newsletter("club-b", spec.newsletter_id) is None


def test_publish_creates_token_and_frozen_snapshot():
    spec = _spec(body="published-text")
    store.save_newsletter("club-a", spec)
    token = store.publish_newsletter("club-a", spec.newsletter_id)
    assert token and len(token) > 20

    # editing the draft does NOT change the live snapshot until re-publish
    edited = m.NewsletterSpec(
        newsletter_id=spec.newsletter_id,
        title="June Roundup",
        sections=[m.Section(blocks=[m.text("v2-draft")])],
    )
    store.save_newsletter("club-a", edited)
    published = store.load_published("club-a", spec.newsletter_id)
    assert published is not None
    assert published.sections[0].blocks[0].props["text"] == "published-text"

    # the draft itself did change
    draft = store.load_newsletter("club-a", spec.newsletter_id)
    assert draft.sections[0].blocks[0].props["text"] == "v2-draft"


def test_resolve_token_round_trip_and_scope():
    spec = _spec()
    store.save_newsletter("club-a", spec)
    token = store.publish_newsletter("club-a", spec.newsletter_id)
    ref = store.resolve_token(token)
    assert ref == ("club-a", spec.newsletter_id)
    assert store.resolve_token("not-a-real-token") is None
    assert store.resolve_token("") is None


def test_unpublish_revokes_token_structurally():
    spec = _spec()
    store.save_newsletter("club-a", spec)
    token = store.publish_newsletter("club-a", spec.newsletter_id)
    assert store.resolve_token(token) is not None
    assert store.unpublish_newsletter("club-a", spec.newsletter_id)
    # old URL resolves to nothing; published snapshot is gone
    assert store.resolve_token(token) is None
    assert store.load_published("club-a", spec.newsletter_id) is None
    # record reflects unpublished state
    rec = store.newsletter_record("club-a", spec.newsletter_id)
    assert rec["published"] is False and rec["public_token"] == ""


def test_republish_keeps_same_token():
    spec = _spec()
    store.save_newsletter("club-a", spec)
    t1 = store.publish_newsletter("club-a", spec.newsletter_id)
    t2 = store.publish_newsletter("club-a", spec.newsletter_id)
    assert t1 == t2


def test_delete_drops_public_token():
    spec = _spec()
    store.save_newsletter("club-a", spec)
    token = store.publish_newsletter("club-a", spec.newsletter_id)
    store.delete_newsletter("club-a", spec.newsletter_id)
    assert store.resolve_token(token) is None


def test_publish_missing_newsletter_returns_none():
    assert store.publish_newsletter("club-a", "nope") is None
    assert store.newsletter_record("club-a", "nope") is None
