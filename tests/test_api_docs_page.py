"""UI 1.11 — Tabbed code-example switcher on the Developer/API docs page.

Two halves:

* **Highlighter unit tests** — the first-party, server-side syntax highlighter
  (``mediahub.web.code_highlight``) must be exact (round-trips to the original
  source), injection-safe (escapes ``<>&``), deterministic, and never raise. The
  switcher / block HTML builders must emit the pure-CSS radio-tab structure.

* **Page + asset tests** — ``/developer/api`` renders, is public (readable under
  the enforced org gate, like the legal pages), hosts the switcher with
  server-rendered token spans, links from the footer, and pulls in NO CDN /
  Prism / hosted highlighter (MediaHub self-hosts everything — see CLAUDE.md).
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

import pytest

from mediahub.web import code_highlight as ch

_ROOT = Path(__file__).resolve().parents[1]
_UIKIT_JS = _ROOT / "src" / "mediahub" / "web" / "static" / "js" / "ui-kit.js"
_COMPONENTS_CSS = (
    _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _plain(highlighted: str) -> str:
    """Strip the highlight spans and unescape — recovers the original source."""
    return _html.unescape(re.sub(r"<[^>]+>", "", highlighted))


# ===========================================================================
# Highlighter — correctness
# ===========================================================================
_SAMPLES = {
    "bash": (
        '# fetch a run\n'
        'RUN_ID="run_8f2c1a"\n'
        'curl -s -X POST "https://x.test/api?n=3" -H "Cookie: $TOKEN"\n'
    ),
    "json": '{"ok": true, "n": 42, "ratio": -1.5e3, "items": [null, "a\\"b"]}',
    "python": (
        "import requests  # http client\n"
        "@deco\n"
        "def go(x):\n"
        '    s = f"hi {x}"\n'
        "    return None\n"
    ),
    "javascript": (
        "const BASE = `/api/${id}`; // base\n"
        '/* block */ let v = "x";\n'
        "if (await fetch(BASE)) console.log(true);\n"
    ),
}


@pytest.mark.parametrize("lang", sorted(_SAMPLES))
def test_highlight_roundtrips_exactly(lang):
    """Stripping the markup must reproduce the input byte-for-byte — the
    tokeniser may never drop, duplicate, or reorder a character."""
    code = _SAMPLES[lang]
    assert _plain(ch.highlight(code, lang)) == code


@pytest.mark.parametrize("lang", sorted(_SAMPLES))
def test_highlight_emits_token_spans(lang):
    out = ch.highlight(_SAMPLES[lang], lang)
    assert '<span class="mh-tok-' in out


def test_highlight_is_deterministic():
    code = _SAMPLES["python"]
    assert ch.highlight(code, "python") == ch.highlight(code, "python")


def test_bash_tokens():
    out = ch.highlight('curl -X POST "u" # c\necho $VAR', "bash")
    assert '<span class="mh-tok-keyword">curl</span>' in out
    assert '<span class="mh-tok-keyword">-X</span>' in out  # flag
    assert '<span class="mh-tok-string">"u"</span>' in out
    assert '<span class="mh-tok-comment"># c</span>' in out
    assert '<span class="mh-tok-variable">$VAR</span>' in out


def test_json_tokens():
    out = ch.highlight('{"key": true, "n": 12, "s": "v"}', "json")
    assert '<span class="mh-tok-property">"key"</span>' in out
    assert '<span class="mh-tok-boolean">true</span>' in out
    assert '<span class="mh-tok-number">12</span>' in out
    assert '<span class="mh-tok-string">"v"</span>' in out
    # The value string is NOT classed as a property (no following colon).
    assert '<span class="mh-tok-property">"v"</span>' not in out


def test_python_tokens():
    out = ch.highlight("def f():\n    return None  # x", "python")
    assert '<span class="mh-tok-keyword">def</span>' in out
    assert '<span class="mh-tok-keyword">return</span>' in out
    assert '<span class="mh-tok-boolean">None</span>' in out
    assert '<span class="mh-tok-comment"># x</span>' in out
    assert '<span class="mh-tok-function">f</span>' in out


def test_javascript_tokens():
    out = ch.highlight('const x = true; // c\nawait fetch("u");', "javascript")
    assert '<span class="mh-tok-keyword">const</span>' in out
    assert '<span class="mh-tok-keyword">await</span>' in out
    assert '<span class="mh-tok-boolean">true</span>' in out
    assert '<span class="mh-tok-comment">// c</span>' in out
    assert '<span class="mh-tok-function">fetch</span>' in out


# ===========================================================================
# Highlighter — safety + robustness
# ===========================================================================
def test_highlight_escapes_html_injection():
    out = ch.highlight('</code><script>alert(1)</script>', "json")
    assert "<script>" not in out
    assert "</code>" not in out
    assert "&lt;script&gt;" in out


def test_highlight_escapes_ampersand_and_brackets_in_every_language():
    payload = 'x = "<b> & </b>"'
    for lang in (*sorted(_SAMPLES), "ruby", ""):
        out = ch.highlight(payload, lang)
        assert "<b>" not in out and "&lt;b&gt;" in out and "&amp;" in out


def test_unknown_language_is_escaped_plain_text():
    out = ch.highlight("<b>&'\"", "ruby")
    assert out == "&lt;b&gt;&amp;'\""
    assert "<span" not in out


@pytest.mark.parametrize("bad", [None, "", "   ", "\n\n", "no-tokens-here"])
def test_highlight_never_raises(bad):
    # Must return a string for any input and any language, never throw.
    assert isinstance(ch.highlight(bad, "python"), str)
    assert isinstance(ch.highlight(bad, "json"), str)
    assert isinstance(ch.highlight(bad, "definitely-not-a-lang"), str)


def test_highlight_handles_unterminated_string():
    # A broken sample must still round-trip and not hang or raise.
    code = 'curl "unterminated\nnext line'
    assert _plain(ch.highlight(code, "bash")) == code


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("curl", "bash"),
        ("sh", "bash"),
        ("shell", "bash"),
        ("js", "javascript"),
        ("node", "javascript"),
        ("py", "python"),
        ("JSON", "json"),
        ("Python", "python"),
        ("ruby", "ruby"),  # unknown stays as-is (lower-cased)
    ],
)
def test_normalize_lang(alias, canonical):
    assert ch.normalize_lang(alias) == canonical


def test_curl_alias_highlights_as_bash():
    assert '<span class="mh-tok-keyword">curl</span>' in ch.highlight("curl -s u", "curl")


# ===========================================================================
# HTML builders — code_block + code_switcher
# ===========================================================================
def test_code_block_structure():
    out = ch.code_block('{"a": 1}', "json")
    assert 'class="mh-code mh-code-block"' in out
    assert '<pre class="mh-cs-panel">' in out
    assert 'class="language-json"' in out
    assert 'class="mh-cs-copy"' in out
    assert '<span class="mh-tok-property">"a"</span>' in out


def test_code_block_custom_label_is_escaped():
    out = ch.code_block("{}", "json", label="<Resp>")
    assert "&lt;Resp&gt;" in out
    assert "<Resp>" not in out


def test_code_switcher_structure():
    out = ch.code_switcher(
        [("cURL", "bash", "curl u"), ("Python", "python", "import x")],
        group_id="ep-status",
    )
    assert 'class="mh-code mh-code-switcher"' in out
    assert out.count('class="mh-cs-radio"') == 2
    assert out.count('class="mh-cs-tab"') == 2
    assert out.count('class="mh-cs-panel"') == 2
    assert 'role="radiogroup"' in out
    # First radio is checked by default, the others are not.
    assert out.count(" checked>") == 1
    # All radios share one group name; labels point at the radios.
    assert out.count('name="ep-status"') == 2
    assert 'id="ep-status-0"' in out and 'for="ep-status-0"' in out
    assert 'id="ep-status-1"' in out and 'for="ep-status-1"' in out


def test_code_switcher_slugifies_group_id():
    out = ch.code_switcher([("cURL", "bash", "curl u")], group_id="ep 1/x!")
    # Unsafe chars become hyphens; never injected raw into name/id attributes.
    assert 'name="ep-1-x-"' in out
    assert "ep 1/x!" not in out


def test_code_switcher_escapes_tab_label():
    out = ch.code_switcher([("<b>", "bash", "x")], group_id="g")
    assert "&lt;b&gt;" in out
    assert "<label class=\"mh-cs-tab\" for=\"g-0\"><b>" not in out


def test_code_switcher_empty_is_blank():
    assert ch.code_switcher([], group_id="g") == ""


def test_supported_languages():
    assert ch.SUPPORTED_LANGUAGES == frozenset({"bash", "python", "javascript", "json"})


# ===========================================================================
# Page + asset integration
# ===========================================================================
@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_api_docs_page_renders(client):
    r = client.get("/developer/api")
    assert r.status_code == 200
    assert "text/html" in r.content_type


def test_api_docs_public_under_enforced_gate(app):
    # A docs page, like the legal pages: readable before sign-up / org setup.
    app.config["ENFORCE_ORG_GATE"] = True
    r = app.test_client().get("/developer/api")
    assert r.status_code == 200


def test_api_docs_hosts_the_switcher_component(client):
    body = client.get("/developer/api").get_data(as_text=True).split("</head>", 1)[-1]
    assert 'class="mh-code mh-code-switcher"' in body
    assert 'role="radiogroup"' in body
    assert 'class="mh-cs-radio"' in body
    assert 'class="mh-cs-copy"' in body
    # Multiple language switchers (quickstart + per-endpoint).
    assert body.count('class="mh-code mh-code-switcher"') >= 5


def test_api_docs_highlighting_is_server_rendered(client):
    body = client.get("/developer/api").get_data(as_text=True).split("</head>", 1)[-1]
    # Real token spans in the markup => no client-side highlighter needed.
    assert len(re.findall(r'<span class="mh-tok-', body)) > 50
    assert '<span class="mh-tok-keyword">curl</span>' in body


def test_api_docs_documents_real_endpoints(client):
    body = client.get("/developer/api").get_data(as_text=True)
    for path in (
        "/health",
        "/api/runs/{run_id}/status",
        "/api/runs/{run_id}/cards",
        "/api/runs/{run_id}/export",
        "/api/runs/{run_id}/reel",
    ):
        assert path in body, f"docs must mention {path}"


def test_api_docs_reel_defaults_match_the_engine(client):
    """The documented reel cover/outro defaults must track the real engine
    constants, not a stale literal.

    Regression: the outro default was documented as 1.0s long after the engine
    default was extended to 2.5s (REEL_OUTRO_SEC), so a developer setting
    ?outro=1.0 to "match the default" would silently shorten the outro.
    """
    from mediahub.visual.motion import REEL_COVER_SEC, REEL_OUTRO_SEC

    body = client.get("/developer/api").get_data(as_text=True)
    expected = f"Default {REEL_COVER_SEC} / {REEL_OUTRO_SEC}."
    assert expected in body, f"docs must state the live reel defaults ({expected!r})"
    # The specific stale value must be gone.
    assert "Default 2.0 / 1.0." not in body


def test_api_docs_no_cdn_or_external_highlighter(client):
    html = client.get("/developer/api").get_data(as_text=True).lower()
    for bad in (
        "prismjs",
        "prism.js",
        "highlight.js",
        "hljs",
        "cdn.jsdelivr",
        "cdnjs.cloudflare",
        "unpkg.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
    ):
        assert bad not in html, f"page must not pull {bad}"


def test_footer_links_to_api_docs(client):
    # The footer is on every page; check it from a different page so we are not
    # just seeing the current page's own URL.
    body = client.get("/privacy").get_data(as_text=True)
    assert 'href="/developer/api"' in body


def test_api_docs_quickstart_shows_session_cookie_and_handles_unknown(client):
    """The legacy /api routes need the session cookie; the quickstart samples
    must say so, and their poll loops must treat 'unknown' (a 404 run) as
    terminal so a copy-pasted script can't spin forever."""
    raw = client.get("/developer/api").get_data(as_text=True).split("</head>", 1)[-1]
    # Strip the highlighter's token spans so we can assert on the real sample text.
    body = _plain(raw)
    # The quickstart mentions the session cookie the legacy routes need.
    assert "session cookie" in body.lower()
    # The cURL sample sends the cookie (-b) and the Python sample passes cookies=.
    assert "curl -s -b" in body
    assert "cookies=cookies" in body
    # 'unknown' is a terminal state in the copy-paste poll loops (Python + JS).
    assert '("done", "error", "unknown")' in body
    assert 'status.status !== "unknown"' in body


def test_api_docs_examples_use_request_host(client):
    # Base URL in the samples is the live deployment host, not a hardcoded one.
    body = client.get("/developer/api").get_data(as_text=True)
    assert "http://localhost/api/runs" in body


# ---- static assets carry the behaviour --------------------------------------
def test_ui_kit_has_copy_binding():
    js = _UIKIT_JS.read_text(encoding="utf-8")
    assert "function bindCopy" in js
    assert "navigator.clipboard" in js
    assert 'execCommand("copy")' in js  # legacy fallback
    assert 'each(root, ".mh-cs-copy", bindCopy)' in js  # wired into init


def test_components_css_has_switcher_and_tokens():
    css = _COMPONENTS_CSS.read_text(encoding="utf-8")
    # Token colours.
    for cls in (
        ".mh-tok-comment",
        ".mh-tok-string",
        ".mh-tok-keyword",
        ".mh-tok-number",
        ".mh-tok-property",
    ):
        assert cls in css
    # Pure-CSS tab switching exists (no JS needed to change language).
    assert ":checked ~ .mh-cs-body" in css
    # Copy button is hidden until JS upgrades it, revealed via .mh-js.
    assert ".mh-cs-copy {" in css and "display: none" in css
    assert ".mh-js .mh-cs-copy" in css


def test_components_css_no_cdn():
    css = _COMPONENTS_CSS.read_text(encoding="utf-8").lower()
    for host in ("googleapis", "gstatic", "cdn.jsdelivr", "cdnjs", "unpkg", "prismjs"):
        assert host not in css, f"theme CSS must not reference {host}"
