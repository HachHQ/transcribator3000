from __future__ import annotations

from app.db.models import Note
from app.domain.enums import NoteStatus

ALLOWED: dict[NoteStatus, set[NoteStatus]] = {
    NoteStatus.RECEIVED: {NoteStatus.TRANSCRIBING, NoteStatus.FAILED},
    NoteStatus.TRANSCRIBING: {NoteStatus.CACHED, NoteStatus.FAILED},
    NoteStatus.CACHED: {NoteStatus.UPLOADED, NoteStatus.FAILED},
    NoteStatus.UPLOADED: {
        NoteStatus.POSTPROCESSING,
        NoteStatus.CLASSIFIED,
        NoteStatus.DONE,
        NoteStatus.FAILED,
    },
    NoteStatus.POSTPROCESSING: {NoteStatus.CLASSIFIED, NoteStatus.DONE, NoteStatus.FAILED},
    NoteStatus.CLASSIFIED: {
        NoteStatus.AWAITING_CONFIRMATION,
        NoteStatus.DONE,
        NoteStatus.FAILED,
    },
    NoteStatus.AWAITING_CONFIRMATION: {NoteStatus.DONE, NoteStatus.FAILED},
    NoteStatus.DONE: set(),
    NoteStatus.FAILED: {
        NoteStatus.TRANSCRIBING,
        NoteStatus.POSTPROCESSING,
        NoteStatus.CLASSIFIED,
        NoteStatus.AWAITING_CONFIRMATION,
    },
}


def transition_note(note: Note, new_status: NoteStatus, *, error: str | None = None) -> None:
    current = NoteStatus(note.status)
    if new_status not in ALLOWED.get(current, set()) and new_status != current:
        raise ValueError(f"Invalid note transition {current} -> {new_status}")
    note.status = new_status.value
    if error is not None:
        note.error_message = error
    elif new_status != NoteStatus.FAILED:
        note.error_message = None
