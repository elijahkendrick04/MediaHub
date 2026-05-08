"""
Swim Content Intelligence — V3 Flask app.

Four stages:
  1. Upload     — choose file, club, output preferences
  2. Verification — show pipeline results (PB, quals, self-check) before dashboard
  3. Dashboard  — content cards with approve/reject/edit
  4. Output     — copy-ready captions + JSON + zip

State is held in-memory keyed by run_id. Persisted artefacts go under
output_v3/<run_id>/. The pilot is single-user, so no auth.
"""
from __future__ import annotations

import os
import time
import uuid
import json
from dataclasses import asdict
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_file, abort, flash,
)

from swim_content.pipeline_v3 import run_pipeline, PipelineRun
from swim_content.output_pack import (
    assemble_pack, render_text_pack, render_json_pack, render_zip_bytes,
)
from swim_content.cards import ContentCard


BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads_v3"
OUTPUTS = BASE / "output_v3"
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)


app = Flask(__name__, template_folder="templates", static_folder="static")
import os as _os
app.secret_key = _os.environ.get("SECRET_KEY", "") or _os.urandom(24).hex()
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024  # 80 MB


# ----------------------------------------------------------------------------
# In-memory run store
# ----------------------------------------------------------------------------

# run_id -> dict(run=PipelineRun, file_path=str, started=ts)
RUNS: dict[str, dict] = {}


def _get_run(run_id: str) -> PipelineRun:
    rec = RUNS.get(run_id)
    if not rec:
        abort(404, "Run not found. It may have expired — please upload again.")
    return rec["run"]


def _save_run_dir(run_id: str) -> Path:
    d = OUTPUTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

@app.route("/")
def root():
    return redirect(url_for("upload_v3"))


@app.route("/upload", methods=["GET", "POST"])
def upload_v3():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Please choose a meet file (.hy3 or .zip).", "error")
            return redirect(url_for("upload_v3"))

        run_id = uuid.uuid4().hex[:12]
        save_path = UPLOADS / f"{run_id}__{f.filename}"
        f.save(save_path)

        club_choice = request.form.get("club_choice", "SUNY")
        output_pref = request.form.get("output_pref", "both")
        use_cache = request.form.get("use_cache", "1") == "1"

        # Run pipeline synchronously. For Swansea-sized files this takes
        # under 60s with cache; first-time fetches add ~1s per swimmer.
        try:
            run = run_pipeline(
                file_path=str(save_path),
                club_choice=club_choice,
                output_pref=output_pref,
                use_pb_cache=use_cache,
            )
        except Exception as exc:
            flash(f"Pipeline error: {exc}", "error")
            return redirect(url_for("upload_v3"))

        RUNS[run_id] = {"run": run, "file_path": str(save_path), "started": time.time()}
        return redirect(url_for("verification_v3", run_id=run_id))

    return render_template("upload_v3.html")


@app.route("/verification/<run_id>")
def verification_v3(run_id: str):
    run = _get_run(run_id)
    return render_template("verification_v3.html", run_id=run_id, run=run)


@app.route("/dashboard/<run_id>")
def dashboard_v3(run_id: str):
    run = _get_run(run_id)
    bucket = request.args.get("bucket", "queue")
    if bucket not in ("queue", "needs_confirmation", "recap", "archive"):
        bucket = "queue"
    bucket_cards = [c for c in run.cards if c.bucket == bucket]
    counts = {
        "queue": sum(1 for c in run.cards if c.bucket == "queue"),
        "needs_confirmation": sum(1 for c in run.cards if c.bucket == "needs_confirmation"),
        "recap": sum(1 for c in run.cards if c.bucket == "recap"),
        "archive": sum(1 for c in run.cards if c.bucket == "archive"),
    }
    return render_template(
        "dashboard_v3.html",
        run_id=run_id, run=run,
        cards=bucket_cards, bucket=bucket, counts=counts,
    )


@app.post("/api/<run_id>/cards/<card_id>/decide")
def api_decide(run_id: str, card_id: str):
    run = _get_run(run_id)
    body = request.get_json(silent=True) or {}
    action = body.get("action")  # 'approve' | 'reject' | 'reset'
    voice = body.get("voice")    # 'clean' | 'team' | 'hype' | None
    custom = body.get("caption")

    target = next((c for c in run.cards if c.card_id == card_id), None)
    if not target:
        return jsonify({"ok": False, "error": "card not found"}), 404

    if action == "approve":
        target.approved = True
        if custom is not None:
            target.user_caption = custom.strip() or None
        elif voice:
            chosen = target.captions.all().get(voice, "")
            target.user_caption = chosen
    elif action == "reject":
        target.approved = False
        target.user_caption = None
    elif action == "reset":
        target.approved = None
        target.user_caption = None
    else:
        return jsonify({"ok": False, "error": "bad action"}), 400

    return jsonify({
        "ok": True,
        "approved": target.approved,
        "user_caption": target.user_caption,
    })


@app.route("/output/<run_id>")
def output_v3(run_id: str):
    run = _get_run(run_id)
    pack = assemble_pack(run.cards, meet_name=run.meet_name, club_name=run.club_display)
    return render_template(
        "output_v3.html",
        run_id=run_id, run=run, pack=pack,
    )


@app.route("/output/<run_id>/download.<fmt>")
def output_download(run_id: str, fmt: str):
    run = _get_run(run_id)
    pack = assemble_pack(run.cards, meet_name=run.meet_name, club_name=run.club_display)
    out_dir = _save_run_dir(run_id)
    base = f"swim-content-{run_id}"

    if fmt == "json":
        path = out_dir / f"{base}.json"
        path.write_text(render_json_pack(pack))
        return send_file(path, as_attachment=True,
                         download_name=f"{base}.json", mimetype="application/json")
    if fmt == "txt":
        path = out_dir / f"{base}.txt"
        path.write_text(render_text_pack(pack))
        return send_file(path, as_attachment=True,
                         download_name=f"{base}.txt", mimetype="text/plain")
    if fmt == "zip":
        path = out_dir / f"{base}.zip"
        path.write_bytes(render_zip_bytes(pack))
        return send_file(path, as_attachment=True,
                         download_name=f"{base}.zip", mimetype="application/zip")
    abort(404)


# ----------------------------------------------------------------------------
# Template helpers
# ----------------------------------------------------------------------------

@app.template_filter("status_class")
def _status_class(status: str) -> str:
    return {"pass": "pass", "warn": "warn", "fail": "fail"}.get(status, "")


@app.template_filter("status_icon")
def _status_icon(status: str) -> str:
    return {"pass": "✓", "warn": "!", "fail": "✗"}.get(status, "·")


@app.template_filter("card_type_label")
def _card_type_label(t: str) -> str:
    return {
        "standout_swim": "Standout swim",
        "athlete_spotlight": "Athlete spotlight",
        "podium_roundup": "Podium roundup",
        "pb_roundup": "PB roundup",
        "qual_alert": "Qualifier alert",
        "weekend_in_numbers": "Weekend in numbers",
        "needs_confirmation": "Needs confirmation",
        "recap_only": "Recap mention",
        "archive": "Archive",
    }.get(t, t)


@app.template_filter("confidence_label")
def _confidence_label(c: str) -> str:
    return {"high": "High confidence", "medium": "Medium confidence",
            "low": "Low confidence"}.get(c, c)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5051, debug=False)
