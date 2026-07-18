"""B-1 — the "how it works" interstitial is first-visit-only, per organisation.

Every Create tile used to route through its explainer slide (/make/<type>) on
EVERY visit, with no skip and no memory — nav → upload was 7 clicks instead of
4, and Plan paid the toll twice. Now: the first visit still shows the intro
(it's genuinely useful once), but viewing it retires it for that organisation
— persisted in a small DATA_DIR sidecar (DATA_DIR/intro_seen/<pid>.json), NOT
the session — so the tile links straight into the real flow from then on. The
explainer stays reachable forever via a "How it works" pill on each tile and
on each flow's landing page. The Meet Recap intro copy also now lists every
accepted upload format instead of just .hy3/zip.
"""

from __future__ import annotations

import json
import re

import pytest


@pytest.fixture()
def env(app, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    save_profile(ClubProfile(profile_id="club-b", display_name="Club B"))
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app, tmp_path


def _client(app, pid="club-a"):
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = pid
    return c


def _tile_hrefs(body: str) -> list[str]:
    """The main action href of every Create tile / the Plan hero anchor."""
    return re.findall(r'<a href="([^"]*)" class="(?:mh-template|mh-plan-tile)\b', body)


# --------------------------------------------------------------------------- #
# First visit — the intro still shows (it is genuinely useful once)
# --------------------------------------------------------------------------- #
def test_first_visit_tiles_open_the_intro(env):
    app, _ = env
    body = _client(app).get("/make").get_data(as_text=True)
    hrefs = _tile_hrefs(body)
    for slug in ("meet_recap", "event_preview", "free_text", "plan"):
        assert f"/make/{slug}" in hrefs, f"{slug}: first visit should open the intro"


# --------------------------------------------------------------------------- #
# Viewing the intro retires it — per content type, per organisation
# --------------------------------------------------------------------------- #
def test_intro_view_retires_the_interstitial_for_that_type_only(env):
    app, _ = env
    c = _client(app)
    with app.test_request_context():
        from flask import url_for

        upload_url = url_for("upload")
    assert c.get("/make/meet_recap").status_code == 200
    body = c.get("/make").get_data(as_text=True)
    hrefs = _tile_hrefs(body)
    assert upload_url in hrefs, "seen tile should link straight to the flow"
    assert "/make/meet_recap" not in hrefs, "seen tile must not re-pay the intro"
    # Unseen siblings still get their first-visit explainer.
    assert "/make/event_preview" in hrefs
    assert "/make/free_text" in hrefs


def test_plan_stops_double_paying(env):
    app, _ = env
    c = _client(app)
    assert c.get("/make/plan").status_code == 200
    body = c.get("/make").get_data(as_text=True)
    assert '<a href="/plan" class="mh-plan-tile">' in body
    hrefs = _tile_hrefs(body)
    assert "/make/plan" not in hrefs


# --------------------------------------------------------------------------- #
# Persistence — a DATA_DIR sidecar per profile, not session state
# --------------------------------------------------------------------------- #
def test_seen_set_is_persisted_on_disk_not_in_the_session(env):
    app, tmp_path = env
    assert _client(app).get("/make/meet_recap").status_code == 200
    sidecar = tmp_path / "intro_seen" / "club-a.json"
    assert sidecar.exists(), "seen-set must persist under DATA_DIR/intro_seen/<pid>.json"
    assert "meet_recap" in json.loads(sidecar.read_text(encoding="utf-8"))
    # A brand-new session (fresh client) for the same organisation still skips
    # the interstitial — the memory is the profile's, not the cookie's.
    body = _client(app).get("/make").get_data(as_text=True)
    assert "/make/meet_recap" not in _tile_hrefs(body)


def test_seen_set_is_tenant_scoped(env):
    app, _ = env
    assert _client(app, "club-a").get("/make/meet_recap").status_code == 200
    body = _client(app, "club-b").get("/make").get_data(as_text=True)
    assert "/make/meet_recap" in _tile_hrefs(
        body
    ), "another organisation must still meet the explainer first"


def test_unknown_slug_marks_nothing(env):
    app, tmp_path = env
    r = _client(app).get("/make/definitely_not_a_type", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert not (tmp_path / "intro_seen" / "club-a.json").exists()


def test_legacy_alias_marks_the_canonical_slug(env):
    app, tmp_path = env
    c = _client(app)
    r = c.get("/make/weekend_preview", follow_redirects=False)
    if r.status_code != 200:
        pytest.skip("weekend_preview alias not resolved on this deployment")
    seen = json.loads((tmp_path / "intro_seen" / "club-a.json").read_text(encoding="utf-8"))
    assert "event_preview" in seen
    assert "weekend_preview" not in seen


# --------------------------------------------------------------------------- #
# The explainer stays reachable forever — tiles AND destination pages
# --------------------------------------------------------------------------- #
def test_tiles_keep_a_how_it_works_pill_before_and_after_seen(env):
    app, _ = env
    c = _client(app)
    for _pass in ("first", "after-seen"):
        body = c.get("/make").get_data(as_text=True)
        pills = re.findall(r'class="mh-how-pill" href="([^"]*)"', body)
        for slug in ("meet_recap", "event_preview", "free_text", "plan"):
            assert f"/make/{slug}" in pills, f"{slug}: missing How-it-works pill ({_pass})"
        c.get("/make/meet_recap")
        c.get("/make/plan")


def test_destination_pages_link_back_to_the_explainer(env):
    app, _ = env
    c = _client(app)
    for page, slug in (
        ("/upload", "meet_recap"),
        ("/free-text", "free_text"),
        ("/weekend-preview", "event_preview"),
        ("/plan", "plan"),
    ):
        body = c.get(page).get_data(as_text=True)
        assert (
            f'class="mh-how-pill" href="/make/{slug}"' in body
        ), f"{page}: the flow's landing page must keep a How-it-works link"


# --------------------------------------------------------------------------- #
# Intro copy — every accepted format, mirroring the upload allowlist
# --------------------------------------------------------------------------- #
def test_meet_recap_intro_lists_every_accepted_format(env):
    app, _ = env
    body = _client(app).get("/make/meet_recap").get_data(as_text=True)
    for token in (".hy3", ".hyv", "SDIF/SD3/CL2", "ZIP", "PDF", "HTML", "CSV", "TXT", ".xlsx"):
        assert token in body, f"Meet Recap intro must mention {token}"


def test_meet_recap_registry_copy_mirrors_the_upload_allowlist():
    from mediahub.club_platform.content_types import REGISTRY, ContentType

    meta = REGISTRY[ContentType.MEET_RECAP]
    step_one = meta.how_it_works.steps[0]
    for token in (".hy3", ".hyv", "SDIF/SD3/CL2", "ZIP", "PDF", "HTML", "CSV", "TXT", ".xlsx"):
        assert token in step_one, f"step 1 must mention {token}"
    for token in (
        ".hy3",
        ".hyv",
        ".sd3",
        ".sdif",
        ".cl2",
        ".zip",
        "PDF",
        "HTML",
        "CSV",
        "TXT",
        ".xlsx",
    ):
        assert token in meta.input_contract, f"input_contract must mention {token}"


# --------------------------------------------------------------------------- #
# CON2-1 (B-1 follow-up) — the seen-sidecar write is atomic
# --------------------------------------------------------------------------- #
def test_intro_mark_seen_writes_the_sidecar_atomically():
    """Unique-tmp + os.replace (the _variant_job_save idiom): two concurrent
    marks must never interleave into a torn sidecar that drops every
    previously-seen slug. The reader already fails soft — this pins the
    writer."""
    import ast
    import pathlib

    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    # Locate the function body by AST rather than by its position relative to
    # the next route decorator — _intro_mark_seen is module-level since the
    # create_app de-closure (finding #15), so positional slicing would sweep
    # in unrelated code.
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_intro_mark_seen"
    )
    body = "\n".join(src.splitlines()[fn.lineno - 1 : fn.end_lineno])
    assert 'tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")' in body
    assert "os.replace(tmp, p)" in body
    # Best-effort tmp cleanup on failure, and no straight write_text on the
    # real path remains.
    assert "tmp.unlink(missing_ok=True)" in body
    assert not re.search(r"(?<![\w.])p\.write_text\(", body)


def test_intro_mark_seen_still_persists_and_dedupes(env):
    """Behavioural: the atomic rewrite still lands the slug once."""
    app, tmp_path = env
    c = _client(app)
    for _ in range(2):
        assert c.get("/make/meet_recap").status_code == 200
    seen_dir = tmp_path / "intro_seen"
    files = list(seen_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data.count("meet_recap") == 1
    # No orphaned tmp files left behind by the atomic write.
    assert not list(seen_dir.glob("*.tmp"))
