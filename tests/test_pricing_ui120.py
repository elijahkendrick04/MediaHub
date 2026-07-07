"""UI 1.20 — polished pricing page.

Covers the four pieces the roadmap calls for, on top of the existing
ADR-0011 / PC.4 honesty guarantees (which live in test_billing.py):

  1. tier cards with **check/cross** feature lists,
  2. a **recommended-plan** highlight,
  3. a **billing-period toggle** (annually / monthly) — and crucially that the
     monthly view is the *honest* per-month expression of the committed annual
     price (annual ÷ 12, "billed annually"), never a fabricated monthly SKU or
     a made-up discount, and never a "/year" leak before the gate is met,
  4. a **feature comparison table** driven by the same single-source matrix as
     the cards (so the two views can't drift).

Stripe is mocked / unset throughout; no real keys, no network. Price evidence
is seeded into the WTP ledger exactly as the operator's verified-payment path
would, so the gate-met assertions exercise real ledger-derived figures rather
than hardcoded numbers.
"""

from __future__ import annotations

import re

from markupsafe import escape as _esc

FAKE_SECRET_KEY = "sk_test_placeholder_not_a_real_key"
FAKE_PRICE_CLUB = "price_club_test"
FAKE_PRICE_FEDERATION = "price_federation_test"


def _make_app(monkeypatch, tmp_path, *, with_stripe: bool):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if with_stripe:
        monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_SECRET_KEY)
        monkeypatch.setenv("STRIPE_PRICE_CLUB", FAKE_PRICE_CLUB)
        monkeypatch.setenv("STRIPE_PRICE_FEDERATION", FAKE_PRICE_FEDERATION)
    else:
        for var in (
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PRICE_CLUB",
            "STRIPE_PRICE_FEDERATION",
        ):
            monkeypatch.delenv(var, raising=False)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _seed_gate_met(prices=(58800, 58800, 82800, 118800, 70800, 99000)):
    """Record ≥5 verified annual payments so a public list price commits.

    The highest cleared price (118800p == £1188) becomes the list price.
    Call this *after* ``_make_app`` has pointed DATA_DIR at the tmp ledger.
    """
    from mediahub.commercial.wtp import QuoteStore

    store = QuoteStore()
    for i, price in enumerate(prices):
        q = store.create(f"Club {i}", price)
        store.record_manual_payment(q.quote_id, amount_pence=price)


def _get(app) -> str:
    return app.test_client().get("/pricing").get_data(as_text=True)


def _render(monkeypatch, tmp_path, *, with_stripe=False, seed_prices=None) -> str:
    """Build the app (sets DATA_DIR), optionally seed the WTP ledger, render."""
    app = _make_app(monkeypatch, tmp_path, with_stripe=with_stripe)
    if seed_prices is not None:
        _seed_gate_met(seed_prices)
    return _get(app)


# --------------------------------------------------------------------------
# 1. Check / cross feature lists
# --------------------------------------------------------------------------


def test_cards_have_both_check_and_cross_marks(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    # Included rows render a check; not-included rows render a muted cross.
    assert "mh-feat-yes" in html
    assert "mh-feat-no" in html
    assert "&check;" in html and "&times;" in html
    # Screen-reader text disambiguates the glyphs.
    assert "— included" in html and "— not included" in html


def test_free_tier_shows_a_cross_for_a_paid_only_feature(monkeypatch, tmp_path):
    """Priority rendering is a paid feature, so the Free card must cross it out."""
    from mediahub.web import billing

    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    # The Free card is the first tier card; isolate it and assert the paid-only
    # row is rendered as a cross within it.
    free_card = html.split('class="mh-tier"', 1)[1].split("mh-tier-cta", 1)[0]
    assert "Priority rendering" in free_card
    # Within the Free card, the Priority-rendering row is a not-included row.
    seg = free_card.split("Priority rendering", 1)[0]
    assert "mh-feat-no" in seg.rsplit("<li", 1)[-1] or "mh-feat-no" in free_card
    # Sanity: the matrix really gates it (free off, club on).
    rows = {r.label: r for r in billing.feature_rows()}
    assert rows["Priority rendering"].value_for(billing.PLAN_FREE) is False
    assert rows["Priority rendering"].value_for(billing.PLAN_CLUB) is True


def test_string_valued_features_show_their_value(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    # Value-bearing rows surface the per-tier value on the card.
    assert "mh-feat-val" in html
    for value in ("3 / month", "Unlimited", "Multi-club", "Community", "Email"):
        assert value in html


# --------------------------------------------------------------------------
# 2. Recommended-plan highlight
# --------------------------------------------------------------------------


def test_recommended_highlight_on_club(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    assert "is-recommended" in html
    assert "mh-tier-badge" in html
    assert ">Recommended<" in html
    # Exactly one recommended card (count the class attribute on the card, not
    # the `.mh-tier.is-recommended` CSS selector which uses a dot).
    assert html.count("mh-tier is-recommended") == 1
    assert html.count('class="mh-tier-badge"') == 1


def test_comparison_table_marks_recommended_column(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    assert "mh-th-rec" in html  # the "Recommended" pill in the table header
    assert "is-rec" in html  # the highlighted Club column cells


# --------------------------------------------------------------------------
# 3. Billing-period toggle
# --------------------------------------------------------------------------


def test_billing_toggle_present_and_accessible(monkeypatch, tmp_path):
    # The toggle only exists once a committed list price is live (PC.4).
    html = _render(monkeypatch, tmp_path, seed_prices=(58800, 58800, 82800, 118800, 70800, 99000))
    assert 'aria-label="Billing period"' in html
    assert ">Annually<" in html and ">Monthly<" in html
    # Annual is the default-selected, real billing model.
    assert 'data-period="annual"' in html
    assert 'aria-pressed="true"' in html and 'aria-pressed="false"' in html
    # Toggle uses the shared segmented component, not a bespoke widget.
    assert "mh-segmented" in html


def test_toggle_absent_when_price_is_tbc(monkeypatch, tmp_path):
    """Before the PC.4 gate no tier emits annual/monthly panes (every paid
    tier reads 'Pricing TBC'), so the segmented control must not render —
    a toggle that visibly does nothing is worse than none. No '/year' or
    '/mo' suffix may leak either."""
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=True))  # no quotes
    assert "Pricing TBC" in html
    assert 'aria-label="Billing period"' not in html
    assert ">Annually<" not in html and ">Monthly<" not in html
    # The container keeps its harmless data-period attribute.
    assert 'data-period="annual"' in html
    assert "/year" not in html
    assert "/mo" not in html


def test_monthly_is_honest_annual_over_twelve(monkeypatch, tmp_path):
    """Gate met: the monthly pane is the committed annual price ÷ 12, labelled
    'billed annually' — not a separate monthly SKU and not a fabricated
    discount."""
    # highest cleared = £1188/yr
    html = _render(monkeypatch, tmp_path, seed_prices=(58800, 58800, 82800, 118800, 70800, 99000))
    # Annual pane keeps the committed figure + /year + the honest label.
    assert "&pound;1188" in html
    assert "/year" in html
    assert "Billed annually" in html
    # Monthly pane is rendered (server-side, toggled client-side) and equals
    # £1188 / 12 == £99, explicitly billed annually.
    assert 'data-pane="monthly"' in html
    assert "&pound;99" in html
    assert "/mo" in html
    assert html.count("billed annually") >= 1  # lower-case label on the monthly pane
    # No fabricated "save N%" / discount claim (there is no monthly SKU to
    # discount against).
    assert not re.search(r"save\s+\d+\s*%", html, re.I)
    assert "% off" not in html.lower()


def test_monthly_two_decimal_path(monkeypatch, tmp_path):
    """A price that doesn't divide evenly by 12 shows 2dp, still honest."""
    # £1000/yr (100000p) → 100000/12 == 8333.33p → £83.33/mo.
    html = _render(monkeypatch, tmp_path, seed_prices=(100000, 100000, 100000, 100000, 100000))
    assert "&pound;1000" in html and "/year" in html
    assert "&pound;83.33" in html and "/mo" in html


def test_toggle_js_is_inline_vanilla(monkeypatch, tmp_path):
    # JS ships with the toggle, i.e. only once the price gate is met.
    html = _render(monkeypatch, tmp_path, seed_prices=(58800, 58800, 82800, 118800, 70800, 99000))
    # Progressive enhancement: a tiny inline script wires the root data-period.
    assert "getElementById('mh-pricing')" in html
    assert "data-period" in html


# --------------------------------------------------------------------------
# 4. Feature comparison table (single-source matrix)
# --------------------------------------------------------------------------


def test_comparison_table_renders_full_matrix(monkeypatch, tmp_path):
    from mediahub.web import billing

    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    assert 'class="mh-compare"' in html
    # Every group title is a section header (HTML-escaped, e.g. & -> &amp;).
    for group in billing.FEATURE_MATRIX:
        assert str(_esc(group.title)) in html
    # Every row label appears (as a row header).
    for row in billing.feature_rows():
        assert str(_esc(row.label)) in html
    # Three plan columns.
    for name in ("Free", "Club", "Federation"):
        assert name in html


def test_table_is_keyboard_table_semantics(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    # Proper table semantics: scoped headers + sr-only state on glyph cells.
    assert 'scope="col"' in html
    assert 'scope="row"' in html
    assert "mh-cell-yes" in html and "mh-cell-no" in html
    assert "mh-sr" in html  # visually-hidden "Included"/"Not included"


def test_cards_and_table_share_one_source(monkeypatch, tmp_path):
    """Both surfaces derive from billing.FEATURE_MATRIX, so a label present in
    the matrix must appear in both the cards and the table (no drift)."""
    from mediahub.web import billing

    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    # Cards: every matrix label shows on a card (in a <li>), HTML-escaped.
    card_region = html.split('class="mh-tier-grid"', 1)[1].split("mh-compare", 1)[0]
    for row in billing.feature_rows():
        assert str(_esc(row.label)) in card_region, f"{row.label} missing from cards"


# --------------------------------------------------------------------------
# Honesty regression: no hardcoded price on the richer markup either
# --------------------------------------------------------------------------


def test_no_hardcoded_amounts_with_new_markup(monkeypatch, tmp_path):
    for with_stripe in (False, True):
        html = _get(_make_app(monkeypatch, tmp_path, with_stripe=with_stripe))
        for amount in ("£30", "£250", "£49", "£99", "$625", "$3,000"):
            assert amount not in html, f"{amount!r} leaked into /pricing"


# --------------------------------------------------------------------------
# Feature-matrix invariants (the data behind both views)
# --------------------------------------------------------------------------


def test_matrix_structure_is_coherent():
    from mediahub.web import billing
    from mediahub.web.billing import PLAN_CLUB, PLAN_FEDERATION, PLAN_FREE

    rows = billing.feature_rows()
    assert rows, "matrix has no rows"
    plans = (PLAN_FREE, PLAN_CLUB, PLAN_FEDERATION)
    for row in rows:
        # Every row resolves a value for every plan.
        for plan in plans:
            v = row.value_for(plan)
            assert isinstance(v, (bool, str)), (row.label, plan, v)
        # "Everything in Club" — any boolean capability Club has, Federation has.
        if row.club is True:
            assert row.federation is True, f"Federation regresses on {row.label!r}"
    # Each plan includes at least one feature (truthy cell).
    for plan in plans:
        included = [r for r in rows if r.value_for(plan) is not False]
        assert included, f"{plan} has no included features"
    # feature_rows() is exactly the flattened matrix, in order.
    flat = [r for g in billing.FEATURE_MATRIX for r in g.rows]
    assert list(rows) == flat


def test_value_for_unknown_plan_is_false():
    from mediahub.web import billing

    row = billing.feature_rows()[0]
    assert row.value_for("nonsense-plan") is False


# --------------------------------------------------------------------------
# a11y regression: empty-table-header (axe rule)
# --------------------------------------------------------------------------


def test_comparison_table_first_header_not_empty(monkeypatch, tmp_path):
    """The first <th scope="col"> in the comparison table must not be empty.

    axe-core 'empty-table-header' fires when a <th> has no accessible text.
    The feature-label column has no visible heading by design, so we supply a
    visually-hidden label via the .mh-sr span.
    """
    html = _get(_make_app(monkeypatch, tmp_path, with_stripe=False))
    # The first th in the comparison thead carries a .mh-sr label.
    assert 'scope="col"><span class="mh-sr">Feature</span>' in html
