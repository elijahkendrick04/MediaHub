"""tests/test_brand_guidelines.py — AI brand-guidelines ingestion.

Three concerns:
  1. Text extraction works fail-soft per format. TXT/MD/HTML/DOCX/ZIP
     all return readable text in-memory; unknown binaries are flagged
     as unsupported without raising.
  2. The LLM is what interprets the extracted text — there is no
     regex pattern matching for "do's" vs "don'ts". When the LLM is
     mocked, its structured output flows through to the saved profile.
  3. When no cloud LLM provider is configured, interpret_guidelines
     returns the canonical empty shape with a clear ``no_provider``
     status — it never fabricates structured fields. Production
     deployments configure an LLM key, so this path only affects
     misconfigured / dev environments where the honest signal is
     better than fake interpreted output.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import guidelines  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Text extraction — per-format
# ---------------------------------------------------------------------------

class TestTextExtraction:
    def test_txt(self):
        out = guidelines.extract_text("guide.txt", b"Always be warm. Never be cynical.")
        assert out["status"] == "ok"
        assert "warm" in out["text"]
        assert out["extractor"] == "plaintext"

    def test_markdown(self):
        out = guidelines.extract_text("guide.md", b"# Brand\n\nWe are warm.\n")
        assert out["status"] == "ok"
        assert "warm" in out["text"]

    def test_html(self):
        html = b"<html><head><title>X</title></head><body><p>Be <b>warm</b>.</p></body></html>"
        out = guidelines.extract_text("guide.html", html)
        assert out["status"] == "ok"
        assert "warm" in out["text"]
        # Tags must be stripped
        assert "<b>" not in out["text"]

    def test_rtf(self):
        rtf = b"{\\rtf1\\ansi Always be \\b warm\\b0 .}"
        out = guidelines.extract_text("guide.rtf", rtf)
        assert out["status"] == "ok"
        assert "warm" in out["text"]

    def test_docx_synthetic(self):
        """Build a minimal valid .docx in-memory and confirm extraction."""
        buf = io.BytesIO()
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Brand voice: warm and inclusive.</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Never use jargon.</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", document_xml)
            zf.writestr("[Content_Types].xml", "<Types/>")  # minimal stub
        out = guidelines.extract_text("guide.docx", buf.getvalue())
        assert out["status"] == "ok"
        assert "warm and inclusive" in out["text"]
        assert "Never use jargon" in out["text"]
        assert out["extractor"] == "docx-xml"

    def test_zip_walks_contents(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("rules.txt", "Be warm. Be specific.")
            zf.writestr("audience.md", "# Audience\n\nClub families.\n")
        out = guidelines.extract_text("guide.zip", buf.getvalue())
        assert out["status"] == "ok"
        assert "warm" in out["text"]
        assert "Club families" in out["text"]
        assert out["extractor"] == "zip-walk"

    def test_empty_bytes(self):
        out = guidelines.extract_text("empty.txt", b"")
        assert out["status"] == "empty"
        assert out["text"] == ""

    def test_oversize_rejected(self):
        big = b"x" * (26 * 1024 * 1024)  # 26 MB > 25 MB cap
        out = guidelines.extract_text("big.txt", big)
        assert out["status"] == "too_large"
        assert out["text"] == ""

    def test_unsupported_binary(self):
        # A real PNG header → looks binary, won't decode to clean text.
        out = guidelines.extract_text(
            "logo.png",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 200,
        )
        # Either "unsupported" (most realistic) or "ok" if the decoded
        # blob happens to look clean. Both are acceptable; the key is
        # no crash.
        assert out["status"] in ("unsupported", "ok", "empty")

    def test_zip_bomb_bounded(self):
        """Many small files in a zip should be capped, not unbounded."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(200):  # 200 entries, cap is 50
                zf.writestr(f"f{i}.txt", "rule " * 100)
        out = guidelines.extract_text("bomb.zip", buf.getvalue())
        # Must not raise; must return SOMETHING but bounded.
        assert out["status"] == "ok"

    def test_single_member_zip_bomb_never_inflates_past_budget(self, monkeypatch):
        """A single high-compression-ratio member (few KB compressed, huge
        inflated) must be refused DURING inflation, not after a full read."""
        # Shrink the budget so the test stays fast and small.
        monkeypatch.setattr(guidelines, "_MAX_ZIP_DECOMPRESSED", 64 * 1024)
        monkeypatch.setattr(guidelines, "_ZIP_CHUNK", 8 * 1024)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 4 MB of zeros compresses to a few KB but inflates 64x past budget.
            zf.writestr("bomb.txt", "\x00" * (4 * 1024 * 1024))
        out = guidelines.extract_text("bomb.zip", buf.getvalue())
        # The bomb member is refused whole — nothing extracted, no blow-up.
        assert out["status"] in ("unsupported", "empty")

    def test_zip_member_lying_about_file_size_still_capped(self, monkeypatch):
        """The declared file_size is only an early filter — the streamed
        read itself enforces the budget even when the header lies."""
        monkeypatch.setattr(guidelines, "_MAX_ZIP_DECOMPRESSED", 16 * 1024)
        monkeypatch.setattr(guidelines, "_ZIP_CHUNK", 4 * 1024)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.txt", "A" * (256 * 1024))
        # Forging the central-directory size field directly is fiddly;
        # instead make every ZipInfo the walk sees claim a tiny size.
        real_infolist = zipfile.ZipFile.infolist

        def lying_infolist(self):
            infos = real_infolist(self)
            for info in infos:
                info.file_size = 10  # claim tiny; actual inflate is 256 KB
            return infos

        monkeypatch.setattr(zipfile.ZipFile, "infolist", lying_infolist)
        out = guidelines.extract_text("liar.zip", buf.getvalue())
        # Member refused by the streamed budget despite the lying header.
        assert out["status"] in ("unsupported", "empty")

    def test_nested_zip_depth_capped(self):
        """zip-in-zip is walked once; deeper nesting is refused."""
        inner2 = io.BytesIO()
        with zipfile.ZipFile(inner2, "w") as zf:
            zf.writestr("deepest.txt", "DEEPEST-LEVEL-RULE")
        inner1 = io.BytesIO()
        with zipfile.ZipFile(inner1, "w") as zf:
            zf.writestr("level2.zip", inner2.getvalue())
            zf.writestr("mid.txt", "MID-LEVEL-RULE")
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("level1.zip", inner1.getvalue())
            zf.writestr("top.txt", "TOP-LEVEL-RULE")
        out = guidelines.extract_text("nested.zip", outer.getvalue())
        assert out["status"] == "ok"
        assert "TOP-LEVEL-RULE" in out["text"]
        assert "MID-LEVEL-RULE" in out["text"]  # depth 1 — allowed
        assert "DEEPEST-LEVEL-RULE" not in out["text"]  # depth 2 — refused


# ---------------------------------------------------------------------------
# 2. LLM-driven interpretation
# ---------------------------------------------------------------------------

class TestLlmInterpretation:
    def test_llm_output_normalised(self, monkeypatch):
        mock_out = {
            "summary": "Warm, inclusive swimming club. Voice is community-led.",
            "voice_attributes": ["warm", "inclusive", "specific", "warm"],  # dup
            "tone_dos": ["Use first names", "Celebrate effort"],
            "tone_donts": ["Never compare swimmers"],
            "prohibited_words": ["loser", "fail"],
            "preferred_terminology": {"members": "swimmers"},
            "hashtag_rules": "Use up to 3 hashtags, always include #ClubLife",
            "sponsor_mention_rules": "Tag @sponsor in every meet recap",
            "audience": "Club families and supporters",
            "key_messages": ["Inclusivity", "Hard work pays off"],
            "palette_mentions": ["#0066cc", "#ff8800"],
        }
        from mediahub.brand import guidelines as g
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda *a, **kw: mock_out,
        )
        monkeypatch.setattr(
            "mediahub.media_ai.llm.is_available",
            lambda: True,
        )

        out = g.interpret_guidelines("Whatever — the LLM is mocked.")
        assert out["status"] == "ok"
        assert "Warm" in out["summary"]
        # De-duped voice attributes
        assert out["voice_attributes"].count("warm") == 1
        assert "inclusive" in out["voice_attributes"]
        assert out["tone_dos"] == ["Use first names", "Celebrate effort"]
        assert out["tone_donts"] == ["Never compare swimmers"]
        assert "loser" in out["prohibited_words"]
        assert out["preferred_terminology"] == {"members": "swimmers"}
        assert "#ClubLife" in out["hashtag_rules"]
        assert "@sponsor" in out["sponsor_mention_rules"]
        assert out["audience"].startswith("Club families")
        assert "Inclusivity" in out["key_messages"]
        assert "#0066cc" in out["palette_mentions"]
        assert "#ff8800" in out["palette_mentions"]

    def test_llm_invalid_palette_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda *a, **kw: {
                "summary": "x",
                "voice_attributes": ["warm"],
                "palette_mentions": ["red", "#GGGGGG", "0066cc", "#abc"],  # bad mixed
            },
        )
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        out = guidelines.interpret_guidelines("text")
        # Only valid hex survives. "#abc" normalises to "#aabbcc".
        # Bare "0066cc" gets prefixed and accepted.
        assert "#aabbcc" in out["palette_mentions"]
        assert "#0066cc" in out["palette_mentions"]
        assert "red" not in out["palette_mentions"]
        assert "#gggggg" not in out["palette_mentions"]

    def test_no_llm_returns_no_provider_status(self, monkeypatch):
        """When no cloud LLM provider is configured the function returns
        the canonical empty shape with status ``no_provider`` — it does
        NOT fabricate structured fields from regex-extracted text."""
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
        out = guidelines.interpret_guidelines(
            "Brand guidelines: be warm. Be inclusive. Never be cynical."
        )
        assert out["status"] == "no_provider"
        assert out["summary"] == ""
        assert out["tone_dos"] == []
        assert out["voice_attributes"] == []

    def test_empty_text_short_circuit(self):
        out = guidelines.interpret_guidelines("")
        assert out["status"] == "empty"

    def test_llm_failure_returns_provider_error(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("LLM down")
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr("mediahub.media_ai.llm.generate_json", boom)
        out = guidelines.interpret_guidelines("Be warm. Be inclusive.")
        assert out["status"] == "provider_error"
        assert out["summary"] == ""


# ---------------------------------------------------------------------------
# 3. End-to-end ingestion
# ---------------------------------------------------------------------------

class TestIngestEndToEnd:
    def test_ingest_txt_with_mocked_llm(self, monkeypatch):
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda *a, **kw: {
                "summary": "A warm community club.",
                "voice_attributes": ["warm"],
                "tone_dos": ["Use first names"],
                "tone_donts": ["Never be cynical"],
                "prohibited_words": [],
                "preferred_terminology": {},
                "hashtag_rules": "",
                "sponsor_mention_rules": "",
                "audience": "",
                "key_messages": [],
                "palette_mentions": [],
            },
        )
        payload = guidelines.ingest_guidelines_file(
            "rules.txt", b"Be warm. Use first names. Never be cynical."
        )
        assert payload["brand_guidelines_status"] == "ok"
        assert payload["brand_guidelines_filename"] == "rules.txt"
        assert payload["brand_guidelines_byte_size"] > 0
        assert payload["brand_guidelines_uploaded_at"]  # ISO ts populated
        assert "warm" in payload["brand_guidelines"]["voice_attributes"]
        assert payload["brand_guidelines_raw_excerpt"].startswith("Be warm")

    def test_ingest_empty_file_clean_status(self):
        payload = guidelines.ingest_guidelines_file("empty.txt", b"")
        assert payload["brand_guidelines_status"] == "empty"
        assert payload["brand_guidelines"] == {}
        # Even an empty upload is recorded with filename + timestamp so
        # we can show the user what they tried to upload.
        assert payload["brand_guidelines_filename"] == "empty.txt"

    def test_ingest_oversize_returns_too_large(self):
        big = b"x" * (26 * 1024 * 1024)
        payload = guidelines.ingest_guidelines_file("big.txt", big)
        assert payload["brand_guidelines_status"] == "too_large"
        assert payload["brand_guidelines"] == {}

    def test_ingest_never_raises(self, monkeypatch):
        """A truly garbage input still returns a clean payload."""
        payload = guidelines.ingest_guidelines_file(
            "weird.xyz",
            b"\x00\x01\x02\x03" * 50,
        )
        # Status will be unsupported/empty/ok — but the call MUST NOT
        # raise. That's the invariant.
        assert "brand_guidelines_status" in payload

    def test_interpret_ok_but_rules_pass_fails_is_not_silent(self, monkeypatch):
        """Interpretation succeeding while the dedicated mandatory-rules
        call fails must NOT read as 'document has no hard rules' — the
        payload carries a distinct error status the UI can act on."""
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        calls = {"n": 0}

        def two_faced(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:  # interpret_guidelines succeeds
                return {"summary": "A warm club.", "voice_attributes": ["warm"]}
            raise RuntimeError("provider blew up on the rules pass")

        monkeypatch.setattr("mediahub.media_ai.llm.generate_json", two_faced)
        payload = guidelines.ingest_guidelines_file(
            "rules.txt", b"The strapline MUST always appear."
        )
        assert payload["brand_guidelines_status"] == "ok"
        assert payload["brand_guidelines_mandatory_rules"] == []
        assert payload["brand_guidelines_mandatory_rules_status"] == "error"

    def test_rules_status_ok_none_and_no_provider(self, monkeypatch):
        # no_provider
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
        rules, status = guidelines.extract_mandatory_rules_with_status("MUST rule.")
        assert (rules, status) == ([], "no_provider")
        # ok — rules found
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda *a, **kw: {"mandatory_rules": ["The strapline MUST appear."]},
        )
        rules, status = guidelines.extract_mandatory_rules_with_status("doc")
        assert status == "ok" and rules
        # none — provider answered, document has no hard rules
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda *a, **kw: {"mandatory_rules": []},
        )
        rules, status = guidelines.extract_mandatory_rules_with_status("doc")
        assert (rules, status) == ([], "none")
        # error — provider answered but output was unparseable (fallback {})
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json", lambda *a, **kw: {}
        )
        rules, status = guidelines.extract_mandatory_rules_with_status("doc")
        assert (rules, status) == ([], "error")
