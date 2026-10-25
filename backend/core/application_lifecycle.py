from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApplicationStatus(str, Enum):
    saved = "saved"
    preparing = "preparing"
    applied = "applied"
    screening = "screening"
    interviewing = "interviewing"
    offer = "offer"
    accepted = "accepted"
    rejected = "rejected"
    withdrawn = "withdrawn"


TRANSITIONS = {
    "saved": ("preparing", "applied", "withdrawn"),
    "preparing": ("saved", "applied", "withdrawn"),
    "applied": ("screening", "interviewing", "offer", "rejected", "withdrawn"),
    "screening": ("interviewing", "offer", "rejected", "withdrawn"),
    "interviewing": ("offer", "rejected", "withdrawn"),
    "offer": ("accepted", "rejected", "withdrawn"),
    "accepted": (),
    "rejected": (),
    "withdrawn": (),
}


def utc_naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def history_entry(previous: str | None, status: str, note: str | None = None) -> dict:
    return {
        "from_status": previous,
        "to_status": status,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }


def transition(application, status: str, note: str | None = None) -> None:
    previous = application.status
    if previous == status:
        return
    if status not in TRANSITIONS.get(previous, ()):
        raise ValueError(f"Cannot move an application from {previous} to {status}.")
    application.status = status
    application.status_history = [
        *(application.status_history or []), history_entry(previous, status, note)
    ]
    if status == "applied" and application.applied_at is None:
        application.applied_at = datetime.utcnow()


class InterviewRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    round: int = Field(ge=1, le=100)
    type: str = Field(min_length=1, max_length=150)
    date: datetime | None = None
    interviewer: str | None = Field(default=None, max_length=200)
    preparation_notes: str | None = Field(default=None, max_length=20000)
    notes: str | None = Field(default=None, max_length=20000)
    outcome: str | None = Field(default=None, max_length=2000)

    _normalize_date = field_validator("date")(utc_naive)


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruiter_name: str | None = Field(default=None, max_length=200)
    recruiter_email: str | None = Field(default=None, max_length=320)
    recruiter_phone: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=20000)
    preparation_notes: str | None = Field(default=None, max_length=20000)
    outcome: str | None = Field(default=None, max_length=10000)
    applied_at: datetime | None = None
    deadline_at: datetime | None = None
    follow_up_at: datetime | None = None
    follow_up_completed_at: datetime | None = None
    interview_rounds: list[InterviewRound] = Field(default_factory=list, max_length=100)

    _normalize_dates = field_validator(
        "applied_at", "deadline_at", "follow_up_at", "follow_up_completed_at"
    )(utc_naive)


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus
    expected_status: ApplicationStatus
    note: str | None = Field(default=None, max_length=2000)
