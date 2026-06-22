"""Forms engine (roadmap 1.16) — build 2: accessible HTML form rendering."""

from __future__ import annotations

from mediahub.forms.models import FormField, FormSpec
from mediahub.forms.render import render_form_html


def _form(**kw):
    return FormSpec(
        title="Trial sign-up",
        intro="Come and try us",
        fields=[
            FormField(label="Name", required=True),
            FormField(label="Email", type="email", required=True),
            FormField(label="Size", type="select", options=["S", "M"]),
            FormField(label="Notes", type="textarea"),
            FormField(label="I agree", type="consent", required=True),
        ],
        **kw,
    )


def test_renders_fields_and_honeypot():
    html = render_form_html(_form(), action_url="/site/TKN/form/f1", nonce="N1")
    assert "Trial sign-up" in html and "Come and try us" in html
    assert 'type="email"' in html
    assert "<select" in html and ">S<" in html and ">M<" in html
    assert "<textarea" in html
    assert 'type="checkbox"' in html  # consent
    # honeypot present + hidden
    assert 'name="_hp"' in html and "left:-9999px" in html
    # the action + nonce are threaded into the inline script
    assert "/site/TKN/form/f1" in html
    assert 'nonce="N1"' in html
    assert "addEventListener('submit'" in html


def test_required_and_minor_note():
    html = render_form_html(_form(collects_minor_data=True))
    assert 'class="req"' in html  # required markers
    assert "young person" in html  # minor-data note shown


def test_escapes_labels_xss():
    form = FormSpec(title="<script>x</script>", fields=[FormField(label="<b>name</b>")])
    html = render_form_html(form)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>name</b>" not in html


def test_preview_omits_script():
    html = render_form_html(_form(), interactive=False)
    assert "<form" in html
    assert "addEventListener" not in html  # no submit script in preview
