"""UI 1.20 — polished pricing page (/pricing).

Covers the four deliverables of the roadmap item and the honesty rules that
constrain them:

  * tier cards with **check/cross** feature lists (matrix-driven),
  * the **recommended-plan** highlight (Club),
  * a **billing-period toggle** — implemented honestly as a per-year/per-month
    *display* toggle of the same annual plan (MediaHub bills annually only, so
    the per-month figure is the annual price ÷ 12, always shown "billed
    annually"; it is **never a separate, invented monthly price**), and
  * a **feature comparison table**.

The ADR-0011 / PC.4 rule that NO price amount is ever hardcoded still holds:
the only real figure is the evidence-gated annual list price from the WTP
ledger, and the per-month figure is derived from it. With the gate unmet the
page shows "Pricing TBC" and renders no number and no toggle.

Stripe is never contacted; the WTP gate is driven by recording manual payments
against the ledger (the same path test_billing.py uses).
"""

from __future__ import annotations

import re

import pytest
from markupsafe import escape as _h

from mediahub.web import auth, billing


def _esc(text: str) -> str:
    """The exact HTML-escaped form the page renders text as (via web._h)."""
    return str(_h(text))


# --------------------------------------------------------------------------- #
# App / ledger harness
# --------------------------------------------------------------------------- #
def _make_app(monkeypatch, tmp_path, *, with_stripe: bool = False):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    keys = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_CLUB", "STRIPE_PRICE_FEDERATION")
    if with_stripe:
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder_not_a_real_key")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_placeholder")
        monkeypatch.setenv("STRIPE_PRICE_CLUB", "price_club_test")
        monkeypatch.setenv("STRIPE_PRICE_FEDERATION", "price_federation_test")
    else:
        for var in keys:
            monkeypatch.delenv(var, raising=False)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _seed_gate(prices_pence):
    """Record N paid annual quotes so public_list_price commits (≥5 clubs)."""
    from mediahub.commercial.wtp import QuoteStore

    store = QuoteStore()
    for i, price in enumerate(prices_pence):
        q = store.create(f"Club {i}", price)
        store.record_manual_payment(q.quote_id, amount_pence=price)
    return store


def _gate_met_app(monkeypatch, tmp_path, *, top_pence=118800, with_stripe=False):
    """An app whose WTP gate is met with ``top_pence`` as the highest cleared
    annual price (so the Club card shows a committed price + period toggle)."""
    app = _make_app(monkeypatch, tmp_path, with_stripe=with_stripe)
    # Five distinct clubs, the highest of which paid ``top_pence``.
    _seed_gate([58800, 58800, 82800, 70800, top_pence])
    return app


def _html(app, path="/pricing"):
    return app.test_client().get(path).get_data(as_text=True)


# --------------------------------------------------------------------------- #
# 1 — comparison matrix data model (billing.py, single source of truth)
# --------------------------------------------------------------------------- #
def _truthy(cell) -> bool:
    """A cell counts as 'included' when True or a non-empty value string."""
    return cell is True or (isinstance(cell, str) and bool(cell.strip()))


class TestComparisonMatrix:
    def test_rows_present_and_grouped(self):
        assert billing.COMPARISON_ROWS, "matrix must not be empty"
        groups = billing.comparison_groups()
        assert groups, "comparison_groups must yield at least one group"
        # Every row is accounted for exactly once, in declaration order.
        flat = [r for _g, rows in groups for r in rows]
        assert flat == list(billing.COMPARISON_ROWS)
        # Group names are coalesced (no consecutive duplicate headings).
        names = [g for g, _ in groups]
        assert len(names) == len(set(names)), "a group heading was split/repeated"

    def test_cells_are_bool_or_nonempty_str(self):
        for row in billing.COMPARISON_ROWS:
            for plan in (auth.PLAN_FREE, auth.PLAN_CLUB, auth.PLAN_FEDERATION):
                cell = billing.cell_for(row, plan)
                assert isinstance(cell, (bool, str)), f"{row.label}/{plan}: {cell!r}"
                if isinstance(cell, str):
                    assert cell.strip(), f"{row.label}/{plan} is an empty value string"

    def test_cell_for_maps_plan_to_attribute(self):
        row = billing.COMPARISON_ROWS[0]
        assert billing.cell_for(row, auth.PLAN_FREE) == row.free
        assert billing.cell_for(row, auth.PLAN_CLUB) == row.club
        assert billing.cell_for(row, auth.PLAN_FEDERATION) == row.federation
        # An unknown plan (e.g. the operator-only 'owner' tier) reads as ✗.
        assert billing.cell_for(row, "owner") is False

    def test_card_rows_are_flagged_subset(self):
        card = billing.card_rows()
        assert card, "at least one card-highlight row is expected"
        assert all(r.card for r in card)
        assert set(card).issubset(set(billing.COMPARISON_ROWS))
        # The card list must contain genuine cross marks (a ✗ on a lower tier)
        # so the cards actually show check/cross, not all ✓.
        assert any(billing.cell_for(r, auth.PLAN_FREE) is False for r in card)

    def test_matrix_is_monotonic_up_the_tiers(self):
        """Capability only ever increases Free → Club → Federation."""
        for row in billing.COMPARISON_ROWS:
            free = billing.cell_for(row, auth.PLAN_FREE)
            club = billing.cell_for(row, auth.PLAN_CLUB)
            fed = billing.cell_for(row, auth.PLAN_FEDERATION)
            if _truthy(free):
                assert _truthy(club), f"{row.label}: Free has it but Club does not"
            if _truthy(club):
                assert _truthy(fed), f"{row.label}: Club has it but Federation does not"

    def test_federation_is_the_superset(self):
        """The top tier includes every feature (no ✗ on Federation)."""
        for row in billing.COMPARISON_ROWS:
            assert _truthy(billing.cell_for(row, auth.PLAN_FEDERATION)), row.label

    def test_matrix_carries_no_price(self):
        """Like TIERS, the matrix is copy-only — never a currency amount."""
        blob = " ".join(
            str(getattr(r, f))
            for r in billing.COMPARISON_ROWS
            for f in ("label", "group", "free", "club", "federation")
        )
        assert not re.search(r"[£$€]\s*\d", blob), "a price leaked into the matrix"


# --------------------------------------------------------------------------- #
# 2 — page render: structure that is always present (gate unmet, signed out)
# --------------------------------------------------------------------------- #
class TestPricingStructure:
    @pytest.fixture
    def html(self, monkeypatch, tmp_path):
        return _html(_make_app(monkeypatch, tmp_path, with_stripe=False))

    def test_three_tiers_render(self, html):
        for name in ("Free", "Club", "Federation"):
            assert name in html

    def test_recommended_highlight_on_club(self, html):
        assert "mh-rec-badge" in html
        assert "Recommended" in html
        assert "mh-plan-card is-rec" in html  # the highlighted card class

    def test_cards_have_check_and_cross(self, html):
        # Both a ✓ and a ✗ appear in the per-tier card feature lists.
        assert "mh-feat-check" in html
        assert "mh-feat-x" in html
        assert 'class="mh-feat mh-feat-no"' in html  # a not-included line exists
        # ✗ rows announce exclusion to assistive tech (the glyph is aria-hidden).
        assert "Not included: " in html

    def test_comparison_table_present_with_every_row(self, html):
        assert 'class="mh-compare-tbl"' in html
        assert "Compare every plan" in html
        # Every group heading and every feature label is rendered (escaped).
        for group, rows in billing.comparison_groups():
            assert _esc(group) in html, f"missing group heading: {group}"
            for row in rows:
                assert _esc(row.label) in html, f"missing comparison row: {row.label}"

    def test_comparison_cells_have_screenreader_labels(self, html):
        # Boolean cells expose text for assistive tech, not just a glyph.
        assert "Included" in html
        assert "Not included" in html
        assert "mh-sr-only" in html

    def test_pricing_nav_link_is_active(self, html):
        # active="pricing" highlights the Pricing nav item (signed-out chrome).
        assert re.search(r'href="/pricing"[^>]*class="active"', html), html[:0] or "nav not active"


# --------------------------------------------------------------------------- #
# 3 — honesty: no number / no toggle until the PC.4 gate is met
# --------------------------------------------------------------------------- #
class TestGateUnmet:
    def test_pricing_tbc_and_no_amounts(self, monkeypatch, tmp_path):
        for with_stripe in (False, True):
            html = _html(_make_app(monkeypatch, tmp_path, with_stripe=with_stripe))
            assert "Pricing TBC" in html
            # No committed annual figure and no per-month figure anywhere.
            assert "/year" not in html
            assert "/mo" not in html
            assert not re.search(r"[£$€]\s*\d", html), "a price leaked with gate unmet"

    def test_no_period_toggle_element_when_gate_unmet(self, monkeypatch, tmp_path):
        html = _html(_make_app(monkeypatch, tmp_path))
        # The CSS rule is always present; the interactive element/JS is not.
        assert 'aria-label="Show price per period"' not in html
        assert "data-period=" not in html
        assert "querySelector('.mh-period-toggle')" not in html

    def test_partial_evidence_stays_tbc(self, monkeypatch, tmp_path):
        """Four paid clubs (<5) is below the gate → still TBC, still no number."""
        app = _make_app(monkeypatch, tmp_path, with_stripe=True)
        _seed_gate([58800, 82800, 118800, 70800])  # only 4 distinct clubs
        html = _html(app)
        assert "Pricing TBC" in html
        assert "/year" not in html


# --------------------------------------------------------------------------- #
# 4 — gate met: committed annual price + honest per-month split + toggle
# --------------------------------------------------------------------------- #
class TestGateMet:
    def test_commits_evidence_derived_annual_price(self, monkeypatch, tmp_path):
        html = _html(_gate_met_app(monkeypatch, tmp_path, top_pence=118800))
        assert "&pound;1188" in html  # highest tested price that cleared
        assert "/year" in html
        assert "Billed annually" in html

    def test_period_toggle_present_and_annual_is_default(self, monkeypatch, tmp_path):
        html = _html(_gate_met_app(monkeypatch, tmp_path))
        assert 'aria-label="Show price per period"' in html
        assert 'data-period="annual"' in html and 'data-period="monthly"' in html
        # Annual is the no-JS default state of the grid.
        assert 'id="mh-plan-grid" data-mh-period="annual"' in html
        # The progressive-enhancement script is wired in.
        assert "querySelector('.mh-period-toggle')" in html

    def test_monthly_figure_is_annual_over_twelve(self, monkeypatch, tmp_path):
        # £1188/yr → £99/mo exactly.
        html = _html(_gate_met_app(monkeypatch, tmp_path, top_pence=118800))
        assert "&pound;99" in html
        assert "/mo" in html

    def test_monthly_split_is_deterministic_for_non_round_price(self, monkeypatch, tmp_path):
        # £1000/yr → 100000/12 = 8333.33p → rounds to £83.33/mo.
        html = _html(_gate_met_app(monkeypatch, tmp_path, top_pence=100000))
        assert "&pound;1000" in html and "/year" in html
        assert "&pound;83.33" in html and "/mo" in html

    def test_monthly_never_implies_monthly_billing(self, monkeypatch, tmp_path):
        """Honesty guard: the per-month figure is framed as annual billing,
        and the page never offers a monthly billing cycle."""
        html = _html(_gate_met_app(monkeypatch, tmp_path))
        assert "Billed annually" in html
        assert "billed annually" in html.lower()
        # We must not claim a monthly billing cadence anywhere.
        assert "billed monthly" not in html.lower()
        assert "per month, billed" not in html.lower()


# --------------------------------------------------------------------------- #
# 5 — CTA wiring preserved through the redesign (CCR pre-contract gate)
# --------------------------------------------------------------------------- #
class TestCtaWiring:
    def _signup(self, app):
        c = app.test_client()
        c.post(
            "/signup",
            data={"email": "buyer@club.org", "password": "twelvechars1", "accept_terms": "1"},
        )
        return c

    def test_signed_in_purchasable_routes_through_confirm(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path, with_stripe=True)
        c = self._signup(app)
        html = c.get("/pricing").get_data(as_text=True)
        assert "/billing/confirm?plan=club" in html
        # The legacy direct-to-checkout POST form must not be on /pricing.
        assert 'action="/billing/checkout"' not in html

    def test_signed_out_paid_tier_invites_login(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path, with_stripe=True)
        html = _html(app)
        assert "Log in to upgrade" in html

    def test_free_tier_cta_is_get_started_when_signed_out(self, monkeypatch, tmp_path):
        html = _html(_make_app(monkeypatch, tmp_path))
        assert "Get started free" in html
