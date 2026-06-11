#!/usr/bin/env python3
"""MediaHub autonomous website tester — the *finder* half.

Boots the Flask app on a throwaway DATA_DIR, drives the real user flows in a
headless Chromium, and records defects into a deduplicated, fix-ready report
(``autotest/reports/BUGS.md`` + ``ledger.json``). It NEVER edits code.

What counts as a bug (real signals only):
  * HTTP 5xx on any navigation or API call
  * an unhandled Python traceback in the server log (even behind a 200)
  * uncaught JS exceptions / console errors in the browser
  * failed same-origin network requests (4xx/5xx assets, XHR, fetch)
  * a broken internal link (404 from a link the app itself rendered)
  * the primary flow failing functionally (upload→configure→process→review→export)

What is explicitly NOT a bug:
  * "AI unavailable" / ``ProviderNotConfigured`` when no LLM key is set — this is
    the *correct* behaviour per CLAUDE.md (surface an honest error, never fake
    output). Recorded under "skipped", never filed as a bug — UNLESS it crashes
    with a 5xx (graceful handling is required).
  * ``_recovery_page`` responses for stale/missing run ids (expected UX).
  * the ``tag bad`` CSS class (used all over for normal status chips/validation).

Usage:
  python -m autotest.run                 # boot locally, full sweep
  AUTOTEST_BASE_URL=http://host:port python -m autotest.run   # test a running target
Env knobs: AUTOTEST_MAX_PAGES, AUTOTEST_FLOW_TIMEOUT, AUTOTEST_HEADLESS,
           AUTOTEST_ALLOW_PROD (required to point at the Render production host).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from autotest import report  # noqa: E402
from autotest.report import Finding  # noqa: E402

SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
SAMPLE = REPO_ROOT / "sample_data" / "MISM-2024-Results.pdf"

PROD_HOSTS = ("mediahub-gzwc.onrender.com",)

# Signatures that mean "AI provider not configured" — expected, not a bug
# (unless it manifests as an unhandled 5xx).
AI_SIGNATURES = (
    "providernotconfigured", "claudeunavailableerror", "api key not configured",
    "ai unavailable", "no llm provider", "gemini_api_key", "anthropic_api_key",
    "provider not configured", "no ai provider",
)
TRACEBACK_MARK = "Traceback (most recent call last):"

# Links we must never click during a read-only crawl (mutate/destroy/leave site).
DESTRUCTIVE_HINTS = ("/delete", "/disconnect", "/clear", "/logout", "/destroy", "/remove")

# Binary / downloadable asset links. Navigating a real browser tab at one of
# these raises "Page.goto: Download is starting" — a harness artifact that was
# filed as a HIGH navigation_error (and burned fixer ticks on non-bugs). They
# are verified with the request API instead (still a real 404/5xx check), never
# with page.goto.
ASSET_EXTENSIONS = (
    ".woff2", ".woff", ".ttf", ".otf", ".eot",
    ".pdf", ".zip", ".csv", ".xlsx", ".xls", ".hy3", ".sd3",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".webm", ".mp3", ".wav", ".wasm", ".map",
)


def _is_asset_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(ASSET_EXTENSIONS)


def _is_ai_unconfigured(text: str) -> bool:
    low = (text or "").lower()
    return any(sig in low for sig in AI_SIGNATURES)


def _judge_inputs_digest(artifacts: dict) -> str:
    """Stable digest of EVERYTHING the AI judges would see this sweep — the
    judge-facing text artifacts (volatile run ids/timestamps stripped, real
    numbers kept) plus the surface screenshots. When it matches the previous
    sweep's digest the judges are skipped: re-judging an unchanged deployment
    re-burns subscription quota to re-state the same opinions (and re-confirm
    the same subjective findings) without any new information. Empty string on
    any failure → caller never skips on an unknown digest."""
    import hashlib
    try:
        from autotest import semantic
        arts = semantic._build_artifacts(artifacts)
    except Exception:
        return ""
    h = hashlib.sha1()
    for k in sorted(arts):
        h.update(k.encode("utf-8"))
        h.update(report.normalise_volatile(str(arts[k])).encode("utf-8"))
    for k in sorted(artifacts):
        if k.endswith("_screenshot"):
            p = REPO_ROOT / str(artifacts[k])
            try:
                h.update(p.read_bytes())
            except OSError:
                h.update(str(artifacts[k]).encode("utf-8"))
    return h.hexdigest()


def _extract_suspect(traceback_text: str) -> str:
    """Deepest in-repo frame from a traceback → 'src/mediahub/...py:LINE'."""
    frames = re.findall(r'File "([^"]+)", line (\d+), in (\S+)', traceback_text or "")
    repo_str = str(REPO_ROOT)
    best = ""
    for path, line, _fn in frames:
        if "mediahub" in path or path.startswith(repo_str):
            rel = path
            if path.startswith(repo_str):
                rel = os.path.relpath(path, repo_str)
            best = f"{rel}:{line}"  # keep walking → last (deepest) in-repo frame wins
    return best


def _last_exception_block(log_text: str) -> str:
    """Return the text from the last Traceback marker to the end."""
    idx = log_text.rfind(TRACEBACK_MARK)
    return log_text[idx:].strip() if idx != -1 else ""


def _seed_ready_profile(data_dir: Path) -> str | None:
    """Write a ready ClubProfile into the server's DATA_DIR so the tester can
    sign in and exercise the gated content flow WITHOUT depending on the AI
    brand-DNA onboarding (which needs an LLM key). Returns the profile id.

    The flow then pins this org via POST /api/organisation/active. We still get
    full coverage of upload→configure→process→review→export; the AI-driven
    onboarding wizard is exercised separately only when a key is present."""
    prev = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(data_dir)
    try:
        from mediahub.web.club_profile import ClubProfile, save_profile
        prof = ClubProfile(
            profile_id="autotest-club",
            display_name="Autotest Aquatics Club",
            short_name="Autotest",
            club_codes=["AUT", "AUTOTEST"],
            tone_notes=("Autonomous test organisation seeded by autotest to exercise the "
                        "full MediaHub content pipeline end to end."),
            brand_keywords=["fast", "proud", "local"],
        )
        save_profile(prof)
        return prof.profile_id
    except Exception:
        return None
    finally:
        if prev is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = prev


# --- server lifecycle --------------------------------------------------------
class AppServer:
    """Boots `python -m mediahub.web` on a throwaway DATA_DIR and captures its
    stderr so we can read tracebacks the production 500 handler hides."""

    def __init__(self, port: int):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None
        self.data_dir = Path(tempfile.mkdtemp(prefix="autotest-data-"))
        self.log_path = Path(tempfile.mkstemp(prefix="autotest-srv-", suffix=".log")[1])
        self._log_fh = None

    def start(self, ready_timeout: float = 60.0) -> None:
        env = os.environ.copy()
        env["DATA_DIR"] = str(self.data_dir)
        env["PORT"] = str(self.port)
        env["PYTHONUNBUFFERED"] = "1"
        self._log_fh = open(self.log_path, "w+b")
        # Inline launcher (not `-m mediahub.web`) so we can force threaded=True —
        # the dev __main__ runs single-threaded, which would serialise Playwright's
        # parallel asset requests and the status-poll-during-pipeline flow.
        launcher = (
            "import os; from mediahub.web.web import app; "
            "app.run(host='127.0.0.1', port=int(os.environ['PORT']), "
            "threaded=True, debug=False, use_reloader=False)"
        )
        self.proc = subprocess.Popen(
            [sys.executable, "-c", launcher],
            cwd=str(REPO_ROOT), env=env,
            stdout=self._log_fh, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + ready_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early (rc={self.proc.returncode}):\n{self.read_log()[-2000:]}")
            try:
                with urllib.request.urlopen(self.base + "/healthz", timeout=3) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.5)
        raise RuntimeError(f"server not ready in {ready_timeout}s:\n{self.read_log()[-2000:]}")

    def read_log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def log_size(self) -> int:
        try:
            return self.log_path.stat().st_size
        except OSError:
            return 0

    def log_since(self, pos: int) -> str:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                return fh.read()
        except OSError:
            return ""

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._log_fh:
            self._log_fh.close()


# --- route discovery ---------------------------------------------------------
def discover_get_routes() -> list[str]:
    """All registered no-argument GET routes, read from the app's url_map.
    Falls back to a curated seed list if the import fails."""
    fallback = ["/", "/activity", "/research", "/settings", "/privacy",
                "/status", "/upload", "/healthz", "/healthz/deps", "/healthz/usage"]
    prev = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="autotest-routes-")
    try:
        from mediahub.web.web import create_app
        app = create_app()
        routes = []
        for rule in app.url_map.iter_rules():
            if rule.arguments or rule.endpoint == "static":
                continue
            if "GET" not in (rule.methods or set()):
                continue
            routes.append(str(rule.rule))
        return sorted(set(routes)) or fallback
    except Exception:
        return fallback
    finally:
        if prev is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = prev


# --- browser-side event collectors -------------------------------------------
class Collector:
    """Buffers per-action browser events; cleared before each probe so events
    attribute to the action that triggered them (one sequential page)."""

    def __init__(self, base: str):
        self.base = base
        self.console: list[str] = []
        self.page_errors: list[str] = []
        self.failed: list[dict] = []

    def attach(self, page) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", lambda exc: self.page_errors.append(str(exc)))
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_requestfailed)

    def _on_console(self, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text or ""
        low = text.lower()
        # "Failed to load resource" is the browser's generic echo of an HTTP
        # failure the network collector already captured with structure — drop
        # the duplicate. AI-unconfigured notices surfaced client-side are
        # expected, not bugs.
        if "failed to load resource" in low or _is_ai_unconfigured(low):
            return
        loc = msg.location or {}
        where = f" ({loc.get('url', '')}:{loc.get('lineNumber', '')})" if loc.get("url") else ""
        self.console.append(f"{text}{where}")

    def _on_response(self, resp) -> None:
        try:
            if not resp.url.startswith(self.base):
                return
            st = resp.status
            rtype = resp.request.resource_type
            # Real failures only. 5xx anywhere is a server bug; a 404 on a
            # static asset is a genuinely broken css/js/img/font. 4xx on
            # xhr/fetch/document are app logic (409 "no active org", 401/403
            # guards, 400 validation) — correct responses, not bugs.
            if st >= 500 or (st == 404 and rtype in ("stylesheet", "script", "image", "font")):
                self.failed.append({"url": resp.url, "status": st, "type": rtype})
        except Exception:
            pass

    def _on_requestfailed(self, req) -> None:
        try:
            if req.url.startswith(self.base):
                self.failed.append({"url": req.url, "status": "failed",
                                    "type": req.resource_type, "failure": str(req.failure)})
        except Exception:
            pass

    def clear(self) -> None:
        self.console.clear()
        self.page_errors.clear()
        self.failed.clear()


# --- the tester --------------------------------------------------------------
class Tester:
    def __init__(self, server: AppServer | None, base: str, page, collector: Collector,
                 max_pages: int):
        self.server = server
        self.base = base
        self.page = page
        self.col = collector
        self.max_pages = max_pages
        self.engine = "chromium"             # B1: set by the launcher (engine[:device])
        self.findings: list[Finding] = []
        self.routes_probed = 0
        self.pages_crawled = 0
        self.visited: list[dict] = []        # (route, status) coverage for the judges
        self.artifacts: dict = {}            # captured for the semantic subagents
        # A4: exercised-ness of each captured artifact, keyed by raw capture point.
        # A flow we DIDN'T run this sweep (e.g. sign-up with AUTOTEST_SIGNUP=0) leaves
        # its artifact empty-by-absence; marked exercised=False here, it is dropped
        # before any judge sees it (semantic.filter_artifacts) — so a page that is
        # empty only because we skipped its flow can never become a finding.
        self.artifact_meta: dict[str, dict] = {}

    # screenshot a finding's page state, keyed by fingerprint
    def _shoot(self, f: Finding) -> None:
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / f"{f.fingerprint()}.png"
            self.page.screenshot(path=str(path), full_page=False)
            f.screenshot = os.path.relpath(path, REPO_ROOT)
        except Exception:
            pass

    def _add(self, f: Finding, shoot: bool = True) -> None:
        # B1: on a non-default engine, tag the finding so its fingerprint doesn't
        # collapse with the chromium run's (a WebKit-only layout break is its own bug).
        if self.engine and self.engine != "chromium" and f.is_bug:
            f.evidence = (f.evidence or "") + f"\n[engine={self.engine}]"
        if shoot and f.is_bug:
            self._shoot(f)
        self.findings.append(f)

    # full-page screenshot of a primary surface, for the vision judge to look at
    def _capture_surface(self, name: str) -> None:
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / f"surface-{name}.png"
            self.page.screenshot(path=str(path), full_page=True)
            self.artifacts[f"{name}_screenshot"] = os.path.relpath(path, REPO_ROOT)
            self._run_visual(name, str(path))   # B3: deterministic baseline diff
        except Exception:
            pass

    def _run_visual(self, surface: str, screenshot_path: str) -> None:
        """B3: diff this surface against its committed visual baseline — a DETERMINISTIC
        ``visual_regression`` finding. Honest-skips when no baseline exists yet (the
        deterministic backbone for the vision judge)."""
        if os.environ.get("AUTOTEST_VISUAL", "1") == "0":
            return
        try:
            from autotest import visual_regression
            for f in visual_regression.check(surface, screenshot_path,
                                             getattr(self, "engine", "chromium")):
                self._add(f, shoot=False)
        except Exception:
            pass

    def reconcile_artifact_meta(self) -> None:
        """A4: after the content journey, mark the canonical judge-facing artifacts
        whose flow was NOT exercised this sweep. A key absent from ``self.artifacts``
        is empty-by-absence (its flow didn't run, e.g. sign-up with AUTOTEST_SIGNUP=0)
        — mark it ``exercised=False`` so semantic.filter_artifacts drops it before any
        judge sees it. A genuinely-empty artifact from a flow that DID run is present
        (even if blank) and stays judge-eligible (a real empty state can be a finding)."""
        not_run = {
            "home_text": "home page not captured this sweep",
            "signup_text": "sign-up / onboarding flow not exercised this sweep",
            "review_text": "no review page inspected this sweep",
            "export_json": "no content pack produced or captured this sweep",
        }
        for key, reason in not_run.items():
            if key not in self.artifacts:
                self.artifact_meta.setdefault(
                    key, {"exercised": False, "skipped_reason": reason})

    def ensure_signed_in(self, profile_id: str) -> bool:
        """Pin the seeded org into the browser session (gate-exempt API), so
        the gated content routes are reachable. A failure here is a real bug —
        the whole product is unusable if you can't sign in."""
        try:
            r = self.page.context.request.post(
                self.base + "/api/organisation/active",
                form={"profile_id": profile_id})
            ok = r.ok
            check = self.page.context.request.get(self.base + "/api/organisation/active")
            pinned = profile_id in (check.text() if check.ok else "")
            if ok and pinned:
                return True
            self._add(Finding(
                category="flow_failure", severity="critical",
                title="Could not pin/sign-in the test organisation",
                route="/api/organisation/active",
                expected="POST profile_id pins the org; GET then reports it active",
                actual=f"POST ok={ok} (HTTP {r.status}); GET-active contains id={pinned}",
                evidence=(r.text()[:600] if not ok else check.text()[:600]),
                repro=["POST /api/organisation/active with form profile_id=<id>",
                       "GET /api/organisation/active"]), shoot=False)
            return False
        except Exception as exc:
            self._add(Finding(
                category="flow_failure", severity="critical",
                title="Sign-in request raised", route="/api/organisation/active",
                expected="Sign-in pins the org", actual=str(exc), evidence=str(exc)),
                shoot=False)
            return False

    def ensure_signed_in_live(self) -> bool:
        """Sign in on a LIVE deployment. Enumerate the orgs on /sign-in and
        prefer a REAL, populated one (so the judges get real content) over our
        own throwaway 'autotest-*' test orgs. AUTOTEST_PROFILE_ID forces one.
        Records the chosen org + a run id in artifacts when content is found."""
        try:
            forced = os.environ.get("AUTOTEST_PROFILE_ID", "").strip()
            self.page.goto(self.base + "/sign-in", wait_until="domcontentloaded", timeout=30000)
            pids = self.page.evaluate(
                "()=>Array.from(new Set(Array.from(document.querySelectorAll('[name=profile_id]'))"
                ".map(e=>e.value).filter(Boolean)))")
            if forced:
                pids = [forced]
            if not pids:
                self._add(Finding(category="live_signin", severity="info", is_bug=False,
                    title="Live sign-in: no organisation listed", route="/sign-in",
                    expected="At least one org on the sign-in picker",
                    actual="No profile_id control found", evidence=self.page.content()[:800]),
                    shoot=False)
                return False
            # real orgs first, our own test orgs last
            ordered = ([p for p in pids if not p.startswith("autotest")]
                       + [p for p in pids if p.startswith("autotest")])
            signed_any = False
            for pid in ordered:
                self.page.context.request.post(self.base + "/sign-in", form={"profile_id": pid})
                self.page.goto(self.base + "/activity", wait_until="domcontentloaded", timeout=30000)
                if "/sign-in" in self.page.url:
                    continue
                signed_any = True
                runs = re.findall(r"/(?:review|runs)/([A-Za-z0-9_-]{6,})", self.page.content())
                if runs:
                    self.artifacts["live_org"] = pid
                    self.artifacts["live_run_id"] = runs[0]
                    return True
            return signed_any
        except Exception as exc:
            self._add(Finding(category="live_signin", severity="medium",
                title="Live sign-in raised", route="/sign-in",
                expected="Sign-in pins an org", actual=str(exc)[:200], evidence=str(exc)),
                shoot=False)
            return False

    def judge_existing_runs(self, max_runs: int = 6) -> int:
        """Live: inspect existing runs in the signed-in org. Deterministically
        flag concrete bugs — a run that produced 0 content cards, and a run
        listed in /activity whose export 404s — and capture a representative
        run's content for the AI judges. Returns the number inspected."""
        try:
            self.page.goto(self.base + "/activity", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return 0
        runs = list(dict.fromkeys(
            re.findall(r"/(?:review|runs)/([A-Za-z0-9_-]{6,})", self.page.content())))
        inspected = zero_card = 0
        captured = False
        for rid in runs[:max_runs]:
            inspected += 1
            try:
                r = self.page.context.request.get(self.base + f"/api/runs/{rid}/export")
            except Exception:
                continue
            if r.status == 404:
                self._add(Finding(category="broken_run_state", severity="medium",
                    title=f"Run shown in /activity but its export 404s ({rid})",
                    route="/api/runs/<id>/export",
                    expected="A run listed in /activity has a fetchable export",
                    actual=f"GET /api/runs/{rid}/export -> 404 (inconsistent run state)",
                    evidence=f"run {rid} appears on /activity",
                    repro=["Sign in", "Open /activity", f"GET /api/runs/{rid}/export"]))
                continue
            if not r.ok:
                continue
            try:
                data = r.json()
            except Exception:
                continue
            cards = data.get("cards") or []
            if not cards:
                zero_card += 1
                self.artifacts.setdefault("export_json", data)
            elif not captured:
                self.artifacts["export_json"] = data
                self.artifacts["live_run_id"] = rid
                captured = True
                try:
                    self.probe(self.base + f"/review/{rid}", "live:review",
                               route_template="/review/<run_id>")
                    self.artifacts["review_text"] = self.page.inner_text("body")[:6000]
                except Exception:
                    pass
        # Systemic, deterministic signal: real meets are producing no content.
        if inspected and zero_card:
            sev = "high" if zero_card >= max(2, inspected // 2) else "medium"
            self._add(Finding(category="content_empty", severity=sev,
                title=f"{zero_card}/{inspected} recent runs produced ZERO content cards",
                route="/review/<run_id>",
                expected="Real meet uploads should generate content cards",
                actual=f"{zero_card} of {inspected} inspected runs have 0 cards — the content "
                       "engine is generating nothing for real meets",
                evidence="Inspected runs from /activity via /api/runs/<id>/export",
                repro=["Sign in", "Open /activity", "Open a recent run — 0 cards"]))
        return inspected

    def run_signup_flow(self) -> str:
        """Exercise the new-club SIGN-UP / onboarding journey
        (/organisation/setup -> /organisation/setup/capture) — what a brand-new
        club hits. On a live site this creates a clearly-labelled test org
        (authorised). Captures the onboarding text for the user-brain judge and
        flags crashes."""
        self._flow_log_pos = self.server.log_size() if self.server else 0
        st, html, _ = self.probe(self.base + "/organisation/setup", "signup:get",
                                 route_template="/organisation/setup")
        if st is not None and st >= 500:
            return "failed:setup-page-5xx"
        if 'name="display_name"' not in html:
            return "skipped:no-setup-form"
        name = f"Autotest Club {uuid.uuid4().hex[:6]}"
        website = os.environ.get("AUTOTEST_SIGNUP_WEBSITE", "").strip()
        try:
            self.page.fill('input[name="display_name"]', name)
            self.page.evaluate(
                """()=>{const s=document.querySelector('select[name=org_type]');
                   if(s){for(const o of s.options){if(o.value){s.value=o.value;
                     s.dispatchEvent(new Event('change',{bubbles:true}));break;}}}}""")
            if website:
                try:
                    self.page.fill('input[name="website_url"]', website)
                except Exception:
                    pass
        except Exception as exc:
            self._add(Finding(category="flow_failure", severity="high",
                title="Sign-up form could not be filled", route="/organisation/setup",
                expected="A fillable org-creation form", actual=str(exc)[:200],
                evidence=str(exc), repro=["Open /organisation/setup"]))
            return "failed:fill"
        if not (self._submit('form[action="/organisation/setup/capture"]')
                or self._submit('form')):
            return "failed:submit"
        self._settle()
        try:
            self.artifacts["signup_text"] = self.page.inner_text("body")[:5000]
        except Exception:
            pass
        new_log = self.server.log_since(getattr(self, "_flow_log_pos", 0)) if self.server else ""
        tb = _last_exception_block(new_log) if TRACEBACK_MARK in new_log else ""
        content = self.page.content()
        if tb or 'data-lane="500"' in content:
            self._add(Finding(category="flow_failure", severity="critical",
                title="Sign-up / onboarding crashed", route="/organisation/setup/capture",
                expected="Onboarding proceeds without error after submitting org details",
                actual=f"Crash during capture (landed {self.page.url})",
                evidence=(tb or content[:1500]), suspect=_extract_suspect(tb) if tb else "",
                repro=["Open /organisation/setup", "Fill org name + type", "Submit"]))
            return "failed:capture-crash"
        return f"completed (landed {urlparse(self.page.url).path})"

    def _active_profile_id_live(self) -> str:
        try:
            r = self.page.context.request.get(self.base + "/api/organisation/active")
            if r.ok:
                return str((r.json() or {}).get("profile_id") or "").strip()
        except Exception:
            pass
        return ""

    def _delete_test_profile(self, pid: str) -> str:
        """Delete a profile via /sign-in/delete. HARD-GUARDED: only ever deletes
        a profile whose id starts with 'autotest' (a profile the tester itself
        created). It will never delete a real org."""
        if not pid or not pid.startswith("autotest"):
            return f"refused — not a test profile ({pid!r})"
        try:
            r = self.page.context.request.post(self.base + "/sign-in/delete",
                                               form={"profile_id": pid})
            chk = self.page.context.request.get(self.base + "/sign-in")
            gone = pid not in (chk.text() if chk.ok else pid)
            return f"deleted (HTTP {r.status}, confirmed={gone})"
        except Exception as exc:
            return f"delete-error: {exc}"

    def run_full_lifecycle(self, flow_timeout: float) -> str:
        """The full new-club journey on a live site: CREATE a test profile
        (sign-up) → UPLOAD a real meet file with real race results → configure
        with a real club → process → judge → DELETE the test profile. Exercises
        creation, upload, and deletion. Deletion is guarded to test profiles."""
        signup = self.run_signup_flow()
        self.artifacts["signup_result"] = signup
        pid = self._active_profile_id_live()
        self.artifacts["lifecycle_profile_id"] = pid
        # Upload a REAL meet (real race results) and drive the content flow.
        upload = self.run_primary_flow(flow_timeout)
        # Clean up: delete the test profile we created (and verify the route).
        deleted = self._delete_test_profile(pid)
        return f"lifecycle: signup={signup} | upload={upload} | delete={deleted}"

    def probe(self, url: str, label: str, *, route_template: str | None = None,
              from_link: bool = False) -> tuple[int | None, str, list[str]]:
        """Navigate to `url`, run every detector, return (status, html, links)."""
        route = route_template or urlparse(url).path or url
        self.col.clear()
        log_pos = self.server.log_size() if self.server else 0
        status: int | None = None
        html = ""
        try:
            resp = self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
            status = resp.status if resp else None
            try:
                self.page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            html = self.page.content()
        except Exception as exc:
            self._add(Finding(
                category="navigation_error", severity="high",
                title=f"Navigation failed: {label}",
                route=route, expected=f"{route} loads",
                actual=f"Playwright navigation raised: {exc}",
                evidence=str(exc), repro=[f"Open {url}"]))
            return None, "", []

        new_log = self.server.log_since(log_pos) if self.server else ""
        self._evaluate(route, url, label, status, html, new_log, from_link)
        if status and status < 400:
            self._run_a11y(route)   # B2: deterministic axe-core pass on the rendered DOM
        self.visited.append({"route": route, "status": status})
        links = self._extract_links(html) if status and status < 400 else []
        return status, html, links

    def _evaluate(self, route: str, url: str, label: str, status: int | None,
                  html: str, new_log: str, from_link: bool) -> None:
        is_500_page = 'data-lane="500"' in html
        traceback_block = _last_exception_block(new_log) if TRACEBACK_MARK in new_log else ""

        # 1) unhandled server traceback (highest-signal; even behind a 200)
        if traceback_block:
            ai = _is_ai_unconfigured(traceback_block)
            self._add(Finding(
                category="server_traceback",
                severity="critical" if route in ("/", "/upload") else "high",
                title=("Unhandled error (AI path not gracefully handled) at " + route)
                      if ai else f"Unhandled server traceback at {route}",
                route=route,
                expected=("Missing AI provider should surface a clean message, not 500"
                          if ai else f"{route} handles the request without raising"),
                actual=f"Server logged an unhandled exception (HTTP {status}).",
                evidence=traceback_block,
                suspect=_extract_suspect(traceback_block),
                repro=[f"Open {url}"]))

        # 2) HTTP 5xx
        if status is not None and status >= 500 and not traceback_block:
            self._add(Finding(
                category="http_5xx", severity="critical" if route == "/" else "high",
                title=f"HTTP {status} at {route}", route=route,
                expected=f"{route} returns a 2xx/3xx response",
                actual=f"HTTP {status}" + (" (rendered 500 page)" if is_500_page else ""),
                evidence=(new_log[-2000:] if new_log.strip() else html[:1500]),
                repro=[f"Open {url}"]))

        # 3) broken internal link: a link the app itself rendered points at a
        #    HARD 404 (no recovery-page escape hatch). A registered route that
        #    soft-404s a param-less probe is its own deliberate choice — every
        #    MediaHub dead-end renders a `mh-hero` recovery page with CTAs, so
        #    we only flag 404s that lack that chrome, and only when we got here
        #    by following a link (not by probing a route directly).
        elif (from_link and status in (404, 410)
              and "mh-hero-actions" not in html and "data-lane" not in html):
            self._add(Finding(
                category="broken_link", severity="medium",
                title=f"Broken internal link → HTTP {status}: {route}", route=route,
                expected="Links the app renders resolve to a real page",
                actual=f"HTTP {status} with no recovery page",
                evidence=html[:1200], repro=[f"Open {url}"]))

        # 4) uncaught JS exceptions
        for exc in self.page_errors_snapshot():
            self._add(Finding(
                category="page_exception", severity="medium",
                title=f"Uncaught JS exception on {route}", route=route,
                expected="No uncaught client-side exceptions",
                actual=exc.splitlines()[0] if exc else "pageerror",
                evidence=exc, repro=[f"Open {url}"]), shoot=False)

        # 5) console errors
        for msg in self.col.console:
            if _is_ai_unconfigured(msg):
                continue  # benign "AI unavailable" surfaced client-side
            self._add(Finding(
                category="js_console_error", severity="low",
                title=f"Console error on {route}", route=route,
                expected="Clean browser console",
                actual=msg.splitlines()[0][:200],
                evidence=msg, repro=[f"Open {url}", "Open devtools console"]), shoot=False)

        # 6) failed same-origin network requests (assets / xhr)
        for fr in self.col.failed:
            st = fr.get("status")
            sev = "high" if (isinstance(st, int) and st >= 500) else "medium"
            self._add(Finding(
                category="network_error", severity=sev,
                title=f"{fr.get('type', 'request')} {st} on {route}", route=route,
                expected="All same-origin sub-requests succeed",
                actual=f"{fr.get('type')} → {st}: {fr.get('url')}",
                evidence=json.dumps(fr, indent=2), repro=[f"Open {url}"]), shoot=False)

    def _run_a11y(self, route: str) -> None:
        """B2: run axe-core against the just-rendered page and record WCAG violations
        as DETERMINISTIC ``a11y`` findings. Honest-skips when axe isn't available (no
        crash, no invented findings) — exactly like the AI judges with no key."""
        if os.environ.get("AUTOTEST_A11Y", "1") == "0":
            return
        try:
            from autotest import a11y
            for f in a11y.run(self.page, route):
                self._add(f, shoot=False)
        except Exception:
            pass

    # pageerror buffer is on the collector
    def page_errors_snapshot(self) -> list[str]:
        return list(self.col.page_errors)

    def _extract_links(self, html: str) -> list[str]:
        out = []
        for href in re.findall(r'href="([^"#]+)"', html):
            if href.startswith(("mailto:", "javascript:", "tel:", "data:")):
                continue
            absu = urljoin(self.base + "/", href)
            if not absu.startswith(self.base):
                continue
            if any(h in absu for h in DESTRUCTIVE_HINTS):
                continue
            out.append(absu.split("#")[0])
        return out

    # --- the primary user flow ------------------------------------------------
    def run_primary_flow(self, flow_timeout: float) -> str:
        # The PRIMARY flow uses a known-good meet so the pipeline produces REAL
        # content (cards/captions) for the AI judges to evaluate — testing an
        # empty shell finds nothing. AUTOTEST_INPUT overrides; rotated/fuzz
        # inputs belong to separate variety passes, not the core flow.
        override = os.environ.get("AUTOTEST_INPUT")
        if override and Path(override).exists():
            input_file = Path(override)
        elif SAMPLE.exists():
            input_file = SAMPLE
        else:
            from autotest import acquire
            input_file = acquire.next_input(int(os.environ.get("AUTOTEST_SWEEP", "0")))
        if input_file is None:
            return "skipped:no-input"
        self.artifacts["input_file"] = str(input_file)
        self._flow_log_pos = self.server.log_size() if self.server else 0
        self.probe(self.base + "/upload", "flow:upload-get", route_template="/upload")
        # locate + fill the file input
        finp = self.page.locator("#mh-upload-form input[type=file]")
        if finp.count() == 0:
            finp = self.page.locator("input[type=file]")
        if finp.count() == 0:
            self._add(Finding(category="flow_failure", severity="critical",
                              title="Upload page has no file input", route="/upload",
                              expected="A file <input> to choose a meet results file",
                              actual="No <input type=file> found on /upload",
                              evidence=self.page.content()[:1500],
                              repro=["Open /upload"]))
            return "failed:no-file-input"
        log_pos = self.server.log_size() if self.server else 0
        finp.first.set_input_files(str(input_file))
        if not self._submit("#mh-upload-form"):
            return "failed:upload-submit"
        self._settle()
        if "/upload/configure" not in self.page.url:
            return self._no_progress(
                "Upload did not advance to the configure step", "/upload",
                "Redirect to /upload/configure?run_id=… (or a clear rejection message)",
                f"Landed on {self.page.url}", "no-configure")

        # configure: pick a club + submit
        sel = self.page.locator("select[name=club_filter]")
        if sel.count() == 0:
            return self._no_progress(
                "Configure step has no club_filter select", "/upload/configure",
                "A <select name=club_filter> of parsed clubs (or a clear 'no clubs found' state)",
                "Select not present (parsing found no clubs for this file)", "no-club-select")
        # Pick a club that actually yields content (a real club in the meet),
        # preferring AUTOTEST_PRIMARY_CLUB (default "manchester" — present in the
        # bundled MISM sample and known to produce cards), else the first club.
        preferred = os.environ.get("AUTOTEST_PRIMARY_CLUB", "manch").lower()
        value = self.page.evaluate(
            """(pref) => {const s=document.querySelector('select[name=club_filter]');
                 if(!s) return null;
                 let first=null;
                 for (const o of s.options){
                   const v=(o.value||'').trim(); if(!v) continue;
                   if(first===null) first=v;
                   if(((o.textContent||v).toLowerCase()).includes(pref)) return v;
                 }
                 return first;}""", preferred)
        if not value:
            return self._no_progress(
                "No selectable club on configure step", "/upload/configure",
                "At least one club parsed from the file",
                "club_filter select had no non-empty option", "no-club-option")
        log_pos = self.server.log_size() if self.server else 0
        sel.first.select_option(value=value)
        form_sel = "form:has(select[name=club_filter])"
        if not self._submit(form_sel):
            return "failed:configure-submit"
        self._settle()

        m = re.search(r"/runs/([A-Za-z0-9_-]+)", self.page.url)
        if not m:
            return self._no_progress(
                "Configure submit did not start a run", "/upload/configure",
                "Redirect to /runs/<id>", f"Landed on {self.page.url}", "no-run")
        run_id = m.group(1)

        status, err = self._poll_status(run_id, flow_timeout)
        if status == "done":
            return self._verify_results(run_id)
        if status == "error":
            if _is_ai_unconfigured(err):
                self._add(Finding(category="ai_unconfigured", severity="info",
                                  title="Pipeline stopped: AI provider not configured",
                                  route="/api/runs/<id>/status",
                                  expected="With an LLM key set, the run completes",
                                  actual=f"Run errored (expected without a key): {err[:200]}",
                                  evidence=err, is_bug=False), shoot=False)
                return "ai-skip (no LLM key)"
            self._flow_fail(f"Run failed: {err[:80]}", f"/runs/{run_id}",
                            "Run completes to 'done'", f"status=error: {err[:300]}", 0,
                            extra_evidence=err)
            return "failed:run-error"
        self._flow_fail("Run never completed", f"/runs/{run_id}",
                        f"Run reaches done/error within {flow_timeout:.0f}s",
                        f"Still '{status}' at timeout", 0)
        return "failed:timeout"

    def _verify_results(self, run_id: str) -> str:
        st, _, _ = self.probe(self.base + f"/review/{run_id}", "flow:review",
                              route_template="/review/<run_id>")
        try:
            self.artifacts["review_text"] = self.page.inner_text("body")[:6000]
        except Exception:
            pass
        self._capture_surface("review")  # for the vision judge to look at
        # export is JSON; check via the context request (carries session cookie)
        try:
            r = self.page.context.request.get(self.base + f"/api/runs/{run_id}/export")
            if r.status == 200:
                try:
                    self.artifacts["export_json"] = r.json()
                except Exception:
                    self.artifacts["export_json"] = {"_raw": r.text()[:2000]}
            if r.status != 200:
                self._add(Finding(category="flow_failure", severity="high",
                                  title="Export endpoint did not return the run",
                                  route="/api/runs/<id>/export",
                                  expected="HTTP 200 with the run JSON",
                                  actual=f"HTTP {r.status}",
                                  evidence=r.text()[:1000],
                                  repro=[f"GET /api/runs/{run_id}/export"]), shoot=False)
                return "failed:export"
        except Exception as exc:
            self._add(Finding(category="flow_failure", severity="high",
                              title="Export request raised", route="/api/runs/<id>/export",
                              expected="Export returns the run JSON",
                              actual=str(exc), evidence=str(exc)), shoot=False)
            return "failed:export"
        # Honest status: a flow that 'passes' but yields zero content cards is
        # not the same as one that produced a pack. (The council flagged the
        # original blanket 'passed' as a misleading success signal.)
        n_cards = len((self.artifacts.get("export_json") or {}).get("cards") or [])
        if not (st and st < 400):
            return "passed-with-review-issue"
        return "passed" if n_cards > 0 else "passed-empty"

    # --- flow helpers ---------------------------------------------------------
    def _submit(self, form_selector: str) -> bool:
        for sub in (f"{form_selector} button[type=submit]", f"{form_selector} input[type=submit]",
                    f"{form_selector} button"):
            loc = self.page.locator(sub)
            if loc.count() > 0:
                try:
                    loc.first.click()
                    return True
                except Exception:
                    break
        try:
            self.page.eval_on_selector(form_selector, "f => f.submit()")
            return True
        except Exception as exc:
            self._add(Finding(category="flow_failure", severity="high",
                              title=f"Could not submit form {form_selector}",
                              route=self.page.url, expected="Form submits",
                              actual=str(exc), evidence=str(exc)), shoot=False)
            return False

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

    def _poll_status(self, run_id: str, timeout: float) -> tuple[str, str]:
        deadline = time.time() + timeout
        last = "unknown"
        while time.time() < deadline:
            try:
                r = self.page.context.request.get(self.base + f"/api/runs/{run_id}/status")
                data = r.json()
                last = data.get("status", "unknown")
                if last in ("done", "error"):
                    return last, data.get("error") or ""
            except Exception:
                pass
            time.sleep(2.0)
        return last, ""

    def _no_progress(self, reason: str, route: str, expected: str, actual: str,
                     soft_result: str) -> str:
        """The flow can't continue from here. If the app crashed (5xx/traceback)
        it's a real bug. If it responded gracefully (e.g. rejected a junk upload,
        or a PDF that yields no clubs) this input simply isn't drivable — record a
        low-key non-bug note and stop. Keeps input rotation + fuzzing from
        spamming false 'critical' failures."""
        new_log = self.server.log_since(getattr(self, "_flow_log_pos", 0)) if self.server else ""
        tb = _last_exception_block(new_log) if TRACEBACK_MARK in new_log else ""
        try:
            crashed = bool(tb) or 'data-lane="500"' in self.page.content()
        except Exception:
            crashed = bool(tb)
        if crashed:
            self._flow_fail(reason, route, expected, actual, getattr(self, "_flow_log_pos", 0))
            return "failed:" + soft_result
        self._add(Finding(
            category="input_not_drivable", severity="info",
            title=f"{reason} (graceful — input not drivable)", route=route,
            expected=expected,
            actual=actual + " — app responded gracefully (HTTP 2xx, no crash)",
            evidence=f"input={self.artifacts.get('input_file', '?')}\n{new_log[-600:]}",
            is_bug=False), shoot=False)
        return "skipped:" + soft_result

    def _flow_fail(self, title: str, route: str, expected: str, actual: str,
                   log_pos: int, extra_evidence: str = "") -> None:
        new_log = self.server.log_since(log_pos) if (self.server and log_pos) else ""
        tb = _last_exception_block(new_log)
        self._add(Finding(
            category="flow_failure",
            severity="critical",
            title=title, route=route, expected=expected, actual=actual,
            evidence=(tb or extra_evidence or new_log[-1500:] or self.page.content()[:1200]),
            suspect=_extract_suspect(tb) if tb else "",
            repro=["Upload sample_data/MISM-2024-Results.pdf at /upload",
                   "Pick a club on the configure step and submit",
                   "Wait for the run to finish, open /review/<id>"]))

    # --- crawl ----------------------------------------------------------------
    def crawl(self, seeds: list[str]) -> None:
        seen: set[str] = set()
        queue = list(dict.fromkeys(seeds))
        while queue and self.pages_crawled < self.max_pages:
            url = queue.pop(0)
            path = urlparse(url).path
            if url in seen:
                continue
            seen.add(url)
            if _is_asset_url(url):
                # A font/PDF/image link: verify it serves (request API), never
                # page.goto it — navigation to a download is a harness artifact,
                # not a product bug. Doesn't consume the page budget.
                self._check_asset(url, path)
                continue
            self.pages_crawled += 1
            _, _, links = self.probe(url, f"crawl:{path}", route_template=path, from_link=True)
            for ln in links:
                if ln not in seen and ln not in queue:
                    queue.append(ln)

    def _check_asset(self, url: str, route: str) -> None:
        """Deterministic check that a linked binary asset actually serves. A
        404/5xx (or a dead connection) is a REAL broken-asset bug — same class as
        the in-page sub-request detector — filed as ``network_error``."""
        try:
            resp = self.page.request.get(url, timeout=15000)
            st = resp.status
            if st >= 400:
                self._add(Finding(
                    category="network_error",
                    severity="high" if st >= 500 else "medium",
                    title=f"Linked asset {st}: {route}", route=route,
                    expected="Assets the app links to (fonts, images, files) serve successfully",
                    actual=f"GET {route} → HTTP {st}",
                    evidence=f"GET {url} returned HTTP {st}",
                    repro=[f"GET {url}"]), shoot=False)
        except Exception as exc:
            self._add(Finding(
                category="network_error", severity="medium",
                title=f"Linked asset unreachable: {route}", route=route,
                expected="Assets the app links to (fonts, images, files) serve successfully",
                actual=f"request failed: {str(exc)[:200]}",
                evidence=str(exc), repro=[f"GET {url}"]), shoot=False)


def _launch_browser(pw, headless: bool):
    """B1: pick the Playwright engine (AUTOTEST_BROWSER = chromium|firefox|webkit)
    and an optional mobile device descriptor (AUTOTEST_DEVICE, e.g. 'iPhone 13').
    Returns (browser, context, engine_label). Falls back to chromium / no-device on
    an unknown value, so a typo degrades instead of crashing the sweep."""
    name = os.environ.get("AUTOTEST_BROWSER", "chromium").strip().lower()
    engine = name if name in ("chromium", "firefox", "webkit") else "chromium"
    btype = {"firefox": pw.firefox, "webkit": pw.webkit}.get(engine, pw.chromium)
    browser = btype.launch(headless=headless)
    ctx_kwargs: dict = {"ignore_https_errors": True}
    device = os.environ.get("AUTOTEST_DEVICE", "").strip()
    if device:
        try:
            ctx_kwargs = {**pw.devices[device], **ctx_kwargs}
            engine = f"{engine}:{device}"
        except Exception:
            pass   # unknown device → desktop context, engine label unchanged
    return browser, browser.new_context(**ctx_kwargs), engine


def _resolve_base() -> tuple[str, AppServer | None]:
    external = os.environ.get("AUTOTEST_BASE_URL", "").strip()
    if external:
        host = urlparse(external).hostname or ""
        if host in PROD_HOSTS and os.environ.get("AUTOTEST_ALLOW_PROD") != "1":
            sys.exit("Refusing to test the production host without AUTOTEST_ALLOW_PROD=1 "
                     "(CLAUDE.md: never run a live test against production without permission).")
        return external.rstrip("/"), None
    port = int(os.environ.get("AUTOTEST_PORT", "8799"))
    server = AppServer(port)
    server.start()
    return server.base, server


def main() -> int:
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:4]
    return _run(run_id)


def _run(run_id: str) -> int:
    from autotest._env import load_dotenv
    load_dotenv()  # pick up GEMINI_API_KEY etc. from the gitignored .env
    max_pages = int(os.environ.get("AUTOTEST_MAX_PAGES", "40"))
    flow_timeout = float(os.environ.get("AUTOTEST_FLOW_TIMEOUT", "210"))
    headless = os.environ.get("AUTOTEST_HEADLESS", "1") != "0"

    routes = discover_get_routes()
    base, server = _resolve_base()
    live_mode = server is None  # external URL (e.g. the live/staging deployment)
    profile_id = os.environ.get("AUTOTEST_PROFILE_ID") or None
    if server is not None and not profile_id:
        profile_id = _seed_ready_profile(server.data_dir)
    flow_result = "not-run"
    council_verdict = ""
    judges_ran = True       # safe default: never freeze lifecycles by accident
    judge_digest = ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser, context, engine = _launch_browser(pw, headless)
            page = context.new_page()
            col = Collector(base)
            col.attach(page)
            tester = Tester(server, base, page, col, max_pages)
            tester.engine = engine   # B1: tag findings + run_meta with the engine/device

            # 0) sign in so the gated content routes are reachable, then capture
            #    the signed-in home text for the user-brain judge.
            if live_mode:
                tester.ensure_signed_in_live()
            elif profile_id:
                tester.ensure_signed_in(profile_id)
            try:
                page.goto(base + "/", wait_until="domcontentloaded", timeout=20000)
                tester.artifacts["home_text"] = page.inner_text("body")[:6000]
                tester._capture_surface("home")  # for the vision judge to look at
            except Exception:
                pass

            # 1) probe every registered no-arg GET route. Skip /api/* (fetch
            #    endpoints — exercised via XHR during real page loads) and any
            #    destructive/sign-out links so the crawl stays read-only & signed in.
            for rule in routes:
                if (rule.startswith("/api/") or rule in ("/sign-out",)
                        or any(h in rule for h in DESTRUCTIVE_HINTS)):
                    continue
                tester.probe(base + rule, f"route:{rule}", route_template=rule)
                tester.routes_probed += 1

            # 2) content journey.
            if live_mode:
                # always inspect existing real runs (read-only) and flag empties
                n = tester.judge_existing_runs()
                flow_result = (f"live:judged-{n}-runs" if tester.artifacts.get("export_json")
                               else f"live:inspected-{n}-runs-no-content")
                # full lifecycle: create test profile -> upload a REAL meet ->
                # judge -> delete the test profile (guarded). Opt-in + authorised.
                if os.environ.get("AUTOTEST_LIVE_FULL") == "1":
                    flow_result = tester.run_full_lifecycle(flow_timeout)
            else:
                flow_result = tester.run_primary_flow(flow_timeout)
                if os.environ.get("AUTOTEST_SIGNUP", "1") != "0":
                    tester.artifacts["signup_result"] = tester.run_signup_flow()
            tester.artifacts["flow_result"] = flow_result
            tester.artifacts["pages"] = tester.visited

            # 3) bounded read-only crawl of internal links
            tester.crawl([base + r for r in ("/", "/activity", "/research",
                                             "/settings", "/privacy", "/status")])

            # 4) semantic subagents — judge MEANING (output correctness, UX,
            #    functional intent), not just crashes. Then the LLM Council
            #    adjudicates their findings (anti-sycophancy: confirm real bugs,
            #    demote noise, surface blind spots). Both self-skip with no key.
            # Run the judges whenever there's ANY real surface to evaluate —
            # a content pack, the home page, the sign-up text, or a review page —
            # not only a full content pack. (Without this, a content-less live
            # site left the AI brain off and found nothing.)
            #    The VISION judge (5) looks at the rendered screenshots for visual
            #    defects neither the deterministic finder nor the text-only
            #    semantic judges can see (broken images, clipped captions, error
            #    banners). It runs on the existing media_ai.llm vision capability
            #    (Gemini/Anthropic) — no GPU, honest-skip with no key. Both feed
            #    the SAME council adjudication so there's one verdict per sweep.
            # A4: flag artifacts from flows we didn't run this sweep as unexercised,
            # so they are dropped before any judge sees them (no false findings on a
            # page that is empty only because we skipped its flow).
            tester.reconcile_artifact_meta()
            _judgeable = any(tester.artifacts.get(k) for k in
                             ("export_json", "home_text", "signup_text", "review_text"))
            # Skip-unchanged: when every surface a judge would see is byte-for-byte
            # what the LAST sweep judged, re-running the judges burns quota to
            # restate the same opinions. Skip them and FREEZE the subjective
            # lifecycle clocks (judges_ran=False below) — no decay, no confirms,
            # no new sightings, because there was no new information.
            judge_digest = _judge_inputs_digest(tester.artifacts)
            skip_unchanged = (
                os.environ.get("AUTOTEST_JUDGE_SKIP_UNCHANGED", "1") == "1"
                and bool(judge_digest)
                and judge_digest == report.get_judge_inputs_digest())
            judges_attempted = False
            try:
                ai_findings: list[Finding] = []
                if not skip_unchanged:
                    if os.environ.get("AUTOTEST_SEMANTIC", "1") != "0" and _judgeable:
                        from autotest import semantic
                        judges_attempted = True
                        ai_findings += semantic.evaluate(tester.artifacts, tester.artifact_meta)
                    if os.environ.get("AUTOTEST_VISION", "1") != "0":
                        from autotest import vision
                        judges_attempted = True
                        ai_findings += vision.evaluate(tester.artifacts)
                candidates = [f for f in ai_findings if f.is_bug]
                passthrough = [f for f in ai_findings if not f.is_bug]
                if candidates and os.environ.get("AUTOTEST_COUNCIL", "1") != "0":
                    from autotest import council
                    candidates, council_verdict = council.adjudicate(
                        candidates, tester.artifacts, tester.artifact_meta)
                tester.findings.extend(passthrough + candidates)
            except Exception:
                pass
            # The judges RAN if they were attempted and didn't all self-skip
            # (CLI missing / no provider key emits only *_skipped markers).
            _SKIP_MARKERS = ("semantic_skipped", "vision_skipped")
            judges_ran = judges_attempted and not (
                ai_findings and all(f.category in _SKIP_MARKERS for f in ai_findings))
            if skip_unchanged:
                print("autotest: judge inputs unchanged since last sweep — "
                      "AI judges skipped (subjective lifecycle frozen)")
            browser.close()
    finally:
        if server:
            tail = server.read_log()
            # global sweep: any traceback in the whole server log not tied to a probe
            if TRACEBACK_MARK in tail:
                tester_findings_have_tb = any(f.category == "server_traceback" for f in
                                              getattr(tester, "findings", []))
                if not tester_findings_have_tb:
                    tb = _last_exception_block(tail)
                    tester.findings.append(Finding(
                        category="server_traceback", severity="high",
                        title="Traceback found in server log (unattributed)",
                        route="server", expected="No unhandled exceptions",
                        actual="A traceback was logged during the session.",
                        evidence=tb, suspect=_extract_suspect(tb)))
            server.stop()

    # Ground-truth oracle (LLM Council 2026-06-01): the live sweep has NO ground
    # truth — it judges whatever runs exist on prod, so it can't tell a real defect
    # from correct behaviour (the "0 cards" empty state got flagged as a bug). So
    # ALSO run the canonical sample meet through the REAL pipeline with a club that
    # matches it, and diff the deterministic output (parser count, club match, V5->V3
    # bridge, card/achievement magnitude via the human-blessed baseline) against the
    # committed golden baseline. This is the falsifiable, reproducible regression
    # signal the live-prod judges can never give. It supersedes the old artifact-based
    # golden check, which never fired in the live CI sweep (golden=False) and whose
    # seeded org didn't match the meet anyway. Deterministic → bypasses council
    # triage. Never break the sweep over it.
    try:
        from autotest import ground_truth as _ground_truth
        tester.findings.extend(_ground_truth.check())
    except Exception:
        pass
    stats = report.merge_findings(tester.findings, run_id, judges_ran=judges_ran)
    if judges_ran and judge_digest:
        report.set_judge_inputs_digest(judge_digest)
    run_meta = {"run_id": run_id, "base_url": base, "routes_probed": tester.routes_probed,
                "pages_crawled": tester.pages_crawled, "flow_result": flow_result,
                "council_verdict": council_verdict, "engine": getattr(tester, "engine", "chromium")}
    report.write_report(run_meta)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps({
        "run_meta": run_meta, "stats": stats,
        "findings": [vars(f) for f in tester.findings]}, indent=2), encoding="utf-8")

    summary = (f"autotest {run_id}: {stats['open']} open bug(s) "
               f"({stats['new']} new), {stats['regressed']} regressed, "
               f"{stats['fixing']} in progress, {stats['fixed']} fixed, "
               f"{stats['meta_open']} meta, {stats['skipped']} skipped · "
               f"judges={'ran' if judges_ran else 'skipped'} · flow={flow_result} · "
               f"routes={tester.routes_probed} crawled={tester.pages_crawled}")
    print(summary)
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as fh:
            fh.write(f"### 🔎 Autonomous test sweep\n\n{summary}\n\n"
                     f"Live report: `autotest/reports/BUGS.md` on the `autotest/state` branch.\n")
    return 0  # finding bugs is success; non-zero is reserved for tester crashes


if __name__ == "__main__":
    raise SystemExit(main())
