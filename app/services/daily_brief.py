from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.domain.models import CompletionRequest
from app.integrations.google.calendar import GoogleCalendarClient
from app.integrations.google.tasks import GoogleTasksClient
from app.integrations.llm.base import LLMProvider


@dataclass
class TimeInterval:
    start: datetime
    end: datetime
    title: str = ""


@dataclass
class DailyBriefResult:
    conflicts: list[tuple[TimeInterval, TimeInterval]]
    free_windows: list[TimeInterval]
    summary_text: str
    open_tasks: list[dict]
    skipped_old_tasks: int = 0


def _parse_event_bounds(item: dict, tz: ZoneInfo) -> TimeInterval | None:
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})
    start_s = start_raw.get("dateTime") or start_raw.get("date")
    end_s = end_raw.get("dateTime") or end_raw.get("date")
    if not start_s or not end_s:
        return None
    start = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_s.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return TimeInterval(start=start, end=end, title=item.get("summary") or "(no title)")


def find_conflicts(events: list[TimeInterval]) -> list[tuple[TimeInterval, TimeInterval]]:
    ordered = sorted(events, key=lambda e: e.start)
    conflicts: list[tuple[TimeInterval, TimeInterval]] = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            if b.start < a.end:
                conflicts.append((a, b))
            else:
                break
    return conflicts


def free_windows(
    busy: list[TimeInterval],
    day_start: datetime,
    day_end: datetime,
    min_minutes: int = 30,
) -> list[TimeInterval]:
    windows: list[TimeInterval] = []
    cursor = day_start
    for block in sorted(busy, key=lambda b: b.start):
        if block.start > cursor:
            gap = block.start - cursor
            if gap >= timedelta(minutes=min_minutes):
                windows.append(TimeInterval(start=cursor, end=block.start, title="free"))
        cursor = max(cursor, block.end)
    if day_end > cursor and (day_end - cursor) >= timedelta(minutes=min_minutes):
        windows.append(TimeInterval(start=cursor, end=day_end, title="free"))
    return windows


def _task_reference_time(task: dict) -> datetime | None:
    """Prefer due date; fall back to last updated (Google Tasks RFC3339)."""
    for key in ("due", "updated"):
        raw = task.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def filter_tasks_by_max_age(
    tasks: list[dict],
    *,
    now: datetime,
    max_age_days: int,
) -> tuple[list[dict], int]:
    """Drop tasks older than max_age_days. max_age_days<=0 disables filtering."""
    if max_age_days <= 0:
        return tasks, 0
    cutoff = now.astimezone(timezone.utc) - timedelta(days=max_age_days)
    kept: list[dict] = []
    skipped = 0
    for task in tasks:
        ref = _task_reference_time(task)
        if ref is None:
            kept.append(task)
            continue
        if ref.astimezone(timezone.utc) < cutoff:
            skipped += 1
            continue
        kept.append(task)
    return kept, skipped


async def build_daily_brief(
    *,
    calendar: GoogleCalendarClient,
    tasks: GoogleTasksClient,
    llm: LLMProvider,
    timezone_name: str,
    system_prompt: str | None = None,
    workday_start_hour: int = 9,
    workday_end_hour: int = 19,
    task_max_age_days: int = 7,
) -> DailyBriefResult:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    day_start = now.replace(hour=workday_start_hour, minute=0, second=0, microsecond=0)
    day_end = now.replace(hour=workday_end_hour, minute=0, second=0, microsecond=0)
    if now > day_end:
        day_start = day_start + timedelta(days=1)
        day_end = day_end + timedelta(days=1)
    if now > day_start:
        day_start = now

    events_raw = calendar.list_events(time_min=day_start, time_max=day_end)
    events = [e for e in (_parse_event_bounds(i, tz) for i in events_raw) if e is not None]
    conflicts = find_conflicts(events)
    free = free_windows(events, day_start, day_end)
    raw_tasks = tasks.list_open_tasks()
    open_tasks, skipped_old = filter_tasks_by_max_age(
        raw_tasks,
        now=now,
        max_age_days=task_max_age_days,
    )

    conflict_lines = [
        f"- CONFLICT: {a.title} ({a.start.isoformat()}) overlaps {b.title} ({b.start.isoformat()})"
        for a, b in conflicts
    ] or ["- No calendar conflicts detected."]
    free_lines = [
        f"- Free {w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')}" for w in free
    ] or ["- No free windows in work hours."]
    task_lines = [f"- {t.get('title', 'untitled')}" for t in open_tasks[:20]] or ["- No open tasks."]

    age_note = ""
    if task_max_age_days > 0:
        age_note = (
            f"\nNote: only tasks with due/updated within the last {task_max_age_days} days "
            f"are listed ({skipped_old} older open tasks omitted).\n"
        )

    facts = (
        f"Date: {now.date().isoformat()} ({timezone_name})\n"
        f"Conflicts:\n" + "\n".join(conflict_lines) + "\n"
        f"Free windows:\n" + "\n".join(free_lines) + "\n"
        f"Open tasks (recent only):\n" + "\n".join(task_lines)
        + age_note
        + "\nUse ONLY the tasks listed above. Do not mention omitted/older tasks."
    )
    summary = await llm.complete(
        CompletionRequest(
            system=system_prompt
            or (
                "You are a personal schedule manager. Write a short daily briefing in Russian. "
                "Do not invent conflicts; use only the facts provided. Suggest which tasks fit free windows. "
                "Never mention tasks that are not in the Open tasks list."
            ),
            user=facts,
            temperature=0.3,
        )
    )
    footer = (
        f"— конфликтов: {len(conflicts)}, свободных окон: {len(free)}, "
        f"актуальных задач: {len(open_tasks)}"
    )
    if skipped_old:
        footer += f" (скрыто старых: {skipped_old}, порог {task_max_age_days}д)"
    return DailyBriefResult(
        conflicts=conflicts,
        free_windows=free,
        summary_text=f"{summary.text.strip()}\n\n{footer}",
        open_tasks=open_tasks,
        skipped_old_tasks=skipped_old,
    )
