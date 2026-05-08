"""
Flask app v2 — pilot-grade single-page upload + review for the Swansea
Uni pilot.

Differences from v1:
  - Accepts a Hytek meet zip directly (auto-extracts .hy3).
  - Accepts up to 4 PB PDFs in one form (Female LC/SC, Male LC/SC).
  - First screen post-upload is the UPLOAD REPORT, not the queue.
  - The queue is recomputed deterministically every time, so re-running
    the same upload produces the same output. No PB-store side effects.
  - Captions never expose internal labels.
"""
from __future__ import annotations
import json
import re
from datetime import date
from pathlib import Path
from tempfile import mkdtemp

from flask import Flask, request, redirect, url_for, render_template, send_file, jsonify, abort, session

from .pipeline import process_meet, PipelineResult
from .club_filter import swansea_uni_roster
from .content_gen_v2 import captions_for_card

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "uploads_v2"
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory session cache. For pilot we don't need DB persistence — every
# upload runs deterministically. A single user, single team, no auth.
_RUN_CACHE: dict[str, PipelineResult] = {}


def _save(file_storage, dest: Path) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    target = dest / file_storage.filename
    file_storage.save(target)
    return str(target)


def _detect_pdf_generated_date(path: str) -> str | None:
    """Sniff the SPORTSYSTEMS PDF footer 'dd/mm/yyyy hh:mm:ss' on page 1
    so we can warn if the PDFs were exported AFTER the meet."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[0].extract_text() or ""
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+\d{2}:\d{2}:\d{2}", text)
        if m:
            dd, mm, yyyy = m.groups()
            return f"{yyyy}-{mm}-{dd}"
    except Exception:
        pass
    return None


def create_app() -> Flask:
    app = Flask(__name__,
                template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"))
    app.secret_key = os.environ.get("SECRET_KEY", "") or os.urandom(24).hex()

    @app.route("/")
    def home():
        runs = [(rid, r.meet.name, r.report.queue_size) for rid, r in _RUN_CACHE.items()]
        return render_template("home_v2.html", runs=runs)

    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "GET":
            return render_template("upload_v2.html")

        run_dir = Path(mkdtemp(prefix="run_", dir=UPLOAD_DIR))
        meet_zip = _save(request.files.get("meet_zip"), run_dir)
        meet_hy3 = _save(request.files.get("meet_hy3"), run_dir)
        if not (meet_zip or meet_hy3):
            return render_template("upload_v2.html",
                                   error="Upload either a Hytek .zip or .hy3 file.")

        pdfs = {
            "female_lc": _save(request.files.get("pb_female_lc"), run_dir),
            "female_sc": _save(request.files.get("pb_female_sc"), run_dir),
            "male_lc":   _save(request.files.get("pb_male_lc"),   run_dir),
            "male_sc":   _save(request.files.get("pb_male_sc"),   run_dir),
        }
        if not any(pdfs.values()):
            return render_template("upload_v2.html",
                                   error="At least one PB PDF is required for PB detection. "
                                         "Upload your SPORTSYSTEMS Club Rankings exports.")

        # Sniff the most recent PDF generated date
        pb_dates = [d for d in (_detect_pdf_generated_date(p) for p in pdfs.values() if p) if d]
        pb_generated = max(pb_dates) if pb_dates else None

        try:
            result = process_meet(
                hy3_path=meet_hy3,
                meet_zip_path=meet_zip,
                pb_pdf_paths={k: v for k, v in pdfs.items() if v},
                roster=swansea_uni_roster(),
                pb_store_generated_iso=pb_generated,
            )
        except Exception as e:
            return render_template("upload_v2.html",
                                   error=f"Processing failed: {e}")

        rid = run_dir.name
        _RUN_CACHE[rid] = result
        return redirect(url_for("report", rid=rid))

    @app.route("/report/<rid>")
    def report(rid):
        result = _RUN_CACHE.get(rid)
        if not result:
            abort(404)
        return render_template("report_v2.html", rid=rid, r=result)

    @app.route("/queue/<rid>")
    def queue(rid):
        result = _RUN_CACHE.get(rid)
        if not result:
            abort(404)
        cards = []
        for c in result.queue.queue:
            cards.append({
                "swimmer": c.swimmer_name,
                "event": f"{c.distance}m {c.stroke}",
                "course": c.course,
                "place": c.place,
                "time": _fmt(c.time_cs),
                "score": c.score,
                "reasons": [r.kind.value for r in c.reasons],
                "captions": captions_for_card(c, n_variants=2),
            })
        return render_template("queue_v2.html",
                               rid=rid, r=result, cards=cards,
                               recap_text=result.weekend_recap_text)

    @app.route("/api/export/<rid>")
    def export_json(rid):
        result = _RUN_CACHE.get(rid)
        if not result:
            abort(404)
        export = {
            "meet": result.meet.name,
            "queue": [
                {
                    "swimmer": c.swimmer_name, "asa_id": c.asa_id,
                    "event": f"{c.distance}m {c.stroke} {c.course}",
                    "place": c.place, "time": _fmt(c.time_cs), "score": c.score,
                    "reasons": [r.kind.value for r in c.reasons],
                    "captions": captions_for_card(c, n_variants=2),
                } for c in result.queue.queue
            ],
            "weekend_recap": result.weekend_recap_text,
            "report": {
                "queue_size": result.report.queue_size,
                "warnings": result.report.warnings,
                "needs_confirmation": result.report.needs_confirmation,
            },
        }
        out_path = UPLOAD_DIR / f"export_{rid}.json"
        out_path.write_text(json.dumps(export, indent=2))
        return send_file(out_path, as_attachment=True)

    return app


def _fmt(cs: int | None) -> str:
    if cs is None:
        return "-"
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=False)
