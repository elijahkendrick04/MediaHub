# tests

Automatic checks (using a tool called pytest) that make sure MediaHub still works
after a change. Run them all with `make test`. If a check goes red, something
broke and needs fixing before it ships.

## Checking the web pages the right way

When a test needs to check that a button, link, or other control is on a page,
look for its **`data-testid`** hook instead of hunting for a CSS class name in the
raw HTML. Class names are styling — they get renamed when we tidy the page up, and
a test that looks for one breaks even though the button still works.

Use the small helper in `_semantic.py`:

```python
from tests._semantic import assert_has_control, assert_no_control, scope

assert_has_control(html, "dock-create", tag="a", href=url_for("make_page"))
assert_no_control(html, "action-dock")   # this control should NOT be here
```

It checks the *control* is really there — the right kind of element, pointing the
right place — which is a stronger check than "this class string is somewhere in
the page". The full why-and-how (and the plan to move the older tests over) is in
[`docs/SEMANTIC_TEST_MIGRATION.md`](../docs/SEMANTIC_TEST_MIGRATION.md).

Checks that read a `.css` or `.js` file straight off disk, or that test a plain
helper function's output, are fine as they are — they're not looking at page
markup, so leave them alone.
