"""PC.11 guard — every vendored reference directory carries a licence.

The 2026-06-12 compliance audit (finding 7.2) flagged two ``vendor/`` dirs
with no upstream licence file — no verifiable right to redistribute. They
were removed. This test keeps the constraint: a directory under ``vendor/``
must contain a LICENSE/LICENCE/COPYING or THIRD_PARTY_NOTICES file somewhere
inside it, or the build goes red.
"""

from __future__ import annotations

import re
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor"

_LICENCE_NAMES = {
    "license",
    "license.md",
    "license.txt",
    "licence",
    "licence.md",
    "licence.txt",
    "copying",
    "copying.md",
    "third_party_notices.md",
    "notice",
    "notice.md",
}

# A README that declares the licence (e.g. "## License\n\nMIT") counts —
# that is the form the 2026-06-12 audit accepted for claude-marketplace-main.
_README_LICENCE_HEADING = re.compile(r"(?im)^#+\s*licen[cs]e\b")

_REMOVED_UNLICENSED = ("agent-skills-main", "bencium-marketplace-main")


def _has_licence_file(directory: Path) -> bool:
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        if f.name.lower() in _LICENCE_NAMES:
            return True
        if f.name.lower().startswith("readme"):
            try:
                if _README_LICENCE_HEADING.search(f.read_text(encoding="utf-8")):
                    return True
            except OSError:
                continue
    return False


def test_every_vendor_dir_has_a_licence_file():
    if not VENDOR.exists():
        return  # nothing vendored, nothing to license
    missing = [
        d.name
        for d in sorted(VENDOR.iterdir())
        if d.is_dir() and not _has_licence_file(d)
    ]
    assert not missing, (
        f"vendor/ dir(s) without any licence/notice file: {missing}. "
        "MediaHub cannot redistribute unlicensed material — add the upstream "
        "licence file or remove the directory (THIRD_PARTY_LICENSES.md)."
    )


def test_the_two_audited_unlicensed_dirs_stay_removed():
    for name in _REMOVED_UNLICENSED:
        assert not (VENDOR / name).exists(), (
            f"vendor/{name} was removed in PC.11 because it carries no "
            "upstream licence — do not reintroduce it without one."
        )
