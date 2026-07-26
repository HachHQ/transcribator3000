from enum import StrEnum


class NoteStatus(StrEnum):
    RECEIVED = "received"
    TRANSCRIBING = "transcribing"
    CACHED = "cached"
    UPLOADED = "uploaded"
    POSTPROCESSING = "postprocessing"
    CLASSIFIED = "classified"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DONE = "done"
    FAILED = "failed"


class IdentityProvider(StrEnum):
    TELEGRAM = "telegram"
    GOOGLE = "google"


class OAuthProvider(StrEnum):
    GOOGLE = "google"
    DROPBOX = "dropbox"


class TaskLinkKind(StrEnum):
    GOOGLE_TASK = "google_task"
    GOOGLE_EVENT = "google_event"
