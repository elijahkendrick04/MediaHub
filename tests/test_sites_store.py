"""Microsite engine (roadmap 1.16) — build 1: persistence, publish & tokens."""

from __future__ import annotations

import pytest

from mediahub.documents.models import text
from mediahub.sites import store
from mediahub.sites.models import SitePage, SiteSection, SiteSpec


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _spec(title="Otters", body="v1"):
    return SiteSpec(
        title=title,
        pages=[SitePage(title="Home", slug="", sections=[SiteSection(blocks=[text(body)])])],
    )


def test_save_load_list_delete():
    spec = _spec()
    store.save_site("club-a", spec)
    loaded = store.load_site("club-a", spec.site_id)
    assert loaded is not None and loaded.title == "Otters"
    summaries = store.list_sites("club-a")
    assert len(summaries) == 1 and summaries[0]["published"] is False
    assert store.delete_site("club-a", spec.site_id)
    assert store.load_site("club-a", spec.site_id) is None


def test_org_isolation():
    spec = _spec()
    store.save_site("club-a", spec)
    # another org cannot see or load it
    assert store.list_sites("club-b") == []
    assert store.load_site("club-b", spec.site_id) is None


def test_publish_creates_token_and_frozen_snapshot():
    spec = _spec(body="published-text")
    store.save_site("club-a", spec)
    token = store.publish_site("club-a", spec.site_id)
    assert token and len(token) > 20

    # the public token resolves to exactly this org+site
    assert store.resolve_token(token) == ("club-a", spec.site_id)

    # editing the draft afterwards does NOT change the live snapshot
    edited = SiteSpec(
        title="Otters",
        site_id=spec.site_id,
        pages=[SitePage(title="Home", slug="", sections=[SiteSection(blocks=[text("v2-draft")])])],
    )
    store.save_site("club-a", edited)
    published = store.load_published("club-a", spec.site_id)
    assert published is not None
    pub_text = published.pages[0].sections[0].blocks[0].props["text"]
    assert pub_text == "published-text"  # frozen at publish, not the new draft

    # re-publishing refreshes the snapshot and keeps the same token
    token2 = store.publish_site("club-a", spec.site_id)
    assert token2 == token
    assert (
        store.load_published("club-a", spec.site_id).pages[0].sections[0].blocks[0].props["text"]
        == "v2-draft"
    )


def test_unpublish_revokes_token_structurally():
    spec = _spec()
    store.save_site("club-a", spec)
    token = store.publish_site("club-a", spec.site_id)
    assert store.unpublish_site("club-a", spec.site_id)
    # the old URL resolves to nothing, and the snapshot is no longer served
    assert store.resolve_token(token) is None
    assert store.load_published("club-a", spec.site_id) is None


def test_delete_removes_token():
    spec = _spec()
    store.save_site("club-a", spec)
    token = store.publish_site("club-a", spec.site_id)
    store.delete_site("club-a", spec.site_id)
    assert store.resolve_token(token) is None


def test_resolve_token_garbage():
    assert store.resolve_token("") is None
    assert store.resolve_token("not-a-real-token") is None


def test_site_password():
    spec = _spec()
    store.save_site("club-a", spec)
    assert store.has_password("club-a", spec.site_id) is False
    assert store.check_site_password("club-a", spec.site_id, "anything") is True  # not gated

    assert store.set_site_password("club-a", spec.site_id, "letmein")
    assert store.has_password("club-a", spec.site_id) is True
    assert store.check_site_password("club-a", spec.site_id, "letmein") is True
    assert store.check_site_password("club-a", spec.site_id, "wrong") is False

    # the hash is never surfaced in the record
    rec = store.site_record("club-a", spec.site_id)
    assert "password" not in rec and rec["has_password"] is True

    # clearing it un-gates
    store.set_site_password("club-a", spec.site_id, "")
    assert store.has_password("club-a", spec.site_id) is False


def test_save_preserves_publish_state():
    spec = _spec()
    store.save_site("club-a", spec)
    token = store.publish_site("club-a", spec.site_id)
    # a plain save must not silently unpublish
    store.save_site("club-a", spec)
    assert store.resolve_token(token) == ("club-a", spec.site_id)
