"""Compare a student's missed classes with a course's attendance policy."""
from __future__ import annotations


def _fmt(x: float) -> str:
    return f"{x:g}"


def attendance_impact(missed: int, max_allowed: int | None, penalty_percent: float | None,
                      summary: str | None = None, penalty_description: str | None = None) -> dict:
    """Return {level, message, penalty_percent, remaining}.

    level: 'ok' | 'warning' | 'over' | 'unknown'
    """
    if max_allowed is None and penalty_percent is None:
        note = penalty_description or summary
        msg = "No numeric attendance policy found in the syllabus."
        if note:
            msg += f" Syllabus says: {note}"
        return {"level": "unknown", "message": msg, "penalty_percent": None, "remaining": None}

    allowed = max_allowed if max_allowed is not None else 0
    over = max(0, missed - allowed)
    remaining = max(0, allowed - missed) if max_allowed is not None else None
    penalty = round(over * penalty_percent, 2) if penalty_percent is not None else None

    if over > 0:
        msg = f"You've missed {missed}, which is {over} more than the {allowed} allowed."
        if penalty is not None:
            msg += f" Estimated penalty: -{_fmt(penalty)} points off your final grade."
        elif penalty_description:
            msg += f" Penalty: {penalty_description}"
        return {"level": "over", "message": msg, "penalty_percent": penalty, "remaining": 0}

    if max_allowed is not None and remaining <= 1:
        msg = (f"Careful: you've used {missed} of {allowed} allowed absences."
               + (" One more absence will start costing you grade points." if remaining == 1
                  else " Any further absence will cost you grade points."))
        if penalty_percent is not None:
            msg += f" ({_fmt(penalty_percent)} points per absence.)"
        return {"level": "warning", "message": msg, "penalty_percent": 0.0, "remaining": remaining}

    msg = f"{missed} missed" + (f", {remaining} absences left before a penalty." if remaining is not None
                                else ".")
    return {"level": "ok", "message": msg, "penalty_percent": 0.0, "remaining": remaining}
