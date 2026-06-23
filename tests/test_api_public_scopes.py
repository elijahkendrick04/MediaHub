"""1.21 public API — scope catalogue invariants."""

from __future__ import annotations

from mediahub.api_public import scopes as sc


def test_default_scopes_are_read_only():
    # No write/approve/manage scope may sneak into the default grant.
    for s in sc.DEFAULT_SCOPES:
        assert s.endswith(":read") or s == "content:export", s


def test_validate_drops_unknown_and_dedupes_and_orders():
    out = sc.validate_scopes(["cards:approve", "bogus:thing", "runs:read", "runs:read", ""])
    assert out == [s for s in sc.ALL_SCOPES if s in {"cards:approve", "runs:read"}]
    assert "bogus:thing" not in out
    assert len(out) == len(set(out))


def test_validate_is_case_insensitive():
    assert sc.validate_scopes(["RUNS:READ"]) == ["runs:read"]


def test_validate_empty():
    assert sc.validate_scopes(None) == []
    assert sc.validate_scopes([]) == []


def test_has_scope():
    assert sc.has_scope(["runs:read", "cards:approve"], "cards:approve")
    assert not sc.has_scope(["runs:read"], "cards:approve")
    assert not sc.has_scope([], "runs:read")


def test_groups_only_reference_known_scopes():
    for group, members in sc.SCOPE_GROUPS.items():
        for s in members:
            assert sc.is_known(s), f"{group} references unknown scope {s}"


def test_every_scope_appears_in_some_group():
    grouped = {s for members in sc.SCOPE_GROUPS.values() for s in members}
    assert grouped == set(sc.ALL_SCOPES)


def test_approve_is_distinct_from_write():
    # The human-publish signal must never be folded into a plain write grant.
    assert "cards:approve" in sc.SCOPES
    assert "cards:approve" not in sc.SCOPE_GROUPS["Ingest"]
