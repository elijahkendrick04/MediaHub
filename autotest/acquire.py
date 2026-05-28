"""Test-input acquisition — so the tester never gets stuck on one upload.

Three sources, in priority order:
  1. The bundled meet-file corpus (sample_data/ + samples/learning_corpus/).
  2. Files downloaded from a source list (autotest/sources.txt or the
     AUTOTEST_SOURCE_URLS env var) — "find files online and upload them".
  3. Generated edge-case / fuzz inputs (empty, truncated, wrong-extension,
     oversize, random bytes) to probe upload validation robustness.

``next_input(sweep)`` rotates deterministically across the pool so every sweep
exercises a *different* real file (anti-complacency). ``download_sources`` and
the optional ``discover_online`` agent hook keep the pool growing.

Nothing here decides pass/fail — it only supplies bytes for the finder to
upload. Downloads are size-capped (50 MB, matching the app limit) and cached
under autotest/cache/inputs (gitignored).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "inputs"
SOURCES_FILE = Path(__file__).resolve().parent / "sources.txt"

_MEET_SUFFIXES = (".pdf", ".zip", ".hy3", ".htm", ".html", ".sd3", ".cl2")
_EXCLUDE_NAME_HINTS = ("meta", "index", "eval_report")
_MAX_BYTES = 50 * 1024 * 1024  # app rejects >50 MB (HTTP 413)


def corpus_files() -> list[Path]:
    """Bundled meet files shipped in the repo."""
    out: list[Path] = []
    sample = REPO_ROOT / "sample_data" / "MISM-2024-Results.pdf"
    if sample.exists():
        out.append(sample.resolve())
    corpus = REPO_ROOT / "samples" / "learning_corpus"
    if corpus.exists():
        for p in sorted(corpus.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _MEET_SUFFIXES:
                continue
            if any(h in p.name.lower() for h in _EXCLUDE_NAME_HINTS):
                continue
            out.append(p.resolve())
    return out


def downloaded_files() -> list[Path]:
    if not CACHE_DIR.exists():
        return []
    return sorted(p.resolve() for p in CACHE_DIR.iterdir()
                  if p.is_file() and p.suffix.lower() in _MEET_SUFFIXES)


def pool() -> list[Path]:
    """Every real meet file available right now, de-duplicated."""
    seen: set[Path] = set()
    out: list[Path] = []
    for p in corpus_files() + downloaded_files():
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def next_input(sweep: int) -> Path | None:
    """Rotate across the pool by sweep index, so no two consecutive sweeps use
    the same file unless the pool has only one."""
    files = pool()
    if not files:
        return None
    return files[sweep % len(files)]


# --- acquisition: pull fresh files from the web ------------------------------
def _source_urls() -> list[str]:
    urls: list[str] = []
    env = os.environ.get("AUTOTEST_SOURCE_URLS", "")
    urls += [u.strip() for u in env.replace(",", " ").split() if u.strip()]
    if SOURCES_FILE.exists():
        for line in SOURCES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    # de-dup, keep order
    return list(dict.fromkeys(urls))


def _safe_name(url: str) -> str:
    base = url.split("?")[0].rstrip("/").split("/")[-1] or "download"
    base = "".join(c for c in base if c.isalnum() or c in "._-")[:80]
    if not Path(base).suffix:
        base += ".pdf"
    return base


def download_sources(urls: list[str] | None = None, *, timeout: float = 30.0) -> list[Path]:
    """Download each source URL into the cache (skipping ones already present).
    Returns the newly-downloaded paths. Failures are swallowed per-URL — a dead
    link must never stop the test loop."""
    urls = urls if urls is not None else _source_urls()
    if not urls:
        return []
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fresh: list[Path] = []
    for url in urls:
        dest = CACHE_DIR / _safe_name(url)
        if dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MediaHub-autotest/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read(_MAX_BYTES + 1)
            if not data or len(data) > _MAX_BYTES:
                continue
            dest.write_bytes(data)
            fresh.append(dest.resolve())
        except Exception:
            continue
    return fresh


def discover_online(max_urls: int = 5, *, timeout: float = 120.0) -> list[str]:
    """Optional agent hook: ask Claude Code (headless) to find public swim-meet
    result files on the web and append them to sources.txt. Gated by
    AUTOTEST_DISCOVER=1 and requires the `claude` CLI on the runner. This is the
    "find files online" autonomy — on the Cowork desktop it has real web access.
    Returns the URLs it added (best-effort; never raises)."""
    if os.environ.get("AUTOTEST_DISCOVER") != "1" or not shutil.which("claude"):
        return []
    prompt = (
        "Find up to {n} direct download URLs (ending .pdf, .zip, .hy3 or .htm) of "
        "PUBLICLY available swimming meet results files — Hy-Tek/Meet Manager PDFs, "
        "SwimMeetResults exports, county/regional result sheets. Only public, "
        "non-personal documents. Output ONLY the raw URLs, one per line, nothing else."
    ).format(n=max_urls)
    try:
        out = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                             timeout=timeout)
        found = [ln.strip() for ln in (out.stdout or "").splitlines()
                 if ln.strip().startswith("http")][:max_urls]
        if found:
            existing = set(_source_urls())
            new = [u for u in found if u not in existing]
            if new:
                with open(SOURCES_FILE, "a", encoding="utf-8") as fh:
                    fh.write("\n# discovered " + ", ".join(new[:1]) + " …\n")
                    fh.write("\n".join(new) + "\n")
            return new
    except Exception:
        return []
    return []


# --- fuzz / edge-case inputs -------------------------------------------------
def fuzz_input(kind: str, tmp_dir: Path) -> Path:
    """Generate a deliberately-broken input to test upload validation. The app
    must reject these gracefully (a clean message), never 500 or hang."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    if kind == "empty":
        p = tmp_dir / "empty.pdf"; p.write_bytes(b""); return p
    if kind == "truncated_pdf":
        p = tmp_dir / "truncated.pdf"; p.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj"); return p
    if kind == "wrong_ext":
        p = tmp_dir / "notreally.pdf"; p.write_text("this is plain text, not a pdf\n" * 50); return p
    if kind == "random":
        p = tmp_dir / "random.pdf"; p.write_bytes(os.urandom(64 * 1024)); return p
    if kind == "html_garbage":
        p = tmp_dir / "garbage.htm"; p.write_text("<html><body>" + ("x" * 10000) + "</body></html>"); return p
    p = tmp_dir / "tiny.pdf"; p.write_bytes(b"%PDF-1.4 tiny"); return p


FUZZ_KINDS = ("empty", "truncated_pdf", "wrong_ext", "random", "html_garbage")
