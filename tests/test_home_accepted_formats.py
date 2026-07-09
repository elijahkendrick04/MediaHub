"""tests/test_home_accepted_formats.py — home page must state accepted file
formats before a visitor signs up.

Regression for: a first-time (signed-out) volunteer landing on "/" has no
reliable way to learn which result-file formats MediaHub accepts before they
commit to signing up. The only format-shaped text on the page used to be the
decorative demo widget's passing filename ("spring-open.hy3"), while the
visible marketing copy ("One upload, four posting-ready formats...") only
described the *output* formats (story/feed/reel) and stayed vague about
*input* formats. The concrete answer (HY3, PDF, CSV, Excel/XLSX) existed only
inside a collapsed FAQ `<details>` item far down the page, which a visitor
skimming the fold above the primary "Sign up" CTA would never open.

This pins that the visible, non-interactive product-story copy shown
immediately below the hero (`_home_io_headline_html`, the "One upload..."
paragraph) names concrete accepted input formats — not just the demo's
throwaway filename.
"""
from __future__ import annotations

import pytest

from mediahub.web import web as webmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _home(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, f"/ -> {resp.status_code}"
    return resp.get_data(as_text=True)


def _pipeline_sub_paragraph(body: str) -> str:
    start = body.find('class="mh-pipeline-sub"')
    assert start != -1, "mh-pipeline-sub paragraph not found on home page"
    end = body.find("</p>", start)
    assert end != -1
    return body[start:end]


class TestAcceptedFormatsStatedBeforeSignup:
    def test_pipeline_sub_names_accepted_input_formats(self, client):
        """The visible 'One upload...' copy must name real accepted input
        formats, not just describe the outputs."""
        body = _home(client)
        para = _pipeline_sub_paragraph(body)
        lowered = para.lower()
        found = [
            token
            for token in ("hy3", "csv", "pdf", "excel", "xlsx")
            if token in lowered
        ]
        assert found, (
            "The 'One upload...' paragraph under the hero names no concrete "
            f"accepted file format (hy3/csv/pdf/excel). Got: {para!r}"
        )

    def test_format_mention_sits_before_the_collapsed_faq(self, client):
        """A visible, non-decorative format mention must appear before the
        visitor reaches the collapsed FAQ accordion, not only inside it or
        buried in the throwaway demo-widget filename."""
        body = _home(client)
        # "spring-open.hy3" is the demo widget's throwaway prop filename — it
        # doesn't count as telling the visitor what's accepted, so scope the
        # check to the copy *after* it (a real class-selector match earlier in
        # an inlined <style> block would give a false pass otherwise).
        needle = "spring-open.hy3"
        i_demo_end = body.find(needle)
        i_faq = body.find('id="mh-faq-h"')
        assert i_faq != -1, "FAQ section not found on home page"
        assert i_demo_end != -1, "demo widget filename not found on home page"
        mid = body[i_demo_end + len(needle) : i_faq].lower()
        found = [token for token in ("hy3", "csv", "pdf", "excel", "xlsx") if token in mid]
        assert found, (
            "No accepted file format is named in the visible product-story "
            "copy between the demo widget and the collapsed FAQ section — a "
            "signed-out visitor would have to open the FAQ accordion to learn "
            "what files are accepted."
        )
