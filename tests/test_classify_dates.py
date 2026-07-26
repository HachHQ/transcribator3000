import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.models import ClassificationResult
from app.services.classify import normalize_classification_datetimes


class ClassifyDateNormalizeTests(unittest.TestCase):
    def test_rebases_wrong_year(self) -> None:
        now = datetime(2026, 7, 26, 15, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
        result = ClassificationResult(
            is_task=True,
            title="Созвон",
            due=datetime(2023, 7, 26, 15, 0, tzinfo=ZoneInfo("Asia/Bangkok")),
        )
        fixed = normalize_classification_datetimes(result, now)
        assert fixed.due is not None
        self.assertEqual(fixed.due.year, 2026)
        self.assertEqual(fixed.due.month, 7)
        self.assertEqual(fixed.due.day, 26)

    def test_keeps_same_year(self) -> None:
        now = datetime(2026, 7, 26, 15, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
        due = datetime(2026, 8, 1, 10, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
        result = ClassificationResult(is_task=True, title="x", due=due)
        fixed = normalize_classification_datetimes(result, now)
        self.assertEqual(fixed.due, due)


if __name__ == "__main__":
    unittest.main()
