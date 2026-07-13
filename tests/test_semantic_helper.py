"""Unit tests for tests/_semantic.py — the refactor-robust HTML assertion helper.

The helper is the foundation of the deep-review #129 migration (swap brittle
CSS-class scraping for stable ``data-testid`` / semantic assertions), so it earns
its own tests: identity by testid, semantic property checks, scoping, body-state
flags, and useful failure messages. If the helper is wrong, every migrated test
inherits the bug — so pin it here first.
"""

from __future__ import annotations

import pytest

from tests._semantic import (
    accessible_name,
    assert_body_flag,
    assert_control_count,
    assert_has_control,
    assert_no_control,
    control_role,
    find_controls,
    get_body,
    get_control,
    scope,
)

_PAGE = """
<html>
  <head><style>/* a comment mentioning <body class="fake"> to fool substrings */</style></head>
  <body class="mh-has-dock" data-has-dock data-page="review">
    <nav class="mh-action-dock" data-testid="action-dock" aria-label="Quick review actions"
         data-builder-url="/pack/abc">
      <a href="/make" data-testid="dock-create" aria-label="Create — start a new content pack">Create</a>
      <a href="/media-library" data-testid="dock-library" aria-label="Open the media library">Library</a>
      <button type="button" class="mh-dock-primary" data-testid="dock-approve"
              data-mh-dock-approve aria-label="Approve the highlighted card">
        <span data-testid="dock-label">Approve</span>
        <span data-testid="dock-count" data-mh-dock-count aria-hidden="true">4</span>
      </button>
    </nav>
    <button data-testid="disabled-btn" disabled>Nope</button>
    <label id="lbl-x">Search meets</label>
    <input data-testid="labelled-input" aria-labelledby="lbl-x">
  </body>
</html>
"""


# --- presence / absence -----------------------------------------------------


def test_find_controls_returns_elements():
    found = find_controls(_PAGE, "action-dock")
    assert len(found) == 1
    assert found[0].name == "nav"


def test_assert_has_control_present():
    el = assert_has_control(_PAGE, "action-dock")
    assert el.name == "nav"


def test_assert_no_control_when_absent():
    assert_no_control(_PAGE, "does-not-exist")


def test_assert_no_control_fails_when_present():
    with pytest.raises(AssertionError):
        assert_no_control(_PAGE, "action-dock")


def test_assert_has_control_fails_when_absent():
    with pytest.raises(AssertionError) as ei:
        assert_has_control(_PAGE, "ghost")
    # The failure message lists what IS available, to guide the fix.
    assert "available testids" in str(ei.value)


# --- semantic property checks ----------------------------------------------


def test_tag_and_href_checks():
    assert_has_control(_PAGE, "dock-create", tag="a", href="/make")


def test_wrong_tag_fails():
    with pytest.raises(AssertionError):
        assert_has_control(_PAGE, "dock-create", tag="button")


def test_wrong_href_fails():
    with pytest.raises(AssertionError):
        assert_has_control(_PAGE, "dock-create", href="/wrong")


def test_role_matches_native_button():
    assert_has_control(_PAGE, "dock-approve", role="button")


def test_role_matches_native_link():
    assert_has_control(_PAGE, "dock-create", role="link")


def test_role_nav_is_navigation():
    assert_has_control(_PAGE, "action-dock", role="navigation")


def test_accessible_name_prefers_aria_label():
    assert accessible_name(get_control(_PAGE, "dock-create")) == "Create — start a new content pack"
    assert_has_control(_PAGE, "dock-create", name_contains="Create")


def test_accessible_name_resolves_labelledby():
    assert accessible_name(get_control(_PAGE, "labelled-input")) == "Search meets"


def test_text_checks():
    assert_has_control(_PAGE, "dock-count", text="4")
    assert_has_control(_PAGE, "dock-label", text_contains="Approve")


def test_enabled_and_disabled():
    assert_has_control(_PAGE, "dock-approve", enabled=True)
    assert_has_control(_PAGE, "disabled-btn", enabled=False)
    with pytest.raises(AssertionError):
        assert_has_control(_PAGE, "disabled-btn", enabled=True)


def test_attrs_presence_and_value():
    # Valueless hook present:
    assert_has_control(_PAGE, "dock-count", attrs={"data-mh-dock-count": True})
    # aria-hidden value exact:
    assert_has_control(_PAGE, "dock-count", attrs={"aria-hidden": "true"})
    # Absence:
    assert_has_control(_PAGE, "dock-label", attrs={"data-mh-dock-count": False})


def test_control_role_helper_direct():
    assert control_role(get_control(_PAGE, "action-dock")) == "navigation"
    assert control_role(get_control(_PAGE, "dock-approve")) == "button"


# --- counting ---------------------------------------------------------------


def test_get_control_raises_on_duplicate():
    dup = '<div data-testid="x"></div><div data-testid="x"></div>'
    with pytest.raises(AssertionError):
        get_control(dup, "x")


def test_assert_control_count():
    dup = '<a data-testid="row"></a><a data-testid="row"></a><a data-testid="row"></a>'
    rows = assert_control_count(dup, "row", 3)
    assert len(rows) == 3
    assert_has_control(dup, "row", count=3, tag="a")


# --- scoping ----------------------------------------------------------------


def test_scope_narrows_to_one_component():
    dock = scope(_PAGE, "action-dock")
    # dock-approve lives inside the dock…
    assert_has_control(dock, "dock-approve", role="button")
    # …and scoping composes: nested scope works on the returned string.
    assert "Create" in dock


# --- body state -------------------------------------------------------------


def test_body_is_real_element_not_substring():
    # The <style> comment contains a fake <body>; get_body returns the real one.
    body = get_body(_PAGE)
    assert body.get("data-page") == "review"


def test_body_flag_present_and_absent():
    assert_body_flag(_PAGE, "has-dock", present=True)
    assert_body_flag(_PAGE, "no-such-flag", present=False)
    with pytest.raises(AssertionError):
        assert_body_flag(_PAGE, "has-dock", present=False)


def test_accepts_parsed_tree_and_string():
    from tests._semantic import parse

    tree = parse(_PAGE)
    # Passing the parsed tree works the same as passing the string.
    assert_has_control(tree, "dock-approve", role="button")
