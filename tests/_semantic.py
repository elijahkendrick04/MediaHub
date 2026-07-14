"""Semantic, refactor-robust assertions for MediaHub's server-rendered HTML.

**Why this exists.** Hundreds of tests scrape ``web.py``'s templates by literal
CSS class (``assert 'class="mh-action-dock"' in html``), literal tag, ``data-*``
string, or hardcoded URL. Those assertions pin *implementation detail*: rename a
class or restructure the markup during the ``web.py`` blueprint decomposition and
huge swaths of the suite break even though every control still works. That
brittleness actively blocks the refactor the suite most needs (deep-review #129).

**What replaces it.** Assert that the *control or behaviour* exists via a stable
hook — a ``data-testid`` on the element — and, when it matters, that the element
is the right *kind* of thing (a button, a link, labelled thus, pointing there).
A template refactor that keeps the control keeps the ``data-testid``, so the test
keeps passing; a refactor that drops the control fails the test, as it should.
This does not weaken what is verified — it swaps "a CSS class string is present
somewhere in the blob" for "a control with this identity and these properties
exists" — which is strictly *more* precise.

Backed by BeautifulSoup (a declared core dependency) over the stdlib
``html.parser`` backend, so it parses real elements (not substrings) with no
extra C-extension in the path.

Typical use::

    from tests._semantic import assert_has_control, assert_no_control, scope

    # A control exists, is a link, and points where url_for() resolves:
    assert_has_control(html, "dock-create", tag="a", href=url_for("make_page"))

    # A control is absent (e.g. the dock on a page that must not carry it):
    assert_no_control(html, "action-dock")

    # Scope to one component, then assert on its innards:
    dock = scope(html, "action-dock")
    assert_has_control(dock, "dock-approve", role="button")

The helpers accept either a raw HTML string or an already-parsed element
(a :class:`bs4.Tag`), so scoping composes without re-parsing surprises.
"""

from __future__ import annotations

from typing import Iterable

from bs4 import BeautifulSoup, Tag

__all__ = [
    "parse",
    "find_controls",
    "get_control",
    "assert_has_control",
    "assert_no_control",
    "assert_control_count",
    "scope",
    "get_body",
    "assert_body_flag",
    "accessible_name",
    "control_role",
]

# Native (implicit) ARIA roles for the handful of elements MediaHub's controls
# actually use. Lets a test say role="button" and match a real <button> without
# forcing an explicit role="" attribute onto the markup.
_IMPLICIT_ROLES = {
    "button": "button",
    "nav": "navigation",
    "main": "main",
    "header": "banner",
    "footer": "contentinfo",
    "form": "form",
    "dialog": "dialog",
    "table": "table",
    "ul": "list",
    "ol": "list",
    "li": "listitem",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
}


def _to_soup(html_or_tag: str | Tag) -> BeautifulSoup | Tag:
    """Accept a raw HTML string or an already-parsed element uniformly."""
    if isinstance(html_or_tag, (BeautifulSoup, Tag)):
        return html_or_tag
    if not isinstance(html_or_tag, str):
        raise TypeError(
            f"expected an HTML string or a bs4 element, got {type(html_or_tag).__name__}"
        )
    return BeautifulSoup(html_or_tag, "html.parser")


def parse(html: str | Tag) -> BeautifulSoup | Tag:
    """Parse HTML once so a test can run several queries against one tree."""
    return _to_soup(html)


def _norm(text: str | None) -> str:
    """Collapse runs of whitespace so text/label matches ignore formatting."""
    return " ".join((text or "").split())


def control_role(el: Tag) -> str | None:
    """The element's effective ARIA role: explicit ``role`` else its native one.

    A bare ``<a>`` with no ``href`` is not a link, so it earns no implicit role
    (mirrors the accessibility model the tests care about)."""
    explicit = el.get("role")
    if explicit:
        return _norm(explicit)
    if el.name == "a":
        return "link" if el.get("href") is not None else None
    if el.name == "input":
        itype = (el.get("type") or "text").lower()
        return {"button": "button", "submit": "button", "reset": "button", "checkbox": "checkbox"}.get(
            itype, "textbox"
        )
    return _IMPLICIT_ROLES.get(el.name)


def accessible_name(el: Tag) -> str:
    """Approximate the element's accessible name (aria-label > labelledby > text).

    Enough of the ARIA name algorithm for asserting a control is labelled about
    the right thing — not a full a11y engine."""
    label = el.get("aria-label")
    if label:
        return _norm(label)
    labelledby = el.get("aria-labelledby")
    if labelledby:
        root = el
        while root.parent is not None:
            root = root.parent
        parts: list[str] = []
        for ref in labelledby.split():
            target = root.find(id=ref) if hasattr(root, "find") else None
            if target:
                parts.append(_norm(target.get_text()))
        if parts:
            return _norm(" ".join(parts))
    return _norm(el.get_text())


def find_controls(html: str | Tag, testid: str) -> list[Tag]:
    """Every element carrying ``data-testid="<testid>"``, in document order."""
    root = _to_soup(html)
    return root.find_all(attrs={"data-testid": testid})


def _describe_available(html: str | Tag) -> str:
    """List the testids that *are* present — turns a miss into a useful message."""
    root = _to_soup(html)
    seen: list[str] = []
    for el in root.find_all(attrs={"data-testid": True}):
        tid = el.get("data-testid")
        if tid and tid not in seen:
            seen.append(tid)
    if not seen:
        return "no data-testid attributes are present in the HTML"
    return "available testids: " + ", ".join(sorted(seen))


def get_control(html: str | Tag, testid: str) -> Tag:
    """The single element with ``testid``; fail loudly on zero or many."""
    found = find_controls(html, testid)
    if len(found) == 1:
        return found[0]
    if not found:
        raise AssertionError(
            f"expected a control with data-testid={testid!r}, found none "
            f"({_describe_available(html)})"
        )
    raise AssertionError(
        f"expected exactly one control with data-testid={testid!r}, found "
        f"{len(found)} — pass count= if that is intended"
    )


def assert_control_count(html: str | Tag, testid: str, count: int) -> list[Tag]:
    """Assert exactly ``count`` controls carry ``testid`` (e.g. N tabs, N rows)."""
    found = find_controls(html, testid)
    assert len(found) == count, (
        f"expected {count} control(s) with data-testid={testid!r}, found {len(found)}"
    )
    return found


def assert_no_control(html: str | Tag, testid: str) -> None:
    """Assert *no* element carries ``testid`` (a control must be absent here)."""
    found = find_controls(html, testid)
    assert not found, (
        f"expected no control with data-testid={testid!r}, found {len(found)}"
    )


def _check_attrs(el: Tag, attrs: dict[str, str | bool]) -> None:
    for name, expected in attrs.items():
        if expected is True:
            assert el.has_attr(name), f"control missing attribute {name!r}"
        elif expected is False:
            assert not el.has_attr(name), f"control unexpectedly has attribute {name!r}"
        else:
            actual = el.get(name)
            assert actual == expected, (
                f"control attribute {name!r}: expected {expected!r}, got {actual!r}"
            )


def assert_has_control(
    html: str | Tag,
    testid: str,
    *,
    tag: str | None = None,
    role: str | None = None,
    name: str | None = None,
    name_contains: str | None = None,
    href: str | None = None,
    text: str | None = None,
    text_contains: str | None = None,
    enabled: bool | None = None,
    count: int | None = None,
    attrs: dict[str, str | bool] | None = None,
) -> Tag | list[Tag]:
    """Assert a control identified by ``data-testid`` exists — and, optionally,
    that it is the right kind of thing.

    With no keyword filters this simply asserts the control is present (exactly
    one, unless ``count`` is given). The optional checks let a test pin the
    control's *identity* without pinning its CSS class:

    * ``tag`` — the element name (``"a"``, ``"button"``, ``"nav"``…).
    * ``role`` — the effective ARIA role (explicit ``role`` or native), so
      ``role="button"`` matches a real ``<button>``.
    * ``name`` / ``name_contains`` — the accessible name (aria-label, else
      labelledby, else text): exact (normalised) or substring.
    * ``href`` — exact link target; pair with ``url_for(...)`` to keep the
      one-source-of-truth URL contract.
    * ``text`` / ``text_contains`` — normalised inner text: exact or substring.
    * ``enabled`` — ``True`` asserts not ``disabled``; ``False`` asserts it is.
    * ``attrs`` — extra attribute checks; a value of ``True``/``False`` asserts
      mere presence/absence (good for valueless hooks like ``data-mh-dock-count``).
    * ``count`` — expect exactly N matches and return the list.

    Returns the matched :class:`bs4.Tag` (or the list when ``count`` is set) so
    the caller can scope further assertions to it.
    """
    if count is not None:
        found = assert_control_count(html, testid, count)
        for el in found:
            _assert_one(el, testid, tag, role, name, name_contains, href, text, text_contains, enabled, attrs)
        return found
    el = get_control(html, testid)
    _assert_one(el, testid, tag, role, name, name_contains, href, text, text_contains, enabled, attrs)
    return el


def _assert_one(
    el: Tag,
    testid: str,
    tag: str | None,
    role: str | None,
    name: str | None,
    name_contains: str | None,
    href: str | None,
    text: str | None,
    text_contains: str | None,
    enabled: bool | None,
    attrs: dict[str, str | bool] | None,
) -> None:
    where = f"control data-testid={testid!r}"
    if tag is not None:
        assert el.name == tag, f"{where}: expected <{tag}>, got <{el.name}>"
    if role is not None:
        actual = control_role(el)
        assert actual == role, f"{where}: expected role {role!r}, got {actual!r}"
    if name is not None:
        actual = accessible_name(el)
        assert actual == name, f"{where}: expected accessible name {name!r}, got {actual!r}"
    if name_contains is not None:
        actual = accessible_name(el)
        assert name_contains in actual, (
            f"{where}: accessible name {actual!r} does not contain {name_contains!r}"
        )
    if href is not None:
        actual = el.get("href")
        assert actual == href, f"{where}: expected href {href!r}, got {actual!r}"
    if text is not None:
        actual = _norm(el.get_text())
        assert actual == text, f"{where}: expected text {text!r}, got {actual!r}"
    if text_contains is not None:
        actual = _norm(el.get_text())
        assert text_contains in actual, (
            f"{where}: text {actual!r} does not contain {text_contains!r}"
        )
    if enabled is not None:
        is_disabled = el.has_attr("disabled") or el.get("aria-disabled") == "true"
        if enabled:
            assert not is_disabled, f"{where}: expected enabled, but it is disabled"
        else:
            assert is_disabled, f"{where}: expected disabled, but it is enabled"
    if attrs:
        _check_attrs(el, attrs)


def scope(html: str | Tag, testid: str) -> str:
    """Outer HTML of the single element with ``testid``, for nested assertions.

    Replaces brittle ``html[html.find('class="x"'):html.find('</nav>')]`` string
    slicing with a parse-accurate boundary::

        dock = scope(html, "action-dock")
        assert_has_control(dock, "dock-approve", role="button")
    """
    return str(get_control(html, testid))


def get_body(html: str | Tag) -> Tag:
    """The document ``<body>`` element (its real attributes, not a substring).

    Robust where an inlined ``<style>`` block or a comment contains the literal
    text ``<body`` — BeautifulSoup returns the actual element."""
    body = _to_soup(html).find("body")
    assert body is not None, "no <body> element found in the HTML"
    return body


def assert_body_flag(html: str | Tag, name: str, present: bool = True) -> None:
    """Assert a page-level state ``data-<name>`` on ``<body>`` (e.g. has-dock).

    Page-mode flags aren't controls, so they get a semantic ``data-*`` state
    hook rather than a CSS class the stylesheet happens to key on."""
    body = get_body(html)
    attr = f"data-{name}"
    if present:
        assert body.has_attr(attr), (
            f"expected <body> to carry {attr} state flag, attributes were "
            f"{sorted(body.attrs)}"
        )
    else:
        assert not body.has_attr(attr), (
            f"expected <body> NOT to carry {attr}, but it does"
        )


def _iter_testids(html: str | Tag) -> Iterable[str]:
    for el in _to_soup(html).find_all(attrs={"data-testid": True}):
        tid = el.get("data-testid")
        if tid:
            yield tid
