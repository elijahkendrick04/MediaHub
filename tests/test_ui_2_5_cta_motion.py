"""UI2.5 — purpose-built primary-CTA variant (`.btn.mh-cta-motion`).

The motion kit shipped Moving-Border (`.mh-moving-border`) and Stateful-Button
(`.btn[data-mh-state]`) as ready-to-use effects, but a raw moving border is
invisible on a filled `.btn`: the button paints its solid lane fill right to
its own edge, burying the inset ring. UI2.5 builds the host that lets the two
effects co-exist on one primary action — a borderless/transparent edge so the
animated ring shows, the stateful loading/success states layered on top — and
wires it to the core-flow primary CTAs (Upload "Continue", Make "Generate the
pack").

Three contracts:

  1. The `.btn.mh-cta-motion` CSS variant exists in the effect layer, rides the shared
     `mh-ba-spin` conic ring, pulls the fill to the padding box so the ring is
     visible, keeps the stateful contract, and stills cleanly under
     `prefers-reduced-motion`.
  2. The Upload submit wears the variant + the stateful spans and spins on
     submit.
  3. The Make "Generate the pack" action wears the variant + the stateful
     spans and drives loading→success through `MH.btnState`.

Presentation-only: the deterministic engine, AI surfaces and explainability
logic are untouched.
"""

from __future__ import annotations

import re

import pytest

from mediahub.web import web as webmod


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="fx-org",
            display_name="CTA SC",
            brand_voice_summary="Testing.",
            brand_capture_status="ok",
        )
    )
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "fx-org"
        yield c


# =========================================================================== #
# 1) The CSS variant
# =========================================================================== #
class TestCtaVariantCss:
    def test_variant_is_in_the_effect_layer(self):
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        assert ".btn.mh-cta-motion {" in THEME_MOTION_CSS
        assert ".btn.mh-cta-motion::before {" in THEME_MOTION_CSS

    def test_effect_layer_is_served_on_every_page(self):
        # The variant must reach real pages — it lives in BASE_CSS via the
        # appended motion layer, not in some orphaned file.
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        assert THEME_MOTION_CSS in webmod.BASE_CSS
        assert ".btn.mh-cta-motion::before {" in webmod.BASE_CSS

    def test_host_is_borderless_so_the_ring_shows(self):
        # The whole point: pull the fill to the padding box behind a transparent
        # border so the animated ring isn't buried under the button's own fill.
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        block = THEME_MOTION_CSS.split(".btn.mh-cta-motion {", 1)[1].split("}", 1)[0]
        assert "border: 1.5px solid transparent;" in block
        assert "background-clip: padding-box;" in block

    def test_ring_rides_the_shared_conic_animation(self):
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        ring = THEME_MOTION_CSS.split(".btn.mh-cta-motion::before {", 1)[1].split("}", 1)[0]
        assert "conic-gradient(from var(--mh-ba)" in ring
        assert "animation: mh-ba-spin var(--mh-beam-speed) linear infinite;" in ring
        # Masked to a thin frame (the standard kit moving-border technique).
        assert "mask-composite: exclude;" in ring

    def test_ring_is_token_driven(self):
        # A re-skin re-skins the CTA: the rim glint reads off --mh-on-primary,
        # never a hard-coded colour.
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        ring = THEME_MOTION_CSS.split(".btn.mh-cta-motion::before {", 1)[1].split("}", 1)[0]
        # The rim glint reads off the brand token …
        fill = ring.split("background: conic-gradient", 1)[1].split(";", 1)[0]
        assert "var(--mh-on-primary)" in fill
        # … with no hard-coded hex colour in the gradient (the only `#` in the
        # block is the mask's #000, which is mechanism, not brand).
        assert "#" not in fill

    def test_success_state_keeps_the_ring_legible(self):
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        assert '.btn.mh-cta-motion[data-mh-state="success"]::before {' in THEME_MOTION_CSS

    def test_stilled_under_reduced_motion(self):
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        # The spin is in the reduced-motion animation:none list …
        rm = THEME_MOTION_CSS.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        assert ".mh-cta-motion::before" in rm
        # … and it settles to a clean static hairline, not a frozen arc.
        assert ".btn.mh-cta-motion::before { background: var(--mh-primary); }" in rm

    def test_does_not_collide_with_the_pricing_cta_utility(self):
        # `.mh-cta` is already taken: the pricing page uses `btn mh-cta` for a
        # full-width plan-card CTA. The motion variant must be namespaced
        # (`mh-cta-motion`) so it never slaps a moving border on those — i.e.
        # the effect layer carries no bare `.btn.mh-cta {`/`.btn.mh-cta:`/
        # `.btn.mh-cta[`/`.btn.mh-cta::` selector that would catch them.
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        assert not re.search(r"\.btn\.mh-cta(?![\w-])", THEME_MOTION_CSS), (
            "motion CTA selector leaks onto the pricing `.mh-cta` utility"
        )


# =========================================================================== #
# 2) Upload "Continue" submit
# =========================================================================== #
class TestUploadCta:
    def test_submit_wears_the_variant_and_stateful_spans(self, client):
        body = client.get("/upload").get_data(as_text=True)
        assert 'id="mh-upload-submit" class="btn mh-cta-motion"' in body
        # The three stateful slots the variant animates between.
        seg = body.split('id="mh-upload-submit"', 1)[1].split("</button>", 1)[0]
        assert 'class="mh-btn-label"' in seg
        assert 'class="mh-btn-spin"' in seg
        assert 'class="mh-btn-check"' in seg

    def test_submit_spins_on_a_valid_submit(self, client):
        body = client.get("/upload").get_data(as_text=True)
        assert "MH.btnState(btn, 'loading')" in body


# =========================================================================== #
# 3) Make "Generate the pack" action
# =========================================================================== #
class TestMakeCta:
    def _render(self):
        with webmod.app.test_request_context("/"):
            return webmod._render_turn_into_card("ui25-run")

    def test_action_wears_the_variant_and_stateful_spans(self):
        html = self._render()
        assert 'id="ti-btn" class="btn mh-cta-motion"' in html
        seg = html.split('id="ti-btn"', 1)[1].split("</button>", 1)[0]
        assert 'class="mh-btn-label"' in seg
        assert 'class="mh-btn-spin"' in seg
        assert 'class="mh-btn-check"' in seg

    def test_action_drives_loading_then_success(self):
        html = self._render()
        assert "setState('loading')" in html
        assert "setState('success')" in html
        # The bespoke textContent spinner is gone — the kit helper owns the
        # visual state now, so nothing nukes the stateful spans.
        assert "btn.textContent" not in html

    def test_action_guards_against_double_fire(self):
        # MH.btnState('loading') only sets pointer-events:none, which a keyboard
        # re-activation (or a missing ui-kit.js) bypasses. A disabled re-entry
        # guard stops a second LLM-heavy pack job; textContent is still untouched
        # so the stateful spans survive.
        html = self._render()
        assert "if (btn.disabled) return;" in html
        assert "btn.disabled = true;" in html
        assert "btn.disabled = false;" in html  # cleared on failure so retry works
        assert "btn.textContent" not in html

    def test_inline_style_keeps_the_borderless_host(self):
        # An inline `border:none` would override the variant's transparent
        # border and re-bury the ring — it must be gone.
        html = self._render()
        seg = html.split('id="ti-btn"', 1)[1].split(">", 1)[0]
        assert "border:none" not in seg
