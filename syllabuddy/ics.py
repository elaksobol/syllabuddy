"""Build an iCalendar (.ics) file that Google Calendar / Apple Calendar / Outlook can import
or subscribe to. Times are 'floating' (no timezone), so they show up at the same wall-clock
time wherever the student's calendar is set."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import db
from .schemas import DAY_CODES


def _esc(text: str) -> str:
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _fold(line: str) -> str:
    out, chunk = [], ""
    for ch in line:
        if len((chunk + ch).encode("utf-8")) > 74:
            out.append(chunk)
            chunk = " " + ch
        else:
            chunk += ch
    out.append(chunk)
    return "\r\n".join(out)


def _dt(d: str, t: str | None) -> str:
    return d.replace("-", "") + "T" + (t or "00:00").replace(":", "") + "00"


def build_calendar(conn, today: date | None = None) -> str:
    settings = db.get_settings(conn)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Syllabuddy//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:Syllabuddy"]

    # Assignments
    for a in db.list_assignments(conn):
        if not a["due_date"]:
            continue
        title = f"{'[Done] ' if a['completed'] else ''}{a['course']}: {a['name']}"
        lines += ["BEGIN:VEVENT", f"UID:assignment-{a['id']}@syllabuddy", f"DTSTAMP:{stamp}"]
        if a["due_time"]:
            start = datetime.fromisoformat(f"{a['due_date']}T{a['due_time']}")
            end = start + timedelta(minutes=30)
            lines += [f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
                      f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}"]
        else:
            d0 = date.fromisoformat(a["due_date"])
            lines += [f"DTSTART;VALUE=DATE:{d0.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(d0 + timedelta(days=1)).strftime('%Y%m%d')}"]
        lines += [f"SUMMARY:{_esc(title)}", f"DESCRIPTION:{_esc('Type: ' + (a['type'] or 'other'))}",
                  "END:VEVENT"]

    # Weekly class meetings (needs semester dates + meeting info)
    s_start, s_end = settings.get("semester_start"), settings.get("semester_end")
    if s_start and s_end:
        first, last = date.fromisoformat(s_start), date.fromisoformat(s_end)
        for c in db.list_courses(conn):
            if not (c["meeting_days"] and c["meeting_start"] and c["meeting_end"]):
                continue
            wanted = {DAY_CODES.index(d) for d in c["meeting_days"] if d in DAY_CODES}
            d0 = first
            while d0 <= last and d0.weekday() not in wanted:
                d0 += timedelta(days=1)
            if d0 > last:
                continue
            lines += ["BEGIN:VEVENT", f"UID:class-{c['id']}@syllabuddy", f"DTSTAMP:{stamp}",
                      f"DTSTART:{_dt(d0.isoformat(), c['meeting_start'])}",
                      f"DTEND:{_dt(d0.isoformat(), c['meeting_end'])}",
                      f"RRULE:FREQ=WEEKLY;BYDAY={','.join(c['meeting_days'])};"
                      f"UNTIL={last.strftime('%Y%m%d')}T235959",
                      f"SUMMARY:{_esc(db.course_label(c))}"]
            if c["classroom"]:
                lines.append(f"LOCATION:{_esc(c['classroom'])}")
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
