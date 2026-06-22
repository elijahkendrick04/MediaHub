"""forms.models — the typed schema for a club form (roadmap 1.16).

A :class:`FormSpec` describes one public form a club embeds on a microsite page:
a trial sign-up, a volunteer rota, a kit order, an event RSVP. It is plain,
JSON-round-trippable data — a list of typed :class:`FormField` — that the renderer
(:mod:`forms.render`) turns into an accessible HTML form and the submit flow
(:mod:`forms.submit`) validates and turns into a **typed row in the 1.13 data hub**
(:mod:`mediahub.data_hub`), one submission per row, exportable and GDPR-deletable.

Because forms can collect a **child's** personal data, the model carries a
``collects_minor_data`` flag and a ``consent`` field type: the submit flow enforces
required consent, and the web layer applies the minors'-data rules hard (ADR-0003 /
the Children's-Code pass). Nothing is silently coerced — an invalid field is
reported, never guessed (CLAUDE.md: make uncertainty explicit).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# The input kinds a club form supports. Renderer + validator dispatch on these;
# unknown kinds fall back to a plain text input (forward-compatible).
FIELD_TYPES: tuple[str, ...] = (
    "text",
    "email",
    "tel",
    "number",
    "textarea",
    "select",
    "checkbox",  # a single yes/no tickbox
    "date",
    "consent",  # a tickbox that, when required, MUST be ticked (GDPR consent)
)

# How each field type lands in a data-hub column (data_hub COLUMN_TYPES are
# "text", "number", "int", "time", "date", "bool").
FIELD_TO_COLUMN_TYPE: dict[str, str] = {
    "text": "text",
    "email": "text",
    "tel": "text",
    "textarea": "text",
    "select": "text",
    "number": "number",
    "date": "date",
    "checkbox": "bool",
    "consent": "bool",
}

DEFAULT_MAX_LEN = 2000

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TEL_RE = re.compile(r"^[0-9+()\-.\s]{6,32}$")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _field_key(label: str, default: str = "field") -> str:
    s = _SLUG_RE.sub("_", str(label or "").strip().lower()).strip("_")
    return s or default


@dataclass(frozen=True)
class FormField:
    """One form field. ``options`` apply to ``select``; ``max_len`` caps text."""

    label: str
    key: str = ""
    type: str = "text"
    required: bool = False
    options: list[str] = field(default_factory=list)
    placeholder: str = ""
    help_text: str = ""
    max_len: int = 0  # 0 → DEFAULT_MAX_LEN for text kinds
    minors_sensitive: bool = False  # e.g. a child's name / DOB — handled with care

    def __post_init__(self) -> None:
        if self.type not in FIELD_TYPES:
            object.__setattr__(self, "type", "text")
        if not self.key:
            object.__setattr__(self, "key", _field_key(self.label))
        object.__setattr__(self, "options", [str(o) for o in (self.options or [])])

    @property
    def column_type(self) -> str:
        return FIELD_TO_COLUMN_TYPE.get(self.type, "text")

    @property
    def effective_max_len(self) -> int:
        return self.max_len if self.max_len > 0 else DEFAULT_MAX_LEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "options": list(self.options),
            "placeholder": self.placeholder,
            "help_text": self.help_text,
            "max_len": self.max_len,
            "minors_sensitive": self.minors_sensitive,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FormField":
        if not isinstance(raw, dict):
            return cls(label="Field")
        return cls(
            label=str(raw.get("label") or "Field"),
            key=str(raw.get("key") or ""),
            type=str(raw.get("type") or "text"),
            required=bool(raw.get("required")),
            options=[str(o) for o in (raw.get("options") or [])],
            placeholder=str(raw.get("placeholder") or ""),
            help_text=str(raw.get("help_text") or ""),
            max_len=int(raw.get("max_len") or 0),
            minors_sensitive=bool(raw.get("minors_sensitive")),
        )


@dataclass(frozen=True)
class FormSpec:
    """A complete, render-ready public form."""

    title: str
    fields: list[FormField] = field(default_factory=list)
    form_id: str = ""
    intro: str = ""
    submit_label: str = "Submit"
    success_message: str = "Thanks — we've got your response."
    notify: bool = True  # ping the club's notify channels on each submission
    collects_minor_data: bool = False  # this form gathers a child's personal data
    table_id: str = ""  # the data-hub table submissions land in (set on first submit)

    def __post_init__(self) -> None:
        if not self.form_id:
            object.__setattr__(self, "form_id", _new_id("form"))
        # de-dupe field keys so two "Name" fields don't collide in the data hub
        seen: set[str] = set()
        deduped: list[FormField] = []
        for f in self.fields:
            key = f.key
            if key in seen:
                n = 2
                while f"{key}_{n}" in seen:
                    n += 1
                key = f"{key}_{n}"
                f = FormField.from_dict({**f.to_dict(), "key": key})
            seen.add(key)
            deduped.append(f)
        object.__setattr__(self, "fields", deduped)

    @property
    def has_minor_sensitive_field(self) -> bool:
        return self.collects_minor_data or any(f.minors_sensitive for f in self.fields)

    def field_by_key(self, key: str) -> FormField | None:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_id": self.form_id,
            "title": self.title,
            "intro": self.intro,
            "submit_label": self.submit_label,
            "success_message": self.success_message,
            "notify": self.notify,
            "collects_minor_data": self.collects_minor_data,
            "table_id": self.table_id,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FormSpec":
        if not isinstance(raw, dict):
            return cls(title="Form")
        return cls(
            title=str(raw.get("title") or "Form"),
            intro=str(raw.get("intro") or ""),
            submit_label=str(raw.get("submit_label") or "Submit"),
            success_message=str(raw.get("success_message") or "Thanks — we've got your response."),
            notify=bool(raw.get("notify", True)),
            collects_minor_data=bool(raw.get("collects_minor_data")),
            table_id=str(raw.get("table_id") or ""),
            fields=[FormField.from_dict(f) for f in (raw.get("fields") or [])],
            form_id=str(raw.get("form_id") or ""),
        )


def new_form(title: str, fields: list[FormField] | None = None, **kwargs: Any) -> FormSpec:
    return FormSpec(title=str(title), fields=list(fields or []), **kwargs)


# A few ready-made field sets the archetypes/UI can start from (deterministic).
def trial_signup_fields() -> list[FormField]:
    return [
        FormField(label="Swimmer's name", type="text", required=True, minors_sensitive=True),
        FormField(label="Parent / guardian name", type="text", required=True),
        FormField(label="Email", type="email", required=True),
        FormField(label="Phone", type="tel"),
        FormField(label="Age group", type="select", options=["8 & under", "9-11", "12-14", "15+"]),
        FormField(
            label="I consent to the club contacting me about a trial",
            type="consent",
            required=True,
        ),
    ]


def rsvp_fields() -> list[FormField]:
    return [
        FormField(label="Name", type="text", required=True),
        FormField(label="Email", type="email", required=True),
        FormField(label="Number attending", type="number"),
        FormField(label="Notes", type="textarea"),
    ]


__all__ = [
    "FIELD_TYPES",
    "FIELD_TO_COLUMN_TYPE",
    "DEFAULT_MAX_LEN",
    "FormField",
    "FormSpec",
    "new_form",
    "trial_signup_fields",
    "rsvp_fields",
]
