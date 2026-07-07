"""M34 (PHOTOS-2) + M33 multi-upload — AI-vision auto-tagging, honestly gated.

* ``describe_photo_vision`` is roster-anchored (a name outside the roster can
  NEVER reach the result), closed-vocabulary for asset types and scene tags,
  defensive about junk model output, and raises ``ClaudeUnavailableError``
  when no provider is configured — never a fabricated tag.
* The store's additive helpers: ``merge_links`` (the M4 write-back seam)
  never drops human-entered values; ``list_untagged`` finds exactly the
  photos nothing has tagged.
* Web wiring: multi-file upload saves every file in one POST; the bulk
  describe job runs with progress and honest per-photo errors; without a
  provider it answers 503 and the library page shows the untagged badge and
  a disabled button with plain copy.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 40), (10, 60, 120)).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# describe_photo_vision (pure — mocked provider)
# ---------------------------------------------------------------------------


class TestDescribePhotoVision:
    def test_parses_and_filters_to_roster_and_vocab(self):
        import mediahub.media_library.describe as d

        raw = json.dumps(
            {
                "athletes": ["eira hughes", "Invented Person", "Eira Hughes"],
                "asset_type": "athlete_action",
                "scene_tags": ["podium", "PODIUM", "made-up-tag", "celebration"],
                "has_face": True,
                "confidence": 0.82,
            }
        )
        with mock.patch.object(d, "_extract_json_block", wraps=d._extract_json_block):
            with mock.patch(
                "mediahub.media_ai.llm.generate_vision", return_value=raw
            ) as gv:
                out = d.describe_photo_vision("/tmp/x.jpg", roster=["Eira Hughes", "Bo Li"])
        # Roster canonical casing wins; invented names are dropped.
        assert out["athletes"] == ["Eira Hughes"]
        assert out["asset_type"] == "athlete_action"
        assert out["scene_tags"] == ["podium", "celebration"]
        assert out["has_face"] is True
        assert out["confidence"] == 0.82
        # The prompt carries the roster + never-invent instruction.
        prompt = gv.call_args.args[1]
        assert "Eira Hughes" in prompt
        assert gv.call_args.kwargs["system"].count("NEVER") >= 1

    def test_empty_roster_means_no_names_ever(self):
        import mediahub.media_library.describe as d

        raw = json.dumps({"athletes": ["Somebody"], "asset_type": "other"})
        with mock.patch("mediahub.media_ai.llm.generate_vision", return_value=raw):
            out = d.describe_photo_vision("/tmp/x.jpg", roster=[])
        assert out["athletes"] == []

    def test_junk_model_output_yields_empty_result_not_crash(self):
        import mediahub.media_library.describe as d

        with mock.patch(
            "mediahub.media_ai.llm.generate_vision", return_value="not json at all"
        ):
            out = d.describe_photo_vision("/tmp/x.jpg", roster=["A B"])
        assert out == d.empty_vision_result()

    def test_unknown_asset_type_and_bad_confidence_are_coerced(self):
        import mediahub.media_library.describe as d

        raw = json.dumps(
            {"asset_type": "selfie", "confidence": "very", "has_face": "yes"}
        )
        with mock.patch("mediahub.media_ai.llm.generate_vision", return_value=raw):
            out = d.describe_photo_vision("/tmp/x.jpg")
        assert out["asset_type"] == "other"
        assert out["confidence"] == 0.0
        assert out["has_face"] is None  # only a real boolean is accepted

    def test_no_provider_raises_honestly(self, monkeypatch):
        import mediahub.media_library.describe as d
        from mediahub.media_ai.llm import ClaudeUnavailableError

        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(ClaudeUnavailableError):
            d.describe_photo_vision("/tmp/x.jpg", roster=["A B"])


# ---------------------------------------------------------------------------
# Store helpers (merge_links / list_untagged)
# ---------------------------------------------------------------------------


class TestStoreHelpers:
    def _store(self, tmp_path):
        from mediahub.media_library.store import MediaLibraryStore

        return MediaLibraryStore(
            db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads"
        )

    def _asset(self, store, **kw):
        from mediahub.media_library.models import MediaAsset

        defaults = dict(
            id="", filename="a.jpg", path="/tmp/a.jpg", type="athlete_action",
            profile_id="alpha",
        )
        defaults.update(kw)
        return store.save(MediaAsset(**defaults))

    def test_merge_links_is_additive_and_dedupes(self, tmp_path):
        store = self._store(tmp_path)
        a = self._asset(store, linked_athlete_names=["Eira Hughes"], tags=["podium"])
        out = store.merge_links(
            a.id,
            athlete_names=["eira hughes", "Bo Li"],
            meet_ids=["r1"],
            tags=["podium", "celebration"],
        )
        assert out.linked_athlete_names == ["Eira Hughes", "Bo Li"]
        assert out.linked_meet_ids == ["r1"]
        assert out.tags == ["podium", "celebration"]

    def test_merge_links_unknown_asset_returns_none(self, tmp_path):
        assert self._store(tmp_path).merge_links("nope", athlete_names=["X"]) is None

    def test_list_untagged_targets_exactly_the_untouched(self, tmp_path):
        store = self._store(tmp_path)
        untagged = self._asset(store)
        self._asset(store, linked_athlete_names=["A B"])  # human-tagged
        self._asset(store, tags=["podium"])  # scene-tagged
        self._asset(store, description_parsed={"vision": {"confidence": 0.5}})
        self._asset(store, type="logo")  # never tag logos
        self._asset(store, type="footage")  # never tag footage
        got = store.list_untagged(profile_id="alpha")
        assert [a.id for a in got] == [untagged.id]


# ---------------------------------------------------------------------------
# Web wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.media_library.store as mls
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    # The media store is a module-level singleton; drop it so each test's
    # DATA_DIR gets a fresh DB instead of accumulating across tests.
    mls._default_store = None
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    return app, wm, tmp_path


def _upload(client, n_files: int, **form):
    payload = {
        "profile_id": "alpha",
        "description": form.pop("description", ""),
        "asset_type": form.pop("asset_type", "athlete_action"),
        "file": [(io.BytesIO(_tiny_jpeg()), f"photo{i}.jpg") for i in range(n_files)],
    }
    return client.post(
        "/api/media-library",
        data=payload,
        content_type="multipart/form-data",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )


class TestMultiUpload:
    def test_many_files_saved_in_one_post(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, 3)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] and body["saved"] == 3 and body["skipped"] == 0
        assert len(body["assets"]) == 3
        assert body["asset"]["id"] == body["assets"][0]["id"]  # back-compat field
        store = wm._v8_get_media_store()
        assert len(store.list(profile_id="alpha")) == 3

    def test_bad_file_in_batch_is_skipped_not_fatal(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library",
                data={
                    "profile_id": "alpha",
                    "file": [
                        (io.BytesIO(_tiny_jpeg()), "ok.jpg"),
                        (io.BytesIO(b"<svg/>"), "evil.svg"),
                    ],
                },
                content_type="multipart/form-data",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["saved"] == 1 and body["skipped"] == 1

    def test_all_rejected_batch_keeps_the_415_contract(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library",
                data={"profile_id": "alpha", "file": (io.BytesIO(b"<svg/>"), "evil.svg")},
                content_type="multipart/form-data",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert resp.status_code == 415

    def test_upload_form_is_multiple(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            html = c.get("/media-library").get_data(as_text=True)
        assert 'type="file" name="file" accept="image/*" multiple' in html


class TestAutotagAtUpload:
    def test_provider_configured_tags_in_background(self, app_env, monkeypatch):
        app, wm, tmp_path = app_env
        vision = {
            "athletes": [],
            "asset_type": "athlete_action",
            "scene_tags": ["podium"],
            "has_face": True,
            "confidence": 0.7,
        }
        with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), \
             mock.patch(
                 "mediahub.media_library.describe.describe_photo_vision",
                 return_value=vision,
             ):
            with app.test_client() as c:
                c.post("/api/organisation/active", data={"profile_id": "alpha"})
                resp = _upload(c, 1)
            assert resp.status_code == 200
            aid = resp.get_json()["asset"]["id"]
            store = wm._v8_get_media_store()
            for _ in range(50):  # the tagger runs on a daemon thread
                a = store.get(aid)
                if a and a.tags:
                    break
                time.sleep(0.1)
        a = store.get(aid)
        assert a.tags == ["podium"]
        assert a.has_face is True
        assert a.description_parsed["vision"]["confidence"] == 0.7

    def test_no_provider_photo_stays_usable_and_untagged(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, 1)
            assert resp.status_code == 200
            aid = resp.get_json()["asset"]["id"]
            store = wm._v8_get_media_store()
            a = store.get(aid)
            assert a is not None and not a.tags and a.has_face is None
            # The library page shows the honest untagged badge + disabled AI
            # button with plain copy.
            html = c.get("/media-library").get_data(as_text=True)
        assert ">untagged</span>" in html
        assert 'id="mh-describe-go"' in html and "disabled" in html
        assert "needs a Gemini or Anthropic API key" in html


class TestDescribeJob:
    def test_no_provider_is_honest_503(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/media-library/describe-job")
        assert resp.status_code == 503
        assert resp.get_json()["error"] == "ai_unavailable"

    def test_bulk_job_tags_untagged_with_progress(self, app_env):
        app, wm, tmp_path = app_env
        # Two untagged uploads (no provider yet, so they stay untagged).
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            _upload(c, 2)
            store = wm._v8_get_media_store()
            assert len(store.list_untagged(profile_id="alpha")) == 2

            vision = {
                "athletes": [],
                "asset_type": "athlete_action",
                "scene_tags": ["mid-race"],
                "has_face": False,
                "confidence": 0.5,
            }
            with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), \
                 mock.patch(
                     "mediahub.media_library.describe.describe_photo_vision",
                     return_value=vision,
                 ):
                resp = c.post("/api/media-library/describe-job")
                assert resp.status_code == 202
                body = resp.get_json()
                assert body["total"] == 2
                j = {}
                for _ in range(80):
                    j = c.get(body["poll_url"]).get_json()
                    if j.get("status") != "running":
                        break
                    time.sleep(0.2)
            assert j["status"] == "done", j
            assert j["done"] == 2 and j["total"] == 2
            assert store.list_untagged(profile_id="alpha") == []

    def test_provider_errors_surface_in_job_status(self, app_env):
        app, wm, tmp_path = app_env
        from mediahub.media_ai.llm import ClaudeUnavailableError

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            _upload(c, 1)
            with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), \
                 mock.patch(
                     "mediahub.media_library.describe.describe_photo_vision",
                     side_effect=ClaudeUnavailableError("vision call failed"),
                 ):
                resp = c.post("/api/media-library/describe-job")
                assert resp.status_code == 202
                body = resp.get_json()
                j = {}
                for _ in range(80):
                    j = c.get(body["poll_url"]).get_json()
                    if j.get("status") != "running":
                        break
                    time.sleep(0.2)
        assert j["status"] == "error"
        assert "vision call failed" in json.dumps(j.get("errors") or {}) or j["error"]


class TestPhotoConfirmWriteBack:
    def test_confirm_links_athlete_and_meet(self, app_env, tmp_path):
        app, wm, _ = app_env
        (wm.RUNS_DIR / "r1.json").write_text(
            json.dumps(
                {
                    "run_id": "r1",
                    "profile_id": "alpha",
                    "meet": {"name": "Open"},
                    "recognition_report": {
                        "ranked_achievements": [
                            {
                                "id": "swim-1",
                                "achievement": {
                                    "swim_id": "swim-1",
                                    "swimmer_name": "Eira Hughes",
                                },
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        from mediahub.media_library.models import MediaAsset

        store = wm._v8_get_media_store()
        asset = store.save(
            MediaAsset(
                id="", filename="a.jpg", path=str(tmp_path / "a.jpg"),
                type="athlete_action", profile_id="alpha",
            )
        )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/runs/r1/cards/swim-1/photo-confirm", json={"asset_id": asset.id}
            )
        assert resp.status_code == 200
        assert resp.get_json()["athlete"] == "Eira Hughes"
        got = store.get(asset.id)
        assert got.linked_athlete_names == ["Eira Hughes"]
        assert "r1" in got.linked_meet_ids
