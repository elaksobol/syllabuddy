"""Flask web app: JSON API + a single-page front end."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, render_template, request

from . import db, emailer
from .attendance import attendance_impact
from .gemini_client import GeminiBackend, GeminiError, generate_flashcards, parse_syllabus
from .ics import build_calendar


def create_app(db_path: str | None = None, backend=None) -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload cap
    app.config["DB_PATH"] = db_path
    app.config["BACKEND"] = backend

    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    def get_backend():
        if app.config["BACKEND"] is None:
            app.config["BACKEND"] = GeminiBackend()
        return app.config["BACKEND"]

    @app.teardown_appcontext
    def close_conn(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.errorhandler(GeminiError)
    def gemini_error(e):
        return jsonify(error=str(e)), 502

    # ---- pages ----
    @app.get("/")
    def index():
        return render_template("index.html")

    # ---- courses ----
    @app.get("/api/courses")
    def courses():
        return jsonify(db.list_courses(conn()))

    @app.delete("/api/courses/<int:cid>")
    def delete_course(cid):
        db.delete_course(conn(), cid)
        return jsonify(ok=True)

    @app.post("/api/upload")
    def upload():
        f = request.files.get("pdf")
        if not f:
            return jsonify(error="Attach a PDF in the 'pdf' field."), 400
        data = f.read()
        if not data.startswith(b"%PDF"):
            return jsonify(error="That file doesn't look like a PDF."), 400
        year = request.form.get("year", type=int)
        extraction = parse_syllabus(data, backend=get_backend(), semester_year=year)
        cid = db.save_extraction(conn(), extraction, source_file=f.filename)
        return jsonify(course_id=cid, extracted=extraction.model_dump())

    # ---- assignments ----
    @app.get("/api/assignments")
    def assignments():
        return jsonify(db.list_assignments(conn()))

    @app.post("/api/assignments")
    def create_assignment():
        j = request.get_json(force=True)
        if not j.get("name") or not j.get("course_id"):
            return jsonify(error="name and course_id are required"), 400
        aid = db.add_assignment(conn(), j["course_id"], j["name"], j.get("due_date"),
                                j.get("due_time"), j.get("type", "other"))
        return jsonify(id=aid), 201

    @app.patch("/api/assignments/<int:aid>")
    def patch_assignment(aid):
        db.update_assignment(conn(), aid, request.get_json(force=True))
        return jsonify(db.get_assignment(conn(), aid))

    @app.delete("/api/assignments/<int:aid>")
    def remove_assignment(aid):
        db.delete_assignment(conn(), aid)
        return jsonify(ok=True)

    @app.post("/api/assignments/<int:aid>/flashcards")
    def flashcards(aid):
        a = db.get_assignment(conn(), aid)
        if not a:
            return jsonify(error="not found"), 404
        notes = (request.get_json(force=True).get("notes") or "").strip()
        if len(notes) < 40:
            return jsonify(error="Paste a bit more of your notes first."), 400
        cards = generate_flashcards(notes, a["name"], a["course"], backend=get_backend())
        return jsonify(cards.model_dump()["cards"])

    # ---- attendance ----
    @app.get("/api/attendance")
    def attendance():
        out = []
        for c in db.list_courses(conn()):
            impact = attendance_impact(c["absences"], c["max_absences"], c["penalty_percent"],
                                       c["attendance_summary"], c["penalty_description"])
            out.append({"course_id": c["id"], "course": db.course_label(c), "missed": c["absences"],
                        "max_absences": c["max_absences"], "policy": c["attendance_summary"], **impact})
        return jsonify(out)

    @app.post("/api/courses/<int:cid>/absences")
    def add_absence(cid):
        db.add_absence(conn(), cid, (request.get_json(silent=True) or {}).get("date"))
        return jsonify(ok=True)

    @app.delete("/api/courses/<int:cid>/absences")
    def remove_absence(cid):
        db.remove_latest_absence(conn(), cid)
        return jsonify(ok=True)

    # ---- settings / calendar / email ----
    @app.get("/api/settings")
    def get_settings():
        return jsonify(db.get_settings(conn()))

    @app.put("/api/settings")
    def put_settings():
        return jsonify(db.set_settings(conn(), request.get_json(force=True)))

    @app.get("/calendar.ics")
    def calendar_ics():
        return Response(build_calendar(conn()), mimetype="text/calendar",
                        headers={"Content-Disposition": "attachment; filename=syllabuddy.ics"})

    @app.get("/api/email/preview")
    def email_preview():
        d = emailer.build_digest(conn(), app_url=os.environ.get("APP_URL", request.host_url.rstrip("/")))
        return jsonify(subject=d["subject"], html=d["html"], text=d["text"])

    @app.post("/api/email/test")
    def email_test():
        try:
            status = emailer.send_weekly(conn(), dry_run=bool(request.args.get("dry")))
        except Exception as e:  # SMTP misconfig etc.
            return jsonify(error=str(e)), 500
        return jsonify(status=status)

    return app


def main():
    app = create_app()
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))


if __name__ == "__main__":
    main()
