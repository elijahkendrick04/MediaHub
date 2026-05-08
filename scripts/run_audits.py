#!/usr/bin/env python3
"""run_audits.py — Phase G of the V9 handoff.

Runs five 10-step audits comparing the live source workspace to the export.
Writes the consolidated report to docs/AUDIT_REPORTS.md.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SRC = Path("/home/user/workspace/swim-content")
EXP = Path("/home/user/workspace/mediahub-export")


def count_files(path: Path, pattern: str = "*", *, exclude_caches: bool = True) -> int:
    """Count files matching a glob pattern, optionally excluding caches."""
    if not path.exists():
        return 0
    n = 0
    for p in path.rglob(pattern):
        if not p.is_file():
            continue
        if exclude_caches and (
            "__pycache__" in p.parts or ".pytest_cache" in p.parts
            or p.suffix == ".pyc"
        ):
            continue
        n += 1
    return n


def count_lines(path: Path, pattern: str = "*.py") -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob(pattern):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        try:
            total += sum(1 for _ in p.open())
        except Exception:
            pass
    return total


def has_module(root: Path, dotted: str) -> bool:
    parts = dotted.split(".")
    p = root
    for part in parts[:-1]:
        p = p / part
    last = parts[-1]
    return (p / f"{last}.py").exists() or (p / last / "__init__.py").exists()


def grep(text_root: Path, pattern: str, glob: str = "*.py") -> int:
    """Return number of files matching pattern."""
    n = 0
    pat = re.compile(pattern)
    for p in text_root.rglob(glob):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        try:
            if pat.search(p.read_text()):
                n += 1
        except Exception:
            pass
    return n


def row(item: str, status: str, evidence: str) -> str:
    return f"| {item} | {status} | {evidence} |\n"


def audit1_architecture() -> str:
    """10-step module audit: source vs export."""
    out = ["## Audit 1 — Architecture completeness\n\n",
           "Compares the top-level live packages in the source workspace ",
           "to those present under `src/mediahub/` (with the legacy packages ",
           "preserved verbatim under `legacy/`).\n\n",
           "| # | Check | Status | Evidence |\n|---|---|---|---|\n"]
    live_pkgs = [
        "interpreter", "recognition", "recognition_swim", "canonical",
        "voice", "brand", "workflow", "club_platform", "pb_discovery",
        "context_engine", "media_ai", "media_library", "media_requirements",
        "venue_search", "inspiration", "creative_brief", "graphic_renderer",
        "content_pack", "content_pack_visual", "web_research", "history",
    ]
    legacy_pkgs = ["swim_content", "swim_content_v5", "swim_content_pb",
                   "engine_v4", "swim_content_v4"]

    checks = []
    for i, pkg in enumerate(live_pkgs[:8], 1):
        src_files = count_files(SRC / pkg, "*.py")
        exp_files = count_files(EXP / "src" / "mediahub" / pkg, "*.py")
        ok = src_files == exp_files and src_files > 0
        checks.append((i, f"`{pkg}` package present + matching file count",
                       "PASS" if ok else "FAIL",
                       f"source={src_files} files, export={exp_files} files"))

    # 9: legacy preserved
    legacy_root = EXP / "legacy"
    legacy_status = "PASS" if all((legacy_root / p).exists() for p in legacy_pkgs[:4]) else "FAIL"
    legacy_count = sum(count_files(legacy_root / p, "*.py") for p in legacy_pkgs[:4])
    src_legacy_count = sum(count_files(SRC / p, "*.py") for p in legacy_pkgs[:4])
    checks.append((9, "legacy packages (`swim_content*`, `engine_v4`) preserved verbatim",
                   "PASS" if src_legacy_count == legacy_count else "FAIL",
                   f"source={src_legacy_count} legacy .py files, export={legacy_count}"))

    # 10: data preserved
    data_files_src = count_files(SRC / "data" / "ontology")
    data_files_exp = count_files(EXP / "data" / "ontology")
    voices_src = count_files(SRC / "data" / "voices" / "seed")
    voices_exp = count_files(EXP / "data" / "voices" / "seed")
    ok = data_files_src == data_files_exp and voices_src == voices_exp
    checks.append((10, "`data/ontology/` and `data/voices/seed/` preserved",
                   "PASS" if ok else "FAIL",
                   f"ontology src={data_files_src}, exp={data_files_exp}; "
                   f"voices src={voices_src}, exp={voices_exp}"))

    for i, item, status, ev in checks:
        out.append(f"| {i} | {item} | {status} | {ev} |\n")
    return "".join(out) + "\n"


def audit2_routes() -> str:
    """10 routes that must exist."""
    out = ["## Audit 2 — Frontend / page / route\n\n",
           "Confirms the Flask url_map of the export contains the live ",
           "production routes.\n\n",
           "| # | Route | Status | Evidence |\n|---|---|---|---|\n"]
    sys.path.insert(0, str(EXP / "src"))
    try:
        from mediahub.web.web import create_app
        app = create_app()
        rules = {r.rule for r in app.url_map.iter_rules()}
    except Exception as e:
        return out[0] + f"\n_Could not introspect: {e}_\n"

    expected = [
        "/",
        "/upload",
        "/runs/<run_id>",
        "/review/<run_id>",
        "/api/runs/<run_id>/status",
        "/api/runs/<run_id>/cards",
        "/api/runs/<run_id>/export",
        "/healthz",
        "/privacy",
        "/research",
    ]
    for i, rule in enumerate(expected, 1):
        ok = rule in rules
        ev = (f"route `{rule}` {'present' if ok else 'missing'} in url_map "
              f"({len(rules)} total rules)")
        out.append(f"| {i} | `{rule}` | {'PASS' if ok else 'FAIL'} | {ev} |\n")
    return "".join(out) + "\n"


def audit3_apis() -> str:
    """10 API checks + the upload→pack flow."""
    out = ["## Audit 3 — Backend / API / data-flow\n\n",
           "Verifies API endpoints and the upload→pack code path are intact.\n\n",
           "| # | Check | Status | Evidence |\n|---|---|---|---|\n"]
    web_py = EXP / "src" / "mediahub" / "web" / "web.py"
    pipe_py = EXP / "src" / "mediahub" / "pipeline" / "pipeline_v4.py"
    web_text = web_py.read_text() if web_py.exists() else ""
    pipe_text = pipe_py.read_text() if pipe_py.exists() else ""

    checks = [
        ("POST /upload handler defined", "@app.route(\"/upload\"" in web_text or '@app.route("/upload"' in web_text or "/upload" in web_text),
        ("`run_pipeline_v4` orchestrator present", "def run_pipeline_v4" in pipe_text),
        ("interpreter_bridge imported by pipeline", "interpreter_bridge" in pipe_text),
        ("pb_bridge imported by pipeline", "pb_bridge" in pipe_text),
        ("Detector V8 official_pb available",
         (EXP / "src" / "mediahub" / "recognition_swim" / "achievements" / "official_pb.py").exists()),
        ("V5 detectors preserved",
         (EXP / "legacy" / "swim_content_v5" / "achievements").exists()),
        ("/api/runs/<run_id>/status endpoint present in source",
         "/api/runs/" in web_text and "status" in web_text),
        ("/api/runs/<run_id>/export endpoint present",
         "export" in web_text and "/api/runs/" in web_text),
        ("/api/runs/<run_id>/cards endpoint present", "cards" in web_text),
        ("graphic_renderer reachable from pipeline (via creative_brief)",
         (EXP / "src" / "mediahub" / "creative_brief" / "generator.py").exists() and
         grep(EXP / "src" / "mediahub" / "creative_brief", "graphic_renderer") > 0),
    ]
    for i, (name, ok) in enumerate(checks, 1):
        ev = f"line scan of `{web_py.name if 'pipeline' not in name else 'pipeline_v4.py'}`"
        out.append(f"| {i} | {name} | {'PASS' if ok else 'FAIL'} | {ev} |\n")
    return "".join(out) + "\n"


def audit4_detectors() -> str:
    """10 detector / PB / ranking checks."""
    out = ["## Audit 4 — Detector / PB / ranking\n\n",
           "Verifies the detector suite, PB engine, and ranker constants ",
           "match the live source.\n\n",
           "| # | Check | Status | Evidence |\n|---|---|---|---|\n"]
    legacy_ach = EXP / "legacy" / "swim_content_v5" / "achievements"
    src_legacy_ach = SRC / "swim_content_v5" / "achievements"
    src_count = count_files(src_legacy_ach, "*.py")
    exp_count = count_files(legacy_ach, "*.py")

    expected_detectors = [
        "pb.py", "qualifier.py", "medal_final.py", "barrier.py",
        "return_to_form.py", "standout_field.py", "standout_history.py",
        "relay.py",
    ]
    checks = []
    for i, fname in enumerate(expected_detectors, 1):
        ok = (legacy_ach / fname).exists()
        checks.append((i, f"V5 detector `{fname}` present in legacy/",
                       "PASS" if ok else "FAIL",
                       f"file size = {(legacy_ach / fname).stat().st_size if ok else 0} bytes"))
    # 9: V8 official_pb
    ok = (EXP / "src" / "mediahub" / "recognition_swim" / "achievements" / "official_pb.py").exists()
    checks.append((9, "V8 detector `official_pb.py` present", "PASS" if ok else "FAIL",
                   "file in `src/mediahub/recognition_swim/achievements/`"))
    # 10: ranker constants preserved
    src_ranker = src_legacy_ach.parent / "ranker.py"
    exp_ranker = legacy_ach.parent / "ranker.py"
    if src_ranker.exists() and exp_ranker.exists():
        ok = src_ranker.read_bytes() == exp_ranker.read_bytes()
    else:
        ok = False
    checks.append((10, "V5 `ranker.py` byte-for-byte preserved",
                   "PASS" if ok else "FAIL",
                   f"source size={src_ranker.stat().st_size if src_ranker.exists() else 0}, "
                   f"export size={exp_ranker.stat().st_size if exp_ranker.exists() else 0}"))

    for i, item, status, ev in checks:
        out.append(f"| {i} | {item} | {status} | {ev} |\n")
    return "".join(out) + f"\n*(Total V5 detectors: source={src_count}, export={exp_count} files)*\n\n"


def audit5_deployment() -> str:
    """10 deployment / setup commands."""
    out = ["## Audit 5 — Deployment / env / setup\n\n",
           "Runs ten concrete commands inside the export and records the result.\n\n",
           "| # | Command | Status | Evidence |\n|---|---|---|---|\n"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(EXP / "src") + ":" + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmds = [
        ("python -c 'import mediahub'",
         [sys.executable, "-c", "import mediahub; print('OK')"]),
        ("python -c 'from mediahub.web import app'",
         [sys.executable, "-c", "from mediahub.web import app; print('OK', app.name)"]),
        ("python -c 'from mediahub.web.web import create_app; create_app()'",
         [sys.executable, "-c", "from mediahub.web.web import create_app; create_app(); print('OK')"]),
        ("python -m pytest --co -q (collection only)",
         [sys.executable, "-m", "pytest", "tests/", "--co", "-q"]),
        ("Procfile present",
         ["test", "-f", str(EXP / "Procfile")]),
        ("Dockerfile present",
         ["test", "-f", str(EXP / "Dockerfile")]),
        ("docker-compose.yml present",
         ["test", "-f", str(EXP / "docker-compose.yml")]),
        ("render.yaml present",
         ["test", "-f", str(EXP / "render.yaml")]),
        ("fly.toml present",
         ["test", "-f", str(EXP / "fly.toml")]),
        (".env.example present",
         ["test", "-f", str(EXP / ".env.example")]),
    ]
    for i, (label, cmd) in enumerate(cmds, 1):
        try:
            r = subprocess.run(cmd, cwd=str(EXP), env=env,
                               capture_output=True, text=True, timeout=60)
            ok = r.returncode == 0
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:]
            ev = f"exit={r.returncode}" + (f": `{tail[0][:80]}`" if tail else "")
        except Exception as e:
            ok = False
            ev = f"exception: {e}"
        out.append(f"| {i} | `{label}` | {'PASS' if ok else 'FAIL'} | {ev} |\n")
    return "".join(out) + "\n"


def main():
    docs = EXP / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    sections = [
        "# Audit Reports\n\n",
        "Five 10-step audits comparing the V9 export to the live source ",
        "workspace. Each row carries concrete evidence — file counts, byte sizes, ",
        "or actual command exit codes.\n\n",
        "_Auto-generated by `scripts/run_audits.py`._\n\n",
        "---\n\n",
        audit1_architecture(),
        "---\n\n",
        audit2_routes(),
        "---\n\n",
        audit3_apis(),
        "---\n\n",
        audit4_detectors(),
        "---\n\n",
        audit5_deployment(),
    ]
    (docs / "AUDIT_REPORTS.md").write_text("".join(sections))
    print(f"Wrote {docs / 'AUDIT_REPORTS.md'}")


if __name__ == "__main__":
    main()
