"""visual.dub — the AI-dub pipeline (1.24): translate narration + revoice plan."""

from __future__ import annotations

from unittest import mock

import pytest

from mediahub.visual import dub
from mediahub.visual.dub import ClaudeUnavailableError, DubUnavailable, dub_plan, voice_for_language


class TestVoiceMapping:
    def test_known_languages(self):
        assert voice_for_language("cy") == "cy-GB-NiaNeural"  # Welsh flagship
        assert voice_for_language("en") == "en-GB-SoniaNeural"
        assert voice_for_language("ar") == "ar-EG-SalmaNeural"

    def test_region_subtag_ignored(self):
        assert voice_for_language("cy-GB") == "cy-GB-NiaNeural"

    def test_unmapped_is_empty(self):
        assert voice_for_language("klingon") == ""
        assert voice_for_language("") == ""
        assert voice_for_language(None) == ""

    def test_is_dubbable(self):
        assert dub.is_dubbable("cy") and not dub.is_dubbable("klingon")

    def test_every_caption_language_has_a_voice(self):
        # The dub map must cover every language the product can caption in, so a
        # bilingual club is never offered a language it can't dub.
        from mediahub.web.languages import SUPPORTED_LANGUAGES

        for lang in SUPPORTED_LANGUAGES:
            assert voice_for_language(lang.code), f"no dub voice for {lang.code}"


class TestDubPlan:
    _BASE = {"voice": "en-GB-SoniaNeural", "script": "Hannah set a new PB.", "music": "bed.mp3"}

    def test_translates_revoices_keeps_music_and_stamps_provenance(self):
        with mock.patch.object(dub, "translate_text", return_value="Gosododd Hannah PB newydd."):
            plan = dub_plan(self._BASE, "cy")
        assert plan["script"] == "Gosododd Hannah PB newydd."
        assert plan["voice"] == "cy-GB-NiaNeural"
        assert plan["music"] == "bed.mp3"  # music bed preserved
        assert plan["dubbed"] is True
        assert plan["dub_source_language"] == "en"
        assert plan["dub_target_language"] == "cy"

    def test_base_plan_is_not_mutated(self):
        with mock.patch.object(dub, "translate_text", return_value="..."):
            dub_plan(self._BASE, "cy")
        assert "dubbed" not in self._BASE  # original untouched

    def test_same_language_is_a_no_op_without_a_provider_call(self):
        tt = mock.MagicMock()
        with mock.patch.object(dub, "translate_text", tt):
            plan = dub_plan(self._BASE, "en", source_language="en")
        tt.assert_not_called()
        assert "dubbed" not in plan

    def test_no_script_raises(self):
        with pytest.raises(DubUnavailable):
            dub_plan({"voice": "x", "music": "bed.mp3"}, "cy")

    def test_unmapped_language_raises(self):
        with pytest.raises(DubUnavailable):
            dub_plan(self._BASE, "klingon")

    def test_no_provider_propagates_honest_error(self):
        def boom(*a, **k):
            raise ClaudeUnavailableError("no provider")

        with mock.patch.object(dub, "translate_text", side_effect=boom):
            with pytest.raises(ClaudeUnavailableError):
                dub_plan(self._BASE, "cy")


class TestReelDubWiring:
    """_reel_audio_plan(dub_language=…) routes the reel narration through the dub.

    The helper returns ``(plan, dub_error)`` — the honest drop reason rides
    alongside the plan (for the manifest), never inside it (cache keys).
    """

    def _run(self, dub_language, translate_ret=None, translate_exc=None):
        import mediahub.visual.audio_mux as ax
        import mediahub.visual.motion as M

        base = {"voice": "en-GB-SoniaNeural", "script": "Hannah set a new PB.", "music": "bed.mp3"}
        tt = (
            mock.MagicMock(side_effect=translate_exc)
            if translate_exc
            else mock.MagicMock(return_value=translate_ret)
        )
        with (
            mock.patch.object(ax, "audio_active", return_value=True),
            mock.patch.object(ax, "voice_active", return_value=True),
            mock.patch.object(M, "_library_bed_for", return_value=None),
            mock.patch.object(ax, "build_audio_plan", return_value=dict(base)),
            mock.patch.object(dub, "translate_text", tt),
        ):
            return M._reel_audio_plan(
                [{"athleteFullName": "Hannah Cox"}],
                {},
                "Champs",
                duration_sec=15.0,
                dub_language=dub_language,
            )

    def test_dub_language_translates_and_revoices(self):
        plan, dub_error = self._run("cy", translate_ret="Gosododd Hannah PB newydd.")
        assert plan["voice"] == "cy-GB-NiaNeural"
        assert plan["script"] == "Gosododd Hannah PB newydd."
        assert plan["dubbed"] is True
        assert plan["music"] == "bed.mp3"  # bed preserved
        assert dub_error == ""

    def test_unavailable_dub_drops_narration_keeps_music(self):
        # No provider → don't ship English pretending to be Welsh: drop the
        # narration, keep the music bed — and say why for the manifest.
        plan, dub_error = self._run("cy", translate_exc=ClaudeUnavailableError("no provider"))
        assert plan is not None
        assert "script" not in plan and "voice" not in plan
        assert plan.get("music") == "bed.mp3"
        assert "dub" in dub_error and "no provider" in dub_error

    def test_no_dub_language_is_the_plain_plan(self):
        plan, dub_error = self._run("")
        assert plan["voice"] == "en-GB-SoniaNeural"
        assert "dubbed" not in plan
        assert dub_error == ""


def test_dub_failure_reason_reaches_the_render_manifest(tmp_path, monkeypatch):
    """Honest-error rule: a reel that silently lost its dub must say why in the
    explainability manifest (the reason rides beside the plan, never in the
    cache-keyed plan itself)."""
    import json
    from pathlib import Path

    import mediahub.visual.audio_mux as ax
    import mediahub.visual.motion as M

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    base = {"voice": "en-GB-SoniaNeural", "script": "Hannah set a new PB.", "music": "bed.mp3"}
    monkeypatch.setattr(ax, "audio_active", lambda: True)
    monkeypatch.setattr(ax, "voice_active", lambda: True)
    monkeypatch.setattr(M, "_library_bed_for", lambda key: None)
    monkeypatch.setattr(ax, "build_audio_plan", lambda **k: dict(base))
    monkeypatch.setattr(
        ax, "apply_audio", lambda video, plan, *, duration_sec, cut_times=None: {"status": "mixed"}
    )
    monkeypatch.setattr(
        ax, "write_poster", lambda video, poster, *, at_sec: Path(poster).write_bytes(b"P") or True
    )

    def _boom(*a, **k):
        raise ClaudeUnavailableError("no provider")

    def _fake_run(
        *,
        composition_id,
        props,
        out_path,
        duration_sec=None,
        size=None,
        timeout=600,
        supersample=1.0,
    ):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    card = {
        "id": "dub-1",
        "achievement": {"swimmer_name": "Hannah Cox", "event_name": "100m Free"},
        "meet_name": "Champs",
    }
    with (
        mock.patch.object(dub, "translate_text", side_effect=_boom),
        mock.patch.object(M, "_run_remotion", side_effect=_fake_run),
    ):
        M.render_meet_reel(
            [card], {"display_name": "Dub SC"}, tmp_path / "o" / "r.mp4", dub_language="cy"
        )

    manifest = json.loads(
        next(
            p for p in M._cache_dir().glob("*.json") if not p.name.endswith(".audio.json")
        ).read_text(encoding="utf-8")
    )
    assert "no provider" in manifest["audio"]["dub_error"]
    assert "cy" in manifest["audio"]["dub_error"]
