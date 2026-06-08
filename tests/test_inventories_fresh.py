"""CI freshness guard for the auto-generated ``docs/ENV_INVENTORY.md``.

The env inventory rotted before: it was generated once (and against a hard-coded
export path), then silently drifted as env vars were added — at one point it
listed 16 of 64 vars and omitted GEMINI_API_KEY/ANTHROPIC_API_KEY. This test
regenerates it deterministically and asserts the committed copy matches, so
adding or removing an env var without regenerating fails CI instead of shipping
a stale, misleading inventory.

Regenerate with: ``python -c 'import scripts.build_inventories as b; b.write_env()'``.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import build_inventories as inv  # noqa: E402


def test_env_inventory_is_current():
    expected = inv.env_inventory_md()
    actual = (_ROOT / "docs" / "ENV_INVENTORY.md").read_text()
    assert actual == expected, (
        "docs/ENV_INVENTORY.md is stale. Regenerate it with "
        "`python -c 'import scripts.build_inventories as b; b.write_env()'` and commit."
    )
