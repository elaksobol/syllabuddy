"""The weekly Sunday-morning email: build it, and send it over SMTP."""
from __future__ import annotations

import os
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage
from html import escape

from . import db

PREP_TYPES = {"exam", "quiz"}


def _pretty(a: dict) -> str:
    d = date.fromisoformat(a["due_date"]).strftime("%a %b %d").replace(" 0", " ")
    return f"{d} {a['due_time']}" if a["due_time"] else d


def build_digest(conn, today: date | None = None, app_url: str = "http://localhost:5000") -> dict:
    """Return {'subject', 'text', 'html', 'upcoming', 'overdue', 'prep'}."""
    today = today or date.today()
    end = today + timedelta(days=7)
    open_items = [a for a in db.list_assignments(conn) if a["due_date"] and not a["completed"]]
    upcoming = [a for a in open_items if today <= date.fromisoformat(a["due_date"]) <= end]
    overdue = [a for a in open_items if date.fromisoformat(a["due_date"]) < today]
    prep = [a for a in upcoming if a["type"] in PREP_TYPES]
    unreviewed = [a for a in upcoming if not a["confirmed"]]

    subject = f"Syllabuddy: {len(upcoming)} thing{'s' if len(upcoming) != 1 else ''} due this week"

    def line(a):
        return f"{_pretty(a)}  -  {a['course']}: {a['name']} ({a['type']})"

    t = [f"Good morning! Here's your week ({today:%b %d} - {end:%b %d}).", ""]
    t.append("DUE THIS WEEK")
    t += [f"  [ ] {line(a)}" for a in upcoming] or ["  Nothing due. Enjoy the breathing room."]
    if overdue:
        t += ["", "STILL NOT CHECKED OFF (past due)"] + [f"  [ ] {line(a)}" for a in overdue]
    t += ["", "DID ANY DUE DATES CHANGE?",
          "  Professors update deadlines after the syllabus is posted. If anything above is",
          f"  wrong, fix it in your tracker: {app_url}/"]
    if unreviewed:
        t.append(f"  ({len(unreviewed)} of these came straight from your syllabus and haven't been reviewed yet.)")
    if prep:
        t += ["", "STUDYING FOR AN EXAM OR QUIZ?"]
        t += [f"  - {a['course']}: {a['name']} ({_pretty(a)})" for a in prep]
        t.append(f"  Paste your class notes into Syllabuddy to get flashcards: {app_url}/")
    t += ["", "WANT FEWER EMAILS?",
          f"  You can silence these on the Weekly email page: {app_url}/#weekly"]
    text = "\n".join(t)

    def li(a, cls=""):
        return (f"<li{cls}><b>{escape(_pretty(a))}</b> &mdash; {escape(a['course'])}: "
                f"{escape(a['name'])} <i>({escape(a['type'])})</i></li>")

    h = [f"<h2>Your week: {today:%b %d} &ndash; {end:%b %d}</h2>", "<h3>Due this week</h3>"]
    h.append("<ul>" + "".join(li(a) for a in upcoming) + "</ul>" if upcoming
             else "<p>Nothing due. Enjoy the breathing room.</p>")
    if overdue:
        h.append("<h3>Still not checked off (past due)</h3><ul>" + "".join(li(a) for a in overdue) + "</ul>")
    h.append(f"<h3>Did any due dates change?</h3><p>If anything above is wrong, "
             f"<a href='{escape(app_url)}/'>update your tracker</a>.</p>")
    if prep:
        h.append("<h3>Studying for an exam or quiz?</h3><ul>"
                 + "".join(f"<li>{escape(a['course'])}: {escape(a['name'])} ({escape(_pretty(a))})</li>" for a in prep)
                 + f"</ul><p><a href='{escape(app_url)}/'>Paste your notes</a> to get flashcards.</p>")
    h.append(f"<h3>Want fewer emails?</h3><p>Silence these on the "
             f"<a href='{escape(app_url)}/#weekly'>Weekly email page</a>.</p>")
    return {"subject": subject, "text": text, "html": "\n".join(h),
            "upcoming": upcoming, "overdue": overdue, "prep": prep}


def send_email(to: str, subject: str, text: str, html: str | None = None):
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP_HOST is not set; see .env.example")
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", user or "syllabuddy@localhost")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def send_weekly(conn, dry_run: bool = False, today: date | None = None) -> str:
    """Send the digest if the student has an address and hasn't muted emails.
    Returns a short status string."""
    s = db.get_settings(conn)
    if s["emails_enabled"] != "1":
        return "skipped: emails are muted in Settings"
    if not s["email"]:
        return "skipped: no email address saved in Settings"
    d = build_digest(conn, today=today, app_url=os.environ.get("APP_URL", "http://localhost:5000"))
    if dry_run:
        return f"DRY RUN to {s['email']}\nSubject: {d['subject']}\n\n{d['text']}"
    send_email(s["email"], d["subject"], d["text"], d["html"])
    return f"sent to {s['email']}"
