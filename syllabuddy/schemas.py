"""Pydantic models describing what we ask Gemini to extract from a syllabus.

These are used twice:
  1. as the `response_schema` sent to Gemini (so it returns JSON in this shape)
  2. to validate / clean what comes back (bad dates become None, not crashes)
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

AssignmentType = Literal[
    "discussion", "essay", "exam", "quiz", "project", "homework", "reading", "other"
]

DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
_DAY_LOOKUP = {
    "mo": "MO", "m": "MO",
    "tu": "TU", "t": "TU",
    "we": "WE", "w": "WE",
    "th": "TH", "r": "TH",
    "fr": "FR", "f": "FR",
    "sa": "SA", "s": "SA",
    "su": "SU", "u": "SU",
}


def _clean_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def _clean_time(value):
    if not value:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(value))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


class Assignment(BaseModel):
    name: str = Field(description="Short title, e.g. 'Midterm Exam' or 'Essay 2'")
    due_date: Optional[str] = Field(
        default=None, description="ISO date YYYY-MM-DD, or null if the syllabus gives no exact date"
    )
    due_time: Optional[str] = Field(
        default=None, description="24-hour HH:MM, or null if no time is given"
    )
    type: AssignmentType = "other"

    @field_validator("due_date", mode="before")
    @classmethod
    def _v_date(cls, v):
        return _clean_date(v)

    @field_validator("due_time", mode="before")
    @classmethod
    def _v_time(cls, v):
        return _clean_time(v)


class CourseInfo(BaseModel):
    course_code: Optional[str] = Field(default=None, description="e.g. 'DATA 440'")
    course_name: Optional[str] = None
    professor_name: Optional[str] = None
    professor_email: Optional[str] = None
    ta_info: Optional[str] = Field(default=None, description="TA names / emails, free text")
    classroom: Optional[str] = Field(default=None, description="Building and room")
    office_hours: Optional[str] = Field(default=None, description="Times and location")
    meeting_days: list[str] = Field(
        default_factory=list,
        description="Weekly meeting days using codes MO, TU, WE, TH, FR, SA, SU",
    )
    meeting_start: Optional[str] = Field(default=None, description="24-hour HH:MM")
    meeting_end: Optional[str] = Field(default=None, description="24-hour HH:MM")

    @field_validator("meeting_days", mode="before")
    @classmethod
    def _v_days(cls, v):
        out = []
        for item in v or []:
            key = str(item).strip().lower()
            code = _DAY_LOOKUP.get(key[:2]) or _DAY_LOOKUP.get(key[:1])
            if code and code not in out:
                out.append(code)
        return out

    @field_validator("meeting_start", "meeting_end", mode="before")
    @classmethod
    def _v_times(cls, v):
        return _clean_time(v)


class AttendancePolicy(BaseModel):
    summary: Optional[str] = Field(
        default=None, description="One or two sentences restating the attendance policy"
    )
    max_absences_allowed: Optional[int] = Field(
        default=None, description="Absences allowed before any penalty; null if unstated"
    )
    penalty_percent_per_absence: Optional[float] = Field(
        default=None,
        description="Percentage points of the final grade lost per absence beyond the allowance; null if unstated",
    )
    penalty_description: Optional[str] = Field(
        default=None, description="Any penalty that is not a simple per-absence percentage"
    )


class SyllabusExtraction(BaseModel):
    course: CourseInfo
    attendance: AttendancePolicy
    assignments: list[Assignment]


class Flashcard(BaseModel):
    question: str
    answer: str


class FlashcardSet(BaseModel):
    cards: list[Flashcard]
