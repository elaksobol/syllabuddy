"""Offline tests: a fake Gemini backend stands in for the real API."""
import io
import json
from datetime import date

import pytest

from syllabuddy import db, emailer
from syllabuddy.app import create_app
from syllabuddy.attendance import attendance_impact
from syllabuddy.gemini_client import GeminiError, parse_syllabus
from syllabuddy.ics import build_calendar
from syllabuddy.schemas import SyllabusExtraction

FAKE = {
    "course": {"course_code": "DATA 440", "course_name": "Automations", "professor_name": "Dr. X",
               "professor_email": "x@uni.edu", "ta_info": "Sam", "classroom": "Hall 101",
               "office_hours": "Tue 2-3pm", "meeting_days": ["Mon", "Wednesday"],
               "meeting_start": "10:00", "meeting_end": "11:15"},
    "attendance": {"summary": "3 free absences, then 2% each", "max_absences_allowed": 3,
                   "penalty_percent_per_absence": 2.0},
    "assignments": [
        {"name": "Essay 1", "due_date": "2026-11-18", "due_time": "23:59", "type": "essay"},
        {"name": "Midterm", "due_date": "2026-11-20", "due_time": None, "type": "exam"},
        {"name": "Mystery", "due_date": "Week 5", "due_time": "late", "type": "homework"},
    ],
}


class FakeBackend:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def generate_json(self, prompt, schema, pdf_bytes=None):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_parse_cleans_bad_values():
    ex = parse_syllabus(b"%PDF", backend=FakeBackend([FAKE]))
    assert ex.course.meeting_days == ["MO", "WE"]
    assert ex.assignments[2].due_date is None and ex.assignments[2].due_time is None


def test_parse_retries_then_succeeds():
    be = FakeBackend([RuntimeError("503"), "not json", FAKE])
    ex = parse_syllabus(b"%PDF", backend=be, sleep=lambda s: None)
    assert be.calls == 3 and ex.course.course_code == "DATA 440"


def test_parse_gives_up():
    be = FakeBackend([RuntimeError("boom")] * 3)
    with pytest.raises(GeminiError):
        parse_syllabus(b"%PDF", backend=be, sleep=lambda s: None)


def test_save_and_reupload_keeps_completed(conn):
    ex = SyllabusExtraction.model_validate(FAKE)
    cid = db.save_extraction(conn, ex)
    aid = [a for a in db.list_assignments(conn) if a["name"] == "Essay 1"][0]["id"]
    db.update_assignment(conn, aid, {"completed": True})
    assert db.save_extraction(conn, ex) == cid  # same course code -> same course
    items = {a["name"]: a for a in db.list_assignments(conn)}
    assert items["Essay 1"]["completed"] == 1 and len(items) == 3


def test_editing_a_date_marks_it_confirmed(conn):
    db.save_extraction(conn, SyllabusExtraction.model_validate(FAKE))
    a = db.list_assignments(conn)[0]
    assert a["confirmed"] == 0
    db.update_assignment(conn, a["id"], {"due_date": "2026-12-01"})
    assert db.get_assignment(conn, a["id"])["confirmed"] == 1


def test_attendance_levels():
    assert attendance_impact(1, 3, 2.0)["level"] == "ok"
    assert attendance_impact(2, 3, 2.0)["level"] == "warning"
    over = attendance_impact(5, 3, 2.0)
    assert over["level"] == "over" and over["penalty_percent"] == 4.0
    assert attendance_impact(2, None, None, "see instructor")["level"] == "unknown"


def test_ics_has_events_and_recurrence(conn):
    db.save_extraction(conn, SyllabusExtraction.model_validate(FAKE))
    db.set_settings(conn, {"semester_start": "2026-08-31", "semester_end": "2026-12-11"})
    ics = build_calendar(conn)
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == 3  # 2 dated + 1 class
    assert "DTSTART:20261118T235900" in ics
    assert "DTSTART;VALUE=DATE:20261120" in ics
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261211T235959" in ics
    assert "DTSTART:20260831T100000" in ics  # first Monday on/after semester start


def test_digest_contents_and_mute(conn):
    db.save_extraction(conn, SyllabusExtraction.model_validate(FAKE))
    d = emailer.build_digest(conn, today=date(2026, 11, 16))
    assert len(d["upcoming"]) == 2 and len(d["prep"]) == 1
    assert "Essay 1" in d["text"] and "flashcards" in d["text"] and "Weekly email page" in d["text"]
    db.set_settings(conn, {"email": "me@x.edu", "emails_enabled": "0"})
    assert emailer.send_weekly(conn).startswith("skipped")
    db.set_settings(conn, {"emails_enabled": "1"})
    assert "DRY RUN" in emailer.send_weekly(conn, dry_run=True, today=date(2026, 11, 16))


def test_web_flow(tmp_path):
    app = create_app(str(tmp_path / "w.db"), backend=FakeBackend([
        FAKE, {"cards": [{"question": "Q?", "answer": "A."}]}]))
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.post("/api/upload", data={"pdf": (io.BytesIO(b"nope"), "a.pdf")}).status_code == 400
    r = c.post("/api/upload", data={"pdf": (io.BytesIO(b"%PDF-1.4 x"), "s.pdf"), "year": "2026"})
    assert r.status_code == 200
    items = c.get("/api/assignments").get_json()
    assert len(items) == 3
    assert c.patch(f"/api/assignments/{items[0]['id']}", json={"completed": True}).get_json()["completed"] == 1
    c.post(f"/api/courses/{r.get_json()['course_id']}/absences")
    att = c.get("/api/attendance").get_json()[0]
    assert att["missed"] == 1 and att["level"] == "ok"
    exam = [a for a in items if a["type"] == "exam"][0]
    cards = c.post(f"/api/assignments/{exam['id']}/flashcards", json={"notes": "x" * 60}).get_json()
    assert cards == [{"question": "Q?", "answer": "A."}]
    assert c.get("/calendar.ics").mimetype == "text/calendar"
    prev = c.get("/api/email/preview").get_json()
    assert "Syllabuddy" in prev["subject"] and "<h2>" in prev["html"]
