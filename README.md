# Syllabuddy

Upload your course syllabi (PDF). Gemini extracts the assignments, dates, attendance policy and
professor/TA/office-hour info, and Syllabuddy turns that into:

- **Assignment tracker** – due dates, times, class, type, a "completed" checkbox, and a review step for
  anything Gemini extracted (yellow rows) so a wrong date doesn't slip through
- **Calendar tab** – month view, `.ics` export for Google Calendar, optional Google Calendar embed
- **Attendance tracker** – a counter per course, compared against the syllabus's attendance policy
- **Course info pop-ups** – hover a course name to see professor, email, TA, room, office hours
- **Weekly Sunday email** – what's due this week, a "did any dates change?" check, a flashcards prompt for
  exams/quizzes that week, and a way to mute it
- **Flashcards** – paste class notes for an exam/quiz and Gemini writes study cards

## Setup

```bash
uv sync            # or: pip install -e ".[dev]"
cp .env.example .env   # add GEMINI_API_KEY, GEMINI_MODEL, and SMTP settings
python -m syllabuddy.app           # http://localhost:5000
```

## Try the parser alone (like the class starter script)

```bash
python scripts/parse_cli.py docs/test_syllabi/*.pdf --year 2026 --no-save
```

## Weekly email

```bash
python scripts/send_weekly.py --dry-run     # print it
python scripts/send_weekly.py               # send it
```
Schedule it for Sunday morning with cron: `0 8 * * 0 cd /path/to/syllabuddy && python scripts/send_weekly.py`
(the Weekly email page also has a "Send test email" button). The student's address and the on/off switch live on that page.

## Layout

| File | Role |
|---|---|
| `syllabuddy/schemas.py` | Pydantic models = Gemini's response schema + validation/cleanup |
| `syllabuddy/gemini_client.py` | Gemini calls (syllabus parsing, flashcards), retries with backoff |
| `syllabuddy/db.py` | SQLite storage |
| `syllabuddy/attendance.py` | Missed classes vs. policy |
| `syllabuddy/ics.py` | Calendar export |
| `syllabuddy/emailer.py` | Weekly digest + SMTP |
| `syllabuddy/app.py` | Flask API |
| `syllabuddy/templates/index.html` | Crayon-style single-page front end (Overview, Assignments, Calendar, My classes, Attendance, Weekly email). Colors/fonts are CSS variables at the top of the file. |
| `tests/` | Offline tests with a fake Gemini backend (`pytest`) |

## Known limits

- Single user per database (no logins). For multiple students you'd add accounts and a `user_id` column.
- Class meeting times use "floating" times (no timezone), so they land at the same clock time in any calendar.
- Syllabus dates that say only "Week 5" are left blank for the student to fill in.
- The weekly email needs something to run the script on a schedule while your computer is on.
