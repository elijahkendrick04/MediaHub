"""First-party, server-side syntax highlighter + code-example switcher (UI 1.11).

MediaHub self-hosts everything on every surface (fonts, the UI-kit JS, the
render engines) and never pulls a CDN — see ``CLAUDE.md``. So the Developer/API
docs page does NOT load Prism.js (or any highlighter) from a CDN. Instead this
module tokenises code **server-side** into HTML-escaped ``<span>``s carrying
``mh-tok-*`` classes that ``theme-components.css`` colours. That keeps the
docs page:

* **No-CDN / first-party** — the highlighter is this ~250-line module, bundled
  in the Python package; nothing is fetched from a third party.
* **Deterministic + testable** — the same input always yields the same HTML, so
  ``tests/test_api_docs_page.py`` can assert exact token output (a client-side
  JS highlighter would need a browser to test).
* **Robust** — highlighting happens before the response leaves the server, so
  there is no flash-of-unstyled-code, and the page is fully readable with
  JavaScript disabled (the language tabs are pure CSS; only the copy button
  needs JS, and it is a progressive enhancement).

Security: every run of source text — both the bits a rule matched and the gaps
between matches — is HTML-escaped (`&`, `<`, `>`), so a code sample containing
``</code><script>`` can never break out into live markup. ``highlight`` never
raises; on any internal error it falls back to fully-escaped plain text.

Public API:

* ``highlight(code, lang)``      -> safe highlighted HTML (no wrapper element)
* ``code_block(code, lang, …)``  -> a standalone ``<pre>`` block + copy button
* ``code_switcher(samples, …)``  -> the tabbed multi-language switcher
* ``normalize_lang`` / ``SUPPORTED_LANGUAGES`` / ``LANGUAGE_LABELS``

The tab mechanism is the classic accessible pure-CSS radio pattern: one hidden
radio per language (a real, focusable form control), positional ``:checked ~``
rules in the stylesheet reveal the matching ``<pre>`` panel and light the
matching ``<label>`` tab. No JavaScript is required to switch languages.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence, Tuple

__all__ = [
    "highlight",
    "code_block",
    "code_switcher",
    "normalize_lang",
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_LABELS",
]


# --------------------------------------------------------------------------
# Token kind -> CSS class. The classes are styled in theme-components.css.
# --------------------------------------------------------------------------
_TOK_CLASS = {
    "comment": "mh-tok-comment",
    "string": "mh-tok-string",
    "number": "mh-tok-number",
    "keyword": "mh-tok-keyword",
    "boolean": "mh-tok-boolean",
    "function": "mh-tok-function",
    "property": "mh-tok-property",
    "variable": "mh-tok-variable",
    "operator": "mh-tok-operator",
    "punctuation": "mh-tok-punctuation",
}

# Language aliases -> canonical name. ``curl`` and ``console`` are common on
# docs pages and both mean "a shell session", which we tokenise as bash.
_ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "console": "bash",
    "curl": "bash",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "py": "python",
    "py3": "python",
}

# Human labels for a language (used by code_block's header chip).
LANGUAGE_LABELS = {
    "bash": "Shell",
    "python": "Python",
    "javascript": "JavaScript",
    "json": "JSON",
}


# --------------------------------------------------------------------------
# Per-language rules: an ORDERED list of (token-kind, regex). Order matters —
# the first rule that matches at a position wins (Python alternation is
# ordered), so comments/strings must precede keywords/operators. Patterns use
# only NON-capturing groups so ``match.lastgroup`` reliably names the rule that
# fired (the scanner relies on this).
# --------------------------------------------------------------------------
_RULES_BASH: list[Tuple[str, str]] = [
    ("comment", r"#[^\n]*"),
    ("string", r"\"(?:[^\"\\]|\\.)*\""),
    ("string", r"'[^']*'"),
    ("variable", r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\d+"),
    ("keyword", r"\b(?:curl|wget|http|sudo|cat|echo|export|jq|set|cd)\b"),
    # Short and long flags: -X, --data-raw, -H. The lookbehind keeps us off a
    # hyphen that sits mid-word (e.g. inside an already-matched token).
    ("keyword", r"(?<![\w-])--?[A-Za-z][A-Za-z0-9-]*"),
    ("number", r"\b\d+\b"),
]

_RULES_JSON: list[Tuple[str, str]] = [
    # An object key is a string immediately followed by a colon.
    ("property", r"\"(?:[^\"\\]|\\.)*\"(?=\s*:)"),
    ("string", r"\"(?:[^\"\\]|\\.)*\""),
    ("boolean", r"\b(?:true|false|null)\b"),
    ("number", r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"),
    ("punctuation", r"[{}\[\],:]"),
]

_RULES_PYTHON: list[Tuple[str, str]] = [
    ("comment", r"#[^\n]*"),
    # Triple-quoted strings (optionally prefixed) before single-line strings.
    ("string", r"(?:[rRbBfFuU]{0,2})\"\"\"(?:[^\\]|\\.)*?\"\"\""),
    ("string", r"(?:[rRbBfFuU]{0,2})'''(?:[^\\]|\\.)*?'''"),
    ("string", r"(?:[rRbBfFuU]{0,2})\"(?:[^\"\\\n]|\\.)*\""),
    ("string", r"(?:[rRbBfFuU]{0,2})'(?:[^'\\\n]|\\.)*'"),
    ("function", r"@[A-Za-z_][\w.]*"),  # decorator
    ("boolean", r"\b(?:True|False|None)\b"),
    (
        "keyword",
        r"\b(?:def|class|return|import|from|as|if|elif|else|for|while|try|except"
        r"|finally|with|pass|break|continue|raise|yield|lambda|global|nonlocal"
        r"|assert|del|in|is|not|and|or|async|await)\b",
    ),
    ("function", r"\b[A-Za-z_]\w*(?=\s*\()"),
    ("number", r"\b\d+(?:\.\d+)?\b"),
]

_RULES_JAVASCRIPT: list[Tuple[str, str]] = [
    ("comment", r"//[^\n]*"),
    ("comment", r"/\*[\s\S]*?\*/"),
    ("string", r"`(?:[^`\\]|\\.)*`"),
    ("string", r"\"(?:[^\"\\\n]|\\.)*\""),
    ("string", r"'(?:[^'\\\n]|\\.)*'"),
    ("boolean", r"\b(?:true|false|null|undefined)\b"),
    (
        "keyword",
        r"\b(?:const|let|var|function|return|if|else|for|while|await|async|new"
        r"|class|extends|import|from|export|default|try|catch|finally|throw"
        r"|typeof|instanceof|in|of|do|switch|case|break|continue|void|delete"
        r"|yield|this|super)\b",
    ),
    ("function", r"\b[A-Za-z_$][\w$]*(?=\s*\()"),
    ("number", r"\b\d+(?:\.\d+)?\b"),
]

_RULES = {
    "bash": _RULES_BASH,
    "json": _RULES_JSON,
    "python": _RULES_PYTHON,
    "javascript": _RULES_JAVASCRIPT,
}

SUPPORTED_LANGUAGES = frozenset(_RULES)


def _compile(rules: Sequence[Tuple[str, str]]):
    """Compile an ordered rule list into one alternation regex + a name->kind
    map. Each rule gets a unique top-level named group ``t<i>`` so the matched
    rule is recoverable via ``match.lastgroup``."""
    kinds: dict[str, str] = {}
    parts: list[str] = []
    for i, (kind, pattern) in enumerate(rules):
        name = f"t{i}"
        kinds[name] = kind
        parts.append(f"(?P<{name}>{pattern})")
    return re.compile("|".join(parts)), kinds


_COMPILED = {lang: _compile(rules) for lang, rules in _RULES.items()}


def _esc(text: str) -> str:
    """HTML-escape text content. Quotes are safe in element text, so we escape
    only the three structural characters — this keeps the rendered code visually
    identical to the source (no ``&#39;`` noise) while being injection-safe."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def normalize_lang(lang: str) -> str:
    """Canonical language name (lower-cased, alias-resolved). Unknown languages
    are returned as-is (lower-cased) so the ``language-*`` class is still set."""
    low = (lang or "").strip().lower()
    return _ALIASES.get(low, low)


def highlight(code: str, lang: str) -> str:
    """Tokenise ``code`` into HTML-escaped, span-wrapped highlighted markup.

    The result has no wrapping element — callers put it inside ``<code>``. An
    unsupported language (or any internal error) yields fully-escaped plain
    text with no spans, never an exception and never raw markup.
    """
    if code is None:
        return ""
    canonical = normalize_lang(lang)
    compiled = _COMPILED.get(canonical)
    if compiled is None:
        return _esc(code)
    try:
        regex, kinds = compiled
        out: list[str] = []
        pos = 0
        for m in regex.finditer(code):
            start = m.start()
            if start > pos:
                out.append(_esc(code[pos:start]))
            kind = kinds.get(m.lastgroup or "")
            css = _TOK_CLASS.get(kind or "")
            token = _esc(m.group())
            if css:
                out.append(f'<span class="{css}">{token}</span>')
            else:  # unknown kind — should not happen, but stay safe
                out.append(token)
            pos = m.end()
        if pos < len(code):
            out.append(_esc(code[pos:]))
        return "".join(out)
    except Exception:
        # Highlighting is decorative; never let it 500 the docs page.
        return _esc(code)


def _slug(value: str) -> str:
    """A safe HTML id/name fragment: keep word chars and hyphens only."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", (value or "cs").strip()) or "cs"


_COPY_ICON = (
    '<svg class="mh-cs-copy-icon" viewBox="0 0 24 24" width="14" height="14" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<rect x="9" y="9" width="13" height="13" rx="2"/>'
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
)


def _copy_button() -> str:
    """A copy-to-clipboard button. Hidden until ``ui-kit.js`` upgrades it (the
    ``.mh-js`` body class reveals it), so no-JS users never see a dead control —
    the code stays selectable for manual copy."""
    return (
        '<button type="button" class="mh-cs-copy" '
        'aria-label="Copy code to clipboard">'
        f"{_COPY_ICON}"
        '<span class="mh-cs-copy-label">Copy</span></button>'
    )


def code_block(code: str, lang: str, *, label: str | None = None, copy: bool = True) -> str:
    """A single highlighted code block with an optional language chip + copy
    button. Used for standalone snippets (e.g. a JSON response sample)."""
    canonical = normalize_lang(lang)
    chip = _esc(label if label is not None else LANGUAGE_LABELS.get(canonical, canonical))
    head = (
        '<div class="mh-cs-head">'
        f'<span class="mh-cs-lang">{chip}</span>'
        f"{_copy_button() if copy else ''}"
        "</div>"
    )
    body = (
        f'<pre class="mh-cs-panel"><code class="language-{_esc(canonical)}">'
        f"{highlight(code, lang)}</code></pre>"
    )
    return f'<div class="mh-code mh-code-block">{head}{body}</div>'


def code_switcher(
    samples: Iterable[Tuple[str, str, str]],
    *,
    group_id: str,
    copy: bool = True,
) -> str:
    """The tabbed code-example switcher (UI 1.11).

    ``samples`` is an ordered iterable of ``(tab_label, lang, code)`` triples —
    e.g. ``[("cURL", "bash", "curl ..."), ("Python", "python", "import ...")]``.
    The first sample is the default-selected tab. ``group_id`` must be unique on
    the page (it scopes the radio group); it is slugified defensively.

    Returns pure HTML/CSS: hidden radios + ``<label>`` tabs + ``<pre>`` panels.
    Language switching needs no JavaScript (positional ``:checked ~`` rules in
    theme-components.css do it); only the copy button is JS-enhanced.
    """
    samples = list(samples)
    if not samples:
        return ""
    gid = _slug(group_id)
    radios: list[str] = []
    tabs: list[str] = []
    panels: list[str] = []
    for i, (tab_label, lang, code) in enumerate(samples):
        rid = f"{gid}-{i}"
        checked = " checked" if i == 0 else ""
        radios.append(f'<input class="mh-cs-radio" type="radio" name="{gid}" id="{rid}"{checked}>')
        tabs.append(f'<label class="mh-cs-tab" for="{rid}">{_esc(tab_label)}</label>')
        canonical = normalize_lang(lang)
        panels.append(
            f'<pre class="mh-cs-panel"><code class="language-{_esc(canonical)}">'
            f"{highlight(code, lang)}</code></pre>"
        )
    head = (
        '<div class="mh-cs-head">'
        f'<div class="mh-cs-tabs">{"".join(tabs)}</div>'
        f"{_copy_button() if copy else ''}"
        "</div>"
    )
    # role="radiogroup" (not tablist): the tabs ARE radios + <label for>, a
    # native, keyboard-navigable radio group — the correct, complete semantic
    # for pure-CSS tabs (a tablist would require role="tab" children + JS).
    return (
        '<div class="mh-code mh-code-switcher" role="radiogroup" '
        'aria-label="Choose a code-example language">'
        f"{''.join(radios)}"
        f"{head}"
        f'<div class="mh-cs-body">{"".join(panels)}</div>'
        "</div>"
    )
