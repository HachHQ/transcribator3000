from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Note, Template
from app.domain.enums import NoteStatus
from app.domain.models import CompletionRequest
from app.integrations.llm.base import LLMProvider
from app.integrations.storage.dropbox import DropboxVault
from app.integrations.storage.note_cache import NoteCache
from app.pipelines.status import transition_note
from app.services.templates import get_prompt_template


async def get_default_template(session: AsyncSession, user_id: uuid.UUID) -> Template | None:
    template = await get_prompt_template(session, user_id, "notes")
    if template:
        return template
    result = await session.execute(select(Template).where(Template.user_id == user_id).limit(1))
    return result.scalar_one_or_none()


async def postprocess_note(
    session: AsyncSession,
    cache: NoteCache,
    vault: DropboxVault,
    llm: LLMProvider,
    note_id: uuid.UUID,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    note = await session.get(Note, note_id)
    if note is None:
        raise RuntimeError(f"Note {note_id} not found")

    transition_note(note, NoteStatus.POSTPROCESSING)
    await session.commit()

    body = await cache.get_body(note_id)
    if body is None and note.dropbox_path:
        body = vault.download_text(note.dropbox_path)
        # strip heading + optional note_id footer for LLM input
        lines = body.splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[2:] if len(lines) > 2 else []
        # drop trailing --- / note_id footer
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines and lines[-1].startswith("note_id:"):
            lines.pop()
            while lines and lines[-1].strip() == "":
                lines.pop()
            if lines and lines[-1].strip() == "---":
                lines.pop()
        body = "\n".join(lines).strip()

    if not body:
        raise RuntimeError("Note body unavailable in cache and Dropbox")

    template: Template | None = None
    if note.template_id:
        template = await session.get(Template, note.template_id)
    if template is None:
        template = await get_default_template(session, note.user_id)

    if template is None:
        # No template — skip LLM edit
        transition_note(note, NoteStatus.CLASSIFIED)
        await session.commit()
        return body

    user_prompt = template.user_prompt.replace("{{body}}", body)
    result = await llm.complete(
        CompletionRequest(
            system=template.system_prompt or "Edit the note according to the instructions.",
            user=user_prompt,
        )
    )
    edited = result.text.strip()
    await cache.set_body(note_id, edited, ttl=settings.note_body_ttl_seconds)

    if note.dropbox_path:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        heading = datetime.now(ZoneInfo(settings.timezone)).strftime("%H:%M:%S")
        content = DropboxVault.format_note_markdown(
            heading=heading, body=edited, note_id=note.id
        )
        vault.upload_markdown(note.dropbox_path, content, overwrite=True)

    note.content_checksum = hashlib.sha256(edited.encode("utf-8")).hexdigest()
    transition_note(note, NoteStatus.CLASSIFIED)
    await session.commit()
    return edited
