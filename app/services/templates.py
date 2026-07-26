from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Template

PromptKind = Literal["notes", "brief", "classify"]

PROMPT_KINDS: tuple[PromptKind, ...] = ("notes", "brief", "classify")

DEFAULT_PROMPTS: dict[PromptKind, str] = {
    "notes": (
        "Ты редактор личных заметок. Исправь речь в текст: пунктуация, абзацы, "
        "убери слова-паразиты. Сохрани смысл. Ответ — только готовый markdown-текст заметки."
    ),
    "brief": (
        "Ты персональный менеджер расписания. Напиши короткий ежедневный брифинг на русском. "
        "Не выдумывай конфликты — опирайся только на факты. "
        "Подскажи, какие открытые задачи лучше вписать в свободные окна. "
        "Упоминай только задачи из списка Open tasks — старые уже отфильтрованы системой."
    ),
    "classify": (
        "You classify personal notes. Decide if the note is an actionable task or calendar event. "
        "Resolve relative dates (сегодня/завтра) using the current datetime provided in the user message. "
        "Always emit full 4-digit ISO years matching that current year unless the note explicitly names another year. "
        "If unsure, is_task=false."
    ),
}

# Legacy name from early scaffold
_NOTES_ALIASES = frozenset({"notes", "default"})


async def get_prompt_template(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: PromptKind,
) -> Template | None:
    if kind == "notes":
        result = await session.execute(
            select(Template)
            .where(
                Template.user_id == user_id,
                Template.name.in_(tuple(_NOTES_ALIASES)),
            )
            .order_by(Template.is_default.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    result = await session.execute(
        select(Template).where(Template.user_id == user_id, Template.name == kind).limit(1)
    )
    return result.scalar_one_or_none()


async def get_system_prompt(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: PromptKind,
) -> str:
    template = await get_prompt_template(session, user_id, kind)
    if template and template.system_prompt.strip():
        return template.system_prompt
    return DEFAULT_PROMPTS[kind]


async def ensure_prompt_templates(session: AsyncSession, user_id: uuid.UUID) -> dict[PromptKind, Template]:
    """Create missing prompt templates for the user. Notes template is marked default."""
    out: dict[PromptKind, Template] = {}
    for kind in PROMPT_KINDS:
        existing = await get_prompt_template(session, user_id, kind)
        if existing:
            # Normalize legacy "default" → keep as notes default
            if kind == "notes" and existing.name == "default":
                existing.name = "notes"
                existing.is_default = True
                await session.commit()
                await session.refresh(existing)
            out[kind] = existing
            continue
        template = Template(
            user_id=user_id,
            name=kind,
            system_prompt=DEFAULT_PROMPTS[kind],
            user_prompt="{{body}}" if kind == "notes" else "{{facts}}",
            output_format="markdown" if kind != "classify" else "json",
            is_default=(kind == "notes"),
        )
        session.add(template)
        await session.flush()
        out[kind] = template
    await session.commit()
    for kind, template in out.items():
        await session.refresh(template)
    return out


async def ensure_default_template(session: AsyncSession, user_id: uuid.UUID) -> Template:
    """Back-compat: ensure all prompts, return notes template."""
    templates = await ensure_prompt_templates(session, user_id)
    return templates["notes"]


async def set_system_prompt(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: PromptKind,
    system_prompt: str,
) -> Template:
    text = system_prompt.strip()
    if not text:
        raise ValueError("Промпт не может быть пустым")
    if len(text) > 8000:
        raise ValueError("Промпт слишком длинный (макс. 8000 символов)")

    await ensure_prompt_templates(session, user_id)
    template = await get_prompt_template(session, user_id, kind)
    if template is None:
        raise RuntimeError(f"Template {kind} missing after ensure")
    template.system_prompt = text
    if kind == "notes":
        template.is_default = True
        template.name = "notes"
    await session.commit()
    await session.refresh(template)
    return template


async def reset_system_prompt(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: PromptKind,
) -> Template:
    return await set_system_prompt(session, user_id, kind, DEFAULT_PROMPTS[kind])


def parse_prompt_kind(raw: str | None) -> PromptKind | None:
    if not raw:
        return None
    value = raw.strip().lower()
    if value in {"note", "notes", "default", "postprocess"}:
        return "notes"
    if value in {"brief", "briefing", "daily"}:
        return "brief"
    if value in {"classify", "classification", "task"}:
        return "classify"
    return None


def preview_prompt(text: str, limit: int = 400) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
