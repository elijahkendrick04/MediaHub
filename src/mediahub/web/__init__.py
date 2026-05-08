"""mediahub.web — Flask UI + helpers (formerly swim_content_v4)."""
from .web import app, create_app  # re-export for gunicorn entry

__all__ = ["app", "create_app"]
