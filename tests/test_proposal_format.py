import unittest
import uuid
from datetime import datetime, timezone

from app.domain.models import ClassificationResult
from app.services.classify import format_proposal_text, is_actionable


class ProposalFormatTests(unittest.TestCase):
    def test_actionable_task(self) -> None:
        result = ClassificationResult(is_task=True, title="Купить молоко")
        self.assertTrue(is_actionable(result))
        text = format_proposal_text(uuid.uuid4(), result)
        self.assertIn("Задача: Купить молоко", text)
        self.assertIn("Подтвердить", text)

    def test_not_actionable(self) -> None:
        result = ClassificationResult(is_task=False, create_calendar_event=False)
        self.assertFalse(is_actionable(result))
        text = format_proposal_text(uuid.uuid4(), result)
        self.assertIn("Не похоже на задачу", text)

    def test_event_with_times(self) -> None:
        start = datetime(2026, 7, 26, 15, 0, tzinfo=timezone.utc)
        result = ClassificationResult(
            create_calendar_event=True,
            title="Созвон",
            start=start,
            duration_minutes=30,
        )
        self.assertTrue(is_actionable(result))
        text = format_proposal_text(uuid.uuid4(), result)
        self.assertIn("Событие: Созвон", text)
        self.assertIn("начало:", text)


if __name__ == "__main__":
    unittest.main()
