"""Finding #46 — generate_json records a ledger row on unparseable output.

Before the fix, ``generate_json`` returned its fallback silently (only a
log.warning), so "the model returned garbage" was indistinguishable from
"the model returned an empty result" in the LLM usage ledger. After the
fix it records a best-effort ledger row with ``error_kind='json_parse'``
and ``ok=False`` so the two cases are distinguishable at the ~20 call sites.
"""

from mediahub.media_ai import llm


def test_generate_json_records_json_parse_ledger_row(monkeypatch):
    captured = []

    # Provider answered, but with output that is not JSON.
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "this is not json at all")

    def fake_log_call(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(llm, "_log_call", fake_log_call)

    result = llm.generate_json("prompt", fallback={"x": 1})

    # Fallback still returned.
    assert result == {"x": 1}

    # A ledger row was recorded distinguishing this from an empty result.
    assert len(captured) == 1
    row = captured[0]
    assert row["ok"] is False
    assert row["error_kind"] == "json_parse"
    assert row["provider"]  # non-empty provider so record_call writes the row
    assert "not json" in row["error_message"]


def test_generate_json_no_ledger_row_on_valid_json(monkeypatch):
    captured = []
    monkeypatch.setattr(llm, "generate", lambda *a, **k: '{"ok": true}')
    monkeypatch.setattr(llm, "_log_call", lambda **k: captured.append(k))

    result = llm.generate_json("prompt")

    assert result == {"ok": True}
    # No json_parse row on the happy path.
    assert captured == []
