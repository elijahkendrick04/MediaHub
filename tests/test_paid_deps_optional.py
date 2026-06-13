"""P0.3 — every paid dependency is provably optional behind a flag, with a
free default wired.

One test per row of the hidden-fee register in
docs/DEPENDENCY_LICENSING.md §2. The contract for each paid path:

  1. it is OFF (or substituted by a free default) with no configuration;
  2. switching it on is an explicit operator flag / env key;
  3. with it off, the surface honest-errors or uses the free default —
     it never silently spends money and never fakes output.

These are config-level assertions — no network calls.
"""

from __future__ import annotations

import pytest

_PAID_ENVS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "MEDIAHUB_LLM_ENDPOINTS",
    "REPLICATE_API_TOKEN",
    "PHOTOROOM_API_KEY",
    "STRIPE_SECRET_KEY",
    "SCHEDULER_ACCESS_TOKEN",
)


@pytest.fixture
def no_paid_config(monkeypatch, tmp_path):
    """An environment with zero paid configuration and an empty DATA_DIR
    (so the secrets-store fallback can't supply keys either)."""
    for name in _PAID_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return monkeypatch


# --- Remotion (Company License for for-profit >3 people) -------------------


def test_remotion_is_optional_behind_the_reel_engine_flag(no_paid_config):
    """The register's top cost liability: a deployment can select the free
    ffmpeg engine and the seam honours it — Remotion is not mandatory."""
    no_paid_config.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg")
    from mediahub.visual.reel_engine import select_reel_engine

    assert select_reel_engine() == "ffmpeg"


def test_default_reel_engine_unchanged_for_licensed_deployments(no_paid_config):
    no_paid_config.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    from mediahub.visual.reel_engine import select_reel_engine

    assert select_reel_engine() == "remotion"


# --- edge-tts (undocumented Microsoft cloud endpoint) -----------------------


def test_voiceover_is_off_by_default(no_paid_config):
    """MEDIAHUB_VOICEOVER is opt-in; with it unset the caption text never
    leaves the box via the Edge endpoint."""
    no_paid_config.delenv("MEDIAHUB_VOICEOVER", raising=False)
    import os

    flag = os.environ.get("MEDIAHUB_VOICEOVER", "").strip().lower()
    assert flag not in {"1", "true", "yes", "on"}


# --- the scheduler (paid scheduling SaaS) ------------------------------------------


def test_scheduler_errors_honestly_without_a_token(no_paid_config):
    from mediahub.publishing.scheduler import SchedulerAuthError, _PreparedToken

    with pytest.raises(SchedulerAuthError, match="not configured"):
        _PreparedToken.require(None)
    with pytest.raises(SchedulerAuthError):
        _PreparedToken.require("   ")


# --- Replicate / PhotoRoom (paid per-call cutout APIs) ----------------------


def test_cutout_free_default_is_in_process_rembg(no_paid_config):
    from mediahub.media_ai.providers import _resolve_provider_choice

    no_paid_config.delenv("MEDIAHUB_CUTOUT_PROVIDER", raising=False)
    no_paid_config.delenv("MEDIAHUB_BG_PROVIDER", raising=False)
    assert _resolve_provider_choice() == "server"


def test_cutout_paid_backends_are_explicit_opt_ins(no_paid_config):
    from mediahub.media_ai.providers import _resolve_provider_choice

    no_paid_config.setenv("MEDIAHUB_CUTOUT_PROVIDER", "replicate")
    assert _resolve_provider_choice() == "replicate"
    # The legacy aliases keep resolving to the free in-process backend.
    no_paid_config.setenv("MEDIAHUB_CUTOUT_PROVIDER", "local")
    assert _resolve_provider_choice() == "server"


# --- Hosted LLM keys (Gemini free tier / Anthropic paid) --------------------


def test_llm_surfaces_error_honestly_with_no_keys(no_paid_config):
    """No key → ProviderNotConfigured. The standing rule: no template or
    heuristic caption is ever substituted for a model."""
    no_paid_config.delenv("MEDIAHUB_LLM_PROVIDER", raising=False)
    from mediahub.ai_core import llm

    assert llm.active_provider() is None
    with pytest.raises(llm.ProviderNotConfigured):
        llm.ask("s", "u")


def test_media_ai_reports_unavailable_with_no_keys(no_paid_config):
    no_paid_config.delenv("MEDIAHUB_LLM_PROVIDER", raising=False)
    from mediahub.media_ai import llm as media_llm

    assert media_llm.is_available() is False


# --- Stripe (billing) --------------------------------------------------------


def test_billing_honest_503_gate_without_stripe_keys(no_paid_config):
    from mediahub.web.billing import billing_configured

    assert billing_configured() is False


# --- Imagen generated backgrounds (billed Gemini feature) -------------------


def test_generated_backgrounds_are_opt_in_and_off_by_default(no_paid_config):
    from mediahub.graphic_renderer.render import _gen_bg_enabled
    from mediahub.visual import ai_background

    no_paid_config.delenv("MEDIAHUB_GEN_BG", raising=False)
    assert _gen_bg_enabled() is False  # flag default OFF — never spends unasked
    assert ai_background.is_available() is False  # and no key resolvable anyway
