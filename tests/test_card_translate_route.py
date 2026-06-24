"""The /api/runs/<run>/card/<card>/translate route (1.24).

End-to-end with the LLM mocked: a successful translate returns the variant AND
persists it on the card (so the bilingual pair rides into approval), and the
honest-error / validation paths behave.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

ORG = "club-x"
SWIM = "swim-001"


@pytest.fixture
def app_with_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.web as web_module
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club X", language="en"))

    achievement = {
        "swim_id": SWIM,
        "swimmer_name": "Emma Davies",
        "event": "200m Backstroke",
        "time": "2:23.45",
        "pb": True,
        "type": "pb",
        "headline": "New PB",
        "place": "1st",
    }
    run = {
        "run_id": "run-1",
        "profile_id": ORG,
        "profile_display": "Club X",
        "meet": {"name": "Winter Champs"},
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [{"rank": 1, "achievement": achievement, "factors": []}],
        },
    }
    runs_dir = tmp_path / "runs_v4"
    monkeypatch.setattr(web_module, "RUNS_DIR", runs_dir, raising=False)
    # _get_wf_store() caches a module-global WorkflowStore built from RUNS_DIR on
    # first call; under xdist an earlier test can leave it pointing elsewhere.
    # Reset it so the route persists into THIS test's runs dir.
    monkeypatch.setattr(web_module, "_wf_store", None, raising=False)
    (runs_dir / "run-1.json").write_text(json.dumps(run), encoding="utf-8")

    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    app._runs_dir = runs_dir  # for assertions
    return app


def _client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = ORG
    return c


def _url(card=SWIM, run="run-1"):
    return f"/api/runs/{run}/card/{card}/translate"


def _wf_translations(app, card=SWIM, run="run-1"):
    from mediahub.workflow.store import WorkflowStore

    return WorkflowStore(app._runs_dir).load(run).get(card)


def _mock_provider(caption="Torrodd Emma PB newydd!"):
    from mediahub.localize import translate as T

    return (
        mock.patch("mediahub.media_ai.llm.is_available", return_value=True),
        mock.patch.object(T, "generate_json", return_value={"caption": caption}),
        mock.patch.object(T, "active_provider", return_value="gemini-api"),
    )


class TestHappyPath:
    def test_translate_returns_variant_and_persists(self, app_with_run):
        client = _client(app_with_run)
        p_av, p_gj, p_prov = _mock_provider()
        with p_av, p_gj, p_prov:
            resp = client.post(
                _url(),
                json={"lang": "cy", "caption": "Emma smashed a new PB!"},
            )
        assert resp.status_code == 200
        j = resp.get_json()
        assert j["ok"] is True
        assert j["language"] == "cy"
        assert j["language_label"] == "Cymraeg"
        assert j["rtl"] is False
        assert j["slots"]["caption"] == "Torrodd Emma PB newydd!"
        # Persisted on the card so approval carries the pair.
        st = _wf_translations(app_with_run)
        assert st is not None and st.translations is not None
        assert st.translations["cy"]["slots"]["caption"] == "Torrodd Emma PB newydd!"

    def test_regional_variant(self, app_with_run):
        client = _client(app_with_run)
        p_av, p_gj, p_prov = _mock_provider(caption="My favorite color")
        with p_av, p_gj, p_prov:
            resp = client.post(_url(), json={"lang": "en-US", "caption": "My favourite colour"})
        assert resp.status_code == 200
        j = resp.get_json()
        assert j["language"] == "en-US"
        assert j["regional_only"] is True


class TestValidation:
    def test_no_language_is_400(self, app_with_run):
        client = _client(app_with_run)
        resp = client.post(_url(), json={"caption": "hi"})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "no_language"

    def test_unsupported_language_is_400(self, app_with_run):
        client = _client(app_with_run)
        resp = client.post(_url(), json={"lang": "klingon", "caption": "hi"})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_language"

    def test_empty_slots_is_400(self, app_with_run):
        client = _client(app_with_run)
        resp = client.post(_url(), json={"lang": "cy", "caption": "   "})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "empty"

    def test_missing_run_is_404(self, app_with_run):
        client = _client(app_with_run)
        resp = client.post(_url(run="nope"), json={"lang": "cy", "caption": "hi"})
        assert resp.status_code == 404


class TestCaptionToolbarUI:
    """The shared caption toolbar ships the on-demand translate control."""

    def test_card_creative_js_includes_translate_control(self):
        import mediahub.web.web as web_module

        js = web_module._card_creative_js()
        assert "MH_TR_LANGS" in js  # the language-list global
        assert "tr-lang-select" in js  # the picker
        assert "/translate" in js  # builds the translate URL from captionUrl
        assert "Cymraeg (Welsh)" in js  # Welsh offered (flagship)
        assert "en-US" in js  # regional variant offered
        assert "saved with this card" in js  # one approval covers the pair

    def test_translatable_langs_excludes_bare_english(self):
        import mediahub.web.web as web_module

        snippet = web_module._translatable_langs_js()
        # bare "en" would be a no-op target; it must not be offered, but the
        # regional English variants must be.
        assert '"en-GB"' in snippet and '"en-US"' in snippet
        assert '["en",' not in snippet


class TestStoredTranslationsRender:
    """1.24: a saved translation re-appears on reload (the bilingual pair must
    survive a refresh), server-side rendered and escaped."""

    def test_helper_renders_label_caption_and_rtl(self):
        import mediahub.web.web as web_module

        card = {
            "workflow": {
                "translations": {
                    "cy": {"language_label": "Cymraeg", "rtl": False, "slots": {"caption": "Nofio gwych!"}},
                    "ar": {"language_label": "العربية", "rtl": True, "slots": {"caption": "تعليق"}},
                }
            }
        }
        html = web_module._render_stored_translations(card)
        assert "Saved translations" in html
        assert "Cymraeg" in html and "Nofio gwych!" in html
        assert "العربية" in html and 'dir="rtl"' in html  # RTL variant flagged

    def test_helper_empty_when_no_translations(self):
        import mediahub.web.web as web_module

        assert web_module._render_stored_translations({}) == ""
        assert web_module._render_stored_translations({"workflow": {}}) == ""
        assert web_module._render_stored_translations({"workflow": {"translations": {}}}) == ""
        # a variant with no caption text contributes nothing
        empty = {"workflow": {"translations": {"cy": {"slots": {}}}}}
        assert web_module._render_stored_translations(empty) == ""

    def test_helper_escapes_caption(self):
        import mediahub.web.web as web_module

        card = {"workflow": {"translations": {"cy": {"slots": {"caption": "<script>x</script>"}}}}}
        out = web_module._render_stored_translations(card)
        assert "<script>" not in out and "&lt;script&gt;" in out

    def test_pack_page_shows_saved_translation_on_load(self, app_with_run):
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(app_with_run._runs_dir)
        ws.set_status("run-1", SWIM, CardStatus.APPROVED)
        ws.set_translation(
            "run-1",
            SWIM,
            "cy",
            {
                "language": "cy",
                "language_label": "Cymraeg",
                "rtl": False,
                "slots": {"caption": "Torrodd Emma PB newydd!"},
            },
        )
        client = _client(app_with_run)
        html = client.get("/pack/run-1").get_data(as_text=True)
        assert "Saved translations" in html
        assert "Cymraeg" in html
        assert "Torrodd Emma PB newydd!" in html


class TestMetering:
    """1.23 governance: translation is metered AI spend like captions."""

    def _count(self):
        from mediahub.observability import feature_quota

        return feature_quota.count_for_org(ORG, feature="translate")

    def test_successful_translate_records_one_use(self, app_with_run):
        client = _client(app_with_run)
        p_av, p_gj, p_prov = _mock_provider()
        with p_av, p_gj, p_prov:
            resp = client.post(_url(), json={"lang": "cy", "caption": "Emma smashed a new PB!"})
        assert resp.status_code == 200 and resp.get_json()["ok"] is True
        assert self._count() == 1  # one translation → one metered use

    def test_quota_reached_blocks_without_calling_provider(self, app_with_run, monkeypatch):
        monkeypatch.setenv("MEDIAHUB_QUOTA_TRANSLATE", "1")
        client = _client(app_with_run)
        from mediahub.localize import translate as T

        with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), mock.patch.object(
            T, "generate_json", return_value={"caption": "x"}
        ) as gj, mock.patch.object(T, "active_provider", return_value="gemini-api"):
            r1 = client.post(_url(), json={"lang": "cy", "caption": "first"})
            assert r1.status_code == 200 and r1.get_json()["ok"] is True
            assert gj.call_count == 1 and self._count() == 1
            # Second call is over the single-use limit → blocked, provider untouched.
            r2 = client.post(_url(), json={"lang": "fr", "caption": "second"})
            assert r2.get_json()["error"] == "quota_reached"
            assert gj.call_count == 1  # generation not attempted again
            assert self._count() == 1  # blocked call not recorded


class TestHonestError:
    def test_no_provider_returns_no_key_and_does_not_persist(self, app_with_run):
        client = _client(app_with_run)
        # No keys configured (fixture deleted them) and is_available unmocked → False.
        resp = client.post(_url(), json={"lang": "cy", "caption": "Emma smashed a new PB!"})
        # 200 + an {"error": "no_key"} body — same honest-error shape as the
        # caption/assist routes (the UI branches on `error`, not the status).
        assert resp.status_code == 200
        assert resp.get_json()["error"] == "no_key"
        # Nothing was written.
        assert _wf_translations(app_with_run) is None
