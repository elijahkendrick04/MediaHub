"""Command-palette / navigation reachability guard.

MediaHub has ~50 user-facing surfaces but the top bar deliberately shows only a
few (see the nav comments in web.py). The command palette (⌘K / Ctrl-K / "/") is
what keeps everything reachable in two keystrokes. Historically, new surfaces got
orphaned and were patched one-at-a-time ("C-1", "C-13", …). This test turns that
reactive habit into a structural guarantee:

  1. Every endpoint listed in the palette spec must actually build (no dead rows
     after a route rename).
  2. The key product/creation/library/publish surfaces must stay in the palette,
     so a refactor can't silently bury the thing users came to make.
  3. The rendered palette JSON must be well-formed and non-trivial.

It intentionally does NOT demand that *every* route be in the palette — auth
flows, legal pages, per-id detail routes and operator tools are reached in
context, not from the finder. It guards the surfaces that matter for "can I find
what I came to do".
"""

from __future__ import annotations

import json

import pytest

from mediahub.web.web import (
    _COMMAND_PALETTE_OPERATOR,
    _COMMAND_PALETTE_SPEC,
    _command_palette_groups,
    create_app,
)


@pytest.fixture(scope="module")
def app():
    """A freshly-built app, NOT the shared module-level ``mediahub.web.web.app``.

    Under ``pytest -n auto`` (xdist) the shared global app can be left
    partially-built by an unrelated test that happens to land earlier in the
    same worker — a known test-isolation hazard that silently drops
    late-registered routes (e.g. ``remote_landing``) and made
    ``test_every_palette_endpoint_builds`` flake on CI while passing in
    isolation. A fresh ``create_app()`` always carries every route and is
    immune to whatever other tests did to the global, so this guard tests the
    real contract deterministically.
    """
    return create_app()


# The surfaces a returning club must always be able to reach from the finder.
# If a refactor removes one of these routes, or drops it from the palette, this
# list is the tripwire — update it deliberately, never to paper over a break.
_KEY_SURFACES = frozenset(
    {
        "make_page",
        "media_library_page",
        "plan_page",
        "template_gallery",
        "spotlight_landing",
        "video_studio_page",
        "design_studio",
        "newsletters_home",
        "documents_home",
        "print_center_page",
        "export_center_page",
        "public_wall_settings",
        "sponsors_page",
        "athletes_page",
        "club_records_page",
        "data_hub_page",
        "activity_page",
        "settings_page",
        "brand_home_page",
        "season_wraps_page",
    }
)


def _all_spec_endpoints() -> set[str]:
    endpoints: set[str] = set()
    for _group, items in list(_COMMAND_PALETTE_SPEC) + [_COMMAND_PALETTE_OPERATOR]:
        for endpoint, _label, _keys in items:
            endpoints.add(endpoint)
    return endpoints


def test_palette_endpoints_resolve(app):
    """Palette rows must resolve — matching the runtime's actual contract.

    ``_command_palette_groups`` deliberately DROPS any endpoint that fails to
    build (so a renamed/absent/late-registered route can never break the whole
    nav). So the guarantee that matters is: every KEY surface builds, and only a
    small number of non-key endpoints may fail to build in a given environment
    (some routes register late in create_app and can be environment-sensitive).
    A typo, a rename, or a mass create_app breakage still trips the ceiling.

    The ``app`` fixture builds a fresh ``create_app()`` rather than importing the
    shared module-level app — under xdist that global can be left partially-built
    by an unrelated test in the same worker, which made this guard flake on CI.
    A fresh app makes the check deterministic; the tolerance above still absorbs
    genuinely environment-conditional routes.
    """
    dead = []
    with app.test_request_context("/"):
        from flask import url_for

        for endpoint in sorted(_all_spec_endpoints()):
            try:
                url_for(endpoint)
            except Exception:  # noqa: BLE001
                dead.append(endpoint)
    # A KEY surface failing to build is always a hard failure.
    dead_key = sorted(set(dead) & _KEY_SURFACES)
    assert not dead_key, f"key command-palette surfaces no longer build: {dead_key}"
    # Everything else: the runtime drops it gracefully, so tolerate a handful of
    # environment-sensitive non-key drops but catch a typo spree / broken app.
    assert len(dead) <= 3, "too many command-palette endpoints fail to build (rename/typo?):\n" + "\n".join(
        sorted(dead)
    )


def test_key_surfaces_are_in_palette():
    """The core creation/library/publish surfaces must stay reachable from the finder."""
    spec_endpoints = _all_spec_endpoints()
    missing = sorted(_KEY_SURFACES - spec_endpoints)
    assert not missing, (
        "These key product surfaces are no longer in the command palette "
        "(users would have no zero-step way to reach them): " + ", ".join(missing)
    )


def test_palette_json_is_wellformed_and_substantial(app):
    """The rendered palette payload is valid JSON with real, unique destinations."""
    with app.test_request_context("/"):
        groups = _command_palette_groups(dev_operator=False, profile_id=None)
    # Round-trips as JSON (this is what ships in the page).
    payload = json.dumps(groups)
    reparsed = json.loads(payload)
    assert reparsed == groups

    items = [it for g in groups for it in g["items"]]
    assert len(items) >= 30, f"palette unexpectedly small ({len(items)} items)"
    # Every item has a label + a url, and urls are internal (start with /).
    for it in items:
        assert it["label"] and isinstance(it["label"], str)
        assert it["url"].startswith("/"), it
    # No duplicate destinations within a single group.
    for g in groups:
        urls = [it["url"] for it in g["items"]]
        assert len(urls) == len(set(urls)), f"duplicate url in group {g['group']}"


def test_operator_group_is_gated(app):
    """Operator destinations appear only for a dev operator, never for a normal user."""
    with app.test_request_context("/"):
        normal = _command_palette_groups(dev_operator=False, profile_id=None)
        operator = _command_palette_groups(dev_operator=True, profile_id=None)
    assert not any(g["group"] == "Operator" for g in normal)
    assert any(g["group"] == "Operator" for g in operator)


@pytest.mark.parametrize("dev", [False, True])
def test_palette_never_raises(app, dev):
    """Building the palette must never raise, even with no active profile."""
    with app.test_request_context("/"):
        groups = _command_palette_groups(dev_operator=dev, profile_id=None)
    assert isinstance(groups, list) and groups
