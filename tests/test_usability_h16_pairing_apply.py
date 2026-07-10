"""H-16 — the AI font pairing must be applicable, and failure must be plain.

"Suggest a pairing" used to end on a dead-end result page (headline / body /
numeral + reason, then only "Back to typography") — the trio could not be
persisted anywhere. And a failure rendered the raw exception text
(`AI pairing is unavailable: {str(e)[:200]}`) into the page.

Now the result page carries an "Apply this pairing to my brand" form that
POSTs to `typography_pair_apply`, which validates the trio against the
self-hosted catalogue and persists it on the active club's BrandKit
(`type_pairing`, via the same `save_brand` write path all brand data uses);
`resolve_design_tokens` surfaces the applied trio as the club's "type" block.
Provider-gap failures show the standard plain wording; other failures a
generic friendly line — raw exception text goes to the server log only.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _signin(c, pid="alpha"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Alpha SC"))
    c.post("/api/organisation/active", data={"profile_id": pid})


_STUB_RESULT = {
    "pairing": "bebas-grotesk",
    "headline_family": "Bebas Neue",
    "body_family": "Space Grotesk",
    "numeral_family": "JetBrains Mono",
    "reason": "Condensed impact over a clean grotesk.",
    "corrected": False,
    "source": "ai",
}


def _stub_ai(monkeypatch):
    from mediahub.brand import design_tokens as dt

    monkeypatch.setattr(dt, "ai_type_pairing", lambda ctx: dict(_STUB_RESULT))


# --------------------------------------------------------------------------- #
# The result page offers Apply
# --------------------------------------------------------------------------- #
def test_result_page_has_apply_form(app_env, monkeypatch):
    _stub_ai(monkeypatch)
    with app_env.test_client() as c:
        _signin(c)
        body = c.post("/settings/typography/pair", data={"mood": "bold"}).get_data(as_text=True)
    assert "Apply this pairing to my brand" in body
    assert "/settings/typography/pair/apply" in body
    assert 'name="headline_family" value="Bebas Neue"' in body


# --------------------------------------------------------------------------- #
# Apply persists to the brand kit and design tokens honour it
# --------------------------------------------------------------------------- #
def test_apply_persists_trio_to_brand_kit(app_env):
    with app_env.test_client() as c:
        _signin(c, pid="club-x")
        r = c.post(
            "/settings/typography/pair/apply",
            data={
                "pairing": "bebas-grotesk",
                "headline_family": "Bebas Neue",
                "body_family": "Space Grotesk",
                "numeral_family": "JetBrains Mono",
            },
        )
        assert r.status_code == 302
        assert "status=pairing-applied" in r.headers["Location"]
        # The typography section confirms it with a banner…
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Pairing applied" in page
        # …and shows the applied state.
        assert "Applied pairing:" in page

    from mediahub.brand.store import load_brand

    kit, _tone, _templates = load_brand("club-x")
    assert kit.type_pairing == {
        "pairing": "bebas-grotesk",
        "headline_family": "Bebas Neue",
        "body_family": "Space Grotesk",
        "numeral_family": "JetBrains Mono",
        "source": "ai",
    }

    from mediahub.brand.design_tokens import resolve_design_tokens

    t = resolve_design_tokens("club-x")["type"]
    assert t["headline_family"] == "Bebas Neue"
    assert t["body_family"] == "Space Grotesk"
    assert t["numeral_family"] == "JetBrains Mono"
    assert t["pairing"] == "bebas-grotesk"
    assert t["source"] == "applied"


def test_apply_rejects_non_catalogue_family(app_env):
    with app_env.test_client() as c:
        _signin(c, pid="club-y")
        r = c.post(
            "/settings/typography/pair/apply",
            data={
                "pairing": "anton-inter",
                "headline_family": "Comic Sans MS",  # not a catalogue face
                "body_family": "Inter",
                "numeral_family": "JetBrains Mono",
            },
        )
        assert r.status_code == 302
        assert "status=pairing-invalid" in r.headers["Location"]

    from mediahub.brand.store import load_brand

    kit, _tone, _templates = load_brand("club-y")
    assert kit.type_pairing is None  # nothing was saved


def test_apply_without_profile_redirects_to_settings(app_env):
    with app_env.test_client() as c:
        r = c.post(
            "/settings/typography/pair/apply",
            data={"headline_family": "Anton", "body_family": "Inter",
                  "numeral_family": "JetBrains Mono"},
        )
        assert r.status_code == 302


def test_unapplied_profile_keeps_deterministic_default_type(app_env):
    from mediahub.brand.design_tokens import resolve_design_tokens

    t = resolve_design_tokens("club-never-applied")["type"]
    assert t["pairing"] == "anton-inter"
    assert t["headline_family"] == "Anton"
    assert "source" not in t


# --------------------------------------------------------------------------- #
# Honest, plain-English failure copy (raw exception → server log only)
# --------------------------------------------------------------------------- #
def test_provider_gap_shows_standard_wording(app_env):
    # No provider keys are configured in the fixture, so the real path raises
    # ClaudeUnavailableError.
    with app_env.test_client() as c:
        _signin(c)
        body = c.post("/settings/typography/pair", data={"mood": "bold"}).get_data(as_text=True)
    assert "AI suggestions are unavailable on this deployment." in body
    assert "Apply this pairing" not in body  # never a fabricated pairing


def test_other_failures_show_generic_line_not_raw_exception(app_env, monkeypatch):
    from mediahub.brand import design_tokens as dt

    def _boom(ctx):
        raise RuntimeError("secret-internal-detail-xyz")

    monkeypatch.setattr(dt, "ai_type_pairing", _boom)
    with app_env.test_client() as c:
        _signin(c)
        body = c.post("/settings/typography/pair", data={"mood": "bold"}).get_data(as_text=True)
    assert "could not suggest a pairing" in body
    assert "secret-internal-detail-xyz" not in body
