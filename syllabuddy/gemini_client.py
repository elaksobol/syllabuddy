"""Everything that talks to Gemini lives here.

`GeminiBackend` is a thin wrapper around the google-genai SDK. The SDK is only
imported when a request is actually made, and parse/flashcard functions accept
any object with a `generate_json(prompt, schema, pdf_bytes=None) -> str`
method, so tests can pass a fake backend and never hit the network.
"""
from __future__ import annotations

import os
import time
from datetime import date

from pydantic import ValidationError

from .schemas import FlashcardSet, SyllabusExtraction

DEFAULT_MODEL = "gemini-2.5-flash"  # override with GEMINI_MODEL in .env


class GeminiError(RuntimeError):
    pass


class GeminiBackend:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._client = None

    def generate_json(self, prompt: str, schema, pdf_bytes: bytes | None = None) -> str:
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY is not set (put it in your .env file).")
        from google import genai  # lazy import
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        contents = []
        if pdf_bytes:
            contents.append(types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"))
        contents.append(prompt)
        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.1,
            ),
        )
        return response.text

    def redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text


def _generate_validated(backend, prompt, schema, pdf_bytes=None, max_attempts=3, sleep=time.sleep):
    """Call Gemini, validate the JSON against `schema`, retry with backoff."""
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = backend.generate_json(prompt, schema, pdf_bytes=pdf_bytes)
            return schema.model_validate_json(raw)
        except GeminiError:
            raise  # config problems won't fix themselves
        except (ValidationError, ValueError) as e:
            last = f"Gemini returned invalid JSON: {e}"
        except Exception as e:  # network, rate limit, 5xx ...
            msg = str(e)
            redact = getattr(backend, "redact", None)
            last = redact(msg) if redact else msg
        if attempt < max_attempts:
            sleep(2 ** attempt)  # 2s, 4s, ...
    raise GeminiError(f"Gemini failed after {max_attempts} attempts: {last}")


SYLLABUS_PROMPT = """You are extracting structured data from a college course syllabus (attached PDF).

Today's date is {today}. The academic semester is in the year {year}; when the syllabus
gives a date without a year (e.g. "Oct 14"), assume {year}.

Return JSON matching the schema. Rules:
- assignments: EVERY graded item with a specific date or deadline (homework, discussion posts,
  essays, projects, quizzes, midterms, finals). Do not include ungraded readings unless they have a deadline.
  Use type "exam" for midterms/finals and "quiz" for quizzes.
- due_date must be ISO format YYYY-MM-DD. If the syllabus only says something like "Week 5" or
  gives no exact date, use null. Never guess a date.
- due_time is 24-hour HH:MM, or null if not stated (do not assume 23:59).
- meeting_days uses the codes MO, TU, WE, TH, FR, SA, SU.
- attendance: restate the policy briefly. Fill max_absences_allowed and penalty_percent_per_absence
  only if the syllabus states numbers; otherwise null and describe in penalty_description.
- Use null for anything not in the syllabus. Do not invent names, emails, or rooms.
"""

FLASHCARD_PROMPT = """You are helping a college student study for "{title}" in {course}.
Below are the student's own class notes. Write {n} flashcards that test the most important
concepts, definitions and relationships in THESE notes only. Questions should be specific and
answers concise (1-3 sentences).

NOTES:
{notes}
"""


def parse_syllabus(pdf_bytes: bytes, backend=None, semester_year: int | None = None,
                   max_attempts: int = 3, sleep=time.sleep) -> SyllabusExtraction:
    backend = backend or GeminiBackend()
    today = date.today()
    prompt = SYLLABUS_PROMPT.format(today=today.isoformat(), year=semester_year or today.year)
    return _generate_validated(backend, prompt, SyllabusExtraction, pdf_bytes=pdf_bytes,
                               max_attempts=max_attempts, sleep=sleep)


def generate_flashcards(notes: str, title: str, course: str, backend=None, n: int = 12,
                        max_attempts: int = 3, sleep=time.sleep) -> FlashcardSet:
    backend = backend or GeminiBackend()
    prompt = FLASHCARD_PROMPT.format(title=title, course=course, n=n, notes=notes[:30000])
    return _generate_validated(backend, prompt, FlashcardSet,
                               max_attempts=max_attempts, sleep=sleep)
