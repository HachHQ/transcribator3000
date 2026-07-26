from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, TaskLink, User
from app.domain.enums import NoteStatus, TaskLinkKind
from app.domain.models import CalendarEventDraft, ClassificationResult, StructuredRequest, TaskDraft
from app.integrations.google.calendar import GoogleCalendarClient
from app.integrations.google.tasks import GoogleTasksClient
from app.integrations.llm.base import LLMProvider
from app.integrations.storage.note_cache import NoteCache
from app.pipelines.status import transition_note
from app.services.templates import get_system_prompt

CLASSIFY_SYSTEM = (
    "You classify personal notes. Decide if the note is an actionable task or calendar event. "
    "Resolve relative dates (сегодня/завтра/в понедельник) using the provided current datetime. "
    "Always use full 4-digit ISO years (e.g. 2026-07-26T15:00:00+07:00). "
    "Never invent years like 2023 or 0023 when the note says today/tomorrow. "
    "If unsure, is_task=false."
)

_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


@dataclass
class ProposeResult:
    classification: ClassificationResult
    awaiting_confirmation: bool
    needs_google: bool


def is_actionable(result: ClassificationResult) -> bool:
    return bool(
        (result.is_task and result.title)
        or (result.create_calendar_event and result.title and (result.start or result.due))
    )


def normalize_classification_datetimes(
    result: ClassificationResult,
    now: datetime,
) -> ClassificationResult:
    """Fix LLM date hallucinations (wrong century/year) relative to `now`."""

    def _fix(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None and now.tzinfo is not None:
            dt = dt.replace(tzinfo=now.tzinfo)
        elif dt.tzinfo is not None and now.tzinfo is not None:
            dt = dt.astimezone(now.tzinfo)

        # Absurd years: 23, 0023, 1923, 2023 while now is 2026, etc.
        if abs(dt.year - now.year) >= 1:
            try:
                dt = dt.replace(year=now.year)
            except ValueError:
                # Feb 29 edge case
                dt = dt.replace(year=now.year, day=28)

        # Still wildly far → keep clock, pin to today
        if abs((dt - now).days) > 366:
            dt = now.replace(
                hour=dt.hour,
                minute=dt.minute,
                second=dt.second,
                microsecond=0,
            )
        return dt

    data = result.model_dump()
    data["due"] = _fix(result.due)
    data["start"] = _fix(result.start)
    data["end"] = _fix(result.end)
    return ClassificationResult.model_validate(data)


def format_proposal_text(note_id: uuid.UUID, result: ClassificationResult) -> str:
    lines = [f"Заметка `{note_id}` — предложение:"]
    if result.is_task and result.title:
        lines.append(f"• Задача: {result.title}")
        if result.due:
            lines.append(f"  срок: {result.due.isoformat()}")
        if result.notes:
            lines.append(f"  заметка: {result.notes[:200]}")
    if result.create_calendar_event and result.title:
        lines.append(f"• Событие: {result.title}")
        if result.start:
            lines.append(f"  начало: {result.start.isoformat()}")
        end = result.end
        if not end and result.start and result.duration_minutes:
            end = result.start + timedelta(minutes=result.duration_minutes)
        if end:
            lines.append(f"  конец: {end.isoformat()}")
    if len(lines) == 1:
        lines.append("• Не похоже на задачу или событие.")
    lines.append("\nПодтвердить создание в Google?")
    return "\n".join(lines)


def _build_classify_user_message(body: str, now: datetime) -> str:
    weekday = _WEEKDAYS_RU[now.weekday()]
    return (
        f"Current local datetime: {now.isoformat()} ({weekday}).\n"
        f"Timezone: {now.tzinfo}.\n"
        "Interpret relative time words in the note against this datetime. "
        "Output all datetimes with the correct 4-digit year.\n\n"
        f"Classify this note:\n\n{body}"
    )


async def propose_classification(
    session: AsyncSession,
    cache: NoteCache,
    llm: LLMProvider,
    note_id: uuid.UUID,
    *,
    google_connected: bool,
    dropbox_body_fallback: str | None = None,
) -> ProposeResult:
    note = await session.get(Note, note_id)
    if note is None:
        raise RuntimeError(f"Note {note_id} not found")

    body = await cache.get_body(note_id) or dropbox_body_fallback
    if not body:
        raise RuntimeError("Note body missing from cache for classification")

    # Ensure we are at CLASSIFIED before branching to await/done
    current = NoteStatus(note.status)
    if current == NoteStatus.POSTPROCESSING:
        transition_note(note, NoteStatus.CLASSIFIED)
    elif current in {NoteStatus.UPLOADED, NoteStatus.FAILED}:
        note.status = NoteStatus.CLASSIFIED.value
        note.error_message = None
    elif current != NoteStatus.CLASSIFIED:
        raise RuntimeError(f"Cannot classify note in status {note.status}")

    user = await session.get(User, note.user_id)
    tz_name = user.timezone if user and user.timezone else "Asia/Bangkok"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Bangkok")
    now = datetime.now(tz)

    system_prompt = await get_system_prompt(session, note.user_id, "classify")
    result = await llm.structured(
        StructuredRequest(
            system=system_prompt or CLASSIFY_SYSTEM,
            user=_build_classify_user_message(body, now),
        ),
        ClassificationResult,
    )
    result = normalize_classification_datetimes(result, now)

    actionable = is_actionable(result)
    needs_google = actionable and not google_connected
    awaiting = actionable and google_connected

    meta = {**(note.meta or {}), "classification": result.model_dump(mode="json")}
    if awaiting:
        transition_note(note, NoteStatus.AWAITING_CONFIRMATION)
        meta["proposal_notified"] = False
    else:
        transition_note(note, NoteStatus.DONE)
        meta["proposal_notified"] = False
        if needs_google:
            meta["needs_google"] = True
    note.meta = meta
    await session.commit()
    return ProposeResult(
        classification=result,
        awaiting_confirmation=awaiting,
        needs_google=needs_google,
    )


def _load_proposal(note: Note) -> ClassificationResult:
    raw = (note.meta or {}).get("classification")
    if not raw:
        raise RuntimeError("No classification proposal in note meta")
    return ClassificationResult.model_validate(raw)


async def apply_classification(
    session: AsyncSession,
    calendar: GoogleCalendarClient,
    tasks: GoogleTasksClient,
    note_id: uuid.UUID,
) -> ClassificationResult:
    note = await session.get(Note, note_id)
    if note is None:
        raise RuntimeError(f"Note {note_id} not found")
    if note.status != NoteStatus.AWAITING_CONFIRMATION.value:
        raise RuntimeError(f"Note is not awaiting confirmation (status={note.status})")

    result = _load_proposal(note)
    body_notes = result.notes

    if result.is_task and result.title:
        created = tasks.create_task(
            TaskDraft(title=result.title, notes=body_notes, due=result.due)
        )
        session.add(
            TaskLink(
                note_id=note.id,
                user_id=note.user_id,
                kind=TaskLinkKind.GOOGLE_TASK.value,
                external_id=created.get("id", ""),
                external_url=created.get("selfLink"),
                title=result.title,
                payload=created,
            )
        )

    if result.create_calendar_event and result.title:
        start = result.start or result.due
        end = result.end
        if start and not end and result.duration_minutes:
            end = start + timedelta(minutes=result.duration_minutes)
        if start and not end:
            end = start + timedelta(minutes=30)
        if start and end:
            created = calendar.create_event(
                CalendarEventDraft(
                    title=result.title,
                    description=body_notes,
                    start=start,
                    end=end,
                )
            )
            session.add(
                TaskLink(
                    note_id=note.id,
                    user_id=note.user_id,
                    kind=TaskLinkKind.GOOGLE_EVENT.value,
                    external_id=created.get("id", ""),
                    external_url=created.get("htmlLink"),
                    title=result.title,
                    payload=created,
                )
            )

    transition_note(note, NoteStatus.DONE)
    note.meta = {**(note.meta or {}), "classification_applied": True}
    await session.commit()
    return result


async def skip_classification(session: AsyncSession, note_id: uuid.UUID) -> None:
    note = await session.get(Note, note_id)
    if note is None:
        raise RuntimeError(f"Note {note_id} not found")
    if note.status != NoteStatus.AWAITING_CONFIRMATION.value:
        raise RuntimeError(f"Note is not awaiting confirmation (status={note.status})")
    transition_note(note, NoteStatus.DONE)
    note.meta = {**(note.meta or {}), "classification_skipped": True}
    await session.commit()


# Legacy helper: propose only (no auto-apply). Prefer propose_classification.
async def classify_note(
    session: AsyncSession,
    cache: NoteCache,
    llm: LLMProvider,
    calendar: GoogleCalendarClient | None,
    tasks: GoogleTasksClient | None,
    note_id: uuid.UUID,
    *,
    dropbox_body_fallback: str | None = None,
) -> ClassificationResult:
    google_connected = calendar is not None and tasks is not None
    proposed = await propose_classification(
        session,
        cache,
        llm,
        note_id,
        google_connected=google_connected,
        dropbox_body_fallback=dropbox_body_fallback,
    )
    return proposed.classification
