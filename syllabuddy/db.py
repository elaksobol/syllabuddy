"""SQLite storage for courses, assignments, absences and settings."""
from __future__ import annotations

import os
import sqlite3
from datetime import date

from .schemas import SyllabusExtraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT, name TEXT,
    professor_name TEXT, professor_email TEXT, ta_info TEXT,
    classroom TEXT, office_hours TEXT,
    meeting_days TEXT DEFAULT '', meeting_start TEXT, meeting_end TEXT,
    attendance_summary TEXT, max_absences INTEGER,
    penalty_percent REAL, penalty_description TEXT,
    source_file TEXT
);
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    due_date TEXT, due_time TEXT,
    type TEXT DEFAULT 'other',
    completed INTEGER DEFAULT 0,
    confirmed INTEGER DEFAULT 0   -- 0 = straight from Gemini, student hasn't reviewed it
);
CREATE TABLE IF NOT EXISTS absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    missed_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_SETTINGS = {
    "email": "",
    "emails_enabled": "1",
    "semester_start": "",
    "semester_end": "",
    "gcal_embed_url": "",
}

ASSIGNMENT_EDITABLE = {"name", "due_date", "due_time", "type", "completed", "confirmed"}


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or os.environ.get("SYLLABUDDY_DB", "syllabuddy.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- settings ----------
def get_settings(conn) -> dict:
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return out


def set_settings(conn, updates: dict) -> dict:
    for k, v in updates.items():
        if k in DEFAULT_SETTINGS:
            conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))
    conn.commit()
    return get_settings(conn)


# ---------- courses ----------
def save_extraction(conn, ex: SyllabusExtraction, source_file: str | None = None) -> int:
    """Store a parsed syllabus. Re-uploading the same course code updates it and keeps
    'completed' checkmarks for assignments whose names match."""
    c, a = ex.course, ex.attendance
    existing = None
    if c.course_code:
        existing = conn.execute("SELECT id FROM courses WHERE code = ?", (c.course_code,)).fetchone()
    values = (c.course_code, c.course_name, c.professor_name, c.professor_email, c.ta_info,
              c.classroom, c.office_hours, ",".join(c.meeting_days), c.meeting_start, c.meeting_end,
              a.summary, a.max_absences_allowed, a.penalty_percent_per_absence,
              a.penalty_description, source_file)
    done = {}
    if existing:
        course_id = existing["id"]
        conn.execute("""UPDATE courses SET code=?, name=?, professor_name=?, professor_email=?,
            ta_info=?, classroom=?, office_hours=?, meeting_days=?, meeting_start=?, meeting_end=?,
            attendance_summary=?, max_absences=?, penalty_percent=?, penalty_description=?,
            source_file=? WHERE id=?""", values + (course_id,))
        done = {r["name"].lower(): r["completed"] for r in
                conn.execute("SELECT name, completed FROM assignments WHERE course_id=?", (course_id,))}
        conn.execute("DELETE FROM assignments WHERE course_id=?", (course_id,))
    else:
        cur = conn.execute("""INSERT INTO courses (code, name, professor_name, professor_email,
            ta_info, classroom, office_hours, meeting_days, meeting_start, meeting_end,
            attendance_summary, max_absences, penalty_percent, penalty_description, source_file)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
        course_id = cur.lastrowid
    for item in ex.assignments:
        conn.execute("INSERT INTO assignments (course_id, name, due_date, due_time, type, completed) "
                     "VALUES (?,?,?,?,?,?)",
                     (course_id, item.name, item.due_date, item.due_time, item.type,
                      done.get(item.name.lower(), 0)))
    conn.commit()
    return course_id


def list_courses(conn) -> list[dict]:
    out = rows(conn.execute("SELECT * FROM courses ORDER BY code, name"))
    for c in out:
        c["meeting_days"] = [d for d in (c["meeting_days"] or "").split(",") if d]
        c["absences"] = conn.execute("SELECT COUNT(*) FROM absences WHERE course_id=?", (c["id"],)).fetchone()[0]
    return out


def get_course(conn, course_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    return dict(r) if r else None


def delete_course(conn, course_id: int):
    conn.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()


def course_label(course: dict) -> str:
    return course.get("code") or course.get("name") or f"Course {course['id']}"


# ---------- assignments ----------
def list_assignments(conn) -> list[dict]:
    return rows(conn.execute("""
        SELECT a.*, COALESCE(c.code, c.name, 'Course ' || c.id) AS course
        FROM assignments a JOIN courses c ON c.id = a.course_id
        ORDER BY a.due_date IS NULL, a.due_date, a.due_time IS NULL, a.due_time, a.name"""))


def get_assignment(conn, assignment_id: int) -> dict | None:
    r = conn.execute("""SELECT a.*, COALESCE(c.code, c.name) AS course FROM assignments a
                        JOIN courses c ON c.id = a.course_id WHERE a.id=?""", (assignment_id,)).fetchone()
    return dict(r) if r else None


def add_assignment(conn, course_id, name, due_date=None, due_time=None, type_="other") -> int:
    cur = conn.execute("INSERT INTO assignments (course_id, name, due_date, due_time, type, confirmed) "
                       "VALUES (?,?,?,?,?,1)", (course_id, name, due_date or None, due_time or None, type_))
    conn.commit()
    return cur.lastrowid


def update_assignment(conn, assignment_id: int, fields: dict):
    fields = {k: v for k, v in fields.items() if k in ASSIGNMENT_EDITABLE}
    for k in ("due_date", "due_time"):
        if k in fields and not fields[k]:
            fields[k] = None
    for k in ("completed", "confirmed"):
        if k in fields:
            fields[k] = 1 if fields[k] else 0
    if not fields:
        return
    # Editing a date by hand counts as the student having reviewed it.
    if "confirmed" not in fields and ("due_date" in fields or "due_time" in fields):
        fields["confirmed"] = 1
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE assignments SET {sets} WHERE id=?", (*fields.values(), assignment_id))
    conn.commit()


def delete_assignment(conn, assignment_id: int):
    conn.execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
    conn.commit()


# ---------- absences ----------
def add_absence(conn, course_id: int, missed_on: str | None = None):
    conn.execute("INSERT INTO absences (course_id, missed_on) VALUES (?,?)",
                 (course_id, missed_on or date.today().isoformat()))
    conn.commit()


def remove_latest_absence(conn, course_id: int):
    conn.execute("DELETE FROM absences WHERE id = (SELECT id FROM absences WHERE course_id=? "
                 "ORDER BY id DESC LIMIT 1)", (course_id,))
    conn.commit()
