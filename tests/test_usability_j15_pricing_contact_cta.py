"""J-15 — paid tiers must never dead-end a treasurer who wants to pay.

Until the PC.4 evidence gate is met, paid tiers read "Pricing TBC" and the CTA
was a pointer-events:none "Not yet available" (or "Unavailable") pill — nothing
to click for a club treasurer ready to buy. The hero also claimed "Annual
prepay keeps it cheaper" although no monthly SKU exists to be cheaper than.

Now: any tier that isn't purchasable here carries a live "Talk to us about
pricing" mailto CTA (CONTACT_EMAIL, subject prefilled), and the hero states
"Simple annual pricing." with no cheaper-than claim.
"""

from __future__ import annotations

FAKE_SECRET_KEY = "sk_test_placeholder_not_a_real_key"
FAKE_PRICE_CLUB = "price_club_test"


def _make_app(monkeypatch, tmp_path, *, stripe_vars: dict | None):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for var in (
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_CLUB",
        "STRIPE_PRICE_FEDERATION",
    ):
        monkeypatch.delenv(var, raising=False)
    for var, val in (stripe_vars or {}).items():
        monkeypatch.setenv(var, val)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _get(app) -> str:
    return app.test_client().get("/pricing").get_data(as_text=True)


def test_unconfigured_deployment_offers_contact_cta_not_dead_pill(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, stripe_vars=None))
    from mediahub.web.legal import CONTACT_EMAIL

    assert "Talk to us about pricing" in html
    assert f"mailto:{CONTACT_EMAIL}?subject=MediaHub%20club%20pricing" in html
    # The dead pills are gone.
    assert "Not yet available" not in html
    assert ">Unavailable<" not in html


def test_unpriced_tier_gets_contact_cta_while_priced_tier_keeps_upgrade_path(
    monkeypatch, tmp_path
):
    # Stripe configured, Club priced, Federation NOT priced: the unpriced tier
    # offers the mailto; the priced tier keeps its normal purchase path
    # (signed out → "Log in to upgrade").
    html = _get(
        _make_app(
            monkeypatch,
            tmp_path,
            stripe_vars={
                "STRIPE_SECRET_KEY": FAKE_SECRET_KEY,
                "STRIPE_PRICE_CLUB": FAKE_PRICE_CLUB,
            },
        )
    )
    assert "Talk to us about pricing" in html
    assert "Log in to upgrade" in html
    assert "Not yet available" not in html


def test_contact_cta_is_a_real_link(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, stripe_vars=None))
    # A live anchor, not a pointer-events:none div.
    import re

    m = re.search(r"<a[^>]+href=\"mailto:[^\"]+\"[^>]*>Talk to us about pricing</a>", html)
    assert m, "contact CTA must be an <a href=mailto:...>"
    assert "pointer-events:none" not in m.group(0)


def test_hero_drops_cheaper_claim_for_simple_annual_pricing(monkeypatch, tmp_path):
    html = _get(_make_app(monkeypatch, tmp_path, stripe_vars=None))
    assert "Annual prepay keeps it cheaper" not in html
    assert "Simple annual pricing." in html
