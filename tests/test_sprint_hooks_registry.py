"""Sprint render-hook registry — isolation contract.

The registry promises "a bad hook is skipped, never fatal". That must hold
not only when a hook's ``apply`` raises (long covered by the per-hook
try/except) but also when a drop-in module fails at *import* time (syntax
error, optional dep at module scope) — one broken file must never kill every
still render.
"""

from __future__ import annotations

import mediahub.graphic_renderer.sprint_hooks as sh


def _ctx() -> sh.RenderHookCtx:
    return sh.RenderHookCtx(
        brief=None,
        width=1080,
        height=1350,
        family="story_card",
        format_name="feed_portrait",
        is_v2=False,
    )


def test_broken_hook_module_import_is_skipped(tmp_path, monkeypatch, caplog):
    bad = tmp_path / "zz_broken_hook.py"
    bad.write_text("def apply(html, ctx:\n", encoding="utf-8")  # SyntaxError
    monkeypatch.setattr(sh, "__path__", list(sh.__path__) + [str(tmp_path)])

    with caplog.at_level("WARNING", logger="mediahub.graphic_renderer.sprint_hooks"):
        out = sh.apply_render_hooks("<html><body>card</body></html>", _ctx())

    assert isinstance(out, str) and "card" in out
    assert any("zz_broken_hook" in r.message for r in caplog.records)


def test_module_raising_at_import_is_skipped(tmp_path, monkeypatch):
    bad = tmp_path / "zz_needs_dep.py"
    bad.write_text("import definitely_not_a_real_dep_xyz\n", encoding="utf-8")
    monkeypatch.setattr(sh, "__path__", list(sh.__path__) + [str(tmp_path)])

    out = sh.apply_render_hooks("<html><body>card</body></html>", _ctx())
    assert isinstance(out, str) and "card" in out
