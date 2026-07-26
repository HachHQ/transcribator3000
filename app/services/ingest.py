from __future__ import annotations

import uuid

from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Job, Note
from app.domain.enums import NoteStatus
from app.integrations.storage.note_cache import NoteCache


async def create_note_ingest(
    session: AsyncSession,
    cache: NoteCache,
    redis: ArqRedis,
    *,
    user_id: uuid.UUID,
    audio_bytes: bytes,
    audio_suffix: str = ".ogg",
    template_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> Note:
    settings = settings or get_settings()
    note = Note(
        user_id=user_id,
        status=NoteStatus.RECEIVED.value,
        template_id=template_id,
        meta={"audio_suffix": audio_suffix},
    )
    session.add(note)
    await session.flush()

    await cache.set_audio(note.id, audio_bytes, ttl=settings.audio_cache_ttl_seconds)

    job = Job(
        user_id=user_id,
        note_id=note.id,
        job_type="transcribe",
        status="queued",
        payload={"note_id": str(note.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(note)

    await redis.enqueue_job("transcribe_note", str(note.id))
    return note
