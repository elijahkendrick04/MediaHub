"""web.spec_editor — a minimal structured editor for newsletter / document specs
(roadmap usability H-5).

Editing either of these surfaces used to mean hand-writing the raw spec JSON in a
monospace ``<textarea>`` — a generate-only experience for the non-technical
volunteers MediaHub is for. This module renders a per-section **title / intro /
link** form driven by a per-surface *field whitelist*, and applies an edited form
back onto the spec dict **by stable id**, leaving every non-whitelisted field
(advanced blocks, images, charts, ids, publish flags) byte-for-byte untouched. The
JSON textarea stays as the labelled "advanced" escape hatch.

Design:

  - **Pure.** No Flask/web imports. The route layer loads the spec, calls
    :func:`apply_structured` on ``spec.to_dict()``, runs the surface's
    ``from_dict`` (so all id-minting / enum-clamping / normalisation still runs),
    and saves.
  - **Whitelist-driven & additive.** Only the text props named in
    :data:`FIELD_WHITELIST` are ever read or written; a block whose kind isn't
    whitelisted is preserved verbatim and simply not shown. No AI, no guessing —
    pure structured editing.
  - **Escaped.** Every id and value emitted into HTML passes through
    ``markupsafe.escape`` (operator-surface stored-XSS guard).

Input-name addressing (parsed back by :func:`apply_structured`)::

    spec__<field>                          # spec chrome  (title, subtitle)
    section__<section_id>__<field>         # section chrome (background, layout, notes)
    block__<block_id>__<path>              # scalar/nested prop (path dotted: button.label)
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from markupsafe import escape as _h

# ---------------------------------------------------------------------------
# Per-surface descriptor tables
#
# A field descriptor is ``(path, label, input_type)`` where ``path`` is a dotted
# path into ``block.props`` and ``input_type`` is "text" | "textarea" | "url".
# Only these paths are read/written; everything else on the block is untouched.
# ---------------------------------------------------------------------------

FIELD_WHITELIST: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "newsletter": {
        "heading": [("text", "Heading", "text")],
        "text": [("text", "Text", "textarea")],
        "button": [("label", "Button label", "text"), ("href", "Button link", "url")],
        # card is a rich recap block ({title, body, src, ...}); only its text is
        # editable here — the image (src) stays in the advanced hatch.
        "card": [("title", "Title", "text"), ("body", "Body", "textarea")],
        "quote": [("text", "Quote", "textarea"), ("attribution", "Attribution", "text")],
        "sponsor": [
            ("name", "Sponsor name", "text"),
            ("href", "Sponsor link", "url"),
            ("label", "Label", "text"),
        ],
    },
    "document": {
        # Only the plain-text document blocks; card/media (images), table, chart
        # and columns (nested) stay in the advanced hatch.
        "heading": [("text", "Heading", "text")],
        "text": [("text", "Text", "textarea")],
        "quote": [("text", "Quote", "textarea"), ("attribution", "Attribution", "text")],
        "stat": [
            ("value", "Value", "text"),
            ("label", "Label", "text"),
            ("sublabel", "Sub-label", "text"),
        ],
    },
}

# Top-level spec text fields. ``(field, label, input_type)``.
SPEC_CHROME: dict[str, list[tuple[str, str, str]]] = {
    "newsletter": [
        ("title", "Title", "text"),
        ("subtitle", "Subtitle / date line", "text"),
        ("kicker", "Kicker", "text"),
        ("preheader", "Inbox preview text", "text"),
        ("subject", "Email subject", "text"),
    ],
    "document": [("title", "Title", "text"), ("subtitle", "Subtitle", "text")],
}

# Per-section chrome. A scalar field is ``(field, label, "text"|"textarea")``; a
# choice field is ``(field, label, tuple_of_options)`` rendered as a <select>.
SECTION_CHROME: dict[str, list[tuple[str, str, Any]]] = {
    "newsletter": [("background", "Background", ("", "surface", "accent"))],
    "document": [
        ("notes", "Speaker notes", "textarea"),
        ("layout", "Layout", ("flow", "cover", "section_break", "centered", "two_col", "closing")),
        ("background", "Background", ("", "surface", "ground", "primary", "accent")),
    ],
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _get_path(props: Mapping[str, Any], path: str) -> str:
    """Read a dotted path out of a props mapping as a string ('' if absent)."""
    cur: Any = props
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return ""
        cur = cur[part]
    return "" if cur is None else str(cur)


def _set_path(props: dict[str, Any], path: str, value: str) -> None:
    """Set a dotted path in a props dict, creating intermediate dicts as needed."""
    parts = path.split(".")
    cur = props
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _iter_sections(spec: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield each top-level section dict (newsletters/documents put sections at
    the top level of the spec)."""
    for section in spec.get("sections") or []:
        if isinstance(section, dict):
            yield section


def _iter_blocks(spec: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield each block dict, across the spec → sections → blocks tree."""
    for section in _iter_sections(spec):
        for block in section.get("blocks") or []:
            if isinstance(block, dict):
                yield block


# ---------------------------------------------------------------------------
# Apply (form → spec dict)
# ---------------------------------------------------------------------------


def apply_structured(spec: dict[str, Any], form: Mapping[str, Any], surface: str) -> dict[str, Any]:
    """Mutate ``spec`` (a ``to_dict()`` result) in place from a submitted form and
    return it. Only whitelisted (block_id, prop) pairs present in the form are
    written; identity fields (newsletter_id/doc_id) are never touched.

    ``form`` is any mapping with ``.get(name)`` and ``in`` membership (Flask's
    ``request.form`` and a plain dict both qualify).
    """
    whitelist = FIELD_WHITELIST.get(surface, {})

    # Spec chrome (title / subtitle / …).
    for field, _label, _typ in SPEC_CHROME.get(surface, []):
        key = f"spec__{field}"
        if key in form:
            spec[field] = str(form.get(key) or "")

    # Section chrome.
    for section in _iter_sections(spec):
        sid = section.get("section_id", "")
        for field, _label, _opts in SECTION_CHROME.get(surface, []):
            key = f"section__{sid}__{field}"
            if key in form:
                section[field] = str(form.get(key) or "")

    # Blocks.
    for block in _iter_blocks(spec):
        bid = block.get("block_id", "")
        kind = block.get("kind", "")
        props = block.get("props")
        if not isinstance(props, dict):
            props = {}
            block["props"] = props
        if kind in whitelist:
            for path, _label, _typ in whitelist[kind]:
                key = f"block__{bid}__{path}"
                if key in form:
                    _set_path(props, path, str(form.get(key) or ""))
    return spec


# ---------------------------------------------------------------------------
# Render (spec dict → HTML form body)
# ---------------------------------------------------------------------------


def has_structured_editor(surface: str) -> bool:
    return bool(FIELD_WHITELIST.get(surface)) or bool(SPEC_CHROME.get(surface))


def _input(name: str, value: str, typ: str) -> str:
    n = _h(name)
    v = _h(value)
    if typ == "textarea":
        return (
            f'<textarea name="{n}" rows="2" class="mh-se-input" '
            f'style="width:100%">{v}</textarea>'
        )
    itype = "url" if typ == "url" else "text"
    return f'<input type="{itype}" name="{n}" value="{v}" class="mh-se-input" style="width:100%">'


def _field_row(name: str, label: str, value: str, typ: str) -> str:
    return (
        '<label class="mh-se-field" style="display:block;margin:6px 0">'
        f'<span class="mh-se-label" style="display:block;font-size:12px;color:var(--ink-muted,#9aa)">'
        f"{_h(label)}</span>"
        f"{_input(name, value, typ)}</label>"
    )


def _select_row(name: str, label: str, value: str, options: Iterable[str]) -> str:
    opts = "".join(
        f'<option value="{_h(o)}"{" selected" if o == value else ""}>{_h(o or "(default)")}</option>'
        for o in options
    )
    return (
        '<label class="mh-se-field" style="display:block;margin:6px 0">'
        f'<span class="mh-se-label" style="display:block;font-size:12px;color:var(--ink-muted,#9aa)">'
        f"{_h(label)}</span>"
        f'<select name="{_h(name)}" class="mh-se-input">{opts}</select></label>'
    )


def _render_block(block: Mapping[str, Any], surface: str) -> str:
    kind = block.get("kind", "")
    bid = str(block.get("block_id", ""))
    props = block.get("props") if isinstance(block.get("props"), Mapping) else {}
    whitelist = FIELD_WHITELIST.get(surface, {})

    if kind not in whitelist:
        return ""
    fields = "".join(
        _field_row(f"block__{bid}__{path}", label, _get_path(props, path), typ)
        for path, label, typ in whitelist[kind]
    )
    if not fields:
        return ""
    return (
        f'<fieldset class="mh-se-block" style="border:1px solid var(--hairline,#333);'
        f'border-radius:6px;padding:8px 10px;margin:8px 0">'
        f'<legend style="font-size:11px;color:var(--ink-faint,#778)">{_h(kind.replace("_", " "))}</legend>'
        f"{fields}</fieldset>"
    )


def _render_section(section: Mapping[str, Any], surface: str) -> str:
    sid = str(section.get("section_id", ""))
    chrome = ""
    for field, label, opts in SECTION_CHROME.get(surface, []):
        cur = str(section.get(field) or "")
        if isinstance(opts, (tuple, list)):
            chrome += _select_row(f"section__{sid}__{field}", label, cur, opts)
        else:
            chrome += _field_row(f"section__{sid}__{field}", label, cur, str(opts))
    blocks = "".join(_render_block(b, surface) for b in (section.get("blocks") or []))
    if not chrome and not blocks:
        return ""
    return f'<div class="mh-se-section" style="margin:10px 0">{chrome}{blocks}</div>'


def render_structured(spec: Mapping[str, Any], surface: str) -> str:
    """Render the structured-editor body (form INNER html — the route wraps it in
    a ``<form>`` with the content-edit action + a Save button).
    """
    parts: list[str] = []
    for field, label, typ in SPEC_CHROME.get(surface, []):
        parts.append(_field_row(f"spec__{field}", label, str(spec.get(field) or ""), typ))
    parts.append("".join(_render_section(s, surface) for s in (spec.get("sections") or [])))
    return "".join(parts)


__all__ = [
    "FIELD_WHITELIST",
    "SECTION_CHROME",
    "SPEC_CHROME",
    "apply_structured",
    "render_structured",
    "has_structured_editor",
]
