"""PC.11 guard — the subprocessor register is pinned to the env-flag surface.

A new external provider is activated by an env key (``*_API_KEY``,
``*_TOKEN``, ``*_ENDPOINT`` …). This test scans every such key literal in
``src/mediahub`` and fails unless the key is declared either in
``legal.SUBPROCESSORS`` (so the DPA table discloses the provider) or in
``legal.NON_SUBPROCESSOR_PROVIDER_ENV`` (a documented, reasoned exclusion).
Result: a provider cannot ship undisclosed — adding ``FOO_API_KEY`` without
touching the register turns the build red.
"""

from __future__ import annotations

import re
from pathlib import Path

from mediahub.web import legal
from tests._helpers import web_surface_src

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "mediahub"
ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# What counts as a provider-shaped env key. Deliberately broad: keys that
# carry credentials for, or point at, an external service.
_PROVIDER_SHAPE = re.compile(
    r"(API_KEY|API_TOKEN|ACCESS_TOKEN|_TOKEN$|SECRET_KEY|WEBHOOK_SECRET|ENDPOINTS?$|WEBHOOK$)"
)

# Uppercase string literals (candidate env keys) in source.
_LITERAL = re.compile(r'"([A-Z][A-Z0-9_]{2,})"')

# Internal keys that match the provider shape but configure no external
# service. Keep this list short and obvious — anything debatable belongs in
# legal.NON_SUBPROCESSOR_PROVIDER_ENV with a recorded reason instead.
_INTERNAL_KEYS = {
    "SECRET_KEY",  # Flask session-signing secret — never leaves the server
}

# Provider activation flags that are not credential-shaped and so are listed
# explicitly: the scan must still find a register entry for each.
_EXTRA_ACTIVATION_FLAGS = {"MEDIAHUB_VOICEOVER"}


def _provider_shaped_keys_in_src() -> set[str]:
    found: set[str] = set()
    for py in SRC_ROOT.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for literal in _LITERAL.findall(text):
            if literal in _EXTRA_ACTIVATION_FLAGS or _PROVIDER_SHAPE.search(literal):
                found.add(literal)
    return found


def _registered_keys() -> set[str]:
    keys: set[str] = set()
    for sub in legal.SUBPROCESSORS:
        keys.update(sub.env_keys)
    return keys


def test_every_provider_env_key_is_declared_in_the_register():
    in_src = _provider_shaped_keys_in_src() - _INTERNAL_KEYS
    declared = _registered_keys() | set(legal.NON_SUBPROCESSOR_PROVIDER_ENV)
    undisclosed = sorted(in_src - declared)
    assert not undisclosed, (
        "Provider-shaped env key(s) found in src/mediahub that are not in the "
        "subprocessor register (legal.SUBPROCESSORS) or the documented "
        f"exclusion list (legal.NON_SUBPROCESSOR_PROVIDER_ENV): {undisclosed}. "
        "Disclose the provider in the DPA register before shipping it."
    )


def test_register_keys_exist_in_code_or_env_example():
    """The register can't list dead flags — every declared env key must be
    real (read in src/ or documented in .env.example)."""
    in_src = _provider_shaped_keys_in_src()
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8") if ENV_EXAMPLE.exists() else ""
    for key in sorted(_registered_keys() | set(legal.NON_SUBPROCESSOR_PROVIDER_ENV)):
        assert key in in_src or key in env_example, (
            f"Register declares env key {key!r} which neither appears in "
            "src/mediahub nor .env.example — remove the stale entry or wire "
            "up the provider."
        )


def test_no_key_is_both_subprocessor_and_excluded():
    overlap = _registered_keys() & set(legal.NON_SUBPROCESSOR_PROVIDER_ENV)
    assert not overlap, f"env keys in both register structures: {sorted(overlap)}"


def test_dpa_table_renders_from_the_register():
    html = legal.dpa_html(privacy_url="/privacy")
    for sub in legal.SUBPROCESSORS:
        assert sub.name in html, f"DPA §6 table is missing register entry {sub.name!r}"
        assert sub.processing in html
    # The table is generated, not hand-maintained.
    assert legal.subprocessor_table_rows_html() in html


def test_public_subprocessors_page_renders_from_the_register():
    """One register, two renders: the public /legal/subprocessors page and
    the DPA table must both come from legal.SUBPROCESSORS — no parallel
    hand-maintained list may reappear in web.py."""
    public = legal.subprocessor_public_rows_html()
    for sub in legal.SUBPROCESSORS:
        assert sub.name in public
        assert sub.transfer_mechanism, f"{sub.name} needs a recorded transfer mechanism"
        assert sub.engaged_when, f"{sub.name} needs a recorded engaged-when note"
    # The subprocessors page lives on the carved web surface (routes_site.py
    # since the #15 carve) — scan the whole surface, which also strengthens the
    # no-parallel-list guard to every routes_*.py module.
    web_src = web_surface_src()
    assert "_SUBPROCESSORS_PUBLIC" not in web_src, (
        "the web surface grew a parallel subprocessor list — render from "
        "legal.SUBPROCESSORS instead (PC.11)"
    )
    assert "subprocessor_public_rows_html" in web_src


def test_canonical_doc_lists_every_register_provider():
    """docs/compliance/SUBPROCESSORS.md is the procurement-facing mirror of
    the register — a provider added in code must be recorded there."""
    doc = (
        Path(__file__).resolve().parents[1] / "docs" / "compliance" / "SUBPROCESSORS.md"
    ).read_text(encoding="utf-8")
    for fragment in (
        "Render",
        "Google",
        "Anthropic",
        "OpenAI-compatible",
        "Photoroom",
        "Replicate",
        "Microsoft",
        "Resend",
        "Stripe",
        "backup target",
    ):
        assert fragment in doc, f"SUBPROCESSORS.md is missing {fragment!r}"


def test_privacy_notice_discloses_each_provider_flow():
    html = legal.privacy_html(
        terms_url="/terms", cookies_url="/cookies", dpa_url="/dpa"
    )
    for needle in (
        "Gemini",
        "Anthropic",
        "OpenAI-compatible",
        "Photoroom",
        "Replicate",
        "Microsoft",
        "edge-tts",
        "Stripe",
        "DuckDuckGo",
        "ntfy",
    ):
        assert needle in html, f"Privacy Notice no longer mentions {needle!r}"


def test_exclusions_carry_recorded_reasons():
    for key, reason in legal.NON_SUBPROCESSOR_PROVIDER_ENV.items():
        assert len(reason.strip()) >= 30, (
            f"Excluded provider key {key!r} needs a real recorded reason, "
            "not a stub."
        )
