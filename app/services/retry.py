from __future__ import annotations

import uuid

from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Note
from app.domain.enums import NoteStatus


async def retry_failed_note(
    session: AsyncSession,
    redis: ArqRedis,
    *,
    note_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Note:
    note = await session.get(Note, note_id)
    if note is None or note.user_id != user_id:
        raise RuntimeError("Note not found")
    if note.status != NoteStatus.FAILED.value:
        raise RuntimeError(f"Note is not failed (status={note.status})")

    # Resume from the furthest successful durable checkpoint
    if note.dropbox_path:
        note.status = NoteStatus.UPLOADED.value
        note.error_message = None
        job_type = "postprocess_note"
        db_job_type = "postprocess"
    else:
        note.status = NoteStatus.RECEIVED.value
        note.error_message = None
        job_type = "transcribe_note"
        db_job_type = "transcribe"

    session.add(
        Job(
            user_id=user_id,
            note_id=note.id,
            job_type=db_job_type,
            status="queued",
            payload={"note_id": str(note.id), "retry": True},
        )
    )
    await session.commit()
    await session.refresh(note)
    await redis.enqueue_job(job_type, str(note.id))
    return note
