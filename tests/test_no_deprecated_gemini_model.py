"""tests/test_no_deprecated_gemini_model.py — Phase 1.5 model-pin guard.

In May 2026, Google deprecated ``gemini-2.0-flash`` and the API now
returns HTTP 404 "no longer available to new users". A previous fix
updated the main ``media_ai.llm`` default but missed the parallel
``ai_core.llm`` module, which surfaced as a real user-visible error
("AI provider error: Gemini tool HTTP 404") on production.

This test scans every default-value reference in code (not in
comments) and fails if any production path still defaults to the
deprecated model name. Comments and docs may still reference it for
historical context — only string literals used as defaults are
caught.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "mediahub"

DEPRECATED_MODEL = "gemini-2.0-flash"


def _all_python_files() -> list[Path]:
    return list(SRC_ROOT.rglob("*.py"))


class TestNoDeprecatedGeminiDefault:
    def test_no_hardcoded_default_to_deprecated_model(self):
        """No Python string literal used as a default value (i.e. not
        inside a comment or docstring) may equal ``gemini-2.0-flash``.

        We parse each file with ast and walk every string-constant node.
        A hit means a real default — comments are filtered out by the
        ast parser (it ignores them) and docstrings are filtered by
        rejecting Expression statements whose value is a Constant.
        """
        offenders: list[tuple[Path, int]] = []
        for py in _all_python_files():
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                # Skip docstrings: a bare expression statement whose
                # value is a string constant.
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                    continue
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and node.value == DEPRECATED_MODEL):
                    offenders.append((py, node.lineno))

        # Filter out docstring lines explicitly — ast.walk visits the
        # docstring Constant nodes that aren't statement-level (rare,
        # mostly inside Expr we already filtered, but be safe).
        real_offenders = []
        for path, line in offenders:
            try:
                src_line = path.read_text(encoding="utf-8").splitlines()[line - 1]
            except (IndexError, OSError):
                src_line = ""
            # Skip lines that are wholly a comment or docstring text.
            stripped = src_line.lstrip()
            if stripped.startswith("#"):
                continue
            real_offenders.append((path, line, src_line.strip()))

        assert not real_offenders, (
            f"Hardcoded reference to deprecated {DEPRECATED_MODEL!r} found in "
            f"production code (deprecated by Google May 2026, returns 404). "
            f"Update to gemini-2.5-flash. Offenders: {real_offenders}"
        )

    def test_main_llm_default_is_current(self):
        """media_ai/llm.py must default to a non-deprecated model."""
        from mediahub.media_ai import llm
        # Reach into the module-level constant.
        import os
        # Force-resolve the default by temporarily clearing the env var.
        # The default lives in the function body of _call_gemini via
        # _GEMINI_MODEL constant.
        assert llm._GEMINI_MODEL != DEPRECATED_MODEL, (
            f"media_ai.llm._GEMINI_MODEL still defaults to "
            f"{DEPRECATED_MODEL!r}"
        )

    def test_ai_core_llm_default_is_current(self):
        """ai_core/llm.py (the tool-use path) must also default to a
        non-deprecated model. This is the path that produced the
        production 'Gemini tool HTTP 404' error."""
        from mediahub.ai_core import llm as ai_core_llm
        import os
        # _gemini_model() reads from env with a hardcoded default.
        # Clear the env so we see the literal default.
        env_backup = os.environ.pop("MEDIAHUB_GEMINI_MODEL", None)
        try:
            default = ai_core_llm._gemini_model()
            assert default != DEPRECATED_MODEL, (
                f"ai_core.llm._gemini_model() default is still "
                f"{DEPRECATED_MODEL!r} (deprecated by Google May 2026)"
            )
        finally:
            if env_backup is not None:
                os.environ["MEDIAHUB_GEMINI_MODEL"] = env_backup

    @pytest.mark.parametrize("module_path,target", [
        ("src/mediahub/media_ai/llm.py", "_GEMINI_MODEL"),
        ("src/mediahub/ai_core/llm.py", "_gemini_model"),
    ])
    def test_default_in_source_text_matches_current(self, module_path, target):
        """Source-level safety net: grep the file for the deprecated
        literal in a defaulting context (``os.environ.get(..., "..."``)
        and fail if found."""
        text = (REPO_ROOT / module_path).read_text(encoding="utf-8")
        # Pattern: any os.environ.get call whose second arg is the bad
        # literal. Matches across lines.
        pattern = re.compile(
            r"os\.environ\.get\([^)]*?[\"']" + re.escape(DEPRECATED_MODEL)
            + r"[\"']\s*\)",
            re.DOTALL,
        )
        assert not pattern.search(text), (
            f"{module_path} still has an os.environ.get default of "
            f"{DEPRECATED_MODEL!r}"
        )
