"""forms.render — a FormSpec → accessible, self-contained HTML form (1.16).

This is the renderer the microsite engine's ``form_embed`` block calls. The form
is plain HTML (progressively enhanced: it carries native ``required``/``type``
validation) plus one small, **self-contained** inline submit script stamped with
the page's CSP ``nonce`` — it serialises the fields to JSON and POSTs them to the
form's same-origin action URL, then shows the success message or per-field errors.
No external scripts, no third-party form service (in-house, rule 11). Every label,
option and message is ``markupsafe``-escaped.

A hidden **honeypot** field (`_hp`) is included for spam defence; a real visitor
never sees it, and :mod:`forms.submit` discards anything that fills it.
"""

from __future__ import annotations

import json

from markupsafe import escape as _h

from .models import FormField, FormSpec
from .submit import DEFAULT_HONEYPOT


def _field_html(f: FormField) -> str:
    req = " required" if f.required else ""
    req_mark = ' <span class="req" aria-hidden="true">*</span>' if f.required else ""
    fid = f"f_{_h(f.key)}"
    help_html = (
        f'<small class="form-help" id="{fid}_help">{_h(f.help_text)}</small>' if f.help_text else ""
    )
    aria_help = f' aria-describedby="{fid}_help"' if f.help_text else ""
    err = f'<small class="form-err" data-err="{_h(f.key)}" role="alert"></small>'

    if f.type in ("checkbox", "consent"):
        # the label wraps the control for a single tickbox
        return (
            '<div class="form-row form-check">'
            f'<label for="{fid}"><input type="checkbox" id="{fid}" name="{_h(f.key)}"{req}{aria_help}/> '
            f"{_h(f.label)}{req_mark}</label>{help_html}{err}</div>"
        )

    if f.type == "textarea":
        control = (
            f'<textarea id="{fid}" name="{_h(f.key)}" rows="4" '
            f'maxlength="{f.effective_max_len}" placeholder="{_h(f.placeholder)}"{req}{aria_help}></textarea>'
        )
    elif f.type == "select":
        opts = '<option value="">Choose…</option>' + "".join(
            f'<option value="{_h(o)}">{_h(o)}</option>' for o in f.options
        )
        control = f'<select id="{fid}" name="{_h(f.key)}"{req}{aria_help}>{opts}</select>'
    else:
        input_type = {
            "email": "email",
            "tel": "tel",
            "number": "number",
            "date": "date",
        }.get(f.type, "text")
        maxlen = (
            f' maxlength="{f.effective_max_len}"' if input_type in ("text", "tel", "email") else ""
        )
        control = (
            f'<input type="{input_type}" id="{fid}" name="{_h(f.key)}" '
            f'placeholder="{_h(f.placeholder)}"{maxlen}{req}{aria_help}/>'
        )

    return (
        '<div class="form-row">'
        f'<label for="{fid}">{_h(f.label)}{req_mark}</label>{control}{help_html}{err}</div>'
    )


def _submit_script(dom_id: str, action_url: str, nonce: str) -> str:
    """The self-contained submit handler (no external JS, nonce-stamped)."""
    cfg = json.dumps({"id": dom_id, "action": action_url})
    nonce_attr = f' nonce="{_h(nonce)}"' if nonce else ""
    js = (
        "(function(){var C=__CFG__;var f=document.getElementById(C.id);if(!f)return;"
        "f.addEventListener('submit',function(e){e.preventDefault();"
        "var s=f.querySelector('[data-form-status]');"
        "f.querySelectorAll('[data-err]').forEach(function(x){x.textContent='';});"
        "var d={};new FormData(f).forEach(function(v,k){d[k]=v;});"
        "f.querySelectorAll('input[type=checkbox]').forEach(function(c){d[c.name]=c.checked;});"
        "if(s){s.className='form-status';s.textContent='Sending…';}"
        "fetch(C.action,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify(d)}).then(function(r){return r.json();}).then(function(j){"
        "if(j&&j.ok){f.reset();f.style.display='none';if(s){s.className='form-success';"
        "s.textContent=j.message||'Thanks — got it.';}}else{if(s){s.className='form-error';"
        "s.textContent='Please check the highlighted fields.';}"
        "if(j&&j.errors){Object.keys(j.errors).forEach(function(k){"
        "var el=f.querySelector('[data-err=\"'+k+'\"]');if(el)el.textContent=j.errors[k];});}}"
        "}).catch(function(){if(s){s.className='form-error';"
        "s.textContent='Something went wrong — please try again.';}});});})();"
    )
    return f"<script{nonce_attr}>{js.replace('__CFG__', cfg)}</script>"


def render_form_html(
    form: FormSpec,
    *,
    action_url: str = "#",
    nonce: str = "",
    interactive: bool = True,
) -> str:
    """Render ``form`` to a self-contained HTML form.

    ``action_url`` is the same-origin endpoint that accepts the JSON submission;
    ``interactive=False`` renders the fields without the submit script (for the
    operator preview in the editor)."""
    dom_id = f"mhform_{_h(form.form_id)}"
    parts = ['<div class="site-form-wrap">']
    if form.title:
        parts.append(f"<h3>{_h(form.title)}</h3>")
    if form.intro:
        parts.append(f'<p class="form-intro">{_h(form.intro)}</p>')
    parts.append(f'<form id="{dom_id}" class="site-form" novalidate>')
    # honeypot — visually hidden, off-screen, not announced to AT
    parts.append(
        f'<div class="form-hp" aria-hidden="true" style="position:absolute;left:-9999px;'
        f'width:1px;height:1px;overflow:hidden">'
        f'<label>Leave this empty<input type="text" name="{DEFAULT_HONEYPOT}" '
        f'tabindex="-1" autocomplete="off"/></label></div>'
    )
    for f in form.fields:
        parts.append(_field_html(f))
    if form.has_minor_sensitive_field:
        parts.append(
            '<p class="form-minor-note">This form collects a young person\'s details. '
            "We only use them for the club activity above and store them securely.</p>"
        )
    parts.append(f'<button type="submit" class="site-btn primary">{_h(form.submit_label)}</button>')
    parts.append('<p class="form-status" data-form-status role="status"></p>')
    parts.append("</form>")
    if interactive:
        parts.append(_submit_script(dom_id, action_url, nonce))
    parts.append("</div>")
    return "".join(parts)


__all__ = ["render_form_html"]
