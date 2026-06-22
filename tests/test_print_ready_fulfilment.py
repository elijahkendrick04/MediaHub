"""Roadmap 1.20 Build D — the fulfilment slot + merch mockup scenes.

The fulfilment slot is off by default and honest-errors; the merch mockups are
deterministic PIL scenes. Both are pure/unit-level (no web, no Chromium).
"""

from __future__ import annotations

import io

import pytest

from PIL import Image

from mediahub.mockups import compose as MK
from mediahub.print_ready import fulfilment as F


def _png(w=600, h=600, colour=(12, 37, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fulfilment slot — off by default, honest, flag-gated
# ---------------------------------------------------------------------------


def test_default_provider_is_null_and_disabled(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_FULFILMENT_PROVIDER", raising=False)
    assert not F.fulfilment_enabled()
    st = F.status()
    assert st["enabled"] is False and st["provider"] == "none"
    assert "download" in st["message"].lower()


def test_null_provider_honest_errors():
    order = F.FulfilmentOrder(
        org_id="org-a",
        lines=(F.OrderLine("poster_a3", {"front": "/tmp/a.pdf"}),),
        ship_to=F.ShipTo("Club", "1 Pool Rd", "Leeds", "LS1 1AA"),
    )
    p = F.NullProvider()
    with pytest.raises(F.FulfilmentUnavailable):
        p.quote(order)
    with pytest.raises(F.FulfilmentUnavailable):
        p.submit(order)
    with pytest.raises(F.FulfilmentUnavailable):
        p.order_status("x")


def test_unknown_provider_falls_back_to_null(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_FULFILMENT_PROVIDER", "definitely-not-real")
    assert F.current_provider().slug == "none"
    assert not F.fulfilment_enabled()


def test_registering_an_enabled_provider_flips_status(monkeypatch):
    class _Fake:
        slug = "fake"
        enabled = True

        def quote(self, order):
            return F.Quote("fake", "GBP", 1200, 350, 5, {"eco": "recycled"})

        def submit(self, order):
            return F.OrderAck("fake", "ord_1", "received")

        def order_status(self, order_id):
            return "received"

    F.register_provider(_Fake())
    try:
        monkeypatch.setenv("MEDIAHUB_FULFILMENT_PROVIDER", "fake")
        assert F.fulfilment_enabled()
        st = F.status()
        assert st["enabled"] and st["provider"] == "fake"
        q = F.current_provider().quote(None)
        assert q.total_pence == 1550 and q.attributes["eco"] == "recycled"
    finally:
        F._PROVIDERS.pop("fake", None)


def test_order_schema_serialises():
    order = F.FulfilmentOrder(
        org_id="org-a",
        lines=(F.OrderLine("club_tee", {"front": "/a.pdf", "back": "/b.pdf"}, quantity=20),),
        ship_to=F.ShipTo("Club", "1 Pool Rd", "Leeds", "LS1 1AA", line2="Unit 2"),
        reference="gala-2026",
    )
    d = order.to_dict()
    assert d["org_id"] == "org-a" and d["reference"] == "gala-2026"
    assert d["lines"][0]["quantity"] == 20
    assert d["ship_to"]["line2"] == "Unit 2"


# ---------------------------------------------------------------------------
# Merch mockup scenes (tee / mug / tote)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", ["tee", "mug", "tote"])
def test_merch_scene_renders_png(template):
    out = MK.compose_mockup(_png(), template, accent="#C8102E")
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG" and img.size == (1080, 1080)


@pytest.mark.parametrize("template", ["tee", "mug", "tote"])
def test_merch_scene_is_deterministic(template):
    data = _png()
    assert MK.compose_mockup(data, template, accent="#0A2540") == MK.compose_mockup(
        data, template, accent="#0A2540"
    )


def test_list_templates_includes_merch_scenes():
    ids = {t["id"] for t in MK.list_templates()}
    assert {"tee", "mug", "tote"} <= ids


def test_unknown_template_honest_errors():
    with pytest.raises(MK.MockupError):
        MK.compose_mockup(_png(), "spaceship")


def test_every_merch_product_template_resolves_to_a_scene():
    # Build D's promise: every product's mockup_template names a real scene.
    from mediahub.print_ready import products as P

    known = set(MK.MOCKUP_TEMPLATES)
    for prod in P.all_products():
        assert prod.mockup_template in known, (prod.slug, prod.mockup_template)
