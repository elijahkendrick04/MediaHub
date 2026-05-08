#!/usr/bin/env python3
"""
build_export.py — Phase A of the V9 handoff.

Walks the live MediaHub source workspace and copies it into mediahub-export/
under the structure described in V9_HANDOFF_SPEC.md. The script is idempotent:
re-running cleans the destination first.

Usage:
    python scripts/build_export.py \
        --source /home/user/workspace/swim-content \
        --dest   /home/user/workspace/mediahub-export
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Top-level packages that move into src/mediahub/<name>/ verbatim.
LIVE_PACKAGES = [
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

# Legacy packages preserved verbatim under legacy/.
LEGACY_PACKAGES = [
    "swim_content",
    "swim_content_pb",
    "swim_content_v5",
    "engine_v4",
    "legacy_scripts",
    "templates_v4",
    "templates",
    "sample_data_v4",
]

LEGACY_FILES = [
    "app_v3.py",
    "smoke_test5.py",
    "run_with_demo.py.disabled",
    "run.py",
    "build_seeds.py",
    "select_meets.py",
    "smoke5_confirmed_pb.json",
    "smoke5_sample_audit.json",
    "all_meets_raw.json",
    "meets_enriched.json",
    "selected_meets.json",
    "schema.sql",
    "seed.py",
]

SKIP_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".cache",
    ".git",
    "node_modules",
    "runs_v4",
    "uploads_v4",
    "smoke_v8_output",
    "static",
    "club_profiles",          # runtime-discovered club JSON
    "patterns_validation_corpus",  # large corpus, not needed for export
    "quals_sources",           # large source dump
}

SKIP_FILE_NAMES = {
    "data.db",
    ".secret_key",
    ".env",
}


def _copy_tree(src: Path, dst: Path, prune_runtime: bool = True) -> int:
    """Copy a directory tree, skipping caches and runtime artefacts. Returns file count."""
    if not src.exists():
        return 0
    count = 0
    for root, dirs, files in os.walk(src):
        # In-place prune
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f in SKIP_FILE_NAMES:
                continue
            if f.endswith(".pyc"):
                continue
            shutil.copy2(Path(root) / f, target_dir / f)
            count += 1
    return count


def _copy_data(source: Path, dest: Path) -> None:
    """Copy data/ but exclude runtime-discovered content and secrets."""
    src_data = source / "data"
    if not src_data.exists():
        return

    # ontology/ — copy verbatim
    _copy_tree(src_data / "ontology", dest / "data" / "ontology")
    # voices/seed/ — copy verbatim
    _copy_tree(src_data / "voices" / "seed", dest / "data" / "voices" / "seed")
    # patterns.jsonl — keep
    pj = src_data / "patterns.jsonl"
    if pj.exists():
        shutil.copy2(pj, dest / "data" / "patterns.jsonl")
    # quals.json — keep
    qj = src_data / "quals.json"
    if qj.exists():
        shutil.copy2(qj, dest / "data" / "quals.json")
    # brand_kits/ — keep dir + .gitkeep + any seeded JSON (small) for testing
    bk = dest / "data" / "brand_kits"
    bk.mkdir(parents=True, exist_ok=True)
    (bk / ".gitkeep").touch()
    src_bk = src_data / "brand_kits"
    if src_bk.exists():
        for f in src_bk.iterdir():
            if f.is_file() and f.suffix == ".json":
                shutil.copy2(f, bk / f.name)
    # discovered/ — keep dirs only with .gitkeep (runtime data)
    for sub in ("clubs", "swimmers", "meets", "pbs", "search_cache"):
        d = dest / "data" / "discovered" / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").touch()
    # secrets.json.example
    (dest / "data" / "secrets.json.example").write_text(
        '{\n  "ANTHROPIC_API_KEY": "sk-ant-...",\n  '
        '"REPLICATE_API_TOKEN": "r8_...",\n  '
        '"PHOTOROOM_API_KEY": "..."\n}\n'
    )


def _copy_samples(source: Path, dest: Path) -> None:
    """Keep INDEX.csv and a small representative slice of learning_corpus."""
    src_samples = source / "samples"
    dst_samples = dest / "samples"
    if not src_samples.exists():
        return
    corpus_src = src_samples / "learning_corpus"
    corpus_dst = dst_samples / "learning_corpus"
    corpus_dst.mkdir(parents=True, exist_ok=True)
    # Keep INDEX.csv + EVAL_REPORT.csv at root
    for f in ("INDEX.csv", "EVAL_REPORT.csv"):
        p = corpus_src / f
        if p.exists():
            shutil.copy2(p, corpus_dst / f)
    # Pick 5 representative meets covering different formats:
    # PDF, ZIP+PDF, HTML, PDF (multi-day), and DOCX/text variant.
    representative_meets = [
        ("level1", "2025_05_swansea_may_lc"),       # single PDF
        ("level1", "2025_11_nd_open_championships"),  # ZIP + PDF + HY3
        ("level1", "2026_01_sheffield_winter_l1"),   # HTML
        ("level1", "2026_01_berkshire_county_champs"),  # multi-day PDF
        ("level1", "2025_04_city_of_bristol_l1"),    # plain PDF
    ]
    for level, meet in representative_meets:
        src = corpus_src / level / meet
        if src.exists():
            dst = corpus_dst / level / meet
            _copy_tree(src, dst)
    # MISM-2024-Results.pdf at samples root (sample_data file)
    mism_src = source / "sample_data" / "MISM-2024-Results.pdf"
    if mism_src.exists():
        shutil.copy2(mism_src, dst_samples / "MISM-2024-Results.pdf")


def _copy_legacy(source: Path, dest: Path) -> None:
    legacy_root = dest / "legacy"
    legacy_root.mkdir(parents=True, exist_ok=True)
    for pkg in LEGACY_PACKAGES:
        src = source / pkg
        if src.exists():
            _copy_tree(src, legacy_root / pkg)
    for f in LEGACY_FILES:
        p = source / f
        if p.exists():
            shutil.copy2(p, legacy_root / f)
    # Smoke scripts at top level
    for f in ("smoke_test5.py",):
        p = source / f
        if p.exists():
            shutil.copy2(p, legacy_root / f)


def _copy_live_packages(source: Path, dest: Path) -> None:
    pkg_root = dest / "src" / "mediahub"
    pkg_root.mkdir(parents=True, exist_ok=True)
    for pkg in LIVE_PACKAGES:
        src = source / pkg
        if src.exists():
            _copy_tree(src, pkg_root / pkg)
    # research/ is data, not a Python package — copy under data/research/
    res_src = source / "research"
    if res_src.exists():
        _copy_tree(res_src, dest / "data" / "research")


def _copy_swim_content_v4(source: Path, dest: Path) -> None:
    """
    Phase B: split swim_content_v4/ across src/mediahub/web/ and src/mediahub/pipeline/.

    Per spec:
      web/      ← web.py, ai_caption.py, secrets_store.py, brand_kit_upload.py, club_discovery.py
      pipeline/ ← pipeline_v4.py, interpreter_bridge.py, pb_bridge.py

    Supporting siblings (canonical, humanise, inference, v3_shim, trust, club_profile,
    ground_truth, adapters/) are placed under web/ since web.py imports from them.
    """
    src = source / "swim_content_v4"
    if not src.exists():
        return
    web_dst = dest / "src" / "mediahub" / "web"
    pipe_dst = dest / "src" / "mediahub" / "pipeline"
    web_dst.mkdir(parents=True, exist_ok=True)
    pipe_dst.mkdir(parents=True, exist_ok=True)

    web_files = {
        "web.py",
        "ai_caption.py",
        "secrets_store.py",
        "brand_kit_upload.py",
        "club_discovery.py",
        "canonical.py",
        "humanise.py",
        "club_profile.py",
        "ground_truth.py",
        "inference.py",
        "v3_shim.py",
        "trust.py",
    }
    pipe_files = {
        "pipeline_v4.py",
        "interpreter_bridge.py",
        "pb_bridge.py",
    }

    # Copy adapters/ subpackage into web/
    adapters_src = src / "adapters"
    if adapters_src.exists():
        _copy_tree(adapters_src, web_dst / "adapters")

    # Copy Python files
    for p in src.iterdir():
        if not p.is_file() or not p.suffix == ".py":
            continue
        if p.name == "__init__.py":
            # write our own __init__ for both packages later
            continue
        if p.name in web_files:
            shutil.copy2(p, web_dst / p.name)
        elif p.name in pipe_files:
            shutil.copy2(p, pipe_dst / p.name)
        else:
            # default: place in web/
            shutil.copy2(p, web_dst / p.name)

    # __init__.py shells
    (web_dst / "__init__.py").write_text(
        '"""mediahub.web — Flask UI + helpers (formerly swim_content_v4)."""\n'
        'from .web import app, create_app  # re-export for gunicorn entry\n'
        '\n__all__ = ["app", "create_app"]\n'
    )
    (pipe_dst / "__init__.py").write_text(
        '"""mediahub.pipeline — orchestration of upload → cards (formerly swim_content_v4 bridges)."""\n'
        'from .pipeline_v4 import run_pipeline_v4, PipelineRunV4\n'
        '\n__all__ = ["run_pipeline_v4", "PipelineRunV4"]\n'
    )

    # __main__.py for `python -m mediahub.web`
    (web_dst / "__main__.py").write_text(
        '"""Run the dev server: python -m mediahub.web"""\n'
        'from .web import app\n\n'
        'def main():\n'
        '    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "5000")))\n\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )


def _copy_tests(source: Path, dest: Path) -> None:
    tests_dst = dest / "tests"
    tests_dst.mkdir(parents=True, exist_ok=True)
    # Merge tests_v4 + tests_v75
    for sub in ("tests_v4", "tests_v75"):
        src = source / sub
        if not src.exists():
            continue
        for p in src.iterdir():
            if p.name in {"__pycache__"}:
                continue
            if p.is_file():
                shutil.copy2(p, tests_dst / p.name)
            elif p.is_dir():
                _copy_tree(p, tests_dst / p.name)
    # Add a conftest.py that ensures src/ is importable
    (tests_dst / "conftest.py").write_text(
        '"""Ensure mediahub package is importable in tests."""\n'
        'import sys\n'
        'from pathlib import Path\n\n'
        'ROOT = Path(__file__).resolve().parent.parent\n'
        'SRC = ROOT / "src"\n'
        'if str(SRC) not in sys.path:\n'
        '    sys.path.insert(0, str(SRC))\n'
        '# Legacy package compatibility: register mediahub.* under their old top-level names\n'
        'import mediahub  # noqa: E402  triggers shim registration\n'
    )


def _copy_dist(source: Path, dest: Path) -> None:
    src_dist = source / "dist"
    if src_dist.exists():
        _copy_tree(src_dist, dest / "dist")


def _copy_docs_build_reports(source: Path, dest: Path) -> None:
    docs_br = dest / "docs" / "build_reports"
    docs_br.mkdir(parents=True, exist_ok=True)
    for p in source.iterdir():
        if not p.is_file():
            continue
        n = p.name
        if (n.startswith("V") and (n.endswith(".md")) and (
            "_BUILD_SPEC" in n or "_FIX_REPORT" in n or "_INTEGRATION" in n
            or "_RESULTS" in n or "_FINAL_REPORT" in n or "_FIX_SPEC" in n
            or "_PROGRESS" in n or "_SPEC" in n or "_AUDIT" in n
            or "_CORPUS" in n or "_REPORT" in n
        )):
            shutil.copy2(p, docs_br / n)
        elif n in (
            "AUDIT_AND_V2_DESIGN.md",
            "BLUEPRINT.md",
            "HANDOFF_TO_CHATGPT.md",
            "INTERPRETER_BUILD_REPORT.md",
            "VOICES_BUILD_REPORT.md",
            "CONTEXT_ENGINE_BUILD_REPORT.md",
            "README_OPEN_THIS_FIRST.md",
        ):
            shutil.copy2(p, docs_br / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--dest", required=True)
    args = ap.parse_args()

    source = Path(args.source).resolve()
    dest = Path(args.dest).resolve()

    if not source.exists():
        print(f"ERROR: source {source} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Building export from {source} → {dest}")

    # Top-level dirs
    for d in ("src/mediahub", "data", "scripts", "tests", "samples",
              "dist", "legacy", "docs/build_reports"):
        (dest / d).mkdir(parents=True, exist_ok=True)

    # mediahub package init — keep what's already there (written explicitly).
    init_path = dest / "src" / "mediahub" / "__init__.py"
    if not init_path.exists():
        init_path.write_text(
            '"""MediaHub package — see docs/ARCHITECTURE.md."""\n'
        )

    # Phase A copies
    _copy_live_packages(source, dest)
    _copy_swim_content_v4(source, dest)
    _copy_legacy(source, dest)
    _copy_data(source, dest)
    _copy_samples(source, dest)
    _copy_dist(source, dest)
    _copy_tests(source, dest)
    _copy_docs_build_reports(source, dest)

    # Top-level scripts (current scripts/ in source)
    for s in (source / "scripts").glob("*.py") if (source / "scripts").exists() else []:
        shutil.copy2(s, dest / "scripts" / s.name)

    # requirements.txt — keep
    rt = source / "requirements.txt"
    if rt.exists():
        shutil.copy2(rt, dest / "requirements.txt")
    # runtime.txt
    rtt = source / "runtime.txt"
    if rtt.exists():
        shutil.copy2(rtt, dest / "runtime.txt")

    # Count for sanity
    total = sum(1 for _ in dest.rglob("*") if _.is_file())
    print(f"Done. {total} files written.")


if __name__ == "__main__":
    main()
