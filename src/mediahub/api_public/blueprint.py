"""mediahub/api_public/blueprint.py — the versioned /api/v1 REST adapter.

The first Flask Blueprint in the monolith. It is a thin transport layer over
``service.py``: parse the request, enforce the bearer token + its scope, call
the capability, render the JSON (or file) response. All domain logic — gates,
tenant checks — lives in the service / the registered callbacks, so this file
stays about HTTP.

Auth model: ``Authorization: Bearer mhk_…``. The token resolves to an org
(``profile_id``) and a scope set, both stashed on ``flask.g`` for the request.
Public meta endpoints (index, health, the OpenAPI doc) need no token.
"""

from __future__ import annotations

import io
import logging

from flask import Blueprint, g, jsonify, request, send_file

from .errors import ApiError, forbidden_scope, rate_limited, unauthorized
from .openapi import API_VERSION, build_spec
from .ratelimit import RateLimiter
from .scopes import has_scope
from .tokens import ApiTokenStore
from . import service

log = logging.getLogger(__name__)

BASE_PATH = "/api/v1"

# Endpoint function names reachable without a token.
_PUBLIC = {"index", "health", "openapi_spec"}


def build_api_v1_blueprint(*, token_store: ApiTokenStore | None = None,
                           rate_limiter: RateLimiter | None = None) -> Blueprint:
    bp = Blueprint("api_v1", __name__, url_prefix=BASE_PATH)
    tokens = token_store or ApiTokenStore()
    limiter = rate_limiter or RateLimiter()

    # --- request lifecycle -------------------------------------------------
    @bp.before_request
    def _authenticate():
        # Resolve the bearer token (if any) and stash it on g.
        g.api_token = None
        g.api_profile_id = None
        g.api_scopes = []
        auth = (request.headers.get("Authorization") or "").strip()
        presented = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if presented:
            tok = tokens.verify(presented)
            if tok is not None:
                g.api_token = tok
                g.api_profile_id = tok.profile_id
                g.api_scopes = list(tok.scopes)

        # Rate limit (per token, or per IP for unauthenticated traffic).
        key = f"tok:{g.api_token.id}" if g.api_token else f"ip:{request.remote_addr or '-'}"
        decision = limiter.check(key)
        g.api_rate = decision
        if not decision.allowed:
            raise rate_limited(decision.reset_after)

        # Public endpoints stop here; everything else needs a valid token.
        func = (request.endpoint or "").split(".")[-1]
        if func in _PUBLIC:
            return None
        if g.api_token is None:
            raise unauthorized()
        return None

    @bp.after_request
    def _rate_headers(resp):
        decision = getattr(g, "api_rate", None)
        if decision is not None and decision.limit:
            resp.headers["X-RateLimit-Limit"] = str(decision.limit)
            resp.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            resp.headers["X-RateLimit-Reset"] = str(decision.reset_after)
        return resp

    @bp.errorhandler(ApiError)
    def _api_error(err: ApiError):
        resp = jsonify(err.to_dict())
        resp.status_code = err.status
        for k, v in err.headers.items():
            resp.headers[k] = v
        return resp

    @bp.errorhandler(Exception)
    def _unexpected(err: Exception):
        # Never leak a traceback over the API; log server-side and return a
        # clean envelope.
        log.warning("api_public unexpected error on %s: %s", request.path, err, exc_info=True)
        resp = jsonify({"error": "internal_error", "message": "An unexpected error occurred."})
        resp.status_code = 500
        return resp

    # --- helpers -----------------------------------------------------------
    def _require(scope: str) -> str:
        if not has_scope(g.api_scopes, scope):
            raise forbidden_scope(scope)
        return g.api_profile_id

    def _bool_arg(name: str, default: bool) -> bool:
        raw = (request.args.get(name) or "").strip().lower()
        if not raw:
            return default
        return raw in ("1", "true", "yes", "on")

    # --- meta --------------------------------------------------------------
    @bp.route("/", methods=["GET"])
    def index():
        return jsonify(
            {
                "service": "MediaHub Platform API",
                "version": API_VERSION,
                "documentation": request.host_url.rstrip("/") + BASE_PATH + "/openapi.json",
                "endpoints": {
                    "runs": BASE_PATH + "/runs",
                    "brand_kits": BASE_PATH + "/brand-kits",
                    "data_tables": BASE_PATH + "/data/tables",
                },
            }
        )

    @bp.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "version": API_VERSION})

    @bp.route("/openapi.json", methods=["GET"])
    def openapi_spec():
        return jsonify(build_spec(BASE_PATH))

    @bp.route("/me", methods=["GET"])
    def me():
        tok = g.api_token
        return jsonify(
            {
                "profile_id": tok.profile_id,
                "token_id": tok.id,
                "name": tok.name,
                "scopes": list(tok.scopes),
            }
        )

    # --- runs --------------------------------------------------------------
    @bp.route("/runs", methods=["GET"])
    def list_runs():
        pid = _require("runs:read")
        limit = request.args.get("limit", 50)
        offset = request.args.get("offset", 0)
        try:
            limit_i, offset_i = int(limit), int(offset)
        except (TypeError, ValueError):
            raise ApiError("bad_request", "limit/offset must be integers", 400)
        return jsonify(service.list_runs(pid, limit=limit_i, offset=offset_i))

    @bp.route("/runs", methods=["POST"])
    def create_run():
        pid = _require("runs:write")
        # Accept either a multipart file field or a raw request body.
        file_name = request.args.get("file_name") or ""
        data = b""
        if request.files:
            f = next(iter(request.files.values()))
            data = f.read()
            file_name = file_name or (f.filename or "")
        else:
            data = request.get_data() or b""
        result = service.submit_results(
            pid,
            data,
            file_name or "results",
            fetch_pbs=_bool_arg("fetch_pbs", True),
            club_filter=(request.args.get("club") or None),
        )
        return jsonify(result), 202

    @bp.route("/runs/<run_id>", methods=["GET"])
    def get_run(run_id: str):
        pid = _require("runs:read")
        return jsonify(service.get_run(pid, run_id))

    # --- cards -------------------------------------------------------------
    @bp.route("/runs/<run_id>/cards", methods=["GET"])
    def list_cards(run_id: str):
        pid = _require("cards:read")
        return jsonify(service.list_cards(pid, run_id, status=request.args.get("status")))

    @bp.route("/runs/<run_id>/cards/<card_id>", methods=["GET"])
    def get_card(run_id: str, card_id: str):
        pid = _require("cards:read")
        return jsonify(service.get_card(pid, run_id, card_id))

    def _actor() -> str:
        tok = getattr(g, "api_token", None)
        return (getattr(tok, "created_by", "") or "") if tok else ""

    @bp.route("/runs/<run_id>/cards/<card_id>/approve", methods=["POST"])
    def approve_card(run_id: str, card_id: str):
        pid = _require("cards:approve")
        payload = request.get_json(silent=True) or {}
        body, status = service.set_card_status(
            pid, run_id, card_id, "approved", notes=payload.get("notes"), actor_email=_actor()
        )
        return jsonify(body), status

    @bp.route("/runs/<run_id>/cards/<card_id>/reject", methods=["POST"])
    def reject_card(run_id: str, card_id: str):
        pid = _require("cards:approve")
        payload = request.get_json(silent=True) or {}
        body, status = service.set_card_status(
            pid, run_id, card_id, "rejected", notes=payload.get("notes"), actor_email=_actor()
        )
        return jsonify(body), status

    @bp.route("/runs/<run_id>/cards/<card_id>", methods=["PATCH"])
    def edit_card(run_id: str, card_id: str):
        pid = _require("cards:write")
        payload = request.get_json(silent=True) or {}
        edits = payload.get("edits", payload)
        body, status = service.edit_card(pid, run_id, card_id, edits, actor_email=_actor())
        return jsonify(body), status

    # --- content export ----------------------------------------------------
    @bp.route("/runs/<run_id>/export", methods=["GET"])
    def export_pack(run_id: str):
        pid = _require("content:export")
        zip_bytes, name = service.export_pack(pid, run_id)
        return send_file(
            io.BytesIO(zip_bytes),
            as_attachment=True,
            download_name=name,
            mimetype="application/zip",
        )

    # --- brand + data ------------------------------------------------------
    @bp.route("/brand-kits", methods=["GET"])
    def list_brand_kits():
        pid = _require("brand:read")
        return jsonify(service.list_brand_kits(pid))

    @bp.route("/data/tables", methods=["GET"])
    def list_data_tables():
        pid = _require("data:read")
        return jsonify(service.list_data_tables(pid))

    # --- webhooks ----------------------------------------------------------
    @bp.route("/webhooks", methods=["GET"])
    def list_webhooks():
        pid = _require("webhooks:read")
        return jsonify(service.list_webhooks(pid))

    @bp.route("/webhooks", methods=["POST"])
    def create_webhook():
        pid = _require("webhooks:manage")
        payload = request.get_json(silent=True) or {}
        url = payload.get("url") or ""
        events = payload.get("events") or []
        if not url:
            raise ApiError("bad_request", "`url` is required.", 400)
        result = service.create_webhook(
            pid, url, events, description=payload.get("description", ""), created_by=_actor()
        )
        return jsonify(result), 201

    @bp.route("/webhooks/<endpoint_id>", methods=["GET"])
    def get_webhook(endpoint_id: str):
        pid = _require("webhooks:read")
        return jsonify(service.get_webhook(pid, endpoint_id))

    @bp.route("/webhooks/<endpoint_id>", methods=["DELETE"])
    def delete_webhook(endpoint_id: str):
        pid = _require("webhooks:manage")
        return jsonify(service.delete_webhook(pid, endpoint_id))

    @bp.route("/webhooks/<endpoint_id>/deliveries", methods=["GET"])
    def list_webhook_deliveries(endpoint_id: str):
        pid = _require("webhooks:read")
        return jsonify(service.list_webhook_deliveries(pid, endpoint_id))

    return bp


__all__ = ["build_api_v1_blueprint", "BASE_PATH"]
