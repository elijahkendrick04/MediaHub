"""F-9 — the formal DSR erasure page must not dump raw JSON at the customer.

The quick /privacy erasure showed a friendly "What was removed" list, but the
Article-12A workflow (/organisation/athlete-rights/<id>/run) rendered the very
same erasure report as a raw ``<pre>{json}</pre>`` block — the compliant,
audited path gave the *worse* experience. Both now render the shared
``_erasure_removed_html`` human summary; the formal path additionally offers a
JSON technical report as a download for anyone who wants the raw numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ATHLETE = "Eira Hughes"
OTHER = "Amelia Osborne"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    return tmp_path


def _seed(data_dir: Path, profile_id="clubx", run_id="runE"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name="Club X"))
    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Test Meet"},
        "cards": [
            {
                "id": "cardA",
                "swim_id": "cardA",
                "swimmer_name": ATHLETE,
                "headline": f"{ATHLETE} PB",
            },
            {
                "id": "cardB",
                "swim_id": "cardB",
                "swimmer_name": OTHER,
                "headline": f"{OTHER} medal",
            },
        ],
        "recognition_report": {
            "ranked_achievements": [
                {"achievement": {"swim_id": "cardA", "swimmer_name": ATHLETE, "event": "100 Free"}},
                {"achievement": {"swim_id": "cardB", "swimmer_name": OTHER, "event": "50 Back"}},
            ],
            "n_achievements": 2,
        },
        "results": [{"name": ATHLETE, "time": "57.10"}, {"name": OTHER, "time": "31.20"}],
    }
    (runs / f"{run_id}.json").write_text(json.dumps(run))
    return run_id


@pytest.fixture
def client(data_dir):
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application.test_client()


def test_formal_erasure_shows_human_summary_not_raw_json(client, data_dir):
    _seed(data_dir)
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"
    client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": ATHLETE, "request_type": "erasure"},
    )
    from mediahub.compliance.dsr import DsrRequestLog

    req = DsrRequestLog().all(profile_id="clubx")[0]
    html = client.post(f"/organisation/athlete-rights/{req.id}/run").get_data(as_text=True)

    # The human "What was removed" list is present…
    assert "What was removed" in html
    assert "card(s) and" in html
    assert "caption-memory row(s)" in html
    assert "cannot reappear in new content" in html
    # …and the raw JSON dump is gone (no <pre> report; the JSON keys only ever
    # appear URL-encoded inside the download href, never as visible text).
    assert "<pre" not in html
    assert '"visual_files_deleted"' not in html
    assert "&quot;memory_rows_deleted&quot;" not in html
    # The technical numbers stay available as a downloadable JSON report.
    assert 'download="erasure-' in html
    assert "data:application/json" in html


def test_both_erasure_paths_share_the_same_summary(client, data_dir):
    """Quick /privacy erasure and the formal DSR path render identical wording."""
    _seed(data_dir)
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"
    quick = client.post("/privacy/athlete/erase", data={"athlete_name": ATHLETE}).get_data(
        as_text=True
    )

    _seed(data_dir, run_id="runF")
    client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": OTHER, "request_type": "erasure"},
    )
    from mediahub.compliance.dsr import DsrRequestLog

    req = DsrRequestLog().all(profile_id="clubx")[0]
    formal = client.post(f"/organisation/athlete-rights/{req.id}/run").get_data(as_text=True)

    for marker in (
        "What was removed",
        "rendered file(s)",
        "PB-cache and",
        "posting-log excerpt(s) blanked",
        "media-library photo(s) deleted",
    ):
        assert marker in quick, marker
        assert marker in formal, marker
