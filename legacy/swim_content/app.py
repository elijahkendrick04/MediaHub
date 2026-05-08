"""
Flask app — single-page approval dashboard.

Routes:
  GET  /                    landing + recent meets
  GET  /upload              upload form
  POST /upload              ingest a meet file -> redirect to /review/<meet_id>
  GET  /review/<meet_id>    three-pane review UI (queue | item | approve)
  POST /api/approve         persist approval choice
  POST /api/import-pbs      upload historical PB CSV
  GET  /api/export/<meet_id>  download approved content as JSON
"""

from __future__ import annotations
import json
import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, request, redirect, url_for, render_template, jsonify, abort, send_file

from . import parsers, identity, detector, crossref, content_gen
from .events import event_human, cs_to_str

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "swim_content.db"
SCHEMA_PATH = ROOT / "schema.sql"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA_PATH.read_text())
    # Seed Swansea club if not present
    if not conn.execute("SELECT 1 FROM club WHERE short_name='SUS'").fetchone():
        conn.execute(
            "INSERT INTO club (name, short_name, brand_json) VALUES (?,?,?)",
            ("Swansea University Swimming", "SUS",
             json.dumps({"primary": "#A30D2D", "secondary": "#000000"})),
        )
    conn.commit()
    conn.close()


def create_app():
    app = Flask(__name__, template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"))
    app.jinja_env.filters["fromjson"] = lambda s: json.loads(s) if s else []
    init_db()

    # ---------------- routes ----------------

    @app.route("/")
    def home():
        conn = get_db()
        meets = conn.execute(
            "SELECT id, name, venue, course, start_date FROM meet ORDER BY id DESC LIMIT 20"
        ).fetchall()
        conn.close()
        return render_template("home.html", meets=meets)

    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "GET":
            return render_template("upload.html")

        f = request.files.get("file")
        if not f:
            return "No file", 400
        meet_name = request.form.get("meet_name") or f.filename
        course = request.form.get("course", "LC")
        venue = request.form.get("venue", "")
        meet_date = request.form.get("meet_date") or date.today().isoformat()

        content = f.read()
        rows = parsers.parse_any(content, f.filename, course_hint=course)
        if not rows:
            return render_template("upload.html",
                                   error=f"No usable rows found in {f.filename}. "
                                         "Check format / column names.")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO meet (name, venue, course, start_date, end_date, source_type, source_uri, status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (meet_name, venue, course, meet_date, meet_date,
             Path(f.filename).suffix.lstrip("."), f.filename, "final"),
        )
        meet_id = cur.lastrowid

        # Default club: Swansea (single-tenant prototype)
        club_id = conn.execute("SELECT id FROM club WHERE short_name='SUS'").fetchone()[0]

        for row in rows:
            sid = identity.resolve_or_create(
                conn, row["swimmer_name"], gender=row["gender"], club_id=club_id
            )
            cur.execute(
                "INSERT INTO race_result (meet_id, swimmer_id, event_code, round, "
                "place, time_cs, entry_time_cs, dq) VALUES (?,?,?,?,?,?,?,?)",
                (meet_id, sid, row["event_code"], row["round"], row["place"],
                 row["time_cs"], row["entry_time_cs"], 1 if row["dq"] else 0),
            )
        conn.commit()

        # Run detection
        items = detector.detect_achievements(conn, meet_id, meet_date)
        ach_ids = detector.persist_achievements(conn, meet_id, items)

        # Pre-generate captions per achievement
        voice = content_gen.SWANSEA_VOICE
        for ach_id, item in zip(ach_ids, items):
            d = item.__dict__.copy()
            captions = content_gen.captions_for_achievement(d, voice=voice)
            for fmt in (item.suggested_formats or []):
                if fmt == "recap_only":
                    continue
                cur.execute(
                    "INSERT INTO content_item (achievement_id, format, captions_json) "
                    "VALUES (?,?,?)",
                    (ach_id, fmt, json.dumps(captions["variants"])),
                )

        # Weekend-in-numbers as a separate content_item
        win = content_gen.weekend_in_numbers(meet_name,
                                             [a.__dict__ for a in items], voice)
        cur.execute(
            "INSERT INTO content_item (achievement_id, format, captions_json) "
            "VALUES (NULL, 'recap', ?)",
            (json.dumps(win["variants"]),),
        )

        conn.commit()
        conn.close()
        return redirect(url_for("review", meet_id=meet_id))

    @app.route("/review/<int:meet_id>")
    def review(meet_id):
        conn = get_db()
        meet = conn.execute("SELECT * FROM meet WHERE id=?", (meet_id,)).fetchone()
        if not meet:
            abort(404)
        achievements = conn.execute(
            "SELECT a.*, s.display_name as swimmer_name, "
            "       COALESCE(r.event_code, '-') as event_code "
            "FROM achievement a "
            "LEFT JOIN swimmer s ON s.id=a.swimmer_id "
            "LEFT JOIN race_result r ON r.id=a.race_id "
            "WHERE a.meet_id=? ORDER BY a.content_worthiness DESC", (meet_id,)
        ).fetchall()
        # Hydrate content_items per achievement
        items_by_ach = {}
        for ci in conn.execute(
            "SELECT * FROM content_item WHERE achievement_id IN "
            "(SELECT id FROM achievement WHERE meet_id=?)",
            (meet_id,)
        ).fetchall():
            items_by_ach.setdefault(ci["achievement_id"], []).append(dict(ci))
        recap_items = [dict(c) for c in conn.execute(
            "SELECT * FROM content_item WHERE achievement_id IS NULL "
            "AND format='recap'"
        ).fetchall()]
        conn.close()

        # Convert SQLite Rows to dicts and add helpers
        ach_view = []
        for a in achievements:
            d = dict(a)
            d["evidence"] = json.loads(d.get("evidence_json") or "{}")
            d["suggested_formats"] = json.loads(d.get("suggested_formats") or "[]")
            d["event_human"] = event_human(d["event_code"]) if d["event_code"] != "-" else ""
            d["content_items"] = items_by_ach.get(d["id"], [])
            for ci in d["content_items"]:
                ci["captions"] = json.loads(ci.get("captions_json") or "[]")
            d["confidence_stars"] = "★" * round(d["confidence"] * 5) + "☆" * (5 - round(d["confidence"] * 5))
            ach_view.append(d)

        return render_template(
            "review.html",
            meet=dict(meet),
            achievements=ach_view,
            recap_items=recap_items,
        )

    @app.route("/api/approve", methods=["POST"])
    def api_approve():
        data = request.get_json(force=True)
        ci_id = int(data["content_item_id"])
        decision = data["decision"]            # 'approved' | 'rejected' | 'edited'
        caption = data.get("caption")
        conn = get_db()
        conn.execute(
            "UPDATE content_item SET approval_status=?, approved_caption=? "
            "WHERE id=?",
            (decision, caption, ci_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/import-pbs", methods=["POST"])
    def api_import_pbs():
        f = request.files.get("file")
        if not f:
            return "No file", 400
        text = f.read().decode("utf-8", errors="ignore")
        conn = get_db()
        n = crossref.import_pbs_csv(conn, text)
        conn.close()
        return jsonify({"imported": n})

    @app.route("/api/export/<int:meet_id>")
    def api_export(meet_id):
        conn = get_db()
        rows = conn.execute(
            "SELECT a.id as ach_id, a.type, a.explanation, a.confidence, "
            "       a.content_worthiness, s.display_name as swimmer, "
            "       ci.id as ci_id, ci.format, ci.approved_caption, ci.approval_status "
            "FROM achievement a "
            "LEFT JOIN swimmer s ON s.id=a.swimmer_id "
            "LEFT JOIN content_item ci ON ci.achievement_id=a.id "
            "WHERE a.meet_id=? AND ci.approval_status='approved' "
            "ORDER BY a.content_worthiness DESC",
            (meet_id,),
        ).fetchall()
        conn.close()
        out = [dict(r) for r in rows]
        out_path = ROOT / f"export_meet_{meet_id}.json"
        out_path.write_text(json.dumps(out, indent=2))
        return send_file(out_path, as_attachment=True)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=False)
