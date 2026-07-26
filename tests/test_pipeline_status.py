import unittest
import uuid

from app.db.models import Note
from app.domain.enums import NoteStatus
from app.pipelines.status import transition_note


class PipelineStatusTests(unittest.TestCase):
    def test_happy_path_with_confirmation(self) -> None:
        note = Note(id=uuid.uuid4(), user_id=uuid.uuid4(), status=NoteStatus.RECEIVED.value)
        transition_note(note, NoteStatus.TRANSCRIBING)
        transition_note(note, NoteStatus.CACHED)
        transition_note(note, NoteStatus.UPLOADED)
        transition_note(note, NoteStatus.POSTPROCESSING)
        transition_note(note, NoteStatus.CLASSIFIED)
        transition_note(note, NoteStatus.AWAITING_CONFIRMATION)
        transition_note(note, NoteStatus.DONE)
        self.assertEqual(note.status, NoteStatus.DONE.value)

    def test_classified_to_done_without_confirm(self) -> None:
        note = Note(id=uuid.uuid4(), user_id=uuid.uuid4(), status=NoteStatus.CLASSIFIED.value)
        transition_note(note, NoteStatus.DONE)
        self.assertEqual(note.status, NoteStatus.DONE.value)

    def test_invalid_transition(self) -> None:
        note = Note(id=uuid.uuid4(), user_id=uuid.uuid4(), status=NoteStatus.RECEIVED.value)
        with self.assertRaises(ValueError):
            transition_note(note, NoteStatus.DONE)


if __name__ == "__main__":
    unittest.main()
