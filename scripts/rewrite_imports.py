#!/usr/bin/env python3
"""
rewrite_imports.py — Phase C of the V9 handoff.

Rewrites absolute imports of live top-level packages to their mediahub.* form.
Also rewrites swim_content_v4.* to mediahub.web.* / mediahub.pipeline.* based on
where each file landed.

Legacy packages (swim_content, swim_content_v5, swim_content_pb, engine_v4) are
NOT rewritten — they remain importable via the legacy/ path that
mediahub.__init__ adds to sys.path.

Usage:
    python scripts/rewrite_imports.py --root /home/user/workspace/mediahub-export
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# Live top-level packages that moved to mediahub.<name>/ (verbatim)
LIVE_TOPS = [
    "recognition",
    "recognition_swim",
    "canonical",
    "interpreter",
    "voice",
    "brand",
    "workflow",
    "club_platform",
    "pb_discovery",
    "context_engine",
    "media_ai",
    "media_library",
    "media_requirements",
    "venue_search",
    "inspiration",
    "creative_brief",
    "graphic_renderer",
    "content_pack",
    "content_pack_visual",
    "web_research",
    "history",
]

# Files of swim_content_v4 that moved to mediahub.web (everything except the 3 below)
PIPELINE_FILES = {"pipeline_v4", "interpreter_bridge", "pb_bridge"}


def rewrite_text(text: str) -> str:
    """Apply all rewrite rules to a single source file's text."""

    # --- swim_content_v4 → mediahub.web / mediahub.pipeline ---
    # `from swim_content_v4.<name> import ...`
    def repl_from_v4(m: re.Match) -> str:
        name = m.group(1)
        prefix = "mediahub.pipeline" if name in PIPELINE_FILES else "mediahub.web"
        return f"from {prefix}.{name} import"
    text = re.sub(r"from\s+swim_content_v4\.([A-Za-z_][A-Za-z0-9_]*)\s+import",
                  repl_from_v4, text)

    # `from swim_content_v4.adapters.<x> import ...` (adapters live under web/)
    text = re.sub(
        r"from\s+swim_content_v4\.adapters\.([A-Za-z_][A-Za-z0-9_]*)\s+import",
        r"from mediahub.web.adapters.\1 import",
        text,
    )

    # `import swim_content_v4.<name>` → `import mediahub.web.<name>` (or pipeline)
    def repl_import_v4(m: re.Match) -> str:
        name = m.group(1)
        rest = m.group(2) or ""
        prefix = "mediahub.pipeline" if name in PIPELINE_FILES else "mediahub.web"
        return f"import {prefix}.{name}{rest}"
    text = re.sub(
        r"import\s+swim_content_v4\.([A-Za-z_][A-Za-z0-9_]*)(\s+as\s+\w+|\b)",
        repl_import_v4, text,
    )

    # `from swim_content_v4 import secrets_store` → `from mediahub.web import secrets_store`
    text = re.sub(
        r"from\s+swim_content_v4\s+import\s+",
        "from mediahub.web import ",
        text,
    )

    # `import swim_content_v4` (bare) → leave with a compat note
    text = re.sub(
        r"^import\s+swim_content_v4\s*$",
        "from mediahub import web as swim_content_v4  # compat shim",
        text, flags=re.MULTILINE,
    )

    # --- live top-level packages → mediahub.X ---
    for top in LIVE_TOPS:
        # `from <top>.<sub> import ...`
        text = re.sub(
            rf"\bfrom\s+{top}\.",
            f"from mediahub.{top}.",
            text,
        )
        # `from <top> import ...`
        text = re.sub(
            rf"\bfrom\s+{top}\s+import\s+",
            f"from mediahub.{top} import ",
            text,
        )
        # `import <top>.<sub>` and `import <top>` — must end at a word boundary
        text = re.sub(
            rf"\bimport\s+{top}(\.[A-Za-z_][\w.]*)?(?=\b)(\s+as\s+\w+)?",
            lambda m: f"import mediahub.{top}{m.group(1) or ''}{m.group(2) or ''}",
            text,
        )

    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()

    targets = list((root / "src" / "mediahub").rglob("*.py")) + \
              list((root / "tests").rglob("*.py")) + \
              list((root / "scripts").rglob("*.py"))

    # Skip the rewrite script itself and the build script
    skip_names = {"rewrite_imports.py", "build_export.py"}

    changed = 0
    for p in targets:
        if p.name in skip_names:
            continue
        original = p.read_text()
        new = rewrite_text(original)
        if new != original:
            p.write_text(new)
            changed += 1
    print(f"Rewrote imports in {changed} files.")


if __name__ == "__main__":
    main()
