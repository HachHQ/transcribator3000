from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class CompletionRequest(BaseModel):
    system: str | None = None
    user: str
    model: str | None = None
    temperature: float = 0.2


class CompletionResult(BaseModel):
    text: str
    model: str
    raw: dict[str, Any] = Field(default_factory=dict)


class StructuredRequest(BaseModel):
    system: str | None = None
    user: str
    model: str | None = None
    temperature: float = 0.0


class TaskDraft(BaseModel):
    title: str
    notes: str | None = None
    due: datetime | None = None


class CalendarEventDraft(BaseModel):
    title: str
    description: str | None = None
    start: datetime
    end: datetime


class ClassificationResult(BaseModel):
    is_task: bool = False
    title: str | None = None
    notes: str | None = None
    due: datetime | None = None
    duration_minutes: int | None = None
    create_calendar_event: bool = False
    start: datetime | None = None
    end: datetime | None = None
